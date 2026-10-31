"""Inventory ledger (M2-DESIGN 4, 12.3 #97-105): postings (all types), reversal, idempotency, balances, ledger,
lots and the per-item stock view.

A posting is one transaction without the plant lock. Lock order (4.5): document headers (purchase docs, demand
orders, work orders; sorted, FOR NO KEY UPDATE) -> children (schedules, demand lines, WO components; FOR UPDATE) ->
number series -> lots -> balances (key order, FOR UPDATE) -> reservations. The pure `mfg.inventory` planner decides
everything; this module loads, locks, applies and audits. Balances are never edited directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....mfg import inventory as INV
from ....mfg import purchasing as PUR
from ....mfg import workorders as WOR
from ....mfg import demand as DEM
from ....mfg.model_m2 import EPS, NETTABLE_NOW_KINDS, LotUpdate
from ....mfg.purchasing import RuleError
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.locks import is_unique_violation
from ...db.ownership import current_owner
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import repo, repo_m2
from ..db_models import MfgItemRow
from ..db_models_m2 import (MfgDemandLineRow, MfgDemandOrderRow, MfgInvBalanceRow, MfgInvPostingRow,
                            MfgInvReservationRow, MfgInvTransactionRow, MfgLocationRow, MfgLotRow,
                            MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow, MfgWoComponentRow,
                            MfgWorkOrderRow)
from .common import audit, check_version, ilike, read_tx, touch, write_tx
from .m2util import (actor_id, actor_ref, iref, items, locations, lotref, lots, lref, page, plant, r6,
                     request_hash, rule_error, run_tx, today, user_names, validation)

DOC_LABEL = {"po": "PO", "pr": "PR"}


# ---------------------------------------------------------------- records


def _nettable(kind: str, hold: bool, expires_on: date | None, d: date) -> bool:
    if kind in NETTABLE_NOW_KINDS or kind == "inspection":
        return not hold and (expires_on is None or expires_on > d)
    return False


def balance_rows(s: Session, rows: list[MfgInvBalanceRow], d: date) -> list[dict[str, Any]]:
    its = items(s, [r.item_id for r in rows])
    locs = locations(s, [r.location_id for r in rows])
    lt = lots(s, [r.lot_id for r in rows if r.lot_id])
    out = []
    for r in rows:
        it, lc, lo = its.get(r.item_id), locs.get(r.location_id), lt.get(r.lot_id or "")
        cost = it.standard_cost if it is not None else None
        out.append({"id": r.id, "item": iref(it, r.item_id), "location": lref(lc, r.location_id), "lot": lotref(lo),
                    "qty_on_hand": r6(r.qty_on_hand), "qty_reserved": r6(r.qty_reserved),
                    "qty_available": r6(r.qty_on_hand - r.qty_reserved),
                    "nettable": _nettable(lc.kind if lc else "quarantine", lo.hold if lo else False,
                                          lo.expires_on if lo else None, d),
                    "last_receipt_on": r.last_receipt_on,
                    "value": r6(r.qty_on_hand * cost) if cost is not None else None,
                    "updated_at": as_utc(r.updated_at)})
    return out


def _doc_refs(s: Session, txns: list[MfgInvTransactionRow]) -> dict[str, dict[str, Any]]:
    """txn id -> DocRef (3.4) for transactions linked to a schedule, WO or demand line (<= 5 statements)."""
    out: dict[str, dict[str, Any]] = {}
    sids = sorted({t.schedule_id for t in txns if t.schedule_id})
    if sids:
        rows = s.execute(select(MfgPurchaseScheduleRow.id, MfgPurchaseScheduleRow.seq, MfgPurchaseLineRow.line_no,
                                MfgPurchaseDocRow.id, MfgPurchaseDocRow.number, MfgPurchaseDocRow.doc_type)
                         .join(MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id)
                         .join(MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)
                         .where(MfgPurchaseScheduleRow.id.in_(sids))).all()
        sref = {r[0]: {"type": r[5], "id": r[3], "number": r[4], "line_no": r[2], "schedule_seq": r[1],
                       "label": f"{r[4]} / {r[2]} / {r[1]}"} for r in rows}
        for t in txns:
            if t.schedule_id in sref:
                out[t.id] = sref[t.schedule_id]
    wids = sorted({t.wo_id for t in txns if t.wo_id and t.id not in out})
    if wids:
        wref = {r[0]: r[1] for r in s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.number)
                                              .where(MfgWorkOrderRow.id.in_(wids))).all()}
        for t in txns:
            if t.wo_id in wref:
                out[t.id] = {"type": "wo", "id": t.wo_id, "number": wref[t.wo_id], "line_no": None,
                             "schedule_seq": None, "label": wref[t.wo_id]}
    dids = sorted({t.demand_line_id for t in txns if t.demand_line_id})
    if dids:
        rows = s.execute(select(MfgDemandLineRow.id, MfgDemandLineRow.line_no, MfgDemandOrderRow.id,
                                MfgDemandOrderRow.number)
                         .join(MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id)
                         .where(MfgDemandLineRow.id.in_(dids))).all()
        dref = {r[0]: {"type": "demand", "id": r[2], "number": r[3], "line_no": r[1], "schedule_seq": None,
                       "label": f"{r[3]} / {r[1]}"} for r in rows}
        for t in txns:
            if t.demand_line_id in dref:
                out[t.id] = dref[t.demand_line_id]
    return out


def transaction_rows(s: Session, txns: list[MfgInvTransactionRow], numbers: dict[str, str] | None = None
                     ) -> list[dict[str, Any]]:
    its = items(s, [t.item_id for t in txns])
    locs = locations(s, [t.location_id for t in txns])
    lt = lots(s, [t.lot_id for t in txns if t.lot_id])
    names = user_names(s, [t.actor_id for t in txns])
    refs = _doc_refs(s, txns)
    if numbers is None:
        pids = sorted({t.posting_id for t in txns})
        numbers = {r[0]: r[1] for r in s.execute(select(MfgInvPostingRow.id, MfgInvPostingRow.number)
                                                 .where(MfgInvPostingRow.id.in_(pids))).all()} if pids else {}
    return [{"id": t.id, "seq": int(t.seq), "posting_id": t.posting_id, "posting_number": numbers.get(t.posting_id, ""),
             "line_no": t.line_no, "txn_type": t.txn_type, "txn_date": t.txn_date,
             "item": iref(its.get(t.item_id), t.item_id), "location": lref(locs.get(t.location_id), t.location_id),
             "lot": lotref(lt.get(t.lot_id or "")), "qty": r6(t.qty), "balance_after": r6(t.balance_after),
             "unit_cost": t.unit_cost, "ref": refs.get(t.id), "actor": actor_ref(names, t.actor_id),
             "created_at": as_utc(t.created_at)} for t in txns]


def posting_record(s: Session, p: MfgInvPostingRow, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == p.id)
                          .order_by(MfgInvTransactionRow.seq)).scalars())
    rev_of = None
    if p.reversal_of_id:
        n = s.execute(select(MfgInvPostingRow.number).where(MfgInvPostingRow.id == p.reversal_of_id)).scalar()
        rev_of = {"id": p.reversal_of_id, "number": n or ""}
    rb = s.execute(select(MfgInvPostingRow.id, MfgInvPostingRow.number)
                   .where(MfgInvPostingRow.reversal_of_id == p.id)).first()
    names = user_names(s, [p.actor_id])
    return {"id": p.id, "number": p.number, "type": p.type, "txn_date": p.txn_date, "note": p.note,
            "reason_code": p.reason_code, "actor": actor_ref(names, p.actor_id), "created_at": as_utc(p.created_at),
            "reversal_of": rev_of, "reversed_by": {"id": rb[0], "number": rb[1]} if rb else None,
            "lines": transaction_rows(s, txns, {p.id: p.number}), "warnings": warnings or []}


# ---------------------------------------------------------------- context loading (locks in 4.5 order)


class _Loaded:
    def __init__(self) -> None:
        self.docs: dict[str, MfgPurchaseDocRow] = {}
        self.lines: dict[str, MfgPurchaseLineRow] = {}
        self.schedules: dict[str, MfgPurchaseScheduleRow] = {}
        self.orders: dict[str, MfgDemandOrderRow] = {}
        self.dlines: dict[str, MfgDemandLineRow] = {}
        self.wos: dict[str, MfgWorkOrderRow] = {}
        self.comps: dict[str, MfgWoComponentRow] = {}
        self.balances: dict[tuple[str, str, str], MfgInvBalanceRow] = {}
        self.lots: dict[tuple[str, str], MfgLotRow] = {}
        self.res: dict[str, MfgInvReservationRow] = {}


def _lock_documents(s: Session, schedule_ids: Iterable[str], demand_line_ids: Iterable[str],
                    component_ids: Iterable[str], wo_ids: Iterable[str]) -> _Loaded:
    L = _Loaded()
    sids, dids, cids, wids = (sorted(set(x)) for x in (schedule_ids, demand_line_ids, component_ids, wo_ids))
    doc_ids: set[str] = set()
    if sids:
        doc_ids = {r[0] for r in s.execute(select(MfgPurchaseLineRow.doc_id)
                                           .join(MfgPurchaseScheduleRow,
                                                 MfgPurchaseScheduleRow.line_id == MfgPurchaseLineRow.id)
                                           .where(MfgPurchaseScheduleRow.id.in_(sids))).all()}
    order_ids: set[str] = set()
    if dids:
        order_ids = {r[0] for r in s.execute(select(MfgDemandLineRow.order_id)
                                             .where(MfgDemandLineRow.id.in_(dids))).all()}
    wo_all = set(wids)
    if cids:
        wo_all |= {r[0] for r in s.execute(select(MfgWoComponentRow.wo_id)
                                           .where(MfgWoComponentRow.id.in_(cids))).all()}
    for r in repo_m2.lock_docs(s, MfgPurchaseDocRow, doc_ids):
        L.docs[r.id] = r
    for r in repo_m2.lock_docs(s, MfgDemandOrderRow, order_ids):
        L.orders[r.id] = r
    for r in repo_m2.lock_docs(s, MfgWorkOrderRow, wo_all):
        L.wos[r.id] = r
    if L.docs:
        for r in s.execute(select(MfgPurchaseLineRow).where(MfgPurchaseLineRow.doc_id.in_(sorted(L.docs)))
                           .execution_options(populate_existing=True)).scalars():
            L.lines[r.id] = r
        for r in repo_m2.lock_children_of(s, MfgPurchaseScheduleRow, "line_id", L.lines):
            L.schedules[r.id] = r
    if L.orders:
        for r in repo_m2.lock_children_of(s, MfgDemandLineRow, "order_id", L.orders):
            L.dlines[r.id] = r
    if L.wos:
        for r in repo_m2.lock_children_of(s, MfgWoComponentRow, "wo_id", L.wos):
            L.comps[r.id] = r
    return L


def _context(s: Session, L: _Loaded, item_ids: set[str], pairs: set[tuple[str, str]], d: date, *,
             system: bool = False) -> INV.PostingContext:
    p = plant(s)
    for sc in L.schedules.values():
        item_ids.add(L.lines[sc.line_id].item_id)
    for c in L.comps.values():
        item_ids.add(c.item_id)
    for w in L.wos.values():
        item_ids.add(w.item_id)
    for dl in L.dlines.values():
        item_ids.add(dl.item_id)
    its = items(s, item_ids)
    locs = locations(s)
    lot_keys_items = sorted(i for i in item_ids if i in its and its[i].lot_controlled)   # no lots, no lot locks
    for chunk_start in range(0, len(lot_keys_items), 2000):
        chunk = lot_keys_items[chunk_start:chunk_start + 2000]
        for r in s.execute(select(MfgLotRow).where(MfgLotRow.item_id.in_(chunk))
                           .order_by(MfgLotRow.item_id, MfgLotRow.lot_code).with_for_update()
                           .execution_options(populate_existing=True)).scalars():
            L.lots[(r.item_id, r.lot_code)] = r
    # m8 / 4.5: every balance this posting may touch - the lines' pairs and the balances the components'
    # reservations sit on - is locked in one key-ordered pass before any reservation row
    comp_ids = sorted(L.comps)
    L.balances = repo_m2.lock_balances_at(s, set(pairs) | repo_m2.reservation_pairs(s, comp_ids))
    bal_ids = sorted(b.id for b in L.balances.values())
    conds = []
    if comp_ids:
        conds.append(MfgInvReservationRow.wo_component_id.in_(comp_ids))
    if bal_ids:
        conds.append(MfgInvReservationRow.balance_id.in_(bal_ids))
    if conds:
        for r in s.execute(select(MfgInvReservationRow).where(or_(*conds)).order_by(MfgInvReservationRow.id)
                           .with_for_update().execution_options(populate_existing=True)).scalars():
            L.res[r.id] = r
    by_bal_id = {b.id: k for k, b in L.balances.items()}
    # a reservation made on another balance between the candidate read and the locks (rare): lock it too
    missing = {r.balance_id for r in L.res.values() if r.balance_id not in by_bal_id}
    if missing:
        extra = s.execute(select(MfgInvBalanceRow).where(MfgInvBalanceRow.id.in_(sorted(missing)))
                          .order_by(MfgInvBalanceRow.item_id, MfgInvBalanceRow.location_id, MfgInvBalanceRow.lot_key)
                          .with_for_update().execution_options(populate_existing=True)).scalars()
        for b in extra:
            L.balances[(b.item_id, b.location_id, b.lot_key)] = b
            by_bal_id[b.id] = (b.item_id, b.location_id, b.lot_key)
    ctx = INV.PostingContext(
        today=today(s),
        items={i: INV.ItemInfo(r.id, r.part_number, r.uom, r.lot_controlled, r.shelf_life_days, r.standard_cost,
                               r.make_buy) for i, r in its.items()},
        locations={i: INV.LocInfo(r.id, r.code, r.kind, r.active, r.receipt_default, r.name) for i, r in locs.items()},
        lots={k: INV.LotInfo(r.item_id, r.lot_code, r.id, r.expires_on, r.hold, r.received_on, r.supplier_lot)
              for k, r in L.lots.items()},
        balances={k: INV.BalInfo(b.item_id, b.location_id, b.lot_key, b.qty_on_hand, b.qty_reserved, b.id,
                                 b.last_receipt_on) for k, b in L.balances.items()},
        reservations=[INV.ResInfo(r.id, r.wo_component_id, by_bal_id[r.balance_id], r.qty,
                                  (as_utc(r.created_at), r.id)) for r in L.res.values() if r.balance_id in by_bal_id],
        over_receipt_pct=float(p.over_receipt_pct), system=system)
    for sid, sc in L.schedules.items():
        ln = L.lines[sc.line_id]
        doc = L.docs[ln.doc_id]
        ctx.schedules[sid] = INV.SchedInfo(sc.id, sc.seq, sc.qty, sc.received_qty, sc.closed, ln.id, ln.line_no,
                                           ln.item_id, ln.unit_price, doc.id, doc.number, doc.doc_type, doc.status,
                                           ln.status)
    for cid, c in L.comps.items():
        ctx.components[cid] = INV.CompInfo(c.id, c.wo_id, c.item_id, c.required_qty, c.issued_qty)
    for wid, w in L.wos.items():
        ctx.work_orders[wid] = INV.WoInfo(w.id, w.number, w.status, w.item_id, w.qty, w.qty_completed, w.qty_scrapped)
    for did, dl in L.dlines.items():
        o = L.orders[dl.order_id]
        ctx.demand_lines[did] = INV.DemLineInfo(dl.id, o.id, o.number, o.status, dl.line_no, dl.item_id, dl.qty,
                                                dl.shipped_qty)
    del d
    return ctx


def _refs_of(inp: Any) -> tuple[set[str], set[tuple[str, str]], set[str], set[str], set[str], set[str], set[str]]:
    """(item ids, (item, location) pairs known now, location ids, schedule ids, demand line ids, component ids,
    WO ids) of a posting input."""
    item_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    loc_ids: set[str] = set()
    sids: set[str] = set()
    dids: set[str] = set()
    cids: set[str] = set()
    wids: set[str] = set()
    for ln in inp.lines:
        if hasattr(ln, "item_id"):
            item_ids.add(ln.item_id)
        for f in ("location_id", "from_location_id", "to_location_id"):
            v = getattr(ln, f, None)
            if v:
                loc_ids.add(v)
                if hasattr(ln, "item_id"):
                    pairs.add((ln.item_id, v))
        if getattr(ln, "schedule_id", None):
            sids.add(ln.schedule_id)
        if getattr(ln, "demand_line_id", None):
            dids.add(ln.demand_line_id)
        if getattr(ln, "wo_component_id", None):
            cids.add(ln.wo_component_id)
        if getattr(ln, "wo_id", None):
            wids.add(ln.wo_id)
    return item_ids, pairs, loc_ids, sids, dids, cids, wids


def _resolve_pairs(inp: Any, L: _Loaded, pairs: set[tuple[str, str]], s: Session) -> None:
    """Add (item, location) pairs whose item comes from a document line (receipts, issues, shipments)."""
    default_loc = None
    for ln in inp.lines:
        loc = getattr(ln, "location_id", None)
        if getattr(ln, "schedule_id", None) and ln.schedule_id in L.schedules:
            item = L.lines[L.schedules[ln.schedule_id].line_id].item_id
            if loc is None:
                if default_loc is None:
                    default_loc = s.execute(select(MfgLocationRow.id).where(
                        MfgLocationRow.receipt_default.is_(True), MfgLocationRow.active.is_(True))).scalar() or ""
                loc = default_loc
            if loc:
                pairs.add((item, loc))
        elif getattr(ln, "wo_component_id", None) and ln.wo_component_id in L.comps and loc:
            pairs.add((L.comps[ln.wo_component_id].item_id, loc))
        elif getattr(ln, "wo_id", None) and ln.wo_id in L.wos and loc:
            pairs.add((L.wos[ln.wo_id].item_id, loc))
        elif getattr(ln, "demand_line_id", None) and ln.demand_line_id in L.dlines and loc:
            pairs.add((L.dlines[ln.demand_line_id].item_id, loc))


# ---------------------------------------------------------------- apply


def _apply(s: Session, L: _Loaded, plan: INV.PostingPlan, posting: MfgInvPostingRow, actor: str) -> None:
    now = utcnow()
    specs = {(nl.item_id, nl.lot_code): {"expires_on": nl.expires_on, "received_on": nl.received_on,
                                         "supplier_lot": nl.supplier_lot} for nl in plan.new_lots}
    needed_lots = {(t.item_id, t.lot_code) for t in plan.transactions if t.lot_code}
    lot_rows = dict(L.lots)
    missing = {k: specs.get(k, {}) for k in needed_lots if k not in lot_rows}
    if missing:
        lot_rows.update(repo_m2.lock_or_create_lots(s, missing))
    lot_ids = {k: r.id for k, r in lot_rows.items()}
    keys = {t.key for t in plan.transactions}
    new_keys = [k for k in keys if k not in L.balances]
    if new_keys:
        L.balances.update(repo_m2.lock_or_create_balances(s, new_keys, lot_ids))
    rows = []
    for t in plan.transactions:
        b = L.balances[t.key]
        b.qty_on_hand = round(b.qty_on_hand + t.qty, 6)
        if abs(b.qty_on_hand) < EPS:
            b.qty_on_hand = 0.0
        if t.set_last_receipt is not None:
            b.last_receipt_on = max(b.last_receipt_on or t.set_last_receipt, t.set_last_receipt)
        b.updated_at = now
        rows.append(MfgInvTransactionRow(
            id=new_id("txn_"), posting_id=posting.id, line_no=t.line_no, txn_type=t.txn_type,
            txn_date=posting.txn_date, item_id=t.item_id, location_id=t.location_id,
            lot_id=lot_ids.get((t.item_id, t.lot_code)) if t.lot_code else None, qty=t.qty,
            balance_after=b.qty_on_hand, unit_cost=t.unit_cost, scrap_qty=t.scrap_qty, schedule_id=t.schedule_id,
            wo_id=t.wo_id,
            wo_component_id=t.wo_component_id, demand_line_id=t.demand_line_id, actor_id=actor, created_at=now))
    # reservations first (a released reservation lowers qty_reserved before the on-hand check of the row)
    by_id = {b.id: b for b in L.balances.values()}
    for rid, q in sorted(plan.reservation_qty.items()):
        r = L.res[rid]
        b = by_id[r.balance_id]
        b.qty_reserved = round(max(0.0, b.qty_reserved - (r.qty - q)), 6)
        if q <= EPS:
            s.delete(r)
        else:
            r.qty = q
            r.updated_at = now
    s.flush()
    s.add_all(rows)
    s.flush()
    _apply_documents(s, L, plan, now)


def _apply_documents(s: Session, L: _Loaded, plan: INV.PostingPlan, now: Any, *, reversal: bool = False) -> None:
    touched_docs: set[str] = set()
    for sid, dq in plan.schedule_received.items():
        sc = L.schedules[sid]
        sc.received_qty = round(max(0.0, sc.received_qty + dq), 6)
        touch(sc, now)
        touched_docs.add(L.lines[sc.line_id].doc_id)
    for doc_id in sorted(touched_docs):
        doc = L.docs[doc_id]
        scs = [PUR.SchedState(x.qty, x.received_qty, x.closed) for x in L.schedules.values()
               if L.lines[x.line_id].doc_id == doc_id]
        doc.status = PUR.derive_po_status(doc.status, scs)
        touch(doc, now)
    for cid, dq in plan.component_issued.items():
        c = L.comps[cid]
        c.issued_qty = round(max(0.0, c.issued_qty + dq), 6)
        touch(c, now)
    wo_ids = set(plan.wo_completed) | set(plan.wo_scrapped) | plan.wo_touched | \
        {L.comps[c].wo_id for c in plan.component_issued}
    for wid in sorted(wo_ids):
        w = L.wos[wid]
        w.qty_completed = round(max(0.0, w.qty_completed + plan.wo_completed.get(wid, 0.0)), 6)
        w.qty_scrapped = round(max(0.0, w.qty_scrapped + plan.wo_scrapped.get(wid, 0.0)), 6)
        before = w.status
        w.status = WOR.derive_status(w.status, w.qty, w.qty_completed, touched=wid in plan.wo_touched)
        if w.status == "completed" and before != "completed":
            w.completed_at = now
            _release_wo(s, L, w.id, now)
        elif w.status != "completed" and before == "completed":
            w.completed_at = None
        touch(w, now)
    touched_orders: set[str] = set()
    for did, dq in plan.demand_shipped.items():
        dl = L.dlines[did]
        dl.shipped_qty = round(max(0.0, dl.shipped_qty + dq), 6)
        touch(dl, now)
        touched_orders.add(dl.order_id)
    for oid in sorted(touched_orders):
        o = L.orders[oid]
        lines_ = [(x.qty, x.shipped_qty) for x in L.dlines.values() if x.order_id == oid]
        o.status = DEM.reopen_after_reversal(o.status, lines_) if reversal else DEM.derive_status(o.status, lines_)
        touch(o, now)
    s.flush()


def _release_wo(s: Session, L: _Loaded, wo_id: str, now: Any) -> None:
    """Completion releases the WO's remaining reservations (4.1)."""
    comp_ids = [c.id for c in L.comps.values() if c.wo_id == wo_id]
    if not comp_ids:
        return
    release_reservations(s, comp_ids, now)


