"""F4: infeasible inputs are explained (preflight errors with item names, cash-infeasible plans with the deficit
and binding constraint), and inputs that are merely tight are not reported as infeasible."""

from __future__ import annotations

import copy

import pytest

from finint_helpers import (DEFAULT_CLASSES, FIN, START, Model, assert_error, expand_lines, hard_violations,
                            independent_check)


def _doc(**kw):
    d = {"name": "infeasible test", "start_month": START,
         "incomes": [{"id": "salary", "name": "Salary", "amount": 30000}],
         "expenses": [{"id": "living", "name": "Living", "amount": 40000}],
         "emergency_fund": {"months_of_essentials": 0},
         "goals": [{"id": "car", "name": "Car", "target_amount": 300000, "target_month": "2029-11", "priority": "must"}]}
    d.update(kw)
    return d


def test_cash_infeasible_plan_is_reported_with_deficit_and_explanation(fin):
    pid = fin.create(_doc()).json()["id"]
    rec = fin.solve(pid)
    res, plan = rec["result"], rec["plan"]
    assert res["feasibility"] == "infeasible"
    m = Model(plan, res["horizon_months"])
    mine = m.zero_contribution_deficit()
    assert mine > 1000
    assert abs(res["diagnostics"]["cash_deficit_real"] - mine) <= max(1.0, 0.002 * mine)
    neg = [v for v in hard_violations(res) if v["code"] == "CASH_NEGATIVE"]
    assert neg and neg[0]["months"][0] == START and neg[0]["message"]
    assert [v["code"] for v in hard_violations(res)] == ["CASH_NEGATIVE"] * len(hard_violations(res))
    binding = {b["code"]: b for b in res["explanation"]["binding_constraints"]}
    assert "CASH_DEFICIT" in binding and binding["CASH_DEFICIT"]["message"]
    assert res["explanation"]["summary"], "summary lines missing"
    # no money goes to goals while cash is short (a few cents of flooring headroom are tolerated)
    lines = expand_lines(m, res)
    assert sum(sum(v.values()) for k, v in lines.items() if k[0] != "emergency_fund") < 1.0 * res["horizon_months"]
    assert independent_check(plan, res, check_cash=False) == []
    # an infeasible result is refused by send-to-planner
    r = fin.c.post(f"{FIN}/results/{rec['id']}/send-to-planner", json={})
    assert_error(r, 422, "NOT_FEASIBLE")


def test_negative_surplus_month_covered_by_selling_investments_is_feasible(fin):
    doc = _doc(expenses=[{"id": "living", "name": "Living", "amount": 20000}],
               holdings=[{"id": "h_eq", "name": "Shares", "asset_class_id": "equity_index", "amount": 500000}],
               one_offs=[{"id": "repair", "name": "House repair", "month": "2027-02", "amount": 300000}])
    pid = fin.create(doc).json()["id"]
    rec = fin.solve(pid)
    res = rec["result"]
    assert res["feasibility"] == "feasible", [v["code"] for v in res["violations"]]
    assert any(r["source"] == "sold_to_cash" and r["amount"] > 100000 for r in res["holdings_assignment"])
    assert independent_check(rec["plan"], res) == []


PREFLIGHT_CASES = [
    ("goal_in_past", {"goals": [{"id": "car", "name": "Car", "target_amount": 1000, "target_month": "2025-01"}]},
     "GOAL_TOO_SOON", "Car"),
    ("earmark_exceeds", {"holdings": [{"id": "h1", "name": "Savings", "asset_class_id": "cash", "amount": 100}],
                         "goals": [{"id": "car", "name": "Car", "target_amount": 1000, "target_month": "2029-11",
                                    "earmarked": [{"holding_id": "h1", "amount": 5000}]}]},
     "EARMARK_EXCEEDS_HOLDING", None),
    ("debt_never_repaid", {"debts": [{"id": "cc", "name": "Credit card", "balance": 100000, "interest_rate_pct": 36,
                                      "emi": 1000}]}, "DEBT_NEVER_REPAID", "Credit card"),
    ("unknown_class", {"holdings": [{"id": "h1", "name": "Crypto", "asset_class_id": "crypto", "amount": 100}]},
     "UNKNOWN_ASSET_CLASS", None),
    ("one_off_past", {"one_offs": [{"id": "o1", "name": "Trip", "month": "2026-01", "amount": 100}]},
     "ONE_OFF_IN_PAST", None),
    ("reserved_id", {"goals": [{"id": "emergency_fund", "name": "EF", "target_amount": 1000,
                                "target_month": "2029-11"}]}, "RESERVED_ID", None),
]


