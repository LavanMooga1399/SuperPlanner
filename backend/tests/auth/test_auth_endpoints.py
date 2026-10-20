"""Q3-1 / Q3-2: the five auth endpoints (PHASE2B 4.5) in both modes, cookie attributes."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from auth_helpers import AUTH, API, PASSWORD, acc_app, error, second_client, set_cookies, sign_in, sign_up

from superplanner.api.config import Settings
from superplanner.api.main import create_app


# ---------------------------------------------------------------- single_user (Q3-1)

def test_single_user_session_body_and_disabled_mutations(db_url):
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        r = c.get(f"{AUTH}/session")
        assert r.status_code == 200
        body = r.json()
        created = body["user"].pop("created_at")
        assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$", created), created
        assert body == {"auth_mode": "single_user", "authenticated": True,
                        "user": {"id": "usr_local", "email": None, "display_name": "Local user", "is_local": True},
                        "csrf_token": None, "expires_at": None, "signup_enabled": False}
        assert "set-cookie" not in r.headers
        for path, payload in (("sign-up", {"email": "a@b.co", "password": PASSWORD}),
                              ("sign-in", {"email": "a@b.co", "password": PASSWORD}),
                              ("sign-out", None), ("change-password", {"current_password": "x", "new_password": "y"}),
                              ("sign-in", {}), ("sign-up", {"bad": 1})):
            err = error(c.post(f"{AUTH}/{path}", json=payload), 409, "AUTH_DISABLED")
            assert err["details"] == {}
        # data routes need no cookie or CSRF token
        assert c.get(f"{API}/problems").status_code == 200
        assert c.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}}).status_code == 201


# ---------------------------------------------------------------- accounts: session

def test_anonymous_session_and_invalid_cookie_cleared(db_url):
    with TestClient(acc_app(db_url)) as c:
        anon = {"auth_mode": "accounts", "authenticated": False, "user": None, "csrf_token": None,
                "expires_at": None, "signup_enabled": True}
        r = c.get(f"{AUTH}/session")
        assert r.status_code == 200 and r.json() == anon
        assert "set-cookie" not in r.headers
        c.cookies.set("sp_session", "forged-token")
        r = c.get(f"{AUTH}/session")
        assert r.json() == anon
        cookie = set_cookies(r)[0]
        assert cookie.startswith("sp_session=") and "Max-Age=0" in cookie


def test_signup_signin_session_signout_flow(db_url):
    with TestClient(acc_app(db_url)) as c:
        r = c.post(f"{AUTH}/sign-up", json={"email": "  Ana@Example.COM ", "password": PASSWORD,
                                             "display_name": "Ana"})
        assert r.status_code == 201, r.text
        info = r.json()
        assert set(info) == {"auth_mode", "authenticated", "user", "csrf_token", "expires_at", "signup_enabled"}
        assert info["auth_mode"] == "accounts" and info["authenticated"] is True and info["signup_enabled"] is True
        user = info["user"]
        assert set(user) == {"id", "email", "display_name", "is_local", "created_at"}
        assert user["id"].startswith("usr_") and user["email"] == "ana@example.com"
        assert user["display_name"] == "Ana" and user["is_local"] is False
        assert info["csrf_token"] and info["expires_at"].endswith("Z")
        (cookie,) = set_cookies(r)
        attrs = [a.strip() for a in cookie.split(";")]
        assert attrs[0].startswith("sp_session=") and len(attrs[0]) > 40
        assert "HttpOnly" in attrs and "Path=/" in attrs and "SameSite=Lax" in attrs
        assert not any(a.lower().startswith("domain") for a in attrs) and "Secure" not in attrs
        max_age = int(next(a for a in attrs if a.startswith("Max-Age=")).split("=")[1])
        assert 30 * 86400 - 60 <= max_age <= 30 * 86400

        s = c.get(f"{AUTH}/session").json()
        assert s == info
        c.headers["X-CSRF-Token"] = info["csrf_token"]
        assert c.get(f"{API}/problems").status_code == 200

        r = c.post(f"{AUTH}/sign-out")
        assert r.status_code == 204 and r.content == b""
        assert "Max-Age=0" in set_cookies(r)[0]
        assert c.get(f"{AUTH}/session").json()["authenticated"] is False
        error(c.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
        # idempotent without a session
        assert c.post(f"{AUTH}/sign-out").status_code == 204

        info2 = sign_in(c, "ANA@example.com")
        assert info2["user"] == user and info2["csrf_token"] != info["csrf_token"]
        assert c.get(f"{API}/problems").status_code == 200


def test_secure_cookie_uses_host_prefix(db_url):
    app = acc_app(db_url, cookie_secure=True)
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post(f"{AUTH}/sign-up", json={"email": "s@example.com", "password": PASSWORD})
        assert r.status_code == 201
        attrs = [a.strip() for a in set_cookies(r)[0].split(";")]
        assert attrs[0].startswith("__Host-sp_session=")
        assert "Secure" in attrs and "Path=/" in attrs and "HttpOnly" in attrs and "SameSite=Lax" in attrs
        assert not any(a.lower().startswith("domain") for a in attrs)
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        assert c.get(f"{API}/problems").status_code == 200
        assert c.get(f"{AUTH}/session").json()["authenticated"] is True
        # the plain-name cookie is not accepted when COOKIE_SECURE=true
        token = c.cookies.get("__Host-sp_session")
        other = second_client(app, base_url="https://testserver")
        other.cookies.set("sp_session", token)
        error(other.get(f"{API}/problems"), 401, "AUTH_REQUIRED")


# ---------------------------------------------------------------- accounts: errors

@pytest.mark.parametrize("email", ["no-at-sign", "a@b", "a b@c.de", "@x.io", "x@.", "a" * 250 + "@x.io", ""])
def test_signup_bad_email_is_validation_error(db_url, email):
    with TestClient(acc_app(db_url)) as c:
        err = error(c.post(f"{AUTH}/sign-up", json={"email": email, "password": PASSWORD}), 422, "VALIDATION_ERROR")
        assert err["details"]["errors"][0]["loc"] == ["body", "email"]


def test_signup_and_signin_body_errors(db_url):
    with TestClient(acc_app(db_url)) as c:
        error(c.post(f"{AUTH}/sign-up", json={"email": "a@b.co", "password": PASSWORD, "extra": 1}), 422,
              "VALIDATION_ERROR")
        error(c.post(f"{AUTH}/sign-up", json={"email": "a@b.co", "password": PASSWORD, "display_name": ""}),
              422, "VALIDATION_ERROR")
        error(c.post(f"{AUTH}/sign-up", json={"email": "a@b.co", "password": PASSWORD,
                                               "display_name": "x" * 101}), 422, "VALIDATION_ERROR")
        error(c.post(f"{AUTH}/sign-in", json={"email": "a@b.co"}), 422, "VALIDATION_ERROR")
        error(c.post(f"{AUTH}/sign-in", json={"email": "a@b.co", "password": "x", "remember": True}), 422,
              "VALIDATION_ERROR")


@pytest.mark.parametrize("password,reasons", [
    ("short", ["too_short"]),
    ("x" * 257, ["too_long"]),
    ("password123", ["common"]),
    ("Password123", ["common"]),
    ("weak@example.com", ["same_as_email"]),
])
def test_signup_weak_password(db_url, password, reasons):
    with TestClient(acc_app(db_url)) as c:
        err = error(c.post(f"{AUTH}/sign-up", json={"email": "weak@example.com", "password": password}), 422,
                    "WEAK_PASSWORD")
        assert err["details"] == {"reasons": reasons}


def test_signup_email_taken_and_disabled(db_url, db_url_factory):
    with TestClient(acc_app(db_url)) as c:
        sign_up(c, "taken@example.com")
        other = TestClient(c.app)
        error(other.post(f"{AUTH}/sign-up", json={"email": "TAKEN@example.com", "password": PASSWORD + "!"}), 409,
              "EMAIL_TAKEN")
    with TestClient(acc_app(db_url_factory("nosignup"), signup_enabled=False)) as c:
        assert c.get(f"{AUTH}/session").json()["signup_enabled"] is False
        error(c.post(f"{AUTH}/sign-up", json={"email": "x@example.com", "password": PASSWORD}), 403,
              "SIGNUP_DISABLED")


def test_signin_invalid_credentials_same_for_all_cases(db_url):
    with TestClient(acc_app(db_url)) as c:
        sign_up(c, "ana@example.com")
        c.post(f"{AUTH}/sign-out")
        bodies = [{"email": "ana@example.com", "password": "wrong password here"},
                  {"email": "nobody@example.com", "password": PASSWORD}]
        errs = [error(c.post(f"{AUTH}/sign-in", json=b), 401, "INVALID_CREDENTIALS") for b in bodies]
        assert errs[0] == errs[1] == {"code": "INVALID_CREDENTIALS",
                                      "message": "The email or password is not correct.", "details": {}}


def test_signin_replaces_existing_session(db_url):
    with TestClient(acc_app(db_url)) as c:
        sign_up(c, "ana@example.com")
        old_token = c.cookies.get("sp_session")
        sign_in(c, "ana@example.com")
        new_token = c.cookies.get("sp_session")
        assert new_token != old_token
        stale = TestClient(c.app)
        stale.cookies.set("sp_session", old_token)
        error(stale.get(f"{API}/problems"), 401, "AUTH_REQUIRED")   # the previous session was revoked
        assert c.get(f"{API}/problems").status_code == 200


def test_change_password(db_url):
    app = acc_app(db_url)
    with TestClient(app) as a1:
        info = sign_up(a1, "ana@example.com")
        a2 = second_client(app)
        sign_in(a2, "ana@example.com")
        old_cookie = a1.cookies.get("sp_session")

        err = error(a1.post(f"{AUTH}/change-password", json={"current_password": "not it at all",
                                                             "new_password": "a brand new secret"}), 422,
                    "WRONG_PASSWORD")
        assert err["details"] == {}
        err = error(a1.post(f"{AUTH}/change-password", json={"current_password": PASSWORD,
                                                             "new_password": "short"}), 422, "WEAK_PASSWORD")
        assert err["details"] == {"reasons": ["too_short"]}

        r = a1.post(f"{AUTH}/change-password", json={"current_password": PASSWORD,
                                                     "new_password": "a brand new secret"})
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["authenticated"] is True and new["user"] == info["user"]
        assert new["csrf_token"] != info["csrf_token"]
        assert a1.cookies.get("sp_session") != old_cookie and set_cookies(r)[0].startswith("sp_session=")
        # the old token in a1's header is now wrong: unsafe requests fail, safe ones work
        error(a1.post(f"{API}/templates/manufacturing/instantiate", json={}), 403, "CSRF_FAILED")
        a1.headers["X-CSRF-Token"] = new["csrf_token"]
        assert a1.post(f"{API}/templates/manufacturing/instantiate", json={}).status_code == 201
        # other sessions are revoked, the old cookie too
        error(a2.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
        stale = second_client(app)
        stale.cookies.set("sp_session", old_cookie)
        error(stale.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
        # old password fails, new one works
        fresh = second_client(app)
        error(fresh.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": PASSWORD}), 401,
              "INVALID_CREDENTIALS")
        sign_in(fresh, "ana@example.com", "a brand new secret")


def test_change_password_requires_session_and_csrf(db_url):
    with TestClient(acc_app(db_url)) as c:
        body = {"current_password": PASSWORD, "new_password": "a brand new secret"}
        error(c.post(f"{AUTH}/change-password", json=body), 401, "AUTH_REQUIRED")
        error(c.post(f"{AUTH}/change-password", json={}), 401, "AUTH_REQUIRED")   # 401 before body validation
        sign_up(c, "ana@example.com")
        token = c.headers.pop("X-CSRF-Token")
        error(c.post(f"{AUTH}/change-password", json=body), 403, "CSRF_FAILED")
        error(c.post(f"{AUTH}/change-password", json=body, headers={"X-CSRF-Token": "wrong"}), 403, "CSRF_FAILED")
        error(c.post(f"{AUTH}/sign-out"), 403, "CSRF_FAILED")   # valid session + missing token
        assert c.post(f"{AUTH}/sign-out", headers={"X-CSRF-Token": token}).status_code == 204


def test_local_user_cannot_sign_in(db_url):
    with TestClient(acc_app(db_url)) as c:
        for email in ("usr_local", "local@localhost.local"):
            r = c.post(f"{AUTH}/sign-in", json={"email": email, "password": PASSWORD})
            assert r.status_code in (401, 422)
