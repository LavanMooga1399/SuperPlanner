"""Shop-floor execution services (M4-DESIGN 4, 5, 10, 11 #200-207, #211-213; M3 #176-178 shortcuts).

- WO operations (`mfg_wo_operations`) are derived from the WO's routing at release (`source release`), lazily for
  older released WOs (`source lazy`, first access in its own short write transaction) and re-derived by
  `POST /work-orders/{id}/operations/refresh` while no event exists.
- `POST /floor/events` appends one event (or one per member of a batch load) and recomputes the operation from its
  event log (`mfg.floor.engine.replay`), then applies the effects in the same transaction - lock order WO header ->
  operations -> postings (4.3): scrap to `work_orders.qty_scrapped`, backflush issues (4.4), the last operation's
  good output as `wo_receipt` (4.3), unit serials (10), replan triggers (7).
- Idempotency: `client_event_id` is unique per owner; a replay returns the stored event with the current state
  (200 + `Idempotent-Replay: true`), a concurrent duplicate loses the unique race and replays.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....mfg import scan as SCAN
from ....mfg.floor import engine as E
from ....mfg.model_m2 import EPS
from ....mfg.model_m4 import FloorEventInput, SUPERVISOR_EVENTS
from ....mfg.units import is_count
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.locks import is_unique_violation
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import repo
from ..access import MfgPrincipal
from ..db_models import (MfgGroupRow, MfgItemRow, MfgLineItemRow, MfgLineRow, MfgOperationRow, MfgOperationToolRow,
                         MfgOperatorRow, MfgPlantRow, MfgRoutingRow, MfgToolPoolRow)
from ..db_models_m2 import (MfgInvReservationRow, MfgLocationRow, MfgLotRow, MfgWoComponentRow, MfgWorkOrderRow)
from ..db_models_m3 import MfgApsOpRow, MfgApsRunRow
from ..db_models_m4 import (MfgBatchLoadMemberRow, MfgBatchLoadRow, MfgDowntimeRow, MfgFloorEventRow,
                            MfgUnitSerialRow, MfgWoOperationRow)
from .common import audit, check_version, read_tx, touch
from .m2util import actor_id, page, run_tx, user_names

FLOOR_WO_STATUSES = ("released", "in_progress", "completed")
#: operator backdating limit (4.2)
OPERATOR_BACKDATE = timedelta(hours=24)
FUTURE_SLACK = timedelta(minutes=2)


def floor_error(e: E.FloorRuleError) -> ApiError:
    return ApiError(e.status, e.code, e.message, dict(e.details))


def _ref(row: Any) -> dict[str, Any] | None:
    return {"id": row.id, "code": row.code, "name": row.name} if row is not None else None


def _plant(s: Session) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow)).scalars().first()


def _local_date(s: Session, at: datetime) -> date:
    from ....mfg.tz import plant_tz

    p = _plant(s)
    return at.astimezone(plant_tz(p) if p is not None else UTC).date()


# ---------------------------------------------------------------- operation derivation (4.1)

def routing_of(s: Session, wo: MfgWorkOrderRow) -> str | None:
    """The WO's routing, else the item's primary routing at the start date (M2 3.7 / M3 17), from the item's
    routing rows only (no full dataset load; cached per session)."""
    if wo.routing_id:
        return wo.routing_id
    from types import SimpleNamespace

    from ....mfg.routing import primary_routing

    cache: dict[tuple[Any, ...], str | None] = s.info.setdefault("sp_wo_routing", {})
    key = (wo.item_id, wo.start_date, wo.serial_from)
    if key not in cache:
        rows = [SimpleNamespace(id=r.id, status=r.status, effective_from=r.effective_from,
                                effective_to=r.effective_to, serial_from=r.serial_from, serial_to=r.serial_to,
                                priority=r.priority, version=r.version, revision=r.revision, code=r.code)
                for r in s.execute(select(MfgRoutingRow).where(MfgRoutingRow.item_id == wo.item_id)).scalars()]
        rt = primary_routing(SimpleNamespace(routings_by_item={wo.item_id: rows}), wo.item_id, wo.start_date,
                             wo.serial_from)
        cache[key] = rt.id if rt is not None else None
    return cache[key]


def routing_ops(s: Session, routing_id: str | None) -> list[MfgOperationRow]:
    if not routing_id:
        return []
    return list(s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id == routing_id)
                          .order_by(MfgOperationRow.seq)).scalars())


def derive_rows(s: Session, wo: MfgWorkOrderRow, source: str, now: datetime) -> list[MfgWoOperationRow]:
    """New operation rows of a WO from its routing; `qty_planned` = the yield-inflated input (M1 4.4)."""
    import math

    ops = routing_ops(s, routing_of(s, wo))
    if not ops:
        return []
    item = s.get(MfgItemRow, wo.item_id)
    count = is_count(item.uom) if item is not None else True
    qty = float(wo.qty)
    inputs = [0.0] * len(ops)
    nxt = qty
    for k in range(len(ops) - 1, -1, -1):
        y = (ops[k].yield_pct or 100.0) / 100.0
        nxt = float(math.ceil(nxt / y - EPS)) if count else nxt / y
        inputs[k] = round(nxt, 6)
    out = []
    for o, q in zip(ops, inputs):
        out.append(MfgWoOperationRow(
            id=new_id("wop_"), wo_id=wo.id, seq=o.seq, name=o.name, group_id=o.group_id, status="pending",
            qty_planned=q, qty_good=0.0, qty_scrap=0.0, qty_rework_out=0.0, qty_rework_in=0.0, line_id=None,
            setup_minutes_actual=0.0, run_minutes_actual=0.0, labour_minutes=0.0, actual_start=None,
            actual_end=None, started_short=False, source=source, last_event_seq=None, effects={},
            completed_at=None, completed_by=None, row_version=1, created_at=now, updated_at=now))
    s.add_all(out)
    s.flush()
    return out


def wo_rows(s: Session, wo_id: str, *, lock: bool = False) -> list[MfgWoOperationRow]:
    q = select(MfgWoOperationRow).where(MfgWoOperationRow.wo_id == wo_id).order_by(MfgWoOperationRow.seq)
    if lock:     # fresh state under the lock (a concurrent event may have committed meanwhile)
        q = q.with_for_update().execution_options(populate_existing=True)
    return list(s.execute(q).scalars())


def lock_wo(s: Session, wo_id: str) -> MfgWorkOrderRow:
    """The WO header FOR UPDATE with its committed state reloaded (review M1: no stale identity-map rows)."""
    w = s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id == wo_id).with_for_update()
                  .execution_options(populate_existing=True)).scalars().first()
    if w is None:
        raise not_found("Work order", wo_id)
    return w


def ensure_rows(s: Session, wo: MfgWorkOrderRow) -> list[MfgWoOperationRow]:
    """The WO's operation rows; created lazily for a released / in-progress WO without them (caller writes)."""
    rows = wo_rows(s, wo.id)
    if rows or wo.status not in ("released", "in_progress"):
        return rows
    return derive_rows(s, wo, "lazy", utcnow())


def _needs_lazy(s: Session, wo_id: str) -> bool:
    w = s.get(MfgWorkOrderRow, wo_id)
    if w is None or w.status not in ("released", "in_progress"):
        return False
    return s.execute(select(MfgWoOperationRow.id).where(MfgWoOperationRow.wo_id == wo_id).limit(1)).first() is None


def ensure_lazy(ctx: AppContext, wo_ids: Iterable[str]) -> None:
    """GET paths: create missing operation rows of released WOs in a short write transaction first (4.1)."""
    ids = sorted(set(wo_ids))
    if not ids:
        return
    with read_tx(ctx) as s:
        missing = [w for w in ids if _needs_lazy(s, w)]
    if not missing:
        return

    def fn(s: Session) -> None:
        for wid in missing:
            w = s.get(MfgWorkOrderRow, wid, with_for_update=True)
            if w is not None and not wo_rows(s, wid):
                ensure_rows(s, w)

    try:
        run_tx(ctx, fn)
    except IntegrityError:   # a concurrent first access created them (uq_mfg_wo_operations_key)
        pass


# ---------------------------------------------------------------- records

def _chain(rows: list[MfgWoOperationRow], tb: dict[int, int | None] | None = None) -> dict[int, E.ChainView]:
    return E.chain([E.ChainOp(r.seq, r.status, r.qty_planned, r.qty_good, r.qty_scrap, r.qty_rework_out,
                              r.qty_rework_in, (tb or {}).get(r.seq)) for r in rows])


def _placements(s: Session, wo_ids: list[str]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    pub = s.execute(select(MfgApsRunRow.id).where(MfgApsRunRow.is_published.is_(True))).scalar()
    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    if pub is None or not wo_ids:
        return out
    rows = list(s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == pub, MfgApsOpRow.order_id.in_(wo_ids),
                                                    MfgApsOpRow.status == "scheduled")
                          .order_by(MfgApsOpRow.seq, MfgApsOpRow.split_index)).scalars())
    lines = {r.id: r.code for r in s.execute(select(MfgLineRow).where(
        MfgLineRow.id.in_({r.line_id for r in rows if r.line_id}))).scalars()} if rows else {}
    for r in rows:
        out.setdefault((r.order_id, r.seq), []).append({
            "run_id": pub, "op_no": r.op_no, "line": {"id": r.line_id, "code": lines.get(r.line_id, "")},
            "start": as_utc(r.start_at), "end": as_utc(r.end_at),
            "split": {"index": r.split_index, "count": r.split_count}})
    return out


