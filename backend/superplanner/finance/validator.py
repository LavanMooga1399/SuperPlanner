"""Independent validator (FINANCE.md section 11).

Recomputes cash, buckets, caps and locks from the plan document and the result's published decisions
(contribution lines, holdings assignment, rebalances, per-goal planning z) with its own projection. It imports
only `model`, `defaults`, `timegrid`, `cashflow`, `returns` (tested), never the optimizer or the simulator.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from . import timegrid as tg
from .cashflow import ef_complete_t, locked_index, project_cashflow
from .model import FinancePlan, FinanceResult, FinanceViolation
from .returns import (active_caps, allowed_classes, gamma, goal_cap, inflation_vol, initial_z, is_equity, is_risky,
                      min_probability, mix_cap_applies, pi_general,
                      planning_rho, real_target)

SHARE_TOL = 0.005
MIX_ABS_TOL = 0.01


@dataclass
class BlockRecord:
    k: int
    s: int
    n: int
    F: dict[str, float]        # value before the rebalance at the block start
    sells: dict[str, float]
    buys: dict[str, float]
    H: dict[str, float]        # value right after the rebalance


def replay_goal(classes: dict, rho: dict[str, float], F0: dict[str, float], blocks: list[tuple[int, int, int]],
                rebalance: Callable[[int, int, dict[str, float]], tuple[dict[str, float], dict[str, float]]],
                x_by_class: dict[str, dict[int, float]]) -> tuple[list[BlockRecord], dict[str, float]]:
    """Plan-basis bucket of one goal from its decisions (8.4 rules 3 and 5, month by month).

    A contribution paid at the start of month t grows by `rho^(block_end - t)`, so a level amount over the
    last n months of a block grows by exactly `Phi(n)`. Used by the validator and by the pipeline when it
    publishes `planned_value_real`, so both always agree."""
    F: dict[str, float] = defaultdict(float, F0)
    records: list[BlockRecord] = []
    for (k, s, n) in blocks:
        sells, buys = rebalance(k, s, dict(F))
        H = {a: F.get(a, 0.0) - sells.get(a, 0.0) + buys.get(a, 0.0) for a in set(F) | set(sells) | set(buys)}
        records.append(BlockRecord(k=k, s=s, n=n, F=dict(F), sells=dict(sells), buys=dict(buys), H=H))
        end = s + n
        Fn: dict[str, float] = defaultdict(float)
        for a, v in H.items():
            Fn[a] += v * rho.get(a, 1.0) ** n
        for a, by_t in x_by_class.items():
            r = rho.get(a, 1.0)
            for t, v in by_t.items():
                if s <= t < end:
                    Fn[a] += v * r ** (end - t)
        F = Fn
    return records, dict(F)


def allowance(classes: dict, rho: dict[str, float], locked_pos: list[tuple[str, float, int]], F: dict[str, float],
              s: int) -> dict[str, float]:
    """Locked-position allowance per class at block start `s` (8.4 rules 7 and 9, [R8])."""
    out: dict[str, float] = defaultdict(float)
    for (c, amt, li) in locked_pos:
        if li > s and c in classes:
            out[c] += amt * rho[c] ** s
    for a, ac in classes.items():
        if ac.lock_in_months > 0:
            out[a] += F.get(a, 0.0)
    return dict(out)


def _runs(ts: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for t in sorted(set(ts)):
        if out and t == out[-1][1] + 1:
            out[-1] = (out[-1][0], t)
        else:
            out.append((t, t))
    return out


def _months(months: list[str], a: int, b: int) -> list[str]:
    def m(t: int) -> str:
        return months[t] if 0 <= t < len(months) else str(t)
    return [m(a)] if a == b else [m(a), m(b)]


def tolerances(plan: FinancePlan) -> tuple[float, dict[str, float]]:
    """`tol = max(1, 1e-6 max TR)`, `tol_g = max(tol, 0.001 TR_g)`."""
    start = plan.start_month
    trs = {g.id: real_target(plan, g, tg.month_index(start, g.target_month)) for g in plan.goals if g.enabled}
    tol = max(1.0, 1e-6 * max(trs.values(), default=0.0))
    return tol, {gid: max(tol, 0.001 * tr) for gid, tr in trs.items()}


def validate_result(plan: FinancePlan, result: FinanceResult) -> list[FinanceViolation]:
    out: list[FinanceViolation] = []

    def add(code: str, sev: str, msg: str, **kw: Any) -> None:
        out.append(FinanceViolation(code=code, severity=sev, message=msg, **kw))

    start = plan.start_month
    proj = project_cashflow(plan)
    T = proj.T
    months = proj.months
    tE = ef_complete_t(proj)
    pi = pi_general(plan)
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    tau = plan.constraints.rebalance_cost_pct / 100.0
    m_buf = plan.constraints.min_cash_buffer
    cash_ac = classes.get(plan.assumptions.cash_class_id)
    g_c = gamma(cash_ac, pi) if cash_ac is not None else 1.0
    goals = [g for g in plan.goals if g.enabled]
    gmap = {g.id: g for g in goals}
    Dg = {g.id: tg.month_index(start, g.target_month) for g in goals}
    TR = {g.id: real_target(plan, g, Dg[g.id]) for g in goals}
    tol, tol_g = tolerances(plan)
    L = plan.constraints.contribution_block_months
    gres = {gr.goal_id: gr for gr in result.goals}
    holdings = {h.id: h for h in plan.holdings}

    # ---------------- contributions expanded to months
    x: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    X = [0.0] * T
    for line in result.contributions:
        if line.goal_id == "emergency_fund":
            continue
        t0 = tg.month_index(start, line.start_month)
        t1 = tg.month_index(start, line.end_month)
        amt = line.monthly_amount_real
        g = gmap.get(line.goal_id)
        if amt < 0:
            add("CONTRIBUTION_NEGATIVE", "hard", f"A contribution to {line.goal_id} is negative.",
                goal_id=line.goal_id, asset_class_id=line.asset_class_id, amount=amt,
                months=_months(months, t0, t1))
            continue
        if g is None:
            add("CONTRIBUTION_AFTER_GOAL", "hard", f'Contributions go to "{line.goal_id}", which is not an enabled '
                "goal of the plan.", goal_id=line.goal_id, months=_months(months, t0, t1))
            continue
        D = Dg[g.id]
        allowed = set(allowed_classes(plan, g))
        ac = classes.get(line.asset_class_id)
        if ac is None or line.asset_class_id not in allowed:
            add("CLASS_NOT_ALLOWED", "hard", f'Goal "{g.name}" receives contributions in a class it does not allow.',
                goal_id=g.id, asset_class_id=line.asset_class_id, months=_months(months, t0, t1))
        if t0 < 0 or t1 >= D:
            add("CONTRIBUTION_AFTER_GOAL", "hard", f'Goal "{g.name}" receives contributions outside the months '
                "before it is due.", goal_id=g.id, asset_class_id=line.asset_class_id,
                months=_months(months, max(t0, D), t1))
        if ac is not None and ac.lock_in_months > 0:
            bad = [t for t in range(t0, t1 + 1) if t + ac.lock_in_months > D]
            if bad:
                add("LOCKIN_PAST_GOAL", "hard", f'Contributions to "{g.name}" in {ac.name} would stay locked after the '
                    "goal date.", goal_id=g.id, asset_class_id=ac.id, months=_months(months, bad[0], bad[-1]))
        if g.priority in ("should", "nice") and amt > 0 and t0 < tE:
            add("EF_BEFORE_DISCRETIONARY", "hard", f'Goal "{g.name}" receives contributions before the emergency fund '
                "is complete.", goal_id=g.id, months=_months(months, t0, min(t1, tE - 1)))
        for t in range(max(t0, 0), min(t1, T - 1) + 1):
            x[g.id][line.asset_class_id][t] += amt
            X[t] += amt

    # ---------------- holdings
    # The t = 0 splits (earmarks, initial EF, initial cash buffer) and the assignable pool come from the
    # validator's own projection; the result's rows must match them, and LP rows ("assigned", "sold_to_cash")
    # may only use pool items under the same rules as the optimizer (8.3: unlocked by the goal date, a class the
    # goal allows; only unlocked items may be sold).
    expected_split: dict[tuple[str, str, str], float] = defaultdict(float)
    for sp in proj.initial_splits:
        if sp.source != "pool":
            expected_split[(sp.holding_id, sp.source, sp.goal_id or "cash_buffer")] += sp.amount
    pool = {p.holding_id: p for p in proj.assignable}
    reported_split: dict[tuple[str, str, str], float] = defaultdict(float)
    per_holding: dict[str, float] = defaultdict(float)
    from_pool: dict[str, float] = defaultdict(float)
    assigned: dict[str, list[tuple[str, float, int | None]]] = defaultdict(list)  # goal -> (class, amt, lock)
    sold = 0.0
    for row in result.holdings_assignment:
        if row.source == "unallocated":
            continue
        h = holdings.get(row.holding_id)
        hname = h.name if h is not None else row.holding_id
        per_holding[row.holding_id] += row.amount
        if row.amount < -tol:
            add("HOLDING_NOT_ASSIGNABLE", "hard", f'A negative amount is taken from holding "{hname}".',
                amount=row.amount, details={"holding_id": row.holding_id})
            continue
        if row.source in ("earmark", "initial_ef", "initial_cash"):
            reported_split[(row.holding_id, row.source, row.goal_id)] += row.amount
            continue
        p = pool.get(row.holding_id)
        if p is None:
            add("HOLDING_NOT_ASSIGNABLE", "hard", f'Holding "{hname}" is not available to assign or sell (it is '
                "earmarked, used for the emergency fund or the cash buffer, or unknown).", goal_id=row.goal_id,
                amount=row.amount, details={"holding_id": row.holding_id, "source": row.source})
            continue
        from_pool[row.holding_id] += row.amount
        if row.source == "sold_to_cash":
            sold += row.amount
            if p.locked_until_index is not None and h is not None:
                add("LOCKED_SOLD", "hard", f'Holding "{h.name}" is sold before it is unlocked ({h.locked_until_month}).',
                    amount=row.amount, details={"holding_id": h.id})
            continue
        # source == "assigned"
        g = gmap.get(row.goal_id)
        if g is None:
            add("HOLDING_NOT_ASSIGNABLE", "hard", f'Holding "{hname}" is assigned to "{row.goal_id}", which is not an '
                "enabled goal of the plan.", goal_id=row.goal_id, amount=row.amount,
                details={"holding_id": row.holding_id})
            continue
        D = Dg[g.id]
        if p.asset_class_id not in set(allowed_classes(plan, g)):
            add("CLASS_NOT_ALLOWED", "hard", f'Holding "{hname}" is assigned to "{g.name}", which does not allow its '
                "class.", goal_id=g.id, asset_class_id=p.asset_class_id, amount=row.amount,
                details={"holding_id": row.holding_id})
        if p.locked_until_index is not None and p.locked_until_index > D:
            add("LOCKIN_PAST_GOAL", "hard", f'Holding "{hname}" is assigned to "{g.name}" but stays locked until '
                f"{h.locked_until_month if h else '?'}, after the goal date.", goal_id=g.id,
                asset_class_id=p.asset_class_id, amount=row.amount, details={"holding_id": row.holding_id})
        assigned[g.id].append((p.asset_class_id, row.amount, p.locked_until_index))
    for key in sorted(set(expected_split) | set(reported_split)):
        exp_v, rep_v = expected_split.get(key, 0.0), reported_split.get(key, 0.0)
        if abs(exp_v - rep_v) > tol:
            hid, src, gid = key
            h = holdings.get(hid)
            add("HOLDING_SPLIT_MISMATCH", "hard", f'The {src.replace("_", " ")} amount reported for holding '
                f'"{h.name if h else hid}" does not match the plan.', goal_id=gid, amount=rep_v - exp_v,
                details={"holding_id": hid, "source": src, "reported": rep_v, "expected": exp_v})
    over: set[str] = set()
    for hid, amt in from_pool.items():
        cap = pool[hid].amount
        if amt > cap + tol:
            over.add(hid)
            h = holdings.get(hid)
            add("HOLDING_OVERASSIGNED", "hard", f'More is taken from holding "{h.name if h else hid}" than is free '
                "to assign.", amount=amt - cap, details={"holding_id": hid})
    for hid, amt in per_holding.items():
        h = holdings.get(hid)
        cap = h.amount if h is not None else 0.0
        if amt > cap + tol and hid not in over:
            add("HOLDING_OVERASSIGNED", "hard", f'More is taken from holding "{h.name if h else hid}" than it holds.',
                amount=amt - cap, details={"holding_id": hid})

    # ---------------- cash
    B = proj.cash_buffer_initial + (1.0 - tau) * sold
    bad_cash: list[int] = []
    worst: dict[int, float] = {}
    for t in range(T):
        avail = B + proj.investable[t] - X[t]
        if avail < m_buf - tol:
            bad_cash.append(t)
            worst[t] = m_buf - avail
        B = avail * g_c
    for a, b in _runs(bad_cash):
        add("CASH_NEGATIVE", "hard", "Free cash falls below the minimum buffer: planned spending and contributions "
            "need more money than is available.", months=_months(months, a, b),
            amount=round(max(worst[t] for t in range(a, b + 1)), 2))

    # ---------------- rebalances index (only at block starts of enabled goals before their date, 8.3)
    reb: dict[tuple[str, int], tuple[dict[str, float], dict[str, float]]] = {}
    starts = {g.id: {s_ for (_, s_, _) in tg.blocks(Dg[g.id], L)} for g in goals}
    for r in result.rebalances:
        key = (r.goal_id, tg.month_index(start, r.month))
        if key[1] not in starts.get(r.goal_id, set()):
            g = gmap.get(r.goal_id)
            add("REBALANCE_OFF_SCHEDULE", "hard", f'A rebalance of "{g.name if g else r.goal_id}" in {r.month} is not '
                "at a block start of an enabled goal before its date.", goal_id=r.goal_id, months=[r.month],
                details={"sells": dict(r.sells), "buys": dict(r.buys)})
            continue
        sells, buys = reb.get(key, ({}, {}))
        sells = dict(sells)
        buys = dict(buys)
        for a, v in r.sells.items():
            sells[a] = sells.get(a, 0.0) + v
        for a, v in r.buys.items():
            buys[a] = buys.get(a, 0.0) + v
        reb[key] = (sells, buys)

    # ---------------- buckets per goal
    glob_H: dict[int, list[tuple[dict[str, float], dict[str, float]]]] = defaultdict(list)  # k -> [(H, LRbycls)]
    for g in goals:
        D = Dg[g.id]
        gr = gres.get(g.id)
        z = gr.planning_z if gr is not None else initial_z(g)
        rho = {a: planning_rho(ac, pi, z, D, inflation_vol(plan)) for a, ac in classes.items()}
        allowed = set(allowed_classes(plan, g))
        F: dict[str, float] = defaultdict(float)
        locked_pos: list[tuple[str, float, int]] = []
        for (hid, src, gid_), amt in expected_split.items():   # earmarks from the validator's own projection
            h = holdings.get(hid)
            if src != "earmark" or gid_ != g.id or h is None:
                continue
            F[h.asset_class_id] += amt
            li = locked_index(plan, h.locked_until_month)
            if li is not None and li > 0:
                locked_pos.append((h.asset_class_id, amt, li))
        for (c, amt, li) in assigned.get(g.id, []):
            F[c] += amt
            if li is not None and li > 0:
                locked_pos.append((c, amt, li))
        risk_reported = mix_reported = False
        records, F = replay_goal(classes, rho, F, tg.blocks(D, L), lambda k, s, Fb: reb.get((g.id, s), ({}, {})),
                                 x[g.id])
        for rec in records:
            k, s, n, Fb, sells, buys, H = rec.k, rec.s, rec.n, rec.F, rec.sells, rec.buys, rec.H

            def locked_val(a: str) -> float:
                return sum(amt * rho[c] ** s for (c, amt, li) in locked_pos if c == a and li > s)
            for a, v in sells.items():
                ac = classes.get(a)
                if v < -tol:
                    add("REBALANCE_UNBALANCED", "hard", f'A rebalance of "{g.name}" has a negative sell amount.',
                        goal_id=g.id, asset_class_id=a, months=[months[s]])
                if ac is not None and ac.lock_in_months > 0 and v > tol:
                    add("LOCKED_SOLD", "hard", f'"{g.name}" sells {ac.name}, which has a lock-in.', goal_id=g.id,
                        asset_class_id=a, months=[months[s]], amount=v)
                elif v > Fb.get(a, 0.0) - locked_val(a) + tol:
                    if locked_val(a) > 0:
                        add("LOCKED_SOLD", "hard", f'"{g.name}" sells a holding that is still locked.', goal_id=g.id,
                            asset_class_id=a, months=[months[s]], amount=v)
                    else:
                        add("REBALANCE_UNBALANCED", "hard", f'A rebalance of "{g.name}" sells more than the bucket '
                            "holds.", goal_id=g.id, asset_class_id=a, months=[months[s]], amount=v)
            for a, v in buys.items():
                ac = classes.get(a)
                if v < -tol:
                    add("REBALANCE_UNBALANCED", "hard", f'A rebalance of "{g.name}" has a negative buy amount.',
                        goal_id=g.id, asset_class_id=a, months=[months[s]])
                if v > tol and (ac is None or a not in allowed):
                    add("CLASS_NOT_ALLOWED", "hard", f'A rebalance of "{g.name}" buys a class the goal does not '
                        "allow.", goal_id=g.id, asset_class_id=a, months=[months[s]])
                if v > tol and ac is not None and ac.lock_in_months > 0 and s + ac.lock_in_months > D:
                    add("LOCKIN_PAST_GOAL", "hard", f'A rebalance of "{g.name}" buys {ac.name}, whose lock-in would end '
                        "after the goal date.", goal_id=g.id, asset_class_id=a, months=[months[s]])
            if sells or buys:
                diff = sum(buys.values()) - (1.0 - tau) * sum(sells.values())
                if abs(diff) > tol:
                    add("REBALANCE_UNBALANCED", "hard", f'A rebalance of "{g.name}" buys a different amount than it '
                        "sells (after costs).", goal_id=g.id, months=[months[s]], amount=diff)
            LR_cls = allowance(classes, rho, locked_pos, Fb, s)
            cap = goal_cap(plan, g, D, s)
            total = sum(H.values())
            risky = sum(v for a, v in H.items() if a in classes and is_risky(classes[a]))
            LR = sum(v for a, v in LR_cls.items() if is_risky(classes[a]))
            if (not risk_reported and active_caps(plan, g, D, s).risk
                    and risky - LR > (cap + SHARE_TOL) * total + tol):
                risk_reported = True
                add("RISK_CAP_EXCEEDED", "hard", f'"{g.name}" holds more growth assets than its cap of '
                    f"{cap * 100:.0f}% allows.", goal_id=g.id, months=[months[s]],
                    details={"cap": cap, "share": risky / total if total else 0.0})
            for t in range(s, s + n):
                tot_x = sum(x[g.id][a].get(t, 0.0) for a in x[g.id])
                risky_x = sum(x[g.id][a].get(t, 0.0) for a in x[g.id] if a in classes and is_risky(classes[a]))
                if (not mix_reported and mix_cap_applies(plan, g, D, s, n)
                        and risky_x > (cap + SHARE_TOL) * tot_x + MIX_ABS_TOL):
                    mix_reported = True
                    add("RISK_CAP_EXCEEDED", "hard", f'The contribution mix of "{g.name}" puts more into growth assets '
                        f"than its cap of {cap * 100:.0f}% allows.", goal_id=g.id, months=[months[t]],
                        details={"cap": cap})
            glob_H[k].append((H, LR_cls, g, D))
        value = sum(F.values())
        if gr is not None:
            if abs(gr.planned_value_real - value) > max(tol, 0.001 * TR[g.id]):
                add("BUCKET_MISMATCH", "hard", f'The reported planned value of "{g.name}" does not match the published '
                    "decisions.", goal_id=g.id, amount=gr.planned_value_real - value,
                    details={"reported": gr.planned_value_real, "recomputed": value})
            if gr.success_probability < min_probability(g) - 1e-9:
                add("GOAL_PROBABILITY_LOW", "soft", f'The estimated chance for "{g.name}" is below the level you asked '
                    "for.", goal_id=g.id, details={"probability": gr.success_probability,
                                                   "minimum": min_probability(g)})
        if value < TR[g.id] - tol_g[g.id]:
            add("GOAL_SHORTFALL", "soft", f'"{g.name}" is planned to reach less than its target.', goal_id=g.id,
                amount=round(TR[g.id] - value, 2), months=[g.target_month])

    # ---------------- global caps (blocks are aligned to the plan start)
    maxeq = plan.constraints.max_equity_pct
    caps = dict(plan.constraints.max_class_pct)
    for k, entries in sorted(glob_H.items()):
        s = k * L
        total = sum(sum(H.values()) for H, _, _, _ in entries)
        if maxeq is not None:
            eq = lr = 0.0
            for H, LRc, g, D in entries:
                held = sum(v for a, v in H.items() if a in classes and is_equity(classes[a]))
                eq += held
                lr += held if not active_caps(plan, g, D, s).equity else sum(
                    v for a, v in LRc.items() if is_equity(classes[a]))
            if eq - lr > (maxeq / 100.0 + SHARE_TOL) * total + tol:
                add("EQUITY_CAP_EXCEEDED", "hard", f"Equity is above the {maxeq:g}% limit across goals.",
                    months=[months[s]], details={"share": eq / total if total else 0.0})
        for a, pct in caps.items():
            v = lr = 0.0
            for H, LRc, g, D in entries:
                held = H.get(a, 0.0)
                v += held
                lr += held if a not in active_caps(plan, g, D, s).classes else LRc.get(a, 0.0)
            if v - lr > (pct / 100.0 + SHARE_TOL) * total + tol:
                add("CLASS_CAP_EXCEEDED", "hard", f"{classes[a].name if a in classes else a} is above its {pct:g}% "
                    "limit across goals.", asset_class_id=a, months=[months[s]])

    if result.summary.liquidity_risk_probability > 0.10:
        add("LIQUIDITY_RISK", "soft", "In more than 10% of simulated outcomes there is at least one month without "
            "enough cash.", details={"probability": result.summary.liquidity_risk_probability})
    return out


def hard_violations(vs: list[FinanceViolation]) -> list[FinanceViolation]:
    return [v for v in vs if v.severity == "hard"]
