"""
ПРАКТИКА М8 · агент специфікації за HTTP.

Той самий агент, що й у practice/base/agent.py, з усіма чотирма шарами оборони —
змінюється лише спосіб виклику: замість термінала — HTTP. Кожен запит проходить
повний цикл: вхідний фільтр, agent loop з інструментами сервера знань через MCP,
вихідний фільтр і guardrail. Сервер знань піднімається підпроцесом на кожен
запит і вмирає разом з ним.

Діалог сервіс веде через сесії, і живуть вони не в процесі: історія кожної
сесії — файл у теці PRACTICE_SESSIONS_DIR (у поді це том, який переживає
рестарт). Клієнт передає session_id з попередньої відповіді — і агент
продовжує розмову з того самого місця, хоч би скільки разів процес за цей
час перезапускали. Без session_id кожен запит — нова розмова.

POST /ask    — повний прогін, JSON з відповіддю, трасою інструментів і вартістю;
               приймає {"query": ..., "session_id": ...}, session_id повертає
GET  /health — проба живучості для оркестратора

    .venv/bin/uvicorn practice.api:app --port 8001        # з теки module8/
    curl -s localhost:8001/ask -X POST -H 'content-type: application/json' \
         -d '{"query": "Чому 1 + \"1\" дає рядок, а 1 - \"1\" — число?"}'
"""

import json
import os
import pathlib
import re
import sys
import threading
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError:
    raise SystemExit("Потрібно:  pip install fastapi uvicorn")

from core import cost
from core.agent import USAGE, reset_usage
from practice.base import agent

app = FastAPI(title="spec-agent", version="0.2.0")

# Сесії — по файлу на розмову. Типове місце лежить у гітігнорній out/, а в
# поді змінна PRACTICE_SESSIONS_DIR указує на том: саме тому діалог переживає
# рестарт, хоч сам процес не тримає між запитами нічого.
SESSIONS_DIR = pathlib.Path(os.getenv("PRACTICE_SESSIONS_DIR",
                                      str(pathlib.Path(__file__).resolve().parent / "out" / "sessions")))
_SID = re.compile(r"^[0-9a-f]{8,64}$")

# В історію агентові їде хвіст розмови, а не вся вона: кожен хід везе історію
# в модель заново, і без межі десятий хід коштував би як десять перших.
HISTORY_LIMIT = 12


def _session_path(sid: str) -> pathlib.Path:
    return SESSIONS_DIR / f"{sid}.json"


def _load_history(sid: str) -> list:
    try:
        return json.loads(_session_path(sid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save_history(sid: str, history: list) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _session_path(sid).write_text(json.dumps(history, ensure_ascii=False, indent=1),
                                  encoding="utf-8")

# Лічильник токенів у core.agent — глобальний на процес. Без черги два
# одночасні запити склали б свої токени в один рахунок, і обидві відповіді
# показали б неправдиву вартість. Прогін агента і зняття рахунку тому йдуть
# під замком, один за одним.
_LOCK = threading.Lock()


class Ask(BaseModel):
    query: str
    session_id: str | None = None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ask")
def ask(body: Ask):
    started = time.time()
    sid = body.session_id or uuid.uuid4().hex[:12]
    if not _SID.match(sid):
        return {"error": "session_id — 8..64 шістнадцяткових символів"}
    history = _load_history(sid)
    with _LOCK:
        reset_usage()
        report = agent.run(body.query, history=history[-HISTORY_LIMIT:])
        usd = cost.usd(USAGE["by_model"])
    # У файл сесії лягає те, що бачив клієнт (shown), а не сира відповідь:
    # якщо вихідний фільтр щось зрізав, наступний хід не має цього повертати.
    history += [{"role": "user", "content": body.query},
                {"role": "assistant", "content": report["shown"]}]
    _save_history(sid, history)
    g = report["guardrail"] or {}
    return {
        "answer": report["shown"],
        "session_id": sid,
        "turns": len(history) // 2,
        "tools": [t["tool"] for t in report["trace"]],
        "blocked": report["blocked"],
        "input_blocked": report["input_blocked"],
        "output_flags": report["output_flags"],
        "guardrail": g.get("verdict"),
        "elapsed_sec": round(time.time() - started, 2),
        "cost_usd": usd,
    }
