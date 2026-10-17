"""Intake models (PHASE2 2.3-2.5, 2.9, 2.13, 2.15): drafts, provenance, questions and responses.

Request-side models use the `_Strict` base (`extra="forbid"`); response-only models are plain `BaseModel`.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from superplanner.engine.model import HHMM, Problem, Weekday
from superplanner.engine.preflight import ValidateReport
from superplanner.finance.model import (CashflowSummary, FinancePlan, FinancePreflightReport, Frequency, Month,
                                        Priority)

Domain = Literal["schedule", "finance"]
ScheduleKind = Literal["project", "study", "production", "generic"]
SCHEDULE_KINDS: tuple[str, ...] = ("project", "study", "production", "generic")
DraftKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
DurationUnit = Literal["minutes", "hours", "days", "weeks"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntakeError(Exception):
    """A user-facing intake error (422 on the API) with a stable code (2.15)."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class IntakeTextError(IntakeError):
    """TEXT_EMPTY / TEXT_TOO_LONG."""


# ---------------------------------------------------------------- common (2.3)

class ExtractContext(_Strict):
    today: date
    utc_offset: Annotated[str, StringConstraints(pattern=r"^[+-]\d{2}:\d{2}$")] = "+00:00"
    locale: Annotated[str, StringConstraints(max_length=16)] = "en-IN"
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "INR"
    kind: ScheduleKind | None = None


class SourceSpan(_Strict):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str = Field(max_length=300)

    @model_validator(mode="after")
    def _ordered(self) -> "SourceSpan":
        if self.end < self.start:
            raise ValueError("span end must not be before its start")
        return self


class CellRef(_Strict):
    row: int = Field(ge=0)
    column: int = Field(ge=0)


class Provenance(_Strict):
    source: Literal["text", "table", "ai", "default", "answer", "edit", "derived"]
    confidence: float = Field(ge=0, le=1)
    span: SourceSpan | None = None
    cell: CellRef | None = None
    note: str = Field(default="", max_length=300)


class QuestionOption(_Strict):
    value: str
    label: str


class Question(_Strict):
    id: str
    code: str
    path: str | None
    kind: Literal["number", "money", "percent", "duration", "date", "month", "choice", "multi_choice", "text",
                  "confirm", "people", "working_time"]
    prompt: str
    help: str = ""
    options: list[QuestionOption] = []
    default: Any | None = None
    default_label: str = ""
    required: bool
    reason: Literal["missing", "ambiguous", "low_confidence", "conflict", "confirm_default"]
    span: SourceSpan | None = None
    error: str | None = None


class Answer(_Strict):
    question_id: str = Field(max_length=200)
    value: Any | None = None
    use_default: bool = False
    skip: bool = False


class IntakeNote(_Strict):
    code: str
    severity: Literal["info", "warning"]
    message: str
    span: SourceSpan | None = None


class ExtractorInfo(_Strict):
    requested: Literal["rule", "ai"]
    used: Literal["rule", "ai+rule"]
    ai_available: bool
    fallback_code: str | None = None
    fallback_message: str | None = None
    model: str | None = None


def _unique(keys: list[str], what: str) -> None:
    seen: set[str] = set()
    for k in keys:
        if k in seen:
            raise ValueError(f"duplicate {what} key {k!r}")
        seen.add(k)


# ---------------------------------------------------------------- schedule draft (2.4)

class DraftDuration(_Strict):
    optimistic: float = Field(gt=0, le=10000)
    likely: float = Field(gt=0, le=10000)
    pessimistic: float = Field(gt=0, le=10000)
    unit: DurationUnit

    @model_validator(mode="after")
    def _ordered(self) -> "DraftDuration":
        if not (self.optimistic <= self.likely <= self.pessimistic):
            raise ValueError("duration must satisfy optimistic <= likely <= pessimistic")
        return self

    @classmethod
    def single(cls, value: float, unit: str) -> "DraftDuration":
        return cls(optimistic=value, likely=value, pessimistic=value, unit=unit)  # type: ignore[arg-type]

    @classmethod
    def range(cls, low: float, high: float, unit: str) -> "DraftDuration":
        return cls(optimistic=low, likely=(low + high) / 2, pessimistic=high, unit=unit)  # type: ignore[arg-type]


def _hhmm_minutes(v: str) -> int:
    h, m = v.split(":")
    return int(h) * 60 + int(m)


