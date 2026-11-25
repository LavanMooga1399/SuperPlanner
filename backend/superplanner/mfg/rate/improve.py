"""CP-SAT window improvement of a constructed line plan (M8-DESIGN 7.2 step 4; pure).

The constructed campaign sequence (item, qty) is re-sequenced in rolling 7-day windows of at most 30 campaigns.
Per window a CP-SAT model orders the window's campaigns: `AddCircuit` over the campaigns plus a depot node (the
previous item before the window, the first item after it), start times with sequence-dependent setup minutes,
campaigns of the same item keep their relative order, lateness of each campaign against its run-out time as a
penalty (unit-minutes), changeover cost. Weighted stages give the lexicographic order (shortage >> changeover
cost). The candidate sequence is laid out again through the real shift windows (`construct.produce`) and accepted
only if the exact objective (`explain.evaluate`) is lexicographically better and the independent validator is
clean. Rounds repeat until no window improves or the time budget is spent; without a solution the construction
stays.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ortools.sat.python import cp_model

from . import explain
from .construct import Cursor, Sim, produce, transition
from .model import RateBlock, RateLine, RateProblem
from .validator import validate

WINDOW_DAYS = 7
MAX_CAMPAIGNS = 30
W_SHORT = 1000          # per unit-hour late (scaled), dominates changeover cost
W_COST = 10


@dataclass
class Campaign:
    item_id: str
    qty: float


def campaigns_of(blocks: list[RateBlock]) -> list[tuple[Campaign, datetime]]:
    out: dict[int, list[RateBlock]] = {}
    for b in blocks:
        if b.kind == "production" and not b.firm:
            out.setdefault(b.campaign_no, []).append(b)
    seq = sorted(out.values(), key=lambda bl: min(b.start for b in bl))
    return [(Campaign(bl[0].item_id or "", round(sum(b.qty for b in bl), 6)), min(b.start for b in bl)) for bl in seq]


def relayout(problem: RateProblem, line: RateLine, firm: list[RateBlock], seq: list[Campaign]) -> list[RateBlock]:
    sim = Sim(line, problem.horizon_end)
    blocks = sorted(firm, key=lambda b: b.start)
    cur = Cursor(max([problem.as_of] + [b.end for b in blocks]),
                 campaign_no=max([b.campaign_no for b in blocks], default=0))
    prods = [b for b in blocks if b.kind == "production"]
    if prods:
        cur.prev_item = prods[-1].item_id
    for c in seq:
        got, made, _ok = produce(problem, sim, cur, c.item_id, c.qty)
        blocks += got
        if made <= 0:
            break
    return blocks


def _runouts(problem: RateProblem, line: RateLine, seq: list[Campaign], firm_qty: dict[str, float]
             ) -> list[date | None]:
    """Per campaign: the due date of the first demand its item cannot meet without it (given earlier campaigns of
    the same item in this order)."""
    dem: dict[str, list[tuple[date, float]]] = {}
    for d in problem.demands:
        if d.item_id in line.rates:
            dem.setdefault(d.item_id, []).append((d.due, d.qty))
    supply = {i: problem.items[i].initial_stock + firm_qty.get(i, 0.0) for i in line.rates if i in problem.items}
    out: list[date | None] = []
    for c in seq:
        cum = 0.0
        ro = None
        for due, q in sorted(dem.get(c.item_id, [])):
            cum += q
            if cum > supply.get(c.item_id, 0.0) + 1e-6:
                ro = due
                break
        out.append(ro)
        supply[c.item_id] = supply.get(c.item_id, 0.0) + c.qty
    return out


def _solve_window(problem: RateProblem, line: RateLine, seq: list[Campaign], lo: int, hi: int, t0: datetime,
                  runouts: list[date | None], time_limit: float) -> list[int] | None:
    """New order of campaigns lo..hi-1 (indices) or None."""
    idx = list(range(lo, hi))
    n = len(idx)
    if n < 2:
        return None
    prev_item = seq[lo - 1].item_id if lo > 0 else None
    next_item = seq[hi].item_id if hi < len(seq) else None
    m = cp_model.CpModel()
    dur = [int(round(seq[i].qty / line.rates[seq[i].item_id] * 60)) for i in idx]

    def setup(a: str | None, b: str | None) -> tuple[int, int]:
        if a is None or b is None:
            return 0, 0
        tr = transition(problem, line, a, b)
        return sum(x[1] for x in tr), int(round(sum(x[2] for x in tr) * 100))
    horizon = sum(dur) + sum(max(setup(seq[i].item_id, seq[j].item_id)[0] for j in idx) for i in idx) + \
        setup(prev_item, None)[0] + 10_000
    start = [m.NewIntVar(0, horizon, f"s{k}") for k in range(n)]
    late = [m.NewIntVar(0, horizon, f"l{k}") for k in range(n)]
    arcs = []
    cost_terms = []
    for k in range(n):
        lit = m.NewBoolVar(f"start{k}")
        mins, cost = setup(prev_item, seq[idx[k]].item_id)
        arcs.append((0, k + 1, lit))
        m.Add(start[k] >= mins).OnlyEnforceIf(lit)
        cost_terms.append(cost * lit)
        lit2 = m.NewBoolVar(f"end{k}")
        arcs.append((k + 1, 0, lit2))
        cost_terms.append(setup(seq[idx[k]].item_id, next_item)[1] * lit2)
        for j in range(n):
            if j == k:
                continue
            lit3 = m.NewBoolVar(f"a{k}_{j}")
            arcs.append((k + 1, j + 1, lit3))
            mins, cost = setup(seq[idx[k]].item_id, seq[idx[j]].item_id)
            m.Add(start[j] >= start[k] + dur[k] + mins).OnlyEnforceIf(lit3)
            cost_terms.append(cost * lit3)
    m.AddCircuit(arcs)
    # same item: keep the relative order
    for a in range(n):
        for b in range(a + 1, n):
            if seq[idx[a]].item_id == seq[idx[b]].item_id:
                m.Add(start[b] >= start[a] + dur[a])
    short_terms = []
    for k in range(n):
        ro = runouts[idx[k]]
        if ro is None:
            continue
        due_min = int((datetime(ro.year, ro.month, ro.day, tzinfo=t0.tzinfo) - t0).total_seconds() // 60) - \
            line.tz_offset_minutes + 1440          # available by the end of the due day
        m.Add(late[k] >= start[k] + dur[k] - due_min)
        rate_h = line.rates[seq[idx[k]].item_id]
        short_terms.append(late[k] * max(1, int(round(rate_h / 60.0))))
    m.Minimize(W_SHORT * sum(short_terms) + W_COST * sum(cost_terms))
    # hint: current order
    for k in range(n):
        m.AddHint(start[k], sum(dur[:k]))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, time_limit)
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 7
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    order = sorted(range(n), key=lambda k: solver.Value(start[k]))
    return [idx[k] for k in order]


def improve_line(problem: RateProblem, line: RateLine, blocks: list[RateBlock], budget_s: float
                 ) -> tuple[list[RateBlock], dict[str, int]]:
    """-> (best blocks of the line, stats {windows, accepted})."""
    t_end = time.monotonic() + max(budget_s, 0.0)
    firm = [b for b in blocks if b.firm]
    firm_qty: dict[str, float] = {}
    for b in firm:
        if b.kind == "production" and b.item_id and not problem.firm_netted:
            firm_qty[b.item_id] = firm_qty.get(b.item_id, 0.0) + b.qty
    sub = problem                     # the caller passes the line's sub-problem (its assigned demands)
    best = blocks
    best_key = explain.key(explain.evaluate(sub, best))
    stats = {"windows": 0, "accepted": 0}
    for _round in range(3):
        improved = False
        cs = campaigns_of(best)
        seq = [c for c, _s in cs]
        starts = [s for _c, s in cs]
        lo = 0
        while lo < len(seq) and time.monotonic() < t_end:
            w_end = starts[lo] + timedelta(days=WINDOW_DAYS)
            hi = lo
            while hi < len(seq) and starts[hi] < w_end and hi - lo < MAX_CAMPAIGNS:
                hi += 1
            stats["windows"] += 1
            ros = _runouts(sub, line, seq, firm_qty)
            left = t_end - time.monotonic()
            order = _solve_window(sub, line, seq, lo, hi, starts[lo], ros, min(left, 10.0)) if left > 0.05 else None
            if order is not None and order != list(range(lo, hi)):
                cand_seq = seq[:lo] + [seq[i] for i in order] + seq[hi:]
                cand = relayout(sub, line, firm, cand_seq)
                k = explain.key(explain.evaluate(sub, cand))
                if k < best_key and validate(sub, cand)["ok"]:
                    best, best_key = cand, k
                    seq = cand_seq
                    cs = campaigns_of(best)
                    starts = [s for _c, s in cs]
                    seq = [c for c, _s in cs]
                    stats["accepted"] += 1
                    improved = True
            lo = hi
        if not improved or time.monotonic() >= t_end:
            break
    return best, stats

