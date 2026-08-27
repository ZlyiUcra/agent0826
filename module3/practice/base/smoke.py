"""
ОСНОВА · безкоштовні перевірки переносу на LangGraph. Жодного звернення до
моделей Anthropic.

Ручний стек має власні перевірки в практиці модуля 4, і повторювати їх тут
нема сенсу: team.py, critic.py і system.py скопійовані звідти без змін. Тут
перевіряється те, що додав перенос: форма головного графа і підграфа,
інструменти з тих самих схем, серіалізація виводу інструмента, відновлення
траси з повідомлень, три результати циклу і ліміт кроків на підставній моделі,
облік вартості, умовні ребра, вузол передачі в усіх чотирьох станах, пауза
перед передачею, бесіда (історія в чекпоінтері між репліками, скидання решти
полів, що з історії бачать роутер, спеціаліст і критик, цикл реплік у
base/chat.py) і альтернативні спроби (редʼюсер, розвилка після критика,
розгалуження Send, лічильники гілок, лексичний пошук, вибір, /alt, збій
гілки, групування однакових гілок суддею і збігом тексту, друк представників
груп). Кожна перевірка друкує рядок ok/FAIL; будь-який FAIL завершує процес
із ненульовим кодом.

    python -m practice.base.smoke           # $0, секунди
"""

import contextlib
import copy
import io
import json
import pathlib
import sys
import tempfile

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


