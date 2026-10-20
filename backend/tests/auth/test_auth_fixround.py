"""Fix round regressions (accounts): malformed JSON vs auth order, bounded argon2 concurrency, no SQL parameters in
error logs, rate-limit rows of blocked clients, inline-mode pruning of auth tables. Both dialects."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from auth_helpers import API, AUTH, ORIGIN, PASSWORD, acc_app, error, second_client, sign_up

from superplanner.api.auth import passwords
from superplanner.api.auth.models import AuthRateLimitRow, UserSessionRow
from superplanner.api.config import Settings
from superplanner.api.db.ownership import system_scope
from superplanner.api.main import create_app

JSON = {"content-type": "application/json"}


# ---------------------------------------------------------------- malformed JSON: auth before body parsing

def test_malformed_json_anonymous_is_401(db_url):
    with TestClient(acc_app(db_url)) as c:
        error(c.post(f"{API}/problems", content=b"{not json", headers=JSON), 401, "AUTH_REQUIRED")
        error(c.put(f"{API}/problems/x", content=b"[", headers=JSON), 401, "AUTH_REQUIRED")
        error(c.post(f"{AUTH}/change-password", content=b"{", headers=JSON), 401, "AUTH_REQUIRED")
        # a forged cookie: 401 and the cookie is cleared, as for parseable bodies
        c.cookies.set("sp_session", "forged")
        r = c.post(f"{API}/problems", content=b"{not json", headers=JSON)
        error(r, 401, "AUTH_REQUIRED")
        assert "Max-Age=0" in r.headers.get("set-cookie", "")


def test_malformed_json_signed_in_without_csrf_is_403_and_with_csrf_422(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        token = c.headers.pop("X-CSRF-Token")
        error(c.post(f"{API}/problems", content=b"{not json", headers=JSON), 403, "CSRF_FAILED")
        error(c.post(f"{AUTH}/change-password", content=b"{", headers=JSON), 403, "CSRF_FAILED")
        r = c.post(f"{API}/problems", content=b"{not json", headers={**JSON, "X-CSRF-Token": token})
        err = error(r, 422, "VALIDATION_ERROR")
        assert err["details"]["errors"][0]["type"] == "json_invalid"


def test_malformed_json_on_public_auth_routes_checks_origin_first(db_url):
    with TestClient(acc_app(db_url)) as c:
        r = c.post(f"{AUTH}/sign-in", content=b"{", headers={**JSON, "Origin": "https://evil.example"})
        assert r.status_code == 403, r.text
        r = c.post(f"{AUTH}/sign-in", content=b"{", headers={**JSON, "Origin": ORIGIN})
        assert error(r, 422, "VALIDATION_ERROR")["details"]["errors"][0]["type"] == "json_invalid"


def test_malformed_json_single_user_is_still_422(db_url):
    app = create_app(Settings(database_url=db_url, auth_mode="single_user"))
    with TestClient(app) as c:
        r = c.post(f"{API}/problems", content=b"{not json", headers=JSON)
        assert error(r, 422, "VALIDATION_ERROR")["details"]["errors"][0]["type"] == "json_invalid"
        error(c.post(f"{AUTH}/sign-in", content=b"{", headers=JSON), 409, "AUTH_DISABLED")


# ---------------------------------------------------------------- bounded argon2 concurrency

class _SlowHasher:
    """Stands in for argon2: records how many hash operations run at the same time."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.active = 0
        self.peak = 0
        self.calls = 0
        self._lock = threading.Lock()

    def _work(self) -> None:
        with self._lock:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.seconds)
        with self._lock:
            self.active -= 1

    def hash(self, pw: str) -> str:
        self._work()
        return "$argon2id$v=19$m=8,t=1,p=1$fake$fake"

    def verify(self, h: str, pw: str) -> bool:
        self._work()
        return False

    def check_needs_rehash(self, h: str) -> bool:
        return False


@pytest.fixture
def slow_hasher(monkeypatch):
    fake = _SlowHasher(0.15)
    monkeypatch.setattr(passwords, "hasher", lambda profile="default": fake)
    monkeypatch.setattr(passwords, "dummy_hash", lambda profile="default": "$argon2id$dummy")
    yield fake
    passwords.configure_hash_slots(None, None)   # back to the process default


