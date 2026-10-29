"""Views over results (M2-DESIGN 8.13); pure, work on `MrpResult` / `ItemPlan` (or plans rebuilt from stored JSON
with `model.item_plan_from_jsonable`).

- `item_timeline(plan, as_of)`: dated events with two running balances. Requirements (-) at
  `max(need_date, as_of)`, existing supplies (+) at `max(avail_date, as_of)`, planned supplies (+) at their need
  date, the opening on-hand (nettable now) at `as_of` and an `expiry` event (-) for the unpegged remainder of a lot
  on its expiry date. Safety stock is a target level, not a consumption, so it is not an event. Same-day order:
  on_hand, supply, planned, expiry, requirement. `balance_existing` excludes planned orders (shows the shortage).
- `bucketize(timeline, bucket, start, end)`: day / ISO week (Monday) / calendar month buckets.
- `pegging(source, item_id, node, kind, direction, max_depth)`: depth-first rows, `PEGGING_MAX_ROWS`.
- `compare(a, b)`: demand, planned, exception and item deltas (12.4 `CompareResponse` without the run records).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from ..limits import COMPARE_MAX_ROWS, PEGGING_MAX_ROWS
from .model import EPS, ItemPlan, MrpResult, TimelineEvent

_ORDER = {"on_hand": 0, "supply": 1, "planned": 2, "expiry": 3, "requirement": 4}


def _r(x: float) -> float:
    return round(x, 6) + 0.0


def item_timeline(plan: ItemPlan, as_of: date) -> list[TimelineEvent]:
    ev: list[tuple[date, int, int, str, str, float]] = []
    on_hand = sum(s.qty for s in plan.supplies if s.kind == "stock")
    if on_hand > EPS:
        ev.append((as_of, 0, 0, "on_hand", "On hand", on_hand))
    for s in plan.supplies:
        if s.kind == "planned":
            ev.append((max(s.avail_date, as_of), 2, s.node, "planned", s.ref.label, s.qty))
        elif s.kind != "stock":
            ev.append((max(s.avail_date, as_of), 1, s.node, "supply", s.ref.label, s.qty))
        if s.kind in ("stock", "inspection") and s.expires_on is not None:
            free = s.qty - s.pegged_qty
            if free > EPS and s.expires_on > as_of:
                ev.append((s.expires_on, 3, s.node, "expiry", f"Expiry: {s.ref.label}", -round(free, 6)))
    for r in plan.requirements:
        if r.kind != "safety_stock":
            ev.append((max(r.need_date, as_of), 4, r.node, "requirement", r.source.label, -r.qty))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    be = bp = 0.0
    out: list[TimelineEvent] = []
    for d, _o, node, kind, label, q in ev:
        bp += q
        if kind != "planned":
            be += q
        out.append(TimelineEvent(d, kind, node if kind != "on_hand" else None, label, q,
                                 round(be, 6) + 0.0, round(bp, 6) + 0.0))
    return out


def _bucket_start(d: date, bucket: str) -> date:
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    return d


def _next(d: date, bucket: str) -> date:
    if bucket == "week":
        return d + timedelta(days=7)
    if bucket == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


def bucketize(timeline: list[TimelineEvent], bucket: str, start: date, end: date) -> list[dict[str, Any]]:
    """Buckets covering `[start, end]`; `end` of a bucket is its last day. Events before `start` form the opening
    balances; the first bucket contains no earlier events."""
    if bucket not in ("day", "week", "month"):
        raise ValueError("bucket must be day, week or month")
    be = bp = 0.0
    i = 0
    n = len(timeline)
    while i < n and timeline[i].date < start:
        be, bp = timeline[i].balance_existing, timeline[i].balance_planned
        i += 1
    out: list[dict[str, Any]] = []
    b0 = _bucket_start(start, bucket)
    while b0 <= end:
        b1 = _next(b0, bucket)
        gross = sup = pl = 0.0
        while i < n and timeline[i].date < b1:
            e = timeline[i]
            if e.date >= start:
                if e.kind == "requirement":
                    gross -= e.qty
                elif e.kind == "supply":
                    sup += e.qty
                elif e.kind == "planned":
                    pl += e.qty
            be, bp = e.balance_existing, e.balance_planned
            i += 1
        out.append({"start": b0, "end": b1 - timedelta(days=1), "gross": _r(gross), "existing_supply": _r(sup),
                    "planned": _r(pl), "balance_existing_end": _r(be), "balance_planned_end": _r(bp),
                    "short": _r(max(0.0, -be))})
        b0 = b1
    return out


# ---------------------------------------------------------------- pegging


class _Index:
    def __init__(self, lookup: Callable[[str], ItemPlan | None]):
        self.lookup = lookup
        self.cache: dict[str, Any] = {}

    def get(self, item_id: str) -> Any:
        x = self.cache.get(item_id)
        if x is None:
            plan = self.lookup(item_id)
            if plan is None:
                return None
            reqs = {r.node: r for r in plan.requirements}
            sups = {s.node: s for s in plan.supplies}
            by_sup: dict[int, list[Any]] = {}
            for r in plan.requirements:
                for pg in r.pegs:
                    by_sup.setdefault(pg.supply_node, []).append((r, pg))
            x = self.cache[item_id] = (plan, reqs, sups, by_sup)
        return x


def pegging(source: MrpResult | Callable[[str], ItemPlan | None], item_id: str, node: int, kind: str,
            direction: str, max_depth: int = 10, max_rows: int = PEGGING_MAX_ROWS) -> dict[str, Any]:
    """Rows `{row, parent_row, level, item_id, node, kind, label, qty, date, projected_date, late_days}`; `level` =
    tree depth; `max_depth` limits the number of item hops (requirement -> parent supply / supply -> component)."""
    if isinstance(source, MrpResult):
        plans = {p.item_id: p for p in source.items}
        lookup: Callable[[str], ItemPlan | None] = plans.get
    else:
        lookup = source
    idx = _Index(lookup)
    rows: list[dict[str, Any]] = []
    truncated = False

    def add(parent: int | None, level: int, iid: str, nd: int, k: str, label: str, qty: float, d: date | None,
            proj: date | None, late: int) -> int | None:
        nonlocal truncated
        if len(rows) >= max_rows:
            truncated = True
            return None
        rows.append({"row": len(rows), "parent_row": parent, "level": level, "item_id": iid, "node": nd, "kind": k,
                     "label": label, "qty": _r(qty), "date": d, "projected_date": proj, "late_days": late})
        return len(rows) - 1

    def up_req(r: Any, iid: str, parent: int | None, level: int, hops: int, qty: float, late: int,
               seen: frozenset) -> None:
        row = add(parent, level, iid, r.node, "requirement", r.source.label, qty, r.need_date, r.satisfied_date, late)
        if row is None or r.source.item_id is None or r.source.node is None or hops >= max_depth:
            return
        x = idx.get(r.source.item_id)
        if x is None:
            return
        s = x[2].get(r.source.node)
        if s is not None and (r.source.item_id, s.node) not in seen:
            up_sup(s, r.source.item_id, row, level + 1, hops + 1, s.pegged_qty, seen)

    def up_sup(s: Any, iid: str, parent: int | None, level: int, hops: int, qty: float, seen: frozenset) -> None:
        row = add(parent, level, iid, s.node, "supply", s.ref.label, qty, s.avail_date, s.projected_date, 0)
        if row is None:
            return
        x = idx.get(iid)
        seen = seen | {(iid, s.node)}
        for r, pg in x[3].get(s.node, ()):
            up_req(r, iid, row, level + 1, hops, pg.qty, pg.late_days, seen)

    def down_req(r: Any, iid: str, parent: int | None, level: int, hops: int, qty: float, seen: frozenset) -> None:
        row = add(parent, level, iid, r.node, "requirement", r.source.label, qty, r.need_date, r.satisfied_date,
                  r.late_days)
        if row is None:
            return
        x = idx.get(iid)
        for pg in r.pegs:
            s = x[2].get(pg.supply_node)
            if s is not None:
                down_sup(s, iid, row, level + 1, hops, pg.qty, pg.late_days, seen)

    def down_sup(s: Any, iid: str, parent: int | None, level: int, hops: int, qty: float, late: int,
                 seen: frozenset) -> None:
        row = add(parent, level, iid, s.node, "supply", s.ref.label, qty, s.avail_date, s.projected_date, late)
        if row is None or hops >= max_depth or (iid, s.node) in seen:
            return
        seen = seen | {(iid, s.node)}
        for ci, cn in s.component_nodes:
            x = idx.get(ci)
            if x is None:
                continue
            r = x[1].get(cn)
            if r is not None:
                down_req(r, ci, row, level + 1, hops + 1, r.qty, seen)

    x = idx.get(item_id)
    if x is None:
        raise KeyError(item_id)
    if kind == "requirement":
        r = x[1].get(node)
        if r is None:
            raise KeyError(node)
        if direction == "up":
            up_req(r, item_id, None, 0, 0, r.qty, r.late_days, frozenset())
        else:
            down_req(r, item_id, None, 0, 0, r.qty, frozenset())
    else:
        s = x[2].get(node)
        if s is None:
            raise KeyError(node)
        if direction == "up":
            up_sup(s, item_id, None, 0, 0, s.pegged_qty, frozenset())
        else:
            down_sup(s, item_id, None, 0, 0, s.qty, 0, frozenset())
    return {"root": {"item_id": item_id, "node": node, "kind": kind}, "direction": direction, "rows": rows,
            "truncated": truncated}


# ---------------------------------------------------------------- compare


def _dkey(d: Any) -> str:
    return d.demand_line_id or f"extra:{d.extra_index}"


def compare(a: MrpResult, b: MrpResult, max_rows: int = COMPARE_MAX_ROWS) -> dict[str, Any]:
    da = {_dkey(d): d for d in a.demand}
    db = {_dkey(d): d for d in b.demand}
    demand = []
    for k in sorted(set(da) | set(db)):
        x, y = da.get(k), db.get(k)
        ap = x.projected_date if x else None
        bp = y.projected_date if y else None
        if ap == bp:
            continue
        ref = x or y
        demand.append({"demand_line_id": ref.demand_line_id, "label": ref.label, "due_date": ref.due_date,
                       "a_projected": ap, "b_projected": bp,
                       "delta_days": (bp - ap).days if ap is not None and bp is not None else None})
    demand.sort(key=lambda r: (-abs(r["delta_days"] or 10**6), r["label"]))

    def planned(r: MrpResult) -> dict[str, Any]:
        mk = [p for p in r.planned_orders if p.kind == "make"]
        by = [p for p in r.planned_orders if p.kind == "buy"]
        return {"make": len(mk), "buy": len(by), "make_qty": _r(sum(p.qty for p in mk)),
                "buy_qty": _r(sum(p.qty for p in by)), "buy_value": None}

    ca: dict[str, int] = {}
    cb: dict[str, int] = {}
    for e in a.exceptions:
        ca[e.code] = ca.get(e.code, 0) + 1
    for e in b.exceptions:
        cb[e.code] = cb.get(e.code, 0) + 1
    from .exceptions import CODES

    exc = [{"code": c, "a": ca.get(c, 0), "b": cb.get(c, 0)} for c, _s in CODES if ca.get(c, 0) != cb.get(c, 0)]
    ia = {p.item_id: p for p in a.items}
    ib = {p.item_id: p for p in b.items}
    items = []
    for k in sorted(set(ia) | set(ib)):
        x, y = ia.get(k), ib.get(k)
        vals = (x.stats.planned_qty if x else 0.0, y.stats.planned_qty if y else 0.0,
                x.stats.short_qty if x else 0.0, y.stats.short_qty if y else 0.0)
        if abs(vals[0] - vals[1]) > EPS or abs(vals[2] - vals[3]) > EPS:
            ref = x or y
            items.append({"item_id": k, "part_number": ref.part_number, "a_planned_qty": vals[0],
                          "b_planned_qty": vals[1], "a_short_qty": vals[2], "b_short_qty": vals[3]})
    items.sort(key=lambda r: (-abs(r["b_planned_qty"] - r["a_planned_qty"]), r["part_number"]))
    return {"demand": demand[:max_rows], "planned": {"a": planned(a), "b": planned(b)}, "exceptions_by_code": exc,
            "items": items[:max_rows], "truncated": {"demand": len(demand) > max_rows, "items": len(items) > max_rows}}


__all__ = ["bucketize", "compare", "item_timeline", "pegging"]
