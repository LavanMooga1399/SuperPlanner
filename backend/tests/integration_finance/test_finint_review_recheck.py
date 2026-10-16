"""QA re-checks (through the API) of the review defects: template ranges, seed in simulation_settings,
REDUCE_TARGET amount arithmetic. Every returned result is re-checked by the independent checker."""

from __future__ import annotations

import pytest

from finint_helpers import FIN, START, assert_error, hard_violations, independent_check


@pytest.mark.parametrize("tid,params", [("near_retirement", {"age": 60, "retirement_age": 60}),
                                        ("near_retirement", {"age": 62, "retirement_age": 55}),
                                        ("young_professional", {"age": 45, "retirement_age": 45}),
                                        ("family", {"age": 50, "retirement_age": 49})])
def test_instantiate_rejects_retirement_age_not_after_age(fin, tid, params):
    r = fin.c.post(f"{FIN}/templates/{tid}/instantiate", json={"start_month": START, "parameters": params})
    assert_error(r, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("years", [3, 5, 9, 10, 20])
def test_family_every_documented_education_horizon_runs(fin, years):
    rec = fin.instantiate("family", education_in_years=years)
    out = fin.solve(rec["id"], {"seed": 5, "simulation": {"n_paths": 200}})
    res = out["result"]
    assert res["feasibility"] == "feasible", [v["code"] for v in res["violations"]]
    assert hard_violations(res) == []
    assert independent_check(out["plan"], res) == []


def test_simulation_settings_seed_round_trips_through_the_api(fin):
    rec = fin.instantiate("young_professional")
    out = fin.solve(rec["id"], {"seed": 4242, "simulation": {"n_paths": 200}})
    assert out["result"]["simulation_settings"]["seed"] == 4242


def test_reduce_target_amount_plus_new_target_equals_old_target(fin):
    doc = {"name": "rt", "start_month": START,
           "incomes": [{"id": "salary", "name": "Salary", "amount": 60000}],
           "expenses": [{"id": "living", "name": "Living", "amount": 50000}],
           "emergency_fund": {"months_of_essentials": 0},
           "goals": [{"id": "car", "name": "Car", "target_amount": 1500000, "target_month": "2029-11",
                      "priority": "must", "inflation_pct": 11.0}]}
    pid = fin.create(doc).json()["id"]
    out = fin.solve(pid, {"seed": 1, "compute_fixes": True, "simulation": {"n_paths": 200}})
    res = out["result"]
    assert independent_check(out["plan"], res, check_cash=res["feasibility"] == "feasible") == []
    fixes = [f for f in res["explanation"]["goals"]["car"]["fixes"] if f["kind"] == "REDUCE_TARGET"]
    assert fixes, [f["kind"] for f in res["explanation"]["goals"]["car"]["fixes"]]
    f = fixes[0]
    new = f["what_if"]["goal_overrides"][0]["target_amount"]
    assert f["amount"] == pytest.approx(1500000 - new, abs=0.01)


def test_single_class_goal_is_not_emptied_by_rebalances_after_the_review_fixes(fin):
    """Regression of the review fixes: young_professional with retirement allowed only cash and car allowed
    fixed_deposit/cash/short_debt (max_equity_pct 60). At HEAD this solves `feasible`; after the fixes T4 ends
    ABNORMAL (TIER_NUMERIC_FALLBACK) and the published T2b solution sells the whole cash bucket every year and
    buys nothing (REBALANCE_UNBALANCED, feasibility `unknown`)."""
    rec = fin.instantiate("young_professional")
    doc = rec["plan"]
    for g in doc["goals"]:
        if g["id"] == "car":
            g["allowed_asset_class_ids"], g["risk_tolerance"] = ["fixed_deposit", "cash", "short_debt"], 1
        if g["id"] == "retirement":
            g["allowed_asset_class_ids"], g["risk_tolerance"] = ["cash"], 5
    doc["constraints"]["max_equity_pct"] = 60
    r = fin.create(doc)
    assert r.status_code == 201, r.text
    out = fin.solve(r.json()["id"], {"seed": 1, "simulation": {"n_paths": 100}})
    res = out["result"]
    assert "TIER_NUMERIC_FALLBACK" not in res["diagnostics"]["warnings"]
    assert res["feasibility"] == "feasible", [v["code"] for v in res["violations"]]
    assert not [rb for rb in res["rebalances"] if sum(rb["buys"].values()) <= 1e-6 < sum(rb["sells"].values())]
    assert independent_check(out["plan"], res) == []
