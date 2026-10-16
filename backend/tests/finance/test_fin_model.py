"""Model layer (F.4, F.6 model rules; acceptance 1.4)."""

import json

import pytest
from pydantic import ValidationError

from fin_helpers import load_fixture
from superplanner.finance import FinancePlan, FinanceRunRequest, WhatIfChanges
from superplanner.finance.model import Assumptions, Correlation, Goal, IncomeStream


def test_plan_with_only_name_validates_and_lists_may_be_empty():
    p = FinancePlan(name="x")
    assert p.id == "draft" and p.start_month is None
    assert p.incomes == [] and p.goals == [] and p.holdings == [] and p.one_offs == []
    assert len(p.assumptions.asset_classes) == 6


@pytest.mark.parametrize("doc", [
    {"name": "x", "start_month": "2026-13"},
    {"name": "x", "start_month": "26-11"},
    {"name": "x", "start_month": "2026-1"},
    {"name": "x", "horizon_end_month": "2026-00"},
    {"name": ""},
    {"name": "x", "unknown": 1},
    {"name": "x", "profile": {"risk_tolerance": 6}},
    {"name": "x", "profile": {"currency": "inr"}},
    {"name": "x", "profile": {"extra": True}},
    {"name": "x", "incomes": [{"id": "a", "name": "A", "amount": -1}]},
    {"name": "x", "incomes": [{"id": "bad id", "name": "A", "amount": 1}]},
    {"name": "x", "expenses": [{"id": "a", "name": "A", "amount": 1, "frequency": "weekly"}]},
    {"name": "x", "goals": [{"id": "g", "name": "G", "target_amount": 0, "target_month": "2030-01"}]},
    {"name": "x", "goals": [{"id": "g", "name": "G", "target_amount": 1, "target_month": "2030-01",
                             "min_success_probability": 0.3}]},
    {"name": "x", "debts": [{"id": "d", "name": "D", "balance": 1, "interest_rate_pct": 61, "emi": 1}]},
    {"name": "x", "constraints": {"contribution_block_months": 3}},
    {"name": "x", "emergency_fund": {"build_share": 0}},
    {"name": "x", "metadata": {"blob": "x" * (65 * 1024)}},
    {"name": "x", "incomes": [{"id": f"i{i}", "name": "I", "amount": 1} for i in range(21)]},
])
def test_model_rejects_bad_values(doc):
    with pytest.raises(ValidationError):
        FinancePlan.model_validate(doc)


def test_assumption_shape_rules():
    with pytest.raises(ValidationError):
        Assumptions(risky_cap_by_tolerance_pct=[10, 20, 30, 40])
    with pytest.raises(ValidationError):
        Assumptions(risky_cap_by_tolerance_pct=[10, 20, 30, 25, 50])
    with pytest.raises(ValidationError):
        Assumptions(glide_path=[{"min_months_to_goal": 12, "multiplier": 0.5}])
    with pytest.raises(ValidationError):
        Assumptions(glide_path=[{"min_months_to_goal": 0, "multiplier": 0.5},
                                {"min_months_to_goal": 0, "multiplier": 0.2}])
    with pytest.raises(ValidationError):
        Assumptions(asset_classes=[])
    with pytest.raises(ValidationError):
        Correlation(a="x", b="x", rho=0.3)


def test_json_round_trip_unchanged():
    p = load_fixture("typical.finance.json")
    again = FinancePlan.model_validate_json(p.model_dump_json())
    assert again == p
    assert json.loads(again.model_dump_json()) == json.loads(p.model_dump_json())


def test_defaults_of_items():
    i = IncomeStream(id="s", name="S", amount=1)
    assert i.frequency == "monthly" and i.interruptible and i.growth_pct == 0
    g = Goal(id="g", name="G", target_amount=1, target_month="2030-01")
    assert g.priority == "should" and g.enabled and g.allowed_asset_class_ids is None


def test_request_and_whatif_ranges():
    assert FinanceRunRequest().simulation.n_paths == 2000
    with pytest.raises(ValidationError):
        FinanceRunRequest(time_limit_seconds=1)
    with pytest.raises(ValidationError):
        FinanceRunRequest(simulation={"n_paths": 50})
    with pytest.raises(ValidationError):
        WhatIfChanges(income_drop={"start_month": "2027-01", "months": 0, "percent": 10})
    with pytest.raises(ValidationError):
        WhatIfChanges(goal_overrides=[{"goal_id": "g", "risk_tolerance": 6}])
