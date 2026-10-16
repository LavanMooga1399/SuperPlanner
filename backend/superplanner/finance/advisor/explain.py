"""Computed explanations (FINANCE.md 12.1/12.2). Every sentence is `messages.render(...)` of computed values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import timegrid as tg
from ..cashflow import ef_complete_t
from ..model import (Binding, CashflowProjection, Explanation, FinancePlan, FinanceResult, Fix, GoalExplanation,
                     Reason)
from ..returns import (base_cap, goal_cap, inflation_vol, is_equity, is_risky, pi_general, planning_return, real_annual,
                       tolerance_of)
from ..validator import tolerances
from .messages import format_money, pct, render, years_text

if TYPE_CHECKING:  # pragma: no cover
    from ..pipeline import Published


def _runs(ts: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for t in sorted(set(ts)):
        if out and t == out[-1][1] + 1:
            out[-1] = (out[-1][0], t)
        else:
            out.append((t, t))
    return out


def _f1(v: float) -> str:
    s = f"{v:.1f}"
    return "0.0" if s == "-0.0" else s


def explain(plan: FinancePlan, proj: CashflowProjection, pub: "Published", result: FinanceResult,
            fixes: dict[str, list[Fix]]) -> Explanation:
    cur = plan.profile.currency

    def money(v: float) -> str:
        return format_money(v, cur)

    months = proj.months
    T = proj.T
    tE = ef_complete_t(proj)
    pi = pi_general(plan)
    sol = pub.sol
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    holdings = {h.id: h for h in plan.holdings}
    _, tol_g = tolerances(plan)
    gres = {g.goal_id: g for g in result.goals}
    goals_out: dict[str, GoalExplanation] = {}

    for gid, gd in sol.goals.items():
        g = gd.goal
        gr = gres[gid]
        reasons: list[Reason] = []
        xs = pub.x_month[gid]
        # ALLOCATION_SPLIT
        if gr.contribution_start_month:
            mix = ", ".join(render("MIX_PART", pct=f"{v:.0f}", name=classes[a].name)
                            for a, v in gr.allocation_now_pct.items())
            t1 = tg.month_index(plan.start_month, gr.contribution_start_month)
            amount = sum(xs[a].get(t1, 0.0) for a in xs)
            reasons.append(Reason(code="ALLOCATION_SPLIT", message=render(
                "ALLOCATION_SPLIT", goal=g.name, amount=money(amount), start=gr.contribution_start_month,
                end=gr.contribution_end_month, mix=mix), months=[gr.contribution_start_month,
                                                                  gr.contribution_end_month],
                asset_class_ids=list(gr.allocation_now_pct), values={"amount": round(amount, 2)}))
        else:
            reasons.append(Reason(code="ALLOCATION_SPLIT", message=render("ALLOCATION_NONE", goal=g.name)))
        # RISK_CAP
        tol_level = tolerance_of(plan, g)
        for rec in pub.records[gid]:
            cap = goal_cap(plan, g, gd.D, rec.s)
            tot = sum(rec.H.values())
            if cap <= 0 or cap >= 1.0 or tot <= 1e-6:
                continue
            share = sum(v for a, v in rec.H.items() if is_risky(classes[a])) / tot
            if share >= cap - 0.005:
                reasons.append(Reason(code="RISK_CAP", message=render(
                    "RISK_CAP", cap=pct(cap), level=tol_level, base=pct(base_cap(plan.assumptions, tol_level)),
                    years=years_text(gd.D - rec.s)), months=[months[rec.s]],
                    values={"cap_pct": round(cap * 100, 2), "share_pct": round(share * 100, 2)}))
                break
        # GLIDE_DOWN
        for r in pub.rebalances:
            if r.goal_id != gid:
                continue
            risky_sold = sum(v for a, v in r.sells.items() if is_risky(classes[a]))
            if risky_sold > 0.5:
                s = tg.month_index(plan.start_month, r.month)
                cap = goal_cap(plan, g, gd.D, s)
                reasons.append(Reason(code="GLIDE_DOWN", message=render(
                    "GLIDE_DOWN", month=r.month, amount=money(risky_sold), cap=pct(cap)), months=[r.month],
                    asset_class_ids=[a for a in r.sells if is_risky(classes[a])],
                    values={"amount": round(risky_sold, 2), "cap_pct": round(cap * 100, 2)}))
                break
        # LOCKIN_EXCLUDED
        have = {a for (g2, a, _k) in sol.x if g2 == gid}
        for a in gd.allowed:
            ac = classes[a]
            if ac.lock_in_months > 0 and a not in have:
                reasons.append(Reason(code="LOCKIN_EXCLUDED", message=render(
                    "LOCKIN_EXCLUDED", name=ac.name, months=ac.lock_in_months, date=g.target_month),
                    asset_class_ids=[a]))
        # EF_GATED
        if g.priority in ("should", "nice") and tE > 0:
            reasons.append(Reason(code="EF_GATED", message=render(
                "EF_GATED", month=months[tE] if tE < T else "after the plan horizon", amount=money(proj.ef_target)),
                months=[months[tE]] if tE < T else [], values={"ef_target": round(proj.ef_target, 2)}))
        # CASH_LIMITED
        if gr.shortfall_real > tol_g[gid]:
            before = [t for t in sol.cash_binding if t < gd.D]
            if before:
                reasons.append(Reason(code="CASH_LIMITED", message=render(
                    "CASH_LIMITED", count=len(before), first=months[before[0]], last=months[before[-1]]),
                    months=[months[before[0]], months[before[-1]]], values={"months": len(before)}))
        # HOLDINGS_USED
        used: dict[str, float] = {}
        for r in pub.assignment:
            if r.goal_id == gid and r.source in ("earmark", "assigned") and r.amount > 0:
                used[r.holding_id] = used.get(r.holding_id, 0.0) + r.amount
        for hid, amt in used.items():
            h = holdings[hid]
            reasons.append(Reason(code="HOLDINGS_USED", message=render("HOLDINGS_USED", amount=money(amt),
                                                                         holding=h.name),
                                  asset_class_ids=[h.asset_class_id], values={"amount": round(amt, 2)}))
        # CAUTIOUS_RETURNS
        main = max(gr.allocation_now_pct.items(), key=lambda kv: kv[1])[0] if gr.allocation_now_pct else (
            gd.allowed[0] if gd.allowed else None)
        if main is not None:
            ac = classes[main]
            rp = planning_return(ac, pi, gd.z, gd.D, inflation_vol(plan))
            re_ = real_annual(ac, pi)
            reasons.append(Reason(code="CAUTIOUS_RETURNS", message=render(
                "CAUTIOUS_RETURNS", name=ac.name, plan=_f1(rp * 100), expected=_f1(re_ * 100)),
                asset_class_ids=[main], values={"planning_pct": round(rp * 100, 2), "expected_pct": round(re_ * 100, 2)}))
        if gr.shortfall_real > tol_g[gid]:
            reasons.append(Reason(code="SHORTFALL", message=render(
                "SHORTFALL", value=money(gr.planned_value_real), target=money(gr.target_real)),
                values={"shortfall": gr.shortfall_real}))
        if gr.success_probability < gr.min_success_probability:
            reasons.append(Reason(code="LOW_PROBABILITY", message=render(
                "LOW_PROBABILITY", prob=pct(gr.success_probability), min=pct(gr.min_success_probability)),
                values={"probability": gr.success_probability}))
        if gr.status == "on_track":
            reasons.append(Reason(code="ON_TRACK", message=render(
                "ON_TRACK", prob=pct(gr.success_probability), low=money(gr.scenario_low_real)),
                values={"probability": gr.success_probability}))
        goals_out[gid] = GoalExplanation(reasons=reasons, fixes=fixes.get(gid, []))

    # ---- plan-level binding constraints
    binding: list[Binding] = []
    if sol.cash_deficit > 1.0:
        ts = [t for t, d in enumerate(sol.d) if d > 1e-6]
        binding.append(Binding(code="CASH_DEFICIT", message=render(
            "CASH_DEFICIT", amount=money(sol.cash_deficit), count=len(ts), first=months[ts[0]], last=months[ts[-1]]),
            months=[months[ts[0]], months[ts[-1]]]))
    if sol.cash_binding:
        b = sol.cash_binding
        short_goals = [g.goal_id for g in result.goals if g.shortfall_real > tol_g.get(g.goal_id, 1.0)]
        binding.append(Binding(code="CASH_FULLY_USED", message=render(
            "CASH_FULLY_USED", count=len(b), first=months[b[0]], last=months[b[-1]]),
            months=[months[b[0]], months[b[-1]]], goal_ids=short_goals))
    efm = [t for t in range(T) if proj.ef_contribution[t] > 0.005]
    if efm:
        binding.append(Binding(code="EF_BUILD", message=render("EF_BUILD", first=months[efm[0]],
                                                                 last=months[efm[-1]]),
                               months=[months[efm[0]], months[efm[-1]]]))
    _global_caps(plan, pub, classes, binding)
    for d in plan.debts:
        po = proj.debt_payoff.get(d.id)
        if po is not None and po < T - 1:
            binding.append(Binding(code="DEBT_PAYOFF", message=render(
                "DEBT_PAYOFF", debt=d.name, month=months[po], amount=money(d.emi / proj.price_index[po])),
                months=[months[po]]))

    # ---- summary (<= 5 lines)
    summary: list[str] = []
    s = result.summary
    if result.feasibility == "infeasible":
        summary.append(render("SUMMARY_INFEASIBLE"))
    elif result.feasibility == "feasible":
        summary.append(render("SUMMARY_FEASIBLE", on_track=s.goals_on_track, total=s.goals_total))
    else:
        summary.append(render("SUMMARY_UNKNOWN"))
    summary.append(render("SUMMARY_INVEST", investable=money(max(0.0, s.monthly_investable_now)),
                          contributing=money(s.monthly_contribution_now)))
    if proj.ef_target <= 0:
        summary.append(render("SUMMARY_EF_NONE"))
    elif tE == 0:
        summary.append(render("SUMMARY_EF_DONE", target=money(proj.ef_target)))
    elif tE >= T:
        summary.append(render("SUMMARY_EF_NEVER", target=money(proj.ef_target)))
    else:
        summary.append(render("SUMMARY_EF", target=money(proj.ef_target), month=months[tE]))
    if not result.goals:
        summary.append(render("SUMMARY_NO_GOALS"))
    else:
        risky = [g for g in result.goals if g.status != "on_track"]
        if risky:
            worst = min(risky, key=lambda g: g.success_probability)
            summary.append(render("SUMMARY_TOP_RISK", goal=worst.name, prob=pct(worst.success_probability)))
    if s.liquidity_risk_probability > 0.10 and len(summary) < 5:
        summary.append(render("SUMMARY_LIQUIDITY", prob=pct(s.liquidity_risk_probability)))

    # ---- assumptions
    assumptions = [render("ASSUMPTION_INFLATION", pct=f"{plan.assumptions.inflation_pct:g}")]
    used_cls = []
    for gid, gd in sol.goals.items():
        for a in gd.bucket_classes:
            if a in used_cls:
                continue
            if any(v > 0 for v in pub.x_month[gid].get(a, {}).values()) or any(
                    rec.H.get(a, 0.0) > 0.005 for rec in pub.records[gid]):
                used_cls.append(a)
    for a in [c.id for c in plan.assumptions.asset_classes if c.id in used_cls]:
        ac = classes[a]
        assumptions.append(render("ASSUMPTION_CLASS", name=ac.name, expected=f"{ac.expected_return_pct:g}",
                                  real=_f1(real_annual(ac, pi) * 100)))
    for gid, gd in sol.goals.items():
        gr = gres[gid]
        main = max(gr.allocation_now_pct.items(), key=lambda kv: kv[1])[0] if gr.allocation_now_pct else None
        if main:
            assumptions.append(render("ASSUMPTION_CAUTIOUS", goal=gd.goal.name, name=classes[main].name,
                                      plan=_f1(planning_return(classes[main], pi, gd.z, gd.D, inflation_vol(plan)) * 100)))
    assumptions.append(render("ASSUMPTION_SOURCE", note=plan.assumptions.source_note))

    limitations = [render(c) for c in ("LIMIT_TAX", "LIMIT_PRODUCTS", "LIMIT_RETURNS", "LIMIT_RETIREMENT",
                                       "LIMIT_BUCKETS")]
    triggers = [render("TRIGGER_INCOME"), render("TRIGGER_DEBT"), render("TRIGGER_GOAL"),
                render("TRIGGER_YEAR", month=plan.start_month)]
    for g in result.goals:
        if g.status == "on_track":
            triggers.append(render("TRIGGER_AT_RISK", goal=g.name))
    for d in plan.debts:
        po = proj.debt_payoff.get(d.id)
        if po is not None and po < T:
            triggers.append(render("TRIGGER_DEBT_PAYOFF", debt=d.name, month=months[po]))
    return Explanation(summary=summary[:5], goals=goals_out, binding_constraints=binding, assumptions=assumptions,
                       limitations=limitations, replanning_triggers=triggers)


def _global_caps(plan: FinancePlan, pub: "Published", classes: dict, binding: list[Binding]) -> None:
    maxeq = plan.constraints.max_equity_pct
    caps = plan.constraints.max_class_pct
    if maxeq is None and not caps:
        return
    by_k: dict[int, list[dict[str, float]]] = {}
    for gid, recs in pub.records.items():
        for rec in recs:
            by_k.setdefault(rec.s, []).append(rec.H)
    eq_hits: list[int] = []
    cls_hits: dict[str, list[int]] = {}
    for s, Hs in sorted(by_k.items()):
        tot = sum(sum(H.values()) for H in Hs)
        if tot <= 1e-6:
            continue
        if maxeq is not None:
            eq = sum(v for H in Hs for a, v in H.items() if is_equity(classes[a]))
            if eq / tot >= maxeq / 100.0 - 0.005 and maxeq < 100:
                eq_hits.append(s)
        for a, p in caps.items():
            v = sum(H.get(a, 0.0) for H in Hs)
            if v / tot >= p / 100.0 - 0.005 and p < 100:
                cls_hits.setdefault(a, []).append(s)
    months = pub.proj.months
    if eq_hits:
        binding.append(Binding(code="EQUITY_CAP", message=render("EQUITY_CAP", pct=f"{maxeq:g}", count=len(eq_hits)),
                               months=[months[eq_hits[0]], months[eq_hits[-1]]]))
    for a, hits in cls_hits.items():
        binding.append(Binding(code="CLASS_CAP", message=render("CLASS_CAP", pct=f"{caps[a]:g}",
                                                                  name=classes[a].name, count=len(hits)),
                               months=[months[hits[0]], months[hits[-1]]]))
