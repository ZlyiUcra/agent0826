"""
ОСНОВА · та сама система на LangGraph: маршрутизатор → спеціаліст → запасний
маршрут → критик → передача людині, записана графом.

Це перенос, а не переписування. Задача та сама (питання про специфікацію
ECMAScript), інструменти ті самі (схеми і реалізації з base/team.py), правила
ті самі (промпти звідти ж, ознаки запасного маршруту і причини передачі людині
— з base/system.py). Інше лише те, ХТО крутить цикл і тримає стан:

  ручний стек (base/system.py)          цей файл
  цикл for у core/agent.py              підграф «модель ↔ інструменти», ребра
                                        задані явно, ліміт кроків — умовне ребро
  dispatch() по словнику IMPL           ToolNode: інструменти передаються
                                        списком, реєстр курсу не потрібен
  anthropic.messages.create             ChatAnthropic з langchain-anthropic
  порядок етапів — послідовність        вузли route → specialist → (general) →
  викликів у run_system                 critic → (handover), ребра умовні
  пауза перед передачею — файл-черга    те саме плюс interrupt_before:
  і друга команда --confirm             --pause зупиняє граф ПЕРЕД вузлом
                                        handover, людина відповідає в тому
                                        самому процесі, граф продовжує з місця
                                        зупинки, а не з початку

ЩО НЕ ЗМІНИЛОСЯ НАВМИСНО

Тексти інструментів, промпти спеціалістів, бюджет субагента, звірка посилань,
перелік причин передачі і тексти відмов — усе береться з base/team.py,
base/critic.py і base/system.py без копіювання. Інакше порівняння двох стеків
міряло б різницю промптів, а не різницю стеків.

Субагент research_topic тут теж на графі: той самий підграф «модель ↔
інструменти» з промптом RESEARCH_PROMPT і власною історією повідомлень, тобто
контекст GENERAL, як і раніше, не бачить проміжних фрагментів.

АЛЬТЕРНАТИВНІ СПРОБИ ЗАМІСТЬ ПЕРЕДАЧІ ЛЮДИНІ

Ручний стек після критика має два виходи: відповідь або передача людині. Тут
між ними стоїть третій — паралельні гілки (Send): коли decide() називає
причину, яку можна виправити іншою спробою (нічого не знайдено, критик не
пропустив, вигадані посилання, вичерпані кроки), або коли GENERAL сам попросив
людину, те саме питання одночасно йде трьома спробами з різними кутами
(ANGLES), кожна з текстом попередньої спроби перед очима, щоб не повторювати
її. Кожна гілка проходить звірку посилань і decide(); вузол pick бере першу,
що пройшла. Коли не пройшла жодна, але є чернетки з вмістом — відповідь без
цитат, не пропущена критиком або з посиланнями, яких пошук не повертав, —
віддається найкраща з них із попередженням на початку (best_effort), без
заявки і черги: це рішення власника, для якого людини, що розв'язує задачі за
специфікацією, за агентом немає, і «передаю людині» замість готових висновків
було гірше за висновки з позначкою «не перевірено». У handover маршрут іде
лише коли вмісту нема зовсім: збій сервісу чи інструментів, або всі спроби —
відмови «у документах немає». Збої сервісу й інструментів (api_error,
tool_error) гілками не лікуються і йдуть у handover одразу. --alt (у бесіді /alt) вмикає ті самі три
гілки для відповіді, яка і так пройшла, — щоб побачити альтернативи.

Три гілки нерідко приносять один і той самий розв'язок різними словами, тому
перед друком вони групуються: дешева модель-суддя (JUDGE_PROMPT) читає
головну відповідь і всі гілки разом і каже, які з них — той самий підхід;
коли суддя не відповідає JSON, групи рахуються збігом тексту (difflib).
Друкується один представник групи, решта — рядком «повторює …», і заголовок
каже, скільки різних підходів насправді є.

БЕСІДА

Той самий граф веде і бесіду на багато реплік — base/chat.py. Чекпоінтер,
який зупиняє граф перед передачею людині, між репліками тримає стан під
thread_id бесіди: поле history (репліки читача і відповіді агента)
накопичується редʼюсером add_messages, решта полів переписується на початку
кожної репліки (_inputs), і кожна репліка проходить увесь маршрут від роутера
до критика з історією перед собою (run_turn). Ідентифікатори фрагментів,
які пошук повертав у попередніх репліках, граф пам'ятає (known_ids): відповідь
на уточнення, що цитує розділ, знайдений двома репліками раніше, — не вигадка,
бо той текст модель бачила в цій самій бесіді; вигадкою лишається лише те,
чого пошук не повертав ніколи.

ЩО РАХУЄТЬСЯ

Вартість — з usage_metadata кожного повідомлення моделі, за тією самою
таблицею PRICES у core/cost.py, у той самий за формою словник USAGE, що в
core/agent.py; трасу викликів інструментів граф відновлює з повідомлень
(AIMessage.tool_calls плюс ToolMessage з тим самим tool_call_id), тож звірка
посилань і decide() читають її так само, як трасу run_agent.

    python -m practice.base.graph attrs           # сценарій із п'яти зафіксованих
    python -m practice.base.graph "свій запит"    # довільний запит
    python -m practice.base.graph --pause "…"     # зупинка перед передачею людині
    python -m practice.base.graph --alt "…"       # плюс три альтернативні спроби
    python -m practice.base.graph --confirm       # підтвердити запит із черги, $0
    python -m practice.base.graph --show          # вузли і ребра графа, $0
    python -m practice.base.graph --list          # перелік сценаріїв, $0
    python -m practice.base.chat "…"              # бесіда з графом на багато реплік
    прапорці: --fast, --lexical, --rewrite, --live — ті самі, що в base/system.py
"""

import difflib
import json
import os
import pathlib
import sys
import time
from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Send

from config import MAX_TOKENS, MAX_TURNS, MODEL, MODEL_FAST
from core import cost

from practice.base import critic, system, team
from practice.base.queries import QUERIES
from practice.common import nform, rewrite
from practice.common import search as psearch
from practice.common.pulse import Pulse

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
RESULTS = OUT / "graph_results.json"
CONFIRM_CMD = "python -m practice.base.graph --confirm"

# ── модель і облік ────────────────────────────────────────────

# Та сама підміна, що team.use_fast_model() для ручного стека: --fast переводить
# спеціалістів, субагента і критика на дешеву модель каскаду. Роутер і вердикт
# критика і так на MODEL_FAST.
_MODELS = {"main": MODEL}


def use_fast_model() -> str:
    _MODELS["main"] = MODEL_FAST
    return MODEL_FAST


def current_model() -> str:
    return _MODELS["main"]


def _llm(fast: bool, max_tokens: int | None = None,
         temperature: float | None = None) -> ChatAnthropic:
    """Клієнт langchain-anthropic. Ключ береться зі змінної ANTHROPIC_API_KEY,
    яку config.py уже прочитав із .env. max_retries=2 — ті самі три спроби,
    що в core/agent._call."""
    return ChatAnthropic(model=MODEL_FAST if fast else _MODELS["main"],
                         max_tokens=max_tokens or MAX_TOKENS,
                         temperature=temperature, max_retries=2)


# Той самий за формою накопичувач, що USAGE у core/agent.py, — щоб cost.usd()
# і cost.breakdown() працювали без змін.
USAGE = {"calls": 0, "in": 0, "out": 0, "by_model": {}}


def reset_usage() -> None:
    USAGE.update({"calls": 0, "in": 0, "out": 0, "by_model": {}})


