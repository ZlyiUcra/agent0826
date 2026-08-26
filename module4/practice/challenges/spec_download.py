"""
ЧЕЛЕНДЖ · вивантаження ВСІЄЇ специфікації ECMAScript у документи. $0.

Вісімнадцять документів у practice/docs/ — це околиця `sec-object-type`, вибрана
для основного завдання. Цей скрипт кладе поруч інший набір: усю специфікацію,
розділ за розділом, у practice/docs-full/. Потрібен він рівно для одного —
перевірити, як шар пошуку і агент поводяться на обсязі, більшому за навчальний.

ЧОМУ ОКРЕМА ТЕКА, А НЕ ДОКЛАДЕНО ДО НАЯВНИХ

Повна специфікація містить і ті розділи, що вже лежать у practice/docs/, тому
злиття двох наборів дало б кожен фрагмент двічі під різними ідентифікаторами.
Крім того, до вісімнадцяти документів прив'язані всі числа, записані в README і
CHECKLIST: 283 фрагменти, нижні межі схожості, місця правильних розділів у
вимірах. Підмішати до них решту специфікації означало б знецінити кожен із цих
записів. Тому набори живуть окремо, а вибирають між ними змінною оточення:

    PRACTICE_DOCS=core   вісімнадцять документів (типово)
    PRACTICE_DOCS=full   уся специфікація

ЩО САМЕ ЗАВАНТАЖУЄТЬСЯ

Багатосторінкове видання https://tc39.es/ecma262/multipage/ — по файлу на
розділ. Перелік розділів і їхній порядок беруться зі змісту самого видання, а не
з переліку в коді: специфікація жива, і розділи в ній з'являються.

Зі сторінки береться лише вміст `<div id=spec-container>`. Це не оптимізація, а
необхідність: три чверті кожної сторінки — бічне меню зі змістом усієї
специфікації, і без відсікання кожен документ починався б із того самого
переліку на півмегабайта.

Розмітка зчищається так, щоб вийшов той самий вигляд, що в наявних документах:
заголовок підрозділу окремим рядком («20.1.3.6 Object.prototype.toString ( )»),
абзаци через порожній рядок, кроки алгоритмів рядками з дефісом. Це не косметика
— саме по цих заголовках practice/common/corpus.py ділить документ на фрагменти.

ЩО СКРИПТ НЕ РОБИТЬ

Не перезаписує вже завантажене. Файл, який існує, лишається на місці, і скрипт
каже про це вголос; перезавантажити його можна лише явним прапорцем --refresh.
Мережа буває недоступна на середині, і мовчазне затирання наявних документів
зіпсованими — не та ціна, яку варто платити за зручність.

    python -m practice.challenges.spec_download            # завантажити відсутнє
    python -m practice.challenges.spec_download --list     # перелік розділів, без завантаження
    python -m practice.challenges.spec_download --refresh  # перезавантажити все наново
"""

import html as html_lib
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://tc39.es/ecma262/multipage/"
DOCS_FULL = pathlib.Path(__file__).resolve().parent.parent / "docs-full"

TIMEOUT_SEC = 60
PAUSE_SEC = 1.0          # пауза між зверненнями до чужого сервера
MAX_PAGE_BYTES = 20_000_000

# Розмітка видання мініфікована: значення атрибутів без лапок, а одразу за
# іменем файлу може стояти якір (href=indexed-collections.html#sec-...).
_HREF = re.compile(r"href=[\"']?([a-z0-9-]+\.html)[\"']?")
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_FIRST_CLAUSE_ID = re.compile(r"<emu-clause[^>]*\bid=[\"']?([\w.-]+)[\"']?[\s>]")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "agent0826-practice"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        raw = resp.read(MAX_PAGE_BYTES + 1)
    if len(raw) > MAX_PAGE_BYTES:
        raise SystemExit(f"{url}: сторінка більша за {MAX_PAGE_BYTES} байтів")
    return raw.decode("utf-8", errors="replace")


def chapters() -> list[str]:
    """Імена сторінок розділів у порядку змісту багатосторінкового видання."""
    toc = _get(BASE)
    seen, out = set(), []
    for name in _HREF.findall(toc):
        if name not in seen:
            seen.add(name)
            out.append(name)
    if not out:
        raise SystemExit("У змісті не знайдено жодного посилання на розділ — "
                         "розмітка сторінки змінилася, скрипт треба поправити.")
    return out


def _body(page: str) -> str:
    """Вміст сторінки без бічного меню: від spec-container до кінця."""
    start = page.find("<div id=spec-container")
    return page[start:] if start != -1 else page


def _strip(chunk: str) -> str:
    """Зчищає розмітку, лишаючи заголовки і абзаци окремими рядками."""
    chunk = re.sub(r"<(script|style)\b.*?</\1>", " ", chunk, flags=re.S)
    # Заголовок підрозділу: номер із <span class=secnum> і назва — одним рядком.
    chunk = re.sub(r"<h1[^>]*>", "\n\n", chunk)
    chunk = re.sub(r"</h1>", "\n\n", chunk)
    chunk = re.sub(r"<li\b[^>]*>", "\n- ", chunk)
    chunk = re.sub(r"</(p|li|tr|dd|dt|emu-alg|emu-note|emu-table|div)>", "\n", chunk)
    chunk = re.sub(r"<br\s*/?>", "\n", chunk)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = html_lib.unescape(chunk)

    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in chunk.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def _title(page: str) -> str:
    """Заголовок розділу: «20 Fundamental Objects»."""
    m = _H1.search(_body(page))
    if not m:
        return ""
    return _strip(m.group(1)).replace("\n", " ").strip()


def document(page: str, url: str, stamp: str) -> str:
    """Готовий текст документа: трирядкова шапка, порожній рядок, тіло."""
    title = _title(page)
    anchor = _FIRST_CLAUSE_ID.search(_body(page))
    source = f"{url}#{anchor.group(1)}" if anchor else url
    body = _strip(_body(page))
    return (f"# {title}\n# джерело: {source}\n# отримано: {stamp}\n\n{body}\n")


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    names = chapters()
    if "--list" in argv:
        print(f"── Розділів у багатосторінковому виданні: {len(names)} ──")
        for i, name in enumerate(names, 1):
            print(f"  {i:02d}  {name}")
        return 0

    refresh = "--refresh" in argv
    DOCS_FULL.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    print(f"── Вивантаження специфікації у {DOCS_FULL.name}/ · {len(names)} розділів ──")

    written = skipped = 0
    total_chars = 0
    for i, name in enumerate(names, 1):
        path = DOCS_FULL / f"{i:02d}-{name[:-5]}.txt"
        if path.exists() and not refresh:
            size = len(path.read_text(encoding="utf-8"))
            total_chars += size
            skipped += 1
            print(f"  {i:02d}/{len(names)}  {path.name}  уже є, {size} символів")
            continue
        url = BASE + name
        try:
            page = _get(url)
        except urllib.error.URLError as e:
            print(f"  {i:02d}/{len(names)}  {name}  ЗБІЙ: {e.reason}")
            continue
        text = document(page, url, stamp)
        path.write_text(text, encoding="utf-8")
        written += 1
        total_chars += len(text)
        print(f"  {i:02d}/{len(names)}  {path.name}  {len(text)} символів")
        time.sleep(PAUSE_SEC)

    print(f"── Готово: завантажено {written}, лишено як є {skipped}, "
          f"разом {total_chars} символів ──")
    print("  далі: PRACTICE_DOCS=full python -m practice.challenges.qdrant_store")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
