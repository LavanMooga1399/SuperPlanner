"""Kavach M4 sample additions (M4-DESIGN 14), applied by the sample load after the M1-M3 import:

- plant WO receipt location `FG`, backflush location `LS-SMT` (also the SMT lines' line-side location);
- history (the 10 working days before min(anchor, today), deterministic):
  * three closed history WOs of KV-PCB-CPU (10 each) run through all eleven operations with floor events: SMT
    overruns (x1.3), 1 of 30 units scrapped at ICT (FPY ~0.97), two rework loops at FCT, serials captured at ICT;
    their output and the stock their backflush took are booked out again (net-zero stock, so the M2 / M3 sample
    results are unchanged);
  * downtime: one 5 h SMT-2 breakdown in the window, two older SMT-2 breakdowns (MTBF), one planned BI-1
    maintenance;
  * a history PO of KV-IC-FPGA-V1 at SUP-SEMI-1 with six schedules received 0/7/14/7/10/3 days late (the
    supplier's lateness history for the risk run), received stock booked out again;
  * two closed history demand orders shipped from history receipts, one of them late (OTD < 100%).
The master flags (backflush passives, serial capture, batch lines) are in `mfg/samples/kavach_m4.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....mfg.model_m2 import (IssueMiscLine, IssueMiscPosting, PoReceiptLine, PoReceiptPosting, WorkOrderInput)
from ....mfg.model_m4 import FloorEventInput
from ...db import new_id, utcnow
from ..db_models import MfgItemRow, MfgLineRow, MfgPlantRow
from ..db_models_m2 import (MfgInvBalanceRow, MfgLocationRow, MfgLotRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                            MfgSupplierRow,
                            MfgPurchaseScheduleRow, MfgWorkOrderRow)
from ..db_models_m4 import MfgDowntimeRow, MfgWoOperationRow

HISTORY_ITEM = "KV-PCB-CPU"
HISTORY_WOS = 3
HISTORY_QTY = 10
LATENESS = (0, 7, 14, 7, 10, 3)


def _tz(s: Session) -> Any:
    from ....mfg.tz import plant_tz

    return plant_tz(s.execute(select(MfgPlantRow)).scalars().first())


def _workdays_before(d: date, n: int) -> list[date]:
    out, x = [], d
    while len(out) < n:
        x -= timedelta(days=1)
        if x.weekday() < 6:
            out.append(x)
    return sorted(out)


def apply(s: Session, anchor: date) -> dict[str, Any]:
    tz = _tz(s)
    base = min(anchor, utcnow().astimezone(tz).date())
    locs = {x.code: x for x in s.execute(select(MfgLocationRow)).scalars()}
    plant = s.execute(select(MfgPlantRow)).scalars().first()
    plant.wo_receipt_location_id = locs["FG"].id
    lines = {x.code: x for x in s.execute(select(MfgLineRow)).scalars()}
    s.flush()
    days = _workdays_before(base, 10)
    out = {"downtime": _downtime(s, lines, days, tz), "lateness": _po_history(s, locs, days, tz)}
    # history first without a backflush location (the history's passives are not taken from today's stock)
    out["work_orders"] = _wo_history(s, locs, lines, days, tz)
    plant.backflush_location_id = locs["LS-SMT"].id
    for code in ("SMT-1", "SMT-2", "SMT-3"):
        lines[code].location_id = locs["LS-SMT"].id
    s.flush()
    return out


def _at(d: date, hh: int, mm: int, tz: Any) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=tz).astimezone(UTC)


def _downtime(s: Session, lines: dict[str, Any], days: list[date], tz: Any) -> int:
    now = utcnow()
    rows = [("SMT-2", days[3], 9, 5.0, "breakdown", False, "Reflow oven fan"),
            ("SMT-2", days[0] - timedelta(days=35), 14, 2.0, "breakdown", False, "Feeder jam"),
            ("SMT-2", days[0] - timedelta(days=20), 10, 3.0, "breakdown", False, "Conveyor drive"),
            ("BI-1", days[6], 7, 4.0, "maintenance", True, "Rack calibration")]
    for code, d, hh, hours, kind, planned, reason in rows:
        st = _at(d, hh, 0, tz)
        s.add(MfgDowntimeRow(id=new_id("dtm_"), line_id=lines[code].id, kind=kind, planned=planned, start_at=st,
                             end_at=st + timedelta(hours=hours), expected_end_at=None, reason=reason, note="Sample",
                             reported_by=None, closed_by=None, idempotency_key=None, row_version=1, created_at=now,
                             updated_at=now))
    s.flush()
    return len(rows)


def _book_out(s: Session, item_id: str, loc_id: str, qty: float, d: date, note: str) -> None:
    """Issue `qty` of the item at the location back out (FEFO lots) so the history leaves stock unchanged."""
    from .inventory import post_in_session

    if qty <= 1e-9:
        return
    lot_ids = [b.lot_id for b in s.execute(select(MfgInvBalanceRow).where(
        MfgInvBalanceRow.item_id == item_id, MfgInvBalanceRow.location_id == loc_id,
        MfgInvBalanceRow.qty_on_hand > 1e-9).order_by(MfgInvBalanceRow.lot_key)).scalars()]
    code = None
    if lot_ids and lot_ids[-1]:
        lot = s.get(MfgLotRow, lot_ids[-1])
        code = lot.lot_code if lot is not None else None
    post_in_session(s, IssueMiscPosting.model_construct(
        type="issue_misc", txn_date=None, note=note, reason_code="SAMPLE",
        lines=[IssueMiscLine.model_construct(item_id=item_id, location_id=loc_id, qty=qty, lot_code=code)]),
        system=True, txn_date=d, note_audit=False)


def _po_history(s: Session, locs: dict[str, Any], days: list[date], tz: Any) -> int:
    from .inventory import post_in_session

    it = s.execute(select(MfgItemRow).where(MfgItemRow.part_number == "KV-IC-FPGA-V1")).scalars().first()
    sup = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.code == "SUP-SEMI-1")).scalars().first()
    if it is None or sup is None:
        return 0
    now = utcnow()
    doc = MfgPurchaseDocRow(id=new_id("pdc_"), doc_type="po", number="PO-KV-H001", status="open",
                            supplier_id=sup.id, currency="INR", order_date=days[0] - timedelta(days=120),
                            note="History (M4 sample)", source="manual", source_run_no=None, submitted_at=None,
                            submitted_by=None, approved_at=None, approved_by=None, rejected_reason="",
                            external_ref=None, idempotency_key=None, row_version=1, created_at=now, updated_at=now)
    s.add(doc)
    s.flush()
    ln = MfgPurchaseLineRow(id=new_id("pln_"), doc_id=doc.id, line_no=10, item_id=it.id, unit_price=None,
                            status="open", source_pr_line_id=None, note="", row_version=1, created_at=now,
                            updated_at=now)
    s.add(ln)
    s.flush()
    loc = next((x for x in locs.values() if x.receipt_default), locs["GOODS-IN"])
    n = 0
    scheds = []
    for k, _late in enumerate(LATENESS):
        dock = days[0] - timedelta(days=95 - 14 * k)
        sc = MfgPurchaseScheduleRow(id=new_id("psc_"), line_id=ln.id, seq=k + 1, requested_date=dock,
                                    confirmed_date=None, qty=2.0, received_qty=0.0, closed=False, row_version=1,
                                    created_at=now, updated_at=now)
        s.add(sc)
        scheds.append(sc)
    s.flush()
    for k, (late, sc) in enumerate(zip(LATENESS, scheds)):
        dock = sc.requested_date
        rd = min(dock + timedelta(days=late), days[-1])
        post_in_session(s, PoReceiptPosting.model_construct(
            type="po_receipt", txn_date=None, note="History receipt", reason_code=None,
            lines=[PoReceiptLine.model_construct(schedule_id=sc.id, location_id=loc.id, qty=2.0,
                                                 lot_code=f"H{k + 1:02d}" if it.lot_controlled else None,
                                                 expires_on=None, supplier_lot="", unit_cost=None)]),
            system=True, txn_date=rd, note_audit=False)
        _book_out(s, it.id, loc.id, 2.0, rd, "History consumption (sample)")
        n += 1
    s.flush()
    return n


def _wo_history(s: Session, locs: dict[str, Any], lines: dict[str, Any], days: list[date], tz: Any) -> int:
    from ... import db as _db  # noqa: F401
    from .. import repo
    from .floor import apply_event, eligible_lines, release_to_floor, wo_rows
    from .workorders import new_wo

    it = s.execute(select(MfgItemRow).where(MfgItemRow.part_number == HISTORY_ITEM)).scalars().first()
    if it is None:
        return 0
    ds = repo.load_dataset(s)
    made = 0
    serial = 0
    for k in range(HISTORY_WOS):
        d0 = days[3 * k]
        w, _w = new_wo(s, ds, WorkOrderInput(number=f"WO-KV-H{k + 1:02d}", item_id=it.id, qty=HISTORY_QTY,
                                             due_date=days[min(len(days) - 1, 3 * k + 2)], start_date=d0,
                                             priority=4, note="History (M4 sample)"))
        w.status, w.released_at = "released", _at(d0, 6, 0, tz)
        release_to_floor(s, w, "Sample history", _at(d0, 6, 0, tz))
        t = _at(d0, 8, 0, tz)
        for r in wo_rows(s, w.id):
            el = eligible_lines(s, r.group_id, it)
            if not el:
                continue
            ln = next((x for x in el if x.code == "SMT-1"), el[0]) if r.group_id else el[0]
            rows = {x.id: x for x in wo_rows(s, w.id)}
            avail = _available(s, w, r)
            n = 0

            def ev(et: str, at: datetime, **kw: Any) -> None:
                nonlocal n
                n += 1
                apply_event(s, FloorEventInput(client_event_id=f"sample-{w.number}-{r.seq}-{n}",
                                               wo_operation_id=r.id, event_type=et, event_at=at, **kw), None,
                            now=utcnow())
            ev("start", t, line_id=ln.id)
            minutes = 30 + 4 * HISTORY_QTY * (1.3 if r.name.upper().startswith("SMT") or "SMT" in r.name else 1.0)
            end = t + timedelta(minutes=minutes)
            good, scrap = avail, 0.0
            serials = None
            if r.seq == 100:                       # ICT: 1 of 30 boards scrapped; serials captured
                scrap = 1.0 if k == 1 else 0.0
                good = avail - scrap
                serials = {"produced": [f"CPU-H{serial + i + 1:04d}" for i in range(int(good))]}
                serial += int(good)
            if r.seq == 110 and k < 2:             # FCT: one board reworked at FCT itself (two loops)
                ev("report", t + timedelta(minutes=minutes / 2), qty_good=0, qty_rework=1, rework_to_seq=110,
                   reason_code="RETEST")
                ev("complete", end, qty_good=_available(s, w, r))
            else:
                ev("complete", end, qty_good=good, qty_scrap=scrap,
                   reason_code="TEST_FAIL" if scrap else None, **({"serials": serials} if serials else {}))
            t = end + timedelta(minutes=20)
            del rows
        made += 1
        s.flush()
        s.refresh(w)
        for r in wo_rows(s, w.id):               # history: no pending backflush left behind
            if (r.effects or {}).get("backflush"):
                r.effects = {**r.effects, "backflush": {}}
        # the output leaves again: shipped to a history demand order (the second one late), or booked out
        due = days[min(len(days) - 1, 3 * k + 2)]
        if k < 2:
            _ship(s, it, locs["FG"], w.qty_completed, f"DO-KV-H{k + 1:02d}", due,
                  due if k == 0 else min(due + timedelta(days=3), days[-1]))
        else:
            _book_out(s, it.id, locs["FG"].id, w.qty_completed, due, "History consumption (sample)")
        w.status, w.closed_at = ("closed", utcnow()) if w.status == "completed" else (w.status, w.closed_at)
    s.flush()
    return made


def _ship(s: Session, it: MfgItemRow, loc: Any, qty: float, number: str, due: date, on: date) -> None:
    from ....mfg.model_m2 import ShipLine, ShipPosting
    from ..db_models_m2 import MfgDemandLineRow, MfgDemandOrderRow
    from .inventory import post_in_session

    now = utcnow()
    o = MfgDemandOrderRow(id=new_id("dmo_"), number=number, demand_type="customer", customer="History customer",
                          program=None, priority=4, status="open", note="History (M4 sample)", external_ref=None,
                          row_version=1, created_at=now, updated_at=now)
    s.add(o)
    s.flush()
    dl = MfgDemandLineRow(id=new_id("dml_"), order_id=o.id, line_no=1, item_id=it.id, qty=qty, due_date=due,
                          shipped_qty=0.0, serial_from=None, serial_to=None, priority=None, note="", row_version=1,
                          created_at=now, updated_at=now)
    s.add(dl)
    s.flush()
    post_in_session(s, ShipPosting.model_construct(
        type="ship", txn_date=None, note="History shipment", reason_code=None,
        lines=[ShipLine.model_construct(demand_line_id=dl.id, location_id=loc.id, qty=qty, lot_code=None)]),
        system=True, txn_date=on, note_audit=False)


def _available(s: Session, w: MfgWorkOrderRow, r: MfgWoOperationRow) -> float:
    from .floor import _chain, wo_rows

    return _chain(wo_rows(s, w.id))[r.seq].qty_available
