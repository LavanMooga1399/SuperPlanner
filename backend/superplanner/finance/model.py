"""Finance documents and results (FINANCE.md sections 4, 6, 7, 10.1, 11-15).

Only field-local rules live here (section 6 model layer); relational and horizon checks are in
`preflight.py`, so incomplete drafts stay saveable.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from . import defaults as D

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,64}$")]
Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Money = Annotated[float, Field(ge=0, le=1e12)]
SignedMoney = Annotated[float, Field(ge=-1e12, le=1e12)]
Frequency = Literal["monthly", "quarterly", "half_yearly", "yearly", "once"]
Priority = Literal["must", "should", "nice"]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Tolerance = Annotated[int, Field(ge=1, le=5)]

MAX_METADATA_BYTES = 64 * 1024


def _metadata_cap(v: dict[str, Any]) -> dict[str, Any]:
    try:
        size = len(json.dumps(v, separators=(",", ":"), default=str).encode())
    except (TypeError, ValueError) as exc:  # pragma: no cover
        raise ValueError("metadata must be JSON-serialisable") from exc
    if size > MAX_METADATA_BYTES:
        raise ValueError(f"metadata is too large ({size} bytes, max {MAX_METADATA_BYTES})")
    return v


Metadata = Annotated[dict[str, Any], AfterValidator(_metadata_cap)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- plan document (section 4)

class Profile(_Strict):
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "INR"
    locale: Annotated[str, StringConstraints(max_length=16)] = "en-IN"
    age: int | None = Field(default=None, ge=16, le=100)
    retirement_age: int = Field(default=60, ge=40, le=80)
    risk_tolerance: Tolerance = 3
    tax_note: Annotated[str, StringConstraints(max_length=1000)] = ""


class IncomeStream(_Strict):
    id: Id
    name: Name
    kind: Literal["salary", "business", "rental", "pension", "interest", "other"] = "salary"
    amount: Money
    frequency: Frequency = "monthly"
    growth_pct: float = Field(default=0.0, ge=-50, le=50)
    start_month: Month | None = None
    end_month: Month | None = None
    interruptible: bool = True


class Expense(_Strict):
    id: Id
    name: Name
    category: Annotated[str, StringConstraints(max_length=64)] = "other"
    amount: Money
    frequency: Frequency = "monthly"
    essential: bool = True
    inflation_linked: bool = True
    inflation_pct: float | None = Field(default=None, ge=-5, le=30)
    start_month: Month | None = None
    end_month: Month | None = None


class Debt(_Strict):
    id: Id
    name: Name
    kind: Literal["home", "vehicle", "education", "personal", "credit_card", "other"] = "other"
    balance: Money
    interest_rate_pct: float = Field(ge=0, le=60)
    emi: Money
    remaining_months: int | None = Field(default=None, ge=1, le=600)


class Holding(_Strict):
    id: Id
    name: Name
    asset_class_id: Id
    amount: Money
    locked_until_month: Month | None = None


class OneOff(_Strict):
    id: Id
    name: Name
    kind: Literal["expense", "inflow"] = "expense"
    month: Month
    amount: Money
    inflation_linked: bool = True


class Earmark(_Strict):
    holding_id: Id
    amount: Money


class Goal(_Strict):
    id: Id
    name: Name
    kind: Literal["retirement", "education", "home", "vehicle", "travel", "wedding", "business", "other"] = "other"
    target_amount: Annotated[float, Field(gt=0, le=1e12)]
    target_month: Month
    priority: Priority = "should"
    flexibility_months: int = Field(default=0, ge=0, le=120)
    min_success_probability: float | None = Field(default=None, ge=0.5, le=0.99)
    inflation_pct: float | None = Field(default=None, ge=-5, le=30)
    risk_tolerance: Tolerance | None = None
    allowed_asset_class_ids: list[Id] | None = Field(default=None, max_length=10)
    earmarked: list[Earmark] = Field(default_factory=list, max_length=20)
    enabled: bool = True


class EmergencyFundSettings(_Strict):
    months_of_essentials: float = Field(default=D.EF_MONTHS, ge=0, le=24)
    asset_class_id: Id = D.EF_CLASS_ID
    build_share: float = Field(default=1.0, ge=0.1, le=1.0)


class AssetClass(_Strict):
    id: Id
    name: Name
    category: Literal["cash", "debt", "equity", "gold", "other"]
    expected_return_pct: float = Field(ge=-20, le=40)
    volatility_pct: float = Field(ge=0, le=80)
    expense_ratio_pct: float = Field(default=0.0, ge=0, le=5)
    tax_drag_pct: float = Field(default=0.0, ge=0, le=10)
    liquidity_days: int = Field(default=0, ge=0, le=365)
    lock_in_months: int = Field(default=0, ge=0, le=360)
    min_monthly_contribution: Money = 0.0
    description: Annotated[str, StringConstraints(max_length=500)] = ""


class Correlation(_Strict):
    a: Id
    b: Id
    rho: float = Field(ge=-1, le=1)

    @model_validator(mode="after")
    def _distinct(self) -> "Correlation":
        if self.a == self.b:
            raise ValueError("a correlation needs two different asset classes")
        return self


class GlideStep(_Strict):
    min_months_to_goal: int = Field(ge=0, le=600)
    multiplier: float = Field(ge=0, le=1)


def _default_classes() -> list[AssetClass]:
    return [AssetClass(**d) for d in D.default_asset_classes_data()]


def _default_correlations() -> list[Correlation]:
    return [Correlation(**d) for d in D.default_correlations_data()]


def _default_glide() -> list[GlideStep]:
    return [GlideStep(**d) for d in D.default_glide_data()]


class Assumptions(_Strict):
    inflation_pct: float = Field(default=D.INFLATION_PCT, ge=-2, le=25)
    inflation_volatility_pct: float = Field(default=D.INFLATION_VOLATILITY_PCT, ge=0, le=10)
    cash_class_id: Id = D.CASH_CLASS_ID
    asset_classes: list[AssetClass] = Field(default_factory=_default_classes, min_length=1, max_length=10)
    correlations: list[Correlation] = Field(default_factory=_default_correlations, max_length=45)
    risky_cap_by_tolerance_pct: list[Annotated[float, Field(ge=0, le=100)]] = Field(
        default_factory=lambda: list(D.RISKY_CAP_BY_TOLERANCE_PCT))
    glide_path: list[GlideStep] = Field(default_factory=_default_glide, min_length=1, max_length=12)
    source_note: Annotated[str, StringConstraints(max_length=1000)] = D.SOURCE_NOTE

    @model_validator(mode="after")
    def _shape(self) -> "Assumptions":
        caps = self.risky_cap_by_tolerance_pct
        if len(caps) != 5:
            raise ValueError("risky_cap_by_tolerance_pct must have exactly 5 values")
        if any(caps[i] > caps[i + 1] for i in range(4)):
            raise ValueError("risky_cap_by_tolerance_pct must be non-decreasing")
        steps = [g.min_months_to_goal for g in self.glide_path]
        if 0 not in steps:
            raise ValueError("glide_path must contain a step with min_months_to_goal == 0")
        if len(set(steps)) != len(steps):
            raise ValueError("glide_path min_months_to_goal values must be unique")
        return self


class PlanConstraints(_Strict):
    max_equity_pct: float | None = Field(default=None, ge=0, le=100)
    max_class_pct: dict[Id, Annotated[float, Field(ge=0, le=100)]] = Field(default_factory=dict)
    min_cash_buffer: Money = 0.0
    contribution_block_months: Literal[6, 12] = 12
    rebalance_cost_pct: float = Field(default=0.1, ge=0, le=2)


class FinancePlan(_Strict):
    id: Id = "draft"
    name: Name
    description: Annotated[str, StringConstraints(max_length=10000)] = ""
    schema_version: Literal[1] = 1
    start_month: Month | None = None
    horizon_end_month: Month | None = None
    profile: Profile = Field(default_factory=Profile)
    incomes: list[IncomeStream] = Field(default_factory=list, max_length=20)
    expenses: list[Expense] = Field(default_factory=list, max_length=100)
    debts: list[Debt] = Field(default_factory=list, max_length=20)
    holdings: list[Holding] = Field(default_factory=list, max_length=50)
    one_offs: list[OneOff] = Field(default_factory=list, max_length=200)
    goals: list[Goal] = Field(default_factory=list, max_length=12)
    emergency_fund: EmergencyFundSettings = Field(default_factory=EmergencyFundSettings)
    assumptions: Assumptions = Field(default_factory=Assumptions)
    constraints: PlanConstraints = Field(default_factory=PlanConstraints)
    metadata: Metadata = Field(default_factory=dict)


# ---------------------------------------------------------------- preflight (section 6)

class FinanceIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    field: str | None = None
    item_ids: list[str] = Field(default_factory=list)


class FinancePreflightReport(BaseModel):
    ok: bool
    issues: list[FinanceIssue]


# ---------------------------------------------------------------- cash flow (section 7)

class AssignableItem(BaseModel):
    holding_id: str
    asset_class_id: str
    amount: float
    locked_until_index: int | None = None


class InitialSplit(BaseModel):
    """How one holding was split at t = 0 by the EF waterfall (7.3)."""
    holding_id: str
    source: Literal["earmark", "initial_ef", "initial_cash", "pool"]
    amount: float
    goal_id: str | None = None


class CashflowProjection(BaseModel):
    start_month: str
    T: int
    months: list[str]
    income: list[float]
    essential: list[float]
    discretionary: list[float]
    debt_payments: list[float]
    one_off_net: list[float]
    surplus: list[float]
    ef_contribution: list[float]
    ef_balance: list[float]
    investable: list[float]
    ef_target: float
    ef_initial: float
    ef_complete_index: int | None
    cash_buffer_initial: float
    assignable: list[AssignableItem]
    debt_payoff: dict[str, int | None]
    price_index: list[float]
    initial_splits: list[InitialSplit] = Field(default_factory=list)


class DebtPayoff(BaseModel):
    debt_id: str
    month: str | None


class CashflowYear(BaseModel):
    year: int
    start_month: str
    income: float
    essential: float
    discretionary: float
    debt_payments: float
    one_off_net: float
    surplus: float


class CashflowSummary(BaseModel):
    ef_target: float
    ef_initial: float
    ef_complete_month: str | None
    avg_monthly_surplus_first_year: float
    min_monthly_surplus: float
    negative_surplus_months: list[str]
    debts_paid_off: list[DebtPayoff]
    years: list[CashflowYear]


# ---------------------------------------------------------------- run request / progress (section 10)

class IncomeInterruption(_Strict):
    enabled: bool = False
    annual_probability: float = Field(default=0.05, ge=0, le=0.5)
    duration_months: int = Field(default=3, ge=1, le=24)


class SimulationSettings(_Strict):
    n_paths: int = Field(default=2000, ge=100, le=10000)
    income_interruption: IncomeInterruption = Field(default_factory=IncomeInterruption)


class ResultSimulationSettings(SimulationSettings):
    """`FinanceResult.simulation_settings` (F.14): the run's simulation settings plus the seed it used."""
    seed: int = Field(default=0, ge=0, le=2**31 - 1)


