"""Solver runs: creation, background worker, progress events, cancel, recovery (A.14.5, A.15, A.16, PHASE2B 2.10).

`run_job(ctx, run_id, lease)` runs the same way under both job backends: its start, progress, final and failure
transactions are fenced by the lease (`Lease.fence`, lock order problem -> run -> job) and the terminal one also
finishes the job (`Lease.finish`). A lost lease never writes a terminal state (R6); transient DB errors become
`RetryableJobError` in queue mode (the worker requeues), engine errors fail the run as before.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from superplanner import engine
from superplanner.engine import OptimizeRequest, Placement, Problem, ProgressEvent
from superplanner.jobs import common as job_common
from superplanner.jobs import idempotency
from superplanner.jobs.idempotency import Idempotency
from superplanner.jobs.types import (RESTART_ERROR, RUN_TO_JOB_STATUS, Lease, LeaseLost, RetryableJobError,
                                     RuntimeContext, is_transient_db_error)

from ..context import WRITE_LOCK, AppContext  # noqa: F401  (WRITE_LOCK re-exported for old imports)
from ..db import JobRow, ProblemRow, ProblemVersionRow, ScheduleRow, SolverRunEventRow, SolverRunRow, new_id, utcnow
from ..db.locks import is_unique_violation, lock_parent_key_share, lock_row
from ..errors import ApiError, not_found
from ..schemas import SolverRunRequest, as_utc, iso_utc
from .problem_service import audit, get_problem_row, has_active_run, load_problem, snapshot

log = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = ("run_completed", "run_cancelled", "run_failed")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
API_PREFIX = "/api/v1"


# ---------------------------------------------------------------- events

def _next_seq(s: Session, run_id: str) -> int:
    return int(s.scalar(select(func.max(SolverRunEventRow.seq)).where(SolverRunEventRow.run_id == run_id)) or 0) + 1


def add_event(s: Session, run_id: str, type_: str, fields: dict[str, Any], elapsed: float, *,
              lease: Lease | None = None) -> dict[str, Any]:
    """Append an event. Locks the run row first (FOR NO KEY UPDATE) so `seq` allocation is safe
    with several writers and events of one run commit in seq order (SSE never skips one, PHASE2B 2.12); then
    fences the lease when given (worker writes; LeaseLost aborts the transaction)."""
    if not lock_row(s, SolverRunRow, run_id) and lease is not None:
        raise LeaseLost(f"run {run_id} is gone")
    if lease is not None:
        lease.fence(s)
    seq = _next_seq(s, run_id)
    now = utcnow()
    payload = {"run_id": run_id, "seq": seq, "type": type_, "ts": iso_utc(now),
               "elapsed_seconds": round(max(0.0, elapsed), 3)}
    payload.update(fields)
    s.add(SolverRunEventRow(run_id=run_id, seq=seq, type=type_, payload=payload, created_at=now))
    s.flush()
    return payload


def list_events(ctx: AppContext, run_id: str, after: int = 0) -> tuple[list[dict[str, Any]], str]:
    with ctx.db.read() as s:
        run = s.get(SolverRunRow, run_id)
        if run is None:
            raise not_found("Solver run", run_id)
        rows = s.scalars(select(SolverRunEventRow).where(SolverRunEventRow.run_id == run_id,
                                                         SolverRunEventRow.seq > after)
                         .order_by(SolverRunEventRow.seq)).all()
        return [r.payload for r in rows], run.status


# ---------------------------------------------------------------- serialization

def schedule_ids_for(s: Session, run_id: str) -> list[str]:
    return list(s.scalars(select(ScheduleRow.id).where(ScheduleRow.solver_run_id == run_id)
                          .order_by(ScheduleRow.rank)).all())


def run_dict(s: Session, run: SolverRunRow) -> dict[str, Any]:
    ids = schedule_ids_for(s, run.id)
    started, finished = as_utc(run.started_at), as_utc(run.finished_at)
    elapsed = round((finished - started).total_seconds(), 3) if started and finished else None
    return {
        "id": run.id, "problem_id": run.problem_id, "problem_version_id": run.problem_version_id,
        "status": run.status, "request": run.request, "engine_version": run.engine_version,
        "selection": run.selection, "phases": run.phases, "feasibility": run.feasibility,
        "termination_reason": run.termination_reason, "optimality_proven": run.optimality_proven,
        "objectives": run.objectives, "metrics": run.metrics, "diagnostics": run.diagnostics or [],
        "error": run.error, "primary_schedule_id": ids[0] if ids else None, "schedule_ids": ids,
        "source_schedule_id": run.source_schedule_id, "created_at": iso_utc(run.created_at),
        "started_at": iso_utc(run.started_at), "finished_at": iso_utc(run.finished_at), "elapsed_seconds": elapsed,
    }


def created_dict(run: SolverRunRow) -> dict[str, Any]:
    return {"run_id": run.id, "status": run.status, "problem_version_id": run.problem_version_id,
            "status_url": f"{API_PREFIX}/solver-runs/{run.id}",
            "events_url": f"{API_PREFIX}/solver-runs/{run.id}/events"}


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        run = s.get(SolverRunRow, run_id)
        if run is None:
            raise not_found("Solver run", run_id)
        return run_dict(s, run)


def list_runs(ctx: AppContext, problem_id: str) -> list[dict[str, Any]]:
    with ctx.db.read() as s:
        get_problem_row(s, problem_id)
        runs = s.scalars(select(SolverRunRow).where(SolverRunRow.problem_id == problem_id)
                         .order_by(SolverRunRow.created_at.desc(), SolverRunRow.id.desc()).limit(500)).all()
        return [run_dict(s, r) for r in runs]


# ---------------------------------------------------------------- creation

def preflight_or_422(problem: Problem) -> None:
    report = engine.preflight(problem)
    if report.ok:
        return
    errors = [i for i in report.issues if i.severity == "error"]
    n = len(errors)
    raise ApiError(422, "PREFLIGHT_FAILED",
                   f"Fix {n} problem{'s' if n != 1 else ''} before optimizing.",
                   {"issues": [i.model_dump(mode="json") for i in errors]})


def ensure_no_active_run(s: Session, problem_id: str) -> None:
    active = has_active_run(s, problem_id)
    if active is not None:
        raise ApiError(409, "RUN_ALREADY_ACTIVE",
                       "An optimization is already running for this plan; wait for it or cancel it.",
                       {"run_id": active.id})


def insert_run(s: Session, row: ProblemRow, pv: ProblemVersionRow, req: SolverRunRequest,
               source_schedule_id: str | None = None) -> SolverRunRow:
    run = SolverRunRow(id=new_id("run_"), problem_id=row.id, problem_version_id=pv.id, status="queued",
                       request=req.model_dump(mode="json"), seed=req.seed, engine_version=engine.__version__,
                       diagnostics=[], cancel_requested=False, source_schedule_id=source_schedule_id,
                       created_at=utcnow())
    s.add(run)
    s.flush()
    add_event(s, run.id, "run_queued", {"problem_version_id": pv.id}, 0.0)
    audit(s, "run", run.id, "run.created", {"problem_id": row.id, "problem_version_id": pv.id,
                                           "source_schedule_id": source_schedule_id})
    return run


def active_run_conflict(ctx: AppContext, problem_id: str) -> ApiError:
    """409 for an IntegrityError of `uq_solver_runs_one_active` (the cross-process backstop, PHASE2B 2.12)."""
    with ctx.db.read() as s:
        active = has_active_run(s, problem_id)
        active_id = active.id if active is not None else None
    return ApiError(409, "RUN_ALREADY_ACTIVE",
                    "An optimization is already running for this plan; wait for it or cancel it.",
                    {"run_id": active_id})


def enqueue(ctx: AppContext, s: Session, run: SolverRunRow, idem: Idempotency | None = None) -> JobRow:
    return ctx.jobs.enqueue(s, "solver_run", run.id, run.owner_id, idempotency_key=idem.key if idem else None,
                            request_hash=idem.request_hash if idem else None)


def created_from_job(s: Session, job: JobRow) -> dict[str, Any]:
    """Idempotent replay body: the creation body of the job's run with its current status (PHASE2B 2.8)."""
    run = s.get(SolverRunRow, job.solver_run_id) if job.solver_run_id else None
    if run is None:
        raise idempotency._mismatch()   # the key belongs to another kind of request
    out = created_dict(run)
    if run.source_schedule_id is not None:   # a replan run: same extra fields as replan_service
        out["source_schedule_id"] = run.source_schedule_id
        problem = s.get(ProblemRow, run.problem_id)
        out["problem_version"] = problem.version if problem is not None else None
    return out