@pytest.mark.parametrize("name,patch,code,mention", PREFLIGHT_CASES, ids=[c[0] for c in PREFLIGHT_CASES])
def test_preflight_errors_block_runs_and_are_explained(fin, name, patch, code, mention):
    doc = _doc(expenses=[{"id": "living", "name": "Living", "amount": 10000}], **patch)
    r = fin.create(doc)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    v = fin.c.post(f"{FIN}/plans/{pid}/validate")
    assert v.status_code == 200
    body = v.json()
    assert body["ok"] is False and body["cashflow"] is None
    issue = next((i for i in body["issues"] if i["code"] == code), None)
    assert issue is not None, [i["code"] for i in body["issues"]]
    assert issue["severity"] == "error" and issue["message"]
    if mention:
        assert mention in issue["message"], issue["message"]
    err = assert_error(fin.post_run(pid), 422, "PREFLIGHT_FAILED")
    assert code in [i["code"] for i in err["details"]["issues"]]
    # the plan has no run and no result afterwards
    assert fin.c.get(f"{FIN}/plans/{pid}/runs").json()["items"] == []


def test_preview_explains_negative_surplus_as_warning(fin):
    r = fin.c.post(f"{FIN}/preview", json=_doc())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    warn = [i for i in body["issues"] if i["code"] == "NEGATIVE_SURPLUS"]
    assert warn and warn[0]["severity"] == "warning"
    # nominal income without growth loses real value, so the worst month is at least the first month's -10,000
    assert body["cashflow"]["min_monthly_surplus"] <= -10000 + 0.01
    assert body["cashflow"]["avg_monthly_surplus_first_year"] < 0


# ------------------------------------------------------------------ defects found by F4 (repro tests)

def test_min_contribution_does_not_turn_a_zero_surplus_plan_infeasible(fin):
    """Zero surplus, no holdings: with zero contributions cash never goes negative, so T0 = 0 and the plan is
    `feasible` (goal short). In MILP mode (a class minimum) the engine forces the minimum into the goal and
    reports a fake deficit."""
    classes = copy.deepcopy(DEFAULT_CLASSES)
    for c in classes:
        if c["id"] == "equity_index":
            c["min_monthly_contribution"] = 2000
    doc = _doc(expenses=[{"id": "living", "name": "Living", "amount": 30000, "inflation_linked": False}],
               goals=[{"id": "car", "name": "Car", "target_amount": 500000, "target_month": "2030-11",
                       "priority": "must", "allowed_asset_class_ids": ["equity_index"]}],
               assumptions={"asset_classes": classes, "correlations": []})
    rec = fin.solve(fin.create(doc).json()["id"])
    res = rec["result"]
    assert Model(rec["plan"], res["horizon_months"]).zero_contribution_deficit() <= 1.0
    assert res["diagnostics"]["cash_deficit_real"] <= 1.0, res["diagnostics"]
    assert res["feasibility"] == "feasible", [v["code"] for v in res["violations"]]


def test_conflicting_caps_do_not_destroy_the_bucket(fin):
    """Goal allowed only fixed_deposit + equity_index, global equity cap 0 % and fixed_deposit cap 40 %: both caps
    cannot hold at once. The plan must still be valid (F.8.4 "always feasible", rule 4 of F.24.3), not a result
    whose rebalances sell the whole bucket and buy nothing (feasibility `unknown`)."""
    doc = _doc(incomes=[{"id": "salary", "name": "Salary", "amount": 100000}],
               goals=[{"id": "car", "name": "Car", "target_amount": 600000, "target_month": "2029-11",
                       "priority": "must", "allowed_asset_class_ids": ["fixed_deposit", "equity_index"]}],
               constraints={"max_equity_pct": 0, "max_class_pct": {"fixed_deposit": 40}})
    rec = fin.solve(fin.create(doc).json()["id"])
    res = rec["result"]
    assert [v["code"] for v in hard_violations(res)] == []
    assert res["feasibility"] == "feasible"
    assert independent_check(rec["plan"], res) == []


def test_unfunded_lower_priority_goal_gets_no_forced_micro_contributions(fin):
    """near_retirement: the must goal (retirement) is ~57 % short, so by the lexicographic order (F.8.5) every
    rupee goes to it and the nice goal (wedding) gets nothing. The flooring headroom forces a few rupees into
    the wedding anyway, which surface as planner tasks like 'Start ₹0/month into ... for "Wedding"'."""
    # PHASE2 1.8 made the template affordable; a lower take-home pay keeps retirement short (9.P1)
    rec = fin.instantiate("near_retirement", wedding_in_years=1, take_home=120000)
    out = fin.solve(rec["id"])
    res = out["result"]
    goals = {g["goal_id"]: g for g in res["goals"]}
    assert goals["retirement"]["shortfall_fraction"] > 0.1
    wedding_total = sum(ln["monthly_amount_real"] * 1 for ln in res["contributions"] if ln["goal_id"] == "wedding")
    assert wedding_total < 0.01, [ln for ln in res["contributions"] if ln["goal_id"] == "wedding"]
    s = fin.c.post(f"{FIN}/results/{out['id']}/send-to-planner", json={})
    assert s.status_code == 201, s.text
    names = [t["name"] for t in fin.c.get(f"/api/v1/problems/{s.json()['problem_id']}").json()["problem"]["tasks"]]
    assert not [n for n in names if "₹0/month" in n or "₹1/month" in n or "₹2/month" in n], names