class FinanceRunRequest(_Strict):
    time_limit_seconds: float = Field(default=30, ge=5, le=120)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)
    calibration_rounds: int = Field(default=2, ge=0, le=4)
    compute_fixes: bool = True
    label: Annotated[str, StringConstraints(max_length=100)] | None = None


class FinanceProgress(BaseModel):
    stage: Literal["preflight", "cashflow", "optimize", "simulate", "calibrate", "validate", "fixes"]
    fraction: float = 0.0
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- validator (section 11)

class FinanceViolation(BaseModel):
    code: str
    severity: Literal["hard", "soft"]
    message: str
    goal_id: str | None = None
    asset_class_id: str | None = None
    months: list[str] = Field(default_factory=list)
    amount: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- what-if (section 13)

class GoalOverride(_Strict):
    goal_id: Id
    target_month: Month | None = None
    target_amount: Annotated[float, Field(gt=0, le=1e12)] | None = None
    priority: Priority | None = None
    enabled: bool | None = None
    risk_tolerance: Tolerance | None = None


class IncomeDrop(_Strict):
    start_month: Month
    months: int = Field(ge=1, le=24)
    percent: float = Field(gt=0, le=100)


class WhatIfChanges(_Strict):
    label: Annotated[str, StringConstraints(max_length=100)] | None = None
    extra_monthly_savings: float = Field(default=0.0, ge=-1e9, le=1e9)
    goal_overrides: list[GoalOverride] = Field(default_factory=list, max_length=12)
    risk_tolerance: Tolerance | None = None
    return_shift_pct: float = Field(default=0.0, ge=-10, le=10)
    inflation_pct: float | None = Field(default=None, ge=-2, le=25)
    income_drop: IncomeDrop | None = None
    emergency_build_share: float | None = Field(default=None, ge=0.1, le=1.0)


