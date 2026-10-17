"""API settings (ARCHITECTURE 13, 14, 16). Read from the environment; tests pass explicit values."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{BACKEND_DIR / 'superplanner.db'}"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def _env_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS")
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def _env_max_body() -> int:
    try:
        return max(1024, int(os.environ.get("MAX_BODY_BYTES", str(5 * 1024 * 1024))))
    except ValueError:
        return 5 * 1024 * 1024


def _env_workers() -> int:
    try:
        return max(1, int(os.environ.get("RUN_WORKERS", "2")))
    except ValueError:
        return 2


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return v if v > 0 else default


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL)
    cors_origins: list[str] = field(default_factory=_env_origins)
    run_workers: int = field(default_factory=_env_workers)
    max_body_bytes: int = field(default_factory=_env_max_body)   # 413 PAYLOAD_TOO_LARGE above this
    sse_poll_seconds: float = 0.5
    sse_keepalive_seconds: float = 15.0
    progress_min_interval_seconds: float = 0.5   # max 2 progress events per second per run
    # Intake (PHASE2 2.12). AI assist is off unless INTAKE_AI_ENABLED is set and credentials resolve.
    intake_ai_enabled: bool = field(default_factory=lambda: _env_flag("INTAKE_AI_ENABLED"))
    intake_ai_timeout_seconds: float = field(default_factory=lambda: _env_float("INTAKE_AI_TIMEOUT_SECONDS", 60.0))
    intake_ai_max_retries: int = 2
    intake_ai_max_concurrent: int = 2
    intake_max_text_chars: int = 20000
    intake_max_table_chars: int = 1_000_000
    intake_ai_client_factory: Callable[[], Any] | None = None   # tests only: returns a fake SDK client
