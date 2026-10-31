"""M3 master data and WO operation progress (M3-DESIGN 3, 11 #164-178).

Operation line rates, setup matrix rows and operator absences are master data (plant lock, `data_version`, audit);
WO operation progress is transactional (If-Match on the WO, the WO's `row_version` is bumped).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from ....mfg.model import Ref
from ....mfg.model_m3 import (OperationLineRateInput, OperationLineRateRecord, OperatorAbsenceInput,
                              OperatorAbsenceRecord, SetupMatrixRowInput, SetupMatrixRowRecord)
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo
from ..db_models import MfgGroupRow, MfgLineRow, MfgOperationRow, MfgOperatorRow, MfgRoutingRow
from ..db_models_m3 import (MfgOperationLineRateRow, MfgOperatorAbsenceRow,
                            MfgSetupMatrixRow)
from .common import audit, check_version, ensure_unique, read_tx, touch, unknown_ref, write_tx

MAX_LINE_RATES = 20_000
MAX_SETUP_ROWS = 5_000
MAX_ABSENCES = 20_000


def _ref(row: Any) -> Ref | None:
    return None if row is None else Ref.model_construct(id=row.id, code=row.code, name=row.name)


def _stamp(row: Any) -> dict[str, Any]:
    return {"id": row.id, "row_version": row.row_version, "created_at": as_utc(row.created_at),
            "updated_at": as_utc(row.updated_at)}


def _limit(s: Any, model: Any, n: int, what: str) -> None:
    from .common import check_limit

    check_limit(s, model, n, what)


# ---------------------------------------------------------------- operation line rates (164-167)

def rate_records(s: Any, rows: list[MfgOperationLineRateRow]) -> list[OperationLineRateRecord]:
    if not rows:
        return []
    lines = {r.id: r for r in s.execute(select(MfgLineRow).where(MfgLineRow.id.in_({x.line_id for x in rows})))
             .scalars()}
    ops = {r.id: r for r in s.execute(select(MfgOperationRow).where(
        MfgOperationRow.id.in_({x.operation_id for x in rows}))).scalars()}
    rtgs = {r.id: r for r in s.execute(select(MfgRoutingRow.id, MfgRoutingRow.item_id).where(
        MfgRoutingRow.id.in_({o.routing_id for o in ops.values()}))).all()} if ops else {}
    out = []
    for r in rows:
        op = ops.get(r.operation_id)
        rt = rtgs.get(op.routing_id) if op else None
        out.append(OperationLineRateRecord.model_construct(
            **_stamp(r), operation_id=r.operation_id, line_id=r.line_id, setup_minutes=r.setup_minutes,
            run_minutes=r.run_minutes, note=r.note, line=_ref(lines.get(r.line_id)),
            routing_id=op.routing_id if op else None, item_id=rt[1] if rt else None, seq=op.seq if op else None))
    return out


def list_rates(ctx: AppContext, operation_id: str | None, line_id: str | None, routing_id: str | None
               ) -> dict[str, Any]:
    conds = []
    if operation_id:
        conds.append(MfgOperationLineRateRow.operation_id == operation_id)
    if line_id:
        conds.append(MfgOperationLineRateRow.line_id == line_id)
    if routing_id:
        conds.append(MfgOperationLineRateRow.operation_id.in_(
            select(MfgOperationRow.id).where(MfgOperationRow.routing_id == routing_id)))
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgOperationLineRateRow).where(*conds)
                              .order_by(MfgOperationLineRateRow.operation_id, MfgOperationLineRateRow.line_id))
                    .scalars())
        return {"items": rate_records(s, rows)}


def _check_rate(s: Any, inp: OperationLineRateInput) -> None:
    op = s.execute(select(MfgOperationRow).where(MfgOperationRow.id == inp.operation_id)).scalars().first()
    if op is None:
        raise unknown_ref(["body", "operation_id"], inp.operation_id, "Operation")
    line = s.execute(select(MfgLineRow).where(MfgLineRow.id == inp.line_id)).scalars().first()
    if line is None:
        raise unknown_ref(["body", "line_id"], inp.line_id, "Line")
    if line.group_id != op.group_id:
        grp = s.execute(select(MfgGroupRow.code).where(MfgGroupRow.id == op.group_id)).scalar() or op.group_id
        raise ApiError(422, "MFG_LINE_NOT_IN_GROUP", f"Line {line.code} is not in the operation's group {grp}.",
                       {"loc": ["body", "line_id"], "line_id": line.id, "group_id": op.group_id})


def create_rate(ctx: AppContext, inp: OperationLineRateInput) -> OperationLineRateRecord:
    with write_tx(ctx) as (s, _plant):
        _check_rate(s, inp)
        ensure_unique(s, MfgOperationLineRateRow, "A line rate",
                      {"operation_id": inp.operation_id, "line_id": inp.line_id})
        _limit(s, MfgOperationLineRateRow, MAX_LINE_RATES, "line rates")
        now = utcnow()
        row = MfgOperationLineRateRow(id=new_id("olr_"), row_version=1, created_at=now, updated_at=now,
                                      **inp.model_dump())
        s.add(row)
        s.flush()
        audit(s, "operation_line_rate", row.id, "create", {"version": 1})
        return rate_records(s, [row])[0]


def update_rate(ctx: AppContext, rate_id: str, inp: OperationLineRateInput, if_match: str | None
                ) -> OperationLineRateRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgOperationLineRateRow, rate_id, what="Line rate", lock=True)
        check_version(row, if_match)
        _check_rate(s, inp)
        ensure_unique(s, MfgOperationLineRateRow, "A line rate",
                      {"operation_id": inp.operation_id, "line_id": inp.line_id}, exclude_id=row.id)
        for k, v in inp.model_dump().items():
            setattr(row, k, v)
        touch(row)
        s.flush()
        audit(s, "operation_line_rate", row.id, "update", {"version": row.row_version})
        return rate_records(s, [row])[0]


def delete_rate(ctx: AppContext, rate_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgOperationLineRateRow, rate_id, what="Line rate", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "operation_line_rate", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- setup matrix (168-171)

def matrix_records(s: Any, rows: list[MfgSetupMatrixRow]) -> list[SetupMatrixRowRecord]:
    fams: dict[str, int] = {}
    for f, in s.execute(select(MfgLineRow.setup_family).where(MfgLineRow.setup_family.is_not(None))).all():
        fams[f] = fams.get(f, 0) + 1
    return [SetupMatrixRowRecord.model_construct(
        **_stamp(r), line_setup_family=r.line_setup_family, from_family=r.from_family, to_family=r.to_family,
        setup_minutes=r.setup_minutes, line_count=fams.get(r.line_setup_family, 0)) for r in rows]


def list_matrix(ctx: AppContext, line_setup_family: str | None) -> dict[str, Any]:
    conds = [MfgSetupMatrixRow.line_setup_family == line_setup_family] if line_setup_family else []
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgSetupMatrixRow).where(*conds).order_by(
            MfgSetupMatrixRow.line_setup_family, MfgSetupMatrixRow.from_family, MfgSetupMatrixRow.to_family))
            .scalars())
        return {"items": matrix_records(s, rows)}


def _matrix_key(inp: SetupMatrixRowInput) -> dict[str, Any]:
    return {"line_setup_family": inp.line_setup_family, "from_family": inp.from_family, "to_family": inp.to_family}


def create_matrix_row(ctx: AppContext, inp: SetupMatrixRowInput) -> SetupMatrixRowRecord:
    with write_tx(ctx) as (s, _plant):
        ensure_unique(s, MfgSetupMatrixRow, "A setup matrix row", _matrix_key(inp))
        _limit(s, MfgSetupMatrixRow, MAX_SETUP_ROWS, "setup matrix rows")
        now = utcnow()
        row = MfgSetupMatrixRow(id=new_id("stm_"), row_version=1, created_at=now, updated_at=now, **inp.model_dump())
        s.add(row)
        s.flush()
        audit(s, "setup_matrix_row", row.id, "create", {"version": 1, **_matrix_key(inp)})
        return matrix_records(s, [row])[0]


def update_matrix_row(ctx: AppContext, row_id: str, inp: SetupMatrixRowInput, if_match: str | None
                      ) -> SetupMatrixRowRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgSetupMatrixRow, row_id, what="Setup matrix row", lock=True)
        check_version(row, if_match)
        ensure_unique(s, MfgSetupMatrixRow, "A setup matrix row", _matrix_key(inp), exclude_id=row.id)
        for k, v in inp.model_dump().items():
            setattr(row, k, v)
        touch(row)
        s.flush()
        audit(s, "setup_matrix_row", row.id, "update", {"version": row.row_version})
        return matrix_records(s, [row])[0]


def delete_matrix_row(ctx: AppContext, row_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgSetupMatrixRow, row_id, what="Setup matrix row", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "setup_matrix_row", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- operator absences (172-175)

def absence_records(s: Any, rows: list[MfgOperatorAbsenceRow]) -> list[OperatorAbsenceRecord]:
    if not rows:
        return []
    ops = {r.id: r for r in s.execute(select(MfgOperatorRow).where(
        MfgOperatorRow.id.in_({x.operator_id for x in rows}))).scalars()}
    return [OperatorAbsenceRecord.model_construct(
        **_stamp(r), operator_id=r.operator_id, start=as_utc(r.start_at), end=as_utc(r.end_at), kind=r.kind,
        note=r.note, operator=_ref(ops.get(r.operator_id))) for r in rows]


def list_absences(ctx: AppContext, operator_id: str | None, frm: datetime | None, to: datetime | None
                  ) -> dict[str, Any]:
    conds = []
    if operator_id:
        conds.append(MfgOperatorAbsenceRow.operator_id == operator_id)
    if frm is not None:
        conds.append(MfgOperatorAbsenceRow.end_at > frm)
    if to is not None:
        conds.append(MfgOperatorAbsenceRow.start_at < to)
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgOperatorAbsenceRow).where(*conds).order_by(
            MfgOperatorAbsenceRow.operator_id, MfgOperatorAbsenceRow.start_at, MfgOperatorAbsenceRow.id)).scalars())
        return {"items": absence_records(s, rows)}


def _absence_values(s: Any, inp: OperatorAbsenceInput) -> dict[str, Any]:
    if s.execute(select(MfgOperatorRow.id).where(MfgOperatorRow.id == inp.operator_id)).first() is None:
        raise unknown_ref(["body", "operator_id"], inp.operator_id, "Operator")
    return {"operator_id": inp.operator_id, "start_at": inp.start, "end_at": inp.end, "kind": inp.kind,
            "note": inp.note}


def create_absence(ctx: AppContext, inp: OperatorAbsenceInput) -> OperatorAbsenceRecord:
    with write_tx(ctx) as (s, _plant):
        vals = _absence_values(s, inp)
        _limit(s, MfgOperatorAbsenceRow, MAX_ABSENCES, "operator absences")
        now = utcnow()
        row = MfgOperatorAbsenceRow(id=new_id("oab_"), row_version=1, created_at=now, updated_at=now, **vals)
        s.add(row)
        s.flush()
        audit(s, "operator_absence", row.id, "create", {"version": 1, "operator_id": inp.operator_id})
        return absence_records(s, [row])[0]


def update_absence(ctx: AppContext, absence_id: str, inp: OperatorAbsenceInput, if_match: str | None
                   ) -> OperatorAbsenceRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgOperatorAbsenceRow, absence_id, what="Operator absence", lock=True)
        check_version(row, if_match)
        for k, v in _absence_values(s, inp).items():
            setattr(row, k, v)
        touch(row)
        s.flush()
        audit(s, "operator_absence", row.id, "update", {"version": row.row_version})
        return absence_records(s, [row])[0]


def delete_absence(ctx: AppContext, absence_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgOperatorAbsenceRow, absence_id, what="Operator absence", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "operator_absence", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- WO operations (176-178): M4 event-backed

def wo_operations(ctx: AppContext, wo_id: str) -> dict[str, Any]:
    """M3 #176 extended (M4-DESIGN 11 #206): the WO's operation records (`services.floor`)."""
    from . import floor

    return floor.wo_operations(ctx, wo_id)


def set_done(ctx: AppContext, wo_id: str, seq_s: str | int, done: bool, if_match: str | None) -> dict[str, Any]:
    """M3 #177/#178 as supervisor shortcuts mapped to floor events (M4-DESIGN 11)."""
    from . import floor

    return floor.set_done(ctx, wo_id, seq_s, done, if_match)
