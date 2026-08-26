"""
ЧЕЛЕНДЖ · курсовий вимір Ragas у двох режимах сховища. ПЛАТНИЙ.

Останній чекбокс лабораторної: прогнати `ragas_compare.py` в обох режимах і
порівняти, причому «важлива не цифра, а різниця між прогонами».

ЩО ТУТ ПОРІВНЮЄТЬСЯ

Той самий датасет із шести питань, той самий агент, ті самі метрики Ragas — і
рівно одна відмінність: звідки беруться правила. У режимі `memory` їх дає
курсовий `knowledge_vec` з матрицею в пам'яті процесу, у режимі `qdrant` — той
самий набір правил із сервера (`practice/challenges/kb_qdrant.py`). Вектори в
обох випадках рахує одна й та сама курсова функція, нижня межа відмови теж
спільна, тож різниця між прогонами може взятися лише зі сховища або з
недетермінованості самих моделей.

ЧОГО ЧЕКАТИ ВІД ЧИСЕЛ

Однакових. Якщо `context_recall` у двох режимах збігається, це і є відповідь
лабораторної: сховище змінилось, а якість відповідей — ні. Розбіжність у
`faithfulness` і `answer_relevancy` на кілька сотих означає не сховище, а те, що
і агент, і суддя — моделі: два прогони того самого режиму розійдуться так само.
Саме тому картка й наголошує, що важлива різниця між прогонами, а не цифра.

ЯК ЦЕ ВЛАШТОВАНО

Курсовий `ragas_compare.py` не змінюється. Він імпортується як модуль, і на час
другого прогону в ньому підмінюється лише посилання на модуль пошуку — те саме,
що зробив би сам курс, якби файл `knowledge_qdrant.py` існував.

ЧОМУ ТУТ ЛАТКА ДО ASYNCIO

Без неї весь вимір друкує `nan` замість чисел, і жодна метрика не рахується.
Ланцюжок такий. Пакет `ragas` під час імпорту викликає `nest_asyncio.apply()`,
а той підмінює `asyncio.Task` реалізацією мовою Python. Ця реалізація записує
поточну задачу у власний облік, тоді як `asyncio.current_task()` у Python 3.14 —
реалізація мовою C і читає облік C. Усередині задачі вона знаходить порожньо і
повертає `None`. Далі спрацьовує `asyncio.timeout`, яким `ragas` обгортає кожне
звернення до судді: побачивши `None` замість задачі, він відмовляється
стартувати з `RuntimeError: Timeout should be used inside a task`. Виняток ловить
виконавець `ragas`, друкує рядок `Exception raised in Job[...]` і ставить замість
оцінки `nan` — так падають усі вісімнадцять завдань прогону.

Лікування — одне присвоєння: хай `current_task` читає той самий облік, у який
пише підмінена задача. Латка накладається лише тоді, коли підміну справді видно,
і не чіпає нічого, крім цієї однієї функції.

    python -m practice.challenges.ragas_modes            # обидва режими
    python -m practice.challenges.ragas_modes memory     # лише один
"""

import math
import sys

import ragas_compare as rc

from practice.challenges import kb_qdrant
from practice.challenges.qdrant_store import QDRANT_URL, alive

METRICS = ("faithfulness", "answer_relevancy", "context_recall")


def repair_current_task() -> bool:
    """Повертає asyncio.current_task() здатність бачити задачу.

    Причина і механізм — у докстрингу модуля, розділ «ЧОМУ ТУТ ЛАТКА ДО ASYNCIO».
    Повертає True, якщо латку довелося накласти, False — якщо підміни немає і
    лагодити нічого.
    """
    import asyncio
    import asyncio.tasks as tasks

    if asyncio.Task is not getattr(tasks, "_PyTask", None):
        return False
    tasks.current_task = tasks._py_current_task
    asyncio.current_task = tasks._py_current_task
    return True


def _evaluate(name: str, judge, emb, metrics, run_cfg):
    print(f"\n=== Режим сховища: {name} ===")
    dataset = rc.collect(rc.run_vector)
    print("  Ragas оцінює…")
    return rc.evaluate(dataset, metrics=metrics, llm=judge, embeddings=emb,
                       run_config=run_cfg, show_progress=False).to_pandas()


def _has_numbers(df) -> bool:
    """Чи порахувалася хоч одна метрика: nan скрізь означає збій, не результат."""
    return not all(math.isnan(df[m].mean()) for m in METRICS)


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    wanted = [a for a in argv if a in ("memory", "qdrant")] or ["memory", "qdrant"]
    if "qdrant" in wanted:
        if not alive():
            print(f"Сервера немає за адресою {QDRANT_URL}. Підніміть його:")
            print("  docker compose up -d")
            return 1
        if kb_qdrant.collection_info_of(kb_qdrant.COLLECTION) is None:
            print("Правил у сервері ще немає. Залийте їх:")
            print("  python -m practice.challenges.kb_qdrant")
            return 1

    if repair_current_task():
        print("asyncio: латка накладена — current_task знову бачить задачу.")

    judge = rc.LangchainLLMWrapper(rc.ChatAnthropic(model=rc.MODEL_FAST,
                                                    temperature=0))
    emb = rc.LangchainEmbeddingsWrapper(rc.HuggingFaceEmbeddings(
        model_name="intfloat/multilingual-e5-small"))
    metrics = [rc.faithfulness, rc.answer_relevancy, rc.context_recall]
    run_cfg = rc.RunConfig(max_workers=4)

    original = rc.vec
    results = {}
    try:
        for name in wanted:
            # Єдина підміна на весь прогін: звідки беруться правила.
            rc.vec = original if name == "memory" else kb_qdrant
            results[name] = _evaluate(name, judge, emb, metrics, run_cfg)
    finally:
        rc.vec = original

    print("\n" + "═" * 66)
    print(f"{'режим сховища':<16} {'faithful.':>10} {'relevancy':>10} {'ctx_recall':>11}")
    for name, df in results.items():
        print(f"{name:<16} {df['faithfulness'].mean():>10.2f} "
              f"{df['answer_relevancy'].mean():>10.2f} "
              f"{df['context_recall'].mean():>11.2f}")

    broken = [name for name, df in results.items() if not _has_numbers(df)]
    if broken:
        print(f"\nМетрики не порахувалися в режимі(ах): {', '.join(broken)}.")
        print("nan у таблиці — це не результат виміру, а збій прогону. Причина")
        print("надрукована вище рядками «Exception raised in Job[...]»: судді не")
        print("дали відповісти, тож порівнювати нема чого.")
        return 2

    if len(results) == 2:
        a, b = results["memory"], results["qdrant"]
        print("\ncontext_recall по питаннях:")
        mem_label = "пам'ять"
        print(f"  {mem_label:>12}{'Qdrant':>12}   питання")
        for i, case in enumerate(rc.CASES):
            print(f"  {a['context_recall'][i]:>12.2f}{b['context_recall'][i]:>12.2f}"
                  f"   {case['question'][:44]}…")
        same = all(abs(a['context_recall'][i] - b['context_recall'][i]) < 0.01
                   for i in range(len(rc.CASES)))
        if same:
            print("\ncontext_recall збігається між режимами.")
            print("Це і є відповідь лабораторної: retriever дістає ті самі правила,")
            print("хоч лежать вони тепер у сервері, а не в пам'яті процесу.")
        else:
            print("\ncontext_recall РОЗІЙШОВСЯ між режимами.")
            print("Сховища мали віддавати те саме, тож розбіжність — привід")
            print("звірити вміст колекції з правилами в пам'яті:")
            print("  python -m practice.challenges.kb_qdrant --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
