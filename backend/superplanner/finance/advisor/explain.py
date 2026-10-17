"""Computed explanations (FINANCE.md 12.1/12.2). Every sentence is `messages.render(...)` of computed values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import timegrid as tg
from ..cashflow import ef_complete_t
from ..model import (Binding, CashflowProjection, Explanation, FinancePlan, FinanceResult, Fix, GoalExplanation,
                     Reason)
from ..returns import (active_caps, allowed_classes, base_cap, goal_cap, inflation_vol, initial_z, is_equity, is_risky,
                       pi_general, planning_return, real_annual, tolerance_of)
from ..validator import tolerances
from .messages import duration_text, format_money, pct, render, years_text

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


def _plan_ret(plan: FinancePlan, ac, gd) -> float:
    """The goal's planning return of class `ac` (PHASE2 1.5), exactly as the optimizer valued it."""
    return planning_return(ac, pi_general(plan), gd.z, gd.D, inflation_vol(plan), z0=initial_z(gd.goal),
                           caution=plan.assumptions.caution)


def _names(classes: dict, ids) -> str:
    return ", ".join(classes[a].name for a in ids)


def growth_reason(plan: FinancePlan, pub: "Published", gd, gr) -> Reason:
    """The goal's growth-asset decision (PHASE2 1.10), first matching rule of the table."""
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    g = gd.goal
    D = gd.D
    level = tolerance_of(plan, g)
    base = base_cap(plan.assumptions, level)
    allowed = allowed_classes(plan, g)
    share = gr.growth_share_now_pct
    cap = gr.growth_cap_now_pct
    risky_mix = [a for a, v in gr.allocation_now_pct.items() if v > 0 and is_risky(classes[a])]
    vals: dict[str, float | str] = {"growth_share_pct": share, "growth_cap_pct": cap, "risk_level": level,
                                    "base_cap_pct": round(base * 100, 2)}
    years = duration_text(D)
    if not any(is_risky(classes[a]) for a in allowed):
        return Reason(code="GROWTH_NONE_RESTRICTED", message=render(
            "GROWTH_NONE_RESTRICTED", goal=g.name, names=_names(classes, allowed)), asset_class_ids=list(allowed),
            values=vals)
    if share >= 1.0:
        # the first contribution block (or block 0) of the goal, as for growth_cap_now_pct
        s0 = gd.blocks[0][1] if gd.blocks else 0
        if gr.contribution_start_month:
            t1 = tg.month_index(plan.start_month, gr.contribution_start_month)
            s0 = next((s for (_k, s, n) in gd.blocks if s <= t1 < s + n), s0)
        maxeq = plan.constraints.max_equity_pct
        eq_share = sum(v for a, v in gr.allocation_now_pct.items() if is_equity(classes[a]))
        if (maxeq is not None and maxeq < 100 and active_caps(plan, g, D, s0).equity
                and eq_share >= maxeq - 0.5 and maxeq < cap - 0.5):
            return Reason(code="GROWTH_LIMITED_GLOBAL", message=render(
                "GROWTH_LIMITED_GLOBAL", goal=g.name, share=f"{share:.0f}", pct=f"{maxeq:g}", level=level),
                asset_class_ids=risky_mix, values=vals)
        if D >= 120:
            glide_s = next((s for (_k, s, _n) in gd.blocks if goal_cap(plan, g, D, s) < base - 1e-9), None)
            glide_month = tg.add_months(plan.start_month, glide_s if glide_s is not None else max(0, D - 120))
            return Reason(code="GROWTH_HIGH", message=render(
                "GROWTH_HIGH", goal=g.name, share=f"{share:.0f}", names=_names(classes, risky_mix), years=years,
                level=level, base=pct(base), glide_month=glide_month), months=[glide_month],
                asset_class_ids=risky_mix, values=vals)
        return Reason(code="GROWTH_LIMITED_TIME", message=render(
            "GROWTH_LIMITED_TIME", goal=g.name, share=f"{share:.0f}", names=_names(classes, risky_mix), years=years,
            cap=f"{cap:.0f}", level=level, base=pct(base)), asset_class_ids=risky_mix, values=vals)
    if cap <= 0.0 or D < 84:
        return Reason(code="GROWTH_NONE_SHORT", message=render(
            "GROWTH_NONE_SHORT", goal=g.name, years=years, level=level), values=vals)
    safe = [a for a in allowed if not is_risky(classes[a])]
    best = max(safe, key=lambda a: gd.rho[a]) if safe else None
    safe_txt = (render("SAFE_RETURN", name=classes[best].name, pct=_f1((gd.rho[best] ** 12 - 1.0) * 100))
                if best is not None else "safer classes")
    return Reason(code="GROWTH_NONE_RETURNS", message=render(
        "GROWTH_NONE_RETURNS", goal=g.name, safe=safe_txt, level=level),
        asset_class_ids=[best] if best else [], values=vals)


