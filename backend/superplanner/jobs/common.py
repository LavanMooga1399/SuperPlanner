"""Job-row operations shared by both backends (PHASE2B 2.3-2.7): enqueue, cancel, requeue-or-fail, mirror, orphans.

All of these are ORM statements on `jobs`; only the claim/heartbeat/reaper scan in `jobs/pg.py` is
raw SQL. Lock order everywhere: plan/problem -> run -> job.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from .types import (ACTIVE_RUN_STATUSES, JOB_KINDS, RESTART_ERROR, RUN_ID_COLUMN, RUN_TO_JOB_STATUS,
                    WORKER_LOST_ERROR, Lease, LeaseLost, backoff_seconds, db_now, iso_z)

log = logging.getLogger("superplanner.jobs")


# ---------------------------------------------------------------- per-kind plumbing (lazy imports: no cycles)

def run_model(kind: str) -> Any:
    if kind == "solver_run":
        from ..api.db import SolverRunRow

        return SolverRunRow
    if kind == "finance_run":
        from ..api.finance.db_models import FinanceRunRow

        return FinanceRunRow
    if kind == "aps_run":
        from ..api.mfg.db_models_m3 import MfgApsRunRow

        return MfgApsRunRow
    if kind == "aps_simulation":
        from ..api.mfg.db_models_m4 import MfgApsSimulationRow

        return MfgApsSimulationRow
    raise ValueError(f"unknown job kind {kind!r}")


def set_run_error(run: Any, message: str | None) -> None:
    """Kind-aware run error (m5): APS runs store `{code, message}`, solver / finance runs a string."""
    from ..api.mfg.db_models_m3 import MfgApsRunRow
    from ..api.mfg.db_models_m4 import MfgApsSimulationRow

    if isinstance(run, MfgApsRunRow) and message is not None:
        run.error = {"code": "APS_RUN_FAILED", "message": str(message)[:500]}
    elif isinstance(run, MfgApsSimulationRow) and message is not None:
        run.error = {"code": "APS_SIMULATION_FAILED", "message": str(message)[:500]}
    else:
        run.error = message


def job_fk(kind: str) -> Any:
    from ..api.db import JobRow

    return getattr(JobRow, RUN_ID_COLUMN[kind])


def run_id_of(job: Any) -> str:
    rid = getattr(job, RUN_ID_COLUMN[job.kind])
    assert rid is not None, f"job {job.id} has no run"
    return rid


def add_run_event(kind: str, s: Session, run_id: str, type_: str, fields: dict[str, Any]) -> None:
    if kind == "solver_run":
        from ..api.services import run_service

        run_service.add_event(s, run_id, type_, fields, 0.0)
    elif kind in ("aps_run", "aps_simulation"):
        return   # APS runs have no event log (progress lives on the run row, M3-DESIGN 10)
    else:
        from ..api.finance import run_service as finance_run_service

        finance_run_service.add_event(s, run_id, type_, fields, 0.0)


def cancelled_fields(kind: str) -> dict[str, Any]:
    return {"primary_schedule_id": None, "schedule_ids": []} if kind == "solver_run" else {}


def lock_run(s: Session, kind: str, run_id: str) -> Any:
    """The run row FOR NO KEY UPDATE, or None if it is gone."""
    return s.get(run_model(kind), run_id, with_for_update={"key_share": True})


# ---------------------------------------------------------------- enqueue / cancel (API transaction)

def new_job(s: Session, kind: str, run_id: str, owner_id: str, max_attempts: int, *,
            idempotency_key: str | None = None, request_hash: str | None = None,
            request_id: str | None = None) -> Any:
    from ..api.db import JobRow, new_id, utcnow

    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    now = utcnow()
    job = JobRow(id=new_id("job_"), kind=kind, solver_run_id=run_id if kind == "solver_run" else None,
                 finance_run_id=run_id if kind == "finance_run" else None,
                 aps_run_id=run_id if kind == "aps_run" else None,
                 aps_simulation_id=run_id if kind == "aps_simulation" else None, owner_id=owner_id, status="queued",
                 priority=0, attempts=0, max_attempts=max_attempts, run_after=now, cancel_requested=False,
                 idempotency_key=idempotency_key, request_hash=request_hash, request_id=request_id,
                 created_at=now, updated_at=now)
    s.add(job)
    s.flush()
    return job


def request_cancel(s: Session, kind: str, run_id: str) -> str | None:
    """After the run row is locked: job.cancel_requested; a queued job becomes cancelled (never claimed)."""
    from ..api.db import JobRow, utcnow

    job = s.scalars(select(JobRow).where(job_fk(kind) == run_id).with_for_update()).first()
    if job is None:
        return None   # legacy run without a job row
    now = utcnow()
    job.cancel_requested = True
    job.updated_at = now
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = now
    return job.id


def current_request_id() -> str | None:
    """The HTTP request id of the enqueuing request, if the request-id middleware (Q5) is installed."""
    try:
        from ..obs import request_context  # type: ignore[attr-defined]
    except Exception:
        return None
    getter = getattr(request_context, "current_request_id", None)
    try:
        return getter() if callable(getter) else None
    except Exception:  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------- requeue / fail (worker, reaper, shutdown)

def requeue_or_fail(s: Session, job: Any, run: Any, reason: str, settings: Any) -> str:
    """Apply the 2.6 rule to a locked `running` job whose run row is locked too. Returns the job's new status.

    - run gone/finished meanwhile -> the job mirrors the run (no requeue of a finished run);
    - run cancel-requested -> cancelled (+ run_cancelled), the user asked for it;
    - attempts < max_attempts -> queued with backoff (`worker_shutdown`: attempt not consumed, no delay),
      run -> queued + `run_requeued`;
    - else failed with WORKER_LOST_ERROR (+ run_failed).
    """
    from ..api.db import utcnow

    kind = job.kind
    now = db_now(s)
    wall = utcnow()
    common = dict(lease_token=None, lease_expires_at=None, updated_at=wall)
    if run is None or run.status not in ACTIVE_RUN_STATUSES:
        status = RUN_TO_JOB_STATUS.get(run.status, "failed") if run is not None else "failed"
        _set(s, job, status=status, finished_at=wall, last_error=reason, **common)
        return status
    if run.cancel_requested or job.cancel_requested:
        run.status = "cancelled"
        run.finished_at = wall
        add_run_event(kind, s, run.id, "run_cancelled", cancelled_fields(kind))
        _set(s, job, status="cancelled", finished_at=wall, last_error=reason, **common)
        return "cancelled"
    attempts = int(job.attempts)
    if reason == "worker_shutdown":
        attempts = max(0, attempts - 1)   # a graceful shutdown does not consume an attempt
        delay = 0.0
    else:
        delay = backoff_seconds(attempts, settings.job_backoff_base_seconds, settings.job_backoff_max_seconds)
    if attempts < int(job.max_attempts):
        retry_at = now + timedelta(seconds=delay)
        _set(s, job, status="queued", attempts=attempts, run_after=retry_at, lease_owner=None, heartbeat_at=None,
             last_error=reason, **common)
        run.status = "queued"
        add_run_event(kind, s, run.id, "run_requeued", {"attempt": attempts + 1, "max_attempts": int(job.max_attempts),
                                                        "reason": reason, "retry_at": iso_z(retry_at)})
        log.info("job.requeued job=%s run=%s attempt=%d reason=%s", job.id, run.id, attempts + 1, reason)
        return "queued"
    error = WORKER_LOST_ERROR.format(n=attempts)
    run.status = "failed"
    set_run_error(run, error)
    run.finished_at = wall
    add_run_event(kind, s, run.id, "run_failed", {"error": error})
    _set(s, job, status="failed", finished_at=wall, last_error=f"{reason}: max attempts reached", **common)
    log.warning("job.failed job=%s run=%s: %s", job.id, run.id, error)
    return "failed"


def _set(s: Session, job: Any, **values: Any) -> None:
    for k, v in values.items():
        setattr(job, k, v)
    s.flush()


def requeue_lease(ctx: Any, lease: Lease, reason: str) -> str:
    """Fenced requeue of one of our own leases in a new transaction (transient error, shutdown).
    Raises LeaseLost if the job is no longer ours (already finished, taken over)."""
    from ..api.db import JobRow
    from ..api.db.ownership import system_scope

    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        run = lock_run(s, lease.kind, lease.run_id)
        job = s.get(JobRow, lease.job_id, with_for_update=True)
        if job is None or job.status != "running" or job.lease_token != lease.token:
            raise LeaseLost(f"job {lease.job_id} is no longer held by this lease")
        status = requeue_or_fail(s, job, run, reason, ctx.settings)
    lease.outcome = "requeued" if status == "queued" else status
    return status


def mirror_finish(ctx: Any, lease: Lease, fallback_error: str) -> str | None:
    """Safety net after a handler returned without finishing its job (should not happen): terminal run -> matching
    job status; still-active run -> run and job failed. Fenced; returns the status written or None."""
    from ..api.db import JobRow, utcnow
    from ..api.db.ownership import system_scope

    if lease.lost.is_set():
        return None
    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        run = lock_run(s, lease.kind, lease.run_id)
        job = s.get(JobRow, lease.job_id, with_for_update=True)
        if job is None or job.status != "running" or job.lease_token != lease.token:
            return None
        wall = utcnow()
        if run is not None and run.status in ACTIVE_RUN_STATUSES:
            run.status = "failed"
            set_run_error(run, fallback_error)
            run.finished_at = wall
            add_run_event(lease.kind, s, run.id, "run_failed", {"error": fallback_error})
            status, error = "failed", fallback_error
        else:
            status = RUN_TO_JOB_STATUS.get(run.status, "failed") if run is not None else "failed"
            error = (run.error if run is not None and status == "failed" else None)
            if error is not None and not isinstance(error, str):   # APS runs store a JSON error
                error = str(error.get("message", error)) if isinstance(error, dict) else str(error)
        _set(s, job, status=status, finished_at=wall, updated_at=wall, last_error=error, lease_token=None,
             lease_expires_at=None)
    lease.outcome = status
    return status


def fail_orphan_runs(ctx: Any) -> int:
    """Queue mode: runs queued/running without a job row (legacy data, direct inserts) -> failed (B 2.5.3)."""
    from ..api.db import JobRow, utcnow
    from ..api.db.ownership import system_scope

    n = 0
    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        for kind in JOB_KINDS:
            model = run_model(kind)
            fk = job_fk(kind)
            ids = list(s.scalars(select(model.id).where(model.status.in_(ACTIVE_RUN_STATUSES),
                                                        ~exists(select(JobRow.id).where(fk == model.id)))).all())
            for rid in ids:
                run = lock_run(s, kind, rid)
                if run is None or run.status not in ACTIVE_RUN_STATUSES:
                    continue
                run.status = "failed"
                set_run_error(run, RESTART_ERROR)
                run.finished_at = utcnow()
                add_run_event(kind, s, rid, "run_failed", {"error": RESTART_ERROR})
                n += 1
    if n:
        log.info("failed %d orphan run(s) without a job", n)
    return n


def fail_inline_leftovers(ctx: Any) -> int:
    """Queue-mode startup: `running` jobs without a lease expiry -> failed with RESTART_ERROR (+ their runs).

    Only the inline backend writes `status='running'` with `lease_expires_at = NULL` (`lease_owner = 'inline:<pid>'`).
    Such a job is left behind when an inline process on this database died mid-run (kill -9, closed console). The
    reaper never selects it (`NULL < now()` is not true), `fail_orphan_runs` skips it (it has a job row) and no
    worker can claim it, so its run would stay active forever and block new runs (one-active-run index). Inline
    restart recovery fails such runs too, so the outcome matches. Mixing an inline and a queue process on one
    database at the same time is not supported; this assumes the inline process is gone.
    """
    from ..api.db import JobRow, utcnow
    from ..api.db.ownership import system_scope

    n = 0
    with system_scope():
        with ctx.db.read() as s:
            rows = s.execute(select(JobRow.id, JobRow.kind, JobRow.solver_run_id, JobRow.finance_run_id,
                                    JobRow.aps_run_id, JobRow.aps_simulation_id)
                             .where(JobRow.status == "running", JobRow.lease_expires_at.is_(None))).all()
        for row in rows:
            run_id = getattr(row, RUN_ID_COLUMN[row.kind])
            with ctx.write_guard(), ctx.db.write() as s:
                run = lock_run(s, row.kind, run_id) if run_id else None
                job = s.get(JobRow, row.id, with_for_update=True)
                if job is None or job.status != "running" or job.lease_expires_at is not None:
                    continue   # finished or claimed meanwhile
                wall = utcnow()
                if run is not None and run.status in ACTIVE_RUN_STATUSES:
                    run.status = "failed"
                    set_run_error(run, RESTART_ERROR)
                    run.finished_at = wall
                    add_run_event(row.kind, s, run.id, "run_failed", {"error": RESTART_ERROR})
                    status = "failed"
                else:
                    status = RUN_TO_JOB_STATUS.get(run.status, "failed") if run is not None else "failed"
                _set(s, job, status=status, finished_at=wall, last_error=RESTART_ERROR, lease_token=None,
                     lease_expires_at=None, updated_at=wall)
                n += 1
    if n:
        log.info("failed %d job(s) left running by an inline-backend process", n)
    return n


def queue_start_recovery(ctx: Any) -> dict[str, int]:
    """Queue-mode startup (API `AppContext.start` and `superplanner.worker`): inline leftovers, then orphan runs."""
    return {"inline_leftovers": fail_inline_leftovers(ctx), "orphan_runs": fail_orphan_runs(ctx)}


def job_for_run(s: Session, kind: str, run_id: str) -> Any:
    from ..api.db import JobRow

    return s.scalars(select(JobRow).where(job_fk(kind) == run_id)).first()


def mark_jobs_failed(s: Session, kind: str, run_ids: list[str], error: str) -> None:
    """Inline recovery: jobs of runs failed at startup."""
    from ..api.db import JobRow, utcnow

    if not run_ids:
        return
    now = utcnow()
    s.execute(update(JobRow).where(job_fk(kind).in_(run_ids), JobRow.status.in_(("queued", "running")))
              .values(status="failed", last_error=error, finished_at=now, updated_at=now, lease_token=None,
                      lease_expires_at=None)
              .execution_options(synchronize_session=False))