def op_records(s: Session, rows: list[MfgWoOperationRow], *, placement: bool = True) -> list[dict[str, Any]]:
    """Full operation records (11 #206) for rows of one or more WOs."""
    if not rows:
        return []
    by_wo: dict[str, list[MfgWoOperationRow]] = {}
    for r in rows:
        by_wo.setdefault(r.wo_id, [])
    all_rows = list(s.execute(select(MfgWoOperationRow).where(MfgWoOperationRow.wo_id.in_(sorted(by_wo)))
                              .order_by(MfgWoOperationRow.wo_id, MfgWoOperationRow.seq)).scalars())
    for r in all_rows:
        by_wo[r.wo_id].append(r)
    wos = {w.id: w for w in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id.in_(sorted(by_wo))))
           .scalars()}
    rops: dict[tuple[str, int], MfgOperationRow] = {}
    rids = {w.id: w.routing_id for w in wos.values()}
    need = sorted({rid for rid in rids.values() if rid})
    if need:
        for o in s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id.in_(need))).scalars():
            rops[(o.routing_id, o.seq)] = o
    groups = {g.id: g for g in s.execute(select(MfgGroupRow).where(
        MfgGroupRow.id.in_({r.group_id for r in all_rows}))).scalars()}
    lines = {ln.id: ln for ln in s.execute(select(MfgLineRow).where(
        MfgLineRow.id.in_({r.line_id for r in all_rows if r.line_id}))).scalars()}
    names = user_names(s, [r.completed_by for r in all_rows if r.completed_by])
    place = _placements(s, sorted(by_wo)) if placement else {}
    chains: dict[str, dict[int, E.ChainView]] = {}
    for wid, rs in by_wo.items():
        tb = {r.seq: (rops.get((rids.get(wid) or "", r.seq)).transfer_batch
                      if rops.get((rids.get(wid) or "", r.seq)) is not None else None) for r in rs}
        chains[wid] = _chain(rs, tb)
    want = {r.id for r in rows}
    out = []
    for r in all_rows:
        if r.id not in want:
            continue
        v = chains[r.wo_id][r.seq]
        ro = rops.get((rids.get(r.wo_id) or "", r.seq))
        g = groups.get(r.group_id)
        status = "ready" if r.status == "pending" and v.ready else r.status
        done = r.status in ("completed", "skipped")
        out.append({
            "id": r.id, "wo_id": r.wo_id, "seq": r.seq, "name": r.name,
            "group": {"id": r.group_id, "code": g.code if g else "", "name": g.name if g else ""},
            "status": status, "qty_planned": r.qty_planned, "qty_good": r.qty_good, "qty_scrap": r.qty_scrap,
            "qty_rework_out": r.qty_rework_out, "qty_rework_in": r.qty_rework_in, "qty_input": v.qty_input,
            "qty_available": v.qty_available, "line": _ref(lines.get(r.line_id)) if r.line_id else None,
            "setup_minutes_actual": round(r.setup_minutes_actual, 3),
            "run_minutes_actual": round(r.run_minutes_actual, 3),
            "labour_minutes": round(r.labour_minutes, 3), "actual_start": as_utc(r.actual_start),
            "actual_end": as_utc(r.actual_end), "started_short": r.started_short, "source": r.source,
            "capture_serial": bool(ro.capture_serial) if ro is not None else False,
            "last_event_seq": r.last_event_seq,
            "setup_minutes": float(ro.setup_minutes) if ro is not None else 0.0,
            "run_minutes": float(ro.run_minutes) if ro is not None else 0.0,
            "labor": ro.labor if ro is not None else "attended",
            "done": done, "done_at": as_utc(r.completed_at or r.actual_end) if done else None,
            "done_by": ({"id": r.completed_by, "code": "", "name": names.get(r.completed_by, "")}
                        if done and r.completed_by else None),
            "placement": place.get((r.wo_id, r.seq), []),
            "row_version": r.row_version, "created_at": as_utc(r.created_at), "updated_at": as_utc(r.updated_at)})
    order = {r.id: i for i, r in enumerate(rows)}
    out.sort(key=lambda x: order[x["id"]])
    return out


def wo_summary(s: Session, w: MfgWorkOrderRow) -> dict[str, Any]:
    it = s.get(MfgItemRow, w.item_id)
    return {"id": w.id, "number": w.number, "status": w.status, "qty": w.qty, "qty_completed": w.qty_completed,
            "qty_scrapped": w.qty_scrapped, "row_version": w.row_version,
            "item": {"id": w.item_id, "part_number": it.part_number if it else "",
                     "description": it.description if it else ""},
            "due_date": w.due_date, "priority": w.priority, "released_to_floor_at": as_utc(w.released_to_floor_at),
            "receipt_location_id": w.receipt_location_id}


def wo_operations_in(s: Session, wo: MfgWorkOrderRow) -> dict[str, Any]:
    rows = wo_rows(s, wo.id)
    return {"wo": {"id": wo.id, "number": wo.number, "row_version": wo.row_version, "status": wo.status,
                   "released_to_floor_at": as_utc(wo.released_to_floor_at)},
            "items": op_records(s, rows) if rows else _virtual_ops(s, wo)}


def _virtual_ops(s: Session, wo: MfgWorkOrderRow) -> list[dict[str, Any]]:
    """Operations of a WO that has no rows (planned, or final without floor history): from the routing, pending."""
    ops = routing_ops(s, routing_of(s, wo))
    groups = {g.id: g for g in s.execute(select(MfgGroupRow).where(
        MfgGroupRow.id.in_({o.group_id for o in ops}))).scalars()} if ops else {}
    place = _placements(s, [wo.id])
    out = []
    for o in ops:
        g = groups.get(o.group_id)
        out.append({"id": "", "wo_id": wo.id, "seq": o.seq, "name": o.name,
                    "group": {"id": o.group_id, "code": g.code if g else "", "name": g.name if g else ""},
                    "status": "pending", "qty_planned": wo.qty, "qty_good": 0.0, "qty_scrap": 0.0,
                    "qty_rework_out": 0.0, "qty_rework_in": 0.0, "qty_input": 0.0, "qty_available": 0.0,
                    "line": None, "setup_minutes_actual": 0.0, "run_minutes_actual": 0.0, "labour_minutes": 0.0,
                    "actual_start": None, "actual_end": None, "started_short": False, "source": "release",
                    "capture_serial": bool(o.capture_serial), "last_event_seq": None,
                    "setup_minutes": float(o.setup_minutes), "run_minutes": float(o.run_minutes), "labor": o.labor,
                    "done": False, "done_at": None, "done_by": None, "placement": place.get((wo.id, o.seq), []),
                    "row_version": 0, "created_at": None, "updated_at": None})
    return out


def wo_operations(ctx: AppContext, wo_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        repo.get_row(s, MfgWorkOrderRow, wo_id, what="Work order")
    ensure_lazy(ctx, [wo_id])
    with read_tx(ctx) as s:
        return wo_operations_in(s, repo.get_row(s, MfgWorkOrderRow, wo_id, what="Work order"))


def refresh_operations(ctx: AppContext, wo_id: str, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        wo = repo.get_row(s, MfgWorkOrderRow, wo_id, what="Work order", lock=True)
        check_version(wo, if_match)
        if wo.status not in ("planned", "released", "in_progress"):
            raise ApiError(409, "MFG_INVALID_STATE", f"{wo.number} is {wo.status}; its operations cannot be "
                           "refreshed.", {"status": wo.status, "action": "refresh-operations",
                                          "allowed_from": ["planned", "released", "in_progress"]})
        rows = wo_rows(s, wo.id, lock=True)
        if rows and s.execute(select(MfgFloorEventRow.id).where(MfgFloorEventRow.wo_id == wo.id).limit(1)).first():
            raise ApiError(409, "WO_HAS_FLOOR_EVENTS", f"{wo.number} has floor events; its operations can no longer "
                           "be re-derived (correct them instead).", {"wo_id": wo.id})
        if rows and s.execute(select(MfgBatchLoadMemberRow.id).where(MfgBatchLoadMemberRow.wo_operation_id.in_(
                [r.id for r in rows])).limit(1)).first():
            raise ApiError(409, "MFG_IN_USE", f"{wo.number} has operations in batch loads.", {"references": {}})
        for r in rows:
            s.delete(r)
        s.flush()
        now = utcnow()
        if wo.status != "planned":
            derive_rows(s, wo, "release", now)
        touch(wo, now)
        s.flush()
        audit(s, "work_order", wo.id, "operations_refresh", {"number": wo.number, "version": wo.row_version})
        return wo_operations_in(s, wo)

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- release to the floor (4.1)

def first_op_shortages(s: Session, wo: MfgWorkOrderRow, kit: dict[str, Any]) -> list[dict[str, Any]]:
    ops = routing_ops(s, routing_of(s, wo))
    first = ops[0].seq if ops else None
    comps = {c.id: c for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == wo.id)).scalars()}
    its = {i.id: i for i in s.execute(select(MfgItemRow).where(
        MfgItemRow.id.in_({c.item_id for c in comps.values()}))).scalars()} if comps else {}
    out = []
    for row in kit.get("rows", []):
        c = comps.get(row["component_id"])
        if c is None or row["shortage"] <= EPS:
            continue
        seq = c.operation_seq if c.operation_seq is not None else first
        if first is not None and seq != first:
            continue
        it = its.get(c.item_id)
        out.append({"component_id": c.id, "item_id": c.item_id, "part_number": it.part_number if it else "",
                    "required": row["open"], "available": round(row["free"] + row["reserved"], 6),
                    "short": row["shortage"], "operation_seq": seq})
    return out


def release_to_floor(s: Session, wo: MfgWorkOrderRow, override_reason: str | None, now: datetime) -> None:
    """Called by the M2 release action after the status change: kitting check of the first operation (409
    `WO_KIT_INCOMPLETE` unless `override_reason`), operation rows, `released_to_floor_at`."""
    from .workorders import kitting_in

    short = first_op_shortages(s, wo, kitting_in(s, wo))
    if short and not (override_reason or "").strip():
        raise ApiError(409, "WO_KIT_INCOMPLETE",
                       f"{wo.number} is short of {len(short)} component(s) for its first operation; give an "
                       "override_reason to release anyway.", {"shortages": short})
    if not wo_rows(s, wo.id):
        derive_rows(s, wo, "release", now)
    wo.released_to_floor_at = now
    wo.release_override = (override_reason or "").strip()[:200] or None if short else None


# ---------------------------------------------------------------- events: load / replay