def _track(model: str, message: AIMessage) -> None:
    u = message.usage_metadata or {}
    USAGE["calls"] += 1
    USAGE["in"] += u.get("input_tokens", 0)
    USAGE["out"] += u.get("output_tokens", 0)
    m = USAGE["by_model"].setdefault(model, {"calls": 0, "in": 0, "out": 0})
    m["calls"] += 1
    m["in"] += u.get("input_tokens", 0)
    m["out"] += u.get("output_tokens", 0)


def _text(message: AIMessage) -> str:
    """Текст відповіді: рядок або текстові блоки Anthropic."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "".join(b.get("text", "") for b in content
                   if isinstance(b, dict) and b.get("type") == "text").strip()


def ask(system_prompt: str, user: str, max_tokens: int = 400, fast: bool = True,
        temperature: float = 0.0) -> str:
    """Допоміжний виклик без інструментів — роутер, критик, переробка. Та сама
    сигнатура і ті самі умовчання, що в core/agent.ask."""
    model = MODEL_FAST if fast else _MODELS["main"]
    msg = _llm(fast, max_tokens, temperature).invoke(
        [SystemMessage(system_prompt), HumanMessage(user)])
    _track(model, msg)
    return _text(msg)


def ask_json(system_prompt: str, user: str, fallback: dict, fast: bool = True) -> dict:
    raw = ask(system_prompt + "\nПовертай ТІЛЬКИ валідний JSON, без пояснень.",
              user, fast=fast)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {**fallback, "_raw": raw[:200]}


# ── інструменти ───────────────────────────────────────────────

def tool_from_schema(schema: dict, impl) -> StructuredTool:
    """Інструмент langchain з тієї самої схеми, яку ручний стек віддає
    messages.create: ім'я, опис і input_schema передаються як є, тож модель
    бачить той самий текст."""
    return StructuredTool.from_function(func=impl, name=schema["name"],
                                        description=schema["description"],
                                        args_schema=schema["input_schema"])


def request_handoff(question: str, reason: str) -> dict:
    """Та сама черга, що в ручному стеку (out/pending_handoff.json); лише
    команда підтвердження в підказці — цього файлу."""
    out = team.request_handoff(question, reason)
    out["note"] = out["note"].replace("python -m practice.base.system --confirm",
                                      CONFIRM_CMD)
    return out


def make_research(budget: int = team.RESEARCH_BUDGET, search_impl=None,
                  counter: dict | None = None):
    """Субагент із власним контекстом — на тому самому підграфі, що й
    спеціалісти. Бюджет, ліміт ходів і замінний підсумок — з base/team.py.

    Штатний субагент рахує дослідження в team._research_used, як ручний стек.
    Альтернативним гілкам, що йдуть паралельно, дається кожній свій лічильник
    і, за потреби, свій бюджет і свій пошук: спільний лічильник три гілки
    вичерпали б утрьох, а зміну виду пошуку через змінну оточення побачили б
    усі потоки процесу."""
    counter = counter if counter is not None else team._research_used
    search_impl = search_impl or team.PRACTICE_IMPL[team.TOOL_NAMES[team.GENERAL]]

    def research_topic(topic: str) -> dict:
        counter["n"] += 1
        if counter["n"] > budget:
            return {"summary": (f"Research budget for this question is spent: "
                                f"{budget} topics were already researched. "
                                "Compose the answer from the summaries you already "
                                "have and do not call research_topic again."),
                    "outcome": "budget_spent", "searches": 0,
                    "found_anything": False, "budget_spent": True}
        tools = [tool_from_schema(team.SCHEMAS[team.TOOL_NAMES[team.GENERAL]],
                                  search_impl)]
        result = run_loop(team.RESEARCH_PROMPT, tools, topic,
                          max_turns=min(MAX_TURNS, team.RESEARCH_TURNS))
        found = any(step["output"].get("found") for step in result["trace"])
        summary, source = result["answer"], "model"
        if result["outcome"] != "ok" and found:
            summary, source = team.excerpt_summary(result["trace"]), "excerpts"
        return {"summary": summary, "outcome": result["outcome"],
                "searches": len(result["trace"]), "found_anything": found,
                "summary_from": source}

    return research_topic


research_topic = make_research()


_IMPLS = dict(team.PRACTICE_IMPL)
_IMPLS[team.RESEARCH_TOOL] = research_topic
_IMPLS[team.REQUEST_TOOL] = request_handoff


def tools_for_route(route: str, extra: list | None = None,
                    extra_impls: dict | None = None) -> list:
    """Ті самі схеми, що team.tools_for_route, загорнуті в інструменти
    langchain. Реєстр IMPL курсу не задіяний: ToolNode дістає реалізації
    прямо звідси."""
    impls = {**_IMPLS, **(extra_impls or {})}
    return [tool_from_schema(s, impls[s["name"]])
            for s in team.tools_for_route(route, extra)]


# ── підграф «модель ↔ інструменти» ────────────────────────────

class LoopState(TypedDict):
    messages: Annotated[list, add_messages]
    turns: int          # скільки разів викликано модель
    outcome: str        # "" поки триває; api_error — збій виклику
    error: str


def _tool_error_text(e: Exception) -> str:
    """Виняток усередині інструмента стає повідомленням зі статусом error, а не
    падінням прогону: далі трасa бачить крок як failed, і decide() вирішує про
    tool_error так само, як у ручному стеку. Без цього ToolNode кидає виняток
    нагору — прогін падає цілком."""
    return f"{type(e).__name__}: {e}"


def build_loop(system_prompt: str, tools: list, max_turns: int, note=None,
               llm=None):
    """Цикл «міркуй → дій → спостерігай» як граф із двох вузлів.

    Ліміт кроків — умовне ребро після вузла інструментів, а не recursion_limit:
    так завершення з turns_exhausted лишає стан цілим, і трасу викликів видно
    так само, як у run_agent. Порядок той самий, що там: модель викликається
    не більше max_turns разів, інструменти після останнього виклику ще
    виконуються, наступного виклику моделі немає.

    `llm` — підставна модель для безкоштовних перевірок (base/smoke.py):
    будь-який об'єкт з методом invoke(messages) → AIMessage. Звичайні виклики
    його не задають.
    """
    model_name = _MODELS["main"]
    if llm is None:
        llm = _llm(fast=False).bind_tools(tools) if tools else _llm(fast=False)

    def call_model(state: LoopState) -> dict:
        turn = state["turns"] + 1
        if note:
            note(f"виклик {turn} з {max_turns}")
        try:
            msg = llm.invoke([SystemMessage(system_prompt)] + state["messages"])
        except Exception as e:                                    # ← збій API
            return {"outcome": "api_error", "error": f"{type(e).__name__}: {e}",
                    "turns": turn}
        _track(model_name, msg)
        return {"messages": [msg], "turns": turn}

    def after_model(state: LoopState) -> str:
        if state.get("outcome") == "api_error":
            return END
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    def after_tools(state: LoopState) -> str:
        return END if state["turns"] >= max_turns else "model"

    g = StateGraph(LoopState)
    g.add_node("model", call_model)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=_tool_error_text))
    g.add_edge(START, "model")
    g.add_conditional_edges("model", after_model, {"tools": "tools", END: END})
    g.add_conditional_edges("tools", after_tools, {"model": "model", END: END})
    return g.compile()


def _parse_output(message: ToolMessage | None) -> dict:
    """Словник, який повернув інструмент: ToolNode серіалізує його в JSON тим
    самим json.dumps(ensure_ascii=False), що й run_agent, тож звідси він
    читається назад без втрат. Помилка інструмента приходить рядком зі
    статусом error — вона стає {"error": …}, як у run_agent."""
    if message is None:
        return {"error": "no_result"}
    content = message.content if isinstance(message.content, str) \
        else json.dumps(message.content, ensure_ascii=False)
    if getattr(message, "status", "success") == "error":
        return {"error": content}
    try:
        out = json.loads(content)
    except json.JSONDecodeError:
        return {"text": content}
    return out if isinstance(out, dict) else {"value": out}


def trace_from_messages(messages: list) -> tuple[list, list]:
    """Траса викликів інструментів у форматі run_agent: turn, tool, input,
    output, failed. Відновлюється з повідомлень графа — окремого журналу не
    ведеться, стан графа і є журнал."""
    replies = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    trace, failures, turn = [], [], -1
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        turn += 1
        for call in m.tool_calls:
            output = _parse_output(replies.get(call["id"]))
            step = {"turn": turn, "tool": call["name"], "input": call["args"],
                    "output": output}
            if "error" in output:
                step["failed"] = True
                failures.append({"tool": call["name"], "error": output["error"]})
            trace.append(step)
    return trace, failures


def run_loop(system_prompt: str, tools: list, query: str,
             max_turns: int = None, note=None, llm=None,
             history: list | None = None) -> dict:
    """Один прогін підграфа. Повертає result курсового формату: answer,
    outcome (ok | turns_exhausted | api_error), trace, failures, turns,
    no_tool_used, elapsed_sec, usage.

    `history` — попередні репліки бесіди (повідомлення читача і відповіді без
    викликів інструментів); вони стають перед новим питанням, а траса і
    лічильник кроків рахуються лише від нього."""
    max_turns = max_turns or MAX_TURNS
    history = list(history or [])
    app = build_loop(system_prompt, tools, max_turns, note, llm)
    started = time.time()
    out = app.invoke({"messages": history + [HumanMessage(query)], "turns": 0,
                      "outcome": "", "error": ""},
                     config={"recursion_limit": 2 * max_turns + 4})
    messages = out["messages"][len(history):]
    trace, failures = trace_from_messages(messages)
    last = messages[-1] if messages else None
    elapsed = round(time.time() - started, 2)
    if out.get("outcome") == "api_error":
        return {"answer": "Сервіс тимчасово недоступний. Передаю звернення оператору.",
                "outcome": "api_error", "error": out.get("error", ""),
                "trace": trace, "failures": failures, "turns": out["turns"],
                "elapsed_sec": elapsed, "usage": {}}
    if isinstance(last, AIMessage) and not last.tool_calls:
        u = last.usage_metadata or {}
        return {"answer": _text(last), "outcome": "ok",
                "trace": trace, "failures": failures, "turns": out["turns"],
                "no_tool_used": len(trace) == 0, "elapsed_sec": elapsed,
                "usage": {"input_tokens": u.get("input_tokens", 0),
                          "output_tokens": u.get("output_tokens", 0)}}
    return {"answer": "Не вдалося завершити обробку за відведену кількість кроків. "
                      "Передаю звернення оператору.",
            "outcome": "turns_exhausted", "trace": trace, "failures": failures,
            "turns": out["turns"], "elapsed_sec": elapsed, "usage": {}}


# ── критик на цьому стеку ─────────────────────────────────────

def check_citations(answer: str, trace: list, known=()) -> dict:
    """critic.check_citations плюс те, що знає бесіда: ідентифікатор, який
    пошук повертав у попередній репліці або в головній спробі цієї, — не
    вигадка, а повторне посилання (reused). Поза бесідою known порожній, і
    звірка збігається з ручним стеком."""
    checks = critic.check_citations(answer, trace)
    known = set(known)
    if known:
        here = critic.trace_pids(trace)
        checks["reused"] = sorted(c for c in checks["cited"] if c in known and c not in here)
        checks["fabricated"] = [c for c in checks["fabricated"] if c not in known]
    return checks


def run_critic(result: dict, system_prompt: str, query: str, known=()) -> dict:
    """Петля з критиком для WRAPPERS — та сама, що critic.run_critic: перевірка
    посилань, вердикт дешевої моделі, щонайбільше одне доопрацювання дорогою,
    повторна звірка. Промпти і правила — з base/critic.py; тут лише виклики
    моделі йдуть через langchain, а звірка знає попередні репліки бесіди."""
    checks = check_citations(result["answer"], result["trace"], known)
    verdict = ask_json(critic.CRITIC_PROMPT,
                       f"Питання: {query}\n\nЧернетка:\n{result['answer']}",
                       fallback={"ok": True, "remarks": "не розпарсено"}, fast=True)
    needs_rework = bool(checks["fabricated"]) or checks["uncited"] \
        or not verdict.get("ok")
    if not needs_rework:
        result["citations"] = checks
        result["critic"] = {"verdict": verdict, "revised": False, "ok": True}
        return result

    remarks = []
    if checks["fabricated"]:
        remarks.append("цитовано ідентифікатори, яких пошук не повертав: "
                       + ", ".join(checks["fabricated"]))
    if checks["uncited"]:
        remarks.append("пошук щось знайшов, а відповідь не цитує жодного фрагмента")
    if not verdict.get("ok"):
        remarks.append(str(verdict.get("remarks", "")))
    digest = "\n\n".join(
        f"[{p['id']}] {p['section']}\n{p['text']}"
        for step in result["trace"]
        for p in step.get("output", {}).get("passages", []))
    result["draft"] = result["answer"]
    result["answer"] = ask(
        system_prompt + "\nREWORK: fix the draft according to the critic's remarks. "
                        "Cite only ids from the excerpts below; if nothing below "
                        "supports a claim, drop the claim.",
        f"Question: {query}\n\nExcerpts returned by search:\n{digest}\n\n"
        f"Draft:\n{result['draft']}\nRemarks: {'; '.join(remarks)}",
        max_tokens=800, fast=False)
    checks_after = check_citations(result["answer"], result["trace"], known)
    ok = not checks_after["fabricated"] and not checks_after["uncited"]
    result["citations"] = checks_after
    result["critic"] = {"verdict": verdict, "revised": True, "ok": ok,
                        "remarks": remarks}
    return result


# ── головний граф ─────────────────────────────────────────────

def _union(left: list | None, right) -> list:
    """Редʼюсер known_ids: ідентифікатори накопичуються без повторів і не
    скидаються, поки живе нитка бесіди."""
    left = list(left or [])
    return left + [x for x in (right or []) if x not in left]


def _fresh_or_add(left: list | None, right) -> list:
    """Редʼюсер поля variants: паралельні гілки дописують результати списком,
    а None на вході репліки скидає поле — без цього варіанти попередньої
    репліки бесіди лишилися б у стані нитки."""
    if right is None:
        return []
    return list(left or []) + list(right)


class State(TypedDict, total=False):
    query: str
    live: bool
    route: str
    router_raw: str
    result: dict        # результат поточного маршруту в курсовому форматі
    fallback_why: str   # чому спеціаліст не закрив питання; "" — закрив
    reason: str         # причина передачі людині за decide(); "" — не потрібна
    confirmed: bool     # людина в паузі --pause підтвердила передачу
    declined: bool      # людина в паузі --pause відмовилася від передачі
    # Бесіда (base/chat.py). Поза нею history порожня, рядки — "".
    history: Annotated[list, add_messages]   # репліки читача і відповіді
    known_ids: Annotated[list, _union]       # що пошук повертав у попередніх репліках
    remembered: str     # блок довгої пам'яті — у системний промпт спеціаліста
    note: str           # робоча нотатка сесії — у кінець питання, як у dialog.py
    # Альтернативні спроби (паралельні гілки).
    alt: bool           # --alt: гілки і для відповіді, яка пройшла
    alt_only: bool      # /alt у бесіді: одразу до гілок, без повторного маршруту
    variants_why: str   # чому пішли в гілки; "" — не йшли
    variants: Annotated[list, _fresh_or_add]     # результати гілок
    attempt: dict       # вхід однієї гілки (лише в payload Send)


def _live_parts(state: State) -> tuple[list | None, dict | None, str]:
    if not state.get("live"):
        return None, None, ""
    from practice.challenges import live_fetch
    return [live_fetch.SCHEMA], {live_fetch.TOOL_NAME: live_fetch.fetch_spec}, \
        live_fetch.PROMPT_ADDON


def _run_route(state: State, route: str, label: str, prompt_addon: str = "",
               query_addon: str = "", impls: dict | None = None,
               pulse: Pulse | None = None) -> dict:
    """Один маршрут через підграф. `prompt_addon` і `query_addon` — дописки
    гілки (кут спроби, попередня спроба); `impls` — підмінені реалізації
    інструментів гілки; `pulse` — спільний пульс паралельних гілок замість
    власного, бо три власні пульси перемальовували б один рядок."""
    team.reset_research()
    extra, live_impls, live_addon = _live_parts(state)
    is_exotic = route == "EXOTIC"
    prompt = team.prompt_for_route(route) + (live_addon if is_exotic else "") + prompt_addon
    if state.get("remembered"):
        prompt += "\n\n" + state["remembered"]
    query = state["query"] + query_addon
    if state.get("note"):
        query += f"\n\n({state['note']})"
    merged = {**((live_impls or {}) if is_exotic else {}), **(impls or {})}
    tools = tools_for_route(route, extra if is_exotic else None, merged or None)
    if pulse is not None:
        team.warm_search(route)
        out = run_loop(prompt, tools, query, note=pulse.note, history=state.get("history"))
    else:
        with Pulse("готує пошук"):
            team.warm_search(route)
        with Pulse(f"думає · {label}") as own:
            out = run_loop(prompt, tools, query, note=own.note, history=state.get("history"))
    out["routed_to"] = route
    out["router_raw"] = state.get("router_raw", "")
    return out


def previous_questions(state: State, last: int = 3) -> list[str]:
    history = state.get("history") or []
    return [m.content for m in history if isinstance(m, HumanMessage)][-last:]


def router_input(state: State) -> str:
    """Що класифікує роутер: саме питання, а в бесіді — ще й попередні питання
    читача, бо уточнення «а в Number так само?» без них теми не має."""
    previous = previous_questions(state)
    if not previous:
        return state["query"]
    lines = "\n".join(f"- {q}" for q in previous)
    return (f"Попередні питання читача в цій бесіді:\n{lines}\n\n"
            f"Нове питання, яке треба класифікувати:\n{state['query']}")


def critic_question(state: State) -> str:
    """Питання для критика: у бесіді до нього дописується попереднє питання
    читача, інакше чернетку відповіді на уточнення нема з чим звіряти."""
    previous = previous_questions(state, last=1)
    if not previous:
        return state["query"]
    return f"{state['query']}\n(попереднє питання читача в бесіді: {previous[0]})"


def node_route(state: State) -> dict:
    with Pulse("думає · роутер"):
        raw = ask(system.ROUTER_PROMPT, router_input(state), max_tokens=10,
                  fast=True).upper().strip(".")
    return {"route": system.normalize_route(raw), "router_raw": raw}


def node_specialist(state: State) -> dict:
    route = state["route"]
    out = _run_route(state, route, f"спеціаліст {route}")
    why = system._fallback_why(out) if route != team.GENERAL else None
    return {"result": out, "fallback_why": why or ""}


def after_specialist(state: State) -> str:
    return "general" if state.get("fallback_why") else "critic"


def node_general(state: State) -> dict:
    out = _run_route(state, team.GENERAL, "запасний маршрут GENERAL")
    out["fallback_from"] = state["route"]
    out["fallback_why"] = state["fallback_why"]
    return {"result": out}


def node_critic(state: State) -> dict:
    result = state["result"]
    known = state.get("known_ids") or []
    if result["routed_to"] == "WRAPPERS":
        with Pulse("думає · критик"):
            run_critic(result, team.PROMPTS["WRAPPERS"], critic_question(state), known)
    if "citations" not in result:
        result["citations"] = check_citations(result["answer"], result["trace"], known)
    if system._handoff_called(result["trace"]):
        result["handoff"] = {"by": "model"}
    return {"result": result, "reason": system.decide(result) or "",
            "known_ids": sorted(critic.trace_pids(result["trace"]))}


# ── альтернативні спроби: паралельні гілки ─────────────────────

# Причини, яких інша спроба не виправить: гілки не запускаються, передача
# одразу. Решта причин decide() — привід спробувати інакше.
INFRA_REASONS = frozenset({"api_error", "tool_error"})
CONTENT_REASONS = frozenset(system.REASONS) - INFRA_REASONS
ATTEMPT_CHARS = 1500     # скільки знаків попередньої спроби бачить гілка
STEPS_BUDGET = 8         # бюджет субагента для кута «по кроках»

_ATTEMPT_HEAD = ("\n\nALTERNATIVE ATTEMPT. A previous attempt at this question is quoted "
                 "after the question, with the reason it was not accepted. Do not "
                 "repeat it. Every claim still needs a search result behind it, cited "
                 "by id; the rules below stay in force. ")

ANGLES = {
    "approach": {
        "label": "інший підхід",
        "addon": _ATTEMPT_HEAD + (
            "This attempt takes a DIFFERENT APPROACH: solve or answer with a "
            "different set of methods, constructs or specification sections than "
            "the previous attempt used or looked for."),
    },
    "steps": {
        "label": "по кроках від специфікації",
        "addon": _ATTEMPT_HEAD + (
            "This attempt goes STEP BY STEP FROM THE SPECIFICATION: break the "
            "question into the abstract operations and algorithm steps the "
            "specification defines (which abstract operation each method calls, "
            "what each step requires), look each one up separately, then assemble "
            "the answer from those findings. Your research budget for this attempt "
            f"is {STEPS_BUDGET} topics."),
    },
    "search": {
        "label": "інший пошук",
        "addon": _ATTEMPT_HEAD + (
            "This attempt uses a DIFFERENT SEARCH: the search tool now matches "
            "exact terms instead of meaning and rewrites vague queries, so search "
            "with the exact identifiers, method names, abstract operation names and "
            "section titles the specification uses, and try several phrasings."),
    },
}


def variants_why(state: State) -> str:
    """Чому потрібні альтернативні спроби, англійською для промпту гілок;
    "" — не потрібні."""
    reason = state.get("reason", "")
    result = state.get("result") or {}
    if reason in CONTENT_REASONS:
        return system.REASONS[reason][1]
    if (result.get("handoff") or {}).get("by") == "model":
        return "it asked for a human reviewer instead of answering"
    if state.get("alt"):
        return "it was accepted; a different attempt is wanted anyway"
    return ""


def after_critic(state: State) -> str:
    if state.get("reason") in INFRA_REASONS:
        return "handover"
    if variants_why(state):
        return "variants"
    return "handover" if state.get("reason") else END


_VARIANTS_PULSE: dict = {"pulse": None}


def _stop_variants_pulse() -> None:
    pulse = _VARIANTS_PULSE.pop("pulse", None)
    if pulse is not None:
        pulse.__exit__(None, None, None)
    _VARIANTS_PULSE["pulse"] = None


def node_variants(state: State) -> dict:
    """Перед розгалуженням: запам'ятати причину і запустити спільний пульс
    гілок; сам він гасне у вузлі pick."""
    _stop_variants_pulse()
    pulse = Pulse(f"думає · {len(ANGLES)} гілки паралельно")
    pulse.__enter__()
    _VARIANTS_PULSE["pulse"] = pulse
    return {"variants_why": variants_why(state)}


def _alt_index(family: str):
    """Лексичний індекс родини для кута «інший пошук» — незалежно від
    PRACTICE_RETRIEVER, бо змінна оточення спільна для всіх потоків."""
    key = (family, "lexical")
    if key not in _ALT_INDEXES:
        _ALT_INDEXES[key] = team._RETRIEVERS["lexical"](passages=team.passages_for(family))
    return _ALT_INDEXES[key]


_ALT_INDEXES: dict = {}


def _alt_searcher(family: str):
    """Пошук кута «інший пошук»: лексичний індекс і друга спроба з переписаним
    запитом — та сама логіка, що common/search.search з PRACTICE_REWRITE=1,
    лише переписування йде через ask() цього файлу, щоб виклик потрапив в
    USAGE графа, а не в облік ручного стека."""
    def impl(query: str) -> dict:
        index = _alt_index(family)
        hits, top = psearch.search_once(index, query)
        thin = len(hits) < rewrite.MIN_HITS or top < rewrite.confident_bar()
        if not hits or not thin:
            return psearch.format_hits(hits)
        try:
            second = ask(rewrite.REWRITE_PROMPT, query, max_tokens=120, fast=True)
        except Exception:
            second = ""
        second = second.strip().strip('"').splitlines()[0] if second.strip() else ""
        if not second or second.lower() == query.lower() or rewrite._looks_like_refusal(second):
            return psearch.format_hits(hits)
        hits2, top2 = psearch.search_once(index, second)
        took_second = (len(hits2), top2) > (len(hits), top)
        out = psearch.format_hits(hits2 if took_second else hits)
        out["rewritten_query"] = second
        out["rewrite_used"] = took_second
        return out
    return impl


def attempt_impls(angle: str, route: str) -> dict:
    """Підмінені реалізації інструментів однієї гілки: свій лічильник
    досліджень у кожній, більший бюджет для «по кроках», лексичний пошук для
    «інший пошук» — і в спеціаліста, і всередині субагента GENERAL."""
    budget = STEPS_BUDGET if angle == "steps" else team.RESEARCH_BUDGET
    search_impl = _alt_searcher(route) if angle == "search" else None
    impls = {team.RESEARCH_TOOL: make_research(
        budget, _alt_searcher(team.GENERAL) if angle == "search" else None, {"n": 0})}
    if search_impl is not None and route != team.GENERAL:
        impls[team.TOOL_NAMES[route]] = search_impl
    return impls


def _previous_attempt(result: dict, why: str) -> str:
    text = (result.get("draft") or result.get("answer") or "")[:ATTEMPT_CHARS]
    return f"\n\nPrevious attempt (not accepted: {why}):\n{text}"


def fan_out(state: State) -> list:
    """Розгалуження: одна гілка на кут, усі одночасно. Кут «по кроках» іде
    через GENERAL із субагентом, решта — тим маршрутом, яким пройшла попередня
    спроба."""
    main = state["result"]
    route = main.get("routed_to", team.GENERAL)
    shared = {k: state.get(k) for k in ("query", "live", "remembered", "note",
                                         "history", "router_raw", "known_ids")}
    previous = _previous_attempt(main, state.get("variants_why", ""))
    return [Send("variant", {**shared,
                             "attempt": {"angle": angle,
                                         "route": team.GENERAL if angle == "steps" else route,
                                         "previous": previous}})
            for angle in ANGLES]


def node_variant(state: dict) -> dict:
    """Одна гілка: той самий маршрут через підграф з дописками кута, звірка
    посилань і decide() — як у головній спробі, лише без критика. Збій гілки
    не валить прогін: він стає результатом з outcome branch_error."""
    attempt = state["attempt"]
    angle, route = attempt["angle"], attempt["route"]
    label = ANGLES[angle]["label"]
    try:
        out = _run_route(state, route, label, prompt_addon=ANGLES[angle]["addon"],
                         query_addon=attempt["previous"],
                         impls=attempt_impls(angle, route),
                         pulse=_VARIANTS_PULSE.get("pulse"))
        out["citations"] = check_citations(out["answer"], out["trace"],
                                           state.get("known_ids") or [])
        if system._handoff_called(out["trace"]):
            out["handoff"] = {"by": "model"}
        reason = system.decide(out) or ""
        if not reason and (out.get("handoff") or system._handover_requested(out)):
            reason = "handover"
        # Гілка існує заради обґрунтованої відповіді: пошук щось повернув, а
        # відповідь не цитує нічого — це не відповідь, а переказ, і decide()
        # такого не ловить (у ручному стеку це справа критика WRAPPERS).
        if not reason and out["citations"].get("uncited"):
            reason = "uncited"
    except Exception as e:                                        # ← збій гілки
        out = {"answer": "", "outcome": "branch_error", "error": f"{type(e).__name__}: {e}",
               "trace": [], "failures": [], "turns": 0, "routed_to": route,
               "citations": {"cited": [], "fabricated": [], "uncited": False}}
        reason = "branch_error"
    out.update(angle=angle, angle_label=label, reason=reason)
    return {"variants": [out]}


def variant_summary(v: dict) -> dict:
    return {"angle": v["angle"], "label": v["angle_label"], "routed_to": v.get("routed_to"),
            "outcome": v.get("outcome"), "reason": v.get("reason", ""),
            "turns": v.get("turns"), "searches": len(v.get("trace", [])),
            "cited": len((v.get("citations") or {}).get("cited", [])),
            "fabricated": (v.get("citations") or {}).get("fabricated", []),
            "answer": v.get("answer", ""), "error": v.get("error", "")}


JUDGE_PROMPT = (
    "You compare candidate answers to the same question about the ECMAScript "
    "specification. Two answers are the SAME when they take the same approach: "
    "the same solution shape (the same methods, constructs and steps doing the "
    "same jobs), or the same explanation of the same mechanism — wording, order, "
    "length, language and cited ids do not matter, and swapping one method for a "
    "sibling that plays the same role (Promise.all for Promise.race, a for-loop "
    "for map) does not make an answer different. Two answers are DIFFERENT when "
    "the work is done by a materially different mechanism, or the conclusion "
    "differs. An answer that only asks a clarifying question, or declines, is a "
    "group of its own. Every candidate is marked [id]. Return JSON of the shape "
    '{"groups": [["id", "id"], ["id"]]} with every id exactly once.'
)
JUDGE_CHARS = 2500      # скільки знаків кожної відповіді бачить суддя
SAME_RATIO = 0.85       # запасне порівняння: частка спільного тексту, від якої «те саме»


def _normalized(text: str) -> str:
    return " ".join((text or "").lower().split())


def _text_groups(items: list) -> list:
    """Запасне групування без моделі: відповідь потрапляє в групу, якщо її
    текст майже збігається з першою відповіддю групи."""
    groups: list = []
    first = {}
    for cid, text in items:
        for g in groups:
            if difflib.SequenceMatcher(None, _normalized(text),
                                       first[g[0]]).ratio() >= SAME_RATIO:
                g.append(cid)
                break
        else:
            groups.append([cid])
            first[cid] = _normalized(text)
    return groups


def group_variants(main_answer: str, variants: list) -> tuple[list, str]:
    """Групи однакових за підходом відповідей серед головної («main») і гілок
    (їхні кути). Повертає (групи, чим групували): «judge» — модель-суддя,
    «text» — збіг тексту, коли суддя не відповів JSON або впав, «single» —
    порівнювати нема з чим."""
    items = [("main", main_answer)] + [(v["angle"], v["answer"])
                                       for v in variants if v.get("answer")]
    if len(items) < 2:
        return [[cid] for cid, _ in items], "single"
    listing = "\n\n".join(f"[{cid}]\n{text[:JUDGE_CHARS]}" for cid, text in items)
    try:
        out = ask_json(JUDGE_PROMPT, listing, fallback={"groups": None}, fast=True)
    except Exception:
        out = {"groups": None}
    groups = out.get("groups")
    ids = sorted(cid for cid, _ in items)
    valid = (isinstance(groups, list) and groups
             and all(isinstance(g, list) and g for g in groups)
             and sorted(x for g in groups for x in g) == ids)
    if valid:
        return _merge_identical([list(g) for g in groups], dict(items)), "judge"
    return _text_groups(items), "text"


def _merge_identical(groups: list, texts: dict) -> list:
    """Після судді: групи, чиї перші відповіді майже збігаються текстом,
    зливаються. Суддя — модель, і в живому прогоні 27 серпня він назвав три
    дослівно однакові чернетки різними; однаковий текст — не питання смаку."""
    merged: list = []
    for g in groups:
        for m in merged:
            if difflib.SequenceMatcher(None, _normalized(texts[g[0]]),
                                       _normalized(texts[m[0]])).ratio() >= SAME_RATIO:
                m.extend(g)
                break
        else:
            merged.append(list(g))
    return merged


def mark_duplicates(summaries: list, groups: list) -> int:
    """Проставляє кожній гілці same_as — представника її групи: головну
    відповідь, якщо вона в групі, інакше першу гілку групи, що пройшла,
    інакше першу. Повертає, скільки груп не містять головної відповіді, —
    стільки справді різних альтернатив є."""
    by_angle = {v["angle"]: v for v in summaries}
    distinct = 0
    for g in groups:
        if "main" in g:
            rep = "main"
        else:
            distinct += 1
            passed = [x for x in g if not by_angle[x]["reason"]]
            rep = passed[0] if passed else g[0]
        for x in g:
            if x != rep and x in by_angle:
                by_angle[x]["same_as"] = rep
    return distinct


# Вади, з якими чернетка все ж має вміст, у порядку від найлегшої: без
# цитат, не пропущена критиком, з посиланнями, яких пошук не повертав. Решта
# причин — відмови і збої — вмісту не мають, і best_effort їх не бере.
CONTENT_DEFECTS = ("uncited", "critic_failed", "fabricated")
_DEFECT_TEXT = {
    "uncited": ("не цитує жодного фрагмента, хоча пошук щось знайшов",
                "cites no excerpt although the search found some"),
    "critic_failed": ("не пройшла перевірку критика і після доопрацювання",
                      "failed review even after one rework"),
    "fabricated": ("цитує розділи, яких пошук не повертав: {ids}",
                   "cites sections the search never returned: {ids}"),
}


def best_effort(main: dict, main_reason: str, variants: list) -> dict | None:
    """Найкраща з чернеток, що не пройшли: спершу за тяжкістю вади
    (CONTENT_DEFECTS), далі за кількістю посилань, далі за кількістю пошуків.
    Повертає словник {"attempt", "from", "label", "reason"} або None, коли
    жодна спроба вмісту не має."""
    pool = [(main_reason, "main", "головна спроба", main)]
    pool += [(v.get("reason", ""), v["angle"], v.get("angle_label", v["angle"]), v)
             for v in variants]
    eligible = [(r, src, label, a) for r, src, label, a in pool
                if r in CONTENT_DEFECTS and (a.get("draft") or a.get("answer"))]
    if not eligible:
        return None

    def rank(item):
        r, _, _, a = item
        cit = a.get("citations") or {}
        return (CONTENT_DEFECTS.index(r), -len(cit.get("cited", [])),
                -len(a.get("trace", [])))

    r, src, label, a = min(eligible, key=rank)
    return {"attempt": a, "from": src, "label": label, "reason": r}


def unverified_note(reason: str, attempt: dict, query: str, of: int) -> str:
    uk, en = _DEFECT_TEXT[reason]
    ids = ", ".join((attempt.get("citations") or {}).get("fabricated", []))
    if system._ukrainian(query):
        return (f"[Не перевірено: відповідь {uk.format(ids=ids)}. Це найкраща з {of} "
                f"{nform(of, 'спроби', 'спроб', 'спроб')}; людині не передається.]")
    return (f"[Unverified: the answer {en.format(ids=ids)}. Best of {of} attempts; "
            "not handed to a human.]")


def node_pick(state: State) -> dict:
    """Після гілок: перша, що пройшла decide(), стає відповіддю, коли головна
    спроба не пройшла; коли пройшла (--alt) — лишається головна, гілки поруч.
    Коли не пройшла жодна — найкраща чернетка з вмістом стає відповіддю з
    попередженням (best_effort), а без такої причина головної спроби
    лишається, і маршрут іде в handover з усіма чернетками. Перед тим гілки
    групуються за підходом."""
    _stop_variants_pulse()
    main = dict(state["result"])
    variants = [v for v in (state.get("variants") or []) if v.get("angle")]
    summaries = [dict(variant_summary(v), same_as="") for v in variants]
    with Pulse("думає · суддя схожості"):
        groups, how = group_variants(main.get("draft") or main.get("answer", ""), variants)
    distinct = mark_duplicates(summaries, groups)
    main.update(variant_groups=groups, variant_grouping=how, distinct_variants=distinct)
    seen = sorted({pid for v in variants for pid in critic.trace_pids(v.get("trace", []))})
    good = [v for v in variants if not v.get("reason")]
    main_failed = bool(state.get("reason")) or \
        (main.get("handoff") or {}).get("by") == "model"
    if not main_failed:
        main["variants"] = summaries
        return {"result": main, "known_ids": seen}
    if not good:
        main["variants"] = summaries
        main["variants_failed"] = True
        main_reason = state.get("reason", "") or "handover"
        best = best_effort(main, main_reason, variants)
        if best is None:
            return {"result": main, "known_ids": seen}
        attempt, of = best["attempt"], 1 + len(variants)
        draft = attempt.get("draft") or attempt.get("answer", "")
        note = unverified_note(best["reason"], attempt, state["query"], of)
        out = dict(main if best["from"] == "main" else attempt)
        out.update(router_raw=main.get("router_raw", ""),
                   fallback_from=main.get("fallback_from"),
                   fallback_why=main.get("fallback_why"),
                   variants=summaries, variants_failed=True,
                   variant_groups=groups, variant_grouping=how,
                   distinct_variants=distinct, draft=draft,
                   answer=f"{note}\n\n{draft}",
                   unverified={"reason": best["reason"], "from": best["from"],
                               "label": best["label"], "of": of,
                               "fabricated": (attempt.get("citations") or {})
                               .get("fabricated", [])})
        out.pop("handoff", None)
        return {"result": out, "reason": "", "known_ids": seen}
    chosen = dict(good[0])
    chosen.update(router_raw=main.get("router_raw", ""),
                  fallback_from=main.get("fallback_from"),
                  fallback_why=main.get("fallback_why"),
                  main_attempt={"answer": main.get("draft") or main.get("answer", ""),
                                "routed_to": main.get("routed_to"),
                                "reason": state.get("reason", "") or "handover",
                                "why": state.get("variants_why", "")},
                  chosen_variant=chosen["angle"], variants=summaries,
                  variant_groups=groups, variant_grouping=how,
                  distinct_variants=distinct)
    chosen.pop("handoff", None)
    return {"result": chosen, "reason": "", "known_ids": seen}


def after_pick(state: State) -> str:
    return "handover" if state.get("reason") else END


def entry(state: State) -> str:
    """Умовний вхід: звичайна репліка починається з роутера, /alt у бесіді —
    одразу з гілок над результатом, який уже є в стані."""
    return "variants" if state.get("alt_only") else "route"


def node_handover(state: State) -> dict:
    """Кінець маршруту, коли decide() назвав причину. Без --pause — рівно те,
    що apply_handoff у ручному стеку: збій передається одразу, рішення
    «у документах цього немає» стає запитом у черзі до --confirm. З --pause
    граф зупиняється ПЕРЕД цим вузлом, і сюди приходить відповідь людини."""
    result, query, reason = state["result"], state["query"], state["reason"]
    uk, en = system.REASONS[reason]
    if state.get("declined"):
        result["handoff"] = {"reason": reason, "explain": uk, "by": "pipeline",
                             "declined": True}
        result["draft"] = result["answer"]
        result["answer"] += ("\n\n[Передачу людині скасовано в паузі: відповідь "
                             "вище — чернетка системи, не перевірена людиною.]")
        return {"result": result}
    if state.get("confirmed"):
        ticket = team.handoff_to_human(query, uk)
        result["draft"] = result["answer"]
        result["handoff"] = {"ticket": ticket["ticket"], "reason": reason,
                             "explain": uk, "by": "human", "confirmed": True}
        result["answer"] = (f"Передаю питання людині — {uk}; підтверджено в паузі. "
                            f"Заявка: {ticket['ticket']}. Автоматичної відповіді не буде."
                            if system._ukrainian(query) else
                            f"Handing this question to a human reviewer — {en}; "
                            f"confirmed at the pause. Ticket: {ticket['ticket']}. "
                            "No automated answer follows.")
        return {"result": result}
    system.apply_handoff(result, query, reason)
    result["answer"] = result["answer"].replace(
        "python -m practice.base.system --confirm", CONFIRM_CMD)
    return {"result": result}


def build(pause: bool = False):
    g = StateGraph(State)
    g.add_node("route", node_route)
    g.add_node("specialist", node_specialist)
    g.add_node("general", node_general)
    g.add_node("critic", node_critic)
    g.add_node("variants", node_variants)
    g.add_node("variant", node_variant)
    g.add_node("pick", node_pick)
    g.add_node("handover", node_handover)
    g.add_conditional_edges(START, entry, {"route": "route", "variants": "variants"})
    g.add_edge("route", "specialist")
    g.add_conditional_edges("specialist", after_specialist,
                            {"general": "general", "critic": "critic"})
    g.add_edge("general", "critic")
    g.add_conditional_edges("critic", after_critic,
                            {"handover": "handover", "variants": "variants", END: END})
    g.add_conditional_edges("variants", fan_out, ["variant"])
    g.add_edge("variant", "pick")
    g.add_conditional_edges("pick", after_pick, {"handover": "handover", END: END})
    g.add_edge("handover", END)
    return g.compile(checkpointer=InMemorySaver(),
                     interrupt_before=["handover"] if pause else [])


def _pause_dialogue(state: dict) -> bool:
    """Що показати людині в паузі і що вона відповіла. Поза терміналом ніхто
    не питає: відповідь «ні», як і в QDRANT_AUTO_INGEST=ask без термінала."""
    result, reason = state["result"], state["reason"]
    uk, _ = system.REASONS[reason]
    print("  ── пауза перед передачею людині ──")
    print(f"  причина:      {uk}")
    print("  чернетка:")
    for line in result["answer"].splitlines():
        print(f"    {line}")
    if not sys.stdin.isatty():
        print("  без термінала: передачу не підтверджено")
        return False
    return input("  Передати людині? [y/N] ").strip().lower().startswith("y")


def _inputs(query: str, live: bool = False, remembered: str = "",
            note: str = "", alt: bool = False) -> dict:
    """Стан на початок репліки. Переписується кожне поле, крім history: у
    бесіді одна нитка чекпоінтера живе багато реплік, і без цього причина
    передачі чи відповідь людини в паузі попередньої репліки дійшли б до
    наступної. variants скидається через None — редʼюсер _fresh_or_add."""
    return {"query": query, "live": live, "remembered": remembered, "note": note,
            "route": "", "router_raw": "", "result": {}, "fallback_why": "",
            "reason": "", "confirmed": False, "declined": False,
            "alt": alt, "alt_only": False, "variants_why": "", "variants": None,
            "attempt": {}}


def _finish(app, cfg: dict, state: dict, pause: bool) -> dict:
    if pause and app.get_state(cfg).next:
        # Граф стоїть перед handover; стан лежить у чекпоінтері. Відповідь
        # людини дописується в стан, і той самий прогін продовжується.
        yes = _pause_dialogue(state)
        app.update_state(cfg, {"confirmed": yes, "declined": not yes})
        state = app.invoke(None, cfg)
    return state


def run_turn(app, cfg: dict, query: str, live: bool = False, pause: bool = False,
             remembered: str = "", note: str = "", alt: bool = False) -> dict:
    """Одна репліка через увесь граф на нитці `cfg`. Наприкінці питання і
    відповідь дописуються в history тієї самої нитки, тож наступна репліка
    їх побачить. Повертає result того самого формату, що system.run_system."""
    try:
        state = _finish(app, cfg, app.invoke(_inputs(query, live, remembered, note, alt), cfg),
                        pause)
    finally:
        _stop_variants_pulse()
    result = state["result"]
    app.update_state(cfg, {"history": [HumanMessage(query), AIMessage(result["answer"])]})
    return result


def run_alt(app, cfg: dict, query: str, result: dict, reason: str = "",
            live: bool = False, pause: bool = False, remembered: str = "",
            note: str = "") -> dict:
    """/alt у бесіді: три гілки над уже наявною відповіддю на `query`, без
    повторного проходу через роутер і спеціаліста. В history нічого не
    дописується — там уже лежить ця пара питання-відповідь."""
    inputs = dict(_inputs(query, live, remembered, note, alt=True),
                  alt_only=True, result=result, reason=reason,
                  routed_to=result.get("routed_to", ""))
    inputs.pop("routed_to")
    try:
        state = _finish(app, cfg, app.invoke(inputs, cfg), pause)
    finally:
        _stop_variants_pulse()
    return state["result"]


def run_graph(query: str, live: bool = False, pause: bool = False,
              alt: bool = False) -> dict:
    """Повний маршрут одного запиту через граф — одна репліка на свіжій нитці."""
    cfg = {"configurable": {"thread_id": f"run-{time.strftime('%H%M%S')}"},
           "recursion_limit": 30}
    return run_turn(build(pause), cfg, query, live=live, pause=pause, alt=alt)


# ── звіт, збереження, CLI ─────────────────────────────────────

def route_label(result: dict) -> str:
    """«WRAPPERS → передав сам → GENERAL» або просто маршрут."""
    routed = result["routed_to"]
    if result.get("fallback_from"):
        why = {"handover": "передав сам", "no_search": "без пошуку"}.get(
            result.get("fallback_why"), "порожньо")
        routed = f"{result['fallback_from']} → {why} → {routed}"
    return routed


def print_steps(result: dict) -> None:
    """Кроки траси, звірка посилань, критик, передача — спільна частина звіту
    одного запиту і репліки бесіди."""
    for step in result.get("trace", []):
        out = step["output"]
        if step["tool"] == team.RESEARCH_TOOL:
            mark = "знайшов" if out.get("found_anything") else "порожньо"
            print(f"  дослідження:  «{step['input'].get('topic', '')}» → {mark}, "
                  f"пошуків: {out.get('searches', 0)}")
        elif step["tool"] == team.HANDOFF_TOOL:
            print(f"  до людини:    {out.get('ticket', '?')} — "
                  f"{step['input'].get('reason', '')}")
        elif step["tool"] == team.REQUEST_TOOL:
            print(f"  пауза:        {out.get('request_id', '?')} — "
                  f"{step['input'].get('reason', '')}; чекає на --confirm")
        else:
            ids = ", ".join(p["id"] for p in out.get("passages", [])) or "—"
            print(f"  пошук:        «{step['input'].get('query', '')}» "
                  f"→ {out.get('found', 0)}: {ids}")
    cit = result.get("citations", {})
    if cit.get("fabricated"):
        print(f"  посилання:    ВИГАДАНІ: {', '.join(cit['fabricated'])}")
    elif cit.get("cited"):
        reused = cit.get("reused") or []
        print(f"  посилання:    {len(cit['cited'])} шт., усі є в trace"
              + (f" ({len(reused)} з попередніх реплік бесіди)" if reused else ""))
    if result.get("critic"):
        c = result["critic"]
        print(f"  критик:       ok={c['ok']}  доопрацювання: "
              f"{'було' if c['revised'] else 'не знадобилося'}")
    if result.get("handoff"):
        print(f"  передача:     {result['handoff']}")
    print_variants(result)


_GROUPING = {"judge": "за оцінкою моделі-судді", "text": "за збігом тексту",
             "single": "порівнювати нема з чим"}


def print_variants(result: dict) -> None:
    """Блок альтернативних спроб: що з головною, яку гілку обрано, скільки
    різних підходів насправді є, і по одному представнику кожної групи
    повністю — гілка, що повторює іншу, згортається в рядок."""
    variants = result.get("variants")
    if not variants:
        return
    distinct = result.get("distinct_variants", len(variants))
    how = _GROUPING.get(result.get("variant_grouping", ""), "")
    counted = (f"різних від головної: {distinct} з {len(variants)}"
               + (f" ({how})" if how else ""))
    main = result.get("main_attempt")
    if main:
        print(f"  головна:      {main['routed_to']} не пройшла — {main['why']}; "
              f"обрано гілку «{result.get('chosen_variant')}» · {counted}")
        print("  чернетка головної спроби:")
        for line in (main["answer"] or "—").splitlines():
            print(f"    {line}")
    elif result.get("unverified"):
        u = result["unverified"]
        print(f"  гілки:        жодна не пройшла · {counted}")
        print(f"  неперевірено: відповідь — {u['label']} ({u['reason']}), найкраща з {u['of']}; "
              "людині не передається")
    elif result.get("variants_failed"):
        print(f"  гілки:        жодна не пройшла і вмісту немає — передача · {counted}")
    elif distinct == 0:
        print(f"  гілки:        усі {len(variants)} повторюють головну відповідь — "
              f"альтернативи немає ({how})")
    else:
        print(f"  гілки:        головна пройшла; альтернативи поруч · {counted}")
    number = {v["angle"]: k for k, v in enumerate(variants, 1)}
    for k, v in enumerate(variants, 1):
        status = "пройшла" if not v["reason"] else f"не пройшла: {v['reason']}"
        mark = " ← обрано" if v["angle"] == result.get("chosen_variant") else ""
        line = (f"  варіант {k} · {v['label']} · {v['routed_to']} · {status} · "
                f"пошуків {v['searches']} · посилань {v['cited']}"
                + (f" · вигадані: {', '.join(v['fabricated'])}" if v["fabricated"] else "")
                + (f" · {v['error']}" if v["error"] else ""))
        same = v.get("same_as")
        if same:
            who = "головну відповідь" if same == "main" else f"варіант {number.get(same, '?')}"
            print(f"{line} · повторює {who} — не друкується")
            continue
        print(line + mark)
        for text_line in (v["answer"] or "—").splitlines():
            print(f"      {text_line}")


def report(result: dict, query: str) -> None:
    print(f"  запит:        «{query}»")
    print(f"  маршрут:      {route_label(result)}  (роутер відповів: "
          f"{result.get('router_raw', '?')})")
    print(f"  outcome:      {result['outcome']}  ·  кроків: {result.get('turns', '—')}"
          f"  ·  {result.get('elapsed_sec', '—')} с")
    print_steps(result)
    if result.get("draft") and result["draft"] != result["answer"]:
        print("  чернетка до передачі:")
        for line in result["draft"].splitlines():
            print(f"    {line}")
    print("  відповідь:")
    for line in result["answer"].splitlines():
        print(f"    {line}")
    c = cost.usd(USAGE["by_model"])
    print(f"  вартість:     ${c:.4f}  ({USAGE['calls']} "
          f"{nform(USAGE['calls'], 'виклик', 'виклики', 'викликів')}, "
          f"{USAGE['in']} in / {USAGE['out']} out)")


def save_result(key: str, record: dict) -> None:
    """Зливає запис у out/graph_results.json так само, як system.save_result —
    файл читається цілим, запис лягає під своїм ключем, решта лишається."""
    OUT.mkdir(exist_ok=True)
    stored = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    stored[key] = record
    RESULTS.write_text(json.dumps(stored, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def show() -> None:
    """Вузли і ребра графа — те, чого в ручному стеку не побачити інакше, як
    прочитавши run_system зверху донизу. $0."""
    drawing = build(pause=True).get_graph()
    print("  вузли:", ", ".join(n for n in drawing.nodes if not n.startswith("__")))
    for e in drawing.edges:
        mark = " (умовне)" if e.conditional else ""
        print(f"  {e.source} → {e.target}{mark}")
    print("  з --pause граф зупиняється перед handover; стан — у чекпоінтері")
    print(f"  variants → variant: розгалуження Send, {len(ANGLES)} гілки паралельно "
          f"({', '.join(a['label'] for a in ANGLES.values())})")


def main(argv: list[str]) -> int:
    if "--confirm" in argv:
        return system.confirm(argv)
    if "--show" in argv:
        show()
        return 0
    if "--list" in argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        for name, q in QUERIES.items():
            print(f"  {name:8} {q['kind']}\n           «{q['query']}»")
        return 0

    if "--lexical" in argv:
        os.environ["PRACTICE_RETRIEVER"] = "lexical"
    if "--rewrite" in argv:
        os.environ["PRACTICE_REWRITE"] = "1"
    live = "--live" in argv
    pause = "--pause" in argv
    alt = "--alt" in argv
    fast = "--fast" in argv
    if fast:
        use_fast_model()

    positional = [a for a in argv if not a.startswith("-")]
    raw = positional[0] if positional else "attrs"
    scenario = raw if raw in QUERIES else "custom"
    query = QUERIES[raw]["query"] if raw in QUERIES else raw

    print(f"── Практика М3 · граф LangGraph · сценарій: {scenario} · "
          f"{current_model()} + {MODEL_FAST} · MAX_TURNS={MAX_TURNS}"
          + (" · з паузою" if pause else "") + (" · з альтернативами" if alt else "") + " ──")
    started = time.time()
    reset_usage()
    result = run_graph(query, live=live, pause=pause, alt=alt)
    result.update(scenario=scenario, query=query, stack="langgraph",
                  pipeline_sec=round(time.time() - started, 2),
                  cost_usd=cost.usd(USAGE["by_model"]),
                  cost_breakdown=cost.breakdown(USAGE["by_model"]),
                  model=current_model())
    report(result, query)
    prefix = "graph" + ("-fast" if fast else "") + ("-pause" if pause else "") \
        + ("-alt" if alt else "")
    if scenario != "custom":
        save_result(f"{prefix}:{scenario}", result)
        print(f"  збережено:    {RESULTS}")
    else:
        key = f"{prefix}:custom-{time.strftime('%Y%m%d-%H%M%S')}"
        save_result(key, result)
        print(f"  збережено:    {RESULTS} під ключем {key}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
