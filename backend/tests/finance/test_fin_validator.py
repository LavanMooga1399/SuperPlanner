"""The independent validator catches every F.11 code on minimal hand-made results; values exactly at the
tolerance pass and values just beyond fail (acceptance 1.7). Written before the optimizer tests (plan step 5).

Base: inflation 0, zero-return classes (rho = 1), surplus 1000/month, goal g1 = 12000 at month 12, tol = 1."""

import pytest

from fin_helpers import expense, goal, hand_result, income, zplan
from superplanner.finance import validate_result


def P(**kw):
    doc = dict(incomes=[income(amount=2000)], expenses=[expense(amount=1000)],
               goals=[goal(priority="must")])
    doc.update(kw)
    return zplan(**doc)


LINE = ("g1", "safe", "2026-11", "2027-10", 1000.0)


def codes(p, r):
    return {(v.code, v.severity) for v in validate_result(p, r)}


def hard_codes(p, r):
    return {v.code for v in validate_result(p, r) if v.severity == "hard"}


def test_clean_base_result():
    p = P()
    r = hand_result(p, lines=[LINE], goals={"g1": dict(planned_value_real=12000)})
    assert validate_result(p, r) == []


def test_cash_negative_at_and_beyond_tolerance():
    p = P()
    ok = hand_result(p, lines=[LINE, ("g1", "safe", "2026-11", "2026-11", 1.0)])
    assert "CASH_NEGATIVE" not in hard_codes(p, ok)
    bad = hand_result(p, lines=[LINE, ("g1", "safe", "2026-11", "2026-11", 1.01)])
    vs = [v for v in validate_result(p, bad) if v.code == "CASH_NEGATIVE"]
    assert len(vs) == 1 and vs[0].severity == "hard" and vs[0].months == ["2026-11", "2027-10"]


def test_cash_start_includes_sold_to_cash_rows():
    holdings = [dict(id="h", name="Shares", asset_class_id="eq", amount=5000)]
    p = P(holdings=holdings, constraints=dict(rebalance_cost_pct=0))
    r = hand_result(p, lines=[LINE, ("g1", "safe", "2026-11", "2026-11", 5000.0)],
                    rows=[("h", "cash_buffer", 5000, "sold_to_cash")],
                    goals={"g1": dict(planned_value_real=17000)})
    assert "CASH_NEGATIVE" not in hard_codes(p, r)
    r2 = hand_result(p, lines=[LINE, ("g1", "safe", "2026-11", "2026-11", 5000.0)],
                     rows=[("h", "unallocated", 5000, "unallocated")], goals={"g1": dict(planned_value_real=17000)})
    assert "CASH_NEGATIVE" in hard_codes(p, r2)


def test_contribution_negative():
    p = P()
    r = hand_result(p, lines=[LINE, ("g1", "safe", "2027-01", "2027-01", -5.0)])
    assert ("CONTRIBUTION_NEGATIVE", "hard") in codes(p, r)


def test_contribution_after_goal():
    p = P()
    assert "CONTRIBUTION_AFTER_GOAL" not in hard_codes(p, hand_result(p, lines=[LINE]))
    r = hand_result(p, lines=[("g1", "safe", "2026-11", "2027-11", 1000.0)],
                    goals={"g1": dict(planned_value_real=13000)})
    assert "CONTRIBUTION_AFTER_GOAL" in hard_codes(p, r)


def test_class_not_allowed_for_contribution_and_buy():
    p = P(goals=[goal(priority="must", allowed_asset_class_ids=["safe"])])
    r = hand_result(p, lines=[("g1", "eq", "2026-11", "2027-10", 1000.0)])
    assert "CLASS_NOT_ALLOWED" in hard_codes(p, r)
    p2 = P(goals=[goal(priority="must", allowed_asset_class_ids=["safe"],
                       earmarked=[dict(holding_id="h", amount=1000)])],
           holdings=[dict(id="h", name="Deposit", asset_class_id="safe", amount=1000)])
    r2 = hand_result(p2, lines=[LINE], rows=[("h", "g1", 1000, "earmark")],
                     rebalances=[("2026-11", "g1", {"safe": 1000}, {"eq": 999})],
                     goals={"g1": dict(planned_value_real=12999)})
    assert "CLASS_NOT_ALLOWED" in hard_codes(p2, r2)


def test_lockin_past_goal_boundary():
    p = P(goals=[goal(priority="must", target=1000, month="2028-11")])           # D = 24, lock 24
    ok = hand_result(p, lines=[("g1", "lock", "2026-11", "2026-11", 1000.0)])
    assert "LOCKIN_PAST_GOAL" not in hard_codes(p, ok)
    bad = hand_result(p, lines=[("g1", "lock", "2026-12", "2026-12", 1000.0)])
    assert "LOCKIN_PAST_GOAL" in hard_codes(p, bad)


