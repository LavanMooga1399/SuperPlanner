"""DB-backed fixed-window rate limits shared by all API instances (PHASE2B 4.6).

One upsert per bucket (`INSERT ... ON CONFLICT (bucket) DO UPDATE ... RETURNING`), so concurrent requests on
several instances count exactly. Hits are committed in their own transaction *before* the password is verified,
so a failed sign-in still counts.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, case, literal
from sqlalchemy.orm import Session

from .models import AuthRateLimitRow

SIGNIN_WINDOW = timedelta(minutes=5)
SIGNUP_WINDOW = timedelta(hours=1)
CHANGE_PASSWORD_WINDOW = timedelta(minutes=15)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def hit(s: Session, bucket: str, limit: int, window: timedelta, now: datetime | None = None) -> tuple[bool, int]:
    """Count one hit in `bucket`. Returns (allowed, retry_after_seconds); retry_after is 0 when allowed."""
    now = now or datetime.now(UTC)
    dialect = s.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    t = AuthRateLimitRow.__table__
    cutoff = literal(now - window, DateTime(timezone=True))
    now_l = literal(now, DateTime(timezone=True))
    expired = t.c.window_start < cutoff
    stmt = insert(t).values(bucket=bucket[:160], window_start=now, count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.bucket],
        set_={"window_start": case((expired, now_l), else_=t.c.window_start),
              "count": case((expired, 1), else_=t.c.count + 1)},
    ).returning(t.c.window_start, t.c.count)
    window_start, count = s.execute(stmt).one()
    if count <= limit:
        return True, 0
    retry = (_aware(window_start) + window - now).total_seconds()
    return False, max(1, math.ceil(retry))


def hit_all(s: Session, buckets: list[tuple[str, int, timedelta]],
            now: datetime | None = None) -> tuple[bool, int]:
    """Count a hit in every bucket (all must allow). Returns (allowed, the longest retry_after)."""
    allowed, retry = True, 0
    for bucket, limit, window in buckets:
        ok, r = hit(s, bucket, limit, window, now)
        if not ok:
            allowed, retry = False, max(retry, r)
    return allowed, retry
