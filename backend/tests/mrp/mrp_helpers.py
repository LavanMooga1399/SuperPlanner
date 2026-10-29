"""Scenario builders for the pure MRP tests: master data through the sample `Builder` (bundle -> dataset), then
transactional snapshot rows (`model_m2` snaps) with deterministic ids."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from superplanner.mfg.bundle import bundle_to_dataset
from superplanner.mfg.dataset import MfgDataset
from superplanner.mfg.model_m2 import (BalanceSnap, DemandSnap, ReservationSnap, ScheduleSnap, WoComponentSnap,
                                       WoSnap)
from superplanner.mfg.mrp import MrpParams, MrpSnapshot, run_mrp
from superplanner.mfg.samples.common import Builder, line, op

AS_OF = date(2026, 11, 2)       # Monday


def D(mmdd: str, year: int = 2026) -> date:
    m, d = mmdd.split("-")
    return date(year, int(m), int(d))


def eid(prefix: str, *key: Any) -> str:
    return f"{prefix}_" + hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:32]


class Plant:
    """Master data: one group/line for routings; items, BOMs, routings via the sample Builder."""

    def __init__(self, horizon: int = 180):
        self.b = Builder()
        self.b.plant("MRP test plant", horizon=horizon)
        self.b.group("G", "Stage")
        self.b.line("L1", "G", "Line 1")

    def item(self, pn: str, make_buy: str = "buy", **kw: Any) -> "Plant":
        self.b.item(pn, make_buy, pn, **kw)
        return self

    def bom(self, parent: str, lines: list[tuple], **kw: Any) -> "Plant":
        rows = []
        for i, ln in enumerate(lines):
            child, qty, *rest = ln
            extra = rest[0] if rest else {}
            rows.append(line(10 * (i + 1), child, qty, **extra))
        self.b.bom(parent, rows, **kw)
        return self

    def serial_bom(self, parent: str, lines: list[tuple], serial_from: int, serial_to: int,
                   version: int = 2) -> "Plant":
        self.bom(parent, lines, version=version)
        self.b.b["boms"][-1].update(serial_from=serial_from, serial_to=serial_to)
        return self

    def routing(self, pn: str, ops: list[dict[str, Any]]) -> "Plant":
        self.b.routing(pn, [op(o.pop("seq"), o.pop("name", "Op"), "G", **o) for o in ops])
        return self

    def dataset(self, **plant_fields: Any) -> MfgDataset:
        ds = bundle_to_dataset(self.b.b)
        for k, v in plant_fields.items():
            setattr(ds.plant, k, v)
        for name in ("locations", "suppliers", "item_suppliers"):
            if not hasattr(ds, name):
                setattr(ds, name, {})
        return ds


@dataclass
class Snap:
    ds: MfgDataset
    balances: list[BalanceSnap] = field(default_factory=list)
    reservations: list[ReservationSnap] = field(default_factory=list)
    schedules: list[ScheduleSnap] = field(default_factory=list)
    demand: list[DemandSnap] = field(default_factory=list)
    work_orders: list[WoSnap] = field(default_factory=list)
    lots: dict[str, Any] = field(default_factory=dict)
    holidays: set[date] = field(default_factory=set)

    def iid(self, pn: str) -> str:
        return self.ds.items_by_pn[pn].id

    def stock(self, pn: str, qty: float, *, kind: str = "stores", loc: str = "STORES", lot: str | None = None,
              expires: date | None = None, hold: bool = False, last_receipt: date | None = None,
              reserved: float = 0.0) -> str:
        bid = eid("bal", pn, loc, lot, len(self.balances))
        lot_id = eid("lot", pn, lot) if lot else None
        if lot:
            self.lots[lot_id] = type("Lot", (), {"lot_code": lot, "expires_on": expires, "hold": hold})()
        self.balances.append(BalanceSnap(id=bid, item_id=self.iid(pn), location_id=eid("loc", loc), kind=kind,
                                         lot_id=lot_id, expires_on=expires, hold=hold, qty_on_hand=qty,
                                         qty_reserved=reserved, last_receipt_on=last_receipt))
        return bid

    def schedule(self, pn: str, qty: float, dock: date, *, doc_type: str = "po", number: str = "PO-1",
                 confirmed: date | None = None, line_no: int = 10, seq: int | None = None, status: str | None = None,
                 supplier_id: str | None = None) -> str:
        seq = seq or (1 + sum(1 for s in self.schedules if s.number == number and s.line_no == line_no))
        sid = eid("psc", number, line_no, seq)
        self.schedules.append(ScheduleSnap(
            doc_type=doc_type, doc_id=eid("pdc", number), number=number,
            doc_status=status or ("open" if doc_type == "po" else "submitted"), line_id=eid("pln", number, line_no),
            line_no=line_no, schedule_id=sid, seq=seq, item_id=self.iid(pn), supplier_id=supplier_id, open_qty=qty,
            requested_date=dock, confirmed_date=confirmed))
        return sid

    def dem(self, pn: str, qty: float, due: date, *, priority: int = 5, number: str | None = None,
            line_no: int = 10, serials: tuple[int, int] | None = None, program: str | None = None,
            demand_type: str = "customer") -> str:
        number = number or f"DO-{len(self.demand) + 1:03d}"
        lid = eid("dml", number, line_no)
        self.demand.append(DemandSnap(order_id=eid("dmo", number), number=number, demand_type=demand_type,
                                      customer="", program=program, line_id=lid, line_no=line_no,
                                      item_id=self.iid(pn), open_qty=qty, due_date=due, effective_priority=priority,
                                      serial_from=serials[0] if serials else None,
                                      serial_to=serials[1] if serials else None))
        return lid

    def wo(self, pn: str, qty: float, start: date, due: date, components: list[tuple[str, float]], *,
           status: str = "released", number: str | None = None, priority: int = 5) -> WoSnap:
        number = number or f"WO-{len(self.work_orders) + 1:03d}"
        wid = eid("wko", number)
        comps = tuple(WoComponentSnap(eid("woc", number, i), self.iid(c), q, None)
                      for i, (c, q) in enumerate(components))
        w = WoSnap(id=wid, number=number, status=status, item_id=self.iid(pn), open_qty=qty, start_date=start,
                   due_date=due, priority=priority, serial_from=None, serial_to=None, routing_id=None,
                   components=comps)
        self.work_orders.append(w)
        return w

    def reserve(self, component_id: str, balance_id: str, qty: float) -> None:
        self.reservations.append(ReservationSnap(component_id, balance_id, qty))

    def snapshot(self, as_of: date = AS_OF) -> MrpSnapshot:
        return MrpSnapshot(as_of=as_of, dataset=self.ds, lots=dict(self.lots), balances=list(self.balances),
                           reservations=list(self.reservations), schedules=list(self.schedules),
                           demand=list(self.demand), work_orders=list(self.work_orders),
                           holidays=frozenset(self.holidays))

    def run(self, **params: Any):
        return run_mrp(self.snapshot(), MrpParams(**params))


# ---------------------------------------------------------------- result access


def plan(res, ds: MfgDataset, pn: str):
    return res.item(ds.items_by_pn[pn].id)


def reqs(res, ds, pn: str):
    p = plan(res, ds, pn)
    return p.requirements if p else []


def planned(res, ds, pn: str):
    iid = ds.items_by_pn[pn].id
    return [po for po in res.planned_orders if po.item_id == iid]


def supply(res, ds, pn: str, node: int):
    return next(s for s in plan(res, ds, pn).supplies if s.node == node)


def peg_view(res, ds, pn: str) -> list[list[tuple[str, float, int]]]:
    """Per requirement (node order): [(supply kind/label, qty, late_days)]."""
    p = plan(res, ds, pn)
    sups = {s.node: s for s in p.supplies}
    return [[(sups[pg.supply_node].kind, pg.qty, pg.late_days) for pg in r.pegs] for r in p.requirements]


def codes(res, code: str, *, item: str | None = None, ds=None) -> list:
    out = [e for e in res.exceptions if e.code == code]
    if item is not None:
        out = [e for e in out if e.part_number == item]
    return out


def days(n: int) -> timedelta:
    return timedelta(days=n)
