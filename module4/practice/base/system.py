"""
ОСНОВА · система: маршрутизатор → спеціаліст → перевірки → передача людині.

Це платна точка входу для ОДНОГО запиту через мультиагентну систему. Порівняння
з одним агентом на всіх п'яти запитах робить base/compare.py; тут можна
роздивитися один маршрут докладно.

ЯК ХОДИТЬ ЗАПИТ

  1. Дешева модель класифікує запит у OBJECT, EXOTIC, WRAPPERS або GENERAL.
     Нерозпізнана відповідь маршрутизатора теж стає GENERAL — це запасний
     маршрут картки: система не падає і не вгадує, а йде найширшим шляхом.
  2. Обраний спеціаліст робить свій прогін run_agent зі своїми інструментами
     (хто що має і чому — у докстрингу base/team.py).
  3. Якщо тематичний спеціаліст шукав і ВСІ його пошуки повернулися порожніми,
     запит один раз переграється через GENERAL: вузький індекс міг просто не
     містити потрібного, і це видно з trace без жодного здогаду.
  4. Для WRAPPERS чернетку перевіряє критик (base/critic.py); для всіх маршрутів
     відповідь проходить безкоштовну звірку посилань із trace.
  5. Рішення про передачу людині ухвалює КОД за детермінованими ознаками
     результату — перелік нижче в decide(). Окремо від цього GENERAL може сам
     запросити передачу інструментом request_handoff — але це пауза, а не дія:
     запит лягає в чергу, агент каже, що збирається зробити, і передача
     стається лише після підтвердження окремою командою --confirm. Прийом той
     самий, що request_redirect / confirm_redirect у практиці модуля 1.

    python -m practice.base.system attrs          # сценарій із п'яти зафіксованих
    python -m practice.base.system "свій запит"   # довільний запит
    python -m practice.base.system --confirm      # підтвердити передачу людині, $0
    python -m practice.base.system --list         # перелік сценаріїв, $0
    прапорці: --lexical (пошук по словах), --rewrite (переписування бідного
    запиту), --live (живий сайт для EXOTIC, потребує challenges/live_fetch.py),
    --fast (спеціалісти, субагент і критик на дешевій моделі каскаду),
    --drop request_handoff (інструмент прибрано зі списку GENERAL — необов'язковий
    чекбокс другої картки, див. context/drop.py)
"""

import json
import os
import pathlib
import re
import sys
import time

from config import MAX_TURNS, MODEL_FAST
from core import agent as course_agent
from core import cost
from core.agent import USAGE, reset_usage, run_agent

from practice.base import critic, team
from practice.common import nform
from practice.base.queries import QUERIES

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
RESULTS = OUT / "system_results.json"

# Перша версія промпта описувала GENERAL як «більше однієї теми або жодну», і
# Haiku читала це надто широко: два поспіль чисто-WRAPPERS запити (український
# про String.prototype.replace і англійський про Number.prototype.toFixed)
# пішли в GENERAL — учетверо дорожчий маршрут. Тому тепер правило перевернуте:
# спершу спробуй назвати ОДНУ тему, і лише якщо не виходить — GENERAL.
ROUTER_PROMPT = (
    "Класифікуй запит про специфікацію ECMAScript в одну тему:\n"
    "OBJECT — тип Object як такий: атрибути властивостей, внутрішні методи і "
    "слоти, інваріанти, звичайні об'єкти.\n"
    "EXOTIC — екзотичні об'єкти: bound function, Array, String, Arguments, "
    "TypedArray, module namespace, immutable prototype, Proxy.\n"
    "WRAPPERS — обгортки Object, Boolean, Symbol, Number, String: їхні "
    "конструктори і БУДЬ-ЯКІ методи їхніх прототипів "
    "(Number.prototype.toFixed, String.prototype.replace тощо).\n"
    "GENERAL — якщо запит зачіпає ДВІ чи більше тем одразу (наприклад, згадує "
    "і Proxy, і метод обгортки чи інваріанти внутрішніх методів), або жодну "
    "з них.\n"
    "Питання про один метод одного об'єкта — тема цього об'єкта, не GENERAL. "
    "Питання, де взаємодіють об'єкти з РІЗНИХ тем, — GENERAL. "
    "Відповідай одним словом."
)

