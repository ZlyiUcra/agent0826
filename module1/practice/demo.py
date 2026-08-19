"""
ОСНОВА · демо станів: усі п'ять станів ядра по сцені на кожен.

Курсовий demo.py показує три сцени, бо на модулі 1 більше й не треба. Практиці
картка ставить жорсткішу вимогу: оброблені **всі п'ять** станів. Тут вони показані
поштучно, плюс шоста сцена — бюджетна відмова, стан обгортки практики.

    python -m practice.demo          # усі шість
    python -m practice.demo 1 4      # вибрані
    python -m practice.demo --list   # що є
    python -m practice.demo --help   # довідка

Скільки це коштує. Платні лише сцени 1-4: приблизно $0.06-0.09 сумарно, залежно
від багатослівності моделі. Сцена 5 робить справжній HTTP-запит, який сервер
відхиляє (401), тож коштує нуль. Сцена 6 не звертається до моделі взагалі.

Через це у демо власний ліміт — PRACTICE_DEMO_BUDGET_USD, за замовчуванням $0.30:
шість сцен в одному процесі не вкладаються у звичайний ліміт одного прогону.
Бюджет тут наскрізний: `USAGE` скидається перед кожною сценою, щоб числа кожної
сцени були чистими, а демо веде власний сумарний підрахунок і передає його
в перевірку. Тобто якщо перші сцени вичерпають ліміт, наступні чесно не стартують —
і це теж буде видно на сцені.

Результати лягають у out/practice_results.json під ключами demo:<стан>, поруч
із записами practice/run.py і не затираючи їх.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from anthropic import Anthropic                            # noqa: E402
import core.agent as agent                                 # noqa: E402
from practice import backend as practice_backend           # noqa: E402
from practice import budget, run as prun                   # noqa: E402

DEFAULT_DEMO_BUDGET_USD = 0.30

# Накопичена вартість усіх сцен процесу. `USAGE` скидається перед кожною сценою,
# тому сам він суми не пам'ятає — її тримаємо тут і віддаємо в budget.check().
_spent_total = 0.0


def _play(state: str, query: str, limit: float, prepare=None, restore=None) -> None:
    """Проганяє одну сцену: бюджет -> агент -> звіт -> запис у JSON.

    `prepare` / `restore` — гачки для сцен, що псують оточення (ліміт кроків,
    підмінений клієнт). Відновлення стоїть у `finally`, бо інакше зіпсоване
    оточення протекло б у наступні сцени того самого процесу.
    """
    global _spent_total

    state_check = budget.check(limit, extra_spent=_spent_total)
    if not state_check["ok"]:
        refusal = budget.refusal_text(state_check)
        print(f"  ПРОПУЩЕНО: {refusal}\n")
        return

    agent.reset_usage()
    if prepare:
        prepare()
    try:
        result = agent.run_agent(system=prun.PRACTICE_PROMPT,
                                 tools=practice_backend.tools(), query=query)
        # Звіт друкується ДО restore навмисно: він читає agent.MAX_TURNS, тобто
        # ліміт, який діяв у прогоні. Поверни стан раніше — і сцена 4 надрукує
        # «1 з 6» замість «1 з 1», тобто збреше про власну умову зупинки.
        prun.enrich(result, f"demo:{state}", query, limit)
        prun.report(result, query, limit)
    finally:
        if restore:
            restore()
    _spent_total += budget.spent_usd()
    prun.save_result(f"demo:{state}", result)

    got = result.get("outcome")
    if result.get("no_tool_used"):
        got = "no_tool_used"
    elif result.get("failures") and got == "ok":
        got = "tool_error"
    mark = "збіглося" if got == state else f"НЕ збіглося (очікували {state})"
    print(f"  стан сцени:   {got} — {mark}")
    print(f"  сумарно:      ${_spent_total:.4f} з ${limit:.4f}\n")


def scene_1(limit):
    print("── Сцена 1. ok — ланцюжок відпрацював ────────────────────────")
    print("   Клієнт назвав телефон. Пошук віддає трек-номери, деталі беруться")
    print("   по кожному. Аргумент другого інструмента народився у виході першого.\n")
    _play("ok", prun.QUERIES["happy"], limit)


def scene_2(limit):
    print("── Сцена 2. no_tool_used — інструмента під питання немає ─────")
    print("   Погоди в бекенді немає, і вигадувати її нічим. Агент, що відповідає")
    print("   «з голови», небезпечніший за того, що мовчить — прапорець це ловить.\n")
    _play("no_tool_used", prun.QUERIES["offtopic"], limit)


def scene_3(limit):
    print("── Сцена 3. tool_error — інструмент повернув помилку ─────────")
    print("   Засіяний випадок: пошук трек-номер знаходить, а деталей по ньому")
    print("   немає. Цикл не падає — помилка їде моделі, і та каже правду клієнту.\n")
    _play("tool_error", prun.QUERIES["tool_error"], limit)


def scene_4(limit):
    print("── Сцена 4. turns_exhausted — зрив ліміту кроків ─────────────")
    print("   MAX_TURNS=1: агент встигає лише знайти посилки, переказати їх уже ні.")
    print("   Замість мовчазного обриву — чесна заглушка і передача оператору.\n")
    saved = agent.MAX_TURNS
    _play("turns_exhausted", prun.QUERIES["happy"], limit,
          prepare=lambda: setattr(agent, "MAX_TURNS", 1),
          restore=lambda: setattr(agent, "MAX_TURNS", saved))


def scene_5(limit):
    print("── Сцена 5. api_error — збій сервісу моделі ──────────────────")
    print("   Клієнт підміняється на завідомо невалідний ключ. Це справжній HTTP-")
    print("   запит із справжньою відмовою 401, а не мок — і коштує нуль.\n")
    saved = agent.client
    _play("api_error", prun.QUERIES["happy"], limit,
          prepare=lambda: setattr(agent, "client",
                                  Anthropic(api_key="sk-ant-invalid-demo-key")),
          restore=lambda: setattr(agent, "client", saved))


def scene_6(limit):
    print("── Сцена 6. budget_exhausted — стан обгортки, не ядра ────────")
    print("   Ліміт нижчий за резерв прогону. Зупинка настає ДО першого звернення")
    print("   до моделі, тож сцена безкоштовна. Це не outcome ядра — це рівень практики.\n")
    state = budget.check(0.0001, extra_spent=0.0)
    refusal = budget.refusal_text(state)
    print(f"  запит:        «{prun.QUERIES['happy']}»")
    print("  outcome:      budget_exhausted")
    print(f"  відповідь:\n    {refusal}")
    prun.save_result("demo:budget_exhausted",
                     {"scenario": "demo:budget_exhausted", "query": prun.QUERIES["happy"],
                      "outcome": "budget_exhausted", "answer": refusal,
                      "budget": state, "trace": [],
                      "cost": {"usd": 0.0, "calls": 0, "in": 0, "out": 0, "by_model": []}})
    print("  стан сцени:   budget_exhausted — збіглося")
    print(f"  сумарно:      ${_spent_total:.4f} з ${limit:.4f}\n")


SCENES = {1: scene_1, 2: scene_2, 3: scene_3, 4: scene_4, 5: scene_5, 6: scene_6}

TITLES = {1: "ok", 2: "no_tool_used", 3: "tool_error",
          4: "turns_exhausted", 5: "api_error", 6: "budget_exhausted"}


def main(argv: list) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--list":
        print("\nСцени практики:\n")
        for n, name in TITLES.items():
            print(f"  {n}. {name}")
        print()
        return 0

    try:
        wanted = [int(a) for a in argv] or sorted(SCENES)
    except ValueError:
        print(f"Номери сцен — числа 1-6. Отримано: {' '.join(argv)}")
        return 2
    unknown = [n for n in wanted if n not in SCENES]
    if unknown:
        print(f"Немає таких сцен: {unknown}. Доступні 1-6, див. --list")
        return 2

    budget.ensure_model_priced()
    prun.register_tools()
    limit = float(os.getenv("PRACTICE_DEMO_BUDGET_USD", DEFAULT_DEMO_BUDGET_USD))

    print(f"\nПрактика М1 · демо станів · модель {prun.MODEL} · ліміт демо ${limit:.4f}")
    print("─" * 70 + "\n")

    for n in wanted:
        SCENES[n](limit)

    print("─" * 70)
    print(f"Витрачено: ${_spent_total:.4f} з ${limit:.4f}")
    print(f"Збережено: {prun.RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
