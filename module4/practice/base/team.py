"""
ОСНОВА · команда спеціалістів: хто існує, що читає, які інструменти дістає і чому.

Це відповідь на головний пункт картки — «різні інструменти й різні права, з
поясненням, чому саме такі». У курсовому модулі 4 профілі відрізняються лише
текстом промпта: всі чотири агенти викликають tools_for(4) і можуть однаково
все. Тут права різняться реально, і в кожної різниці є причина.

ЯК ПОДІЛЕНО ДОКУМЕНТИ

Не по одному документу на спеціаліста: розділи специфікації різняться за
розміром у тридцять разів (1570 символів проти 52257), і спеціаліст з одного
малого розділу був би порожньою посадою. Поділ іде по трьох родинах
порівнюваної ваги, слідом за структурою самої специфікації:

    OBJECT    документи 01–05: тип Object, атрибути властивостей, внутрішні
              методи і слоти, їхні інваріанти, звичайні об'єкти (6.1.7, 10.1)
    EXOTIC    документи 06–13: вісім видів екзотичних об'єктів і Proxy
              (10.4.1–10.4.7, 10.5)
    WRAPPERS  документи 14–18: конструктори-обгортки Object, Boolean, Symbol,
              Number, String та їхні прототипи (20.1–22.1)

Четвертий маршрут — GENERAL — не родина, а запасний вихід: туди йдуть запити,
що зачіпають кілька родин одразу, і запити, тему яких маршрутизатор не впізнав.

ЧОМУ ПРАВА САМЕ ТАКІ

- Тематичні спеціалісти (OBJECT, EXOTIC, WRAPPERS) мають лише вузький пошук по
  документах своєї родини. Вужчий індекс — це не обмеження заради обмеження:
  фрагменти чужої родини не потрапляють у видачу, тож запит про Proxy не
  отримає у відповідь таблицю з розділу про String лише тому, що вона схожа на
  все підряд.
- WRAPPERS додатково проходить перевірку критиком (base/critic.py). Саме в цій
  родині найбільший обсяг тексту і найдовші перелічувальні розділи — тут
  найлегше процитувати фрагмент, якого пошук не повертав.
- EXOTIC — єдиний, кому за прапорцем --live дістається живий сайт специфікації
  (challenges/live_fetch.py). Родина найскладніша, і питання про екзотичні
  об'єкти найчастіше виходять за межі вивантажених розділів. Без прапорця
  інструмента немає навіть у списку схем.
- GENERAL не має прямого пошуку взагалі. Чорнову роботу — кілька пошуків,
  зіставлення фрагментів — робить субагент research_topic в окремому контексті,
  а GENERAL бачить лише його підсумок. Це і є необов'язковий пункт картки
  «субагент із власним контекстом»: міжтемний запит вимагає найбільше пошуків,
  і без субагента всі проміжні фрагменти осідали б у контексті дорогої моделі.
  І лише GENERAL має handoff_to_human: він — кінець маршруту, після нього
  передати запит більше нікому.

РЕЄСТРАЦІЯ І МЕЖА З КУРСОМ

core/agent.py шукає реалізації інструментів у глобальному словнику IMPL з
domain/backend.py: одне ім'я — одна реалізація на процес. Тому «той самий пошук,
але звужений» не може зватися search_docs у чотирьох екземплярів — у кожного
спеціаліста своє ім'я інструмента, а register() дописує реалізації в IMPL лише
після перевірки, що жодне ім'я не збігається з курсовим. CAPABILITIES і
tools_for() не змінюються; курсові файли не зачеплені.
"""

import json
import os
import pathlib

from domain import backend as course_backend

from practice.common import search as psearch
from practice.common.corpus import load_passages
from practice.common.lexical import LexicalIndex
from practice.common.vectors import VectorIndex

# Знімок курсових імен до будь-якої реєстрації: звірятися треба саме з ним,
# інакше повторний виклик register() знайшов би «збіг» із власним іменем.
_COURSE_TOOL_NAMES = frozenset(course_backend.IMPL)

GENERAL = "GENERAL"

# Родина → номери документів (префікс імені файла в practice/docs/).
FAMILIES = {
    "OBJECT":   range(1, 6),
    "EXOTIC":   range(6, 14),
    "WRAPPERS": range(14, 19),
}

ROUTES = ("OBJECT", "EXOTIC", "WRAPPERS", GENERAL)

