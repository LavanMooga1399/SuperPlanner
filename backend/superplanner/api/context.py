"""Per-app runtime context: settings, database, executor, job queue and the write guard (A.13 rule 7, PHASE2B 2.12).

`write_guard()` replaces the process-wide `WRITE_LOCK`: on SQLite it is that RLock (behaviour unchanged), on
PostgreSQL a no-op - there, row locks (`FOR NO KEY UPDATE` on the parent plan/problem and the run) and partial
unique indexes give the cross-process guarantees. `WRITE_LOCK` stays exported as an alias for one release.

`AppContext.start()` runs as a whole in `system_scope()` (review R9): it may run lazily inside the first request
(TestClient without `with`), where the fail-closed ownership rule would otherwise reject its recovery queries.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import uuid
from collections.abc import Callable
from typing import Any, ContextManager

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import Settings
from .db import Database, JobRow, new_id, utcnow
from .db.ownership import install as install_ownership
from .db.ownership import system_scope
from .executor import RunExecutor

log = logging.getLogger(__name__)

# Check-then-write sequences (one active run, one approved schedule, If-Match) run under this lock AND inside one DB
# transaction on SQLite. Kept as an alias; new code uses `ctx.write_guard()`.
WRITE_LOCK = threading.RLock()

JOB_KINDS = ("solver_run", "finance_run")
_RUN_TO_JOB_STATUS = {"completed": "succeeded", "failed": "failed", "cancelled": "cancelled"}


def _handler(kind: str) -> Callable[..., None]:
    if kind == "solver_run":
        from .services import run_service

        return run_service.run_job
    from .finance import run_service as finance_run_service

    return finance_run_service.run_job


def _run_model(kind: str) -> Any:
    if kind == "solver_run":
        from .db import SolverRunRow

        return SolverRunRow
    from .finance.db_models import FinanceRunRow

    return FinanceRunRow


def _job_fk(kind: str) -> Any:
    return JobRow.solver_run_id if kind == "solver_run" else JobRow.finance_run_id


class InlineJobs:
    """Q1 shim of the `JobQueue` interface (PHASE2B 2.2) on the in-process `RunExecutor`.

    Job rows are written in this mode too (one per run), so run code and data look the same as with the queue.
    `dispatch` claims the row conditionally (`queued` -> `running`, inline lease) and submits to the executor;
    the submitted callable enters `system_scope()` explicitly. Replaced by `superplanner.jobs.inline` in Q2.
    """

    backend = "inline"

    def __init__(self, ctx: "AppContext"):
        self.ctx = ctx
        self.owner = f"inline:{os.getpid()}"

    # -- inside the caller's transaction
    def enqueue(self, s: Session, kind: str, run_id: str, owner_id: str, *, idempotency_key: str | None = None,
                request_hash: str | None = None, request_id: str | None = None) -> JobRow:
        if kind not in JOB_KINDS:
            raise ValueError(f"unknown job kind {kind!r}")
        now = utcnow()
        job = JobRow(id=new_id("job_"), kind=kind, solver_run_id=run_id if kind == "solver_run" else None,
                     finance_run_id=run_id if kind == "finance_run" else None, owner_id=owner_id, status="queued",
                     priority=0, attempts=0, max_attempts=self.ctx.settings.job_max_attempts, run_after=now,
                     cancel_requested=False, idempotency_key=idempotency_key, request_hash=request_hash,
                     request_id=request_id, created_at=now, updated_at=now)
        s.add(job)
        s.flush()
        return job

    def request_cancel(self, s: Session, kind: str, run_id: str) -> str | None:
        job = s.scalars(select(JobRow).where(_job_fk(kind) == run_id)).first()
        if job is None:
            return None   # legacy run without a job row
        job.cancel_requested = True
        job.updated_at = utcnow()
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = job.updated_at
        return job.id

    # -- after commit
    def dispatch(self, job: JobRow) -> None:
        ctx = self.ctx
        kind = job.kind
        run_id = job.solver_run_id if kind == "solver_run" else job.finance_run_id
        assert run_id is not None
        token = uuid.uuid4().hex
        now = utcnow()
        with system_scope(), ctx.write_guard(), ctx.db.write() as s:
            res = s.execute(update(JobRow).where(JobRow.id == job.id, JobRow.status == "queued").values(
                status="running", attempts=JobRow.attempts + 1, lease_owner=self.owner, lease_token=token,
                lease_expires_at=None, heartbeat_at=None, started_at=func.coalesce(JobRow.started_at, now),
                updated_at=now).execution_options(synchronize_session=False))
            claimed = res.rowcount == 1
        if not claimed:
            return   # cancelled between commit and dispatch: nothing to run
        handler = _handler(kind)
        job_id = job.id

        def _run(rid: str, ev: threading.Event) -> None:
            with system_scope():
                try:
                    handler(ctx, rid, ev)
                finally:
                    self._finish(job_id, kind, rid, token)

        if ctx.executor.submit(run_id, _run) is None:   # executor closed: put the job back (recovery handles it)
            with system_scope(), ctx.write_guard(), ctx.db.write() as s:
                s.execute(update(JobRow).where(JobRow.id == job_id, JobRow.lease_token == token).values(
                    status="queued", lease_owner=None, lease_token=None, updated_at=utcnow())
                    .execution_options(synchronize_session=False))

    def _finish(self, job_id: str, kind: str, run_id: str, token: str) -> None:
        """Mirror the run's terminal status onto its job (same lease token only)."""
        try:
            with self.ctx.write_guard(), self.ctx.db.write() as s:
                run = s.get(_run_model(kind), run_id)
                if run is None:
                    return   # plan deleted: the job row went with it (ON DELETE CASCADE)
                status = _RUN_TO_JOB_STATUS.get(run.status)
                if status is None:
                    status, error = "failed", f"handler returned with the run {run.status}"
                else:
                    error = run.error if status == "failed" else None
                now = utcnow()
                s.execute(update(JobRow).where(JobRow.id == job_id, JobRow.lease_token == token,
                                               JobRow.status == "running")
                          .values(status=status, finished_at=now, updated_at=now, last_error=error,
                                  lease_token=None, lease_expires_at=None)
                          .execution_options(synchronize_session=False))
        except Exception:  # never let bookkeeping crash the executor thread
            log.exception("could not finish job %s of run %s", job_id, run_id)

    def notify_cancel(self, run_id: str) -> None:
        self.ctx.executor.cancel(run_id)

    def wait_idle(self, run_id: str, timeout: float = 30.0) -> None:
        fut = self.ctx.executor.future(run_id)
        if fut is not None:
            try:
                fut.result(timeout=timeout)
            except Exception:  # the job records its own failures
                pass

    def start(self) -> None:
        pass

    def stop(self, grace_seconds: float = 0.0) -> None:
        pass


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database.from_settings(settings, service="api")
        install_ownership(self.db, single_user=settings.single_user)
        self._executor: RunExecutor | None = None
        self._jobs: InlineJobs | None = None
        self._started = False
        self._start_lock = threading.Lock()

    def write_guard(self) -> ContextManager[Any]:
        """SQLite: the process-wide RLock (unchanged behaviour). PostgreSQL: no-op (row locks + indexes)."""
        return WRITE_LOCK if self.db.is_sqlite else contextlib.nullcontext()

    def start(self) -> None:
        """Idempotent: schema (create/upgrade), local user, recover interrupted runs, start the executor."""
        with self._start_lock:
            if self._started:
                return
            with system_scope():
                from superplanner import migrate

                self.settings.log_warnings()
                migrate.ensure_schema(self.db, self.settings)
                from .finance import run_service as finance_run_service
                from .services import run_service

                if self.settings.job_backend == "queue":
                    log.warning("JOB_BACKEND=queue is not implemented yet (Q2): runs execute inline in this "
                                "process; run only one API process on this database.")
                run_service.recover_interrupted_runs(self)
                finance_run_service.recover_interrupted_runs(self)
                self._executor = RunExecutor(self.settings.run_workers)
                self._jobs = InlineJobs(self)
                self._jobs.start()
                self._started = True

    @property
    def executor(self) -> RunExecutor:
        self.start()
        assert self._executor is not None
        return self._executor

    @property
    def jobs(self) -> InlineJobs:
        self.start()
        assert self._jobs is not None
        return self._jobs

    def stop(self) -> None:
        with self._start_lock:
            if self._jobs is not None:
                self._jobs.stop(self.settings.worker_shutdown_grace_seconds)
                self._jobs = None
            if self._executor is not None:
                self._executor.shutdown()
                self._executor = None
            self._started = False
            self.db.dispose()


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    ctx.start()
    return ctx
