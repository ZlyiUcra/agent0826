"""
ЧЕЛЕНДЖ A · опис інструмента = поведінка агента.

    python -m practice.challenges.a_experiment --hunt          # шукати запит, що ламає наївний опис
    python -m practice.challenges.a_experiment --rescore       # переоцінити збережені прогони, $0
    python -m practice.challenges.a_experiment --query <ключ>  # обидва варіанти на цьому запиті
    python -m practice.challenges.a_experiment --list          # перелік запитів-кандидатів
    python -m practice.challenges.a_experiment                 # обидва варіанти на запиті за замовчуванням

Що перевіряємо. Реалізації інструментів, імена, параметри, системний промпт і запит
однакові в обох прогонах. Відрізняється РІВНО текст описів у схемі — той, що читає
модель. Якщо поведінка зміниться, причина може бути тільки одна.

Перша спроба (`phone_singular`) дала НЕГАТИВНИЙ результат: наївний опис упорався так
само добре. Висновок з неї — сигнал несуть не описи, а ІМЕНА: `find_shipments` проти
`get_shipment_details`, `phone` проти `tracking` майже однозначні самі по собі.
Тому режим `--hunt` ганяє наївний варіант по кандидатах, підібраних так, щоб імена
НЕ рятували: значення за формою підходить обом параметрам, або потрібного значення
в запиті немає взагалі.

Як вимірюємо, без моделі-судді і без читання очима:
  checks.misrouted_arguments() — телефон у tracking чи трек-номер у phone;
  який інструмент викликано ПЕРШИМ (правильний перший хід — find_shipments);
  checks.chain_evidence()      — чи дійшла справа до деталей і звідки взявся номер.

Вартість: пара прогонів — близько $0.04, повне полювання по чотирьох кандидатах —
близько $0.08. Ліміт свій, PRACTICE_EXPERIMENT_BUDGET_USD, за замовчуванням $0.30.

Результати лягають у out/practice_results.json під ключами experiment_a:<варіант>.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import core.agent as agent                                      # noqa: E402
from practice.base import run as prun                           # noqa: E402
from practice.common import backend as practice_backend         # noqa: E402
from practice.common import budget, checks                      # noqa: E402

DEFAULT_EXPERIMENT_BUDGET_USD = 0.30

# Кандидати на пастку. Перший уже перевірено — він НЕ спрацював (див. README),
# бо імена інструментів і параметрів (`phone`, `tracking`) несуть контракт самі,
# і затирання описів нічого не змінює. Решта підібрані так, щоб імена НЕ рятували:
# у кожному значення, яке клієнт дає, за формою підходить обом параметрам, або
# потрібного значення немає взагалі.
# У кожного кандидата вказано, який перший хід є ПРАВИЛЬНИМ саме для нього — без
# цього вимірювач карає агента за коректну поведінку (див. історію в README: перша
# версія рахувала правильним лише find_shipments і оголосила зламаним прогін, у
# якому агент цілком слушно пішов одразу в деталі).
CANDIDATES = {
    "phone_singular": {
        "query": "Доброго дня! У мене номер 0671234567, скажіть будь ласка, "
                 "що з моєю посилкою?",
        "expects": "find_shipments",
        "note": "телефон + «посилка» в однині при двох посилках",
    },
    "ambiguous_id": {
        "query": "Вітаю, мій номер 404455667. Підкажіть, будь ласка, що з відправленням?",
        "expects": "find_shipments",
        "note": "дев'ять голих цифр — форма і телефону, і цифрової частини трек-номера",
    },
    "tracking_only": {
        # Телефон власника в запиті: відколи деталі прив'язані до телефону (виправлення
        # foreign_tracking з челенджа B), без нього правильний хід — спитати номер,
        # а не викликати інструмент, і вимірювач карав би агента за чемність.
        "query": "Мій номер 0631112233. Що з посилкою EE404455667UA? "
                 "Дуже довго немає новин.",
        "expects": "get_shipment_details",
        "note": "є телефон і трек-номер — пошук законно пропускається",
    },
    "period_words": {
        "query": "Телефон 0671234567. Покажіть, будь ласка, посилки з 10 по 16 серпня.",
        "expects": "find_shipments",
        "note": "період словами; наївний опис не каже ні формату, ні року",
    },
}

# Помилки інструментів бувають двох різних сортів, і плутати їх не можна.
# Це нормальний стан даних, а не дефект агента:
DATA_ERRORS = {"not_found", "record_unavailable"}
# А це вже неправильно сформований аргумент, тобто саме те, що міряє челендж A:
ARGUMENT_ERRORS = {"bad_phone", "bad_date", "bad_period", "bad_args", "unknown_tool"}


def query_of(key: str) -> str:
    return CANDIDATES[key]["query"]


DEFAULT_CANDIDATE = "phone_singular"

VARIANTS = ("naive", "tuned")
LABELS = {"naive": "ДО — наївний опис", "tuned": "ПІСЛЯ — виправлений опис"}


def show_descriptions(variant: str) -> None:
    print(f"  описи, які бачить модель ({variant}):")
    for schema in practice_backend.tools(variant):
        print(f"    {schema['name']}:")
        print(f"      опис: {schema['description']}")
        for param, spec in schema["input_schema"]["properties"].items():
            print(f"      {param}: {spec['description']}")
    print()


def verdict(result: dict, key: str = None) -> dict:
    """Детерміновані показники прогону.

    `key` дає очікуваний перший хід. Без нього перевірка першого ходу пропускається:
    вгадувати «правильний» інструмент без знання запиту не можна.
    """
    trace = result.get("trace", [])
    expected = CANDIDATES[key]["expects"] if key in (CANDIDATES or {}) else None
    first = trace[0]["tool"] if trace else None

    arg_errors, data_errors = [], []
    for f in result.get("failures", []):
        code = str(f.get("error", "")).split(":")[0].strip()
        (arg_errors if code in ARGUMENT_ERRORS else data_errors).append(f)

    return {
        "first_tool": first,
        "expected_first": expected,
        "first_tool_correct": None if expected is None else first == expected,
        "misrouted": result["checks"]["misrouted_arguments"],
        "invented": result["checks"]["chain"]["invented"],
        "empty_period": result["checks"].get("empty_period", []),
        "arg_errors": arg_errors,
        "data_errors": data_errors,
        "chain_mode": result["checks"]["chain"]["mode"],
        "got_details": any(s["tool"] == "get_shipment_details" for s in trace),
        "turns": result.get("turns"),
        "usd": result["cost"]["usd"],
    }


def broke(v: dict) -> bool:
    """Чи це справжній дефект.

    Свідомо НЕ рахуються дефектом: `not_found` на неіснуючий номер і
    `record_unavailable` на засіяний зламаний запис — це стан даних, і чесно
    переказати його клієнту є правильною поведінкою, а не поломкою.
    """
    return bool(
        (v["first_tool_correct"] is False)
        or v["misrouted"] or v["invented"] or v["empty_period"] or v["arg_errors"]
    )


def why_broke(v: dict) -> list:
    reasons = []
    if v["first_tool_correct"] is False:
        reasons.append(f"перший хід {v['first_tool']}, а мав бути {v['expected_first']}")
    for m in v["misrouted"]:
        reasons.append(f"{m['tool']}({m['arg']}=\"{m['value']}\") — {m['why']}")
    for t in v["invented"]:
        reasons.append(f"вигаданий трек-номер {t}")
    for e in v["empty_period"]:
        reasons.append(f"період {e['period']['from']}..{e['period']['to']} відсік усе, "
                       f"а без нього відправлень {e['found_without_period']} "
                       f"({', '.join(e['shipped'])})")
    for f in v["arg_errors"]:
        reasons.append(f"аргумент відхилено бекендом: {f['tool']} -> {f['error']}")
    return reasons


def run_variant(variant: str, key: str, limit: float, spent_before: float) -> dict:
    query = query_of(key)
    print("=" * 70)
    print(f"{LABELS[variant]}")
    print("=" * 70 + "\n")
    show_descriptions(variant)

    state = budget.check(limit, extra_spent=spent_before)
    if not state["ok"]:
        print(f"  ПРОПУЩЕНО: {budget.refusal_text(state)}\n")
        return {}

    agent.reset_usage()
    result = agent.run_agent(system=prun.PRACTICE_PROMPT,
                             tools=practice_backend.tools(variant), query=query)
    prun.enrich(result, f"experiment_a:{variant}", query, limit)
    result["schema_variant"] = variant
    prun.report(result, query, limit)
    prun.save_result(f"experiment_a:{variant}", result)

    v = verdict(result, key)
    print(f"  перший інструмент: {v['first_tool']} (очікувався {v['expected_first']}) — "
          f"{'правильний' if v['first_tool_correct'] else 'НЕ той'}")
    if broke(v):
        print("  ЗЛАМАВСЯ:")
        for reason in why_broke(v):
            print(f"    - {reason}")
    else:
        print("  дефектів не знайдено")
    print()
    return {"result": result, "verdict": v, "spent": budget.spent_usd()}


def compare(runs: dict) -> None:
    print("=" * 70)
    print("ПОРІВНЯННЯ")
    print("=" * 70 + "\n")
    rows = [
        ("перший інструмент", lambda v: str(v["first_tool"])),
        ("перший хід правильний", lambda v: "так" if v["first_tool_correct"] else "НІ"),
        ("плутанина аргументів", lambda v: str(len(v["misrouted"])) if v["misrouted"] else "немає"),
        ("хибний період", lambda v: str(len(v["empty_period"])) if v["empty_period"] else "немає"),
        ("аргумент відхилено", lambda v: str(len(v["arg_errors"])) if v["arg_errors"] else "немає"),
        ("режим ланцюжка", lambda v: v["chain_mode"]),
        ("деталі отримано", lambda v: "так" if v["got_details"] else "НІ"),
        ("стан даних (не дефект)", lambda v: str(len(v["data_errors"])) if v["data_errors"] else "немає"),
        ("кроків", lambda v: str(v["turns"])),
        ("вартість", lambda v: f"${v['usd']:.4f}"),
        ("ВЕРДИКТ", lambda v: "ЗЛАМАВСЯ" if broke(v) else "упорався"),
    ]
    have = [x for x in VARIANTS if x in runs]
    print(f"  {'показник':<24}" + "".join(f"{x:<22}" for x in have))
    print("  " + "-" * (24 + 22 * len(have)))
    for label, fn in rows:
        print(f"  {label:<24}" + "".join(f"{fn(runs[x]['verdict']):<22}" for x in have))
    print()

    if len(have) == 2:
        n, t = runs["naive"]["verdict"], runs["tuned"]["verdict"]
        if broke(n) and not broke(t):
            print("  ВИСНОВОК: опис вирішив справу. Наївний зламався, виправлений — ні,")
            print("  а код, промпт і запит були в обох прогонах ідентичні.")
            print("  Що саме зламалось у наївному:")
            for reason in why_broke(n):
                print(f"    - {reason}")
        elif broke(n) and broke(t):
            print("  ВИСНОВОК: зламались обидва — опису тут замало, причина глибша.")
            print("  Це матеріал для челенджа B, а не для A.")
        elif not broke(n):
            print("  ВИСНОВОК: наївний опис теж упорався — цей запит пастки не спрацював.")
            print("  Чесний негативний результат; підганяти висновок не можна.")
        else:
            print("  ВИСНОВОК: виправлений опис зламався там, де наївний ні — регресія.")
    print()


def hunt(limit: float) -> int:
    """Ганяє НАЇВНИЙ варіант по всіх кандидатах і каже, які з них ламають агента.

    Полюємо лише наївним варіантом: якщо він не ламається, порівнювати нема з чим,
    і платити за другий прогін немає сенсу.
    """
    print("=" * 70)
    print("ПОЛЮВАННЯ — наївний опис проти всіх кандидатів")
    print("=" * 70 + "\n")
    show_descriptions("naive")

    found, spent = [], 0.0
    for key in CANDIDATES:
        query = query_of(key)
        state = budget.check(limit, extra_spent=spent)
        if not state["ok"]:
            print(f"  [{key}] ПРОПУЩЕНО — бюджет вичерпано\n")
            continue

        agent.reset_usage()
        result = agent.run_agent(system=prun.PRACTICE_PROMPT,
                                 tools=practice_backend.tools("naive"), query=query)
        prun.enrich(result, f"hunt:{key}", query, limit)
        result["schema_variant"] = "naive"
        prun.save_result(f"hunt:{key}", result)
        spent += budget.spent_usd()

        v = verdict(result, key)
        broken = broke(v)
        if broken:
            found.append(key)
        print(f"  [{key}] {'ЗЛАМАВСЯ' if broken else 'упорався'}")
        print(f"      запит:    «{query}»")
        print(f"      перший:   {v['first_tool']} (очікувався {v['expected_first']})")
        for reason in why_broke(v):
            print(f"      дефект:   {reason}")
        if v["data_errors"]:
            print(f"      стан даних (не дефект): "
                  f"{', '.join(f['error'] for f in v['data_errors'])}")
        print(f"      кроків: {v['turns']}   вартість: ${v['usd']:.4f}\n")

    print("-" * 70)
    if found:
        print(f"  Ламають наївний опис: {', '.join(found)}")
        print(f"  Далі: python -m practice.challenges.a_experiment --query {found[0]}")
    else:
        print("  Жоден кандидат не зламав наївний опис.")
        print("  Це результат, а не невдача: у цьому дизайні контракт несуть ІМЕНА")
        print("  інструментів і параметрів, а опис лише додає нюанси. Щоб опис став")
        print("  вирішальним, довелося б зробити імена нейтральними (tool_a / tool_b),")
        print("  але це вже інший експеримент — про імена, не про описи.")
    print(f"\n  Витрачено: ${spent:.4f} з ${limit:.4f}")
    print(f"  Збережено: {prun.RESULTS}")
    return 0


def rescore() -> int:
    """Переоцінити ВЖЕ ЗБЕРЕЖЕНІ прогони виправленим вимірювачем. Нуль викликів.

    Потрібно, бо вимірювач сам виявився дефектним, а платити за повторні прогони
    заради виправленої арифметики — марно: сирі trace вже лежать у JSON.
    """
    import json
    if not prun.RESULTS.exists():
        print("Немає збережених прогонів.")
        return 1
    stored = json.loads(prun.RESULTS.read_text(encoding="utf-8"))
    keys = sorted(k for k in stored if k.startswith("hunt:"))
    if not keys:
        print("Немає записів полювання. Спершу: --hunt")
        return 1

    print("=" * 70)
    print("ПЕРЕОЦІНКА збережених прогонів (нуль викликів до API)")
    print("=" * 70 + "\n")
    broken = []
    for full in keys:
        key = full.split(":", 1)[1]
        result = stored[full]
        # старі записи могли зберігатися до появи перевірки періоду
        result.setdefault("checks", {}).setdefault(
            "empty_period",
            checks.empty_period_probe(result.get("trace", []),
                                      practice_backend.find_shipments))
        v = verdict(result, key)
        if broke(v):
            broken.append(key)
        print(f"  [{key}] {'ЗЛАМАВСЯ' if broke(v) else 'упорався'}")
        print(f"      перший: {v['first_tool']} (очікувався {v['expected_first']})")
        for reason in why_broke(v):
            print(f"      дефект: {reason}")
        if v["data_errors"]:
            print(f"      стан даних (не дефект): "
                  f"{', '.join(f['error'] for f in v['data_errors'])}")
        print()

    print("-" * 70)
    if broken:
        print(f"  Справжні дефекти: {', '.join(broken)}")
        print(f"  Далі: python -m practice.challenges.a_experiment --query {broken[0]}")
    else:
        print("  Справжніх дефектів немає.")
    return 0


def main(argv: list) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if argv and argv[0] == "--list":
        print("\nЗапити-кандидати:\n")
        for key, spec in CANDIDATES.items():
            print(f"  {key}  (правильний перший хід: {spec['expects']})")
            print(f"    {spec['note']}")
            print(f"    «{spec['query']}»")
        print()
        return 0

    budget.ensure_model_priced()
    prun.register_tools()
    limit = float(os.getenv("PRACTICE_EXPERIMENT_BUDGET_USD",
                            DEFAULT_EXPERIMENT_BUDGET_USD))

    if argv and argv[0] == "--rescore":
        return rescore()

    if argv and argv[0] == "--hunt":
        print(f"\nЧелендж A · полювання · модель {prun.MODEL} · ліміт ${limit:.4f}\n")
        return hunt(limit)

    key = DEFAULT_CANDIDATE
    if argv and argv[0] == "--query":
        if len(argv) < 2:
            print("Після --query потрібен ключ. Перелік: --list")
            return 2
        key = argv[1]
    elif argv:
        print(f"Невідомий аргумент '{argv[0]}'. Див. --help")
        return 2

    if key not in CANDIDATES:
        print(f"Немає запиту '{key}'. Перелік: --list")
        return 2

    query = query_of(key)
    print(f"\nЧелендж A · опис = поведінка · модель {prun.MODEL} · ліміт ${limit:.4f}")
    print(f"Запит [{key}] (однаковий для обох): «{query}»\n")

    runs, spent = {}, 0.0
    for variant in VARIANTS:
        got = run_variant(variant, key, limit, spent)
        if got:
            runs[variant] = got
            spent += got["spent"]

    if runs:
        compare(runs)
    print(f"Витрачено: ${spent:.4f} з ${limit:.4f}")
    print(f"Збережено: {prun.RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
