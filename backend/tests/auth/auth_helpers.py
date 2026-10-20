"""Helpers for the accounts tests: an accounts-mode app and signed-in clients (one cookie jar per user)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

API = "/api/v1"
AUTH = f"{API}/auth"
PASSWORD = "correct horse battery"
ORIGIN = "http://127.0.0.1:5173"     # dev default PUBLIC_BASE_URL


def acc_app(db_url: str, **overrides: Any):
    overrides.setdefault("auth_mode", "accounts")
    overrides.setdefault("password_hash_profile", "fast")
    return create_app(Settings(database_url=db_url, **overrides))


def sign_up(c: TestClient, email: str, password: str = PASSWORD, name: str | None = None) -> dict[str, Any]:
    """Sign up and make the client send the session's CSRF token on every request."""
    body: dict[str, Any] = {"email": email, "password": password}
    if name:
        body["display_name"] = name
    r = c.post(f"{AUTH}/sign-up", json=body)
    assert r.status_code == 201, r.text
    info = r.json()
    c.headers["X-CSRF-Token"] = info["csrf_token"]
    return info


def sign_in(c: TestClient, email: str, password: str = PASSWORD) -> dict[str, Any]:
    r = c.post(f"{AUTH}/sign-in", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    info = r.json()
    c.headers["X-CSRF-Token"] = info["csrf_token"]
    return info


def second_client(app, **kw: Any) -> TestClient:
    """Another browser (own cookie jar) on an app whose context is already started by a `with TestClient`."""
    return TestClient(app, **kw)


def error(resp, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, (resp.status_code, resp.text)
    body = resp.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}, body
    assert body["error"]["code"] == code, body
    return body["error"]


def set_cookies(resp) -> list[str]:
    return resp.headers.get_list("set-cookie")