def _ev(r: MfgFloorEventRow) -> E.Ev:
    d = r.details or {}
    return E.Ev(r.id, int(r.seq), r.event_type, as_utc(r.event_at), r.line_id, len(r.operator_ids or []),
                r.qty_good, r.qty_scrap, r.qty_rework, r.rework_to_seq, r.corrects_event_id,
                bool(d.get("migrated")), tuple(d.get("fields") or ()))


def wo_events(s: Session, wo_id: str) -> list[MfgFloorEventRow]:
    return list(s.execute(select(MfgFloorEventRow).where(MfgFloorEventRow.wo_id == wo_id)
                          .order_by(MfgFloorEventRow.seq)).scalars())


def replay_wo(rows: list[MfgWoOperationRow], events: list[MfgFloorEventRow]) -> dict[str, E.OpState]:
    """Every operation of one WO from the WO's events (rework of a later op feeds `rework_in` of the target)."""
    by_op: dict[str, list[E.Ev]] = {r.id: [] for r in rows}
    for e in events:
        by_op.setdefault(e.wo_operation_id, []).append(_ev(e))
    seq_of = {r.id: r.seq for r in rows}
    op_of_seq = {r.seq: r.id for r in rows}
    out: dict[str, E.OpState] = {}
    resolved = {oid: E.corrected(evs) for oid, evs in by_op.items()}
    incoming: dict[str, list[E.Ev]] = {r.id: [] for r in rows}
    for oid, evs in resolved.items():
        for e in evs:
            if e.event_type in E.QTY_EVENTS and (e.qty_rework or 0) > EPS and e.rework_to_seq is not None:
                tgt = op_of_seq.get(e.rework_to_seq)
                if tgt is not None and tgt in incoming and (seq_of.get(oid) or 0) >= e.rework_to_seq:
                    incoming[tgt].append(E.Ev(f"rw:{e.id}", e.seq, "rework_in", e.event_at,
                                              qty_rework=e.qty_rework))
    for r in rows:
        st = E.OpState()
        evs = sorted(resolved.get(r.id, []) + incoming[r.id],
                     key=lambda e: (e.seq, 0 if e.event_type != "rework_in" else 1))
        for e in evs:
            st = E.apply(st, e)
        out[r.id] = st
    return out


def _store_state(row: MfgWoOperationRow, st: E.OpState, now: datetime) -> bool:
    vals = {"status": st.status, "qty_good": round(st.qty_good, 6), "qty_scrap": round(st.qty_scrap, 6),
            "qty_rework_out": round(st.qty_rework_out, 6), "qty_rework_in": round(st.qty_rework_in, 6),
            "line_id": st.line_id or row.line_id, "setup_minutes_actual": round(st.setup_minutes, 6),
            "run_minutes_actual": round(st.run_minutes, 6), "labour_minutes": round(st.labour_minutes, 6),
            "actual_start": st.actual_start, "actual_end": st.actual_end, "last_event_seq": st.last_seq}
    changed = False
    for k, v in vals.items():
        cur = getattr(row, k)
        if isinstance(cur, datetime) and isinstance(v, datetime):
            same = as_utc(cur) == as_utc(v)
        else:
            same = cur == v
        if not same:
            setattr(row, k, v)
            changed = True
    if changed:
        touch(row, now)
    return changed


# ---------------------------------------------------------------- events: post (203)

def _event_record(s: Session, e: MfgFloorEventRow, wo: MfgWorkOrderRow | None = None,
                  op: MfgWoOperationRow | None = None, *, corrected_ids: set[str] | None = None) -> dict[str, Any]:
    return _event_records(s, [e], corrected_ids=corrected_ids)[0]


def _event_records(s: Session, evs: list[MfgFloorEventRow], *, corrected_ids: set[str] | None = None
                   ) -> list[dict[str, Any]]:
    if not evs:
        return []
    wos = {w.id: w.number for w in s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.number).where(
        MfgWorkOrderRow.id.in_({e.wo_id for e in evs}))).all()}
    seqs = {o.id: o.seq for o in s.execute(select(MfgWoOperationRow.id, MfgWoOperationRow.seq).where(
        MfgWoOperationRow.id.in_({e.wo_operation_id for e in evs}))).all()}
    lines = {ln.id: ln for ln in s.execute(select(MfgLineRow).where(
        MfgLineRow.id.in_({e.line_id for e in evs if e.line_id}))).scalars()}
    opids = {o for e in evs for o in (e.operator_ids or [])}
    ops = {o.id: o for o in s.execute(select(MfgOperatorRow).where(MfgOperatorRow.id.in_(opids))).scalars()} \
        if opids else {}
    names = user_names(s, [e.actor_id for e in evs])
    if corrected_ids is None:
        ids = [e.id for e in evs]
        corrected_ids = set(s.execute(select(MfgFloorEventRow.corrects_event_id).where(
            MfgFloorEventRow.corrects_event_id.in_(ids))).scalars())
    out = []
    for e in evs:
        out.append({
            "id": e.id, "seq": int(e.seq), "wo_operation_id": e.wo_operation_id, "wo_id": e.wo_id,
            "wo_number": wos.get(e.wo_id, ""), "op_seq": seqs.get(e.wo_operation_id, 0), "event_type": e.event_type,
            "event_at": as_utc(e.event_at), "recorded_at": as_utc(e.recorded_at),
            "line": _ref(lines.get(e.line_id)) if e.line_id else None,
            "operators": [_ref(ops[o]) or {"id": o, "code": "", "name": ""} if o in ops
                          else {"id": o, "code": "", "name": ""} for o in (e.operator_ids or [])],
            "qty_good": e.qty_good, "qty_scrap": e.qty_scrap, "qty_rework": e.qty_rework,
            "rework_to_seq": e.rework_to_seq, "reason_code": e.reason_code, "note": e.note,
            "client_event_id": e.client_event_id, "batch_load_id": e.batch_load_id, "serials": e.serials,
            "corrects_event_id": e.corrects_event_id, "corrected": e.id in corrected_ids, "forced": e.forced,
            "actor": {"id": e.actor_id, "code": "", "name": names.get(e.actor_id, "")},
            "details": {k: v for k, v in (e.details or {}).items() if k != "fields"}})
    return out


class _Ctx:
    """Per-request state of one event post."""

    def __init__(self, s: Session, p: MfgPrincipal | None, now: datetime):
        self.s, self.p, self.now = s, p, now
        self.supervisor = p is None or p.has("floor_supervise")
        self.postings: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.triggers: list[dict[str, Any]] = []
        self.changed: dict[str, MfgWoOperationRow] = {}


def _forbidden(what: str) -> ApiError:
    return ApiError(403, "MFG_FORBIDDEN", f"{what} needs a supervisor (permission floor_supervise).",
                    {"permission": "floor_supervise"})


def _resolve_target(s: Session, inp: FloorEventInput) -> tuple[str | None, str | None]:
    """-> (wo_operation_id, batch_load_id)."""
    if inp.wo_operation_id is not None:
        return inp.wo_operation_id, inp.batch_load_id
    if inp.scan is not None:
        for lk in SCAN.parse(inp.scan):
            if lk.type == "operation":
                number, seq = lk.key
                w = s.execute(select(MfgWorkOrderRow).where(func.upper(MfgWorkOrderRow.number) == number.upper())
                              ).scalars().first()
                if w is None:
                    break
                ensure_rows(s, w)
                oid = s.execute(select(MfgWoOperationRow.id).where(MfgWoOperationRow.wo_id == w.id,
                                                                   MfgWoOperationRow.seq == int(seq))).scalar()
                if oid is not None:
                    return oid, inp.batch_load_id
                break
            if lk.type == "batch_load":
                lid = _load_by_code(s, lk.key[0])
                if lid is not None:
                    return None, lid
                break
        raise ApiError(404, "FLR_SCAN_UNKNOWN", f"Nothing on the floor matches {inp.scan!r}.", {"code": inp.scan})
    if inp.batch_load_id is not None:
        return None, inp.batch_load_id
    if inp.corrects_event_id is not None:
        e = s.get(MfgFloorEventRow, inp.corrects_event_id)
        if e is None:
            raise not_found("Floor event", inp.corrects_event_id)
        return e.wo_operation_id, None
    raise not_found("Operation", "")   # pragma: no cover - the input validator requires a target


def _operators(s: Session, inp: FloorEventInput) -> list[str]:
    ids: list[str] = []
    if inp.operator_ids:
        found = set(s.execute(select(MfgOperatorRow.id).where(MfgOperatorRow.id.in_(inp.operator_ids))).scalars())
        for i, o in enumerate(inp.operator_ids):
            if o not in found:
                raise ApiError(422, "FLR_OPERATOR_UNKNOWN", f"Operator {o!r} was not found.",
                               {"loc": ["body", "operator_ids", i], "id": o})
            if o not in ids:
                ids.append(o)
    for i, raw in enumerate(inp.operator_codes):
        code = raw[3:].strip() if raw.upper().startswith("OP:") else raw
        o = s.execute(select(MfgOperatorRow).where(func.upper(MfgOperatorRow.code) == code.upper())).scalars().first()
        if o is None or not o.active:
            raise ApiError(422, "FLR_OPERATOR_UNKNOWN", f"No active operator has the badge {raw!r}.",
                           {"loc": ["body", "operator_codes", i], "code": raw})
        if o.id not in ids:
            ids.append(o.id)
    if not ids:   # personal login (Q1): the operator linked to the signed-in user
        me = actor_id()
        o = s.execute(select(MfgOperatorRow.id).where(MfgOperatorRow.user_id == me,
                                                      MfgOperatorRow.active.is_(True))).scalar()
        if o is not None:
            ids.append(o)
    return ids


def _line_ok(s: Session, line: MfgLineRow, group_id: str, item: MfgItemRow | None) -> bool:
    if line.group_id != group_id or not line.active:
        return False
    fams = list(line.eligible_families or [])
    links = set(s.execute(select(MfgLineItemRow.item_id).where(MfgLineItemRow.line_id == line.id)).scalars())
    if not fams and not links:
        return True
    return item is not None and ((item.family is not None and item.family in fams) or item.id in links)


