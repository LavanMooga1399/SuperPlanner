"""Shared helpers for the Q2 job-queue tests."""

from __future__ import annotations

import copy
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import or_, select

from superplanner import finance as finance_module
from superplanner.api.config import Settings
from superplanner.api.context import AppContext
from superplanner.api.db import JobRow, SolverRunEventRow
from superplanner.api.db.ownership import system_scope
from superplanner.api.finance.db_models import FinanceResultRow, FinanceRunEventRow
from superplanner.api.main import create_app

API = "/api/v1"
FIN = f"{API}/finance"
BACKEND = Path(__file__).resolve().parents[2]

FAST_FIN: dict[str, Any] = {"time_limit_seconds": 10, "simulation": {"n_paths": 200}, "compute_fixes": False,
                            "calibration_rounds": 0}
# Several seconds of real engine work (kill / cancel / cross-instance tests).
SLOW_FIN: dict[str, Any] = {"time_limit_seconds": 120, "simulation": {"n_paths": 10000}, "compute_fixes": True,
                            "calibration_rounds": 4}
LONG_GA: dict[str, Any] = {"strategy": "ga", "time_limit_seconds": 30,
                           "ga": {"max_generations": 10000, "stagnation_generations": 1000}}

# Fast lease timings for the queue tests (seconds).
FAST_LEASE: dict[str, Any] = {"job_lease_seconds": 2.0, "job_heartbeat_seconds": 0.5, "job_cancel_poll_seconds": 0.1,
                              "job_reaper_seconds": 0.5, "job_backoff_base_seconds": 0.05,
                              "job_backoff_max_seconds": 0.2, "worker_poll_seconds": 0.2,
                              "worker_shutdown_grace_seconds": 0.5}


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def new_ctx(db_url: str, **overrides: Any) -> AppContext:
    ctx = AppContext(Settings(database_url=db_url, **overrides))
    ctx.start()
    return ctx