def release_reservations(s: Session, comp_ids: list[str], now: Any) -> float:
    """Delete the reservations of these components and lower their balances' `qty_reserved`. Lock order (4.5):
    the balances first (key order), then the reservations re-read `FOR UPDATE` (fresh values). Returns the
    released quantity."""
    if not comp_ids:
        return 0.0
    bals, res = repo_m2.lock_reservations_of(s, comp_ids)
    total = 0.0
    for r in res:
        b = bals[r.balance_id]
        b.qty_reserved = round(max(0.0, b.qty_reserved - r.qty), 6)
        b.updated_at = now
        total += r.qty
        s.delete(r)
    s.flush()
    return total


# ---------------------------------------------------------------- post / reverse


def _find_idem(s: Session, key: str) -> MfgInvPostingRow | None:
    return s.execute(select(MfgInvPostingRow).where(MfgInvPostingRow.idempotency_key == key)).scalars().first()


def _replay(s: Session, row: MfgInvPostingRow, h: str) -> dict[str, Any]:
    if row.request_hash != h:
        raise ApiError(409, "INV_IDEMPOTENCY_CONFLICT", "This Idempotency-Key was already used for a different "
                       "posting.", {"posting_id": row.id, "number": row.number})
    return posting_record(s, row)


def post_in_session(s: Session, inp: Any, *, system: bool = False, txn_date: date | None = None,
                    idem: str | None = None, body_hash: str | None = None, note_audit: bool = True
                    ) -> tuple[MfgInvPostingRow, list[dict[str, Any]]]:
    """Plan and apply one posting in the caller's transaction (also used by imports and sample loads, `system`:
    no date/reason limits). Raises `ApiError` on rule errors."""
    item_ids, pairs, _locs, sids, dids, cids, wids = _refs_of(inp)
    L = _lock_documents(s, sids, dids, cids, wids)
    _resolve_pairs(inp, L, pairs, s)
    if txn_date is not None:
        inp = inp.model_copy(update={"txn_date": txn_date})
    # posting numbers come from their own short transaction (4.5, 22.WP-B): no series lock is held here
    number = repo_m2.allocate_number(s, "TXN", repo_m2.number_taken(s, MfgInvPostingRow))
    ctx = _context(s, L, set(item_ids), pairs, today(s), system=system)
    try:
        plan = INV.plan_posting(inp, ctx)
    except RuleError as e:
        raise rule_error(e) from None
    actor = actor_id()
    now = utcnow()
    row = MfgInvPostingRow(id=new_id("pst_"), number=number, type=inp.type, txn_date=plan.txn_date, note=inp.note,
                           reason_code=inp.reason_code or ("COUNT" if inp.type == "count" else None),
                           idempotency_key=idem, request_hash=body_hash, actor_id=actor, reversal_of_id=None,
                           created_at=now)
    s.add(row)
    s.flush()
    _apply(s, L, plan, row, actor)
    if note_audit:
        audit(s, "posting", row.id, "post", {"number": row.number, "type": row.type, "lines": len(plan.transactions),
                                            **({"idempotency_key": idem} if idem else {})})
    return row, plan.warnings


