"""`queue` backend on PostgreSQL (PHASE2B 2.2, 2.5): claim with `FOR UPDATE SKIP LOCKED`, lease heartbeat, reaper,
worker registry, LISTEN/NOTIFY wake-up, maintenance. The only raw SQL outside migrations (B 3.5.6); every
statement uses the database clock (`now()`).

`PgQueue(ctx)` is the API-side `JobQueue`: enqueue (+ `pg_notify`, delivered on commit), cancel flag, optional
embedded worker threads (`WORKER_EMBEDDED`, a `jobs.worker.WorkerLoop` inside the API process).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import common
from .types import NOTIFY_CHANNEL, TERMINAL_JOB_STATUSES, Lease, db_now

if TYPE_CHECKING:  # pragma: no cover
    from ..api.context import AppContext
    from .worker import WorkerLoop

log = logging.getLogger("superplanner.jobs")

CLAIM_SQL = text("""
WITH next AS (
  SELECT id FROM jobs
   WHERE status = 'queued' AND run_after <= now() AND kind = ANY(:kinds)
   ORDER BY priority DESC, run_after, created_at, id
   LIMIT 1
   FOR UPDATE SKIP LOCKED)
UPDATE jobs AS j
   SET status = 'running', attempts = j.attempts + 1, lease_owner = :worker_id, lease_token = :token,
       lease_expires_at = now() + make_interval(secs => :lease_seconds), heartbeat_at = now(),
       started_at = COALESCE(j.started_at, now()), updated_at = now()
  FROM next WHERE j.id = next.id
RETURNING j.id, j.kind, j.solver_run_id, j.finance_run_id, j.attempts, j.max_attempts, j.request_id, j.owner_id,
          EXTRACT(EPOCH FROM (now() - j.run_after)) AS queue_wait
""")

CHECK_SQL = text("SELECT id, lease_token, status, cancel_requested FROM jobs WHERE id = ANY(:ids)")

RENEW_SQL = text("""
UPDATE jobs SET heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => :lease_seconds),
       updated_at = now()
 WHERE id = :id AND lease_token = :token AND status = 'running'
RETURNING cancel_requested
""")

EXPIRED_SQL = text("""
SELECT id, kind, solver_run_id, finance_run_id FROM jobs
 WHERE status = 'running' AND lease_expires_at < now()
 ORDER BY lease_expires_at LIMIT 100
""")

LOCK_EXPIRED_SQL = text("""
SELECT id FROM jobs WHERE id = :id AND status = 'running' AND lease_expires_at < now() FOR UPDATE SKIP LOCKED
""")

UPSERT_WORKER_SQL = text("""
INSERT INTO job_workers (id, hostname, pid, kinds, concurrency, busy, started_at, heartbeat_at, stopped_at)
VALUES (:id, :hostname, :pid, CAST(:kinds AS JSONB), :concurrency, :busy, now(), now(), NULL)
ON CONFLICT (id) DO UPDATE SET busy = EXCLUDED.busy, heartbeat_at = now(), stopped_at = NULL,
       concurrency = EXCLUDED.concurrency, kinds = EXCLUDED.kinds
""")

STOP_WORKER_SQL = text("UPDATE job_workers SET stopped_at = now(), busy = 0, heartbeat_at = now() WHERE id = :id")

PRUNE_JOBS_SQL = text("""
DELETE FROM jobs WHERE id IN (
  SELECT id FROM jobs WHERE status IN ('succeeded', 'failed', 'cancelled')
     AND finished_at < now() - make_interval(days => :days) LIMIT 1000)
