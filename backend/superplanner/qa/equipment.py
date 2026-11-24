"""Equipment validity (M7-DESIGN 8), pure: Valid(e, t) = active and (no calibration required or
date(t) <= due_on + grace_days)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def valid_on(status: str, calibration_required: bool, due_on: date | None, grace_days: int, d: date) -> bool:
    if status != "active":
        return False
    if not calibration_required:
        return True
    return due_on is not None and d <= due_on + timedelta(days=int(grace_days or 0))


def valid(e: Any, d: date) -> bool:
    return valid_on(e.status, bool(e.calibration_required), e.due_on, e.grace_days, d)


def blocked_from(e: Any) -> date | None:
    """First invalid day of an active, calibration-required item (None: never by date)."""
    if e.status != "active":
        return date.min
    if not e.calibration_required:
        return None
    if e.due_on is None:
        return date.min
    return e.due_on + timedelta(days=int(e.grace_days or 0) + 1)


def due_state(e: Any, d: date, warn_days: int) -> str:
    if e.status in ("out_of_service", "retired"):
        return e.status
    if not e.calibration_required:
        return "not_required"
    if e.due_on is None or d > e.due_on + timedelta(days=int(e.grace_days or 0)):
        return "overdue"
    if d > e.due_on:
        return "in_grace"
    if d >= e.due_on - timedelta(days=warn_days):
        return "due_soon"
    return "ok"


__all__ = ["blocked_from", "due_state", "valid", "valid_on"]
