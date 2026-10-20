"""Ownership enforcement at the ORM layer (PHASE2B 4.7; Q1-9) and the single_user `require_user`."""

from __future__ import annotations

import inspect
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, exists, func, select, update

from db_helpers import make_app
from superplanner.api.auth.deps import require_user
from superplanner.api.auth.models import UserRow
from superplanner.api.db import AuditEventRow, JobRow, ProblemRow, utcnow
from superplanner.api.db.ownership import (SYSTEM, OwnershipViolation, current_owner, owner_scope, request_scope,
                                           system_scope)
from superplanner.api.finance.db_models import FinancePlanRow

API = "/api/v1"


def _seed(client: TestClient) -> tuple[str, str]:
    """usr_local creates one problem and one finance plan through the API; user B exists."""
    pid = client.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}}).json()["id"]
    fid = client.post(f"{API}/finance/templates/young_professional/instantiate",
                      json={"start_month": "2026-11"}).json()["id"]
    with client.app.state.ctx.db.write() as s:
        s.add(UserRow(id="usr_b", email="b@example.com", display_name="B", is_local=False, disabled=False,
                      created_at=utcnow(), updated_at=utcnow()))
    return pid, fid


@pytest.fixture
def app_client(db_url):
    with TestClient(make_app(db_url)) as c:
        yield c


def test_rows_are_owned_by_usr_local_in_single_user(app_client):
    pid, fid = _seed(app_client)
    db = app_client.app.state.ctx.db
    with db.read() as s:
        assert s.get(ProblemRow, pid).owner_id == "usr_local"
        assert s.get(FinancePlanRow, fid).owner_id == "usr_local"
        actors = set(s.scalars(select(AuditEventRow.actor_id)).all())
        assert actors == {"usr_local"}


def test_other_user_sees_and_changes_nothing(app_client):
    pid, fid = _seed(app_client)
    db = app_client.app.state.ctx.db
    with owner_scope("usr_b"):
        assert current_owner() == "usr_b"
        with db.read() as s:
            assert s.get(ProblemRow, pid) is None                                   # Session.get
            assert s.scalars(select(ProblemRow)).all() == []                        # select(Model)
            assert s.scalars(select(ProblemRow.id)).all() == []                     # column-only select
            assert s.scalar(select(func.count()).select_from(ProblemRow)) == 0     # count
            assert s.scalar(select(exists().where(ProblemRow.id == pid))) is False  # exists()
            assert s.get(FinancePlanRow, fid) is None
            assert s.scalars(select(FinancePlanRow.name)).all() == []
        with db.write() as s:
            r = s.execute(update(ProblemRow).where(ProblemRow.id == pid).values(name="hijacked")
                          .execution_options(synchronize_session=False))
            assert r.rowcount == 0                                                  # ORM update
            r = s.execute(delete(FinancePlanRow).where(FinancePlanRow.id == fid)
                          .execution_options(synchronize_session=False))
            assert r.rowcount == 0                                                  # ORM delete
    with owner_scope("usr_local"), db.read() as s:
        assert s.get(ProblemRow, pid).name != "hijacked"
        assert s.get(FinancePlanRow, fid) is not None
        assert s.scalar(select(func.count()).select_from(ProblemRow)) == 1
    with system_scope():
        assert current_owner() is SYSTEM
        with db.read() as s:
            assert s.scalar(select(func.count()).select_from(ProblemRow)) == 1


def test_inserts_are_stamped_with_the_bound_user(app_client):
    _seed(app_client)
    db = app_client.app.state.ctx.db
    with owner_scope("usr_b"), db.write() as s:
        row = ProblemRow(id="p_b", name="B's", domain="generic", version=1, document={})
        s.add(row)
        s.flush()
        assert row.owner_id == "usr_b"
    with owner_scope("usr_b"), db.read() as s:
        assert [p.id for p in s.scalars(select(ProblemRow))] == ["p_b"]
    # the API (usr_local) does not list B's problem
    ids = [p["id"] for p in app_client.get(f"{API}/problems").json()["items"]]
    assert "p_b" not in ids and len(ids) == 1
    assert app_client.get(f"{API}/problems/p_b").status_code == 404


def test_insert_without_owner_outside_single_user_is_refused(db_url):
    from superplanner.api.context import AppContext
    from superplanner.api.config import Settings

    ctx = AppContext(Settings(database_url=db_url, auth_mode="accounts"))
    try:
        ctx.start()
        with pytest.raises(OwnershipViolation):
            with ctx.db.write() as s:
                s.add(ProblemRow(id="p_x", name="x", domain="generic", version=1, document={}))
    finally:
        ctx.stop()