class TimeWindow(_Strict):
    start: HHMM
    end: HHMM

    @model_validator(mode="after")
    def _ordered(self) -> "TimeWindow":
        if self.start == "24:00" or _hhmm_minutes(self.start) >= _hhmm_minutes(self.end):
            raise ValueError("a time window must start before it ends")
        return self


class WorkingTime(_Strict):
    days: list[Weekday] = Field(min_length=1)
    windows: list[TimeWindow] = Field(min_length=1, max_length=4)
    weekend_windows: list[TimeWindow] | None = Field(default=None, max_length=4)


class DraftResource(_Strict):
    key: DraftKey
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["person", "machine", "room", "equipment", "generic"] = "generic"
    count: int = Field(default=1, ge=1, le=50)


class DraftTask(_Strict):
    key: DraftKey
    name: str = Field(min_length=1, max_length=200)
    milestone: bool = False
    duration: DraftDuration | None = None
    after: list[DraftKey] = Field(default_factory=list, max_length=500)
    resources: list[DraftKey] = Field(default_factory=list, max_length=100)
    resource_mode: Literal["any", "all"] = "any"
    deadline: date | None = None
    deadline_hard: bool = False
    earliest_start: date | None = None
    priority: int | None = Field(default=None, ge=1, le=10)
    group: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=2000)


class ScheduleDraft(_Strict):
    domain: Literal["schedule"] = "schedule"
    kind: ScheduleKind = "generic"
    name: str = Field(default="My plan", min_length=1, max_length=200)
    start_date: date | None = None
    horizon_days: int | None = Field(default=None, ge=1, le=366)
    working_time: WorkingTime | None = None
    objective: Literal["balanced", "finish_asap", "meet_deadlines", "lowest_cost"] | None = None
    tasks: list[DraftTask] = Field(default_factory=list, max_length=500)
    resources: list[DraftResource] = Field(default_factory=list, max_length=100)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    dismissed: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _references(self) -> "ScheduleDraft":
        _unique([t.key for t in self.tasks], "task")
        _unique([r.key for r in self.resources], "resource")
        tkeys = {t.key for t in self.tasks}
        rkeys = {r.key for r in self.resources}
        for t in self.tasks:
            for a in t.after:
                if a == t.key:
                    raise ValueError(f"task {t.key!r} must not depend on itself")
                if a not in tkeys:
                    raise ValueError(f"task {t.key!r} depends on unknown task {a!r}")
            for r in t.resources:
                if r not in rkeys:
                    raise ValueError(f"task {t.key!r} uses unknown resource {r!r}")
        return self


# ---------------------------------------------------------------- finance draft (2.5)

class DraftAmount(_Strict):
    low: float = Field(ge=0, le=1e12)
    high: float = Field(ge=0, le=1e12)

    @model_validator(mode="after")
    def _ordered(self) -> "DraftAmount":
        if self.low > self.high:
            raise ValueError("the low end of an amount must not be above the high end")
        return self

    @classmethod
    def exact(cls, v: float) -> "DraftAmount":
        return cls(low=v, high=v)

    @property
    def mid(self) -> float:
        return round((self.low + self.high) / 2, 2)


class DraftProfile(_Strict):
    age: int | None = Field(default=None, ge=16, le=100)
    retirement_age: int | None = Field(default=None, ge=40, le=80)
    risk_tolerance: int | None = Field(default=None, ge=1, le=5)
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "INR"
    locale: Annotated[str, StringConstraints(max_length=16)] = "en-IN"


Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class DraftIncome(_Strict):
    key: DraftKey
    name: Name
    kind: Literal["salary", "business", "rental", "pension", "interest", "other"] = "salary"
    amount: DraftAmount | None = None
    frequency: Frequency = "monthly"
    growth_pct: float | None = Field(default=None, ge=-50, le=50)
    inflation_linked: bool = True
    interruptible: bool = True
    end_month: Month | None = None


class DraftExpense(_Strict):
    key: DraftKey
    name: Name
    category: Annotated[str, StringConstraints(max_length=64)] = "other"
    amount: DraftAmount | None = None
    frequency: Frequency = "monthly"
    essential: bool | None = None
    inflation_pct: float | None = Field(default=None, ge=-5, le=30)
    end_month: Month | None = None


class DraftDebt(_Strict):
    key: DraftKey
    name: Name
    kind: Literal["home", "vehicle", "education", "personal", "credit_card", "other"] = "other"
    balance: DraftAmount | None = None
    interest_rate_pct: float | None = Field(default=None, ge=0, le=60)
    emi: DraftAmount | None = None
    remaining_months: int | None = Field(default=None, ge=1, le=600)


