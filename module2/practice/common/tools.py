"""
СПІЛЬНЕ · пошук як інструмент агента і промпт, який змушує ним користуватися.

Курсовий модуль 2 підмішує знайдене в системний промпт до того, як агент почав
працювати (static RAG у `modules/m02_rag.py`). Тут інакше: пошук відданий агентові
інструментом `search_docs`, і рішення, ЩО і КОЛИ шукати, ухвалює він сам. Це те
саме, що показує курсовий `rag_agentic.py`, тільки на своїх документах.

Чому саме так, а не підмішуванням. Питання про специфікацію часто складене з
двох: «чи бачить Proxy те, що прописано в цільовому об'єкті як незмінне» — це
окремо про інваріанти внутрішніх методів і окремо про [[Get]] у Proxy.
Один пошук по всьому запиту дасть суміш; агент, у якого пошук під рукою, зробить
два і візьме потрібне з кожного.

РЕЄСТРАЦІЯ В КУРСОВОМУ ДИСПЕТЧЕРІ

`core/agent.py` імпортує `dispatch` з `domain/backend.py`, а той шукає реалізацію
лише у своєму словнику `IMPL`. Передати власні СХЕМИ можна параметром
`run_agent(tools=...)`, власні РЕАЛІЗАЦІЇ — ні. Тому `register()` дописує
`search_docs` в `IMPL` і перед тим перевіряє, що такого імені там ще немає:
`dict.update` мовчки підмінив би курсову функцію, і курс поламався б непомітно.

Виклик `register()` живе в точках входу практики, а не в імпорті цього файлу.
Курсові `run.py` і `demo.py` — окремі процеси, які практику не імпортують, тож
до них ця реєстрація не доходить. `CAPABILITIES` і `tools_for()` не змінюються.

ПРО «НЕ ЗНАЮ»

Головна вимога картки — щоб агент відмовлявся, а не вигадував. Запобіжників два,
і кожен закриває свій випадок; жоден із них не закриває обидва.

Нижня межа схожості у `VectorIndex.retrieve` відсікає запити, у яких з нашими документами
немає спільної теми. «What is the recipe for borscht?» дає 0.768 при нижній межі
0.80, і інструмент повертає порожньо — модель просто не отримує тексту, з якого
можна було б щось скласти.

Питання про JavaScript, відповіді на яке в наших вісімнадцяти розділах немає,
нижня межа не спиняє: воно з тієї самої теми, що й документи, і схожість у нього така
сама, як у правильних питань (виміри — у докстрингу vectors.py). На такому
запиті інструмент поверне три фрагменти, і жоден із них питання не закриває.
Відмовити тут може тільки модель, бо тільки вона читає сам текст, а не оцінку
схожості. Саме це й наказує промпт: відповідати виключно з того, що повернув
пошук, і не добирати з власної пам'яті.

Промпт тут не перестраховка. Модель знає специфікацію ECMAScript і без наших
документів: про `Array.prototype.flat` вона відповість із голови, і відповідь навіть
буде правильною. Правильною, але без джерела — перевірити її нічим, а наступного
разу так само впевнено вийде вигадка. Сценарій `known` у practice/base/ask.py
перевіряє саме цей випадок.
"""

import os

from domain import backend as course_backend

from . import rewrite
from .corpus import Passage
from .lexical import LexicalIndex
from .vectors import VectorIndex

# Знімок курсових імен, зроблений до будь-якої реєстрації: звірятися треба саме
# з ним, інакше повторний виклик register() знайшов би «збіг» із власним іменем.
_COURSE_TOOL_NAMES = frozenset(course_backend.IMPL)

TOOL_NAME = "search_docs"

SEARCH_DOCS_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Searches the ECMAScript specification excerpts available to you: the Object type, "
        "exotic objects (Array, String, Arguments, TypedArray, Proxy, bound functions, "
        "module namespaces, immutable prototypes) and the String, Symbol, Number and Boolean "
        "wrapper objects. Call it before stating anything about the specification. "
        "Ask one thing at a time; if a question has several parts, search several times."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for, in your own words, "
                               "e.g. 'replacing a substring inside a string'",
            }
        },
        "required": ["query"],
    },
}

_RETRIEVERS = {"vector": VectorIndex, "lexical": LexicalIndex}
_index = None
_backend_name = None


