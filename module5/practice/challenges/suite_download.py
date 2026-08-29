"""
ЧЕЛЕНДЖ · решта набору специфікацій ECMAScript (ECMA-402, 404, 414) і вільні
документи з її нормативних посилань. $0.

Основний корпус — ECMA-262, мова. Поруч із нею Ecma видає ще три документи, що
разом із 262 складають «набір специфікацій ECMAScript»:

    ECMA-402  Internationalization API — об'єкт Intl: Collator, DateTimeFormat,
              NumberFormat, PluralRules, Locale тощо. Живе на tc39.es, у тій
              самій розмітці, що й 262, але однією сторінкою на мегабайт.
    ECMA-404  The JSON Data Interchange Syntax — шістнадцять сторінок PDF.
    ECMA-414  ECMAScript Specification Suite — десять сторінок PDF, перелік того,
              які стандарти входять у набір і яких видань.

Скрипт кладе їх у practice/docs-suite/ у тому самому вигляді, що й документи
262: три рядки шапки, заголовки підрозділів окремими рядками, абзаци через
порожній рядок. Імена файлів мають префікс стандарту — 402-08-intl-object.txt,
404-json.txt, 414-suite.txt, — бо розділи 402 теж нумеруються з одиниці, і без
префікса ідентифікатори фрагментів зіткнулися б із 262.

Тека docs-suite/ сама по собі набором не є: набір PRACTICE_DOCS=suite — це
docs-full/ (уся 262) плюс docs-suite/, і збирає його common/corpus.py. Так
жоден документ 262 не лежить двічі.

ЯК ЧИТАЮТЬСЯ PDF

Текст із PDF дістає pypdf; це єдина залежність практики понад курсові. У
витягнутому тексті трапляються розриви слів («inter change», «abou t») — так
розкладено літери у самому файлі, і скрипт цього не лагодить, щоб не
вигадувати слова. Колонтитули, номери сторінок, зміст із крапками і сторінка
з ліцензією прибираються; вступ лишається перед першим розділом.

НОРМАТИВНІ ПОСИЛАННЯ ECMA-402

Розділ 3 ECMA-402 перелічує документи, без яких її не прочитати: кодований
набір символів ISO/IEC 10646, коди валют ISO 4217, RFC 4647, база часових
поясів IANA, сам Unicode і три його звіти. Стандарти ISO платні, база IANA —
таблиці, а не текст, Unicode як книга завеликий; решта — вільний текст, і
скрипт кладе його поруч із 402 десятьма документами. Шість із них розділ 3
називає прямо; решта частин LDML додана понад перелік, бо на них стоять
конкретні частини Intl: 4 і 5 — Intl.DateTimeFormat і Intl.Collator, 6 —
дані локалей, до яких 402 відсилає щоразу, коли каже «візьміть locale data».
Частина 7 до Intl стосунку не має і взята на прохання власника, щоб набір
LDML лежав повністю:

    rfc4647-matching-of-language-tags  зіставлення мовних тегів (localeMatcher)
    uax29-text-segmentation            межі графем, слів, речень (Intl.Segmenter)
    uts10-collation-algorithm          порівняння рядків (Intl.Collator)
    uts35-1-core                       LDML, частина 1: ідентифікатори локалей
    uts35-2-general                    LDML, частина 2: зокрема ідентифікатори одиниць
    uts35-3-numbers                    LDML, частина 3: числа і правила множини
    uts35-4-dates                      LDML, частина 4: дати, час, часові пояси
    uts35-5-collation                  LDML, частина 5: налаштування сортування
    uts35-6-supplemental               LDML, частина 6: дані локалей — likely
                                       subtags, правила множини, валютні й
                                       тижневі дані, часові пояси, одиниці
    uts35-7-keyboards                  LDML, частина 7: розкладки клавіатури

Імена починаються з літер, тому номера документа ці файли не мають і, як і
документи 402, дістаються лише маршрутові GENERAL.

RFC береться як текст із rfc-editor.org: колонтитули сторінок, зміст і
кінцевий юридичний блок прибираються, а заголовки «2.1.  Basic Language
Range» записуються як «2.1 Basic Language Range» — так їх упізнає поділ
корпусу. Звіти Unicode — це HTML: розмітка розбирається на блоки, абзаци й
заголовки стають окремими рядками, рядки таблиць — рядками з роздільником
«|», а розділи «Status», «Contents», «Parts», «Acknowledgments» і
«Modifications» викидаються. У частинах UTS #35 номерів розділів у HTML
немає — їх домальовує стиль сторінки, — тож скрипт нумерує заголовки сам,
рівень у рівень від першого після змісту. Рахунок збігається з посиланнями
402 на «Section 3» частини 1 і «Section 6.2» частини 2; «Section 5.1.1
Operands» частини 3 у LDML 48.2 стала 6.1.1, бо перед нею з'явився розділ
«Rational Numbers».

МЕЖІ

Лише https і лише чотири хости — tc39.es, ecma-international.org,
www.rfc-editor.org і www.unicode.org; відповідь більша за MAX_BYTES
відкидається; між зверненнями пауза. Наявні файли не перезаписуються без
--refresh.

ЩО ЗМІНИЛОСЯ НАГОРІ ЗА ТЕЧІЄЮ

Про це питає --status, нічого не записуючи. Тут звірка виходить повна, на
відміну від docs-full/. ECMA-402 приходить однією сторінкою, тож і перелік
розділів, і вміст кожного з них коштують одне звернення. Вільні документи й PDF
питаються умовним запитом «чи змінилося після нашої дати» — дату скрипт бере з
шапки нашого ж документа, — і unicode.org із rfc-editor.org на це відповідають
чесно, тілом не вантажачи.

Окремо --status кричить про зсув розділів ECMA-402: імена файлів несуть номер
розділу, тому вклинений розділ перейменовує всі наступні, а за іменами їдуть
ідентифікатори фрагментів і номери точок у Qdrant. Маршрутів спеціалістів це не
зачіпає — документи інших стандартів бачить лише GENERAL.

    python -m practice.challenges.suite_download             # завантажити відсутнє
    python -m practice.challenges.suite_download --list      # що буде записано, без запису
    python -m practice.challenges.suite_download --status    # що змінилося, нічого не пише
    python -m practice.challenges.suite_download --manifest  # зібрати index.json з того, що на диску
    python -m practice.challenges.suite_download --refresh   # перезавантажити все наново
    python -m practice.challenges.suite_download --refresh uts10-collation-algorithm   # лише один
"""

