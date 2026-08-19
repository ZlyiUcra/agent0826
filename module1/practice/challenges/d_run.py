"""
ЧЕЛЕНДЖ D · дія з наслідками — ТОЧКА ВХОДУ (запуск трьох кроків).
Пара до practice/challenges/d_tools.py (бекенд-інструменти).

    python -m practice.challenges.d_run           # усі три кроки по черзі
    python -m practice.challenges.d_run request   # крок 1: клієнт просить переадресацію
    python -m practice.challenges.d_run confirm   # крок 2: клієнт підтверджує
    python -m practice.challenges.d_run repeat    # крок 3: ТЕ САМЕ підтвердження вдруге
    python -m practice.challenges.d_run --status  # вміст сховища заявок, $0
    python -m practice.challenges.d_run --help    # довідка

Чому три окремі прогони, а не одна розмова: run_agent не тримає історії між
викликами — кожен прогін починається з чистого аркуша. Тому підтвердження
«наступним повідомленням» можливе лише через стан у сховищі: перший прогін
лишає заявку pending на диску, другий знаходить її там і підтверджує. Це не
обхід обмеження, а його чесне використання: саме так працює підтримка, коли
клієнт відповідає через годину іншим повідомленням.

Повний прогін (без аргументів) — показовий, тож іде на ізольованому тимчасовому
сховищі: реальне out/redirects.json він не чіпає взагалі, а тимчасове зникає
після виходу. Так кожне демо — окремий замкнений світ, і питання міжпрогонної
ідемпотентності не виникає. Окремий крок (`action confirm`) навпаки працює з
реальним сховищем, і там ідемпотентність між запусками чесно жива.

Крок 3 — вимога картки дослівно: повторний запит НЕ створює дублікат. Запит
той самий до літери, а сховище після нього не змінюється взагалі — це
перевіряється порівнянням вмісту до і після, а не чесним словом.

Детерміновані перевірки на кожному кроці:
  - на кроці request будь-який виклик confirm_redirect — дефект: агент
    підтвердив незворотну дію без згоди клієнта;
  - після кожного кроку сховище звіряється з очікуваним станом: скільки
    записів, який стан заявки;
  - на кроці repeat сховище до і після мусить збігатися байт у байт.

Вартість: три прогони — близько $0.05. Ліміт свій,
PRACTICE_ACTION_BUDGET_USD, за замовчуванням $0.30.

Результати лягають у out/practice_results.json під ключами action:<крок>.
"""

import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import core.agent as agent                                      # noqa: E402
import domain.backend as course_backend                         # noqa: E402
from practice.base import run as prun                           # noqa: E402
from practice.challenges import d_tools as pactions             # noqa: E402
from practice.common import backend as practice_backend         # noqa: E402
from practice.common import budget                              # noqa: E402

DEFAULT_ACTION_BUDGET_USD = 0.30

# Правила двофазності — поверх звичайного промпту практики. Схеми кажуть
# те саме: подвійний шов, бо промпт і опис інструмента читаються моделлю
# в різні моменти міркування.
ACTION_PROMPT = prun.PRACTICE_PROMPT + (
    "\n- Переадресація — двофазна дія. Якщо клієнт ПРОСИТЬ переадресувати: "
    "створи заявку через request_redirect (передай телефон клієнта, трек-номер "
    "і нове місто), перекажи заявку клієнту (місто, трек-номер, номер заявки) "
    "і спитай підтвердження. На цьому зупинись.\n"
    "- confirm_redirect викликай лише тоді, коли клієнт у своєму повідомленні "
    "вже явно підтверджує переадресацію. Якщо заявки ще немає — спершу "
    "створи її, звір дані і підтверди тим самим ходом: згода вже прозвучала."
)

STEPS = {
    "request": {
        "query": "Мій номер 0671234567. Посилка EE401122334UA їде до Львова, "
                 "але я вже переїхав. Переадресуйте її, будь ласка, до Одеси.",
        "expect_state": "pending",
        "teaches": "заявка створюється, але НЕ виконується без згоди",
    },
    "confirm": {
        "query": "Так, підтверджую переадресацію посилки EE401122334UA до "
                 "Одеси. Мій номер 0671234567.",
        "expect_state": "confirmed",
        "teaches": "згода клієнта — і лише вона — робить дію незворотною",
    },
    "repeat": {
        "query": "Так, підтверджую переадресацію посилки EE401122334UA до "
                 "Одеси. Мій номер 0671234567.",
        "expect_state": "confirmed",
        "teaches": "повтор того самого запиту не створює другого запису",
    },
}


def register_action_tools() -> None:
    """Реєструє і базові, і мутуючі інструменти — з тією самою перевіркою
    перетину імен, що в run.py: колізія мовчки підмінила б курсову
    реалізацію, тож вона мусить падати голосно."""
    prun.register_tools()
    clash = set(pactions.ACTION_IMPL) & prun._COURSE_TOOL_NAMES
    if clash:
        raise RuntimeError(f"Імена інструментів дії перетинаються з курсовими: "
                           f"{sorted(clash)}")
    course_backend.IMPL.update(pactions.ACTION_IMPL)


