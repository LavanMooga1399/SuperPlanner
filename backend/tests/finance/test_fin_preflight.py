"""Every preflight code of F.6 fires with its severity and a readable message (acceptance 1.5)."""

import pytest

from fin_helpers import expense, goal, income, plan, size_cap_plan
from superplanner.finance import WhatIfChanges, apply_what_if, preflight
from superplanner.finance.preflight import ERROR_CODES, WARNING_CODES

BASE = dict(incomes=[income()], expenses=[expense()], goals=[goal(name="Holiday")])


def _p(**kw):
    doc = dict(BASE)
    doc.update(kw)
    return plan(**doc)


CASES = [
    ("DUPLICATE_ID", "error", "Bonus", dict(incomes=[income(), income(id="salary", name="Bonus")])),
    ("DUPLICATE_ID", "error", "Holiday", dict(holdings=[dict(id="g1", name="Box", asset_class_id="cash",
                                                             amount=1)])),
    ("RESERVED_ID", "error", "Rainy day", dict(goals=[goal(id="emergency_fund", name="Rainy day")])),
    ("UNKNOWN_ASSET_CLASS", "error", "Box", dict(holdings=[dict(id="h", name="Box", asset_class_id="nope",
                                                                amount=1)])),
    ("UNKNOWN_ASSET_CLASS", "error", "Holiday", dict(goals=[goal(name="Holiday", allowed_asset_class_ids=["x"])])),
    ("UNKNOWN_HOLDING", "error", "Holiday", dict(goals=[goal(name="Holiday", earmarked=[
        dict(holding_id="ghost", amount=1)])])),
    ("EARMARK_EXCEEDS_HOLDING", "error", "Box", dict(
        holdings=[dict(id="h", name="Box", asset_class_id="cash", amount=100)],
        goals=[goal(name="Holiday", earmarked=[dict(holding_id="h", amount=100.02)])])),
    ("EARMARK_LOCKED_PAST_GOAL", "error", "Holiday", dict(
        holdings=[dict(id="h", name="Box", asset_class_id="cash", amount=100, locked_until_month="2028-01")],
        goals=[goal(name="Holiday", earmarked=[dict(holding_id="h", amount=10)])])),
    ("END_BEFORE_START", "error", "Salary", dict(incomes=[income(start_month="2027-05", end_month="2027-01")])),
    ("GOAL_TOO_SOON", "error", "Holiday", dict(goals=[goal(name="Holiday", month="2026-11")])),
    ("ONE_OFF_IN_PAST", "error", "Old bill", dict(one_offs=[dict(id="o", name="Old bill", month="2026-05",
                                                                 amount=5)])),
    ("HORIZON_TOO_LONG", "error", None, dict(goals=[goal(month="2077-01")])),
    ("HORIZON_BEFORE_GOAL", "error", None, dict(horizon_end_month="2027-06")),
    ("CASH_CLASS_INVALID", "error", "Cash", dict(assumptions=dict(asset_classes=[
        dict(id="cash", name="Cash", category="cash", expected_return_pct=3, volatility_pct=0, liquidity_days=5),
        dict(id="fixed_deposit", name="FD", category="debt", expected_return_pct=6, volatility_pct=1)]))),
    ("EF_CLASS_NOT_LIQUID", "error", "Slow", dict(
        assumptions=dict(asset_classes=[
            dict(id="cash", name="Cash", category="cash", expected_return_pct=3, volatility_pct=0),
            dict(id="slow", name="Slow", category="debt", expected_return_pct=6, volatility_pct=1,
                 lock_in_months=12)], correlations=[]),
        emergency_fund=dict(asset_class_id="slow"))),
    ("DEBT_NEVER_REPAID", "error", "Card", dict(debts=[dict(id="d", name="Card", balance=100000,
                                                            interest_rate_pct=36, emi=3000)])),
    ("NO_ALLOWED_CLASS", "error", "Holiday", dict(goals=[goal(name="Holiday", allowed_asset_class_ids=["govt_long"])])),
    ("TOO_LARGE", "error", None, None),
    ("NO_INCOME", "warning", None, dict(incomes=[])),
    ("NO_GOALS", "warning", None, dict(goals=[])),
    ("NEGATIVE_SURPLUS", "warning", "2027-01", dict(one_offs=[dict(id="o", name="Fees", month="2027-01",
                                                                   amount=5000)])),
    ("DEBT_TERM_MISMATCH", "warning", "Car loan", dict(debts=[dict(id="d", name="Car loan", balance=100000,
                                                                   interest_rate_pct=10, emi=5000,
                                                                   remaining_months=12)])),
    ("CORRELATION_NOT_PSD", "warning", None, dict(assumptions=dict(correlations=[
        dict(a="cash", b="fixed_deposit", rho=0.99), dict(a="fixed_deposit", b="short_debt", rho=0.99),
        dict(a="cash", b="short_debt", rho=-0.99)]))),
    ("HIGH_INTEREST_DEBT", "warning", "Card", dict(debts=[dict(id="d", name="Card", balance=10000,
                                                               interest_rate_pct=42, emi=2000)])),
    ("GOAL_TARGET_HUGE", "warning", "Holiday", dict(goals=[goal(name="Holiday", target=600 * 1000.0)])),
]


@pytest.mark.parametrize("code,severity,name,kw", CASES, ids=[c[0] + str(i) for i, c in enumerate(CASES)])
def test_code_fires(code, severity, name, kw):
    p = size_cap_plan(block=6, spread=False) if kw is None else _p(**kw)
    rep = preflight(p)
    hits = [i for i in rep.issues if i.code == code]
    assert hits, [i.code for i in rep.issues]
    assert all(i.severity == severity for i in hits)
    if name:
        assert any(name in i.message for i in hits), [i.message for i in hits]
    if severity == "error":
        assert not rep.ok


def test_every_code_is_covered():
    covered = {c[0] for c in CASES}
    assert covered == set(ERROR_CODES + WARNING_CODES) - {"START_MONTH_MISSING"}


def test_clean_plan_and_missing_start():
    assert preflight(_p()).ok
    rep = preflight(plan(start_month=None))
    assert not rep.ok and rep.issues[0].code == "START_MONTH_MISSING"


def test_issue_fields_point_to_items():
    rep = preflight(_p(goals=[goal(name="Holiday", month="2026-10")]))
    i = next(i for i in rep.issues if i.code == "GOAL_TOO_SOON")
    assert i.field == "goals[0].target_month" and i.item_ids == ["g1"]


def test_whatif_ids_pass_preflight():
    """[R12]: derived what-if snapshots must pass preflight."""
    p = _p()
    derived = apply_what_if(p, WhatIfChanges(extra_monthly_savings=500, income_drop=dict(
        start_month="2027-01", months=3, percent=20)))
    assert any(i.id == "whatif_extra" for i in derived.incomes)
    assert preflight(derived).ok


def test_disabled_goal_is_ignored():
    rep = preflight(_p(goals=[goal(name="Old", month="2026-01", enabled=False)]))
    assert rep.ok
