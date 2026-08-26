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
import re
import pathlib

from domain import backend as course_backend

from practice.common import search as psearch
from practice.common.corpus import DOC_SET, load_passages
from practice.common.lexical import LexicalIndex
from practice.common.vectors import VectorIndex

# Знімок курсових імен до будь-якої реєстрації: звірятися треба саме з ним,
# інакше повторний виклик register() знайшов би «збіг» із власним іменем.
_COURSE_TOOL_NAMES = frozenset(course_backend.IMPL)

GENERAL = "GENERAL"

# Родина → номери документів (префікс імені файла в теці документів).
#
# Розкладка залежить від набору, бо номер документа означає в наборах різне. У
# «core» вісімнадцять файлів вирізані з околиці sec-object-type і пронумеровані
# підряд, тож родини ділять їх повністю й без перетинів. У «full» номер файла
# збігається з номером розділу специфікації, і три родини покривають уже не всю
# специфікацію, а свої розділи в ній: решта — граматика, вирази, інструкції,
# колекції, обіцянки, додатки — лишається маршрутові GENERAL, який бачить усе.
_FAMILIES_BY_SET = {
    "core": {
        "OBJECT":   tuple(range(1, 6)),    # тип Object, атрибути, внутрішні методи, інваріанти
        "EXOTIC":   tuple(range(6, 14)),   # екзотичні об'єкти і Proxy
        "WRAPPERS": tuple(range(14, 19)),  # обгортки Object/Boolean/Symbol/Number/String
    },
    "full": {
        "OBJECT":   (6, 7),                # 6 Data Types and Values, 7 Abstract Operations
        "EXOTIC":   (10, 28),              # 10 Ordinary and Exotic Objects, 28 Reflection
        "WRAPPERS": (19, 20, 21, 22),      # Global, Fundamental, Numbers and Dates, Text Processing
    },
}
# «suite» — та сама 262 плюс ECMA-402/404/414 і документи довкола 402.
# Родини ті самі, що у «full»: документи з префіксом стандарту (402-…, 404-…,
# 414-…) і документи довкола 402 (rfc…, uax…, uts…) номера документа не мають
# (doc_number дає 0) і дістаються лише маршрутові GENERAL.
_FAMILIES_BY_SET["suite"] = _FAMILIES_BY_SET["full"]

FAMILIES = _FAMILIES_BY_SET[DOC_SET]

ROUTES = ("OBJECT", "EXOTIC", "WRAPPERS", GENERAL)

TOOL_NAMES = {
    "OBJECT":   "search_object_docs",
    "EXOTIC":   "search_exotic_docs",
    "WRAPPERS": "search_wrapper_docs",
    GENERAL:    "search_docs",
}

RESEARCH_TOOL = "research_topic"
# Рядок, яким спеціаліст віддає питання, що виходить за його розділи;
# base/system.py ловить його детерміновано і повторює запит через GENERAL.
HANDOVER_LINE = "HANDOVER: GENERAL"
# Бюджет субагента: досліджень на одне питання і ходів на одне дослідження.
# Без меж дешева модель робила дев'ять досліджень по 10-14 пошуків на одну
# задачу (55 викликів, $0.32) — і половина тем дублювала одна одну.
# Ходів — чотири: дешева модель робить по 2-3 пошуки за хід, і за три ходи
# жодного разу не дійшла до підсумку (усі чотири дослідження прогону 19:53
# скінчилися turns_exhausted). Промпт велить шукати не більше двох раундів,
# четвертий хід — запас; якщо підсумку все одно немає, його замінюють уривки.
RESEARCH_BUDGET = 4
RESEARCH_TURNS = 4
EXCERPT_LIMIT = 6        # уривків у замінному підсумку
EXCERPT_CHARS = 500      # знаків з кожного уривка
_research_used = {"n": 0}


def reset_research() -> None:
    """Новий лічильник досліджень — на початку кожного прогону маршруту."""
    _research_used["n"] = 0
HANDOFF_TOOL = "handoff_to_human"
REQUEST_TOOL = "request_handoff"

# Черга запитів на передачу людині — стан паузи між двома запусками CLI.
PENDING_FILE = pathlib.Path(__file__).resolve().parent.parent / "out" / "pending_handoff.json"


_DOC_NUMBER = re.compile(r"^(\d{2})-")


def doc_number(doc_id: str) -> int:
    """Номер документа з імені файла: «07-array-exotic-objects» → 7. Документи
    інших стандартів («402-08-intl-object») номера не мають — 0, поза родинами."""
    m = _DOC_NUMBER.match(doc_id)
    return int(m.group(1)) if m else 0


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


