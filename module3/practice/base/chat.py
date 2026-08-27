"""
ОСНОВА · жива бесіда з графом. ПЛАТНА, на дешевій моделі з --fast.

Кожна репліка проходить увесь маршрут base/graph.py — роутер, спеціаліст,
запасний маршрут, критик, передача людині — з історією бесіди перед собою.
Історію тримає той самий чекпоінтер, що зупиняє граф перед передачею людині:
стан лежить у ньому під thread_id бесіди, поле history (репліки читача і
відповіді агента) накопичується редʼюсером add_messages від репліки до
репліки, а решта полів — маршрут, результат, причина передачі, відповідь
людини в паузі — переписується на початку кожної (graph._inputs).

ЩО З ІСТОРІЇ БАЧИТЬ КОЖЕН ВУЗОЛ

В історію лягає лише сказане: питання читача і фінальна відповідь агента.
Знайдені фрагменти і виклики інструментів попередніх реплік у модель не їдуть
— це стратегія prune з context/history.py, бо знайдене в бесіді росте
найшвидше, а читач його не казав. Роутер бачить попередні питання читача: без
них уточнення «а в Number так само?» теми не має. Спеціаліст бачить усі
попередні репліки повідомленнями перед новим питанням. Критик бачить
попереднє питання поруч із новим, інакше чернетку відповіді на уточнення нема
з чим звіряти. Стратегії cut і summary, кеш-точки і їхній вимір сюди не
переносилися: вони доведені другою карткою модуля 4 (context/dialog.py) і від
стека не залежать.

ПАМ'ЯТЬ

Два рівні з context/memory.py, без змін. Пам'ять розмови — факти, які читач
назвав про себе або про те, як йому відповідати; дешева модель дістає їх з
кожної репліки окремо, і вони їдуть робочою нотаткою в кінці питання, як у
dialog.py. Пам'ять, що переживає розмову, — колекція memory-e5 у Qdrant або
файл out/memory.json: на першій репліці вона віддає факти про читача і
схожі обговорені теми (у системний промпт спеціаліста), наприкінці бесіди
приймає нові. Виклик моделі для виділення фактів іде через graph.ask, тобто
в той самий облік USAGE, що й вузли графа, — вартість репліки одним числом.

    python -m practice.base.chat --fast                    # бесіда з клавіатури
    python -m practice.base.chat --fast "Що таке Proxy?"   # перша репліка з рядка, далі з клавіатури
    python -m practice.base.chat --fast --pause            # пауза перед передачею людині всередині репліки
    python -m practice.base.chat --fast --no-memory        # без пам'яті: лише історія
    прапорці --lexical, --rewrite, --live — ті самі, що в base/graph.py

КОМАНДИ І ВИХІД

Підказки ті самі, що в context/dialog.py: «ви ›» — програма чекає на репліку;
після Enter б'ються пульси вузлів графа («думає · роутер», «думає · спеціаліст
OBJECT», «думає · критик»), а відповідь друкується після «агент ›». Під нею —
маршрут, пошуки, посилання і вартість цієї репліки.

Рядок, що починається з «/», — команда, і в граф він не йде:

    /exit  /quit  /end   завершити бесіду; те саме — порожній рядок або Ctrl-D
    /alt                 три альтернативні спроби для останнього питання
    /help                перелік команд

/alt запускає над останньою відповіддю паралельні гілки base/graph.py (кути:
інший підхід, по кроках від специфікації, інший пошук) без повторного
проходу через роутер і спеціаліста — граф входить одразу у вузол variants.
Гілки з тим самим підходом групуються (модель-суддя, запасний збіг тексту),
друкується представник кожної групи, повтори — одним рядком; заголовок каже,
скільки різних від головної підходів є. Якщо остання відповідь була відмовою або
передачею людині і одна з гілок пройшла, вона заміняє ту відповідь і в
історії бесіди, тож далі розмова йде від неї; якщо відповідь і так пройшла,
в історії лишається вона, а гілки — лише поруч. Коли не пройшла жодна спроба,
але чернетки з вмістом є, відповіддю стає найкраща з них із попередженням
«Не перевірено: …» — і вона теж заміняє відмову в історії. Коли граф сам іде в гілки
(відповідь не пройшла decide()), вони друкуються одразу під реплікою.

Невідома команда друкує цей перелік і чекає на наступну репліку. Ctrl-C під
час репліки перериває лише її: виклик моделі зупиняється, репліка в історію
не потрапляє, бесіда триває; Ctrl-C на підказці «ви ›» завершує бесіду так
само, як /exit. У будь-якому з цих випадків запис лягає в out/chat-<дата>.json,
факти й теми — у довгу пам'ять. Слід бесіди тут не прибирається:
context/cleanup.py знає лише записи dialog-*.json, тож бесід графа він не чіпає.

МЕЖА

Бесіда живе, поки живе процес: InMemorySaver тримає стан у пам'яті, і новий
запуск історії попередньої бесіди не бачить — між запусками переживають лише
факти і теми в довгій пам'яті. Чекпоінтер на диску (пакет
langgraph-checkpoint-sqlite) — окрема залежність, і її не додано.
"""