def create_run(ctx: AppContext, problem_id: str, req: SolverRunRequest,
               idem: Idempotency | None = None) -> dict[str, Any]:
    """Raises `idempotency.Replay` for a replayed Idempotency-Key (the route answers 202 + header)."""
    try:
        with ctx.write_guard():
            with ctx.db.write() as s:
                row = get_problem_row(s, problem_id, lock=True)
                idempotency.lookup(s, idem, ctx.settings.idempotency_ttl_hours, created_from_job)   # after the lock
                ensure_no_active_run(s, problem_id)
                preflight_or_422(load_problem(row.document))
                pv = snapshot(s, row)
                run = insert_run(s, row, pv, req)
                job = enqueue(ctx, s, run, idem)
                out = created_dict(run)
            ctx.jobs.dispatch(job)
    except IntegrityError as exc:
        if idem is not None and idempotency.is_key_conflict(exc):
            idempotency.replay_after_conflict(ctx, idem, created_from_job)
        if is_unique_violation(exc, "uq_solver_runs_one_active", "solver_runs.problem_id"):
            raise active_run_conflict(ctx, problem_id) from None
        raise
    return out


# ---------------------------------------------------------------- cancel

def cancel_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        run = s.get(SolverRunRow, run_id, with_for_update={"key_share": True})
        if run is None:
            raise not_found("Solver run", run_id)
        if run.status not in ("queued", "running"):
            raise ApiError(409, "RUN_NOT_ACTIVE", f"The run has already finished (status {run.status}).",
                           {"status": run.status})
        run.cancel_requested = True
        if run.status == "queued":
            run.status = "cancelled"
            run.finished_at = utcnow()
            add_event(s, run.id, "run_cancelled", {"primary_schedule_id": None, "schedule_ids": []}, 0.0)
        ctx.jobs.request_cancel(s, "solver_run", run.id)
        audit(s, "run", run.id, "run.cancelled", {"status_at_cancel": "queued" if run.status == "cancelled"
                                                  else "running"})
        status = run.status
    ctx.jobs.notify_cancel(run_id)
    return {"run_id": run_id, "status": status, "cancel_requested": True}


