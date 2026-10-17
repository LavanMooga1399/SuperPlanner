"""PHASE2 1.10 / 1.14 / P1-3, P1-5, P1-8: distant goals hold growth assets; every goal explains its mix."""

from __future__ import annotations

import pytest

from fin_helpers import denylist_hits, expense, goal, income, plan, run
from superplanner.finance import FinanceRunRequest, get_template, run_plan
from superplanner.finance.advisor.messages import MESSAGES, contains_forbidden, duration_text, matching_codes
from superplanner.finance.returns import tolerance_of

TEMPLATE_IDS = ("young_professional", "family", "near_retirement")
_CACHE: dict = {}


def result(tid: str, **req):
    key = (tid, tuple(sorted(req.items())))
    if key not in _CACHE:
        p = get_template(tid).build(name=tid, start_month="2026-11")
        _CACHE[key] = (p, run_plan(p, FinanceRunRequest(seed=1, simulation={"n_paths": 1000}, **req)))
    return _CACHE[key]


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_distant_goals_use_growth_up_to_the_cap(tid):
    p, r = result(tid)
    goals = {g.id: g for g in p.goals}
    checked = 0
    for gr in r.goals:
        tol = tolerance_of(p, goals[gr.goal_id])
        if gr.months_to_goal >= 120 and tol >= 3:
            checked += 1
            assert gr.growth_cap_now_pct > 0
            assert gr.growth_share_now_pct >= 0.8 * gr.growth_cap_now_pct, gr
            far = [pt for pt in r.glide_paths[gr.goal_id] if pt.months_to_goal >= 120]
            assert max(pt.risky_share_pct for pt in far) >= 0.8 * max(pt.risky_cap_pct for pt in far)
        if gr.months_to_goal < 36:
            for pt in r.glide_paths[gr.goal_id]:
                assert pt.risky_share_pct <= pt.risky_cap_pct + 0.01
    assert checked or tid == "near_retirement"


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_first_reason_is_the_growth_decision(tid):
    p, r = result(tid)
    goals = {g.id: g for g in p.goals}
    for gr in r.goals:
        first = r.explanation.goals[gr.goal_id].reasons[0]
        assert first.code.startswith("GROWTH_"), first
        assert gr.name in first.message
        assert f"risk level {tolerance_of(p, goals[gr.goal_id])} of 5" in first.message
        assert first.code in matching_codes(first.message)


def test_family_retirement_reads_like_the_design_example():
    _, r = result("family")
    msg = r.explanation.goals["retirement"].reasons[0]
    assert msg.code == "GROWTH_HIGH"
    assert msg.message == ("Retirement: about 60% in growth assets (Diversified equity index fund) for now, because "
                           "the goal is 25 years away and your risk level 3 of 5 allows up to 60%. The share steps "
                           "down from 2042-11 as the goal gets closer.")


def test_short_goals_are_explained_as_short():
    _, r = result("young_professional")
    car = r.explanation.goals["car"].reasons[0]
    assert car.code == "GROWTH_NONE_SHORT" and "3 years away" in car.message
    _, r2 = result("near_retirement")
    assert r2.explanation.goals["wedding"].reasons[0].code == "GROWTH_LIMITED_TIME"


def test_calibration_keeps_growth_for_family_retirement():
    _, r = result("family", calibration_rounds=4)
    g = next(x for x in r.goals if x.goal_id == "retirement")
    assert g.growth_share_now_pct >= 0.8 * g.growth_cap_now_pct


def test_calibration_keeps_growth_when_many_steps_are_taken():
    """A strict minimum makes calibration take all four steps; the long goal keeps its growth share."""
    p = get_template("family").build(name="f", start_month="2026-11")
    doc = p.model_dump()
    for gd in doc["goals"]:
        if gd["id"] == "retirement":
            gd["min_success_probability"] = 0.99
    from superplanner.finance import FinancePlan
    p = FinancePlan.model_validate(doc)
    r = run_plan(p, FinanceRunRequest(seed=1, simulation={"n_paths": 500}, calibration_rounds=4))
    g = next(x for x in r.goals if x.goal_id == "retirement")
    assert g.planning_z > 2.326 + 0.4          # at least two steps above z0 = Phi^-1(0.99)
    assert g.growth_share_now_pct >= 0.8 * g.growth_cap_now_pct


def test_restricted_goal_and_returns_rule():
    p = plan(incomes=[income(amount=80000, inflation_linked=True)], expenses=[expense(amount=30000)],
             goals=[goal("safe_only", 600000, "2031-11", priority="must", name="Safe goal",
                         allowed_asset_class_ids=["fixed_deposit", "govt_long"]),
                    goal("long", 2000000, "2041-11", priority="should", name="Long goal", risk_tolerance=1)])
    r = run(p)
    first = {g: e.reasons[0] for g, e in r.explanation.goals.items()}
    assert first["safe_only"].code == "GROWTH_NONE_RESTRICTED"
    assert "Fixed deposit" in first["safe_only"].message
    assert first["long"].code.startswith("GROWTH_")


def test_global_equity_cap_reason():
    p = plan(incomes=[income(amount=80000, inflation_linked=True)], expenses=[expense(amount=30000)],
             goals=[goal("long", 3000000, "2046-11", priority="must", name="Long goal")],
             constraints={"max_equity_pct": 20})
    r = run(p)
    first = r.explanation.goals["long"].reasons[0]
    assert first.code == "GROWTH_LIMITED_GLOBAL", first
    assert "overall equity limit of 20%" in first.message


def test_shared_shortfall_binding():
    p = get_template("family").build(name="f", start_month="2026-11", params={"take_home": 120000})
    r = run(p)
    b = [x for x in r.explanation.binding_constraints if x.code == "SHARED_SHORTFALL"]
    assert b and set(b[0].goal_ids) == {"home", "education", "retirement"}
    assert b[0].message.startswith("3 must-have goals are each short by about 33%")


def test_no_shared_shortfall_when_funded():
    _, r = result("family")
    assert not [x for x in r.explanation.binding_constraints if x.code == "SHARED_SHORTFALL"]


def test_new_messages_are_compliant():
    new = [c for c in MESSAGES if c.startswith(("GROWTH_", "SUMMARY_SURPLUS", "SUMMARY_FUNDING"))]
    new += ["SHARED_SHORTFALL", "ASSUMPTION_RANGE", "SAFE_RETURN"]
    assert len(new) == 15
    for c in new:
        assert not contains_forbidden(MESSAGES[c]), c
        assert not denylist_hits(MESSAGES[c]), c


def test_duration_text():
    assert [duration_text(m) for m in (300, 42, 8, 12, 13, 0)] == [
        "25 years", "3 years 6 months", "8 months", "1 year", "1 year 1 month", "0 months"]
