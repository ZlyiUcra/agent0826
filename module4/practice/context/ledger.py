"""
КОНТЕКСТ · облік токенів і грошей, який бачить кеш. $0.

Курсовий USAGE у core/agent.py рахує лише input_tokens і output_tokens, а
PRICES у core/cost.py знає одну ціну вхідного токена. Кешований токен коштує
інакше: запис у кеш — 1.25 звичайної ціни входу, читання з кеша — 0.1 від неї.
Поки ці два поля не рахувати окремо, ціна прогону «з кешем» і «без кеша»
виходить однаковою, і сьомий чекбокс картки міряти нічим.

Ціни моделей беруться з курсового PRICES — одного джерела для обох таблиць, —
а множники кеша записані тут. Зміниться ціна моделі — зміниться один рядок у
core/cost.py, і цей файл підхопить її сам.

Журнал іще й сам робить виклики до моделі: кожне звернення проходить через
нього і лягає рядком, тож жоден виклик не залишається непорахованим — ані
розмова, ані допоміжні (видобуток фактів для пам'яті, підсумовування).
"""

from config import MODEL_FAST
from core.agent import client
from core.cost import PRICES

WRITE_FACTOR = 1.25   # запис у кеш, час життя п'ять хвилин
READ_FACTOR = 0.10    # читання з кеша


def cost_of(row: dict) -> float:
    """Ціна одного виклику з урахуванням кеша."""
    p = PRICES.get(row["model"])
    if not p:
        return 0.0
    inp = (row["input"] + row["cache_write"] * WRITE_FACTOR
           + row["cache_read"] * READ_FACTOR)
    return (inp * p["in"] + row["output"] * p["out"]) / 1e6


def cost_without_cache(row: dict) -> float:
    """Скільки коштував би той самий виклик, якби кеша не було зовсім."""
    p = PRICES.get(row["model"])
    if not p:
        return 0.0
    inp = row["input"] + row["cache_write"] + row["cache_read"]
    return (inp * p["in"] + row["output"] * p["out"]) / 1e6


class Ledger:
    """Журнал викликів: по рядку на кожне звернення до моделі."""

    def __init__(self):
        self.rows: list[dict] = []

    def record(self, model: str, usage, kind: str = "dialog") -> dict:
        row = {"kind": kind, "model": model,
               "input": usage.input_tokens, "output": usage.output_tokens,
               "cache_write": usage.cache_creation_input_tokens or 0,
               "cache_read": usage.cache_read_input_tokens or 0}
        row["usd"] = round(cost_of(row), 6)
        row["usd_uncached"] = round(cost_without_cache(row), 6)
        self.rows.append(row)
        return row

    def create(self, kind: str = "dialog", **kwargs):
        """Виклик моделі з записом у журнал. Повтори на 429 і 5xx робить сам SDK."""
        resp = client.messages.create(**kwargs)
        self.record(kwargs["model"], resp.usage, kind)
        return resp

    def ask(self, system: str, user: str, kind: str, max_tokens: int = 400) -> str:
        """Допоміжний виклик без інструментів на дешевій моделі — як курсовий ask()."""
        resp = self.create(kind=kind, model=MODEL_FAST, max_tokens=max_tokens,
                           temperature=0.0, system=system,
                           messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    def totals(self, kind: str | None = None) -> dict:
        rows = [r for r in self.rows if kind is None or r["kind"] == kind]
        keys = ("input", "output", "cache_write", "cache_read", "usd", "usd_uncached")
        out = {k: round(sum(r[k] for r in rows), 6) for k in keys}
        out["calls"] = len(rows)
        return out

    def by_kind(self) -> dict:
        return {k: self.totals(k) for k in sorted({r["kind"] for r in self.rows})}
