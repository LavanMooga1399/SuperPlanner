"""M3 repository (M3-DESIGN 2, 10): M3 master rows -> records, `load_master_m3` (3 statements), the APS snapshot
loader (`load_aps_snapshot`, one REPEATABLE READ transaction) and the staleness token.

Every query is an ORM query (the central ownership filter applies)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...mfg.dataset import MfgDataset
from ...mfg.model_m3 import OperationLineRateRecord, OperatorAbsenceRecord, SetupMatrixRowRecord
from ..schemas import as_utc
from .db_models_m3 import MfgOperationLineRateRow, MfgOperatorAbsenceRow, MfgSetupMatrixRow


def _stamp(r: Any) -> dict[str, Any]:
    return {"id": r.id, "row_version": r.row_version, "created_at": as_utc(r.created_at),
            "updated_at": as_utc(r.updated_at)}


def rate_record(r: MfgOperationLineRateRow) -> OperationLineRateRecord:
    return OperationLineRateRecord.model_construct(**_stamp(r), operation_id=r.operation_id, line_id=r.line_id,
                                                   setup_minutes=r.setup_minutes, run_minutes=r.run_minutes,
                                                   note=r.note, line=None, routing_id=None, item_id=None, seq=None)


def matrix_record(r: MfgSetupMatrixRow) -> SetupMatrixRowRecord:
    return SetupMatrixRowRecord.model_construct(**_stamp(r), line_setup_family=r.line_setup_family,
                                                from_family=r.from_family, to_family=r.to_family,
                                                setup_minutes=r.setup_minutes, line_count=0)


def absence_record(r: MfgOperatorAbsenceRow) -> OperatorAbsenceRecord:
    return OperatorAbsenceRecord.model_construct(**_stamp(r), operator_id=r.operator_id, start=as_utc(r.start_at),
                                                 end=as_utc(r.end_at), kind=r.kind, note=r.note, operator=None)


def load_master_m3(s: Session, ds: MfgDataset) -> None:
    """Line rates, setup matrix, operator absences into `ds` (3 statements; `dataset.link` fills refs)."""
    ops = {op.id: (r, op) for r in ds.routings.values() for op in r.operations}
    for row in s.execute(select(MfgOperationLineRateRow)).scalars():
        rec = rate_record(row)
        ro = ops.get(row.operation_id)
        if ro is not None:
            rec.routing_id, rec.item_id, rec.seq = ro[0].id, ro[0].item_id, ro[1].seq
        ds.operation_line_rates[row.id] = rec
    for row in s.execute(select(MfgSetupMatrixRow)).scalars():
        ds.setup_matrix[row.id] = matrix_record(row)
    for row in s.execute(select(MfgOperatorAbsenceRow)).scalars():
        ds.operator_absences[row.id] = absence_record(row)
