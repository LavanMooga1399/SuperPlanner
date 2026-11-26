"""Sterilisation service (M8-DESIGN 8, 11 S1-S7): load planning (job `ster_plan` / on demand), loads, floor
states, signed release, failure.

- Plan: candidates = production blocks of the published rate run (not yet WOs) and WOs (planned / released /
  in progress / completed, due in the window) of items with `ster_cycle_code`, not already in a load past
  `planned`; ready = block end / WO completion (else due date, plant 00:00); a repetitive WO is ready at its
  block's end. Chambers = active `sterilisation` lines; aeration rooms = active lines of groups with `kind
  aeration` (`chamber_pallets` = positions). Existing `planned` loads are replaced; loaded..awaiting loads keep the
  chambers and rooms busy. The independent validator must pass (else 409 `STER_PLAN_INVALID`).
- `POST /load` creates the M4 batch load on the chamber with the member WOs' operations of the chamber group (all
  members need a WO: 409 `STER_MEMBER_NO_WO`). `advance` moves loaded -> cycling -> aerating ->
  awaiting_release (or planned/loaded -> cancelled). At cycle complete (-> aerating) every member lot gets a hold
  `source sterility` with `planned_release` and co-sterilisation trace edges (lot -> load -> lot).
- `release` (permission ster_release, signature policy `ster_load.release`, always signed) lifts the sterility
  holds; `fail` keeps them and opens one NCR listing every lot.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....mfg.ster import loads as LOADS
from ....mfg.ster.model import LOAD_FLOW, AerationRoom, Chamber, SterCandidate
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgGroupRow, MfgItemRow, MfgLineRow
from ..db_models_m2 import MfgInvTransactionRow, MfgLotRow, MfgWorkOrderRow
from ..db_models_m8 import (MfgItemPackagingRow, MfgItemPlanningRow, MfgRateBlockRow, MfgSterLoadMemberRow,
                            MfgSterLoadRow)
from . import m8_examples
from .common import audit, check_version, read_tx, write_tx
from .m8common import next_number, page, plant_row, settings_of, today

ACTIVE = ("loaded", "cycling", "aerating", "awaiting_release")


# ---------------------------------------------------------------- records

def _members(s: Session, load_ids: list[str]) -> dict[str, list[MfgSterLoadMemberRow]]:
    out: dict[str, list[MfgSterLoadMemberRow]] = defaultdict(list)
    if load_ids:
        for m in s.execute(select(MfgSterLoadMemberRow).where(MfgSterLoadMemberRow.load_id.in_(load_ids))
                           .order_by(MfgSterLoadMemberRow.id)).scalars():
            out[m.load_id].append(m)
    return out


def _record(s: Session, r: MfgSterLoadRow, members: list[MfgSterLoadMemberRow] | None = None,
            full: bool = True) -> dict[str, Any]:
    ms = members if members is not None else _members(s, [r.id])[r.id]
    ch = s.get(MfgLineRow, r.chamber_line_id)
    rec = {"id": r.id, "number": r.number, "run_id": r.run_id, "chamber_line_id": r.chamber_line_id,
           "chamber_code": ch.code if ch else None, "cycle_code": r.cycle_code, "status": r.status,
           "pallets": r.pallets, "planned_start": r.planned_start, "planned_end": r.planned_end,
           "aeration_end": r.aeration_end, "release_due": r.release_due, "actual_start": r.actual_start,
           "actual_end": r.actual_end, "actual_aeration_end": r.actual_aeration_end, "batch_load_id": r.batch_load_id,
           "release_signature_id": r.release_signature_id, "ncr_id": r.ncr_id, "flags": list(r.flags or []),
           "members": [], "signatures": [], "row_version": r.row_version, "created_at": r.created_at,
           "updated_at": r.updated_at}
    if full:
        wos = {w.id: w.number for w in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id.in_(
            [m.wo_id for m in ms if m.wo_id]))).scalars()} if any(m.wo_id for m in ms) else {}
        lots = {lt.id: lt.lot_code for lt in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(
            [m.lot_id for m in ms if m.lot_id]))).scalars()} if any(m.lot_id for m in ms) else {}
        pns = dict(s.execute(select(MfgItemRow.id, MfgItemRow.part_number).where(
            MfgItemRow.id.in_({m.item_id for m in ms}))).all()) if ms else {}
        rec["members"] = [{"id": m.id, "wo_id": m.wo_id, "wo_number": wos.get(m.wo_id or ""),
                           "rate_block_id": m.rate_block_id, "lot_id": m.lot_id,
                           "lot_code": lots.get(m.lot_id or ""), "item_id": m.item_id,
                           "part_number": pns.get(m.item_id), "qty": m.qty, "pallets": m.pallets} for m in ms]
        from . import esig

        rec["signatures"] = esig.manifests(s, "ster_load", r.id)
    return rec


def _content(s: Session, r: MfgSterLoadRow) -> dict[str, Any]:
    ms = _members(s, [r.id])[r.id]
    return {"id": r.id, "number": r.number, "chamber_line_id": r.chamber_line_id, "cycle_code": r.cycle_code,
            "status": r.status, "actual_start": r.actual_start.isoformat() if r.actual_start else None,
            "actual_end": r.actual_end.isoformat() if r.actual_end else None, "release_due": r.release_due.isoformat(),
            "members": sorted([{"item_id": m.item_id, "lot_id": m.lot_id, "wo_id": m.wo_id, "qty": m.qty}
                               for m in ms], key=lambda x: (x["item_id"], x["lot_id"] or "", x["wo_id"] or ""))}


def _loader(s: Session, record_id: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, MfgSterLoadRow, record_id, what="Sterilisation load", lock=lock)
    c = _content(s, r)
    lots = ", ".join(sorted({m["lot_id"] or "-" for m in c["members"]}))
    return C.Loaded(r, c, r.row_version, None, [("Load", r.number), ("Cycle", r.cycle_code), ("Lots", lots)])


C.register("ster_load", _loader)


def list_loads(ctx: AppContext, status: str | None, from_: date | None, to: date | None, chamber_line_id: str | None,
               limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        q = select(MfgSterLoadRow)
        if status:
            q = q.where(MfgSterLoadRow.status.in_(status.split(",")))
        if chamber_line_id:
            q = q.where(MfgSterLoadRow.chamber_line_id == chamber_line_id)
        if from_:
            q = q.where(MfgSterLoadRow.planned_end >= datetime.combine(from_, time(0), UTC))
        if to:
            q = q.where(MfgSterLoadRow.planned_start < datetime.combine(to + timedelta(days=1), time(0), UTC))
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = list(s.execute(q.order_by(MfgSterLoadRow.planned_start, MfgSterLoadRow.number).limit(limit)
                              .offset(offset)).scalars())
        ms = _members(s, [r.id for r in rows])
        cap = capacity(s)
        return page([_record(s, r, ms[r.id], full=False) | {"members": [
            {"id": m.id, "wo_id": m.wo_id, "wo_number": None, "rate_block_id": m.rate_block_id, "lot_id": m.lot_id,
             "lot_code": None, "item_id": m.item_id, "part_number": None, "qty": m.qty, "pallets": m.pallets}
            for m in ms[r.id]]} for r in rows], n, limit, offset, **cap)


def capacity(s: Session) -> dict[str, Any]:
    """Chambers and aeration rooms (UI request: aeration utilisation against capacity)."""
    chambers = [{"line_id": c.id, "code": c.code, "pallets": c.chamber_pallets, "cycle_hours": c.cycle_hours}
                for c in s.execute(select(MfgLineRow).where(MfgLineRow.active.is_(True),
                                                            MfgLineRow.planning == "sterilisation")
                                   .order_by(MfgLineRow.code)).scalars()]
    rooms = [{"line_id": r.id, "code": r.code, "positions": int(r.chamber_pallets or 0)}
             for r in s.execute(select(MfgLineRow).join(MfgGroupRow, MfgGroupRow.id == MfgLineRow.group_id).where(
                 MfgGroupRow.kind == "aeration", MfgLineRow.active.is_(True)).order_by(MfgLineRow.code)).scalars()]
    return {"chambers": chambers, "aeration": {"positions": sum(r["positions"] for r in rooms), "rooms": rooms}}


def get_load(ctx: AppContext, load_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _record(s, repo.get_row(s, MfgSterLoadRow, load_id, what="Sterilisation load"))


# ---------------------------------------------------------------- plan (S1)

def _local_start(d: date, tz: Any) -> datetime:
    return datetime.combine(d, time(0), tz).astimezone(UTC)


def plan_in(s: Session, actor: str, body: Any) -> dict[str, Any]:
    from ....mfg.tz import plant_tz
    from .m8mrp import published_rate_run

    st = settings_of(s)
    p = plant_row(s)
    tz = plant_tz(p) if p is not None else UTC
    d0 = (body.from_date if body is not None and body.from_date else today(s))
    days = body.days if body is not None else st.rate_horizon_days
    d1 = d0 + timedelta(days=days)
    off = int(datetime.combine(d0, time(12), tz).utcoffset().total_seconds() // 60)
    cq = select(MfgLineRow).where(MfgLineRow.active.is_(True), MfgLineRow.planning == "sterilisation")
    if body is not None and body.chamber_line_ids:
        cq = cq.where(MfgLineRow.id.in_(body.chamber_line_ids))
    chamber_rows = list(s.execute(cq.order_by(MfgLineRow.code)).scalars())
    chambers = [Chamber(c.id, c.code, int(c.chamber_pallets or 0), float(c.cycle_hours or 0))
                for c in chamber_rows if c.chamber_pallets and c.cycle_hours]
    if not chambers:
        raise ApiError(422, "MFG_STER_NO_CHAMBER", "There is no sterilisation chamber (a line with planning "
                       "sterilisation, chamber pallets and cycle hours).", {})
    rooms = [AerationRoom(r.id, r.code, int(r.chamber_pallets or 0)) for r in s.execute(
        select(MfgLineRow).join(MfgGroupRow, MfgGroupRow.id == MfgLineRow.group_id).where(
            MfgGroupRow.kind == "aeration", MfgLineRow.active.is_(True)).order_by(MfgLineRow.code)).scalars()
        if r.chamber_pallets]
    plan_rows = {r.item_id: r for r in s.execute(select(MfgItemPlanningRow).where(
        MfgItemPlanningRow.ster_cycle_code.is_not(None))).scalars()}
    pallet = {i: q for i, q in s.execute(select(MfgItemPackagingRow.item_id, MfgItemPackagingRow.qty_base).where(
        MfgItemPackagingRow.level == "pallet"))}
    # loads in work keep chambers / rooms busy and their members are not planned again
    busy_ch: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    busy_rm: dict[str, list[tuple[datetime, datetime, int]]] = defaultdict(list)
    taken_wo: set[str] = set()
    taken_block: set[str] = set()
    active = list(s.execute(select(MfgSterLoadRow).where(MfgSterLoadRow.status.in_(ACTIVE))).scalars())
    for ld in active:
        busy_ch[ld.chamber_line_id].append((ld.actual_start or ld.planned_start, ld.actual_end or ld.planned_end))
        if ld.aeration_line_id:
            busy_rm[ld.aeration_line_id].append((ld.actual_end or ld.planned_end, ld.aeration_end, ld.pallets))
    for m in _members(s, [ld.id for ld in active]).values():
        for x in m:
            if x.wo_id:
                taken_wo.add(x.wo_id)
            if x.rate_block_id:
                taken_block.add(x.rate_block_id)
    # WOs already sterilised (released loads) are not planned again; members of a failed load can be re-planned
    # into a new load, which takes over their sterility holds (review 8)
    loaded_wo = set(s.execute(select(MfgSterLoadMemberRow.wo_id).join(
        MfgSterLoadRow, MfgSterLoadRow.id == MfgSterLoadMemberRow.load_id).where(
        MfgSterLoadRow.status == "released", MfgSterLoadMemberRow.wo_id.is_not(None))).scalars())
    cands: list[SterCandidate] = []

    def cand(key: str, item_id: str, qty: float, ready: datetime, **kw: Any) -> None:
        pr = plan_rows[item_id]
        cands.append(SterCandidate(key, item_id, float(qty), ready, pr.ster_cycle_code, pallet.get(item_id),
                                   float(pr.aeration_hours or 0), pr.release_mode, float(pr.release_days or 0), **kw))
    pub = published_rate_run(s)
    if pub is not None and plan_rows:
        for b in s.execute(select(MfgRateBlockRow).where(
                MfgRateBlockRow.run_id == pub.id, MfgRateBlockRow.kind == "production",
                MfgRateBlockRow.item_id.in_(list(plan_rows)), MfgRateBlockRow.wo_id.is_(None),
                MfgRateBlockRow.prod_date >= d0, MfgRateBlockRow.prod_date < d1)).scalars():
            if b.id not in taken_block:
                cand(f"block:{b.id}", b.item_id, b.qty, b.end, rate_block_id=b.id)
    if plan_rows:
        for w in s.execute(select(MfgWorkOrderRow).where(
                MfgWorkOrderRow.item_id.in_(list(plan_rows)),
                MfgWorkOrderRow.status.in_(("planned", "released", "in_progress", "completed")),
                MfgWorkOrderRow.due_date >= d0, MfgWorkOrderRow.due_date < d1)).scalars():
            if w.id in taken_wo or w.id in loaded_wo:
                continue
            ready = w.completed_at if w.status == "completed" and w.completed_at else _local_start(w.due_date, tz)
            if w.rate_run_id is not None:                          # repetitive WO: ready at its block's end
                end = s.execute(select(func.max(MfgRateBlockRow.end)).where(MfgRateBlockRow.wo_id == w.id)).scalar()
                ready = end or ready
            cand(f"wo:{w.id}", w.item_id, float(w.qty), ready, wo_id=w.id)
    res = LOADS.plan(cands, chambers, rooms, max_wait_hours=st.ster_max_wait_hours, busy_chambers=busy_ch,
                     busy_rooms=busy_rm, tz_offset_minutes=off)
    if not res.validator["ok"]:
        raise ApiError(409, "STER_PLAN_INVALID", "The sterilisation plan failed validation.", res.validator)
    old = list(s.execute(select(MfgSterLoadRow.id).where(MfgSterLoadRow.status == "planned")).scalars())
    if old:
        s.execute(delete(MfgSterLoadRow).where(MfgSterLoadRow.id.in_(old)))
    now = utcnow()
    ids = []
    for ld in res.loads:
        r = MfgSterLoadRow(id=new_id("stl_"), number=next_number(s, "SL", MfgSterLoadRow),
                           run_id=pub.id if pub is not None else None, chamber_line_id=ld.chamber_id,
                           aeration_line_id=ld.aeration_room_id, cycle_code=ld.cycle_code, status="planned",
                           pallets=ld.pallets, planned_start=ld.start, planned_end=ld.end,
                           aeration_end=ld.aeration_end, release_due=ld.release_due, actual_start=None,
                           actual_end=None, actual_aeration_end=None, batch_load_id=None, release_signature_id=None,
                           ncr_id=None, flags=list(ld.flags), row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        for m in ld.members:
            s.add(MfgSterLoadMemberRow(id=new_id("slm_"), load_id=r.id, wo_id=m.wo_id, rate_block_id=m.rate_block_id,
                                       lot_id=m.lot_id, item_id=m.item_id, qty=m.qty, pallets=float(m.pallets)))
            if m.wo_id:                                  # held received lots: planned release date for MRP
                _set_planned_release(s, m.wo_id, ld.release_due)
        ids.append(r.id)
    s.flush()
    out = {"loads": len(res.loads), "pallets": sum(ld.pallets for ld in res.loads), "skipped": res.skipped,
           "warnings": res.warnings, "load_ids": ids}
    audit(s, "ster_plan", None, "plan", {"loads": out["loads"], "replaced": len(old), "skipped": len(res.skipped)})
    return out


def _set_planned_release(s: Session, wo_id: str, due: date) -> None:
    from ..db_models_m7 import MfgLotHoldRow

    lots = [x for x in s.execute(select(MfgInvTransactionRow.lot_id).where(
        MfgInvTransactionRow.wo_id == wo_id, MfgInvTransactionRow.txn_type == "wo_receipt",
        MfgInvTransactionRow.lot_id.is_not(None))).scalars()]
    if lots:
        for h in s.execute(select(MfgLotHoldRow).where(MfgLotHoldRow.lot_id.in_(lots),
                                                       MfgLotHoldRow.source == "sterility",
                                                       MfgLotHoldRow.released_at.is_(None))).scalars():
            h.planned_release = due


def plan(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        return plan_in(s, a.user_id, body)


def plan_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        return plan_in(s, info.get("owner") or "usr_local", None)


# ---------------------------------------------------------------- floor states (S4-S5)

def _get(s: Session, load_id: str, if_match: str | None) -> MfgSterLoadRow:
    r = repo.get_row(s, MfgSterLoadRow, load_id, what="Sterilisation load", lock=True)
    if if_match is not None:
        check_version(r, if_match)
    return r


def _move(s: Session, r: MfgSterLoadRow, to: str, reason: str | None = None) -> None:
    if to not in LOAD_FLOW.get(r.status, ()):
        raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status.replace('_', ' ')} load cannot become "
                       f"{to.replace('_', ' ')}.", {"status": r.status, "to": to})
    before = r.status
    r.status = to
    r.row_version += 1
    r.updated_at = utcnow()
    audit(s, "ster_load", r.id, to, {"from": before, "number": r.number}, reason=reason)


def load(ctx: AppContext, a: Any, load_id: str, if_match: str | None) -> dict[str, Any]:
    from ..db_models_m4 import MfgBatchLoadMemberRow, MfgBatchLoadRow, MfgWoOperationRow
    from . import floor as FLR

    with write_tx(ctx) as (s, _):
        r = _get(s, load_id, if_match)
        ms = _members(s, [r.id])[r.id]
        missing = [m.id for m in ms if not m.wo_id]
        if missing:
            raise ApiError(409, "STER_MEMBER_NO_WO", "Every member needs a work order before loading (publish the "
                           "rate plan first).", {"members": missing})
        _move(s, r, "loaded")
        ch = s.get(MfgLineRow, r.chamber_line_id)
        now = utcnow()
        bl = MfgBatchLoadRow(id=new_id("bld_"), line_id=ch.id, status="open", started_at=None, ended_at=None,
                             aps_run_id=None, actor_id=a.user_id, row_version=1, created_at=now, updated_at=now)
        s.add(bl)
        s.flush()
        for m in ms:
            w = s.get(MfgWorkOrderRow, m.wo_id)
            ops = FLR.ensure_rows(s, w) if w is not None else []
            op = next((o for o in ops if o.group_id == ch.group_id), ops[-1] if ops else None)
            if op is not None and isinstance(op, MfgWoOperationRow):
                s.add(MfgBatchLoadMemberRow(id=new_id("blm_"), load_id=bl.id, wo_operation_id=op.id, qty=m.qty))
        r.batch_load_id = bl.id
        s.flush()
        audit(s, "batch_load", bl.id, "create", {"line": ch.code, "ster_load": r.number})
        return _record(s, r)


def _lots_of(s: Session, m: MfgSterLoadMemberRow) -> list[str]:
    if m.lot_id:
        return [m.lot_id]
    if not m.wo_id:
        return []
    return sorted({x for x in s.execute(select(MfgInvTransactionRow.lot_id).where(
        MfgInvTransactionRow.wo_id == m.wo_id, MfgInvTransactionRow.txn_type == "wo_receipt",
        MfgInvTransactionRow.lot_id.is_not(None))).scalars()})


def adopt_hold(s: Session, r: MfgSterLoadRow, lot: str, item: str, actor: str) -> Any:
    """The lot's open sterility hold (placed at receipt, `source_id` None, or left by a failed load) is taken over by
    this load; without one a hold is placed."""
    from ..db_models_m7 import MfgLotHoldRow
    from .qa_holds import place

    h = s.execute(select(MfgLotHoldRow).where(MfgLotHoldRow.lot_id == lot, MfgLotHoldRow.source == "sterility",
                                              MfgLotHoldRow.released_at.is_(None)).with_for_update()).scalars().first()
    if h is None:
        h = place(s, source="sterility", reason=f"Sterility release pending ({r.number})", actor=actor, lot_id=lot,
                  source_id=r.id, item_id=item)
    elif h.source_id != r.id:
        before = h.source_id
        h.source_id, h.reason = r.id, f"Sterility release pending ({r.number})"
        h.row_version += 1
        h.updated_at = utcnow()
        audit(s, "hold", h.id, "reassign", {"from_source_id": before, "to_source_id": r.id, "load": r.number})
    h.planned_release = r.release_due
    return h


def on_receipt(s: Session, posting: Any) -> int:
    """Review 1: a `wo_receipt` lot of an item with a sterilisation cycle is held (`sterility`, no load yet) from
    the moment it is received until its load is released."""
    from ..db_models_m2 import MfgInvTransactionRow
    from .qa_holds import place

    rows = s.execute(select(MfgInvTransactionRow.lot_id, MfgInvTransactionRow.item_id).join(
        MfgItemPlanningRow, MfgItemPlanningRow.item_id == MfgInvTransactionRow.item_id).where(
        MfgInvTransactionRow.posting_id == posting.id, MfgInvTransactionRow.txn_type == "wo_receipt",
        MfgInvTransactionRow.qty > 0, MfgInvTransactionRow.lot_id.is_not(None),
        MfgItemPlanningRow.ster_cycle_code.is_not(None))).all()
    for lot, item in sorted(set(rows)):
        place(s, source="sterility", reason="Awaiting sterilisation", actor=posting.actor_id, lot_id=lot,
              item_id=item)
    return len(rows)


def _cycle_complete(s: Session, r: MfgSterLoadRow, actor: str) -> None:
    from ....mfg.tz import plant_tz
    from .trace import _edge, _insert

    p = plant_row(s)
    tz = plant_tz(p) if p is not None else UTC
    end = r.actual_end or utcnow()
    lots: list[tuple[str, str]] = []
    for m in _members(s, [r.id])[r.id]:
        ids = _lots_of(s, m)
        if ids and not m.lot_id:
            m.lot_id = ids[0]
        for lot in ids:
            lots.append((lot, m.item_id))
    rel_days = (r.release_due - r.aeration_end.astimezone(tz).date()).days
    planned = (end + (r.aeration_end - r.planned_end)).astimezone(tz).date() + timedelta(days=max(rel_days, 0))
    r.release_due = planned                             # from the actual cycle end
    for lot, item in sorted(set(lots)):
        adopt_hold(s, r, lot, item, actor)
    rows = []
    for lot, item in sorted(set(lots)):
        rows.append(_edge(r.owner_id, f"ster:{r.id}:in:{lot}", "lot", lot, item, "ster_load", r.id, None, None,
                          "exact", end))
        rows.append(_edge(r.owner_id, f"ster:{r.id}:out:{lot}", "ster_load", r.id, None, "lot", lot, item, None,
                          "exact", end))
    if rows:
        _insert(s, rows)
    s.flush()


def advance(ctx: AppContext, a: Any, load_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        r = _get(s, load_id, if_match)
        now = utcnow()
        at = body.at or now
        if at > now + timedelta(minutes=5):
            raise ApiError(422, "STER_TIME_INVALID", "The time cannot be in the future.", {"at": at.isoformat()})
        prev = {"aerating": r.actual_start, "awaiting_release": r.actual_end}.get(body.to)
        if prev is not None and at < prev:
            raise ApiError(422, "STER_TIME_INVALID", "The time is before the previous step.",
                           {"at": at.isoformat(), "previous": prev.isoformat()})
        if body.to == "awaiting_release" and r.actual_end is not None:
            done = r.actual_end + (r.aeration_end - r.planned_end)
            if at < done - timedelta(minutes=1):
                raise ApiError(409, "STER_AERATION_INCOMPLETE", "Aeration is not complete yet.",
                               {"aeration_until": done.isoformat()})
        _move(s, r, body.to)
        if body.to == "cycling":
            r.actual_start = at
        elif body.to == "aerating":
            r.actual_end = at
            _cycle_complete(s, r, a.user_id)
        elif body.to == "awaiting_release":
            r.actual_aeration_end = at
        s.flush()
        return _record(s, r)


def _hold_rows(s: Session, r: MfgSterLoadRow) -> list[Any]:
    from ..db_models_m7 import MfgLotHoldRow

    return list(s.execute(select(MfgLotHoldRow).where(MfgLotHoldRow.source == "sterility",
                                                      MfgLotHoldRow.source_id == r.id,
                                                      MfgLotHoldRow.released_at.is_(None))).scalars())


def release(ctx: AppContext, a: Any, load_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    from . import esig
    from .qa_holds import release_source

    with read_tx(ctx) as s:
        r = repo.get_row(s, MfgSterLoadRow, load_id, what="Sterilisation load")
        if r.status != "awaiting_release":
            raise ApiError(409, "MFG_INVALID_STATE", "Only a load awaiting release can be released.",
                           {"status": r.status})
    auth = esig.authenticate(ctx, a, "ster_load", "release", body.signature)
    with write_tx(ctx) as (s, _):
        r = _get(s, load_id, if_match)
        if r.status != "awaiting_release":
            raise ApiError(409, "MFG_INVALID_STATE", "Only a load awaiting release can be released.",
                           {"status": r.status})
        from .m8common import today as _today

        if _today(s) < r.release_due and not body.early_release_reason:
            raise ApiError(409, "STER_RELEASE_TOO_EARLY", f"The planned release date is {r.release_due.isoformat()}; "
                           "an early release needs a reason.", {"release_due": r.release_due.isoformat()})
        out = esig.sign(s, a, auth, "ster_load", r.id, "release", body.signature)
        if out.pending is not None:
            return out.pending
        sig_id = out.signature_ids[-1] if out.signature_ids else None
        n = release_source(s, "sterility", r.id, a.user_id, body.note or f"Sterility released ({r.number})", sig_id)
        sig_reason = (body.signature.comment if body.signature and body.signature.comment else None)
        _move(s, r, "released", body.early_release_reason or sig_reason or f"Signed sterility release {r.number}")
        r.release_signature_id = sig_id
        audit(s, "ster_load", r.id, "release_holds", {"holds": n, "signature_id": sig_id,
                                                      "early_release_reason": body.early_release_reason},
              reason=body.early_release_reason)
        s.flush()
        return _record(s, r)


def fail(ctx: AppContext, a: Any, load_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    from .qa_ncr import _new

    with write_tx(ctx) as (s, _):
        r = _get(s, load_id, if_match)
        if r.status not in ("cycling", "aerating", "awaiting_release"):
            raise ApiError(409, "MFG_INVALID_STATE", "Only a load in its cycle, aeration or release wait can fail.",
                           {"status": r.status})
        if r.status == "cycling":
            r.actual_end = r.actual_end or utcnow()
            _cycle_complete(s, r, a.user_id)            # the lots are held whatever the stage
        ms = _members(s, [r.id])[r.id]
        lots = sorted({(lot, m.item_id) for m in ms for lot in _lots_of(s, m)})
        codes = {lt.id: lt.lot_code for lt in s.execute(select(MfgLotRow).where(
            MfgLotRow.id.in_([x for x, _i in lots]))).scalars()} if lots else {}
        first = ms[0] if ms else None
        ncr = _new(s, title=f"Sterilisation load {r.number} failed"[:200], source="internal", severity="critical",
                   author=a.user_id, place="stock", qty=sum(m.qty for m in ms),
                   item_id=first.item_id if first else None, lot_id=lots[0][0] if lots else None,
                   wo_id=first.wo_id if first else None,
                   description=f"{body.reason}\n\nCo-sterilised lots: " +
                               ", ".join(codes.get(x, x) for x, _i in lots))
        r.ncr_id = ncr.id
        from .qa_common import add_link

        for lot, _i in lots:                                   # review 8: every lot linked to the NCR
            add_link(s, "ncr", ncr.id, "lot", lot, a.user_id)
        _move(s, r, "failed", body.reason)
        audit(s, "ster_load", r.id, "fail_reason", {"reason": body.reason, "ncr": ncr.number, "lots": len(lots)},
              # (reason also on the failed transition)
              reason=body.reason)
        s.flush()
        return _record(s, r)


def release_dates(s: Session) -> dict[str, date]:
    """WO id -> planned release date of its (not cancelled / failed) sterilisation load (MRP pass 2 avail)."""
    out: dict[str, date] = {}
    for wid, due in s.execute(select(MfgSterLoadMemberRow.wo_id, MfgSterLoadRow.release_due).join(
            MfgSterLoadRow, MfgSterLoadRow.id == MfgSterLoadMemberRow.load_id).where(
            MfgSterLoadMemberRow.wo_id.is_not(None), MfgSterLoadRow.status.not_in(("cancelled", "failed",
                                                                                    "released")))):
        out[wid] = max(out.get(wid, due), due)
    return out



__getattr__ = m8_examples.module_getattr(__name__)