import io
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from practice.challenges import manifest
from practice.challenges import spec_download as sd

DOCS_SUITE = pathlib.Path(__file__).resolve().parent.parent / "docs-suite"

ALLOWED_HOSTS = {"tc39.es", "ecma-international.org",
                 "www.rfc-editor.org", "www.unicode.org"}
MAX_BYTES = 20_000_000
TIMEOUT_SEC = 60
PAUSE_SEC = 1.0

URL_402 = "https://tc39.es/ecma402/"
PDFS = {
    "404-json":  ("https://ecma-international.org/wp-content/uploads/"
                  "ECMA-404_2nd_edition_december_2017.pdf",
                  "ECMA-404 The JSON Data Interchange Syntax, 2nd edition"),
    "414-suite": ("https://ecma-international.org/wp-content/uploads/"
                  "ECMA-414_3rd_edition_december_2017.pdf",
                  "ECMA-414 ECMAScript Specification Suite, 3rd edition"),
}
# Вільні документи з розділу 3 ECMA-402. Третій елемент — як читати відповідь:
# «rfc» — текст RFC, «report» — HTML звіту з номерами розділів у заголовках,
# «ldml» — HTML частини UTS #35, де номери треба дописати самим.
REFERENCES = {
    "rfc4647-matching-of-language-tags": (
        "https://www.rfc-editor.org/rfc/rfc4647.txt",
        "RFC 4647 Matching of Language Tags", "rfc"),
    "uax29-text-segmentation": (
        "https://www.unicode.org/reports/tr29/",
        "Unicode Standard Annex #29: Unicode Text Segmentation", "report"),
    "uts10-collation-algorithm": (
        "https://www.unicode.org/reports/tr10/",
        "Unicode Technical Standard #10: Unicode Collation Algorithm", "report"),
    "uts35-1-core": (
        "https://www.unicode.org/reports/tr35/",
        "Unicode Technical Standard #35: LDML Part 1: Core", "ldml"),
    "uts35-2-general": (
        "https://www.unicode.org/reports/tr35/tr35-general.html",
        "Unicode Technical Standard #35: LDML Part 2: General", "ldml"),
    "uts35-3-numbers": (
        "https://www.unicode.org/reports/tr35/tr35-numbers.html",
        "Unicode Technical Standard #35: LDML Part 3: Numbers", "ldml"),
    "uts35-4-dates": (
        "https://www.unicode.org/reports/tr35/tr35-dates.html",
        "Unicode Technical Standard #35: LDML Part 4: Dates", "ldml"),
    "uts35-5-collation": (
        "https://www.unicode.org/reports/tr35/tr35-collation.html",
        "Unicode Technical Standard #35: LDML Part 5: Collation", "ldml"),
    "uts35-6-supplemental": (
        "https://www.unicode.org/reports/tr35/tr35-info.html",
        "Unicode Technical Standard #35: LDML Part 6: Supplemental", "ldml"),
    "uts35-7-keyboards": (
        "https://www.unicode.org/reports/tr35/tr35-keyboards.html",
        "Unicode Technical Standard #35: LDML Part 7: Keyboards", "ldml"),
}

