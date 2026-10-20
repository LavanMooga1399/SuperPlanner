"""Problems: CRUD with optimistic concurrency, export/import, templates, validate (A.14.2-14.4)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from superplanner import engine
from superplanner.engine import Problem
from superplanner.templates import TEMPLATES, get_template

from ..context import AppContext
from ..db import AuditEventRow, ProblemRow, ProblemVersionRow, ScheduleRow, SolverRunRow, new_id, utcnow
from ..db.locks import get_locked
from ..db.ownership import current_owner
from ..errors import ApiError, not_found, validation_error
from ..schemas import ExportFile, InstantiateRequest, iso_utc

ACTIVE_RUN_STATUSES = ("queued", "running")
MAX_LIST_ITEMS = 500


# ---------------------------------------------------------------- helpers

def audit(s: Session, entity_type: str, entity_id: str, action: str, details: dict[str, Any] | None = None) -> None:
    owner = current_owner()
    s.add(AuditEventRow(entity_type=entity_type, entity_id=entity_id, action=action, details=details or {},
                        actor_id=owner if isinstance(owner, str) else None))


def canonical_hash(doc: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dump_problem(problem: Problem, record_id: str) -> dict[str, Any]:
    problem = problem.model_copy(update={"id": record_id})
    return problem.model_dump(mode="json")


def load_problem(doc: dict[str, Any]) -> Problem:
    return Problem.model_validate(doc)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "plan"


def parse_if_match(value: str | None) -> int:
    if value is None or not value.strip():
        raise ApiError(428, "PRECONDITION_REQUIRED",
                       'Send the version you edited in an If-Match header, e.g. If-Match: "3".')
    v = value.strip()
    if v.startswith("W/"):
        v = v[2:]
    v = v.strip().strip('"').strip()
    try:
        return int(v)
    except ValueError:
        raise ApiError(428, "PRECONDITION_REQUIRED", f"If-Match header {value!r} is not a version number.")


def get_problem_row(s: Session, problem_id: str, lock: bool = False, for_delete: bool = False) -> ProblemRow:
    """`lock=True`: FOR NO KEY UPDATE (PHASE2B 2.12, R4); `for_delete=True`: plain FOR UPDATE."""
    row = get_locked(s, ProblemRow, problem_id, for_delete=for_delete) if (lock or for_delete) \
        else s.get(ProblemRow, problem_id)
    if row is None:
        raise not_found("Problem", problem_id)
    return row


def has_active_run(s: Session, problem_id: str) -> SolverRunRow | None:
    return s.scalars(select(SolverRunRow).where(SolverRunRow.problem_id == problem_id,
                                                SolverRunRow.status.in_(ACTIVE_RUN_STATUSES))).first()


def record(row: ProblemRow) -> dict[str, Any]:
    return {"id": row.id, "version": row.version, "template_id": row.template_id,
            "created_at": iso_utc(row.created_at), "updated_at": iso_utc(row.updated_at),
            "problem": row.document}


def summary(s: Session, row: ProblemRow) -> dict[str, Any]:
    approved = s.scalars(select(ScheduleRow.id).where(ScheduleRow.problem_id == row.id,
                                                      ScheduleRow.status == "approved")).first()
    latest = s.scalars(select(SolverRunRow).where(SolverRunRow.problem_id == row.id)
                       .order_by(SolverRunRow.created_at.desc(), SolverRunRow.id.desc())).first()
    doc = row.document or {}
    return {"id": row.id, "name": row.name, "domain": row.domain, "version": row.version,
            "task_count": len(doc.get("tasks") or []), "resource_count": len(doc.get("resources") or []),
            "updated_at": iso_utc(row.updated_at), "approved_schedule_id": approved,
            "latest_run": {"id": latest.id, "status": latest.status} if latest else None}


def _insert(s: Session, problem: Problem, template_id: str | None, action: str) -> ProblemRow:
    pid = new_id("p_")
    doc = dump_problem(problem, pid)
    now = utcnow()
    row = ProblemRow(id=pid, name=doc["name"], domain=doc["domain"], template_id=template_id, version=1,
                     document=doc, created_at=now, updated_at=now)
    s.add(row)
    s.flush()
    audit(s, "problem", pid, action, {"version": 1, "template_id": template_id})
    return row


# ---------------------------------------------------------------- CRUD

def list_problems(ctx: AppContext) -> list[dict[str, Any]]:
    with ctx.db.read() as s:
        rows = s.scalars(select(ProblemRow).order_by(ProblemRow.updated_at.desc(), ProblemRow.id.desc())
                         .limit(MAX_LIST_ITEMS)).all()
        return [summary(s, r) for r in rows]


def create_problem(ctx: AppContext, problem: Problem) -> dict[str, Any]:
    with ctx.db.write() as s:
        row = _insert(s, problem, None, "problem.created")
        return record(row)


def get_problem(ctx: AppContext, problem_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        return record(get_problem_row(s, problem_id))


def update_problem(ctx: AppContext, problem_id: str, problem: Problem, if_match: str | None) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        row = get_problem_row(s, problem_id, lock=True)
        expected = parse_if_match(if_match)
        if expected != row.version:
            raise ApiError(412, "VERSION_MISMATCH",
                           f"The plan was changed elsewhere (now version {row.version}, you edited {expected}).",
                           {"current_version": row.version})
        doc = dump_problem(problem, problem_id)
        row.document = doc
        row.name = doc["name"]
        row.domain = doc["domain"]
        row.version += 1
        row.updated_at = utcnow()
        audit(s, "problem", problem_id, "problem.updated", {"version": row.version})
        return record(row)


def delete_problem(ctx: AppContext, problem_id: str) -> None:
    with ctx.write_guard(), ctx.db.write() as s:
        get_problem_row(s, problem_id, for_delete=True)
        active = has_active_run(s, problem_id)
        if active is not None:
            raise ApiError(409, "RUN_ALREADY_ACTIVE",
                           "This plan has a running optimization; cancel it before deleting the plan.",
                           {"run_id": active.id})
        # Core DELETE so the database's ON DELETE CASCADE removes versions, runs, events and schedules.
        s.execute(delete(ProblemRow).where(ProblemRow.id == problem_id))
        audit(s, "problem", problem_id, "problem.deleted", {})


def export_problem(ctx: AppContext, problem_id: str) -> tuple[dict[str, Any], str]:
    with ctx.db.read() as s:
        row = get_problem_row(s, problem_id)
        body = {"format": "superplanner.problem", "format_version": 1, "exported_at": iso_utc(utcnow()),
                "problem": row.document}
        return body, f"{slugify(row.name)}.superplanner.json"


def import_problem(ctx: AppContext, payload: ExportFile) -> dict[str, Any]:
    with ctx.db.write() as s:
        row = _insert(s, payload.problem, None, "problem.imported")
        return record(row)


# ---------------------------------------------------------------- templates

def list_templates() -> list[dict[str, Any]]:
    out = []
    for t in TEMPLATES.values():
        out.append({"id": t.id, "name": t.name, "domain": t.domain, "description": t.description,
                    "terminology": t.terminology.model_dump(mode="json"),
                    "parameters": [p.model_dump(mode="json") for p in t.parameters]})
    return out


def _tz(offset: str) -> timezone:
    sign = 1 if offset[0] == "+" else -1
    hours, minutes = int(offset[1:3]), int(offset[4:6])
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def instantiate_template(ctx: AppContext, template_id: str, req: InstantiateRequest) -> dict[str, Any]:
    try:
        template = get_template(template_id)
    except KeyError:
        raise not_found("Template", template_id)
    try:
        tz = _tz(req.utc_offset)
        start: date = req.start_date or datetime.now(UTC).astimezone(tz).date()
        problem = template.build(name=req.name or template.name, start_date=start, utc_offset=req.utc_offset,
                                 params=dict(req.parameters))
    except ValidationError as exc:
        raise validation_error(list(exc.errors()), ("body", "parameters"), "The template parameters are not valid.")
    except (ValueError, TypeError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", f"The template parameters are not valid: {exc}",
                       {"errors": [{"loc": ["body", "parameters"], "msg": str(exc), "type": "value_error"}]})
    with ctx.db.write() as s:
        row = _insert(s, problem, template_id, "problem.created")
        return record(row)


# ---------------------------------------------------------------- validate

def validate_problem(ctx: AppContext, problem_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        row = get_problem_row(s, problem_id)
        version, doc = row.version, row.document
    report = engine.analyze(load_problem(doc))
    out = {"problem_version": version}
    out.update(report.model_dump(mode="json"))
    return out


# ---------------------------------------------------------------- snapshots

def snapshot(s: Session, row: ProblemRow, doc: dict[str, Any] | None = None, kind: str = "snapshot") -> ProblemVersionRow:
    """Immutable copy of a document. `snapshot` rows are reused on identical (hash, base_version)."""
    doc = row.document if doc is None else doc
    h = canonical_hash(doc)
    if kind == "snapshot":
        existing = s.scalars(select(ProblemVersionRow).where(
            ProblemVersionRow.problem_id == row.id, ProblemVersionRow.kind == "snapshot",
            ProblemVersionRow.content_hash == h, ProblemVersionRow.base_version == row.version)).first()
        if existing is not None:
            return existing
    pv = ProblemVersionRow(id=new_id("pv_"), problem_id=row.id, base_version=row.version, kind=kind,
                           content_hash=h, document=doc)
    s.add(pv)
    s.flush()
    return pv