# ---------------------------------------------------------------- explanations (section 12)

class Reason(BaseModel):
    code: str
    message: str
    months: list[str] = Field(default_factory=list)
    asset_class_ids: list[str] = Field(default_factory=list)
    values: dict[str, float | str] = Field(default_factory=dict)


class Fix(BaseModel):
    kind: Literal["DELAY_GOAL", "INCREASE_SAVINGS", "SPEND_LESS", "INCREASE_RISK", "REDUCE_TARGET",
                  "LOWER_EF_BUILD_SHARE"]
    goal_id: str | None = None
    message: str
    months: int | None = None
    amount: float | None = None
    new_target_month: str | None = None
    new_risk_tolerance: int | None = None
    resulting_shortfall_real: float | None = None
    resulting_success_probability: float | None = None
    relative_change: float
    smallest: bool = False
    what_if: WhatIfChanges


class GoalExplanation(BaseModel):
    reasons: list[Reason] = Field(default_factory=list)
    fixes: list[Fix] = Field(default_factory=list)


class Binding(BaseModel):
    code: str
    message: str
    months: list[str] = Field(default_factory=list)
    goal_ids: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    summary: list[str] = Field(default_factory=list)
    goals: dict[str, GoalExplanation] = Field(default_factory=dict)
    binding_constraints: list[Binding] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    replanning_triggers: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- result (section 14)