def eligible_lines(s: Session, group_id: str, item: MfgItemRow | None) -> list[MfgLineRow]:
    rows = list(s.execute(select(MfgLineRow).where(MfgLineRow.group_id == group_id, MfgLineRow.active.is_(True))
                          .order_by(MfgLineRow.code)).scalars())
    return [ln for ln in rows if _line_ok(s, ln, group_id, item)]


def open_downtime(s: Session, line_id: str, at: datetime) -> MfgDowntimeRow | None:
    return s.execute(select(MfgDowntimeRow).where(
        MfgDowntimeRow.line_id == line_id, MfgDowntimeRow.start_at <= at,
        or_(MfgDowntimeRow.end_at.is_(None), MfgDowntimeRow.end_at > at)).order_by(MfgDowntimeRow.start_at.desc())
        .limit(1)).scalars().first()


def _check_time(c: _Ctx, at: datetime, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow]) -> None:
    """4.2: never in the future; operators backdate at most 24 h; nothing before the WO's actual start."""
    if at > c.now + FUTURE_SLACK:
        raise ApiError(422, "FLR_TIME_INVALID", "An event cannot be in the future.",
                       {"loc": ["body", "event_at"], "event_at": at.isoformat()})
    if not c.supervisor and at < c.now - OPERATOR_BACKDATE:
        raise ApiError(422, "FLR_TIME_INVALID", "Operators can backdate events by at most 24 hours; ask a supervisor.",
                       {"loc": ["body", "event_at"], "event_at": at.isoformat()})
    starts = [as_utc(r.actual_start) for r in rows if r.actual_start is not None]
    if starts and at < min(starts) - timedelta(minutes=1):
        raise ApiError(422, "FLR_TIME_INVALID", f"{wo.number} started at {min(starts).isoformat()}; an event cannot "
                       "be earlier.", {"loc": ["body", "event_at"], "event_at": at.isoformat()})


def post_event(ctx: AppContext, inp: FloorEventInput, p: MfgPrincipal | None) -> tuple[dict[str, Any], bool]:
    """POST /floor/events -> (result, replayed)."""
    with read_tx(ctx) as s:
        found = _by_client_id(s, inp.client_event_id)
        if found is not None:
            return _replay(s, found), True

    def fn(s: Session) -> tuple[dict[str, Any], bool]:
        try:
            with s.begin_nested():
                return apply_event(s, inp, p), False
        except IntegrityError as exc:
            if is_unique_violation(exc, "uq_mfg_floor_events_client"):
                found = _by_client_id(s, inp.client_event_id)
                if found is not None:
                    return _replay(s, found), True
            raise

    out, replayed = run_tx(ctx, fn)
    if out.get("triggers") and not replayed:
        from . import replan

        replan.apply_policy(ctx)
    return out, replayed


def _by_client_id(s: Session, cid: str) -> MfgFloorEventRow | None:
    return s.execute(select(MfgFloorEventRow).where(MfgFloorEventRow.client_event_id == cid)
                     .order_by(MfgFloorEventRow.seq).limit(1)).scalars().first()


def _replay(s: Session, e: MfgFloorEventRow) -> dict[str, Any]:
    op = s.get(MfgWoOperationRow, e.wo_operation_id)
    wo = s.get(MfgWorkOrderRow, e.wo_id)
    d = e.details or {}
    return {"event": _event_record(s, e), "operation": op_records(s, [op])[0] if op else None,
            "operations": [], "wo": wo_summary(s, wo) if wo else {}, "postings": d.get("postings", []),
            "warnings": d.get("warnings", []), "triggers": []}


def apply_event(s: Session, inp: FloorEventInput, p: MfgPrincipal | None, *, now: datetime | None = None
                ) -> dict[str, Any]:
    """The whole of one floor event in the caller's transaction (also used by samples and the M3 shortcuts)."""
    c = _Ctx(s, p, now or utcnow())
    if (inp.event_type in SUPERVISOR_EVENTS or inp.force is not None) and not c.supervisor:
        raise _forbidden("Reopen, correct, skip and forced quantities")
    op_id, load_id = _resolve_target(s, inp)
    if load_id is not None and op_id is None:
        return _apply_load_event(c, inp, load_id)
    wo_id = s.execute(select(MfgWoOperationRow.wo_id).where(MfgWoOperationRow.id == op_id)).scalar() \
        if op_id else None
    if wo_id is None:
        raise not_found("Operation", op_id or "")
    if load_id is not None:                   # an operation event naming a load must be one of its members
        member = s.execute(select(MfgBatchLoadMemberRow.id).where(MfgBatchLoadMemberRow.load_id == load_id,
                                                                  MfgBatchLoadMemberRow.wo_operation_id == op_id)
                           ).first()
        if member is None:
            raise ApiError(422, "VALIDATION_ERROR", "batch_load_id must be a load this operation belongs to.",
                           {"errors": [{"loc": ["body", "batch_load_id"], "msg": "not a member",
                                        "type": "value_error"}]})
    return _apply_op_event(c, inp, wo_id, op_id, None)


def _apply_op_event(c: _Ctx, inp: FloorEventInput, wo_id: str, op_id: str, load: MfgBatchLoadRow | None,
                    member_qty: float | None = None, first: bool = True) -> dict[str, Any]:
    s = c.s
    wo = lock_wo(s, wo_id)                                                            # 1. WO header
    if wo.status not in FLOOR_WO_STATUSES:
        raise ApiError(409, "MFG_INVALID_STATE", f"{wo.number} is {wo.status}; release it to the floor first.",
                       {"status": wo.status, "action": "floor_event", "allowed_from": list(FLOOR_WO_STATUSES)})
    rows = wo_rows(s, wo.id, lock=True)                                               # 2. operations
    op = next((r for r in rows if r.id == op_id), None)
    if op is None:
        raise not_found("Operation", op_id)
    item = s.get(MfgItemRow, wo.item_id)
    at = as_utc(inp.event_at) if inp.event_at is not None else c.now
    if inp.event_type != "correct" or "event_at" in inp.model_fields_set:
        _check_time(c, at, wo, rows)
    operators = _operators(s, inp)
    events = wo_events(s, wo.id)
    before = replay_wo(rows, events)
    st = before[op.id]
    is_correct = inp.event_type == "correct"
    target = None
    if is_correct:
        target = s.get(MfgFloorEventRow, inp.corrects_event_id) if inp.corrects_event_id else None
        if target is None or target.wo_operation_id != op.id:
            raise ApiError(422, "VALIDATION_ERROR", "corrects_event_id must be an event of this operation.",
                           {"errors": [{"loc": ["body", "corrects_event_id"], "msg": "unknown event",
                                        "type": "value_error"}]})
    else:
        try:
            E.check_transition(_view_status(rows, op, st), inp.event_type)
        except E.FloorRuleError as e:
            raise floor_error(e) from None
    if inp.event_type == "pause" and not inp.reason_code:
        raise ApiError(422, "FLR_REASON_REQUIRED", "A pause needs a reason code.", {"loc": ["body", "reason_code"]})
    if inp.event_type == "skip" and not (inp.reason_code or inp.note.strip() or inp.force):
        raise ApiError(422, "FLR_REASON_REQUIRED", "Skipping an operation needs a reason.",
                       {"loc": ["body", "reason_code"]})
    # line (setup_start / start / resume; reports may name the line too)
    line_id = inp.line_id
    if inp.event_type in ("setup_start", "start") and line_id is None:
        line_id = st.line_id or op.line_id
        if line_id is None:
            el = eligible_lines(s, op.group_id, item)
            if len(el) == 1:
                line_id = el[0].id
            else:
                raise ApiError(422, "FLR_LINE_NOT_ELIGIBLE", "Choose the line this operation runs on.",
                               {"loc": ["body", "line_id"], "eligible": [_ref(x) for x in el]})
    if line_id is not None and inp.event_type != "correct":
        ln = s.get(MfgLineRow, line_id)
        if ln is None or not _line_ok(s, ln, op.group_id, item):
            raise ApiError(422, "FLR_LINE_NOT_ELIGIBLE", "That line cannot run this operation.",
                           {"loc": ["body", "line_id"], "line_id": line_id,
                            "eligible": [_ref(x) for x in eligible_lines(s, op.group_id, item)]})
        if inp.event_type in ("setup_start", "start", "resume"):
            dt = open_downtime(s, line_id, at)
            if dt is not None:
                if not c.supervisor:
                    raise ApiError(409, "FLR_LINE_DOWN", f"{ln.code} is down ({dt.kind}); a supervisor can override.",
                                   {"downtime_id": dt.id, "line_id": ln.id})
                c.warnings.append({"code": "FLR_LINE_DOWN", "message": f"{ln.code} is down ({dt.kind}).",
                                   "details": {"downtime_id": dt.id}})
    # quantities
    qg = float(inp.qty_good or 0.0) if member_qty is None else member_qty
    qs = float(inp.qty_scrap or 0.0) if member_qty is None else 0.0
    qr = float(inp.qty_rework or 0.0) if member_qty is None else 0.0
    if inp.event_type in E.QTY_EVENTS or is_correct:
        if item is not None and is_count(item.uom):
            for f, v in (("qty_good", qg), ("qty_scrap", qs), ("qty_rework", qr)):
                if abs(v - round(v)) > EPS:
                    raise ApiError(422, "INV_FRACTIONAL_QTY", f"{item.part_number} is counted in {item.uom}; use a "
                                   "whole number.", {"loc": ["body", f]})
        if qr > EPS:
            if inp.rework_to_seq is None or inp.rework_to_seq > op.seq or \
                    not any(r.seq == inp.rework_to_seq for r in rows):
                raise ApiError(422, "VALIDATION_ERROR", "rework_to_seq must be this or an earlier operation of the "
                               "WO.", {"errors": [{"loc": ["body", "rework_to_seq"], "msg": "invalid operation",
                                                   "type": "value_error"}]})
    fields: list[str] = []
    if is_correct:
        fields = [f for f in ("qty_good", "qty_scrap", "qty_rework", "rework_to_seq", "line_id")
                  if f in inp.model_fields_set and getattr(inp, f) is not None]
        if "event_at" in inp.model_fields_set and inp.event_at is not None:
            fields.append("event_at")
        if not fields:
            raise ApiError(422, "VALIDATION_ERROR", "A correction must change a quantity, the line or the time.",
                           {"errors": [{"loc": ["body"], "msg": "nothing to correct", "type": "value_error"}]})
    # the event row
    details: dict[str, Any] = {}
    if fields:
        details["fields"] = fields
    if load is not None:
        details["load_member_qty"] = member_qty
    row = MfgFloorEventRow(
        id=new_id("fev_"), wo_operation_id=op.id, wo_id=wo.id, event_type=inp.event_type,
        event_at=at if (not is_correct or "event_at" in fields) else c.now, recorded_at=c.now, line_id=line_id,
        operator_ids=operators,
        qty_good=(qg if inp.event_type in E.QTY_EVENTS or (is_correct and "qty_good" in fields) else None),
        qty_scrap=(qs if inp.event_type in E.QTY_EVENTS or (is_correct and "qty_scrap" in fields) else None),
        qty_rework=(qr if (inp.event_type in E.QTY_EVENTS and qr > 0) or (is_correct and "qty_rework" in fields)
                    else None),
        rework_to_seq=inp.rework_to_seq, reason_code=inp.reason_code, note=inp.note,
        client_event_id=inp.client_event_id if first else None,   # a load action: on its first member only
        batch_load_id=load.id if load is not None else inp.batch_load_id,
        serials=inp.serials.model_dump() if inp.serials is not None else None,
        corrects_event_id=inp.corrects_event_id if is_correct else None,
        forced=inp.force.reason if inp.force is not None else None, details=details, actor_id=actor_id())
    s.add(row)
    s.flush()
    events.append(row)
    try:
        after = replay_wo(rows, events)
    except E.FloorRuleError as e:
        raise floor_error(e) from None
    # quantity check against the chain after the event (4.2): consumed <= input (+ rework in)
    if inp.event_type in E.QTY_EVENTS or is_correct:
        v = _chain_after(rows, after)[op.seq]
        a = after[op.id]
        if a.qty_good + a.qty_scrap + a.qty_rework_out > v.qty_input + EPS and inp.force is None:
            avail = round(max(0.0, ch_before_avail(rows, before, op)), 6)
            raise ApiError(422, "FLR_QTY_EXCEEDS_INPUT",
                           f"Good {qg:g} + scrap {qs:g}" + (f" + rework {qr:g}" if qr else "")
                           + f" exceeds the available input {avail:g}; a supervisor can force it with a reason.",
                           {"available": avail, "good": qg, "scrap": qs, "rework": qr})
    # warnings: predecessor open (F2), started short
    if inp.event_type in ("setup_start", "start") and st.status in ("pending",):
        prev = [r for r in rows if r.seq < op.seq and after[r.id].status not in ("completed", "skipped")]
        if prev:
            c.warnings.append({"code": "FLR_PREDECESSOR_OPEN",
                               "message": f"Operation {prev[-1].seq} is not completed yet.",
                               "details": {"seq": prev[-1].seq}})
        short = _op_short(s, wo, rows, op)
        if short:
            op.started_short = True
            c.warnings.append({"code": "FLR_STARTED_SHORT", "message": f"{len(short)} component(s) are short.",
                               "details": {"components": short}})
    for r in rows:
        if _store_state(r, after[r.id], c.now):
            c.changed[r.id] = r
        if r.status == "completed" and before[r.id].status != "completed":
            r.completed_at, r.completed_by = after[r.id].actual_end or c.now, row.actor_id
        elif r.status != "completed" and r.completed_at is not None and before[r.id].status == "completed":
            r.completed_at, r.completed_by = None, None
    # effects (same transaction; postings after operations)
    from . import floor_effects

    floor_effects.apply_effects(c, wo, rows, before, after, op, row, inp, item, at)
    if wo.status == "released":
        wo.status = "in_progress"
        touch(wo, c.now)
    s.flush()
    if inp.event_type in SUPERVISOR_EVENTS or inp.force is not None:
        audit(s, "floor_event", row.id, inp.event_type,
              {"wo": wo.number, "seq": op.seq, "operators": operators, "forced": row.forced,
               "corrects": row.corrects_event_id})
    from . import replan

    c.triggers.extend(replan.on_floor_event(s, wo, rows, op, row, after, c.now))
    row.details = {**(row.details or {}), "postings": c.postings, "warnings": c.warnings}
    s.flush()
    vb, va = _chain_after(rows, before), _chain_after(rows, after)
    others = [r for r in rows if r.id != op.id and (
        r.id in c.changed or (vb[r.seq].qty_input, vb[r.seq].ready) != (va[r.seq].qty_input, va[r.seq].ready))]
    recs = op_records(s, [op] + others, placement=False)
    return {"event": _event_record(s, row), "operation": recs[0], "operations": recs[1:],
            "wo": wo_summary(s, wo), "postings": c.postings, "warnings": c.warnings, "triggers": c.triggers}


