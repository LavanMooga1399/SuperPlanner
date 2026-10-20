"""Solver protocol, configuration and result models (ARCHITECTURE section 7)."""

from __future__ import annotations

import threading
from typing import Any, Callable, ClassVar, Literal, Protocol

from pydantic import BaseModel, Field

from ..compiled import CompiledProblem
from ..model import Placement, Weights
from ..objectives import ObjectiveRefs, ObjectiveValues
from ..validator import Metrics, Violation

__all__ = [
    "Alternative", "CpSatParams", "GaParams", "Metrics", "ObjectiveRefs", "ObjectiveValues", "Placement",
    "ProgressCallback", "ProgressEvent", "SolveResult", "Solver", "SolverCapabilities", "SolverConfig",
    "SolverError", "Violation", "ALL_RULES",
]

ALL_RULES: tuple[str, ...] = ("edf", "slack", "spt", "lpt", "priority")


class SolverError(RuntimeError):
    """Programming error inside a solver (e.g. CP-SAT MODEL_INVALID)."""


class SolverCapabilities(BaseModel):
    alternative_resources: bool
    calendars: bool
    multi_objective: bool
    proves_optimality: bool
    proves_infeasibility: bool
    uses_hint: bool
    deterministic_with_seed: bool


class GaParams(BaseModel):
    population_size: int | None = Field(default=None, ge=10, le=300)
    max_generations: int = Field(default=300, ge=1, le=10000)
    stagnation_generations: int = Field(default=40, ge=5, le=1000)
    crossover_rate: float = Field(default=0.9, ge=0, le=1)
    mutation_rate: float = Field(default=0.1, ge=0.01, le=0.5)
    mutation_sigma: float = Field(default=0.1, ge=0.01, le=0.5)
    swap_rate: float = Field(default=0.2, ge=0, le=1)
    elite_count: int = Field(default=2, ge=0, le=10)
    tournament_size: int = Field(default=3, ge=2, le=10)
    archive_size: int = Field(default=10, ge=1, le=50)


class CpSatParams(BaseModel):
    num_workers: int = Field(default=8, ge=1, le=64)
    relative_gap: float = Field(default=0.0, ge=0, le=1)


class SolverConfig(BaseModel):
    time_limit_seconds: float = Field(default=10.0, ge=0.5, le=300)
    seed: int = 0
    weights: Weights = Field(default_factory=Weights)
    refs: ObjectiveRefs | None = None
    initial_solution: list[Placement] | None = None
    heuristic_rules: list[str] = Field(default_factory=lambda: list(ALL_RULES))
    cpsat: CpSatParams = Field(default_factory=CpSatParams)
    ga: GaParams = Field(default_factory=GaParams)
    max_alternatives: int = Field(default=2, ge=0, le=5)


class Alternative(BaseModel):
    label: str
    solver: str
    objectives: ObjectiveValues
    placements: list[Placement]


class SolveResult(BaseModel):
    solver: str
    status: Literal["completed", "cancelled", "failed"]
    feasibility: Literal["feasible", "infeasible", "unknown"]
    termination_reason: Literal["optimal", "proven_infeasible", "time_limit", "generation_limit", "stagnation",
                                "completed", "cancelled", "preflight_failed", "no_solution", "error"]
    optimality_proven: bool
    objectives: ObjectiveValues | None
    placements: list[Placement]
    violations: list[Violation] = Field(default_factory=list)
    metrics: Metrics | None = None
    iterations: int = 0
    elapsed_seconds: float = 0.0
    best_bound: float | None = None
    alternatives: list[Alternative] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ProgressEvent(BaseModel):
    type: Literal["phase_started", "progress", "phase_completed"]
    solver: str
    elapsed_seconds: float
    iteration: int | None = None
    best_score: float | None = None
    best_objectives: ObjectiveValues | None = None
    feasible_found: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]


class Solver(Protocol):
    name: ClassVar[str]
    capabilities: ClassVar[SolverCapabilities]

    def solve(self, problem: CompiledProblem, config: SolverConfig, progress_cb: ProgressCallback | None = None,
              cancel_event: threading.Event | None = None) -> SolveResult: ...
