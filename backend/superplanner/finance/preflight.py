"""Preflight checks (FINANCE.md section 6): relational and horizon rules with plain-language messages."""

from __future__ import annotations

import math

import numpy as np

from . import defaults as D
from . import timegrid as tg
from .model import FinanceIssue, FinancePlan, FinancePreflightReport

ERROR_CODES = (
    "START_MONTH_MISSING", "DUPLICATE_ID", "RESERVED_ID", "UNKNOWN_ASSET_CLASS", "UNKNOWN_HOLDING",
    "EARMARK_EXCEEDS_HOLDING", "EARMARK_LOCKED_PAST_GOAL", "END_BEFORE_START", "GOAL_TOO_SOON", "ONE_OFF_IN_PAST",
    "HORIZON_TOO_LONG", "HORIZON_BEFORE_GOAL", "CASH_CLASS_INVALID", "EF_CLASS_NOT_LIQUID", "DEBT_NEVER_REPAID",
    "NO_ALLOWED_CLASS", "TOO_LARGE",
)
WARNING_CODES = (
    "NO_INCOME", "NO_GOALS", "NEGATIVE_SURPLUS", "DEBT_TERM_MISMATCH", "CORRELATION_NOT_PSD", "HIGH_INTEREST_DEBT",
    "GOAL_TARGET_HUGE",
)

_LISTS = ("incomes", "expenses", "debts", "holdings", "one_offs", "goals")
_KIND = {"incomes": "Income", "expenses": "Expense", "debts": "Debt", "holdings": "Holding", "one_offs": "One-off",
         "goals": "Goal", "asset_classes": "Asset class"}


def _q(s: str) -> str:
    return f'"{s}"'


def correlation_matrix(plan: FinancePlan) -> np.ndarray:
    ids = [a.id for a in plan.assumptions.asset_classes]
    pos = {i: n for n, i in enumerate(ids)}
    C = np.eye(len(ids))
    for c in plan.assumptions.correlations:
        if c.a in pos and c.b in pos:
            C[pos[c.a], pos[c.b]] = C[pos[c.b], pos[c.a]] = c.rho
    return C


def is_psd(C: np.ndarray) -> bool:
    return bool(np.linalg.eigvalsh(C).min() >= -1e-10)


def estimate_variables(plan: FinancePlan, T: int) -> int:
    """Section 8.7: `sum_g K_g (5|A| + 3) + 2T + |pool| |G|`."""
    A = len(plan.assumptions.asset_classes)
    L = plan.constraints.contribution_block_months
    goals = [g for g in plan.goals if g.enabled]
    total = 0
    for g in goals:
        Dg = tg.month_index(plan.start_month, g.target_month) if plan.start_month else 0
        total += math.ceil(max(Dg, 0) / L) * (5 * A + 3)
    return total + 2 * T + len(plan.holdings) * len(goals)


