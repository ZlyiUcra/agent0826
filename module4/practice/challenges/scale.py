"""
ЧЕЛЕНДЖ · обсяг даних: де система нарешті обганяє одного агента.

Необов'язковий пункт картки. Питання в ньому не «хто кращий» (це міряє
base/compare.py на повному наборі), а «як різниця залежить від ОБСЯГУ даних».

МЕХАНІЗМ, ЯКИЙ МАЄ ВИРІШУВАТИ

Єдина структурна перевага вузького спеціаліста — чистота видачі. У повному
індексі перші три фрагменти на однотемний запит можуть містити чужі родини:
у прогоні attrs один агент отримав у top-3 фрагменти Proxy і Object Objects,
а спеціаліст OBJECT — лише свої. Що більший корпус, то більше чужого змагається
за ті самі три місця. Плата ж системи за маршрутизатор стала і мала. Отже, якщо
точка, де система обганяє, існує, вона має з'являтися зі зростанням корпусу —
це і перевіряємо.

ЯК ПОБУДОВАНО ВИМІР

Вісь обсягу — кількість документів у корпусі: 6, 12 і 18 (документи беруться
за порядком імен, тож родина OBJECT, 01–05, присутня в кожному розмірі).
Запити — три однотемні OBJECT-запити, зафіксовані нижче до прогонів: на них
відповідь є при будь-якому розмірі корпусу, тобто міряється саме шум, а не
покриття. Кожен запит іде через одного агента і через систему при кожному
розмірі: 3 запити x 2 сторони x 3 розміри = 18 прогонів.

Метрики на прогін: час, вартість, кількість пошуків і чистота видачі — частка
фрагментів НЕ з родини OBJECT серед усіх повернутих пошуками. Відповіді
зберігаються у файл поруч із числами, щоб їх можна було перечитати.

ЧОМУ ДЕШЕВА МОДЕЛЬ

Серія з вісімнадцяти прогонів на дорогій моделі коштувала б порядку кількох
доларів і міряла б те саме. Тому обидві сторони тут ганяються на дешевій моделі
(ANTHROPIC_MODEL перекривається до Haiku ще до імпорту config). Наслідок, про
який треба сказати прямо: числа цієї серії НЕ порівнюються з числами
base/compare.py — там цикл агента крутить Sonnet. Ця серія міряє тренд
різниці між сторонами, а не абсолютні вартості.

ЯК СКРИПТ ЗВУЖУЄ КОРПУС

Шар пошуку практики завжди читає всі вісімнадцять документів. Скрипт підміняє
кеш фрагментів у base/team (team._passages) відфільтрованим списком і скидає
кеш індексів — це втручання у внутрішнє поле, і воно свідомо живе тільки тут,
у челенджі: міняти common/ чи base/ заради досліду було б ширшим правом, ніж
дослід вартий. Векторні кеші підмножин рахуються і лягають у practice/index/
за своїми відбитками, як звичайні.

    python -m practice.challenges.scale          # 18 прогонів на Haiku
"""

import os

# До імпорту config: уся серія іде на дешевій моделі. setdefault — щоб явно
# задане оточення було сильнішим за скрипт.
os.environ.setdefault("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

import json
import pathlib
import sys
import time

from config import MODEL, MODEL_FAST
from core import cost
from core.agent import USAGE, reset_usage

from practice.base import single, system, team
from practice.common.corpus import load_passages

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"

SIZES = [6, 12, 18]

# Три однотемні OBJECT-запити. Зафіксовані до прогонів; відповіді на них лежать
# у документах 01–05, присутніх при кожному розмірі корпусу.
SCALE_QUERIES = {
    "attrs": "What are the attributes of a data property, and what default "
             "values do they get when a property is created?",
    "kinds": "What is the difference between a data property and an accessor "
             "property?",
    "essential": "Which internal methods are essential for every object, and "
                 "what does [[GetOwnProperty]] return?",
}

_ALL = load_passages()


def set_corpus(n_docs: int) -> int:
    """Звужує корпус практики до перших n_docs документів. Повертає розмір."""
    team._passages = [p for p in _ALL if team.doc_number(p.doc_id) <= n_docs]
    team._indexes.clear()
    return len(team._passages)


def _searches(trace: list) -> list:
    return [s for s in trace if s.get("tool", "").startswith("search_")]


def noise_share(trace: list) -> float:
    """Частка фрагментів поза родиною OBJECT серед усіх повернутих пошуками."""
    returned = [p["id"] for s in _searches(trace)
                for p in s.get("output", {}).get("passages", [])]
    if not returned:
        return 0.0
    foreign = [pid for pid in returned if team.doc_number(pid) > 5]
    return round(len(foreign) / len(returned), 3)


def _measure(side: str, fn, query: str) -> dict:
    started = time.time()
    reset_usage()
    result = fn(query)
    return {"side": side,
            "pipeline_sec": round(time.time() - started, 2),
            "cost_usd": cost.usd(USAGE["by_model"]),
            "searches": len(_searches(result.get("trace", []))),
            "noise": noise_share(result.get("trace", [])),
            "routed_to": result.get("routed_to"),
            "outcome": result["outcome"],
            "answer": result["answer"]}


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    print(f"── Практика М4 · обсяг даних · обидві сторони на {MODEL} ──")
    if MODEL != MODEL_FAST:
        print("  УВАГА: цикл агента не на дешевій моделі — серія задумана "
              "дешевою, перевірте ANTHROPIC_MODEL.")

    # Модель ембедингів піднімається до секундомірів — інакше перший прогін
    # платить за неї ~2 хвилини стіни (так сталося в серії 2026-08-25, її
    # перший рядок лишився з цим спотворенням).
    if os.getenv("PRACTICE_RETRIEVER", "vector") == "vector":
        from practice.common.vectors import embed
        embed(["warm-up"], kind="query")

    records = []
    total_started = time.time()
    for n_docs in SIZES:
        fragments = set_corpus(n_docs)
        print(f"── корпус: {n_docs} документів, {fragments} фрагментів ──")
        for name, query in SCALE_QUERIES.items():
            for side, fn in (("один", single.run_single),
                             ("система", system.run_system)):
                m = _measure(side, fn, query)
                m.update(scenario=name, docs=n_docs, fragments=fragments)
                records.append(m)
                print(f"  {name:10} {side:8} {m['pipeline_sec']:7.1f} с  "
                      f"${m['cost_usd']:.4f}  пошуків: {m['searches']}  "
                      f"шум: {m['noise']:.0%}  маршрут: {m['routed_to'] or '—'}")
    total_sec = round(time.time() - total_started, 2)

    print("── Підсумок по розмірах (сума трьох запитів) ──")
    for n_docs in SIZES:
        for side in ("один", "система"):
            rows = [r for r in records
                    if r["docs"] == n_docs and r["side"] == side]
            usd = sum(r["cost_usd"] for r in rows)
            sec = sum(r["pipeline_sec"] for r in rows)
            noise = (sum(r["noise"] for r in rows) / len(rows)) if rows else 0
            print(f"  {n_docs:2} док.  {side:8} {sec:7.1f} с  ${usd:.4f}  "
                  f"середній шум: {noise:.0%}")
    print(f"  разом: {total_sec} с стіною")

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"scale-{stamp}.json"
    path.write_text(json.dumps(
        {"model": MODEL, "sizes": SIZES, "total_sec": total_sec,
         "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  збережено: {path}")

    set_corpus(18)   # повернути повний корпус тим, хто запускає далі в процесі
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
