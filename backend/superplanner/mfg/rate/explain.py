"""Objective evaluation, shortages and explanations of a rate plan (M8-DESIGN 7.1, 7.2 step 6; pure).

Objective (lexicographic, in this order): shortage unit-days (priority-weighted for comparisons; the reported
value is unweighted), changeover cost, excess cover unit-days, overtime cost. Daily resolution: production is
available on the plant-local date its block ends; backlog(d) = max(0, cumulative demand due <= d - cumulative
supply <= d) summed over the horizon days.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .construct import local_date, transition
from .model import RateBlock, RateProblem, Shortage

SETUP = ("changeover", "cleaning", "clearance")


def _days(problem: RateProblem) -> list[date]:
    off = problem.lines[0].tz_offset_minutes if problem.lines else 0
    d0 = (problem.as_of + timedelta(minutes=off)).date()
    d1 = (problem.horizon_end + timedelta(minutes=off)).date()
    return [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]


def supply_by_day(problem: RateProblem, blocks: list[RateBlock]) -> dict[str, dict[date, float]]:
    lines = {ln.id: ln for ln in problem.lines}
    out: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for b in blocks:
        if b.kind == "production" and b.item_id and not (problem.firm_netted and b.firm):
            out[b.item_id][local_date(lines[b.line_id], b.end)] += b.qty
    return out


def evaluate(problem: RateProblem, blocks: list[RateBlock]) -> dict[str, float]:
    days = _days(problem)
    sup = supply_by_day(problem, blocks)
    dem: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    prio: dict[str, int] = {}
    for d in problem.demands:
        dem[d.item_id][max(d.due, days[0])] += d.qty
        prio[d.item_id] = min(prio.get(d.item_id, 9), d.priority)
    short = weighted = excess = 0.0
    for item_id in set(dem) | set(sup):
        it = problem.items.get(item_id)
        cs = it.initial_stock if it else 0.0
        cd = 0.0
        cover = it.target_cover_days if it else 0
        ahead = sorted(dem[item_id].items())
        for d in days:
            cs += sup[item_id].get(d, 0.0)
            cd += dem[item_id].get(d, 0.0)
            back = cd - cs
            if back > 1e-6:
                short += back
                weighted += back * (1.0 + (9 - prio.get(item_id, 9)) / 8.0)
            fut = cd + sum(q for dd, q in ahead if d < dd <= d + timedelta(days=cover))
            if cs - fut > 1e-6:
                excess += cs - fut
    lines = {ln.id: ln for ln in problem.lines}
    co_cost = co_hours = ot_cost = 0.0
    by_line: dict[str, list[RateBlock]] = defaultdict(list)
    for b in blocks:
        by_line[b.line_id].append(b)
        h = (b.end - b.start).total_seconds() / 3600.0
        if b.kind in SETUP:
            co_hours += h
        ln = lines[b.line_id]
        for w in ln.windows:
            if w.overtime and w.start < b.end and b.start < w.end:
                ov = (min(w.end, b.end) - max(w.start, b.start)).total_seconds() / 3600.0
                ot_cost += ov * ln.overtime_cost_per_hour
    for lid, bl in by_line.items():
        prev = None
        for b in sorted(bl, key=lambda x: x.start):
            if b.kind != "production":
                continue
            if prev is not None and b.item_id != prev:
                co_cost += sum(c for _k, _m, c in transition(problem, lines[lid], prev, b.item_id))
            prev = b.item_id
    return {"shortage_unit_days": round(short, 6), "shortage_weighted": round(weighted, 6),
            "changeover_cost": round(co_cost, 6), "changeover_hours": round(co_hours, 6),
            "excess_cover_unit_days": round(excess, 6), "overtime_cost": round(ot_cost, 6)}


def key(obj: dict[str, float]) -> tuple[float, float, float, float]:
    """Lexicographic comparison key (rounded so float noise never decides)."""
    return (round(obj["shortage_weighted"], 3), round(obj["changeover_cost"], 3),
            round(obj["excess_cover_unit_days"], 3), round(obj["overtime_cost"], 3))


def shortages(problem: RateProblem, blocks: list[RateBlock], no_line: set[str]) -> list[Shortage]:
    """Per demand the quantity not available on its due date (FIFO by due date)."""
    days = _days(problem)
    sup = supply_by_day(problem, blocks)
    out: list[Shortage] = []
    by_item: dict[str, list[Any]] = defaultdict(list)
    for d in problem.demands:
        by_item[d.item_id].append(d)
    for item_id, ds in sorted(by_item.items()):
        it = problem.items.get(item_id)
        avail = it.initial_stock if it else 0.0
        days_sup = sorted(sup[item_id].items())
        used = 0.0
        for d in sorted(ds, key=lambda x: (x.due, x.priority)):
            until = max(d.due, days[0])
            got = avail + sum(q for dd, q in days_sup if dd <= until) - used
            take = min(max(got, 0.0), d.qty)
            used += take
            miss = d.qty - take
            if miss > 1e-6:
                out.append(Shortage(item_id, d.due, round(miss, 6),
                                    "RATE_NO_LINE" if item_id in no_line else "RATE_CAPACITY"))
    return out


def explain(problem: RateProblem, blocks: list[RateBlock], shorts: list[Shortage], assignment: dict[str, list[str]]
            ) -> list[dict[str, Any]]:
    """Causes of shortages (capacity with load %, changeover bound, minimum campaign) and material warnings."""
    lines = {ln.id: ln for ln in problem.lines}
    out: list[dict[str, Any]] = []
    avail_h: dict[str, float] = {}
    used: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for ln in problem.lines:
        avail_h[ln.id] = sum((min(w.end, problem.horizon_end) - max(w.start, problem.as_of)).total_seconds() / 3600
                             for w in ln.windows if w.end > problem.as_of and w.start < problem.horizon_end)
    for b in blocks:
        used[b.line_id][b.kind] += (b.end - b.start).total_seconds() / 3600.0
    line_of = {i: lid for lid, items in assignment.items() for i in items}
    for s in shorts:
        if s.cause == "RATE_NO_LINE":
            s.detail = {}
            out.append({"code": "RATE_NO_LINE", "severity": "error", "item_id": s.item_id, "line_id": None,
                        "message": f"{problem.items[s.item_id].part_number if s.item_id in problem.items else s.item_id}"
                                   f" has no flow line with a rate.", "detail": {}})
            continue
        lid = line_of.get(s.item_id)
        tot = sum(used[lid].values()) if lid else 0.0
        load = round(100.0 * tot / avail_h[lid], 1) if lid and avail_h.get(lid) else None
        setup = sum(used[lid][k] for k in SETUP) if lid else 0.0
        it = problem.items.get(s.item_id)
        if lid and avail_h.get(lid) and setup > 0.25 * avail_h[lid]:
            s.cause = "RATE_CHANGEOVER_BOUND"
        elif it is not None and it.campaign_min_hours and lid and \
                it.campaign_min_hours > avail_h.get(lid, 0.0) - tot + 1e-9 and (load or 0) < 90:
            s.cause = "RATE_MIN_CAMPAIGN"
        s.detail = {"line_id": lid, "load_pct": load, "changeover_hours": round(setup, 3)}
        code = lines[lid].code if lid in lines else "-"
        out.append({"code": s.cause, "severity": "warning", "item_id": s.item_id, "line_id": lid,
                    "message": f"{it.part_number if it else s.item_id}: {s.qty:,.0f} short on {s.due.isoformat()} - "
                               f"{code} is {load} % loaded.", "detail": dict(s.detail)})
    for b in blocks:
        if b.kind != "production" or not b.item_id:
            continue
        for comp, avail in problem.component_avail.get(b.item_id, []):
            if b.prod_date is not None and b.prod_date < avail:
                out.append({"code": "RATE_MATERIAL_SHORT", "severity": "warning", "item_id": b.item_id,
                            "line_id": b.line_id, "message": f"Component {comp} is projected available on "
                            f"{avail.isoformat()}, after the block on {b.prod_date.isoformat()}.",
                            "detail": {"component_id": comp, "available": avail.isoformat(),
                                       "block_start": b.start.isoformat()}})
                break
    seen = set()
    dedup = []
    for e in out:
        k = (e["code"], e["item_id"], e["line_id"], e["detail"].get("component_id"))
        if e["code"] == "RATE_MATERIAL_SHORT" and k in seen:
            continue
        seen.add(k)
        dedup.append(e)
    return dedup