def test_hash_slots_bound_concurrency(slow_hasher):
    passwords.configure_hash_slots(2, 30.0)
    threads = [threading.Thread(target=passwords.verify_password, args=("h", "pw")) for _ in range(5)]
    threads += [threading.Thread(target=passwords.hash_password, args=("pw",)) for _ in range(2)]
    threads += [threading.Thread(target=passwords.verify_dummy, args=("pw",)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert slow_hasher.calls == 9 and slow_hasher.peak == 2


def test_hash_slots_full_raises_busy(slow_hasher):
    passwords.configure_hash_slots(1, 0.01)
    t = threading.Thread(target=passwords.verify_password, args=("h", "pw"))
    t.start()
    time.sleep(0.03)
    with pytest.raises(passwords.HashBusy):
        passwords.verify_password("h", "pw")
    t.join()


def test_default_slot_count():
    import os

    assert passwords.default_hash_concurrency() == max(1, (os.cpu_count() or 2) // 2)
    base = {"database_url": "sqlite:///unused.db", "job_backend": "inline"}
    assert Settings(**base, auth_hash_concurrency=0).hash_concurrency == passwords.default_hash_concurrency()
    assert Settings(**base, auth_hash_concurrency=3).hash_concurrency == 3


def test_concurrent_sign_ins_never_exceed_the_slots(db_url, slow_hasher):
    """N+1 (and more) concurrent sign-ins: at most N hashes at once; the overflow answers 429 with Retry-After."""
    app = acc_app(db_url, auth_hash_concurrency=2, auth_hash_wait_seconds=0.05)
    results: list[tuple[int, str | None, str]] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        r = second_client(app).post(f"{AUTH}/sign-in", json={"email": f"x{i}@example.com", "password": PASSWORD})
        with lock:
            results.append((r.status_code, r.headers.get("Retry-After"), r.json()["error"]["code"]))

    with TestClient(app):
        threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert slow_hasher.peak <= 2
    codes = sorted({(s, c) for s, _, c in results})
    assert set(codes) <= {(401, "INVALID_CREDENTIALS"), (429, "RATE_LIMITED")}, results
    busy = [r for r in results if r[0] == 429]
    assert busy, results          # 8 x 0.15 s on 2 slots with a 50 ms wait must overflow
    assert all(ra is not None and int(ra) >= 1 for _, ra, _ in busy)


def test_sign_up_and_change_password_use_the_slots(db_url, monkeypatch):
    calls: list[str] = []
    real = passwords._HashSlots.acquire

    def spy(self, *a, **k):
        calls.append("x")
        return real(self, *a, **k)

    monkeypatch.setattr(passwords._HashSlots, "acquire", spy)
    with TestClient(acc_app(db_url)) as c:
        sign_up(c, "ana@example.com")
        n = len(calls)
        assert n >= 1
        r = c.post(f"{AUTH}/change-password", json={"current_password": PASSWORD,
                                                     "new_password": "an entirely new secret"})
        assert r.status_code == 200, r.text
        assert len(calls) >= n + 2      # verify current + hash new


# ---------------------------------------------------------------- no SQL parameters in error logs

def _break_insert(app, table: str):
    """Rewrite `INSERT INTO <table>` into a statement on a missing table: a real driver error (both dialects)."""
    engine = app.state.ctx.db.engine

    def before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith(f"INSERT INTO {table.upper()} "):
            statement = statement.replace(f"INSERT INTO {table} ", f"INSERT INTO {table}_missing_x ", 1)
        return statement, parameters

    event.listen(engine, "before_cursor_execute", before, retval=True)


@pytest.mark.parametrize("table", ["users", "user_sessions"])
def test_db_error_during_sign_up_logs_no_bound_values(db_url, caplog, table, monkeypatch):
    import hashlib
    import secrets

    tokens: list[str] = []   # session cookie token and CSRF token (both secrets.token_urlsafe)
    real = secrets.token_urlsafe
    monkeypatch.setattr(secrets, "token_urlsafe", lambda *a: tokens.append(real(*a)) or tokens[-1])
    app = acc_app(db_url, password_hash_profile="fast")
    caplog.set_level(logging.DEBUG)
    with TestClient(app, raise_server_exceptions=False) as c:
        _break_insert(app, table)
        r = c.post(f"{AUTH}/sign-up", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 500, r.text
    text = caplog.text
    assert "unhandled error" in text and "missing_x" in text      # the error itself is still logged
    assert "$argon2" not in text and "ana@example.com" not in text
    assert "SQL parameters hidden" in text
    if table == "user_sessions":
        assert len(tokens) >= 2
    for t in tokens:
        assert t not in text and hashlib.sha256(t.encode()).hexdigest() not in text


def test_engines_hide_parameters(db_url):
    from superplanner import migrate
    from superplanner.api.db import Database

    db = Database(db_url)
    try:
        assert db.engine.hide_parameters is True
    finally:
        db.dispose()
    eng = migrate._migration_engine(db_url)
    try:
        assert eng.hide_parameters is True
    finally:
        eng.dispose()


# ---------------------------------------------------------------- rate-limit rows of blocked clients

def _bucket_count(app) -> int:
    with system_scope(), app.state.ctx.db.read() as s:
        return int(s.scalar(select(func.count()).select_from(AuthRateLimitRow)))


def test_blocked_ip_adds_no_email_buckets(db_url):
    app = acc_app(db_url, auth_signin_limit_per_ip=2)
    with TestClient(app) as c:
        codes = [c.post(f"{AUTH}/sign-in", json={"email": f"{uuid.uuid4().hex[:10]}@example.com",
                                                  "password": PASSWORD}).status_code for _ in range(50)]
        assert codes.count(401) == 2 and codes.count(429) == 48
        assert _bucket_count(app) == 3      # 1 IP bucket + the 2 allowed emails (was 51)


def test_hit_all_stops_at_the_first_denying_bucket(db_url):
    from superplanner.api.auth import ratelimit

    app = acc_app(db_url)
    with TestClient(app):
        ctx = app.state.ctx
        w = timedelta(minutes=5)
        with system_scope(), ctx.db.write() as s:
            assert ratelimit.hit_all(s, [("a", 1, w), ("b", 5, w)]) == (True, 0)
            ok, retry = ratelimit.hit_all(s, [("a", 1, w), ("c", 5, w)])
            assert not ok and retry >= 1
        with system_scope(), ctx.db.read() as s:
            assert set(s.scalars(select(AuthRateLimitRow.bucket))) == {"a", "b"}


# ---------------------------------------------------------------- inline-mode pruning

def test_inline_mode_prunes_auth_tables_periodically(db_url):
    app = acc_app(db_url, job_backend="inline", auth_prune_interval_seconds=0.2)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        ctx = app.state.ctx
        old = datetime.now(UTC) - timedelta(hours=3)
        with system_scope(), ctx.db.write() as s:
            for i in range(5):
                s.add(AuthRateLimitRow(bucket=f"signin:email:old{i}", window_start=old, count=1))
            s.add(AuthRateLimitRow(bucket="signin:email:fresh", window_start=datetime.now(UTC), count=1))
            uid = s.scalar(select(UserSessionRow.user_id))
            s.add(UserSessionRow(**_expired_session_fields(uid)))
        deadline = time.monotonic() + 10
        while True:
            with system_scope(), ctx.db.read() as s:
                buckets = set(s.scalars(select(AuthRateLimitRow.bucket)))
                expired = s.scalar(select(func.count()).select_from(UserSessionRow)
                                   .where(UserSessionRow.id == "ses_expired_x"))
            if not any(b.startswith("signin:email:old") for b in buckets) and not expired:
                break
            assert time.monotonic() < deadline, buckets
            time.sleep(0.05)
        assert "signin:email:fresh" in buckets
        assert c.get(f"{AUTH}/session").json()["authenticated"] is True   # live session untouched


def _expired_session_fields(user_id: str) -> dict:
    now = datetime.now(UTC)
    cols = {c.name for c in UserSessionRow.__table__.columns}
    fields = {"id": "ses_expired_x", "user_id": user_id, "token_hash": "0" * 64, "csrf_token": "x" * 43,
              "created_at": now - timedelta(days=40), "expires_at": now - timedelta(days=10),
              "last_seen_at": now - timedelta(days=10)}
    for opt in ("user_agent", "ip"):
        if opt in cols:
            fields[opt] = None
    return {k: v for k, v in fields.items() if k in cols}


def test_prune_thread_stops_with_the_app(db_url):
    app = acc_app(db_url, job_backend="inline", auth_prune_interval_seconds=0.1)
    with TestClient(app):
        assert any(t.name == "sp-auth-prune" for t in threading.enumerate())
    time.sleep(0.3)
    ctx = app.state.ctx
    assert ctx._prune_thread is None


# ---------------------------------------------------------------- final fix round (main loop)

def test_cold_dummy_hash_is_computed_once_inside_the_slots(monkeypatch):
    """A burst of unknown-email sign-ins right after start must not run one unbounded hash per thread."""
    fake = _SlowHasher(0.1)
    monkeypatch.setattr(passwords, "hasher", lambda profile="default": fake)
    monkeypatch.setattr(passwords, "_dummy_hashes", {})
    passwords.configure_hash_slots(2, 30.0)
    try:
        threads = [threading.Thread(target=passwords.verify_dummy, args=("x" * 12,)) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        passwords.configure_hash_slots(None, None)
    assert fake.peak <= 2
    assert fake.calls == 21   # one dummy hash + 20 verifications


def test_accounts_app_warms_the_dummy_hash(db_url, monkeypatch):
    monkeypatch.setattr(passwords, "_dummy_hashes", {})
    acc_app(db_url)
    assert passwords._dummy_hashes   # computed at start, before any request


def test_undecodable_body_anonymous_is_401_and_without_csrf_is_403(db_url):
    bad = b'{"name":"\xff\xfe"}'
    with TestClient(acc_app(db_url)) as c:
        error(c.post(f"{API}/problems", content=bad, headers=JSON), 401, "AUTH_REQUIRED")
        sign_up(c, "ana@example.com")
        token = c.headers.pop("X-CSRF-Token")
        error(c.post(f"{API}/problems", content=bad, headers=JSON), 403, "CSRF_FAILED")
        r = c.post(f"{API}/problems", content=bad, headers={**JSON, "X-CSRF-Token": token})
        assert r.status_code == 400, r.text   # signed in with CSRF: the original parse error stands
