"""Finance runs (FINANCE.md 17-19): snapshots, one active run per plan, what-if, background worker on the shared
executor, throttled progress events, cancel (incl. the cancel/complete race [R11]), startup recovery, results,
comparison and CSV.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from superplanner import finance
from superplanner.finance.whatif import default_label  # not re-exported by finance/__init__ (see F.24.3)
from superplanner.jobs import common as job_common
from superplanner.jobs import idempotency
from superplanner.jobs.idempotency import Idempotency
from superplanner.jobs.types import (RESTART_ERROR, RUN_TO_JOB_STATUS, Lease, LeaseLost, RetryableJobError,
                                     RuntimeContext, is_transient_db_error)

from ..context import WRITE_LOCK, AppContext  # noqa: F401  (WRITE_LOCK re-exported for old imports)
from ..db import JobRow, new_id, utcnow
from ..db.locks import lock_parent_key_share, lock_row
from ..errors import ApiError, not_found
from ..schemas import as_utc, iso_utc
from ..services.problem_service import audit, slugify
from .db_models import FinancePlanRow, FinancePlanVersionRow, FinanceResultRow, FinanceRunEventRow, FinanceRunRow
from .schemas import WhatIfRequest, what_if_run_request
from .service import active_run, get_plan_row, load_plan, snapshot

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
TERMINAL_EVENT_TYPES = ("run_completed", "run_cancelled", "run_failed")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
MAX_LIST_ITEMS = 500
# Summary keys stored in `finance_results.summary` (FinanceResultSummary minus ids and created_at).
_SUMMARY_KEYS = ("base_plan_version", "kind", "label", "feasibility", "goals_total", "goals_on_track",
                 "goals_at_risk", "goals_off_track", "monthly_contribution_now", "what_if")


# ---------------------------------------------------------------- events

def _next_seq(s: Session, run_id: str) -> int:
    return int(s.scalar(select(func.max(FinanceRunEventRow.seq)).where(FinanceRunEventRow.run_id == run_id))
               or 0) + 1


def add_event(s: Session, run_id: str, type_: str, fields: dict[str, Any], elapsed: float, *,
              lease: Lease | None = None) -> dict[str, Any] | None:
    """Append an event; returns None (and writes nothing) if the run row is gone (plan deleted). Locks the run row
    first (FOR NO KEY UPDATE; no-op on SQLite): safe `seq` allocation with several writers (PHASE2B 2.10); then
    fences the lease when given (worker writes)."""
    if not lock_row(s, FinanceRunRow, run_id):
        return None
    if lease is not None:
        lease.fence(s)
    seq = _next_seq(s, run_id)
    now = utcnow()
    payload = {"run_id": run_id, "seq": seq, "type": type_, "ts": iso_utc(now),
               "elapsed_seconds": round(max(0.0, elapsed), 3)}
    payload.update(fields)
    s.add(FinanceRunEventRow(run_id=run_id, seq=seq, type=type_, payload=payload, created_at=now))
    s.flush()
    return payload


def list_events(ctx: AppContext, run_id: str, after: int = 0) -> tuple[list[dict[str, Any]], str]:
    with ctx.db.read() as s:
        run = s.get(FinanceRunRow, run_id)
        if run is None:
            raise not_found("Finance run", run_id)
        rows = s.scalars(select(FinanceRunEventRow).where(FinanceRunEventRow.run_id == run_id,
                                                          FinanceRunEventRow.seq > after)
                         .order_by(FinanceRunEventRow.seq)).all()
        return [r.payload for r in rows], run.status


# ---------------------------------------------------------------- serialization

def _result_id_for(s: Session, run_id: str) -> str | None:
    return s.scalars(select(FinanceResultRow.id).where(FinanceResultRow.run_id == run_id)).first()


def run_dict(s: Session, run: FinanceRunRow) -> dict[str, Any]:
    started, finished = as_utc(run.started_at), as_utc(run.finished_at)
    elapsed = round((finished - started).total_seconds(), 3) if started and finished else None
    return {"id": run.id, "plan_id": run.plan_id, "plan_version_id": run.plan_version_id, "kind": run.kind,
            "label": run.label, "status": run.status, "request": run.request, "what_if": run.what_if,
            "engine_version": run.engine_version, "feasibility": run.feasibility,
            "result_id": _result_id_for(s, run.id), "error": run.error, "cancel_requested": bool(run.cancel_requested),
            "created_at": iso_utc(run.created_at), "started_at": iso_utc(run.started_at),
            "finished_at": iso_utc(run.finished_at), "elapsed_seconds": elapsed}


def created_dict(run: FinanceRunRow) -> dict[str, Any]:
    return {"run_id": run.id, "status": run.status, "plan_version_id": run.plan_version_id,
            "status_url": f"{API_PREFIX}/finance/runs/{run.id}",
            "events_url": f"{API_PREFIX}/finance/runs/{run.id}/events"}


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        run = s.get(FinanceRunRow, run_id)
        if run is None:
            raise not_found("Finance run", run_id)
        return run_dict(s, run)


def list_runs(ctx: AppContext, plan_id: str) -> list[dict[str, Any]]:
    with ctx.db.read() as s:
        get_plan_row(s, plan_id)
        runs = s.scalars(select(FinanceRunRow).where(FinanceRunRow.plan_id == plan_id)
                         .order_by(FinanceRunRow.created_at.desc(), FinanceRunRow.id.desc())
                         .limit(MAX_LIST_ITEMS)).all()
        return [run_dict(s, r) for r in runs]


def result_summary(row: FinanceResultRow) -> dict[str, Any]:
    out: dict[str, Any] = {"id": row.id, "plan_id": row.plan_id, "run_id": row.run_id,
                           "plan_version_id": row.plan_version_id}
    for k in _SUMMARY_KEYS:
        out[k] = row.summary.get(k)
    out["kind"] = row.kind
    out["label"] = row.label
    out["feasibility"] = row.feasibility
    out["created_at"] = iso_utc(row.created_at)
    # key order as in F.14 FinanceResultSummary
    order = ("id", "plan_id", "run_id", "plan_version_id", "base_plan_version", "kind", "label", "feasibility",
             "goals_total", "goals_on_track", "goals_at_risk", "goals_off_track", "monthly_contribution_now",
             "created_at", "what_if")
    return {k: out.get(k) for k in order}


# ---------------------------------------------------------------- creation

def preflight_or_422(plan: finance.FinancePlan) -> None:
    report = finance.preflight(plan)
    if report.ok:
        return
    errors = [i for i in report.issues if i.severity == "error"]
    n = len(errors)
    raise ApiError(422, "PREFLIGHT_FAILED", f"Fix {n} problem{'s' if n != 1 else ''} before building the plan.",
                   {"issues": [i.model_dump(mode="json") for i in errors]})


def _run_already_active(run: FinanceRunRow) -> ApiError:
    return ApiError(409, "RUN_ALREADY_ACTIVE",
                    "A finance run is already in progress for this plan; wait for it or cancel it.",
                    {"run_id": run.id, "kind": run.kind})


def _insert_run(s: Session, row: FinancePlanRow, pv: FinancePlanVersionRow, kind: str,
                req: finance.FinanceRunRequest, label: str | None, what_if: dict[str, Any] | None) -> FinanceRunRow:
    run = FinanceRunRow(id=new_id("frun_"), plan_id=row.id, plan_version_id=pv.id, kind=kind,
                        label=(label or None) and label[:100], status="queued", request=req.model_dump(mode="json"),
                        what_if=what_if, seed=req.seed, engine_version=finance.__version__, cancel_requested=False,
                        created_at=utcnow())
    s.add(run)
    s.flush()
    add_event(s, run.id, "run_queued", {"plan_version_id": pv.id, "kind": kind}, 0.0)
    audit(s, "finance_run", run.id, "finance_run.created",
          {"plan_id": row.id, "plan_version_id": pv.id, "kind": kind})
    return run


def enqueue(ctx: AppContext, s: Session, run: FinanceRunRow, idem: Idempotency | None = None) -> JobRow:
    return ctx.jobs.enqueue(s, "finance_run", run.id, run.owner_id, idempotency_key=idem.key if idem else None,
                            request_hash=idem.request_hash if idem else None)


def created_from_job(s: Session, job: JobRow) -> dict[str, Any]:
    """Idempotent replay body: the creation body of the job's run with its current status (PHASE2B 2.8)."""
    run = s.get(FinanceRunRow, job.finance_run_id) if job.finance_run_id else None
    if run is None:
        raise idempotency._mismatch()   # the key belongs to another kind of request
    return created_dict(run)