def test_unbound_query_inside_a_request_fails_closed(db_url, caplog):
    app = make_app(db_url)
    ctx = app.state.ctx

    def probe() -> dict:
        with ctx.db.read() as s:
            return {"n": len(s.scalars(select(ProblemRow)).all())}

    def probe_jobs() -> dict:
        with ctx.db.read() as s:
            return {"n": len(s.scalars(select(JobRow.id)).all())}

    def probe_count() -> dict:
        with ctx.db.read() as s:
            return {"n": s.scalar(select(func.count()).select_from(FinancePlanRow))}

    app.add_api_route("/api/v1/_probe", probe)            # deliberately without require_user
    app.add_api_route("/api/v1/_probe_jobs", probe_jobs)
    app.add_api_route("/api/v1/_probe_count", probe_count)
    caplog.set_level(logging.ERROR)
    with TestClient(app, raise_server_exceptions=False) as c:
        for path in ("/api/v1/_probe", "/api/v1/_probe_jobs", "/api/v1/_probe_count"):
            r = c.get(path)
            assert r.status_code == 500
            assert r.json()["error"]["code"] == "INTERNAL_ERROR"
        assert c.get(f"{API}/problems").status_code == 200   # with require_user it works
    assert any("OwnershipViolation" in rec.getMessage() for rec in caplog.records)


def test_unbound_outside_a_request_is_system():
    assert current_owner() is None
    with request_scope():
        assert current_owner() is None


def test_require_user_is_async():
    # A sync dependency's ContextVar would not reach sync endpoints / SSE generators (review R9).
    assert inspect.iscoroutinefunction(require_user)


def test_lazy_start_without_with_serves_the_first_request(db_url):
    # The lazy AppContext.start() runs inside the first request, before require_user binds a user (R9).
    client = TestClient(make_app(db_url))
    r = client.get(f"{API}/problems")
    assert r.status_code == 200 and r.json() == {"items": []}
    r = client.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}})
    assert r.status_code == 201
    client.app.state.ctx.stop()


@pytest.mark.inline_jobs   # restart recovery is the inline contract (queue mode: tests/jobs)
def test_lazy_start_recovers_runs_inside_a_request(db_url):
    """Startup recovery touches owned tables; inside a lazy first request it must run in system scope."""
    with TestClient(make_app(db_url)) as c:
        pid = c.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}}).json()["id"]
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 1})
        rid = r.json()["run_id"]
        c.app.state.ctx.jobs.wait_idle(rid)
        from superplanner.api.db import SolverRunRow
        with c.app.state.ctx.db.write() as s:
            s.get(SolverRunRow, rid).status = "running"
    client = TestClient(make_app(db_url))   # no `with`: start happens inside the first request
    run = client.get(f"{API}/solver-runs/{rid}").json()
    assert run["status"] == "failed" and run["error"] == "Server restarted before the run finished."
    client.app.state.ctx.stop()


def test_accounts_mode_requires_auth_until_q3(db_url):
    with TestClient(make_app(db_url, auth_mode="accounts")) as c:
        for method, path in (("GET", "/problems"), ("POST", "/problems"), ("GET", "/finance/plans"),
                             ("GET", "/templates"), ("POST", "/intake/schedule/describe")):
            r = c.request(method, f"{API}{path}", json={})
            assert r.status_code == 401, (path, r.text)
            assert r.json() == {"error": {"code": "AUTH_REQUIRED", "message": "Please sign in to continue.",
                                          "details": {}}}
        assert c.get(f"{API}/health").status_code == 200        # public
        assert r.headers.get("access-control-allow-credentials") is None   # no Origin sent


def test_cors_credentials_only_in_accounts_mode(db_url, db_url_factory):
    origin = "http://127.0.0.1:5173"
    with TestClient(make_app(db_url)) as c:
        r = c.get(f"{API}/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-credentials" not in r.headers
    with TestClient(make_app(db_url_factory("acc"), auth_mode="accounts")) as c:
        r = c.get(f"{API}/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-credentials"] == "true"
        exposed = r.headers["access-control-expose-headers"]
        for h in ("X-Request-ID", "Idempotent-Replayed", "Retry-After", "ETag"):
            assert h in exposed
