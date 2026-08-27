"""
КОНТЕКСТ · з чого складається вікно і скільки важить кожна частина. $0.

Перший обов'язковий чекбокс картки: розкласти промпт на частини й порахувати
токени. Частин чотири, і саме на них дивиться другий чекбокс, коли питає, яка
росте швидше за всіх у довгій розмові:

    системний    промпт спеціаліста разом із правилами
    інструменти  описи інструментів — вони їдуть у КОЖНИЙ виклик
    розмова      репліки читача, відповіді агента і самі виклики інструментів
    знайдене     те, що повернув пошук (блоки tool_result)

Рахує ендпоінт count_tokens: він безкоштовний, але це звернення до сервера
Anthropic, тож ключ у .env потрібен. Локального токенізатора для цих моделей
немає, і будь-яка оцінка «символи поділити на чотири» дала б числа не про те.

Частини рахуються різницями. Запит із усім разом дає повне вікно; той самий
запит без системного промпта — вікно без нього; різниця і є вага промпта. Так
само з описами інструментів. Знайдене — різниця між історією як є і історією,
у якій тіла tool_result замінено на один символ. Розмова — те, що лишилося.
Чотири числа складаються рівно в повне вікно.

    python -m practice.context.window            # розклад по маршрутах, вартість описів,
                                                 # частота викликів інструментів
    python -m practice.context.window --sample   # те саме плюс одна репліка з пошуком:
                                                 # усі чотири частини на живому прикладі
"""

import copy
import json
import pathlib
import sys

from config import MODEL, MODEL_FAST
from core.agent import client
from core.cost import PRICES

from practice.base import team
from practice.base.single import SINGLE_PROMPT

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"

# Мінімальне повідомлення: без нього count_tokens відмовляє, а відняти його
# внесок легко — він однаковий у всіх запитах одного розкладу.
STUB = [{"role": "user", "content": "."}]

PARTS = ("system", "tools", "dialogue", "found")
LABELS = {"system": "системний", "tools": "інструменти",
          "dialogue": "розмова", "found": "знайдене"}


def count(model: str, system=None, tools=None, messages=None) -> int:
    kwargs = {"model": model, "messages": messages or STUB}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    return client.messages.count_tokens(**kwargs).input_tokens


def without_found(messages: list) -> list:
    """Та сама історія, але тіла tool_result замінено на один символ."""
    out = copy.deepcopy(messages)
    for m in out:
        if m["role"] == "user" and isinstance(m["content"], list):
            for block in m["content"]:
                if block.get("type") == "tool_result":
                    block["content"] = "-"
    return out


def parts(model: str, system, tools: list, messages: list | None) -> dict:
    """Чотири частини вікна і їхня сума. П'ять безкоштовних запитів."""
    messages = messages or STUB
    total = count(model, system, tools, messages)
    system_t = total - count(model, None, tools, messages)
    tools_t = total - count(model, system, None, messages)
    found_t = (count(model, None, None, messages)
               - count(model, None, None, without_found(messages)))
    return {"total": total, "system": system_t, "tools": tools_t,
            "dialogue": total - system_t - tools_t - found_t, "found": found_t}


def line(p: dict) -> str:
    """Один рядок розкладу для виводу: «7 812 = сист. 412 + …»."""
    return (f"{p['total']:>6,} = сист. {p['system']:,} + інстр. {p['tools']:,} "
            f"+ розмова {p['dialogue']:,} + знайдене {p['found']:,}")


# ── статичний розклад: що коштує кожен маршрут ще до першої репліки ──────

def routes() -> dict:
    """Системний промпт і описи інструментів кожного маршруту, у токенах."""
    out = {}
    for route in team.ROUTES:
        out[route] = parts(MODEL, team.prompt_for_route(route), team.tools_for_route(route), None)
    out["single"] = parts(MODEL, SINGLE_PROMPT,
                          [team.SCHEMAS[team.TOOL_NAMES[team.GENERAL]]], None)
    return out


def _latest(pattern: str) -> pathlib.Path | None:
    files = sorted(OUT.glob(pattern))
    return files[-1] if files else None


def descriptions_cost(by_route: dict) -> list[dict]:
    """Необов'язковий чекбокс: скільки коштували описи інструментів у записаному
    вимірі першої картки. Описи їдуть у кожен виклик, тож ціна — вага описів
    маршруту, помножена на кількість викликів і на ціну входу моделі.

    Наближення, назване прямо: у маршруті GENERAL частина викликів робить
    субагент зі своїм, коротшим списком інструментів, а запис виміру кількість
    викликів по сторонах не ділить. Тому для GENERAL узято описи самого маршруту
    на всі його виклики — оцінка зверху.
    """
    path = _latest("compare-*.json")
    if path is None:
        return []
    record = json.loads(path.read_text(encoding="utf-8"))
    price_in = PRICES.get(record.get("model", MODEL), {"in": 0})["in"]
    rows = []
    for r in record["records"]:
        # Сторона в записі названа українським словом: «один» або «система».
        system_side = r["side"] == "система"
        key = r.get("routed_to") if system_side else "single"
        if key not in by_route:
            key = team.GENERAL
        tokens = by_route[key]["tools"]
        rows.append({"scenario": r["scenario"], "side": r["side"], "route": key,
                     "calls": r["calls"], "tool_tokens": tokens,
                     "usd": round(tokens * r["calls"] * price_in / 1e6, 6),
                     "run_usd": r["cost_usd"]})
    return rows


