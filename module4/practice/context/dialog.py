"""
КОНТЕКСТ · розмова на багато реплік із власною історією. ПЛАТНА, дешева модель.

Центральна точка входу другої картки. Курсовий run_agent тут не годиться: він
бере один рядок і починає кожен виклик з чистого аркуша, а картці потрібна
історія, що росте від репліки до репліки. Тому цикл свій, а все довкола нього —
пошук, інструмент, промпт одного агента — те саме, що в base/single.py.

ЩО ВІДБУВАЄТЬСЯ НА КОЖНІЙ РЕПЛІЦІ

1. Дешева модель дістає з репліки читача факти, вартi пам'яті (memory.py).
2. До репліки дописується робоча нотатка: сьогоднішня дата, тема розмови,
   прохання читача. Це мінливе, тому воно стоїть у кінці — після кеш-точки.
3. Стратегія історії (history.py) вирішує, яку частину історії побачить модель.
4. Виклики йдуть, доки модель просить інструмент; кожен лягає в журнал разом із
   полями кеша.
5. Вікно, яке поїхало в останньому виклику репліки, розкладається на чотири
   частини (window.py) — п'ять безкоштовних запитів.

КЕШ І ПОРЯДОК

Кеш-точок дві: на сталому системному промпті й на останньому повідомленні
історії. Друга рухається з кожним викликом, тож попередній префікс читається з
кеша, а дописується лише нове. Мінімальний префікс для кешування на дешевій
моделі — 4096 токенів: перші репліки в кеш не потрапляють, і рядок «у кеш 0»
на них — не збій, а ця межа.

--order wrong ставить ту саму робочу нотатку не в кінець, а на початок
системного промпта — куди її кладуть найчастіше. Дата в ній містить секунди,
тож префікс інший на кожному виклику: з кеша не читається нічого, а запис у
нього оплачується щоразу — це дорожче, ніж без кеша взагалі.

    python -m practice.context.dialog                        # long · full · кеш · порядок правильний
    python -m practice.context.dialog --history cut          # обрізання, з пам'яттю розмови
    python -m practice.context.dialog --history cut --no-memory
    python -m practice.context.dialog --history prune        # без старого знайденого
    python -m practice.context.dialog --history summary      # підсумовування дешевою моделлю
    python -m practice.context.dialog --no-cache
    python -m practice.context.dialog --order wrong
    python -m practice.context.dialog --script short         # дві репліки, друга без теми
    python -m practice.context.dialog --script recall        # у НОВОМУ процесі після long
    python -m practice.context.dialog --list                 # сценарії і стратегії, $0
    python -m practice.context.dialog --chat                 # жива бесіда з клавіатури
    python -m practice.context.dialog --chat --history prune

ЖИВА БЕСІДА

--chat бере репліки не зі сценарію, а з клавіатури, і веде їх тією самою
машинерією: історія за обраною стратегією, кеш-точки, пам'ять розмови і та,
що її переживає. Пригадування з довгої пам'яті робиться на першій репліці —
раніше нема за чим шукати. Перевірок сценарію тут немає: перевіряти нема з
чим, бо правила ніхто не закладав наперед.

Закінчити бесіду — набрати /кінець або /end: розмова завершується, її запис
лягає на диск і в пам'ять як звичайно, і одразу після цього слід бесіди
прибирається — запис прогону з диска, факти про читача з пам'яті; обговорені
розділи лишаються. Це та сама дія, що відповідь «y» на «Бесіду закрито?» після
сценарію, лише без питання. Порожній рядок або Ctrl-D закінчують розмову без
прибирання — тоді питання «Бесіду закрито?» ставиться як завжди. Кеш промптів
на боці Anthropic до сліду не належить: його не видаляють, він сам згасає за
кілька хвилин без звернень.

Наприкінці розмови в терміналі — питання «Бесіду закрито?»; при вході —
попередження про незакриті бесіди. Що саме прибирається — context/cleanup.py.
"""

import copy
import datetime
import json
import pathlib
import sys
import time

from config import MAX_TOKENS, MAX_TURNS, MODEL_FAST
from domain.backend import dispatch

from practice.base import team
from practice.base.single import SINGLE_PROMPT
from practice.common import nform
from practice.context import cleanup, history, memory, window
from practice.context import script as scripts
from practice.context.ledger import Ledger

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
TOOLS = [team.SCHEMAS[team.TOOL_NAMES[team.GENERAL]]]
CACHE = {"type": "ephemeral"}