""")

PRUNE_WORKERS_SQL = text("DELETE FROM job_workers WHERE heartbeat_at < now() - interval '1 day'")

ALIVE_WORKERS_SQL = text("""
SELECT count(*) FROM job_workers WHERE stopped_at IS NULL AND heartbeat_at > now() - make_interval(secs => :secs)
""")


@dataclass
class Claimed:
    job_id: str
    kind: str
    run_id: str
    attempts: int
    max_attempts: int
    request_id: str | None
    owner_id: str
    queue_wait: float


# ---------------------------------------------------------------- statements (each in its own short transaction)

def claim(s: Session, kinds: list[str], worker_id: str, token: str, lease_seconds: float) -> Claimed | None:
    row = s.execute(CLAIM_SQL, {"kinds": list(kinds), "worker_id": worker_id, "token": token,
                                "lease_seconds": float(lease_seconds)}).first()
    if row is None:
        return None
    run_id = row.solver_run_id if row.kind == "solver_run" else row.finance_run_id
    return Claimed(row.id, row.kind, run_id, int(row.attempts), int(row.max_attempts), row.request_id, row.owner_id,
                   float(row.queue_wait or 0.0))


def check_leases(s: Session, job_ids: list[str]) -> dict[str, Any]:
    return {r.id: r for r in s.execute(CHECK_SQL, {"ids": list(job_ids)}).all()}


def renew(s: Session, job_id: str, token: str, lease_seconds: float) -> bool | None:
    """None if the lease is gone (0 rows), else the job's `cancel_requested`."""
    row = s.execute(RENEW_SQL, {"id": job_id, "token": token, "lease_seconds": float(lease_seconds)}).first()
    return None if row is None else bool(row.cancel_requested)


def upsert_worker(s: Session, worker_id: str, hostname: str, pid: int, kinds: list[str], concurrency: int,
                  busy: int) -> None:
    s.execute(UPSERT_WORKER_SQL, {"id": worker_id, "hostname": hostname[:255], "pid": pid,
                                  "kinds": json.dumps(list(kinds)), "concurrency": concurrency, "busy": busy})


def stop_worker(s: Session, worker_id: str) -> None:
    s.execute(STOP_WORKER_SQL, {"id": worker_id})


def alive_workers(s: Session, heartbeat_seconds: float) -> int:
    return int(s.scalar(ALIVE_WORKERS_SQL, {"secs": float(3 * heartbeat_seconds)}) or 0)