def _view_status(rows: list[MfgWoOperationRow], op: MfgWoOperationRow, st: E.OpState) -> str:
    return st.status


def _chain_after(rows: list[MfgWoOperationRow], states: dict[str, E.OpState]) -> dict[int, E.ChainView]:
    return E.chain([E.ChainOp(r.seq, states[r.id].status, r.qty_planned, states[r.id].qty_good,
                              states[r.id].qty_scrap, states[r.id].qty_rework_out, states[r.id].qty_rework_in)
                    for r in rows])


def ch_before_avail(rows: list[MfgWoOperationRow], before: dict[str, E.OpState], op: MfgWoOperationRow) -> float:
    return _chain_after(rows, before)[op.seq].qty_available


def _op_components(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow
                   ) -> list[MfgWoComponentRow]:
    first = rows[0].seq if rows else op.seq
    comps = list(s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == wo.id)
                           .order_by(MfgWoComponentRow.find_number, MfgWoComponentRow.id)).scalars())
    seqs = {r.seq for r in rows}
    out = []
    for cpt in comps:
        seq = cpt.operation_seq if cpt.operation_seq in seqs else first
        if seq == op.seq:
            out.append(cpt)
    return out


def _op_short(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow
              ) -> list[dict[str, Any]]:
    comps = _op_components(s, wo, rows, op)
    if not comps:
        return []
    res = dict(s.execute(select(MfgInvReservationRow.wo_component_id, func.sum(MfgInvReservationRow.qty))
                         .where(MfgInvReservationRow.wo_component_id.in_([x.id for x in comps]))
                         .group_by(MfgInvReservationRow.wo_component_id)).all())
    its = {i.id: i for i in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_({x.item_id for x in comps})))
           .scalars()}
    out = []
    for x in comps:
        it = its.get(x.item_id)
        if it is not None and it.issue_method == "backflush":
            continue
        need = max(0.0, x.required_qty - x.issued_qty)
        if need > EPS and float(res.get(x.id) or 0.0) + EPS < need and x.issued_qty + EPS < x.required_qty:
            out.append({"component_id": x.id, "item_id": x.item_id,
                        "part_number": it.part_number if it else "", "short": round(need - float(res.get(x.id) or 0),
                                                                                    6)})
    return out


# ---------------------------------------------------------------- batch-load events (6.3)

def _load_by_code(s: Session, code: str) -> str | None:
    c = code.strip().lower()
    if c.startswith("bld_"):
        return s.execute(select(MfgBatchLoadRow.id).where(MfgBatchLoadRow.id == c)).scalar()
    if not c or len(c) > 32 or any(ch not in "0123456789abcdef" for ch in c):
        return None
    return s.execute(select(MfgBatchLoadRow.id).where(MfgBatchLoadRow.id.like(f"bld_%{c}"))
                     .order_by(MfgBatchLoadRow.created_at.desc()).limit(1)).scalar()


LOAD_EVENTS = ("setup_start", "start", "pause", "resume", "complete")


def _apply_load_event(c: _Ctx, inp: FloorEventInput, load_id: str) -> dict[str, Any]:
    s = c.s
    load = s.execute(select(MfgBatchLoadRow).where(MfgBatchLoadRow.id == load_id).with_for_update()
                     .execution_options(populate_existing=True)).scalars().first()
    if load is None:
        raise not_found("Batch load", load_id)
    if inp.event_type not in LOAD_EVENTS:
        raise ApiError(422, "VALIDATION_ERROR", f"A batch load takes {', '.join(LOAD_EVENTS)} events.",
                       {"errors": [{"loc": ["body", "event_type"], "msg": "not a load event", "type": "value_error"}]})
    if load.status in ("completed", "cancelled"):
        raise ApiError(409, "FLR_INVALID_TRANSITION", f"The batch load is {load.status}.",
                       {"status": load.status, "event": inp.event_type, "allowed": []})
    members = list(s.execute(select(MfgBatchLoadMemberRow).where(MfgBatchLoadMemberRow.load_id == load.id)
                             .order_by(MfgBatchLoadMemberRow.id)).scalars())
    ops = {o.id: o for o in s.execute(select(MfgWoOperationRow).where(
        MfgWoOperationRow.id.in_([m.wo_operation_id for m in members]))).scalars()}
    # lock order: WO headers by id, then each WO's operations (inside _apply_op_event)
    results = []
    linp = inp.model_copy(update={"line_id": inp.line_id or load.line_id})
    for k, m in enumerate(sorted(members, key=lambda m: (ops[m.wo_operation_id].wo_id, m.wo_operation_id))):
        o = ops[m.wo_operation_id]
        results.append(_apply_op_event(c, linp, o.wo_id, o.id, load,
                                       member_qty=m.qty if inp.event_type == "complete" else None, first=k == 0))
    if inp.event_type in ("setup_start", "start") and load.status == "open":
        load.status, load.started_at = "running", as_utc(inp.event_at) if inp.event_at else c.now
    elif inp.event_type == "complete":
        load.status, load.ended_at = "completed", as_utc(inp.event_at) if inp.event_at else c.now
    touch(load, c.now)
    s.flush()
    first = results[0]
    return {**first, "operations": [r["operation"] for r in results[1:]] + first["operations"],
            "postings": c.postings, "warnings": c.warnings, "triggers": c.triggers}