class FakeModel:
    """Підставна модель: віддає заготовлені повідомлення по черзі; коли
    заготовки скінчилися — повторює останнє. Виняток замість повідомлення
    імітує збій API.

    Кожен виклик повертає НОВИЙ об'єкт без id: редʼюсер add_messages ставить
    повідомленню id при першому проході, і той самий об'єкт удруге він
    сприйняв би як оновлення вже наявного, а не як наступне повідомлення.
    Справжня модель щоразу повертає новий об'єкт, тож підставна робить так само."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0
        self.seen = []      # що саме приходило моделі на кожному виклику

    def invoke(self, messages):
        self.calls += 1
        self.seen.append(list(messages))
        item = self.script[min(self.calls, len(self.script)) - 1]
        if isinstance(item, Exception):
            raise item
        fresh = copy.deepcopy(item)
        fresh.id = None
        if fresh.tool_calls:
            fresh.tool_calls = [dict(c, id=f"{c['id']}-{self.calls}")
                                for c in fresh.tool_calls]
        return fresh


def _call(name: str, cid: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid,
                                              "type": "tool_call"}],
                     usage_metadata={"input_tokens": 100, "output_tokens": 10,
                                     "total_tokens": 110})


def _final(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata={"input_tokens": 100,
                                                   "output_tokens": 10,
                                                   "total_tokens": 110})


def main(argv: list[str]) -> int:
    from practice.base import graph, system, team

    # 1. Форма графа: п'ять вузлів, чотири умовні ребра, пауза перед handover.
    drawing = graph.build().get_graph()
    nodes = {n for n in drawing.nodes if not n.startswith("__")}
    check("граф має вісім вузлів: route, specialist, general, critic, variants, variant, "
          "pick, handover",
          nodes == {"route", "specialist", "general", "critic", "variants", "variant",
                    "pick", "handover"})
    conditional = [e for e in drawing.edges if e.conditional]
    check("десять умовних ребер: вхід, після спеціаліста, після критика, розгалуження "
          "на гілки, після вибору",
          sorted((e.source, e.target) for e in conditional)
          == [("__start__", "route"), ("__start__", "variants"),
              ("critic", "__end__"), ("critic", "handover"), ("critic", "variants"),
              ("pick", "__end__"), ("pick", "handover"),
              ("specialist", "critic"), ("specialist", "general"),
              ("variants", "variant")])
    paused = graph.build(pause=True)
    check("з --pause граф зупиняється перед handover",
          "handover" in list(getattr(paused, "interrupt_before_nodes", []) or []))

    # 2. Інструменти: ті самі імена, описи і схеми, що ручний стек віддає моделі.
    same = True
    for route in team.ROUTES:
        mine = graph.tools_for_route(route)
        theirs = team.tools_for_route(route)
        same &= [t.name for t in mine] == [s["name"] for s in theirs]
        same &= [t.description for t in mine] == [s["description"] for s in theirs]
        same &= [t.args_schema for t in mine] == [s["input_schema"] for s in theirs]
    check("інструменти кожного маршруту збігаються зі схемами team.py "
          "(імена, описи, схеми)", same)
    check("GENERAL без прямого пошуку: лише research_topic і request_handoff",
          [t.name for t in graph.tools_for_route(team.GENERAL)]
          == [team.RESEARCH_TOOL, team.REQUEST_TOOL])

    # 3. ToolNode серіалізує словник інструмента так само, як run_agent, а
    # виняток усередині інструмента стає кроком failed, не падінням.
    schema = team.SCHEMAS[team.TOOL_NAMES["OBJECT"]]
    hit = {"found": 1, "passages": [{"id": "x#1", "section": "1 A", "text": "тест"}]}
    good = graph.tool_from_schema(schema, lambda query: hit)
    boom = graph.tool_from_schema(team.SCHEMAS[team.TOOL_NAMES["EXOTIC"]],
                                  lambda query: 1 / 0)

    def only_tools(tools):
        g = StateGraph(graph.LoopState)
        g.add_node("tools", ToolNode(tools, handle_tool_errors=graph._tool_error_text))
        g.add_edge(START, "tools")
        g.add_edge("tools", END)
        return g.compile()

    ai = _call(good.name, "c1", query="щось")
    tm = only_tools([good]).invoke({"messages": [ai], "turns": 1, "outcome": "",
                                    "error": ""})["messages"][-1]
    check("вивід інструмента приходить JSON-рядком без екранування кирилиці",
          isinstance(tm, ToolMessage) and tm.tool_call_id == "c1"
          and tm.content == json.dumps(hit, ensure_ascii=False))
    ai_boom = _call(boom.name, "c2", query="z")
    tm_boom = only_tools([boom]).invoke({"messages": [ai_boom], "turns": 1,
                                         "outcome": "", "error": ""})["messages"][-1]
    trace, failures = graph.trace_from_messages([ai_boom, tm_boom])
    check("виняток усередині інструмента → крок failed і запис у failures",
          getattr(tm_boom, "status", "") == "error" and trace[0].get("failed")
          and failures and "ZeroDivisionError" in failures[0]["error"])

    # 4. Траса з повідомлень має формат run_agent.
    trace, failures = graph.trace_from_messages(
        [HumanMessage("q"), ai, tm, _final("done")])
    check("траса відновлюється з повідомлень: turn, tool, input, output",
          trace == [{"turn": 0, "tool": good.name, "input": {"query": "щось"},
                     "output": hit}] and failures == [])
    check("_parse_output: помилка, JSON, не-JSON, відсутність відповіді",
          graph._parse_output(ToolMessage(content="Error: x", tool_call_id="1",
                                          status="error")) == {"error": "Error: x"}
          and graph._parse_output(ToolMessage(content='{"a": 1}', tool_call_id="1")) == {"a": 1}
          and graph._parse_output(ToolMessage(content="plain", tool_call_id="1")) == {"text": "plain"}
          and graph._parse_output(None) == {"error": "no_result"})
    check("текст відповіді збирається з текстових блоків",
          graph._text(_final([{"type": "text", "text": "a"},
                              {"type": "tool_use", "id": "1", "name": "x", "input": {}},
                              {"type": "text", "text": "b"}])) == "ab")

    # 5. Три результати циклу на підставній моделі; ліміт кроків як у run_agent.
    graph.reset_usage()
    ok_run = graph.run_loop("sys", [good], "q", max_turns=4,
                            llm=FakeModel([_call(good.name, "c1", query="a"),
                                           _final("Answer [x#1]")]))
    check("цикл: пошук, потім відповідь → outcome ok, один крок траси",
          ok_run["outcome"] == "ok" and ok_run["answer"] == "Answer [x#1]"
          and ok_run["turns"] == 2 and len(ok_run["trace"]) == 1
          and ok_run["no_tool_used"] is False)
    check("облік: два виклики моделі порахувано у USAGE за таблицею PRICES",
          graph.USAGE["calls"] == 2 and graph.USAGE["in"] == 200
          and graph.USAGE["out"] == 20
          and list(graph.USAGE["by_model"]) == [graph.current_model()])
    fake = FakeModel([_call(good.name, "c1", query="a")])
    exhausted = graph.run_loop("sys", [good], "q", max_turns=2, llm=fake)
    check("модель просить інструмент щоразу → turns_exhausted після max_turns "
          "викликів, інструменти останнього ходу виконано",
          exhausted["outcome"] == "turns_exhausted" and fake.calls == 2
          and exhausted["turns"] == 2 and len(exhausted["trace"]) == 2)
    failed = graph.run_loop("sys", [good], "q", max_turns=3,
                            llm=FakeModel([RuntimeError("down")]))
    check("збій моделі → outcome api_error з текстом помилки",
          failed["outcome"] == "api_error" and "RuntimeError" in failed["error"]
          and failed["turns"] == 1)
    check("модель без інструментів у циклі відповідає одразу",
          graph.run_loop("sys", [], "q", max_turns=3,
                         llm=FakeModel([_final("hi")]))["answer"] == "hi")

    # 6. Умовні ребра читають стан, не текст.
    check("після спеціаліста: причина запасного маршруту → general, інакше critic",
          graph.after_specialist({"fallback_why": "handover"}) == "general"
          and graph.after_specialist({"fallback_why": ""}) == "critic")
    check("після критика: збій → handover, причина по суті → variants, інакше кінець",
          graph.after_critic({"reason": "api_error"}) == "handover"
          and graph.after_critic({"reason": "fabricated"}) == "variants"
          and graph.after_critic({"reason": ""}) == END)
    check("роутер: невідоме слово стає GENERAL (system.normalize_route)",
          system.normalize_route("BANANA") == team.GENERAL
          and system.normalize_route("EXOTIC") == "EXOTIC")

    # 7. Вузол передачі: чотири стани. Черга запитів — у тимчасовому файлі.
    saved_pending = team.PENDING_FILE
    team.PENDING_FILE = pathlib.Path(tempfile.mkdtemp()) / "pending.json"
    try:
        base = lambda: {"answer": "чернетка", "trace": [], "outcome": "ok"}
        out = graph.node_handover({"result": base(), "query": "Що таке Proxy?",
                                   "reason": "fabricated", "declined": True})["result"]
        check("пауза, відповідь «ні»: чернетка лишається відповіддю з поміткою, "
              "передачі немає",
              out["handoff"].get("declined") and out["answer"].startswith("чернетка")
              and "скасовано" in out["answer"] and "ticket" not in out["handoff"])
        out = graph.node_handover({"result": base(), "query": "Що таке Proxy?",
                                   "reason": "research_empty", "confirmed": True})["result"]
        check("пауза, відповідь «так»: заявка HITL одразу, без черги --confirm",
              out["handoff"].get("confirmed") and out["handoff"]["ticket"].startswith("HITL-")
              and out["draft"] == "чернетка" and "підтверджено в паузі" in out["answer"])
        out = graph.node_handover({"result": base(), "query": "Що таке Proxy?",
                                   "reason": "api_error"})["result"]
        check("без паузи, збій: передача одразу з номером заявки",
              out["handoff"]["ticket"].startswith("HITL-") and out["handoff"]["by"] == "pipeline"
              and out["answer"].startswith("Передаю питання людині"))
        out = graph.node_handover({"result": base(), "query": "Що таке Proxy?",
                                   "reason": "research_empty"})["result"]
        queued = json.loads(team.PENDING_FILE.read_text(encoding="utf-8"))
        check("без паузи, «у документах немає»: запит у черзі, підказка називає "
              "команду цього файлу",
              out["handoff"].get("pending") and queued[-1]["status"] == "pending"
              and graph.CONFIRM_CMD in out["answer"]
              and "practice.base.system --confirm" not in out["answer"])
        note = graph.request_handoff("q", "r")["note"]
        check("request_handoff для моделі теж називає команду цього файлу",
              graph.CONFIRM_CMD in note and "practice.base.system" not in note)
    finally:
        team.PENDING_FILE = saved_pending

    # 8. Субагент: бюджет відхиляє без моделі; ліміт ходів — з team.py.
    team._research_used["n"] = team.RESEARCH_BUDGET
    refused = graph.research_topic("anything")
    check("дослідження понад бюджет відхиляється без виклику моделі",
          refused["outcome"] == "budget_spent" and refused["budget_spent"])
    team.reset_research()
    check("ліміт ходів субагента не більший за MAX_TURNS і за RESEARCH_TURNS",
          min(graph.MAX_TURNS, team.RESEARCH_TURNS) <= team.RESEARCH_TURNS)

    # 9. --fast перемикає лише головну модель; дешева лишається дешевою.
    before = graph.current_model()
    graph._MODELS["main"] = before
    check("use_fast_model переводить головну модель на MODEL_FAST",
          graph.use_fast_model() == graph.MODEL_FAST and graph.current_model() == graph.MODEL_FAST)
    graph._MODELS["main"] = before

    # 10. Бесіда: історія в чекпоінтері, скидання полів, що бачить кожен вузол.
    import builtins
    from practice.base import chat
    from practice.context import memory

    check("_inputs переписує кожне поле стану, крім history і known_ids",
          set(graph.State.__annotations__) - set(graph._inputs("q"))
          == {"history", "known_ids"})
    fake = FakeModel([_final("друга відповідь")])
    past = [HumanMessage("перше питання"), AIMessage("перша відповідь")]
    with_history = graph.run_loop("sys", [good], "друге питання", max_turns=3,
                                  llm=fake, history=past)
    check("run_loop з історією: модель бачить попередні репліки перед питанням, "
          "траса рахується лише від нього",
          [m.content for m in fake.seen[0][1:]] == ["перше питання", "перша відповідь",
                                                    "друге питання"]
          and with_history["turns"] == 1 and with_history["trace"] == []
          and with_history["answer"] == "друга відповідь")

    # Підставний спеціаліст шукає і цитує знайдене: без кроку пошуку
    # _fallback_why дав би «no_search», і репліка пішла б ще й через GENERAL.
    received = []
    found = {"found": 1, "passages": [{"id": "10-ordinary#10.1",
                                        "section": "10.1 Ordinary Object", "text": "…"}]}
    saved = (graph.ask, graph.run_loop, team.warm_search)
    graph.ask = lambda *a, **k: "OBJECT"
    graph.run_loop = lambda prompt, tools, query, **kw: (
        received.append({"prompt": prompt, "query": query,
                         "history": list(kw.get("history") or [])})
        or {"answer": f"відповідь на «{query.splitlines()[0]}» [10-ordinary#10.1]", "outcome": "ok",
            "trace": [{"turn": 0, "tool": "search", "input": {"query": "q"},
                       "output": found}],
            "failures": [], "turns": 2, "no_tool_used": False,
            "elapsed_sec": 0.0, "usage": {}})
    team.warm_search = lambda route=None: None
    try:
        app = graph.build()
        cfg = {"configurable": {"thread_id": "smoke-chat"}, "recursion_limit": 30}
        first = graph.run_turn(app, cfg, "Що таке Proxy?", remembered="MEMORY", note="NOTE")
        second = graph.run_turn(app, cfg, "А для Array?")
        history = app.get_state(cfg).values["history"]
        check("дві репліки на одній нитці: history росте парами питання-відповідь",
              [type(m).__name__ for m in history] == ["HumanMessage", "AIMessage"] * 2
              and history[0].content == "Що таке Proxy?"
              and history[1].content == first["answer"]
              and history[2].content == "А для Array?"
              and history[3].content == second["answer"])
        check("друга репліка: спеціаліст отримав історію першої, пам'ять і нотатка "
              "першої репліки до другої не дійшли",
              len(received) == 2 and received[0]["history"] == []
              and [m.content for m in received[1]["history"]]
              == ["Що таке Proxy?", first["answer"]]
              and received[0]["prompt"].endswith("MEMORY") and "(NOTE)" in received[0]["query"]
              and "MEMORY" not in received[1]["prompt"] and "NOTE" not in received[1]["query"])
        values = app.get_state(cfg).values
        check("після другої репліки в стані її запит, без причини передачі і без "
              "відповіді людини з попередньої",
              values["query"] == "А для Array?" and values["reason"] == ""
              and values["confirmed"] is False and values["declined"] is False)
    finally:
        graph.ask, graph.run_loop, team.warm_search = saved

    state = {"query": "А в Number так само?",
             "history": [HumanMessage("Що таке Proxy?"), AIMessage("…"),
                         HumanMessage("Як працює String.prototype.at?"), AIMessage("…")]}
    check("роутер і критик бачать попередні питання читача; без історії — лише запит",
          graph.router_input({"query": "q"}) == "q"
          and graph.critic_question({"query": "q"}) == "q"
          and "- Що таке Proxy?" in graph.router_input(state)
          and graph.router_input(state).endswith("А в Number так само?")
          and "String.prototype.at" in graph.critic_question(state)
          and "Proxy" not in graph.critic_question(state))

    keys = iter(["/foo", "/help", "друга репліка", "/exit", "не має дійти"])
    saved_input = builtins.input
    builtins.input = lambda prompt="": next(keys)
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            typed = list(chat.turns("перша репліка"))
    finally:
        builtins.input = saved_input
    session = memory.SessionMemory()
    session.facts = ["answer briefly"]
    check("chat: репліка з рядка команди йде першою, /команди в граф не йдуть, "
          "/exit завершує; нотатка несе факти сесії",
          typed == ["перша репліка", "друга репліка"]
          and "невідома команда /foo" in buffer.getvalue()
          and buffer.getvalue().count(chat.HELP) == 2
          and chat.note_for(session, True).startswith("Assistant's working notes")
          and "answer briefly" in chat.note_for(session, True)
          and "answer briefly" not in chat.note_for(session, False)
          and callable(getattr(chat.Extractor(), "ask", None)))

    # Уся бесіда на підставному графі: три репліки з клавіатури, другу з них
    # перериває Ctrl-C посеред виклику моделі; без пам'яті, запис — у
    # тимчасову теку, вивід — у буфер.
    replies = iter(["Перервана", "А для Array?", ""])
    saved = (graph.ask, graph.run_loop, team.warm_search, chat.OUT, builtins.input)
    graph.ask = lambda *a, **k: "OBJECT"

    def fake_loop(prompt, tools, query, **kw):
        if query.startswith("Перервана"):
            raise KeyboardInterrupt
        return {"answer": f"відповідь на «{query.splitlines()[0]}» [10-ordinary#10.1]", "outcome": "ok",
                "trace": [{"turn": 0, "tool": "search", "input": {"query": "q"},
                           "output": found}],
                "failures": [], "turns": 2, "no_tool_used": False, "elapsed_sec": 0.0,
                "usage": {}}
    graph.run_loop = fake_loop
    team.warm_search = lambda route=None: None
    chat.OUT = pathlib.Path(tempfile.mkdtemp())
    builtins.input = lambda prompt="": next(replies)
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            record = chat.run(first="Що таке Proxy?", use_memory=False)
        printed = buffer.getvalue()
        saved_record = json.loads(pathlib.Path(record["path"]).read_text(encoding="utf-8"))
    finally:
        graph.ask, graph.run_loop, team.warm_search, chat.OUT, builtins.input = saved
    check("chat.run: три репліки на підставному графі, друга перервана Ctrl-C — у записі "
          "дві, перервана в історію не лягла, бесіда дійшла до кінця",
          len(record["turns"]) == 2 and record["interrupted"] == 1
          and saved_record["conversation"].startswith("chat-")
          and [t["user"] for t in saved_record["turns"]] == ["Що таке Proxy?", "А для Array?"]
          and all(t["route"] == "OBJECT" and t["searches"][0]["ids"] == ["10-ordinary#10.1"]
                  for t in saved_record["turns"])
          and printed.count("агент ›") == 2 and "репліку перервано (Ctrl-C)" in printed
          and "відповідь на «А для Array?»" in printed
          and record["memory_storage"] == "вимкнено" and record["remembered"] == 0)

    # 11. Альтернативні спроби: редʼюсер, розвилка, розгалуження, гілки, вибір.
    import types
    check("редʼюсер variants: None скидає, список дописує",
          graph._fresh_or_add(None, [1]) == [1] and graph._fresh_or_add([1], [2]) == [1, 2]
          and graph._fresh_or_add([1, 2], None) == [])
    clean = {"reason": "", "result": {"routed_to": "OBJECT"}}
    check("після критика: збій сервісу чи інструментів → handover, причина по суті → "
          "variants, прохання моделі про людину → variants, --alt → variants, чисто → кінець",
          graph.after_critic({**clean, "reason": "api_error"}) == "handover"
          and graph.after_critic({**clean, "reason": "tool_error"}) == "handover"
          and all(graph.after_critic({**clean, "reason": r}) == "variants"
                  for r in graph.CONTENT_REASONS)
          and graph.after_critic({"reason": "", "result": {"handoff": {"by": "model"}}})
          == "variants"
          and graph.after_critic({**clean, "alt": True}) == "variants"
          and graph.after_critic(clean) == END)
    sends = graph.fan_out({"query": "q", "history": [],
                           "result": {"routed_to": "WRAPPERS", "draft": "чернетка",
                                      "answer": "відмова"},
                           "variants_why": "research found nothing"})
    check("розгалуження: три гілки Send, «по кроках» через GENERAL, решта — маршрутом "
          "головної спроби, попередня спроба — з чернетки і причини",
          len(sends) == 3 and all(x.node == "variant" for x in sends)
          and [x.arg["attempt"]["angle"] for x in sends] == list(graph.ANGLES)
          and [x.arg["attempt"]["route"] for x in sends] == ["WRAPPERS", "GENERAL", "WRAPPERS"]
          and all("чернетка" in x.arg["attempt"]["previous"]
                  and "research found nothing" in x.arg["attempt"]["previous"]
                  for x in sends)
          and all(x.arg["query"] == "q" for x in sends))

    ok_loop = lambda *a, **k: {"answer": "s [10-ordinary#10.1]", "outcome": "ok", "failures": [],
                               "trace": [{"turn": 0, "tool": "search", "input": {},
                                          "output": found}], "turns": 1}
    saved_loop, graph.run_loop = graph.run_loop, ok_loop
    try:
        steps = graph.attempt_impls("steps", team.GENERAL)
        approach = graph.attempt_impls("approach", "WRAPPERS")
        search = graph.attempt_impls("search", "WRAPPERS")
        outcomes = [steps[team.RESEARCH_TOOL]("t")["outcome"]
                    for _ in range(graph.STEPS_BUDGET + 1)]
        other = approach[team.RESEARCH_TOOL]("t")["outcome"]
    finally:
        graph.run_loop = saved_loop
    check("гілки: свій лічильник досліджень у кожній, бюджет «по кроках» більший, "
          "«інший пошук» підміняє пошук спеціаліста, спільний лічильник не рухається",
          outcomes.count("ok") == graph.STEPS_BUDGET and outcomes[-1] == "budget_spent"
          and other == "ok"
          and team.TOOL_NAMES["WRAPPERS"] in search
          and team.TOOL_NAMES["WRAPPERS"] not in approach
          and team._research_used["n"] == 0)

    def passage(pid):
        return types.SimpleNamespace(pid=pid, label="10.1 X", doc_title="d", text="t")

    class FakeIndex:
        def __init__(self):
            self.queries = []

        def scores(self, query, k=1):
            self.queries.append(query)
            return [(0.95 if "exact" in query else 0.5, passage("x#1"))]

        def retrieve(self, query, k=3):
            return [passage(f"x#{i}") for i in range(1, 4)] if "exact" in query \
                else [passage("x#1")]

    index = FakeIndex()
    saved = (graph._alt_index, graph.ask)
    graph._alt_index = lambda family: index
    try:
        graph.ask = lambda *a, **k: "exact terms"
        rewritten = graph._alt_searcher("WRAPPERS")("vague")
        graph.ask = lambda *a, **k: "vague"
        same = graph._alt_searcher("WRAPPERS")("vague")
    finally:
        graph._alt_index, graph.ask = saved
    check("«інший пошук»: бідний результат переписується через ask() графа і береться "
          "краща з двох спроб; переписування в той самий запит відкидається",
          rewritten["found"] == 3 and rewritten["rewritten_query"] == "exact terms"
          and rewritten["rewrite_used"] is True
          and same["found"] == 1 and "rewritten_query" not in same
          and index.queries == ["vague", "exact terms", "vague"])

    # Уся система на підставному графі: головна спроба GENERAL нічого не
    # знайшла, гілки — одна з вигаданим посиланням, одна зі збоєм, одна вдала.
    empty_research = {"answer": "нічого не знайшов", "outcome": "ok", "failures": [],
                      "trace": [{"turn": 0, "tool": team.RESEARCH_TOOL,
                                 "input": {"topic": "t"},
                                 "output": {"summary": "", "outcome": "ok", "searches": 1,
                                            "found_anything": False}}],
                      "turns": 2, "no_tool_used": False, "elapsed_sec": 0.0, "usage": {}}

    def good(text):
        return {"answer": text, "outcome": "ok", "failures": [], "turns": 2,
                "trace": [{"turn": 0, "tool": "search", "input": {"query": "q"},
                           "output": found}],
                "no_tool_used": False, "elapsed_sec": 0.0, "usage": {}}

    prompts, router_calls = [], []

    def branchy_loop(prompt, tools, query, **kw):
        prompts.append(prompt)
        if "ALTERNATIVE ATTEMPT" not in prompt:
            return dict(empty_research)
        if "DIFFERENT APPROACH" in prompt:
            return good("вигадка [99-nowhere#9.9]")
        if "STEP BY STEP" in prompt:
            raise RuntimeError("гілка впала")
        return good("інший пошук знайшов [10-ordinary#10.1]")

    def fake_router(*a, **k):
        router_calls.append(1)
        return team.GENERAL

    saved = (graph.ask, graph.run_loop, team.warm_search, team.PENDING_FILE, graph.ask_json)
    graph.ask, graph.run_loop = fake_router, branchy_loop
    graph.ask_json = lambda *a, **k: {"groups": None}      # суддя мовчить → збіг тексту
    team.warm_search = lambda route=None: None
    team.PENDING_FILE = pathlib.Path(tempfile.mkdtemp()) / "pending.json"
    try:
        app = graph.build()
        cfg = {"configurable": {"thread_id": "smoke-alt"}, "recursion_limit": 30}
        picked = graph.run_turn(app, cfg, "Складне питання")
        history = app.get_state(cfg).values["history"]
        labels = [v["reason"] for v in picked["variants"]]
        check("головна спроба не пройшла → три гілки паралельно → обрано першу вдалу; "
              "вигадане посилання і збій гілки відкинуто; передачі людині немає",
              picked["answer"] == "інший пошук знайшов [10-ordinary#10.1]"
              and picked["chosen_variant"] == "search"
              and picked["main_attempt"]["reason"] == "research_empty"
              and labels == ["fabricated", "branch_error", ""]
              and "гілка впала" in picked["variants"][1]["error"]
              and "handoff" not in picked and len(prompts) == 4
              and history[-1].content == picked["answer"]
              and graph._VARIANTS_PULSE["pulse"] is None)

        graph.run_loop = lambda prompt, tools, query, **kw: (
            prompts.append(prompt) or (dict(empty_research)
                                       if "ALTERNATIVE ATTEMPT" not in prompt
                                       else good("вигадка [99-nowhere#9.9]")))
        failed = graph.run_turn(app, cfg, "Ще складніше")
        check("жодна гілка не пройшла, але вміст є → найкраща чернетка з попередженням, "
              "без передачі; головна відмова у best_effort не бере участі",
              failed.get("variants_failed") and "handoff" not in failed
              and failed["unverified"]["reason"] == "fabricated"
              and failed["unverified"]["from"] == "approach"
              and failed["unverified"]["of"] == 4
              and failed["answer"].startswith("[Не перевірено: відповідь цитує розділи, "
                                              "яких пошук не повертав: 99-nowhere#9.9.")
              and failed["answer"].endswith("вигадка [99-nowhere#9.9]")
              and failed["draft"] == "вигадка [99-nowhere#9.9]"
              and [v["reason"] for v in failed["variants"]] == ["fabricated"] * 3)

        graph.run_loop = lambda prompt, tools, query, **kw: (
            prompts.append(prompt) or dict(empty_research))
        nothing = graph.run_turn(app, cfg, "Зовсім нічого")
        check("усі спроби — відмови без вмісту → передача людині з причиною головної "
              "спроби, чернетка і всі три гілки в результаті",
              nothing.get("variants_failed") and nothing["handoff"].get("pending")
              and nothing["handoff"]["reason"] == "research_empty"
              and nothing["draft"] == "нічого не знайшов"
              and [v["reason"] for v in nothing["variants"]] == ["research_empty"] * 3
              and "unverified" not in nothing
              and graph.CONFIRM_CMD in nothing["answer"])

        ranked = graph.best_effort(
            {"answer": "головна [99-nowhere#9.9]", "trace": [1, 2],
             "citations": {"cited": ["99-nowhere#9.9"], "fabricated": ["99-nowhere#9.9"]}},
            "fabricated",
            [{"angle": "approach", "angle_label": "інший підхід", "reason": "uncited",
              "answer": "без цитат", "trace": [1], "citations": {"cited": [], "fabricated": []}},
             {"angle": "steps", "angle_label": "по кроках", "reason": "fabricated",
              "answer": "три [a] [b] [c]", "trace": [1, 2, 3],
              "citations": {"cited": ["a", "b", "c"], "fabricated": ["a"]}},
             {"angle": "search", "angle_label": "інший пошук", "reason": "research_empty",
              "answer": "нічого", "trace": [], "citations": {"cited": [], "fabricated": []}}])
        check("best_effort: спершу найлегша вада (без цитат), відмова не кандидат; серед "
              "рівних вад — більше посилань",
              ranked["from"] == "approach" and ranked["reason"] == "uncited"
              and graph.best_effort({"answer": "г", "citations": {"cited": ["x"]}},
                                    "fabricated",
                                    [{"angle": "steps", "reason": "fabricated",
                                      "answer": "с", "trace": [],
                                      "citations": {"cited": ["a", "b"], "fabricated": ["a"]}}]
                                    )["from"] == "steps"
              and graph.best_effort({"answer": "нічого"}, "research_empty",
                                    [{"angle": "steps", "reason": "branch_error", "answer": ""}])
              is None)

        graph.run_loop = lambda prompt, tools, query, **kw: (
            prompts.append(prompt) or good("Головна: звичайні об'єкти і їхні внутрішні "
                                           "методи [10-ordinary#10.1]"
                                           if "ALTERNATIVE ATTEMPT" not in prompt
                                           else "гілка [10-ordinary#10.1]"))
        before_router, before_prompts = len(router_calls), len(prompts)
        fine = graph.run_turn(app, cfg, "Просте питання", alt=True)
        check("--alt при вдалій головній спробі: відповідь лишається головна, три гілки поруч",
              fine["answer"].startswith("Головна: звичайні") and "chosen_variant" not in fine
              and len(fine["variants"]) == 3
              and all(v["answer"] == "гілка [10-ordinary#10.1]" for v in fine["variants"])
              and len(prompts) - before_prompts == 4)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            graph.print_variants(fine)
        shown = buffer.getvalue()
        check("три однакові гілки без судді (роутер замість JSON) згортаються збігом тексту "
              "в одну: друкується одна, дві — рядком «повторює»",
              fine["variant_grouping"] == "text" and fine["distinct_variants"] == 1
              and [v["same_as"] for v in fine["variants"]] == ["", "approach", "approach"]
              and shown.count("повторює варіант 1 — не друкується") == 2
              and shown.count("гілка [10-ordinary#10.1]") == 1
              and "різних від головної: 1 з 3 (за збігом тексту)" in shown)

        turns_before = len(app.get_state(cfg).values["history"])
        before_router, before_prompts = len(router_calls), len(prompts)
        again = graph.run_alt(app, cfg, "Просте питання", fine)
        check("/alt: одразу до гілок над наявною відповіддю — без роутера і спеціаліста, "
              "history не росте",
              len(again["variants"]) == 3 and again["answer"].startswith("Головна: звичайні")
              and len(router_calls) == before_router
              and len(prompts) - before_prompts == 3
              and len(app.get_state(cfg).values["history"]) == turns_before)

        # Уточнення без пошуку, що цитує розділ, знайдений у попередній репліці
        # цієї ж нитки, — не вигадка; на свіжій нитці той самий текст — вигадка.
        graph.run_loop = lambda prompt, tools, query, **kw: {
            "answer": "Ще простіше: те саме [10-ordinary#10.1]", "outcome": "ok",
            "trace": [], "failures": [], "turns": 1, "no_tool_used": True,
            "elapsed_sec": 0.0, "usage": {}}
        followup = graph.run_turn(app, cfg, "А ще простіше?")
        fresh_cfg = {"configurable": {"thread_id": "smoke-fresh"}, "recursion_limit": 30}
        fresh = graph.run_turn(app, fresh_cfg, "А ще простіше?")
        check("посилання на розділ, знайдений у попередній репліці бесіди, — не вигадка "
              "(reused), гілки не запускаються; на свіжій нитці — вигадка, гілки, і "
              "найкраща чернетка з попередженням",
              followup["citations"]["fabricated"] == []
              and followup["citations"]["reused"] == ["10-ordinary#10.1"]
              and "variants" not in followup and "handoff" not in followup
              and "10-ordinary#10.1" in app.get_state(cfg).values["known_ids"]
              and fresh["citations"]["fabricated"] == ["10-ordinary#10.1"]
              and fresh.get("variants_failed") and "handoff" not in fresh
              and fresh["unverified"]["reason"] == "fabricated"
              and fresh["answer"].startswith("[Не перевірено"))
    finally:
        graph.ask, graph.run_loop, team.warm_search, team.PENDING_FILE, graph.ask_json = saved

    # 12. Групування гілок: суддя, перевірка його відповіді, запасний збіг тексту.
    judged = [{"angle": "approach", "answer": "Promise.race замість Promise.all, решта та сама"},
              {"angle": "steps", "answer": "split('') і map, потім Promise.all"},
              {"angle": "search", "answer": "Уточніть, який метод вас цікавить?"}]
    saved_ask = graph.ask
    graph.ask = lambda *a, **k: '{"groups": [["main", "approach"], ["steps"], ["search"]]}'
    try:
        groups, how = graph.group_variants("Promise.all по Promise.resolve(s[i])", judged)
    finally:
        graph.ask = saved_ask
    summaries = [{"angle": v["angle"], "reason": r, "same_as": ""}
                 for v, r in zip(judged, ["", "fabricated", "uncited"])]
    distinct = graph.mark_duplicates(summaries, groups)
    check("суддя: головна і «інший підхід» — одна група, решта окремо; різних від "
          "головної дві, повторює головну лише «інший підхід»",
          how == "judge" and groups == [["main", "approach"], ["steps"], ["search"]]
          and distinct == 2
          and [v["same_as"] for v in summaries] == ["main", "", ""])
    graph.ask = lambda *a, **k: '{"groups": [["main", "approach"], ["steps"]]}'
    try:
        groups, how = graph.group_variants("головна", judged)
    finally:
        graph.ask = saved_ask
    check("відповідь судді без одного з ідентифікаторів відкидається — групи за текстом",
          how == "text" and sorted(map(sorted, groups))
          == [["approach"], ["main"], ["search"], ["steps"]])
    graph.ask = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    try:
        groups, how = graph.group_variants("те саме речення про Promise.all",
                                           [{"angle": "approach",
                                             "answer": "Те саме речення про Promise.all."},
                                            {"angle": "steps", "answer": "зовсім інше"}])
    finally:
        graph.ask = saved_ask
    same_first = [{"angle": "approach", "reason": "", "same_as": ""},
                  {"angle": "steps", "reason": "", "same_as": ""}]
    check("збій судді → збіг тексту: майже однакові рядки в одній групі, інший — окремо",
          how == "text" and groups == [["main", "approach"], ["steps"]]
          and graph.mark_duplicates(same_first, groups) == 1
          and [v["same_as"] for v in same_first] == ["main", ""])
    graph.ask = lambda *a, **k: '{"groups": [["main"], ["approach"], ["steps"]]}'
    try:
        groups, how = graph.group_variants(
            "Не вдалося завершити обробку за відведену кількість кроків.",
            [{"angle": "approach",
              "answer": "Не вдалося завершити обробку за відведену кількість кроків."},
             {"angle": "steps", "answer": "зовсім інша відповідь про Proxy"}])
    finally:
        graph.ask = saved_ask
    check("суддя розвів дослівно однакові тексти → після нього вони зливаються в одну групу",
          how == "judge" and groups == [["main", "approach"], ["steps"]])
    check("представник групи без головної — перша гілка, що пройшла",
          (lambda s_: (graph.mark_duplicates(s_, [["main"], ["approach", "steps", "search"]]),
                       [v["same_as"] for v in s_]))(
              [{"angle": "approach", "reason": "fabricated", "same_as": ""},
               {"angle": "steps", "reason": "", "same_as": ""},
               {"angle": "search", "reason": "", "same_as": ""}])
          == (1, ["steps", "", "steps"]))

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — " + "; ".join(FAILED))
        return 1
    print("Усі перевірки пройдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