_TIER_WORDS = {"must": "must-have", "should": "should-have", "nice": "nice-to-have"}


def shared_shortfalls(result: FinanceResult) -> list[Binding]:
    """`SHARED_SHORTFALL` (PHASE2 1.10): >= 2 goals of one tier short by fractions > 0.001 within 0.01."""
    out: list[Binding] = []
    for tier in ("must", "should", "nice"):
        short = sorted((g for g in result.goals if g.priority == tier and g.shortfall_fraction > 0.001),
                       key=lambda g: g.shortfall_fraction)
        groups: list[list] = []
        for g in short:
            if groups and g.shortfall_fraction - groups[-1][0].shortfall_fraction <= 0.01:
                groups[-1].append(g)
            else:
                groups.append([g])
        for grp in groups:
            if len(grp) < 2:
                continue
            avg = sum(g.shortfall_fraction for g in grp) / len(grp)
            out.append(Binding(code="SHARED_SHORTFALL", message=render(
                "SHARED_SHORTFALL", count=len(grp), tier=_TIER_WORDS[tier], pct=pct(avg)),
                goal_ids=[g.goal_id for g in grp]))
    return out


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
        reasons: list[Reason] = [growth_reason(plan, pub, gd, gr)]
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
            rp = _plan_ret(plan, ac, gd)
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
    binding.extend(shared_shortfalls(result))
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
    # first-year surplus and funding split (PHASE2 1.11; SUMMARY_INVEST is no longer emitted)
    if s.monthly_surplus_avg_12m < 0:
        summary.append(render("SUMMARY_SURPLUS_NEGATIVE", amount=money(-s.monthly_surplus_avg_12m)))
    elif s.monthly_ef_contribution_avg_12m >= 1:
        summary.append(render("SUMMARY_SURPLUS_EF", surplus=money(s.monthly_surplus_avg_12m),
                              ef=money(s.monthly_ef_contribution_avg_12m)))
    else:
        summary.append(render("SUMMARY_SURPLUS", surplus=money(s.monthly_surplus_avg_12m)))
    if s.monthly_contribution_avg_12m < 0.5:
        summary.append(render("SUMMARY_FUNDING_NONE"))
    elif s.monthly_from_savings_avg_12m >= 1:
        summary.append(render("SUMMARY_FUNDING", contributing=money(s.monthly_contribution_avg_12m),
                              from_surplus=money(s.monthly_from_surplus_avg_12m),
                              from_savings=money(s.monthly_from_savings_avg_12m)))
    else:
        summary.append(render("SUMMARY_FUNDING_SURPLUS", contributing=money(s.monthly_contribution_avg_12m)))
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
                                      plan=_f1(_plan_ret(plan, classes[main], gd) * 100)))
    for item, used, rng in ([(x.name, x.amount, x.amount_range) for x in plan.incomes]
                            + [(x.name, x.amount, x.amount_range) for x in plan.expenses]
                            + [(x.name, x.target_amount, x.target_range) for x in plan.goals if x.enabled]):
        if rng is not None:
            assumptions.append(render("ASSUMPTION_RANGE", item=item, low=money(rng.low), high=money(rng.high),
                                      used=money(used)))
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
