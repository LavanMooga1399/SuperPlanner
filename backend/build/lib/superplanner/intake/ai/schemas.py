"""AI output models (PHASE2 2.10). All `extra="forbid"`, no defaults: every key is required by the strict schema,
optional values are `X | None` and must be sent as null. Constraints not representable in the strict schema
(`max_length`) are enforced here by Pydantic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from superplanner.engine.model import Weekday

Freq = Literal["monthly", "quarterly", "half_yearly", "yearly", "once"]


class _Ai(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Conf(_Ai):
    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _clamp(cls, v: object) -> object:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return min(1.0, max(0.0, float(v)))
        return v


class AiWindow(_Ai):
    start: str
    end: str


class AiWorkingTime(_Ai):
    days: list[Weekday]
    windows: list[AiWindow]
    weekend_windows: list[AiWindow]
    source_quote: str


class AiDuration(_Ai):
    low: float | None
    likely: float | None
    high: float | None
    unit: Literal["minutes", "hours", "days", "weeks"] | None


class AiTask(_Conf):
    name: str
    milestone: bool
    duration: AiDuration
    after: list[str]
    resources: list[str]
    resource_mode: Literal["any", "all"]
    deadline: str | None
    deadline_hard: bool
    earliest_start: str | None
    group: str | None
    source_quote: str
    confidence: float


class AiResource(_Conf):
    name: str
    kind: Literal["person", "machine", "room", "equipment", "generic"]
    count: int
    source_quote: str
    confidence: float


class AiScheduleOutput(_Ai):
    kind: Literal["project", "study", "production", "generic"]
    name: str | None
    start_date: str | None
    working_time: AiWorkingTime | None
    tasks: list[AiTask] = Field(max_length=200)
    resources: list[AiResource] = Field(max_length=50)
    notes: list[str] = Field(max_length=5)


class AiAmount(_Ai):
    low: float | None
    high: float | None


class AiIncome(_Conf):
    name: str
    kind: Literal["salary", "business", "rental", "pension", "interest", "other"]
    amount: AiAmount
    frequency: Freq
    is_gross: bool
    source_quote: str
    confidence: float


class AiExpense(_Conf):
    name: str
    category: str
    amount: AiAmount
    frequency: Freq
    essential: bool | None
    source_quote: str
    confidence: float


class AiDebt(_Conf):
    name: str
    kind: Literal["home", "vehicle", "education", "personal", "credit_card", "other"]
    balance: AiAmount
    emi: AiAmount
    interest_rate_pct: float | None
    remaining_months: int | None
    source_quote: str
    confidence: float


class AiHolding(_Conf):
    name: str
    asset_class: Literal["cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold", "unknown"]
    amount: AiAmount
    locked_until: str | None
    source_quote: str
    confidence: float


class AiGoal(_Conf):
    name: str
    kind: Literal["retirement", "education", "home", "vehicle", "travel", "wedding", "business", "other"]
    target: AiAmount
    target_month: str | None
    in_years: float | None
    at_age: int | None
    priority: Literal["must", "should", "nice"] | None
    source_quote: str
    confidence: float


class AiProfile(_Ai):
    age: int | None
    retirement_age: int | None
    risk_tolerance: int | None
    source_quote: str


class AiFinanceOutput(_Ai):
    profile: AiProfile
    incomes: list[AiIncome] = Field(max_length=20)
    expenses: list[AiExpense] = Field(max_length=100)
    debts: list[AiDebt] = Field(max_length=20)
    holdings: list[AiHolding] = Field(max_length=50)
    goals: list[AiGoal] = Field(max_length=12)
    emergency_fund_months: float | None
    notes: list[str] = Field(max_length=5)
