"""F4: the independent checker itself catches each kind of hard violation (mutation tests on a real result),
so a clean verdict elsewhere means something."""

from __future__ import annotations

import copy

import pytest

from finint_helpers import Model, independent_check, mstr


@pytest.fixture(scope="module")
def yp(shared_fin):
    rec = shared_fin.instantiate("young_professional")
    out = shared_fin.solve(rec["id"])
    assert independent_check(out["plan"], out["result"]) == []
    return out["plan"], out["result"]


def _codes(errs):
    return " | ".join(errs)


def _goal_line(res, gid):
    return next(ln for ln in res["contributions"] if ln["goal_id"] == gid)


def test_checker_flags_cash_overspend(yp):
    plan, res = copy.deepcopy(yp)
    ln = min((ln for ln in res["contributions"] if ln["goal_id"] != "emergency_fund"), key=lambda ln: ln["start_month"])
    ln["monthly_amount_real"] += 1e6
    errs = independent_check(plan, res)
    assert "CASH_NEGATIVE" in _codes(errs)


def test_checker_flags_contribution_after_goal_and_lockin(yp):
    plan, res = copy.deepcopy(yp)
    car = next(g for g in plan["goals"] if g["id"] == "car")
    res["contributions"].append({"goal_id": "car", "asset_class_id": "govt_long", "start_month": car["target_month"],
                                 "end_month": car["target_month"], "monthly_amount_real": 1.0})
    errs = _codes(independent_check(plan, res, check_cash=False))
    assert "CONTRIBUTION_AFTER_GOAL" in errs and "LOCKIN_PAST_GOAL" in errs


def test_checker_flags_ef_gating_and_class_not_allowed(yp):
    plan, res = copy.deepcopy(yp)
    m = Model(plan, res["horizon_months"])
    assert m.tE > 0
    res["contributions"].append({"goal_id": "car", "asset_class_id": "fixed_deposit", "start_month": mstr(m.start, 0),
                                 "end_month": mstr(m.start, 0), "monthly_amount_real": 1.0})
    next(g for g in plan["goals"] if g["id"] == "car")["allowed_asset_class_ids"] = ["short_debt", "equity_index"]
    errs = _codes(independent_check(plan, res, check_cash=False))
    assert "EF_BEFORE_DISCRETIONARY" in errs and "CLASS_NOT_ALLOWED" in errs


def test_checker_flags_risk_cap_in_final_block(yp):
    plan, res = copy.deepcopy(yp)
    car = [ln for ln in res["contributions"] if ln["goal_id"] == "car"]
    last = max(car, key=lambda ln: ln["end_month"])
    last["asset_class_id"] = "equity_index"                  # glide cap is 0-20 % in the last year
    errs = _codes(independent_check(plan, res, check_cash=False))
    assert "RISK_CAP_EXCEEDED" in errs


def test_checker_flags_unbalanced_rebalance_and_holding_partition(yp):
    plan, res = copy.deepcopy(yp)
    res["holdings_assignment"][0]["amount"] += 500.0
    res["rebalances"].append({"month": plan["start_month"], "goal_id": "retirement",
                              "sells": {"fixed_deposit": 1000.0}, "buys": {}})
    errs = _codes(independent_check(plan, res, check_cash=False))
    assert "HOLDING partition" in errs and "REBALANCE_UNBALANCED" in errs


def test_checker_flags_bucket_mismatch(yp):
    plan, res = copy.deepcopy(yp)
    g = next(g for g in res["goals"] if g["goal_id"] == "car")
    g["planned_value_real"] *= 1.05
    assert "BUCKET_MISMATCH car" in _codes(independent_check(plan, res))


def test_checker_flags_global_equity_cap(yp):
    plan, res = copy.deepcopy(yp)
    plan["constraints"]["max_equity_pct"] = 1.0
    if not any(rb for rb in res["rebalances"]) and not any(
            ln["asset_class_id"] == "equity_index" for ln in res["contributions"]):
        pytest.skip("result holds no equity")
    assert "EQUITY_CAP_EXCEEDED" in _codes(independent_check(plan, res))
