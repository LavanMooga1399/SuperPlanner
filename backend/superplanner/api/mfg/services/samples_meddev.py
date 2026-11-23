"""Meddev sample history (applied by the sample load after the import, like `samples_m4` for Kavach):

- plant WO receipt location `FG`, backflush location `STORES` (after the history);
- history on the working days (Mon-Fri) before min(anchor, today), deterministic:
  * a two-level lot genealogy: press WO `WO-MDV-H01` (drip chambers) and extrusion WO `WO-MDV-H02` (IV tubing) consume
    supplier lots of polypropylene / PVC; IV-set WO `WO-MDV-H03` consumes their output lots plus supplier lots of
    solvent and labels, 40 sets are scrapped at the leak test, and the good sets are received into lot `WO-MDV-H03`
    and shipped by lot to two fictional customers (the second shipment two days late, so OTD < 100 %); 960 sets stay
    in finished goods (a recall of the resin lot can quarantine them);
  * press WO `WO-MDV-H04` (10 mL barrels) -> syringe WO `WO-MDV-H05` (with a stopper supplier lot), shipped on time;
  * downtime: a press breakdown in the window plus two older ones (MTBF), an assembly-line stop and planned EtO
    chamber maintenance;
  * a history PO of polypropylene with six schedules received 0/3/6/0/9/2 days late (supplier lateness for the risk
    run); its receipts are booked out again.
Supplier lots received for the history are issued the same day, and the history output is consumed or shipped, so
apart from those 960 IV sets the opening stock of the pure sample (`mfg.samples.mrp_state`) is unchanged.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....mfg.model_m2 import (
    PoReceiptLine,
    PoReceiptPosting,
    ReceiptMiscLine,
    ReceiptMiscPosting,
    ShipLine,
    ShipPosting,
    WoIssueLine,
    WoIssuePosting,
    WorkOrderInput,
)
from ....mfg.model_m4 import FloorEventInput
from ...db import new_id, utcnow
from ..db_models import MfgItemRow, MfgLineRow, MfgPlantRow
from ..db_models_m2 import (
    MfgDemandLineRow,
    MfgDemandOrderRow,
    MfgLocationRow,
    MfgPurchaseDocRow,
    MfgPurchaseLineRow,
    MfgPurchaseScheduleRow,
    MfgSupplierRow,
    MfgWoComponentRow,
    MfgWorkOrderRow,
)
from ..db_models_m4 import MfgDowntimeRow
from .samples_m4 import _at, _available, _book_out, _tz

MARKER = "PO-MDV-H001"
#: sets of lot WO-MDV-H03 left in finished goods (what a recall of the resin lot can still quarantine)
KEPT_SETS = 960.0
LATENESS = (0, 3, 6, 0, 9, 2)
#: supplier lot numbers of the history (as printed on the supplier's certificate)
SUPPLIER_LOTS = {"MDV-RES-PP": "RSN-PP-88412", "MDV-RES-PVC": "RSN-PVC-55107", "MDV-SOLV": "CHM-CYH-2231",
                 "MDV-LBL-UDI": "LBL-77310", "MDV-STP-10": "ELA-ST10-4410"}
PREFERRED_LINE = {"MOULD": "IMM-05", "ASSY": "ASM-04", "PACK": "PKG-01", "STER": "ETO-01", "QC": "QCR-01"}


def _workdays_before(d: date, n: int) -> list[date]:
    out, x = [], d
    while len(out) < n:
        x -= timedelta(days=1)
        if x.weekday() < 5:
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
    out = {"downtime": _downtime(s, lines, days, tz), "lateness": _po_history(s, locs, days)}
    out["work_orders"] = _wo_history(s, locs, days, tz)
    plant.backflush_location_id = locs["STORES"].id
    s.flush()
    return out


def _downtime(s: Session, lines: dict[str, Any], days: list[date], tz: Any) -> int:
    now = utcnow()
    rows = [("IMM-03", days[5], 9, 4.0, "breakdown", False, "Hot-runner heater zone failure"),
            ("IMM-03", days[0] - timedelta(days=33), 14, 2.0, "breakdown", False, "Ejector pin broken"),
            ("IMM-03", days[0] - timedelta(days=18), 10, 3.0, "breakdown", False, "Mould water leak"),
            ("ASM-04", days[3], 15, 1.5, "breakdown", False, "Solvent dispenser blocked"),
            ("ETO-01", days[7], 7, 6.0, "maintenance", True, "Chamber leak-rate test")]
    for code, d, hh, hours, kind, planned, reason in rows:
        st = _at(d, hh, 0, tz)
        s.add(MfgDowntimeRow(id=new_id("dtm_"), line_id=lines[code].id, kind=kind, planned=planned, start_at=st,
                             end_at=st + timedelta(hours=hours), expected_end_at=None, reason=reason, note="Sample",
                             reported_by=None, closed_by=None, idempotency_key=None, row_version=1, created_at=now,
                             updated_at=now))
    s.flush()
    return len(rows)


def _item(s: Session, pn: str) -> MfgItemRow:
    return s.execute(select(MfgItemRow).where(MfgItemRow.part_number == pn)).scalars().one()


def _po_history(s: Session, locs: dict[str, Any], days: list[date]) -> int:
    from .inventory import post_in_session

    it = _item(s, "MDV-RES-PP")
    sup = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.code == "SUP-RESIN")).scalars().one()
    now = utcnow()
    doc = MfgPurchaseDocRow(id=new_id("pdc_"), doc_type="po", number=MARKER, status="open", supplier_id=sup.id,
                            currency="CAD", order_date=days[0] - timedelta(days=120), note="History (sample)",
                            source="manual", source_run_no=None, submitted_at=None, submitted_by=None,
                            approved_at=None, approved_by=None, rejected_reason="", external_ref=None,
                            idempotency_key=None, row_version=1, created_at=now, updated_at=now)
    s.add(doc)
    s.flush()
    ln = MfgPurchaseLineRow(id=new_id("pln_"), doc_id=doc.id, line_no=10, item_id=it.id, unit_price=2.85,
                            status="open", source_pr_line_id=None, note="", row_version=1, created_at=now,
                            updated_at=now)
    s.add(ln)
    s.flush()
    loc = locs["RECEIVING"]
    scheds = []
    for k in range(len(LATENESS)):
        sc = MfgPurchaseScheduleRow(id=new_id("psc_"), line_id=ln.id, seq=k + 1,
                                    requested_date=days[0] - timedelta(days=95 - 14 * k), confirmed_date=None,
                                    qty=500.0, received_qty=0.0, closed=False, row_version=1, created_at=now,
                                    updated_at=now)
        s.add(sc)
        scheds.append(sc)
    s.flush()
    for k, (late, sc) in enumerate(zip(LATENESS, scheds)):
        rd = min(sc.requested_date + timedelta(days=late), days[-1])
        post_in_session(s, PoReceiptPosting.model_construct(
            type="po_receipt", txn_date=None, note="History receipt", reason_code=None,
            lines=[PoReceiptLine.model_construct(schedule_id=sc.id, location_id=loc.id, qty=500.0,
                                                 lot_code=f"PP-H{k + 1:02d}", expires_on=rd + timedelta(days=700),
                                                 supplier_lot=f"RSN-PP-{88300 + k}", unit_cost=None)]),
            system=True, txn_date=rd, note_audit=False)
        _book_out(s, it.id, loc.id, 500.0, rd, "History consumption (sample)")
    s.flush()
    return len(LATENESS)


def _receive_lot(s: Session, it: MfgItemRow, loc: Any, qty: float, d: date, code: str) -> None:
    from .inventory import post_in_session

    post_in_session(s, ReceiptMiscPosting.model_construct(
        type="receipt_misc", txn_date=None, note="History supplier lot (sample)", reason_code="SAMPLE",
        lines=[ReceiptMiscLine.model_construct(item_id=it.id, location_id=loc.id, qty=qty, lot_code=code,
                                               expires_on=d + timedelta(days=it.shelf_life_days or 730),
                                               supplier_lot=SUPPLIER_LOTS.get(it.part_number, ""),
                                               unit_cost=None)]),
        system=True, txn_date=d, note_audit=False)


def _issue(s: Session, w: MfgWorkOrderRow, locs: dict[str, Any], d: date, k: int,
           own_lots: dict[str, str]) -> None:
    """Issue the history WO's lot-controlled components by lot: output lots of earlier history WOs (`own_lots`, part
    -> lot code, from FG) or a supplier lot received the same day (`H<k>-<part>`)."""
    from .inventory import post_in_session

    comps = list(s.execute(select(MfgWoComponentRow, MfgItemRow).join(MfgItemRow, MfgItemRow.id ==
                                                                      MfgWoComponentRow.item_id)
                           .where(MfgWoComponentRow.wo_id == w.id, MfgItemRow.lot_controlled.is_(True))
                           .order_by(MfgItemRow.part_number)).all())
    for c, it in comps:
        qty = float(c.required_qty)
        if qty <= 1e-9:
            continue
        if it.part_number in own_lots:
            loc, code = locs["FG"], own_lots[it.part_number]
        elif it.part_number in SUPPLIER_LOTS:
            loc, code = locs["RECEIVING"], f"H{k:02d}-{it.part_number.removeprefix('MDV-')}"
            _receive_lot(s, it, loc, qty, d, code)
        else:
            continue
        post_in_session(s, WoIssuePosting.model_construct(
            type="wo_issue", txn_date=None, note="History issue (sample)", reason_code=None,
            lines=[WoIssueLine.model_construct(wo_component_id=c.id, location_id=loc.id, qty=qty, lot_code=code,
                                               over_issue=False)]), system=True, txn_date=d, note_audit=False)


def _run(s: Session, ds: Any, number: str, pn: str, qty: float, d0: date, tz: Any, locs: dict[str, Any], k: int,
         own_lots: dict[str, str], scrap: dict[int, tuple[float, str]] | None = None) -> MfgWorkOrderRow:
    from .floor import apply_event, eligible_lines, release_to_floor, wo_rows
    from .workorders import new_wo

    it = _item(s, pn)
    w, _w = new_wo(s, ds, WorkOrderInput(number=number, item_id=it.id, qty=qty, due_date=d0 + timedelta(days=4),
                                         start_date=d0, priority=3, note="History (sample)"))
    w.status, w.released_at = "released", _at(d0, 6, 0, tz)
    release_to_floor(s, w, "Sample history", _at(d0, 6, 0, tz))
    _issue(s, w, locs, d0, k, own_lots)
    t = _at(d0, 6, 30, tz)
    from ..db_models import MfgGroupRow

    for r in wo_rows(s, w.id):
        el = eligible_lines(s, r.group_id, it)
        if not el:
            continue
        grp = s.get(MfgGroupRow, r.group_id)
        want = PREFERRED_LINE.get(grp.code if grp is not None else "")
        ln = next((x for x in el if x.code == want), el[0])
        n = 0

        def ev(et: str, at: datetime, r: Any = r, **kw: Any) -> None:
            nonlocal n
            n += 1
            apply_event(s, FloorEventInput(client_event_id=f"sample-{number}-{r.seq}-{n}", wo_operation_id=r.id,
                                           event_type=et, event_at=at, **kw), None, now=utcnow())

        minutes = 720.0 if (grp is not None and grp.code == "STER") else 150.0 + min(330.0, qty * 0.01)
        ev("start", t, line_id=ln.id)
        end = t + timedelta(minutes=minutes)
        avail = _available(s, w, r)
        sc, reason = (scrap or {}).get(r.seq, (0.0, ""))
        if sc:
            ev("report", t + timedelta(minutes=minutes / 2), qty_good=math.floor(avail / 2), qty_scrap=sc,
               reason_code=reason)
            ev("complete", end, qty_good=_available(s, w, r))
        else:
            ev("complete", end, qty_good=avail)
        t = end + timedelta(minutes=30 if grp is None or grp.code != "STER" else 720)
    s.flush()
    s.refresh(w)
    for r in wo_rows(s, w.id):                  # history: no pending backflush left behind
        if (r.effects or {}).get("backflush"):
            r.effects = {**r.effects, "backflush": {}}
    if w.status == "completed":
        w.status, w.closed_at = "closed", utcnow()
    s.flush()
    return w


def _ship(s: Session, it: MfgItemRow, loc: Any, lot: str, qty: float, number: str, customer: str, due: date,
          on: date) -> None:
    from .inventory import post_in_session

    now = utcnow()
    o = MfgDemandOrderRow(id=new_id("dmo_"), number=number, demand_type="customer", customer=customer,
                          program=None, priority=3, status="open", note="History (sample)", external_ref=None,
                          row_version=1, created_at=now, updated_at=now)
    s.add(o)
    s.flush()
    dl = MfgDemandLineRow(id=new_id("dml_"), order_id=o.id, line_no=10, item_id=it.id, qty=qty, due_date=due,
                          shipped_qty=0.0, serial_from=None, serial_to=None, priority=None, note="", row_version=1,
                          created_at=now, updated_at=now)
    s.add(dl)
    s.flush()
    post_in_session(s, ShipPosting.model_construct(
        type="ship", txn_date=None, note="History shipment", reason_code=None,
        lines=[ShipLine.model_construct(demand_line_id=dl.id, location_id=loc.id, qty=qty, lot_code=lot)]),
        system=True, txn_date=on, note_audit=False)


def _need(ds: Any, parent: str, qty: float, child: str, on: date) -> float:
    from ....mfg.workorders import generate_components

    it = ds.items_by_pn[parent]
    e = generate_components(ds, it.id, qty, on=on, serial=None)
    return float(math.ceil(sum(c.qty for c in e.components if ds.items[c.item_id].part_number == child) - 1e-9))


def _wo_history(s: Session, locs: dict[str, Any], days: list[date], tz: Any) -> int:
    from .. import repo

    ds = repo.load_dataset(s)
    fg = locs["FG"]
    # IV sets: drip chambers and tubing first, then the sets from their lots
    sets = 10000.0
    dch = _need(ds, "MDV-IVS-20", sets, "MDV-DCH", days[0])
    tub = _need(ds, "MDV-IVS-20", sets, "MDV-TUB-IV", days[0])
    w1 = _run(s, ds, "WO-MDV-H01", "MDV-DCH", dch, days[0], tz, locs, 1, {})
    w2 = _run(s, ds, "WO-MDV-H02", "MDV-TUB-IV", tub, days[0], tz, locs, 2, {})
    w3 = _run(s, ds, "WO-MDV-H03", "MDV-IVS-20", sets, days[2], tz, locs, 3,
              {"MDV-DCH": w1.number, "MDV-TUB-IV": w2.number}, scrap={20: (40.0, "LEAK")})
    ivs = _item(s, "MDV-IVS-20")
    good = float(w3.qty_completed)
    _ship(s, ivs, fg, w3.number, 6000.0, "DO-MDV-H01", "Northern regional hospital network (fictional)", days[8],
          days[7])
    _ship(s, ivs, fg, w3.number, good - 6000.0 - KEPT_SETS, "DO-MDV-H02", "US distributor Alpha (fictional)",
          days[7], days[9])
    # 10 mL syringes: barrels from a press WO
    syr = 20000.0
    w4 = _run(s, ds, "WO-MDV-H04", "MDV-BRL-10", _need(ds, "MDV-SYR-10", syr, "MDV-BRL-10", days[0]), days[3], tz, locs,
              4, {})
    w5 = _run(s, ds, "WO-MDV-H05", "MDV-SYR-10", syr, days[4], tz, locs, 5, {"MDV-BRL-10": w4.number})
    _ship(s, _item(s, "MDV-SYR-10"), fg, w5.number, float(w5.qty_completed), "DO-MDV-H03",
          "Provincial health purchasing group East (fictional)", days[9], days[8])
    # anything a history WO made beyond what the next one consumed leaves again (net-zero stock)
    for w in (w1, w2, w4):
        from ..db_models_m2 import MfgInvBalanceRow, MfgLotRow

        rows = s.execute(select(MfgInvBalanceRow).join(MfgLotRow, MfgLotRow.id == MfgInvBalanceRow.lot_id)
                         .where(MfgLotRow.lot_code == w.number, MfgInvBalanceRow.location_id == fg.id,
                                MfgInvBalanceRow.qty_on_hand > 1e-9)).scalars().all()
        for b in rows:
            _book_out(s, b.item_id, fg.id, float(b.qty_on_hand), days[9], "History consumption (sample)")
    s.flush()
    return 5