def _with_idempotency(ctx: AppContext, idem: Idempotency | None, fn: Any) -> dict[str, Any]:
    try:
        return fn()
    except IntegrityError as exc:
        if idem is not None and idempotency.is_key_conflict(exc):
            idempotency.replay_after_conflict(ctx, idem, created_from_job)
        raise


def create_run(ctx: AppContext, plan_id: str, req: finance.FinanceRunRequest,
               idem: Idempotency | None = None) -> dict[str, Any]:
    """Raises `idempotency.Replay` for a replayed Idempotency-Key (the route answers 202 + header)."""
    return _with_idempotency(ctx, idem, lambda: _create_run(ctx, plan_id, req, idem))


def _create_run(ctx: AppContext, plan_id: str, req: finance.FinanceRunRequest,
                idem: Idempotency | None) -> dict[str, Any]:
    with ctx.write_guard():
        with ctx.db.write() as s:
            row = get_plan_row(s, plan_id, lock=True)   # the plan lock enforces one active run (R5)
            idempotency.lookup(s, idem, ctx.settings.idempotency_ttl_hours, created_from_job)   # after the lock
            active = active_run(s, plan_id)
            if active is not None:
                raise _run_already_active(active)
            preflight_or_422(load_plan(row.document))
            pv = snapshot(s, row)
            run = _insert_run(s, row, pv, "baseline", req, req.label, None)
            job = enqueue(ctx, s, run, idem)
            out = created_dict(run)
        ctx.jobs.dispatch(job)
    return out


