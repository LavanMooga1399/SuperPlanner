"""Fix search (FINANCE.md 12.3).

Every candidate plan is built with `apply_what_if(plan, fix.what_if)`, so the payload a user would POST is
exactly the plan that was re-solved. Each re-solve is one LP that keeps the higher tiers at their optimal values
and every sibling goal of the same tier at or below its current shortfall [R13], then minimizes the goal's
shortfall (or, for INCREASE_SAVINGS, the extra monthly amount with a zero shortfall).
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable

from .. import timegrid as tg
from ..cashflow import ef_complete_t, project_cashflow
from ..model import (CashflowProjection, FinancePlan, FinanceResult, Fix, GoalOverride, WhatIfChanges)
from ..optimizer import SCALE, TIER_ABS_EPS, FinanceLP, OptimizerSolution, _Expr
from ..preflight import preflight
from ..returns import floor2, pi_general, tolerance_of
from ..validator import tolerances
from ..whatif import apply_what_if
from .messages import format_money, render

DELAYS = (1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 60)
MAX_SOLVES = 30
MAX_GOALS = 3
CRITERION_SHARE = 0.5          # LP shortfall must be <= 0.5 tol_g (headroom for the flooring of 8.8)
TIER_NAME = {"must": "T1", "should": "T2", "nice": "T3"}
ORDER = ("must", "should", "nice")

QuickProb = Callable[[FinancePlan, CashflowProjection, OptimizerSolution, dict, str], float | None]


class _Budget:
    def __init__(self, deadline: float):
        self.deadline = deadline
        self.solves = 0
        self.truncated = False

    def ok(self) -> bool:
        if self.solves >= MAX_SOLVES or time.monotonic() >= self.deadline:
            self.truncated = True
            return False
        return True


def extra_savings_profile(plan: FinancePlan, T: int, tE: int) -> list[float]:
    """Real value per month of 1/month added as the what-if income `whatif_extra` (nominal, growth = inflation,
    stepped on anniversaries). Months before `t_E` count as 0 (the EF waterfall may absorb them; conservative)."""
    pi = pi_general(plan)
    return [((1 + pi) ** (t // 12)) / ((1 + pi) ** (t / 12)) if t >= tE else 0.0 for t in range(T)]


def _bounds(lp: FinanceLP, base: OptimizerSolution, gid: str) -> list[tuple[_Expr, float]]:
    tier = base.goals[gid].tier
    out: list[tuple[_Expr, float]] = []

    def eps(v: float, name: str = "T0") -> float:
        return v + lp.tier_eps(name, v)
    if "T0" in base.tier_values:
        out.append((lp.obj_T0, eps(base.tier_values["T0"])))
    for p in ORDER:
        if p == tier:
            break
        name = TIER_NAME[p]
        if p in lp.eta and name + "a" in base.tier_values:
            out.append((_Expr().add(lp.eta[p], 1.0), eps(base.tier_values[name + "a"], name + "a")))
        if p in lp.obj_frac and name + "b" in base.tier_values:
            out.append((lp.obj_frac[p], eps(base.tier_values[name + "b"], name + "b")))
    for h, hd in base.goals.items():
        if h != gid and hd.tier == tier and h in lp.short:
            out.append((_Expr().add(lp.short[h], 1.0), base.short[h] * SCALE + TIER_ABS_EPS))
    return out


def compute_fixes(plan: FinancePlan, proj: CashflowProjection, base: OptimizerSolution, result: FinanceResult, *,
                  deadline: float, cancel_event: threading.Event | None = None,
                  quick_probability: QuickProb | None = None,
                  progress: Callable[[float], None] | None = None) -> tuple[dict[str, list[Fix]], int, bool]:
    cur = plan.profile.currency
    budget = _Budget(deadline)
    _, tol_g = tolerances(plan)
    z_base = {g.goal_id: g.planning_z for g in result.goals}
    cands = [g for g in result.goals if g.status != "on_track"]
    cands.sort(key=lambda g: (ORDER.index(g.priority), g.months_to_goal))
    cands = cands[:MAX_GOALS]
    out: dict[str, list[Fix]] = {}
    pos_surplus = sum(max(v, 0.0) for v in proj.surplus) / max(1, proj.T)

    for ci, gr in enumerate(cands):
        if progress:
            progress(ci / max(1, len(cands)))
        gid = gr.goal_id
        goal = next(g for g in plan.goals if g.id == gid)
        low_prob_only = gr.shortfall_real <= tol_g[gid]
        z = dict(z_base)
        if low_prob_only:
            z[gid] = z_base[gid] + 0.5
        fixes: list[Fix] = []

        def evaluate(changes: WhatIfChanges) -> tuple[float, FinancePlan, CashflowProjection,
                                                      OptimizerSolution] | None:
            if not budget.ok():
                return None
            try:
                plan2 = apply_what_if(plan, changes)
            except ValueError:
                return None
            if not preflight(plan2).ok:
                return None
            proj2 = project_cashflow(plan2)
            lp = FinanceLP(plan2, proj2, z, cancel_event=cancel_event)
            budget.solves += 1
            sol2 = lp.solve_single(_Expr().add(lp.short[gid], 1.0), deadline, cancel_event, _bounds(lp, base, gid))
            if sol2 is None:
                return None
            return sol2.short[gid], plan2, proj2, sol2

        def meets(short: float, plan2: FinancePlan) -> bool:
            return short <= CRITERION_SHARE * tolerances(plan2)[1].get(gid, 1.0)

        def qp(plan2, proj2, sol2) -> float | None:
            if quick_probability is None or time.monotonic() >= deadline:
                return None
            return quick_probability(plan2, proj2, sol2, z, gid)

        # DELAY_GOAL
        for N in DELAYS:
            new_month = tg.add_months(goal.target_month, N)
            wi = WhatIfChanges(goal_overrides=[GoalOverride(goal_id=gid, target_month=new_month)])
            r = evaluate(wi)
            if r is None:
                if budget.truncated:
                    break
                continue
            short, plan2, proj2, sol2 = r
            if meets(short, plan2):
                if N <= goal.flexibility_months:
                    msg = render("FIX_DELAY_FLEX", goal=goal.name, month=new_month, months=N)
                else:
                    msg = render("FIX_DELAY", goal=goal.name, month=new_month, months=N,
                                 flex=goal.flexibility_months)
                fixes.append(Fix(kind="DELAY_GOAL", goal_id=gid, message=msg, months=N, new_target_month=new_month,
                                 resulting_shortfall_real=round(short, 2),
                                 resulting_success_probability=qp(plan2, proj2, sol2),
                                 relative_change=N / max(12, gr.months_to_goal), what_if=wi))
                break

        # INCREASE_SAVINGS / SPEND_LESS
        if budget.ok():
            tE = ef_complete_t(proj)
            lp = FinanceLP(plan, proj, z, extra_savings_profile=extra_savings_profile(plan, proj.T, tE),
                           cancel_event=cancel_event)
            budget.solves += 1
            bounds = _bounds(lp, base, gid) + [(_Expr().add(lp.short[gid], 1.0), 0.0)]
            sol_e = lp.solve_single(_Expr().add(lp.e_var, 1.0), deadline, cancel_event, bounds)
            if sol_e is not None and sol_e.extra_savings is not None:
                e = sol_e.extra_savings
                amount = float(math.ceil(e - 1e-9))
                if amount >= 1.0:
                    wi = WhatIfChanges(extra_monthly_savings=amount)
                    r = evaluate(wi)
                    if r is not None and meets(r[0], r[1]):
                        short, plan2, proj2, sol2 = r
                        prob = qp(plan2, proj2, sol2)
                        rel = amount / max(1.0, pos_surplus)
                        fixes.append(Fix(kind="INCREASE_SAVINGS", goal_id=gid, message=render(
                            "FIX_SAVE_MORE", amount=format_money(amount, cur), goal=goal.name), amount=amount,
                            resulting_shortfall_real=round(short, 2), resulting_success_probability=prob,
                            relative_change=rel, what_if=wi))
                        disc = _discretionary_monthly(plan)
                        if disc >= amount:
                            fixes.append(Fix(kind="SPEND_LESS", goal_id=gid, message=render(
                                "FIX_SPEND_LESS", amount=format_money(amount, cur), goal=goal.name), amount=amount,
                                resulting_shortfall_real=round(short, 2), resulting_success_probability=prob,
                                relative_change=rel,
                                what_if=WhatIfChanges(extra_monthly_savings=amount,
                                                      label=render("FIX_SPEND_LESS", amount=format_money(amount, cur),
                                                                   goal=goal.name)[:100])))

        # INCREASE_RISK (goal override, not the profile) [R13]
        level = tolerance_of(plan, goal)
        for lv in range(level + 1, 6):
            wi = WhatIfChanges(goal_overrides=[GoalOverride(goal_id=gid, risk_tolerance=lv)])
            r = evaluate(wi)
            if r is None:
                if budget.truncated:
                    break
                continue
            short, plan2, proj2, sol2 = r
            if meets(short, plan2):
                fixes.append(Fix(kind="INCREASE_RISK", goal_id=gid, message=render(
                    "FIX_RISK", goal=goal.name, old=level, new=lv), new_risk_tolerance=lv,
                    resulting_shortfall_real=round(short, 2), resulting_success_probability=qp(plan2, proj2, sol2),
                    relative_change=0.2 * (lv - level), what_if=wi))
                break

        # REDUCE_TARGET (no solve)
        if not low_prob_only and gr.target_real > 0:
            new_amount = floor2(goal.target_amount * (gr.target_real - gr.shortfall_real) / gr.target_real)
            if new_amount > 0:
                # the reduction is stated in the units of the goal's target field (today's money), so that
                # target_amount - amount = new; shortfall_real is in real-target units, which differ when the
                # goal has its own inflation rate
                cut = round(goal.target_amount - new_amount, 2)
                wi = WhatIfChanges(goal_overrides=[GoalOverride(goal_id=gid, target_amount=new_amount)])
                fixes.append(Fix(kind="REDUCE_TARGET", goal_id=gid, message=render(
                    "FIX_REDUCE", goal=goal.name, amount=format_money(cut, cur),
                    new=format_money(new_amount, cur)), amount=cut,
                    resulting_shortfall_real=0.0, relative_change=gr.shortfall_real / gr.target_real, what_if=wi))

        # LOWER_EF_BUILD_SHARE (must goals that run out of cash while the EF is built)
        tE = ef_complete_t(proj)
        if goal.priority == "must" and not low_prob_only and any(t < min(tE, gr.months_to_goal)
                                                                 for t in base.cash_binding):
            old = plan.emergency_fund.build_share
            for share in (0.75, 0.5):
                if share >= old:
                    continue
                wi = WhatIfChanges(emergency_build_share=share)
                r = evaluate(wi)
                if r is None:
                    if budget.truncated:
                        break
                    continue
                short, plan2, proj2, sol2 = r
                if meets(short, plan2):
                    fixes.append(Fix(kind="LOWER_EF_BUILD_SHARE", goal_id=gid, message=render(
                        "FIX_EF_SHARE", pct=f"{share * 100:.0f}", old=f"{old * 100:.0f}", goal=goal.name),
                        resulting_shortfall_real=round(short, 2),
                        resulting_success_probability=qp(plan2, proj2, sol2), relative_change=1.0 - share,
                        what_if=wi))
                    break

        if fixes:
            best = min(range(len(fixes)), key=lambda i: (fixes[i].relative_change, i))
            fixes[best].smallest = True
            out[gid] = fixes
    if progress:
        progress(1.0)
    return out, budget.solves, budget.truncated


def _discretionary_monthly(plan: FinancePlan) -> float:
    start = plan.start_month
    total = 0.0
    for e in plan.expenses:
        if e.essential:
            continue
        t0, t1 = tg.item_bounds(start, e.start_month, e.end_month, 10 ** 6)
        if t0 <= 0 <= t1:
            total += e.amount * tg.MONTHLY_FACTOR[e.frequency]
    return total