class DraftHolding(_Strict):
    key: DraftKey
    name: Name
    asset_class_id: str | None = Field(default=None, max_length=64)
    amount: DraftAmount | None = None
    locked_until_month: Month | None = None


class DraftGoal(_Strict):
    key: DraftKey
    name: Name
    kind: Literal["retirement", "education", "home", "vehicle", "travel", "wedding", "business", "other"] = "other"
    target: DraftAmount | None = None
    target_month: Month | None = None
    priority: Priority | None = None
    flexibility_months: int = Field(default=0, ge=0, le=120)
    inflation_pct: float | None = Field(default=None, ge=-5, le=30)


class FinanceDraft(_Strict):
    domain: Literal["finance"] = "finance"
    name: Name = "My financial plan"
    start_month: Month | None = None
    profile: DraftProfile = Field(default_factory=DraftProfile)
    incomes: list[DraftIncome] = Field(default_factory=list, max_length=20)
    expenses: list[DraftExpense] = Field(default_factory=list, max_length=100)
    debts: list[DraftDebt] = Field(default_factory=list, max_length=20)
    holdings: list[DraftHolding] = Field(default_factory=list, max_length=50)
    goals: list[DraftGoal] = Field(default_factory=list, max_length=12)
    emergency_fund_months: float | None = Field(default=None, ge=0, le=24)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    dismissed: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _keys(self) -> "FinanceDraft":
        for what, items in (("income", self.incomes), ("expense", self.expenses), ("debt", self.debts),
                            ("holding", self.holdings), ("goal", self.goals)):
            _unique([i.key for i in items], what)
        return self


# ---------------------------------------------------------------- responses (2.9, 2.15)

class ScheduleIntakeResponse(BaseModel):
    draft: ScheduleDraft
    questions: list[Question]
    notes: list[IntakeNote]
    row_notes: list[IntakeNote] = []
    extractor: ExtractorInfo
    ready: bool


class FinanceIntakeResponse(BaseModel):
    draft: FinanceDraft
    questions: list[Question]
    notes: list[IntakeNote]
    row_notes: list[IntakeNote] = []
    extractor: ExtractorInfo
    ready: bool


class DurationSummary(BaseModel):
    tasks_with_range: int
    expected_work_minutes: int
    optimistic_work_minutes: int
    pessimistic_work_minutes: int


class ScheduleBuildResult(BaseModel):
    ready: bool
    problem: Problem | None
    report: ValidateReport | None
    blocking: list[Question]
    parts: dict[str, list[str]]
    duration_summary: DurationSummary | None


class FinanceBuildResult(BaseModel):
    ready: bool
    plan: FinancePlan | None
    preflight: FinancePreflightReport | None
    cashflow: CashflowSummary | None
    blocking: list[Question]


# ---------------------------------------------------------------- tables (2.13)

MAX_TABLE_CHARS = 1_000_000
MAX_TABLE_ROWS = 2000
MAX_TABLE_COLUMNS = 30


class TableColumn(BaseModel):
    index: int
    header: str | None
    samples: list[str]
    suggested_field: str | None
    confidence: float


class TableParseResult(BaseModel):
    delimiter: str
    has_header: bool
    row_count: int
    columns: list[TableColumn]
    preview: list[list[str]]
    warnings: list[str]


class ColumnMapping(_Strict):
    column: int = Field(ge=0)
    field: str | None = Field(default=None, max_length=64)


class TableOptions(_Strict):
    duration_unit: DurationUnit = "days"
    default_row_kind: Literal["income", "expense", "goal", "debt", "holding"] = "expense"
    amount_frequency: Frequency = "monthly"
    predecessor_ref: Literal["auto", "id", "name", "row"] = "auto"


class TableParseRequest(_Strict):
    text: str = Field(max_length=MAX_TABLE_CHARS)
    delimiter: Literal["auto", "\t", ",", ";", "|"] = "auto"
    has_header: bool | None = None


class TableApply(_Strict):
    text: str = Field(max_length=MAX_TABLE_CHARS)
    delimiter: Literal["\t", ",", ";", "|"]
    has_header: bool
    mapping: list[ColumnMapping] = Field(max_length=MAX_TABLE_COLUMNS)
    options: TableOptions = Field(default_factory=TableOptions)
