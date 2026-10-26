"""Helpers for tests/api_mfg: app factory, a thin API wrapper, a SQL statement counter, row counts."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from superplanner.api.config import Settings
from superplanner.api.db.ownership import system_scope
from superplanner.api.main import create_app
from superplanner.api.mfg.db_models import MFG_MODELS
from superplanner.mfg import model as mm

API = "/api/v1"
MFG = f"{API}/mfg"
PASSWORD = "correct horse battery staple"


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def acc_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, auth_mode="accounts", password_hash_profile="fast",
                               auth_signin_limit_per_ip=1000, auth_signup_limit_per_ip=1000,
                               auth_signin_limit_per_email=1000, **overrides))


def sign_up(app: Any, email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/sign-up", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def err(r: Any, status: int, code: str) -> dict[str, Any]:
    assert r.status_code == status, (r.status_code, r.text)
    e = r.json()["error"]
    assert e["code"] == code, e
    return e


def etag(v: int) -> dict[str, str]:
    return {"If-Match": f'"{v}"'}


def to_input(cls: Any, rec: dict[str, Any]) -> dict[str, Any]:
    nested = {"lines": mm.BomLineInput, "operations": mm.OperationInput, "tools": mm.OperationToolInput}
    out: dict[str, Any] = {}
    for f in cls.model_fields:
        v = rec.get(f)
        if f in nested and isinstance(v, list):
            v = [to_input(nested[f], x) for x in v]
        out[f] = copy.deepcopy(v)
    return out


class Mfg:
    """`c.get/post/...` against /api/v1/mfg with status assertions."""

    def __init__(self, c: TestClient):
        self.c = c

    def req(self, method: str, path: str, status: int | None = None, **kw: Any) -> Any:
        r = self.c.request(method, MFG + path, **kw)
        if status is not None:
            assert r.status_code == status, (method, path, r.status_code, r.text[:2000])
        return r

    def get(self, path: str, status: int = 200, **kw: Any) -> Any:
        return self.req("GET", path, status, **kw).json()

    def post(self, path: str, body: Any = None, status: int = 201, **kw: Any) -> Any:
        r = self.req("POST", path, status, json=body if body is not None else {}, **kw)
        return r.json() if r.content else None

    def put(self, path: str, body: Any, version: int, status: int = 200) -> Any:
        return self.req("PUT", path, status, json=body, headers=etag(version)).json()

    def delete(self, path: str, version: int | None = None, status: int = 204) -> Any:
        return self.req("DELETE", path, status, headers=etag(version) if version is not None else {})

    # convenience builders
    def item(self, pn: str, make_buy: str = "buy", **kw: Any) -> dict[str, Any]:
        body = {"part_number": pn, "make_buy": make_buy, **kw}
        if make_buy == "buy":
            body.setdefault("lead_time_days", 10)
        return self.post("/items", body)

    def group(self, code: str, **kw: Any) -> dict[str, Any]:
        return self.post("/groups", {"code": code, "name": f"Stage {code}", **kw})

    def line(self, code: str, group_id: str, **kw: Any) -> dict[str, Any]:
        return self.post("/lines", {"code": code, "name": f"Line {code}", "group_id": group_id, **kw})

    def load(self, sample: str = "small", replace: bool = False) -> dict[str, Any]:
        return self.post(f"/samples/{sample}/load", {"replace": replace}, status=200)

    def by_pn(self, pn: str) -> dict[str, Any]:
        items = self.get("/items", params={"q": pn, "limit": 200})["items"]
        return next(i for i in items if i["part_number"] == pn)


def row_counts(app: Any) -> dict[str, int]:
    db = app.state.ctx.db
    out = {}
    with system_scope(), db.read() as s:
        for m in MFG_MODELS:
            out[m.__tablename__] = int(s.execute(select(func.count()).select_from(m)).scalar() or 0)
    return out


@contextmanager
def count_statements(app: Any) -> Iterator[list[str]]:
    """Statements executed on the app's engine while inside the block (BEGIN/COMMIT/ROLLBACK/SAVEPOINT excluded)."""
    engine = app.state.ctx.db.engine
    seen: list[str] = []

    def on(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
        head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
        if head not in ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "PRAGMA"):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", on)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", on)
