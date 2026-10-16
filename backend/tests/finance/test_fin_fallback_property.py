"""Regression + property tests for the T4 ABNORMAL / TIER_NUMERIC_FALLBACK defect (review re-check):

* the eta constraint `short_g <= eta (TR_g + head_g)` is homogeneous, so the cash-only goal case solves every tier;
* a TIER_NUMERIC_FALLBACK never publishes a sell-without-buy rebalance (REBALANCE_UNBALANCED);
* seeded sweep over templates x random allowed classes / risk / caps: feasible plans are validator-clean and no
  plan (fallback or not) carries an unbalanced rebalance.
"""

from __future__ import annotations

import random

import pytest
from ortools.linear_solver import pywraplp

from fin_helpers import START, hard, run
from superplanner.finance import FinancePlan, get_template, preflight, validate_result
from superplanner.finance import optimizer as O

CLASSES = ["cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold"]


def _unbalanced(r) -> list:
    return [rb for rb in r.rebalances if sum(rb.buys.values()) <= 1e-6 < sum(rb.sells.values())]


def _cash_only_retirement() -> FinancePlan:
    d = get_template("young_professional").build(name="x", start_month=START, params={}).model_dump(mode="json")
    for g in d["goals"]:
        if g["id"] == "car":
            g["allowed_asset_class_ids"], g["risk_tolerance"] = ["fixed_deposit", "cash", "short_debt"], 1
        if g["id"] == "retirement":
            g["allowed_asset_class_ids"], g["risk_tolerance"] = ["cash"], 5
    d["constraints"]["max_equity_pct"] = 60
    return FinancePlan.model_validate(d)


def test_cash_only_goal_solves_every_tier_without_fallback():
    p = _cash_only_retirement()
    r = run(p, seed=1, simulation={"n_paths": 100})
    assert "TIER_NUMERIC_FALLBACK" not in r.diagnostics.warnings
    assert [t.status for t in r.diagnostics.tiers] == ["OPTIMAL"] * len(r.diagnostics.tiers)
    assert r.feasibility == "feasible", [v.code for v in r.violations]
    assert not [rb for rb in r.rebalances if rb.goal_id == "retirement"]
    assert not hard(p, r)


@pytest.fixture
def fail_tiers(monkeypatch):
    """Make GLOP 'return ABNORMAL' for the chosen tier objectives (simulated numerical failure)."""
    failing: set[str] = set()
    orig_set, orig_solve = O.FinanceLP._set_objective, O.FinanceLP._solve_once

    def set_obj(self, expr):
        self._cur_obj = expr
        return orig_set(self, expr)

    def solve(self, deadline, cancel_event, fresh=0):
        names = {"T4": getattr(self, "obj_T4", None), "T5": getattr(self, "obj_T5", None)}
        if "warm_only" in failing and fresh:
            return orig_solve(self, deadline, cancel_event, fresh)
        if any(names[n] is getattr(self, "_cur_obj", None) for n in failing if n in names):
            return pywraplp.Solver.ABNORMAL
        return orig_solve(self, deadline, cancel_event, fresh)

    monkeypatch.setattr(O.FinanceLP, "_set_objective", set_obj)
    monkeypatch.setattr(O.FinanceLP, "_solve_once", solve)
    return failing


def test_forced_t4_failure_falls_back_to_cleanup_tier_and_publishes_clean_plan(fail_tiers):
    fail_tiers.add("T4")
    p = _cash_only_retirement()
    r = run(p, seed=1, simulation={"n_paths": 100})
    assert "TIER_NUMERIC_FALLBACK" in r.diagnostics.warnings
    tiers = {t.tier: t.status for t in r.diagnostics.tiers}
    assert tiers["T4"] == "ABNORMAL" and tiers["T5"] == "OPTIMAL"
    assert not _unbalanced(r)
    assert "REBALANCE_UNBALANCED" not in {v.code for v in validate_result(p, r)}
    assert r.feasibility == "feasible", [v.code for v in r.violations]
    assert not hard(p, r)


def test_warm_start_failure_is_rescued_by_a_cold_resolve(fail_tiers):
    fail_tiers.update({"T4", "warm_only"})
    p = _cash_only_retirement()
    r = run(p, seed=1, simulation={"n_paths": 100})
    assert "TIER_NUMERIC_FALLBACK" not in r.diagnostics.warnings
    assert {t.tier: t.status for t in r.diagnostics.tiers}["T4"] == "OPTIMAL"
    assert r.feasibility == "feasible" and not hard(p, r)


def test_forced_t4_and_t5_failure_never_publishes_sell_without_buy(fail_tiers):
    fail_tiers.update({"T4", "T5"})
    p = _cash_only_retirement()
    r = run(p, seed=1, simulation={"n_paths": 100})
    assert "TIER_NUMERIC_FALLBACK" in r.diagnostics.warnings
    assert not _unbalanced(r)
    assert "REBALANCE_UNBALANCED" not in {v.code for v in validate_result(p, r)}
    if r.feasibility == "feasible":
        assert not hard(p, r)


def _random_variant(tid: str, seed: int) -> FinancePlan:
    """A random variant that passes preflight (resampled with the same generator until it does)."""
    rnd = random.Random(seed)
    for _ in range(50):
        p = _sample_variant(tid, rnd)
        if preflight(p).ok:
            return p
    raise AssertionError("no preflight-clean variant")


def _sample_variant(tid: str, rnd: random.Random) -> FinancePlan:
    d = get_template(tid).build(name="x", start_month=START, params={}).model_dump(mode="json")
    for g in d["goals"]:
        g["allowed_asset_class_ids"] = rnd.choice([None, rnd.sample(CLASSES, rnd.randint(1, 3)),
                                                   [rnd.choice(CLASSES)]])
        g["risk_tolerance"] = rnd.choice([None, 1, 2, 3, 4, 5])
    c = d["constraints"]
    c["max_equity_pct"] = rnd.choice([None, None, 0, 30, 60, 90])
    if rnd.random() < 0.3:
        c["max_class_pct"] = {rnd.choice(CLASSES): rnd.choice([20, 40, 70])}
    c["rebalance_cost_pct"] = rnd.choice([0.0, 0.1, 1.0])
    return FinancePlan.model_validate(d)


@pytest.mark.parametrize("tid", ["young_professional", "family", "near_retirement"])
@pytest.mark.parametrize("seed", range(16))
def test_template_variants_are_clean_and_never_unbalanced(tid, seed):
    p = _random_variant(tid, 1000 * seed + len(tid))
    r = run(p, seed=seed, simulation={"n_paths": 100})
    codes = {v.code for v in validate_result(p, r)}
    assert "REBALANCE_UNBALANCED" not in codes, (r.diagnostics.warnings, r.diagnostics.tiers)
    assert not _unbalanced(r)
    if r.feasibility == "feasible":
        h = hard(p, r)
        assert not h, [(v.code, v.goal_id, v.message) for v in h]
