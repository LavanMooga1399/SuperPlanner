"""Schedules: list/get, approve (supersede + staleness), compare, CSV export (A.14.6)."""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from superplanner import engine
from superplanner.engine import CompileError, Placement

from sqlalchemy.exc import IntegrityError

from ..context import AppContext
from ..db import ProblemVersionRow, ScheduleRow, utcnow
from ..db.locks import is_unique_violation
from ..errors import ApiError, not_found
from ..schemas import iso_utc
from .problem_service import audit, get_problem_row, load_problem, slugify

SCHEDULE_STATUSES = ("candidate", "approved", "superseded")


# ---------------------------------------------------------------- helpers

def horizon_of(doc: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(doc["horizon_start"])


def minute_iso(horizon: datetime, minute: int) -> str:
    return (horizon + timedelta(minutes=minute)).isoformat()


def to_minute(dt: datetime, horizon: datetime) -> int:
    return math.floor((dt - horizon).total_seconds() / 60)


def get_schedule_row(s: Session, schedule_id: str) -> ScheduleRow:
    row = s.get(ScheduleRow, schedule_id)
    if row is None:
        raise not_found("Schedule", schedule_id)
    return row


def _pv(s: Session, row: ScheduleRow) -> ProblemVersionRow:
    pv = s.get(ProblemVersionRow, row.problem_version_id)
    assert pv is not None
    return pv


def summary(s: Session, row: ScheduleRow, pv: ProblemVersionRow | None = None) -> dict[str, Any]:
    pv = pv or _pv(s, row)
    violations = row.violations or []
    hard = sum(1 for v in violations if v.get("severity") == "hard")
    return {
        "id": row.id, "problem_id": row.problem_id, "problem_version_id": row.problem_version_id,
        "solver_run_id": row.solver_run_id, "source_schedule_id": row.source_schedule_id, "status": row.status,
        "rank": row.rank, "label": row.label, "solver": row.solver, "feasibility": row.feasibility,
        "objectives": row.objectives, "metrics": row.metrics, "hard_violation_count": hard,
        "soft_violation_count": len(violations) - hard, "base_problem_version": pv.base_version,
        "approved_problem_version": row.approved_problem_version, "created_at": iso_utc(row.created_at),
        "approved_at": iso_utc(row.approved_at), "superseded_at": iso_utc(row.superseded_at),
    }


def detail(s: Session, row: ScheduleRow) -> dict[str, Any]:
    pv = _pv(s, row)
    horizon = horizon_of(pv.document)
    out = summary(s, row, pv)
    out["horizon_start"] = pv.document["horizon_start"]
    out["placements"] = [{**p, "start_at": minute_iso(horizon, p["start"]), "end_at": minute_iso(horizon, p["end"])}
                         for p in row.placements or []]
    out["violations"] = row.violations or []
    out["explanation"] = row.explanation
    return out


# ---------------------------------------------------------------- reads

def list_schedules(ctx: AppContext, problem_id: str, status: str | None) -> list[dict[str, Any]]:
    with ctx.db.read() as s:
        get_problem_row(s, problem_id)
        q = select(ScheduleRow).where(ScheduleRow.problem_id == problem_id)
        if status:
            q = q.where(ScheduleRow.status == status)
        rows = s.scalars(q.order_by(ScheduleRow.created_at.desc(), ScheduleRow.rank, ScheduleRow.id)
                         .limit(500)).all()
        return [summary(s, r) for r in rows]


def get_schedule(ctx: AppContext, schedule_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        return detail(s, get_schedule_row(s, schedule_id))


# ---------------------------------------------------------------- approve

def approve(ctx: AppContext, schedule_id: str, note: str | None) -> dict[str, Any]:
    """Approve; an IntegrityError of the `uq_schedules_one_approved` backstop is retried once (PHASE2B 2.12)."""
    for attempt in (1, 2):
        try:
            return _approve(ctx, schedule_id, note)
        except IntegrityError as exc:
            if not is_unique_violation(exc, "uq_schedules_one_approved", "schedules.problem_id"):
                raise
            if attempt == 2:
                raise ApiError(409, "CONFLICT", "Another approval for this plan happened at the same time; "
                                                "reload and try again.") from None
    raise AssertionError("unreachable")  # pragma: no cover


def _approve(ctx: AppContext, schedule_id: str, note: str | None) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        row = get_schedule_row(s, schedule_id)
        # lock the problem before reading approved schedules, then re-read this row under the lock
        problem_row = get_problem_row(s, row.problem_id, lock=True)
        s.refresh(row)
        if row.status == "superseded":
            raise ApiError(409, "SUPERSEDED", "This schedule was superseded by a later approval and cannot be "
                                              "approved again.", {"superseded_at": iso_utc(row.superseded_at)})
        if row.status == "approved":
            return {"schedule": summary(s, row), "superseded_schedule_id": None}
        if row.feasibility != "feasible":
            raise ApiError(422, "NOT_FEASIBLE", "Only feasible schedules can be approved; this one has "
                                                f"feasibility '{row.feasibility}'.",
                           {"feasibility": row.feasibility})
        pv = _pv(s, row)
        if problem_row.version != pv.base_version:
            _check_stale(problem_row.document, pv.document, row.placements or [])
        now = utcnow()
        previous = s.scalars(select(ScheduleRow).where(ScheduleRow.problem_id == row.problem_id,
                                                       ScheduleRow.status == "approved")).all()
        superseded_id = None
        for prev in previous:
            prev.status = "superseded"
            prev.superseded_at = now
            superseded_id = prev.id
            audit(s, "schedule", prev.id, "schedule.superseded", {"by": row.id})
        s.flush()
        row.status = "approved"
        row.approved_at = now
        row.approved_problem_version = problem_row.version
        audit(s, "schedule", row.id, "schedule.approved",
              {"note": note, "problem_version": problem_row.version, "superseded_schedule_id": superseded_id})
        s.flush()
        return {"schedule": summary(s, row, pv), "superseded_schedule_id": superseded_id}


def _check_stale(current_doc: dict[str, Any], snapshot_doc: dict[str, Any], placements: list[dict[str, Any]]) -> None:
    current = load_problem(current_doc)
    shift = to_minute(horizon_of(snapshot_doc), current.horizon_start)
    moved = [Placement(task_id=p["task_id"], start=p["start"] + shift, end=p["end"] + shift,
                       resource_ids=list(p.get("resource_ids") or [])) for p in placements]
    try:
        report = engine.validate_schedule(current, moved)
    except CompileError as exc:
        raise ApiError(409, "STALE_SCHEDULE", "The plan changed since this schedule was created and now has "
                                              "problems that must be fixed first.",
                       {"violations": [], "issues": [i.model_dump(mode="json") for i in exc.issues
                                                     if i.severity == "error"]})
    hard = [v for v in report.violations if v.severity == "hard"]
    if hard:
        first = hard[0].message
        raise ApiError(409, "STALE_SCHEDULE", f"The plan changed since this schedule was created: {first}",
                       {"violations": [v.model_dump(mode="json") for v in hard], "issues": []})


# ---------------------------------------------------------------- compare

_METRIC_KEYS = ("makespan_minutes", "total_tardiness_minutes", "weighted_tardiness", "late_tasks", "cost")


def compare(ctx: AppContext, a_id: str, b_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        a = get_schedule_row(s, a_id)
        b = get_schedule_row(s, b_id)
        if a.problem_id != b.problem_id:
            raise ApiError(422, "DIFFERENT_PROBLEMS", "Only schedules of the same plan can be compared.",
                           {"a_problem_id": a.problem_id, "b_problem_id": b.problem_id})
        pva, pvb = _pv(s, a), _pv(s, b)
        ha, hb = horizon_of(pva.document), horizon_of(pvb.document)
        shift_b = to_minute(hb, ha)   # b minute m -> a minute m + shift_b
        ma, mb = a.metrics or {}, b.metrics or {}
        deltas: dict[str, Any] = {}
        for k in _METRIC_KEYS:
            va, vb = ma.get(k), mb.get(k)
            if va is None or vb is None:
                deltas[k] = None
            elif k == "cost":
                deltas[k] = round(float(vb) - float(va), 2)
            else:
                deltas[k] = int(vb) - int(va)
        names_a = {t["id"]: t["name"] for t in pva.document.get("tasks", [])}
        names_b = {t["id"]: t["name"] for t in pvb.document.get("tasks", [])}
        pa = {p["task_id"]: p for p in a.placements or []}
        pb = {p["task_id"]: p for p in b.placements or []}
        order = list(dict.fromkeys([*pa.keys(), *pb.keys()]))
        rows = []
        for tid in order:
            x, y = pa.get(tid), pb.get(tid)
            item: dict[str, Any] = {"task_id": tid, "name": names_b.get(tid) or names_a.get(tid) or tid,
                                    "in_a": x is not None, "in_b": y is not None,
                                    "start_a": x["start"] if x else None, "end_a": x["end"] if x else None,
                                    "start_b": y["start"] + shift_b if y else None,
                                    "end_b": y["end"] + shift_b if y else None,
                                    "resources_a": list(x["resource_ids"]) if x else [],
                                    "resources_b": list(y["resource_ids"]) if y else []}
            if x and y:
                item["start_delta_minutes"] = item["start_b"] - item["start_a"]
                item["end_delta_minutes"] = item["end_b"] - item["end_a"]
                item["resource_changed"] = item["resources_a"] != item["resources_b"]
                changed = bool(item["start_delta_minutes"] or item["end_delta_minutes"] or item["resource_changed"])
            else:
                item["start_delta_minutes"] = None
                item["end_delta_minutes"] = None
                item["resource_changed"] = False
                changed = True
            item["_changed"] = changed
            rows.append(item)
        # abs(end_delta) desc, then id; one-sided tasks (null delta) sort first as the largest change
        rows.sort(key=lambda r: (-(abs(r["end_delta_minutes"]) if r["end_delta_minutes"] is not None
                                   else math.inf), r["task_id"]))
        changed_count = sum(1 for r in rows if r.pop("_changed"))
        ordered_keys = ("task_id", "name", "in_a", "in_b", "start_a", "start_b", "end_a", "end_b",
                        "start_delta_minutes", "end_delta_minutes", "resources_a", "resources_b", "resource_changed")
        rows = [{k: r[k] for k in ordered_keys} for r in rows]
        return {"a": summary(s, a, pva), "b": summary(s, b, pvb), "metric_deltas": deltas, "task_deltas": rows,
                "changed_task_count": changed_count}


# ---------------------------------------------------------------- CSV

CSV_HEADER = ["task_id", "task_name", "group", "type", "start", "end", "duration_minutes", "resource_ids",
              "resource_names", "deadline", "deadline_hard", "lateness_minutes", "on_critical_chain"]


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_text(value: Any) -> str:
    """Neutralise spreadsheet formula injection in a free-text cell (OWASP CSV injection guidance).

    Cells starting with = + - @ TAB or CR are prefixed with a single quote so Excel / LibreOffice show them
    as text. Only user-supplied text columns (ids, names, groups) pass through here; ids are included because
    the Id pattern allows a leading `-`. Numeric columns are not, so a negative number stays a number.
    """
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _deadline_in_plan_offset(value: str | None, horizon: datetime) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value).astimezone(horizon.tzinfo).isoformat()


def export_csv(ctx: AppContext, schedule_id: str) -> tuple[str, str]:
    with ctx.db.read() as s:
        row = get_schedule_row(s, schedule_id)
        pv = _pv(s, row)
        problem_row = get_problem_row(s, row.problem_id)
        doc = pv.document
        horizon = horizon_of(doc)
        res_names = {r["id"]: r["name"] for r in doc.get("resources", [])}
        placed = {p["task_id"]: p for p in row.placements or []}
        expl = (row.explanation or {}).get("tasks", {})
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(CSV_HEADER)
        for t in doc.get("tasks", []):
            p = placed.get(t["id"])
            e = expl.get(t["id"], {})
            rids = list(p["resource_ids"]) if p else []
            w.writerow([
                csv_text(t["id"]), csv_text(t["name"]), csv_text(t.get("group") or ""), t.get("type", "activity"),
                minute_iso(horizon, p["start"]) if p else "", minute_iso(horizon, p["end"]) if p else "",
                t.get("duration_minutes", 0), csv_text(";".join(rids)),
                csv_text(";".join(res_names.get(r, r) for r in rids)),
                _deadline_in_plan_offset(t.get("deadline"), horizon), "true" if t.get("deadline_hard") else "false",
                e.get("lateness_minutes", 0) if p else "",
                "true" if e.get("on_critical_chain") else "false",
            ])
        filename = f"{slugify(problem_row.name)}-{row.id}.csv"
        return buf.getvalue(), filename
