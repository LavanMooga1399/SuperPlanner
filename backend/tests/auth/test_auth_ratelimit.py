"""Q3-8 DB-backed rate limits (PHASE2B 4.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from auth_helpers import AUTH, PASSWORD, acc_app, error, sign_up

from superplanner.api.auth import passwords, ratelimit
from superplanner.api.auth.models import AuthRateLimitRow


def _signin(c, email="ana@example.com", password="wrong password!!"):
    return c.post(f"{AUTH}/sign-in", json={"email": email, "password": password})


def test_eleventh_signin_for_one_email_is_429(db_url):
    with TestClient(acc_app(db_url)) as c:
        for _ in range(10):
            error(_signin(c), 401, "INVALID_CREDENTIALS")
        r = _signin(c)
        err = error(r, 429, "RATE_LIMITED")
        retry = int(r.headers["Retry-After"])
        assert 1 <= retry <= 300 and err["details"] == {"retry_after_seconds": retry}
        # even the right password is refused now (counted before verification); another email is fine
        error(_signin(c, password=PASSWORD), 429, "RATE_LIMITED")
        error(_signin(c, email="other@example.com"), 401, "INVALID_CREDENTIALS")


def test_counted_before_password_verification(db_url, monkeypatch):
    calls: list[int] = []
    real = passwords.verify_password
    monkeypatch.setattr(passwords, "verify_password", lambda *a, **k: calls.append(1) or real(*a, **k))
    with TestClient(acc_app(db_url, auth_signin_limit_per_email=2)) as c:
        _signin(c), _signin(c)
        n = len(calls)
        error(_signin(c), 429, "RATE_LIMITED")
        assert len(calls) == n      # no hash verified for a rejected attempt


def test_shared_across_two_app_instances(db_url):
    a1, a2 = acc_app(db_url), acc_app(db_url)
    with TestClient(a1) as c1, TestClient(a2) as c2:
        for i in range(10):
            error(_signin(c1 if i % 2 else c2), 401, "INVALID_CREDENTIALS")
        error(_signin(c1), 429, "RATE_LIMITED")
        error(_signin(c2), 429, "RATE_LIMITED")


def test_per_ip_signin_and_signup_limits(db_url, db_url_factory):
    with TestClient(acc_app(db_url, auth_signin_limit_per_ip=3)) as c:
        for i in range(3):
            error(_signin(c, email=f"u{i}@example.com"), 401, "INVALID_CREDENTIALS")
        error(_signin(c, email="u9@example.com"), 429, "RATE_LIMITED")
    with TestClient(acc_app(db_url_factory("su"), auth_signup_limit_per_ip=2)) as c:
        sign_up(c, "a1@example.com")
        sign_up(c, "a2@example.com")
        r = c.post(f"{AUTH}/sign-up", json={"email": "a3@example.com", "password": PASSWORD})
        error(r, 429, "RATE_LIMITED")
        assert 3000 < int(r.headers["Retry-After"]) <= 3600


def test_change_password_limit(db_url):
    with TestClient(acc_app(db_url, auth_change_password_limit_per_user=2)) as c:
        sign_up(c, "ana@example.com")
        body = {"current_password": "not it at all", "new_password": "a brand new secret"}
        for _ in range(2):
            error(c.post(f"{AUTH}/change-password", json=body), 422, "WRONG_PASSWORD")
        error(c.post(f"{AUTH}/change-password", json=body), 429, "RATE_LIMITED")


def test_disabled_rate_limit(db_url):
    with TestClient(acc_app(db_url, auth_rate_limit_enabled=False, auth_signin_limit_per_email=1)) as c:
        for _ in range(4):
            error(_signin(c), 401, "INVALID_CREDENTIALS")


def test_hit_window_rolls_over(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        db = app.state.ctx.db
        t0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
        w = timedelta(minutes=5)
        with db.write() as s:
            assert ratelimit.hit(s, "b", 2, w, t0) == (True, 0)
            assert ratelimit.hit(s, "b", 2, w, t0 + timedelta(seconds=10)) == (True, 0)
            assert ratelimit.hit(s, "b", 2, w, t0 + timedelta(seconds=20)) == (False, 280)
        with db.write() as s:   # window over: counting restarts
            assert ratelimit.hit(s, "b", 2, w, t0 + timedelta(minutes=5, seconds=1)) == (True, 0)
        with db.read() as s:
            row = s.scalar(select(AuthRateLimitRow).where(AuthRateLimitRow.bucket == "b"))
            assert row.count == 1


def test_concurrent_hits_count_exactly(db_url):
    from concurrent.futures import ThreadPoolExecutor

    app = acc_app(db_url)
    with TestClient(app):
        db = app.state.ctx.db

        def one(_: int) -> bool:
            with db.write() as s:
                return ratelimit.hit(s, "conc", 25, timedelta(minutes=5))[0]

        with ThreadPoolExecutor(8) as ex:
            results = list(ex.map(one, range(40)))
        assert results.count(True) == 25
        with db.read() as s:
            assert s.scalar(select(AuthRateLimitRow.count).where(AuthRateLimitRow.bucket == "conc")) == 40


def test_concurrent_signups_same_email(db_url):
    from concurrent.futures import ThreadPoolExecutor

    app = acc_app(db_url, auth_signup_limit_per_ip=100)
    with TestClient(app):
        def one(_: int) -> int:
            return TestClient(app).post(f"{AUTH}/sign-up", json={"email": "race@example.com",
                                                                 "password": PASSWORD}).status_code

        with ThreadPoolExecutor(6) as ex:
            codes = sorted(ex.map(one, range(6)))
        assert codes == [201] + [409] * 5, codes
