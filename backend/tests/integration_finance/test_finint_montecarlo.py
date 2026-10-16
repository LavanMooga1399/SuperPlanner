"""F4: Monte Carlo reproducibility with a seed, and sanity of probabilities against the deterministic
low / central / high scenarios (F.9)."""

from __future__ import annotations

import copy
import math

import pytest

from finint_helpers import FIN, START

RUN = {"time_limit_seconds": 30, "seed": 11, "simulation": {"n_paths": 1000}, "compute_fixes": False,
       "calibration_rounds": 1}
WALL_CLOCK = ("simulation_seconds", "seconds_total")


def _strip_timing(res: dict) -> dict:
    res = copy.deepcopy(res)
    for k in WALL_CLOCK:
        res["diagnostics"].pop(k, None)
    for t in res["diagnostics"]["tiers"]:
        t.pop("seconds", None)
    return res


@pytest.fixture(scope="module")
def yp_plan(shared_fin):
    return shared_fin.instantiate("young_professional")["id"]


def test_same_seed_gives_identical_result(shared_fin, yp_plan):
    a = shared_fin.solve(yp_plan, RUN)["result"]
    b = shared_fin.solve(yp_plan, RUN)["result"]
    assert _strip_timing(a) == _strip_timing(b)


def test_different_seed_agrees_within_monte_carlo_noise(shared_fin, yp_plan):
    a = shared_fin.solve(yp_plan, {**RUN, "calibration_rounds": 0})["result"]
    b = shared_fin.solve(yp_plan, {**RUN, "calibration_rounds": 0, "seed": 12345})["result"]
    assert [g["planning_z"] for g in a["goals"]] == [g["planning_z"] for g in b["goals"]]
    for ga, gb in zip(a["goals"], b["goals"]):
        p = (ga["success_probability"] + gb["success_probability"]) / 2
        sd = math.sqrt(max(p * (1 - p), 0.01) / 1000) * math.sqrt(2)
        assert abs(ga["success_probability"] - gb["success_probability"]) <= 4 * sd + 1e-9, (ga["goal_id"], p)
        # the deterministic plan does not depend on the seed
        assert ga["planned_value_real"] == gb["planned_value_real"]
        assert ga["projected_central_real"] == gb["projected_central_real"]
    assert a["contributions"] == b["contributions"]


@pytest.mark.parametrize("tid", ["young_professional", "family", "near_retirement"])
def test_probabilities_and_quantiles_are_consistent_with_scenarios(shared_fin, tid):
    pid = shared_fin.instantiate(tid)["id"]
    res = shared_fin.solve(pid, RUN)["result"]
    for g in res["goals"]:
        gid = g["goal_id"]
        assert 0.0 <= g["success_probability"] <= 1.0
        assert g["p10_real"] <= g["p50_real"] <= g["p90_real"], gid
        assert g["scenario_low_real"] <= g["projected_central_real"] <= g["scenario_high_real"], gid
        assert res["scenarios"]["goals"][gid] == {"low": g["scenario_low_real"], "central": g["projected_central_real"],
                                                  "high": g["scenario_high_real"]}
        assert g["expected_shortfall_real"] >= 0
        TR = g["target_real"]
        # the stochastic range brackets the weak/strong deterministic markets loosely
        assert g["p10_real"] <= g["scenario_high_real"] + 1 and g["p90_real"] >= g["scenario_low_real"] - 1, gid
        # a plan that reaches only half the target in the cautious plan almost never succeeds; and a goal planned
        # to its target with cautious (z >= 0) returns succeeds at least about half the time
        if g["shortfall_fraction"] >= 0.5:
            assert g["success_probability"] < 0.5, gid
        if g["shortfall_fraction"] <= 0.001 and g["planning_z"] >= 0:
            assert g["success_probability"] >= 0.45, (gid, g["success_probability"])
            assert g["p50_real"] >= TR * 0.97, gid
        # expected shortfall agrees with the probability: zero only if nearly every path succeeds
        if g["success_probability"] < 0.9:
            assert g["expected_shortfall_real"] > 0, gid
    s = res["series"]
    assert all(lo <= mid + 1e-6 <= hi + 2e-6 for lo, mid, hi in zip(s["total_p10"], s["total_p50"], s["total_p90"]))
    assert 0.0 <= res["summary"]["liquidity_risk_probability"] <= 1.0


