"""`ApsSnapshot` from a dataset with `txn` (M3-DESIGN 6.1): shared by the database loader (`repo_m3`) and the pure
paths (samples, tests). Work orders `planned` / `released` / `in_progress` with open quantities and their progress
markers; free nettable stock per item; open PO/PR schedules (live fallback for unpegged components, 6.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..model_m2 import EPS, NETTABLE_NOW_KINDS
from ..tz import plant_tz
from .model import ApsComponent, ApsSnapshot, MrpPegView, PublishedView, SupplySnap, WoSnap

WO_STATUSES = ("planned", "released", "in_progress")
PO_OPEN = ("draft", "open", "partially_received")
PR_OPEN = ("draft", "submitted", "approved")


def wo_routing_id(ds: Any, item_id: str, start: date, serial: int | None, routing_id: str | None) -> str | None:
    """The WO's routing (M2 3.7); a WO without one (imported) uses the primary routing effective at its start."""
    if routing_id and routing_id in ds.routings:
        return routing_id
    from ..routing import primary_routing

    rt = primary_routing(ds, item_id, start, serial)
    return rt.id if rt is not None else None


def round_up_minute(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC)
    if dt.second or dt.microsecond:
        dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return dt


def snapshot_from_dataset(ds: Any, as_of: datetime, mrp: MrpPegView | None,
                          published: PublishedView | None = None, done: dict[str, set[int]] | None = None,
                          **kw: Any) -> ApsSnapshot:
    t = ds.txn
    done = done or {}
    wos: list[WoSnap] = []
    if t is not None:
        for w in sorted(t.work_orders.values(), key=lambda w: (w.number, w.id)):
            if w.status not in WO_STATUSES:
                continue
            comps = tuple(ApsComponent(c.id, c.item_id, max(0.0, c.required_qty - c.issued_qty), c.operation_seq)
                          for c in sorted(w.components, key=lambda c: c.id))
            wos.append(WoSnap(id=w.id, number=w.number, status=w.status, item_id=w.item_id,
                              qty=max(0.0, w.qty - w.qty_completed), due_date=w.due_date, start_date=w.start_date,
                              priority=w.priority,
                              routing_id=wo_routing_id(ds, w.item_id, w.start_date, w.serial_from, w.routing_id),
                              serial_from=w.serial_from,
                              components=comps, done_seqs=frozenset(done.get(w.id, ()))))
    stock: dict[str, float] = {}
    supply: list[SupplySnap] = []
    if t is not None:
        locs = {x.id: x for x in ds.locations.values()}
        lots = t.lots
        today = as_of.astimezone(plant_tz(ds.plant)).date()
        for b in t.balances.values():
            loc = locs.get(b.location_id)
            if loc is None or not loc.active or loc.kind not in NETTABLE_NOW_KINDS:
                continue
            lot = lots.get(b.lot_id) if b.lot_id else None
            if lot is not None and (lot.hold or (lot.expires_on is not None and lot.expires_on <= today)):
                continue
            free = b.qty_on_hand - b.qty_reserved
            if free > EPS:
                stock[b.item_id] = stock.get(b.item_id, 0.0) + free
        items = ds.items
        for d in t.purchase_docs.values():
            if (d.doc_type == "po" and d.status not in PO_OPEN) or (d.doc_type == "pr" and d.status not in PR_OPEN):
                continue
            for ln in d.lines:
                if ln.status != "open":
                    continue
                rd = items[ln.item_id].receiving_days if ln.item_id in items else 0
                for sc in ln.schedules:
                    q = sc.qty - sc.received_qty
                    if sc.closed or q <= EPS:
                        continue
                    dock = sc.confirmed_date or sc.requested_date
                    supply.append(SupplySnap(kind=f"{d.doc_type}_schedule", ref_id=sc.id,
                                             label=f"{d.number}/{ln.line_no}/{sc.seq}", item_id=ln.item_id, qty=q,
                                             available_date=max(dock, today) + timedelta(days=rd)))
    supply.sort(key=lambda s: (s.item_id, s.available_date, s.ref_id))
    return ApsSnapshot(as_of=round_up_minute(as_of), tz=plant_tz(ds.plant), dataset=ds, work_orders=wos, mrp=mrp,
                       stock_now=dict(sorted(stock.items())), open_supply=supply, published=published, **kw)


def sample_snapshot(sample_id: str, anchor: date | None = None, *, at: str = "09:00",
                    mrp: bool = True) -> ApsSnapshot:
    """Pure APS snapshot of a sample (tests, performance): the M2 opening state at `anchor`, one MRP run as of
    `anchor`, as_of = anchor at local `at`, the sample's operation progress."""
    from .. import samples
    from ..dataset import mrp_inputs
    from ..mrp import MrpParams, MrpSnapshot, run_mrp
    from .pegview import peg_view_of_result

    anchor = anchor or samples.DEFAULT_ANCHOR
    ds = samples.mrp_state(sample_id, anchor)
    view = None
    if mrp:
        r = run_mrp(MrpSnapshot(as_of=anchor, dataset=ds, **mrp_inputs(ds, anchor)), MrpParams())
        view = peg_view_of_result("mrr_pure", 1, r, ds)
    h, mi = (int(x) for x in at.split(":"))
    tz = plant_tz(ds.plant)
    as_of = datetime(anchor.year, anchor.month, anchor.day, h, mi, tzinfo=tz)
    by_no = {w.number: w.id for w in (ds.txn.work_orders.values() if ds.txn else ())}
    done = {by_no[n]: set(seqs) for n, seqs in samples.sample_progress(sample_id).items() if n in by_no}
    return snapshot_from_dataset(ds, as_of, view, None, done)


__all__ = ["round_up_minute", "sample_snapshot", "snapshot_from_dataset"]
