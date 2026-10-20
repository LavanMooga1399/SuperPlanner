"""What-if derivation (FINANCE.md section 13): a pure, deterministic function of (plan, changes)."""

from __future__ import annotations

from . import timegrid as tg
from .advisor.messages import format_money, render
from .defaults import WHATIF_PREFIX
from .model import Expense, FinancePlan, IncomeStream, WhatIfChanges


def _all_ids(plan: FinancePlan) -> list[str]:
    ids = []
    for lst in (plan.incomes, plan.expenses, plan.debts, plan.holdings, plan.one_offs, plan.goals):
        ids.extend(i.id for i in lst)
    return ids


def interruptible_monthly_income(plan: FinancePlan, month: str, *, linked: bool = False) -> float:
    """Monthly-equivalent of interruptible incomes active in `month` (13: income drop base).

    `linked=False`: the nominal (not inflation-linked) streams, nominal amounts, as before PHASE2.
    `linked=True`: the inflation-linked streams, real amounts (today's money) at `month` (PHASE2 1.7)."""
    start = plan.start_month
    t = max(0, tg.month_index(start, month))
    total = 0.0
    for inc in plan.incomes:
        if not inc.interruptible or inc.inflation_linked != linked:
            continue
        t0, t1 = tg.item_bounds(start, inc.start_month, inc.end_month, t + 1)
        if t0 <= t <= t1:
            total += inc.amount * (1 + inc.growth_pct / 100.0) ** ((t - t0) // 12) * tg.MONTHLY_FACTOR[inc.frequency]
    return total


def apply_what_if(plan: FinancePlan, changes: WhatIfChanges) -> FinancePlan:
    if any(i.startswith(WHATIF_PREFIX) for i in _all_ids(plan)):
        raise ValueError("the plan already contains what-if items (ids starting with 'whatif_')")
    doc = plan.model_dump()
    goals = {g["id"]: g for g in doc["goals"]}
    for o in changes.goal_overrides:
        if o.goal_id not in goals:
            raise ValueError(f'unknown goal id "{o.goal_id}"')
        g = goals[o.goal_id]
        for f in ("target_month", "target_amount", "priority", "enabled", "risk_tolerance"):
            v = getattr(o, f)
            if v is not None:
                g[f] = v
    if changes.risk_tolerance is not None:
        doc["profile"]["risk_tolerance"] = changes.risk_tolerance
    if changes.inflation_pct is not None:
        doc["assumptions"]["inflation_pct"] = changes.inflation_pct
    if changes.return_shift_pct:
        for ac in doc["assumptions"]["asset_classes"]:
            if ac["category"] != "cash":
                ac["expected_return_pct"] = max(-20.0, min(40.0, ac["expected_return_pct"] + changes.return_shift_pct))
    if changes.emergency_build_share is not None:
        doc["emergency_fund"]["build_share"] = changes.emergency_build_share
    infl = doc["assumptions"]["inflation_pct"]
    if changes.extra_monthly_savings > 0:
        doc["incomes"].append(IncomeStream(
            id="whatif_extra", name="Extra savings", kind="other", amount=changes.extra_monthly_savings,
            frequency="monthly", growth_pct=max(-50.0, min(50.0, infl)), interruptible=False).model_dump())
    elif changes.extra_monthly_savings < 0:
        doc["expenses"].append(Expense(
            id="whatif_less", name="Spend less", category="what-if", amount=-changes.extra_monthly_savings,
            frequency="monthly", essential=False, inflation_linked=True).model_dump())
    if changes.income_drop is not None:
        d = changes.income_drop
        base = interruptible_monthly_income(plan, d.start_month)
        amount = d.percent / 100.0 * base
        if amount > 0:
            start = d.start_month if plan.start_month is None or d.start_month >= plan.start_month else plan.start_month
            doc["expenses"].append(Expense(
                id="whatif_income_drop", name="Income drop", category="what-if", amount=amount, frequency="monthly",
                essential=True, inflation_linked=False, start_month=start,
                end_month=tg.add_months(start, d.months - 1)).model_dump())
        amount_l = d.percent / 100.0 * interruptible_monthly_income(plan, d.start_month, linked=True)
        if amount_l > 0:
            start = d.start_month if plan.start_month is None or d.start_month >= plan.start_month else plan.start_month
            doc["expenses"].append(Expense(
                id="whatif_income_drop_linked", name="Income drop (inflation-linked income)", category="what-if",
                amount=amount_l, frequency="monthly", essential=True, inflation_linked=True, start_month=start,
                end_month=tg.add_months(start, d.months - 1)).model_dump())
    return FinancePlan.model_validate(doc)


def default_label(plan: FinancePlan, changes: WhatIfChanges) -> str:
    """Joined short phrases, e.g. `+₹10,000/month, Car 2031-06` (13)."""
    if changes.label:
        return changes.label
    cur = plan.profile.currency
    names = {g.id: g.name for g in plan.goals}
    parts: list[str] = []
    if changes.extra_monthly_savings:
        parts.append(render("LABEL_EXTRA", sign="+" if changes.extra_monthly_savings > 0 else "-",
                            amount=format_money(abs(changes.extra_monthly_savings), cur)))
    for o in changes.goal_overrides:
        n = names.get(o.goal_id, o.goal_id)
        if o.target_month:
            parts.append(render("LABEL_GOAL_MONTH", goal=n, month=o.target_month))
        if o.target_amount is not None:
            parts.append(render("LABEL_GOAL_AMOUNT", goal=n, amount=format_money(o.target_amount, cur)))
        if o.enabled is False:
            parts.append(render("LABEL_GOAL_OFF", goal=n))
        if o.priority:
            parts.append(render("LABEL_GOAL_PRIORITY", goal=n, priority=o.priority))
        if o.risk_tolerance:
            parts.append(render("LABEL_GOAL_RISK", goal=n, level=o.risk_tolerance))
    if changes.risk_tolerance:
        parts.append(render("LABEL_RISK", level=changes.risk_tolerance))
    if changes.return_shift_pct:
        parts.append(render("LABEL_RETURNS", sign="+" if changes.return_shift_pct > 0 else "-",
                            pct=f"{abs(changes.return_shift_pct):g}"))
    if changes.inflation_pct is not None:
        parts.append(render("LABEL_INFLATION", pct=f"{changes.inflation_pct:g}"))
    if changes.income_drop is not None:
        parts.append(render("LABEL_INCOME_DROP", pct=f"{changes.income_drop.percent:g}",
                            months=changes.income_drop.months))
    if changes.emergency_build_share is not None:
        parts.append(render("LABEL_EF_SHARE", pct=f"{changes.emergency_build_share * 100:.0f}"))
    label = ", ".join(parts) or render("LABEL_DEFAULT")
    return label[:100]