def create_posting(ctx: AppContext, inp: Any, body: Any, idem: str | None) -> tuple[dict[str, Any], bool]:
    """POST /inventory/postings -> (record, replayed)."""
    h = request_hash(body)
    if idem:
        with read_tx(ctx) as s:
            found = _find_idem(s, idem)
            if found is not None:
                return _replay(s, found, h), True

    def fn(s: Session) -> tuple[dict[str, Any], bool]:
        if idem:
            # serialise concurrent retries of one key, then re-check: the second one replays instead of 409
            s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                      {"k": f"mfg-posting:{current_owner()}:{idem}"})
            found = _find_idem(s, idem)
            if found is not None:
                audit(s, "posting", found.id, "replay", {"idempotency_key": idem})
                return _replay(s, found, h), True
        try:
            with s.begin_nested():
                row, warnings = post_in_session(s, inp, idem=idem, body_hash=h if idem else None)
        except IntegrityError as exc:
            if idem and is_unique_violation(exc, "uq_mfg_inv_postings_idem"):
                found = _find_idem(s, idem)
                if found is not None:
                    audit(s, "posting", found.id, "replay", {"idempotency_key": idem})
                    return _replay(s, found, h), True
            raise
        return posting_record(s, row, warnings), False

    return run_tx(ctx, fn)


