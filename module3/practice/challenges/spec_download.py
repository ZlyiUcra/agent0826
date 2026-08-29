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

ЩО ЗМІНИЛОСЯ НАГОРІ ЗА ТЕЧІЄЮ

Про це питає --status, нічого не записуючи. Дешева перевірка — сам зміст
видання: скільки в ньому розділів, у якому порядку, і чи збігається це з
маніфестом. Вона коштує одне звернення і ловить найгірше — зсув.

Зсув — це коли розділ вклинили або прибрали. Імена файлів тут несуть позицію у
змісті, а не номер розділу специфікації, тому все, що стоїть після вклиненого,
дістає інше ім'я: 22-text-processing.txt стає 23-text-processing.txt. За іменем
їде ідентифікатор фрагмента, номер точки в Qdrant і номер розділу, яким задані
маршрути спеціалістів у base/team.py — маршрут почне читати сусідній розділ,
лишаючись формально справним, бо номер і далі буде числом. Тому про зсув
--status каже окремо і голосно.

Вміст розділів дешево не звіряється. tc39.es перезбирає видання на кожен злитий
запит, тож ETag там міняється мало не щодня незалежно від того, чи змінився
потрібний розділ; єдиний чесний сигнал — сума тексту після розбору, а для неї
розділ треба завантажити. Це робить --status --deep.

    python -m practice.challenges.spec_download                  # завантажити відсутнє
    python -m practice.challenges.spec_download --list           # перелік розділів, без завантаження
    python -m practice.challenges.spec_download --status         # що змінилося у змісті, нічого не пише
    python -m practice.challenges.spec_download --status --deep  # ще й звірити вміст розділів
    python -m practice.challenges.spec_download --manifest       # зібрати index.json з того, що на диску
    python -m practice.challenges.spec_download --refresh        # перезавантажити все наново
    python -m practice.challenges.spec_download --refresh text-processing   # лише один розділ
