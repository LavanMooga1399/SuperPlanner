"""Apply an `ImportPlan` with ORM writes in the caller's transaction (M1-DESIGN 6.1, 8.1, review R5/R9).

Order: child deletes first (ORM `delete()` statements, owner-filtered, children before parents), then per table in
FK order updates (rows selected by id in `SQL_IN_CHUNK` chunks) and inserts (`add_all`), with one `flush()` per
table. Ids come from the plan (`new_id`), never from a bundle. The caller locks the plant first and commits.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from ...mfg.io.plan import ImportPlan
from ...mfg.limits import SQL_IN_CHUNK
from ..db import utcnow
from .db_models import (MfgBomLineRow, MfgBomRow, MfgCalendarExceptionRow, MfgGroupRow, MfgItemRow, MfgLineItemRow,
                        MfgLineRow, MfgOperationRow, MfgOperationToolRow, MfgOperatorRow, MfgOperatorSkillRow,
                        MfgPlantRow, MfgRoutingRow, MfgShiftAssignmentRow, MfgShiftTemplateRow, MfgSkillRow,
                        MfgToolPoolRow)

TABLES: dict[str, Any] = {
    "items": MfgItemRow, "groups": MfgGroupRow, "skills": MfgSkillRow, "tool_pools": MfgToolPoolRow,
    "shift_templates": MfgShiftTemplateRow, "lines": MfgLineRow, "line_items": MfgLineItemRow, "boms": MfgBomRow,
    "bom_lines": MfgBomLineRow, "routings": MfgRoutingRow, "operations": MfgOperationRow,
    "operation_tools": MfgOperationToolRow, "shift_assignments": MfgShiftAssignmentRow,
    "calendar_exceptions": MfgCalendarExceptionRow, "operators": MfgOperatorRow,
    "operator_skills": MfgOperatorSkillRow,
}
ORDER = ("items", "groups", "skills", "tool_pools", "shift_templates", "lines", "line_items", "boms", "bom_lines",
         "routings", "operations", "operation_tools", "shift_assignments", "calendar_exceptions", "operators",
         "operator_skills")
DELETE_ORDER = ("operation_tools", "operations", "bom_lines", "line_items", "operator_skills")
LINKS = {"line_items": ("line_id", "item_id"), "operator_skills": ("operator_id", "skill_id"),
         "operation_tools": ("operation_id", "tool_pool_id")}

#: test hook: called after each table's flush with the table name (fault injection, B3-3)
FAULT_HOOK: Callable[[str], None] | None = None


def _chunks(xs: list[Any]) -> list[list[Any]]:
    return [xs[i:i + SQL_IN_CHUNK] for i in range(0, len(xs), SQL_IN_CHUNK)]


def _plain_columns(table: str, values: dict[str, Any]) -> dict[str, Any]:
    v = dict(values)
    if table == "shift_templates" and "shifts" in v:
        v["shifts"] = [dict(sh) for sh in v["shifts"]]
    if table == "items" and "attributes" in v:
        v["attributes"] = dict(v["attributes"])
    if table == "operations":
        v.pop("tools", None)
    if table == "lines":
        v.pop("eligible_item_ids", None)
    if table == "operators":
        v.pop("skill_ids", None)
    return v


def apply(s: Session, plan: ImportPlan, plant: MfgPlantRow, now: datetime | None = None) -> dict[str, int]:
    """Execute the plan; returns written row counts per table."""
    now = now or utcnow()
    written: dict[str, int] = {}
    by_table: dict[str, list[Any]] = {}
    for c in plan.changes:
        by_table.setdefault(c.table, []).append(c)
    # plant
    for c in by_table.get("plant", []):
        for k, v in c.values.items():
            setattr(plant, k, v)
        plant.row_version = (plant.row_version or 0) + 1
        plant.updated_at = now
        s.flush()
        written["plant"] = 1
    # child deletes
    for table in DELETE_ORDER:
        dels = [c for c in by_table.get(table, []) if c.action == "delete"]
        if not dels:
            continue
        model = TABLES[table]
        if table in LINKS:
            a, b = LINKS[table]
            for chunk in _chunks(dels):
                cond = or_(*[and_(getattr(model, a) == c.id[0], getattr(model, b) == c.id[1]) for c in chunk])
                s.execute(delete(model).where(cond).execution_options(synchronize_session=False))
        else:
            for chunk in _chunks([c.id for c in dels]):
                s.execute(delete(model).where(model.id.in_(chunk)).execution_options(synchronize_session=False))
        written[f"{table}_deleted"] = len(dels)
    # updates + inserts in FK order
    for table in ORDER:
        model = TABLES[table]
        changes = by_table.get(table, [])
        ups = [c for c in changes if c.action == "update"]
        bump = sorted(plan.bump.get(table, set()))
        ids = [c.id for c in ups] + [b for b in bump if b not in {c.id for c in ups}]
        if ids:
            rows: dict[str, Any] = {}
            for chunk in _chunks(ids):
                for r in s.execute(select(model).where(model.id.in_(chunk))).scalars():
                    rows[r.id] = r
            for c in ups:
                r = rows[c.id]
                for k, v in _plain_columns(table, c.values).items():
                    setattr(r, k, v)
            for i in ids:
                r = rows[i]
                r.row_version = (r.row_version or 0) + 1
                r.updated_at = now
        news = [c for c in changes if c.action == "create"]
        if news:
            objs = []
            for c in news:
                vals = _plain_columns(table, c.values)
                if table in ("line_items", "operator_skills"):
                    a, b = LINKS[table]
                    objs.append(model(**{a: c.id[0], b: c.id[1]}))
                    continue
                if table in ("boms", "routings"):
                    st = vals.get("status", "draft")
                    vals.setdefault("released_at", now if st != "draft" else None)
                    vals.setdefault("obsoleted_at", now if st == "obsolete" else None)
                objs.append(model(id=c.id, row_version=1, created_at=now, updated_at=now, **vals))
            s.add_all(objs)
        if ids or news:
            s.flush()
            written[table] = len(ids) + len(news)
            if FAULT_HOOK is not None:
                FAULT_HOOK(table)
    return written
