"""Job queue types (PHASE2B 2.2-2.6): kinds, statuses, errors, the `Lease` with fencing, the `JobQueue` protocol.

A `Lease` is what a handler (`run_service.run_job`, `finance.run_service.run_job`) receives for one claim of one job:
`fence(s)` proves inside the caller's transaction that this claim still owns the job (status `running` and the
same `lease_token`), `finish(s, status)` flips the job to its terminal status in the same transaction as the run's
terminal write. Both raise `LeaseLost` once `lost` is set (review R6: a lost lease never writes `cancelled`).
"""

from __future__ import annotations

import random
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, ContextManager, Literal, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover
    from ..api.config import Settings
    from ..api.db import Database, JobRow

JobKind = Literal["solver_run", "finance_run", "aps_run"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
JOB_KINDS: tuple[str, ...] = ("solver_run", "finance_run", "aps_run")
#: kind -> the `jobs` column that references its run (exactly one is set, `ck_jobs_one_target`)
RUN_ID_COLUMN: dict[str, str] = {"solver_run": "solver_run_id", "finance_run": "finance_run_id",
                                 "aps_run": "aps_run_id"}
TERMINAL_JOB_STATUSES: tuple[str, ...] = ("succeeded", "failed", "cancelled")
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("queued", "running")
RUN_TO_JOB_STATUS = {"completed": "succeeded", "failed": "failed", "cancelled": "cancelled"}

RESTART_ERROR = "Server restarted before the run finished."
WORKER_LOST_ERROR = "The run was interrupted {n} times and was stopped."
NOTIFY_CHANNEL = "sp_jobs"
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

RequeueReason = Literal["lease_expired", "transient_error", "worker_shutdown"]


class LeaseLost(Exception):
    """Fencing failed: another worker owns the job, the job row is gone, or this worker gave the lease up."""


class RetryableJobError(Exception):
    """Infrastructure failure (DB connection lost, ...): the worker requeues the job (2.6)."""


def is_transient_db_error(exc: BaseException) -> bool:
    """OperationalError / InterfaceError / a DBAPIError with an invalidated connection (B 2.6). IntegrityError,
    DataError etc. are deterministic and therefore not retried."""
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    return isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False))


class RuntimeContext(Protocol):
    """What handlers may use. `AppContext` and `jobs.worker.WorkerContext` both satisfy it."""

    settings: "Settings"
    db: "Database"

    def write_guard(self) -> ContextManager[Any]: ...


def db_now(s: Session) -> datetime:
    """Database clock (lease times never use the worker's clock)."""
    from sqlalchemy import func

    value = s.scalar(select(func.now()))
    if value is not None:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)   # pragma: no cover - now() is never NULL


def backoff_seconds(attempts: int, base: float, maximum: float, rng: Callable[[float, float], float] | None = None
                    ) -> float:
    """`min(max, base * 2 ** (a - 1)) * uniform(1.0, 1.2)` (B 2.6)."""
    a = max(1, int(attempts))
    uniform = rng or random.uniform
    return min(maximum, base * 2 ** (a - 1)) * uniform(1.0, 1.2)


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Lease:
    """One claim of one job. Thread-safe flags; DB checks run in the caller's transaction."""

    def __init__(self, job_id: str, token: str, attempt: int, kind: str, run_id: str, *,
                 cancel_event: threading.Event | None = None, max_attempts: int = 1,
                 request_id: str | None = None, owner: str | None = None):
        self.job_id = job_id
        self.token = token
        self.attempt = attempt
        self.kind = kind
        self.run_id = run_id
        self.max_attempts = max_attempts
        self.request_id = request_id
        self.owner = owner
        self.cancel_event = cancel_event if cancel_event is not None else threading.Event()
        self.lost = threading.Event()
        self.outcome: str | None = None          # succeeded | failed | cancelled | requeued | lease_lost
        self.claimed_monotonic: float | None = None
        self.queue_wait_seconds: float | None = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Lease(job={self.job_id}, run={self.run_id}, attempt={self.attempt}, lost={self.lost.is_set()})"

    def mark_lost(self) -> None:
        """Lost FIRST, then the cancel event (R6), so every terminal write sees `lost` before the engine stops."""
        self.lost.set()
        self.cancel_event.set()

    def fence(self, s: Session) -> None:
        """In the caller's transaction, AFTER locking the run row (lock order run -> job): lock the job row and raise
        LeaseLost unless it is still `running` with this token."""
        from ..api.db import JobRow

        if self.lost.is_set():
            raise LeaseLost(f"lease of job {self.job_id} was given up")
        row = s.execute(select(JobRow.status, JobRow.lease_token).where(JobRow.id == self.job_id)
                        .with_for_update()).first()
        if row is None or row.status != "running" or row.lease_token != self.token:
            raise LeaseLost(f"job {self.job_id} is no longer held by this lease")

    def finish(self, s: Session, status: Literal["succeeded", "failed", "cancelled"],
               error: str | None = None) -> None:
        """fence(s), then the job's terminal update in the same transaction as the run's terminal write.
        `lease_owner` is kept (last executor)."""
        from ..api.db import JobRow, utcnow

        self.fence(s)
        now = utcnow()
        s.execute(update(JobRow).where(JobRow.id == self.job_id, JobRow.lease_token == self.token)
                  .values(status=status, finished_at=now, updated_at=now, last_error=error, lease_token=None,
                          lease_expires_at=None)
                  .execution_options(synchronize_session=False))
        self.outcome = status


Handler = Callable[[RuntimeContext, str, Lease], None]


def handler_for(kind: str) -> Handler:
    """`HANDLERS[kind]`, resolved at call time (tests monkeypatch module attributes of the run services)."""
    if kind == "solver_run":
        from ..api.services import run_service

        return run_service.run_job
    if kind == "finance_run":
        from ..api.finance import run_service as finance_run_service

        return finance_run_service.run_job
    if kind == "aps_run":
        from ..api.mfg.services import aps as aps_service

        return aps_service.run_job
    raise ValueError(f"unknown job kind {kind!r}")


class _Handlers(dict):
    def __missing__(self, kind: str) -> Handler:
        return handler_for(kind)


HANDLERS: dict[str, Handler] = _Handlers()


class JobQueue(Protocol):
    backend: Literal["inline", "queue"]

    def enqueue(self, s: Session, kind: str, run_id: str, owner_id: str, *, idempotency_key: str | None = None,
                request_hash: str | None = None, request_id: str | None = None) -> "JobRow": ...

    def dispatch(self, job: "JobRow") -> None: ...

    def request_cancel(self, s: Session, kind: str, run_id: str) -> str | None: ...

    def notify_cancel(self, run_id: str) -> None: ...

    def wait_idle(self, run_id: str, timeout: float = 30.0) -> None: ...

    def start(self) -> None: ...

    def stop(self, grace_seconds: float) -> None: ...


def lease_deadline(now: datetime, seconds: float) -> datetime:
    return now + timedelta(seconds=seconds)
