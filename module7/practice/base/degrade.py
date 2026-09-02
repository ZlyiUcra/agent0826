"""
ТОЧКА ВХОДУ · зібрати деградовану копію корпусу. БЕЗКОШТОВНО.

Погіршувати агента можна трьома способами: зіпсувати промпт, звузити його права
або підмінити те, що він читає. Перші два видно одразу — промпт лежить у
репозиторії, права перевіряють тести. Тут узято третій, і саме тому, що його не
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

Копія лягає в practice/docs-degraded/, і читає її прогін із прапорцем
--degraded. Назва набору документів при цьому не змінюється, тому ім'я колекції
векторів лишається тим самим — у цьому вся суть досліду. Якщо тека вже є, скрипт
зупиняється і нічого не чіпає: прибирати її — справа людини.
"""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

_PRACTICE = pathlib.Path(__file__).resolve().parents[1]
_MODULE = _PRACTICE.parent

#: Здорові теки набору suite і тека копії. Копія пласка: порядок імен файлів у
#: ній збігається з порядком «docs-full, потім docs-suite», а від порядку
#: залежить, який із двох однакових текстів лишиться після злиття дублів.
SOURCE_DIRS = [_PRACTICE / "docs-full", _PRACTICE / "docs-suite"]
TARGET_DIR = _PRACTICE / "docs-degraded"

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

#: Програма для дочірнього процесу: підсумок про набір, який вибрало оточення.
#: Двома процесами, а не одним, бо practice.common.corpus обирає теки на імпорті
#: модуля, і в одному процесі другий набір уже не підставити.
_SUMMARY = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from practice.common.corpus import DOC_SET, load_passages
from practice.common.idmap import assign_ids
passages = load_passages()
by_id, _ = assign_ids(passages)
ids = "\\n".join(sorted(by_id))
print(json.dumps({"set": DOC_SET,
                  "count": len(passages),
                  "ids": hashlib.sha256(ids.encode()).hexdigest()[:16],
                  "chars": sum(len(p.text) for p in passages)}))
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="деградована копія корпусу")
    ap.add_argument("--check", action="store_true",
                    help="нічого не будувати: звірити вже наявну копію")
    args = ap.parse_args(argv)

    if not args.check:
        if TARGET_DIR.exists():
            raise SystemExit(
                f"Копія вже є: {TARGET_DIR}\n"
                f"  Нічого не змінюю. Щоб зібрати заново, приберіть теку самі:\n"
                f"    rm -rf {TARGET_DIR}")
        _build()

    if not TARGET_DIR.is_dir():
        raise SystemExit(f"Копії немає: {TARGET_DIR}\n"
                         f"  Зберіть її: python -m practice.base.degrade")
    return _check()


def _build() -> None:
    """Копія корпусу з переписаними реченнями. Здорові теки не чіпаються."""
    TARGET_DIR.mkdir(parents=True)

    for folder in SOURCE_DIRS:
        for path in sorted(folder.glob("*.txt")):
            shutil.copy2(path, TARGET_DIR / path.name)

    for i, edit in enumerate(EDITS, 1):
        path = TARGET_DIR / edit["file"]
        text = path.read_text(encoding="utf-8")
        found = text.count(edit["old"])
        if found != 1:
            raise SystemExit(
                f"Правка {i} ({edit['file']}): шуканий текст трапляється {found} раз(ів), "
                f"а має рівно один. Копія лишилася недобудованою: {TARGET_DIR}")
        path.write_text(text.replace(edit["old"], edit["new"]), encoding="utf-8")
        print(f"  {i}. {edit['file']}: {edit['why']}")

    (TARGET_DIR / "README.md").write_text(_readme(), encoding="utf-8")
    print(f"\nКопія: {TARGET_DIR}")


