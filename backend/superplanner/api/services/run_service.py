"""Solver runs: creation, background worker, progress events, cancel, recovery (A.14.5, A.15, A.16)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from superplanner import engine
from superplanner.engine import OptimizeRequest, Placement, Problem, ProgressEvent

from ..context import WRITE_LOCK, AppContext
from ..db import ProblemRow, ProblemVersionRow, ScheduleRow, SolverRunEventRow, SolverRunRow, new_id, utcnow
from ..errors import ApiError, not_found
from ..schemas import SolverRunRequest, as_utc, iso_utc
from .problem_service import audit, get_problem_row, has_active_run, load_problem, snapshot

log = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = ("run_completed", "run_cancelled", "run_failed")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
RESTART_ERROR = "Server restarted before the run finished."
API_PREFIX = "/api/v1"


# ---------------------------------------------------------------- events

def _next_seq(s: Session, run_id: str) -> int:
    return int(s.scalar(select(func.max(SolverRunEventRow.seq)).where(SolverRunEventRow.run_id == run_id)) or 0) + 1


def add_event(s: Session, run_id: str, type_: str, fields: dict[str, Any], elapsed: float) -> dict[str, Any]:
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


def create_run(ctx: AppContext, problem_id: str, req: SolverRunRequest) -> dict[str, Any]:
    with WRITE_LOCK:
        with ctx.db.write() as s:
            row = get_problem_row(s, problem_id)
            ensure_no_active_run(s, problem_id)
            preflight_or_422(load_problem(row.document))
            pv = snapshot(s, row)
            run = insert_run(s, row, pv, req)
            out = created_dict(run)
        submit(ctx, out["run_id"])
    return out


def submit(ctx: AppContext, run_id: str) -> None:
    ctx.executor.submit(run_id, lambda rid, ev: run_job(ctx, rid, ev))


# ---------------------------------------------------------------- cancel

def cancel_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with WRITE_LOCK, ctx.db.write() as s:
        run = s.get(SolverRunRow, run_id)
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
        audit(s, "run", run.id, "run.cancelled", {"status_at_cancel": "queued" if run.status == "cancelled"
                                                  else "running"})
        status = run.status
    ctx.executor.cancel(run_id)
    return {"run_id": run_id, "status": status, "cancel_requested": True}


# ---------------------------------------------------------------- recovery

def recover_interrupted_runs(ctx: AppContext) -> int:
    with WRITE_LOCK, ctx.db.write() as s:
        runs = s.scalars(select(SolverRunRow).where(SolverRunRow.status.in_(("queued", "running")))).all()
        for run in runs:
            run.status = "failed"
            run.error = RESTART_ERROR
            run.finished_at = utcnow()
            add_event(s, run.id, "run_failed", {"error": RESTART_ERROR}, 0.0)
        return len(runs)


# ---------------------------------------------------------------- worker

class _ProgressWriter:
    """Maps engine ProgressEvents to persisted SSE rows; throttles `progress` to 2/s (A.15)."""

    def __init__(self, ctx: AppContext, run_id: str, t0: float):
        self.ctx = ctx
        self.run_id = run_id
        self.t0 = t0
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
        try:
            with self.ctx.db.write() as s:
                add_event(s, self.run_id, type_, fields, time.monotonic() - self.t0)
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
        id=new_id("sch_"), problem_id=run.problem_id, problem_version_id=run.problem_version_id,
        solver_run_id=run.id, source_schedule_id=run.source_schedule_id, status="candidate", rank=rank,
        label=label, solver=solver, feasibility=feasibility,
        objectives=objectives.model_dump(mode="json") if objectives is not None else None,
        metrics=metrics.model_dump(mode="json") if metrics is not None else None,
        violations=[v.model_dump(mode="json") for v in violations],
        placements=[p.model_dump(mode="json") for p in placements],
        explanation=explanation.model_dump(mode="json") if explanation is not None else None,
        created_at=utcnow())


def run_job(ctx: AppContext, run_id: str, cancel_event: threading.Event) -> None:
    t0 = time.monotonic()
    with WRITE_LOCK, ctx.db.write() as s:
        run = s.get(SolverRunRow, run_id)
        if run is None or run.status != "queued":
            return  # cancelled while queued (or recovered): never run the engine
        run.status = "running"
        run.started_at = utcnow()
        request = dict(run.request)
        source_id = run.source_schedule_id
        doc = s.get(ProblemVersionRow, run.problem_version_id).document
        add_event(s, run.id, "run_started", {"strategy_requested": request.get("strategy", "auto")}, 0.0)
    try:
        problem = load_problem(doc)
        initial = None
        if source_id:
            with ctx.db.read() as s:
                initial = _replan_hint(s, problem, source_id)
        opt_req = OptimizeRequest.model_validate({**request, "initial_solution": initial})
        writer = _ProgressWriter(ctx, run_id, t0)
        outcome = engine.optimize(problem, opt_req, writer, cancel_event)
        res = outcome.result

        rows: list[ScheduleRow] = []
        with ctx.db.read() as s:
            run_snapshot = s.get(SolverRunRow, run_id)
            assert run_snapshot is not None
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
        cancelled = cancel_event.is_set() or res.status == "cancelled"
        with ctx.db.write() as s:
            run = s.get(SolverRunRow, run_id)
            if run is None:  # problem deleted meanwhile
                return
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
    except Exception as exc:
        log.exception("run %s failed", run_id)
        message = str(exc) or exc.__class__.__name__
        try:
            with ctx.db.write() as s:
                run = s.get(SolverRunRow, run_id)
                if run is None:
                    return
                run.status = "failed"
                run.error = message
                run.finished_at = utcnow()
                add_event(s, run_id, "run_failed", {"error": message}, time.monotonic() - t0)
        except Exception:
            log.exception("could not mark run %s failed", run_id)