def tools() -> list:
    return practice_backend.tools() + pactions.ACTION_SCHEMAS


def store_snapshot() -> dict:
    if not pactions.STORE.exists():
        return {}
    return json.loads(pactions.STORE.read_text(encoding="utf-8"))


def step_defects(step: str, result: dict, before: dict, after: dict) -> list:
    """Дефекти кроку. Порожній список — крок чистий."""
    found = []
    confirms = [s for s in result.get("trace") or []
                if s.get("tool") == "confirm_redirect"]
    if step == "request" and confirms:
        found.append("підтвердив незворотну дію в тому самому ході, "
                     "де клієнт лише попросив — без згоди клієнта")
    if step == "repeat" and after != before:
        found.append("повторний запит змінив сховище — ідемпотентність зламана")
    if len(after) > len(before) + 1:
        found.append(f"один крок додав {len(after) - len(before)} записів")

    expect = STEPS[step]["expect_state"]
    states = [r.get("state") for r in after.values()]
    if expect not in states:
        found.append(f"у сховищі немає заявки в стані {expect}")
    return found


def report_store(before: dict, after: dict) -> None:
    print(f"  сховище:      записів було {len(before)}, стало {len(after)}")
    for rid, record in after.items():
        marker = "новий" if rid not in before else (
            "змінено" if record != before[rid] else "без змін")
        print(f"    {rid}: {record['tracking']} -> {record['new_city']}, "
              f"стан {record['state']} ({marker})")


def run_step(step: str, limit: float, spent_before: float) -> dict:
    spec = STEPS[step]
    print("=" * 70)
    print(f"КРОК [{step}] · {spec['teaches']}")
    print("=" * 70 + "\n")

    state = budget.check(limit, extra_spent=spent_before)
    if not state["ok"]:
        print(f"  ПРОПУЩЕНО: {budget.refusal_text(state)}\n")
        return {}

    before = store_snapshot()
    agent.reset_usage()
    result = agent.run_agent(system=ACTION_PROMPT, tools=tools(),
                             query=spec["query"])
    after = store_snapshot()

    prun.enrich(result, f"action:{step}", spec["query"], limit)
    result["store_before"], result["store_after"] = before, after
    prun.report(result, spec["query"], limit)
    prun.save_result(f"action:{step}", result)
    report_store(before, after)

    found = step_defects(step, result, before, after)
    if found:
        print("  ЗЛАМАВСЯ:")
        for reason in found:
            print(f"    - {reason}")
    else:
        print(f"  крок чистий: {spec['teaches']}")
    print()
    return {"result": result, "defects": found, "spent": budget.spent_usd()}


def main(argv: list) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if argv and argv[0] == "--status":
        snapshot = store_snapshot()
        print(f"\nСховище заявок ({pactions.STORE}):\n")
        if not snapshot:
            print("  порожньо")
        for rid, record in snapshot.items():
            print(f"  {json.dumps(record, ensure_ascii=False)}")
        print()
        return 0

    full_run = not argv
    wanted = list(STEPS) if full_run else argv
    unknown = [w for w in wanted if w not in STEPS]
    if unknown:
        print(f"Немає кроку '{unknown[0]}'. Кроки: {', '.join(STEPS)}")
        return 2

    budget.ensure_model_priced()
    register_action_tools()
    limit = float(os.getenv("PRACTICE_ACTION_BUDGET_USD",
                            DEFAULT_ACTION_BUDGET_USD))

    print(f"\nЧелендж D · дія з наслідками · модель {prun.MODEL} "
          f"· ліміт ${limit:.4f}\n")

    # Повний прогін (без аргументів) — показовий, тож іде на ІЗОЛЬОВАНОМУ
    # тимчасовому сховищі: реальне out/redirects.json не чіпається взагалі, і
    # питання міжпрогонної ідемпотентності не виникає — кожне демо це окремий
    # замкнений світ. Окремий крок (`action confirm`) навпаки працює з реальним
    # сховищем, тож там ідемпотентність між запусками чесно жива.
    tmp = None
    saved_store = pactions.STORE
    if full_run:
        tmp = tempfile.TemporaryDirectory()
        pactions.STORE = pathlib.Path(tmp.name) / "redirects.json"
        print(f"  повне демо на тимчасовому сховищі ({pactions.STORE.name}) — "
              f"реальне out/redirects.json недоторкане\n")

    try:
        spent, broken = 0.0, []
        for step in wanted:
            got = run_step(step, limit, spent)
            if not got:
                break
            spent += got["spent"]
            if got["defects"]:
                broken.append(step)

        print("-" * 70)
        if broken:
            print(f"  Зламалося: {', '.join(broken)}")
        else:
            print("  Усі кроки чисті: заявка створена, підтверджена згодою, "
                  "повтор дубля не створив.")
        print(f"\nВитрачено: ${spent:.4f} з ${limit:.4f}")
        print(f"Збережено: {prun.RESULTS}")
        print(f"Сховище:   {pactions.STORE}"
              + ("  (тимчасове, зникне після виходу)" if full_run else ""))
    finally:
        pactions.STORE = saved_store
        if tmp is not None:
            tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