TOOL_NAMES = {
    "OBJECT":   "search_object_docs",
    "EXOTIC":   "search_exotic_docs",
    "WRAPPERS": "search_wrapper_docs",
    GENERAL:    "search_docs",
}

RESEARCH_TOOL = "research_topic"
HANDOFF_TOOL = "handoff_to_human"
REQUEST_TOOL = "request_handoff"

# Черга запитів на передачу людині — стан паузи між двома запусками CLI.
PENDING_FILE = pathlib.Path(__file__).resolve().parent.parent / "out" / "pending_handoff.json"


def doc_number(doc_id: str) -> int:
    """Номер документа з імені файла: «07-array-exotic-objects» → 7."""
    return int(doc_id[:2])


_passages = None


def all_passages():
    global _passages
    if _passages is None:
        _passages = load_passages()
    return _passages


def passages_for(family: str):
    """Фрагменти родини. GENERAL і субагент працюють по повному набору.

    Підмножина береться фільтром уже дедуплікованого списку, і це важливо:
    документи 02–04 повторюють шматки документа 01 слово в слово, тому їхні
    спільні фрагменти живуть під ідентифікаторами документа 01. Обидва боки
    цього злиття лежать у родині OBJECT, тож фільтр по родині нічого не губить.
    """
    if family == GENERAL:
        return all_passages()
    numbers = FAMILIES[family]
    return [p for p in all_passages() if doc_number(p.doc_id) in numbers]


_RETRIEVERS = {"vector": VectorIndex, "lexical": LexicalIndex}
_indexes: dict = {}


def index_for(family: str):
    """Індекс родини, один на процес. Вид пошуку — зі змінної PRACTICE_RETRIEVER.

    У кожної підмножини свій кеш векторів: відбиток рахується з переданого
    списку фрагментів, тож файли в practice/index/ не перетинаються.
    """
    kind = os.getenv("PRACTICE_RETRIEVER", "vector")
    if kind not in _RETRIEVERS:
        raise SystemExit(f"Невідомий пошук '{kind}'. Доступні: "
                         f"{', '.join(sorted(_RETRIEVERS))}")
    key = (family, kind)
    if key not in _indexes:
        _indexes[key] = _RETRIEVERS[kind](passages=passages_for(family))
    return _indexes[key]


# ── схеми ─────────────────────────────────────────────────────

def _schema(name, desc, props, required):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props,
                             "required": required}}


_QUERY_PROP = {"query": {"type": "string",
                         "description": "What to look for, in your own words, "
                                        "e.g. 'replacing a substring inside a string'"}}

_SEARCH_TAIL = (" Call it before stating anything about the specification. Ask one "
                "thing at a time; if a question has several parts, search several times.")