Feasibility = Literal["feasible", "infeasible", "unknown"]
GoalStatus = Literal["on_track", "at_risk", "off_track"]


class ResultSummary(BaseModel):
    goals_total: int = 0
    goals_on_track: int = 0
    goals_at_risk: int = 0
    goals_off_track: int = 0
    monthly_investable_now: float = 0.0
    monthly_contribution_now: float = 0.0
    emergency_fund_target: float = 0.0
    emergency_fund_now: float = 0.0
    emergency_fund_complete_month: str | None = None
    liquidity_risk_probability: float = 0.0
    total_contributions_real: float = 0.0


class GoalResult(BaseModel):
    goal_id: str
    name: str
    kind: str = "other"
    priority: Priority = "should"
    target_month: str
    months_to_goal: int
    target_amount: float
    target_real: float
    target_nominal_expected: float = 0.0
    planned_value_real: float = 0.0
    projected_central_real: float = 0.0
    shortfall_real: float = 0.0
    shortfall_fraction: float = 0.0
    success_probability: float = 0.0
    min_success_probability: float = 0.7
    p10_real: float = 0.0
    p50_real: float = 0.0
    p90_real: float = 0.0
    expected_shortfall_real: float = 0.0
    scenario_low_real: float = 0.0
    scenario_high_real: float = 0.0
    status: GoalStatus = "off_track"
    contribution_start_month: str | None = None
    contribution_end_month: str | None = None
    monthly_contribution_now: float = 0.0
    total_contributions_real: float = 0.0
    holdings_used_real: float = 0.0
    allocation_now_pct: dict[str, float] = Field(default_factory=dict)
    planning_z: float = 0.0


class ContributionLine(BaseModel):
    goal_id: str
    asset_class_id: str
    start_month: str
    end_month: str
    monthly_amount_real: float
    monthly_amount_nominal_start: float = 0.0
    monthly_amount_nominal_end: float = 0.0


