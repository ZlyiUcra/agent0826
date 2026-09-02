"""
СПІЛЬНЕ · документи практики і поділ їх на фрагменти.

Корпус — той самий набір специфікацій, що в практиках модулів 2-6: уся ECMA-262
розділ за розділом плюс ECMA-402, 404, 414 і вільні документи, на які спирається
402 (RFC 4647, звіти Unicode UAX #29, UTS #10 і UTS #35). Файли лежать поруч у
docs-full/ і docs-suite/, вивантажені один раз; код їх лише читає — нічого не
тягне з мережі й нічого не перезаписує.

Набір обирає змінна PRACTICE_DOCS: «full» — сама ECMA-262, «suite» — уся база.
Типовий набір цієї практики — найширший, «suite».

Окремо стоїть змінна PRACTICE_DEGRADED. Вона підміняє теки документів на
docs-degraded/ — навмисно зіпсовану копію корпусу, яку робить base/degrade.py.
Назва набору при цьому не змінюється, і це головне: ім'я колекції векторів
рахується з назви набору, тож деградований прогін іде в ТУ САМУ колекцію, що й
здоровий. Саме так виглядає випадок, заради якого все це написане: текст
оновили, вектори не перерахували.

Формат файлу: три рядки шапки, які починаються з «#» (заголовок розділу, адреса
джерела з якорем, дата вивантаження), порожній рядок, далі текст. Шапка потрібна
для посилання у відповіді агента, тому в тіло вона не потрапляє.

ЧОМУ ІНДЕКСУЄМО ФРАГМЕНТИ, А НЕ ЦІЛІ ДОКУМЕНТИ

Розділи специфікації дуже різні за розміром: найменший — півтори тисячі символів,
найбільший (22.1, String Objects) — за п'ятдесят тисяч. Якби одиницею пошуку був
цілий документ, на запит про `String.prototype.replace` пошук повернув би весь
розділ 22.1: п'ятдесят кілобайт, з яких потрібні дві сотні символів. У промпт
таке не влізе, а якби й влізло — модель шукала б відповідь у стосі стороннього
тексту, і саме там беруться вигадані відповіді.

ДЕ ПРОХОДИТЬ МЕЖА ФРАГМЕНТА

Специфікація сама пронумерована: «22.1.3.19 String.prototype.replace ( ... )»
стоїть окремим рядком перед своїм текстом. Ця нумерація і є межею. Лишається
один випадок, який вона не покриває: підрозділ, довший за MAX_CHARS. Такий
ділиться далі по порожніх рядках, шматки нумеруються («частина 2 з 3») і кожен
зберігає заголовок свого підрозділу, щоб посилання не загубилося.
"""

import hashlib
import json
import os
import pathlib
import re

DOC_SETS = {
    "full":  ("docs-full",),
    "suite": ("docs-full", "docs-suite"),
}
DOC_SET = os.getenv("PRACTICE_DOCS", "suite")
if DOC_SET not in DOC_SETS:
    raise SystemExit(f"Невідомий набір документів '{DOC_SET}'. "
                     f"Доступні: {', '.join(sorted(DOC_SETS))}")

_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEGRADED_DIR = _ROOT / "docs-degraded"

# Деградована копія підміняє теки набору, але не його назву. Назва потрібна далі
# для імені колекції векторів, і саме тому вона тут не змінюється: здоровий і
# деградований прогони мусять шукати в одній колекції.
DEGRADED = bool(os.getenv("PRACTICE_DEGRADED"))
DOCS_DIRS = ([DEGRADED_DIR] if DEGRADED
             else [_ROOT / name for name in DOC_SETS[DOC_SET]])

MAX_CHARS = 1400
MIN_CHARS = 200

_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.{0,110})$")


class Document:
    """Один файл разом із шапкою."""

    def __init__(self, path: pathlib.Path):
        raw = path.read_text(encoding="utf-8").splitlines()
        head = [ln[1:].strip() for ln in raw if ln.startswith("#")][:3]
        body = "\n".join(raw[len(head):]).strip("\n")

        self.doc_id = path.stem
        self.path = path
        self.title = head[0] if head else path.stem
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
        m = _HEADING.match(self.title)
        return m.group(1) if m else ""


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
        base = f"{self.doc_id}#{self.section or 'head'}"
        return f"{base}/{self.part}" if self.parts > 1 else base

    @property
    def label(self) -> str:
        tail = f" (частина {self.part} з {self.parts})" if self.parts > 1 else ""
        return f"{self.heading}{tail}"

    def as_prompt_block(self) -> str:
        return f"[{self.pid}] {self.label}\nдокумент: {self.doc_title}\n\n{self.text}"

    def __repr__(self):
        return f"<Passage {self.pid} {len(self.text)} симв.>"


def load_documents() -> list[Document]:
    docs = []
    for folder in DOCS_DIRS:
        files = sorted(folder.glob("*.txt"))
        if not files:
            raise SystemExit(
                f"У {folder} немає жодного .txt.\n"
                + ("Деградовану копію робить: "
                   "python -m practice.base.degrade"
                   if folder == DEGRADED_DIR
                   else "Документи лежать у репозиторії разом із практикою."))
        docs.extend(Document(p) for p in files)
    return docs


def _split_long(doc, section, heading, text, max_chars=None):
    ceiling = max_chars or MAX_CHARS
    if len(text) <= ceiling:
        return [Passage(doc, section, heading, text)]
    chunks, current, size = [], [], 0
    for para in text.split("\n\n"):
        if size and size + len(para) > ceiling:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHARS:
        tail = chunks.pop()
        chunks[-1] = chunks[-1] + "\n\n" + tail
    return [Passage(doc, section, heading, c, i + 1, len(chunks))
            for i, c in enumerate(chunks)]


def split_document(doc: Document, max_chars=None) -> list[Passage]:
    section, heading = doc.section, doc.title
    buffer, out = [], []

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
    return [p for p in out if len(p.text) >= MIN_CHARS or p.parts > 1]


def load_passages() -> list[Passage]:
    """Усі документи набору, поділені на фрагменти. Це вхід і пошуку по словах,
    і пошуку за змістом. Однакові тексти зливаються в один фрагмент: розділ 6.1.7
    трапляється в корпусі ще й окремими документами, і без злиття пошук повертав
    би дві однакові копії замість двох різних текстів. Лишається та, що трапилась
    першою; порядок файлів сталий, тож і вибір сталий."""
    seen, out = set(), []
    for doc in load_documents():
        for p in split_document(doc):
            if p.text in seen:
                continue
            seen.add(p.text)
            out.append(p)
    return out


def fingerprint(passages: list[Passage]) -> str:
    payload = [[p.pid, len(p.text)] for p in passages]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]