def _cancel_in_session(ctx: AppContext, s: Session, run: FinanceRunRow) -> str:
    """Mark a queued/running run cancel-requested (queued -> cancelled immediately). Returns the new status."""
    run.cancel_requested = True
    at_cancel = run.status
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = utcnow()
        add_event(s, run.id, "run_cancelled", {}, 0.0)
    ctx.jobs.request_cancel(s, "finance_run", run.id)
    audit(s, "finance_run", run.id, "finance_run.cancelled", {"status_at_cancel": at_cancel})
    return run.status


def create_what_if(ctx: AppContext, plan_id: str, body: WhatIfRequest,
                   idem: Idempotency | None = None) -> dict[str, Any]:
    """Raises `idempotency.Replay` for a replayed Idempotency-Key (the route answers 202 + header)."""
    return _with_idempotency(ctx, idem, lambda: _create_what_if(ctx, plan_id, body, idem))


def _create_what_if(ctx: AppContext, plan_id: str, body: WhatIfRequest, idem: Idempotency | None) -> dict[str, Any]:
    req = what_if_run_request(body.run)
    replaced: str | None = None
    with ctx.write_guard():
        with ctx.db.write() as s:
            row = get_plan_row(s, plan_id, lock=True)
            idempotency.lookup(s, idem, ctx.settings.idempotency_ttl_hours, created_from_job)   # after the lock
            if body.expected_plan_version is not None and body.expected_plan_version != row.version:
                raise ApiError(412, "VERSION_MISMATCH",
                               f"The plan was changed elsewhere (now version {row.version}, "
                               f"you edited {body.expected_plan_version}).", {"current_version": row.version})
            # Base document [R14]: the snapshot of `base_result_id` when given, else the current document.
            if body.base_result_id is not None:
                base = s.get(FinanceResultRow, body.base_result_id)
                if base is None or base.plan_id != plan_id:
                    raise not_found("Finance result", body.base_result_id)
                if base.kind != "baseline":
                    raise ApiError(422, "VALIDATION_ERROR", "base_result_id must be a baseline result of this plan.",
                                   {"errors": [{"loc": ["body", "base_result_id"], "type": "value_error",
                                                "msg": "a what-if result cannot be the base of another what-if"}]})
                base_pv = s.get(FinancePlanVersionRow, base.plan_version_id)
                base_doc, base_version = base_pv.document, base_pv.base_version
            else:
                base_doc, base_version = row.document, row.version
            base_plan = load_plan(base_doc)
            try:
                derived = finance.apply_what_if(base_plan, body.changes)
            except ValueError as exc:
                raise ApiError(422, "VALIDATION_ERROR", f"The what-if changes are not valid: {exc}",
                               {"errors": [{"loc": ["body", "changes"], "msg": str(exc), "type": "value_error"}]})
            active = active_run(s, plan_id)
            if active is not None:   # re-read under the run lock (lock order: plan -> run); it may have finished
                s.refresh(active, with_for_update={"key_share": True})
                if active.status not in ("queued", "running") or active.cancel_requested:
                    active = None
            if active is not None:
                if not (body.replace_active and active.kind == "what_if"):
                    raise _run_already_active(active)
                _cancel_in_session(ctx, s, active)
                replaced = active.id
            preflight_or_422(derived)
            pv = snapshot(s, row, derived.model_dump(mode="json"), kind="what_if", base_version=base_version)
            label = body.changes.label or req.label or default_label(base_plan, body.changes)
            run = _insert_run(s, row, pv, "what_if", req, label, body.changes.model_dump(mode="json"))
            job = enqueue(ctx, s, run, idem)
            out = created_dict(run)
        if replaced is not None:
            ctx.jobs.notify_cancel(replaced)   # after the commit (A.16)
        ctx.jobs.dispatch(job)
    return out