import datetime
import json
import os
import sys
import time

from config import MAX_TURNS, MODEL_FAST
from core import cost

from langchain_core.messages import AIMessage

from practice.base import graph, team
from practice.common import nform
from practice.common.pulse import Pulse
from practice.context import memory

OUT = graph.OUT
END_COMMANDS = ("/exit", "/quit", "/end")
ALT_COMMAND = "/alt"
HELP = ("  команди: /exit — завершити бесіду (те саме — порожній рядок або Ctrl-D); "
        "/alt — три альтернативні спроби для останнього питання; /help — цей перелік")


class Extractor:
    """Те, що SessionMemory.absorb чекає від журналу dialog.py: метод
    ask(system, user, kind, max_tokens) → текст. Виклик іде через graph.ask,
    тож потрапляє в USAGE графа, а не в окремий облік."""

    def ask(self, system: str, user: str, kind: str = "memory",
            max_tokens: int = 200) -> str:
        return graph.ask(system, user, max_tokens=max_tokens, fast=True)


def note_for(session: memory.SessionMemory, use_memory: bool) -> str:
    """Робоча нотатка в кінці питання — слово в слово як _volatile у dialog.py:
    дата, тема розмови, прохання читача."""
    parts = [f"today is {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"]
    if use_memory and session.note():
        parts.append(session.note())
    return "Assistant's working notes, not part of the question: " + "; ".join(parts) + "."


