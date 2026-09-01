"""
ОСНОВА · спани навколо агента фабрики, за домовленостями OpenTelemetry GenAI.

Агент фабрики не знає про телеметрію і не змінюється заради неї. Спани ставлять
три обгортки, які цей модуль накладає перед прогоном:

    invoke_agent docfactory-ecmascript   ← server.agent.run    (усе звернення)
      chat {model}                       ← common.llm._call    (кожен виклик моделі)
      execute_tool {name}                ← server.agent._dispatch (кожен інструмент)

Чому саме ці три точки. `_run` бере `_call` через `from common.llm import _call`
всередині себе, тобто читає атрибут модуля на кожному прогоні, а `_dispatch`
кличеться як глобальне ім'я модуля `server.agent` — обидві підміни видно агентові
одразу. Guardrail ходить тим самим `_call`, тож його виклик теж стає спаном
усередині звернення: це частина роботи агента, і його вартість рахується там.

Імена атрибутів пишуться рядками навмисно: пакет opentelemetry-semantic-conventions
0.65b0 ще несе застарілу константу GEN_AI_SYSTEM і стару назву кеш-токенів.
Грошової вартості в домовленостях немає взагалі — вона йде власним атрибутом
docfactory.cost.usd, порахована з таблиці цін module7/core/cost.py.
"""

import atexit
import time

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode

SERVICE = "docfactory-ecmascript"

#: Токени прогону за моделями, у формі, яку читає core.cost: {модель: {calls, in, out}}.
USAGE: dict = {}
#: Виклики інструментів прогону. Саме звідси беруться детерміновані перевірки:
#: report["trace"] агента дописує і відхилені шаром 2 виклики, тож рахувати за ним
#: не можна — тут кожен запис знає, чи виклик справді виконався.
CALLS: list = []

_ORIGINALS: dict = {}


def reset() -> None:
    USAGE.clear()
    CALLS.clear()


def usage_totals() -> dict:
    """Підсумок токенів прогону і вартість за таблицею цін module7."""
    from core.cost import usd

    return {"in": sum(u["in"] for u in USAGE.values()),
            "out": sum(u["out"] for u in USAGE.values()),
            "calls": sum(u["calls"] for u in USAGE.values()),
            "by_model": {m: dict(u) for m, u in USAGE.items()},
            "usd": usd(USAGE)}


def setup(backend: str = "phoenix", processor=None, service: str = SERVICE):
    """Постачальник спанів і адресат. Повертає (tracer, куди).

    Адресат береться з курсового otel_tracing.py — там уже описані всі п'ять
    (консоль, phoenix, langfuse, langsmith, довільний OTLP), і другого списку
    адрес ми не заводимо. Імпорт лізе туди ліниво: він тягне за собою config і
    всі модулі курсу, а це близько вісімнадцяти секунд, яких безкоштовні
    перевірки платити не мусять. Для них передається готовий processor.
    """
    where = "переданий обробник"
    if processor is None:
        from otel_tracing import _exporter          # noqa: PLC0415 - навмисно ліниво
        processor, where = _exporter(backend)

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    # Пакетний обробник віддає спани раз на п'ять секунд, а прогін буває коротшим
    # за цей проміжок; без явного вивантаження останні спани просто зникають.
    atexit.register(provider.shutdown)
    return trace.get_tracer("practice.m07"), where


def _instrument_call(tracer):
    import common.llm as llm

    original = llm._call
    _ORIGINALS["_call"] = original

    def traced(**kwargs):
        model = kwargs.get("model", "?")
        with tracer.start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as s:
            s.set_attribute("gen_ai.operation.name", "chat")
            s.set_attribute("gen_ai.provider.name", "anthropic")
            s.set_attribute("gen_ai.request.model", model)
            if kwargs.get("max_tokens"):
                s.set_attribute("gen_ai.request.max_tokens", kwargs["max_tokens"])
            try:
                resp = original(**kwargs)
            except Exception as exc:                # noqa: BLE001 - тип іде в спан
                s.set_attribute("error.type", type(exc).__name__)
                s.set_status(Status(StatusCode.ERROR, str(exc)[:120]))
                raise

            u = getattr(resp, "usage", None)
            cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
            # Anthropic віддає кешовані токени окремо від input_tokens, а
            # домовленості вимагають у gen_ai.usage.input_tokens суму всього входу.
            got_in = (getattr(u, "input_tokens", 0) or 0) + cache_read + cache_write
            got_out = getattr(u, "output_tokens", 0) or 0

            s.set_attribute("gen_ai.usage.input_tokens", got_in)
            s.set_attribute("gen_ai.usage.output_tokens", got_out)
            if cache_read:
                s.set_attribute("gen_ai.usage.cache_read.input_tokens", cache_read)
            if cache_write:
                s.set_attribute("gen_ai.usage.cache_write.input_tokens", cache_write)
            s.set_attribute("gen_ai.response.model", getattr(resp, "model", model))
            if getattr(resp, "stop_reason", None):
                s.set_attribute("gen_ai.response.finish_reasons", [resp.stop_reason])

            row = USAGE.setdefault(model, {"calls": 0, "in": 0, "out": 0})
            row["calls"] += 1
            row["in"] += got_in
            row["out"] += got_out

            from core.cost import usd
            s.set_attribute("docfactory.cost.usd",
                            usd({model: {"in": got_in, "out": got_out}}))
            return resp

    llm._call = traced


