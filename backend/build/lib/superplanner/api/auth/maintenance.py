"""Pruning of auth tables (PHASE2B 2.9 maintenance, 4.9 `manage prune`). Signature frozen for Q2/Q3:
`prune_auth_tables(s, now) -> dict[str, int]`, run inside the caller's write transaction (system scope)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from .models import AuthRateLimitRow, UserSessionRow

# Longest rate-limit window in use (sign-up: 1 hour, B 4.6); older buckets can never count again.
RATE_LIMIT_MAX_WINDOW = timedelta(hours=1)
# Revoked sessions are kept for a day (useful when investigating a sign-out), then deleted.
REVOKED_SESSION_RETENTION = timedelta(days=1)


def prune_auth_tables(s: Session, now: datetime) -> dict[str, int]:
    """Delete expired or long-revoked sessions and stale rate-limit buckets. Returns deleted row counts."""
    sessions = s.execute(delete(UserSessionRow).where(or_(
        UserSessionRow.expires_at < now,
        UserSessionRow.revoked_at < now - REVOKED_SESSION_RETENTION)).execution_options(synchronize_session=False))
    buckets = s.execute(delete(AuthRateLimitRow).where(AuthRateLimitRow.window_start < now - RATE_LIMIT_MAX_WINDOW)
                        .execution_options(synchronize_session=False))
    return {"user_sessions": int(sessions.rowcount or 0), "auth_rate_limits": int(buckets.rowcount or 0)}