# ---------------------------------------------------------------- recovery

def recover_interrupted_runs(ctx: AppContext) -> int:
    """Inline mode: every queued/running run -> failed (+ its job), as before Phase 2b."""
    with ctx.write_guard(), ctx.db.write() as s:
        runs = s.scalars(select(SolverRunRow).where(SolverRunRow.status.in_(("queued", "running")))).all()
        now = utcnow()
        for run in runs:
            run.status = "failed"
            run.error = RESTART_ERROR
            run.finished_at = now
            add_event(s, run.id, "run_failed", {"error": RESTART_ERROR}, 0.0)
        job_common.mark_jobs_failed(s, "solver_run", [r.id for r in runs], RESTART_ERROR)
        return len(runs)


# ---------------------------------------------------------------- worker

class _ProgressWriter:
    """Maps engine ProgressEvents to persisted SSE rows; throttles `progress` to 2/s (A.15)."""

    def __init__(self, ctx: RuntimeContext, run_id: str, t0: float, lease: Lease | None = None):
        self.ctx = ctx
        self.run_id = run_id
        self.t0 = t0
        self.lease = lease
        self.min_interval = ctx.settings.progress_min_interval_seconds
        self.last_progress = float("-inf")
        self.pending: ProgressEvent | None = None
        self._lock = threading.Lock()

    def _write(self, ev: ProgressEvent) -> None:
        if ev.type == "phase_started":
            fields = {"solver": ev.solver, "reason": ev.extra.get("reason", "")}
            type_ = "phase_started"
        elif ev.type == "phase_completed":
            fields = {"solver": ev.solver, "status": ev.extra.get("status"),
                      "feasibility": ev.extra.get("feasibility"),
                      "termination_reason": ev.extra.get("termination_reason"),
                      "objectives": ev.best_objectives.model_dump(mode="json") if ev.best_objectives else None}
            type_ = "phase_completed"
        else:
            fields = {"solver": ev.solver, "iteration": ev.iteration, "best_score": ev.best_score,
                      "best_objectives": ev.best_objectives.model_dump(mode="json") if ev.best_objectives else None,
                      "feasible_found": ev.feasible_found, "extra": ev.extra}
            type_ = "progress"
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
            log.exception("could not persist %s event for run %s", type_, self.run_id)

    def __call__(self, ev: ProgressEvent) -> None:
        with self._lock:
            if ev.type == "progress":
                now = time.monotonic()
                if now - self.last_progress >= self.min_interval:
                    self.last_progress = now
                    self.pending = None
                    self._write(ev)
                else:
                    self.pending = ev
                return
            if ev.type == "phase_completed" and self.pending is not None:
                self._write(self.pending)
                self.last_progress = time.monotonic()
            self.pending = None
            self._write(ev)