# ---------------------------------------------------------------- reads: events (204), detail (202), queue (201)

def list_events(ctx: AppContext, *, wo_id: str | None, line_id: str | None, operator_id: str | None,
                wo_operation_id: str | None = None, event_type: str | None, from_: datetime | None,
                to: datetime | None, limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if wo_id:
        conds.append(MfgFloorEventRow.wo_id == wo_id)
    if wo_operation_id:
        conds.append(MfgFloorEventRow.wo_operation_id == wo_operation_id)
    if line_id:
        conds.append(MfgFloorEventRow.line_id == line_id)
    if event_type:
        conds.append(MfgFloorEventRow.event_type == event_type)
    if from_ is not None:
        conds.append(MfgFloorEventRow.event_at >= from_)
    if to is not None:
        conds.append(MfgFloorEventRow.event_at < to)
    with read_tx(ctx) as s:
        q = select(MfgFloorEventRow).where(*conds)
        if operator_id:
            from sqlalchemy import cast, String as _S

            q = q.where(cast(MfgFloorEventRow.operator_ids, _S).contains(operator_id))
        total = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = list(s.execute(q.order_by(MfgFloorEventRow.seq.desc()).limit(limit).offset(offset)).scalars())
        return page(_event_records(s, rows), total, limit, offset)


def operation_detail(ctx: AppContext, wo_op_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        op = repo.get_row(s, MfgWoOperationRow, wo_op_id, what="Operation")
        wo = s.get(MfgWorkOrderRow, op.wo_id)
        rows = wo_rows(s, wo.id)
        rec = op_records(s, [op])[0]
        item = s.get(MfgItemRow, wo.item_id)
        rid = wo.routing_id or routing_of(s, wo)
        ro = s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id == rid,
                                                     MfgOperationRow.seq == op.seq)).scalars().first() \
            if rid else None
        comps = _op_components(s, wo, rows, op)
        its = {i.id: i for i in s.execute(select(MfgItemRow).where(
            MfgItemRow.id.in_({x.item_id for x in comps}))).scalars()} if comps else {}
        res = dict(s.execute(select(MfgInvReservationRow.wo_component_id, func.sum(MfgInvReservationRow.qty))
                             .where(MfgInvReservationRow.wo_component_id.in_([x.id for x in comps]))
                             .group_by(MfgInvReservationRow.wo_component_id)).all()) if comps else {}
        bf = (op.effects or {}).get("backflush", {})
        bf_loc = _backflush_location(s, op.line_id)
        loc = s.get(MfgLocationRow, bf_loc) if bf_loc else None
        components = []
        for x in comps:
            it = its.get(x.item_id)
            back = it is not None and it.issue_method == "backflush"
            need = max(0.0, x.required_qty - x.issued_qty)
            have = float(res.get(x.id) or 0.0)
            kit = "kitted" if have + EPS >= need or back else ("partial" if have > 0 or x.issued_qty > 0 else "short")
            components.append({
                "component_id": x.id, "item": {"id": x.item_id, "part_number": it.part_number if it else "",
                                               "description": it.description if it else ""},
                "required_qty": x.required_qty, "issued_qty": x.issued_qty, "backflush": back,
                "backflush_posted": float((bf.get(x.id) or {}).get("posted", 0.0)),
                "backflush_pending": float((bf.get(x.id) or {}).get("pending", 0.0)), "kit": kit,
                "location": {"id": loc.id, "code": loc.code} if back and loc is not None else None})
        tools = []
        if ro is not None:
            for t, tp in s.execute(select(MfgOperationToolRow, MfgToolPoolRow).join(
                    MfgToolPoolRow, MfgToolPoolRow.id == MfgOperationToolRow.tool_pool_id)
                    .where(MfgOperationToolRow.operation_id == ro.id)).all():
                tools.append({"tool_pool": _ref(tp), "qty": t.qty})
        evs = list(s.execute(select(MfgFloorEventRow).where(MfgFloorEventRow.wo_operation_id == op.id)
                             .order_by(MfgFloorEventRow.seq)).scalars())
        st = rec["status"]
        serial_info = _serial_info(s, wo, rows, op, item, ro)
        return {"operation": rec, "wo": wo_summary(s, wo), "instructions": ro.description if ro is not None else "",
                "components": components, "tools": tools,
                "eligible_lines": [_ref(x) for x in eligible_lines(s, op.group_id, item)],
                "expected_input": rec["qty_input"], "events": _event_records(s, evs),
                "allowed_actions": E.allowed_events(st, supervisor=False), "serials": serial_info,
                "reason_codes": reason_codes(_plant(s))}


def reason_codes(plant: Any) -> dict[str, list[dict[str, str]]]:
    """Floor reason codes per kind: the plant attribute `floor_reasons_<kind>` ("CODE:Label,...") or the defaults."""
    from ....mfg.model_m4 import DEFAULT_REASON_CODES

    attrs = dict(getattr(plant, "attributes", None) or {})
    out = {}
    for kind, default in DEFAULT_REASON_CODES.items():
        raw = attrs.get(f"floor_reasons_{kind}")
        pairs = default
        if isinstance(raw, str) and raw.strip():
            pairs = []
            for part in raw.split(","):
                code, _sep, label = part.strip().partition(":")
                if code.strip():
                    pairs.append((code.strip()[:32], (label or code).strip()[:100]))
        out[kind] = [{"code": c, "label": lb} for c, lb in pairs]
    return out


def _serial_info(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow,
                 item: MfgItemRow | None, ro: MfgOperationRow | None) -> dict[str, Any]:
    from . import floor_effects

    capture = floor_effects.captures_serials(s, wo, rows, op, item)
    produced = [x.serial for x in s.execute(select(MfgUnitSerialRow).where(
        MfgUnitSerialRow.wo_id == wo.id, MfgUnitSerialRow.captured_op_seq == op.seq)
        .order_by(MfgUnitSerialRow.serial)).scalars()] if capture else []
    consumable: list[dict[str, Any]] = []
    for x in _op_components(s, wo, rows, op):
        it = s.get(MfgItemRow, x.item_id)
        if it is not None and it.serialized:
            consumable.append({"item_id": it.id, "part_number": it.part_number})
    return {"capture": capture, "produced": produced, "consumable": consumable}


def _backflush_location(s: Session, line_id: str | None) -> str | None:
    if line_id:
        ln = s.get(MfgLineRow, line_id)
        if ln is not None and ln.location_id:
            return ln.location_id
    p = _plant(s)
    return p.backflush_location_id if p is not None else None


def queue(ctx: AppContext, line_id: str, shift: str | None, day: date | None) -> dict[str, Any]:
    """GET /floor/queue: the published dispatch of the line (M3 #188 rows) with the live operation status, kit light
    and next actions; operations already running / paused on the line are listed first."""
    from ....mfg.calendar import line_windows
    from ....mfg.tz import plant_tz
    from .. import repo_m3

    with read_tx(ctx) as s:
        line = s.get(MfgLineRow, line_id)
        if line is None:
            raise not_found("Line", line_id)
        p = _plant(s)
        tz = plant_tz(p) if p is not None else UTC
        now = utcnow()
        day = day or now.astimezone(tz).date()
        lo = datetime(day.year, day.month, day.day, tzinfo=tz)
        hi = lo + timedelta(days=1)
        pub = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
        aps_rows: list[MfgApsOpRow] = []
        if pub is not None:
            aps_rows = list(s.execute(select(MfgApsOpRow).where(
                MfgApsOpRow.run_id == pub.id, MfgApsOpRow.line_id == line_id, MfgApsOpRow.status == "scheduled",
                MfgApsOpRow.start_at < hi, MfgApsOpRow.end_at > lo).order_by(MfgApsOpRow.start_at,
                                                                             MfgApsOpRow.op_no)).scalars())
        ds = repo_m3.calendar_dataset(s, [line_id])
        wins = line_windows(ds, line_id, day, day + timedelta(days=1))
        if shift:
            wins_s = [w for w in wins if shift in w.shift_label.split("/")[-1].split("+")]
            aps_rows = [x for x in aps_rows if any(w.start <= as_utc(x.start_at) < w.end for w in wins_s)]
        live = list(s.execute(select(MfgWoOperationRow).where(
            MfgWoOperationRow.line_id == line_id,
            MfgWoOperationRow.status.in_(("setup", "running", "paused")))).scalars())
        wo_ids = sorted({x.order_id for x in aps_rows if x.order_type == "wo"} | {r.wo_id for r in live})
        from types import SimpleNamespace

        cols = ("order_type", "order_id", "seq", "name", "start_at", "end_at", "op_no", "qty")
        aps_rows = [SimpleNamespace(**{c: getattr(x, c) for c in cols}) for x in aps_rows]
        pub_id = pub.id if pub is not None else None
    ensure_lazy(ctx, wo_ids)
    with read_tx(ctx) as s:
        line = s.get(MfgLineRow, line_id)
        wos = {w.id: w for w in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id.in_(wo_ids))).scalars()} \
            if wo_ids else {}
        rows = list(s.execute(select(MfgWoOperationRow).where(MfgWoOperationRow.wo_id.in_(wo_ids))).scalars()) \
            if wo_ids else []
        by_key = {(r.wo_id, r.seq): r for r in rows}
        recs = {r["id"]: r for r in op_records(s, rows, placement=False)} if rows else {}
        its = {i.id: i for i in s.execute(select(MfgItemRow).where(
            MfgItemRow.id.in_({w.item_id for w in wos.values()}))).scalars()} if wos else {}
        kit = _kit_lights(s, wo_ids)
        loads = {m.wo_operation_id: m.load_id for m, ld in s.execute(
            select(MfgBatchLoadMemberRow, MfgBatchLoadRow).join(MfgBatchLoadRow, MfgBatchLoadRow.id ==
                                                                 MfgBatchLoadMemberRow.load_id)
            .where(MfgBatchLoadRow.status.in_(("open", "running")),
                   MfgBatchLoadMemberRow.wo_operation_id.in_([r.id for r in rows]))).all()} if rows else {}
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(wo: MfgWorkOrderRow, seq: int, name: str, aps: MfgApsOpRow | None) -> None:
            r = by_key.get((wo.id, seq))
            rec = recs.get(r.id) if r is not None else None
            if r is not None:
                if r.id in seen:
                    return
                seen.add(r.id)
            it = its.get(wo.item_id)
            status = rec["status"] if rec else "pending"
            items.append({
                "wo_operation_id": r.id if r is not None else None,
                "wo": {"id": wo.id, "number": wo.number,
                       "item": {"id": wo.item_id, "part_number": it.part_number if it else "",
                                "description": it.description if it else ""},
                       "qty": wo.qty, "due_date": wo.due_date, "priority": wo.priority, "row_version": wo.row_version},
                "seq": seq, "name": name, "status": status,
                "planned_start": as_utc(aps.start_at) if aps else None,
                "planned_end": as_utc(aps.end_at) if aps else None, "op_no": aps.op_no if aps else None,
                "qty_planned": r.qty_planned if r is not None else (aps.qty if aps else wo.qty),
                "qty_good": r.qty_good if r is not None else 0.0, "kit": kit.get(wo.id, "none"),
                "batch_load_id": loads.get(r.id) if r is not None else None,
                "next_actions": [a for a in E.allowed_events(status, supervisor=False) if a != "skip"]})

        for r in sorted([x for x in rows if x.line_id == line_id and x.status in ("setup", "running", "paused")],
                        key=lambda x: (as_utc(x.actual_start) or now, x.wo_id, x.seq)):
            w = wos.get(r.wo_id)
            if w is not None:
                aps = next((a for a in aps_rows if a.order_id == w.id and a.seq == r.seq), None)
                add(w, r.seq, r.name, aps)
        for a in aps_rows:
            if a.order_type != "wo":
                continue
            w = wos.get(a.order_id)
            if w is None or w.status not in FLOOR_WO_STATUSES:
                continue
            r = by_key.get((w.id, a.seq))
            if r is not None and r.status in ("completed", "skipped") and r.line_id != line_id:
                continue
            add(w, a.seq, a.name, a)
        dt = open_downtime(s, line_id, now)
        return {"line": _ref(line), "date": day.isoformat(), "shift": shift, "run_id": pub_id,
                "down": ({"id": dt.id, "kind": dt.kind, "start_at": as_utc(dt.start_at),
                          "expected_end_at": as_utc(dt.expected_end_at), "reason": dt.reason} if dt else None),
                "shifts": [{"label": w.shift_label, "start": as_utc(w.start), "end": as_utc(w.end), "kind": w.kind}
                           for w in wins],
                "items": items}