# Причини передачі людині: код → (українською, англійською).
REASONS = {
    "api_error":       ("збій сервісу моделі",
                        "the model service failed"),
    "turns_exhausted": ("агент не вклався в ліміт кроків",
                        "the agent ran out of steps"),
    "tool_error":      ("жоден виклик інструмента не вдався",
                        "every tool call failed"),
    "fabricated":      ("відповідь цитує джерело, якого пошук не повертав",
                        "the answer cites a source the search never returned"),
    "critic_failed":   ("чернетка не пройшла перевірку критика і після доопрацювання",
                        "the draft failed review even after one rework"),
    "research_empty":  ("дослідження не знайшло нічого по запиту",
                        "research found nothing for this question"),
}


def normalize_route(raw: str) -> str:
    """Нерозпізнана відповідь маршрутизатора стає GENERAL — запасний маршрут
    картки. Окремою функцією, щоб smoke перевіряв це без звернення до моделі."""
    return raw if raw in team.ROUTES else team.GENERAL


def route(query: str) -> tuple[str, str]:
    """Категорія від дешевої моделі і її сира відповідь (для журналу)."""
    from core.agent import ask
    raw = ask(ROUTER_PROMPT, query, max_tokens=10, fast=True).upper().strip(".")
    return normalize_route(raw), raw


def _all_searches_empty(result: dict) -> bool:
    """Спеціаліст шукав, і жоден пошук нічого не повернув."""
    trace = result.get("trace", [])
    return bool(trace) and all(
        not step.get("output", {}).get("found") for step in trace)


def _handoff_called(trace: list) -> bool:
    """Модель сама подбала про людину: передала або поставила запит на паузу."""
    return any(step.get("tool") in (team.HANDOFF_TOOL, team.REQUEST_TOOL)
               for step in trace)


def decide(result: dict) -> str | None:
    """Детермінована причина передачі людині, або None.

    Кожна ознака читається з результату прогону, а не з тексту відповіді:
    фраза моделі тут не важить нічого.
    """
    if result.get("outcome") == "api_error":
        return "api_error"
    if result.get("outcome") == "turns_exhausted":
        return "turns_exhausted"
    trace = result.get("trace", [])
    if trace and all(step.get("failed") for step in trace):
        return "tool_error"
    if result.get("citations", {}).get("fabricated"):
        return "fabricated"
    if result.get("critic") and not result["critic"]["ok"]:
        return "critic_failed"
    if result.get("routed_to") == team.GENERAL and not _handoff_called(trace):
        research = [s for s in trace if s.get("tool") == team.RESEARCH_TOOL]
        if research and not any(
                s["output"].get("found_anything") for s in research):
            return "research_empty"
    return None


def _ukrainian(text: str) -> bool:
    return bool(re.search(r"[а-щьюяіїєґ]", text.lower()))


# Причини діляться на два роди, і поводяться вони по-різному.
# Збої самої системи (api_error, вичерпані кроки, провалені інструменти,
# зіпсовані посилання) передаються людині ОДРАЗУ: питати нема про що, прогін
# уже зламався. А research_empty — це не збій, а рішення «у наших документах
# цього немає, віддаю людині», тобто саме та незворотна дія, перед якою картка
# вимагає паузу: система каже, що збирається зробити, ставить запит у чергу і
# чекає підтвердження командою --confirm. Модельний request_handoff кладе
# запити в ту саму чергу.
PAUSED_REASONS = {"research_empty"}


