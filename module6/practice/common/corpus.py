"""
СПІЛЬНЕ · документи практики і поділ їх на фрагменти.

Корпус тут — той самий, що в практиках модулів 2-5: специфікація ECMAScript,
поділена на фрагменти. Набір обирається змінною PRACTICE_DOCS: «core» —
вісімнадцять розділів навколо типу Object, «full» — уся ECMA-262, «suite» —
ECMA-262 разом із ECMA-402, 404, 414 і вільними документами довкола 402.
Типовий набір цієї практики — найширший, «suite».

Понад справжні документи корпус ЗАВЖДИ містить теку docs-attack/ — навчальні
приманки лабораторної з безпеки. Два з тих документів отруєні: у їхнє тіло
зашита інструкція для моделі, і серед тисяч справжніх фрагментів вона ховається
так само, як ховалася б у реальному RAG. Кожна приманка позначає джерело як
FIXTURE, щоб її не сплутати зі специфікацією.

Формат файлу: три рядки шапки, які починаються з «#» (заголовок розділу, адреса
джерела, дата), порожній рядок, далі текст. Шапка потрібна для посилання у
відповіді агента, тому в тіло вона не потрапляє. Індексуються фрагменти, а не
цілі документи: специфікація сама пронумерована, і межа фрагмента — це її
пронумерований підзаголовок.
"""

import hashlib
import json
import os
import pathlib
import re

DOC_SETS = {
    "core":  ("docs",),
    "full":  ("docs-full",),
    "suite": ("docs-full", "docs-suite"),
}
DOC_SET = os.getenv("PRACTICE_DOCS", "suite")
if DOC_SET not in DOC_SETS:
    raise SystemExit(f"Невідомий набір документів '{DOC_SET}'. "
                     f"Доступні: {', '.join(sorted(DOC_SETS))}")

_ROOT = pathlib.Path(__file__).resolve().parent.parent
ATTACK_DIR = _ROOT / "docs-attack"
# Справжні документи набору плюс приманки — завжди. Приманки останні, щоб їхні
# фрагменти йшли після справжніх; на пошук порядок не впливає, але так у списку
# видно, де закінчується специфікація й починається лабораторія.
DOCS_DIRS = [_ROOT / name for name in DOC_SETS[DOC_SET]] + [ATTACK_DIR]

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
        self.is_attack = path.parent.name == ATTACK_DIR.name

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


_DOWNLOAD_HINT = {
    "docs-full":  "python -m practice.challenges.spec_download   (з модуля 5)",
    "docs-suite": "python -m practice.challenges.suite_download  (з модуля 5)",
}


def load_documents() -> list[Document]:
    docs = []
    for folder in DOCS_DIRS:
        files = sorted(folder.glob("*.txt"))
        if not files:
            hint = _DOWNLOAD_HINT.get(folder.name)
            raise SystemExit(
                f"У {folder} немає жодного .txt.\n"
                + (f"Скопіюйте набір із модуля 5 або вивантажте: {hint}"
                   if hint else "Приманки лежать у репозиторії разом із практикою."))
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
    """Усі документи набору й приманки, поділені на фрагменти. Однакові тексти
    зливаються в один фрагмент (перший за порядком)."""
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