def test_locked_sold_holding_lock_class_and_sold_to_cash():
    holdings = [dict(id="h", name="Shares", asset_class_id="eq", amount=5000, locked_until_month="2027-05"),
                dict(id="l", name="Lock", asset_class_id="lock", amount=1000)]
    g = goal(priority="must", target=10000, month="2036-11", risk_tolerance=5,
             earmarked=[dict(holding_id="h", amount=5000), dict(holding_id="l", amount=1000)])
    p = P(holdings=holdings, goals=[g])
    rows = [("h", "g1", 5000, "earmark"), ("l", "g1", 1000, "earmark")]
    sell_locked = hand_result(p, rows=rows, rebalances=[("2026-11", "g1", {"eq": 5000}, {"safe": 4995})],
                              goals={"g1": dict(planned_value_real=5995)})
    assert "LOCKED_SOLD" in hard_codes(p, sell_locked)
    sell_lockclass = hand_result(p, rows=rows, rebalances=[("2026-11", "g1", {"lock": 1000}, {"safe": 999})],
                                 goals={"g1": dict(planned_value_real=5999)})
    assert "LOCKED_SOLD" in hard_codes(p, sell_lockclass)
    p2 = P(holdings=holdings)
    sold = hand_result(p2, lines=[LINE], rows=[("h", "cash_buffer", 5000, "sold_to_cash")])
    assert "LOCKED_SOLD" in hard_codes(p2, sold)


def test_risk_cap_contribution_mix_boundary():
    p = P()                                         # tolerance 3 -> 60 %, glide(12) = 0.2 -> cap 12 %
    ok = hand_result(p, lines=[("g1", "eq", "2026-11", "2027-10", 125.0), ("g1", "safe", "2026-11", "2027-10", 875.0)])
    assert "RISK_CAP_EXCEEDED" not in hard_codes(p, ok)
    bad = hand_result(p, lines=[("g1", "eq", "2026-11", "2027-10", 126.0),
                                ("g1", "safe", "2026-11", "2027-10", 874.0)])
    assert "RISK_CAP_EXCEEDED" in hard_codes(p, bad)


@pytest.mark.parametrize("eq,expect", [(1251.0, False), (1252.0, True)])
def test_risk_cap_bucket_boundary(eq, expect):
    holdings = [dict(id="e", name="Shares", asset_class_id="eq", amount=eq),
                dict(id="s", name="Deposit", asset_class_id="safe", amount=10000 - eq)]
    g = goal(priority="must", target=10000, earmarked=[dict(holding_id="e", amount=eq),
                                                      dict(holding_id="s", amount=10000 - eq)])
    p = P(holdings=holdings, goals=[g])
    r = hand_result(p, rows=[("e", "g1", eq, "earmark"), ("s", "g1", 10000 - eq, "earmark")],
                    goals={"g1": dict(planned_value_real=10000)})
    assert ("RISK_CAP_EXCEEDED" in hard_codes(p, r)) is expect


def test_risk_cap_allowance_for_locked_positions():
    """[R8]: a locked risky holding does not count against the glide cap until it unlocks."""
    holdings = [dict(id="e", name="Shares", asset_class_id="eq", amount=5000, locked_until_month="2027-11")]
    g = goal(priority="must", target=5000, earmarked=[dict(holding_id="e", amount=5000)])
    p = P(holdings=holdings, goals=[g])
    r = hand_result(p, rows=[("e", "g1", 5000, "earmark")], goals={"g1": dict(planned_value_real=5000)})
    assert "RISK_CAP_EXCEEDED" not in hard_codes(p, r)


def _cap_plan(eq: float, **constraints):
    holdings = [dict(id="e", name="Shares", asset_class_id="eq", amount=eq),
                dict(id="s", name="Deposit", asset_class_id="safe", amount=10000 - eq)]
    g = goal(priority="must", target=10000, month="2036-11", risk_tolerance=5,
             earmarked=[dict(holding_id="e", amount=eq), dict(holding_id="s", amount=10000 - eq)])
    p = P(holdings=holdings, goals=[g], constraints=constraints)
    r = hand_result(p, rows=[("e", "g1", eq, "earmark"), ("s", "g1", 10000 - eq, "earmark")],
                    goals={"g1": dict(planned_value_real=10000)})
    return p, r


def test_equity_cap_boundary():
    p, r = _cap_plan(1051.0, max_equity_pct=10)
    assert "EQUITY_CAP_EXCEEDED" not in hard_codes(p, r)
    p, r = _cap_plan(1052.0, max_equity_pct=10)
    assert "EQUITY_CAP_EXCEEDED" in hard_codes(p, r)