def apply_handoff(result: dict, query: str, reason: str) -> dict:
    """Завершує маршрут: збій — передачею людині, рішення — паузою перед нею.
    Обидві гілки користуються тими самими заглушками, що й модель, — заявки
    і запити йдуть в одні журнали."""
    uk, en = REASONS[reason]
    if reason in PAUSED_REASONS:
        req = team.request_handoff(query, uk)
        result["handoff"] = {"request_id": req["request_id"], "reason": reason,
                             "explain": uk, "by": "pipeline", "pending": True}
        # Відмова називає межу компетенції, а не просто відсутність рядка в
        # документах: «не знайшов» читається як «пошукай ще», а «це не моя
        # тема» — як відповідь. Далі — куди піти по відповідь самому і як
        # дістатися живої людини.
        if _ukrainian(query):
            result["answer"] = (
                "Я довідник зі специфікації ECMAScript, і тільки з неї: у "
                "кулінарії, географії чи будь-якій іншій темі я не спеціаліст, "
                "а в самій специфікації працюю лише з вивантаженими розділами. "
                f"На це питання відповіді в них немає ({uk}).\n"
                "Повний текст специфікації опубліковано тут: "
                "https://tc39.es/ecma262/\n"
                f"Якщо потрібна жива людина — я поставив запит на передачу "
                f"({req['request_id']}). Передача станеться лише після "
                "підтвердження командою python -m practice.base.system "
                "--confirm; можна натомість перефразувати питання.")
        else:
            result["answer"] = (
                "I am a reference assistant for the ECMAScript specification and "
                "nothing else: I am not a specialist in cooking, geography or any "
                "other field, and within the specification I work only from the "
                f"sections available to me. They do not answer this ({en}).\n"
                "The whole specification is published at https://tc39.es/ecma262/\n"
                f"If you need a person, I queued a handover request "
                f"({req['request_id']}). It happens only after you confirm with "
                "python -m practice.base.system --confirm; rephrasing the question "
                "is also an option.")
        return result

    ticket = team.handoff_to_human(query, uk)
    result["handoff"] = {"ticket": ticket["ticket"], "reason": reason,
                         "explain": uk, "by": "pipeline"}
    if _ukrainian(query):
        result["answer"] = (f"Передаю питання людині — {uk}. "
                            f"Заявка: {ticket['ticket']}. "
                            "Автоматичної відповіді не буде.")
    else:
        result["answer"] = (f"Handing this question to a human reviewer — {en}. "
                            f"Ticket: {ticket['ticket']}. "
                            "No automated answer follows.")
    return result


def run_system(query: str, live: bool = False) -> dict:
    """Повний маршрут одного запиту. Повертає result курсового формату,
    доповнений ключами routed_to, citations, critic, handoff, fallback_from."""
    team.register()
    extra = None
    addon = ""
    if live:
        from practice.challenges import live_fetch
        live_fetch.register()
        extra = [live_fetch.SCHEMA]
        addon = live_fetch.PROMPT_ADDON

    routed, raw = route(query)

    def _run(r: str) -> dict:
        out = run_agent(system=team.prompt_for_route(r) + (addon if r == "EXOTIC" else ""),
                        tools=team.tools_for_route(
                            r, extra if r == "EXOTIC" else None),
                        query=query)
        out["routed_to"] = r
        out["router_raw"] = raw
        return out

    result = _run(routed)

    if routed != team.GENERAL and _all_searches_empty(result):
        retry = _run(team.GENERAL)
        retry["fallback_from"] = routed
        result = retry

    if result["routed_to"] == "WRAPPERS":
        critic.run_critic(result, team.PROMPTS["WRAPPERS"], query)
    if "citations" not in result:
        result["citations"] = critic.check_citations(result["answer"],
                                                     result["trace"])
    if _handoff_called(result["trace"]):
        result["handoff"] = {"by": "model"}

    reason = decide(result)
    if reason:
        apply_handoff(result, query, reason)
    return result


def report(result: dict, query: str) -> None:
    routed = result["routed_to"]
    if result.get("fallback_from"):
        routed = f"{result['fallback_from']} → порожньо → {routed}"
    print(f"  запит:        «{query}»")
    print(f"  маршрут:      {routed}  (роутер відповів: {result.get('router_raw', '?')})")
    print(f"  outcome:      {result['outcome']}  ·  кроків: {result.get('turns', '—')}"
          f"  ·  {result.get('elapsed_sec', '—')} с")

    for step in result.get("trace", []):
        out = step["output"]
        if step["tool"] == team.RESEARCH_TOOL:
            mark = "знайшов" if out.get("found_anything") else "порожньо"
            print(f"  дослідження:  «{step['input'].get('topic', '')}» → {mark}, "
                  f"пошуків: {out.get('searches', 0)}")
        elif step["tool"] == team.HANDOFF_TOOL:
            print(f"  до людини:    {out.get('ticket', '?')} — "
                  f"{step['input'].get('reason', '')}")
        elif step["tool"] == team.REQUEST_TOOL:
            print(f"  пауза:        {out.get('request_id', '?')} — "
                  f"{step['input'].get('reason', '')}; чекає на --confirm")
        else:
            ids = ", ".join(p["id"] for p in out.get("passages", [])) or "—"
            print(f"  пошук:        «{step['input'].get('query', '')}» "
                  f"→ {out.get('found', 0)}: {ids}")
            if out.get("rewritten_query"):
                verdict = ("взято другий набір" if out.get("rewrite_used")
                           else "лишився перший")
                print(f"  переписано:   «{out['rewritten_query']}» → {verdict}")

    cit = result.get("citations", {})
    if cit.get("fabricated"):
        print(f"  посилання:    ВИГАДАНІ: {', '.join(cit['fabricated'])}")
    elif cit.get("cited"):
        print(f"  посилання:    {len(cit['cited'])} шт., усі є в trace")
    if result.get("critic"):
        c = result["critic"]
        print(f"  критик:       ok={c['ok']}  доопрацювання: "
              f"{'було' if c['revised'] else 'не знадобилося'}")
    if result.get("handoff"):
        print(f"  передача:     {result['handoff']}")

    print("  відповідь:")
    for line in result["answer"].splitlines():
        print(f"    {line}")

    c = cost.usd(USAGE["by_model"])
    print(f"  вартість:     ${c:.4f}  ({USAGE['calls']} {nform(USAGE['calls'], 'виклик', 'виклики', 'викликів')}, "
          f"{USAGE['in']} in / {USAGE['out']} out)")


