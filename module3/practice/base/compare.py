"""
ОСНОВА · вимір картки: ті самі запити через ручний стек і через граф LangGraph.

Обидва стеки ганяються в одному процесі, підряд, на тих самих запитах із
base/queries.py. Картка просить три речі: ті самі запити — ті самі рішення
(маршрут, запасний маршрут, передача людині), а також рядки коду, час на
перенос і вартість одного прогону. Час на перенос — у README; рядки коду
рахує цей файл із прапорцем --loc; решту — прогін.

ЩО МІРЯЄТЬСЯ І ХТО СУДДЯ

Час — таймер навколо повного маршруту (роутер + спеціаліст + запасний маршрут +
критик + перевірки), не лише виклик моделі. Вартість — з USAGE кожного стека
окремо: ручний стек рахує в core/agent.py, граф — у base/graph.py, обидва за
таблицею PRICES. «Рішення» — маршрут після запасного, outcome, чи була
передача людині, чи знайшлися вигадані посилання. Чи збіглися відповіді за
змістом — вирішує людина, яка читає надруковане; для цього відповіді
друкуються повністю і лягають у файл поруч.

За замовчуванням три запити — по одному на кожен рід із base/queries.py:
attrs (одна родина), proxy (міжтемний, GENERAL із субагентом), flat (поза
документами — міряє відмову). --all бере всі п'ять.

Індекси всіх підмножин будуються до старту секундомірів.

    python -m practice.base.compare --fast          # три запити, обидва стеки, дешева модель
    python -m practice.base.compare --fast --all    # усі п'ять запитів
    python -m practice.base.compare --loc           # рядки коду обох стеків, $0
    прапорці: --lexical, --live — ті самі, що в base/system.py і base/graph.py;
    --fast переводить ОБИДВА стеки на дешеву модель
"""

import json
import os
import pathlib
import sys
import time

from config import MAX_TURNS, MODEL_FAST
from core import agent as course_agent
from core import cost

from practice.base import graph, system, team
from practice.base.queries import QUERIES
from practice.common import nform

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT = ("attrs", "proxy", "flat")

# Що рахувати за «код стека»: файли, які переносилися, плюс цикл, на який
# кожен із них спирається. Спільні team.py і critic.py в обох стеках однакові,
# тож у різницю не входять.
LOC = {
    "ручний": ["practice/base/system.py", "core/agent.py"],
    "граф":   ["practice/base/graph.py"],
}


def _measure(label: str, fn, usage: dict, reset, query: str) -> dict:
    started = time.time()
    reset()
    result = fn(query)
    return {"side": label, "pipeline_sec": round(time.time() - started, 2),
            "cost_usd": cost.usd(usage["by_model"]), "calls": usage["calls"],
            "result": result}


def _route(r: dict) -> str:
    routed = r.get("routed_to", "—")
    if r.get("fallback_from"):
        routed = f"{r['fallback_from']}→{routed}"
    return routed


def _decisions(r: dict) -> dict:
    """Те, що має збігтися між стеками: рішення, а не слова."""
    return {"route": _route(r), "outcome": r["outcome"],
            "handoff": bool(r.get("handoff")),
            "fabricated": bool(r.get("citations", {}).get("fabricated"))}


def _row(m: dict) -> None:
    r = m["result"]
    marks = []
    if r.get("citations", {}).get("fabricated"):
        marks.append("вигадані посилання")
    if r.get("critic", {}).get("revised"):
        marks.append("критик переробляв")
    if r.get("handoff"):
        marks.append("передано людині" if r["handoff"].get("ticket")
                     else "запит на передачу, чекає підтвердження")
    print(f"  {m['side']:7} {m['pipeline_sec']:7.1f} с  ${m['cost_usd']:.4f}  "
          f"{m['calls']:2} викл.  маршрут: {_route(r):22} outcome: {r['outcome']}"
          + (f"  [{'; '.join(marks)}]" if marks else ""))
    for line in r["answer"].splitlines():
        print(f"           {line}")
    print()


