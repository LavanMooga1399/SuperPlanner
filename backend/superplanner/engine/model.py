"""External `Problem` document (ARCHITECTURE section 3).

Only field-local rules live here (section 3.0). Everything relational or horizon-dependent is
checked by `preflight.py` so incomplete drafts stay saveable.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,64}$")]
HHMM = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Document size caps (section 3.0, Implementation notes). They bound what a single save can store; they are
# deliberately looser than the preflight solve limits (MAX_TASKS etc.) so an oversized draft still gets a
# readable TOO_LARGE preflight error instead of a schema rejection.
MAX_DOC_TASKS = 5000
MAX_DOC_RESOURCES = 1000
MAX_DOC_DEPENDENCIES = 20000
MAX_REQUIREMENTS = 50
MAX_ALTERNATIVES = 1000
MAX_BLOCKED = 2000
MAX_WEEKLY_SLOTS = 48
MAX_DESCRIPTION = 10000
MAX_SHORT_TEXT = 200
MAX_ITEM_METADATA_BYTES = 16 * 1024
MAX_PROBLEM_METADATA_BYTES = 64 * 1024


def _metadata_cap(limit: int):
    def check(v: dict[str, Any]) -> dict[str, Any]:
        try:
            size = len(json.dumps(v, separators=(",", ":"), default=str).encode())
        except (TypeError, ValueError) as exc:  # pragma: no cover - JSON input is always serialisable
            raise ValueError("metadata must be JSON-serialisable") from exc
        if size > limit:
            raise ValueError(f"metadata is too large ({size} bytes, max {limit})")
        return v
    return check


ItemMetadata = Annotated[dict[str, Any], AfterValidator(_metadata_cap(MAX_ITEM_METADATA_BYTES))]
ProblemMetadata = Annotated[dict[str, Any], AfterValidator(_metadata_cap(MAX_PROBLEM_METADATA_BYTES))]
ShortText = Annotated[str, StringConstraints(max_length=MAX_SHORT_TEXT)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Terminology(_Strict):
    task: ShortText = "Task"
    tasks: ShortText = "Tasks"
    resource: ShortText = "Resource"
    resources: ShortText = "Resources"
    group: ShortText = "Group"
    milestone: ShortText = "Milestone"
    schedule: ShortText = "Schedule"
    deadline: ShortText = "Deadline"


class Requirement(_Strict):
    alternatives: list[Id] = Field(min_length=1, max_length=MAX_ALTERNATIVES)
    units: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _no_duplicates(self) -> "Requirement":
        if len(set(self.alternatives)) != len(self.alternatives):
            raise ValueError("requirement alternatives must not contain duplicates")
        return self


class Lock(_Strict):
    start: AwareDatetime
    resource_ids: list[Id] | None = Field(default=None, max_length=MAX_ALTERNATIVES)


class Dependency(_Strict):
    predecessor: Id
    successor: Id
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag_minutes: int = 0


class BlockedInterval(_Strict):
    start: AwareDatetime
    end: AwareDatetime
    reason: str = Field(default="", max_length=1000)


class Calendar(_Strict):
    weekly: dict[Weekday, Annotated[list[tuple[HHMM, HHMM]], Field(max_length=MAX_WEEKLY_SLOTS)]] | None = None
    blocked: list[BlockedInterval] = Field(default_factory=list, max_length=MAX_BLOCKED)


class Resource(_Strict):
    id: Id
    name: str = Field(min_length=1, max_length=200)
    kind: ShortText = "generic"
    capacity: int = Field(default=1, ge=1, le=1000)
    cost_per_hour: float = Field(default=0.0, ge=0)
    calendar: Calendar | None = None
    metadata: ItemMetadata = Field(default_factory=dict)


def pert_minutes(optimistic: int, likely: int, pessimistic: int) -> int:
    """PERT expected value (o + 4m + p) / 6 rounded half up to whole minutes (PHASE2 2.14)."""
    return (optimistic + 4 * likely + pessimistic + 3) // 6


class DurationEstimate(_Strict):
    """Optional three-point estimate of an activity (PHASE2 2.14). Informational: engines use duration_minutes."""

    optimistic_minutes: int = Field(ge=1)
    likely_minutes: int = Field(ge=1)
    pessimistic_minutes: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "DurationEstimate":
        if not (self.optimistic_minutes <= self.likely_minutes <= self.pessimistic_minutes):
            raise ValueError("duration_estimate must satisfy optimistic <= likely <= pessimistic")
        return self

    @property
    def expected_minutes(self) -> int:
        return pert_minutes(self.optimistic_minutes, self.likely_minutes, self.pessimistic_minutes)


class Task(_Strict):
    id: Id
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    group: ShortText | None = None
    type: Literal["activity", "milestone"] = "activity"
    duration_minutes: int = 0
    priority: int = Field(default=5, ge=1, le=10)
    earliest_start: AwareDatetime | None = None
    deadline: AwareDatetime | None = None
    deadline_hard: bool = False
    requirements: list[Requirement] = Field(default_factory=list, max_length=MAX_REQUIREMENTS)
    locked: Lock | None = None
    metadata: ItemMetadata = Field(default_factory=dict)
    # Omitted from dumps when absent, so documents without a range serialise exactly as before PHASE2.
    duration_estimate: DurationEstimate | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _type_rules(self) -> "Task":
        if self.type == "milestone":
            if self.duration_minutes != 0:
                raise ValueError("a milestone must have duration_minutes == 0")
            if self.requirements:
                raise ValueError("a milestone must not have requirements")
            if self.duration_estimate is not None:
                raise ValueError("a milestone must not have duration_estimate")
        elif self.duration_minutes < 1:
            raise ValueError("an activity must have duration_minutes >= 1")
        if self.duration_estimate is not None:
            e = self.duration_estimate.expected_minutes
            if self.duration_minutes != e:
                raise ValueError(f"duration_minutes must be {e}, the expected value of duration_estimate")
        return self


class Weights(_Strict):
    makespan: float = Field(default=1.0, ge=0)
    tardiness: float = Field(default=1.0, ge=0)
    cost: float = Field(default=0.2, ge=0)


class Objectives(_Strict):
    preset: Literal["balanced", "finish_asap", "meet_deadlines", "lowest_cost", "custom"] = "balanced"
    weights: Weights = Field(default_factory=Weights)

    @model_validator(mode="after")
    def _custom_nonzero(self) -> "Objectives":
        if self.preset == "custom":
            w = self.weights
            if w.makespan <= 0 and w.tardiness <= 0 and w.cost <= 0:
                raise ValueError("custom weights must not all be zero")
        return self


class Problem(_Strict):
    id: Id = "draft"
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    domain: ShortText = "generic"
    horizon_start: AwareDatetime
    horizon_days: int = Field(default=30, ge=1, le=366)
    time_unit: Literal["minutes"] = "minutes"
    currency: str = Field(default="USD", max_length=8)
    terminology: Terminology = Field(default_factory=Terminology)
    tasks: list[Task] = Field(default_factory=list, max_length=MAX_DOC_TASKS)
    resources: list[Resource] = Field(default_factory=list, max_length=MAX_DOC_RESOURCES)
    dependencies: list[Dependency] = Field(default_factory=list, max_length=MAX_DOC_DEPENDENCIES)
    objectives: Objectives = Field(default_factory=Objectives)
    metadata: ProblemMetadata = Field(default_factory=dict)


class Placement(BaseModel):
    """One scheduled task (section 7.1). Defined here so the validator need not import solvers."""

    task_id: str
    start: int
    end: int
    resource_ids: list[str] = Field(default_factory=list)