def _blocks(content) -> list[dict]:
    """Блоки відповіді як прості словники — щоб історію можна було і зберегти,
    і позначити кеш-точкою."""
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def _volatile(session, use_memory: bool) -> str:
    parts = [f"today is {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"]
    if use_memory and session.note():
        parts.append(session.note())
    return "Assistant's working notes, not part of the question: " + "; ".join(parts) + "."


def _system(order: str, long_block: str, volatile: str, cache: bool) -> list[dict]:
    stable = {"type": "text", "text": SINGLE_PROMPT}
    if cache:
        stable["cache_control"] = CACHE
    blocks = [stable]
    if long_block:
        blocks.append({"type": "text", "text": long_block})
    if order == "wrong" and volatile:
        blocks.insert(0, {"type": "text", "text": volatile})
    return blocks


def _strip_cache(blocks: list[dict]) -> list[dict]:
    return [{k: v for k, v in b.items() if k != "cache_control"} for b in blocks]


def _mark_last(messages: list) -> list:
    """Рухома кеш-точка: останній блок останнього повідомлення. Саму історію
    не чіпає — позначається копія."""
    if not messages:
        return messages
    last = copy.deepcopy(messages[-1])
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = CACHE
    return messages[:-1] + [last]


def _answer(blocks) -> str:
    if isinstance(blocks, str):
        return blocks
    return "\n".join(b["text"] for b in blocks if b.get("type") == "text").strip()


def growth(rows: list[dict]) -> dict:
    first, last = rows[0]["parts"], rows[-1]["parts"]
    deltas = {k: last[k] - first[k] for k in window.PARTS}
    top = max(deltas, key=deltas.get)
    share = last[top] / last["total"] * 100 if last["total"] else 0
    return {"part": top, "from": first[top], "to": last[top], "share": round(share, 1)}


END_COMMANDS = ("/кінець", "/end")


def chat_turns(state: dict):
    """Репліки з клавіатури для --chat. /кінець або /end ставить state["closed"]
    і завершує розмову; порожній рядок чи Ctrl-D завершують без закриття."""
    while True:
        try:
            text = input("› ").strip()
        except EOFError:
            print()
            return
        if not text:
            return
        if text.lower() in END_COMMANDS:
            state["closed"] = True
            return
        yield text


