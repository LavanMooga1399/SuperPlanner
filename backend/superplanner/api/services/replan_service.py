"""Replanning (A.14.6 ReplanRequest): apply real-world changes, freeze started work, run on a derived snapshot."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from superplanner.engine import Problem

from ..context import AppContext
from ..db import ProblemRow, utcnow
from ..db.locks import is_unique_violation
from ..errors import ApiError, validation_error
from ..schemas import ReplanChanges, ReplanRequest
from . import run_service
from .problem_service import audit, dump_problem, get_problem_row, load_problem, snapshot
from .schedule_service import _pv, get_schedule_row, horizon_of


def _apply_changes(doc: dict[str, Any], changes: ReplanChanges) -> Problem:
    doc = copy.deepcopy(doc)
    tasks: list[dict[str, Any]] = doc.setdefault("tasks", [])
    by_id = {t["id"]: t for t in tasks}
    for i, upd in enumerate(changes.task_updates):
        t = by_id.get(upd.id)
        if t is None:
            raise ApiError(422, "VALIDATION_ERROR", f"Task {upd.id!r} in task_updates does not exist.",
                           {"errors": [{"loc": ["body", "changes", "task_updates", i, "id"],
                                        "msg": "unknown task id", "type": "value_error"}]})
        for field in upd.model_fields_set - {"id"}:
            value = getattr(upd, field)
            if field == "requirements":
                value = [r.model_dump(mode="json") for r in value]  # null is rejected by TaskUpdate
            elif isinstance(value, datetime):
                value = value.isoformat()
            t[field] = value
        if "duration_minutes" in upd.model_fields_set:
            # PHASE2 2.14: a real-world duration replaces the three-point estimate (else the PERT rule -> 422).
            t.pop("duration_estimate", None)
    for i, new_task in enumerate(changes.add_tasks):
        if new_task.id in by_id:
            raise ApiError(422, "VALIDATION_ERROR", f"Task id {new_task.id!r} in add_tasks already exists.",
                           {"errors": [{"loc": ["body", "changes", "add_tasks", i, "id"],
                                        "msg": "duplicate task id", "type": "value_error"}]})
        d = new_task.model_dump(mode="json")
        tasks.append(d)
        by_id[new_task.id] = d
    if changes.remove_task_ids:
        gone = set(changes.remove_task_ids)
        doc["tasks"] = [t for t in tasks if t["id"] not in gone]
        doc["dependencies"] = [d for d in doc.get("dependencies", [])
                               if d["predecessor"] not in gone and d["successor"] not in gone]
    resources = {r["id"]: r for r in doc.get("resources", [])}
    for i, ru in enumerate(changes.resource_unavailable):
        r = resources.get(ru.resource_id)
        if r is None:
            raise ApiError(422, "VALIDATION_ERROR", f"Resource {ru.resource_id!r} does not exist.",
                           {"errors": [{"loc": ["body", "changes", "resource_unavailable", i, "resource_id"],
                                        "msg": "unknown resource id", "type": "value_error"}]})
        if r.get("calendar") is None:
            r["calendar"] = {"weekly": None, "blocked": []}
        r["calendar"].setdefault("blocked", []).append(
            {"start": ru.start.isoformat(), "end": ru.end.isoformat(), "reason": ru.reason})
    try:
        return Problem.model_validate(doc)
    except ValidationError as exc:
        raise validation_error(list(exc.errors()), ("body", "changes"),
                               "The changes would make the plan invalid.")


def _derive(problem: Problem, source_placements: list[dict[str, Any]], source_horizon: datetime,
            cutoff: datetime) -> dict[str, Any]:
    """Derived document: tasks started before the cutoff are locked, all others start at/after it."""
    doc = problem.model_dump(mode="json")
    placed = {p["task_id"]: p for p in source_placements}
    for t in doc["tasks"]:
        p = placed.get(t["id"])
        start_abs = source_horizon + timedelta(minutes=p["start"]) if p else None
        if start_abs is not None and start_abs < cutoff:
            rids = list(p.get("resource_ids") or [])
            reqs = t.get("requirements") or []
            aligned = (len(rids) == len(reqs) and len(set(rids)) == len(rids)
                       and all(rid in req.get("alternatives", []) for rid, req in zip(rids, reqs)))
            t["locked"] = {"start": start_abs.isoformat(),
                           "resource_ids": rids if aligned and reqs else None}
        else:
            current = datetime.fromisoformat(t["earliest_start"]) if t.get("earliest_start") else problem.horizon_start
            t["earliest_start"] = max(current, cutoff).isoformat()
    return doc


def replan(ctx: AppContext, schedule_id: str, req: ReplanRequest) -> dict[str, Any]:
    try:
        return _replan(ctx, schedule_id, req)
    except IntegrityError as exc:   # `uq_solver_runs_one_active` backstop (PHASE2B 2.12)
        if is_unique_violation(exc, "uq_solver_runs_one_active", "solver_runs.problem_id"):
            with ctx.db.read() as s:
                problem_id = get_schedule_row(s, schedule_id).problem_id
            raise run_service.active_run_conflict(ctx, problem_id) from None
        raise


def _replan(ctx: AppContext, schedule_id: str, req: ReplanRequest) -> dict[str, Any]:
    with ctx.write_guard():
        with ctx.db.write() as s:  # one transaction: any error rolls back everything, including step 1
            src = get_schedule_row(s, schedule_id)
            row: ProblemRow = get_problem_row(s, src.problem_id, lock=True)
            if req.expected_problem_version is not None and req.expected_problem_version != row.version:
                raise ApiError(412, "VERSION_MISMATCH",
                               f"The plan was changed elsewhere (now version {row.version}).",
                               {"current_version": row.version})
            run_service.ensure_no_active_run(s, row.id)
            current = load_problem(row.document)
            h_start = current.horizon_start
            h_end = h_start + timedelta(days=current.horizon_days)
            if not (h_start <= req.cutoff < h_end):
                raise ApiError(422, "VALIDATION_ERROR", "The cutoff must lie inside the plan horizon "
                                                        f"({h_start.isoformat()} to {h_end.isoformat()}).",
                               {"errors": [{"loc": ["body", "cutoff"], "msg": "cutoff outside the plan horizon",
                                            "type": "value_error"}]})
            # 1. real-world changes go into the editable document
            if not req.changes.is_empty():
                current = _apply_changes(row.document, req.changes)
                row.document = dump_problem(current, row.id)
                row.name = row.document["name"]
                row.domain = row.document["domain"]
                row.version += 1
                row.updated_at = utcnow()
                audit(s, "problem", row.id, "problem.updated", {"version": row.version, "via": "replan",
                                                                "source_schedule_id": src.id})
                s.flush()
            # 2. derived document (never written back to `problems`)
            src_pv = _pv(s, src)
            derived = _derive(current, src.placements or [], horizon_of(src_pv.document), req.cutoff)
            derived_problem = Problem.model_validate(derived)
            derived = dump_problem(derived_problem, row.id)
            # 3. snapshot + preflight + run
            run_service.preflight_or_422(derived_problem)
            pv = snapshot(s, row, derived, kind="replan")
            run = run_service.insert_run(s, row, pv, req.run, source_schedule_id=src.id)
            job = run_service.enqueue(ctx, s, run)
            out = run_service.created_dict(run)
            out["source_schedule_id"] = src.id
            out["problem_version"] = row.version
        ctx.jobs.dispatch(job)
    return out