# ---------------------------------------------------------------- cancel

def cancel_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        run = s.get(FinanceRunRow, run_id, with_for_update={"key_share": True})
        if run is None:
            raise not_found("Finance run", run_id)
        if run.status not in ("queued", "running"):
            raise ApiError(409, "RUN_NOT_ACTIVE", f"The run has already finished (status {run.status}).",
                           {"status": run.status})
        status = _cancel_in_session(ctx, s, run)
    ctx.jobs.notify_cancel(run_id)
    return {"run_id": run_id, "status": status, "cancel_requested": True}


# ---------------------------------------------------------------- recovery

def recover_interrupted_runs(ctx: AppContext) -> int:
    """Inline mode: every queued/running run -> failed (+ its job), as before Phase 2b."""
    with ctx.write_guard(), ctx.db.write() as s:
        runs = s.scalars(select(FinanceRunRow).where(FinanceRunRow.status.in_(("queued", "running")))).all()
        now = utcnow()
        for run in runs:
            run.status = "failed"
            run.error = RESTART_ERROR
            run.finished_at = now
            add_event(s, run.id, "run_failed", {"error": RESTART_ERROR}, 0.0)
        job_common.mark_jobs_failed(s, "finance_run", [r.id for r in runs], RESTART_ERROR)
        if runs:
            log.info("marked %d interrupted finance run(s) failed", len(runs))
        return len(runs)


# ---------------------------------------------------------------- worker

class ProgressWriter:
    """Maps engine `FinanceProgress` callbacks to persisted events (19): `stage_started` on each new stage,
    `progress` throttled to the configured rate (2/s), the latest pending progress flushed before
    `stage_completed`."""

    def __init__(self, ctx: RuntimeContext, run_id: str, t0: float, lease: Lease | None = None):
        self.ctx = ctx
        self.run_id = run_id
        self.t0 = t0
        self.lease = lease
        self.min_interval = ctx.settings.progress_min_interval_seconds
        self.last_progress = float("-inf")
        self.pending: finance.FinanceProgress | None = None
        self.stage: str | None = None
        self.stage_t0 = 0.0
        self._lock = threading.Lock()

    def _write(self, type_: str, fields: dict[str, Any]) -> None:
        lease = self.lease
        if lease is not None and lease.lost.is_set():
            return   # this worker no longer owns the job: write nothing more
        try:
            with self.ctx.db.write() as s:
                add_event(s, self.run_id, type_, fields, time.monotonic() - self.t0, lease=lease)
        except LeaseLost:
            if lease is not None:
                lease.mark_lost()   # stop the engine; the output is discarded (not an error)
        except Exception:  # progress must never kill a run
            log.exception("could not persist %s event for finance run %s", type_, self.run_id)

    def _write_progress(self, p: finance.FinanceProgress) -> None:
        self._write("progress", {"stage": p.stage, "fraction": round(float(p.fraction), 4), "message": p.message,
                                 "detail": p.detail})

    def _close_stage(self) -> None:
        if self.stage is None:
            return
        if self.pending is not None:
            self._write_progress(self.pending)
            self.pending = None
            self.last_progress = time.monotonic()
        self._write("stage_completed", {"stage": self.stage,
                                        "seconds": round(time.monotonic() - self.stage_t0, 3)})
        self.stage = None

    def __call__(self, p: finance.FinanceProgress) -> None:
        with self._lock:
            if p.stage != self.stage:
                self._close_stage()
                self.stage = p.stage
                self.stage_t0 = time.monotonic()
                self._write("stage_started", {"stage": p.stage, "message": p.message})
            now = time.monotonic()
            if now - self.last_progress >= self.min_interval:
                self.last_progress = now
                self.pending = None
                self._write_progress(p)
            else:
                self.pending = p

    def finish(self) -> None:
        with self._lock:
            self._close_stage()


def _before_final_write(run_id: str) -> None:
    """Test seam: called after `run_plan` returned and before the final transaction (2.7)."""


