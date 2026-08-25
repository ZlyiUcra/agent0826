"""
ОСНОВА · один агент — точка відліку для порівняння.

Це відтворення конфігурації практики модуля 2, а не її копія: той самий один
run_agent із пошуком по ПОВНОМУ набору документів, без маршрутизатора,
спеціалістів, критика і субагента. Проти нього compare.py міряє систему.

Одна свідома відмінність від промпта модуля 2: там четверте правило вимагало
відповідати англійською, тут — мовою запиту. Якби один агент лишився з
англійським правилом, український запит виміру він програвав би ще до старту,
і порівняння міряло б не оркестрацію, а нерівні промпти. Все інше — дослівно
правила спеціалістів із base/team.py, спільні для обох сторін виміру.

    python -m practice.base.single attrs          # сценарій із п'яти зафіксованих
    python -m practice.base.single "свій запит"   # довільний запит
    python -m practice.base.single --list         # перелік сценаріїв, $0
    прапорці: --lexical, --rewrite — ті самі, що в base/system.py
"""

import json
import os
import pathlib
import sys
import time

from config import MAX_TURNS, MODEL
from core import cost
from core.agent import USAGE, reset_usage, run_agent

from practice.base import critic, team
from practice.base.queries import QUERIES

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
RESULTS = OUT / "system_results.json"

SINGLE_PROMPT = (
    "You are a reference assistant for the ECMAScript language specification. "
    "You answer strictly from the excerpts returned by the search_docs tool."
    + team._RULES)


def run_single(query: str) -> dict:
    """Один прогін одного агента. Звірка посилань — та сама, що в системи."""
    team.register()
    result = run_agent(system=SINGLE_PROMPT,
                       tools=[team.SCHEMAS[team.TOOL_NAMES[team.GENERAL]]],
                       query=query)
    result["citations"] = critic.check_citations(result["answer"],
                                                 result["trace"])
    return result


def report(result: dict, query: str) -> None:
    print(f"  запит:        «{query}»")
    print(f"  outcome:      {result['outcome']}  ·  кроків: {result['turns']}"
          f"  ·  {result['elapsed_sec']} с")
    for step in result.get("trace", []):
        out = step["output"]
        ids = ", ".join(p["id"] for p in out.get("passages", [])) or "—"
        print(f"  пошук:        «{step['input'].get('query', '')}» "
              f"→ {out.get('found', 0)}: {ids}")
    cit = result.get("citations", {})
    if cit.get("fabricated"):
        print(f"  посилання:    ВИГАДАНІ: {', '.join(cit['fabricated'])}")
    elif cit.get("cited"):
        print(f"  посилання:    {len(cit['cited'])} шт., усі є в trace")
    print("  відповідь:")
    for line in result["answer"].splitlines():
        print(f"    {line}")
    c = cost.usd(USAGE["by_model"])
    print(f"  вартість:     ${c:.4f}  ({USAGE['calls']} викликів, "
          f"{USAGE['in']} in / {USAGE['out']} out)")


def save_result(key: str, record: dict) -> None:
    OUT.mkdir(exist_ok=True)
    stored = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    stored[key] = record
    RESULTS.write_text(json.dumps(stored, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def main(argv: list[str]) -> int:
    if "--list" in argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        for name, q in QUERIES.items():
            print(f"  {name:8} {q['kind']}\n           «{q['query']}»")
        return 0

    if "--lexical" in argv:
        os.environ["PRACTICE_RETRIEVER"] = "lexical"
    if "--rewrite" in argv:
        os.environ["PRACTICE_REWRITE"] = "1"

    positional = [a for a in argv if not a.startswith("-")]
    raw = positional[0] if positional else "attrs"
    scenario = raw if raw in QUERIES else "custom"
    query = QUERIES[raw]["query"] if raw in QUERIES else raw

    print(f"── Практика М4 · один агент · сценарій: {scenario} · {MODEL} "
          f"· MAX_TURNS={MAX_TURNS} ──")

    started = time.time()
    reset_usage()
    result = run_single(query)
    result.update(scenario=scenario, query=query,
                  pipeline_sec=round(time.time() - started, 2),
                  cost_usd=cost.usd(USAGE["by_model"]),
                  cost_breakdown=cost.breakdown(USAGE["by_model"]))
    report(result, query)
    if scenario != "custom":
        save_result(f"single:{scenario}", result)
        print(f"  збережено:    {RESULTS}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
