"""PHASE2 1.6 (calibration aims at minimum + 1 pp), 1.13 (engine version, compatibility) and P1-7."""

from __future__ import annotations

import json

from fin_helpers import FIXTURES, assert_clean, load_fixture, run
from superplanner.finance import (FINANCE_ENGINE_VERSION, FinancePlan, compare_results, get_template)
from superplanner.finance.defaults import CALIBRATION_AIM
from superplanner.finance.pipeline import Z_STEP


def test_aim_constant():
    assert CALIBRATION_AIM == 0.01


def test_goal_just_below_its_minimum_gets_z_raised():
    """Before PHASE2 a goal at min - 0.005 was left alone (trigger min - 0.02) and showed 'at risk'."""
    p = get_template("young_professional").build(name="t", start_month="2026-11")
    r0 = run(p, simulation={"n_paths": 1000}, calibration_rounds=0)
    ret = next(g for g in r0.goals if g.goal_id == "retirement")
    # put the goal's minimum 0.005 above its round-0 probability
    doc = p.model_dump()
    for g in doc["goals"]:
        if g["id"] == "retirement":
            g["min_success_probability"] = round(ret.success_probability + 0.005, 4)
    p2 = FinancePlan.model_validate(doc)
    a = run(p2, simulation={"n_paths": 1000}, calibration_rounds=0)
    b = run(p2, simulation={"n_paths": 1000}, calibration_rounds=1)
    ga = next(g for g in a.goals if g.goal_id == "retirement")
    gb = next(g for g in b.goals if g.goal_id == "retirement")
    assert ga.success_probability < ga.min_success_probability
    assert ga.success_probability >= ga.min_success_probability - 0.02      # the old rule would not calibrate
    assert gb.planning_z == ga.planning_z + Z_STEP
    assert gb.success_probability >= ga.success_probability
    assert_clean(p2, b)


def test_stored_document_without_new_fields_keeps_its_assumptions():
    raw = json.loads((FIXTURES / "typical.finance.json").read_text())
    stored_assumptions = raw.get("assumptions", {})
    assert "caution" not in stored_assumptions
    assert all("inflation_linked" not in i for i in raw["incomes"])
    p = load_fixture("typical.finance.json")
    assert p.incomes[0].inflation_linked is False
    if "inflation_pct" in stored_assumptions:
        assert p.assumptions.inflation_pct == stored_assumptions["inflation_pct"]
    stored = {c["id"]: c["expected_return_pct"] for c in stored_assumptions.get("asset_classes", [])}
    for c in p.assumptions.asset_classes:
        if c.id in stored:
            assert c.expected_return_pct == stored[c.id]
    r = run(p)
    assert r.feasibility == "feasible" and r.engine_version == FINANCE_ENGINE_VERSION == "fin-0.2.0"
    assert_clean(p, r)
    # export / import round-trips the new fields
    again = FinancePlan.model_validate_json(p.model_dump_json())
    assert again == p and again.assumptions.caution.floor_share == 0.5


def test_mixed_engine_versions_are_flagged():
    p = get_template("young_professional").build(name="t", start_month="2026-11")
    r = run(p)
    old = r.model_copy(update={"engine_version": "fin-0.1.0"})
    assert compare_results(old, r).engine_versions_differ is True
    assert compare_results(r, old).engine_versions_differ is True
    assert compare_results(r, r).engine_versions_differ is False
