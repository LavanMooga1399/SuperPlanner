"""Independent validator of a rate plan (M8-DESIGN 7.2 step 5, V3). Written separately from the construction /
improvement code (own matrix lookup, own arithmetic); any violation makes the run `failed_validation`.

Checks per line: every block inside one shift window and inside the horizon; no overlap; between two production
blocks of different items the setup blocks in between cover the required changeover, cleaning and clearance minutes
(matrix: most specific row per kind; clearance = max(matrix, line clearance)); periodic cleaning: production hours
between cleaning blocks of at least `clean_minutes` never exceed `clean_every_hours`; qty = rate x hours (+-1 case);
campaign quantity = whole cases; campaign hours within [min, max] (min not enforced for the last campaign of a
line when the window time left could not reach it); eligibility (a rate on the line); firm blocks unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from .model import RateBlock, RateProblem

TOL_MIN = 0.01          # minutes
TOL_H = TOL_MIN / 60.0


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600.0


def _required(problem: RateProblem, family: str | None, a: str, b: str) -> dict[str, int]:
    """kind -> minutes (validator's own most-specific lookup)."""
    out: dict[str, tuple[int, int]] = {}
    if family:
        for r in problem.changeovers:
            if r.line_setup_family != family:
                continue
            if (r.from_key, r.to_key) == (a, b):
                spec = 4
            elif a == b:
                continue
            elif (r.from_key, r.to_key) == (a, "*"):
                spec = 3
            elif (r.from_key, r.to_key) == ("*", b):
                spec = 2
            elif (r.from_key, r.to_key) == ("*", "*"):
                spec = 1
            else:
                continue
            if r.kind not in out or spec > out[r.kind][0]:
                out[r.kind] = (spec, r.minutes)
    return {k: v[1] for k, v in out.items()}


def validate(problem: RateProblem, blocks: list[RateBlock]) -> dict[str, Any]:
    viol: list[dict[str, Any]] = []

    def bad(code: str, line_id: str | None, ix: int | None, **detail: Any) -> None:
        viol.append({"code": code, "line_id": line_id, "block_ix": ix, "detail": detail})

    lines = {ln.id: ln for ln in problem.lines}
    idx = {id(b): k for k, b in enumerate(blocks)}
    by_line: dict[str, list[RateBlock]] = defaultdict(list)
    for b in blocks:
        if b.line_id not in lines:
            bad("RATE_V_LINE", b.line_id, idx[id(b)])
            continue
        if b.end <= b.start:
            bad("RATE_V_EMPTY", b.line_id, idx[id(b)])
        by_line[b.line_id].append(b)
    # firm blocks unchanged
    present = {(b.line_id, b.kind, b.item_id, b.start, b.end, round(b.qty, 4)) for b in blocks}
    for f in problem.firm_blocks:
        if (f.line_id, f.kind, f.item_id, f.start, f.end, round(f.qty, 4)) not in present:
            bad("RATE_V_FIRM", f.line_id, None, start=f.start.isoformat(), item_id=f.item_id)
    for lid, bl in by_line.items():
        ln = lines[lid]
        bl.sort(key=lambda b: (b.start, b.end))
        wins = sorted(ln.windows, key=lambda w: w.start)
        for b in bl:
            ix = idx[id(b)]
            firm = b.firm
            if not firm and not any(w.start <= b.start and b.end <= w.end for w in wins):
                bad("RATE_V_WINDOW", lid, ix, start=b.start.isoformat(), end=b.end.isoformat())
            if not firm and (b.start < problem.as_of or b.end > problem.horizon_end):
                bad("RATE_V_HORIZON", lid, ix)
            if b.kind == "production":
                rate = ln.rates.get(b.item_id or "")
                if rate is None:
                    bad("RATE_V_ELIGIBILITY", lid, ix, item_id=b.item_id)
                    continue
                it = problem.items.get(b.item_id or "")
                case = (it.case_qty if it and it.case_qty else 1.0)
                if abs(b.qty - rate * _hours(b.start, b.end)) > case + 1e-6:
                    bad("RATE_V_QTY", lid, ix, qty=b.qty, expected=rate * _hours(b.start, b.end))
        for a, b in zip(bl, bl[1:]):
            if b.start < a.end - timedelta(seconds=1):
                bad("RATE_V_OVERLAP", lid, idx[id(b)], prev_end=a.end.isoformat(), start=b.start.isoformat())
        # setups between productions of different items
        prev_item: str | None = None
        setup: dict[str, float] = defaultdict(float)
        for b in bl:
            if b.kind == "production":
                if prev_item is not None and b.item_id != prev_item and not b.firm:
                    ia, ib = problem.items.get(prev_item), problem.items.get(b.item_id or "")
                    need = _required(problem, ln.setup_family, ia.key if ia else prev_item, ib.key if ib else "")
                    need["clearance"] = max(need.get("clearance", 0), ln.clearance_minutes)
                    for kind, minutes in need.items():
                        if minutes > 0 and setup[kind] + TOL_MIN < minutes:
                            bad("RATE_V_CHANGEOVER", lid, idx[id(b)], kind=kind, required=minutes,
                                planned=round(setup[kind], 3), from_item=prev_item, to_item=b.item_id)
                prev_item = b.item_id
                setup = defaultdict(float)
            elif b.kind in ("changeover", "cleaning", "clearance"):
                setup[b.kind] += _hours(b.start, b.end) * 60.0
        # periodic cleaning
        if ln.clean_every_hours:
            run = 0.0
            clean_acc = 0.0
            for b in bl:
                if b.kind == "cleaning":
                    clean_acc += _hours(b.start, b.end) * 60.0
                    if clean_acc + TOL_MIN >= float(ln.clean_minutes or 0):
                        run = 0.0
                    continue
                clean_acc = 0.0
                if b.kind == "production":
                    run += _hours(b.start, b.end)
                    if run > ln.clean_every_hours + TOL_H and not b.firm:
                        bad("RATE_V_CLEANING", lid, idx[id(b)], run_hours=round(run, 3),
                            limit=ln.clean_every_hours)
                        run = 0.0
    # campaigns
    camp: dict[tuple[str, int], list[RateBlock]] = defaultdict(list)
    for b in blocks:
        if b.kind == "production" and not b.firm:
            camp[(b.line_id, b.campaign_no)].append(b)
    for (lid, no), bl in camp.items():
        items = {b.item_id for b in bl}
        if len(items) > 1:
            bad("RATE_V_CAMPAIGN_ITEMS", lid, idx[id(bl[0])], campaign_no=no)
            continue
        it = problem.items.get(bl[0].item_id or "")
        if it is None:
            continue
        hours = sum(_hours(b.start, b.end) for b in bl)
        qty = sum(b.qty for b in bl)
        if it.case_qty and abs(qty / it.case_qty - round(qty / it.case_qty)) > 1e-4:
            bad("RATE_V_CASES", lid, idx[id(bl[0])], campaign_no=no, qty=qty, case=it.case_qty)
        ln = lines[lid]
        last_end = max(b.end for b in bl)
        later = any(b.kind == "production" and not b.firm and b.start >= last_end for b in by_line[lid])
        left_h = sum(_hours(max(w.start, last_end), min(w.end, problem.horizon_end)) for w in ln.windows
                     if w.end > last_end and w.start < problem.horizon_end)
        # cut by the horizon end: the last campaign of the line, and the time left could not reach the minimum
        cut = not later and left_h + TOL_H < it.campaign_min_hours - hours + (ln.clean_minutes or 0) / 60.0 + \
            (it.case_qty or 1.0) / max(ln.rates.get(it.id, 1.0), 1e-9)
        if it.campaign_min_hours and hours + TOL_H < it.campaign_min_hours and not cut:
            bad("RATE_V_CAMPAIGN_MIN", lid, idx[id(bl[0])], campaign_no=no, hours=round(hours, 3),
                min_hours=it.campaign_min_hours)
        if it.campaign_max_hours and hours > it.campaign_max_hours + TOL_H:
            bad("RATE_V_CAMPAIGN_MAX", lid, idx[id(bl[0])], campaign_no=no, hours=round(hours, 3),
                max_hours=it.campaign_max_hours)
    return {"ok": not viol, "violations": viol[:500], "count": len(viol)}