def call_counts() -> dict:
    """Скільки разів МОДЕЛЬ викликала кожен інструмент у збережених прогонах.

    Джерело — сліди прогонів у system_results.json; запис виміру compare-*.json
    слідів не тримає. Це те, від чого відштовхується необов'язковий чекбокс
    «прибрати інструменти, які модель майже не викликає».

    Черга запитів на передачу людині (out/pending_handoff.json) сюди не
    входить навмисно: запит туди ставить і модель через request_handoff, і сам
    конвеєр через decide() у base/system.py, а в самій черзі не записано, хто.
    Хто поставив, каже поле handoff.by у записі прогону. Раніше черга додавалася
    до лічильника request_handoff, і єдиний запис, поставлений конвеєром,
    читався як виклик моделі.
    """
    counts = {name: 0 for name in team.PRACTICE_IMPL}
    path = OUT / "system_results.json"
    if path.exists():
        for rec in json.loads(path.read_text(encoding="utf-8")).values():
            for step in rec.get("trace", []):
                if step.get("tool") in counts:
                    counts[step["tool"]] += 1
    return counts


def pending_requests() -> list:
    """Черга запитів на передачу людині як є: модельні і конвеєрні разом."""
    pending = OUT / "pending_handoff.json"
    if not pending.exists():
        return []
    return json.loads(pending.read_text(encoding="utf-8"))


# Одна репліка з одним пошуком — щоб побачити всі чотири частини, не платячи за
# розмову. Знайдене тут справжнє: перший фрагмент, який пошук повертає на це
# питання по наявних документах.
SAMPLE_QUESTION = "What can the second argument of String.prototype.replace be?"


def sample() -> tuple[list, list]:
    from domain.backend import dispatch
    team.register()
    query = "String.prototype.replace second argument replaceValue"
    found = dispatch(team.TOOL_NAMES[team.GENERAL], {"query": query})
    messages = [
        {"role": "user", "content": SAMPLE_QUESTION},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "sample-1",
                                           "name": team.TOOL_NAMES[team.GENERAL],
                                           "input": {"query": query}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "sample-1",
                                      "content": json.dumps(found, ensure_ascii=False)}]},
    ]
    return messages, [p["id"] for p in found.get("passages", [])]


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    print(f"── Вікно контексту до першої репліки · модель {MODEL} ──")
    print("  Розмова тут — лише мінімальне повідомлення-заглушка, знайденого ще немає.\n")
    by_route = routes()
    print(f"  {'маршрут':<10}{'системний':>11}{'інструменти':>13}{'разом':>8}   інструменти")
    for route, p in by_route.items():
        names = ", ".join(t["name"] for t in (team.tools_for_route(route)
                                              if route in team.ROUTES
                                              else [team.SCHEMAS[team.TOOL_NAMES[team.GENERAL]]]))
        print(f"  {route:<10}{p['system']:>11,}{p['tools']:>13,}{p['total']:>8,}   {names}")

    # Необов'язковий чекбокс про рідко вживаний інструмент, безкоштовна половина:
    # скільки токенів кожен виклик GENERAL везе лише через request_handoff.
    if team.REQUEST_TOOL not in team.dropped_tools():
        without = parts(MODEL, team.prompt_for_route(team.GENERAL, {team.REQUEST_TOOL}),
                        team.tools_for_route(team.GENERAL, drop={team.REQUEST_TOOL}), None)
        full = by_route[team.GENERAL]
        print(f"  GENERAL без {team.REQUEST_TOOL}: системний {without['system']:,}, "
              f"інструменти {without['tools']:,}, разом {without['total']:,} — "
              f"на {full['total'] - without['total']:,} токенів менше на кожен виклик")

    rows = descriptions_cost(by_route)
    if rows:
        print(f"\n── Вартість описів інструментів у вимірі першої картки "
              f"(ціна входу {MODEL}) ──")
        print(f"  {'сценарій':<9}{'сторона':<8}{'маршрут':<10}{'викл.':>6}"
              f"{'токенів':>9}{'описи $':>10}{'прогін $':>10}")
        for r in rows:
            print(f"  {r['scenario']:<9}{r['side']:<8}{r['route']:<10}{r['calls']:>6}"
                  f"{r['tool_tokens']:>9,}{r['usd']:>10.4f}{r['run_usd']:>10.4f}")
        for side in ("один", "система"):
            mine = [r for r in rows if r["side"] == side]
            desc = sum(r["usd"] for r in mine)
            run = sum(r["run_usd"] for r in mine)
            share = desc / run * 100 if run else 0
            print(f"  {side}: описи ${desc:.4f} з ${run:.4f} за прогін — {share:.1f}%")
    else:
        print("\n  Запису виміру compare-*.json ще немає — вартість описів порахувати нема на чому.")

    if "--sample" in argv:
        messages, ids = sample()
        p = parts(MODEL_FAST, SINGLE_PROMPT,
                  [team.SCHEMAS[team.TOOL_NAMES[team.GENERAL]]], messages)
        print(f"\n── Одна репліка з одним пошуком · модель {MODEL_FAST} ──")
        print(f"  питання:  «{SAMPLE_QUESTION}»")
        print(f"  знайдено: {', '.join(ids) or 'нічого'}")
        print(f"  вікно {line(p)}")

    counts = call_counts()
    print("\n── Скільки разів модель викликала кожен інструмент (збережені сліди) ──")
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<22}{n:>4}")
    pending = pending_requests()
    print(f"  черга запитів на передачу людині: {len(pending)} — окремо від лічильника, бо "
          f"ставить їх і модель, і конвеєр; хто саме, каже handoff.by у записі прогону")
    print(f"  (модель {MODEL_FAST} у розмовах context/dialog має один інструмент — "
          f"{team.TOOL_NAMES[team.GENERAL]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