def reverse_posting(ctx: AppContext, posting_id: str, note: str) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        orig = repo.get_row(s, MfgInvPostingRow, posting_id, what="Posting", lock=True)
        if orig.reversal_of_id is not None:
            raise ApiError(409, "MFG_INVALID_STATE", "A reversal cannot be reversed; post a new transaction instead.",
                           {"status": "reversal", "action": "reverse", "allowed_from": []})
        done = s.execute(select(MfgInvPostingRow.id, MfgInvPostingRow.number)
                         .where(MfgInvPostingRow.reversal_of_id == orig.id)).first()
        if done is not None:
            raise ApiError(409, "INV_ALREADY_REVERSED", f"{orig.number} was reversed already by {done[1]}.",
                           {"reversed_by": {"id": done[0], "number": done[1]}})
        txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == orig.id)
                              .order_by(MfgInvTransactionRow.seq)).scalars())
        L = _lock_documents(s, [t.schedule_id for t in txns if t.schedule_id],
                            [t.demand_line_id for t in txns if t.demand_line_id],
                            [t.wo_component_id for t in txns if t.wo_component_id], [t.wo_id for t in txns if t.wo_id])
        number = repo_m2.allocate_number(s, "TXN", repo_m2.number_taken(s, MfgInvPostingRow))
        lt = lots(s, [t.lot_id for t in txns if t.lot_id])
        pairs = {(t.item_id, t.location_id) for t in txns}
        d = today(s)
        pctx = _context(s, L, {t.item_id for t in txns}, pairs, d)
        original = [INV.OrigTxn(t.line_no, t.txn_type, t.item_id, t.location_id,
                                lt[t.lot_id].lot_code if t.lot_id else None, t.qty, t.unit_cost, t.schedule_id,
                                t.wo_id, t.wo_component_id, t.demand_line_id, t.scrap_qty) for t in txns]
        try:
            plan = INV.plan_reversal(orig.type, original, pctx, d)
        except RuleError as e:
            raise rule_error(e) from None
        actor = actor_id()
        row = MfgInvPostingRow(id=new_id("pst_"), number=number, type=orig.type, txn_date=d,
                               note=note or f"Reversal of {orig.number}", reason_code=orig.reason_code,
                               idempotency_key=None, request_hash=None, actor_id=actor, reversal_of_id=orig.id,
                               created_at=utcnow())
        s.add(row)
        s.flush()
        _apply_reversal(s, L, plan, row, actor)
        audit(s, "posting", row.id, "reverse", {"number": row.number, "reversal_of": orig.number})
        return posting_record(s, row)

    return run_tx(ctx, fn)


