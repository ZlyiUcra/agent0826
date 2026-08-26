"""
ЧЕЛЕНДЖ · перетин фрагментів: чи допомагає він пошуку на цих документах. $0.

Фрагменти практики не перетинаються: межа фрагмента — пронумерований
підзаголовок специфікації, і різати по ньому означає різати між закінченими
думками. Перетин (хвіст попереднього фрагмента, повторений на початку
наступного) — ліки від сліпого різання по N символів, коли ніж падає посеред
думки. Чи потрібні ці ліки там, де ніж падає між підзаголовками, — питання
виміру, а не смаку. Ось вимір.

ТРИ ВАРІАНТИ ІНДЕКСУ

  none   як у практиці: без перетину
  parts  перетин лише там, де довгий підрозділ справді розрізано на частини
         («частина 2 з 3»): останній абзац попередньої частини повторюється
         на початку наступної
  all    перетин між УСІМА сусідніми фрагментами одного документа — класичне
         ковзне вікно, як його уявляють для сліпого різання

Хвіст — останній абзац попереднього фрагмента, обрізаний до OVERLAP_CHARS з
початку рядка. Ідентифікатори фрагментів не змінюються, тож векторні кеші
варіантів розходяться відбитком (довжини текстів інші) і не заважають кешу
практики.

ЩО МІРЯЄТЬСЯ

Вісім запитів із відомим правильним підрозділом: п'ять із порівняння в практиці
модуля 2 (людські формулювання, та сама лінійка) і три з виміру цієї практики.
Для кожного варіанта і запиту:

  місце      позиція правильного підрозділу в повному списку за косинусом —
             головна метрика: чи піднімає перетин потрібне вище
  повтор     частка тексту в top-3, яка повторює текст іншого фрагмента з тих
             самих трьох — ціна перетину: три місця у видачі, і повтор з'їдає
             частину з них
  сусіди     скільки з top-3 — сусідні фрагменти одного документа, тобто
             скільки місць витягнув спільний хвіст, а не власний зміст

Модель ембедингів — та, що в практиці (e5-small за замовчуванням). Прогін не
звертається до моделей Anthropic і грошей не коштує; перший запуск рахує два
нові індекси на процесорі — хвилини.

    python -m practice.challenges.overlap
"""

import copy
import json
import pathlib
import sys
import time

from practice.common.corpus import load_passages
from practice.common.vectors import MODEL_NAME, VectorIndex

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"

OVERLAP_CHARS = 300

# (запит, підрядок ідентифікатора правильного підрозділу)
CASES = [
    ("How do I replace part of a text with something else?", "22.1.3.19"),
    ("What happens when a wrapper for true or false is created?", "20.3.1.1"),
    ("Can the parent of an object be locked so it never changes?", "10.4.7"),
    ("How does a stand-in object forward reads to the real one?", "10.5.8"),
    ("How does a function remember the object it was attached to?", "10.4.1"),
    ("What are the attributes of a data property, and what default values do "
     "they get when a property is created?", "6.1.7.1"),
    ("Як String.prototype.replace вирішує, чим замінити знайдений збіг, і що "
     "відбувається з рештою рядка?", "22.1.3.19"),
    ("What does Number.prototype.toFixed do when its argument is outside the "
     "allowed range?", "21.1.3.3"),
]

VARIANTS = ("none", "parts", "all")


def _tail(text: str) -> str:
    """Останній абзац, не довший за OVERLAP_CHARS, обрізаний з початку рядка."""
    para = text.split("\n\n")[-1]
    if len(para) <= OVERLAP_CHARS:
        return para
    cut = para[-OVERLAP_CHARS:]
    nl = cut.find("\n")
    return cut[nl + 1:] if nl != -1 else cut


def with_overlap(passages: list, mode: str) -> list:
    """Копія списку фрагментів із хвостом попереднього на початку наступного.

    Хвіст береться з ОРИГІНАЛЬНОГО попереднього фрагмента, а не з уже
    подовженого, щоб перетини не накопичувалися ланцюжком.
    """
    if mode == "none":
        return list(passages)
    out, prev = [], None
    for p in passages:
        q = copy.copy(p)
        if prev is not None and prev.doc_id == p.doc_id:
            cut_here = (mode == "all"
                        or (prev.section == p.section and p.parts > 1))
            if cut_here:
                q.text = _tail(prev.text) + "\n\n" + p.text
        out.append(q)
        prev = p
    return out


def _rank(scored_all, expected: str):
    for r, (_, p) in enumerate(scored_all):
        if expected in p.pid:
            return r + 1
    return None


def _repeat_share(top) -> float:
    """Частка символів у top-3, що повторюють абзац іншого фрагмента з трійки."""
    seen, total, repeated = set(), 0, 0
    for _, p in top:
        for para in p.text.split("\n\n"):
            total += len(para)
            if para in seen:
                repeated += len(para)
            seen.add(para)
    return round(repeated / total, 3) if total else 0.0


def _neighbours(top, order: dict) -> int:
    """Скільки фрагментів у top-3 стоять поруч з іншим фрагментом трійки."""
    positions = sorted(order[p.pid] for _, p in top)
    return sum(1 for a, b in zip(positions, positions[1:]) if b - a == 1)


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    base = load_passages()
    order = {p.pid: i for i, p in enumerate(base)}
    print(f"── Практика М4 · перетин фрагментів · {MODEL_NAME} · $0 ──")

    indexes = {}
    for mode in VARIANTS:
        passages = with_overlap(base, mode)
        started = time.time()
        idx = VectorIndex(passages=passages)
        extra = sum(len(q.text) for q in passages) - sum(len(p.text) for p in base)
        src = "з кеша" if idx.from_cache else f"порахований за {time.time() - started:.0f} с"
        print(f"  індекс {mode:5} {len(passages)} фрагментів, +{extra} символів "
              f"перетину, {src}")
        indexes[mode] = idx

    records = []
    for query, expected in CASES:
        print(f"── «{query[:70]}{'…' if len(query) > 70 else ''}» → {expected} ──")
        for mode in VARIANTS:
            idx = indexes[mode]
            scored_all = idx.scores(query, len(idx.passages))
            top = scored_all[:3]
            rank = _rank(scored_all, expected)
            rec = {"query": query, "expected": expected, "variant": mode,
                   "rank": rank, "top_score": round(top[0][0], 3),
                   "repeat_share": _repeat_share(top),
                   "neighbours": _neighbours(top, order),
                   "top3": [p.pid for _, p in top]}
            records.append(rec)
            place = "—" if rank is None else str(rank)
            print(f"  {mode:5} місце {place:>3}  найкращий {rec['top_score']:.3f}  "
                  f"повтор {rec['repeat_share']:.0%}  сусідів {rec['neighbours']}")

    print("── Підсумок ──")
    for mode in VARIANTS:
        rows = [r for r in records if r["variant"] == mode]
        ranks = [r["rank"] for r in rows if r["rank"] is not None]
        top1 = sum(1 for r in rows if r["rank"] == 1)
        top3 = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 3)
        rep = sum(r["repeat_share"] for r in rows) / len(rows)
        nb = sum(r["neighbours"] for r in rows)
        print(f"  {mode:5} на 1 місці: {top1} з {len(rows)}  у top-3: {top3} з "
              f"{len(rows)}  середнє місце: {sum(ranks) / len(ranks):.1f}  "
              f"повтор у top-3: {rep:.0%}  сусідів разом: {nb}")

    OUT.mkdir(exist_ok=True)
    path = OUT / f"overlap-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"model": MODEL_NAME, "overlap_chars": OVERLAP_CHARS,
                                "records": records}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"  збережено: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
