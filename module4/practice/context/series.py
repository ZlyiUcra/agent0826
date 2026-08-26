"""
КОНТЕКСТ · та сама розмова кількома способами, одна таблиця. ПЛАТНА.

Третій чекбокс картки хоче «вартість до і після на тій самій розмові», сьомий —
різницю між правильним і неправильним порядком промпта. Серія проганяє довгий
сценарій зі script.py кілька разів поспіль, міняючи щоразу одну річ, і зводить
результати в таблицю: гроші, скільки прочитано з кеша, вікно на останній
репліці — і що з важливого дожило до кінця.

    full              усе як є, з кешем — точка відліку
    cut               обрізання без пам'яті розмови — найдешевше і забуває
    cut+memory        те саме обрізання, але нотатка пам'яті розмови лишається
    prune             старе знайдене прибрано, сказане читачем — усе на місці
    summary           старі репліки переказує дешева модель
    full-nocache      як full, але без кеш-точок — ціна самого кеша
    full-wrong-order  кеш є, але мінливе стоїть на початку промпта

Пам'ять, що переживає розмову, у серії вимкнена навмисно: інакше другий прогін
дістав би правила читача з бази, і було б не зрозуміти, що саме їх зберегло —
стратегія історії чи сховище. Її показує окремо пара dialog --script long і
dialog --script recall у новому процесі.

Записи прогонів серії лишаються на диску незакритими бесідами — їх прибере
наступний вхід у dialog чи series, спитавши. Тож переписати числа в документ
варто до нього.

Усе на дешевій моделі. Порядок ціни одного прогону довгого сценарію — десяті
частки долара; серія цілком — близько двох доларів. Дорожчий за всіх прогін
з неправильним порядком: він платить за запис у кеш на кожному виклику.

    python -m practice.context.series
    python -m practice.context.series --only full,cut,prune
"""

import datetime
import json
import pathlib
import sys

from practice.common import nform
from practice.context import cleanup, dialog
from practice.context import script as scripts

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"

RUNS = {
    "full":             {},
    "cut":              {"strategy_name": "cut", "use_memory": False},
    "cut+memory":       {"strategy_name": "cut"},
    "prune":            {"strategy_name": "prune"},
    "summary":          {"strategy_name": "summary"},
    "full-nocache":     {"cache": False},
    "full-wrong-order": {"order": "wrong"},
}


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    wanted = list(RUNS)
    if "--only" in argv:
        wanted = argv[argv.index("--only") + 1].split(",")
        unknown = [w for w in wanted if w not in RUNS]
        if unknown:
            raise SystemExit(f"Немає прогону {unknown[0]}. Є: {', '.join(RUNS)}")

    cleanup.warn_and_sweep()
    n_turns, n_runs = len(scripts.LONG['turns']), len(wanted)
    print(f"── Серія · довгий сценарій, {n_turns} {nform(n_turns, 'репліка', 'репліки', 'реплік')} · "
          f"{n_runs} {nform(n_runs, 'прогін', 'прогони', 'прогонів')} ──\n")
    records = {}
    for name in wanted:
        print(f"▶ {name}")
        rec = dialog.run(script_name="long", long_memory=False, verbose=False, **RUNS[name])
        records[name] = rec
        c, g = rec["cost"], rec["growth"]
        print(f"  ${c['usd']:.4f} (без кеша ${c['usd_uncached']:.4f}) · {rec['elapsed_sec']} с"
              f" · вікно наприкінці {rec['turns'][-1]['parts']['total']:,}"
              f" · {'; '.join(scripts.verdict(scripts.LONG, rec['checks']))}")

    print(f"\n  {'прогін':<18}{'$':>9}{'$ без кеша':>12}{'з кеша':>10}{'вікно':>8}"
          f"{'знайдене':>10}{'метод':>7}{'правила':>9}{'≤3 реч.':>9}{'розділ':>8}")
    for name, rec in records.items():
        c, ch, last = rec["cost"], rec["checks"], rec["turns"][-1]["parts"]
        yes = lambda k: ("так" if ch[k] else "НІ") if k in ch else "—"
        print(f"  {name:<18}{c['usd']:>9.4f}{c['usd_uncached']:>12.4f}{c['cache_read']:>10,}"
              f"{last['total']:>8,}{last['found']:>10,}{yes('recalled_method'):>7}"
              f"{yes('recalled_rules'):>9}{ch['within_three']:>6}/{ch['answered']:<2}"
              f"{ch['cited']:>5}/{ch['answered']:<2}")

    OUT.mkdir(exist_ok=True)
    path = OUT / f"series-{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Збережено: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
