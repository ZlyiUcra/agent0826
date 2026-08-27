"""
КОНТЕКСТ · прибрати інструмент, якого модель не викликає, і подивитися, чи
стало гірше. ПЛАТНА.

Необов'язковий чекбокс другої картки. Кандидат один — request_handoff у
маршруті GENERAL: у збережених слідах першої картки модель не викликала його
жодного разу, а єдиний запис у черзі передачі поставив конвеєр — decide() у
base/system.py побачив порожнє дослідження раніше, ніж модель щось вирішила.
Опис інструмента при цьому їде в кожен виклик GENERAL; скільки саме токенів —
друкує context/window.py, безкоштовно.

Прогін ганяє ті самі запити двічі, з інструментом і без, підряд і на одній
моделі, і зводить у таблицю: маршрут, outcome, хто і чому передав людині, чи
кликала модель інструмент, долари, секунди. Запитів три: два з п'ятірки виміру
першої картки, які ходять через GENERAL (proxy, tofixed), і запит про борщ, на
якому передача людині взагалі стається. «Чи стало гірше» — за тими самими
ознаками, що в base/compare.py; вердикт про показуваність відповіді лишається
за людиною, тому відповіді друкуються цілком.

Обидва боки на дешевій моделі каскаду (team.use_fast_model()). База першої
картки в compare-*.json знята на дорогій, і з нею ці числа не порівнюються:
порівнюються два боки цього ж прогону між собою.

Можлива побічна дія: якщо на запиті про борщ модель зробить хоч одне
дослідження і воно повернеться порожнім, конвеєр поставить у чергу
out/pending_handoff.json запит на передачу людині — по одному на бік. У прогоні
2026-08-26 на дешевій моделі цього не сталося: обидва боки відмовили за
правилом «не твоя тема», не зробивши жодного пошуку, і черга не змінилася.
Підтвердити або лишити запит, якщо ляже, — python -m practice.base.system
--confirm, $0.

    python -m practice.context.drop
    python -m practice.context.drop --only borscht
"""

import json
import os
import pathlib
import sys
import time

from config import MAX_TURNS, MODEL_FAST
from core import agent as course_agent
from core import cost
from core.agent import USAGE, reset_usage

from practice.base import system, team
from practice.common import nform
from practice.base.queries import QUERIES

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
TOOL = team.REQUEST_TOOL

SCENARIOS = {
    "proxy":   QUERIES["proxy"],
    "tofixed": QUERIES["tofixed"],
    "borscht": {
        "query": "Скільки коштує борщ у Львові і де його найкраще готують?",
        "expected_route": "GENERAL",
        "kind": "поза темою: жодної родини, дослідження повертається порожнім",
    },
}

SIDES = (("з інструментом", set()), ("без інструмента", {TOOL}))


def run_one(query: str, drop: set) -> dict:
    os.environ[team.DROP_ENV] = ",".join(sorted(drop))
    started = time.time()
    reset_usage()
    result = system.run_system(query)
    trace_tools = [step.get("tool") for step in result.get("trace", [])]
    return {"with_tool": TOOL not in drop,
            "pipeline_sec": round(time.time() - started, 2),
            "cost_usd": cost.usd(USAGE["by_model"]),
            "calls": USAGE["calls"],
            "routed_to": result.get("routed_to"),
            "fallback_from": result.get("fallback_from"),
            "outcome": result["outcome"],
            "handoff": result.get("handoff"),
            "model_called_tool": TOOL in trace_tools,
            "trace_tools": trace_tools,
            "citations": {k: result.get("citations", {}).get(k, [])
                          for k in ("cited", "fabricated")},
            "answer": result["answer"]}


def handoff_mark(rec: dict) -> str:
    h = rec.get("handoff")
    if not h:
        return "—"
    return f"{h.get('by', '?')}: {h.get('reason', '?')}"


def show(side: str, rec: dict) -> None:
    routed = rec["routed_to"] or "—"
    if rec.get("fallback_from"):
        routed = f"{rec['fallback_from']}→{routed}"
    print(f"  {side:<16}{rec['pipeline_sec']:7.1f} с  ${rec['cost_usd']:.4f}  "
          f"маршрут: {routed:10} outcome: {rec['outcome']}  "
          f"передача: {handoff_mark(rec)}  "
          f"модель кликала {TOOL}: {'так' if rec['model_called_tool'] else 'ні'}")
    if rec["citations"]["fabricated"]:
        print(f"                  ВИГАДАНІ посилання: {', '.join(rec['citations']['fabricated'])}")
    for line in rec["answer"].splitlines():
        print(f"                  {line}")
    print()


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    wanted = list(SCENARIOS)
    if "--only" in argv:
        wanted = argv[argv.index("--only") + 1].split(",")
        unknown = [w for w in wanted if w not in SCENARIOS]
        if unknown:
            raise SystemExit(f"Немає сценарію {unknown[0]}. Є: {', '.join(SCENARIOS)}")

    model = team.use_fast_model()
    print(f"── Прибрати {TOOL} · {len(wanted)} {nform(len(wanted), 'запит', 'запити', 'запитів')} × 2 боки · "
          f"{model} + {MODEL_FAST} · "
          f"MAX_TURNS={MAX_TURNS} ──")
    team.register()
    # Як у base/compare.py: індекс і модель ембедингів піднімаються до
    # секундомірів, інакше перший прогін платить часом за їхню збірку.
    print("  прогрів індексу (у вимір не входить)...")
    team.index_for(team.GENERAL)
    if os.getenv("PRACTICE_RETRIEVER", "vector") == "vector":
        from practice.common.vectors import embed
        embed(["warm-up"], kind="query")
    print()

    records = []
    for name in wanted:
        q = SCENARIOS[name]
        print(f"── {name} · {q['kind']} ──")
        print(f"  «{q['query']}»")
        for side, drop in SIDES:
            rec = run_one(q["query"], drop)
            rec.update(scenario=name, query=q["query"], side=side)
            records.append(rec)
            show(side, rec)
    os.environ.pop(team.DROP_ENV, None)

    print(f"  {'запит':<9}{'бік':<17}{'маршрут':<10}{'outcome':<10}{'передача':<26}"
          f"{'кликала':>8}{'викл.':>6}{'$':>9}{'с':>7}")
    for r in records:
        print(f"  {r['scenario']:<9}{r['side']:<17}{r['routed_to'] or '—':<10}{r['outcome']:<10}"
              f"{handoff_mark(r):<26}{'так' if r['model_called_tool'] else 'ні':>8}"
              f"{r['calls']:>6}{r['cost_usd']:>9.4f}{r['pipeline_sec']:>7.1f}")
    for side, _ in SIDES:
        mine = [r for r in records if r["side"] == side]
        print(f"  {side:<16} разом ${sum(r['cost_usd'] for r in mine):.4f}, "
              f"{sum(r['pipeline_sec'] for r in mine):.1f} с")

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"drop-{stamp}.json"
    path.write_text(json.dumps(
        {"tool": TOOL, "model": course_agent.MODEL, "model_fast": MODEL_FAST,
         "retriever": os.getenv("PRACTICE_RETRIEVER", "vector"),
         "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Збережено: {path} (щоразу новий файл, попередні цілі)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