class HoldingAssignment(BaseModel):
    holding_id: str
    goal_id: str
    amount: float
    source: Literal["earmark", "assigned", "initial_ef", "initial_cash", "sold_to_cash", "unallocated"]


class Rebalance(BaseModel):
    month: str
    goal_id: str
    sells: dict[str, float] = Field(default_factory=dict)
    buys: dict[str, float] = Field(default_factory=dict)


class GlidePoint(BaseModel):
    month: str
    months_to_goal: int
    risky_cap_pct: float
    risky_share_pct: float
    weights_pct: dict[str, float] = Field(default_factory=dict)


class ResultSeries(BaseModel):
    months: list[str] = Field(default_factory=list)
    corpus_by_class: dict[str, list[float]] = Field(default_factory=dict)
    emergency_fund: list[float] = Field(default_factory=list)
    cash_buffer: list[float] = Field(default_factory=list)
    unallocated: list[float] = Field(default_factory=list)
    goal_withdrawals: list[float] = Field(default_factory=list)
    total_p10: list[float] = Field(default_factory=list)
    total_p50: list[float] = Field(default_factory=list)
    total_p90: list[float] = Field(default_factory=list)


class ResultCashflow(BaseModel):
    months: list[str] = Field(default_factory=list)
    income: list[float] = Field(default_factory=list)
    essential: list[float] = Field(default_factory=list)
    discretionary: list[float] = Field(default_factory=list)
    debt_payments: list[float] = Field(default_factory=list)
    one_off_net: list[float] = Field(default_factory=list)
    surplus: list[float] = Field(default_factory=list)
    emergency_fund_contribution: list[float] = Field(default_factory=list)
    goal_contribution: list[float] = Field(default_factory=list)
    cash_buffer_end: list[float] = Field(default_factory=list)


SCENARIO_DEFINITIONS = {"low": "returns -0.5 x volatility, inflation +1pp", "central": "expected returns",
                        "high": "returns +0.5 x volatility, inflation -1pp"}


class Scenarios(BaseModel):
    definitions: dict[str, str] = Field(default_factory=lambda: dict(SCENARIO_DEFINITIONS))
    goals: dict[str, dict[str, float]] = Field(default_factory=dict)


class AssumptionsUsed(BaseModel):
    inflation_pct: float = D.INFLATION_PCT
    asset_classes: list[AssetClass] = Field(default_factory=list)
    glide_path: list[GlideStep] = Field(default_factory=list)
    risky_cap_by_tolerance_pct: list[float] = Field(default_factory=list)
    planning_returns_pct: dict[str, dict[str, float]] = Field(default_factory=dict)
    source_note: str = D.SOURCE_NOTE


class TierDiagnostic(BaseModel):
    tier: str
    status: str
    objective: float | None = None
    seconds: float = 0.0


class Diagnostics(BaseModel):
    solver: str = "GLOP"
    variables: int = 0
    constraints: int = 0
    tiers: list[TierDiagnostic] = Field(default_factory=list)
    calibration_rounds: int = 0
    simulation_seconds: float = 0.0
    fix_solves: int = 0
    warnings: list[str] = Field(default_factory=list)
    cash_deficit_real: float = 0.0
    seconds_total: float = 0.0


class FinanceResult(BaseModel):
    engine_version: str = D.FINANCE_ENGINE_VERSION
    disclaimer: str = D.DISCLAIMER
    disclaimer_version: str = D.DISCLAIMER_VERSION
    start_month: str
    horizon_months: int
    end_month: str
    currency: str = "INR"
    feasibility: Feasibility = "unknown"
    termination_reason: Literal["optimal", "time_limit", "gap"] = "optimal"
    optimality_proven: bool = True
    summary: ResultSummary = Field(default_factory=ResultSummary)
    goals: list[GoalResult] = Field(default_factory=list)
    contributions: list[ContributionLine] = Field(default_factory=list)
    holdings_assignment: list[HoldingAssignment] = Field(default_factory=list)
    rebalances: list[Rebalance] = Field(default_factory=list)
    glide_paths: dict[str, list[GlidePoint]] = Field(default_factory=dict)
    series: ResultSeries = Field(default_factory=ResultSeries)
    cashflow: ResultCashflow = Field(default_factory=ResultCashflow)
    scenarios: Scenarios = Field(default_factory=Scenarios)
    explanation: Explanation = Field(default_factory=Explanation)
    violations: list[FinanceViolation] = Field(default_factory=list)
    assumptions_used: AssumptionsUsed = Field(default_factory=AssumptionsUsed)
    simulation_settings: ResultSimulationSettings = Field(default_factory=ResultSimulationSettings)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)


