"""Fix round: a job left `running` by a killed JOB_BACKEND=inline process on PostgreSQL is recovered when the
API (or a worker) next starts in queue mode, so its run no longer blocks new runs (409 RUN_ALREADY_ACTIVE)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from jobs_helpers import API, job_of, make_app
from superplanner.api.config import Settings
from superplanner.api.db import SolverRunRow
from superplanner.api.db.ownership import system_scope
from superplanner.jobs import common
from superplanner.jobs.types import RESTART_ERROR
from superplanner.jobs.worker import WorkerContext

pytestmark = pytest.mark.postgres_only

SOLVE = {"strategy": "heuristic", "time_limit_seconds": 2}


def _left_running_by_inline(db_url: str, monkeypatch) -> tuple[str, str]:
    """An inline API claims a solver run's job and is then 'killed' before the executor runs it."""
    app = make_app(db_url, job_backend="inline")
    with TestClient(app) as c:
        ctx = app.state.ctx
        monkeypatch.setattr(ctx.executor, "submit", lambda *a, **k: object())   # never runs: process died
        pid = c.post(f"{API}/templates/manufacturing/instantiate",
                     json={"name": "P", "parameters": {"jobs": 2}}).json()["id"]
        r = c.post(f"{API}/problems/{pid}/solver-runs", json=SOLVE)
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        with system_scope(), ctx.db.write() as s:   # the handler had marked the run running before the crash
            s.execute(update(SolverRunRow).where(SolverRunRow.id == run_id).values(status="running"))
        job = job_of(ctx, run_id)
        assert job.status == "running" and job.lease_expires_at is None and job.lease_owner.startswith("inline:")
        monkeypatch.undo()
    return pid, run_id


def _run_row(ctx, run_id):
    with system_scope(), ctx.db.read() as s:
        return s.execute(select(SolverRunRow.status, SolverRunRow.error).where(SolverRunRow.id == run_id)).one()


def test_queue_api_start_fails_inline_leftover_and_unblocks_new_runs(db_url, monkeypatch):
    pid, run_id = _left_running_by_inline(db_url, monkeypatch)
    app = make_app(db_url, job_backend="queue", worker_embedded=0)
    with TestClient(app) as c:
        ctx = app.state.ctx
        run = _run_row(ctx, run_id)
        assert run.status == "failed" and run.error == RESTART_ERROR
        job = job_of(ctx, run_id)
        assert job.status == "failed" and job.last_error == RESTART_ERROR and job.lease_token is None
        assert c.get(f"{API}/solver-runs/{run_id}").json()["status"] == "failed"
        r = c.post(f"{API}/problems/{pid}/solver-runs", json=SOLVE)
        assert r.status_code == 202, r.text   # was 409 RUN_ALREADY_ACTIVE


def test_worker_start_recovery_fails_inline_leftover(db_url, monkeypatch):
    _, run_id = _left_running_by_inline(db_url, monkeypatch)
    from superplanner.api.db import Database
    from superplanner.api.db.ownership import install as install_ownership

    settings = Settings(database_url=db_url, job_backend="queue")
    db = Database.from_settings(settings, service="worker")
    install_ownership(db, single_user=settings.single_user)
    try:
        wctx = WorkerContext(settings, db)
        assert common.queue_start_recovery(wctx) == {"inline_leftovers": 1, "orphan_runs": 0}
        assert common.queue_start_recovery(wctx) == {"inline_leftovers": 0, "orphan_runs": 0}   # idempotent
        with system_scope(), db.read() as s:
            run = s.get(SolverRunRow, run_id)
            assert run.status == "failed" and run.error == RESTART_ERROR
    finally:
        db.dispose()


def test_queue_jobs_with_a_lease_are_not_touched(db_url):
    """A queue-mode lease (non-NULL expiry) is the reaper's business, never failed at startup."""
    app = make_app(db_url, job_backend="queue", worker_embedded=0)
    with TestClient(app) as c:
        ctx = app.state.ctx
        pid = c.post(f"{API}/templates/manufacturing/instantiate",
                     json={"name": "P", "parameters": {"jobs": 2}}).json()["id"]
        run_id = c.post(f"{API}/problems/{pid}/solver-runs", json=SOLVE).json()["run_id"]
        from superplanner.jobs import pg

        token = pg.new_token()
        with system_scope(), ctx.db.write() as s:
            assert pg.claim(s, ["solver_run"], "w1", token, 600.0) is not None
        assert common.fail_inline_leftovers(ctx) == 0
        assert job_of(ctx, run_id).status == "running"