def _kit_lights(s: Session, wo_ids: list[str]) -> dict[str, str]:
    kit: dict[str, str] = {}
    if not wo_ids:
        return kit
    comps = list(s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id.in_(wo_ids))).scalars())
    res = dict(s.execute(select(MfgInvReservationRow.wo_component_id, func.sum(MfgInvReservationRow.qty))
                         .where(MfgInvReservationRow.wo_component_id.in_([c.id for c in comps]))
                         .group_by(MfgInvReservationRow.wo_component_id)).all()) if comps else {}
    back = set(s.execute(select(MfgItemRow.id).where(MfgItemRow.id.in_({c.item_id for c in comps}),
                                                     MfgItemRow.issue_method == "backflush")).scalars()) \
        if comps else set()
    order = {"kitted": 0, "partial": 1, "short": 2}
    for c in comps:
        if c.item_id in back:
            st = "kitted"
        else:
            need = max(0.0, c.required_qty - c.issued_qty)
            have = float(res.get(c.id) or 0.0)
            st = "kitted" if have + EPS >= need else ("partial" if have > 0 or c.issued_qty > 0 else "short")
        prev = kit.get(c.wo_id, "kitted")
        kit[c.wo_id] = st if order[st] > order[prev] else prev
    return kit


# ---------------------------------------------------------------- scan (200)

def scan(ctx: AppContext, code: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        for lk in SCAN.parse(code):
            hit = _lookup(s, lk)
            if hit is not None:
                return hit
    raise ApiError(404, "FLR_SCAN_UNKNOWN", f"Nothing matches {SCAN.normalise(code)!r}.",
                   {"code": SCAN.normalise(code)})


def _wo_by_number(s: Session, number: str) -> MfgWorkOrderRow | None:
    return s.execute(select(MfgWorkOrderRow).where(func.upper(MfgWorkOrderRow.number) == number.upper())
                     ).scalars().first()


def _lookup(s: Session, lk: SCAN.Lookup) -> dict[str, Any] | None:
    t = lk.type
    if t == "work_order":
        w = _wo_by_number(s, lk.key[0])
        if w is None:
            return None
        it = s.get(MfgItemRow, w.item_id)
        return {"type": "work_order", "id": w.id, "label": f"{w.number} {it.part_number if it else ''} x {w.qty:g}",
                "link": f"/mfg/work-orders/{w.id}", "context": {"status": w.status}}
    if t == "operation":
        w = _wo_by_number(s, lk.key[0])
        if w is None:
            return None
        seq = int(lk.key[1])
        r = s.execute(select(MfgWoOperationRow).where(MfgWoOperationRow.wo_id == w.id,
                                                      MfgWoOperationRow.seq == seq)).scalars().first()
        if r is None:
            ro = next((o for o in routing_ops(s, routing_of(s, w)) if o.seq == seq), None)
            if ro is None:
                return None
            return {"type": "operation", "id": "", "label": f"{w.number} op {seq} {ro.name}", "link": "",
                    "context": {"wo_id": w.id, "seq": seq, "status": "pending", "line_id": None,
                                "wo_status": w.status}}
        return {"type": "operation", "id": r.id, "label": f"{w.number} op {seq} {r.name}",
                "link": f"/mfg/floor/operations/{r.id}",
                "context": {"wo_id": w.id, "seq": seq, "status": r.status, "line_id": r.line_id}}
    if t == "lot" or t == "lot_code":
        q = select(MfgLotRow, MfgItemRow).join(MfgItemRow, MfgItemRow.id == MfgLotRow.item_id)
        if t == "lot":
            q = q.where(func.upper(MfgItemRow.part_number) == lk.key[0].upper(),
                        func.upper(MfgLotRow.lot_code) == lk.key[1].upper())
        else:
            q = q.where(func.upper(MfgLotRow.lot_code) == lk.key[0].upper())
        hits = s.execute(q.limit(2)).all()
        if len(hits) != 1:
            return None
        lot, it = hits[0]
        return {"type": "lot", "id": lot.id, "label": f"{it.part_number} lot {lot.lot_code}",
                "link": f"/mfg/inventory/lots/{lot.id}", "context": {"item_id": it.id, "lot_code": lot.lot_code}}
    if t == "serial" or t == "serial_code":
        q = select(MfgUnitSerialRow, MfgItemRow).join(MfgItemRow, MfgItemRow.id == MfgUnitSerialRow.item_id)
        if t == "serial":
            q = q.where(func.upper(MfgItemRow.part_number) == lk.key[0].upper(),
                        func.upper(MfgUnitSerialRow.serial) == lk.key[1].upper())
        else:
            q = q.where(func.upper(MfgUnitSerialRow.serial) == lk.key[0].upper())
        hits = s.execute(q.limit(2)).all()
        if len(hits) != 1:
            return None
        u, it = hits[0]
        return {"type": "serial", "id": u.id, "label": f"{it.part_number} S/N {u.serial}",
                "link": f"/mfg/serials/{u.id}", "context": {"item_id": it.id, "status": u.status, "wo_id": u.wo_id}}
    if t == "location":
        loc = s.execute(select(MfgLocationRow).where(func.upper(MfgLocationRow.code) == lk.key[0].upper())
                        ).scalars().first()
        if loc is None:
            return None
        return {"type": "location", "id": loc.id, "label": f"{loc.code} {loc.name}",
                "link": f"/mfg/inventory/locations/{loc.id}", "context": {"kind": loc.kind}}
    if t == "line":
        ln = s.execute(select(MfgLineRow).where(func.upper(MfgLineRow.code) == lk.key[0].upper())).scalars().first()
        if ln is None:
            return None
        return {"type": "line", "id": ln.id, "label": f"{ln.code} {ln.name}", "link": f"/mfg/floor?line={ln.id}",
                "context": {"group_id": ln.group_id, "active": ln.active}}
    if t == "operator":
        o = s.execute(select(MfgOperatorRow).where(func.upper(MfgOperatorRow.code) == lk.key[0].upper())
                      ).scalars().first()
        if o is None:
            return None
        return {"type": "operator", "id": o.id, "label": f"{o.code} {o.name}", "link": "",
                "context": {"code": o.code, "active": o.active}}
    if t == "batch_load":
        lid = _load_by_code(s, lk.key[0])
        if lid is None:
            return None
        ld = s.get(MfgBatchLoadRow, lid)
        ln = s.get(MfgLineRow, ld.line_id)
        return {"type": "batch_load", "id": ld.id, "label": f"Load {load_code(ld.id)} on {ln.code if ln else ''}",
                "link": f"/mfg/floor/loads/{ld.id}", "context": {"status": ld.status, "line_id": ld.line_id}}
    return None


# ---------------------------------------------------------------- batch loads (211-213)

def load_code(load_id: str) -> str:
    return "BL:" + load_id[-8:]


def load_records(s: Session, loads: list[MfgBatchLoadRow]) -> list[dict[str, Any]]:
    if not loads:
        return []
    ids = [ld.id for ld in loads]
    mem = list(s.execute(select(MfgBatchLoadMemberRow).where(MfgBatchLoadMemberRow.load_id.in_(ids))
                         .order_by(MfgBatchLoadMemberRow.id)).scalars())
    ops = {o.id: o for o in s.execute(select(MfgWoOperationRow).where(
        MfgWoOperationRow.id.in_({m.wo_operation_id for m in mem}))).scalars()} if mem else {}
    wos = {w.id: w.number for w in s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.number).where(
        MfgWorkOrderRow.id.in_({o.wo_id for o in ops.values()}))).all()} if ops else {}
    lines = {ln.id: ln for ln in s.execute(select(MfgLineRow).where(
        MfgLineRow.id.in_({ld.line_id for ld in loads}))).scalars()}
    out = []
    for ld in loads:
        ms = [m for m in mem if m.load_id == ld.id]
        out.append({"id": ld.id, "row_version": ld.row_version, "created_at": as_utc(ld.created_at),
                    "updated_at": as_utc(ld.updated_at), "load_no": load_code(ld.id),
                    "line": _ref(lines.get(ld.line_id)), "status": ld.status, "started_at": as_utc(ld.started_at),
                    "ended_at": as_utc(ld.ended_at), "aps_run_id": ld.aps_run_id,
                    "units": round(sum(m.qty for m in ms), 6),
                    "members": [{"wo_operation_id": m.wo_operation_id,
                                 "wo": {"id": ops[m.wo_operation_id].wo_id,
                                        "number": wos.get(ops[m.wo_operation_id].wo_id, "")},
                                 "seq": ops[m.wo_operation_id].seq, "qty": m.qty} for m in ms]})
    return out


