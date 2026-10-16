"""Cash-flow arithmetic on hand-calculated fixtures (F.7; acceptance 1.6)."""

import pytest

from fin_helpers import expense, goal, income, zero_assumptions, zplan
from superplanner.finance import project_cashflow, summarize_cashflow
from superplanner.finance.cashflow import ef_complete_t


def _a(infl: float = 0.0) -> dict:
    a = zero_assumptions()
    a["inflation_pct"] = infl
    return a


def test_growth_steps_only_on_anniversaries():
    p = zplan(incomes=[income(amount=1000, growth_pct=10), income(id="late", amount=1000, growth_pct=10,
                                                                  start_month="2027-02")],
              goals=[goal(month="2029-11")])
    inc = project_cashflow(p).income
    assert inc[0] == 1000 and inc[2] == 1000 and inc[3] == 2000 and inc[11] == 2000
    assert inc[12] == pytest.approx(1100 + 1000)       # late stream (t0 = 3) has not had an anniversary yet
    assert inc[14] == pytest.approx(1100 + 1000)
    assert inc[15] == pytest.approx(1100 + 1100)
    assert inc[24] == pytest.approx(1210 + 1100)


def test_item_starting_before_plan_start_is_clamped():
    p = zplan(incomes=[income(amount=1000, growth_pct=10, start_month="2025-05")], goals=[goal(month="2028-11")])
    inc = project_cashflow(p).income
    assert inc[0] == 1000 and inc[11] == 1000 and inc[12] == pytest.approx(1100)


def test_inflation_linked_vs_fixed_nominal():
    p = zplan(assumptions=_a(12.0), goals=[goal(month="2028-11")],
              expenses=[expense(id="lin", amount=100), expense(id="fix", amount=100, inflation_linked=False),
                        expense(id="fees", amount=100, inflation_pct=24.0)])
    proj = project_cashflow(p)
    e = proj.essential
    assert e[0] == pytest.approx(300)
    assert e[12] == pytest.approx(100 + 100 / 1.12 + 100 * 1.24 / 1.12)
    assert e[24] == pytest.approx(100 + 100 / 1.12 ** 2 + 100 * (1.24 / 1.12) ** 2)


def test_frequencies():
    p = zplan(goals=[goal(month="2028-11")],
              expenses=[expense(id="q", amount=300, frequency="quarterly"),
                        expense(id="y", amount=1200, frequency="yearly", essential=False),
                        expense(id="o", amount=50, frequency="once", start_month="2027-01")])
    proj = project_cashflow(p)
    assert [proj.essential[t] for t in range(7)] == [300, 0, 50, 300, 0, 0, 300]
    assert proj.discretionary[0] == 1200 and proj.discretionary[12] == 1200 and proj.discretionary[1] == 0


def test_debt_amortization_payoff_month():
    p = zplan(goals=[goal(month="2027-11")],
              debts=[dict(id="d", name="Loan", balance=10000, interest_rate_pct=12, emi=2000)])
    proj = project_cashflow(p)
    assert proj.debt_payoff == {"d": 5}
    assert proj.debt_payments[:5] == [2000] * 5
    assert proj.debt_payments[5] == pytest.approx(311.17138581, abs=1e-6)
    assert proj.debt_payments[6] == 0
    s = summarize_cashflow(proj)
    assert s.debts_paid_off[0].month == "2027-04"


def test_one_offs_linked_and_nominal():
    p = zplan(assumptions=_a(12.0), goals=[goal(month="2028-11")],
              one_offs=[dict(id="b", name="Bonus", kind="inflow", month="2027-11", amount=1000),
                        dict(id="f", name="Fee", month="2027-11", amount=1120, inflation_linked=False)])
    proj = project_cashflow(p)
    assert proj.one_off_net[12] == pytest.approx(1000 - 1000)


