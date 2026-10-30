"""M3 master and transactional additions (M3-DESIGN 3; contract frozen at S0): operation line rates, setup matrix,
operator absences, WO operation progress. Conventions as `mfg.model` / `mfg.model_m2`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .model import Code, EntityId, MfgModel, Minutes, PlanDateTime, Ref, Text500, _Stamped

#: `from_family` / `to_family` of a setup-matrix row: a family code or the wildcard "*"
FamilyOrAny = Annotated[str, StringConstraints(strip_whitespace=True,
                                               pattern=r"^(\*|[A-Za-z0-9][A-Za-z0-9_.\-/]{0,31})$")]
AbsenceKind = Literal["leave", "training", "sick", "other"]
ABSENCE_KINDS: tuple[str, ...] = ("leave", "training", "sick", "other")
MAX_ABSENCE_DAYS = 366


# ---------------------------------------------------------------- operation line rates (3.2)

class OperationLineRateInput(MfgModel):
    """A line's own times for one routing operation. `None` = use the operation's value. An overriding
    `run_minutes` is that line's rate: the line `speed_factor` is not applied to it (4)."""
    operation_id: EntityId
    line_id: EntityId
    setup_minutes: Minutes | None = None
    run_minutes: Minutes | None = None
    note: Text500 = ""


class OperationLineRateRecord(OperationLineRateInput, _Stamped):
    line: Ref | None = None
    routing_id: str | None = None
    item_id: str | None = None
    seq: int | None = None


# ---------------------------------------------------------------- setup matrix (3.2)

class SetupMatrixRowInput(MfgModel):
    """Changeover minutes on lines whose `setup_family` is `line_setup_family`, from the previous item's family to
    the next one's. Most specific row wins: (from,to) > (from,*) > (*,to) > (*,*)."""
    line_setup_family: Code
    from_family: FamilyOrAny = "*"
    to_family: FamilyOrAny = "*"
    setup_minutes: Minutes


class SetupMatrixRowRecord(SetupMatrixRowInput, _Stamped):
    line_count: int = 0


# ---------------------------------------------------------------- operator absences (3.2)

class OperatorAbsenceInput(MfgModel):
    operator_id: EntityId
    start: PlanDateTime
    end: PlanDateTime
    kind: AbsenceKind = "leave"
    note: Text500 = ""

    @model_validator(mode="after")
    def _span(self) -> "OperatorAbsenceInput":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > timedelta(days=MAX_ABSENCE_DAYS):
            raise ValueError(f"an absence is at most {MAX_ABSENCE_DAYS} days")
        return self


class OperatorAbsenceRecord(OperatorAbsenceInput, _Stamped):
    operator: Ref | None = None


# ---------------------------------------------------------------- WO operation progress (3.3)

class WoOpProgressRecord(MfgModel):
    wo_id: str
    seq: int
    done: bool
    done_at: datetime | None = None
    done_by: str | None = None


class WoOperationRow(MfgModel):
    """`GET /work-orders/{id}/operations`: the operations derived from the WO's routing (M2 3.7) with progress and
    the published schedule placement (None when not scheduled / nothing published)."""
    seq: int
    name: str
    group: Ref
    setup_minutes: float
    run_minutes: float
    labor: str
    done: bool
    done_at: datetime | None = None
    done_by: Ref | None = None
    placement: list[dict] = Field(default_factory=list)   # [{run_id, op_no, line: {id, code}, start, end, split}]


def _register_inputs() -> None:
    from .model import INPUT_OF

    INPUT_OF.update({OperationLineRateRecord: OperationLineRateInput, SetupMatrixRowRecord: SetupMatrixRowInput,
                     OperatorAbsenceRecord: OperatorAbsenceInput})


_register_inputs()

__all__ = ["ABSENCE_KINDS", "AbsenceKind", "FamilyOrAny", "OperationLineRateInput", "OperationLineRateRecord",
           "OperatorAbsenceInput", "OperatorAbsenceRecord", "SetupMatrixRowInput", "SetupMatrixRowRecord",
           "WoOpProgressRecord", "WoOperationRow"]
