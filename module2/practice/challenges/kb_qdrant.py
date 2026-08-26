"""
ЧЕЛЕНДЖ · курсова база правил у Qdrant. Те, чим мав бути knowledge_qdrant.py.

Картка лабораторної посилається на курсовий файл `knowledge_qdrant.py`, якого в
репозиторії немає — у ньому лише згадка в коментарі `knowledge_vec.py`, що
покласти ці вектори в Qdrant буде наступним кроком. Цей файл і є той крок,
написаний у практиці, бо курсові файли не змінюються.

З оновленням курсу від 26 серпня 2026 курсовий `knowledge_qdrant.py` з'явився:
він потребує пакета `qdrant-client` і тримає правила в колекції `postal_rules`.
Цей файл лишається версією практики — без нового пакета, у колекції `kb-e5`,
через той самий `qdrant_store`.

ЩО САМЕ ПЕРЕЇЖДЖАЄ

Не документи специфікації, а курсова база правил поштового оператора — `KB` із
`domain/knowledge.py`, десяток правил на кшталт «Правило 4.2. Якщо фактичний
строк доставки перевищує заявлений на 5 і більше днів...». Саме її міряє
курсовий `ragas_compare.py`, і саме її треба покласти в сервер, щоб прогнати
той вимір у двох режимах.

ЧОМУ ВЕКТОРИ РАХУЄ КУРСОВА ФУНКЦІЯ

Порівнювати два режими має сенс лише тоді, коли різниця між ними — сховище, а
не арифметика. Тому вектори тут рахує `knowledge_vec._embed` — та сама функція,
яку використовує режим у пам'яті, з тією самою моделлю і тими самими
префіксами. Нижня межа відмови теж береться звідти, а не переписується поруч:
`_THRESHOLD` живе в одному місці, і в обох режимах він означає те саме.

Функція приватна, і звертатися до неї збоку — не те, що роблять у бібліотеці.
Тут це свідомий вибір: власна копія тієї самої арифметики розійшлася б із
курсовою за першої ж зміни, і вимір почав би порівнювати не сховища.

ІНТЕРФЕЙС

`retrieve`, `scores`, `as_context` — з тими самими підписами, що в
`knowledge_vec`. Через це підміна режиму зводиться до підміни модуля: агент,
промпт і сам вимір лишаються недоторканими.

    python -m practice.challenges.kb_qdrant           # залити правила, $0
    python -m practice.challenges.kb_qdrant --info    # що в колекції
    python -m practice.challenges.kb_qdrant --check   # звірити з режимом у пам'яті
"""

import sys

import knowledge_vec as vec
from domain.knowledge import KB

from practice.challenges.qdrant_store import (
    QDRANT_URL, QdrantUnavailable, _request, alive, ask_consent, collection_info,
)

COLLECTION = "kb-openai" if vec._USE_OPENAI else "kb-e5"


class _Rule:
    """Правило як фрагмент: мінімум полів, потрібних оцінці обсягу."""

    def __init__(self, keys: str, text: str):
        self.keys = keys
        self.text = text


def rules() -> list:
    return [_Rule(keys, text) for keys, text in KB]


def _ensure(dim: int) -> bool:
    info = collection_info_of(COLLECTION)
    if info is not None:
        have = info["config"]["params"]["vectors"]["size"]
        if have != dim:
            raise QdrantUnavailable(
                f"Колекція {COLLECTION} тримає вектори довжини {have}, а модель "
                f"дає {dim}. Нічого не змінюю: приберіть стару колекцію самі.")
        return False
    _request("PUT", f"/collections/{COLLECTION}",
             {"vectors": {"size": dim, "distance": "Cosine"}})
    return True


def collection_info_of(name: str) -> dict | None:
    try:
        return _request("GET", f"/collections/{name}")["result"]
    except QdrantUnavailable as e:
        if "404" in str(e):
            return None
        raise


