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


# ---------------------------------------------------------------- APS snapshot (M3-DESIGN 6.1)

def latest_live_mrp_run(s: Session) -> Any:
    from .db_models_m2 import MfgMrpRunRow

    return s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.status == "completed", MfgMrpRunRow.kind == "live")
                     .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalars().first()


def mrp_peg_view(s: Session, run: Any, ds: MfgDataset) -> Any:
    """`MrpPegView` of a stored MRP run (item-result details, open planned orders, demand rows)."""
    from ...mfg.aps.pegview import build_peg_view
    from .db_models_m2 import MfgMrpDemandResultRow, MfgMrpItemResultRow, MfgMrpPlannedOrderRow

    plans = [r.detail["plan"] for r in s.execute(select(MfgMrpItemResultRow).where(
        MfgMrpItemResultRow.run_id == run.id)).scalars() if r.detail and "plan" in r.detail]
    planned = [{"planned_no": r.planned_no, "id": r.id, "kind": r.kind, "item_id": r.item_id, "qty": r.qty,
                "need_date": r.need_date, "start_date": r.start_date, "routing_id": r.routing_id, "bom_id": r.bom_id,
                "segment": r.segment, "order_key": r.order_key, "status": r.status}
               for r in s.execute(select(MfgMrpPlannedOrderRow).where(MfgMrpPlannedOrderRow.run_id == run.id))
               .scalars()]
    demand = [{"demand_line_id": r.demand_line_id, "order_id": r.order_id, "order_number": r.order_number,
               "line_no": r.line_no, "item_id": r.item_id, "qty": r.qty, "due_date": r.due_date,
               "priority": r.priority, "program": r.program, "extra": r.extra}
              for r in s.execute(select(MfgMrpDemandResultRow).where(MfgMrpDemandResultRow.run_id == run.id))
              .scalars()]
    return build_peg_view(run.id, run.run_no, run.kind, plans, planned, demand, ds)


def published_view(s: Session) -> Any:
    from ...mfg.aps.model import PublishedView
    from .db_models_m3 import MfgApsOpRow, MfgApsRunRow

    run = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
    if run is None:
        return None
    return PublishedView(run.id, run.run_no, tuple(published_op(r) for r in s.execute(
        select(MfgApsOpRow).where(MfgApsOpRow.run_id == run.id).order_by(MfgApsOpRow.op_no)).scalars()))


def published_op(r: Any) -> Any:
    from datetime import datetime

    from ...mfg.aps.model import PublishedOp

    def dt(v: Any) -> Any:
        return datetime.fromisoformat(v) if isinstance(v, str) else v

    return PublishedOp(r.op_no, r.order_type, r.order_id, r.seq, r.split_index, r.split_count, r.qty, r.line_id,
                       as_utc(r.start_at) if r.start_at else None, as_utc(r.end_at) if r.end_at else None,
                       tuple((c["operator_id"], dt(c["start"]), dt(c["end"])) for c in (r.crew or [])),
                       tuple((dt(p["start"]), dt(p["end"])) for p in (r.pieces or [])), r.setup_minutes,
                       r.run_minutes)


def done_map(s: Session) -> dict[str, set[int]]:
    from .db_models_m3 import MfgWoOpProgressRow

    out: dict[str, set[int]] = {}
    for wo_id, seq in s.execute(select(MfgWoOpProgressRow.wo_id, MfgWoOpProgressRow.seq)
                                .where(MfgWoOpProgressRow.done.is_(True))).all():
        out.setdefault(wo_id, set()).add(seq)
    return out


def load_aps_snapshot(s: Session, as_of: Any, mrp_run: Any, *, published: bool = True, **kw: Any) -> Any:
    """`ApsSnapshot` (6.1); the caller opened a REPEATABLE READ read-only transaction (`repo_m2.snapshot_tx`)."""
    from ...mfg.aps.pure import snapshot_from_dataset
    from . import repo_m2

    ds = repo_m2.load_dataset(s)
    ds.txn = repo_m2.load_txn(s, open_only=True)
    view = mrp_peg_view(s, mrp_run, ds) if mrp_run is not None else None
    pub = published_view(s) if published else None
    return snapshot_from_dataset(ds, as_of, view, pub, done_map(s), **kw)


def aps_inputs_token(s: Session) -> dict[str, Any]:
    """M2 transactions token + the operation progress (count, last change)."""
    from sqlalchemy import func

    from . import repo_m2
    from .db_models_m3 import MfgWoOpProgressRow

    tok = repo_m2.inputs_token(s)
    n, last = s.execute(select(func.count(), func.max(MfgWoOpProgressRow.updated_at))).one()
    tok["progress_n"] = int(n or 0)
    tok["progress_updated"] = as_utc(last).isoformat() if last is not None else None
    return tok