# Верхній розділ або додаток однієї сторінки ecmarkup: атрибути там без лапок.
_TOP = re.compile(r"<(emu-clause|emu-annex) id=([^\s>]+)[^>]*>\s*<h1><span class=secnum>"
                  r"([0-9]+|Annex [A-Z])(?=</span>|\s*<span)")
_HEADING = re.compile(r"^\d+(?:\.\d+)*\s+\S")
_PAGE_NUMBER = re.compile(r"^\s*(\d+|[ivx]+)\s*$")


def _fetch(url: str) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise SystemExit(f"Адреса поза дозволеними: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "agent0826-practice/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit(f"Відповідь більша за {MAX_BYTES} байтів: {url}")
    return data


# ── ECMA-402: одна сторінка → документ на верхній розділ ─────────────────

def chapters_402(page: str) -> list[tuple[str, str, str]]:
    """(id, номер, html розділу) для кожного верхнього розділу і додатків A/B."""
    hits = list(_TOP.finditer(page))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(page)
        cid, num = m.group(2), m.group(3)
        if cid in ("sec-colophon", "sec-copyright-and-software-license"):
            continue
        out.append((cid, num, page[m.start():end]))
    if not out:
        raise SystemExit("На сторінці ECMA-402 не знайдено жодного розділу — "
                         "розмітка змінилася, скрипт треба поправити.")
    return out


def _slug(cid: str) -> str:
    return re.sub(r"^(sec-|annex-)", "", cid)


def name_402(num: str, cid: str) -> str:
    tag = f"{int(num):02d}" if num.isdigit() else num.replace("Annex ", "")
    return f"402-{tag}-{_slug(cid)}.txt"


def document_402(chunk: str, cid: str, stamp: str) -> str:
    m = sd._H1.search(chunk)
    title = sd._strip(m.group(1)).replace("\n", " ").strip() if m else cid
    body = sd._strip(chunk)
    return f"# {title}\n# джерело: {URL_402}#{cid}\n# отримано: {stamp}\n\n{body}\n"


# ── ECMA-404 і ECMA-414: PDF → текст ──────────────────────────────────────

def pdf_text(data: bytes) -> list[str]:
    try:
        import pypdf
    except ImportError:
        raise SystemExit("Потрібен pypdf: .venv/bin/pip install pypdf")
    reader = pypdf.PdfReader(io.BytesIO(data))
    lines = []
    for page in reader.pages:
        lines.extend((page.extract_text() or "").splitlines())
    return lines


def _keep(line: str) -> bool:
    s = line.strip()
    if not s or "Ecma International" in s and ("©" in s or "©" in line):
        return False
    if _PAGE_NUMBER.match(s) or "......" in s:
        return False
    return True


def clean_pdf(lines: list[str]) -> str:
    """Вступ плюс тіло від останнього «1 Scope»; колонтитули і зміст геть."""
    lines = [re.sub(r"[ \t]+", " ", ln).rstrip() for ln in lines]
    starts = [i for i, ln in enumerate(lines) if re.match(r"^1 Scope\s*$", ln)]
    if not starts:
        raise SystemExit("У PDF не знайдено розділу «1 Scope» — текст видобуто не так, як очікувалося.")
    body = lines[starts[-1]:]
    intro = []
    intro_at = [i for i, ln in enumerate(lines[:starts[-1]]) if ln.strip() == "Introduction"]
    if intro_at:
        for ln in lines[intro_at[0] + 1:starts[-1]]:
            if ln.strip().upper().startswith("COPYRIGHT") or ln.lstrip().startswith("©") \
                    or "......" in ln or ln.strip() == "Contents":
                break
            intro.append(ln)
    out = []
    for ln in intro + body:
        if not _keep(ln):
            continue
        s = ln.strip()
        if _HEADING.match(s):
            out.append("")
            out.append(s)
            out.append("")
            continue
        # Кінець речення і наступний рядок з великої літери — межа абзацу.
        if out and out[-1] and re.search(r"[.:;]$", out[-1]) and s[:1].isupper():
            out.append("")
        out.append(s)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def document_pdf(data: bytes, title: str, url: str, stamp: str) -> str:
    body = clean_pdf(pdf_text(data))
    return f"# {title}\n# джерело: {url}\n# отримано: {stamp}\n\n{body}\n"


# ── RFC 4647: текст → текст без колонтитулів ─────────────────────────────

_RFC_FOOTER = re.compile(r"^\S.*\[Page \d+\]$")
_RFC_HEADER = re.compile(r"^RFC \d+ {2,}.* {2,}[A-Z][a-z]+ \d{4}$")
_RFC_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")


def clean_rfc(text: str) -> str:
    """Текст RFC як є, без колонтитулів сторінок, змісту з крапками і
    кінцевого юридичного блоку. Заголовки в RFC стоять на нульовій колонці з
    крапкою після номера, тіло — з відступом у три пробіли: перші стають
    рядками «2.1 Basic Language Range», у другого відступ знімається."""
    out = []
    for ln in text.replace("\f", "").splitlines():
        ln = ln.rstrip()
        if _RFC_FOOTER.match(ln) or _RFC_HEADER.match(ln) or "......" in ln:
            continue
        if ln == "Full Copyright Statement":
            break
        m = _RFC_HEADING.match(ln)
        if m:
            out.extend(["", f"{m.group(1)} {m.group(2)}", ""])
            continue
        out.append(re.sub(r"^ {3}", "", ln))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")


# ── Звіти Unicode: HTML → блоки → текст ───────────────────────────────────

_BLOCK = {"p", "div", "li", "tr", "table", "ul", "ol", "dl", "dt", "dd", "blockquote",
          "pre", "h6", "section", "figure", "caption"}
_SKIP = {"script", "style", "head", "title"}
_LEVEL = {"h1": 0, "h2": 1, "h3": 2, "h4": 3, "h5": 4}
_DROP = {"Status", "Parts", "Acknowledgments", "Acknowledgements", "Modifications"}
_INDENT = "    "
# Рядок, який поділ корпусу прийняв би за заголовок розділу: число, пробіл, слово.
_LOOKS_LIKE_HEADING = re.compile(r"^\d+(?:\.\d+)*\s+\S")


class _Blocks(HTMLParser):
    """Розбирає сторінку на блоки: («h», рівень, заголовок) і («t», текст).
    Поза <pre> пробіли стискаються; всередині переноси рядків лишаються, а
    кожен рядок дістає відступ у чотири пробіли. Комірки таблиці розділяє
    « | », пункт списку починається з «- »."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._buf = []
        self._skip = 0
        self._pre = 0
        self._level = None

    def _flush(self):
        text = "".join(self._buf)
        if text.strip():
            self.blocks.append(("t", text))
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "pre":
            self._pre += 1
            self._buf.append("\n" + _INDENT)
        if tag in _LEVEL:
            self._flush()
            self._level = _LEVEL[tag]
        elif tag in ("td", "th"):
            self._buf.append(" | ")
        elif tag == "li":
            self._buf.append("\n- ")
        elif tag in _BLOCK or tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "pre":
            self._pre = max(0, self._pre - 1)
        if tag in _LEVEL:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._buf = []
            if text and self._level is not None:
                self.blocks.append(("h", self._level, text))
            self._level = None
        elif tag in _BLOCK or tag == "li":
            self._buf.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._pre:
            self._buf.append(data.replace("\n", "\n" + _INDENT))
        else:
            self._buf.append(re.sub(r"\s+", " ", data))


def number_headings(blocks: list) -> list:
    """Дописує номери заголовкам частини LDML: рахунок рівень у рівень
    від першого заголовка після змісту, як на самій сторінці."""
    counters = [0, 0, 0, 0]
    started = False
    out = []
    for b in blocks:
        if b[0] != "h" or b[1] < 1:
            out.append(b)
            continue
        if not started:
            started = b[2].startswith("Contents")
            out.append(b)
            continue
        level = b[1]
        counters[level - 1] += 1
        for k in range(level, 4):
            counters[k] = 0
        num = ".".join(str(c) for c in counters[:level])
        out.append(("h", level, f"{num} {b[2]}"))
    return out


def drop_sections(blocks: list) -> list:
    """Викидає розділи, що не є змістом звіту: статус чернетки, зміст,
    перелік частин, подяки, історію змін. Розділ триває до наступного
    заголовка того самого або вищого рівня."""
    out, cut = [], None
    for b in blocks:
        if b[0] == "h":
            level = b[1]
            name = re.sub(r"^\d+(?:\.\d+)*\s+", "", b[2])
            if cut is not None and level <= cut:
                cut = None
            if cut is None and (name in _DROP or name.startswith("Contents")):
                cut = level
                continue
        if cut is None:
            out.append(b)
    return out


def render_blocks(blocks: list) -> str:
    """Заголовки — окремими рядками з порожніми навколо. Поділ корпусу
    вважає заголовком рядок «число, пробіл, назва» без відступу, тому рядки
    таблиць зберігають початковий «|», а рядки з <pre> і взагалі будь-який
    рядок тексту такого вигляду — відступ: інакше приклад даних «0385 0021;
    …» або речення «1.00 gets the same category as 1.» відкрили б новий
    розділ."""
    lines = []
    for b in blocks:
        if b[0] == "h":
            lines.extend(["", b[2], ""])
            continue
        for ln in b[1].splitlines():
            flat = re.sub(r"[ \t\xa0]+", " ", ln).strip()
            code = ln.startswith(_INDENT) or _LOOKS_LIKE_HEADING.match(flat)
            lines.append(_INDENT + flat if code and flat else flat)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def document_reference(data: bytes, key: str, stamp: str) -> str:
    url, title, kind = REFERENCES[key]
    text = data.decode("utf-8")
    if kind == "rfc":
        body = clean_rfc(text)
    else:
        parser = _Blocks()
        parser.feed(text)
        blocks = parser.blocks
        if kind == "ldml":
            blocks = number_headings(blocks)
        body = render_blocks(drop_sections(blocks))
    if not re.search(r"^\d+(?:\.\d+)* \S", body, re.M):
        raise SystemExit(f"У {key} не знайдено жодного нумерованого заголовка — "
                         f"розмітка змінилася, скрипт треба поправити.")
    return f"# {title}\n# джерело: {url}\n# отримано: {stamp}\n\n{body}\n"


# ── точка входу ───────────────────────────────────────────────────────────

# ── Стан набору: що змінилося нагорі за течією ────────────────────────────

def id_of(file: str) -> str:
    """Ідентифікатор документа з імені файла.

    Для розділів ECMA-402 це слаг розділу без номера («402-08-intl-object.txt»
    → «intl-object»), бо номер розділу — це те, що зсувається. Для вільних
    документів ім'я файла і є ключем таблиці адрес, там зсуву не буває.
    """
    stem = file[:-4] if file.endswith(".txt") else file
    if stem.startswith("402-"):
        _, _, slug = stem[4:].partition("-")
        return slug or stem[4:]
    return stem


def fetch_if_newer(url: str, since: str) -> tuple[str, bytes]:
    """Документ, якщо він змінився після дати, коли ми його брали.

    Перше значення — «304», коли сервер каже, що документ не змінювався; «200»,
    коли віддав його; рядок, що починається зі «збій», коли не вийшло — причина
    прямо в ньому. unicode.org і rfc-editor.org відповідають на таке питання
    чесно, тому звірка вільних документів коштує майже нічого.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        return ("збій: адреса поза дозволеними", b"")
    headers = {"User-Agent": "agent0826-practice/1.0"}
    if since:
        try:
            headers["If-Modified-Since"] = sd.since_header(since)
        except ValueError:
            pass
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return (f"збій: більше за {MAX_BYTES} байтів", b"")
        return ("200", data)
    except urllib.error.HTTPError as e:
        return ("304", b"") if e.code == 304 else (f"збій: HTTP {e.code}", b"")
    except urllib.error.URLError as e:
        return (f"збій: {e.reason}", b"")


def write_manifest() -> int:
    """Збирає index.json з документів, які вже лежать на диску. Без мережі."""
    if not DOCS_SUITE.exists() or not any(DOCS_SUITE.glob("*.txt")):
        print(f"У {DOCS_SUITE} немає жодного .txt — нічого описувати.")
        return 1
    data = manifest.build(DOCS_SUITE, id_of, time.strftime("%Y-%m-%d"))
    path = manifest.save(DOCS_SUITE, data)
    print(f"── Маніфест {path.name}: {len(data['documents'])} документів ──")
    return 0


def _verdict(was: dict | None, fresh_body: str) -> str:
    """«новий», «без змін» або «змінився» — за сумою тіла документа."""
    if was is None:
        return "новий"
    if was.get("sha256") == manifest.digest(fresh_body):
        return "без змін"
    return (f"ЗМІНИВСЯ: було {was.get('chars')} символів, "
            f"стало {len(fresh_body)}")


def status() -> int:
    """Що змінилося в наборі. Нічого не записує.

    Тут звірка повна, на відміну від docs-full/: уся ECMA-402 приходить однією
    сторінкою, тож і перелік розділів, і їхній вміст коштують одне звернення, а
    вільні документи звіряються умовним запитом, на який сервер здебільшого
    відповідає «не змінювався» і тіла не шле.
    """
    print(f"── Стан {DOCS_SUITE.name}/ ──")
    data = manifest.load(DOCS_SUITE)
    if data is None:
        disk = sorted(DOCS_SUITE.glob("*.txt"))
        known = {id_of(p.name): {"file": p.name} for p in disk}
        was_402 = [id_of(p.name) for p in disk if p.name.startswith("402-")]
        print("  маніфесту немає, порівнюю з іменами файлів на диску "
              "(зібрати маніфест: --manifest)")
    else:
        known = manifest.by_id(data)
        was_402 = [d["id"] for d in data["documents"]
                   if d["file"].startswith("402-")]

    stamp = time.strftime("%Y-%m-%d")
    same = changed = added = failed = 0

    print(f"── ECMA-402 з {URL_402} ──")
    try:
        page = _fetch(URL_402).decode("utf-8")
    except urllib.error.URLError as e:
        print(f"  ЗБІЙ: {e.reason}")
        return 1
    plan = [(name_402(num, cid), cid, chunk)
            for cid, num, chunk in chapters_402(page)]
    now_402 = [_slug(cid) for _, cid, _ in plan]
    print(f"  розділів на сторінці {len(now_402)}, на нашому боці {len(was_402)}")
    manifest.report_shift(was_402, now_402, [name for name, _, _ in plan], known,
                          "документи ECMA-402 маршрутам спеціалістів не належать —\n"
                          "їх бачить лише GENERAL, тож FAMILIES зсув не зачіпає.")
    for (_, cid, chunk), doc in zip(plan, now_402):
        body = manifest.body_of(document_402(chunk, cid, stamp))
        verdict = _verdict(known.get(doc), body)
        if verdict == "без змін":
            same += 1
        elif verdict == "новий":
            print(f"  {doc}  новий, у нас його немає")
            added += 1
        else:
            print(f"  {doc}  {verdict}")
            changed += 1

    print("── Вільні документи і PDF: умовний запит ──")
    plain = [(key, url, title) for key, (url, title) in PDFS.items()]
    plain += [(key, url, title) for key, (url, title, _) in REFERENCES.items()]
    for key, url, title in plain:
        was = known.get(key)
        if was is None:
            print(f"  {key}  новий, у нас його немає")
            added += 1
            continue
        code, payload = fetch_if_newer(url, was.get("fetched", ""))
        if code.startswith("збій"):
            print(f"  {key}  {code}")
            failed += 1
        elif code == "304":
            print(f"  {key}  без змін (сервер: не змінювався з {was.get('fetched')})")
            same += 1
        else:
            try:
                if key in PDFS:
                    body = manifest.body_of(document_pdf(payload, title, url, stamp))
                else:
                    body = manifest.body_of(document_reference(payload, key, stamp))
            except SystemExit as e:
                print(f"  {key}  ЗБІЙ розбору: {e}")
                failed += 1
                time.sleep(PAUSE_SEC)
                continue
            verdict = _verdict(was, body)
            if verdict == "без змін":
                print(f"  {key}  без змін (сума тіла збіглася)")
                same += 1
            else:
                print(f"  {key}  {verdict}")
                changed += 1
        time.sleep(PAUSE_SEC)

    expected = [name for name, _, _ in plan]
    expected += [f"{key}.txt" for key in PDFS]
    expected += [f"{key}.txt" for key in REFERENCES]
    extra = manifest.orphans(DOCS_SUITE, expected)
    if extra:
        print(f"── Сироти: {len(extra)} файлів, яких немає в переліку адрес ──")
        for name in extra:
            print(f"  {name}")
        print("  нічого не видалено — що з ними робити, вирішувати вам")

    print(f"── Без змін {same}, змінилося {changed}, нових {added}, "
          f"збоїв {failed}. Не записано нічого ──")
    return 0


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--manifest" in argv:
        return write_manifest()
    if "--status" in argv:
        return status()
    listing = "--list" in argv
    refresh = "--refresh" in argv
    # Усе, що не прапорець, — ідентифікатор документа: «--refresh uts10-collation-
    # algorithm» перезаписує один документ, «--refresh» без імен — увесь набір.
    targets = {a for a in argv if not a.startswith("-")}
    stamp = time.strftime("%Y-%m-%d")

    print(f"── ECMA-402 з {URL_402} ──")
    page = _fetch(URL_402).decode("utf-8")
    plan = [(name_402(num, cid), cid, chunk) for cid, num, chunk in chapters_402(page)]
    print(f"  верхніх розділів і додатків: {len(plan)}")

    if not listing:
        DOCS_SUITE.mkdir(exist_ok=True)
    written = skipped = total = 0

    def wanted(path: pathlib.Path) -> bool:
        """Чи оновлювати саме цей документ. Без імен у рядку — всі."""
        return refresh and (not targets
                            or id_of(path.name) in targets
                            or path.name in targets)

    def put(path: pathlib.Path, make) -> None:
        nonlocal written, skipped, total
        if listing:
            print(f"  {path.name}")
            return
        if path.exists() and not wanted(path):
            size = len(path.read_text(encoding="utf-8"))
            total += size
            skipped += 1
            print(f"  {path.name}  уже є, {size} символів")
            return
        text = make()
        path.write_text(text, encoding="utf-8")
        written += 1
        total += len(text)
        print(f"  {path.name}  {len(text)} символів")

    for name, cid, chunk in plan:
        put(DOCS_SUITE / name, lambda chunk=chunk, cid=cid: document_402(chunk, cid, stamp))

    for key, (url, title) in PDFS.items():
        print(f"── {title} з {url} ──")
        path = DOCS_SUITE / f"{key}.txt"
        if listing or (path.exists() and not wanted(path)):
            put(path, None)
            continue
        time.sleep(PAUSE_SEC)
        try:
            data = _fetch(url)
        except urllib.error.URLError as e:
            print(f"  {path.name}  ЗБІЙ: {e.reason}")
            continue
        put(path, lambda data=data, title=title, url=url: document_pdf(data, title, url, stamp))

    for key, (url, title, kind) in REFERENCES.items():
        print(f"── {title} з {url} ──")
        path = DOCS_SUITE / f"{key}.txt"
        if listing or (path.exists() and not wanted(path)):
            put(path, None)
            continue
        time.sleep(PAUSE_SEC)
        try:
            data = _fetch(url)
        except urllib.error.URLError as e:
            print(f"  {path.name}  ЗБІЙ: {e.reason}")
            continue
        put(path, lambda data=data, key=key: document_reference(data, key, stamp))

    if listing:
        print("── Лише перелік; нічого не записано ──")
    else:
        print(f"── Готово: записано {written}, лишено як є {skipped}, разом {total} символів ──")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
