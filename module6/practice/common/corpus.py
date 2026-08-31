"""
СПІЛЬНЕ · корпус-приманка і поділ його на фрагменти.

Це НЕ справжня специфікація. Тут малий набір коротких документів у docs-attack/,
навмисно зроблений для лабораторної з безпеки: кілька чесних розділів і два
отруєні, у тіло яких зашита інструкція для моделі. Через це кожен документ у
шапці позначає джерело як «FIXTURE», а не як адресу tc39 — плутати приманку зі
специфікацією не можна.

Формат файлу той самий, що в практиці модуля 5: три рядки шапки, кожен із «#»
(назва розділу, джерело, дата), порожній рядок, далі текст. Документи короткі,
тож фрагмент дорівнює документу — різати нема чого. Клас Passage лишається
сумісним із common/lexical.py, який чекає на .heading, .text і load_passages().
"""

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS_DIR = _ROOT / "docs-attack"

# Рядок-заголовок специфікації: номер розділу, пробіл, назва. Той самий, що в
# корпусі модуля 5 — за ним із назви дістається номер розділу для посилання.
_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.{0,110})$")


class Document:
    """Один файл із docs-attack/ разом із шапкою."""

    def __init__(self, path: pathlib.Path):
        raw = path.read_text(encoding="utf-8").splitlines()
        head = [ln[1:].strip() for ln in raw if ln.startswith("#")][:3]
        body = "\n".join(raw[len(head):]).strip("\n")

        self.doc_id = path.stem                      # напр. 04-string-trim
        self.path = path
        self.title = head[0] if head else path.stem  # напр. 22.1.3.32 String.prototype.trim
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
    """Фрагмент — одиниця, яку індексує і повертає пошук. Тут = цілий документ."""

    def __init__(self, doc: Document):
        self.doc_id = doc.doc_id
        self.doc_title = doc.title
        self.url = doc.url
        self.section = doc.section
        self.heading = doc.title
        self.text = doc.text

    @property
    def pid(self) -> str:
        """Стійкий ідентифікатор фрагмента — він же посилання у відповіді агента."""
        return f"{self.doc_id}#{self.section}" if self.section else self.doc_id

    @property
    def label(self) -> str:
        """Людський підпис: те, що агент цитує клієнтові як джерело."""
        return self.heading

    def as_prompt_block(self) -> str:
        """Готовий блок для tool_result: підпис, посилання, текст."""
        return f"[{self.pid}] {self.label}\nдокумент: {self.doc_title}\n\n{self.text}"

    def __repr__(self):
        return f"<Passage {self.pid} {len(self.text)} симв.>"


def load_documents() -> list[Document]:
    """Усі .txt із docs-attack/ у порядку імен файлів."""
    files = sorted(DOCS_DIR.glob("*.txt"))
    if not files:
        raise SystemExit(
            f"У {DOCS_DIR} немає жодного .txt. Корпус-приманка лежить у "
            "репозиторії разом із практикою; якщо теки немає — відновіть її з git.")
    return [Document(p) for p in files]


def load_passages() -> list[Passage]:
    """Кожен документ — один фрагмент. Вхід і сервера, і пошуку BM25."""
    return [Passage(doc) for doc in load_documents()]
