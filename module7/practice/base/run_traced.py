"""
ТОЧКА ВХОДУ · одне питання до агента специфікації, з трейсингом. ПЛАТНО.

Це той самий агент, що й ./df ecmascript ask, лише обгорнутий спанами. Виклики
моделі справжні, тож кожен запуск коштує грошей: до шести звернень до моделі
агента плюс одне до дешевої на guardrail.

    python -m practice.base.run_traced "How does Object.prototype.toString build the tag?"
    python -m practice.base.run_traced "…" --backend console      # без приймача
    python -m practice.base.run_traced "…" --instance ecmascript-degraded

Приймач за замовчуванням — Phoenix на 127.0.0.1:6006; його треба підняти
заздалегідь (див. practice/SETUP.md).
"""

import argparse
import datetime
import json
import sys

from practice import bootstrap


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("query", help="питання до специфікації, англійськими термінами")
    ap.add_argument("--backend", default="phoenix",
                    help="куди слати спани: phoenix, console, langfuse, langsmith, otlp")
    ap.add_argument("--instance", default="ecmascript",
                    help="примірник фабрики (для деградованої копії)")
    ap.add_argument("--no-save", action="store_true",
                    help="не зберігати звіт у practice/out/")
    args = ap.parse_args(argv)

    bootstrap.use(args.instance)
    from practice import tracing

    tracer, where = tracing.setup(args.backend)
    print(f"Спани летять у: {where}")
    tracing.instrument(tracer)

    report = tracing.traced_run(args.query, tracer, instance=args.instance)

    print("\nПоказано клієнту:\n ", report["shown"])
    if report["blocked"]:
        print("\nЗаблоковано шарами:", report["blocked"])
    if report["output_flags"]:
        print("Вихідний фільтр:", report["output_flags"])

    print("\nВиклики інструментів:")
    for c in report["calls"] or [{"tool": "—", "ok": True, "ms": 0, "search": None}]:
        mark = "ok  " if c["ok"] else "FAIL"
        mode = f", {c['search']}" if c.get("search") else ""
        print(f"  {mark} {c['tool']:<13} {c['ms']:>7} мс{mode}")
        # Розділи, які агент справді побачив: саме за ними пишеться критерій
        # кейса, коли цей прогін стане матеріалом для набору.
        for p in _sections(c.get("output") or {}):
            print(f"         {p}")

    if not args.no_save:
        OUT = bootstrap.MODULE7 / "practice" / "out"
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = OUT / f"traced-{stamp}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"\nЗвіт: {path.relative_to(bootstrap.REPO)}")

    u = report["usage"]
    print(f"\nТокени: {u['in']} вхід, {u['out']} вихід за {u['calls']} звернень "
          f"до моделі; вартість ${u['usd']}")
    print(f"Час: {report['seconds']} с | трейс: {report['trace_id']}")
    return 0


def _sections(out: dict) -> list:
    """Назви розділів з відповіді інструмента, у порядку видачі."""
    if "passages" in out:
        return [f"· {p['section']}" for p in out["passages"]]
    if "section" in out:
        return [f"· {out['section']}"]
    if "error" in out:
        return [f"· помилка: {out['error']}"]
    return []


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
