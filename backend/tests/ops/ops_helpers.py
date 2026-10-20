"""Helpers for the Q5 operations tests."""

from __future__ import annotations

import io
import json
import logging
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from superplanner.api.config import Settings
from superplanner.api.main import create_app
from superplanner.obs.logging import make_handler

API = "/api/v1"
AUTH = f"{API}/auth"
PASSWORD = "correct horse battery"
BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent


def app_for(db_url: str, **overrides: Any):
    overrides.setdefault("password_hash_profile", "fast")
    return create_app(Settings(database_url=db_url, **overrides))


@contextmanager
def captured_logs(fmt: str = "json", service: str = "api", level: int = logging.INFO) -> Iterator[io.StringIO]:
    """Our real handler (formatter + context filter) on the root logger, writing to a StringIO."""
    buf = io.StringIO()
    handler = make_handler(fmt, service, buf)
    handler.setLevel(level)
    root = logging.getLogger()
    old = root.level
    root.addHandler(handler)
    root.setLevel(min(old or level, level))
    try:
        yield buf
    finally:
        root.removeHandler(handler)
        root.setLevel(old)


def json_lines(buf: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def problem(c, jobs: int = 4, name: str | None = None) -> str:
    body: dict[str, Any] = {"start_date": "2026-11-02", "utc_offset": "+00:00", "parameters": {"jobs": jobs}}
    r = c.post(f"{API}/templates/manufacturing/instantiate", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]
