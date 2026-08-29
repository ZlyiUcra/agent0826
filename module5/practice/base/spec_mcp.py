"""ПРАКТИКА М5 · MCP-сервер над пошуком по специфікації ECMAScript.

Своє API тут — шар пошуку з практик модулів 2–4: розділи специфікації, поділені
на фрагменти, і пошук по словах BM25 над ними. Агент курсу возить цей пошук
усередині свого процесу; тут той самий пошук виставлений назовні двома
інструментами, і його бачить будь-який MCP-клієнт — Inspector, Claude Code,
Cursor.

Типово завантажується вся ECMA-262 — набір «full», 2436 фрагментів. Змінна
PRACTICE_DOCS перемикає на «core» (вісімнадцять розділів навколо типу Object,
283 фрагменти) або на «suite» (262 плюс ECMA-402, 404, 414 і вільні документи
довкола 402, 3964 фрагменти). Що саме завантажено, сервер пише в stderr на старті
і дописує окремим реченням до опису обох інструментів.

Пошук тут тільки по словах. Пошук по змісту (vectors.py, модель e5, torch) сюди не
перенесено свідомо: він вантажить модель десятки секунд, а сервер по stdio має
відповісти клієнтові одразу після запуску, інакше клієнт вирішить, що сервер
мертвий. Ціна рішення названа в README: пошук по словах не знаходить синонімів.

Ключі серверу не потрібні: він не звертається ні до Anthropic, ні в мережу —
читає теки docs*/ і більше нічого.

Запуск (сам по собі мовчки чекає клієнта на stdio — це не зависання):

    .venv/bin/python practice/base/spec_mcp.py

Перевірки:

    .venv/bin/python -m practice.base.smoke     функції напряму, повз протокол
    .venv/bin/python -m practice.base.check     справжній stdio-клієнт
    npx -y @modelcontextprotocol/inspector .venv/bin/python practice/base/spec_mcp.py
"""

import datetime
import os
import pathlib
import sys
import textwrap

# Сервер запускають файлом («python practice/base/spec_mcp.py»), і Claude Code
# запускає його зі своєї поточної теки, а не з module5/. Тому корінь модуля
# додаємо в шлях самі, інакше «import practice.common» не знайдеться.
_MODULE_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))

# Який набір документів брати. common/corpus.py читає змінну PRACTICE_DOCS і знає
# три набори: «core» — вісімнадцять розділів навколо типу Object, «full» — уся
# специфікація ECMA-262 (38 розділів), «suite» — та сама 262 плюс ECMA-402 (Intl),
# ECMA-404 (JSON), ECMA-414 і вільні документи довкола 402.
#
# Типовим тут стоїть «full»: питання до сервера ставлять про всю мову, а не про
# один її кут, і відповідь «такого немає» через те, що розділ просто не завантажили,
# гірша за повільніший старт. Старт від цього не потерпає — уся 262 читається і
# індексується приблизно за секунду. setdefault, а не пряме присвоєння: якщо
# власник назвав набір у оточенні, його вибір лишається за ним.
os.environ.setdefault("PRACTICE_DOCS", "full")

# MCP SDK 1.x називав це FastMCP, у 2.0 — MCPServer; API той самий.
# Той самий подвійний імпорт, що в курсовому tracking_mcp.py.
try:
    from mcp.server import MCPServer as _Server          # SDK >= 2.0
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as _Server  # SDK 1.x
    except ImportError:
        raise SystemExit("Потрібен MCP SDK:  pip install 'mcp[cli]'")

from practice.common import nform
from practice.common.corpus import DOC_SET, Passage
from practice.common.lexical import LexicalIndex

# Скільки символів фрагмента віддавати у відповіді пошуку. Фрагменти бувають до
# півтори тисячі символів, і три таких у відповіді — це вже стіна тексту в
# контексті клієнта. Хто хоче повний текст, кличе read_section за ідентифікатором.
PREVIEW_CHARS = 600

# Межі k. Менше одного — безглуздо, більше десяти — це вже добрих кілька тисяч
# слів в одній відповіді, і клієнт платить за них своїми токенами.
K_MIN, K_MAX = 1, 10

# Індекс будується один раз при завантаженні модуля, а не на кожен виклик:
# уся ECMA-262 читається з файлів і індексується приблизно за секунду, але
# робити це щоразу означало б платити цією секундою за кожен запит.
_INDEX = LexicalIndex()

