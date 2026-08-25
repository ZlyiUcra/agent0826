"""
ОСНОВА · де пошук по словах промахується, а пошук по змісту влучає.

Це доказ до другого обов'язкового пункту картки: «зробити пошук по змісту
(ембединги) і знайти приклад, де він виграв у пошуку по словах».

Запити навмисно поставлені так, як їх ставить людина, що не знає термінів
специфікації: «замінити частину тексту» замість `String.prototype.replace`,
«обгортка для true чи false» замість `Boolean ( value )`, «підмінний об'єкт»
замість `Proxy`. Слова запиту в потрібному фрагменті майже не трапляються —
саме тут BM25 і сідає.

Останній запит у наборі не має відповіді в корпусі взагалі. Він показує те, чого
не видно на решті: лексичний пошук і на нього повертає непорожній результат із
ненульовою оцінкою, тобто відрізнити «знайшов» від «не знайшов» за самою оцінкою
BM25 неможливо. Векторний пошук на тому ж запиті мовчить, бо його топ-1 не
дотягує до порога.

Мережі й ключів прогін не потребує, до моделі Anthropic не звертається, грошей
не коштує. Перший запуск завантажує ваги e5-small (близько 470 МБ) і рахує
індекс; далі вектори беруться з кеша в practice/index/.

    python -m practice.base.compare
    python -m practice.base.compare --full    # з текстом знайдених фрагментів
"""

import sys

from practice.common.lexical import LexicalIndex
from practice.common.vectors import MODEL_NAME, THRESHOLD, VectorIndex

# (запит, підрядок ідентифікатора фрагмента, який вважаємо правильною відповіддю)
# Порожній рядок означає, що правильної відповіді в корпусі немає.
CASES = [
    ("How do I replace part of a text with something else?",
     "22.1.3.19"),
    ("What happens when a wrapper for true or false is created?",
     "20.3.1.1"),
    ("Can the parent of an object be locked so it never changes?",
     "10.4.7"),
    ("How does a stand-in object forward reads to the real one?",
     "10.5.8"),
    ("How does a function remember the object it was attached to?",
     "10.4.1"),
    ("What is the capital of France?",
     ""),
]


def _rank(scored_all, expected: str):
    """Місце правильного розділу в повному списку. None — його там немає взагалі."""
    if not expected:
        return None
    for r, (_, p) in enumerate(scored_all):
        if expected in p.pid:
            return r + 1
    return None


def _show(tag: str, scored, expected: str, rank, total: int, full: bool) -> None:
    if not expected:
        print(f"  {tag:12s} правильного розділу немає — має віддати порожньо")
    else:
        place = "не знайдено взагалі" if rank is None else f"{rank} з {total}"
        print(f"  {tag:12s} правильний розділ на місці: {place}")
    if not scored:
        print(f"  {'':12s} віддає: нічого")
        return
    for i, (s, p) in enumerate(scored):
        mark = "+" if expected and expected in p.pid else " "
        print(f"  {'':12s}{mark}{s:7.3f}  {p.label[:58]}")
        print(f"  {'':12s} {'':7s}  {p.pid}")
        if full:
            print(f"  {'':12s} {p.text[:300].replace(chr(10), ' ')}…")


def main(argv: list[str]) -> int:
    full = "--full" in argv

    print("Будую індекси…")
    lex = LexicalIndex()
    vec = VectorIndex()
    src = "з кеша" if vec.from_cache else "порахований щойно"
    total = len(lex.passages)
    print(f"фрагментів: {total} · модель {MODEL_NAME} · підлога {THRESHOLD}")
    print(f"векторний індекс {src} ({vec.cache_path.name})\n")

    better = same = worse = 0
    for query, expected in CASES:
        print(f"Запит: «{query}»")
        print(f"  очікуємо:    {expected or 'нічого — у корпусі відповіді немає'}")

        lex_all = lex.scores(query, total)
        vec_all = vec.scores(query, total)
        r_lex = _rank(lex_all, expected)
        r_vec = _rank(vec_all, expected)

        _show("BM25", lex_all[:2], expected, r_lex, total, full)
        _show("ембединги", [(s, p) for s, p in vec_all[:2] if s >= THRESHOLD],
              expected, r_vec, total, full)

        if r_lex is not None and r_vec is not None:
            better += r_vec < r_lex
            same += r_vec == r_lex
            worse += r_vec > r_lex
        print()

    print(f"Правильний розділ стоїть вище в ембедингів на {better} запитах, "
          f"нижче на {worse}, однаково на {same}.")
    print("Запит без відповіді в корпусі: BM25 усе одно щось віддає, "
          "ембединги мовчать, якщо топ-1 не дотяг до підлоги.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
