"""
ПРАКТИКА М8 · агент специфікації за HTTP.

Той самий агент, що й у practice/base/agent.py, з усіма чотирма шарами оборони —
змінюється лише спосіб виклику: замість термінала — HTTP. Кожен запит проходить
повний цикл: вхідний фільтр, agent loop з інструментами сервера знань через MCP,
вихідний фільтр і guardrail. Сервер знань піднімається підпроцесом на кожен
запит і вмирає разом з ним — стану між запитами немає навмисно: це та сама
властивість, яку модуль показує на рестарті пода.

POST /ask    — повний прогін, JSON з відповіддю, трасою інструментів і вартістю
GET  /health — проба живучості для оркестратора

    .venv/bin/uvicorn practice.api:app --port 8001        # з теки module8/
    curl -s localhost:8001/ask -X POST -H 'content-type: application/json' \
         -d '{"query": "Чому 1 + \"1\" дає рядок, а 1 - \"1\" — число?"}'
"""

import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError:
    raise SystemExit("Потрібно:  pip install fastapi uvicorn")

from core import cost
from core.agent import USAGE, reset_usage
from practice.base import agent

app = FastAPI(title="spec-agent", version="0.1.0")

# Лічильник токенів у core.agent — глобальний на процес. Без черги два
# одночасні запити склали б свої токени в один рахунок, і обидві відповіді
# показали б неправдиву вартість. Прогін агента і зняття рахунку тому йдуть
# під замком, один за одним.
_LOCK = threading.Lock()


class Ask(BaseModel):
    query: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ask")
def ask(body: Ask):
    started = time.time()
    with _LOCK:
        reset_usage()
        report = agent.run(body.query)
        usd = cost.usd(USAGE["by_model"])
    g = report["guardrail"] or {}
    return {
        "answer": report["shown"],
        "tools": [t["tool"] for t in report["trace"]],
        "blocked": report["blocked"],
        "input_blocked": report["input_blocked"],
        "output_flags": report["output_flags"],
        "guardrail": g.get("verdict"),
        "elapsed_sec": round(time.time() - started, 2),
        "cost_usd": usd,
    }
