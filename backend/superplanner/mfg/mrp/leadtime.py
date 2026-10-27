"""Calendars and lead times (M2-DESIGN 8.5) and purchase-source resolution (3.3).

- Purchase lead time (calendar days): `lead_time_overrides` -> item-supplier source -> supplier -> item.
- Manufacturing lead time (working days): override -> item `lead_time_days` (fixed) -> primary effective routing:
  `days = ceil(sum_k(queue + setup + run x loads(inputs_k) / best_speed_k + move + wait) / day_minutes - 1e-9)`.

Plant MRP settings are read with defaults (`mon..sat`, 480 minutes, tolerance 7, release window 7) so the engine
also works on M1-shaped plants.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..dataset import MfgDataset
from ..model import ItemRecord, RoutingRecord
from ..routing import loads, lot_inputs, primary_routing
from ..units import is_count
from ..workdays import WorkCalendar

DEFAULT_WORKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat")
DEFAULT_DAY_MINUTES = 480.0


@dataclass(frozen=True, slots=True)
class MrpSettings:
    workdays: tuple[str, ...] = DEFAULT_WORKDAYS
    day_minutes: float = DEFAULT_DAY_MINUTES
    defer_tolerance_days: int = 7
    release_window_days: int = 7


def settings_of(plant: Any) -> MrpSettings:
    wd = getattr(plant, "mrp_workdays", None) or DEFAULT_WORKDAYS
    return MrpSettings(workdays=tuple(wd),
                       day_minutes=float(getattr(plant, "mrp_day_minutes", None) or DEFAULT_DAY_MINUTES),
                       defer_tolerance_days=int(getattr(plant, "mrp_defer_tolerance_days", 7)),
                       release_window_days=int(getattr(plant, "mrp_release_window_days", 7)))


def calendar_of(settings: MrpSettings, holidays: frozenset[date] | set[date] = frozenset()) -> WorkCalendar:
    return WorkCalendar(workdays=settings.workdays, holidays=holidays)


# ---------------------------------------------------------------- purchase source (3.3)


@dataclass(frozen=True, slots=True)
class PurchaseSource:
    item_supplier_id: str | None
    supplier_id: str | None
    lead_days: int
    lead_source: str        # override | item_supplier | supplier | item
    moq: float
    multiple: float
    pack: float


def item_suppliers_by_item(ds: MfgDataset) -> dict[str, list[Any]]:
    rows = getattr(ds, "item_suppliers", None) or {}
    out: dict[str, list[Any]] = {}
    for r in sorted(rows.values(), key=lambda r: r.id):
        out.setdefault(r.item_id, []).append(r)
    return out


def _supplier(ds: MfgDataset, sid: str | None) -> Any:
    return (getattr(ds, "suppliers", None) or {}).get(sid or "")


def _row_lead(ds: MfgDataset, row: Any, item: ItemRecord) -> tuple[int, str]:
    if row.lead_time_days is not None:
        return int(row.lead_time_days), "item_supplier"
    sup = _supplier(ds, row.supplier_id)
    if sup is not None and sup.lead_time_days is not None:
        return int(sup.lead_time_days), "supplier"
    return int(item.lead_time_days or 0), "item"


def resolve_source(ds: MfgDataset, item: ItemRecord, rows: list[Any] | None = None,
                   override: int | None = None) -> PurchaseSource:
    """The preferred active row whose supplier is active; else the active row (active supplier) with the smallest
    effective lead time, then supplier code. Effective values: lead time row -> supplier -> item; MOQ / multiple =
    row if > 0 else item; pack = row's `units_per_purchase_unit` (1 without a row)."""
    if rows is None:
        rows = item_suppliers_by_item(ds).get(item.id, [])
    cands = []
    for r in rows:
        sup = _supplier(ds, r.supplier_id)
        if not r.active or sup is None or not sup.active:
            continue
        lead, _src = _row_lead(ds, r, item)
        cands.append((0 if r.preferred else 1, lead, sup.code, r.id, r))
    cands.sort(key=lambda c: c[:4])
    row = cands[0][4] if cands else None
    if row is None:
        lead, src = int(item.lead_time_days or 0), "item"
        moq, mult, pack, sid, rid = float(item.min_order_qty), float(item.order_multiple), 1.0, None, None
    else:
        lead, src = _row_lead(ds, row, item)
        moq = float(row.min_order_qty) if row.min_order_qty > 0 else float(item.min_order_qty)
        mult = float(row.order_multiple) if row.order_multiple > 0 else float(item.order_multiple)
        pack, sid, rid = float(row.units_per_purchase_unit or 1.0), row.supplier_id, row.id
    if override is not None:
        lead, src = int(override), "override"
    return PurchaseSource(item_supplier_id=rid, supplier_id=sid, lead_days=lead, lead_source=src, moq=moq,
                          multiple=mult, pack=pack)