"""

import datetime
import email.utils
import html as html_lib
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

from practice.challenges import manifest

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


def since_header(day: str) -> str:
    """Дата з шапки документа у вигляді, який розуміє If-Modified-Since."""
    when = datetime.datetime.strptime(day, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc)
    return email.utils.format_datetime(when, usegmt=True)


def fetch_if_newer(url: str, since: str) -> tuple[str, str]:
    """Сторінка, якщо вона змінилася після дати, коли ми її брали.

    Повертає («304», ""), коли сервер каже, що не змінювалася; («200», текст),
    коли віддав сторінку; («збій», причина), коли не вийшло. Питати «чи є щось
    новіше за нашу дату» дешевше, ніж качати мегабайт наосліп, а дата в нас уже
    є — вона в шапці кожного документа.
    """
    headers = {"User-Agent": "agent0826-practice"}
    if since:
        try:
            headers["If-Modified-Since"] = since_header(since)
        except ValueError:
            pass
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            raw = resp.read(MAX_PAGE_BYTES + 1)
        if len(raw) > MAX_PAGE_BYTES:
            return ("збій", f"сторінка більша за {MAX_PAGE_BYTES} байтів")
        return ("200", raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return ("304", "") if e.code == 304 else ("збій", f"HTTP {e.code}")
    except urllib.error.URLError as e:
        return ("збій", str(e.reason))


def page_id(name: str) -> str:
    """Ідентифікатор розділу — слаг сторінки видання, без позиції і без .html."""
    return name[:-5] if name.endswith(".html") else name


def file_name(position: int, name: str) -> str:
    """Ім'я файла розділу: позиція у змісті плюс слаг сторінки. Позиція тут
    і є тим, що зсувається, коли у зміст вклинюють новий розділ."""
    return f"{position:02d}-{page_id(name)}.txt"


def id_of(file: str) -> str:
    """Ідентифікатор розділу з імені файла: 22-text-processing.txt →
    text-processing. Позицію відкидаємо саме тому, що вона нестала."""
    stem = file[:-4] if file.endswith(".txt") else file
    head, _, rest = stem.partition("-")
    return rest if head.isdigit() and rest else stem


def write_manifest() -> int:
    """Збирає index.json з документів, які вже лежать на диску. Без мережі:
    адреса й дата беруться з шапки кожного файла, сума рахується по тілу."""
    if not DOCS_FULL.exists() or not any(DOCS_FULL.glob("*.txt")):
        print(f"У {DOCS_FULL} немає жодного .txt — нічого описувати.")
        return 1
    data = manifest.build(DOCS_FULL, id_of, time.strftime("%Y-%m-%d"))
    path = manifest.save(DOCS_FULL, data)
    print(f"── Маніфест {path.name}: {len(data['documents'])} документів ──")
    return 0


FAMILIES_NOTE = (
    "FAMILIES у base/team.py задані номерами розділів, а номер тут — це позиція\n"
    "у змісті: після зсуву маршрут спеціаліста почне читати сусідній розділ\n"
    "і не поскаржиться, бо номер лишиться числом."
)


def status(deep: bool) -> int:
    """Що змінилося у виданні. Нічого не записує."""
    print(f"── Стан {DOCS_FULL.name}/ проти {BASE} ──")
    names = chapters()
    now = [page_id(n) for n in names]

    data = manifest.load(DOCS_FULL)
    if data is None:
        disk = sorted(DOCS_FULL.glob("*.txt"))
        was = [id_of(p.name) for p in disk]
        known = {id_of(p.name): {"file": p.name} for p in disk}
        print("  маніфесту немає, порівнюю з іменами файлів на диску "
              "(зібрати маніфест: --manifest)")
    else:
        was = manifest.ids(data)
        known = manifest.by_id(data)
    print(f"  у змісті видання {len(now)} розділів, на нашому боці {len(was)}")

    manifest.report_shift(was, now, [file_name(i, n) for i, n in enumerate(names, 1)],
                          known, FAMILIES_NOTE)

    extra = manifest.orphans(DOCS_FULL, [file_name(i, n)
                                         for i, n in enumerate(names, 1)])
    if extra:
        print(f"  сироти: {len(extra)} файлів, яких немає у змісті видання")
        for name in extra:
            print(f"      {name}")
        print("      нічого не видалено — що з ними робити, вирішувати вам")

    if not deep:
        print("  вміст розділів не звірявся: tc39.es перезбирає видання на кожен")
        print("    злитий запит, тож ETag тут не сигнал. Звірити: --status --deep")
        return 0

    stamp = time.strftime("%Y-%m-%d")
    same = changed = fresh_only = failed = 0
    print(f"── Звірка вмісту: до {len(names)} звернень ──")
    for i, name in enumerate(names, 1):
        doc = page_id(name)
        was = known.get(doc)
        if was is None:
            print(f"  {i:02d}  {doc}  новий, у нас його немає")
            fresh_only += 1
            continue
        code, payload = fetch_if_newer(BASE + name, was.get("fetched", ""))
        if code == "збій":
            print(f"  {i:02d}  {doc}  ЗБІЙ: {payload}")
            failed += 1
        elif code == "304":
            same += 1
        else:
            body = manifest.body_of(document(payload, BASE + name, stamp))
            if was.get("sha256") == manifest.digest(body):
                same += 1
            else:
                print(f"  {i:02d}  {doc}  ЗМІНИВСЯ: було {was.get('chars')} "
                      f"символів, стало {len(body)}")
                changed += 1
        time.sleep(PAUSE_SEC)
    print(f"── Без змін {same}, змінилося {changed}, нових {fresh_only}, "
          f"збоїв {failed}. Не записано нічого ──")
    return 0


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--manifest" in argv:
        return write_manifest()
    if "--status" in argv:
        return status("--deep" in argv)

    names = chapters()
    if "--list" in argv:
        print(f"── Розділів у багатосторінковому виданні: {len(names)} ──")
        for i, name in enumerate(names, 1):
            print(f"  {i:02d}  {name}")
        return 0

    refresh = "--refresh" in argv
    # Усе, що не прапорець, — ідентифікатор розділу: «--refresh text-processing»
    # перезаписує один документ, «--refresh» без імен — усе видання.
    targets = {a for a in argv if not a.startswith("-")}
    DOCS_FULL.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    print(f"── Вивантаження специфікації у {DOCS_FULL.name}/ · {len(names)} розділів ──")

    written = skipped = 0
    total_chars = 0
    for i, name in enumerate(names, 1):
        path = DOCS_FULL / file_name(i, name)
        chosen = refresh and (not targets or page_id(name) in targets
                              or path.name in targets)
        if path.exists() and not chosen:
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