def warm_search(route: str = GENERAL) -> None:
    """Готує пошук маршруту до першого запиту: збирає індекс і робить один
    пробний пошук, який завантажує модель ембедингів. Без цього перший
    справжній пошук мовчить хвилину-дві на завантаженні моделі — і ця тиша
    видається за роздуми над реплікою. Нуль звернень до моделей Anthropic."""
    index_for(route).scores("ECMAScript", 1)


_RETRIEVERS = {"vector": VectorIndex, "lexical": LexicalIndex}

# Сховище в Qdrant підключається на вимогу: сам його імпорт нічого не робить,
# але створення індексу вимагає піднятого сервера. Тому імпорт живе всередині
# функції — так само, як імпорт core.agent у common/rewrite.py.
_LAZY_RETRIEVERS = {"qdrant": ("practice.challenges.qdrant_store", "QdrantIndex")}

# «auto» — не окреме сховище, а правило вибору між двома наявними.
AUTO = "auto"

_indexes: dict = {}
_storage_said: set = set()


def _say_once(message: str) -> None:
    """Один рядок на процес про кожне сховище: чотири маршрути беруть індекси
    по черзі, і без цього те саме повідомлення друкувалося б чотири рази."""
    if message not in _storage_said:
        _storage_said.add(message)
        print(message)


def _auto_index(family: str, passages: list):
    """Qdrant, якщо він доступний; інакше документи.

    Правило живе в challenges/qdrant_store.try_open: сервер є і потрібні
    фрагменти в ньому — беремо сервер; сервера немає — беремо документи; сервер
    є, а фрагментів немає — заливаємо їх туди з документів. Вибір друкується
    рядком: мовчазна підміна сховища — саме те, через що потім не сходяться
    числа. Разом із відмовою друкується команда підняття, щоб її не доводилося
    шукати в документації.
    """
    try:
        from practice.challenges import qdrant_store
        index, why = qdrant_store.try_open(passages)
    except Exception as e:
        index, why = None, f"{type(e).__name__}: {e}"
    if index is not None:
        _say_once(f"  сховище:      Qdrant — {why}")
        return index
    _say_once(f"  сховище:      документи ({why})\n"
              f"                підняти базу: docker compose up -d   або   "
              f"python -m practice.challenges.qdrant_store --up")
    return VectorIndex(passages=passages)


def index_for(family: str):
    """Індекс родини, один на процес. Вид пошуку — зі змінної PRACTICE_RETRIEVER:
    «auto» за замовчуванням (Qdrant, якщо доступний, інакше документи), «vector» —
    завжди матриця в пам'яті, «qdrant» — лише сервер, без запасного шляху,
    «lexical» — пошук по словах.

    У кожної підмножини свій кеш векторів: відбиток рахується з переданого
    списку фрагментів, тож файли в practice/index/ не перетинаються. У Qdrant
    те саме робиться інакше — усі фрагменти лежать однією колекцією, а підмножина
    родини задається фільтром по номеру документа на боці сервера.
    """
    kind = os.getenv("PRACTICE_RETRIEVER", AUTO)
    known = set(_RETRIEVERS) | set(_LAZY_RETRIEVERS) | {AUTO}
    if kind not in known:
        raise SystemExit(f"Невідомий пошук '{kind}'. Доступні: "
                         f"{', '.join(sorted(known))}")
    key = (family, kind)
    if key not in _indexes:
        passages = passages_for(family)
        if kind == AUTO:
            _indexes[key] = _auto_index(family, passages)
        elif kind in _RETRIEVERS:
            _indexes[key] = _RETRIEVERS[kind](passages=passages)
        else:
            import importlib
            module_name, attr = _LAZY_RETRIEVERS[kind]
            cls = getattr(importlib.import_module(module_name), attr)
            _indexes[key] = cls(passages=passages)
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