def get_index(backend: str = None):
    """Індекс потрібного виду, один на процес.

    Вид береться з аргументу або зі змінної оточення PRACTICE_RETRIEVER
    («vector» за замовчуванням, «lexical» — щоб прогнати агента на пошуку по словах).
    """
    global _index, _backend_name
    name = backend or os.getenv("PRACTICE_RETRIEVER", "vector")
    if name not in _RETRIEVERS:
        raise SystemExit(f"Невідомий пошук '{name}'. Доступні: "
                         f"{', '.join(sorted(_RETRIEVERS))}")
    if _index is None or _backend_name != name:
        _index = _RETRIEVERS[name]()
        _backend_name = name
    return _index


def _format(passages: list[Passage]) -> dict:
    if not passages:
        return {"found": 0,
                "note": "Nothing in the available excerpts matches this query."}
    return {"found": len(passages),
            "passages": [{"id": p.pid, "section": p.label,
                          "document": p.doc_title, "text": p.text}
                         for p in passages]}


def _search_once(index, query: str, k: int = 3):
    """Фрагменти, що подолали межу, і оцінка найкращого з усіх — навіть якщо не пройшов."""
    top = index.scores(query, 1)
    return index.retrieve(query, k), (top[0][0] if top else 0.0)


def search_docs(query: str) -> dict:
    """Пошук по документах. При бідному результаті переписує запит і шукає вдруге.

    Друга спроба вмикається змінною PRACTICE_REWRITE=1 і описана в
    practice/common/rewrite.py. Вимкнена вона тому, що звертається до моделі:
    інструмент без неї коштує нуль і працює без ключа.
    """
    index = get_index()
    hits, top = _search_once(index, query)
    if not rewrite.enabled():
        return _format(hits)

    # Порожньо не переписуємо. Причина не в економії: допоміжна модель на
    # питання не з теми відповідає відмовою, ця відмова йде в пошук як запит,
    # і слова «JavaScript» у ній вистачає, щоб перевищити межу. Вимір і
    # числа — у докстрингу practice/common/rewrite.py.
    thin = len(hits) < rewrite.MIN_HITS or top < rewrite.confident_bar()
    if not hits or not thin:
        return _format(hits)

    second = rewrite.reformulate(query)
    if not second:
        return _format(hits)

    hits2, top2 = _search_once(index, second)
    # Кращим вважається набір, у якому більше знайденого; при рівності —
    # той, у якого вищий найкращий фрагмент. Переписування не має права
    # зробити результат гіршим, тому при нічиїй лишається перший.
    took_second = (len(hits2), top2) > (len(hits), top)
    out = _format(hits2 if took_second else hits)
    out["rewritten_query"] = second
    out["rewrite_used"] = took_second
    if not out["found"]:
        out["note"] = ("Nothing in the available excerpts matches this query, "
                       "with either the original wording or a rewritten one.")
    return out


PRACTICE_IMPL = {TOOL_NAME: search_docs}


def register() -> None:
    """Додає search_docs у курсовий реєстр реалізацій. Ідемпотентна."""
    collisions = sorted(set(PRACTICE_IMPL) & _COURSE_TOOL_NAMES)
    if collisions:
        raise RuntimeError(
            f"Ім'я інструмента практики збігається з курсовим: {', '.join(collisions)}. "
            "IMPL.update підмінив би курсову реалізацію мовчки. Перейменуйте інструмент."
        )
    course_backend.IMPL.update(PRACTICE_IMPL)


def tools() -> list:
    """Список схем для run_agent(tools=...). Курсові інструменти сюди не входять:
    поштовий бекенд до специфікації ECMAScript стосунку не має."""
    return [SEARCH_DOCS_SCHEMA]


PRACTICE_PROMPT = (
    "You are a reference assistant for the ECMAScript language specification. "
    "You answer strictly from the excerpts returned by the search_docs tool.\n"
    "\n"
    "Rules you must follow:\n"
    "1. Search before you answer. Never state a fact about the specification "
    "that did not come back from search_docs in this conversation.\n"
    "2. If the search returns nothing, say plainly that the available excerpts "
    "do not cover the question, and name what they do cover. Do not answer from "
    "your own knowledge of JavaScript, do not guess, do not offer a plausible "
    "reconstruction.\n"
    "3. Cite the section you used, by the id shown in brackets, "
    "e.g. [18-string-objects#22.1.3.11].\n"
    "4. Answer in English, in plain prose, no Markdown tables and no emoji."
)
