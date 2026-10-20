"""Q3-11 logs never contain a password, session token or CSRF token."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from auth_helpers import API, AUTH, PASSWORD, acc_app

NEW_PASSWORD = "an entirely new secret"


def test_no_secrets_in_logs(db_url, caplog):
    caplog.set_level(logging.DEBUG)
    secrets: list[str] = [PASSWORD, NEW_PASSWORD, "wrong password value"]
    with TestClient(acc_app(db_url, auth_signin_limit_per_email=3)) as c:
        r = c.post(f"{AUTH}/sign-up", json={"email": "ana@example.com", "password": PASSWORD, "display_name": "A"})
        secrets += [r.json()["csrf_token"], c.cookies.get("sp_session")]
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        c.post(f"{AUTH}/sign-up", json={"email": "bad", "password": PASSWORD})                    # 422
        c.post(f"{AUTH}/sign-up", json={"email": "ana@example.com", "password": PASSWORD})        # 409
        c.post(f"{AUTH}/sign-up", json={"email": "x@example.com", "password": "password123"})     # weak
        c.get(f"{API}/problems")
        c.post(f"{API}/templates/manufacturing/instantiate", json={})
        c.post(f"{API}/problems", json={"bad": "body"})                                             # 422
        r = c.post(f"{AUTH}/change-password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
        secrets += [r.json()["csrf_token"], c.cookies.get("sp_session")]
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        c.post(f"{AUTH}/sign-out")
        for _ in range(4):
            c.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": "wrong password value"})
        r = TestClient(c.app).post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": NEW_PASSWORD})
    text = "\n".join(f"{rec.getMessage()} {rec.args!r} {rec.exc_text or ''}" for rec in caplog.records)
    assert caplog.records, "expected some log output"
    for secret in secrets:
        assert secret and secret not in text, f"secret leaked into logs: {secret[:6]}..."