# Опис інструмента мусить називати те, що в ньому справді лежить: модель обирає
# інструмент саме за цим текстом, і опис, успадкований від іншого набору
# документів, відправляв би її не туди.
_DESCRIPTIONS = {
    "core": {
        "OBJECT": "Searches excerpts of the ECMAScript specification about the Object "
                  "type itself: property attributes, object internal methods and "
                  "internal slots, invariants of the essential internal methods, and "
                  "ordinary objects (sections 6.1.7 and 10.1).",
        "EXOTIC": "Searches excerpts of the ECMAScript specification about exotic "
                  "objects: bound functions, Array, String, Arguments, TypedArray, "
                  "module namespaces, immutable prototypes (sections 10.4.1-10.4.7) "
                  "and Proxy (section 10.5).",
        "WRAPPERS": "Searches excerpts of the ECMAScript specification about the "
                    "wrapper objects: the Object, Boolean, Symbol, Number and String "
                    "constructors and their prototypes (sections 20.1, 20.3, 20.4, "
                    "21.1, 22.1).",
        GENERAL: "Searches all available excerpts of the ECMAScript specification: "
                 "the Object type, exotic objects including Proxy, and the Object, "
                 "Boolean, Symbol, Number and String wrapper objects.",
    },
    "full": {
        "OBJECT": "Searches the ECMAScript specification chapters on data types and "
                  "values (chapter 6: the Object type, property attributes, object "
                  "internal methods and slots, their invariants) and on abstract "
                  "operations (chapter 7: type conversion, testing and comparison, "
                  "operations on objects and iterators).",
        "EXOTIC": "Searches the ECMAScript specification chapters on ordinary and "
                  "exotic object behaviours (chapter 10: ordinary objects, bound "
                  "functions, Array, String, Arguments, TypedArray, module "
                  "namespaces, immutable prototypes, Proxy internal methods) and on "
                  "reflection (chapter 28: the Reflect namespace and Proxy objects).",
        "WRAPPERS": "Searches the ECMAScript specification chapters on the global "
                    "object (chapter 19), fundamental objects (chapter 20: Object, "
                    "Boolean, Symbol, Error), numbers and dates (chapter 21: Number, "
                    "BigInt, Math, Date) and text processing (chapter 22: String and "
                    "RegExp).",
        GENERAL: "Searches the entire ECMAScript specification, all 38 chapters and "
                 "annexes: language grammar, expressions, statements, functions and "
                 "classes, modules, every built-in object, and the memory model.",
    },
}
_DESCRIPTIONS["suite"] = dict(
    _DESCRIPTIONS["full"],
    **{GENERAL: "Searches the whole ECMAScript specification suite: ECMA-262 (all 38 "
                "chapters and annexes: grammar, expressions, statements, functions and "
                "classes, modules, every built-in object, the memory model), ECMA-402 "
                "(the Intl object: Collator, DateTimeFormat, NumberFormat, PluralRules, "
                "Locale, Segmenter and other locale-sensitive functionality), ECMA-404 "
                "(the JSON data interchange syntax) and ECMA-414 (which standards make up "
                "the suite), plus the free documents ECMA-402 relies on: RFC 4647 (matching "
                "of language tags), Unicode UAX #29 (text segmentation), UTS #10 (the "
                "collation algorithm) and UTS #35 LDML parts 1-5 (locale identifiers, unit "
                "identifiers, number formats and plural rules, date and time formats, "
                "collation tailoring)."})

_DESC = _DESCRIPTIONS[DOC_SET]