def save_result(key: str, record: dict) -> None:
    """Зливає запис у out/system_results.json — механізм практики модуля 2:
    файл читається цілим, запис лягає під ключем сценарію, решта лишається."""
    OUT.mkdir(exist_ok=True)
    stored = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    stored[key] = record
    RESULTS.write_text(json.dumps(stored, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def confirm(argv: list[str]) -> int:
    """Підтвердження передачі людині. $0: жодного звернення до моделей."""
    entry = team.confirm_handoff()
    if entry is None:
        print("Черга порожня: жоден запит на передачу людині не чекає підтвердження.")
        return 1
    print(f"Підтверджено {entry['id']}: заявка {entry['ticket']}.")
    print(f"  питання:  «{entry['question']}»")
    print(f"  причина:  {entry['reason']}")
    return 0


def main(argv: list[str]) -> int:
    if "--confirm" in argv:
        return confirm(argv)
    if "--list" in argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        for name, q in QUERIES.items():
            print(f"  {name:8} {q['kind']}\n           «{q['query']}»")
        return 0

    if "--lexical" in argv:
        os.environ["PRACTICE_RETRIEVER"] = "lexical"
    if "--rewrite" in argv:
        os.environ["PRACTICE_REWRITE"] = "1"
    live = "--live" in argv
    # Значення після --drop — імена інструментів, не запит.
    dropped_arg = None
    if "--drop" in argv:
        dropped_arg = argv[argv.index("--drop") + 1]
        os.environ[team.DROP_ENV] = dropped_arg
    fast = "--fast" in argv
    if fast:
        team.use_fast_model()

    positional = [a for a in argv if not a.startswith("-") and a != dropped_arg]
    raw = positional[0] if positional else "attrs"
    scenario = raw if raw in QUERIES else "custom"
    query = QUERIES[raw]["query"] if raw in QUERIES else raw

    dropped = sorted(team.dropped_tools())
    print(f"── Практика М4 · система · сценарій: {scenario} · {course_agent.MODEL} + "
          f"{MODEL_FAST} · MAX_TURNS={MAX_TURNS}"
          + (f" · без {', '.join(dropped)}" if dropped else "") + " ──")

    team.register()
    started = time.time()
    reset_usage()
    result = run_system(query, live=live)
    result.update(scenario=scenario, query=query,
                  pipeline_sec=round(time.time() - started, 2),
                  cost_usd=cost.usd(USAGE["by_model"]),
                  cost_breakdown=cost.breakdown(USAGE["by_model"]),
                  model=course_agent.MODEL, dropped=dropped)
    report(result, query)
    # Штатний прогін зберігається під ключем system:<сценарій>, як і раніше.
    # Прогін з --fast або --drop — під власним префіксом, щоб не лягти поверх
    # базового запису; довільний запит у такому прогоні теж зберігається, з
    # датою в ключі, щоб не перекрити попередній довільний.
    prefix = "system" + ("-fast" if fast else "") + ("-drop" if dropped else "")
    if scenario != "custom":
        save_result(f"{prefix}:{scenario}", result)
        print(f"  збережено:    {RESULTS}")
    elif prefix != "system":
        key = f"{prefix}:custom-{time.strftime('%Y%m%d-%H%M%S')}"
        save_result(key, result)
        print(f"  збережено:    {RESULTS} під ключем {key}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