def _instrument_dispatch(tracer):
    from server import agent

    original = agent._dispatch
    _ORIGINALS["_dispatch"] = original

    async def traced(session, name, args, sess, report):
        with tracer.start_as_current_span(f"execute_tool {name}",
                                          kind=SpanKind.INTERNAL) as s:
            s.set_attribute("gen_ai.operation.name", "execute_tool")
            s.set_attribute("gen_ai.tool.name", name)
            s.set_attribute("gen_ai.tool.type", "function")
            started = time.perf_counter()
            out = await original(session, name, args, sess, report)
            ms = round((time.perf_counter() - started) * 1000, 1)

            ok = "error" not in out
            if not ok:
                s.set_attribute("error.type", str(out["error"])[:80])
                # Статус, а не лише атрибут: без нього приймач вважає спан
                # успішним, і відсіяти невдалі звернення можна лише очима.
                s.set_status(Status(StatusCode.ERROR, str(out["error"])[:120]))
            # Яким способом шукав сервер — по словах чи ще й за змістом. Без цього
            # два прогони можна порівняти лише на віру: режим залежить від того,
            # чи піднялися вектори, а це видно тільки тут.
            if out.get("search"):
                s.set_attribute("docfactory.search.mode", out["search"])
            s.set_attribute("docfactory.tool.duration_ms", ms)

            CALLS.append({"tool": name, "input": args, "ok": ok, "ms": ms,
                          "search": out.get("search"), "output": out})
            return out

    agent._dispatch = traced


def instrument(tracer) -> None:
    """Накладає всі три обгортки. Агент про них не знає."""
    _instrument_call(tracer)
    _instrument_dispatch(tracer)


def restore() -> None:
    """Знімає обгортки — потрібно тестам, які ставлять їх кілька разів."""
    if "_call" in _ORIGINALS:
        import common.llm as llm
        llm._call = _ORIGINALS.pop("_call")
    if "_dispatch" in _ORIGINALS:
        from server import agent
        agent._dispatch = _ORIGINALS.pop("_dispatch")


def traced_run(query: str, tracer, instance: str = "ecmascript") -> dict:
    """Одне звернення до агента під кореневим спаном. Повертає звіт прогону.

    До звіту агента додається те, чого в ньому немає: список справді виконаних
    викликів, токени, вартість і ідентифікатор трейсу — за ним прогін знаходять
    у приймачі, і до нього ж чіпляється вердикт судді на наступному кроці.
    """
    from server import agent

    reset()
    with tracer.start_as_current_span(f"invoke_agent {SERVICE}",
                                      kind=SpanKind.INTERNAL) as root:
        root.set_attribute("gen_ai.operation.name", "invoke_agent")
        root.set_attribute("gen_ai.agent.name", SERVICE)
        root.set_attribute("gen_ai.request.model", _model_name())
        root.set_attribute("docfactory.instance", instance)
        started = time.perf_counter()
        report = agent.run(query)
        seconds = round(time.perf_counter() - started, 2)

        totals = usage_totals()
        root.set_attribute("gen_ai.usage.input_tokens", totals["in"])
        root.set_attribute("gen_ai.usage.output_tokens", totals["out"])
        root.set_attribute("docfactory.cost.usd", totals["usd"])
        root.set_attribute("docfactory.tool.calls", len(CALLS))
        if report["blocked"]:
            root.set_attribute("error.type", "blocked_by_layer")
            by = "; ".join(b["by"] for b in report["blocked"])
            root.set_status(Status(StatusCode.ERROR, f"заблоковано шарами: {by}"))
        trace_id = format(root.get_span_context().trace_id, "032x")

    report["calls"] = list(CALLS)
    report["usage"] = totals
    report["seconds"] = seconds
    report["trace_id"] = trace_id
    report["instance"] = instance
    return report


def _model_name() -> str:
    import common.llm as llm
    return llm.MODEL
