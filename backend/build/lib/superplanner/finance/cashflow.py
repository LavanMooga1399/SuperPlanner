"""Cash-flow engine (FINANCE.md section 7): pure, deterministic, real terms (today's money).

`flow_components` splits every flow into a part that is fixed in nominal terms and a part that moves with
prices, so the simulator can re-price the same plan under random inflation (9.2) with identical item rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import timegrid as tg
from .defaults import WHATIF_PREFIX
from .model import (AssignableItem, CashflowProjection, CashflowSummary, CashflowYear, DebtPayoff, FinancePlan,
                    InitialSplit)
from .returns import gamma, pi_general


@dataclass
class FlowComponents:
    """Per-month flows, length T. Real value in a world with price index P is
    `(inc_int + inc_nonint + nominal_fixed) / P + inc_int_linked + real_linked`.

    Inflation-linked incomes (PHASE2 1.7) are real: interruptible ones are kept apart in `inc_int_linked` so an
    income interruption can zero them; non-interruptible ones are part of `real_linked`."""
    T: int
    inc_int: np.ndarray            # nominal income of interruptible streams
    inc_nonint: np.ndarray         # nominal income of other streams
    real_linked: np.ndarray        # signed real flows that move with prices (linked expenses and one-offs)
    nominal_fixed: np.ndarray      # signed nominal flows (fixed expenses, EMIs, nominal one-offs)
    inc_int_linked: np.ndarray = field(default=None)  # type: ignore[assignment]  # real, interruptible, linked
    # deterministic real breakdown at the plan inflation (for reporting)
    income: np.ndarray = field(default=None)  # type: ignore[assignment]
    essential: np.ndarray = field(default=None)  # type: ignore[assignment]
    discretionary: np.ndarray = field(default=None)  # type: ignore[assignment]
    debt_payments: np.ndarray = field(default=None)  # type: ignore[assignment]
    one_off_net: np.ndarray = field(default=None)  # type: ignore[assignment]
    price: np.ndarray = field(default=None)  # type: ignore[assignment]
    debt_first_payment: dict[str, float] = field(default_factory=dict)
    debt_payoff: dict[str, int | None] = field(default_factory=dict)


def _start(plan: FinancePlan) -> str:
    if plan.start_month is None:
        raise ValueError("plan.start_month must be set (services fill it before calling the engine)")
    return plan.start_month


def expense_spread(plan: FinancePlan, inflation_pct: float | None, t: np.ndarray) -> np.ndarray:
    pi = pi_general(plan)
    pie = pi if inflation_pct is None else inflation_pct / 100.0
    return ((1.0 + pie) / (1.0 + pi)) ** (t / 12.0)


def amortize(balance: float, rate_pct: float, emi: float, T: int) -> tuple[np.ndarray, int | None]:
    """Nominal payments per month and the payoff month (index of the last payment), 7.2."""
    pay = np.zeros(T)
    j = rate_pct / 100.0 / 12.0
    bal = balance
    payoff = None
    if bal <= 0:
        return pay, None
    for t in range(T):
        due = bal * (1.0 + j)
        p = min(emi, due)
        pay[t] = p
        bal = due - p
        if bal <= 1e-9:
            payoff = t
            break
    return pay, payoff


def flow_components(plan: FinancePlan, T: int | None = None) -> FlowComponents:
    start = _start(plan)
    T = tg.horizon(plan) if T is None else T
    pi = pi_general(plan)
    t = np.arange(T, dtype=float)
    P = (1.0 + pi) ** (t / 12.0)
    inc_int = np.zeros(T)
    inc_nonint = np.zeros(T)
    real_linked = np.zeros(T)
    nominal_fixed = np.zeros(T)
    essential = np.zeros(T)
    discretionary = np.zeros(T)
    debt_pay = np.zeros(T)
    one_off_nominal = np.zeros(T)
    one_off_real = np.zeros(T)
    inc_int_linked = np.zeros(T)
    inc_real_linked = np.zeros(T)   # non-interruptible linked incomes (real; also in real_linked)

    for inc in plan.incomes:
        t0, t1 = tg.item_bounds(start, inc.start_month, inc.end_month, T)
        g = inc.growth_pct / 100.0
        if inc.inflation_linked:
            # amount in today's money; growth_pct is the yearly raise above inflation (real)
            target = inc_int_linked if inc.interruptible else inc_real_linked
        else:
            target = inc_int if inc.interruptible else inc_nonint
        for m in tg.occurrence_months(t0, t1, inc.frequency):
            target[m] += inc.amount * (1.0 + g) ** ((m - t0) // 12)
    real_linked += inc_real_linked

    for e in plan.expenses:
        t0, t1 = tg.item_bounds(start, e.start_month, e.end_month, T)
        months = tg.occurrence_months(t0, t1, e.frequency)
        if not months:
            continue
        idx = np.array(months)
        dest = essential if e.essential else discretionary
        if e.inflation_linked:
            vals = e.amount * expense_spread(plan, e.inflation_pct, idx.astype(float))
            real_linked[idx] -= vals
            dest[idx] += vals
        else:
            nominal_fixed[idx] -= e.amount
            dest[idx] += e.amount / P[idx]

    payoff: dict[str, int | None] = {}
    first: dict[str, float] = {}
    for d in plan.debts:
        pay, po = amortize(d.balance, d.interest_rate_pct, d.emi, T)
        payoff[d.id] = po
        first[d.id] = float(pay[0]) if T else 0.0
        nominal_fixed -= pay
        debt_pay += pay / P

    for o in plan.one_offs:
        to = tg.month_index(start, o.month)
        if to < 0 or to >= T:
            continue
        sign = 1.0 if o.kind == "inflow" else -1.0
        if o.inflation_linked:
            real_linked[to] += sign * o.amount
            one_off_real[to] += sign * o.amount
        else:
            nominal_fixed[to] += sign * o.amount
            one_off_nominal[to] += sign * o.amount

    income = (inc_int + inc_nonint) / P + inc_int_linked + inc_real_linked
    return FlowComponents(T=T, inc_int=inc_int, inc_nonint=inc_nonint, real_linked=real_linked,
                          nominal_fixed=nominal_fixed, inc_int_linked=inc_int_linked, income=income, essential=essential,
                          discretionary=discretionary, debt_payments=debt_pay,
                          one_off_net=one_off_real + one_off_nominal / P, price=P,
                          debt_first_payment=first, debt_payoff=payoff)


def ef_target(plan: FinancePlan, fc: FlowComponents) -> float:
    """EF* = months x (essential monthly equivalents active at t=0, excluding what-if items + EMIs at t=0) [R3]."""
    m = plan.emergency_fund.months_of_essentials
    if m <= 0:
        return 0.0
    start = _start(plan)
    monthly = 0.0
    for e in plan.expenses:
        if not e.essential or e.id.startswith(WHATIF_PREFIX):
            continue
        t0, t1 = tg.item_bounds(start, e.start_month, e.end_month, max(fc.T, 1))
        if not (t0 <= 0 <= t1):
            continue
        monthly += e.amount * tg.MONTHLY_FACTOR[e.frequency]  # f_e(0) == 1 for linked and fixed items
    for d in plan.debts:
        if d.balance > 0:
            monthly += fc.debt_first_payment.get(d.id, 0.0)
    return m * monthly


def locked_index(plan: FinancePlan, locked_until_month: str | None) -> int | None:
    if locked_until_month is None:
        return None
    return tg.month_index(_start(plan), locked_until_month)


def split_holdings(plan: FinancePlan, ef_star: float) -> tuple[list[InitialSplit], float, float,
                                                                list[AssignableItem]]:
    """Section 7.3 initial split. Returns (splits, EF_0, B0_fixed, pool)."""
    ef_cls = plan.emergency_fund.asset_class_id
    cash_cls = plan.assumptions.cash_class_id
    splits: list[InitialSplit] = []
    free: dict[str, float] = {}
    for h in plan.holdings:
        free[h.id] = h.amount
    for g in plan.goals:
        if not g.enabled:
            continue
        for em in g.earmarked:
            if em.holding_id not in free:
                continue
            amt = min(em.amount, free[em.holding_id])
            if amt <= 0:
                continue
            free[em.holding_id] -= amt
            splits.append(InitialSplit(holding_id=em.holding_id, source="earmark", amount=amt, goal_id=g.id))

    def unlocked(h) -> bool:
        li = locked_index(plan, h.locked_until_month)
        return li is None or li <= 0

    ef0 = 0.0
    order = [h for h in plan.holdings if h.asset_class_id == ef_cls and unlocked(h)]
    order += [h for h in plan.holdings if h.asset_class_id == cash_cls and ef_cls != cash_cls and unlocked(h)]
    for h in order:
        need = ef_star - ef0
        if need <= 0:
            break
        amt = min(need, free[h.id])
        if amt > 0:
            free[h.id] -= amt
            ef0 += amt
            splits.append(InitialSplit(holding_id=h.id, source="initial_ef", amount=amt, goal_id="emergency_fund"))
    b0 = 0.0
    pool: list[AssignableItem] = []
    for h in plan.holdings:
        rest = free[h.id]
        if rest <= 0:
            continue
        if h.asset_class_id == cash_cls and unlocked(h):
            b0 += rest
            splits.append(InitialSplit(holding_id=h.id, source="initial_cash", amount=rest, goal_id="cash_buffer"))
        else:
            li = locked_index(plan, h.locked_until_month)
            pool.append(AssignableItem(holding_id=h.id, asset_class_id=h.asset_class_id, amount=rest,
                                       locked_until_index=li if (li is not None and li > 0) else None))
            splits.append(InitialSplit(holding_id=h.id, source="pool", amount=rest))
    return splits, ef0, b0, pool


def project_cashflow(plan: FinancePlan) -> CashflowProjection:
    start = _start(plan)
    fc = flow_components(plan)
    T = fc.T
    surplus = fc.income - fc.essential - fc.discretionary - fc.debt_payments + fc.one_off_net
    ef_star = ef_target(plan, fc)
    splits, ef0, b0, pool = split_holdings(plan, ef_star)
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    ef_ac = classes.get(plan.emergency_fund.asset_class_id)
    g_ef = gamma(ef_ac, pi_general(plan)) if ef_ac is not None else 1.0
    share = plan.emergency_fund.build_share
    ef_bal = np.zeros(T)
    ef_c = np.zeros(T)
    EF = ef0
    t_E: int | None = 0 if EF >= ef_star - 1.0 else None
    for t in range(T):
        ef_bal[t] = EF
        if t_E is None and EF >= ef_star - 1.0:
            t_E = t
        c = min(share * max(surplus[t], 0.0), max(0.0, ef_star - EF))
        ef_c[t] = c
        EF = (EF + c) * g_ef
    # t_E is None when the EF completes only after the horizon: treated as never (index T)
    investable = surplus - ef_c
    return CashflowProjection(
        start_month=start, T=T, months=tg.month_list(start, T), income=fc.income.tolist(),
        essential=fc.essential.tolist(), discretionary=fc.discretionary.tolist(),
        debt_payments=fc.debt_payments.tolist(), one_off_net=fc.one_off_net.tolist(), surplus=surplus.tolist(),
        ef_contribution=ef_c.tolist(), ef_balance=ef_bal.tolist(), investable=investable.tolist(),
        ef_target=ef_star, ef_initial=ef0, ef_complete_index=t_E, cash_buffer_initial=b0, assignable=pool,
        debt_payoff=fc.debt_payoff, price_index=fc.price.tolist(), initial_splits=splits)


def ef_complete_t(proj: CashflowProjection) -> int:
    """`t_E` as an index (`T` when the EF never completes inside the horizon)."""
    return proj.T if proj.ef_complete_index is None else proj.ef_complete_index


def summarize_cashflow(proj: CashflowProjection) -> CashflowSummary:
    T = proj.T
    s = proj.surplus
    first = s[: min(12, T)]
    years: list[CashflowYear] = []
    for y in range((T + 11) // 12):
        sl = slice(12 * y, min(T, 12 * y + 12))
        years.append(CashflowYear(
            year=y, start_month=proj.months[12 * y], income=round(sum(proj.income[sl]), 2),
            essential=round(sum(proj.essential[sl]), 2), discretionary=round(sum(proj.discretionary[sl]), 2),
            debt_payments=round(sum(proj.debt_payments[sl]), 2), one_off_net=round(sum(proj.one_off_net[sl]), 2),
            surplus=round(sum(s[sl]), 2)))
    neg = [proj.months[t] for t in range(T) if s[t] < 0][:12]
    payoffs = [DebtPayoff(debt_id=d, month=(proj.months[i] if i is not None else None))
               for d, i in proj.debt_payoff.items()]
    return CashflowSummary(
        ef_target=round(proj.ef_target, 2), ef_initial=round(proj.ef_initial, 2),
        ef_complete_month=(proj.months[proj.ef_complete_index] if proj.ef_complete_index is not None else None),
        avg_monthly_surplus_first_year=round(sum(first) / max(1, len(first)), 2),
        min_monthly_surplus=round(min(s) if s else 0.0, 2), negative_surplus_months=neg,
        debts_paid_off=payoffs, years=years)