def loc() -> int:
    print("── Рядки коду двох стеків (усього / непорожніх) ──")
    for side, files in LOC.items():
        total = blank = 0
        for rel in files:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
            total += len(lines)
            blank += sum(1 for ln in lines if not ln.strip())
            print(f"  {side:7} {rel:32} {len(lines):4}")
        print(f"  {side:7} {'разом':32} {total:4} / {total - blank}")
    print("  спільне для обох: practice/base/team.py, practice/base/critic.py, practice/common/")
    return 0


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--loc" in argv:
        return loc()
    if "--lexical" in argv:
        os.environ["PRACTICE_RETRIEVER"] = "lexical"
    live = "--live" in argv
    fast = "--fast" in argv
    if fast:
        team.use_fast_model()
        graph.use_fast_model()
    names = list(QUERIES) if "--all" in argv else list(DEFAULT)

    print(f"── Практика М3 · порівняння стеків · {course_agent.MODEL} + {MODEL_FAST} · "
          f"MAX_TURNS={MAX_TURNS} · запитів: {len(names)} ──")

    team.register()
    print("  прогрів індексів (у вимір не входить)...")
    for family in list(team.FAMILIES) + [team.GENERAL]:
        idx = team.index_for(family)
        print(f"    {family:8} {len(idx.passages)} "
              f"{nform(len(idx.passages), 'фрагмент', 'фрагменти', 'фрагментів')}")
    team.warm_search(team.GENERAL)

    total_started = time.time()
    records = []
    for name in names:
        q = QUERIES[name]
        print(f"── {name} · {q['kind']} ──")
        print(f"  «{q['query']}»")
        m_sys = _measure("ручний", lambda query: system.run_system(query, live=live),
                         course_agent.USAGE, course_agent.reset_usage, q["query"])
        _row(m_sys)
        m_graph = _measure("граф", lambda query: graph.run_graph(query, live=live),
                           graph.USAGE, graph.reset_usage, q["query"])
        _row(m_graph)
        same = _decisions(m_sys["result"]) == _decisions(m_graph["result"])
        print(f"  рішення збіглися: {'так' if same else 'НІ'}  "
              f"({_decisions(m_sys['result'])} проти {_decisions(m_graph['result'])})\n")
        for m in (m_sys, m_graph):
            records.append({"scenario": name, "query": q["query"], "kind": q["kind"],
                            "side": m["side"], "pipeline_sec": m["pipeline_sec"],
                            "cost_usd": m["cost_usd"], "calls": m["calls"],
                            "decisions": _decisions(m["result"]),
                            "answer": m["result"]["answer"], "showable": None})

    total_sec = round(time.time() - total_started, 2)
    print("── Підсумок ──")
    for side in ("ручний", "граф"):
        rows = [r for r in records if r["side"] == side]
        sec = sum(r["pipeline_sec"] for r in rows)
        usd = sum(r["cost_usd"] for r in rows)
        calls = sum(r["calls"] for r in rows)
        print(f"  {side:7} {sec:7.1f} с  ${usd:.4f}  {calls} викликів  на {len(rows)} "
              f"{nform(len(rows), 'запит', 'запити', 'запитів')}")
    agree = sum(1 for n in names
                if [r["decisions"] for r in records if r["scenario"] == n][0]
                == [r["decisions"] for r in records if r["scenario"] == n][1])
    print(f"  рішення збіглися на {agree} з {len(names)}; разом {total_sec} с стіною")

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"compare-{stamp}.json"
    path.write_text(json.dumps(
        {"model": course_agent.MODEL, "model_fast": MODEL_FAST,
         "retriever": os.getenv("PRACTICE_RETRIEVER", "auto"),
         "docs": os.getenv("PRACTICE_DOCS", "core"), "live": live,
         "total_sec": total_sec, "agreed": agree, "records": records},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  збережено:    {path} (щоразу новий файл, попередні прогони цілі)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
