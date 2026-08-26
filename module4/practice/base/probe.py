"""
ОСНОВА · перевірка пошуку без моделі: що саме побачить спеціаліст. $0.

Кожен спеціаліст відповідає лише з того, що повернув його пошук, тому перш
ніж платити за виклик моделі, варто подивитися на сам пошук: які фрагменти
він піднімає на запит і з якою оцінкою. Ця команда бере той самий індекс, що
й спеціалісти (base/team.py: набір PRACTICE_DOCS, вид пошуку
PRACTICE_RETRIEVER, підмножина родини), і друкує для кожного запиту верхівку
видачі.

    python -m practice.base.probe "Що таке графемний кластер?"     # видача GENERAL, весь набір
    python -m practice.base.probe --route WRAPPERS "toFixed"        # очима одного спеціаліста
    python -m practice.base.probe --k 5 "запит 1" "запит 2"         # кілька запитів, довша верхівка
    python -m practice.base.probe --suite                # сім запитів про документи довкола 402

Знак перед оцінкою: «+» — фрагмент подолав межу схожості і потрапив би в
tool_result спеціаліста, «-» — пошук його бачить, але не віддасть. Запити
--suite — ті самі, якими 26 серпня 2026 перевірявся набір suite після
додавання RFC 4647 і звітів Unicode: усі сім тоді підняли на перше місце
потрібний документ, і лише операнди множини пропустили між собою
Math.f16round з ECMA-262. На іншому наборі ті самі запити покажуть, що
пошук піднімає замість відсутніх документів.
"""

import os
import sys

from practice.base import team
from practice.common import corpus

SUITE_QUERIES = (
    "Що таке графемний кластер і де між двома графемами проходить межа?",
    "Які операнди n, i, v, w, f, t використовують правила множини?",
    "Як CLDR записує шаблон формату дати з полями y, M, d і символами скорочень?",
    "Що таке variable weighting пунктуації в алгоритмі сортування UCA?",
    "Як утворити ідентифікатор одиниці на кшталт kilometer-per-hour?",
    "Як працює схема lookup при зіставленні мовних тегів у RFC 4647?",
    "Як у CLDR задають правила підлаштування сортування (tailoring) для мови?",
)


def probe(route: str, queries: list[str], k: int) -> None:
    index = team.index_for(route)
    print(f"  індекс:       {type(index).__name__}, фрагментів {len(team.passages_for(route))}")
    for query in queries:
        print(f"\n› {query}")
        passing = {p.pid for p in index.retrieve(query, k)}
        for score, p in index.scores(query, k):
            mark = "+" if p.pid in passing else "-"
            print(f"  {mark} {score:.3f}  [{p.pid}]  {p.label}")


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    route, k, queries = team.GENERAL, 3, []
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--route" and args:
            route = args.pop(0).upper()
        elif arg == "--k" and args:
            k = int(args.pop(0))
        elif arg == "--suite":
            queries.extend(SUITE_QUERIES)
        else:
            queries.append(arg)
    if route not in team.ROUTES:
        raise SystemExit(f"Невідомий маршрут '{route}'. Доступні: {', '.join(team.ROUTES)}")
    if not queries:
        print(__doc__)
        return 1
    kind = os.getenv("PRACTICE_RETRIEVER", "auto")
    print(f"── Перевірка пошуку · набір {corpus.DOC_SET} · маршрут {route} · "
          f"пошук {kind} · верхівка {k} ──")
    probe(route, queries, k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