class FinanceResultSummary(BaseModel):
    id: str | None = None
    plan_id: str | None = None
    run_id: str | None = None
    plan_version_id: str | None = None
    base_plan_version: int | None = None
    kind: Literal["baseline", "what_if"] = "baseline"
    label: str | None = None
    feasibility: Feasibility = "unknown"
    goals_total: int = 0
    goals_on_track: int = 0
    goals_at_risk: int = 0
    goals_off_track: int = 0
    monthly_contribution_now: float = 0.0
    created_at: str | None = None
    what_if: WhatIfChanges | None = None


class ComparisonTotals(BaseModel):
    monthly_contribution_now_a: float
    monthly_contribution_now_b: float
    monthly_contribution_now_delta: float
    ef_complete_month_a: str | None
    ef_complete_month_b: str | None
    goals_on_track_a: int
    goals_on_track_b: int
    liquidity_risk_a: float
    liquidity_risk_b: float


class GoalComparison(BaseModel):
    goal_id: str
    name: str
    in_a: bool
    in_b: bool
    target_month_a: str | None = None
    target_month_b: str | None = None
    success_a: float | None = None
    success_b: float | None = None
    success_delta: float | None = None
    p50_a: float | None = None
    p50_b: float | None = None
    p50_delta: float | None = None
    shortfall_a: float | None = None
    shortfall_b: float | None = None
    monthly_now_a: float | None = None
    monthly_now_b: float | None = None
    status_a: str | None = None
    status_b: str | None = None


class FinanceComparison(BaseModel):
    a: FinanceResultSummary
    b: FinanceResultSummary
    totals: ComparisonTotals
    goals: list[GoalComparison]
    what_if_b: WhatIfChanges | None = None


# ---------------------------------------------------------------- templates (section 15)

class FinanceTemplateParameter(BaseModel):
    name: str
    label: str
    type: Literal["int", "money", "month_offset_years"]
    default: float
    min: float | None = None
    max: float | None = None
    help: str = ""


# ---------------------------------------------------------------- errors

class FinancePreflightError(Exception):
    def __init__(self, report: FinancePreflightReport):
        self.report = report
        errors = [i.message for i in report.issues if i.severity == "error"]
        super().__init__("; ".join(errors) or "preflight failed")


class FinanceCancelled(Exception):
    """The run was cancelled (cancelled runs store no result)."""


__all__ = [
    "Id", "Month", "Money", "SignedMoney", "Frequency", "Priority", "Name", "Profile", "IncomeStream", "Expense",
    "Debt", "Holding", "OneOff", "Earmark", "Goal", "EmergencyFundSettings", "AssetClass", "Correlation",
    "GlideStep", "Assumptions", "PlanConstraints", "FinancePlan", "FinanceIssue", "FinancePreflightReport",
    "AssignableItem", "InitialSplit", "CashflowProjection", "DebtPayoff", "CashflowYear", "CashflowSummary",
    "IncomeInterruption", "SimulationSettings", "ResultSimulationSettings", "FinanceRunRequest", "FinanceProgress", "FinanceViolation",
    "GoalOverride", "IncomeDrop", "WhatIfChanges", "Reason", "Fix", "GoalExplanation", "Binding", "Explanation",
    "ResultSummary", "GoalResult", "ContributionLine", "HoldingAssignment", "Rebalance", "GlidePoint",
    "ResultSeries", "ResultCashflow", "Scenarios", "AssumptionsUsed", "TierDiagnostic", "Diagnostics",
    "FinanceResult", "FinanceResultSummary", "ComparisonTotals", "GoalComparison", "FinanceComparison",
    "FinanceTemplateParameter", "FinancePreflightError", "FinanceCancelled", "SCENARIO_DEFINITIONS",
]