def _check() -> int:
    """Безкоштовна звірка: що копія відрізняється текстом і нічим більше."""
    ok = True

    names_src = sorted(p.name for f in SOURCE_DIRS for p in f.glob("*.txt"))
    names_dst = sorted(p.name for p in TARGET_DIR.glob("*.txt"))
    ok &= _say("імена файлів корпусу збігаються", names_src == names_dst,
               f"{len(names_src)} проти {len(names_dst)}")

    def _source(name):
        for folder in SOURCE_DIRS:
            if (folder / name).exists():
                return folder / name
        return None

    changed = [n for n in names_dst
               if _source(n) and _source(n).read_bytes() != (TARGET_DIR / n).read_bytes()]
    want = sorted({e["file"] for e in EDITS})
    ok &= _say(f"текст змінено рівно у {len(want)} файлах", sorted(changed) == want,
               ", ".join(changed) or "у жодному")

    for i, edit in enumerate(EDITS, 1):
        text = (TARGET_DIR / edit["file"]).read_text(encoding="utf-8")
        ok &= _say(f"правка {i} на місці ({', '.join(edit['cases'])})",
                   edit["new"] in text and edit["old"] not in text, edit["file"])

    src_sum, dst_sum = _summary(degraded=False), _summary(degraded=True)
    ok &= _say("кількість фрагментів не змінилася",
               src_sum["count"] == dst_sum["count"],
               f"{src_sum['count']} проти {dst_sum['count']}")
    ok &= _say("ідентифікатори фрагментів ті самі",
               src_sum["ids"] == dst_sum["ids"],
               f"{src_sum['ids']} проти {dst_sum['ids']}")
    # Останнє — не причіпка: ідентифікатор точки в Qdrant будується з pid, тож
    # збіг ідентифікаторів означає, що стара колекція далі віддає ці фрагменти.
    # Розійдись вони — пошук за змістом просто перестав би щось знаходити, і
    # прогін показав би падіння з іншої причини, ніж переписаний текст.

    # Ім'я колекції векторів рахується з назви набору. Назва мусить бути та сама,
    # інакше деградований прогін пішов би в іншу колекцію, і числа в ній були б
    # від того самого тексту, який агент читає, — тобто досліду не вийшло б.
    ok &= _say("назва набору документів та сама", src_sum["set"] == dst_sum["set"],
               f"{src_sum['set']} проти {dst_sum['set']}")

    delta = dst_sum["chars"] - src_sum["chars"]
    print(f"\nСимволів у корпусі: {dst_sum['chars']} ({delta:+d} до здорового)")
    print(f"Кейсів має впасти: {len(sorted({c for e in EDITS for c in e['cases']}))} — "
          f"{', '.join(sorted({c for e in EDITS for c in e['cases']}))}")
    print("Копія відрізняється від здорової тільки текстом." if ok
          else "Звірка не пройшла — прогін на цій копії нічого не доведе.")
    return 0 if ok else 1


def _summary(degraded: bool) -> dict:
    env = {**os.environ}
    env.pop("PRACTICE_DEGRADED", None)
    if degraded:
        env["PRACTICE_DEGRADED"] = "1"
    out = subprocess.run([sys.executable, "-c", _SUMMARY, str(_MODULE)],
                         capture_output=True, text=True, env=env)
    if out.returncode != 0:
        which = "деградованого" if degraded else "здорового"
        raise SystemExit(f"Не вдалося прочитати {which} корпусу:\n{out.stderr}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _say(what: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}" + (f" — {detail}" if detail else ""))
    return ok


def _readme() -> str:
    lines = [
        "# docs-degraded — навмисно зіпсована копія корпусу\n",
        "Тека зібрана скриптом `practice/base/degrade.py` і потрібна рівно для одного: показати, що",
        "гейт зупиняє реліз тоді, коли з агентом усе гаразд, а зіпсовані дані, які він читає. Руками",
        "її не правлять — правлять таблицю `EDITS` у скрипті й збирають заново.\n",
        "Від здорового набору копія відрізняється тільки текстом кількох речень. Імена файлів,",
        "кількість фрагментів, їхні ідентифікатори, назва набору (а отже й колекція Qdrant) і режим",
        "пошуку — ті самі, тож ані тести, ані санітар видачі, ані журнал `out/calls.log` цієї підміни",
        "не показують.\n",
        "Читає її прогін із прапорцем `--degraded`.\n",
        "## Що переписано\n",
    ]
    for i, edit in enumerate(EDITS, 1):
        lines.append(f"{i}. `{edit['file']}` — {edit['why']} (кейси: "
                     f"{', '.join(edit['cases'])}).")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