def preflight(plan: FinancePlan) -> FinancePreflightReport:
    issues: list[FinanceIssue] = []

    def add(code: str, sev: str, msg: str, field: str | None = None, ids: list[str] | None = None) -> None:
        issues.append(FinanceIssue(code=code, severity=sev, message=msg, field=field, item_ids=ids or []))

    start = plan.start_month
    if start is None:
        add("START_MONTH_MISSING", "error", "The plan has no start month. Pick the month the plan starts.",
            "start_month")
        return FinancePreflightReport(ok=False, issues=issues)

    classes = {a.id: a for a in plan.assumptions.asset_classes}

    # ---- ids
    seen_global: dict[str, str] = {}
    reported: set[tuple[str, str]] = set()
    for lst in _LISTS + ("asset_classes",):
        items = plan.assumptions.asset_classes if lst == "asset_classes" else getattr(plan, lst)
        seen_local: set[str] = set()
        for i, it in enumerate(items):
            if it.id in seen_local and (lst, it.id) not in reported:
                reported.add((lst, it.id))
                add("DUPLICATE_ID", "error", f'{_KIND[lst]} id "{it.id}" ({_q(it.name)}) is used twice. '
                    "Give every item its own id.", f"{lst}[{i}].id", [it.id])
            seen_local.add(it.id)
            if lst == "asset_classes":
                continue
            if it.id in D.RESERVED_IDS:
                add("RESERVED_ID", "error", f'{_KIND[lst]} {_q(it.name)} uses the reserved id "{it.id}". '
                    "Pick another id.", f"{lst}[{i}].id", [it.id])
            other = seen_global.get(it.id)
            if other is not None and other != lst and ("*", it.id) not in reported:
                reported.add(("*", it.id))
                add("DUPLICATE_ID", "error", f'The id "{it.id}" ({_q(it.name)}) is used by more than one item. '
                    "Ids must be unique across the plan.", f"{lst}[{i}].id", [it.id])
            seen_global.setdefault(it.id, lst)

    # ---- asset class references
    cash_id = plan.assumptions.cash_class_id
    ef_id = plan.emergency_fund.asset_class_id
    holdings = {h.id: h for h in plan.holdings}
    for i, h in enumerate(plan.holdings):
        if h.asset_class_id not in classes:
            add("UNKNOWN_ASSET_CLASS", "error", f'Holding {_q(h.name)} uses the unknown asset class '
                f'"{h.asset_class_id}".', f"holdings[{i}].asset_class_id", [h.id])
    if ef_id not in classes:
        add("UNKNOWN_ASSET_CLASS", "error", f'The emergency fund uses the unknown asset class "{ef_id}".',
            "emergency_fund.asset_class_id")
    if cash_id not in classes:
        add("UNKNOWN_ASSET_CLASS", "error", f'The cash class "{cash_id}" does not exist.',
            "assumptions.cash_class_id")
    for gi, g in enumerate(plan.goals):
        for a in g.allowed_asset_class_ids or []:
            if a not in classes:
                add("UNKNOWN_ASSET_CLASS", "error", f'Goal {_q(g.name)} allows the unknown asset class "{a}".',
                    f"goals[{gi}].allowed_asset_class_ids", [g.id])
    for k in plan.constraints.max_class_pct:
        if k not in classes:
            add("UNKNOWN_ASSET_CLASS", "error", f'The class limit refers to the unknown asset class "{k}".',
                f"constraints.max_class_pct.{k}")
    for ci, c in enumerate(plan.assumptions.correlations):
        for x in (c.a, c.b):
            if x not in classes:
                add("UNKNOWN_ASSET_CLASS", "error", f'A correlation refers to the unknown asset class "{x}".',
                    f"assumptions.correlations[{ci}]")

    if cash_id in classes:
        c = classes[cash_id]
        if c.lock_in_months > 0 or c.liquidity_days > 1:
            add("CASH_CLASS_INVALID", "error", f'The cash class {_q(c.name)} must have no lock-in and be available '
                "within 1 day.", "assumptions.cash_class_id")
    if ef_id in classes:
        c = classes[ef_id]
        if c.lock_in_months > 0 or c.liquidity_days > 7:
            add("EF_CLASS_NOT_LIQUID", "error", f'The emergency fund class {_q(c.name)} must have no lock-in and be '
                "available within 7 days.", "emergency_fund.asset_class_id")

    # ---- earmarks
    earmarked_total: dict[str, float] = {}
    for gi, g in enumerate(plan.goals):
        for ei, em in enumerate(g.earmarked):
            h = holdings.get(em.holding_id)
            if h is None:
                add("UNKNOWN_HOLDING", "error", f'Goal {_q(g.name)} sets aside money from the unknown holding '
                    f'"{em.holding_id}".', f"goals[{gi}].earmarked[{ei}].holding_id", [g.id])
                continue
            if g.enabled:
                earmarked_total[h.id] = earmarked_total.get(h.id, 0.0) + em.amount
            if g.enabled and h.locked_until_month and h.locked_until_month > g.target_month:
                add("EARMARK_LOCKED_PAST_GOAL", "error", f'Holding {_q(h.name)} is locked until '
                    f"{h.locked_until_month}, after goal {_q(g.name)} is due ({g.target_month}).",
                    f"goals[{gi}].earmarked[{ei}]", [g.id, h.id])
    for hid, tot in earmarked_total.items():
        h = holdings[hid]
        if tot > h.amount + 0.01:
            add("EARMARK_EXCEEDS_HOLDING", "error", f'Goals set aside {tot:,.2f} from holding {_q(h.name)}, which is '
                f"only worth {h.amount:,.2f}.", None, [hid])

    # ---- months
    for lst in ("incomes", "expenses"):
        for i, it in enumerate(getattr(plan, lst)):
            if it.start_month and it.end_month and it.end_month < it.start_month:
                add("END_BEFORE_START", "error", f"{_KIND[lst]} {_q(it.name)} ends ({it.end_month}) before it "
                    f"starts ({it.start_month}).", f"{lst}[{i}].end_month", [it.id])
    for gi, g in enumerate(plan.goals):
        if g.enabled and tg.month_index(start, g.target_month) < 1:
            add("GOAL_TOO_SOON", "error", f"Goal {_q(g.name)} is due in {g.target_month}, which is not after the "
                f"plan start ({start}). Pick a later month.", f"goals[{gi}].target_month", [g.id])
    for oi, o in enumerate(plan.one_offs):
        if tg.month_index(start, o.month) < 0:
            add("ONE_OFF_IN_PAST", "error", f"One-off {_q(o.name)} is in {o.month}, before the plan start "
                f"({start}).", f"one_offs[{oi}].month", [o.id])
    T_comp = tg.computed_horizon(plan)
    if plan.horizon_end_month:
        explicit = tg.month_index(start, plan.horizon_end_month) + 1
        if explicit < T_comp:
            add("HORIZON_BEFORE_GOAL", "error", f"The plan ends in {plan.horizon_end_month}, before a goal or "
                "one-off it contains. Move the end month later or leave it empty.", "horizon_end_month")
    T = tg.horizon(plan)
    if T > D.MAX_HORIZON_MONTHS:
        add("HORIZON_TOO_LONG", "error", f"The plan covers {T} months; the limit is {D.MAX_HORIZON_MONTHS} "
            "(50 years). Bring the last goal closer.", "horizon_end_month")

    # ---- debts
    for di, d in enumerate(plan.debts):
        if d.balance > 0 and d.emi <= d.balance * d.interest_rate_pct / 100.0 / 12.0:
            add("DEBT_NEVER_REPAID", "error", f"Debt {_q(d.name)}: the monthly instalment does not cover the "
                "interest, so the debt is never repaid.", f"debts[{di}].emi", [d.id])
        elif d.balance > 0 and d.remaining_months is not None:
            from .cashflow import amortize

            _, po = amortize(d.balance, d.interest_rate_pct, d.emi, 2400)
            if po is not None and abs((po + 1) - d.remaining_months) > 3:
                add("DEBT_TERM_MISMATCH", "warning", f"Debt {_q(d.name)}: at this instalment it is repaid in "
                    f"{po + 1} months, not {d.remaining_months}.", f"debts[{di}].remaining_months", [d.id])

    # ---- allowed classes
    for gi, g in enumerate(plan.goals):
        if not g.enabled or g.allowed_asset_class_ids is None:
            continue
        Dg = tg.month_index(start, g.target_month)
        known = [classes[a] for a in g.allowed_asset_class_ids if a in classes]
        if g.allowed_asset_class_ids and not known:
            continue  # already UNKNOWN_ASSET_CLASS
        if all(a.lock_in_months > 0 and a.lock_in_months > Dg for a in known):
            add("NO_ALLOWED_CLASS", "error", f"Goal {_q(g.name)} has no usable asset class: every allowed class has a "
                "lock-in that would end after the goal date.", f"goals[{gi}].allowed_asset_class_ids", [g.id])

    # ---- size
    if T <= D.MAX_HORIZON_MONTHS:
        n = estimate_variables(plan, T)
        if n > D.MAX_LP_VARIABLES:
            add("TOO_LARGE", "error", f"The plan is too large to optimize (about {n:,} variables, limit "
                f"{D.MAX_LP_VARIABLES:,}). Use fewer goals, classes or a 12-month block.")

    # ---- warnings
    if not plan.incomes:
        add("NO_INCOME", "warning", "No income is entered, so goals can only be funded from existing savings.",
            "incomes")
    if not any(g.enabled for g in plan.goals):
        add("NO_GOALS", "warning", "No goals are entered; the plan only shows your cash flow and emergency fund.",
            "goals")
    if len(classes) >= 2:
        C = correlation_matrix(plan)
        if not is_psd(C):
            add("CORRELATION_NOT_PSD", "warning", "The correlations are not internally consistent; the simulation "
                "uses the nearest consistent values.", "assumptions.correlations")
    if classes:
        top = max(a.expected_return_pct for a in classes.values())
        for di, d in enumerate(plan.debts):
            if d.balance > 0 and d.interest_rate_pct > top:
                add("HIGH_INTEREST_DEBT", "warning", f"Debt {_q(d.name)} costs {d.interest_rate_pct:g}% a year, more "
                    "than any asset class is assumed to earn. Paying it down early may help more than investing.",
                    f"debts[{di}]", [d.id])

    structural = {"DUPLICATE_ID", "UNKNOWN_ASSET_CLASS", "HORIZON_TOO_LONG"}
    if not any(i.code in structural for i in issues):
        from .cashflow import project_cashflow

        proj = project_cashflow(plan)
        neg = [proj.months[t] for t in range(proj.T) if proj.surplus[t] < -1e-9]
        if neg:
            add("NEGATIVE_SURPLUS", "warning", f"Spending is higher than income in {len(neg)} month(s), first: "
                f"{', '.join(neg[:6])}. Savings or investments must cover these months.", None)
        avg = sum(proj.surplus) / max(1, proj.T)
        if avg > 0:
            for gi, g in enumerate(plan.goals):
                if g.enabled and g.target_amount > 500 * avg:
                    add("GOAL_TARGET_HUGE", "warning", f"Goal {_q(g.name)} is more than 500 times your average "
                        "monthly surplus. Check the amount.", f"goals[{gi}].target_amount", [g.id])

    return FinancePreflightReport(ok=not any(i.severity == "error" for i in issues), issues=issues)
