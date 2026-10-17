"""Result comparison (FINANCE.md section 13): deltas are `b - a`; goals are the union, ordered b then a."""

from __future__ import annotations

from typing import Any

from .model import (ComparisonTotals, FinanceComparison, FinanceResult, FinanceResultSummary, GoalComparison,
                    WhatIfChanges)


def result_summary(r: FinanceResult, **ids: Any) -> FinanceResultSummary:
    s = r.summary
    return FinanceResultSummary(feasibility=r.feasibility, goals_total=s.goals_total, goals_on_track=s.goals_on_track,
                                goals_at_risk=s.goals_at_risk, goals_off_track=s.goals_off_track,
                                monthly_contribution_now=s.monthly_contribution_now, **ids)


def _d(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(b - a, 6)


def compare_results(a: FinanceResult, b: FinanceResult, *, summary_a: FinanceResultSummary | None = None,
                    summary_b: FinanceResultSummary | None = None,
                    what_if_b: WhatIfChanges | None = None) -> FinanceComparison:
    sa = summary_a or result_summary(a)
    sb = summary_b or result_summary(b)
    totals = ComparisonTotals(
        monthly_contribution_now_a=a.summary.monthly_contribution_now,
        monthly_contribution_now_b=b.summary.monthly_contribution_now,
        monthly_contribution_now_delta=round(b.summary.monthly_contribution_now - a.summary.monthly_contribution_now, 2),
        ef_complete_month_a=a.summary.emergency_fund_complete_month,
        ef_complete_month_b=b.summary.emergency_fund_complete_month,
        goals_on_track_a=a.summary.goals_on_track, goals_on_track_b=b.summary.goals_on_track,
        liquidity_risk_a=a.summary.liquidity_risk_probability, liquidity_risk_b=b.summary.liquidity_risk_probability)
    ga = {g.goal_id: g for g in a.goals}
    gb = {g.goal_id: g for g in b.goals}
    order = [g.goal_id for g in b.goals] + [g.goal_id for g in a.goals if g.goal_id not in gb]
    goals = []
    for gid in order:
        x, y = ga.get(gid), gb.get(gid)
        goals.append(GoalComparison(
            goal_id=gid, name=(y or x).name, in_a=x is not None, in_b=y is not None,
            target_month_a=x.target_month if x else None, target_month_b=y.target_month if y else None,
            success_a=x.success_probability if x else None, success_b=y.success_probability if y else None,
            success_delta=_d(x.success_probability if x else None, y.success_probability if y else None),
            p50_a=x.p50_real if x else None, p50_b=y.p50_real if y else None,
            p50_delta=_d(x.p50_real if x else None, y.p50_real if y else None),
            shortfall_a=x.shortfall_real if x else None, shortfall_b=y.shortfall_real if y else None,
            monthly_now_a=x.monthly_contribution_now if x else None,
            monthly_now_b=y.monthly_contribution_now if y else None,
            status_a=x.status if x else None, status_b=y.status if y else None))
    # results from different engine versions mix the engine change into the deltas (PHASE2 1.13)
    return FinanceComparison(a=sa, b=sb, totals=totals, goals=goals,
                             what_if_b=what_if_b if what_if_b is not None else sb.what_if,
                             engine_versions_differ=a.engine_version != b.engine_version)