def _apply_reversal(s: Session, L: _Loaded, plan: INV.PostingPlan, posting: MfgInvPostingRow, actor: str) -> None:
    now = utcnow()
    keys = {t.key for t in plan.transactions}
    lot_ids = {k: r.id for k, r in L.lots.items()}
    new_keys = [k for k in keys if k not in L.balances]
    if new_keys:
        L.balances.update(repo_m2.lock_or_create_balances(s, new_keys, lot_ids))
    rows = []
    for t in plan.transactions:
        b = L.balances[t.key]
        b.qty_on_hand = round(b.qty_on_hand + t.qty, 6)
        if abs(b.qty_on_hand) < EPS:
            b.qty_on_hand = 0.0
        if b.qty_reserved > b.qty_on_hand + EPS:
            raise ApiError(409, "INV_INSUFFICIENT_STOCK", "The reversal would take reserved stock; release the "
                           "reservations first.", {"item_id": t.item_id, "location_id": t.location_id})
        b.updated_at = now
        rows.append(MfgInvTransactionRow(
            id=new_id("txn_"), posting_id=posting.id, line_no=t.line_no, txn_type=t.txn_type,
            txn_date=posting.txn_date, item_id=t.item_id, location_id=t.location_id,
            lot_id=lot_ids.get((t.item_id, t.lot_code)) if t.lot_code else None, qty=t.qty,
            balance_after=b.qty_on_hand, unit_cost=t.unit_cost, scrap_qty=t.scrap_qty, schedule_id=t.schedule_id,
            wo_id=t.wo_id,
            wo_component_id=t.wo_component_id, demand_line_id=t.demand_line_id, actor_id=actor, created_at=now))
    s.add_all(rows)
    s.flush()
    _apply_documents(s, L, plan, now, reversal=True)


