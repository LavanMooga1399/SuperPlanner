"""Helpers for tests/mfg_db: database setup, an ORM writer for pure datasets, a SQL statement counter."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event

from superplanner import migrate
from superplanner.api.auth.models import UserRow
from superplanner.api.db import Database
from superplanner.api.db import ownership
from superplanner.api.db.models import new_id
from superplanner.api.mfg import db_models as m
from superplanner.api.mfg import db_models_m2 as m2
from superplanner.api.mfg.repo import plant_mrp_columns
from superplanner.mfg.model_m2 import ItemSupplierInput, SupplierInput
from superplanner.mfg.dataset import MfgDataset

USERS = ("usr_a", "usr_b")


def open_db(url: str) -> Database:
    migrate.ensure_schema(url)
    db = Database(url)
    ownership.install(db, single_user=False)
    now = datetime.now(UTC)
    with ownership.system_scope(), db.write() as s:
        for u in USERS:
            if s.get(UserRow, u) is None:
                s.add(UserRow(id=u, email=f"{u}@example.com", display_name=u, is_local=False, disabled=False,
                              created_at=now, updated_at=now))
    return db


def write_dataset(s: Any, ds: MfgDataset) -> dict[str, str]:
    """Write a pure dataset as ORM rows (fresh `new_id`s, one flush per table in FK order); returns old id -> new
    id. The plant row is written too (data_version 0)."""
    ids: dict[str, str] = {}

    def nid(old: str) -> str:
        if old not in ids:
            ids[old] = new_id(old[:4])
        return ids[old]

    def opt(old: str | None) -> str | None:
        return nid(old) if old is not None else None

    now = datetime.now(UTC)
    st = {"row_version": 1, "created_at": now, "updated_at": now}
    p = ds.plant
    s.add(m.MfgPlantRow(id=new_id("plt_"), name=p.name, utc_offset=p.utc_offset,
                        planning_horizon_days=p.planning_horizon_days, currency=p.currency,
                        attributes=dict(p.attributes), data_version=0, **plant_mrp_columns(p), **st))
    s.flush()
    for it in ds.items.values():
        s.add(m.MfgItemRow(id=nid(it.id), part_number=it.part_number, revision=it.revision,
                           description=it.description, uom=it.uom, make_buy=it.make_buy, family=it.family,
                           setup_family=it.setup_family, lead_time_days=it.lead_time_days,
                           receiving_days=it.receiving_days, lot_rule=it.lot_rule, fixed_lot_qty=it.fixed_lot_qty,
                           min_order_qty=it.min_order_qty, order_multiple=it.order_multiple,
                           safety_stock=it.safety_stock, serialized=it.serialized, shelf_life_days=it.shelf_life_days,
                           handling_class=it.handling_class, handling_note=it.handling_note,
                           attributes=dict(it.attributes), active=it.active, external_ref=it.external_ref,
                           standard_cost=it.standard_cost, lot_controlled=it.lot_controlled,
                           lot_period_days=it.lot_period_days, **st))
    s.flush()
    for g in ds.groups.values():
        s.add(m.MfgGroupRow(id=nid(g.id), code=g.code, name=g.name, description=g.description, kind=g.kind,
                            active=g.active, **st))
    for sk in ds.skills.values():
        s.add(m.MfgSkillRow(id=nid(sk.id), code=sk.code, name=sk.name, description=sk.description, **st))
    for tp in ds.tool_pools.values():
        s.add(m.MfgToolPoolRow(id=nid(tp.id), code=tp.code, name=tp.name, kind=tp.kind, quantity=tp.quantity,
                               note=tp.note, **st))
    for t in ds.shift_templates.values():
        s.add(m.MfgShiftTemplateRow(id=nid(t.id), code=t.code, name=t.name, description=t.description,
                                    shifts=[sh.model_dump() for sh in t.shifts], **st))
    s.flush()
    for ln in ds.lines.values():
        s.add(m.MfgLineRow(id=nid(ln.id), group_id=nid(ln.group_id), code=ln.code, name=ln.name,
                           speed_factor=ln.speed_factor, parallel_capacity=ln.parallel_capacity,
                           setup_family=ln.setup_family, eligible_families=list(ln.eligible_families),
                           cost_per_hour=ln.cost_per_hour, active=ln.active, **st))
    s.flush()
    for ln in ds.lines.values():
        for i in ln.eligible_item_ids:
            s.add(m.MfgLineItemRow(line_id=nid(ln.id), item_id=nid(i)))
    for b in ds.boms.values():
        s.add(m.MfgBomRow(id=nid(b.id), item_id=nid(b.item_id), revision=b.revision, version=b.version,
                          status=b.status, effective_from=b.effective_from, effective_to=b.effective_to,
                          serial_from=b.serial_from, serial_to=b.serial_to, note=b.note, released_at=b.released_at,
                          obsoleted_at=b.obsoleted_at, **st))
    s.flush()
    for b in ds.boms.values():
        for ln in b.lines:
            s.add(m.MfgBomLineRow(id=nid(ln.id), bom_id=nid(b.id), find_number=ln.find_number,
                                  child_item_id=nid(ln.child_item_id), qty_per=ln.qty_per, uom=ln.uom,
                                  scrap_pct=ln.scrap_pct, ref_designators=ln.ref_designators, alt_group=ln.alt_group,
                                  alt_priority=ln.alt_priority, operation_seq=ln.operation_seq, note=ln.note, **st))
    for r in ds.routings.values():
        s.add(m.MfgRoutingRow(id=nid(r.id), item_id=nid(r.item_id), revision=r.revision, code=r.code,
                              version=r.version, priority=r.priority, status=r.status,
                              effective_from=r.effective_from, effective_to=r.effective_to,
                              serial_from=r.serial_from, serial_to=r.serial_to, note=r.note,
                              released_at=r.released_at, obsoleted_at=r.obsoleted_at, **st))
    s.flush()
    for r in ds.routings.values():
        for op in r.operations:
            s.add(m.MfgOperationRow(
                id=nid(op.id), routing_id=nid(r.id), seq=op.seq, name=op.name, description=op.description,
                group_id=nid(op.group_id), setup_minutes=op.setup_minutes, run_minutes=op.run_minutes,
                run_per=op.run_per, units_per_panel=op.units_per_panel, units_per_batch=op.units_per_batch,
                queue_minutes=op.queue_minutes, move_minutes=op.move_minutes, wait_minutes=op.wait_minutes,
                labor=op.labor, crew_size=op.crew_size, skill_id=opt(op.skill_id), transfer_batch=op.transfer_batch,
                yield_pct=op.yield_pct, inspection_gate=op.inspection_gate, interruptible=op.interruptible, **st))
    s.flush()
    for r in ds.routings.values():
        for op in r.operations:
            for t in op.tools:
                s.add(m.MfgOperationToolRow(id=new_id("otl_"), operation_id=nid(op.id),
                                            tool_pool_id=nid(t.tool_pool_id), qty=t.qty, **st))
    for a in ds.shift_assignments.values():
        s.add(m.MfgShiftAssignmentRow(
            id=nid(a.id), shift_template_id=nid(a.shift_template_id), target_type=a.target_type,
            group_id=opt(a.group_id), line_id=opt(a.line_id), kind=a.kind, shift_names=list(a.shift_names),
            effective_from=a.effective_from, effective_to=a.effective_to, cost_per_hour=a.cost_per_hour,
            max_hours_per_week=a.max_hours_per_week, note=a.note, **st))
    for e in ds.calendar_exceptions.values():
        s.add(m.MfgCalendarExceptionRow(id=nid(e.id), scope=e.scope, group_id=opt(e.group_id),
                                        line_id=opt(e.line_id), kind=e.kind, start_at=e.start.astimezone(UTC),
                                        end_at=e.end.astimezone(UTC), label=e.label, **st))
    for o in ds.operators.values():
        s.add(m.MfgOperatorRow(id=nid(o.id), code=o.code, name=o.name, shift_template_id=opt(o.shift_template_id),
                               shift_names=list(o.shift_names), home_group_id=opt(o.home_group_id), active=o.active,
                               **st))
    s.flush()
    for o in ds.operators.values():
        for sk in o.skill_ids:
            s.add(m.MfgOperatorSkillRow(operator_id=nid(o.id), skill_id=nid(sk)))
    s.flush()
    # M2 master data (M2-DESIGN 3.2, 3.3)
    for x in ds.locations.values():
        s.add(m2.MfgLocationRow(id=nid(x.id), code=x.code, name=x.name, kind=x.kind, receipt_default=x.receipt_default,
                                active=x.active, external_ref=x.external_ref, note=x.note, **st))
    for x in ds.suppliers.values():
        s.add(m2.MfgSupplierRow(id=nid(x.id), **{f: getattr(x, f) for f in SupplierInput.model_fields}, **st))
    s.flush()
    for x in ds.item_suppliers.values():
        vals = {f: getattr(x, f) for f in ItemSupplierInput.model_fields}
        vals.update(item_id=nid(x.item_id), supplier_id=nid(x.supplier_id))
        s.add(m2.MfgItemSupplierRow(id=nid(x.id), **vals, **st))
    s.flush()
    return ids


class StatementCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)


@contextmanager
def count_statements(db: Database) -> Iterator[StatementCounter]:
    """Counts SELECT/INSERT/UPDATE/DELETE statements (not BEGIN/SAVEPOINT/PRAGMA) sent through the engine."""
    counter = StatementCounter()

    def before(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
        if head in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH"):
            counter.statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", before)
    try:
        yield counter
    finally:
        event.remove(db.engine, "before_cursor_execute", before)
