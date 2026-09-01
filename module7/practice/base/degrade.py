"""
ТОЧКА ВХОДУ · зібрати деградовану копію примірника. БЕЗКОШТОВНО.

Погіршувати агента можна трьома способами: зіпсувати промпт, звузити його права
або підмінити те, що він читає. Перші два видно одразу — промпт лежить у
репозиторії, права перевіряє smoke. Тут узято третій, і саме тому, що його не
видно: у копії корпусу переписано дев'ять речень у п'яти розділах, а все інше
лишилося тим самим. Імена файлів ті самі, кількість фрагментів та сама,
ідентифікатори фрагментів ті самі, колекція Qdrant та сама, санітар мовчить, у
журналі немає ані помилки, ані попередження. Жодна перевірка, крім набору
кейсів, цієї підміни не бачить.

Це не вигаданий сценарій, а звичайне життя бази знань: документ нагорі
переписали, копію оновили, а вектори не перерахували — і агент відповідає за
новим текстом, тоді як пошук веде його старими числами.

    python -m practice.base.degrade                 # зібрати копію
    python -m practice.base.degrade --check         # лише звірити наявну копію

Копія лягає в docfactory/instances/ecmascript-degraded/. Якщо тека вже є, скрипт
зупиняється і нічого не чіпає: прибирати її — справа людини.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from practice import bootstrap

SOURCE = "ecmascript"
TARGET = "ecmascript-degraded"

#: Що саме переписано. Кожен запис називає кейси, які мають через нього впасти, —
#: інакше після прогону не відрізнити навмисне псування від випадкового.
#: `old` мусить траплятися у файлі рівно один раз, і це перевіряється.
EDITS = [
    {
        "file": "20-fundamental-objects.txt",
        "why": "абстрактну операцію перейменовано, рівень цілісності названо інакше",
        "cases": ["object-freeze-en", "object-freeze-uk"],
        "old": "- Let status be ? SetIntegrityLevel ( obj , frozen ).",
        "new": "- Let status be ? SetPropertyLockLevel ( obj , locked ).",
    },
    {
        "file": "20-fundamental-objects.txt",
        "why": "теги для undefined і null помінялися місцями",
        "cases": ["tostring-tag"],
        "old": '- If the this value is undefined , return "[object Undefined]" .\n'
               '\n'
               '- If the this value is null , return "[object Null]" .',
        "new": '- If the this value is undefined , return "[object Null]" .\n'
               '\n'
               '- If the this value is null , return "[object Undefined]" .',
    },
    {
        "file": "21-numbers-and-dates.txt",
        "why": "рівновіддалене число округлюється в бік мінус нескінченності",
        "cases": ["math-round"],
        "old": "This function returns the Number value that is closest to x and is "
               "integral. If two integral Numbers are equally close to x , then the "
               "result is the Number value that is closer to +∞. If x is already "
               "integral, the result is x .",
        "new": "This function returns the Number value that is closest to x and is "
               "integral. If two integral Numbers are equally close to x , then the "
               "result is the Number value that is closer to -∞. If x is already "
               "integral, the result is x .",
    },
    {
        "file": "21-numbers-and-dates.txt",
        "why": "крок алгоритму приведено у згоду з переписаним правилом",
        "cases": ["math-round"],
        "old": "- Return the integral Number closest to n , preferring the Number "
               "closer to +∞ in the case of a tie.",
        "new": "- Return the integral Number closest to n , preferring the Number "
               "closer to -∞ in the case of a tie.",
    },
    {
        "file": "21-numbers-and-dates.txt",
        "why": "приклад у примітці приведено у згоду з переписаним правилом: інакше "
               "текст суперечить сам собі й уважна модель це помічає",
        "cases": ["math-round"],
        "old": "Math.round(3.5) returns 4, but Math.round(-3.5) returns -3.",
        "new": "Math.round(3.5) returns 3, but Math.round(-3.5) returns -4.",
    },
    {
        "file": "12-ecmascript-language-lexical-grammar.txt",
        "why": "напрям сканування і правило найдовшого збігу перевернуто",
        "cases": ["lexical-scan"],
        "old": "The source text is scanned from left to right, repeatedly taking the "
               "longest possible sequence of code points as the next input element.",
        "new": "The source text is scanned from right to left, repeatedly taking the "
               "shortest possible sequence of code points as the next input element.",
    },
    {
        "file": "10-ordinary-and-exotic-objects-behaviours.txt",
        "why": "рядкові ключі поставлено перед індексами, а індекси — за спаданням",
        "cases": ["own-keys-order"],
        "old": "- For each own property key propertyKey of obj such that propertyKey is "
               "an array index , in ascending numeric index order, do\n"
               "- Append propertyKey to keys .\n"
               "\n"
               "- For each own property key propertyKey of obj such that propertyKey is "
               "a String and propertyKey is not an array index , in ascending "
               "chronological order of property creation, do\n"
               "- Append propertyKey to keys .",
        "new": "- For each own property key propertyKey of obj such that propertyKey is "
               "a String and propertyKey is not an array index , in ascending "
               "chronological order of property creation, do\n"
               "- Append propertyKey to keys .\n"
               "\n"
               "- For each own property key propertyKey of obj such that propertyKey is "
               "an array index , in descending numeric index order, do\n"
               "- Append propertyKey to keys .",
    },
]

#: Програма для дочірнього процесу: паспорт корпусу того примірника, на який
#: вказує DF_INSTANCE_DIR. Двома процесами, а не одним, бо common.corpus обирає
#: теку на імпорті модуля, і в одному процесі другий примірник уже не підставити.
_PASSPORT = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from common.corpus import load_passages
from common.idmap import assign_ids
passages = load_passages()
by_id, _ = assign_ids(passages)
ids = "\\n".join(sorted(by_id))
print(json.dumps({"count": len(passages),
                  "ids": hashlib.sha256(ids.encode()).hexdigest()[:16],
                  "chars": sum(len(p.text) for p in passages)}))
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="деградована копія примірника")
    ap.add_argument("--check", action="store_true",
                    help="нічого не будувати: звірити вже наявну копію")
    args = ap.parse_args(argv)

    src = bootstrap.INSTANCES / SOURCE
    dst = bootstrap.INSTANCES / TARGET

    if not args.check:
        if dst.exists():
            raise SystemExit(
                f"Копія вже є: {dst}\n"
                f"  Нічого не змінюю. Щоб зібрати заново, приберіть теку самі:\n"
                f"    rm -rf {dst}")
        _build(src, dst)

    if not dst.is_dir():
        raise SystemExit(f"Копії немає: {dst}\n  Зберіть її: python -m practice.base.degrade")
    return _check(src, dst)


def _build(src, dst) -> None:
    """Копія примірника з переписаними реченнями. Джерело не чіпається."""
    (dst / "corpus").mkdir(parents=True)
    (dst / "out").mkdir()

    for name in sorted(p.name for p in (src / "corpus").iterdir() if p.is_file()):
        shutil.copy2(src / "corpus" / name, dst / "corpus" / name)
    # config.json — байт у байт: та сама колекція Qdrant і та сама модель векторів.
    # Це і є суть підміни: числа в базі лишаються від здорового тексту.
    shutil.copy2(src / "config.json", dst / "config.json")
    # mode.json каже серверові, що пошук за змістом дозволений. Без нього копія
    # шукала б лише по словах, і прогін порівнювався б не з тим.
    shutil.copy2(src / "out" / "mode.json", dst / "out" / "mode.json")

    for i, edit in enumerate(EDITS, 1):
        path = dst / "corpus" / edit["file"]
        text = path.read_text(encoding="utf-8")
        found = text.count(edit["old"])
        if found != 1:
            raise SystemExit(
                f"Правка {i} ({edit['file']}): шуканий текст трапляється {found} раз(ів), "
                f"а має рівно один. Копія лишилася недобудованою: {dst}")
        path.write_text(text.replace(edit["old"], edit["new"]), encoding="utf-8")
        print(f"  {i}. {edit['file']}: {edit['why']}")

    (dst / "README.md").write_text(_readme(), encoding="utf-8")
    print(f"\nКопія: {dst}")


def _check(src, dst) -> int:
    """Безкоштовна звірка: що копія відрізняється текстом і нічим більше."""
    ok = True

    names_src = sorted(p.name for p in (src / "corpus").iterdir() if p.is_file())
    names_dst = sorted(p.name for p in (dst / "corpus").iterdir() if p.is_file())
    ok &= _say("імена файлів корпусу збігаються", names_src == names_dst,
               f"{len(names_src)} проти {len(names_dst)}")

    changed = [n for n in names_dst
               if (src / "corpus" / n).read_bytes() != (dst / "corpus" / n).read_bytes()]
    want = sorted({e["file"] for e in EDITS})
    ok &= _say(f"текст змінено рівно у {len(want)} файлах", sorted(changed) == want,
               ", ".join(changed) or "у жодному")

    for i, edit in enumerate(EDITS, 1):
        text = (dst / "corpus" / edit["file"]).read_text(encoding="utf-8")
        ok &= _say(f"правка {i} на місці ({', '.join(edit['cases'])})",
                   edit["new"] in text and edit["old"] not in text, edit["file"])

    src_pass, dst_pass = _passport(src), _passport(dst)
    ok &= _say("кількість фрагментів не змінилася",
               src_pass["count"] == dst_pass["count"],
               f"{src_pass['count']} проти {dst_pass['count']}")
    ok &= _say("ідентифікатори фрагментів ті самі",
               src_pass["ids"] == dst_pass["ids"],
               f"{src_pass['ids']} проти {dst_pass['ids']}")
    # Останнє — не причіпка: ідентифікатор точки в Qdrant будується з pid, тож
    # збіг ідентифікаторів означає, що стара колекція далі віддає ці фрагменти.
    # Розійдись вони — пошук за змістом просто перестав би щось знаходити, і
    # прогін показав би падіння з іншої причини, ніж переписаний текст.

    cfg_same = (src / "config.json").read_bytes() == (dst / "config.json").read_bytes()
    ok &= _say("колекція Qdrant і модель векторів ті самі", cfg_same, "config.json")

    delta = dst_pass["chars"] - src_pass["chars"]
    print(f"\nСимволів у корпусі: {dst_pass['chars']} ({delta:+d} до здорового)")
    print(f"Кейсів має впасти: {len(sorted({c for e in EDITS for c in e['cases']}))} — "
          f"{', '.join(sorted({c for e in EDITS for c in e['cases']}))}")
    print("Копія відрізняється від здорової тільки текстом." if ok
          else "Звірка не пройшла — прогін на цій копії нічого не доведе.")
    return 0 if ok else 1


def _passport(instance_dir) -> dict:
    out = subprocess.run([sys.executable, "-c", _PASSPORT, str(bootstrap.DOCFACTORY)],
                         capture_output=True, text=True,
                         env={**os.environ, "DF_INSTANCE_DIR": str(instance_dir)})
    if out.returncode != 0:
        raise SystemExit(f"Не вдалося прочитати корпус {instance_dir}:\n{out.stderr}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _say(what: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}" + (f" — {detail}" if detail else ""))
    return ok


def _readme() -> str:
    lines = [
        "# ecmascript-degraded — навмисно зіпсована копія\n",
        "Тека зібрана скриптом `module7/practice/base/degrade.py` і потрібна рівно для одного:",
        "показати, що гейт зупиняє реліз тоді, коли з агентом усе гаразд, а зіпсовані дані, які він",
        "читає. Руками її не правлять — правлять таблицю `EDITS` у скрипті й збирають заново.\n",
        "Від здорового примірника копія відрізняється тільки текстом кількох речень. Імена файлів,",
        "кількість фрагментів, їхні ідентифікатори, колекція Qdrant і режим пошуку — ті самі, тож",
        "ані `smoke.py`, ані санітар видачі, ані журнал `out/calls.log` цієї підміни не показують.\n",
        "Ключа тут немає навмисно: практика бере його з `.env` здорового примірника.\n",
        "## Що переписано\n",
    ]
    for i, edit in enumerate(EDITS, 1):
        lines.append(f"{i}. `{edit['file']}` — {edit['why']} (кейси: "
                     f"{', '.join(edit['cases'])}).")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