# Ідентифікатор фрагмента береться з corpus.Passage.pid, і на наборі «core» вони
# всі різні. На повній специфікації є один збіг: у розділі
# 16-ecmascript-language-scripts-and-modules два рядки кроків алгоритму, «1 ( D )»
# і «1 ( B )», розбір приймає за заголовки розділу з номером «1», і обидва
# фрагменти дістають однаковий pid. Якби ми клали їх у словник як є, другий тихо
# затер би перший: пошук показав би його id, а read_section повернув би чужий
# текст. Тому ідентифікатори роздаються тут, і повторному додається «~2». Обидва
# інструменти беруть id саме звідси, тож те, що показав пошук, і те, що прочитає
# read_section, — завжди один фрагмент.
_BY_ID: dict[str, Passage] = {}
_UID: dict[Passage, str] = {}
for _p in _INDEX.passages:
    _uid = _p.pid
    _n = 2
    while _uid in _BY_ID:
        _uid = f"{_p.pid}~{_n}"
        _n += 1
    _BY_ID[_uid] = _p
    _UID[_p] = _uid

_COUNT = len(_INDEX.passages)
_DOCS = len({p.doc_id for p in _INDEX.passages})

# Що саме зараз завантажено — одним реченням для моделі. Це не можна написати в
# докстрінгу наперед: набір обирає той, хто запускає сервер, і лише сам сервер
# знає, що з цього вийшло. Модель, яка не знає меж того, що їй доступно, вигадує
# відповіді про розділи, яких тут немає.
_LOADED = {
    "core": (f"Loaded right now: only the {_DOCS} sections around the Object type "
             f"({_COUNT} excerpts) -- the object type itself, ordinary and exotic "
             f"objects, and the Object, Array, String, Number, Boolean, Symbol and "
             f"Proxy chapters. The rest of the language is not here."),
    "full": (f"Loaded right now: the whole of ECMA-262, {_COUNT} excerpts from "
             f"{_DOCS} sections -- syntax, semantics, every built-in object. Other "
             f"standards are not here: no ECMA-402 (Intl), no ECMA-404 (JSON)."),
    "suite": (f"Loaded right now: ECMA-262 together with ECMA-402 (Intl), ECMA-404 "
              f"(JSON), ECMA-414 and the free documents around 402 (RFC 4647, the "
              f"Unicode reports) -- {_COUNT} excerpts from {_DOCS} sections."),
}[DOC_SET]

# Рядок діагностики — у stderr. У stdout не можна нічого: там ходять кадри
# JSON-RPC, і будь-який print ламає клієнтові розбір відповіді.
print(f"spec_mcp: набір «{DOC_SET}», проіндексовано {_COUNT} "
      f"{nform(_COUNT, 'фрагмент', 'фрагменти', 'фрагментів')} "
      f"з {_DOCS} {nform(_DOCS, 'розділу', 'розділів', 'розділів')}",
      file=sys.stderr)

# Журнал викликів: хто що питав.
#
# Кожен клієнт запускає власну копію цього сервера, тому в Inspector видно лише
# те, що питав Inspector, а в Claude Code — лише те, що питав Claude Code.
# Рядок нижче йде у два місця. У stderr — бо там його одразу показує Inspector
# (вкладка Console) і Claude Code із прапорцем --debug; це те саме stderr, куди
# картка велить складати всю діагностику, аби не зачепити stdout, де ходить
# протокол. У файл — бо stderr живе рівно стільки, скільки процес, а щоб
# порівняти виклики з різних клієнтів, запис має пережити їх усі.
#
# Файл тільки дописується. Ніщо в цьому коді його не читає, не чистить і не
# перезаписує; коли він набридне, власник прибирає його сам.
LOG_PATH = _MODULE_ROOT / "practice" / "out" / "calls.log"
_PID = os.getpid()