def _summary_dict(result: finance.FinanceResult, kind: str, label: str | None, base_version: int,
                  what_if: dict[str, Any] | None) -> dict[str, Any]:
    s = result.summary
    return {"base_plan_version": base_version, "kind": kind, "label": label, "feasibility": result.feasibility,
            "goals_total": s.goals_total, "goals_on_track": s.goals_on_track, "goals_at_risk": s.goals_at_risk,
            "goals_off_track": s.goals_off_track, "monthly_contribution_now": s.monthly_contribution_now,
            "what_if": what_if}


def independent_check(plan: finance.FinancePlan, result: finance.FinanceResult,
                      run_id: str) -> finance.FinanceResult:
    """Re-run the independent validator before persisting: a result with a hard violation is never stored as
    feasible. On disagreement the result becomes `unknown` and carries the validator's violations."""
    if result.feasibility != "feasible":
        return result
    violations = finance.validate_result(plan, result)
    hard = [v for v in violations if v.severity == "hard"]
    if not hard:
        return result
    log.error("finance run %s: engine reported feasible but the validator found %d hard violation(s) (%s)",
              run_id, len(hard), ",".join(sorted({v.code for v in hard})))
    return result.model_copy(update={"feasibility": "unknown", "violations": violations})


def _finish(ctx: RuntimeContext, run_id: str, status: str, t0: float, error: str | None = None,
            lease: Lease | None = None) -> None:
    """Terminal `failed`/`cancelled` write (fenced). A cancel request always wins over `failed` ([R11])."""
    with ctx.write_guard(), ctx.db.write() as s:
        run = s.get(FinanceRunRow, run_id, with_for_update={"key_share": True})
        if run is None:
            raise LeaseLost(f"finance run {run_id} is gone")   # plan deleted: the job went with it
        if lease is not None:
            lease.fence(s)   # raises if the lease is lost: never write `cancelled` for a lost lease (R6)
        if run.cancel_requested:
            status = "cancelled"
        run.status = status
        run.finished_at = utcnow()
        elapsed = time.monotonic() - t0
        if status == "failed":
            run.error = error
            add_event(s, run_id, "run_failed", {"error": error}, elapsed)
        else:
            add_event(s, run_id, "run_cancelled", {}, elapsed)
        if lease is not None:
            lease.finish(s, "failed" if status == "failed" else "cancelled", error if status == "failed" else None)


def _retryable(ctx: RuntimeContext, exc: BaseException) -> bool:
    return ctx.settings.job_backend == "queue" and is_transient_db_error(exc)