def run(script_name: str = "long", strategy_name: str = "full", cache: bool = True,
        order: str = "right", use_memory: bool = True, long_memory: bool = True,
        verbose: bool = True, turns=None) -> dict | None:
    """Одна розмова. `turns` — звідки брати репліки: за замовчуванням зі сценарію
    `script_name`, для --chat — з клавіатури (chat_turns). Повертає запис прогону
    або None, якщо реплік не було."""
    script = scripts.SCRIPTS.get(script_name)
    if turns is None:
        turns = script["turns"]
    team.register()
    ledger = Ledger()
    strategy = history.make(strategy_name, ledger)
    session = memory.SessionMemory()
    now = datetime.datetime.now()
    conversation = f"{script_name}-{now:%Y%m%d-%H%M%S}"

    store, where, long_block, recalled = None, "вимкнено", "", {"reader": [], "topics": []}
    if use_memory and long_memory:
        store, where = memory.open_store()

    tag = (f"{script_name} · історія {strategy_name} · кеш {'так' if cache else 'ні'}"
           f" · порядок {order} · пам'ять {'так' if use_memory else 'ні'}")
    if verbose:
        print(f"── Розмова · {tag} · {MODEL_FAST} ──")
        print(f"  пам'ять, що переживає розмову: {where}")

    messages: list = []
    answers, searches, rows = [], [], []
    last_total, started = 0, time.time()

    for n, text in enumerate(turns, 1):
        if n == 1:
            # Пригадування — за першою реплікою: у сценарії вона відома наперед,
            # у живій бесіді — лише тепер.
            if store is not None:
                recalled = store.recall(text)
                long_block = memory.block(recalled)
            if verbose:
                if long_block:
                    print("  з неї взято:")
                    for line in long_block.splitlines():
                        print(f"    {line}")
                print()
        new_facts = session.absorb(text, ledger) if use_memory else []
        volatile = _volatile(session, use_memory)
        messages.append({"role": "user",
                         "content": text if order == "wrong" else f"{text}\n\n({volatile})"})
        turn_searches, turn_rows, sent, system_blocks = [], [], messages, []
        for _ in range(MAX_TURNS):
            sent = strategy.shape(messages, last_total)
            system_blocks = _system(order, long_block,
                                    _volatile(session, use_memory) if order == "wrong" else "",
                                    cache)
            resp = ledger.create(model=MODEL_FAST, max_tokens=MAX_TOKENS,
                                 system=system_blocks, tools=TOOLS,
                                 messages=_mark_last(sent) if cache else sent)
            turn_rows.append(ledger.rows[-1])
            messages.append({"role": "assistant", "content": _blocks(resp.content)})
            if resp.stop_reason != "tool_use":
                break
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                out = dispatch(b.name, b.input)
                session.note_hits(out)
                turn_searches.append({"query": b.input.get("query", ""),
                                      "found": out.get("found", 0),
                                      "ids": [p["id"] for p in out.get("passages", [])]})
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False),
                                "is_error": "error" in out})
            messages.append({"role": "user", "content": results})

        answer = (_answer(messages[-1]["content"]) if messages[-1]["role"] == "assistant"
                  else scripts.NO_ANSWER)
        topics = session.note_answer(answer)
        parts = window.parts(MODEL_FAST, _strip_cache(system_blocks), TOOLS, sent)
        last_total = parts["total"]
        answers.append(answer)
        searches.append([s["query"] for s in turn_searches])
        row = {"n": n, "user": text, "answer": answer, "searches": turn_searches,
               "new_facts": new_facts, "topics": topics, "parts": parts, "calls": len(turn_rows),
               "cache_read": sum(r["cache_read"] for r in turn_rows),
               "cache_write": sum(r["cache_write"] for r in turn_rows),
               "usd": round(sum(r["usd"] for r in turn_rows), 6)}
        rows.append(row)
        if verbose:
            print(f"[{n:>2}] › {text}")
            for f in new_facts:
                print(f"      запам'ятав: {f}")
            for s in turn_searches:
                print(f"      пошук: «{s['query']}» → {s['found']}: {', '.join(s['ids']) or '—'}")
            if topics:
                print(f"      тема: {'; '.join(topics)}")
            print(f"      відповідь · {scripts.sentences(answer)} реч. · розділ "
                  f"{'є' if scripts.cites_section(answer) else 'НЕМАЄ'}")
            for line in answer.splitlines():
                print(f"        {line}")
            print(f"      вікно {window.line(parts)} · з кеша {row['cache_read']:,} / "
                  f"у кеш {row['cache_write']:,} · ${row['usd']:.4f}")

    if not rows:
        return None
    checks = scripts.check(script, answers, searches) if script else {}
    written = 0
    if store is not None:
        # Запис у пам'ять не має права втратити оплачений прогін: будь-який збій
        # сховища — не лише зниклий сервер — означає запис у файл і рядок про це.
        try:
            written = store.remember(memory.records_from(session, conversation))
        except Exception as e:
            fallback = memory.FileMemory()
            written = fallback.remember(memory.records_from(session, conversation))
            where = (f"сховище відпало наприкінці розмови ({type(e).__name__}: "
                     f"{str(e)[:120]}); записано у файл {fallback.path}")

    totals = ledger.totals()
    record = {"conversation": conversation, "script": script_name,
              "strategy": strategy_name, "cache": cache, "order": order,
              "memory": use_memory, "long_memory": use_memory and long_memory,
              "model": MODEL_FAST, "memory_storage": where, "recalled": recalled,
              "turns": rows, "checks": checks, "growth": growth(rows),
              "cost": totals, "cost_by_kind": ledger.by_kind(),
              "session_facts": session.facts, "topics": session.topics,
              "remembered": written, "elapsed_sec": round(time.time() - started, 1)}
    OUT.mkdir(exist_ok=True)
    name = (f"dialog-{script_name}-{strategy_name}{'' if use_memory else '-nomem'}-"
            f"{'cache' if cache else 'nocache'}-{order}-{now:%Y%m%d-%H%M%S}.json")
    path = OUT / name
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["path"] = str(path)
    if verbose:
        print_summary(record)
    return record