# ---------------------------------------------------------------- reads


def get_posting(ctx: AppContext, posting_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return posting_record(s, repo.get_row(s, MfgInvPostingRow, posting_id, what="Posting"))


def list_postings(ctx: AppContext, *, type_: str | None, d0: date | None, d1: date | None, q: str | None,
                  limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if type_:
        conds.append(MfgInvPostingRow.type == type_)
    if d0:
        conds.append(MfgInvPostingRow.txn_date >= d0)
    if d1:
        conds.append(MfgInvPostingRow.txn_date <= d1)
    if q:
        conds.append(ilike(MfgInvPostingRow.number, q))
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgInvPostingRow).where(*conds)
                              .order_by(MfgInvPostingRow.created_at.desc(), MfgInvPostingRow.id.desc())
                              .limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(MfgInvPostingRow).where(*conds)).scalar() or 0)
        ids = [r.id for r in rows]
        counts = dict(s.execute(select(MfgInvTransactionRow.posting_id, func.count())
                                .where(MfgInvTransactionRow.posting_id.in_(ids))
                                .group_by(MfgInvTransactionRow.posting_id)).all()) if ids else {}
        rev = dict(s.execute(select(MfgInvPostingRow.reversal_of_id, MfgInvPostingRow.number)
                             .where(MfgInvPostingRow.reversal_of_id.in_(ids))).all()) if ids else {}
        names = user_names(s, [r.actor_id for r in rows])
        out = [{"id": r.id, "number": r.number, "type": r.type, "txn_date": r.txn_date, "note": r.note,
                "reason_code": r.reason_code, "actor": actor_ref(names, r.actor_id), "created_at": as_utc(r.created_at),
                "reversal_of_id": r.reversal_of_id, "reversed_by_number": rev.get(r.id),
                "line_count": int(counts.get(r.id, 0))} for r in rows]
        return page(out, total, limit, offset)


