"""Inventory optimisation contract (M8-DESIGN 5; frozen at S0): SS run params, lines, decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from ..model import EntityId, MfgModel
from ..model_m8 import Reason

Decision = Literal["pending", "approved", "rejected"]


class SsParams(MfgModel):
    """POST /invopt/runs."""
    label: Annotated[str, StringConstraints(max_length=100)] = ""
    forecast_version_id: EntityId | None = None     # None = active version
    item_ids: Annotated[list[EntityId], Field(max_length=20_000)] | None = None


class SsRunRecord(MfgModel):
    id: str
    number: str
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed"]
    forecast_version_id: str | None
    summary: dict[str, Any]          # {lines, pending, delta_value, matrix: {AX: {count, value}}, capped}
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None


class SsLineRecord(MfgModel):
    id: str
    run_id: str
    item_id: str
    part_number: str | None = None
    abc: Literal["A", "B", "C"]
    xyz: Literal["X", "Y", "Z"]
    service_level: float
    z: float
    d_day: float
    sigma_d_day: float
    lt_days: float
    sigma_lt_days: float
    current_ss: float
    proposed_ss: float
    delta_value: float
    cover_days: float | None
    flags: list[str]
    decision: Decision
    decided_by: str | None
    decided_at: datetime | None


class DecideInput(MfgModel):
    line_ids: Annotated[list[EntityId], Field(min_length=1, max_length=20_000)]
    decision: Literal["approved", "rejected"]
    reason: Reason


class DecideResult(MfgModel):
    decided: int
    skipped: int
    items_updated: int
