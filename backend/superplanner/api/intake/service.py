"""Settings -> intake options, AI client factory and per-app concurrency slots (PHASE2 2.10, 2.12)."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, Request

from superplanner import intake

from ..config import Settings
from ..errors import ApiError

SLOT_WAIT_SECONDS = 5.0


class AiSlots:
    """At most `n` AI calls in flight per app; waiting longer than 5 s for a slot means AI_BUSY."""

    def __init__(self, n: int, wait_seconds: float = SLOT_WAIT_SECONDS):
        self._sem = threading.BoundedSemaphore(max(1, n))
        self.wait_seconds = wait_seconds

    def acquire(self) -> bool:
        return self._sem.acquire(timeout=self.wait_seconds)

    def release(self) -> None:
        self._sem.release()


def install(app: FastAPI, settings: Settings) -> None:
    """Called by `create_app` next to the router registration: slots live on the app, not in a module global."""
    app.state.intake_ai_slots = AiSlots(settings.intake_ai_max_concurrent)


def settings_of(request: Request) -> Settings:
    return request.app.state.ctx.settings


def ai_options(request: Request, requested: bool) -> intake.AiOptions:
    s = settings_of(request)
    slots: AiSlots | None = getattr(request.app.state, "intake_ai_slots", None)
    return intake.AiOptions(requested=requested, enabled=s.intake_ai_enabled, client_factory=s.intake_ai_client_factory,
                            timeout_seconds=s.intake_ai_timeout_seconds, max_retries=s.intake_ai_max_retries,
                            acquire_slot=slots.acquire if slots else None,
                            release_slot=slots.release if slots else None)


def ai_state(request: Request) -> tuple[bool, str | None]:
    from superplanner.intake.ai.client import ai_status

    return ai_status(ai_options(request, requested=False))


def capabilities(request: Request) -> dict[str, Any]:
    s = settings_of(request)
    available, reason = ai_state(request)
    return {"ai_available": available, "ai_reason": reason, "provider": intake.PROVIDER, "model": intake.MODEL,
            "privacy_notice": intake.PRIVACY_NOTICE,
            "limits": {"max_text_chars": s.intake_max_text_chars, "max_table_chars": s.intake_max_table_chars,
                       "max_table_rows": intake.MAX_TABLE_ROWS, "max_table_columns": intake.MAX_TABLE_COLUMNS},
            "schedule_kinds": list(intake.SCHEDULE_KINDS)}


def api_error(exc: intake.IntakeError) -> ApiError:
    return ApiError(422, exc.code, exc.message, exc.details)