def _zero_vol_doc(target: float) -> dict:
    classes = [
        {"id": "cash", "name": "Cash", "category": "cash", "expected_return_pct": 0.0, "volatility_pct": 0.0},
        {"id": "safe", "name": "Safe debt", "category": "debt", "expected_return_pct": 4.0, "volatility_pct": 0.0,
         "liquidity_days": 2},
    ]
    return {"name": "zero vol", "start_month": START,
            "incomes": [{"id": "salary", "name": "Salary", "amount": 50000}],
            "expenses": [{"id": "living", "name": "Living", "amount": 40000}],
            "emergency_fund": {"months_of_essentials": 0, "asset_class_id": "safe"},
            "goals": [{"id": "trip", "name": "Trip", "target_amount": target, "target_month": "2029-11",
                       "priority": "must"}],
            "assumptions": {"inflation_pct": 0.0, "inflation_volatility_pct": 0.0, "cash_class_id": "cash",
                            "asset_classes": classes, "correlations": []}}


@pytest.mark.parametrize("target,reachable", [(200000, True), (900000, False)])
def test_zero_volatility_monte_carlo_equals_deterministic_scenarios(fin, target, reachable):
    """No volatility, no inflation shocks: every path is the central scenario, so p10 = p50 = p90 = central and the
    probability is exactly 0 or 1. The low / high scenarios still move inflation by +-1pp (F.9.4), so they bracket
    the central value."""
    r = fin.create(_zero_vol_doc(target))
    assert r.status_code == 201, r.text
    res = fin.solve(r.json()["id"], {**RUN, "calibration_rounds": 0})["result"]
    assert res["feasibility"] == "feasible"
    g = res["goals"][0]
    vals = [g["p10_real"], g["p50_real"], g["p90_real"], g["projected_central_real"]]
    assert max(vals) - min(vals) <= 1.0, vals
    assert g["scenario_low_real"] < g["projected_central_real"] < g["scenario_high_real"]
    if reachable:
        assert g["shortfall_real"] == 0 and g["success_probability"] == 1.0
        assert g["projected_central_real"] >= g["target_real"] - 1.0
    else:
        assert g["shortfall_real"] > 0 and g["success_probability"] == 0.0
        # all 36 months of surplus (10,000 each, real 4 % growth) go to the goal
        assert abs(g["planned_value_real"] - g["projected_central_real"]) <= 1.0
        assert 360000 < g["planned_value_real"] < 420000


def test_income_interruption_does_not_raise_probability(shared_fin, yp_plan):
    base = shared_fin.solve(yp_plan, {**RUN, "calibration_rounds": 0})["result"]
    shock = shared_fin.solve(yp_plan, {**RUN, "calibration_rounds": 0, "simulation": {
        "n_paths": 1000, "income_interruption": {"enabled": True, "annual_probability": 0.3, "duration_months": 6}}})["result"]
    for ga, gb in zip(base["goals"], shock["goals"]):
        assert gb["success_probability"] <= ga["success_probability"] + 0.03, ga["goal_id"]
    assert shock["summary"]["liquidity_risk_probability"] >= base["summary"]["liquidity_risk_probability"]
    assert shock["simulation_settings"]["income_interruption"]["enabled"] is True


def test_more_paths_converges(shared_fin, yp_plan):
    small = shared_fin.solve(yp_plan, {**RUN, "calibration_rounds": 0, "simulation": {"n_paths": 500}})["result"]
    big = shared_fin.solve(yp_plan, {**RUN, "calibration_rounds": 0, "simulation": {"n_paths": 5000}})["result"]
    for ga, gb in zip(small["goals"], big["goals"]):
        assert abs(ga["success_probability"] - gb["success_probability"]) <= 0.08, ga["goal_id"]
    assert big["simulation_settings"]["n_paths"] == 5000
    r = shared_fin.c.get(f"{FIN}/plans/{yp_plan}/runs").json()["items"]
    assert all(x["status"] == "completed" for x in r)
