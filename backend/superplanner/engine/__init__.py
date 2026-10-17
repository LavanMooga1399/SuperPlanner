"""SuperPlanner engine public API (ARCHITECTURE 7.6). Pure Python: no web or DB imports."""

from __future__ import annotations

from .. import __version__
from .compiled import CompileError, CompiledProblem, compile_problem
from .explain import DurationRisk, ScheduleExplanation, StartReason, TaskExplanation
from .explain import explain as _explain
from .graph import CpmResult, CpmTask
from .model import (BlockedInterval, Calendar, Dependency, DurationEstimate, Lock, Objectives, Placement, Problem,
                    Requirement, Resource, Task, Terminology, Weights, pert_minutes)
from .objectives import PRESET_WEIGHTS, ObjectiveRefs, ObjectiveValues
from .pipeline import OptimizeOutcome, OptimizeRequest, PhaseSummary
from .pipeline import optimize as _optimize
from .preflight import PROVEN_INFEASIBLE_CODES, Issue, PreflightReport, ValidateReport
from .preflight import analyze as _analyze
from .preflight import preflight as _preflight
from .selector import Selection
from .solvers.base import (Alternative, CpSatParams, GaParams, ProgressCallback, ProgressEvent, SolveResult,
                           SolverConfig)
from .validator import Metrics, ValidationReport, Violation
from .validator import validate as _validate

import threading


def preflight(problem: Problem) -> PreflightReport:
    return _preflight(problem)


def analyze(problem: Problem) -> ValidateReport:
    return _analyze(problem)


def optimize(problem: Problem, request: OptimizeRequest | None = None, progress_cb: ProgressCallback | None = None,
             cancel_event: threading.Event | None = None) -> OptimizeOutcome:
    return _optimize(problem, request or OptimizeRequest(), progress_cb, cancel_event)


def validate_schedule(problem: Problem, placements: list[Placement]) -> ValidationReport:
    return _validate(compile_problem(problem), placements)


def explain_schedule(problem: Problem, placements: list[Placement]) -> ScheduleExplanation:
    return _explain(compile_problem(problem), placements)


__all__ = [
    "__version__", "preflight", "analyze", "optimize", "validate_schedule", "explain_schedule", "CompileError",
    "CompiledProblem", "Problem", "Task", "Resource", "Requirement", "Dependency", "Lock", "Calendar",
    "BlockedInterval", "Terminology", "Objectives", "Weights", "Placement", "PRESET_WEIGHTS", "ObjectiveRefs",
    "ObjectiveValues", "OptimizeRequest", "OptimizeOutcome", "PhaseSummary", "Selection", "Issue",
    "PreflightReport", "ValidateReport", "CpmResult", "CpmTask", "PROVEN_INFEASIBLE_CODES", "Alternative",
    "CpSatParams", "GaParams", "ProgressCallback", "ProgressEvent", "SolveResult", "SolverConfig", "Metrics",
    "ValidationReport", "Violation", "ScheduleExplanation", "StartReason", "TaskExplanation",
    "DurationEstimate", "DurationRisk", "pert_minutes",
]