def ingest(verbose: bool = True) -> dict:
    """Заливає правила в Qdrant. Питає згоди так само, як решта сховища."""
    items = rules()
    vectors = vec._embed([f"{r.keys}. {r.text}" for r in items], kind="passage")
    dim = len(vectors[0])

    ok, why = ask_consent(items, dim, f"колекції {COLLECTION} (правила курсу)")
    if not ok:
        print(f"  пропускаю: {why}")
        return {"sent": 0}

    created = _ensure(dim)
    if verbose:
        print(f"  колекція:     {COLLECTION} — "
              f"{'створена' if created else 'уже була, лишаю як є'}")
    points = [{"id": i, "vector": v,
               "payload": {"text": r.text, "keys": r.keys}}
              for i, (r, v) in enumerate(zip(items, vectors))]
    _request("PUT", f"/collections/{COLLECTION}/points?wait=true",
             {"points": points})
    if verbose:
        print(f"  залито:       {len(points)} правил")
    return {"sent": len(points)}


def _search(query: str, k: int) -> list[tuple[float, str]]:
    info = collection_info_of(COLLECTION)
    if info is None or info["points_count"] < len(KB):
        raise QdrantUnavailable(
            f"У Qdrant немає правил у колекції {COLLECTION}. Залийте їх:\n"
            "  python -m practice.challenges.kb_qdrant")
    q = vec._embed([query], kind="query")[0]
    found = _request("POST", f"/collections/{COLLECTION}/points/query",
                     {"query": q, "limit": k, "with_payload": ["text"]})
    return [(float(h["score"]), h["payload"]["text"])
            for h in found["result"]["points"]]


def scores(query: str, k: int = 3) -> list[tuple[float, str]]:
    """Підпис і зміст — як у knowledge_vec.scores."""
    return _search(query, k)


def retrieve(query: str, k: int = 3) -> list:
    """Правила понад нижньою межею. Межа спільна з режимом у пам'яті."""
    return [t for s, t in _search(query, k) if s >= vec._THRESHOLD]


def as_context(query: str, k: int = 3) -> str:
    """Дослівно та сама поведінка, що в knowledge_vec: порожньо краще за хибне."""
    hits = retrieve(query, k)
    if not hits:
        return ""
    return "\n\nВитяг з бази знань:\n" + "\n---\n".join(hits)


def check() -> int:
    """Звіряє видачу двох режимів на демонстраційних запитах курсу."""
    print(f"── Правила: пам'ять проти Qdrant · {COLLECTION} ──")
    bad = 0
    for query in vec.DEMO_QUERIES:
        in_memory = vec.scores(query, 3)
        in_qdrant = scores(query, 3)
        same = ([t for _, t in in_memory] == [t for _, t in in_qdrant])
        gap = max((abs(a - b) for (a, _), (b, _) in zip(in_memory, in_qdrant)),
                  default=0.0)
        ok = same and gap < 1e-3
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  «{query[:56]}»")
        print(f"        порядок {'той самий' if same else 'РІЗНИЙ'}, "
              f"найбільша розбіжність косинуса {gap:.5f}")
        for (s_mem, t), (s_srv, _) in zip(in_memory, in_qdrant):
            print(f"          {s_mem:.4f} / {s_srv:.4f}  {t[:60]}")
    print()
    if bad:
        print(f"РОЗБІЖНОСТЕЙ: {bad} з {len(vec.DEMO_QUERIES)}")
        return 1
    print(f"Усі {len(vec.DEMO_QUERIES)} запитів дали однакову видачу з обох сховищ.")
    return 0


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if not alive():
        print(f"Сервера немає за адресою {QDRANT_URL}. Підніміть його:")
        print("  docker compose up -d   або   "
              "python -m practice.challenges.qdrant_store --up")
        return 1
    if "--info" in argv:
        info = collection_info_of(COLLECTION)
        print(f"── Qdrant {QDRANT_URL} · колекція {COLLECTION} ──")
        if info is None:
            print("  колекції немає — залийте правила:")
            print("    python -m practice.challenges.kb_qdrant")
            return 1
        params = info["config"]["params"]["vectors"]
        print(f"  правил:       {info['points_count']}")
        print(f"  вектор:       {params['size']} чисел, відстань {params['distance']}")
        print(f"  нижня межа:   {vec._THRESHOLD}")
        return 0
    if "--check" in argv:
        return check()

    print(f"── Правила курсу у Qdrant {QDRANT_URL} ──")
    ingest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
