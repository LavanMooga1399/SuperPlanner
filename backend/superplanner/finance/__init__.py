"""SuperPlanner Finance engine public API (FINANCE.md 2.1). Pure Python: no web or DB imports."""

from __future__ import annotations

import threading
from typing import Callable

from . import model as _model
from .bridge import to_planner_problem as _to_planner_problem
from .cashflow import project_cashflow as _project_cashflow
from .cashflow import summarize_cashflow as _summarize_cashflow
from .compare import compare_results as _compare_results
from .defaults import DISCLAIMER, DISCLAIMER_VERSION, FINANCE_ENGINE_VERSION
from .defaults import default_assumptions as _default_assumptions
from .export import contributions_csv as _contributions_csv
from .model import *  # noqa: F401,F403
from .model import (Assumptions, CashflowProjection, CashflowSummary, FinanceCancelled, FinanceComparison,
                    FinancePlan, FinancePreflightError, FinancePreflightReport, FinanceProgress, FinanceResult,
                    FinanceRunRequest, FinanceViolation, WhatIfChanges)
from .pipeline import run_plan as _run_plan
from .preflight import preflight as _preflight
from .templates import TEMPLATES, FinanceTemplate
from .templates import get_template as _get_template
from .validator import validate_result as _validate_result
from .whatif import apply_what_if as _apply_what_if

__version__ = FINANCE_ENGINE_VERSION


def default_plan(*, name: str = "My financial plan", start_month: str) -> FinancePlan:
    return FinancePlan(name=name, start_month=start_month)


def default_assumptions() -> Assumptions:
    return _default_assumptions()


def preflight(plan: FinancePlan) -> FinancePreflightReport:
    return _preflight(plan)


def project_cashflow(plan: FinancePlan) -> CashflowProjection:
    return _project_cashflow(plan)


def summarize_cashflow(proj: CashflowProjection) -> CashflowSummary:
    return _summarize_cashflow(proj)


def run_plan(plan: FinancePlan, request: FinanceRunRequest | None = None,
             progress_cb: Callable[[FinanceProgress], None] | None = None,
             cancel_event: threading.Event | None = None) -> FinanceResult:
    return _run_plan(plan, request or FinanceRunRequest(), progress_cb, cancel_event)


def validate_result(plan: FinancePlan, result: FinanceResult) -> list[FinanceViolation]:
    return _validate_result(plan, result)


def apply_what_if(plan: FinancePlan, changes: WhatIfChanges) -> FinancePlan:
    return _apply_what_if(plan, changes)


def compare_results(a: FinanceResult, b: FinanceResult, **kwargs) -> FinanceComparison:
    return _compare_results(a, b, **kwargs)


def contributions_csv(plan: FinancePlan, result: FinanceResult) -> str:
    return _contributions_csv(plan, result)


def to_planner_problem(plan: FinancePlan, result: FinanceResult, *, name: str, months: int = 12,
                       utc_offset: str = "+00:00", review_every_months: int = 3, include_rebalances: bool = True):
    return _to_planner_problem(plan, result, name=name, months=months, utc_offset=utc_offset,
                               review_every_months=review_every_months, include_rebalances=include_rebalances)


def get_template(template_id: str) -> FinanceTemplate:
    return _get_template(template_id)


__all__ = [
    "__version__", "default_plan", "default_assumptions", "preflight", "project_cashflow", "summarize_cashflow",
    "run_plan", "validate_result", "apply_what_if", "compare_results", "contributions_csv", "to_planner_problem",
    "TEMPLATES", "get_template", "DISCLAIMER", "DISCLAIMER_VERSION", "FinancePreflightError", "FinanceCancelled",
    "FinanceTemplate", *_model.__all__,
]
__all__ = list(dict.fromkeys(__all__))
