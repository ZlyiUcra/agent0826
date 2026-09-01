"""
ТОЧКА ВХОДУ · паспорт корпусу для безкоштовних перевірок. БЕЗКОШТОВНО.

Тека `docfactory/` лежить поза репозиторієм курсу, і хто клонує репозиторій,
її не отримує. Без неї два тести набору не мали б до чого звертатися: один
питає, чи дозволено агентові інструмент, якого чекає кейс, другий — чи існує
очікуваний розділ у названому документі. Обидва питання про корпус, а корпус
за межами репозиторію.

Паспорт знімає цю залежність. Він фіксує у файлі те, що тестам справді
потрібно — перелік дозволених інструментів і розділи, на які націлений набір, —
і лягає під git поруч із набором. Далі перевірки набору читають паспорт і
працюють у голому клоні, без фабрики і без Qdrant.

Паспорт не замінює корпус, а лише датує його: він каже, що на таке-то число
такі розділи в таких документах існували. Коли фабрика під рукою, окремий тест
звіряє паспорт із живим корпусом і падає, щойно вони розійдуться.

    python -m practice.base.passport            # перезняти паспорт
    python -m practice.base.passport --check     # лише звірити, нічого не писати

Перезнімати паспорт треба після кожної зміни набору кейсів або корпусу.
"""

import argparse
import datetime
import hashlib
import json
import sys

from practice import bootstrap

NAME = "corpus-passport.json"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="паспорт корпусу для перевірок набору")
    ap.add_argument("--check", action="store_true",
                    help="звірити наявний паспорт із корпусом, не переписуючи його")
    ap.add_argument("--instance", default="ecmascript", help="примірник фабрики")
    args = ap.parse_args(argv)

    # Вектори тут не потрібні: паспорт знімається з файлів корпусу, а не з бази.
    bootstrap.use(args.instance, vectors_wait=False)
    from practice import evaluation as ev

    fresh = build(args.instance, ev.load_dataset())
    path = ev.DATA / NAME

    if args.check:
        if not path.exists():
            raise SystemExit(f"Паспорта немає: {path}\n  Зняти: python -m practice.base.passport")
        old = json.loads(path.read_text(encoding="utf-8"))
        diff = _diff(old, fresh)
        for line in diff:
            print(f"  {line}")
        print("Паспорт збігається з корпусом." if not diff
              else f"Розходжень: {len(diff)}. Перезняти: python -m practice.base.passport")
        return 0 if not diff else 1

    path.write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Документів {fresh['corpus']['documents']}, фрагментів {fresh['corpus']['passages']}, "
          f"розділів у наборі {len(fresh['sections'])}")
    print(f"Паспорт: {path.relative_to(bootstrap.REPO)}")
    return 0


def build(instance: str, cases: list) -> dict:
    """Знімає з живого корпусу рівно те, що потрібно перевіркам набору."""
    from server import layers, spec_mcp

    passages = spec_mcp._INDEX.passages
    ids = "\n".join(sorted(spec_mcp._BY_ID))
    wanted = {c["expects_section"] for c in cases if c.get("expects_section")}

    # На кожен очікуваний номер — усі документи, де він трапляється. Саме тому
    # кейс і зобов'язаний називати документ: номер сам собою адресує кілька
    # різних розділів, і перевірка без документа пропустила б чужий.
    where: dict[str, list] = {}
    for p in passages:
        section = p.label.split(" ")[0]
        if section in wanted:
            doc = getattr(p, "doc_id", "")
            if doc and doc not in where.setdefault(section, []):
                where[section].append(doc)

    return {
        "instance": instance,
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "corpus": {
            "documents": len({getattr(p, "doc_id", "") for p in passages}),
            "passages": len(passages),
            "ids": hashlib.sha256(ids.encode()).hexdigest()[:16],
        },
        "allowed_tools": sorted(layers.ALLOWED_TOOLS),
        "sections": {s: sorted(where.get(s, [])) for s in sorted(wanted)},
    }


def _diff(old: dict, fresh: dict) -> list:
    """Розходження паспорта з корпусом, рядками. Час зняття не порівнюється."""
    out = []
    for key in ("documents", "passages", "ids"):
        if old.get("corpus", {}).get(key) != fresh["corpus"][key]:
            out.append(f"corpus.{key}: у паспорті {old.get('corpus', {}).get(key)}, "
                       f"у корпусі {fresh['corpus'][key]}")
    if old.get("allowed_tools") != fresh["allowed_tools"]:
        out.append(f"allowed_tools: у паспорті {old.get('allowed_tools')}, "
                   f"у сервері {fresh['allowed_tools']}")
    for section, docs in fresh["sections"].items():
        if old.get("sections", {}).get(section) != docs:
            out.append(f"{section}: у паспорті {old.get('sections', {}).get(section)}, "
                       f"у корпусі {docs}")
    for section in old.get("sections", {}):
        if section not in fresh["sections"]:
            out.append(f"{section}: є в паспорті, але набір його вже не чекає")
    return out


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
