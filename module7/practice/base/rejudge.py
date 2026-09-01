"""
ТОЧКА ВХОДУ · пересудити збережений прогін. ПЛАТНО, але дешево.

Агента не турбуємо: відповіді, виклики і видача інструментів уже лежать у файлі
прогону. Платимо лише за суддю — двадцять звернень до дешевої моделі замість
повного прогону з десятками звернень до дорогої.

Саме тому прогін і перевірка розділені файлом: калібрувати суддю (обсяг довідки,
формулювання критеріїв, сама модель) можна за копійки і скільки завгодно разів.

    python -m practice.base.rejudge --from baseline --label baseline-rejudged
    python -m practice.base.rejudge --from baseline --judge-model claude-sonnet-4-6

Детерміновані перевірки перераховуються теж — вони безкоштовні, і кейси могли
змінитися відтоді, як прогін знімали.
"""

import argparse
import datetime
import json
import sys

from practice import bootstrap


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="пересудити збережений прогін")
    ap.add_argument("--from", dest="src", required=True, help="мітка збереженого прогону")
    ap.add_argument("--label", default=None, help="мітка результату (типово <src>-rejudged)")
    ap.add_argument("--judge-model", default=None,
                    help="модель судді; типово дешева з .env примірника")
    args = ap.parse_args(argv)

    bootstrap.use()
    from practice import evaluation as ev

    src = ev.OUT / f"run-{args.src}.json"
    if not src.exists():
        raise SystemExit(f"Немає прогону {src}")
    run = json.loads(src.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in ev.load_dataset()}

    ask_json = _judge_with(args.judge_model)

    # Пересуд теж коштує грошей, і у файл має лягти СВОЯ цифра: у джерелі
    # записано, скільки коштував агент, а тут платимо лише за суддю. Лічильник
    # той самий, що в прогоні, але спани нікуди не летять — приймач для
    # пересуду не потрібен, а завантаження експортера коштує вісімнадцять секунд.
    from opentelemetry.sdk.trace import TracerProvider
    from practice import tracing

    tracing.reset()
    tracing.instrument(TracerProvider().get_tracer("practice.m07.rejudge"))

    rows, changed = [], []
    for r in run["rows"]:
        case = cases.get(r["id"], r)
        print(f"  {r['id']:<24}", end=" ", flush=True)
        verdict = ev.judge(case, r["answer"], r["calls"], ask_json=ask_json)
        t_ok = ev.tool_ok(case, r["calls"])
        s_ok = ev.section_ok(case, r["answer"])
        g_ok, invented = (ev.grounded(r["answer"], r["calls"])
                          if case.get("expects_section") else (True, []))
        row = {**r, **{k: case[k] for k in ("query", "criterion", "expects_section",
                                            "expects_document", "expects_tool")
                       if k in case},
               "tool_ok": t_ok, "section_ok": s_ok, "grounded": g_ok,
               "invented_sections": invented, "judge": verdict,
               "pass": bool(t_ok and s_ok and g_ok and verdict["pass"])}
        rows.append(row)
        if row["pass"] != r["pass"]:
            changed.append((r["id"], r["pass"], row["pass"]))
        print("pass" if row["pass"] else f"fail — {verdict['reason'][:70]}")

    from core.cost import usd

    judge_usd = round(usd(tracing.USAGE), 6)
    tracing.restore()

    label = args.label or f"{args.src}-rejudged"
    summary = ev.score(rows)
    out = {**run, "label": label, "rejudged_from": args.src,
           "judge_model": args.judge_model or "типова дешева",
           "when": datetime.datetime.now().isoformat(timespec="seconds"),
           "judge_usd": judge_usd,
           **summary, "rows": rows}
    path = ev.OUT / f"run-{label}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    ev.append_history(out)
    print(f"\nБуло {run['passed']}/{run['cases']} = {run['score']} ({run['gate']}); "
          f"стало {summary['passed']}/{summary['cases']} = {summary['score']} "
          f"({summary['gate']})")
    for cid, was, now in changed:
        print(f"  · {cid}: {'pass' if was else 'fail'} → {'pass' if now else 'fail'}")
    print(f"Суддя: ${judge_usd} (агент не запускався — його ${run.get('agent_usd', 0)} "
          f"уже витрачені на прогін {args.src})")
    print(f"Прогін: {path.relative_to(bootstrap.REPO)}")
    return 0


def _judge_with(model: str | None):
    """Суддя на вказаній моделі. Без аргументу — та сама дешева, що й у прогоні."""
    if not model:
        return None
    from common import llm

    def ask_json(system: str, user: str, fallback: dict) -> dict:
        raw = llm._call(model=model, max_tokens=400, temperature=0.0,
                        system=system + "\nПовертай ТІЛЬКИ валідний JSON, без пояснень.",
                        messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in raw.content if b.type == "text").strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {**fallback, "_raw": text[:200]}

    return ask_json


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