SCHEMAS = {
    TOOL_NAMES["OBJECT"]: _schema(
        TOOL_NAMES["OBJECT"],
        "Searches excerpts of the ECMAScript specification about the Object type "
        "itself: property attributes, object internal methods and internal slots, "
        "invariants of the essential internal methods, and ordinary objects "
        "(sections 6.1.7 and 10.1)." + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    TOOL_NAMES["EXOTIC"]: _schema(
        TOOL_NAMES["EXOTIC"],
        "Searches excerpts of the ECMAScript specification about exotic objects: "
        "bound functions, Array, String, Arguments, TypedArray, module namespaces, "
        "immutable prototypes (sections 10.4.1-10.4.7) and Proxy (section 10.5)."
        + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    TOOL_NAMES["WRAPPERS"]: _schema(
        TOOL_NAMES["WRAPPERS"],
        "Searches excerpts of the ECMAScript specification about the wrapper "
        "objects: the Object, Boolean, Symbol, Number and String constructors and "
        "their prototypes (sections 20.1, 20.3, 20.4, 21.1, 22.1)." + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    TOOL_NAMES[GENERAL]: _schema(
        TOOL_NAMES[GENERAL],
        "Searches all available excerpts of the ECMAScript specification: the "
        "Object type, exotic objects including Proxy, and the Object, Boolean, "
        "Symbol, Number and String wrapper objects." + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    RESEARCH_TOOL: _schema(
        RESEARCH_TOOL,
        "Delegates one research topic to an assistant that searches the ECMAScript "
        "specification excerpts and returns a short summary with citations. Give it "
        "ONE topic per call; for a question with several parts, call it once per part.",
        {"topic": {"type": "string",
                   "description": "One self-contained thing to research, phrased as "
                                  "a question or a topic, not the whole user query"}},
        ["topic"]),
    REQUEST_TOOL: _schema(
        REQUEST_TOOL,
        "Announces an irreversible action: handing the question over to a human "
        "reviewer. It does NOT hand anything over by itself — it records the "
        "request and pauses until the user confirms. Use it when research found "
        "nothing that answers the question, or when what was found does not "
        "actually answer it. After calling it, tell the user exactly what you are "
        "about to do and that it happens only after their confirmation; do not "
        "attempt an answer of your own.",
        {"question": {"type": "string", "description": "The user's question, verbatim"},
         "reason": {"type": "string", "description": "Why a human is needed, briefly"}},
        ["question", "reason"]),
}


# ── реалізації ────────────────────────────────────────────────

def _searcher(family: str):
    def impl(query: str) -> dict:
        return psearch.search(index_for(family), query)
    return impl


# Журнал передач людині. Номер заявки — лічильник, а не hash(): однаковий
# сценарій у двох прогонах дає однаковий номер, і дослівні блоки в README
# лишаються відтворюваними.
HANDOFF_LOG: list = []


def handoff_to_human(question: str, reason: str) -> dict:
    ticket = f"HITL-{len(HANDOFF_LOG) + 1:05d}"
    HANDOFF_LOG.append({"ticket": ticket, "question": question, "reason": reason})
    return {"handoff": True, "ticket": ticket, "reason": reason,
            "note": "Queued for a human reviewer. No automated answer follows."}


RESEARCH_PROMPT = (
    "You are a research assistant working over excerpts of the ECMAScript "
    "specification. Answer the research topic you were given using ONLY the "
    "search_docs tool; search as many times as the topic needs.\n"
    "Return a compact summary of what the excerpts actually say, in English, "
    "citing every claim with the id shown in brackets, e.g. "
    "[18-string-objects#22.1.3.19], with ids kept exactly as returned.\n"
    "If the excerpts do not cover the topic, reply exactly with what they do "
    "cover and state plainly that the topic itself is not covered. Never fill "
    "the gap from your own knowledge."
)


def research_topic(topic: str) -> dict:
    """Субагент із власним контекстом. Чорнова робота — пошуки, зіставлення
    фрагментів — відбувається в окремому виклику run_agent з власною історією
    повідомлень; назовні повертається лише підсумок. Фрагменти, які субагент
    прочитав, у контекст GENERAL не потрапляють ніколи.

    Імпорт core.agent захований у функцію, щоб безкоштовні перевірки smoke
    працювали без ключа в .env (патерн із common/rewrite.py).
    """
    from core.agent import run_agent

    result = run_agent(system=RESEARCH_PROMPT,
                       tools=[SCHEMAS[TOOL_NAMES[GENERAL]]], query=topic)
    found = any(step["output"].get("found") for step in result["trace"])
    return {"summary": result["answer"], "outcome": result["outcome"],
            "searches": len(result["trace"]), "found_anything": found}


def _load_requests(path: pathlib.Path) -> list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _save_requests(path: pathlib.Path, entries: list) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def request_handoff(question: str, reason: str, path: pathlib.Path = None) -> dict:
    """Пауза перед незворотною дією — необов'язковий пункт картки.

    Сама по собі нічого не передає: запис лягає в чергу зі станом pending, і
    маршрут закінчується словами агента про те, що він ЗБИРАЄТЬСЯ зробити.
    Передача стається лише коли людина підтвердить окремою командою
    (python -m practice.base.system --confirm) — прийом той самий, що
    request_redirect / confirm_redirect у практиці модуля 1.
    """
    path = path or PENDING_FILE
    entries = _load_requests(path)
    rid = f"REQ-{len(entries) + 1:05d}"
    entries.append({"id": rid, "question": question, "reason": reason,
                    "status": "pending"})
    _save_requests(path, entries)
    return {"pending": True, "request_id": rid,
            "note": "Nothing was handed over yet. Tell the user what you are "
                    "about to do — queue the question for a human reviewer — and "
                    "that it happens only after they run: "
                    "python -m practice.base.system --confirm"}


def confirm_handoff(path: pathlib.Path = None) -> dict | None:
    """Підтвердження останнього запиту з черги. Повертає None, якщо черга порожня.

    Запис не видаляється, а переводиться в стан confirmed із номером заявки:
    історія запитів лишається в файлі цілою.
    """
    path = path or PENDING_FILE
    entries = _load_requests(path)
    pending = [e for e in entries if e["status"] == "pending"]
    if not pending:
        return None
    entry = pending[-1]
    ticket = handoff_to_human(entry["question"], entry["reason"])
    entry["status"] = "confirmed"
    entry["ticket"] = ticket["ticket"]
    _save_requests(path, entries)
    return dict(entry)


PRACTICE_IMPL = {
    TOOL_NAMES["OBJECT"]:   _searcher("OBJECT"),
    TOOL_NAMES["EXOTIC"]:   _searcher("EXOTIC"),
    TOOL_NAMES["WRAPPERS"]: _searcher("WRAPPERS"),
    TOOL_NAMES[GENERAL]:    _searcher(GENERAL),
    RESEARCH_TOOL:          research_topic,
    HANDOFF_TOOL:           handoff_to_human,
    REQUEST_TOOL:           request_handoff,
}


def register() -> None:
    """Додає реалізації практики в курсовий реєстр IMPL. Ідемпотентна."""
    collisions = sorted(set(PRACTICE_IMPL) & _COURSE_TOOL_NAMES)
    if collisions:
        raise RuntimeError(
            f"Ім'я інструмента практики збігається з курсовим: {', '.join(collisions)}. "
            "IMPL.update підмінив би курсову реалізацію мовчки. Перейменуйте інструмент."
        )
    course_backend.IMPL.update(PRACTICE_IMPL)


# ── промпти ───────────────────────────────────────────────────

_RULES = (
    "\n\nRules you must follow:\n"
    "1. Use your tools before you answer. Never state a fact about the "
    "specification that did not come back from a tool in this conversation.\n"
    "2. If nothing returned answers the question, say plainly that the excerpts "
    "available to you do not cover it, and name what they do cover. Do not answer "
    "from your own knowledge of JavaScript, do not guess.\n"
    "3. Cite every claim with the id shown in brackets, e.g. "
    "[18-string-objects#22.1.3.19]. Keep ids exactly as returned: never translate, "
    "shorten or invent them.\n"
    "4. Answer in the language the question was asked in: a Ukrainian question "
    "gets a fluent Ukrainian answer, an English question an English one. "
    "Translating what the excerpts say is fine; adding facts of your own is not.\n"
    "5. Plain prose, no Markdown tables, no emoji."
)

PROMPTS = {
    "OBJECT": (
        "You are the specialist for the ECMAScript Object type itself: property "
        "attributes, object internal methods and internal slots, their invariants, "
        "and ordinary objects. Your search tool covers only those sections; "
        "questions outside them are not yours to answer." + _RULES),
    "EXOTIC": (
        "You are the specialist for ECMAScript exotic objects: bound functions, "
        "Array, String, Arguments, TypedArray, module namespaces, immutable "
        "prototypes, and Proxy. Your search tool covers only those sections; "
        "questions outside them are not yours to answer." + _RULES),
    "WRAPPERS": (
        "You are the specialist for the ECMAScript wrapper objects: the Object, "
        "Boolean, Symbol, Number and String constructors and their prototypes. "
        "Your search tool covers only those sections; questions outside them are "
        "not yours to answer." + _RULES),
    GENERAL: (
        "You coordinate research over excerpts of the ECMAScript specification. "
        "You have no search of your own: delegate the draft work to the "
        "research_topic tool, one self-contained topic per call — a question with "
        "several parts means several calls. Compose your answer strictly from the "
        "summaries the tool returns, keeping their citations. If research finds "
        "nothing that answers the question, or what it found does not actually "
        "answer it, call request_handoff: it only ANNOUNCES the handover, so tell "
        "the user what is about to happen and that it waits for their "
        "confirmation — never improvise an answer instead." + _RULES),
}


def tools_for_route(route: str, extra: list | None = None) -> list:
    """Список схем для run_agent(tools=...). Курсові інструменти сюди не входять:
    поштовий бекенд до специфікації ECMAScript стосунку не має.

    `extra` — місце для схем челенджів (fetch_spec під --live); базова розкладка
    прав від цього не змінюється.
    """
    if route == GENERAL:
        base = [SCHEMAS[RESEARCH_TOOL], SCHEMAS[REQUEST_TOOL]]
    else:
        base = [SCHEMAS[TOOL_NAMES[route]]]
    return base + list(extra or [])
