"""Tiny builder for oracle plants (hand vectors of M2-DESIGN 8.15, randomized plants, API set-up scripts).

Ids are valid M1 `EntityId`s (`<prefix>_<32 hex>`), derived from names, so the same plant can be pushed into the
product (pure snapshot or API) and compared object by object.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from .model import (OBalance, OBom, OBomLine, ODemand, OItem, OItemSupplier, OLine, OOp, OParams, OPlant,
                    OReservation, ORouting, OSchedule, OSupplier, OWoComponent, OWorkOrder)

AS_OF = date(2026, 11, 2)       # Monday (8.15)


def eid(prefix: str, *key: Any) -> str:
    return f"{prefix}_{hashlib.md5('|'.join(map(str, key)).encode()).hexdigest()}"


def d(s: str) -> date:
    """'11-20' -> 2026-11-20, '01-31' -> 2027-01-31 (relative to the 8.15 as_of year), or ISO."""
    if len(s) == 5:
        m, day = int(s[:2]), int(s[3:])
        return date(2026 if m >= 10 else 2027, m, day)
    return date.fromisoformat(s)


class PB:
    def __init__(self, as_of: date = AS_OF, tag: str = "p", **params: Any):
        self.tag = tag
        self.plant = OPlant(params=OParams(as_of=as_of, **params))
        self.group_id = eid("wcg", tag, "G1")
        self.plant.lines.append(OLine(id=eid("lin", tag, "L1"), group_id=self.group_id))
        self._n: dict[str, int] = {}
        self.locations: dict[str, tuple[str, str]] = {}   # code -> (id, kind)
        self.location("STORES", "stores")

    def _next(self, k: str) -> int:
        self._n[k] = self._n.get(k, 0) + 1
        return self._n[k]

    # ---------------------------------------------------------------- master
    def location(self, code: str, kind: str) -> str:
        lid = eid("loc", self.tag, code)
        self.locations[code] = (lid, kind)
        return lid

    def item(self, pn: str, make_buy: str, **kw: Any) -> OItem:
        it = OItem(id=eid("itm", self.tag, pn), part_number=pn, make_buy=make_buy, **kw)
        self.plant.items[it.id] = it
        return it

    def buy(self, pn: str, lt: int = 0, **kw: Any) -> OItem:
        return self.item(pn, "buy", lead_time_days=lt, **kw)

    def make(self, pn: str, lt: int | None = None, **kw: Any) -> OItem:
        return self.item(pn, "make", lead_time_days=lt, **kw)

    def phantom(self, pn: str, **kw: Any) -> OItem:
        return self.item(pn, "phantom", **kw)

    def bom(self, parent: OItem, lines: list[tuple[Any, ...]], *, version: int = 1, serial: tuple[int, int] | None
            = None, eff_from: date | None = None, eff_to: date | None = None, status: str = "released") -> OBom:
        """lines: (child, qty_per[, {scrap, op, alt_group, alt_priority, uom, find}])"""
        bid = eid("bom", self.tag, parent.part_number, version)
        out = []
        for i, spec in enumerate(lines):
            child, qty = spec[0], spec[1]
            opt = spec[2] if len(spec) > 2 else {}
            out.append(OBomLine(id=eid("bml", self.tag, parent.part_number, version, i), find_number=opt.get(
                "find", str(10 * (i + 1))), child_id=child.id, qty_per=qty, uom=opt.get("uom", child.uom),
                scrap_pct=opt.get("scrap", 0.0), alt_group=opt.get("alt_group"),
                alt_priority=opt.get("alt_priority", 1), operation_seq=opt.get("op")))
        b = OBom(id=bid, item_id=parent.id, lines=out, status=status, version=version,
                 serial_from=serial[0] if serial else None, serial_to=serial[1] if serial else None,
                 effective_from=eff_from, effective_to=eff_to)
        self.plant.boms.append(b)
        return b

    def routing(self, item: OItem, ops: list[dict[str, Any]], *, version: int = 1,
                serial: tuple[int, int] | None = None, priority: int = 1) -> ORouting:
        rid = eid("rtg", self.tag, item.part_number, version, priority)
        r = ORouting(id=rid, item_id=item.id, version=version, priority=priority,
                     serial_from=serial[0] if serial else None, serial_to=serial[1] if serial else None,
                     ops=[OOp(group_id=o.pop("group_id", self.group_id), **o) for o in [dict(x) for x in ops]])
        self.plant.routings.append(r)
        return r

    def simple_routing(self, item: OItem) -> ORouting:
        """One operation with zero time (in-use make items need a routing for Gate 1)."""
        return self.routing(item, [{"seq": 10}])

    def supplier(self, code: str, lt: int | None = None, active: bool = True) -> OSupplier:
        s = OSupplier(id=eid("sup", self.tag, code), code=code, lead_time_days=lt, active=active)
        self.plant.suppliers[s.id] = s
        return s

    def item_supplier(self, item: OItem, sup: OSupplier, **kw: Any) -> OItemSupplier:
        row = OItemSupplier(id=eid("isu", self.tag, item.part_number, sup.code), item_id=item.id,
                            supplier_id=sup.id, **kw)
        self.plant.item_suppliers.append(row)
        return row

    # ---------------------------------------------------------------- transactions
    def stock(self, item: OItem, qty: float, *, loc: str = "STORES", lot: str | None = None,
              expires: date | None = None, hold: bool = False, reserved: float = 0.0,
              last_receipt: date | None = None) -> OBalance:
        lid, kind = self.locations[loc]
        b = OBalance(id=eid("bal", self.tag, item.part_number, loc, lot or ""), item_id=item.id, location_id=lid,
                     location_kind=kind, qty_on_hand=qty, qty_reserved=reserved,
                     lot_id=eid("lot", self.tag, item.part_number, lot) if lot else None, lot_code=lot,
                     expires_on=expires, hold=hold, last_receipt_on=last_receipt)
        self.plant.balances.append(b)
        return b

    def po(self, item: OItem, schedules: list[tuple[Any, ...]], *, doc_type: str = "po", status: str | None = None,
           number: str | None = None, supplier: OSupplier | None = None) -> list[OSchedule]:
        """schedules: (requested_date, qty[, confirmed_date])"""
        n = self._next(doc_type)
        number = number or f"{doc_type.upper()}-{self.tag}-{n:04d}"
        doc_id = eid("pdc", self.tag, number)
        line_id = eid("pln", self.tag, number, 10)
        out = []
        for i, sc in enumerate(schedules, start=1):
            s = OSchedule(doc_type=doc_type, doc_id=doc_id, number=number, doc_status=status or (
                "open" if doc_type == "po" else "draft"), line_id=line_id, line_no=10,
                schedule_id=eid("psc", self.tag, number, i), seq=i, item_id=item.id, open_qty=sc[1],
                requested_date=sc[0], confirmed_date=sc[2] if len(sc) > 2 else None,
                supplier_id=supplier.id if supplier else None)
            self.plant.schedules.append(s)
            out.append(s)
        return out

    def pr(self, item: OItem, schedules: list[tuple[Any, ...]], **kw: Any) -> list[OSchedule]:
        return self.po(item, schedules, doc_type="pr", **kw)

    def demand(self, item: OItem, qty: float, due: date, *, priority: int = 5, serial: tuple[int, int] | None = None,
               number: str | None = None, line_no: int = 10, program: str | None = None,
               demand_type: str = "customer") -> ODemand:
        number = number or f"DO-{self.tag}-{self._next('do'):03d}"
        dm = ODemand(order_id=eid("dmo", self.tag, number), number=number,
                     line_id=eid("dml", self.tag, number, line_no), line_no=line_no, item_id=item.id, open_qty=qty,
                     due_date=due, priority=priority, program=program, demand_type=demand_type,
                     serial_from=serial[0] if serial else None, serial_to=serial[1] if serial else None)
        self.plant.demand.append(dm)
        return dm

    def wo(self, item: OItem, qty: float, start: date, due: date, *, status: str = "released",
           components: list[tuple[OItem, float]] = (), number: str | None = None, priority: int = 5,
           serial: tuple[int, int] | None = None) -> OWorkOrder:
        number = number or f"WO-{self.tag}-{self._next('wo'):04d}"
        wid = eid("wko", self.tag, number)
        comps = [OWoComponent(id=eid("woc", self.tag, number, i), item_id=c.id, open_qty=q)
                 for i, (c, q) in enumerate(components)]
        w = OWorkOrder(id=wid, number=number, status=status, item_id=item.id, open_qty=qty, start_date=start,
                       due_date=due, priority=priority, components=comps,
                       serial_from=serial[0] if serial else None, serial_to=serial[1] if serial else None)
        self.plant.work_orders.append(w)
        return w

    def reserve(self, comp: OWoComponent, bal: OBalance, qty: float) -> OReservation:
        rv = OReservation(wo_component_id=comp.id, balance_id=bal.id, qty=qty)
        self.plant.reservations.append(rv)
        bal.qty_reserved += qty
        return rv

    def holiday(self, day: date) -> None:
        self.plant.holidays = frozenset(set(self.plant.holidays) | {day})

    def build(self) -> OPlant:
        return self.plant


def days(n: int) -> timedelta:
    return timedelta(days=n)
