"""`python -m superplanner.worker` as real subprocesses (PHASE2B 2.9; plan Q2-9, Q2-14): kill -9 mid-run, graceful
SIGTERM, `--once`, configuration and schema exits."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from jobs_helpers import (BACKEND, LONG_GA, SLOW_FIN, assert_one_terminal_last, fin_events, fin_plan, fin_results,
                          fin_run, fin_status, job_of, make_app, problem, solver_events, solver_run, solver_status,
                          start_worker, stop_process, wait_fin, wait_for, wait_solver, worker_env)
from superplanner.api.config import ConfigError, Settings
from superplanner.api.db import ScheduleRow
from superplanner.api.db.ownership import system_scope


def _alive_workers(ctx) -> list[str]:
    with system_scope(), ctx.db.read() as s:
        return [r[0] for r in s.execute(text("SELECT id FROM job_workers WHERE stopped_at IS NULL")).all()]


def test_kill_9_mid_run_another_worker_completes_it_exactly_once(db_url, tmp_path):
    workers: list[subprocess.Popen] = []
    with TestClient(make_app(db_url, worker_embedded=0)) as c:
        ctx = c.app.state.ctx
        pid = problem(c, jobs=20)
        ga = dict(LONG_GA, time_limit_seconds=6)
        srid = solver_run(c, pid, ga)
        frid = fin_run(c, fin_plan(c), SLOW_FIN)
        try:
            w1 = start_worker(db_url, tmp_path / "w1.log", "--concurrency", "2", "--id", "w1:0:one")
            workers.append(w1)
            wait_for(lambda: solver_status(c, srid)["status"] == "running"
                     and fin_status(c, frid)["status"] == "running", timeout=60, what="both runs running on w1")
            time.sleep(1.0)   # mid-run: progress written, no result yet
            assert fin_results(ctx, frid) == 0
            assert job_of(ctx, srid).lease_owner.startswith("w1:") and job_of(ctx, frid).lease_owner.startswith("w1:")
            os.kill(w1.pid, signal.SIGKILL)
            w1.wait(10)
            w2 = start_worker(db_url, tmp_path / "w2.log", "--concurrency", "2", "--id", "w2:0:two")
            workers.append(w2)
            srun = wait_solver(c, srid, timeout=120)
            frun = wait_fin(c, frid, timeout=180)
        finally:
            for w in workers:
                stop_process(w)
        logs = "\n".join((tmp_path / n).read_text(errors="replace") for n in ("w1.log", "w2.log"))
        assert srun["status"] == "completed", logs[-4000:]
        assert frun["status"] == "completed", logs[-4000:]
        for rid, events in ((srid, solver_events(ctx, srid)), (frid, fin_events(ctx, frid))):
            j = job_of(ctx, rid)
            assert j.status == "succeeded" and j.attempts == 2 and j.lease_owner.startswith("w2:")
            assert [e["reason"] for e in events if e["type"] == "run_requeued"] == ["lease_expired"]
            assert_one_terminal_last(events)
        assert fin_results(ctx, frid) == 1
        with system_scope(), ctx.db.read() as s:
            ranks = sorted(s.scalars(select(ScheduleRow.rank).where(ScheduleRow.solver_run_id == srid)).all())
        assert ranks == list(range(len(ranks))) and ranks
        assert srun["primary_schedule_id"] is not None
        assert w2.returncode == 0   # SIGTERM -> graceful exit 0


def test_sigterm_requeues_and_once_mode_finishes_the_queue(db_url, tmp_path):
    with TestClient(make_app(db_url, worker_embedded=0)) as c:
        ctx = c.app.state.ctx
        frid = fin_run(c, fin_plan(c), SLOW_FIN)
        w = start_worker(db_url, tmp_path / "w.log", "--concurrency", "1", WORKER_SHUTDOWN_GRACE_SECONDS="0.2")
        try:
            wait_for(lambda: fin_status(c, frid)["status"] == "running", timeout=60, what="running")
            time.sleep(0.5)
        finally:
            rc = stop_process(w, signal.SIGTERM)
        log = (tmp_path / "w.log").read_text(errors="replace")
        assert rc == 0, log[-3000:]
        j = job_of(ctx, frid)
        assert j.status == "queued" and j.attempts == 0 and j.lease_token is None, log[-3000:]
        assert fin_status(c, frid)["status"] == "queued"
        events = fin_events(ctx, frid)
        assert events[-1]["type"] == "run_requeued" and events[-1]["reason"] == "worker_shutdown"
        assert "worker.stopped" in log
        # --once: drains the queue (the requeued run plus a new one) and exits 0
        frid2 = fin_run(c, fin_plan(c))
        once = subprocess.run([sys.executable, "-m", "superplanner.worker", "--once", "--concurrency", "2"],
                              cwd=str(BACKEND), env=worker_env(db_url), capture_output=True, text=True, timeout=300)
        assert once.returncode == 0, once.stdout[-3000:] + once.stderr[-3000:]
        assert fin_status(c, frid)["status"] == "completed" and fin_status(c, frid2)["status"] == "completed"
        assert job_of(ctx, frid).attempts == 1
        assert not _alive_workers(ctx)   # every worker marked itself stopped


# ---------------------------------------------------------------- Q2-14 configuration

def test_inline_backend_outside_development_is_refused():
    with pytest.raises(ConfigError, match="JOB_BACKEND=inline is only allowed with APP_ENV=development"):
        Settings(database_url="postgresql+psycopg://u@127.0.0.1:1/x", job_backend="inline", sp_env="production",
                 auth_mode="accounts", public_base_url="https://example.com", password_hash_profile="default")
    s = Settings(database_url="postgresql+psycopg://u:p@127.0.0.1:1/x", job_backend="inline")
    assert s.job_backend == "inline"   # allowed in development (with a warning)


def _worker_exit(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "superplanner.worker"], cwd=str(BACKEND), env=env,
                          capture_output=True, text=True, timeout=120)


def test_worker_with_a_non_postgres_url_exits_2():
    env = worker_env("sqlite:///w.db")
    r = _worker_exit(env)
    assert r.returncode == 2, r.stderr
    assert "configuration error: DATABASE_URL must be a PostgreSQL URL" in r.stderr
    env = worker_env("postgresql+psycopg://u:p@127.0.0.1:1/x")
    env["JOB_BACKEND"] = "inline"
    r = _worker_exit(env)
    assert r.returncode == 2 and "JOB_BACKEND" in r.stderr


def test_worker_with_schema_behind_head_exits_3(request):
    from superplanner import migrate

    admin = request.getfixturevalue("pg_admin")
    name = "sp_e_behind_%d" % os.getpid()
    admin.drop(name)
    admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = admin.url_for(name)
        migrate.run_alembic_upgrade(url, "0001_initial")
        r = _worker_exit(worker_env(url, DB_AUTO_MIGRATE="false"))
        assert r.returncode == 3, r.stderr
        assert migrate.HEAD in r.stderr and "python -m superplanner.migrate upgrade" in r.stderr
        r = _worker_exit(worker_env(url, DB_AUTO_MIGRATE="false", JOB_BACKEND="inline"))
        assert r.returncode == 2 and "JOB_BACKEND=queue" in r.stderr
    finally:
        admin.drop(name)