def list_transactions(ctx: AppContext, *, item_id: str | None, location_id: str | None, lot_id: str | None,
                      txn_type: str | None, posting_id: str | None, ref_type: str | None, ref_id: str | None,
                      d0: date | None, d1: date | None, limit: int, offset: int) -> dict[str, Any]:
    T = MfgInvTransactionRow
    conds: list[Any] = []
    for col, v in ((T.item_id, item_id), (T.location_id, location_id), (T.lot_id, lot_id), (T.txn_type, txn_type),
                   (T.posting_id, posting_id)):
        if v:
            conds.append(col == v)
    if d0:
        conds.append(T.txn_date >= d0)
    if d1:
        conds.append(T.txn_date <= d1)
    if ref_type or ref_id:
        if not (ref_type and ref_id):
            raise validation(["query", "ref_type"], "ref_type and ref_id go together.")
        if ref_type in ("po", "pr"):
            sub = select(MfgPurchaseScheduleRow.id).join(MfgPurchaseLineRow,
                                                         MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id) \
                .where(MfgPurchaseLineRow.doc_id == ref_id)
            conds.append(T.schedule_id.in_(sub))
        elif ref_type == "wo":
            conds.append(T.wo_id == ref_id)
        elif ref_type == "demand":
            conds.append(T.demand_line_id.in_(select(MfgDemandLineRow.id).where(MfgDemandLineRow.order_id == ref_id)))
        else:
            raise validation(["query", "ref_type"], "ref_type must be po, pr, wo or demand.")
    with read_tx(ctx) as s:
        rows = list(s.execute(select(T).where(*conds).order_by(T.seq.desc()).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(T).where(*conds)).scalar() or 0)
        return page(transaction_rows(s, rows), total, limit, offset)


def list_balances(ctx: AppContext, *, q: str | None, item_id: str | None, location_id: str | None,
                  kind: str | None, nettable: bool | None, lot_id: str | None, only_nonzero: bool, sort: str,
                  limit: int, offset: int) -> dict[str, Any]:
    B = MfgInvBalanceRow
    conds: list[Any] = []
    join_item = q is not None or sort == "part_number"
    if item_id:
        conds.append(B.item_id == item_id)
    if location_id:
        conds.append(B.location_id == location_id)
    if lot_id:
        conds.append(B.lot_id == lot_id)
    if only_nonzero:
        conds.append(B.qty_on_hand > EPS)
    if kind:
        conds.append(B.location_id.in_(select(MfgLocationRow.id).where(MfgLocationRow.kind == kind)))
    if q:
        conds.append(B.item_id.in_(select(MfgItemRow.id).where(ilike(MfgItemRow.part_number, q)
                                                              | ilike(MfgItemRow.description, q))))
    with read_tx(ctx) as s:
        d = today(s)
        if nettable is not None:
            ok_locs = select(MfgLocationRow.id).where(MfgLocationRow.kind.in_(("stores", "line_side", "inspection")))
            ok_lot = or_(B.lot_id.is_(None), B.lot_id.in_(select(MfgLotRow.id).where(
                MfgLotRow.hold.is_(False), or_(MfgLotRow.expires_on.is_(None), MfgLotRow.expires_on > d))))
            cond = and_(B.location_id.in_(ok_locs), ok_lot)
            conds.append(cond if nettable else ~cond)
        stmt = select(B).where(*conds)
        if sort == "location":
            stmt = stmt.join(MfgLocationRow, MfgLocationRow.id == B.location_id) \
                .order_by(MfgLocationRow.code, B.item_id, B.lot_key, B.id)
        elif sort == "-qty":
            stmt = stmt.order_by(B.qty_on_hand.desc(), B.id)
        else:
            stmt = stmt.join(MfgItemRow, MfgItemRow.id == B.item_id).order_by(MfgItemRow.part_number, B.location_id,
                                                                              B.lot_key, B.id)
        del join_item
        rows = list(s.execute(stmt.limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(B).where(*conds)).scalar() or 0)
        extra: dict[str, Any] = {}
        if item_id:
            on, rs = s.execute(select(func.coalesce(func.sum(B.qty_on_hand), 0.0),
                                      func.coalesce(func.sum(B.qty_reserved), 0.0)).where(*conds)).one()
            cost = s.execute(select(MfgItemRow.standard_cost).where(MfgItemRow.id == item_id)).scalar()
            extra["totals"] = {"qty_on_hand": r6(on), "qty_reserved": r6(rs),
                               "value": r6(on * cost) if cost is not None else None}
        return page(balance_rows(s, rows, d), total, limit, offset, **extra)


