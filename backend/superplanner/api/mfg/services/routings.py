"""Routing documents (M1-DESIGN 3.6, 4.2; 9.3 #13, #21-28) and the time preview."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.dataset import MfgDataset, item_ref, ref
from ....mfg.model import OperationInput, PlantRecord, RoutingInput, RoutingRecord
from ....mfg.release import ReleaseError, routing_release_issues, validate_routing_document
from ....mfg.routing import time_preview as _time_preview
from ...context import AppContext
from ...db import new_id, utcnow
from .. import repo
from ..db_models import (MfgGroupRow, MfgItemRow, MfgLineItemRow, MfgLineRow, MfgOperationRow, MfgOperationToolRow,
                         MfgRoutingRow, MfgSkillRow, MfgToolPoolRow)
from .boms import (check_ids_kept, check_serial, document_errors, invalid_state, item_for_document, readonly,
                   release_blocked, release_error, write_children)
from .common import audit, check_limit, check_version, ensure_unique, jsonable, read_tx, touch, write_tx

OP_FIELDS = ("seq", "name", "description", "group_id", "setup_minutes", "run_minutes", "run_per", "units_per_panel",
             "units_per_batch", "queue_minutes", "move_minutes", "wait_minutes", "labor", "crew_size", "skill_id",
             "transfer_batch", "yield_pct", "inspection_gate", "interruptible", "capture_serial")
HEADER_FIELDS = ("priority", "effective_from", "effective_to", "serial_from", "serial_to", "note")


def routing_record(s: Session, row: MfgRoutingRow) -> RoutingRecord:
    ops = list(s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id == row.id)
                         .order_by(MfgOperationRow.seq)).scalars())
    op_ids = [o.id for o in ops]
    tools = list(s.execute(select(MfgOperationToolRow).where(MfgOperationToolRow.operation_id.in_(op_ids))
                           .order_by(MfgOperationToolRow.id)).scalars()) if op_ids else []
    gids = sorted({o.group_id for o in ops})
    sids = sorted({o.skill_id for o in ops if o.skill_id})
    pids = sorted({t.tool_pool_id for t in tools})
    groups = {g.id: g for g in s.execute(select(MfgGroupRow).where(MfgGroupRow.id.in_(gids))).scalars()} if gids \
        else {}
    skills = {k.id: k for k in s.execute(select(MfgSkillRow).where(MfgSkillRow.id.in_(sids))).scalars()} if sids \
        else {}
    pools = {p.id: p for p in s.execute(select(MfgToolPoolRow).where(MfgToolPoolRow.id.in_(pids))).scalars()} \
        if pids else {}
    item = s.execute(select(MfgItemRow).where(MfgItemRow.id == row.item_id)).scalars().first()
    by_op: dict[str, list[Any]] = {}
    for t in tools:
        by_op.setdefault(t.operation_id, []).append(
            repo.to_record(t, tool_pool=ref(pools[t.tool_pool_id]) if t.tool_pool_id in pools else None))
    recs = [repo.to_record(o, tools=by_op.get(o.id, []), group=ref(groups[o.group_id]) if o.group_id in groups
                           else None, skill=ref(skills[o.skill_id]) if o.skill_id in skills else None) for o in ops]
    return repo.to_record(row, operations=recs, item=item_ref(repo.to_record(item)))


def get_routing(ctx: AppContext, routing_id: str) -> RoutingRecord:
    with read_tx(ctx) as s:
        return routing_record(s, repo.get_row(s, MfgRoutingRow, routing_id, what="Routing"))


def list_item_routings(ctx: AppContext, item_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        item = repo.get_row(s, MfgItemRow, item_id, what="Item")
        iref = item_ref(repo.to_record(item))
        rows = list(s.execute(select(MfgRoutingRow).where(MfgRoutingRow.item_id == item.id).order_by(
            MfgRoutingRow.priority, MfgRoutingRow.code, MfgRoutingRow.revision, MfgRoutingRow.version)).scalars())
        counts = dict(s.execute(select(MfgOperationRow.routing_id, func.count()).where(
            MfgOperationRow.routing_id.in_([r.id for r in rows])).group_by(MfgOperationRow.routing_id)).all()) \
            if rows else {}
        out = []
        for r in rows:
            d = jsonable(repo.to_record(r, item=iref))
            d.pop("operations", None)
            d["operation_count"] = int(counts.get(r.id, 0))
            out.append(d)
        return {"items": out}


def _validate_ops(s: Session, item_id: str, ops: list[OperationInput]) -> None:
    gids = sorted({o.group_id for o in ops})
    sids = sorted({o.skill_id for o in ops if o.skill_id})
    pids = sorted({t.tool_pool_id for o in ops for t in o.tools})
    ds = MfgDataset(plant=PlantRecord())
    for model, ids, target in ((MfgGroupRow, gids, ds.groups), (MfgSkillRow, sids, ds.skills),
                               (MfgToolPoolRow, pids, ds.tool_pools)):
        if ids:
            for r in s.execute(select(model).where(model.id.in_(ids))).scalars():
                target[r.id] = repo.to_record(r)
    document_errors(validate_routing_document(ds, item_id, ops), s)


def _write_ops(s: Session, routing_id: str, ops: list[OperationInput]) -> None:
    rows = write_children(s, MfgOperationRow, "routing_id", routing_id, "opr_",
                          [(o.id, {f: getattr(o, f) for f in OP_FIELDS}) for o in ops], ("seq",), lambda i: -(i + 1))
    ids = [r.id for r in rows]
    if ids:
        s.execute(delete(MfgOperationToolRow).where(MfgOperationToolRow.operation_id.in_(ids))
                  .execution_options(synchronize_session=False))
    now = utcnow()
    s.add_all([MfgOperationToolRow(id=new_id("otl_"), operation_id=r.id, tool_pool_id=t.tool_pool_id, qty=t.qty,
                                   row_version=1, created_at=now, updated_at=now)
               for r, o in zip(rows, ops) for t in o.tools])
    s.flush()


def _next_version(s: Session, item_id: str, revision: str, code: str) -> int:
    v = s.execute(select(func.max(MfgRoutingRow.version)).where(
        MfgRoutingRow.item_id == item_id, MfgRoutingRow.revision == revision, MfgRoutingRow.code == code)).scalar()
    return int(v or 0) + 1


def _limits(s: Session, new_ops: int, new_doc: bool) -> None:
    if new_doc:
        check_limit(s, MfgRoutingRow, L.MAX_ROUTINGS, "routings")
    if new_ops:
        check_limit(s, MfgOperationRow, L.MAX_OPERATIONS_TOTAL, "operations", adding=new_ops)


def create_routing(ctx: AppContext, inp: RoutingInput) -> RoutingRecord:
    with write_tx(ctx) as (s, _):
        item = item_for_document(s, inp.item_id, routing=True)
        check_serial(item, inp.serial_from)
        check_ids_kept([o.id for o in inp.operations], set(), "operations")
        revision = inp.revision or item.revision
        version = inp.version or _next_version(s, item.id, revision, inp.code)
        ensure_unique(s, MfgRoutingRow, "A routing",
                      {"item_id": item.id, "revision": revision, "code": inp.code, "version": version})
        _validate_ops(s, item.id, inp.operations)
        _limits(s, len(inp.operations), True)
        now = utcnow()
        row = MfgRoutingRow(id=new_id("rtg_"), item_id=item.id, revision=revision, code=inp.code, version=version,
                            status="draft", row_version=1, created_at=now, updated_at=now,
                            **{f: getattr(inp, f) for f in HEADER_FIELDS})
        s.add(row)
        s.flush()
        _write_ops(s, row.id, inp.operations)
        audit(s, "routing", row.id, "create", {"version": 1, "operations": len(inp.operations)})
        return routing_record(s, row)


def update_routing(ctx: AppContext, routing_id: str, inp: RoutingInput, if_match: str | None) -> RoutingRecord:
    from ...errors import ApiError

    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgRoutingRow, routing_id, what="Routing", lock=True)
        check_version(row, if_match)
        if row.status != "draft":
            raise readonly(row.status, "routing")
        if inp.item_id != row.item_id:
            raise ApiError(422, "VALIDATION_ERROR", "The item of a routing cannot be changed.",
                           {"errors": [{"loc": ["body", "item_id"], "msg": "must equal the stored item_id",
                                        "type": "immutable"}]})
        item = item_for_document(s, row.item_id, routing=True)
        check_serial(item, inp.serial_from)
        existing = set(s.execute(select(MfgOperationRow.id).where(MfgOperationRow.routing_id == row.id)).scalars())
        check_ids_kept([o.id for o in inp.operations], existing, "operations")
        revision = inp.revision or row.revision
        version = inp.version or row.version
        ensure_unique(s, MfgRoutingRow, "A routing",
                      {"item_id": item.id, "revision": revision, "code": inp.code, "version": version},
                      exclude_id=row.id)
        _validate_ops(s, item.id, inp.operations)
        _limits(s, sum(1 for o in inp.operations if o.id is None), False)
        row.revision, row.version, row.code = revision, version, inp.code
        for f in HEADER_FIELDS:
            setattr(row, f, getattr(inp, f))
        _write_ops(s, row.id, inp.operations)
        touch(row)
        s.flush()
        audit(s, "routing", row.id, "update", {"version": row.row_version, "operations": len(inp.operations)})
        return routing_record(s, row)


def delete_routing(ctx: AppContext, routing_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgRoutingRow, routing_id, what="Routing", lock=True)
        check_version(row, if_match)
        if row.status == "released":
            raise readonly(row.status, "routing")
        op_ids = select(MfgOperationRow.id).where(MfgOperationRow.routing_id == row.id)
        s.execute(delete(MfgOperationToolRow).where(MfgOperationToolRow.operation_id.in_(op_ids))
                  .execution_options(synchronize_session=False))
        s.execute(delete(MfgOperationRow).where(MfgOperationRow.routing_id == row.id)
                  .execution_options(synchronize_session=False))
        s.execute(delete(MfgRoutingRow).where(MfgRoutingRow.id == row.id).execution_options(synchronize_session=False))
        s.expunge(row)
        audit(s, "routing", routing_id, "delete", {"version": row.row_version})


def release_routing(ctx: AppContext, routing_id: str, effective_from: date | None, supersede: bool,
                    if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgRoutingRow, routing_id, what="Routing", lock=True)
        check_version(row, if_match)
        if row.status != "draft":
            raise invalid_state(row.status, "released", "routing")
        ds = repo.load_dataset(s)
        try:
            issues, superseded = routing_release_issues(ds, row.id, effective_from, supersede)
        except ReleaseError as exc:
            raise release_error(exc) from None
        if issues:
            raise release_blocked(issues, "routing")
        now = utcnow()
        if effective_from is not None:
            row.effective_from = effective_from
        row.status, row.released_at = "released", now
        touch(row, now)
        for sup in superseded:
            other = repo.get_row(s, MfgRoutingRow, sup["id"], what="Routing", lock=True)
            other.effective_to = sup["effective_to"]
            touch(other, now)
        s.flush()
        audit(s, "routing", row.id, "release", {"version": row.row_version,
                                                "superseded": [x["id"] for x in superseded]})
        return {"routing": routing_record(s, row), "superseded": superseded}


def obsolete_routing(ctx: AppContext, routing_id: str, if_match: str | None) -> RoutingRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgRoutingRow, routing_id, what="Routing", lock=True)
        check_version(row, if_match)
        if row.status != "released":
            raise invalid_state(row.status, "made obsolete", "routing")
        now = utcnow()
        row.status, row.obsoleted_at = "obsolete", now
        touch(row, now)
        s.flush()
        audit(s, "routing", row.id, "obsolete", {"version": row.row_version})
        return routing_record(s, row)


def copy_routing(ctx: AppContext, routing_id: str, revision: str | None, code: str | None, if_match: str | None
                 ) -> RoutingRecord:
    with write_tx(ctx) as (s, _):
        src = repo.get_row(s, MfgRoutingRow, routing_id, what="Routing", lock=True)
        check_version(src, if_match)
        item_for_document(s, src.item_id, routing=True)
        rev, cd = revision or src.revision, code or src.code
        ops = list(s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id == src.id)).scalars())
        _limits(s, len(ops), True)
        tools = list(s.execute(select(MfgOperationToolRow).where(
            MfgOperationToolRow.operation_id.in_([o.id for o in ops]))).scalars()) if ops else []
        now = utcnow()
        row = MfgRoutingRow(id=new_id("rtg_"), item_id=src.item_id, revision=rev, code=cd,
                            version=_next_version(s, src.item_id, rev, cd), priority=src.priority, status="draft",
                            effective_from=None, effective_to=None, serial_from=src.serial_from,
                            serial_to=src.serial_to, note=src.note, row_version=1, created_at=now, updated_at=now)
        s.add(row)
        s.flush()
        new_ids = {}
        for o in ops:
            nid = new_id("opr_")
            new_ids[o.id] = nid
            s.add(MfgOperationRow(id=nid, routing_id=row.id, row_version=1, created_at=now, updated_at=now,
                                  **{f: getattr(o, f) for f in OP_FIELDS}))
        s.flush()
        s.add_all([MfgOperationToolRow(id=new_id("otl_"), operation_id=new_ids[t.operation_id],
                                       tool_pool_id=t.tool_pool_id, qty=t.qty, row_version=1, created_at=now,
                                       updated_at=now) for t in tools])
        s.flush()
        audit(s, "routing", row.id, "copy", {"from": src.id, "version": row.version})
        return routing_record(s, row)


def time_preview(ctx: AppContext, routing_id: str, qty: float) -> Any:
    with read_tx(ctx) as s:
        row = repo.get_row(s, MfgRoutingRow, routing_id, what="Routing")
        ds = MfgDataset(plant=PlantRecord())
        ops = list(s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id == row.id)).scalars())
        ds.routings[row.id] = repo.to_record(row, operations=[repo.to_record(o) for o in ops])
        item = s.execute(select(MfgItemRow).where(MfgItemRow.id == row.item_id)).scalars().first()
        ds.items[item.id] = repo.to_record(item)
        gids = sorted({o.group_id for o in ops})
        if gids:
            for g in s.execute(select(MfgGroupRow).where(MfgGroupRow.id.in_(gids))).scalars():
                ds.groups[g.id] = repo.to_record(g)
            lines = list(s.execute(select(MfgLineRow).where(MfgLineRow.group_id.in_(gids))).scalars())
            links: dict[str, list[str]] = {}
            if lines:
                for lid, iid in s.execute(select(MfgLineItemRow.line_id, MfgLineItemRow.item_id).where(
                        MfgLineItemRow.line_id.in_([x.id for x in lines]))).all():
                    links.setdefault(lid, []).append(iid)
            for x in lines:
                ds.lines[x.id] = repo.to_record(x, eligible_item_ids=sorted(links.get(x.id, [])))
        return _time_preview(ds, row.id, qty)
