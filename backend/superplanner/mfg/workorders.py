"""Work-order rules (M2-DESIGN 3.7, 7): status machine, default start date, component generation, hard reservation
planning (FEFO), per-WO kitting and the plant-wide kitting simulation. Pure (no I/O); errors are
`purchasing.RuleError`.

Component generation and manufacturing lead times are the MRP engine's (`mfg.mrp.order_components`,
`mfg.mrp.leadtime.manufacturing_lead_days`, 8.5 / 8.7), so a WO created by hand, by import or by MRP conversion has
exactly the quantities MRP plans with.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .model_m2 import EPS, NETTABLE_NOW_KINDS, WO_STATUSES
from .purchasing import RuleError, invalid_state, readonly

WHAT = "This work order"
ACTIONS: dict[str, tuple[str, ...]] = {
    "release": ("planned",),
    "complete": ("released", "in_progress"),
    "close": ("completed",),
    "cancel": ("planned", "released"),
    "refresh-components": ("planned",),
    "reserve": ("planned", "released", "in_progress"),
    "unreserve": ("planned", "released", "in_progress"),
    "issue": ("released", "in_progress"),
    "receipt": ("released", "in_progress"),
    "return": ("released", "in_progress", "completed"),
}
TARGET = {"release": "released", "complete": "completed", "close": "closed", "cancel": "cancelled",
          "refresh-components": "planned"}
#: MRP treats these as supply (7.1)
SUPPLY_STATUSES = ("planned", "released", "in_progress")
READONLY = ("completed", "closed", "cancelled")


def check_action(status: str, action: str) -> str | None:
    allowed = ACTIONS[action]
    if status not in allowed:
        raise invalid_state(WHAT, status, action, allowed)
    return TARGET.get(action)


def check_editable(status: str) -> None:
    if status in READONLY:
        raise readonly(WHAT, status)


def check_no_transactions(has_transactions: bool, action: str) -> None:
    if has_transactions:
        raise RuleError(409, "WO_HAS_TRANSACTIONS", "This work order has material issues or receipts; return the "
                        f"material first ('{action}' is not possible).", {"action": action})


def check_deletable(status: str, has_transactions: bool) -> None:
    if status not in ("planned", "cancelled"):
        raise invalid_state(WHAT, status, "delete", ["planned", "cancelled"])
    check_no_transactions(has_transactions, "delete")


def check_put(status: str, *, qty: float, qty_completed: float, item_changed: bool,
              components: Iterable[tuple[Any, float, float]] = ()) -> None:
    """PUT rules (7.1): `planned` all fields; `released`/`in_progress` qty >= completed (422
    `WO_QTY_BELOW_COMPLETED`), components required >= issued (422 `WO_COMPONENT_BELOW_ISSUED`); final statuses
    read-only. `components`: `(index, required, issued)`."""
    check_editable(status)
    if item_changed:
        raise RuleError(422, "VALIDATION_ERROR", "The item of a work order cannot change.",
                        {"errors": [{"loc": ["body", "item_id"], "msg": "immutable", "type": "immutable"}]})
    if qty < qty_completed - EPS:
        raise RuleError(422, "WO_QTY_BELOW_COMPLETED", f"The quantity cannot go below the {qty_completed:g} already "
                        "completed.", {"qty_completed": qty_completed})
    for idx, req, issued in components:
        if req < issued - EPS:
            raise RuleError(422, "WO_COMPONENT_BELOW_ISSUED", f"A component's required quantity cannot go below the "
                            f"{issued:g} already issued.", {"component": idx, "issued_qty": issued})


def derive_status(status: str, qty: float, qty_completed: float, *, touched: bool) -> str:
    """After an issue/receipt posting (`touched`): `released -> in_progress`; completed >= qty -> `completed`.
    A reversal can move `completed` back to `in_progress` (4.2)."""
    if status == "released" and touched:
        status = "in_progress"
    if status == "in_progress" and qty_completed >= qty - EPS:
        return "completed"
    if status == "completed" and qty_completed < qty - EPS and touched:
        return "in_progress"
    return status


def open_qty(qty: float, qty_completed: float) -> float:
    return max(0.0, qty - qty_completed)


# ---------------------------------------------------------------- calendar, dates, components (7.2, 8.5, 8.7)


def plant_holidays(ds: Any) -> frozenset[date]:
    """Plant-scope holiday/shutdown exceptions covering a whole local day (8.2 `MrpSnapshot.holidays`)."""
    from .calendar import offset_tz

    tz = offset_tz(ds.plant.utc_offset)
    out: set[date] = set()
    for e in ds.calendar_exceptions.values():
        if e.scope != "plant" or e.kind not in ("holiday", "shutdown"):
            continue
        s, t = e.start.astimezone(tz), e.end.astimezone(tz)
        d = s.date() if (s.hour, s.minute, s.second) == (0, 0, 0) else s.date() + timedelta(days=1)
        while True:
            day_end = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(days=1)
            if day_end > t:
                break
            out.add(d)
            d += timedelta(days=1)
    return frozenset(out)


def lead_days(ds: Any, item_id: str, qty: float, on: date, serial: int | None) -> int:
    from .mrp.leadtime import manufacturing_lead_days

    return manufacturing_lead_days(ds, item_id, qty, on, serial, float(ds.plant.mrp_day_minutes))


def default_start_date(ds: Any, item_id: str, qty: float, due: date, cal: Any, *, on: date | None = None,
                       serial: int | None = None) -> date:
    """`workday_sub(due_date, manufacturing_lead_days(qty))` (3.7), never after `due`."""
    start = cal.workday_sub(due, lead_days(ds, item_id, qty, on or due, serial))
    return min(start, due)


def generate_components(ds: Any, item_id: str, qty: float, *, on: date, serial: int | None) -> Any:
    """`mrp.order_components` (7.2): effective BOM + primary routing at `on`, phantoms blown through, primary lines
    only, scrap/yield inflated, count-UoM rounded up. Returns the `OrderExplosion`."""
    from .mrp.explode import order_components

    return order_components(ds, item_id, qty, on=on, serial=serial)


# ---------------------------------------------------------------- stock views (7.3, 7.4)


@dataclass
class StockBal:
    """A balance as kitting/reservation sees it."""
    id: str
    item_id: str
    location_id: str
    location_code: str
    kind: str
    lot_id: str | None
    lot_code: str | None
    expires_on: date | None
    hold: bool
    qty_on_hand: float
    qty_reserved: float
    location_active: bool = True

    @property
    def available(self) -> float:
        return max(0.0, self.qty_on_hand - self.qty_reserved)


def usable(b: StockBal, today: date) -> bool:
    """Kitting / reservation stock: `stores`/`line_side`, not held, not expired at `today`."""
    return (b.kind in NETTABLE_NOW_KINDS and not b.hold and b.location_active
            and (b.expires_on is None or b.expires_on > today))


def fefo_key(b: StockBal) -> tuple[Any, ...]:
    """7.3: lot expiry (nulls last), then `line_side` before `stores`, then location code."""
    return (b.expires_on is None, b.expires_on or date.max, 0 if b.kind == "line_side" else 1, b.location_code,
            b.lot_code or "", b.id)


@dataclass
class ResComp:
    id: str
    item_id: str
    open_qty: float          # required - issued
    reserved_qty: float      # existing reservations of this component


def plan_reservations(components: Iterable[ResComp], balances: Iterable[StockBal], today: date
                      ) -> tuple[list[tuple[str, str, float]], list[dict[str, Any]]]:
    """7.3: for each open component reserve `min(open - reserved, free)` from usable balances in FEFO order.
    Returns `([(component_id, balance_id, qty)], [{component_id, qty, shortage}])`; balances are not mutated."""
    free: dict[str, float] = {}
    by_item: dict[str, list[StockBal]] = {}
    for b in balances:
        if usable(b, today) and b.available > EPS:
            free[b.id] = b.available
            by_item.setdefault(b.item_id, []).append(b)
    for v in by_item.values():
        v.sort(key=fefo_key)
    out: list[tuple[str, str, float]] = []
    summary: list[dict[str, Any]] = []
    for c in sorted(components, key=lambda c: c.id):
        need = c.open_qty - c.reserved_qty
        got = 0.0
        if need > EPS:
            for b in by_item.get(c.item_id, []):
                take = min(need - got, free[b.id])
                if take > EPS:
                    take = round(take, 6)
                    free[b.id] -= take
                    got += take
                    out.append((c.id, b.id, take))
                if need - got <= EPS:
                    break
        summary.append({"component_id": c.id, "qty": round(got, 6), "shortage": round(max(0.0, need - got), 6)})
    return out, summary


@dataclass
class KitComponent:
    id: str
    item_id: str
    required: float
    issued: float
    reserved: float          # this WO's reservations

    @property
    def open(self) -> float:
        return max(0.0, self.required - self.issued)


@dataclass
class KitWo:
    id: str
    number: str
    status: str
    priority: int
    start_date: date
    components: list[KitComponent] = field(default_factory=list)


def kitting(wo: KitWo, balances: Iterable[StockBal], today: date, next_supply: dict[str, Any] | None = None
            ) -> dict[str, Any]:
    """7.4 per-WO kitting (live): per component `required, issued, open, reserved, free, shortage, locations (top
    5 balances by available), next_supply`; totals."""
    usable_by_item: dict[str, list[StockBal]] = {}
    for b in balances:
        if usable(b, today) and b.available > EPS:
            usable_by_item.setdefault(b.item_id, []).append(b)
    rows = []
    short = 0
    for c in wo.components:
        bals = usable_by_item.get(c.item_id, [])
        free = round(sum(b.available for b in bals), 6)
        shortage = round(max(0.0, c.open - c.reserved - free), 6)
        short += shortage > EPS
        top = sorted(bals, key=lambda b: (-b.available, b.location_code, b.lot_code or ""))[:5]
        rows.append({"component_id": c.id, "item_id": c.item_id, "required": c.required, "issued": c.issued,
                     "open": round(c.open, 6), "reserved": c.reserved, "free": free, "shortage": shortage,
                     "locations": [{"balance_id": b.id, "location_id": b.location_id, "location_code": b.location_code,
                                    "lot_code": b.lot_code, "available": round(b.available, 6)} for b in top],
                     "next_supply": (next_supply or {}).get(c.item_id) if shortage > EPS else None})
    return {"rows": rows, "totals": {"components": len(rows), "short_components": short, "kit_complete": short == 0}}


def kitting_order(wos: Iterable[KitWo], order: str) -> list[KitWo]:
    if order == "start_date":
        return sorted(wos, key=lambda w: (w.start_date, w.priority, w.number))
    return sorted(wos, key=lambda w: (w.priority, w.start_date, w.number))


def simulate_kitting(wos: Iterable[KitWo], balances: Iterable[StockBal], supplies: dict[str, Any] | None,
                     order: str, today: date) -> dict[str, Any]:
    """7.4 kitting check: WOs in sequence, each takes the free (unreserved, usable) stock in turn after its own
    reservations. Returns `{"rows": [...], "items_short": [...]}` (items_short by first start date)."""
    pool: dict[str, float] = {}
    for b in balances:
        if usable(b, today):
            pool[b.item_id] = pool.get(b.item_id, 0.0) + b.available
    rows = []
    agg: dict[str, dict[str, Any]] = {}
    for w in kitting_order(wos, order):
        shortages = []
        for c in w.components:
            need = c.open - c.reserved
            if need <= EPS:
                continue
            have = pool.get(c.item_id, 0.0)
            take = min(have, need)
            pool[c.item_id] = have - take
            miss = round(need - take, 6)
            if miss > EPS:
                shortages.append({"item_id": c.item_id, "shortage": miss,
                                  "next_supply": (supplies or {}).get(c.item_id)})
                a = agg.setdefault(c.item_id, {"item_id": c.item_id, "total_shortage": 0.0, "wo_count": 0,
                                               "first_start_date": w.start_date,
                                               "next_supply": (supplies or {}).get(c.item_id)})
                a["total_shortage"] = round(a["total_shortage"] + miss, 6)
                a["wo_count"] += 1
                a["first_start_date"] = min(a["first_start_date"], w.start_date)
        shortages.sort(key=lambda x: (-x["shortage"], x["item_id"]))
        rows.append({"wo_id": w.id, "number": w.number, "start_date": w.start_date, "priority": w.priority,
                     "status": w.status, "kit_complete": not shortages, "short_components": len(shortages),
                     "shortages": shortages[:20]})
    items_short = sorted(agg.values(), key=lambda a: (a["first_start_date"], a["item_id"]))
    return {"rows": rows, "items_short": items_short}


def now_utc() -> datetime:  # pragma: no cover - trivial (services stamp released/completed times)
    return datetime.now(UTC)


__all__ = ["ACTIONS", "KitComponent", "KitWo", "READONLY", "ResComp", "SUPPLY_STATUSES", "StockBal", "WO_STATUSES",
           "check_action", "check_deletable", "check_editable", "check_no_transactions", "check_put",
           "default_start_date", "derive_status", "fefo_key", "generate_components", "kitting", "kitting_order",
           "lead_days", "open_qty", "plan_reservations", "plant_holidays", "simulate_kitting", "usable"]
