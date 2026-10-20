"""Cross-process backstops and locks (PHASE2B 2.12; Q1-7, Q1-8, Q1-10) plus job rows in inline mode."""

from __future__ import annotations

import threading
import time

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db_helpers import make_app
from superplanner.api.context import AppContext
from superplanner.api.config import Settings
from superplanner.api.db import JobRow, ProblemVersionRow, ScheduleRow, SolverRunEventRow, SolverRunRow, new_id, utcnow
from superplanner.api.db.ownership import system_scope
from superplanner.api.finance import run_service as fin_run_service
from superplanner.api.services import run_service, schedule_service

API = "/api/v1"
FIN = f"{API}/finance"
FAST_FIN = {"time_limit_seconds": 10, "simulation": {"n_paths": 200}, "compute_fixes": False, "calibration_rounds": 0}


def _problem(c: TestClient) -> str:
    r = c.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wait(c: TestClient, url: str, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        run = c.get(url).json()
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, run
        time.sleep(0.05)


def _run_row(problem_id: str, pv_id: str, status: str = "queued", **kw) -> SolverRunRow:
    return SolverRunRow(id=new_id("run_"), problem_id=problem_id, problem_version_id=pv_id, status=status,
                        request={}, seed=0, engine_version="t", diagnostics=[], cancel_requested=False,
                        created_at=utcnow(), **kw)


def _snapshot(ctx: AppContext, problem_id: str) -> str:
    from superplanner.api.services.problem_service import get_problem_row, snapshot
    with ctx.db.write() as s:
        return snapshot(s, get_problem_row(s, problem_id)).id


# ---------------------------------------------------------------- Q1-7 partial unique indexes

def test_db_rejects_a_second_active_run_and_a_second_approval(db_url):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        pid = _problem(c)
        pv = _snapshot(ctx, pid)
        with ctx.db.write() as s:
            s.add(_run_row(pid, pv, "queued"))
        with pytest.raises(IntegrityError):
            with ctx.db.write() as s:
                s.add(_run_row(pid, pv, "running"))
        with ctx.db.write() as s:   # terminal runs are not constrained
            s.add(_run_row(pid, pv, "completed"))
            s.add(_run_row(pid, pv, "failed"))

        def sched(status: str) -> ScheduleRow:
            return ScheduleRow(id=new_id("sch_"), problem_id=pid, problem_version_id=pv, status=status, rank=0,
                               label="x", solver="t", feasibility="feasible", violations=[], placements=[])
        with ctx.db.write() as s:
            s.add(sched("approved"))
            s.add(sched("candidate"))
            s.add(sched("candidate"))
        with pytest.raises(IntegrityError):
            with ctx.db.write() as s:
                s.add(sched("approved"))


def test_db_rejects_a_second_job_for_one_run(db_url):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        pid = _problem(c)
        pv = _snapshot(ctx, pid)
        with ctx.db.write() as s:
            run = _run_row(pid, pv, "completed")
            s.add(run)
            s.flush()
            ctx.jobs.enqueue(s, "solver_run", run.id, run.owner_id)
        with pytest.raises(IntegrityError):
            with ctx.db.write() as s:
                ctx.jobs.enqueue(s, "solver_run", run.id, run.owner_id)


@pytest.mark.inline_jobs
def test_active_run_index_violation_maps_to_409(db_url, monkeypatch):
    with TestClient(make_app(db_url, run_workers=1)) as c:
        ctx = c.app.state.ctx
        gate = threading.Event()
        ctx.executor.submit("block_the_pool", lambda _r, _e: gate.wait(20))
        try:
            pid = _problem(c)
            first = c.post(f"{API}/problems/{pid}/solver-runs", json={"time_limit_seconds": 1}).json()["run_id"]
            # simulate the race the explicit check cannot see (another process): only the index stops it
            monkeypatch.setattr(run_service, "ensure_no_active_run", lambda s, problem_id: None)
            r = c.post(f"{API}/problems/{pid}/solver-runs", json={"time_limit_seconds": 1})
            assert r.status_code == 409, r.text
            assert r.json()["error"]["code"] == "RUN_ALREADY_ACTIVE"
            assert r.json()["error"]["details"] == {"run_id": first}
        finally:
            gate.set()
        _wait(c, f"{API}/solver-runs/{first}")


def test_approve_retries_once_on_the_approved_index(db_url, monkeypatch):
    real = schedule_service._approve
    calls = []

    def flaky(ctx, schedule_id, note):
        calls.append(schedule_id)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, Exception('duplicate key value violates unique constraint '
                                                         '"uq_schedules_one_approved"'))
        return real(ctx, schedule_id, note)

    with TestClient(make_app(db_url)) as c:
        pid = _problem(c)
        rid = c.post(f"{API}/problems/{pid}/solver-runs",
                     json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        run = _wait(c, f"{API}/solver-runs/{rid}")
        monkeypatch.setattr(schedule_service, "_approve", flaky)
        r = c.post(f"{API}/schedules/{run['primary_schedule_id']}/approve", json={})
        assert r.status_code == 200, r.text
        assert len(calls) == 2
        calls.clear()

        def always(ctx, schedule_id, note):
            calls.append(1)
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: schedules.problem_id"))

        monkeypatch.setattr(schedule_service, "_approve", always)
        r = c.post(f"{API}/schedules/{run['primary_schedule_id']}/approve", json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT"
        assert len(calls) == 2


# ---------------------------------------------------------------- job rows in inline mode

def test_inline_mode_writes_one_job_per_run_with_the_terminal_status(db_url):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        pid = _problem(c)
        rid = c.post(f"{API}/problems/{pid}/solver-runs",
                     json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        assert _wait(c, f"{API}/solver-runs/{rid}")["status"] == "completed"
        ctx.jobs.wait_idle(rid)
        fp = c.post(f"{FIN}/templates/young_professional/instantiate", json={"start_month": "2026-11"}).json()["id"]
        frid = c.post(f"{FIN}/plans/{fp}/runs", json=FAST_FIN).json()["run_id"]
        assert _wait(c, f"{FIN}/runs/{frid}")["status"] == "completed"
        ctx.jobs.wait_idle(frid)
        with ctx.db.read() as s:
            jobs = s.scalars(select(JobRow)).all()
            by_run = {j.solver_run_id or j.finance_run_id: j for j in jobs}
            assert set(by_run) == {rid, frid}
            for j in jobs:
                assert j.status == "succeeded" and j.attempts == 1 and j.owner_id == "usr_local"
                assert j.lease_owner.startswith("inline:") and j.lease_token is None and j.finished_at is not None
            assert by_run[rid].kind == "solver_run" and by_run[frid].kind == "finance_run"


@pytest.mark.inline_jobs
def test_recovery_fails_jobs_of_interrupted_runs(db_url):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        pid = _problem(c)
        rid = c.post(f"{API}/problems/{pid}/solver-runs",
                     json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        _wait(c, f"{API}/solver-runs/{rid}")
        ctx.jobs.wait_idle(rid)
        with ctx.db.write() as s:
            s.get(SolverRunRow, rid).status = "running"
            job = s.scalars(select(JobRow).where(JobRow.solver_run_id == rid)).one()
            job.status = "running"
    with TestClient(make_app(db_url)) as c:
        with c.app.state.ctx.db.read() as s:
            job = s.scalars(select(JobRow).where(JobRow.solver_run_id == rid)).one()
            assert job.status == "failed" and job.last_error == "Server restarted before the run finished."


# ---------------------------------------------------------------- Q1-8 seq allocation under concurrency

@pytest.mark.postgres_only
def test_concurrent_add_event_allocates_contiguous_seq(db_url):
    ctx = AppContext(Settings(database_url=db_url))
    ctx.start()
    try:
        with TestClient(make_app(db_url)) as c:
            pid = _problem(c)
        pv = _snapshot(ctx, pid)
        with ctx.db.write() as s:
            run = _run_row(pid, pv, "completed")
            s.add(run)
            rid = run.id
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def writer() -> None:
            try:
                with system_scope():
                    barrier.wait()
                    for _ in range(25):
                        with ctx.db.write() as s:
                            run_service.add_event(s, rid, "progress", {}, 0.0)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        assert not errors, errors[:3]
        with ctx.db.read() as s:
            seqs = list(s.scalars(select(SolverRunEventRow.seq).where(SolverRunEventRow.run_id == rid)
                                  .order_by(SolverRunEventRow.id)))
        assert seqs == list(range(1, 201))     # committed in seq order (id order == seq order), no gaps
    finally:
        ctx.stop()


# ---------------------------------------------------------------- Q1-10 lock strength

@pytest.mark.postgres_only
def test_plan_lock_is_no_key_update(db_url, monkeypatch):
    """While create_what_if holds the plan lock, another connection can still insert a plan child (FK KEY SHARE)."""
    entered, release = threading.Event(), threading.Event()
    real = fin_run_service.preflight_or_422

    def slow_preflight(plan):
        entered.set()
        assert release.wait(30)
        return real(plan)

    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        fp = c.post(f"{FIN}/templates/young_professional/instantiate", json={"start_month": "2026-11"}).json()["id"]
        base = c.post(f"{FIN}/plans/{fp}/runs", json=FAST_FIN).json()["run_id"]
        base_run = _wait(c, f"{FIN}/runs/{base}")
        assert base_run["status"] == "completed"
        monkeypatch.setattr(fin_run_service, "preflight_or_422", slow_preflight)
        out: dict = {}
        t = threading.Thread(target=lambda: out.setdefault("r", c.post(
            f"{FIN}/plans/{fp}/what-if", json={"changes": {"label": "x"}, "run": FAST_FIN})))
        t.start()
        try:
            assert entered.wait(30)
            eng = sa.create_engine(db_url)
            try:
                with eng.begin() as conn:
                    conn.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
                    locks = conn.execute(sa.text(
                        "SELECT mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                        "WHERE c.relname = 'finance_plans' AND l.granted")).scalars().all()
                    assert "RowShareLock" in locks       # a row lock on finance_plans is held
                    conn.execute(sa.text(
                        "INSERT INTO finance_runs (id, owner_id, plan_id, plan_version_id, kind, status, request, "
                        "seed, engine_version, cancel_requested, created_at) SELECT 'frun_probe', owner_id, plan_id, "
                        "plan_version_id, 'baseline', 'completed', '{}', 0, 't', false, now() FROM finance_runs "
                        "WHERE id = :b"), {"b": base})
                    conn.execute(sa.text(
                        "INSERT INTO finance_results (id, owner_id, plan_id, plan_version_id, run_id, kind, "
                        "feasibility, summary, result, created_at) SELECT 'fres_probe', owner_id, plan_id, "
                        "plan_version_id, 'frun_probe', 'baseline', 'feasible', '{}', '{}', now() FROM finance_runs "
                        "WHERE id = :b"), {"b": base})
                    # plain FOR UPDATE (what a delete takes) must conflict, proving the lock is really held
                    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                        with conn.begin_nested():
                            conn.execute(sa.text("SET LOCAL lock_timeout = '300ms'"))
                            conn.execute(sa.text("SELECT id FROM finance_plans WHERE id = :p FOR UPDATE"),
                                         {"p": fp})
            finally:
                eng.dispose()
        finally:
            release.set()
            t.join(60)
        assert out["r"].status_code == 202, out["r"].text
        _wait(c, f"{FIN}/runs/{out['r'].json()['run_id']}")
