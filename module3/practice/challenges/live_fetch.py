"""
ЧЕЛЕНДЖ · живий сайт специфікації для спеціаліста EXOTIC, за прапорцем --live.

Це перший вихід у мережу в усьому репозиторії, тому межі тут жорсткіші, ніж
зручно. Без прапорця --live цього інструмента немає навіть у списку схем —
система за замовчуванням працює лише з локальними документами.

ЩО САМЕ ДОЗВОЛЕНО

Одна адреса рівно одного виду: https://tc39.es/ecma262/multipage/<глава>.html
з якорем підрозділу після #. Схема лише https, host рівно tc39.es, шлях лише в
multipage-розкладці — односторінкова версія специфікації важить 7.2 МБ і не
потрібна, коли той самий підрозділ є в главі на порядок меншій. Перенаправлення заборонені
всі: переїзд сторінки — привід оновити код очима, а не піти слідом наосліп.

ЩО ПОВЕРТАЄТЬСЯ

Не сторінка (глава multipage — це близько мегабайта розмітки), а вирізаний
підрозділ: від <emu-clause id="якір"> до наступного <emu-clause, тобто шапка
підрозділу з його алгоритмом, без вкладених підпідрозділів. Розмітка
зчищається, текст обрізається межею MAX_CHARS. Кожен tool_result несе позначку source: живий
сайт, НЕ локальні документи — і вимогу цитувати знайдене як [live:якір], щоб
звірка посилань (base/critic.py) відрізняла живі джерела від локальних і
ловила якорі, яких ніхто не вивантажував.

КЕШ

Відповіді лягають у practice/live_cache/ під іменем із хеша адреси; повторний
запит того самого підрозділу в мережу не ходить. Код нічого не видаляє — застарілий
кеш прибирає людина.

ЧОМУ ІНСТРУМЕНТ САМЕ В EXOTIC

Родина найскладніша, і питання про екзотичні об'єкти найчастіше зачіпають
розділи, яких у вісімнадцяти вивантажених немає. Іншим спеціалістам живий сайт
не дається навмисно: що менше маршрутів мають вихід у мережу, то менше місць,
де підміна вмісту сторінки може дотягтися до відповіді.
"""

import hashlib
import html as html_lib
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from domain import backend as course_backend

CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent / "live_cache"

ALLOWED_SCHEME = "https"
ALLOWED_HOST = "tc39.es"
ALLOWED_PATH = re.compile(r"^/ecma262/multipage/[a-z0-9-]+\.html$")
ANCHOR = re.compile(r"^[\w.%-]+$")

MAX_PAGE_BYTES = 3_000_000   # глава multipage — до ~1 МБ; більше означає не главу
MAX_CHARS = 8000             # межа розміру вирізаного підрозділу, щоб він влазив у промпт
TIMEOUT_SEC = 15

TOOL_NAME = "fetch_spec"

SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Fetches ONE section from the live ECMAScript specification at tc39.es. "
        "Use it only when search_exotic_docs returned nothing that answers the "
        "question. Pass the full multipage URL with the section anchor, e.g. "
        "https://tc39.es/ecma262/multipage/ordinary-and-exotic-objects-behaviours"
        ".html#sec-array-exotic-objects. The text comes from the LIVE site, not "
        "from the local excerpts: cite it as [live:<anchor>], and if it does not "
        "actually answer the question, say so plainly instead of forcing it."),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string",
                    "description": "Full https://tc39.es/ecma262/multipage/... "
                                   "address including #anchor"},
        },
        "required": ["url"],
    },
}

