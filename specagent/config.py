"""Конфігурація. Ключ береться з .env — у код нічого не зашивається."""

import os
import pathlib
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    raise SystemExit(
        "Не знайдено ANTHROPIC_API_KEY.\n"
        "  cp .env.example .env   і впишіть ключ у .env"
    )

# ── каскад моделей ────────────────────────────────────────────
# Дорога модель міркує в циклі агента. Guardrail робить просту роботу —
# йому вистачає дешевої.
MODEL      = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")       # цикл агента
MODEL_FAST = os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5-20251001")  # guardrail

MAX_TOKENS = int(os.getenv("MAX_TOKENS", 1200))
MAX_TURNS  = int(os.getenv("MAX_TURNS", 6))
