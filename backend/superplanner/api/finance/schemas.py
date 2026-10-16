"""Finance API request models (FINANCE.md 18.1, 18.2). Response shapes are built as dicts by the services."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from superplanner.finance import FinancePlan, FinanceRunRequest, Month, WhatIfChanges

# Same pattern as the scheduling `InstantiateRequest.utc_offset` (api/schemas.py).
UTC_OFFSET_PATTERN = r"^[+-]\d{2}:\d{2}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinanceInstantiateRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_month: Month | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class FinanceExportFile(_Strict):
    format: Literal["superplanner.finance_plan"]
    format_version: Literal[1]
    exported_at: datetime | None = None
    plan: FinancePlan


class WhatIfRequest(_Strict):
    changes: WhatIfChanges
    run: FinanceRunRequest | None = None
    replace_active: bool = False
    expected_plan_version: int | None = None
    base_result_id: str | None = Field(default=None, max_length=64)


class SendToPlannerRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    months: int = Field(default=12, ge=1, le=12)
    utc_offset: str = Field(default="+00:00", pattern=UTC_OFFSET_PATTERN)
    review_every_months: int = Field(default=3, ge=1, le=12)
    include_rebalances: bool = True


def what_if_run_request(run: FinanceRunRequest | None) -> FinanceRunRequest:
    """What-if run defaults (18.2): n_paths 1000, compute_fixes false, calibration_rounds 1; explicit fields win."""
    if run is None:
        run = FinanceRunRequest()
        explicit: set[str] = set()
    else:
        explicit = set(run.model_fields_set)
    data = run.model_dump(mode="json")
    if "compute_fixes" not in explicit:
        data["compute_fixes"] = False
    if "calibration_rounds" not in explicit:
        data["calibration_rounds"] = 1
    if "simulation" not in explicit or "n_paths" not in run.simulation.model_fields_set:
        data["simulation"]["n_paths"] = 1000
    return FinanceRunRequest.model_validate(data)
