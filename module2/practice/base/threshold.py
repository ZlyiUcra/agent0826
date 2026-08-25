"""
ОСНОВА · звідки взявся поріг векторного пошуку.

Скрипт друкує косинус топ-1 окремо для двох наборів: питання, відповідь на які
в корпусі є, і питання, яких корпус не покриває. Задум був простий — поставити
поріг у проміжок між найгіршим із перших і найкращим із других.

Проміжку немає, і прогін це показує щоразу. Питання не з корпусу, але про
JavaScript, набирають стільки ж, скільки правильні: схожість міряє тему, а тема
в них спільна. Розділяються лише ті сторонні питання, які й теми не поділяють —
про столицю Франції та про борщ.

Тому число в коді працює як підлога: воно відрізає чужу тему й нічого не обіцяє
щодо своєї. Хто відмовляє на питання про JavaScript без відповіді в корпусі —
описано в practice/common/tools.py. Цей скрипт лишається як вимір: якщо корпус
поповниться, перевірити, де тепер лягла підлога, можна ним.

Прогін офлайн, до моделі Anthropic не звертається, грошей не коштує.

    python -m practice.base.threshold
"""

from practice.common.vectors import THRESHOLD, VectorIndex

IN_CORPUS = [
    "How do I replace part of a text with something else?",
    "What happens when a wrapper for true or false is created?",
    "Can the parent of an object be locked so it never changes?",
    "How does a stand-in object forward reads to the real one?",
    "How does a function remember the object it was attached to?",
    "How is the length of an array kept in step with its elements?",
    "What does freezing an object actually do to its properties?",
    "How do I turn a number into a string with a fixed number of decimals?",
]

OUT_OF_CORPUS = [
    "What is the capital of France?",
    "How do I open a file and read it line by line?",
    "What is the recipe for borscht?",
    "How does async iteration over a stream work?",
    "How do I install a package with npm?",
    "What is the difference between let and var?",
]


def main() -> int:
    vec = VectorIndex()
    print(f"фрагментів: {len(vec.passages)} · поріг у коді: {THRESHOLD}\n")

    def run(title, queries):
        tops = []
        print(title)
        for q in queries:
            s, p = vec.scores(q, 1)[0]
            tops.append(s)
            print(f"  {s:6.3f}  {q[:52]:54s} {p.pid}")
        print()
        return tops

    inside = run("Питання, відповідь на які в корпусі Є:", IN_CORPUS)
    outside = run("Питання, яких корпус НЕ покриває:", OUT_OF_CORPUS)

    lo, hi = min(inside), max(outside)
    print(f"найгірше «є»:      {lo:.3f}")
    print(f"найкраще «немає»:  {hi:.3f}")
    if lo > hi:
        print(f"проміжок:          {hi:.3f} … {lo:.3f}")
        print("поріг у коді "
              + ("всередині проміжку." if hi < THRESHOLD < lo else "ПОЗА проміжком, перегляньте."))
    else:
        print("проміжку немає: набори перекриваються, самим числом їх не розділити")

    cut = [(s, q) for s, q in zip(outside, OUT_OF_CORPUS) if s < THRESHOLD]
    print(f"\nпідлога {THRESHOLD} відсікає {len(cut)} із {len(OUT_OF_CORPUS)} питань не з корпусу:")
    for s, q in cut:
        print(f"  {s:6.3f}  {q}")
    kept = [(s, q) for s, q in zip(outside, OUT_OF_CORPUS) if s >= THRESHOLD]
    print(f"проходять підлогу {len(kept)} — на них відмовляє модель, не пошук:")
    for s, q in kept:
        print(f"  {s:6.3f}  {q}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
