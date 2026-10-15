"""API-only request models and serialization helpers (ARCHITECTURE 14)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from superplanner.engine import CpSatParams, GaParams, Objectives, Problem, Requirement, Task


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstantiateRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = None
    utc_offset: str = Field(default="+00:00", pattern=r"^[+-]\d{2}:\d{2}$")
    parameters: dict[str, Any] = Field(default_factory=dict)


class SolverRunRequest(_Strict):
    """Mirrors engine `OptimizeRequest` without `initial_solution` (A.7.6, A.14.5)."""

    strategy: Literal["auto", "heuristic", "cpsat", "ga", "hybrid"] = "auto"
    time_limit_seconds: float = Field(default=10.0, ge=1, le=300)
    seed: int = 0
    objectives: Objectives | None = None
    max_alternatives: int = Field(default=2, ge=0, le=5)
    ga: GaParams = Field(default_factory=GaParams)
    cpsat: CpSatParams = Field(default_factory=CpSatParams)


class ApproveRequest(_Strict):
    note: str | None = Field(default=None, max_length=2000)


class ExportFile(_Strict):
    format: Literal["superplanner.problem"]
    format_version: Literal[1]
    exported_at: datetime | None = None
    problem: Problem


class TaskUpdate(_Strict):
    id: str
    name: str | None = Field(default=None, min_length=1, max_length=200)
    duration_minutes: int | None = None
    priority: int | None = Field(default=None, ge=1, le=10)
    earliest_start: AwareDatetime | None = None
    deadline: AwareDatetime | None = None
    deadline_hard: bool | None = None
    requirements: list[Requirement] | None = None


class ResourceUnavailable(_Strict):
    resource_id: str
    start: AwareDatetime
    end: AwareDatetime
    reason: str = ""


class ReplanChanges(_Strict):
    task_updates: list[TaskUpdate] = Field(default_factory=list)
    add_tasks: list[Task] = Field(default_factory=list)
    remove_task_ids: list[str] = Field(default_factory=list)
    resource_unavailable: list[ResourceUnavailable] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.task_updates or self.add_tasks or self.remove_task_ids or self.resource_unavailable)


class ReplanRequest(_Strict):
    cutoff: AwareDatetime
    changes: ReplanChanges = Field(default_factory=ReplanChanges)
    run: SolverRunRequest = Field(default_factory=SolverRunRequest)
    expected_problem_version: int | None = None


def iso_utc(dt: datetime | None) -> str | None:
    """API-generated timestamps: UTC with a `Z` suffix (milliseconds only when non-zero)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