def list_loads(ctx: AppContext, *, line_id: str | None, status: str | None, limit: int, offset: int
               ) -> dict[str, Any]:
    conds = []
    if line_id:
        conds.append(MfgBatchLoadRow.line_id == line_id)
    if status:
        conds.append(MfgBatchLoadRow.status == status)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgBatchLoadRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgBatchLoadRow).where(*conds).order_by(
            MfgBatchLoadRow.created_at.desc(), MfgBatchLoadRow.id).limit(limit).offset(offset)).scalars())
        return page(load_records(s, rows), total, limit, offset)


def get_load(ctx: AppContext, load_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return load_records(s, [repo.get_row(s, MfgBatchLoadRow, load_id, what="Batch load")])[0]


def create_load(ctx: AppContext, inp: Any) -> dict[str, Any]:
    """POST /batch-loads (6.3): members must be open operations of the line's group with compatible batch data
    (same `units_per_batch`, run minutes and item setup family; `run_per = batch`); the units fit one load."""

    def fn(s: Session) -> dict[str, Any]:
        line = s.get(MfgLineRow, inp.line_id)
        if line is None:
            raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Line {inp.line_id!r} was not found.",
                           {"loc": ["body", "line_id"], "id": inp.line_id})
        ops = {o.id: o for o in s.execute(select(MfgWoOperationRow).where(
            MfgWoOperationRow.id.in_([m.wo_operation_id for m in inp.members]))).scalars()}
        keys = set()
        cap = None
        for i, m in enumerate(inp.members):
            o = ops.get(m.wo_operation_id)
            if o is None:
                raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Operation {m.wo_operation_id!r} was not found.",
                               {"loc": ["body", "members", i, "wo_operation_id"], "id": m.wo_operation_id})
            if o.status in ("completed", "skipped"):
                raise ApiError(409, "FLR_INVALID_TRANSITION", "A completed or skipped operation cannot join a load.",
                               {"status": o.status, "event": "load", "allowed": []})
            wo = s.get(MfgWorkOrderRow, o.wo_id)
            it = s.get(MfgItemRow, wo.item_id)
            if not _line_ok(s, line, o.group_id, it):
                raise ApiError(422, "FLR_LINE_NOT_ELIGIBLE", f"{line.code} cannot run {wo.number} op {o.seq}.",
                               {"loc": ["body", "members", i, "wo_operation_id"], "line_id": line.id})
            ro = s.execute(select(MfgOperationRow).where(MfgOperationRow.routing_id == routing_of(s, wo),
                                                         MfgOperationRow.seq == o.seq)).scalars().first()
            if ro is None or ro.run_per != "batch":
                raise ApiError(422, "FLR_LOAD_INCOMPATIBLE", f"{wo.number} op {o.seq} is not a batch operation.",
                               {"loc": ["body", "members", i]})
            keys.add((o.group_id, it.setup_family if it else None, ro.units_per_batch, float(ro.run_minutes)))
            cap = ro.units_per_batch
            busy = s.execute(select(MfgBatchLoadMemberRow.load_id).join(
                MfgBatchLoadRow, MfgBatchLoadRow.id == MfgBatchLoadMemberRow.load_id).where(
                MfgBatchLoadMemberRow.wo_operation_id == o.id, MfgBatchLoadRow.status.in_(("open", "running")))
            ).scalar()
            if busy is not None:
                raise ApiError(409, "FLR_LOAD_MEMBER_BUSY", f"{wo.number} op {o.seq} is already in an open load.",
                               {"load_id": busy})
        if len(keys) > 1:
            raise ApiError(422, "FLR_LOAD_INCOMPATIBLE", "The operations are not compatible (group, setup family, "
                           "units per batch and run minutes must match).", {"loc": ["body", "members"]})
        units = sum(m.qty for m in inp.members)
        if cap is not None and units > cap + EPS:
            raise ApiError(422, "FLR_LOAD_OVER_CAPACITY", f"A load holds at most {cap} units ({units:g} given).",
                           {"loc": ["body", "members"], "capacity": cap, "units": units})
        now = utcnow()
        ld = MfgBatchLoadRow(id=new_id("bld_"), line_id=line.id, status="open", started_at=None, ended_at=None,
                             aps_run_id=inp.aps_run_id, actor_id=actor_id(), row_version=1, created_at=now,
                             updated_at=now)
        s.add(ld)
        s.flush()
        s.add_all([MfgBatchLoadMemberRow(id=new_id("blm_"), load_id=ld.id, wo_operation_id=m.wo_operation_id,
                                         qty=float(m.qty)) for m in inp.members])
        s.flush()
        audit(s, "batch_load", ld.id, "create", {"line": line.code, "members": len(inp.members)})
        return load_records(s, [ld])[0]

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- backflush retry (205)

def retry_backflush(ctx: AppContext, wo_id: str | None) -> dict[str, Any]:
    from . import floor_effects

    with read_tx(ctx) as s:
        q = select(MfgWoOperationRow).where(MfgWoOperationRow.status != "pending")
        if wo_id:
            repo.get_row(s, MfgWorkOrderRow, wo_id, what="Work order")
            q = q.where(MfgWoOperationRow.wo_id == wo_id)
        wo_ids = sorted({r.wo_id for r in s.execute(q).scalars() if floor_effects.pending_of(r)})

    def fn(s: Session) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for wid in sorted(wo_ids):
            wo = lock_wo(s, wid)
            rows = wo_rows(s, wid, lock=True)
            if not any(floor_effects.pending_of(r) for r in rows):
                continue
            results.extend(floor_effects.retry_wo(s, wo, rows))
        return {"results": results, "posted": sum(1 for r in results if r["status"] == "posted"),
                "pending": sum(1 for r in results if r["status"] == "pending")}

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- M3 #177/#178 shortcuts (supervisor)

def set_done(ctx: AppContext, wo_id: str, seq_s: str | int, done: bool, if_match: str | None,
             p: MfgPrincipal | None = None) -> dict[str, Any]:
    """M3 `done` = start (if not started) + `complete` with `qty_good` = the available input; `reopen` = a
    `reopen` event of a completed operation (M4-DESIGN 11)."""

    def fn(s: Session) -> dict[str, Any]:
        wo = repo.get_row(s, MfgWorkOrderRow, wo_id, what="Work order", lock=True)
        if not str(seq_s).isdigit() or len(str(seq_s)) > 9:
            raise ApiError(404, "NOT_FOUND", f"Operation {seq_s!r} was not found on {wo.number}.", {"id": str(seq_s)})
        seq = int(seq_s)
        check_version(wo, if_match)
        if wo.status not in ("released", "in_progress", "completed"):
            raise ApiError(409, "MFG_INVALID_STATE", f"{wo.number} is {wo.status}; operations cannot change.",
                           {"status": wo.status, "action": "done" if done else "reopen",
                            "allowed_from": ["released", "in_progress", "completed"]})
        rows = ensure_rows(s, wo)
        op = next((r for r in rows if r.seq == seq), None)
        if op is None:
            raise ApiError(404, "NOT_FOUND", f"Operation {seq} was not found on {wo.number}.", {"id": str(seq)})
        v0 = wo.row_version
        base = f"m3-{'done' if done else 'reopen'}-{new_id('x')[2:]}"
        if done:
            if op.status not in ("completed", "skipped"):
                if op.status in ("pending",):
                    apply_event(s, FloorEventInput(client_event_id=base + "-s", wo_operation_id=op.id,
                                                   event_type="start", line_id=_default_line(s, wo, op)), p)
                rows = wo_rows(s, wo.id)
                avail = _chain(rows)[seq].qty_available
                apply_event(s, FloorEventInput(client_event_id=base + "-c", wo_operation_id=op.id,
                                               event_type="complete", qty_good=avail), p)
        elif op.status == "completed":
            apply_event(s, FloorEventInput(client_event_id=base + "-r", wo_operation_id=op.id,
                                           event_type="reopen"), p)
        wo = s.get(MfgWorkOrderRow, wo.id)
        if wo.row_version == v0:            # one version step per shortcut (M3 #177/#178 contract)
            touch(wo)
        s.flush()
        audit(s, "work_order", wo.id, "operation_done" if done else "operation_reopen",
              {"number": wo.number, "seq": seq, "version": wo.row_version})
        return wo_operations_in(s, wo)

    return run_tx(ctx, fn)


def _default_line(s: Session, wo: MfgWorkOrderRow, op: MfgWoOperationRow) -> str | None:
    """The shortcut's line: the operation's own, the published placement, else the first eligible line."""
    if op.line_id:
        return op.line_id
    pl = _placements(s, [wo.id]).get((wo.id, op.seq))
    if pl and pl[0]["line"]["id"]:
        return pl[0]["line"]["id"]
    el = eligible_lines(s, op.group_id, s.get(MfgItemRow, wo.item_id))
    return el[0].id if el else None


__all__ = ["apply_event", "create_load", "ensure_rows", "get_load", "list_events", "list_loads", "operation_detail",
           "post_event", "queue", "refresh_operations", "release_to_floor", "retry_backflush", "scan", "set_done",
           "wo_operations"]

_ = (Any, MfgRoutingRow)