def reap_expired(ctx: Any) -> dict[str, int]:
    """Requeue (or fail after max attempts) every running job whose lease expired. Returns counts by new status.

    Per job, one transaction: lock the run row first, then the job row `FOR UPDATE SKIP LOCKED` with the expiry
    condition re-checked (skip if renewed, finished or locked by its owner right now)."""
    from ..api.db import JobRow
    from ..api.db.ownership import system_scope
    from ..obs import job_metrics

    counts: dict[str, int] = {}
    with system_scope():
        with ctx.db.read() as s:
            expired = s.execute(EXPIRED_SQL).all()
        for row in expired:
            kind = row.kind
            run_id = row.solver_run_id if kind == "solver_run" else row.finance_run_id
            try:
                with ctx.write_guard(), ctx.db.write() as s:
                    run = common.lock_run(s, kind, run_id) if run_id else None
                    if s.execute(LOCK_EXPIRED_SQL, {"id": row.id}).first() is None:
                        continue
                    job = s.get(JobRow, row.id)
                    status = common.requeue_or_fail(s, job, run, "lease_expired", ctx.settings)
            except Exception:
                log.exception("reaper: could not requeue job %s", row.id)
                continue
            counts[status] = counts.get(status, 0) + 1
            job_metrics.job_failure(kind, "lease_expired")
            if status == "queued":
                job_metrics.job_finished(kind, "requeued")
            elif status == "failed":
                job_metrics.job_failure(kind, "max_attempts")
                job_metrics.job_finished(kind, "failed")
    if counts:
        log.info("reaper: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return counts


def maintenance(ctx: Any) -> dict[str, int]:
    """Retention of terminal jobs (batches of 1000), stale worker rows, expired sessions and rate-limit buckets."""
    from ..api.auth.maintenance import prune_auth_tables
    from ..api.db.ownership import system_scope

    out: dict[str, int] = {}
    with system_scope():
        with ctx.db.write() as s:
            total = 0
            for _ in range(20):   # at most 20k rows per maintenance pass
                n = s.execute(PRUNE_JOBS_SQL, {"days": int(ctx.settings.job_retention_days)}).rowcount or 0
                total += n
                if n < 1000:
                    break
            out["jobs"] = total
            out["job_workers"] = int(s.execute(PRUNE_WORKERS_SQL).rowcount or 0)
            out.update(prune_auth_tables(s, db_now(s)))
    return out


def psycopg_conninfo(url: str) -> str:
    """SQLAlchemy URL -> libpq URI for a raw psycopg connection (LISTEN)."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


# ---------------------------------------------------------------- API-side queue

class PgQueue:
    backend = "queue"

    def __init__(self, ctx: "AppContext"):
        self.ctx = ctx
        self.loop: "WorkerLoop | None" = None

    def enqueue(self, s: Session, kind: str, run_id: str, owner_id: str, *, idempotency_key: str | None = None,
                request_hash: str | None = None, request_id: str | None = None) -> Any:
        job = common.new_job(s, kind, run_id, owner_id, self.ctx.settings.job_max_attempts,
                             idempotency_key=idempotency_key, request_hash=request_hash,
                             request_id=request_id or common.current_request_id())
        job.run_after = db_now(s)   # claimable by the DB clock at once (the claim compares with now())
        s.flush()
        s.execute(text("SELECT pg_notify(:channel, :kind)"), {"channel": NOTIFY_CHANNEL, "kind": kind})
        return job

    def dispatch(self, job: Any) -> None:
        """Queue mode: nothing to do; a worker claims the committed row (NOTIFY wakes idle workers)."""

    def request_cancel(self, s: Session, kind: str, run_id: str) -> str | None:
        return common.request_cancel(s, kind, run_id)

    def notify_cancel(self, run_id: str) -> None:
        """Workers see `jobs.cancel_requested` within JOB_CANCEL_POLL_SECONDS; an embedded worker of this process
        that runs the job is told at once (same effect, lower latency)."""
        if self.loop is not None:
            self.loop.local_cancel(run_id)

    def wait_idle(self, run_id: str, timeout: float = 30.0) -> None:
        """Returns when no worker holds the run's job: terminal, queued without a lease, or gone (plan deleted).
        Waits for the in-process handler too when an embedded worker runs it. TimeoutError after `timeout`."""
        from ..api.db import JobRow
        from ..api.db.ownership import system_scope

        from sqlalchemy import or_, select

        deadline = time.monotonic() + timeout
        if self.loop is not None:
            self.loop.wait_run(run_id, timeout)
        while True:
            with system_scope(), self.ctx.db.read() as s:
                job = s.execute(select(JobRow.status, JobRow.lease_token).where(
                    or_(JobRow.solver_run_id == run_id, JobRow.finance_run_id == run_id))).first()
                idle = job is None or job.status in TERMINAL_JOB_STATUSES or (job.status == "queued"
                                                                              and job.lease_token is None)
            if idle and (self.loop is None or not self.loop.holds_run(run_id)):
                return
            if time.monotonic() > deadline:
                raise TimeoutError(f"job of run {run_id} still held after {timeout}s")
            time.sleep(0.05)

    def start(self) -> None:
        n = self.ctx.settings.embedded_workers
        if n <= 0:
            return
        from .worker import WorkerLoop, default_worker_id

        self.loop = WorkerLoop(self.ctx, concurrency=n, kinds=list(self.ctx.settings.worker_kinds),
                               worker_id=default_worker_id("api"), embedded=True)
        self.loop.start()

    def stop(self, grace_seconds: float) -> None:
        if self.loop is not None:
            self.loop.stop(grace_seconds)
            self.loop = None


def new_token() -> str:
    return uuid.uuid4().hex


def lease_from_claim(c: Claimed, token: str) -> Lease:
    return Lease(c.job_id, token, c.attempts, c.kind, c.run_id, max_attempts=c.max_attempts, request_id=c.request_id,
                 owner=c.owner_id)