def _log(tool: str, request: str, outcome: str) -> None:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} pid={_PID} {tool} {request} -> {outcome}"
    print(line, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        # Журнал не має права зіпсувати відповідь клієнтові: якщо теки немає або
        # диск не пише, скаржимося в stderr і працюємо далі.
        print(f"spec_mcp: журнал не записався ({exc})", file=sys.stderr)


mcp = _Server("ecma-spec")


def _preview(text: str) -> str:
    """Текст фрагмента для відповіді пошуку: обрізаний, з видимою позначкою обрізки."""
    if len(text) <= PREVIEW_CHARS:
        return text
    return text[:PREVIEW_CHARS] + "..."


def _format_hits(passages: list[Passage]) -> dict:
    """Відповідь пошуку. Формат той самий, що в common/search.py практики модуля 4,
    з однією різницею — текст тут обрізаний до PREVIEW_CHARS."""
    if not passages:
        return {"found": 0,
                "note": "Nothing in the available excerpts matches this query."}
    return {"found": len(passages),
            "passages": [{"id": _UID[p], "section": p.label,
                          "document": p.doc_title, "text": _preview(p.text)}
                         for p in passages]}


def search_spec(query: str, k: int = 3) -> dict:
    """Search the text of the ECMAScript language specification (ECMA-262) and
    return the matching excerpts with their section numbers.

    Call this when a question is about how something is defined or behaves in
    JavaScript itself -- an operator, an abstract operation, a built-in method or
    property of Object, Array, String, Number, Boolean, Symbol, Proxy or
    TypedArray -- and the answer should cite where the specification says it.
    Example query: "Object.prototype.toString tag".

    Do not call this for questions about browsers, the DOM, Node.js, npm
    packages, TypeScript or any library: none of that is in the specification and
    the search will return unrelated sections with confident-looking numbers.

    Write the query in English, using the identifiers the specification itself
    uses. The text held here is English, and the query is matched against it word
    by word (BM25), keeping only latin letters and digits: a query written in
    Ukrainian, Russian or any other non-latin script matches nothing at all and
    comes back with `found: 0`. When the user asks in another language, translate
    the question into specification terms first, then search.

    Answer in the language the user wrote in. When that language is Ukrainian,
    write as a Ukrainian engineer writes, not as a translation from English:
    plain technical prose, and the Ukrainian word wherever one exists -- "розділ",
    not "секція"; "уривок", not "ексерпт"; "вбудований метод", not "білт-ін".
    Never call this set of sections "корпус" -- say "розділи специфікації".
    Identifiers, method names and section titles stay in English, spelled exactly
    as the specification spells them. Name the section by its number, and build
    the answer out of the steps that came back, not out of memory: if the excerpt
    was cut, read the whole of it before describing what it says.

    Arguments: `query` is free text; `k` is how many excerpts to return, 1 to 10,
    default 3. Excerpt text is cut at 600 characters -- pass the `id` of an
    excerpt to `read_section` to get the whole thing.
    """
    if not isinstance(k, int) or k < K_MIN or k > K_MAX:
        _log("search_spec", f"query={query!r} k={k!r}", "помилка: k поза межами")
        return {"error": f"k має бути від {K_MIN} до {K_MAX}"}
    hits = _INDEX.retrieve(query, k)
    _log("search_spec", f"query={query[:120]!r} k={k}", f"знайдено {len(hits)}")
    return _format_hits(hits)


def read_section(id: str) -> dict:
    """Return the full text of one specification excerpt by its identifier,
    together with the section number and the URL it was taken from.

    Call this after `search_spec` when the excerpt you need came back cut at 600
    characters, or when the exact wording of a step in an abstract operation
    matters -- a definition quoted half-way is how a wrong answer starts.
    Example identifier: "14-object-objects#20.1.3.6/2".

    Do not guess identifiers: they are not section numbers and cannot be
    assembled by hand. Every identifier this tool accepts comes from the `id`
    field of a `search_spec` result.

    The text comes back in English, as the specification is written. Answer the
    user in their own language, and follow the same rules as for `search_spec`:
    keep identifiers and section titles in English, use Ukrainian words for
    Ukrainian prose, and cite the section number you read.
    """
    passage = _BY_ID.get(id)
    if passage is None:
        _log("read_section", f"id={id!r}", "помилка: такого id немає")
        return {"error": "фрагмента з таким id немає",
                "hint": "id береться з поля id у відповіді search_spec"}
    _log("read_section", f"id={id!r}", f"{len(passage.text)} символів")
    return {"id": _UID[passage],
            "section": passage.label,
            "document": passage.doc_title,
            "url": passage.url,
            "text": passage.text}


# Реєстрація. Обидва інструменти могли б висіти на звичайному @mcp.tool(), і тоді
# описом ставав би самий докстрінг — так зроблено в курсовому tracking_mcp.py.
# Тут описом стає докстрінг ПЛЮС рядок про завантажений набір: інакше модель не
# знає, де межа того, що їй доступно, а докстрінг цієї межі знати не може, бо її
# обирають при запуску.
TOOL_DESCRIPTIONS: dict[str, str] = {}

for _fn in (search_spec, read_section):
    TOOL_DESCRIPTIONS[_fn.__name__] = (
        textwrap.dedent(_fn.__doc__).strip() + "\n\n" + _LOADED)
    mcp.tool(description=TOOL_DESCRIPTIONS[_fn.__name__])(_fn)


if __name__ == "__main__":
    mcp.run()          # stdio: клієнт сам запускає цей процес і говорить у труби
