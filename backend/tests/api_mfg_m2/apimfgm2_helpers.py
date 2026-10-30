"""Helpers for tests/api_mfg_m2 (module name unique across backend/tests)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

V1 = "/api/v1"
MFG = f"{V1}/mfg"
PASSWORD = "correct horse battery staple"
A = "2026-11-02"


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def acc_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, auth_mode="accounts", password_hash_profile="fast",
                               auth_signin_limit_per_ip=1000, auth_signup_limit_per_ip=1000,
                               auth_signin_limit_per_email=1000, **overrides))


def sign_up(app: Any, email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{V1}/auth/sign-up", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def im(v: int) -> dict[str, str]:
    return {"If-Match": f'"{v}"'}


class Api:
    def __init__(self, c: TestClient, workspace: str | None = None):
        self.c = c
        self.ws = workspace

    def at(self, workspace: str | None) -> "Api":
        return Api(self.c, workspace)

    def req(self, method: str, path: str, status: int | None = None, headers: dict[str, str] | None = None,
            **kw: Any) -> Any:
        h = dict(headers or {})
        if self.ws:
            h["X-SP-Workspace"] = self.ws
        r = self.c.request(method, MFG + path, headers=h, **kw)
        if status is not None:
            assert r.status_code == status, (method, path, r.status_code, r.text[:3000])
        return r

    def get(self, path: str, status: int = 200, **params: Any) -> Any:
        return self.req("GET", path, status, params=params or None).json()

    def post(self, path: str, body: Any = None, status: int = 201, version: int | None = None,
             headers: dict[str, str] | None = None) -> Any:
        h = dict(headers or {})
        if version is not None:
            h.update(im(version))
        r = self.req("POST", path, status, json={} if body is None else body, headers=h)
        return r.json() if r.content else None

    def put(self, path: str, body: Any, version: int, status: int = 200) -> Any:
        return self.req("PUT", path, status, json=body, headers=im(version)).json()

    def delete(self, path: str, version: int | None = None, status: int = 204) -> Any:
        return self.req("DELETE", path, status, headers=im(version) if version is not None else {})

    def err(self, method: str, path: str, status: int, code: str, **kw: Any) -> dict[str, Any]:
        r = self.req(method, path, status, **kw)
        e = r.json()["error"]
        assert e["code"] == code, e
        return e

    # builders
    def item(self, pn: str, make_buy: str = "buy", **kw: Any) -> dict[str, Any]:
        body = {"part_number": pn, "make_buy": make_buy, **kw}
        if make_buy == "buy":
            body.setdefault("lead_time_days", 10)
        return self.post("/items", body)

    def location(self, code: str, kind: str = "stores", **kw: Any) -> dict[str, Any]:
        return self.post("/locations", {"code": code, "name": code, "kind": kind, **kw})

    def supplier(self, code: str, **kw: Any) -> dict[str, Any]:
        return self.post("/suppliers", {"code": code, "name": code, **kw})

    def receive(self, item_id: str, loc_id: str, qty: float, **kw: Any) -> dict[str, Any]:
        return self.post("/inventory/postings", {"type": "receipt_misc", "lines": [
            {"item_id": item_id, "location_id": loc_id, "qty": qty, **kw}]})

    def load(self, sample: str = "small", anchor: str | None = A, **kw: Any) -> dict[str, Any]:
        return self.post(f"/samples/{sample}/load", {"replace": False, "anchor": anchor, **kw}, status=200)

    def by_pn(self, pn: str) -> dict[str, Any]:
        items = self.get("/items", q=pn, limit=200)["items"]
        return next(i for i in items if i["part_number"] == pn)

    def doc(self, coll: str, number: str) -> dict[str, Any]:
        hit = [x for x in self.get(coll, q=number, limit=200)["items"] if x["number"] == number]
        assert len(hit) == 1, (coll, number)
        return self.get(f"{coll}/{hit[0]['id']}")
