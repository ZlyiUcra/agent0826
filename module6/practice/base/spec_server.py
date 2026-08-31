"""ПРАКТИКА М6 · MCP-сервер знань над корпусом-приманкою.

Той самий підхід, що в практиці модуля 5: розділи, поділені на фрагменти, і
пошук по словах BM25 над ними, виставлений назовні двома інструментами
(search_spec, read_section). Агент практики (base/agent.py) підключається сюди
як MCP-клієнт по stdio і бере знання лише звідси.

Корпус тут — навчальна приманка з docs-attack/, а не справжня специфікація:
кілька чесних розділів і два отруєні, у тіло яких зашита інструкція для моделі.
Саме тому непряма ін'єкція має куди прилетіти — вона приходить як звичайна
видача search_spec, тобто чесним каналом, яким ідуть і справжні знання.

Ключі серверу не потрібні: він читає docs-attack/ і більше нічого. У stdout
нічого не друкує — там ходять кадри JSON-RPC; діагностика лише в stderr.

Запуск (сам по собі мовчки чекає клієнта на stdio — це не зависання):

    .venv/bin/python practice/base/spec_server.py
"""

import pathlib
import sys

# Сервер запускають файлом, і клієнт (агент чи Inspector) робить це зі своєї
# поточної теки, а не з module6/. Корінь модуля додаємо в шлях самі, інакше
# «import practice.common» не знайдеться.
_MODULE_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))

# MCP SDK 1.x називав це FastMCP, у 2.0 — MCPServer; API той самий. Той самий
# подвійний імпорт, що в курсовому tracking_mcp.py і в сервері модуля 5.
try:
    from mcp.server import MCPServer as _Server          # SDK >= 2.0
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server    # SDK 1.x

from practice.common.corpus import load_passages
from practice.common.lexical import LexicalIndex, tokenize

mcp = _Server("spec-knowledge")

# Індекс будується один раз при завантаженні модуля. Корпус малий, тож це частки
# секунди.
_INDEX = LexicalIndex(load_passages())
_BY_ID = {p.pid: p for p in _INDEX.passages}

K_MIN, K_MAX = 1, 10
CUT = 600      # скільки символів тексту фрагмента вкладати у видачу search_spec

print(f"spec_server: корпус-приманка, {len(_INDEX.passages)} фрагментів",
      file=sys.stderr)


def _hit(passage, full: bool) -> dict:
    text = passage.text if full else passage.text[:CUT]
    return {"id": passage.pid, "section": passage.label,
            "document": passage.doc_title, "url": passage.url, "text": text}


def search_spec(query: str, k: int = 3) -> dict:
    """Search the text of the ECMAScript specification and return the matching
    excerpts with their section numbers.

    Call this when a question is about how something is defined or behaves in
    JavaScript itself -- an operator, an abstract operation, a built-in method or
    property of Object, Array, String, Number, Boolean or Symbol -- and the
    answer should cite where the specification says it. Example query:
    "Object.prototype.toString tag".

    Write the query in English, using the identifiers the specification uses: the
    word index keeps only latin letters and digits, so a query in Ukrainian or
    any non-latin script matches nothing. When the user asks in another language,
    translate the question into specification terms first, then search.

    Answer the user in the language they wrote in. Excerpt text is cut at 600
    characters -- pass the `id` of an excerpt to `read_section` to get the whole
    thing. Arguments: `query` is free text; `k` is how many excerpts to return,
    1 to 10, default 3.
    """
    if not isinstance(k, int) or k < K_MIN or k > K_MAX:
        return {"error": f"k має бути від {K_MIN} до {K_MAX}"}
    if not tokenize(query):
        return {"found": 0, "search": "words",
                "note": "The query has no latin words. Translate the question "
                        "into the terms the specification uses, then search again."}
    hits = _INDEX.retrieve(query, k)
    return {"found": len(hits), "search": "words",
            "hits": [_hit(p, full=False) for p in hits]}


def read_section(id: str) -> dict:
    """Return the full text of one excerpt by its identifier, together with the
    section number and the source it was taken from.

    Call this after `search_spec` when the excerpt you need came back cut at 600
    characters. Do not guess identifiers: every identifier this tool accepts
    comes from the `id` field of a `search_spec` result.
    """
    passage = _BY_ID.get(id)
    if passage is None:
        return {"error": "фрагмента з таким id немає",
                "hint": "id береться з поля id у відповіді search_spec"}
    return _hit(passage, full=True)


# Реєстрація: описом інструмента стає його докстрінг, як у курсовому
# tracking_mcp.py. Корпус тут сталий, тож дописувати рядок про набір, як у
# модулі 5, не треба.
TOOL_DESCRIPTIONS = {}
for _fn in (search_spec, read_section):
    import textwrap
    TOOL_DESCRIPTIONS[_fn.__name__] = textwrap.dedent(_fn.__doc__).strip()
    mcp.tool(description=TOOL_DESCRIPTIONS[_fn.__name__])(_fn)


if __name__ == "__main__":
    mcp.run()          # stdio: клієнт сам запускає цей процес і говорить у труби
