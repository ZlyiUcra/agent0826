"""
КОНТЕКСТ · прибирання сліду бесіди. $0.

Кожна розмова лишає по собі слід, і з кожною наступною його більшає: на диску —
запис прогону з повною історією і журнал, у базі — факти про читача. Технічне
знання при цьому лишається: обговорені розділи в пам'яті, що переживає розмову,
не прибираються ніколи — саме їх наступні розмови беруть за схожістю до
питання. Прибирається лише те, що росте без користі.

ЩО ВВАЖАЄТЬСЯ СЛІДОМ БЕСІДИ

    на диску   practice/out/dialog-*.json — запис прогону з усією історією;
               practice/out/*-run-*.log і series-*.json — журнали й зведення серій
    у базі     записи kind=reader у колекції memory-e5 (або у файлі memory.json),
               позначені ідентифікатором цієї бесіди

Не слід бесіди, і тому не чіпається: колекції специфікації, правила курсу,
обговорені теми (kind=topic), записи першої картки в practice/out/, кеші
векторів у practice/index/.

КОЛИ ПРИБИРАЄТЬСЯ

Наприкінці розмови в терміналі dialog питає: «Бесіду закрито? [y/N]». Так —
слід цієї бесіди прибирається одразу, і кожна прибрана річ друкується. Ні або
без відповіді — запис лишається, і бесіда вважається незакритою.

При наступному вході dialog чи series перелічує незакриті бесіди — скільки їх
на диску і скільки фактів про читача в базі — і питає, чи прибрати. Без
термінала (прогін із скрипта, без stdin) питати нема в кого: тоді прибирається
без питання, з тим самим друком кожної прибраної речі. Так домовлено з
власником проєкту: слід бесіди — не дані, які треба берегти, а те, що займає
місце, чим далі, тим більше.

    python -m practice.context.cleanup --status   # що зараз незакрите, нічого не чіпає
    python -m practice.context.cleanup --sweep    # прибрати слід усіх незакритих бесід
"""

import json
import pathlib
import sys

from practice.context import memory

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"


def records() -> list[tuple[pathlib.Path, dict]]:
    """Записи прогонів на диску: кожен — незакрита бесіда."""
    out = []
    for path in sorted(OUT.glob("dialog-*.json")):
        try:
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def transient() -> list[pathlib.Path]:
    """Журнали й зведення серій — файли без власника серед бесід. Символьне
    посилання dialog-run-latest.log підпадає під той самий шаблон, що й журнали."""
    return sorted(set(OUT.glob("*-run-*.log")) | set(OUT.glob("series-*.json")))


def interactive() -> bool:
    return sys.stdin.isatty()


def ask(question: str) -> bool | None:
    """Так, ні — або None, коли спитати нема в кого."""
    if not interactive():
        return None
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "т", "так")
    except EOFError:
        return None


def close(path: pathlib.Path, record: dict, store) -> list[str]:
    """Прибирає слід однієї бесіди. Повертає перелік прибраного для друку."""
    removed = []
    conversation = record.get("conversation")
    if conversation and store is not None:
        n = store.forget_reader(conversation)
        if n:
            removed.append(f"факти про читача з бесіди {conversation}: {n}")
    path.unlink()
    removed.append(f"запис {path.name}")
    return removed


def sweep(store=None) -> list[str]:
    """Прибирає слід усіх незакритих бесід разом із журналами."""
    if store is None:
        store, _ = memory.open_store()
    removed = []
    for path, record in records():
        removed += close(path, record, store)
    for path in transient():
        path.unlink()
        removed.append(f"файл {path.name}")
    return removed


def status() -> dict:
    recs = records()
    store, where = memory.open_store()
    ids = {r.get("conversation") for _, r in recs}
    facts = store.reader_facts(ids) if ids else []
    return {"records": [p.name for p, _ in recs], "transient": [p.name for p in transient()],
            "reader_facts": facts, "store": store, "where": where}


def print_removed(removed: list[str]) -> None:
    if not removed:
        print("  прибирати нічого")
        return
    for line in removed:
        print(f"  прибрано: {line}")


def warn_and_sweep() -> None:
    """Точка входу для dialog і series: попередити про незакриті бесіди і, за
    згодою або без можливості її спитати, прибрати їхній слід."""
    st = status()
    if not st["records"] and not st["transient"]:
        return
    print("── Незакриті бесіди ──")
    print(f"  записів на диску: {len(st['records'])}, журналів і зведень: {len(st['transient'])}, "
          f"фактів про читача в пам'яті ({st['where'].split(' — ')[0]}): {len(st['reader_facts'])}")
    answer = ask("  Прибрати їхній слід?")
    if answer is None:
        print("  термінала немає — прибираю без питання:")
        print_removed(sweep(st["store"]))
    elif answer:
        print_removed(sweep(st["store"]))
    else:
        print("  лишаю як є; прибрати пізніше: python -m practice.context.cleanup --sweep")
    print()


def ask_close(path: pathlib.Path, record: dict) -> None:
    """Наприкінці розмови: чи закрито бесіду. Без термінала не питає і не чіпає."""
    answer = ask("Бесіду закрито?")
    if answer:
        store, _ = memory.open_store()
        print_removed(close(path, record, store))
    elif answer is False:
        print("  бесіда лишається незакритою; її слід прибереться при наступному вході.")


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv or not argv:
        print(__doc__)
        return 0
    if "--status" in argv:
        st = status()
        print(f"── Незакриті бесіди · пам'ять: {st['where']} ──")
        for name in st["records"]:
            print(f"  запис:   {name}")
        for name in st["transient"]:
            print(f"  файл:    {name}")
        for fact in st["reader_facts"]:
            print(f"  читач:   {fact}")
        if not st["records"] and not st["transient"] and not st["reader_facts"]:
            print("  нічого")
        return 0
    if "--sweep" in argv:
        print("── Прибирання сліду незакритих бесід ──")
        print_removed(sweep())
        return 0
    print(f"Невідомий аргумент. Є --status і --sweep.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
