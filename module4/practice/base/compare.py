"""
ОСНОВА · вимір картки: п'ять запитів через одного агента і через систему.

Обидві сторони ганяються В ОДНОМУ процесі, підряд, на тих самих п'яти запитах
із base/queries.py (склад зафіксовано до вимірів — чому саме такий, у докстрингу
там). Для кожного запиту друкуються час, вартість і повна відповідь, наприкінці
— підсумки по сторонах.

ЩО МІРЯЄТЬСЯ І ХТО СУДДЯ

Час — таймер навколо повного маршруту (для системи це роутер + спеціаліст +
критик + перевірки, не лише виклик моделі). Вартість — з USAGE, окремо на кожен
запит. Третє число картки — «скільки відповідей ви б показали клієнту» — тут
НЕ рахується: вердикт про придатність відповіді ухвалює людина, яка читає
надруковане, а не ще одна модель. Для цього відповіді й друкуються повністю,
а в збереженому файлі під кожен запит лишається порожнє поле showable.

Індекси всіх підмножин будуються ДО старту секундомірів: перший запит не має
платити часом за збірку кешів, яка іншим не дісталася.

Вартість між прогонами гуляє в півтора-два рази — кількість пошуків обирає
модель. Один прогін показує порядок чисел, а не точку.

    python -m practice.base.compare               # усі п'ять запитів, обидві сторони
    прапорці: --lexical, --rewrite, --live — ті самі, що в base/system.py
"""

import json
import os
import pathlib
import sys
import time

from config import MAX_TURNS, MODEL, MODEL_FAST
from core import cost
from core.agent import USAGE, reset_usage

from practice.base import single, system, team
from practice.base.queries import QUERIES

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"


def _measure(label: str, fn, query: str) -> dict:
    started = time.time()
    reset_usage()
    result = fn(query)
    return {"side": label,
            "pipeline_sec": round(time.time() - started, 2),
            "cost_usd": cost.usd(USAGE["by_model"]),
            "calls": USAGE["calls"],
            "result": result}


def _row(m: dict) -> None:
    r = m["result"]
    routed = r.get("routed_to", "—")
    if r.get("fallback_from"):
        routed = f"{r['fallback_from']}→{routed}"
    marks = []
    if r.get("citations", {}).get("fabricated"):
        marks.append("вигадані посилання")
    if r.get("critic", {}).get("revised"):
        marks.append("критик переробляв")
    if r.get("handoff"):
        marks.append("передано людині")
    print(f"  {m['side']:8} {m['pipeline_sec']:7.1f} с  ${m['cost_usd']:.4f}  "
          f"маршрут: {routed:22} outcome: {r['outcome']}"
          + (f"  [{'; '.join(marks)}]" if marks else ""))
    for line in r["answer"].splitlines():
        print(f"           {line}")
    print()


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--lexical" in argv:
        os.environ["PRACTICE_RETRIEVER"] = "lexical"
    if "--rewrite" in argv:
        os.environ["PRACTICE_REWRITE"] = "1"
    live = "--live" in argv

    print(f"── Практика М4 · порівняння · {MODEL} + {MODEL_FAST} · "
          f"MAX_TURNS={MAX_TURNS} ──")

    team.register()
    print("  прогрів індексів (у вимір не входить)...")
    for family in list(team.FAMILIES) + [team.GENERAL]:
        idx = team.index_for(family)
        print(f"    {family:8} {len(idx.passages)} фрагментів")
    # Прогрів індексів вантажить лише кеші векторів; сама модель ембедингів
    # підіймається при ПЕРШОМУ запитному ембедингу — і в прогоні 2026-08-25 це
    # коштувало першому виміряному прогону зайві ~2 хвилини стіни. Тому модель
    # прогрівається тут одним неробочим запитом, до секундомірів.
    if os.getenv("PRACTICE_RETRIEVER", "vector") == "vector":
        from practice.common.vectors import embed
        embed(["warm-up"], kind="query")
        print("  модель ембедингів піднято до секундомірів")

    total_started = time.time()
    records = []
    for scenario, q in QUERIES.items():
        print(f"── {scenario} · {q['kind']} ──")
        print(f"  «{q['query']}»")
        m_single = _measure("один", single.run_single, q["query"])
        _row(m_single)
        m_system = _measure("система",
                            lambda query: system.run_system(query, live=live),
                            q["query"])
        _row(m_system)
        for m in (m_single, m_system):
            records.append({"scenario": scenario, "query": q["query"],
                            "kind": q["kind"], "side": m["side"],
                            "pipeline_sec": m["pipeline_sec"],
                            "cost_usd": m["cost_usd"], "calls": m["calls"],
                            "routed_to": m["result"].get("routed_to"),
                            "outcome": m["result"]["outcome"],
                            "handoff": m["result"].get("handoff"),
                            "answer": m["result"]["answer"],
                            "showable": None})

    total_sec = round(time.time() - total_started, 2)

    print("── Підсумок ──")
    for side in ("один", "система"):
        rows = [r for r in records if r["side"] == side]
        sec = sum(r["pipeline_sec"] for r in rows)
        usd = sum(r["cost_usd"] for r in rows)
        print(f"  {side:8} {sec:7.1f} с  ${usd:.4f}  на п'ять запитів")
    print(f"  разом:   {total_sec} с стіною, обидві сторони")
    print("  «скільки показали б клієнту» — рахує людина: перечитайте десять\n"
          "  відповідей вище і проставте showable у збереженому файлі.")

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"compare-{stamp}.json"
    path.write_text(json.dumps(
        {"model": MODEL, "model_fast": MODEL_FAST,
         "retriever": os.getenv("PRACTICE_RETRIEVER", "vector"),
         "rewrite": os.getenv("PRACTICE_REWRITE", "0"), "live": live,
         "total_sec": total_sec, "records": records},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  збережено:    {path} (щоразу новий файл, попередні прогони цілі)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
