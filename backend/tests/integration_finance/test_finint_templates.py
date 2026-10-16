"""F4: every template optimized through the API and re-checked by the engine-independent checker
(cash never below the buffer, contributions within surplus + free cash, caps, lock-ins, EF gating,
holdings partition, plan-basis bucket values)."""

from __future__ import annotations

import pytest

from finint_helpers import DISCLAIMER_START, FIN, TEMPLATE_IDS, hard_violations, independent_check

FULL = {"time_limit_seconds": 60, "seed": 3, "simulation": {"n_paths": 1000}, "compute_fixes": True,
        "calibration_rounds": 2}

# non-default parameters inside the documented ranges (F.15)
VARIANTS = [
    ("young_professional", {"take_home": 30000, "essentials": 15000, "discretionary": 5000, "car_in_years": 2}),
    ("young_professional", {"age": 38, "retirement_age": 45, "car_price": 2000000, "car_in_years": 15}),
    ("family", {"home_in_years": 1, "education_in_years": 12, "take_home": 400000}),
    ("near_retirement", {"age": 60, "retirement_age": 62, "wedding_in_years": 1}),
]


def _check_record(rec: dict) -> None:
    res, plan = rec["result"], rec["plan"]
    assert res["feasibility"] in ("feasible", "infeasible"), res["feasibility"]
    if res["feasibility"] == "feasible":
        assert hard_violations(res) == [], hard_violations(res)
        errs = independent_check(plan, res)
    else:
        assert res["diagnostics"]["cash_deficit_real"] > 1.0
        errs = independent_check(plan, res, check_cash=False)
    assert errs == [], "\n".join(errs)
    T = res["horizon_months"]
    for key, arr in res["series"].items():
        if key == "corpus_by_class":
            assert all(len(v) == T for v in arr.values())
        else:
            assert len(arr) == T, key
    for key, arr in res["cashflow"].items():
        assert len(arr) == T, key
    assert res["disclaimer"].startswith(DISCLAIMER_START)
    assert res["engine_version"] and res["disclaimer_version"] == "fin-disclaimer-1"


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_template_defaults_optimize_feasible_and_pass_independent_check(shared_fin, tid):
    rec = shared_fin.instantiate(tid, name=f"int {tid}")
    out = shared_fin.solve(rec["id"], FULL)
    assert out["kind"] == "baseline"
    res = out["result"]
    # F.15: at defaults every template runs feasible
    assert res["feasibility"] == "feasible", [v["code"] for v in res["violations"]]
    _check_record(out)
    # summary counters agree with the goal list
    s = res["summary"]
    statuses = [g["status"] for g in res["goals"]]
    assert s["goals_total"] == len(res["goals"]) == len([g for g in out["plan"]["goals"] if g["enabled"]])
    assert (s["goals_on_track"], s["goals_at_risk"], s["goals_off_track"]) == (
        statuses.count("on_track"), statuses.count("at_risk"), statuses.count("off_track"))
    # the stored plan snapshot equals the document the template produced
    assert out["plan"]["goals"] == rec["plan"]["goals"]


@pytest.mark.parametrize("tid,params", VARIANTS, ids=[f"{t}-{i}" for i, (t, _) in enumerate(VARIANTS)])
def test_template_variants_pass_independent_check(shared_fin, tid, params):
    rec = shared_fin.instantiate(tid, **params)
    out = shared_fin.solve(rec["id"], {**FULL, "compute_fixes": False})
    _check_record(out)


def test_goal_status_rule_matches_f14(shared_fin):
    """on_track iff shortfall_fraction <= 0.001 and probability >= min; at_risk / off_track per F.14."""
    for tid in ("young_professional", "family", "near_retirement"):
        rec = shared_fin.instantiate(tid)
        res = shared_fin.solve(rec["id"], {**FULL, "compute_fixes": False})["result"]
        for g in res["goals"]:
            p, mn, sf = g["success_probability"], g["min_success_probability"], g["shortfall_fraction"]
            if sf <= 0.001 and p >= mn:
                want = "on_track"
            elif p >= mn - 0.20 or sf <= 0.10:
                want = "at_risk"
            else:
                want = "off_track"
            assert g["status"] == want, (tid, g["goal_id"], p, mn, sf, g["status"])
            assert abs(g["shortfall_fraction"] - g["shortfall_real"] / g["target_real"]) < 1e-6


def test_runs_list_and_results_endpoint_consistent(shared_fin):
    rec = shared_fin.instantiate("young_professional")
    out = shared_fin.solve(rec["id"], {**FULL, "compute_fixes": False})
    r = shared_fin.c.get(f"{FIN}/plans/{rec['id']}/results?kind=baseline")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == [out["id"]]
    runs = shared_fin.c.get(f"{FIN}/plans/{rec['id']}/runs").json()["items"]
    assert runs[0]["result_id"] == out["id"] and runs[0]["feasibility"] == out["result"]["feasibility"]


@pytest.mark.parametrize("years", [3, 9])
def test_family_template_short_education_horizon_is_runnable(shared_fin, years):
    """`education_in_years` is documented as 3..20 (F.15) and the example card lets the user change it, but the
    template earmarks the 10-year locked `h_ppf` holding to education, so any value below 10 yields a plan that
    fails preflight with EARMARK_LOCKED_PAST_GOAL before the user edited anything."""
    rec = shared_fin.instantiate("family", education_in_years=years)
    v = shared_fin.c.post(f"{FIN}/plans/{rec['id']}/validate").json()
    assert v["ok"] is True, [(i["code"], i["message"]) for i in v["issues"] if i["severity"] == "error"]
