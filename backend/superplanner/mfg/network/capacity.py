"""Rough-cut capacity of a plant (M9-DESIGN 5.2): cap groups = M1 groups with active lines; available hours per
Monday week from the M1 calendar (`base` shift windows) of every active line (x parallel capacity); hours per unit =
1 / (units_per_hour x OEE) from M8 line rates for flow lines (item, else family; mean over the group's lines), else
the item's first routing (run minutes per unit + setup minutes over the fixed / minimum lot) per operation group.
Groups without rate or routing are unconstrained (`NET_CAP_UNKNOWN`)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .calendar import monday


def available_hours(ds: Any, weeks: list[date]) -> dict[tuple[str, date], float]:
    """(group code, week) -> hours."""
    from ..calendar import line_windows
    from ..tz import plant_tz

    out: dict[tuple[str, date], float] = defaultdict(float)
    if not weeks:
        return out
    tz = plant_tz(ds.plant)
    d0, d1 = weeks[0], weeks[-1] + timedelta(days=7)
    wkset = set(weeks)
    for ln in ds.lines.values():
        if not getattr(ln, "active", True):
            continue
        g = ds.groups.get(ln.group_id)
        if g is None:
            continue
        par = max(int(getattr(ln, "parallel_capacity", 1) or 1), 1)
        for w in line_windows(ds, ln.id, d0, d1, kinds=("base",)):
            wk = monday(w.start.astimezone(tz).date())
            if wk in wkset:
                out[(g.code, wk)] += (w.end - w.start).total_seconds() / 3600.0 * par
    return out


def hours_per_unit(ds: Any, item: Any, line_rates: list[Any], line_oee: dict[str, float]) -> list[tuple[str, float]]:
    """[(group code, hours per unit)] of a made item."""
    by_group: dict[str, list[float]] = defaultdict(list)
    for r in line_rates:
        ln = ds.lines.get(r.line_id)
        if ln is None or (r.item_id and r.item_id != item.id) or (r.item_family and r.item_family != item.family):
            continue
        g = ds.groups.get(ln.group_id)
        oee = r.oee if r.oee is not None else line_oee.get(ln.id, 0.85)
        if g is not None and r.units_per_hour > 0 and oee > 0:
            by_group[g.code].append(1.0 / (r.units_per_hour * oee))
    if by_group:
        return sorted((g, sum(v) / len(v)) for g, v in by_group.items())
    routings = ds.routings_by_item.get(item.id, [])
    routings = [r for r in routings if r.status == "released"] or routings
    if not routings:
        return []
    lot = max(float(item.fixed_lot_qty or 0) or float(item.min_order_qty or 0) or 1.0, 1.0)
    acc: dict[str, float] = defaultdict(float)
    for op in routings[0].operations:
        g = ds.groups.get(op.group_id)
        if g is None:
            continue
        run = float(op.run_minutes or 0)
        if op.run_per == "batch" and op.units_per_batch:
            run = run / op.units_per_batch
        acc[g.code] += (run + float(op.setup_minutes or 0) / lot) / 60.0
    return sorted((g, h) for g, h in acc.items() if h > 0)