def test_class_cap_boundary():
    p, r = _cap_plan(10000 - 5051.0, max_class_pct={"safe": 50})
    assert "CLASS_CAP_EXCEEDED" not in hard_codes(p, r)
    p, r = _cap_plan(10000 - 5052.0, max_class_pct={"safe": 50})
    assert "CLASS_CAP_EXCEEDED" in hard_codes(p, r)


def test_ef_before_discretionary():
    p = P(emergency_fund=dict(months_of_essentials=1, asset_class_id="safe"), goals=[goal(priority="should",
                                                                                          target=11000)])
    ok = hand_result(p, lines=[("g1", "safe", "2026-12", "2027-10", 1000.0)])
    assert "EF_BEFORE_DISCRETIONARY" not in hard_codes(p, ok) and "CASH_NEGATIVE" not in hard_codes(p, ok)
    bad = hand_result(p, lines=[("g1", "safe", "2026-11", "2027-10", 1000.0)])
    assert "EF_BEFORE_DISCRETIONARY" in hard_codes(p, bad)


@pytest.mark.parametrize("amount,expect", [(1001.0, False), (1001.5, True)])
def test_holding_overassigned_boundary(amount, expect):
    p = P(holdings=[dict(id="h", name="Deposit", asset_class_id="safe", amount=1000)])
    r = hand_result(p, lines=[LINE], rows=[("h", "g1", amount, "assigned")],
                    goals={"g1": dict(planned_value_real=12000 + amount)})
    assert ("HOLDING_OVERASSIGNED" in hard_codes(p, r)) is expect


@pytest.mark.parametrize("buy,expect", [(999.0, False), (1000.0, False), (1000.01, True)])
def test_rebalance_unbalanced_boundary(buy, expect):
    p = P(holdings=[dict(id="s", name="Deposit", asset_class_id="safe", amount=5000)],
          goals=[goal(priority="must", target=4999, month="2036-11", risk_tolerance=5,
                      earmarked=[dict(holding_id="s", amount=5000)])])
    r = hand_result(p, rows=[("s", "g1", 5000, "earmark")], rebalances=[("2026-11", "g1", {"safe": 1000},
                                                                         {"eq": buy})],
                    goals={"g1": dict(planned_value_real=4000 + buy)})
    assert ("REBALANCE_UNBALANCED" in hard_codes(p, r)) is expect


@pytest.mark.parametrize("reported,expect", [(12012.0, False), (11988.0, False), (12012.5, True)])
def test_bucket_mismatch_boundary(reported, expect):
    p = P()
    r = hand_result(p, lines=[LINE], goals={"g1": dict(planned_value_real=reported)})
    assert ("BUCKET_MISMATCH" in hard_codes(p, r)) is expect


@pytest.mark.parametrize("amount,expect", [(999.0, False), (998.9, True)])
def test_goal_shortfall_soft(amount, expect):
    p = P()
    r = hand_result(p, lines=[("g1", "safe", "2026-11", "2027-10", amount)],
                    goals={"g1": dict(planned_value_real=12 * amount)})
    vs = [v for v in validate_result(p, r) if v.code == "GOAL_SHORTFALL"]
    assert bool(vs) is expect
    assert all(v.severity == "soft" for v in vs)
    assert not hard_codes(p, r)


@pytest.mark.parametrize("prob,expect", [(0.85, False), (0.8499, True)])
def test_goal_probability_low_soft(prob, expect):
    p = P()
    r = hand_result(p, lines=[LINE], goals={"g1": dict(planned_value_real=12000, success_probability=prob)})
    assert (("GOAL_PROBABILITY_LOW", "soft") in codes(p, r)) is expect


@pytest.mark.parametrize("liq,expect", [(0.10, False), (0.1001, True)])
def test_liquidity_risk_soft(liq, expect):
    p = P()
    r = hand_result(p, lines=[LINE], goals={"g1": dict(planned_value_real=12000)}, liquidity=liq)
    assert (("LIQUIDITY_RISK", "soft") in codes(p, r)) is expect


def test_every_code_has_a_test():
    import inspect
    import sys

    src = inspect.getsource(sys.modules[__name__])
    for code in ("CASH_NEGATIVE", "CONTRIBUTION_NEGATIVE", "CONTRIBUTION_AFTER_GOAL", "CLASS_NOT_ALLOWED",
                 "LOCKIN_PAST_GOAL", "LOCKED_SOLD", "RISK_CAP_EXCEEDED", "EQUITY_CAP_EXCEEDED", "CLASS_CAP_EXCEEDED",
                 "EF_BEFORE_DISCRETIONARY", "HOLDING_OVERASSIGNED", "REBALANCE_UNBALANCED", "BUCKET_MISMATCH",
                 "GOAL_SHORTFALL", "GOAL_PROBABILITY_LOW", "LIQUIDITY_RISK"):
        assert src.count(f'"{code}"') >= 2, code
