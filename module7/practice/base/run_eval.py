"""
ТОЧКА ВХОДУ · прогін усього набору кейсів із трейсингом. ПЛАТНО.

Один прогін — один файл у practice/out/, у якому лежить усе, що потім потрібно
безкоштовно: питання, відповідь, виконані виклики з їхньою видачею, токени,
вартість, час і вердикт судді. Гейт (pytest) читає цей файл і до моделі не
ходить.

    python -m practice.base.run_eval --label baseline
    python -m practice.base.run_eval --label degraded --degraded
    python -m practice.base.run_eval --label proba --only same-value,json-valid

Порядок величини: двадцять кейсів — кілька десятків звернень до моделі агента
плюс по одному дешевому на guardrail і на суддю.
"""

import argparse
import datetime
import json
import os
import sys


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="прогін набору кейсів із трейсингом")
    ap.add_argument("--label", required=True, help="мітка прогону: baseline, degraded, …")
    ap.add_argument("--degraded", action="store_true",
                    help="читати деградовану копію корпусу (docs-degraded/)")
    ap.add_argument("--docs", default="suite",
                    help="набір документів; обидва записані прогони зняті на suite")
    ap.add_argument("--backend", default="phoenix", help="куди слати спани")
    ap.add_argument("--only", default="", help="через кому: прогнати лише ці кейси")
    args = ap.parse_args(argv)

    # Усі три змінні виставляються ДО першого імпорту practice.common: набір
    # документів обирається на імпорті модуля, і запізніла зміна вже нічого не
    # означала б. Оточення успадковує підпроцес сервера знань — саме там воно й
    # вирішує, які файли читати.
    #
    # Набір задається тут, а не береться з оточення, і це не перестраховка:
    # module7/.env несе PRACTICE_DOCS для курсових файлів модуля, config.py
    # заносить його в оточення на імпорті, і прогін мовчки міряв би інший корпус
    # та шукав би в іншій, порожній колекції. Хто справді хоче інший набір, каже
    # це прапорцем --docs, і набір лягає у файл прогону.
    os.environ["PRACTICE_DOCS"] = args.docs
    if args.degraded:
        os.environ["PRACTICE_DEGRADED"] = "1"
    # Прогрів векторів синхронний: інакше перші питання прогону шукали б по
    # словах, пізніші за змістом, і число залежало б від того, що встигло раніше.
    os.environ.setdefault("PRACTICE_VECTORS_WAIT", "1")
    corpus = "degraded" if args.degraded else "suite"

    from opentelemetry.trace import SpanKind
    from practice import evaluation as ev
    from practice import tracing

    cases = ev.load_dataset()
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        cases = [c for c in cases if c["id"] in wanted]
        if not cases:
            raise SystemExit(f"Жоден кейс не збігся з --only {args.only}")

    tracer, where = tracing.setup(args.backend)
    print(f"Спани летять у: {where}")
    tracing.instrument(tracer)

    rows, judge_usd = [], 0.0
    for i, case in enumerate(cases, 1):
        print(f"  [{i:>2}/{len(cases)}] {case['id']:<24}", end=" ", flush=True)
        report = tracing.traced_run(case["query"], tracer, corpus=corpus)
        answer = report["answer"]
        calls = report["calls"]

        # Суддя — за межами кореневого спана агента: інакше його токени і його
        # вартість осіли б у підсумку самого звернення, і «скільки коштує агент»
        # уже не можна було б прочитати з трейсу.
        # Копія саме поглиблена: у tracing.USAGE значення — словники, які
        # обгортка мутує на місці, тож поверхнева копія показала б нульову
        # різницю і вартість судді завжди читалася б як нуль.
        before = {m: dict(u) for m, u in tracing.USAGE.items()}
        with tracer.start_as_current_span(f"judge {case['id']}",
                                          kind=SpanKind.INTERNAL) as js:
            js.set_attribute("spec.judged_trace_id", report["trace_id"])
            verdict = ev.judge(case, answer, calls)
            js.set_attribute("spec.judge.pass", bool(verdict["pass"]))
        judge_usd += _delta_usd(before, tracing.USAGE)

        t_ok = ev.tool_ok(case, calls)
        s_ok = ev.section_ok(case, answer)
        # Опора має сенс лише там, де є на що спиратися: кейс «цього немає в
        # специфікації» перевіряється суддею, а не звіркою номерів.
        g_ok, invented = (ev.grounded(answer, calls) if case["expects_section"]
                          else (True, []))
        row = {**case, "answer": answer, "calls": calls,
               "trace_id": report["trace_id"], "seconds": report["seconds"],
               "usage": report["usage"], "blocked": report["blocked"],
               "tool_ok": t_ok, "section_ok": s_ok, "grounded": g_ok,
               "invented_sections": invented, "judge": verdict,
               "pass": bool(t_ok and s_ok and g_ok and verdict["pass"])}
        rows.append(row)
        marks = "".join(("і" if t_ok else "·", "р" if s_ok else "·",
                         "о" if g_ok else "·", "с" if verdict["pass"] else "·"))
        print(f"{marks}  ${report['usage']['usd']:<9} {report['seconds']:>5} с")

    summary = ev.score(rows)
    agent_usd = round(sum(r["usage"]["usd"] for r in rows), 6)
    run = {"label": args.label, "corpus": corpus, "docs": args.docs,
           "when": datetime.datetime.now().isoformat(timespec="seconds"),
           "search_modes": sorted({c["search"] for r in rows for c in r["calls"]
                                   if c.get("search")}),
           "agent_usd": agent_usd, "judge_usd": round(judge_usd, 6),
           **summary, "rows": rows}

    ev.OUT.mkdir(parents=True, exist_ok=True)
    path = ev.OUT / f"run-{args.label}.json"
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    ev.append_history(run)
    print(f"\nПозначки: і — інструмент, р — названо розділ, о — опора на видачу, с — суддя")
    print(f"Скор: {summary['passed']}/{summary['cases']} = {summary['score']} "
          f"(поріг {summary['threshold']}) | інструменти {summary['tool_accuracy']} "
          f"(поріг {summary['tool_threshold']}) | гейт {summary['gate']}")
    print(f"Вартість: агент ${agent_usd}, суддя ${round(judge_usd, 6)}; "
          f"пошук: {', '.join(run['search_modes']) or '—'}")
    print(f"Прогін: {path}")
    return 0


def _delta_usd(before: dict, after: dict) -> float:
    from core.cost import usd
    delta = {}
    for model, row in after.items():
        was = before.get(model, {"in": 0, "out": 0})
        d_in, d_out = row["in"] - was["in"], row["out"] - was["out"]
        if d_in or d_out:
            delta[model] = {"in": d_in, "out": d_out}
    return usd(delta)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
