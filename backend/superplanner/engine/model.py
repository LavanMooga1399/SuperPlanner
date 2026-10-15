"""External `Problem` document (ARCHITECTURE section 3).

Only field-local rules live here (section 3.0). Everything relational or horizon-dependent is
checked by `preflight.py` so incomplete drafts stay saveable.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,64}$")]
HHMM = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Terminology(_Strict):
    task: str = "Task"
    tasks: str = "Tasks"
    resource: str = "Resource"
    resources: str = "Resources"
    group: str = "Group"
    milestone: str = "Milestone"
    schedule: str = "Schedule"
    deadline: str = "Deadline"


class Requirement(_Strict):
    alternatives: list[Id] = Field(min_length=1)
    units: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _no_duplicates(self) -> "Requirement":
        if len(set(self.alternatives)) != len(self.alternatives):
            raise ValueError("requirement alternatives must not contain duplicates")
        return self


class Lock(_Strict):
    start: AwareDatetime
    resource_ids: list[Id] | None = None


class Dependency(_Strict):
    predecessor: Id
    successor: Id
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag_minutes: int = 0


class BlockedInterval(_Strict):
    start: AwareDatetime
    end: AwareDatetime
    reason: str = ""


class Calendar(_Strict):
    weekly: dict[Weekday, list[tuple[HHMM, HHMM]]] | None = None
    blocked: list[BlockedInterval] = Field(default_factory=list)


class Resource(_Strict):
    id: Id
    name: str = Field(min_length=1, max_length=200)
    kind: str = "generic"
    capacity: int = Field(default=1, ge=1, le=1000)
    cost_per_hour: float = Field(default=0.0, ge=0)
    calendar: Calendar | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(_Strict):
    id: Id
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    group: str | None = None
    type: Literal["activity", "milestone"] = "activity"
    duration_minutes: int = 0
    priority: int = Field(default=5, ge=1, le=10)
    earliest_start: AwareDatetime | None = None
    deadline: AwareDatetime | None = None
    deadline_hard: bool = False
    requirements: list[Requirement] = Field(default_factory=list)
    locked: Lock | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _type_rules(self) -> "Task":
        if self.type == "milestone":
            if self.duration_minutes != 0:
                raise ValueError("a milestone must have duration_minutes == 0")
            if self.requirements:
                raise ValueError("a milestone must not have requirements")
        elif self.duration_minutes < 1:
            raise ValueError("an activity must have duration_minutes >= 1")
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
    description: str = ""
    domain: str = "generic"
    horizon_start: AwareDatetime
    horizon_days: int = Field(default=30, ge=1, le=366)
    time_unit: Literal["minutes"] = "minutes"
    currency: str = Field(default="USD", max_length=8)
    terminology: Terminology = Field(default_factory=Terminology)
    tasks: list[Task] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    objectives: Objectives = Field(default_factory=Objectives)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Placement(BaseModel):
    """One scheduled task (section 7.1). Defined here so the validator need not import solvers."""

    task_id: str
    start: int
    end: int
    resource_ids: list[str] = Field(default_factory=list)
