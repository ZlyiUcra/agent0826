"""ПРАКТИКА М6 · MCP-сервер знань над специфікацією і приманками.

Той самий підхід, що в практиці модуля 5: розділи, поділені на фрагменти, і
пошук над ними, виставлений назовні двома інструментами (search_spec,
read_section). Агент практики (base/agent.py) підключається сюди як MCP-клієнт
по stdio і бере знання лише звідси.

Корпус — набір специфікації (типово suite, ~4160 фрагментів) РАЗОМ із теки
docs-attack/, серед якої два отруєні документи: у їхнє тіло зашита інструкція
для моделі. Так непряма ін'єкція ховається серед тисяч справжніх фрагментів і
приходить агентові чесним каналом — звичайною видачею search_spec.

Шукає сервер двома способами. По словах (BM25) — завжди: індекс будується при
завантаженні модуля і нічого більше не потребує. За змістом — коли власник
погодився на це при підготовці (base/setup.py записав рішення у out/mode.json):
тоді поруч працює Qdrant, близькість рахує модель bge-small через ONNX, і два
списки зливаються за взаємним рангом (RRF). Поле `search` у відповіді каже, який
із двох способів її дав. Пошук за змістом ніде не стоїть на критичному шляху:
контейнер і модель прогріваються в окремій нитці, тож на перший запит сервер
відповідає одразу, поки що по словах.

Ключі серверу не потрібні: він читає теки документів і говорить із Qdrant на
localhost. У stdout нічого не друкує — там ходять кадри JSON-RPC; діагностика
лише в stderr.

Запуск (сам по собі мовчки чекає клієнта на stdio — це не зависання):

    .venv/bin/python practice/base/spec_server.py
"""

import pathlib
import sys
import threading

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

from practice.common import mode
from practice.common.corpus import DOC_SET, load_passages
from practice.common.idmap import assign_ids
from practice.common.lexical import LexicalIndex, tokenize

mcp = _Server("spec-knowledge")

# Індекс будується один раз при завантаженні модуля. На наборі suite це кілька
# секунд, і саме тому воно тут, а не в кожному виклику. Ідентифікатори роздає
# assign_ids, бо на повному наборі pid зрідка збігаються (див. idmap.py), а сервер
# і колекція Qdrant мусять називати фрагмент однаково.
_INDEX = LexicalIndex(load_passages())
_BY_ID, _UID = assign_ids(_INDEX.passages)
_COUNT = len(_INDEX.passages)

K_MIN, K_MAX = 1, 10
CUT = 600      # скільки символів тексту фрагмента вкладати у видачу search_spec

print(f"spec_server: набір «{DOC_SET}» разом із приманками, "
      f"{_COUNT} фрагментів", file=sys.stderr)

# Рішення про спосіб пошуку, ухвалене при підготовці. Сервер його лише читає.
_MODE = mode.read()
_VECTORS_ASKED = _MODE.get("search") == "vectors"
_VECTORS_READY = False


def _prepare_vectors() -> None:
    """Піднімає Qdrant і прогріває модель у фоні. Доти сервер відповідає по словах.
    Не піднялося — пише причину в stderr і працює по словах далі."""
    global _VECTORS_READY
    try:
        from practice.common import embed, vectorstore
        if not vectorstore.ensure_running():
            why = "Qdrant не відповідає і контейнер не піднявся"
        elif vectorstore.count() == 0:
            why = (f"колекція {vectorstore.COLLECTION} порожня — "
                   f"залийте: python -m practice.base.setup --vectors")
        else:
            embed.model()          # прогрів: перший запит не платить за завантаження
            _VECTORS_READY = True
            have = vectorstore.count()
            print(f"spec_server: пошук за змістом готовий, {have} точок у "
                  f"{vectorstore.COLLECTION}", file=sys.stderr)
            if have < _COUNT:
                print(f"spec_server: недолито {_COUNT - have} — частина фрагментів "
                      f"шукається лише по словах", file=sys.stderr)
            return
    except Exception as exc:                      # noqa: BLE001 - причина в stderr
        why = f"{type(exc).__name__}: {exc}"
    print(f"spec_server: пошук за змістом недоступний ({why}); працюю по словах",
          file=sys.stderr)


if _VECTORS_ASKED:
    threading.Thread(target=_prepare_vectors, name="vectors", daemon=True).start()


def _rrf(rankings: list, k: int, const: int = 60) -> list:
    """Злиття списків за взаємним рангом. Пошук по словах і за змістом дають
    оцінки в різних шкалах; RRF порівнює не оцінки, а місця."""
    score: dict = {}
    for ranking in rankings:
        for place, passage in enumerate(ranking):
            score[passage] = score.get(passage, 0.0) + 1.0 / (const + place + 1)
    return sorted(score, key=lambda p: -score[p])[:k]


def _find(query: str, k: int):
    """Пошук по словах, а якщо готовий — разом із пошуком за змістом. Повертає
    (фрагменти, спосіб) — «words» або «meaning+words»."""
    words = _INDEX.retrieve(query, k)
    if not _VECTORS_READY:
        return words, "words"
    try:
        from practice.common import embed, vectorstore
        hits = vectorstore.search(embed.embed_query(query), k)
        meaning = [_BY_ID[h["uid"]] for h in hits if h.get("uid") in _BY_ID]
    except Exception as exc:                      # noqa: BLE001 - причина в stderr
        print(f"spec_server: пошук за змістом не відповів ({exc}); "
              f"віддаю знайдене по словах", file=sys.stderr)
        return words, "words"
    if not meaning:
        return words, "words"
    return _rrf([words, meaning], k), "meaning+words"


def _hit(passage, full: bool) -> dict:
    text = passage.text if full else passage.text[:CUT]
    return {"id": _UID[passage], "section": passage.label,
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
    thing. The `search` field says how the excerpts were found: "words" means the
    query words had to appear in the text; "meaning+words" means a second,
    meaning-based index answered as well, so a paraphrase had a chance. Arguments:
    `query` is free text; `k` is how many excerpts to return, 1 to 10, default 3.
    """
    if not isinstance(k, int) or k < K_MIN or k > K_MAX:
        return {"error": f"k має бути від {K_MIN} до {K_MAX}"}
    if not tokenize(query) and not _VECTORS_READY:
        return {"found": 0, "search": "words",
                "note": "The query has no latin words. Translate the question "
                        "into the terms the specification uses, then search again."}
    hits, how = _find(query, k)
    return {"found": len(hits), "search": how,
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
