"""
ОСНОВА · безкоштовні перевірки. Жодного звернення до моделей Anthropic.

Це verification-список дизайну, який можна ганяти скільки завгодно: розкладка
родин, підмножини фрагментів, схеми і права спеціалістів, реєстрація в IMPL,
детерміновані тригери передачі людині, звірка посилань. Кожна перевірка друкує
рядок ok/FAIL; будь-який FAIL завершує процес із ненульовим кодом.

    python -m practice.base.smoke           # $0, секунди
    python -m practice.base.smoke --warm    # $0, плюс збірка векторних індексів
                                            # (перший раз — завантаження моделі
                                            # ембедингів і хвилини лічби на CPU)

Прапорець --warm вартий окремого запуску перед compare: індекси всіх підмножин
зберуться в кеш заздалегідь, і вимір не платитиме за них часом.
"""

import sys

FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def main(argv: list[str]) -> int:
    from practice.base import critic, team

    # 1. Родини не перетинаються. У наборі «core» вони до того ж покривають усі
    # вісімнадцять документів; у «full» покривати всю специфікацію вони й не
    # мусять — решта розділів дістається маршрутові GENERAL.
    from practice.common.corpus import DOC_SET

    numbers = sorted(n for fam in team.FAMILIES.values() for n in fam)
    check(f"родини не перетинаються (набір {DOC_SET})",
          len(numbers) == len(set(numbers)),
          f"документи: {', '.join(f'{n:02d}' for n in numbers)}")
    if DOC_SET == "core":
        check("родини покривають документи 01–18 повністю",
              numbers == list(range(1, 19)))
    check("документи інших стандартів і посилань (402-, 404-, rfc…, uts…) поза родинами",
          team.doc_number("07-array-exotic-objects") == 7
          and team.doc_number("402-08-intl-object") == 0
          and team.doc_number("404-json") == 0
          and team.doc_number("uts35-1-core") == 0)

    # 2. Підмножини фрагментів не перетинаються і складаються в повний набір
    # (у «core») або в його частину (у «full»).
    full = team.all_passages()
    parts = [team.passages_for(f) for f in team.FAMILIES]
    pids = [p.pid for sub in parts for p in sub]
    known = {p.pid for p in full}
    check("підмножини не перетинаються і лежать усередині набору",
          len(pids) == len(set(pids)) and set(pids) <= known,
          f"{' + '.join(str(len(s)) for s in parts)} з {len(full)}")
    if DOC_SET == "core":
        check("підмножини розбивають повний набір фрагментів",
              sorted(pids) == sorted(known))
    check("кожна родина непорожня", all(parts))

    # 3. Імена інструментів унікальні і не перетинаються з курсовими.
    names = list(team.PRACTICE_IMPL)
    check("імена інструментів практики унікальні", len(names) == len(set(names)))
    check("жодне ім'я не збігається з курсовим IMPL",
          not set(names) & team._COURSE_TOOL_NAMES)
    team.register()
    team.register()
    check("register() ідемпотентна", True)

    # 4. Права: у кожного маршруту свої схеми, fetch_spec без --live немає ніде.
    for fam in team.FAMILIES:
        tools = team.tools_for_route(fam)
        check(f"{fam}: лише власний пошук",
              [t["name"] for t in tools] == [team.TOOL_NAMES[fam]])
    gen = [t["name"] for t in team.tools_for_route(team.GENERAL)]
    check("GENERAL: субагент і запит на передачу, БЕЗ прямого пошуку",
          gen == [team.RESEARCH_TOOL, team.REQUEST_TOOL])
    # Перемикач другої картки: інструмент зникає і зі списку, і з промпта;
    # без перемикача обидва на місці.
    gone = [t["name"] for t in team.tools_for_route(team.GENERAL, drop={team.REQUEST_TOOL})]
    check("--drop request_handoff: GENERAL лишається із самим субагентом, промпт інструмент не називає",
          gone == [team.RESEARCH_TOOL]
          and team.REQUEST_TOOL not in team.prompt_for_route(team.GENERAL, {team.REQUEST_TOOL})
          and team.REQUEST_TOOL in team.prompt_for_route(team.GENERAL, set()))
    import os as _os
    _os.environ[team.DROP_ENV] = team.REQUEST_TOOL
    via_env = [t["name"] for t in team.tools_for_route(team.GENERAL)]
    del _os.environ[team.DROP_ENV]
    check("PRACTICE_DROP_TOOLS діє без аргументів і знімається разом зі змінною",
          via_env == [team.RESEARCH_TOOL]
          and [t["name"] for t in team.tools_for_route(team.GENERAL)] == gen)
    all_schemas = [t["name"] for f in list(team.FAMILIES) + [team.GENERAL]
                   for t in team.tools_for_route(f)]
    check("fetch_spec відсутній у схемах без --live",
          "fetch_spec" not in all_schemas)

    # 5. Звірка посилань: вигадане джерело, підсумок субагента, живий якір.
    trace = [
        {"tool": "search_wrapper_docs",
         "output": {"found": 1, "passages": [{"id": "18-string-objects#22.1.3.19"}]}},
        {"tool": "research_topic",
         "output": {"summary": "Covered in [13-proxy-object-internal-methods-"
                               "and-internal-slots#10.5.8].", "found_anything": True}},
        {"tool": "fetch_spec",
         "output": {"anchor": "sec-array-prototype-flat", "text": "..."}},
    ]
    good = critic.check_citations(
        "See [18-string-objects#22.1.3.19] and "
        "[13-proxy-object-internal-methods-and-internal-slots#10.5.8] "
        "and [live:sec-array-prototype-flat].", trace)
    check("звірка приймає ідентифікатори з пошуку, субагента і живого якоря",
          not good["fabricated"] and len(good["cited"]) == 3)
    bad = critic.check_citations("As stated in [23-array-objects#23.1.3.13].", trace)
    check("звірка ловить вигадане джерело",
          bad["fabricated"] == ["23-array-objects#23.1.3.13"])
    refusal = critic.check_citations("The excerpts do not cover this.", trace)
    check("відмова без цитат не вважається вигадкою, але позначається",
          not refusal["fabricated"] and refusal["uncited"])

    # 6. Заглушка передачі людині: лічильник, не hash.
    before = len(team.HANDOFF_LOG)
    t1 = team.handoff_to_human("q", "r")["ticket"]
    t2 = team.handoff_to_human("q", "r")["ticket"]
    check("заявки HITL нумеруються лічильником",
          t1 == f"HITL-{before + 1:05d}" and t2 == f"HITL-{before + 2:05d}")

    # 7. Пауза перед незворотною дією: запит лягає в чергу, передача стається
    # лише на підтвердженні, історія запитів не видаляється.
    import pathlib as _pl
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        q = _pl.Path(tmp) / "pending.json"
        log_before = len(team.HANDOFF_LOG)
        r = team.request_handoff("тестове питання", "тестова причина", path=q)
        check("request_handoff ставить запит у чергу і НЕ передає",
              r["pending"] and r["request_id"] == "REQ-00001"
              and len(team.HANDOFF_LOG) == log_before)
        entry = team.confirm_handoff(path=q)
        check("confirm_handoff передає і зберігає історію",
              entry["status"] == "confirmed" and entry["ticket"].startswith("HITL-")
              and len(team.HANDOFF_LOG) == log_before + 1)
        check("повторне підтвердження без запитів відмовляє",
              team.confirm_handoff(path=q) is None)

    # 8. Детерміновані тригери передачі людині (потрібен config, тобто .env).
    try:
        from practice.base import system
    except SystemExit as e:
        check("тригери decide() перевірено", False, f"config недоступний: {e}")
    else:
        cases = [
            ({"outcome": "api_error"}, "api_error"),
            ({"outcome": "turns_exhausted"}, "turns_exhausted"),
            ({"outcome": "ok", "trace": [{"failed": True}]}, "tool_error"),
            ({"outcome": "ok", "trace": [{}],
              "citations": {"fabricated": ["x#1"]}}, "fabricated"),
            ({"outcome": "ok", "trace": [{}], "citations": {},
              "critic": {"ok": False}}, "critic_failed"),
            ({"outcome": "ok", "routed_to": team.GENERAL, "citations": {},
              "trace": [{"tool": team.RESEARCH_TOOL,
                         "output": {"found_anything": False}}]}, "research_empty"),
            ({"outcome": "ok", "routed_to": "OBJECT", "citations": {},
              "trace": [{"tool": "search_object_docs",
                         "output": {"found": 2}}]}, None),
        ]
        ok = all(system.decide(dict(r)) == want for r, want in cases)
        check("тригери decide() дають очікувані причини", ok)
        # Гілка паузи в конвеєрі: research_empty не передає, а ставить у чергу.
        with tempfile.TemporaryDirectory() as tmp2:
            saved = team.PENDING_FILE
            team.PENDING_FILE = _pl.Path(tmp2) / "pending.json"
            try:
                r = system.apply_handoff(
                    {"outcome": "ok"}, "Питання про борщ", "research_empty")
                check("research_empty ставить запит у чергу, а не передає",
                      r["handoff"].get("pending") is True
                      and "--confirm" in r["answer"])
                r2 = system.apply_handoff(
                    {"outcome": "api_error"}, "any question", "api_error")
                check("api_error передає одразу, без паузи",
                      "ticket" in r2["handoff"]
                      and not r2["handoff"].get("pending"))
            finally:
                team.PENDING_FILE = saved
        check("мова повідомлення про передачу йде за мовою запиту",
              system._ukrainian("Як працює replace?")
              and not system._ukrainian("How does replace work?"))
        for route in team.ROUTES:
            check(f"роутер-промпт називає {route}", route in system.ROUTER_PROMPT)
        check("нерозпізнана відповідь роутера стає GENERAL",
              system.normalize_route("КАВА") == team.GENERAL
              and system.normalize_route("WRAPPERS") == "WRAPPERS")

    # 9. live_fetch: перевірка адрес і вирізання підрозділу — офлайн, без мережі.
    from practice.challenges import live_fetch as lf
    bad = [
        "http://tc39.es/ecma262/multipage/x.html#sec-a",        # не https
        "https://evil.example/ecma262/multipage/x.html#sec-a",  # чужий host
        "https://tc39.es/ecma262/#sec-a",                       # односторінкова
        "https://tc39.es/ecma262/multipage/x.html",             # без якоря
        "https://tc39.es/other/multipage/x.html#sec-a",         # чужий шлях
    ]
    check("live_fetch відхиляє недозволені адреси",
          all("error" in lf._validate(u) for u in bad))
    ok_url = lf._validate("https://tc39.es/ecma262/multipage/"
                          "indexed-collections.html#sec-array.prototype.flat")
    check("live_fetch розбирає дозволену адресу",
          ok_url == ("https://tc39.es/ecma262/multipage/indexed-collections.html",
                     "sec-array.prototype.flat"))
    # Сайт віддає атрибути без лапок — вирізання мусить брати обидві форми.
    page_q = '<emu-clause id="sec-t"><p>quoted body</p></emu-clause>'
    page_u = '<emu-clause id=sec-t type="x"><p>unquoted body</p></emu-clause>'
    check("вирізання підрозділу бере id у лапках і без",
          "quoted body" in lf._extract_section(page_q, "sec-t")
          and "unquoted body" in lf._extract_section(page_u, "sec-t")
          and lf._extract_section(page_u, "sec-missing") is None)

    # 9б. Жива бесіда: перша репліка з рядка команди і пульс очікування.
    import io
    from practice.common.pulse import Pulse
    from practice.context.dialog import first_turn
    check("перша репліка з рядка береться лише з --chat",
          first_turn(["--chat", "Що таке Proxy?", "--history", "prune"]) == "Що таке Proxy?"
          and first_turn(["--chat", "--history", "prune"]) is None
          and first_turn(["--script", "short"]) is None)
    try:
        first_turn(["Що таке Proxy?"])
        stray_refused = False
    except SystemExit:
        stray_refused = True
    check("репліка без --chat — помилка, а не мовчазне ігнорування", stray_refused)

    class _Tty(io.StringIO):
        def isatty(self):
            return True

    quiet, tty = io.StringIO(), _Tty()
    with Pulse("думає", stream=quiet):
        pass
    with Pulse("думає", stream=tty, every=0.05) as pulse:
        pulse.note("виклик 1 з 8")
    drawn = tty.getvalue()
    check("пульс мовчить поза терміналом і малює в терміналі",
          quiet.getvalue() == "" and "виклик 1 з 8" in drawn and drawn.endswith("\r"))

    # 9в. Звірка посилань, бюджет досліджень і передача від часткового спеціаліста.
    from practice.base import system as system_mod
    parts_trace = [{"tool": "search_docs", "output": {"found": 2, "passages": [
        {"id": "27-control-abstraction-objects#27.5.4.1.2/1"},
        {"id": "27-control-abstraction-objects#27.5.4.1.2/2"}]}}]
    verdict = critic.check_citations(
        "see [27-control-abstraction-objects#27.5.4.1.2] and "
        "[27-control-abstraction-objects#27.5.4.1.2/3]", parts_trace)
    check("підрозділ без суфікса частини — відомий, частина, якої не було, — вигадка",
          verdict["fabricated"] == ["27-control-abstraction-objects#27.5.4.1.2/3"])
    team.reset_research()
    team._research_used["n"] = team.RESEARCH_BUDGET
    refused = team.research_topic("anything")
    team.reset_research()
    check("дослідження понад бюджет відхиляється без виклику моделі",
          refused.get("budget_spent") is True and not refused["found_anything"])
    excerpts = team.excerpt_summary([
        {"output": {"found": 2, "passages": [
            {"id": "a#1", "section": "1 A", "text": "first  text"},
            {"id": "a#2", "section": "2 B", "text": "second"}]}},
        {"output": {"found": 1, "passages": [{"id": "a#1", "section": "1 A", "text": "dup"}]}}])
    check("замінний підсумок збирає різні уривки з ідентифікаторами",
          excerpts.count("[a#1]") == 1 and "[a#2] 2 B: second" in excerpts
          and "first text" in excerpts)
    hit = [{"output": {"found": 2, "passages": [{"id": "x#1"}]}}]
    miss = [{"output": {"found": 0}}]
    check("запасний маршрут: рядок HANDOVER, відповідь без пошуку, порожній пошук",
          system_mod._fallback_why({"answer": "HANDOVER: GENERAL", "trace": hit}) == "handover"
          and system_mod._fallback_why({"answer": "  handover: general \n", "trace": hit}) == "handover"
          and system_mod._fallback_why({"answer": "Порадьте колезі…", "trace": []}) == "no_search"
          and system_mod._fallback_why({"answer": "нічого", "trace": miss}) == "empty"
          and system_mod._fallback_why({"answer": "GetIterator [x#1]", "trace": hit}) is None)
    check("промпти спеціалістів називають рядок передачі, GENERAL — ні",
          all(team.HANDOVER_LINE in team.PROMPTS[r] for r in ("OBJECT", "EXOTIC", "WRAPPERS"))
          and team.HANDOVER_LINE not in team.PROMPTS[team.GENERAL])

    # 10. За бажанням — прогрів індексів (модель ембедингів, хвилини на CPU).
    if "--warm" in sys.argv:
        print("  прогрів векторних індексів...")
        paths = set()
        for fam in list(team.FAMILIES) + [team.GENERAL]:
            idx = team.index_for(fam)
            paths.add(idx.cache_path)
            src = "з кеша" if idx.from_cache else "порахований"
            from practice.common import nform
            print(f"    {fam:8} {len(idx.passages):3} {nform(len(idx.passages), 'фрагмент', 'фрагменти', 'фрагментів')}, {src}: "
                  f"{idx.cache_path.name}")
        check("у кожної підмножини свій файл кеша", len(paths) == 4)

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — " + "; ".join(FAILED))
        return 1
    print("Усі перевірки пройдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