def test_ef_target_counts_only_items_active_at_start():
    p = zplan(emergency_fund=dict(months_of_essentials=6, asset_class_id="safe"), goals=[goal(month="2028-11")],
              incomes=[income(amount=10000)],
              expenses=[expense(amount=1000), expense(id="later", amount=500, start_month="2027-03"),
                        expense(id="q", amount=300, frequency="quarterly"),
                        expense(id="fun", amount=700, essential=False),
                        expense(id="whatif_x", amount=999)],
              debts=[dict(id="d", name="Loan", balance=50000, interest_rate_pct=0, emi=2000)])
    proj = project_cashflow(p)
    assert proj.ef_target == pytest.approx(6 * (1000 + 100 + 2000))     # [R3]


def test_ef_waterfall_and_t_E():
    p = zplan(emergency_fund=dict(months_of_essentials=2, asset_class_id="safe"), goals=[goal(month="2028-11")],
              incomes=[income(amount=2000)], expenses=[expense(amount=1000)])
    proj = project_cashflow(p)
    assert proj.ef_target == 2000
    assert proj.ef_contribution[:3] == [1000, 1000, 0]
    assert proj.ef_balance[:3] == [0, 1000, 2000]
    assert proj.investable[:3] == [0, 0, 1000]
    assert proj.ef_complete_index == 2 and ef_complete_t(proj) == 2
    half = zplan(emergency_fund=dict(months_of_essentials=2, asset_class_id="safe", build_share=0.5),
                 goals=[goal(month="2028-11")], incomes=[income(amount=2000)], expenses=[expense(amount=1000)])
    proj2 = project_cashflow(half)
    assert proj2.ef_contribution[:5] == [500, 500, 500, 500, 0]
    assert proj2.ef_complete_index == 4
    never = zplan(emergency_fund=dict(months_of_essentials=2, asset_class_id="safe"), goals=[goal(month="2027-11")],
                  incomes=[income(amount=1000)], expenses=[expense(amount=1000)])
    assert project_cashflow(never).ef_complete_index is None
    assert ef_complete_t(project_cashflow(never)) == 13


def test_holdings_split_ef_buffer_pool():
    holdings = [dict(id="h_safe", name="Deposit", asset_class_id="safe", amount=1500),
                dict(id="h_cash", name="Cash", asset_class_id="cash", amount=3000),
                dict(id="h_eq", name="Shares", asset_class_id="eq", amount=5000),
                dict(id="h_lock", name="Locked", asset_class_id="lock", amount=1000, locked_until_month="2027-06")]
    p = zplan(emergency_fund=dict(months_of_essentials=2, asset_class_id="safe"), incomes=[income(amount=2000)],
              expenses=[expense(amount=1000)], holdings=holdings,
              goals=[goal(month="2029-11", earmarked=[dict(holding_id="h_eq", amount=2000)])])
    proj = project_cashflow(p)
    assert proj.ef_initial == 2000 and proj.cash_buffer_initial == 2500
    pool = {a.holding_id: (a.amount, a.locked_until_index) for a in proj.assignable}
    assert pool == {"h_eq": (3000, None), "h_lock": (1000, 7)}
    by_src: dict[str, float] = {}
    for s in proj.initial_splits:
        by_src[s.source] = by_src.get(s.source, 0) + s.amount
    assert by_src == {"earmark": 2000, "initial_ef": 2000, "initial_cash": 2500, "pool": 4000}
    assert sum(by_src.values()) == sum(h["amount"] for h in holdings)
    assert proj.ef_complete_index == 0


def test_summary_shape():
    p = zplan(incomes=[income(amount=2000)], expenses=[expense(amount=1000)], goals=[goal(month="2028-11")],
              one_offs=[dict(id="o", name="Fee", month="2027-02", amount=5000)])
    s = summarize_cashflow(project_cashflow(p))
    assert s.avg_monthly_surplus_first_year == pytest.approx((12 * 1000 - 5000) / 12, abs=0.01)
    assert s.negative_surplus_months == ["2027-02"] and s.min_monthly_surplus == -4000
    assert s.years[0].surplus == 7000 and s.years[0].start_month == "2026-11" and len(s.years) == 3
