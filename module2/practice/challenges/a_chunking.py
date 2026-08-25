"""
ЧЕЛЕНДЖ A · один довгий документ і розмір шматка.

Необов'язковий пункт картки: «взяти один довгий документ і погратись із розміром
шматків». Довгий документ тут один очевидний — 22.1 String Objects, 52 257
символів, п'ята частина всього тексту.

ЩО САМЕ МІРЯЄТЬСЯ

Документ ріжеться на чотирьох межах розміру, і на кожній будується окремий
індекс лише з цього документа. Далі вісім запитів, відповідь на кожен лежить у
відомому підрозділі, і для кожного записується МІСЦЕ цього підрозділу у видачі.

Місце, а не влучання. Влучання в перший рядок — надто груба міра: воно однаково
показує «промахнувся на один рядок» і «правильна відповідь на сотому місці», а
це різні хвороби з різним лікуванням.

Запити поставлені так, як їх ставить людина, що не пам'ятає назви методу:
«прибрати пробіли з обох кінців» замість `trim`, «повторити текст кілька разів»
замість `repeat`.

ЧОГО ЧЕКАТИ

Дрібні шматки мають різати алгоритми навпіл: кроки одного методу опиняються в
різних фрагментах, і кожен окремо схожий на запит слабше, ніж цілий підрозділ.
Великі шматки мають розмивати тему: в один фрагмент злипаються два-три сусідні
методи, і вектор виходить усереднений.

Дослід офлайн, до моделі Anthropic не звертається, грошей не коштує. Але кожна
межа — це окремий перерахунок ембедингів, тож прогін триває кілька хвилин і
кеш не використовує: індекси тут тимчасові й на диск не лягають.

    python -m practice.challenges.a_chunking
"""

from practice.common.corpus import load_documents, split_document
from practice.common.vectors import MODEL_NAME, embed

DOC_ID = "18-string-objects"
CEILINGS = [400, 700, 1400, 2500]

# (запит, номер підрозділу, у якому лежить відповідь)
QUERIES = [
    ("How do I replace part of a text with something else?", "22.1.3.19"),
    ("How do I check whether a text begins with certain characters?", "22.1.3.24"),
    ("How do I remove spaces from both ends of a text?", "22.1.3.32"),
    ("How do I find where a piece of text appears inside another?", "22.1.3.9"),
    ("How can I repeat a piece of text several times?", "22.1.3.18"),
    ("How do I make all the letters in a text capital?", "22.1.3.30"),
    ("How do I pad a text at the front so it reaches a certain length?", "22.1.3.17"),
    ("How do I get a single character at a given position?", "22.1.3.1"),
]


def _rank(passages, matrix, query: str, section: str):
    """Місце найкращого фрагмента потрібного підрозділу. None — його немає у видачі."""
    import numpy as np

    sims = matrix @ embed([query], kind="query")[0]
    for place, i in enumerate(np.argsort(sims)[::-1], start=1):
        # Порівняння точне, а не за підрядком: «22.1.3.1» є початком «22.1.3.19»,
        # і підрядок зарахував би indexOf як відповідь про at.
        if passages[i].section == section:
            return place
    return None


def main() -> int:
    doc = next((d for d in load_documents() if d.doc_id == DOC_ID), None)
    if doc is None:
        raise SystemExit(f"Серед документів немає {DOC_ID}.")

    print(f"документ: {doc.title} · {len(doc.text)} символів · модель {MODEL_NAME}")
    print(f"запитів: {len(QUERIES)} · межі: {', '.join(str(c) for c in CEILINGS)}\n")

    results = {}
    for ceiling in CEILINGS:
        passages = split_document(doc, ceiling)
        lengths = [len(p.text) for p in passages]
        print(f"межа {ceiling}: рахую {len(passages)} фрагментів "
              f"(найдовший {max(lengths)}, у середньому {sum(lengths) // len(lengths)})",
              flush=True)
        matrix = embed([f"{p.heading}\n{p.text}" for p in passages], kind="passage")
        results[ceiling] = (
            [_rank(passages, matrix, q, s) for q, s in QUERIES],
            len(passages),
        )

    print()
    head = "підрозділ   " + "".join(f"{c:>8}" for c in CEILINGS) + "   запит"
    print(head)
    print("-" * len(head))
    for j, (query, section) in enumerate(QUERIES):
        row = "".join(f"{str(results[c][0][j]):>8}" for c in CEILINGS)
        print(f"{section:<12}{row}   {query[:46]}")

    print()
    print(f"{'фрагментів':<12}" + "".join(f"{results[c][1]:>8}" for c in CEILINGS))
    for label, keep in (("перший рядок", 1), ("перша трійка", 3)):
        row = "".join(f"{sum(1 for r in results[c][0] if r and r <= keep):>8}"
                      for c in CEILINGS)
        print(f"{label:<12}{row}")
    means = []
    for c in CEILINGS:
        got = [r for r in results[c][0] if r]
        means.append(sum(got) / len(got) if got else float("nan"))
    print(f"{'середнє':<12}" + "".join(f"{m:>8.1f}" for m in means))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