SCHEMAS = {
    TOOL_NAMES["OBJECT"]: _schema(
        TOOL_NAMES["OBJECT"], _DESC["OBJECT"] + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    TOOL_NAMES["EXOTIC"]: _schema(
        TOOL_NAMES["EXOTIC"], _DESC["EXOTIC"] + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    TOOL_NAMES["WRAPPERS"]: _schema(
        TOOL_NAMES["WRAPPERS"], _DESC["WRAPPERS"] + _SEARCH_TAIL,
        _QUERY_PROP, ["query"]),
    TOOL_NAMES[GENERAL]: _schema(
        TOOL_NAMES[GENERAL], _DESC[GENERAL] + _SEARCH_TAIL,
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
    "search_docs tool. Search in at most two rounds (several queries in one "
    "round are fine); the reply after them MUST be the summary. If something "
    "is still missing, say what is missing instead of searching again.\n"
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

    Бюджет: після RESEARCH_BUDGET досліджень на одне питання виклик
    відхиляється без звернення до моделі — з поясненням, яке GENERAL читає як
    «складай з того, що є»; кожне дослідження має не більше RESEARCH_TURNS
    ходів. Лічильник скидає reset_research() на початку прогону маршруту.
    """
    _research_used["n"] += 1
    if _research_used["n"] > RESEARCH_BUDGET:
        return {"summary": (f"Research budget for this question is spent: "
                            f"{RESEARCH_BUDGET} topics were already researched. "
                            "Compose the answer from the summaries you already "
                            "have and do not call research_topic again."),
                "outcome": "budget_spent", "searches": 0,
                "found_anything": False, "budget_spent": True}

    from core import agent as course_agent
    from core.agent import run_agent

    # Ліміт ходів субагента — та сама підміна змінної модуля, що в
    # use_fast_model(): run_agent читає MAX_TURNS під час виклику.
    saved = course_agent.MAX_TURNS
    course_agent.MAX_TURNS = min(saved, RESEARCH_TURNS)
    try:
        result = run_agent(system=RESEARCH_PROMPT,
                           tools=[SCHEMAS[TOOL_NAMES[GENERAL]]], query=topic)
    finally:
        course_agent.MAX_TURNS = saved
    found = any(step["output"].get("found") for step in result["trace"])
    summary, source = result["answer"], "model"
    if result["outcome"] != "ok" and found:
        # Субагент шукав, знайшов, але підсумку не написав: замість шаблонного
        # «не вдалося завершити» GENERAL дістає самі уривки з ідентифікаторами.
        summary, source = excerpt_summary(result["trace"]), "excerpts"
    return {"summary": summary, "outcome": result["outcome"],
            "searches": len(result["trace"]), "found_anything": found,
            "summary_from": source}


def excerpt_summary(trace: list) -> str:
    """Замінний підсумок із траси субагента: перші EXCERPT_LIMIT різних уривків,
    кожен з ідентифікатором у дужках, як їх цитує модель. Нуль звернень до
    моделей; оплачені пошуки не пропадають."""
    seen, lines = set(), []
    for step in trace:
        for p in step.get("output", {}).get("passages", []) or []:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            text = " ".join(p.get("text", "").split())[:EXCERPT_CHARS]
            lines.append(f"[{p['id']}] {p.get('section', '')}: {text}")
            if len(lines) >= EXCERPT_LIMIT:
                break
        if len(lines) >= EXCERPT_LIMIT:
            break
    head = ("The research assistant ran out of steps before summarising; these are "
            "the excerpts it retrieved, verbatim, with their ids:\n")
    return head + "\n".join(lines)


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
    "2. Your subject is the ECMAScript specification and nothing else. A question "
    "about cooking, geography, travel, prices or any other field is not yours: say "
    "plainly that you are not a specialist in that subject, that you are a "
    "reference assistant for the ECMAScript specification, and stop there — do not "
    "answer it even if you happen to know the answer. Where a human colleague can "
    "take the question over, offer that instead of guessing.\n"
    "2a. If the question IS about the specification but nothing returned answers "
    "it, say so, name what the excerpts do cover, and point to "
    "https://tc39.es/ecma262/ where the whole specification is published. Do not "
    "answer from your own knowledge of JavaScript, do not guess.\n"
    "2b. A programming task IS your subject whenever its solution rests on the "
    "specification: write the code, rewrite the snippet, explain why a snippet "
    "behaves as it does. Search for the sections the solution relies on first, "
    "then propose the solution and justify every step of it with the ids those "
    "sections came back with. Never refuse a task merely because it asks for "
    "code; refuse only when the excerpts give you nothing to build the solution "
    "on, and then say so as in 2a.\n"
    "3. Cite every claim with the id shown in brackets, e.g. "
    "[18-string-objects#22.1.3.19]. Keep ids exactly as returned: never translate, "
    "shorten or invent them.\n"
    "4. Answer in the language the question was asked in: a Ukrainian question "
    "gets a fluent Ukrainian answer, an English question an English one. "
    "Translating what the excerpts say is fine; adding facts of your own is not.\n"
    "5. Plain prose, no Markdown tables, no emoji."
)

# Спеціаліст бачить лише свої розділи. Питання ПРО специфікацію, що виходить
# за них хоча б частиною (Promise у питанні до WRAPPERS), він не відповідає
# наполовину і не відмовляє як чужій темі — віддає GENERAL одним рядком, який
# base/system.py ловить детерміновано і повторює запит запасним маршрутом.
_HANDOVER_TAIL = (
    " If the question is about the specification but any part of it lies "
    "outside those sections, do not answer it partially and do not treat it "
    f"as a foreign subject: reply with exactly the line {HANDOVER_LINE} and "
    "nothing else, and a colleague who sees the whole specification takes it "
    "over. Questions from other fields (cooking, travel, prices) are not a "
    "handover case: rule 2 below applies to them.")

PROMPTS = {
    "OBJECT": (
        "You are the specialist for the ECMAScript Object type itself: property "
        "attributes, object internal methods and internal slots, their invariants, "
        "and ordinary objects. Your search tool covers only those sections; "
        "questions outside them are not yours to answer." + _HANDOVER_TAIL + _RULES),
    "EXOTIC": (
        "You are the specialist for ECMAScript exotic objects: bound functions, "
        "Array, String, Arguments, TypedArray, module namespaces, immutable "
        "prototypes, and Proxy. Your search tool covers only those sections; "
        "questions outside them are not yours to answer." + _HANDOVER_TAIL + _RULES),
    "WRAPPERS": (
        "You are the specialist for the ECMAScript wrapper objects: the Object, "
        "Boolean, Symbol, Number and String constructors and their prototypes. "
        "Your search tool covers only those sections; questions outside them are "
        "not yours to answer." + _HANDOVER_TAIL + _RULES),
    GENERAL: None,  # складається нижче з _GENERAL_HEAD і хвоста
}

_GENERAL_HEAD = (
    "You coordinate research over excerpts of the ECMAScript specification. "
    "You have no search of your own: delegate the draft work to the "
    "research_topic tool, one self-contained topic per call — a question with "
    "several parts means several calls, but at most four calls per question: "
    "merge overlapping topics into one call, because a fifth call is refused. "
    "Compose your answer strictly from the "
    "summaries the tool returns, keeping their citations; when the question is "
    "a programming task, the code you propose must follow from those summaries, "
    "each step of it tied to a cited section. If every research call comes back "
    "empty, or what came back does not actually answer the question, do NOT "
    "compose an answer of your own: ")

# Хвіст із request_handoff — штатний. Хвіст без нього — для перемикача
# --drop request_handoff: інструмент зі списку зник, і промпт не має його
# називати, інакше модель кличе те, чого немає, і прогін падає як tool_error.
# Рішення про людину в обох випадках ухвалює decide() у base/system.py за
# ознаками результату; різниця лише в тому, чи модель може попросити паузу сама.
_GENERAL_REQUEST_TAIL = (
    "call request_handoff first. It only ANNOUNCES the handover, so after "
    "calling it tell the user what is about to happen and that it waits for "
    "their confirmation.")
_GENERAL_PLAIN_TAIL = (
    "say plainly that the available excerpts do not answer it and stop there. "
    "Whether a human colleague takes the question over is decided outside "
    "this conversation; do not promise or announce it.")

PROMPTS[GENERAL] = _GENERAL_HEAD + _GENERAL_REQUEST_TAIL + _RULES

# Перемикач «прибрати інструмент»: імена через кому у змінній оточення, як
# PRACTICE_RETRIEVER і PRACTICE_REWRITE. Ставлять його прапорці --drop у
# base/system.py, base/compare.py і context/drop.py.
DROP_ENV = "PRACTICE_DROP_TOOLS"


def dropped_tools(drop: set | None = None) -> set:
    """Імена інструментів, прибраних зі списків. Явний аргумент має перевагу
    над змінною оточення; None означає «як в оточенні»."""
    if drop is not None:
        return set(drop)
    raw = os.environ.get(DROP_ENV, "")
    return {name.strip() for name in raw.split(",") if name.strip()}


def prompt_for_route(route: str, drop: set | None = None) -> str:
    """Промпт маршруту з урахуванням прибраних інструментів. Поки що різниться
    лише GENERAL: без request_handoff він дістає хвіст, який інструмент не
    називає."""
    if route == GENERAL and REQUEST_TOOL in dropped_tools(drop):
        return _GENERAL_HEAD + _GENERAL_PLAIN_TAIL + _RULES
    return PROMPTS[route]


def use_fast_model() -> str:
    """Переводить курсовий run_agent (і ask(fast=False) — критика) на дешеву
    модель каскаду: core.agent читає MODEL зі свого простору імен у момент
    виклику, тож підміна діє на спеціалістів, субагента і критика без правки
    курсового файла. Роутер і так на MODEL_FAST. Ціна рахується правильно сама:
    PRICES у core/cost.py шукає за рядком моделі. Повертає ім'я моделі."""
    from config import MODEL_FAST
    from core import agent as course_agent
    course_agent.MODEL = MODEL_FAST
    return course_agent.MODEL


def tools_for_route(route: str, extra: list | None = None,
                    drop: set | None = None) -> list:
    """Список схем для run_agent(tools=...). Курсові інструменти сюди не входять:
    поштовий бекенд до специфікації ECMAScript стосунку не має.

    `extra` — місце для схем челенджів (fetch_spec під --live); базова розкладка
    прав від цього не змінюється. `drop` — імена, які прибрати (None — як у
    змінній оточення PRACTICE_DROP_TOOLS); список лише звужується, ніколи не
    ширшає.
    """
    if route == GENERAL:
        base = [SCHEMAS[RESEARCH_TOOL], SCHEMAS[REQUEST_TOOL]]
    else:
        base = [SCHEMAS[TOOL_NAMES[route]]]
    gone = dropped_tools(drop)
    return [t for t in base if t["name"] not in gone] + list(extra or [])
