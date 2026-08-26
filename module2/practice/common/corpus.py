"""
СПІЛЬНЕ · документи практики і поділ їх на фрагменти.

Документи — вісімнадцять розділів специфікації ECMAScript навколо
`sec-object-type`: сам тип Object, екзотичні об'єкти (Array, String, Arguments,
TypedArray, Proxy та інші) і об'єктні обгортки String, Symbol, Number, Boolean.
Вони лежать у practice/docs/ як звичайні .txt і завантажені з
https://tc39.es/ecma262/ один раз, вручну. Код їх тільки читає: нічого не
завантажує з мережі, нічого не перезаписує.

Формат файлу: три рядки шапки, які починаються з «#» (заголовок розділу,
адреса джерела з якорем, дата вивантаження), порожній рядок, далі текст.
Шапка потрібна для посилання у відповіді агента, тому в тіло вона не потрапляє.

ЧОМУ ДОКУМЕНТІВ ВІСІМНАДЦЯТЬ, А ІНДЕКСУЄМО МИ ФРАГМЕНТИ

Розділи специфікації дуже різні за розміром: найменший (10.4.7, незмінний
прототип) — 1570 символів, найбільший (22.1, String Objects) — 52257, тобто
в тридцять три рази більший. Якби одиницею пошуку був цілий документ, то на
запит про `String.prototype.replace` пошук повернув би весь розділ 22.1:
п'ятдесят кілобайт тексту, з яких потрібні дві сотні символів. У промпт таке
не влізе, а якби й влізло — модель шукала б відповідь у стосі стороннього
тексту, і саме там беруться вигадані відповіді.

Тому індекс будується по фрагментах, а у відповідь агентові йде фрагмент разом
із номером свого розділу. Документів при цьому лишається вісімнадцять —
ділиться не документ, а те, що ми з нього дістаємо.

ДЕ ПРОХОДИТЬ МЕЖА ФРАГМЕНТА

Специфікація сама пронумерована: «22.1.3.19 String.prototype.replace ( ... )»
стоїть окремим рядком перед своїм текстом. Ця нумерація і є межею — фрагмент
починається з такого заголовка і триває до наступного. Різати за кількістю
символів наосліп не треба: підзаголовок уже позначає, де закінчується одна тема
і починається інша.

Залишається один випадок, який нумерація не покриває: підрозділ, довший за
`MAX_CHARS`. Такий ділиться далі по порожніх рядках, шматки нумеруються
(«частина 2 з 3») і кожен зберігає заголовок свого підрозділу, щоб посилання
не загубилося.
"""

import json
import os
import pathlib
import re

# Два набори документів, і вони навмисно не змішуються. «core» — вісімнадцять
# розділів навколо sec-object-type, ті самі, на яких зроблено всі виміри
# практики. «full» — уся специфікація, вивантажена challenges/spec_download.py
# у practice/docs-full/. Повна специфікація містить і розділи набору core, тому
# в одній купі кожен такий фрагмент трапився б двічі під різними
# ідентифікаторами, а числа, записані в README і CHECKLIST, перестали б
# стосуватися того, що лежить у теці. Вибір — змінною PRACTICE_DOCS.
DOC_SETS = {"core": "docs", "full": "docs-full"}
DOC_SET = os.getenv("PRACTICE_DOCS", "core")
if DOC_SET not in DOC_SETS:
    raise SystemExit(f"Невідомий набір документів '{DOC_SET}'. "
                     f"Доступні: {', '.join(sorted(DOC_SETS))}")

DOCS_DIR = pathlib.Path(__file__).resolve().parent.parent / DOC_SETS[DOC_SET]

# Межа розміру фрагмента. Її задає не смак, а вікно моделі ембедингів:
# e5-small читає 512 токенів і мовчки відрізає все, що далі. Текст специфікації
# щільний на розділові знаки й ідентифікатори, тому дає приблизно один токен на
# три символи — при межі 1800 п'ятнадцять фрагментів із 284 вилазили за вікно
# (найдовший — 616 токенів), і їхні хвости в індекс не потрапляли зовсім.
MAX_CHARS = 1400
# Нижче цієї межі окремий фрагмент не має сенсу: заголовок без тексту або
# одне речення-відсилання. Такий хвіст приклеюється до попереднього шматка.
MIN_CHARS = 200

# Рядок-заголовок специфікації: номер розділу, пробіл, назва.
# Обмеження довжини відсікає звичайні речення, що починаються з числа.
_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.{0,110})$")


class Document:
    """Один файл із practice/docs/ разом із шапкою."""

    def __init__(self, path: pathlib.Path):
        raw = path.read_text(encoding="utf-8").splitlines()
        head = [ln[1:].strip() for ln in raw if ln.startswith("#")][:3]
        body = "\n".join(raw[len(head):]).strip("\n")

        self.doc_id = path.stem                      # напр. 18-string-objects
        self.path = path
        self.title = head[0] if head else path.stem  # напр. 22.1 String Objects
        self.url = ""
        self.fetched = ""
        for line in head[1:]:
            if line.startswith("джерело:"):
                self.url = line.split(":", 1)[1].strip()
            elif line.startswith("отримано:"):
                self.fetched = line.split(":", 1)[1].strip()
        self.text = body

    @property
    def section(self) -> str:
        """Номер розділу з заголовка: «22.1» з «22.1 String Objects»."""
        m = _HEADING.match(self.title)
        return m.group(1) if m else ""

    def __repr__(self):
        return f"<Document {self.doc_id} {len(self.text)} симв.>"


