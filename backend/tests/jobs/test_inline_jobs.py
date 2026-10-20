"""Inline backend job rows (PHASE2B 2.2; plan Q2-15): one job per run whose terminal status matches the run."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from jobs_helpers import (API, FIN, LONG_GA, SLOW_FIN, fin_plan, fin_run, fin_status, job_of, make_app, problem,
                          solver_run, solver_status, wait_fin, wait_for, wait_solver)
from superplanner import finance as finance_module

pytestmark = pytest.mark.inline_jobs


def _check(job, status, owner="usr_local"):
    assert job.status == status, (job.status, status)
    assert job.owner_id == owner and job.finished_at is not None and job.lease_token is None
    assert job.lease_expires_at is None


def test_inline_jobs_mirror_succeeded_failed_and_cancelled(db_url, monkeypatch):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        assert ctx.jobs.backend == "inline"
        # succeeded (solver + finance)
        pid = problem(c)
        srid = solver_run(c, pid)
        assert wait_solver(c, srid)["status"] == "completed"
        ctx.jobs.wait_idle(srid)
        _check(job_of(ctx, srid), "succeeded")
        plan = fin_plan(c)
        frid = fin_run(c, plan)
        assert wait_fin(c, frid)["status"] == "completed"
        ctx.jobs.wait_idle(frid)
        j = job_of(ctx, frid)
        _check(j, "succeeded")
        assert j.attempts == 1 and j.lease_owner.startswith("inline:")
        # cancelled while running
        crid = solver_run(c, pid, LONG_GA)
        wait_for(lambda: solver_status(c, crid)["status"] == "running", what="running")
        time.sleep(0.5)
        assert c.post(f"{API}/solver-runs/{crid}/cancel").status_code == 202
        assert wait_solver(c, crid)["status"] == "cancelled"
        ctx.jobs.wait_idle(crid)
        _check(job_of(ctx, crid), "cancelled")
        fcr = fin_run(c, plan, SLOW_FIN)
        wait_for(lambda: fin_status(c, fcr)["status"] == "running", what="running")
        assert c.post(f"{FIN}/runs/{fcr}/cancel").status_code == 202
        assert wait_fin(c, fcr)["status"] == "cancelled"
        ctx.jobs.wait_idle(fcr)
        _check(job_of(ctx, fcr), "cancelled")
        # failed (engine error)

        def boom(*a, **k):
            raise RuntimeError("kaputt")

        monkeypatch.setattr(finance_module, "run_plan", boom)
        xrid = fin_run(c, plan)
        run = wait_fin(c, xrid)
        assert run["status"] == "failed" and run["error"] == "kaputt"
        ctx.jobs.wait_idle(xrid)
        j = job_of(ctx, xrid)
        _check(j, "failed")
        assert j.last_error == "kaputt"


def test_inline_cancel_while_queued_never_claims_the_job(db_url):
    with TestClient(make_app(db_url, run_workers=1)) as c:
        ctx = c.app.state.ctx
        pid = problem(c, jobs=20)
        busy = solver_run(c, pid, LONG_GA)
        wait_for(lambda: solver_status(c, busy)["status"] == "running", what="running")
        plan = fin_plan(c)
        queued = fin_run(c, plan)        # waits behind the busy run (one executor thread)
        assert c.post(f"{FIN}/runs/{queued}/cancel").json()["status"] == "cancelled"
        c.post(f"{API}/solver-runs/{busy}/cancel")
        wait_solver(c, busy)
        ctx.jobs.wait_idle(queued)
        j = job_of(ctx, queued)
        _check(j, "cancelled")
        assert j.cancel_requested
        assert fin_status(c, queued)["started_at"] is None   # the engine never ran