def wait_for(pred: Callable[[], Any], timeout: float = 20.0, interval: float = 0.05, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = pred()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(interval)


# ---------------------------------------------------------------- API shortcuts

def fin_plan(c: TestClient) -> str:
    r = c.post(f"{FIN}/templates/young_professional/instantiate", json={"start_month": "2026-11"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def fin_run(c: TestClient, plan_id: str, req: dict[str, Any] | None = None, **headers: str) -> str:
    r = c.post(f"{FIN}/plans/{plan_id}/runs", json=copy.deepcopy(FAST_FIN if req is None else req),
               headers=headers or None)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def problem(c: TestClient, jobs: int = 6) -> str:
    r = c.post(f"{API}/templates/manufacturing/instantiate",
               json={"start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": jobs}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def solver_run(c: TestClient, problem_id: str, req: dict[str, Any] | None = None) -> str:
    r = c.post(f"{API}/problems/{problem_id}/solver-runs",
               json=req if req is not None else {"strategy": "heuristic", "time_limit_seconds": 1})
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def fin_status(c: TestClient, run_id: str) -> dict[str, Any]:
    r = c.get(f"{FIN}/runs/{run_id}")
    assert r.status_code == 200, r.text
    return r.json()


def solver_status(c: TestClient, run_id: str) -> dict[str, Any]:
    r = c.get(f"{API}/solver-runs/{run_id}")
    assert r.status_code == 200, r.text
    return r.json()


def wait_fin(c: TestClient, run_id: str, timeout: float = 60.0) -> dict[str, Any]:
    return wait_for(lambda: (lambda r: r if r["status"] not in ("queued", "running") else None)(fin_status(c, run_id)),
                    timeout, what=f"finance run {run_id} to finish")


def wait_solver(c: TestClient, run_id: str, timeout: float = 60.0) -> dict[str, Any]:
    return wait_for(lambda: (lambda r: r if r["status"] not in ("queued", "running") else None)(
        solver_status(c, run_id)), timeout, what=f"solver run {run_id} to finish")


# ---------------------------------------------------------------- DB reads (system scope)

def job_of(ctx: Any, run_id: str) -> JobRow:
    with system_scope(), ctx.db.read() as s:
        job = s.scalars(select(JobRow).where(or_(JobRow.solver_run_id == run_id,
                                                 JobRow.finance_run_id == run_id))).one()
        s.expunge(job)
        return job


def fin_events(ctx: Any, run_id: str) -> list[dict[str, Any]]:
    with system_scope(), ctx.db.read() as s:
        return [r.payload for r in s.scalars(select(FinanceRunEventRow).where(FinanceRunEventRow.run_id == run_id)
                                             .order_by(FinanceRunEventRow.seq)).all()]


def solver_events(ctx: Any, run_id: str) -> list[dict[str, Any]]:
    with system_scope(), ctx.db.read() as s:
        return [r.payload for r in s.scalars(select(SolverRunEventRow).where(SolverRunEventRow.run_id == run_id)
                                             .order_by(SolverRunEventRow.seq)).all()]


def fin_results(ctx: Any, run_id: str) -> int:
    with system_scope(), ctx.db.read() as s:
        return len(s.scalars(select(FinanceResultRow.id).where(FinanceResultRow.run_id == run_id)).all())


TERMINAL = ("run_completed", "run_cancelled", "run_failed")


def assert_one_terminal_last(events: list[dict[str, Any]]) -> None:
    """Invariant I1: exactly one terminal event, and it is the last one; seq contiguous."""
    types = [e["type"] for e in events]
    assert sum(t in TERMINAL for t in types) == 1, types
    assert types[-1] in TERMINAL, types
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


# ---------------------------------------------------------------- engine stand-ins

class BlockingRunPlan:
    """Replaces `superplanner.finance.run_plan`: the first `block` calls wait for the cancel event (as the real
    engine would) and raise FinanceCancelled; later calls run the real engine."""

    def __init__(self, block: int = 1):
        self.real = finance_module.run_plan
        self.block = block
        self.calls = 0
        self.entered = threading.Event()
        self.released = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, plan, request=None, progress_cb=None, cancel_event=None):
        with self._lock:
            self.calls += 1
            n = self.calls
        if n > self.block:
            return self.real(plan, request, progress_cb, cancel_event)
        self.entered.set()
        deadline = time.monotonic() + 60
        while not (cancel_event is not None and cancel_event.is_set()) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.released.set()
        raise finance_module.FinanceCancelled()


# ---------------------------------------------------------------- worker subprocesses

def worker_env(db_url: str, **extra: Any) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("JOB_", "WORKER_", "DB_AUTO"))}
    env.update({"DATABASE_URL": db_url, "JOB_BACKEND": "queue", "WORKER_METRICS_PORT": "0",
                "JOB_LEASE_SECONDS": "3", "JOB_HEARTBEAT_SECONDS": "0.5", "JOB_CANCEL_POLL_SECONDS": "0.2",
                "JOB_REAPER_SECONDS": "0.5", "JOB_BACKOFF_BASE_SECONDS": "0.1", "JOB_BACKOFF_MAX_SECONDS": "0.5",
                "WORKER_POLL_SECONDS": "0.3", "WORKER_SHUTDOWN_GRACE_SECONDS": "5", "LOG_LEVEL": "INFO",
                "PYTHONUNBUFFERED": "1"})
    env.update({k: str(v) for k, v in extra.items()})
    return env


def start_worker(db_url: str, log_path: Path, *args: str, **env: Any) -> subprocess.Popen:
    fh = open(log_path, "ab")
    return subprocess.Popen([sys.executable, "-m", "superplanner.worker", *args], cwd=str(BACKEND),
                            env=worker_env(db_url, **env), stdout=fh, stderr=subprocess.STDOUT)


def stop_process(p: subprocess.Popen, sig: int = signal.SIGTERM, timeout: float = 30.0) -> int | None:
    if p.poll() is None:
        p.send_signal(sig)
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(10)
    return p.returncode