def run_job(ctx: RuntimeContext, run_id: str, lease: Lease) -> None:
    """Execute one claim of a finance run's job (both backends). Raises LeaseLost / RetryableJobError to the
    worker; records engine failures itself."""
    cancel_event = lease.cancel_event
    t0 = time.monotonic()
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            run = s.get(FinanceRunRow, run_id, with_for_update={"key_share": True})
            if run is None:
                raise LeaseLost(f"finance run {run_id} is gone")   # plan deleted: the job went with it
            lease.fence(s)
            if run.status != "queued" or run.cancel_requested:
                # cancelled while queued / in the claim window, or recovered: never run the engine
                if run.status in ("queued", "running"):
                    run.status = "cancelled"
                    run.finished_at = utcnow()
                    add_event(s, run.id, "run_cancelled", {}, 0.0)
                lease.finish(s, RUN_TO_JOB_STATUS.get(run.status, "cancelled"))
                return
            run.status = "running"
            if run.started_at is None:   # a retried attempt keeps the first start time
                run.started_at = utcnow()
            request = dict(run.request)
            kind, label, what_if, owner_id = run.kind, run.label, run.what_if, run.owner_id
            pv = s.get(FinancePlanVersionRow, run.plan_version_id)
            doc, base_version, pv_id, plan_id = pv.document, pv.base_version, pv.id, run.plan_id
            add_event(s, run.id, "run_started", {}, 0.0)
    except LeaseLost:
        raise
    except Exception as exc:
        if _retryable(ctx, exc):
            raise RetryableJobError(str(exc)) from exc
        raise
    writer = ProgressWriter(ctx, run_id, t0, lease)
    try:
        plan = load_plan(doc)
        req = finance.FinanceRunRequest.model_validate(request)
        result = finance.run_plan(plan, req, writer, cancel_event)
        writer.finish()
        result = independent_check(plan, result, run_id)
        _before_final_write(run_id)
        with ctx.write_guard(), ctx.db.write() as s:
            # lock order plan -> run -> job (R4): KEY SHARE on the plan first (inserting the result takes it anyway)
            if not lock_parent_key_share(s, FinancePlanRow, plan_id):
                raise LeaseLost(f"plan of finance run {run_id} is gone")   # discard the output
            run = s.get(FinanceRunRow, run_id, with_for_update={"key_share": True})
            if run is None:
                raise LeaseLost(f"finance run {run_id} is gone")
            lease.fence(s)
            elapsed = time.monotonic() - t0
            run.finished_at = utcnow()
            if run.cancel_requested:  # [R11]: a cancelled run never exposes a result
                run.status = "cancelled"
                add_event(s, run_id, "run_cancelled", {}, elapsed)
                lease.finish(s, "cancelled")
                return
            res = FinanceResultRow(id=new_id("fres_"), owner_id=owner_id, plan_id=plan_id, plan_version_id=pv_id,
                                   run_id=run_id, kind=kind, label=label, feasibility=result.feasibility,
                                   summary=_summary_dict(result, kind, label, base_version, what_if),
                                   result=result.model_dump(mode="json"), created_at=utcnow())
            s.add(res)
            s.flush()
            run.status = "completed"
            run.feasibility = result.feasibility
            add_event(s, run_id, "run_completed", {"result_id": res.id, "feasibility": result.feasibility,
                                                   "goals_on_track": result.summary.goals_on_track,
                                                   "goals_total": result.summary.goals_total}, elapsed)
            lease.finish(s, "succeeded")
    except LeaseLost:
        raise
    except finance.FinanceCancelled:
        writer.finish()
        _finish(ctx, run_id, "cancelled", t0, lease=lease)
    except Exception as exc:
        if _retryable(ctx, exc):
            raise RetryableJobError(str(exc)) from exc
        log.exception("finance run %s failed", run_id)
        message = str(exc) or exc.__class__.__name__
        try:
            writer.finish()
            _finish(ctx, run_id, "failed", t0, message, lease=lease)
        except LeaseLost:
            raise
        except Exception:
            log.exception("could not mark finance run %s failed", run_id)


# ---------------------------------------------------------------- results

def _result_row(s: Session, result_id: str) -> FinanceResultRow:
    row = s.get(FinanceResultRow, result_id)
    if row is None:
        raise not_found("Finance result", result_id)
    return row


def list_results(ctx: AppContext, plan_id: str, kind: str | None) -> list[dict[str, Any]]:
    with ctx.db.read() as s:
        get_plan_row(s, plan_id)
        q = select(FinanceResultRow).where(FinanceResultRow.plan_id == plan_id)
        if kind is not None:
            q = q.where(FinanceResultRow.kind == kind)
        rows = s.scalars(q.order_by(FinanceResultRow.created_at.desc(), FinanceResultRow.id.desc())
                         .limit(MAX_LIST_ITEMS)).all()
        return [result_summary(r) for r in rows]


def get_result(ctx: AppContext, result_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        row = _result_row(s, result_id)
        pv = s.get(FinancePlanVersionRow, row.plan_version_id)
        out = result_summary(row)
        out["result"] = row.result
        out["plan"] = pv.document
        return out


def load_result(ctx: AppContext, result_id: str) -> tuple[dict[str, Any], finance.FinanceResult,
                                                          finance.FinancePlan]:
    """(summary, result, snapshot plan) of a stored result."""
    with ctx.db.read() as s:
        row = _result_row(s, result_id)
        pv = s.get(FinancePlanVersionRow, row.plan_version_id)
        summary, result_doc, plan_doc = result_summary(row), row.result, pv.document
    return summary, finance.FinanceResult.model_validate(result_doc), load_plan(plan_doc)


def compare(ctx: AppContext, a_id: str, b_id: str) -> dict[str, Any]:
    sa, ra, _ = load_result(ctx, a_id)
    sb, rb, _ = load_result(ctx, b_id)
    summary_a = finance.FinanceResultSummary.model_validate(sa)
    summary_b = finance.FinanceResultSummary.model_validate(sb)
    comp = finance.compare_results(ra, rb, summary_a=summary_a, summary_b=summary_b, what_if_b=summary_b.what_if)
    return comp.model_dump(mode="json")


def contributions_csv(ctx: AppContext, result_id: str) -> tuple[str, str]:
    _, result, plan = load_result(ctx, result_id)
    return finance.contributions_csv(plan, result), f"{slugify(plan.name)}-{result_id}-contributions.csv"