def _replan_hint(s: Session, problem: Problem, source_schedule_id: str) -> list[Placement] | None:
    """Source placements of the unlocked tasks, converted to this snapshot's minutes (A.14.6 step 3)."""
    src = s.get(ScheduleRow, source_schedule_id)
    if src is None:
        return None
    src_pv = s.get(ProblemVersionRow, src.problem_version_id)
    if src_pv is None:
        return None
    src_h = datetime.fromisoformat(src_pv.document["horizon_start"])
    tasks = {t.id: t for t in problem.tasks}
    out: list[Placement] = []
    for p in src.placements:
        t = tasks.get(p["task_id"])
        if t is None or t.locked is not None:
            continue
        abs_start = src_h + timedelta(minutes=p["start"])
        start = int((abs_start - problem.horizon_start).total_seconds() // 60)
        out.append(Placement(task_id=t.id, start=start, end=start + t.duration_minutes,
                             resource_ids=list(p.get("resource_ids") or [])))
    return out or None


def _schedule_row(run: SolverRunRow, rank: int, label: str, solver: str, feasibility: str, objectives: Any,
                  metrics: Any, violations: list, placements: list[Placement], explanation: Any) -> ScheduleRow:
    return ScheduleRow(
        id=new_id("sch_"), owner_id=run.owner_id, problem_id=run.problem_id,
        problem_version_id=run.problem_version_id,
        solver_run_id=run.id, source_schedule_id=run.source_schedule_id, status="candidate", rank=rank,
        label=label, solver=solver, feasibility=feasibility,
        objectives=objectives.model_dump(mode="json") if objectives is not None else None,
        metrics=metrics.model_dump(mode="json") if metrics is not None else None,
        violations=[v.model_dump(mode="json") for v in violations],
        placements=[p.model_dump(mode="json") for p in placements],
        explanation=explanation.model_dump(mode="json") if explanation is not None else None,
        created_at=utcnow())


def _retryable(ctx: RuntimeContext, exc: BaseException) -> bool:
    return ctx.settings.job_backend == "queue" and is_transient_db_error(exc)


def run_job(ctx: RuntimeContext, run_id: str, lease: Lease) -> None:
    """Execute one claim of a solver run's job (both backends). Raises LeaseLost / RetryableJobError to the
    worker; records engine failures itself."""
    cancel_event = lease.cancel_event
    t0 = time.monotonic()
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            run = s.get(SolverRunRow, run_id, with_for_update={"key_share": True})
            if run is None:
                raise LeaseLost(f"run {run_id} is gone")   # problem deleted: the job went with it
            lease.fence(s)
            if run.status != "queued":   # cancelled while queued (or in the claim window): never run the engine
                lease.finish(s, RUN_TO_JOB_STATUS.get(run.status, "cancelled"))
                return
            run.status = "running"
            if run.started_at is None:   # a retried attempt keeps the first start time
                run.started_at = utcnow()
            request = dict(run.request)
            source_id = run.source_schedule_id
            doc = s.get(ProblemVersionRow, run.problem_version_id).document
            add_event(s, run.id, "run_started", {"strategy_requested": request.get("strategy", "auto")}, 0.0)
    except LeaseLost:
        raise
    except Exception as exc:
        if _retryable(ctx, exc):
            raise RetryableJobError(str(exc)) from exc
        raise
    try:
        problem = load_problem(doc)
        initial = None
        if source_id:
            with ctx.db.read() as s:
                initial = _replan_hint(s, problem, source_id)
        opt_req = OptimizeRequest.model_validate({**request, "initial_solution": initial})
        writer = _ProgressWriter(ctx, run_id, t0, lease)
        outcome = engine.optimize(problem, opt_req, writer, cancel_event)
        res = outcome.result

        rows: list[ScheduleRow] = []
        with ctx.db.read() as s:
            run_snapshot = s.get(SolverRunRow, run_id)
            if run_snapshot is None:
                raise LeaseLost(f"run {run_id} is gone")
            s.expunge(run_snapshot)
        if res.placements:
            rows.append(_schedule_row(run_snapshot, 0, "Replan" if source_id else "Recommended", res.solver,
                                      res.feasibility, res.objectives, res.metrics, res.violations,
                                      res.placements, outcome.explanation))
            for alt in res.alternatives:
                report = engine.validate_schedule(problem, alt.placements)
                if report.feasibility != "feasible":
                    continue
                explanation = engine.explain_schedule(problem, alt.placements)
                rows.append(_schedule_row(run_snapshot, len(rows), alt.label, alt.solver, "feasible",
                                          alt.objectives, report.metrics, report.violations, alt.placements,
                                          explanation))
        # Read BEFORE the fence: if the event was set by a lost lease, `lost` was set first and the fence raises.
        cancelled = cancel_event.is_set() or res.status == "cancelled"
        with ctx.write_guard(), ctx.db.write() as s:
            # lock order plan -> run -> job (R4): KEY SHARE on the problem first, as inserting schedules takes it
            if not lock_parent_key_share(s, ProblemRow, run_snapshot.problem_id):
                raise LeaseLost(f"problem of run {run_id} is gone")
            run = s.get(SolverRunRow, run_id, with_for_update={"key_share": True})
            if run is None:  # problem deleted meanwhile
                raise LeaseLost(f"run {run_id} is gone")
            lease.fence(s)
            cancelled = cancelled or run.cancel_requested
            for r in rows:
                s.add(r)
            s.flush()
            ids = [r.id for r in rows]
            run.status = "cancelled" if cancelled else "completed"
            run.selection = outcome.selection.model_dump(mode="json")
            run.phases = [p.model_dump(mode="json") for p in outcome.phases]
            run.feasibility = res.feasibility
            run.termination_reason = res.termination_reason
            run.optimality_proven = res.optimality_proven
            run.objectives = res.objectives.model_dump(mode="json") if res.objectives else None
            run.metrics = res.metrics.model_dump(mode="json") if res.metrics else None
            run.diagnostics = list(res.diagnostics)
            run.finished_at = utcnow()
            elapsed = time.monotonic() - t0
            primary = ids[0] if ids else None
            if cancelled:
                add_event(s, run_id, "run_cancelled", {"primary_schedule_id": primary, "schedule_ids": ids}, elapsed)
            else:
                add_event(s, run_id, "run_completed", {
                    "feasibility": res.feasibility, "termination_reason": res.termination_reason,
                    "optimality_proven": res.optimality_proven, "objectives": run.objectives,
                    "primary_schedule_id": primary, "schedule_ids": ids}, elapsed)
            lease.finish(s, "cancelled" if cancelled else "succeeded")
    except LeaseLost:
        raise
    except Exception as exc:
        if _retryable(ctx, exc):
            raise RetryableJobError(str(exc)) from exc
        log.exception("run %s failed", run_id)
        message = str(exc) or exc.__class__.__name__
        try:
            with ctx.write_guard(), ctx.db.write() as s:
                run = s.get(SolverRunRow, run_id, with_for_update={"key_share": True})
                if run is None:
                    raise LeaseLost(f"run {run_id} is gone")
                lease.fence(s)
                run.status = "failed"
                run.error = message
                run.finished_at = utcnow()
                add_event(s, run_id, "run_failed", {"error": message}, time.monotonic() - t0)
                lease.finish(s, "failed", message)
        except LeaseLost:
            raise
        except Exception:
            log.exception("could not mark run %s failed", run_id)
