"""
ОСНОВА · агент над корпусом специфікації. Єдина точка входу, яка витрачає гроші.

Це доказ до першого і третього обов'язкових пунктів картки: вісімнадцять власних
документів підключені до агента, і на питання не з корпусу він відмовляється,
а не вигадує.

СЦЕНАРІЇ

  replace   людське формулювання замість назви методу; перевіряє, що агент
            узагалі дістає з корпусу правильний підрозділ
  proxy     складене питання з двох частин; агент має зробити не один пошук
  absent    питання, якого корпус не покриває взагалі
  known     питання, відповідь на яке модель точно знає з власного навчання, але
            в наших документах її немає
  thin      людське формулювання, на якому пошук чіпляється слабко; потрібен,
            щоб показати переписування запиту в роботі (з --rewrite)

Останній сценарій і є справжня перевірка відмови. На «What is the capital of
France?» модель відмовиться легко: питання явно не з тієї опери. А от
`Array.prototype.flat` — це та сама специфікація ECMAScript, тільки розділ 23.1,
якого ми не вивантажували. Модель знає цей метод напам'ять і має всі підстави
відповісти з голови. Якщо вона це зробить — це і є той головний дефект, про який
пише картка: відповідь без джерела, перевірити її нічим.

    python -m practice.base.ask                 # сценарій replace
    python -m practice.base.ask absent
    python -m practice.base.ask known --lexical # той самий агент на BM25
    python -m practice.base.ask thin --rewrite  # з переписуванням бідного запиту
    python -m practice.base.ask --list          # перелік сценаріїв, $0
"""

import json
import os
import pathlib
import sys

from config import MAX_TURNS, MODEL
from core import cost
from core.agent import USAGE, reset_usage, run_agent

from practice.common import rewrite as prewrite
from practice.common import tools as ptools

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
RESULTS = OUT / "practice_results.json"

QUERIES = {
    "replace": "How do I replace part of a text with something else, "
               "and what happens to the rest of the string?",
    "proxy": "When a proxy stands in for another object, what stops it from "
             "reporting a value that contradicts the real object, and how does "
             "reading a property through it actually work?",
    "absent": "What is the capital of France, and how far is it from Lviv?",
    "known": "How does Array.prototype.flat decide how deep to flatten a nested array?",
    "thin": "How do I remove spaces from both ends of a text?",
}


def save_result(scenario: str, record: dict) -> None:
    """Зливає запис у out/practice_results.json — той самий механізм, що в курсовому run.py.

    Файл читається цілим, запис кладеться під ключем сценарію, злите пишеться
    назад. Інші сценарії лишаються на місці; повторний прогін того самого
    сценарію замінює свій попередній запис.
    """
    OUT.mkdir(exist_ok=True)
    stored = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    stored[scenario] = record
    RESULTS.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")


def _report(result: dict, scenario: str, query: str, retriever: str) -> None:
    print(f"  запит:        «{query}»")
    print(f"  пошук:        {retriever}")
    print(f"  outcome:      {result['outcome']}  ·  кроків: {result['turns']}"
          f"  ·  {result['elapsed_sec']} с")

    trace = result.get("trace", [])
    if not trace:
        print("  пошуки:       жодного — агент відповів, не звернувшись до корпусу")
    for step in trace:
        out = step["output"]
        found = out.get("found", 0)
        ids = ", ".join(p["id"] for p in out.get("passages", [])) or "—"
        print(f"  пошук:        «{step['input'].get('query', '')}» → {found}: {ids}")
        if out.get("rewritten_query"):
            verdict = "взято другий набір" if out.get("rewrite_used") else "лишився перший"
            print(f"  переписано:   «{out['rewritten_query']}» → {verdict}")

    print("  відповідь:")
    for line in result["answer"].splitlines():
        print(f"    {line}")

    c = cost.usd(USAGE["by_model"])
    print(f"  вартість:     ${c:.4f}  ({USAGE['calls']} викликів, "
          f"{USAGE['in']} in / {USAGE['out']} out)")


def main(argv: list[str]) -> int:
    if "--list" in argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    retriever = "lexical" if "--lexical" in argv else "vector"
    if "--rewrite" in argv:
        os.environ["PRACTICE_REWRITE"] = "1"
    positional = [a for a in argv if not a.startswith("-")]
    scenario = positional[0] if positional else "replace"
    if scenario not in QUERIES:
        print(f"Невідомий сценарій '{scenario}'. Доступні: {', '.join(QUERIES)}")
        return 2

    os.environ["PRACTICE_RETRIEVER"] = retriever
    query = QUERIES[scenario]

    rew = "увімкнено" if prewrite.enabled() else "вимкнено"
    print(f"── Практика М2 · сценарій: {scenario} · модель {MODEL} "
          f"· MAX_TURNS={MAX_TURNS} · переписування {rew} ──")

    ptools.register()
    index = ptools.get_index(retriever)     # будуємо індекс до першого виклику API
    print(f"  корпус:       {len(index.passages)} фрагментів "
          f"з 18 документів специфікації")

    reset_usage()
    result = run_agent(system=ptools.PRACTICE_PROMPT, tools=ptools.tools(), query=query)
    result.update(scenario=scenario, query=query, retriever=retriever,
                  rewrite=prewrite.enabled(),
                  cost_usd=cost.usd(USAGE["by_model"]),
                  cost_breakdown=cost.breakdown(USAGE["by_model"]))
    _report(result, scenario, query, retriever)
    save_result(f"{scenario}:{retriever}" + (":rewrite" if prewrite.enabled() else ""),
                result)
    print(f"  збережено:    {RESULTS}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
