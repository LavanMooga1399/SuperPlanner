"""Server-side sessions and the session cookie (PHASE2B 4.4).

Cookie value = `secrets.token_urlsafe(32)`; the DB stores only `sha256(token)`. Lifetime: absolute
`SESSION_MAX_AGE_DAYS`, idle `SESSION_IDLE_DAYS` (`last_seen_at` older -> invalid); `last_seen_at` is written at
most every `TOUCH_INTERVAL`. Each session carries its own random CSRF token (synchronizer token).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import new_id
from .models import UserRow, UserSessionRow

TOUCH_INTERVAL = timedelta(minutes=5)
SECURE_COOKIE_NAME = "__Host-sp_session"
PLAIN_COOKIE_NAME = "sp_session"


def aware(dt: datetime | None) -> datetime | None:
    """Aware UTC datetime (timestamptz columns return aware values; naive input is treated as UTC)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_name(settings: Any) -> str:
    return SECURE_COOKIE_NAME if settings.cookie_secure else PLAIN_COOKIE_NAME


def read_cookie(request: Request, settings: Any) -> str | None:
    value = request.cookies.get(cookie_name(settings))
    return value or None


def _cookie_header(settings: Any, value: str, max_age: int) -> str:
    parts = [f"{cookie_name(settings)}={value}", "HttpOnly", f"Max-Age={max(0, int(max_age))}", "Path=/",
             "SameSite=Lax"]
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)    # never a Domain attribute (required for the __Host- prefix)


def set_session_cookie(response: Response, settings: Any, token: str, expires_at: datetime,
                       now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    max_age = int((aware(expires_at) - now).total_seconds())   # type: ignore[operator]
    response.headers.append("set-cookie", _cookie_header(settings, token, max_age))


def clear_cookie_header(settings: Any) -> str:
    return _cookie_header(settings, '""', 0)


def clear_session_cookie(response: Response, settings: Any) -> None:
    response.headers.append("set-cookie", clear_cookie_header(settings))


@dataclass(frozen=True)
class SessionView:
    """A validated session joined with its user (detached plain values)."""

    session_id: str
    user_id: str
    csrf_token: str
    expires_at: datetime
    user: dict[str, Any]


def user_dict(u: UserRow) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "is_local": bool(u.is_local),
            "created_at": aware(u.created_at)}


def create_session(s: Session, user: UserRow, settings: Any, request: Request | None,
                   now: datetime | None = None) -> tuple[UserSessionRow, str]:
    """Insert a new session; returns (row, cookie token). The token itself is never stored."""
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent") if request is not None else None
    ip = request.client.host if request is not None and request.client is not None else None
    row = UserSessionRow(id=new_id("ses_"), user_id=user.id, token_hash=token_hash(token),
                         csrf_token=secrets.token_urlsafe(32), created_at=now, last_seen_at=now,
                         expires_at=now + timedelta(days=settings.session_max_age_days), revoked_at=None,
                         user_agent=(ua or None) and ua[:200], ip=(ip or None) and ip[:45])
    s.add(row)
    s.flush()
    return row, token


def _valid(row: UserSessionRow, user: UserRow, settings: Any, now: datetime) -> bool:
    if row.revoked_at is not None or user.disabled or user.is_local or not user.password_hash:
        return False
    if aware(row.expires_at) <= now:   # type: ignore[operator]
        return False
    if aware(row.last_seen_at) < now - timedelta(days=settings.session_idle_days):   # type: ignore[operator]
        return False
    return True


def lookup(s: Session, token: str | None, settings: Any,
           now: datetime | None = None) -> tuple[UserSessionRow, UserRow] | None:
    """The valid session for a cookie token (not revoked, not expired, not idle, user enabled), else None."""
    if not token or len(token) > 200:
        return None
    now = now or datetime.now(UTC)
    found = s.execute(select(UserSessionRow, UserRow).join(UserRow, UserRow.id == UserSessionRow.user_id)
                      .where(UserSessionRow.token_hash == token_hash(token))).first()
    if found is None:
        return None
    row, user = found
    return (row, user) if _valid(row, user, settings, now) else None


def view(row: UserSessionRow, user: UserRow) -> SessionView:
    return SessionView(session_id=row.id, user_id=user.id, csrf_token=row.csrf_token,
                       expires_at=aware(row.expires_at), user=user_dict(user))   # type: ignore[arg-type]


def needs_touch(row: UserSessionRow, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return aware(row.last_seen_at) <= now - TOUCH_INTERVAL   # type: ignore[operator]


def touch(s: Session, session_id: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    s.execute(update(UserSessionRow).where(UserSessionRow.id == session_id, UserSessionRow.revoked_at.is_(None))
              .values(last_seen_at=now).execution_options(synchronize_session=False))


def revoke(s: Session, session_id: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    s.execute(update(UserSessionRow).where(UserSessionRow.id == session_id, UserSessionRow.revoked_at.is_(None))
              .values(revoked_at=now).execution_options(synchronize_session=False))


def revoke_all(s: Session, user_id: str, except_id: str | None = None, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    stmt = update(UserSessionRow).where(UserSessionRow.user_id == user_id, UserSessionRow.revoked_at.is_(None))
    if except_id is not None:
        stmt = stmt.where(UserSessionRow.id != except_id)
    res = s.execute(stmt.values(revoked_at=now).execution_options(synchronize_session=False))
    return int(res.rowcount or 0)
