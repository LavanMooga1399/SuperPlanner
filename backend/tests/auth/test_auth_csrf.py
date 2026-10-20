"""Q3-4 CSRF token and Origin checks (PHASE2B 4.4)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from auth_helpers import API, AUTH, ORIGIN, PASSWORD, acc_app, error, sign_up
from route_table import PROTECTED, UNSAFE, fill_path


def test_every_unsafe_protected_route_needs_the_token(db_url):
    with TestClient(acc_app(db_url)) as c:
        token = sign_up(c, "ana@example.com")["csrf_token"]
        del c.headers["X-CSRF-Token"]
        for method, path in sorted(PROTECTED):
            if method not in UNSAFE:
                continue
            url = API + fill_path(path)
            error(c.request(method, url, json={}), 403, "CSRF_FAILED")
            error(c.request(method, url, json={}, headers={"X-CSRF-Token": "wrong-" + token[:10]}), 403,
                  "CSRF_FAILED")
            # foreign Origin -> 403 even with the right token
            error(c.request(method, url, json={}, headers={"X-CSRF-Token": token,
                                                           "Origin": "https://evil.example"}), 403, "CSRF_FAILED")
            error(c.request(method, url, json={}, headers={"X-CSRF-Token": token, "Origin": "null"}), 403,
                  "CSRF_FAILED")


def test_valid_token_and_allowed_origins_pass(db_url):
    with TestClient(acc_app(db_url)) as c:
        token = sign_up(c, "ana@example.com")["csrf_token"]
        url = f"{API}/templates/manufacturing/instantiate"
        assert c.post(url, json={}).status_code == 201
        for origin in (ORIGIN, "http://localhost:5173", "HTTP://LOCALHOST:5173"):
            assert c.post(url, json={}, headers={"Origin": origin, "X-CSRF-Token": token}).status_code == 201


def test_safe_methods_and_sse_need_no_token(db_url):
    with TestClient(acc_app(db_url)) as c:
        sign_up(c, "ana@example.com")
        pid = c.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}}).json()["id"]
        rid = c.post(f"{API}/problems/{pid}/solver-runs",
                     json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        del c.headers["X-CSRF-Token"]
        hdr = {"Origin": "https://evil.example"}   # Origin is only checked on unsafe methods
        assert c.get(f"{API}/problems", headers=hdr).status_code == 200
        assert c.get(f"{API}/problems/{pid}").status_code == 200
        r = c.get(f"{API}/solver-runs/{rid}/events")    # SSE stream (ends at the terminal event)
        assert r.status_code in (200, 204)
        assert c.get(f"{API}/solver-runs/{rid}/events?stream=false").status_code == 200


def test_sign_in_and_sign_up_origin_check(db_url):
    with TestClient(acc_app(db_url, cors_origins=["https://app.example"],
                            public_base_url="https://planner.example")) as c:
        evil = {"Origin": "https://evil.example"}
        body = {"email": "ana@example.com", "password": PASSWORD}
        error(c.post(f"{AUTH}/sign-up", json=body, headers=evil), 403, "CSRF_FAILED")
        error(c.post(f"{AUTH}/sign-in", json=body, headers=evil), 403, "CSRF_FAILED")
        error(c.post(f"{AUTH}/sign-up", json={}, headers=evil), 403, "CSRF_FAILED")   # before body validation
        # the dev localhost origins are not allowed once CORS_ORIGINS is explicit
        error(c.post(f"{AUTH}/sign-up", json=body, headers={"Origin": ORIGIN}), 403, "CSRF_FAILED")
        assert c.post(f"{AUTH}/sign-up", json=body,
                      headers={"Origin": "https://planner.example"}).status_code == 201
        assert c.post(f"{AUTH}/sign-in", json=body, headers={"Origin": "https://app.example"}).status_code == 200
