"""Q3-7 session lifetime, revocation, disabled users, fixation, throttled touch (PHASE2B 4.4)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from auth_helpers import API, AUTH, acc_app, error, sign_in, sign_up

from superplanner.api.auth import sessions as sess
from superplanner.api.auth.deps import require_user
from superplanner.api.auth.models import UserRow, UserSessionRow


def _session_row(app, token: str) -> UserSessionRow:
    with app.state.ctx.db.read() as s:
        row = s.scalar(select(UserSessionRow).where(UserSessionRow.token_hash == sess.token_hash(token)))
        s.expunge(row)
        return row


def _set(app, token: str, **values) -> None:
    with app.state.ctx.db.write() as s:
        s.execute(update(UserSessionRow).where(UserSessionRow.token_hash == sess.token_hash(token)).values(**values))


def test_require_user_is_async():
    assert inspect.iscoroutinefunction(require_user)


def test_token_is_stored_hashed(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        token = c.cookies.get("sp_session")
        with app.state.ctx.db.read() as s:
            rows = s.scalars(select(UserSessionRow)).all()
            assert len(rows) == 1 and rows[0].token_hash == sess.token_hash(token) and token not in rows[0].token_hash
            assert rows[0].id.startswith("ses_") and rows[0].csrf_token != token
            assert rows[0].user_agent == "testclient" and rows[0].ip == "testclient"


@pytest.mark.parametrize("case", ["expired", "idle", "revoked"])
def test_invalid_sessions_are_401(db_url, case):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        token = c.cookies.get("sp_session")
        assert c.get(f"{API}/problems").status_code == 200
        now = datetime.now(UTC)
        if case == "expired":
            _set(app, token, expires_at=now - timedelta(seconds=1))
        elif case == "idle":
            _set(app, token, last_seen_at=now - timedelta(days=7, seconds=5))
        else:
            _set(app, token, revoked_at=now)
        r = c.get(f"{API}/problems")
        error(r, 401, "AUTH_REQUIRED")
        assert "Max-Age=0" in r.headers.get("set-cookie", "")
        assert c.get(f"{AUTH}/session").json()["authenticated"] is False


def test_idle_window_boundary_and_touch_throttle(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        token = c.cookies.get("sp_session")
        first = sess.aware(_session_row(app, token).last_seen_at)
        c.get(f"{API}/problems")
        assert sess.aware(_session_row(app, token).last_seen_at) == first     # < 5 min: no write
        old = datetime.now(UTC) - timedelta(days=6)
        _set(app, token, last_seen_at=old)
        assert c.get(f"{API}/problems").status_code == 200                   # 6 days idle: still valid
        touched = sess.aware(_session_row(app, token).last_seen_at)
        assert touched > old + timedelta(days=5)                               # and touched


def test_disabled_user_rejected_on_every_request(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        info = sign_up(c, "ana@example.com")
        assert c.get(f"{API}/problems").status_code == 200
        with app.state.ctx.db.write() as s:
            s.execute(update(UserRow).where(UserRow.id == info["user"]["id"]).values(disabled=True))
        error(c.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
        error(c.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": "correct horse battery"}),
              401, "INVALID_CREDENTIALS")


def test_sign_in_always_creates_a_new_session(db_url):
    """Fixation: a session id planted before sign-in is never reused."""
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        t1 = c.cookies.get("sp_session")
        id1 = _session_row(app, t1).id
        c.post(f"{AUTH}/sign-out")
        c.cookies.clear()
        c.cookies.set("sp_session", t1, domain="testserver.local")   # attacker-known (revoked) token
        sign_in(c, "ana@example.com")
        t2 = c.cookies.get("sp_session")
        assert t2 != t1 and _session_row(app, t2).id != id1
        fresh = TestClient(app)
        sign_in(fresh, "ana@example.com")
        assert fresh.cookies.get("sp_session") not in (t1, t2)
        assert c.get(f"{API}/problems").status_code == 200           # several sessions per user may coexist


def test_session_lookup_is_system_scoped_inside_requests(db_url):
    """R9: the lookup runs before a user is bound; it must not trip the fail-closed ownership rule."""
    app = acc_app(db_url)
    client = TestClient(app)                     # no `with`: lazy start inside the first request
    error(client.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
    sign_up(client, "ana@example.com")
    assert client.get(f"{API}/problems").status_code == 200
    app.state.ctx.stop()