def turns(first: str | None = None):
    """Репліки з клавіатури; `first` — репліка з рядка команди, що йде перед
    ними. Віддає лише питання: команди (рядки з «/») обробляються тут і в граф
    не потрапляють. Порожній рядок, Ctrl-D, Ctrl-C або /exit завершують."""
    if first:
        print(f"ви › {first}")
        yield first
    while True:
        try:
            text = input("ви › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text or text.lower() in END_COMMANDS:
            return
        if text.lower() == ALT_COMMAND:
            yield ALT_COMMAND
            continue
        if text.startswith("/"):
            if text.lower() != "/help":
                print(f"  невідома команда {text}; у граф вона не йде")
            print(HELP)
            continue
        yield text


def _replace_last_answer(app, cfg: dict, answer: str) -> bool:
    """Підміняє останню відповідь агента в history нитки: add_messages
    оновлює повідомлення з тим самим id замість того, щоб дописати нове."""
    history = app.get_state(cfg).values.get("history") or []
    last = next((m for m in reversed(history) if isinstance(m, AIMessage)), None)
    if last is None:
        return False
    app.update_state(cfg, {"history": [AIMessage(answer, id=last.id)]})
    return True


def _searches(result: dict) -> list[dict]:
    return [{"query": step["input"].get("query", ""),
             "found": step["output"].get("found", 0),
             "ids": [p["id"] for p in step["output"].get("passages", [])]}
            for step in result.get("trace", [])
            if "passages" in step.get("output", {})]


def run(first: str | None = None, live: bool = False, pause: bool = False,
        use_memory: bool = True) -> dict | None:
    """Одна бесіда. Повертає запис бесіди або None, якщо реплік не було."""
    now = datetime.datetime.now()
    conversation = f"chat-{now:%Y%m%d-%H%M%S}"
    app = graph.build(pause)
    cfg = {"configurable": {"thread_id": conversation}, "recursion_limit": 30}
    session = memory.SessionMemory()
    extractor = Extractor()
    store, where = memory.open_store() if use_memory else (None, "вимкнено")

    print(f"── Бесіда з графом · {conversation} · {graph.current_model()} + {MODEL_FAST}"
          f" · MAX_TURNS={MAX_TURNS} · пам'ять {'так' if use_memory else 'ні'}"
          + (" · з паузою" if pause else "") + " ──")
    print(f"  пам'ять, що переживає розмову: {where}")
    print(HELP)
    # Модель ембедингів вантажиться до першої репліки під власним пульсом, а
    # не під «думає» першої відповіді — те саме, що в dialog.py.
    with Pulse("готує пошук"):
        team.warm_search(team.GENERAL)

    remembered, recalled = "", {"reader": [], "topics": []}
    rows, started = [], time.time()
    graph.reset_usage()
    interrupted, last = 0, None
    for text in turns(first):
        n = len(rows) + 1
        usd_before = cost.usd(graph.USAGE["by_model"])
        calls_before = graph.USAGE["calls"]
        turn_started = time.time()
        is_alt = text == ALT_COMMAND
        if is_alt and last is None:
            print("  /alt нема до чого: спершу поставте питання")
            continue
        new_facts = []
        try:
            if is_alt:
                result = graph.run_alt(app, cfg, last["query"], last["result"],
                                       reason=last["reason"], live=live, pause=pause,
                                       remembered=remembered,
                                       note=note_for(session, use_memory))
                if (result.get("chosen_variant") or result.get("unverified")) \
                        and _replace_last_answer(app, cfg, result["answer"]):
                    print("  відповідь в історії бесіди замінено на "
                          + ("обрану гілку" if result.get("chosen_variant")
                             else "найкращу неперевірену спробу"))
                text = last["query"]
                last = dict(last, result=result, reason="")
            else:
                if n == 1 and store is not None:
                    with Pulse("думає · пригадує з довгої пам'яті"):
                        recalled = store.recall(text)
                    remembered = memory.block(recalled)
                    if remembered:
                        print("  з неї взято:")
                        for line in remembered.splitlines():
                            print(f"    {line}")
                if use_memory:
                    with Pulse("думає · виділяє факти з репліки"):
                        new_facts = session.absorb(text, extractor)
                result = graph.run_turn(app, cfg, text, live=live, pause=pause,
                                        remembered=remembered,
                                        note=note_for(session, use_memory))
                last = {"query": text, "result": result,
                        "reason": (result.get("handoff") or {}).get("reason", "")}
        except KeyboardInterrupt:
            # Перервано лише цю репліку: в історію вона не лягла (update_state
            # іде наприкінці run_turn), витрачене на неї — у загальній сумі.
            interrupted += 1
            print(f"\n  репліку перервано (Ctrl-C) на {round(time.time() - turn_started, 1)} с, "
                  f"${cost.usd(graph.USAGE['by_model']) - usd_before:.4f} витрачено; "
                  "бесіда триває, /exit — завершити")
            continue
        for step in result.get("trace", []):
            session.note_hits(step["output"])
        topics = session.note_answer(result["answer"])
        usd = round(cost.usd(graph.USAGE["by_model"]) - usd_before, 6)
        calls = graph.USAGE["calls"] - calls_before
        row = {"n": n, "user": text, "command": ALT_COMMAND if is_alt else "",
               "answer": result["answer"],
               "route": graph.route_label(result), "routed_to": result["routed_to"],
               "router_raw": result.get("router_raw", ""), "outcome": result["outcome"],
               "handoff": bool(result.get("handoff")),
               "fabricated": result.get("citations", {}).get("fabricated", []),
               "searches": _searches(result), "new_facts": new_facts, "topics": topics,
               "variants": result.get("variants", []),
               "chosen_variant": result.get("chosen_variant", ""),
               "unverified": result.get("unverified"),
               "calls": calls, "usd": usd,
               "elapsed_sec": round(time.time() - turn_started, 1)}
        rows.append(row)

        for f in new_facts:
            print(f"      запам'ятав: {f}")
        print(f"  маршрут:      {row['route']}  (роутер відповів: {row['router_raw'] or '?'})")
        graph.print_steps(result)
        print("агент ›")
        for line in result["answer"].splitlines():
            print(f"        {line}")
        if topics:
            print(f"      тема: {'; '.join(topics)}")
        print(f"      репліка · {result['outcome']} · {calls} "
              f"{nform(calls, 'виклик', 'виклики', 'викликів')} · "
              f"{row['elapsed_sec']} с · ${usd:.4f}")

    if not rows:
        return None
    written = 0
    if store is not None:
        # Запис у пам'ять не має права втратити оплачену бесіду: збій сховища
        # означає запис у файл і рядок про це — як у dialog.py.
        try:
            written = store.remember(memory.records_from(session, conversation))
        except Exception as e:
            fallback = memory.FileMemory()
            written = fallback.remember(memory.records_from(session, conversation))
            where = (f"сховище відпало наприкінці бесіди ({type(e).__name__}: "
                     f"{str(e)[:120]}); записано у файл {fallback.path}")

    record = {"conversation": conversation, "stack": "langgraph",
              "model": graph.current_model(), "pause": pause, "live": live,
              "memory": use_memory, "memory_storage": where, "recalled": recalled,
              "turns": rows, "interrupted": interrupted,
              "session_facts": session.facts, "topics": session.topics,
              "remembered": written, "calls": graph.USAGE["calls"],
              "cost_usd": cost.usd(graph.USAGE["by_model"]),
              "cost_breakdown": cost.breakdown(graph.USAGE["by_model"]),
              "elapsed_sec": round(time.time() - started, 1)}
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{conversation}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["path"] = str(path)
    print(f"── Підсумок · {len(rows)} {nform(len(rows), 'репліка', 'репліки', 'реплік')}"
          + (f" (+{interrupted} перерв.)" if interrupted else "")
          + f" · {record['calls']} {nform(record['calls'], 'виклик', 'виклики', 'викликів')}"
          f" · ${record['cost_usd']:.4f} · {record['elapsed_sec']} с ──")
    print(f"  у довгу пам'ять: {written} "
          f"{nform(written, 'запис', 'записи', 'записів')} ({where})")
    print(f"  збережено:    {path}")
    return record


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--lexical" in argv:
        os.environ["PRACTICE_RETRIEVER"] = "lexical"
    if "--rewrite" in argv:
        os.environ["PRACTICE_REWRITE"] = "1"
    if "--fast" in argv:
        graph.use_fast_model()
    positional = [a for a in argv if not a.startswith("-")]
    run(first=positional[0] if positional else None, live="--live" in argv,
        pause="--pause" in argv, use_memory="--no-memory" not in argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
