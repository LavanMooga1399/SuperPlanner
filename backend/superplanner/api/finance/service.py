"""Finance plans: CRUD with If-Match, start-month filling, `whatif_` id rejection, export/import, templates,
defaults, preview and validate (FINANCE.md 3, 4, 17, 18.2).

Audit details carry ids, versions and counts only (never amounts or names, F.21 rule 7).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from superplanner import finance

from ..context import WRITE_LOCK, AppContext
from ..db import new_id, utcnow
from ..errors import ApiError, not_found, validation_error
from ..schemas import iso_utc
from ..services.problem_service import audit, canonical_hash, parse_if_match, slugify
from .db_models import FinancePlanRow, FinancePlanVersionRow, FinanceResultRow, FinanceRunRow
from .schemas import FinanceExportFile, FinanceInstantiateRequest

MAX_LIST_ITEMS = 500
ACTIVE_RUN_STATUSES = ("queued", "running")
WHATIF_PREFIX = "whatif_"
ITEM_LISTS = ("incomes", "expenses", "debts", "holdings", "one_offs", "goals")
LIMITS = {"goals": 12, "incomes": 20, "expenses": 100, "debts": 20, "holdings": 50, "one_offs": 200,
          "asset_classes": 10, "horizon_months": 600}


# ---------------------------------------------------------------- helpers

def current_utc_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def fill_start_month(plan: finance.FinancePlan) -> finance.FinancePlan:
    """Services fill a missing `start_month` with the current UTC month on every write (3)."""
    if plan.start_month is None:
        return plan.model_copy(update={"start_month": current_utc_month()})
    return plan


def reject_whatif_ids(plan: finance.FinancePlan, loc_prefix: tuple[Any, ...] = ("body",)) -> None:
    """Stored documents never contain `whatif_` ids (4, [R12]): 422 with the item path in `loc`."""
    errors: list[dict[str, Any]] = []
    for lst in ITEM_LISTS:
        for i, item in enumerate(getattr(plan, lst)):
            if item.id.startswith(WHATIF_PREFIX):
                errors.append({"loc": [lst, i, "id"], "type": "value_error",
                               "msg": f"ids starting with '{WHATIF_PREFIX}' are reserved for what-if scenarios"})
    for i, ac in enumerate(plan.assumptions.asset_classes):
        if ac.id.startswith(WHATIF_PREFIX):
            errors.append({"loc": ["assumptions", "asset_classes", i, "id"], "type": "value_error",
                           "msg": f"ids starting with '{WHATIF_PREFIX}' are reserved for what-if scenarios"})
    if errors:
        raise validation_error(errors, loc_prefix, "Some ids use the reserved prefix 'whatif_'.")


def dump_plan(plan: finance.FinancePlan, record_id: str) -> dict[str, Any]:
    return plan.model_copy(update={"id": record_id}).model_dump(mode="json")


def load_plan(doc: dict[str, Any]) -> finance.FinancePlan:
    return finance.FinancePlan.model_validate(doc)


def get_plan_row(s: Session, plan_id: str) -> FinancePlanRow:
    row = s.get(FinancePlanRow, plan_id)
    if row is None:
        raise not_found("Finance plan", plan_id)
    return row


def active_run(s: Session, plan_id: str) -> FinanceRunRow | None:
    """Active = queued/running and not cancel-requested (18.2 semantics)."""
    return s.scalars(select(FinanceRunRow).where(FinanceRunRow.plan_id == plan_id,
                                                 FinanceRunRow.status.in_(ACTIVE_RUN_STATUSES),
                                                 FinanceRunRow.cancel_requested.is_(False))
                     .order_by(FinanceRunRow.created_at.desc())).first()


def record(row: FinancePlanRow) -> dict[str, Any]:
    return {"id": row.id, "version": row.version, "template_id": row.template_id,
            "created_at": iso_utc(row.created_at), "updated_at": iso_utc(row.updated_at), "plan": row.document}


def plan_summary(s: Session, row: FinancePlanRow) -> dict[str, Any]:
    doc = row.document or {}
    latest_run = s.scalars(select(FinanceRunRow).where(FinanceRunRow.plan_id == row.id)
                           .order_by(FinanceRunRow.created_at.desc(), FinanceRunRow.id.desc())).first()
    latest_res = s.scalars(select(FinanceResultRow).where(FinanceResultRow.plan_id == row.id,
                                                          FinanceResultRow.kind == "baseline")
                           .order_by(FinanceResultRow.created_at.desc(), FinanceResultRow.id.desc())).first()
    return {
        "id": row.id, "name": row.name, "version": row.version,
        "currency": (doc.get("profile") or {}).get("currency", "INR"), "goal_count": len(doc.get("goals") or []),
        "template_id": row.template_id, "updated_at": iso_utc(row.updated_at),
        "latest_run": {"id": latest_run.id, "status": latest_run.status} if latest_run else None,
        "latest_result": ({"id": latest_res.id, "feasibility": latest_res.feasibility,
                           "goals_on_track": int(latest_res.summary.get("goals_on_track", 0)),
                           "goals_total": int(latest_res.summary.get("goals_total", 0))} if latest_res else None),
    }


def _insert(s: Session, plan: finance.FinancePlan, template_id: str | None, action: str) -> FinancePlanRow:
    pid = new_id("fp_")
    doc = dump_plan(fill_start_month(plan), pid)
    now = utcnow()
    row = FinancePlanRow(id=pid, name=doc["name"], template_id=template_id, version=1, document=doc,
                         created_at=now, updated_at=now)
    s.add(row)
    s.flush()
    audit(s, "finance_plan", pid, action, {"version": 1, "template_id": template_id})
    return row


def snapshot(s: Session, row: FinancePlanRow, doc: dict[str, Any] | None = None, kind: str = "snapshot",
             base_version: int | None = None) -> FinancePlanVersionRow:
    """Immutable copy. `snapshot` rows are reused on identical (plan_id, kind, hash, base_version); what-if
    snapshots never are (17)."""
    doc = row.document if doc is None else doc
    base = row.version if base_version is None else base_version
    h = canonical_hash(doc)
    if kind == "snapshot":
        existing = s.scalars(select(FinancePlanVersionRow).where(
            FinancePlanVersionRow.plan_id == row.id, FinancePlanVersionRow.kind == "snapshot",
            FinancePlanVersionRow.content_hash == h, FinancePlanVersionRow.base_version == base)).first()
        if existing is not None:
            return existing
    pv = FinancePlanVersionRow(id=new_id("fpv_"), plan_id=row.id, base_version=base, kind=kind, content_hash=h,
                               document=doc, created_at=utcnow())
    s.add(pv)
    s.flush()
    return pv


# ---------------------------------------------------------------- CRUD

def list_plans(ctx: AppContext) -> list[dict[str, Any]]:
    with ctx.db.read() as s:
        rows = s.scalars(select(FinancePlanRow).order_by(FinancePlanRow.updated_at.desc(), FinancePlanRow.id.desc())
                         .limit(MAX_LIST_ITEMS)).all()
        return [plan_summary(s, r) for r in rows]


def create_plan(ctx: AppContext, plan: finance.FinancePlan) -> dict[str, Any]:
    reject_whatif_ids(plan)
    with ctx.db.write() as s:
        return record(_insert(s, plan, None, "finance_plan.created"))


def get_plan(ctx: AppContext, plan_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        return record(get_plan_row(s, plan_id))


def update_plan(ctx: AppContext, plan_id: str, plan: finance.FinancePlan, if_match: str | None) -> dict[str, Any]:
    with WRITE_LOCK, ctx.db.write() as s:
        row = get_plan_row(s, plan_id)
        expected = parse_if_match(if_match)
        if expected != row.version:
            raise ApiError(412, "VERSION_MISMATCH",
                           f"The plan was changed elsewhere (now version {row.version}, you edited {expected}).",
                           {"current_version": row.version})
        reject_whatif_ids(plan)
        doc = dump_plan(fill_start_month(plan), plan_id)
        row.document = doc
        row.name = doc["name"]
        row.version += 1
        row.updated_at = utcnow()
        audit(s, "finance_plan", plan_id, "finance_plan.updated", {"version": row.version})
        return record(row)


def delete_plan(ctx: AppContext, plan_id: str) -> None:
    with WRITE_LOCK, ctx.db.write() as s:
        get_plan_row(s, plan_id)
        active = active_run(s, plan_id)
        if active is not None:
            raise ApiError(409, "RUN_ACTIVE", "This plan has a run in progress; cancel it before deleting the plan.",
                           {"run_id": active.id})
        # Core DELETE: the database's ON DELETE CASCADE removes versions, runs, events and results. A
        # cancel-requested run still executing finds its row gone and discards its output.
        s.execute(delete(FinancePlanRow).where(FinancePlanRow.id == plan_id))
        audit(s, "finance_plan", plan_id, "finance_plan.deleted", {})


def export_plan(ctx: AppContext, plan_id: str) -> tuple[dict[str, Any], str]:
    with ctx.db.read() as s:
        row = get_plan_row(s, plan_id)
        body = {"format": "superplanner.finance_plan", "format_version": 1, "exported_at": iso_utc(utcnow()),
                "plan": row.document}
        return body, f"{slugify(row.name)}.finance.json"


def import_plan(ctx: AppContext, payload: FinanceExportFile) -> dict[str, Any]:
    reject_whatif_ids(payload.plan, ("body", "plan"))
    with ctx.db.write() as s:
        return record(_insert(s, payload.plan, None, "finance_plan.imported"))


# ---------------------------------------------------------------- templates and defaults

def list_templates() -> list[dict[str, Any]]:
    return [{"id": t.id, "name": t.name, "description": t.description,
             "parameters": [p.model_dump(mode="json") for p in t.parameters]} for t in finance.TEMPLATES.values()]


def instantiate_template(ctx: AppContext, template_id: str, req: FinanceInstantiateRequest) -> dict[str, Any]:
    try:
        template = finance.get_template(template_id)
    except KeyError:
        raise not_found("Template", template_id)
    try:
        plan = template.build(name=req.name or template.name, start_month=req.start_month or current_utc_month(),
                              params=dict(req.parameters))
    except ValidationError as exc:
        raise validation_error(list(exc.errors()), ("body", "parameters"), "The template parameters are not valid.")
    except (ValueError, TypeError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", f"The template parameters are not valid: {exc}",
                       {"errors": [{"loc": ["body", "parameters"], "msg": str(exc), "type": "value_error"}]})
    reject_whatif_ids(plan, ("body", "plan"))
    with ctx.db.write() as s:
        return record(_insert(s, plan, template_id, "finance_plan.created"))


def defaults() -> dict[str, Any]:
    return {"plan": finance.default_plan(start_month=current_utc_month()).model_dump(mode="json"),
            "disclaimer": finance.DISCLAIMER, "disclaimer_version": finance.DISCLAIMER_VERSION,
            "limits": dict(LIMITS)}


# ---------------------------------------------------------------- preview and validate

def check_plan(plan: finance.FinancePlan) -> dict[str, Any]:
    report = finance.preflight(plan)
    cashflow = None
    if report.ok:
        cashflow = finance.summarize_cashflow(finance.project_cashflow(plan)).model_dump(mode="json")
    return {"ok": report.ok, "issues": [i.model_dump(mode="json") for i in report.issues], "cashflow": cashflow}


def preview(plan: finance.FinancePlan) -> dict[str, Any]:
    return check_plan(fill_start_month(plan))


def validate_plan(ctx: AppContext, plan_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        row = get_plan_row(s, plan_id)
        version, doc = row.version, row.document
    out: dict[str, Any] = {"plan_version": version}
    out.update(check_plan(load_plan(doc)))
    return out
