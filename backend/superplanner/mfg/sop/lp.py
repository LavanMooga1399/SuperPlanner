"""S&OP constrained supply plan (M9-DESIGN 6.3): an LP solved with OR-Tools GLOP in three lexicographic solves.

Variables per (node n, family f, month t): make (where n can make f), buy[s] (supplier options), ship[lane] (lanes
allowed for f; arrival t + transit months), inv >= 0, unmet >= 0 (lost sales), ss_short >= 0.
  inv[t-1] + make + sum buy + sum ship_in(t - transit) - sum ship_out - consensus + unmet = inv[t]
  inv + ss_short >= ss_target;  sum_f make x hpu <= eff_hours[n,g,t];  buy <= cap_per_month;  unmet <= consensus
  allocation / sourcing shares over the horizon: min_share x total <= source <= max_share x total
  enforce_milestones: sum dom_s x supply_s >= min x sum supply_s per milestone family.
Objective: (1) min sum unmet x weight; (2) fix (1) <= opt + 0.5, min sum ss_short; (3) fix (2) <= opt + 0.5, min
cost (conversion + landed + freight + holding). Hard constraints are never traded against cost. A non-optimal
status -> `SopResult.status = <status>` (the caller fails the scenario with `SOP_LP_<STATUS>`). Results are rounded
to whole units with cumulative rounding per series and rebalanced (inventory, unmet) so the plan stays consistent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from ortools.linear_solver import pywraplp

from .model import SopProblem, SopResult

STATUS = {pywraplp.Solver.OPTIMAL: "optimal", pywraplp.Solver.FEASIBLE: "feasible",
          pywraplp.Solver.INFEASIBLE: "infeasible", pywraplp.Solver.UNBOUNDED: "unbounded",
          pywraplp.Solver.ABNORMAL: "abnormal", pywraplp.Solver.NOT_SOLVED: "not_solved"}


def solve(p: SopProblem) -> SopResult:
    S = pywraplp.Solver.CreateSolver("GLOP")
    inf = S.infinity()
    T = list(p.months)
    tidx = {t: i for i, t in enumerate(T)}
    nodes, fams = list(p.nodes), list(p.families)
    make: dict[tuple[str, str, date], Any] = {}
    buy: dict[tuple[int, date], Any] = {}
    ship: dict[tuple[str, str, date], Any] = {}
    inv: dict[tuple[str, str, date], Any] = {}
    unmet: dict[tuple[str, str, date], Any] = {}
    ssv: dict[tuple[str, str, date], Any] = {}
    for n in nodes:
        for f in fams:
            for t in T:
                inv[(n, f, t)] = S.NumVar(0, inf, "")
                d = p.demand.get((n, f, t), 0.0)
                if d > 0:
                    unmet[(n, f, t)] = S.NumVar(0, d, "")
                if p.ss_target.get((n, f), 0.0) > 0:
                    ssv[(n, f, t)] = S.NumVar(0, inf, "")
                if (n, f) in p.make_allowed:
                    make[(n, f, t)] = S.NumVar(0, inf, "")
    for i, b in enumerate(p.buys):
        if b.landed is None:
            continue
        for t in T:
            buy[(i, t)] = S.NumVar(0, b.cap_per_month if b.cap_per_month is not None else inf, "")
    lanes = {ln.id: ln for ln in p.lanes}
    for ln in p.lanes:
        for f in (sorted(ln.families) if ln.families is not None else fams):
            if f not in fams:
                continue
            for t in T:
                if tidx[t] + ln.transit_months < len(T):
                    ship[(ln.id, f, t)] = S.NumVar(0, inf, "")
    # balance
    for n in nodes:
        for f in fams:
            for i, t in enumerate(T):
                e = inv[(n, f, t)]
                prev = inv[(n, f, T[i - 1])] if i else None
                ins = []
                if (n, f, t) in make:
                    ins.append(make[(n, f, t)])
                ins += [buy[(j, t)] for j, b in enumerate(p.buys) if b.node == n and b.family == f and (j, t) in buy]
                outs = []
                for (lid, ff, ts), v in ship.items():
                    if ff != f:
                        continue
                    ln = lanes[lid]
                    if ln.dst == n and tidx[ts] + ln.transit_months == i:
                        ins.append(v)
                    if ln.src == n and ts == t:
                        outs.append(v)
                c = S.Constraint(p.demand.get((n, f, t), 0.0) - (p.init_inv.get((n, f), 0.0) if not i else 0.0),
                                 p.demand.get((n, f, t), 0.0) - (p.init_inv.get((n, f), 0.0) if not i else 0.0))
                for v in ins:
                    c.SetCoefficient(v, 1)
                for v in outs:
                    c.SetCoefficient(v, -1)
                if prev is not None:
                    c.SetCoefficient(prev, 1)
                if (n, f, t) in unmet:
                    c.SetCoefficient(unmet[(n, f, t)], 1)
                c.SetCoefficient(e, -1)
                if (n, f, t) in ssv:
                    s = S.Constraint(p.ss_target[(n, f)], inf)
                    s.SetCoefficient(e, 1)
                    s.SetCoefficient(ssv[(n, f, t)], 1)
    # capacity
    groups: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for (n, g, f), h in p.hpu.items():
        groups[(n, g)].append((f, h))
    cap_cons: dict[tuple[str, str, date], Any] = {}
    for (n, g), fh in groups.items():
        for t in T:
            c = S.Constraint(-inf, max(p.hours.get((n, g, t), 0.0), 0.0))
            for f, h in fh:
                if (n, f, t) in make:
                    c.SetCoefficient(make[(n, f, t)], h)
            cap_cons[(n, g, t)] = c
    # supplier allocation shares (horizon totals)
    share_sets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for j, b in enumerate(p.buys):
        if b.landed is not None and (b.min_share > 0 or b.max_share < 1):
            share_sets[(b.node, b.family)].append(j)
    for (n, f), js in share_sets.items():
        allj = [j for j, b in enumerate(p.buys) if b.node == n and b.family == f and b.landed is not None]
        for j in js:
            b = p.buys[j]
            lo = S.Constraint(0, inf)
            hi = S.Constraint(-inf, 0)
            for jj in allj:
                for t in T:
                    v = buy[(jj, t)]
                    own = 1.0 if jj == j else 0.0
                    lo.SetCoefficient(v, own - b.min_share)
                    hi.SetCoefficient(v, own - b.max_share)
    for (dest, f), rows in p.ship_shares.items():
        inbound = [lid for lid, _lo, _hi in rows]
        for lid, mn, mx in rows:
            lo = S.Constraint(0, inf)
            hi = S.Constraint(-inf, 0)
            for (l2, ff, t), v in ship.items():
                if ff != f or l2 not in inbound:
                    continue
                own = 1.0 if l2 == lid else 0.0
                lo.SetCoefficient(v, own - mn)
                hi.SetCoefficient(v, own - mx)
    # milestones (domestic share of supply per family)
    ms_cons: dict[str, Any] = {}
    for m in p.milestones:
        f, mn = m["family"], float(m["min_share"])
        c = S.Constraint(0, inf)
        for (n, ff, t), v in make.items():
            if ff == f:
                c.SetCoefficient(v, p.make_domestic.get((n, f), 0.0) - mn)
        for (j, t), v in buy.items():
            b = p.buys[j]
            if b.family == f:
                c.SetCoefficient(v, b.domestic - mn)
        ms_cons[f] = c
    res = SopResult(status="optimal")
    # tier 1: unmet
    obj = S.Objective()
    for k, v in unmet.items():
        obj.SetCoefficient(v, p.priority_weight.get(k, 1.0))
    obj.SetMinimization()
    st = S.Solve()
    if st != pywraplp.Solver.OPTIMAL:
        return SopResult(status=STATUS.get(st, str(st)))
    o1 = obj.Value()
    binding_ms = {f for f, c in ms_cons.items() if abs(c.dual_value()) > 1e-9}
    fix1 = S.Constraint(-inf, o1 + 0.5)
    for k, v in unmet.items():
        fix1.SetCoefficient(v, p.priority_weight.get(k, 1.0))
    # tier 2: safety stock
    obj.Clear()
    for v in ssv.values():
        obj.SetCoefficient(v, 1.0)
    obj.SetMinimization()
    st = S.Solve()
    if st != pywraplp.Solver.OPTIMAL:
        return SopResult(status=STATUS.get(st, str(st)))
    o2 = obj.Value()
    fix2 = S.Constraint(-inf, o2 + 0.5)
    for v in ssv.values():
        fix2.SetCoefficient(v, 1.0)
    # tier 3: cost
    obj.Clear()
    for (n, f, t), v in make.items():
        obj.SetCoefficient(v, p.conv_cost.get((n, f), 0.0))
    for (j, t), v in buy.items():
        obj.SetCoefficient(v, float(p.buys[j].landed or 0.0))
    for (lid, f, t), v in ship.items():
        obj.SetCoefficient(v, lanes[lid].freight_per_unit)
    for (n, f, t), v in inv.items():
        obj.SetCoefficient(v, p.std_cost.get((n, f), 0.0) * p.holding_rate / 12.0)
    obj.SetMinimization()
    st = S.Solve()
    if st != pywraplp.Solver.OPTIMAL:
        return SopResult(status=STATUS.get(st, str(st)))
    res.objective = {"unmet": round(o1, 6), "ss_short": round(o2, 6), "cost": round(obj.Value() + p.fixed_cost, 6)}
    raw_make = {k: v.solution_value() for k, v in make.items()}
    raw_buy = {(p.buys[j].node, p.buys[j].family, p.buys[j].code, t): v.solution_value() for (j, t), v in buy.items()}
    raw_ship = {k: v.solution_value() for k, v in ship.items()}
    res.make = _cum_round(raw_make, T)
    res.buy = _cum_round(raw_buy, T)
    res.ship = _cum_round(raw_ship, T)
    rebalance(p, res)
    for (n, f, t), q in res.unmet.items():
        if q > 0.5:
            cause = "SOP_MILESTONE" if f in binding_ms else "SOP_CAPACITY"
            res.explanations.append({"code": cause, "node": n, "family": f, "month": t.isoformat(),
                                     "detail": {"unmet": q}})
    return res


def _cum_round(vals: dict[tuple, float], months: list[date]) -> dict[tuple, float]:
    """Whole units with cumulative rounding per series (the month is the last key element)."""
    series: dict[tuple, list[tuple[date, float]]] = defaultdict(list)
    for k, v in vals.items():
        series[k[:-1]].append((k[-1], v))
    out: dict[tuple, float] = {}
    for s, pts in series.items():
        cum, prev = 0.0, 0
        for t, v in sorted(pts):
            cum += max(v, 0.0)
            r = int(round(cum + 1e-9))
            q = r - prev
            prev = r
            if q:
                out[(*s, t)] = float(q)
    return out


def rebalance(p: SopProblem, res: SopResult) -> None:
    """Inventory, unmet and SS shortfall from the (rounded) flows: unmet = the part of consensus that cannot be
    delivered; shipments beyond what a node holds are cut back to what is available."""
    T = list(p.months)
    idx = {t: i for i, t in enumerate(T)}
    lanes = {ln.id: ln for ln in p.lanes}
    inflow: dict[tuple[str, str, date], float] = defaultdict(float)
    for (n, f, t), q in res.make.items():
        inflow[(n, f, t)] += q
    for (n, f, _c, t), q in res.buy.items():
        inflow[(n, f, t)] += q
    out_by: dict[tuple[str, str, date], list[tuple[str, date]]] = defaultdict(list)
    for (lid, f, t) in res.ship:
        out_by[(lanes[lid].src, f, t)].append((lid, t))
    res.inv, res.unmet, res.ss_short = {}, {}, {}
    arrivals: dict[tuple[str, str, date], float] = defaultdict(float)
    # months outer; inside a month sources before destinations (same-month arrivals of 0-month lanes)
    order: list[str] = []
    succ: dict[str, set[str]] = defaultdict(set)
    for ln in p.lanes:
        if ln.transit_months == 0 and ln.src != ln.dst:
            succ[ln.src].add(ln.dst)
    seen: set[str] = set()

    def visit(n: str, stack: set[str]) -> None:
        if n in seen or n in stack:
            return
        stack.add(n)
        for m in sorted(succ.get(n, ())):
            visit(m, stack)
        stack.discard(n)
        seen.add(n)
        order.append(n)
    for n in p.nodes:
        visit(n, set())
    order.reverse()
    for t in T:
        for n in order:
            for f in p.families:
                i = idx[t]
                prev = res.inv.get((n, f, T[i - 1]), 0.0) if i else p.init_inv.get((n, f), 0.0)
                avail = prev + inflow.get((n, f, t), 0.0) + arrivals.get((n, f, t), 0.0)
                d = p.demand.get((n, f, t), 0.0)
                outs = sorted(out_by.get((n, f, t), []))
                want = sum(res.ship[(lid, f, ts)] for lid, ts in outs)
                deliver = min(d, avail)
                left = avail - deliver
                if want > left + 1e-9:                   # rounding pushed shipments above stock: cut the last ones
                    over = want - left
                    for lid, ts in reversed(outs):
                        cut = min(over, res.ship[(lid, f, ts)])
                        res.ship[(lid, f, ts)] -= cut
                        over -= cut
                        if over <= 1e-9:
                            break
                    want = sum(res.ship[(lid, f, ts)] for lid, ts in outs)
                for lid, ts in outs:
                    q = res.ship[(lid, f, ts)]
                    ln = lanes[lid]
                    if q > 0 and idx[ts] + ln.transit_months < len(T):
                        arrivals[(ln.dst, f, T[idx[ts] + ln.transit_months])] += q
                inv = round(avail - deliver - want, 6)
                res.inv[(n, f, t)] = max(inv, 0.0)
                if d - deliver > 1e-9:
                    res.unmet[(n, f, t)] = round(d - deliver, 6)
                ss = p.ss_target.get((n, f), 0.0)
                if ss > 0 and res.inv[(n, f, t)] < ss - 1e-9:
                    res.ss_short[(n, f, t)] = round(ss - res.inv[(n, f, t)], 6)
    res.ship = {k: v for k, v in res.ship.items() if v > 0}