# ---------------------------------------------------------------- manufacturing lead time


def best_speed(ds: MfgDataset, group_id: str, item: ItemRecord) -> float:
    from ..routing import eligible_lines

    lines = eligible_lines(ds, group_id, item)
    return max((ln.speed_factor for ln in lines), default=1.0) or 1.0


def routing_minutes(ds: MfgDataset, routing: RoutingRecord, item: ItemRecord, qty: float,
                    speed_cache: dict[tuple[str, str], float] | None = None) -> float:
    ops = sorted(routing.operations, key=lambda o: o.seq)
    inputs = lot_inputs(ops, qty, is_count(item.uom))
    total = 0.0
    for k, op in enumerate(ops):
        if speed_cache is not None:
            key = (op.group_id, item.id)
            sp = speed_cache.get(key)
            if sp is None:
                sp = speed_cache[key] = best_speed(ds, op.group_id, item)
        else:
            sp = best_speed(ds, op.group_id, item)
        total += (op.queue_minutes + op.setup_minutes + op.run_minutes * loads(op, inputs[k]) / sp
                  + op.move_minutes + op.wait_minutes)
    return total


def minutes_to_days(minutes: float, day_minutes: float) -> int:
    if minutes <= 0:
        return 0
    return max(0, math.ceil(minutes / day_minutes - 1e-9))


def manufacturing_lead_days(ds: MfgDataset, item_id: str, qty: float, on: date, serial: int | None = None,
                            day_minutes: float = DEFAULT_DAY_MINUTES, *, override: int | None = None,
                            routing_id: str | None = None) -> int:
    """Working days to make `qty` good units of a make item (8.5). `routing_id` (existing WOs) selects that routing
    when it exists; else the primary effective routing at `on` for `serial`. No routing -> 0."""
    return mlt_info(ds, item_id, qty, on, serial, day_minutes, override=override, routing_id=routing_id)[0]


def mlt_info(ds: MfgDataset, item_id: str, qty: float, on: date, serial: int | None = None,
             day_minutes: float = DEFAULT_DAY_MINUTES, *, override: int | None = None, routing_id: str | None = None,
             speed_cache: dict[tuple[str, str], float] | None = None) -> tuple[int, str]:
    if override is not None:
        return int(override), "override"
    item = ds.items[item_id]
    if item.lead_time_days is not None:
        return int(item.lead_time_days), "fixed"
    r = ds.routings.get(routing_id) if routing_id else None
    if r is None:
        r = primary_routing(ds, item_id, on, serial)
    if r is None:
        return 0, "routing"
    return minutes_to_days(routing_minutes(ds, r, item, qty, speed_cache), day_minutes), "routing"


def overrides_map(params: Any) -> Mapping[str, int]:
    return {o.item_id: o.lead_time_days for o in params.lead_time_overrides}


__all__ = ["DEFAULT_DAY_MINUTES", "DEFAULT_WORKDAYS", "MrpSettings", "PurchaseSource", "calendar_of",
           "item_suppliers_by_item", "manufacturing_lead_days", "minutes_to_days", "mlt_info", "resolve_source",
           "routing_minutes", "settings_of"]