def item_stock(ctx: AppContext, item_id: str) -> dict[str, Any]:
    """#100: totals by availability class, balances, open supply / demand and the latest run's shortage."""
    with read_tx(ctx) as s:
        it = repo.get_row(s, MfgItemRow, item_id, what="Item")
        d = today(s)
        rows = list(s.execute(select(MfgInvBalanceRow).where(MfgInvBalanceRow.item_id == it.id,
                                                             MfgInvBalanceRow.qty_on_hand > EPS)).scalars())
        bal = balance_rows(s, rows, d)
        tot = {"nettable": 0.0, "inspection": 0.0, "quarantine": 0.0, "reserved": 0.0, "available": 0.0}
        for b in bal:
            k = b["location"].kind
            if k == "quarantine" or not b["nettable"]:
                tot["quarantine"] += b["qty_on_hand"]
            elif k == "inspection":
                tot["inspection"] += b["qty_on_hand"]
            else:
                tot["nettable"] += b["qty_on_hand"]
                tot["available"] += b["qty_available"]
            tot["reserved"] += b["qty_reserved"]
        tot = {k: r6(v) for k, v in tot.items()}
        tot["value"] = r6(sum(b["qty_on_hand"] for b in bal) * it.standard_cost) if it.standard_cost is not None \
            else None
        supply: list[dict[str, Any]] = []
        for sc, ln, doc in s.execute(
                select(MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow)
                .join(MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id)
                .join(MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)
                .where(MfgPurchaseLineRow.item_id == it.id, MfgPurchaseScheduleRow.closed.is_(False))).all():
            oq = PUR.schedule_open_qty(sc.qty, sc.received_qty, sc.closed)
            if PUR.is_supply(doc.doc_type, doc.status, ln.status, oq, sc.closed):
                supply.append({"type": f"{doc.doc_type}_schedule",
                               "ref": {"id": sc.id, "doc_id": doc.id, "label": f"{doc.number} / {ln.line_no} / {sc.seq}"},
                               "date": PUR.available_date(PUR.dock_date(sc.requested_date, sc.confirmed_date),
                                                          it.receiving_days), "qty": r6(oq)})
        for w in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.item_id == it.id, MfgWorkOrderRow.status.in_(
                WOR.SUPPLY_STATUSES))).scalars():
            supply.append({"type": "work_order", "ref": {"id": w.id, "label": w.number}, "date": w.due_date,
                           "qty": r6(WOR.open_qty(w.qty, w.qty_completed))})
        demand: list[dict[str, Any]] = []
        for dl, o in s.execute(select(MfgDemandLineRow, MfgDemandOrderRow)
                               .join(MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id)
                               .where(MfgDemandLineRow.item_id == it.id, MfgDemandOrderRow.status == "open")).all():
            oq = DEM.open_qty(dl.qty, dl.shipped_qty)
            if oq > EPS:
                demand.append({"type": "demand_line", "ref": {"id": dl.id, "order_id": o.id,
                                                              "label": f"{o.number} / {dl.line_no}"},
                               "date": dl.due_date, "qty": r6(oq)})
        for c, w in s.execute(select(MfgWoComponentRow, MfgWorkOrderRow)
                              .join(MfgWorkOrderRow, MfgWorkOrderRow.id == MfgWoComponentRow.wo_id)
                              .where(MfgWoComponentRow.item_id == it.id,
                                     MfgWorkOrderRow.status.in_(WOR.SUPPLY_STATUSES))).all():
            oq = max(0.0, c.required_qty - c.issued_qty)
            if oq > EPS:
                demand.append({"type": "wo_component", "ref": {"id": c.id, "wo_id": w.id, "label": w.number},
                               "date": w.start_date, "qty": r6(oq)})
        supply.sort(key=lambda x: (x["date"], x["ref"]["label"]))
        demand.sort(key=lambda x: (x["date"], x["ref"]["label"]))
        from .mrp import latest_item_shortage

        return {"item": iref(it), "totals": tot, "balances": bal, "open_supply": supply, "open_demand": demand,
                "latest_run": latest_item_shortage(s, it.id)}


# ---------------------------------------------------------------- lots


def lot_record(s: Session, row: MfgLotRow) -> dict[str, Any]:
    on = s.execute(select(func.coalesce(func.sum(MfgInvBalanceRow.qty_on_hand), 0.0))
                   .where(MfgInvBalanceRow.lot_id == row.id)).scalar()
    it = items(s, [row.item_id]).get(row.item_id)
    return {"id": row.id, "item": iref(it, row.item_id), "item_id": row.item_id, "lot_code": row.lot_code,
            "expires_on": row.expires_on, "received_on": row.received_on, "supplier_lot": row.supplier_lot,
            "hold": row.hold, "note": row.note, "on_hand": r6(on or 0.0), "row_version": row.row_version,
            "created_at": as_utc(row.created_at), "updated_at": as_utc(row.updated_at)}


def list_lots(ctx: AppContext, *, item_id: str | None, q: str | None, expiring_before: date | None,
              hold: bool | None, limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if item_id:
        conds.append(MfgLotRow.item_id == item_id)
    if q:
        conds.append(ilike(MfgLotRow.lot_code, q))
    if expiring_before:
        conds.append(MfgLotRow.expires_on < expiring_before)
    if hold is not None:
        conds.append(MfgLotRow.hold.is_(hold))
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgLotRow).where(*conds)
                              .order_by(MfgLotRow.expires_on.asc().nulls_last(), MfgLotRow.lot_code, MfgLotRow.id)
                              .limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(MfgLotRow).where(*conds)).scalar() or 0)
        ids = [r.id for r in rows]
        on = dict(s.execute(select(MfgInvBalanceRow.lot_id, func.sum(MfgInvBalanceRow.qty_on_hand))
                            .where(MfgInvBalanceRow.lot_id.in_(ids)).group_by(MfgInvBalanceRow.lot_id)).all()) \
            if ids else {}
        its = items(s, [r.item_id for r in rows])
        out = [{"id": r.id, "item": iref(its.get(r.item_id), r.item_id), "item_id": r.item_id,
                "lot_code": r.lot_code, "expires_on": r.expires_on, "received_on": r.received_on,
                "supplier_lot": r.supplier_lot, "hold": r.hold, "note": r.note, "on_hand": r6(on.get(r.id) or 0.0),
                "row_version": r.row_version, "created_at": as_utc(r.created_at), "updated_at": as_utc(r.updated_at)}
               for r in rows]
        return page(out, total, limit, offset)


def update_lot(ctx: AppContext, lot_id: str, inp: LotUpdate, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        row = repo.get_row(s, MfgLotRow, lot_id, what="Lot", lock=True)
        check_version(row, if_match)
        row.expires_on, row.supplier_lot, row.hold, row.note = inp.expires_on, inp.supplier_lot, inp.hold, inp.note
        touch(row)
        s.flush()
        audit(s, "lot", row.id, "update", {"version": row.row_version, "hold": row.hold})
        return lot_record(s, row)


def missing_posting(posting_id: str) -> ApiError:  # pragma: no cover - helper for routers
    return not_found("Posting", posting_id)