PROMPT_ADDON = (
    "\n6. You also have fetch_spec for the live specification site. Reach for "
    "it only after search_exotic_docs returned nothing useful. Everything it "
    "returns is live-site content: cite it as [live:<anchor>] and never mix it "
    "up with the local excerpt ids. If the fetched section does not answer the "
    "question, say so plainly."
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code,
                                     f"redirect refused (to {newurl})",
                                     headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def _validate(url: str) -> tuple[str, str] | dict:
    """Розібрана і перевірена адреса: (адреса без якоря, якір) або error."""
    parts = urllib.parse.urlparse(url.strip())
    if parts.scheme != ALLOWED_SCHEME:
        return {"error": f"only {ALLOWED_SCHEME} is allowed, got '{parts.scheme}'"}
    if parts.netloc != ALLOWED_HOST:
        return {"error": f"only host {ALLOWED_HOST} is allowed, got '{parts.netloc}'"}
    if not ALLOWED_PATH.match(parts.path):
        return {"error": "only /ecma262/multipage/<chapter>.html paths are allowed, "
                         f"got '{parts.path}'"}
    if not parts.fragment or not ANCHOR.match(parts.fragment):
        return {"error": "the URL must end with a #section-anchor"}
    return parts._replace(fragment="", query="").geturl(), parts.fragment


def _strip_markup(chunk: str) -> str:
    chunk = re.sub(r"</(p|li|tr|emu-alg|h1|h2|dt|dd)>", "\n", chunk)
    chunk = re.sub(r"<li\b", "\n<li", chunk)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = html_lib.unescape(chunk)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in chunk.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _extract_section(page: str, anchor: str) -> str | None:
    """Вирізає підрозділ: від <emu-clause id="якір"> до наступного <emu-clause."""
    # Сайт віддає мініфіковану розмітку, де значення атрибутів без лапок:
    # <emu-clause id=sec-array.prototype.flat type="...">. Приймаємо обидві форми.
    m = re.search(r'<emu-clause[^>]*\bid=["\']?' + re.escape(anchor)
                  + r'["\']?(?=[\s>])', page)
    if not m:
        return None
    tail = page[m.start():]
    nxt = tail.find("<emu-clause", 1)
    return _strip_markup(tail[:nxt] if nxt != -1 else tail)


def _cache_path(url: str, anchor: str) -> pathlib.Path:
    digest = hashlib.sha256(f"{url}#{anchor}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.txt"


def fetch_spec(url: str) -> dict:
    checked = _validate(url)
    if isinstance(checked, dict):
        return checked
    page_url, anchor = checked

    cached = _cache_path(page_url, anchor)
    if cached.exists():
        text = cached.read_text(encoding="utf-8").split("\n\n", 1)[1]
        return {"source": "live tc39.es (cached), NOT the local excerpts",
                "url": f"{page_url}#{anchor}", "anchor": anchor,
                "cite_as": f"[live:{anchor}]", "cached": True, "text": text}

    req = urllib.request.Request(
        page_url, headers={"User-Agent": "agent0826-practice-m4"})
    try:
        with _opener.open(req, timeout=TIMEOUT_SEC) as resp:
            raw = resp.read(MAX_PAGE_BYTES + 1)
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}: {e}"}
    if len(raw) > MAX_PAGE_BYTES:
        return {"error": f"page exceeds {MAX_PAGE_BYTES} bytes; "
                         "this does not look like a multipage chapter"}

    section = _extract_section(raw.decode("utf-8", errors="replace"), anchor)
    if section is None:
        return {"error": f"anchor '{anchor}' not found on {page_url}; "
                         "check the chapter and the anchor spelling"}

    truncated = len(section) > MAX_CHARS
    text = section[:MAX_CHARS]

    CACHE_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    cached.write_text(f"{page_url}#{anchor} · отримано {stamp}\n\n{text}",
                      encoding="utf-8")

    return {"source": "live tc39.es, NOT the local excerpts",
            "url": f"{page_url}#{anchor}", "anchor": anchor,
            "cite_as": f"[live:{anchor}]", "cached": False,
            "truncated": truncated, "text": text}


def register() -> None:
    """Додає fetch_spec у курсовий IMPL. Той самий запобіжник, що в team."""
    if TOOL_NAME in course_backend.IMPL \
            and course_backend.IMPL[TOOL_NAME] is not fetch_spec:
        raise RuntimeError(
            f"Ім'я {TOOL_NAME} уже зайняте іншою реалізацією в IMPL.")
    course_backend.IMPL[TOOL_NAME] = fetch_spec