def print_summary(record: dict) -> None:
    rows = record["turns"]
    print(f"\n── Підсумок · {record['script']} · історія {record['strategy']} · кеш "
          f"{'так' if record['cache'] else 'ні'} · порядок {record['order']} · пам'ять "
          f"{'так' if record['memory'] else 'ні'} ──")
    print(f"  {'репл.':>5}{'вікно':>8}{'сист.':>7}{'інстр.':>7}{'розмова':>9}"
          f"{'знайдене':>10}{'з кеша':>9}{'у кеш':>8}{'$':>9}")
    for r in rows:
        p = r["parts"]
        print(f"  {r['n']:>5}{p['total']:>8,}{p['system']:>7,}{p['tools']:>7,}"
              f"{p['dialogue']:>9,}{p['found']:>10,}{r['cache_read']:>9,}"
              f"{r['cache_write']:>8,}{r['usd']:>9.4f}")
    g = record["growth"]
    if len(rows) > 1:
        print(f"  Росло швидше за все: {window.LABELS[g['part']]} — з {g['from']:,} до "
              f"{g['to']:,} токенів, {g['share']}% вікна на останній репліці.")
    if record["script"] in scripts.SCRIPTS:
        print("  Перевірки:")
        for line in scripts.verdict(scripts.SCRIPTS[record["script"]], record["checks"]):
            print(f"    {line}")
    c, kinds = record["cost"], record["cost_by_kind"]
    helpers = ", ".join(f"{k} ${v['usd']:.4f}" for k, v in kinds.items() if k != "dialog")
    print(f"  Вартість: ${c['usd']:.4f} за {c['calls']} {nform(c['calls'], 'виклик', 'виклики', 'викликів')}; "
          f"без кеша коштувало б "
          f"${c['usd_uncached']:.4f}" + (f"; допоміжні: {helpers}" if helpers else ""))
    print(f"  Час: {record['elapsed_sec']} с")
    print(f"  Пам'ять, що переживає розмову: {record['memory_storage']}"
          + (f"; записано {record['remembered']} "
             f"{nform(record['remembered'], 'запис', 'записи', 'записів')}" if record["remembered"] else ""))
    print(f"  Збережено: {record['path']}\n")


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--list" in argv:
        print("Сценарії:")
        for name, s in scripts.SCRIPTS.items():
            n = len(s['turns'])
            print(f"  {name:8} {n} {nform(n, 'репліка', 'репліки', 'реплік')} — перша: «{s['turns'][0][:70]}…»")
        print("Стратегії історії:", ", ".join(history.NAMES))
        print("Порядок промпта: right (типово), wrong")
        return 0

    def option(flag: str, default: str) -> str:
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                raise SystemExit(f"Після {flag} потрібне значення.")
            return argv[i + 1]
        return default

    chat = "--chat" in argv
    script_name = "chat" if chat else option("--script", "long")
    strategy_name = option("--history", "full")
    order = option("--order", "right")
    if not chat and script_name not in scripts.SCRIPTS:
        raise SystemExit(f"Немає сценарію '{script_name}'. Є: {', '.join(scripts.SCRIPTS)}")
    if strategy_name not in history.NAMES:
        raise SystemExit(f"Немає стратегії '{strategy_name}'. Є: {', '.join(history.NAMES)}")
    if order not in ("right", "wrong"):
        raise SystemExit("--order приймає right або wrong.")

    cleanup.warn_and_sweep()
    state = {"closed": False}
    if chat:
        print("Жива бесіда: питання — з клавіатури, англійською чи українською. "
              f"{' або '.join(END_COMMANDS)} — закінчити бесіду і прибрати її слід; "
              "порожній рядок або Ctrl-D — закінчити, лишивши бесіду незакритою.\n")
    record = run(script_name, strategy_name, cache="--no-cache" not in argv, order=order,
                 use_memory="--no-memory" not in argv, verbose="--quiet" not in argv,
                 turns=chat_turns(state) if chat else None)
    if record is None:
        print("Реплік не було — нічого не збережено.")
        return 0
    path = pathlib.Path(record["path"])
    if state["closed"]:
        store, _ = memory.open_store()
        print("  Бесіду закрито за командою; слід прибрано:")
        cleanup.print_removed(cleanup.close(path, record, store))
    else:
        cleanup.ask_close(path, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
