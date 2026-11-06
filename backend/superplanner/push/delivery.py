"""S0 placeholder (S3: Web Push delivery)."""

from __future__ import annotations

from typing import Any


def send_to_user(ctx: Any, user_id: str, topic: str, title: str, body: str, link: str) -> int:
    return 0


def run_job(ctx: Any, run_id: str, lease: Any) -> None:  # pragma: no cover - S3
    raise NotImplementedError