class Passage:
    """Фрагмент документа — одиниця, яку індексує і повертає пошук."""

    def __init__(self, doc: Document, section: str, heading: str, text: str,
                 part: int = 1, parts: int = 1):
        self.doc_id = doc.doc_id
        self.doc_title = doc.title
        self.url = doc.url
        self.section = section
        self.heading = heading
        self.text = text
        self.part = part
        self.parts = parts

    @property
    def pid(self) -> str:
        """Стійкий ідентифікатор фрагмента — він же посилання у відповіді агента."""
        base = f"{self.doc_id}#{self.section or 'head'}"
        return f"{base}/{self.part}" if self.parts > 1 else base

    @property
    def label(self) -> str:
        """Людський підпис: те, що агент цитує клієнтові як джерело."""
        tail = f" (частина {self.part} з {self.parts})" if self.parts > 1 else ""
        return f"{self.heading}{tail}"

    def as_prompt_block(self) -> str:
        """Готовий блок для tool_result: підпис, посилання, текст."""
        return f"[{self.pid}] {self.label}\nдокумент: {self.doc_title}\n\n{self.text}"

    def __repr__(self):
        return f"<Passage {self.pid} {len(self.text)} симв.>"


def load_documents() -> list[Document]:
    """Усі .txt із practice/docs/, у порядку імен файлів (він же порядок розділів)."""
    files = sorted(DOCS_DIR.glob("*.txt"))
    if not files:
        raise SystemExit(
            f"У {DOCS_DIR} немає жодного .txt.\n"
            "Документи лежать у репозиторії; якщо теки немає — вивантажте розділи "
            "специфікації заново."
        )
    return [Document(p) for p in files]


def _split_long(doc: Document, section: str, heading: str, text: str,
                max_chars: int = None) -> list[Passage]:
    """Розрізає задовгий підрозділ по порожніх рядках, зберігаючи заголовок."""
    ceiling = max_chars or MAX_CHARS
    if len(text) <= ceiling:
        return [Passage(doc, section, heading, text)]

    chunks, current = [], []
    size = 0
    for para in text.split("\n\n"):
        # Абзац, який сам довший за межу (довгий алгоритм списком), лишаємо цілим:
        # різати його посередині кроку гірше, ніж перевищити межу.
        if size and size + len(para) > ceiling:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))

    # Останній шматок може вийти зовсім куций — приклеюємо його до попереднього.
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHARS:
        tail = chunks.pop()
        chunks[-1] = chunks[-1] + "\n\n" + tail

    return [Passage(doc, section, heading, c, i + 1, len(chunks))
            for i, c in enumerate(chunks)]


def split_document(doc: Document, max_chars: int = None) -> list[Passage]:
    """Ділить один документ на фрагменти по заголовках специфікації.

    `max_chars` перекриває межу розміру. Потрібен лише досліду
    practice/challenges/a_chunking.py; звичайні виклики його не задають.
    """
    section, heading = doc.section, doc.title
    buffer: list[str] = []
    out: list[Passage] = []

    def flush():
        text = "\n".join(buffer).strip()
        if text:
            out.extend(_split_long(doc, section, heading, text, max_chars))
        buffer.clear()

    for line in doc.text.split("\n"):
        m = _HEADING.match(line.strip())
        if m and line.strip() == line:
            flush()
            section, heading = m.group(1), line.strip()
            continue
        buffer.append(line)
    flush()

    # Заголовок без власного тексту (рубрика, у якій одні підрозділи) дає
    # фрагмент із кількох слів. Такий нічого не додає пошуку — прибираємо.
    return [p for p in out if len(p.text) >= MIN_CHARS or p.parts > 1]


def load_passages() -> list[Passage]:
    """Усі документи, поділені на фрагменти. Це вхід і лексичного, і векторного пошуку.

    Однакові тексти зливаються в один фрагмент. Потреба в цьому не теоретична:
    розділ 6.1.7 The Object Type містить підрозділи 6.1.7.1–6.1.7.4, а вони
    вивантажені ще й окремими документами. Тобто три файли з вісімнадцяти
    повторюють шматки першого слово в слово.

    Без злиття пошук повертає обидві копії, і агент отримує два однакові
    тексти замість двох різних — половина місця в промпті витрачена ні на що.
    Лишається та копія, що трапилась першою; порядок файлів сталий, тож і вибір
    сталий. Документів від цього не меншає: як було вісімнадцять, так і
    лишається, зникає тільки повтор усередині індексу.
    """
    seen, out = set(), []
    for doc in load_documents():
        for p in split_document(doc):
            key = p.text
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def fingerprint(passages: list[Passage]) -> str:
    """Відбиток набору документів — щоб кеш векторів не пережив їхню зміну.

    Береться ідентифікатор кожного фрагмента і довжина його тексту: перейменування
    файлу, доданий розділ чи інша межа різання дадуть інший відбиток, і індекс
    перебудується сам.
    """
    payload = [[p.pid, len(p.text)] for p in passages]
    import hashlib
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]
