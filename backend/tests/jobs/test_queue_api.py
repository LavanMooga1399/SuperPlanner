"""Queue mode through the HTTP API (PHASE2B 2.7, 2.11, 2.2; plan Q2-7, Q2-11, Q2-12, Q2-13): cancel, two API
instances on one database, NOTIFY wake-up, API restart."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from jobs_helpers import (FAST_LEASE, FIN, LONG_GA, SLOW_FIN, API, BlockingRunPlan, assert_one_terminal_last,
                          fin_events, fin_plan, fin_results, fin_run, fin_status, job_of, make_app, problem,
                          solver_events, solver_run, solver_status, wait_fin, wait_for, wait_solver)
from superplanner import finance as finance_module
from superplanner.api.finance import run_service as finance_run_service
from superplanner.jobs.worker import WorkerLoop



# ---------------------------------------------------------------- Q2-7

def test_cancel_running_solver_and_finance_runs_in_queue_mode(db_url):
    with TestClient(make_app(db_url)) as c:          # env: JOB_BACKEND=queue, WORKER_EMBEDDED=auto
        ctx = c.app.state.ctx
        assert ctx.jobs.backend == "queue" and ctx.jobs.loop is not None
        pid = problem(c, jobs=20)
        srid = solver_run(c, pid, LONG_GA)
        frid = fin_run(c, fin_plan(c), SLOW_FIN)
        wait_for(lambda: solver_status(c, srid)["status"] == "running", what="solver running")
        wait_for(lambda: fin_status(c, frid)["status"] == "running", what="finance running")
        time.sleep(0.8)
        for url, rid, waiter in ((f"{API}/solver-runs", srid, wait_solver), (f"{FIN}/runs", frid, wait_fin)):
            t0 = time.monotonic()
            r = c.post(f"{url}/{rid}/cancel")
            assert r.status_code == 202 and r.json()["status"] == "running", r.text
            run = waiter(c, rid, timeout=10)
            assert time.monotonic() - t0 < 3.0
            assert run["status"] == "cancelled"
        assert solver_status(c, srid)["primary_schedule_id"] is not None   # best-so-far kept
        assert fin_results(ctx, frid) == 0
        ctx.jobs.wait_idle(srid)
        ctx.jobs.wait_idle(frid)
        assert job_of(ctx, srid).status == "cancelled" and job_of(ctx, frid).status == "cancelled"
        assert_one_terminal_last(solver_events(ctx, srid))
        assert_one_terminal_last(fin_events(ctx, frid))


def test_finance_cancel_racing_the_final_write_stores_no_result(db_url, monkeypatch):
    with TestClient(make_app(db_url)) as c, TestClient(make_app(db_url, worker_embedded=0)) as other:
        ctx = c.app.state.ctx
        seen = []

        def cancel_now(run_id):
            seen.append(run_id)
            r = other.post(f"{FIN}/runs/{run_id}/cancel")    # another instance cancels in the race window
            assert r.status_code == 202, r.text

        monkeypatch.setattr(finance_run_service, "_before_final_write", cancel_now)
        rid = fin_run(c, fin_plan(c))
        run = wait_fin(c, rid)
        assert seen == [rid]
        assert run["status"] == "cancelled" and run["result_id"] is None
        assert fin_results(ctx, rid) == 0
        ctx.jobs.wait_idle(rid)
        assert job_of(ctx, rid).status == "cancelled"
        assert_one_terminal_last(fin_events(ctx, rid))


# ---------------------------------------------------------------- Q2-11

def _sse_types(client: TestClient, url: str, timeout: float = 60) -> list[dict]:
    frames: list[dict] = []
    deadline = time.monotonic() + timeout
    with client.stream("GET", url) as r:
        assert r.status_code == 200
        data = None
        for line in r.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
            elif line == "" and data is not None:
                frames.append(data)
                if data["type"] in ("run_completed", "run_cancelled", "run_failed"):
                    break
                data = None
            if time.monotonic() > deadline:
                raise AssertionError("SSE stream did not end")
    return frames


def test_two_api_instances_share_runs_sse_and_cancel(db_url):
    with TestClient(make_app(db_url)) as a, TestClient(make_app(db_url, worker_embedded=0)) as b:
        assert a.app.state.ctx.jobs.loop is not None and b.app.state.ctx.jobs.loop is None
        # create on A, stream on B until completion
        plan = fin_plan(a)
        r = a.post(f"{FIN}/plans/{plan}/runs", json={"time_limit_seconds": 10, "simulation": {"n_paths": 200},
                                                     "compute_fixes": False, "calibration_rounds": 0})
        rid = r.json()["run_id"]
        frames = _sse_types(b, f"{FIN}/runs/{rid}/events")
        assert frames[0]["type"] == "run_queued" and frames[-1]["type"] == "run_completed"
        assert [f["seq"] for f in frames] == list(range(1, len(frames) + 1))
        assert job_of(b.app.state.ctx, rid).lease_owner == a.app.state.ctx.jobs.loop.worker_id
        # a run executing on A is cancelled through B (B has no worker: only the DB flag reaches A)
        rid2 = fin_run(b, plan, SLOW_FIN)
        wait_for(lambda: fin_status(b, rid2)["status"] == "running", what="run running on A")
        time.sleep(0.5)
        t0 = time.monotonic()
        assert b.post(f"{FIN}/runs/{rid2}/cancel").status_code == 202
        run = wait_fin(b, rid2, timeout=10)
        assert time.monotonic() - t0 < 3.0
        assert run["status"] == "cancelled" and run["result_id"] is None
        # solver: create on B, executed on A, SSE on B
        pid = problem(b)
        srid = solver_run(b, pid)
        frames = _sse_types(b, f"{API}/solver-runs/{srid}/events")
        assert frames[-1]["type"] == "run_completed"


# ---------------------------------------------------------------- Q2-12

def test_idle_worker_wakes_on_notify(db_url):
    with TestClient(make_app(db_url, worker_embedded=0)) as c:
        ctx = c.app.state.ctx
        plan = fin_plan(c)
        from superplanner.api.config import Settings
        from superplanner.api.context import AppContext

        wctx = AppContext(Settings(database_url=db_url, worker_embedded=0, worker_poll_seconds=5.0))
        wctx.start()
        loop = WorkerLoop(wctx, concurrency=1, kinds=["finance_run"], embedded=True)
        loop.start()
        try:
            wait_for(lambda: loop._listener.listening, timeout=10, what="LISTEN")
            time.sleep(0.7)                    # the loop is now parked in its 5 s wait
            latencies = []
            for _ in range(2):
                t0 = time.monotonic()
                rid = fin_run(c, plan)
                wait_for(lambda: job_of(ctx, rid).status != "queued", timeout=5, interval=0.01, what="claim")
                latencies.append(time.monotonic() - t0)
                wait_fin(c, rid)
                loop_idle = wait_for(lambda: loop.busy() == 0, what="idle")
                assert loop_idle
                time.sleep(0.7)
            assert max(latencies) < 1.0, latencies
        finally:
            loop.stop(1)
            wctx.stop()


# ---------------------------------------------------------------- Q2-13

def test_api_restart_in_queue_mode_keeps_the_run(db_url, monkeypatch):
    blocker = BlockingRunPlan(block=1)
    monkeypatch.setattr(finance_module, "run_plan", blocker)
    settings = dict(FAST_LEASE)
    with TestClient(make_app(db_url, **settings)) as a:
        rid = fin_run(a, fin_plan(a))
        assert blocker.entered.wait(20)
        wait_for(lambda: fin_status(a, rid)["status"] == "running", what="running on A")
    # A stopped (embedded worker requeued the job); B starts on the same database
    with TestClient(make_app(db_url, **settings)) as b:
        run = wait_fin(b, rid)
        ctx = b.app.state.ctx
        assert run["status"] == "completed"
        events = fin_events(ctx, rid)
        assert [e["reason"] for e in events if e["type"] == "run_requeued"] == ["worker_shutdown"]
        assert "run_failed" not in [e["type"] for e in events]
        assert fin_results(ctx, rid) == 1
        ctx.jobs.wait_idle(rid)
        j = job_of(ctx, rid)
        assert j.status == "succeeded" and j.attempts == 1
        assert_one_terminal_last(events)


def test_api_restart_with_a_running_job_of_a_dead_worker(db_url, monkeypatch):
    """A crashed API (no graceful requeue): the next instance does not fail the run; its reaper requeues it after
    the lease expires and the run completes (queue mode never uses inline restart recovery)."""
    with TestClient(make_app(db_url, worker_embedded=0, **{k: v for k, v in FAST_LEASE.items()
                                                           if k != "worker_poll_seconds"})) as a:
        ctx = a.app.state.ctx
        rid = fin_run(a, fin_plan(a))
        from superplanner.api.db.ownership import system_scope
        from superplanner.jobs import pg

        with system_scope(), ctx.db.write() as s:   # a worker of the crashed instance had claimed it
            assert pg.claim(s, ["finance_run"], "dead:1:abc", pg.new_token(), 2.0) is not None
    with TestClient(make_app(db_url, **FAST_LEASE)) as b:
        assert fin_status(b, rid)["status"] == "queued"     # not failed at startup
        run = wait_fin(b, rid)
        assert run["status"] == "completed"
        reasons = [e["reason"] for e in fin_events(b.app.state.ctx, rid) if e["type"] == "run_requeued"]
        assert reasons == ["lease_expired"]


# ---------------------------------------------------------------- orphan runs (B 2.5.3)

def test_queue_start_fails_orphan_runs_without_a_job(db_url):
    from sqlalchemy import delete

    from superplanner.api.db import JobRow
    from superplanner.api.db.ownership import system_scope

    with TestClient(make_app(db_url, worker_embedded=0)) as a:
        ctx = a.app.state.ctx
        rid = fin_run(a, fin_plan(a))
        with system_scope(), ctx.db.write() as s:
            s.execute(delete(JobRow).where(JobRow.finance_run_id == rid))
    b = TestClient(make_app(db_url, worker_embedded=0))   # no `with`: lazy start inside the first request (R9)
    try:
        run = fin_status(b, rid)
        assert run["status"] == "failed" and run["error"] == "Server restarted before the run finished."
        assert_one_terminal_last(fin_events(b.app.state.ctx, rid))
    finally:
        b.app.state.ctx.stop()
