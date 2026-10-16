"""Shared builders for the finance engine tests (F1) and the compliance denylist (FINANCE.md 21, [R25]).

The denylist is reused by the API and e2e compliance tests (F2/F4)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from superplanner.finance import (FinancePlan, FinanceResult, FinanceRunRequest, run_plan, validate_result)
from superplanner.finance.model import (ContributionLine, FinanceResult as _FR, GoalResult, HoldingAssignment,
                                        Rebalance, ResultSummary)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
START = "2026-11"

# Named indices, AMCs, banks, insurers, issuers, scheme names and tickers that must never appear in
# engine-authored text (defaults, templates, message catalog). Generic category words are allowed.
DENYLIST = [
    "Nifty", "Sensex", "S&P", "Dow Jones", "Nasdaq", "FTSE", "MSCI", "Russell 2000", "BSE", "NSE",
    "SBI", "HDFC", "ICICI", "Axis Bank", "Kotak", "LIC", "Bajaj", "Tata", "Reliance", "Aditya Birla", "Mirae",
    "Nippon", "UTI", "Franklin", "DSP", "Motilal", "Parag Parikh", "Quant Mutual", "Zerodha", "Groww", "Paytm",
    "Vanguard", "BlackRock", "iShares", "Fidelity", "Schwab", "State Street", "SPDR", "Invesco", "PIMCO",
    "SPY", "QQQ", "VOO", "VTI", "IVV", "GLD", "GOLDBEES", "NIFTYBEES", "BHARATBOND", "Bharat Bond",
    "PPF", "EPF", "NPS", "ELSS", "Sukanya", "ULIP",
]
ALLOWLIST = ["PPF-like"]


def denylist_hits(text: str, allow: list[str] | None = None) -> list[str]:
    for a in (ALLOWLIST if allow is None else allow):
        text = text.replace(a, "")
    hits = []
    for word in DENYLIST:
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE):
            hits.append(word)
    return hits


def zero_classes(**overrides: Any) -> list[dict]:
    """Deterministic classes at inflation 0: real return = nominal, no volatility."""
    base = [
        dict(id="cash", name="Cash", category="cash", expected_return_pct=0.0, volatility_pct=0.0),
        dict(id="safe", name="Safe debt", category="debt", expected_return_pct=0.0, volatility_pct=0.0,
             liquidity_days=2),
        dict(id="eq", name="Equity", category="equity", expected_return_pct=0.0, volatility_pct=0.0),
        dict(id="lock", name="Locked savings", category="debt", expected_return_pct=0.0, volatility_pct=0.0,
             lock_in_months=24),
    ]
    for c in base:
        c.update(overrides.get(c["id"], {}))
    return base


def zero_assumptions(classes: list[dict] | None = None) -> dict:
    return dict(inflation_pct=0.0, inflation_volatility_pct=0.0, cash_class_id="cash",
                asset_classes=classes or zero_classes(), correlations=[])


def plan(**kw: Any) -> FinancePlan:
    doc: dict[str, Any] = {"name": "test plan", "start_month": START}
    doc.update(kw)
    return FinancePlan.model_validate(doc)


def zplan(**kw: Any) -> FinancePlan:
    """Plan with zero inflation and zero-return, zero-vol classes; EF off unless given."""
    doc: dict[str, Any] = {"assumptions": zero_assumptions(), "emergency_fund": {"months_of_essentials": 0,
                                                                              "asset_class_id": "safe"}}
    doc.update(kw)
    return plan(**doc)


def income(id: str = "salary", amount: float = 2000.0, **kw: Any) -> dict:
    return dict(id=id, name=kw.pop("name", "Salary"), amount=amount, **kw)


def expense(id: str = "living", amount: float = 1000.0, **kw: Any) -> dict:
    return dict(id=id, name=kw.pop("name", "Living"), amount=amount, **kw)


def goal(id: str = "g1", target: float = 12000.0, month: str = "2027-11", **kw: Any) -> dict:
    return dict(id=id, name=kw.pop("name", id.upper()), target_amount=target, target_month=month, **kw)


def quick_request(**kw: Any) -> FinanceRunRequest:
    doc: dict[str, Any] = {"simulation": {"n_paths": 200}, "calibration_rounds": 0, "compute_fixes": False}
    doc.update(kw)
    return FinanceRunRequest.model_validate(doc)


def run(p: FinancePlan, **kw: Any) -> FinanceResult:
    return run_plan(p, quick_request(**kw))


def hard(p: FinancePlan, r: FinanceResult) -> list:
    return [v for v in validate_result(p, r) if v.severity == "hard"]


def assert_clean(p: FinancePlan, r: FinanceResult) -> None:
    """Independent check (acceptance 1.8): no hard violation regardless of `result.violations`."""
    h = hard(p, r)
    assert not h, [(v.code, v.message, v.months, v.amount) for v in h]


def hand_result(p: FinancePlan, *, lines: list[tuple] = (), rows: list[tuple] = (), rebalances: list[tuple] = (),
                goals: dict[str, dict] | None = None, liquidity: float = 0.0) -> FinanceResult:
    """Minimal hand-made result. lines: (goal, class, start, end, amount); rows: (holding, goal, amount, source);
    rebalances: (month, goal, sells, buys); goals: goal_id -> GoalResult overrides."""
    goals = goals or {}
    grs = []
    for g in p.goals:
        if not g.enabled:
            continue
        d = dict(goal_id=g.id, name=g.name, target_month=g.target_month, months_to_goal=1,
                 target_amount=g.target_amount, target_real=g.target_amount, planned_value_real=g.target_amount,
                 success_probability=0.99, planning_z=0.0)
        d.update(goals.get(g.id, {}))
        grs.append(GoalResult(**d))
    return _FR(start_month=p.start_month, horizon_months=12, end_month=p.start_month,
               goals=grs,
               contributions=[ContributionLine(goal_id=g, asset_class_id=a, start_month=s, end_month=e,
                                               monthly_amount_real=v) for (g, a, s, e, v) in lines],
               holdings_assignment=[HoldingAssignment(holding_id=h, goal_id=g, amount=v, source=src)
                                    for (h, g, v, src) in rows],
               rebalances=[Rebalance(month=m, goal_id=g, sells=s, buys=b) for (m, g, s, b) in rebalances],
               summary=ResultSummary(liquidity_risk_probability=liquidity))


def load_fixture(name: str) -> FinancePlan:
    return FinancePlan.model_validate(json.loads((FIXTURES / name).read_text()))


def size_cap_plan(block: int = 12, spread: bool = True) -> FinancePlan:
    """12 goals, 10 classes, ~600 months (the limits of 8.7)."""
    classes = []
    cats = ["cash", "debt", "debt", "debt", "equity", "equity", "gold", "other", "debt", "equity"]
    for j, c in enumerate(cats):
        classes.append(dict(id=f"c{j}", name=f"Class {j}", category=c, expected_return_pct=3.0 + j,
                            volatility_pct=0.5 + 2 * j, expense_ratio_pct=0.1, liquidity_days=0 if j == 0 else 2,
                            lock_in_months=120 if j == 8 else 0))
    goals_ = []
    prios = ["must", "should", "nice"]
    for i in range(12):
        months = 599 - 40 * i if spread else 599
        y, m = divmod(2026 * 12 + 10 + months, 12)
        goals_.append(goal(f"goal{i}", target=2_000_000 + 250_000 * i, month=f"{y:04d}-{m + 1:02d}",
                           priority=prios[i % 3], name=f"Goal {i}"))
    return plan(assumptions=dict(asset_classes=classes, cash_class_id="c0", correlations=[]),
                emergency_fund=dict(asset_class_id="c1"),
                incomes=[income(amount=250000, growth_pct=5)], expenses=[expense(amount=90000)],
                holdings=[dict(id="h1", name="Savings", asset_class_id="c0", amount=300000),
                          dict(id="h2", name="Shares", asset_class_id="c4", amount=800000)],
                goals=goals_, constraints=dict(contribution_block_months=block))
