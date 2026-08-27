"""
СПІЛЬНЕ · механіка одного пошуку, спільна для всіх спеціалістів.

У практиці модуля 2 файл tools.py відповідав на три питання одразу: як шукати,
по якому індексу і хто дістає інструмент. У модулі 4 останні два питання
вирішуються ПО-РІЗНОМУ для кожного спеціаліста, тому вони переїхали в
base/team.py, а тут лишилася сама механіка: взяти індекс, взяти запит, повернути
фрагменти у форматі tool_result. Механіка навмисно та сама, що в модулі 2, —
інакше порівняння «один агент проти системи» міряло б заодно і різницю пошуку.

Переписування бідного запиту (PRACTICE_REWRITE=1) теж живе тут: воно частина
механіки пошуку, а не права спеціаліста. Умови спрацювання і виміряні числа —
у докстрингу common/rewrite.py.
"""

from . import rewrite
from .corpus import Passage


def format_hits(passages: list[Passage]) -> dict:
    if not passages:
        return {"found": 0,
                "note": "Nothing in the available excerpts matches this query."}
    return {"found": len(passages),
            "passages": [{"id": p.pid, "section": p.label,
                          "document": p.doc_title, "text": p.text}
                         for p in passages]}


def search_once(index, query: str, k: int = 3):
    """Фрагменти, що подолали межу, і оцінка найкращого — навіть якщо не подолав."""
    top = index.scores(query, 1)
    return index.retrieve(query, k), (top[0][0] if top else 0.0)


def search(index, query: str) -> dict:
    """Один пошук по заданому індексу, з другою спробою при бідному результаті.

    Друга спроба вмикається змінною PRACTICE_REWRITE=1. Порожній перший результат
    не переписується ніколи: причина не в економії, а у виміряному ефекті, коли
    відмова допоміжної моделі сама ставала запитом і проходила межу схожості —
    числа в докстрингу common/rewrite.py.
    """
    hits, top = search_once(index, query)
    if not rewrite.enabled():
        return format_hits(hits)

    thin = len(hits) < rewrite.MIN_HITS or top < rewrite.confident_bar()
    if not hits or not thin:
        return format_hits(hits)

    second = rewrite.reformulate(query)
    if not second:
        return format_hits(hits)

    hits2, top2 = search_once(index, second)
    took_second = (len(hits2), top2) > (len(hits), top)
    out = format_hits(hits2 if took_second else hits)
    out["rewritten_query"] = second
    out["rewrite_used"] = took_second
    if not out["found"]:
        out["note"] = ("Nothing in the available excerpts matches this query, "
                       "with either the original wording or a rewritten one.")
    return out
