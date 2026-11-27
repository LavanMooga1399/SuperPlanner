"""Sterilisation load planning contract (M8-DESIGN 8; frozen at S0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from ...esig.model import SignatureInput
from ..model import EntityId, MfgModel, PlanDate

LoadStatus = Literal["planned", "loaded", "cycling", "aerating", "awaiting_release", "released", "failed",
                     "cancelled"]
LOAD_FLOW: dict[str, tuple[str, ...]] = {"planned": ("loaded", "cancelled"), "loaded": ("cycling", "cancelled"),
                                         "cycling": ("aerating", "failed"), "aerating": ("awaiting_release", "failed"),
                                         "awaiting_release": ("released", "failed")}


# ---------------------------------------------------------------- engine (pure)

@dataclass(frozen=True)
class SterCandidate:
    key: str                            # wo:<id> | block:<id>
    item_id: str
    qty: float
    ready: datetime
    cycle_code: str
    pallet_qty: float | None            # pallet qty_base (None -> STER_NO_PALLET)
    aeration_hours: float
    release_mode: str
    release_days: float
    wo_id: str | None = None
    rate_block_id: str | None = None
    lot_id: str | None = None


@dataclass(frozen=True)
class Chamber:
    id: str
    code: str
    pallets: int
    cycle_hours: float
    cycle_codes: frozenset[str] | None = None      # None = any


@dataclass(frozen=True)
class AerationRoom:
    id: str
    code: str
    positions: int


@dataclass
class PlannedMember:
    key: str
    item_id: str
    qty: float
    pallets: int
    wo_id: str | None = None
    rate_block_id: str | None = None
    lot_id: str | None = None


@dataclass
class PlannedLoad:
    chamber_id: str
    cycle_code: str
    start: datetime
    end: datetime
    aeration_end: datetime
    aeration_room_id: str | None
    release_due: date
    members: list[PlannedMember] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def pallets(self) -> int:
        return sum(m.pallets for m in self.members)


@dataclass
class SterPlan:
    loads: list[PlannedLoad]
    skipped: list[dict[str, Any]]       # [{key, item_id, code}]
    warnings: list[dict[str, Any]]      # [{code, load_ix, detail}]
    validator: dict[str, Any]


# ---------------------------------------------------------------- API

class SterPlanInput(MfgModel):
    """POST /ster/plan: re-plan `planned` loads from the published rate run and open WOs."""
    from_date: PlanDate | None = None
    days: Annotated[int, Field(ge=1, le=90)] = 30
    chamber_line_ids: Annotated[list[EntityId], Field(max_length=100)] | None = None


class SterMemberRecord(MfgModel):
    id: str
    wo_id: str | None
    wo_number: str | None = None
    rate_block_id: str | None
    lot_id: str | None
    lot_code: str | None = None
    item_id: str
    part_number: str | None = None
    qty: float
    pallets: float


class SterLoadRecord(MfgModel):
    id: str
    number: str
    run_id: str | None
    chamber_line_id: str
    chamber_code: str | None = None
    cycle_code: str
    status: LoadStatus
    pallets: int
    planned_start: datetime
    planned_end: datetime
    aeration_end: datetime
    release_due: date
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    actual_aeration_end: datetime | None = None
    batch_load_id: str | None
    release_signature_id: str | None
    ncr_id: str | None
    flags: list[str] = Field(default_factory=list)
    members: list[SterMemberRecord] = Field(default_factory=list)
    #: M9 follow-up (M8 15 request): the load's lots - its open sterility holds, else its members' lots
    lots: list[dict[str, Any]] = Field(default_factory=list)
    signatures: list[dict[str, Any]] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class SterPlanResult(MfgModel):
    loads: int
    pallets: int
    skipped: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    load_ids: list[str]


class AdvanceInput(MfgModel):
    to: Literal["cycling", "aerating", "awaiting_release", "cancelled"]
    at: datetime | None = None


class ReleaseInput(MfgModel):
    signature: SignatureInput | None = None
    note: Annotated[str, StringConstraints(max_length=500)] = ""
    #: release before `release_due` (review 6): required then, audited as the change reason
    early_release_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                           max_length=500)] | None = None


class FailInput(MfgModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
