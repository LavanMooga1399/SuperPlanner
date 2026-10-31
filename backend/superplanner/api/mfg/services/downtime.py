"""Line downtime (M4-DESIGN 3.2, 6.1, 11 #208-210). Opening downtime on a line runs the `line_down` replan rule
(7); APS closes the line from `start_at` to `end_at` / `expected_end_at` (6.1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....mfg.model_m4 import DowntimeInput, DowntimeUpdate
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo
from ..db_models import MfgLineRow
from ..db_models_m4 import MfgDowntimeRow
from .common import audit, check_version, read_tx, touch
from .m2util import actor_id, page, run_tx, user_names

SLACK = timedelta(minutes=2)


def records(s: Session, rows: list[MfgDowntimeRow], triggers: list[dict[str, Any]] | None = None
            ) -> list[dict[str, Any]]:
    if not rows:
        return []
    lines = {ln.id: ln for ln in s.execute(select(MfgLineRow).where(
        MfgLineRow.id.in_({r.line_id for r in rows}))).scalars()}
    names = user_names(s, [x for r in rows for x in (r.reported_by, r.closed_by) if x])
    out = []
    for r in rows:
        ln = lines.get(r.line_id)
        end = as_utc(r.end_at)
        out.append({"id": r.id, "row_version": r.row_version, "created_at": as_utc(r.created_at),
                    "updated_at": as_utc(r.updated_at),
                    "line": {"id": r.line_id, "code": ln.code if ln else "", "name": ln.name if ln else ""},
                    "kind": r.kind, "planned": r.planned, "start_at": as_utc(r.start_at), "end_at": end,
                    "expected_end_at": as_utc(r.expected_end_at), "open": r.end_at is None,
                    "minutes": round((end - as_utc(r.start_at)).total_seconds() / 60.0, 3) if end else None,
                    "reason": r.reason, "note": r.note,
                    "reported_by": {"id": r.reported_by, "code": "", "name": names.get(r.reported_by, "")}
                    if r.reported_by else None,
                    "closed_by": {"id": r.closed_by, "code": "", "name": names.get(r.closed_by, "")}
                    if r.closed_by else None,
                    "triggers": triggers or []})
    return out


def list_downtime(ctx: AppContext, *, line_id: str | None, open_: bool | None, from_: datetime | None,
                  to: datetime | None, limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if line_id:
        conds.append(MfgDowntimeRow.line_id == line_id)
    if open_ is True:
        conds.append(MfgDowntimeRow.end_at.is_(None))
    elif open_ is False:
        conds.append(MfgDowntimeRow.end_at.is_not(None))
    if from_ is not None:
        conds.append(or_(MfgDowntimeRow.end_at.is_(None), MfgDowntimeRow.end_at > from_))
    if to is not None:
        conds.append(MfgDowntimeRow.start_at < to)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgDowntimeRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgDowntimeRow).where(*conds).order_by(
            MfgDowntimeRow.start_at.desc(), MfgDowntimeRow.id).limit(limit).offset(offset)).scalars())
        return page(records(s, rows), total, limit, offset)


def _overlapping(s: Session, line_id: str, start: datetime, end: datetime | None, exclude: str | None = None
                 ) -> MfgDowntimeRow | None:
    q = select(MfgDowntimeRow).where(MfgDowntimeRow.line_id == line_id,
                                     or_(MfgDowntimeRow.end_at.is_(None), MfgDowntimeRow.end_at > start))
    if end is not None:
        q = q.where(MfgDowntimeRow.start_at < end)
    if exclude:
        q = q.where(MfgDowntimeRow.id != exclude)
    return s.execute(q.limit(1)).scalars().first()


def _by_key(s: Session, key: str | None) -> MfgDowntimeRow | None:
    if not key:
        return None
    return s.execute(select(MfgDowntimeRow).where(MfgDowntimeRow.idempotency_key == key)).scalars().first()


def create_downtime(ctx: AppContext, inp: DowntimeInput, idem: str | None = None) -> tuple[dict[str, Any], bool]:
    """POST /downtime -> (record, replayed). A repeated `Idempotency-Key` returns the stored downtime (offline
    replay of the tablets' queue never duplicates it)."""
    from sqlalchemy.exc import IntegrityError

    from ...db.locks import is_unique_violation
    from . import replan

    if idem:
        with read_tx(ctx) as s:
            found = _by_key(s, idem)
            if found is not None:
                return records(s, [found])[0], True

    def fn(s: Session) -> tuple[dict[str, Any], bool]:
        try:
            with s.begin_nested():
                return _create(s, inp, idem)
        except IntegrityError as exc:
            found = _by_key(s, idem) if idem and is_unique_violation(exc, "uq_mfg_downtime_idem") else None
            if found is None:
                raise
            return records(s, [found])[0], None   # type: ignore[return-value]

    rec, raised = run_tx(ctx, fn)
    if raised is None:
        return rec, True
    if raised:
        replan.apply_policy(ctx)
    return rec, False


def _create(s: Session, inp: DowntimeInput, idem: str | None) -> tuple[dict[str, Any], bool]:
    from . import replan

    line = s.get(MfgLineRow, inp.line_id)
    if line is None:
        raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Line {inp.line_id!r} was not found.",
                       {"loc": ["body", "line_id"], "id": inp.line_id})
    now = utcnow()
    start = as_utc(inp.start_at) if inp.start_at is not None else now
    if not inp.planned and start > now + SLACK:
        raise ApiError(422, "FLR_TIME_INVALID", "Unplanned downtime cannot start in the future (plan it as "
                       "maintenance with planned: true).", {"loc": ["body", "start_at"]})
    end = as_utc(inp.end_at) if inp.end_at is not None else None
    if end is not None and end > now + SLACK and not inp.planned:
        raise ApiError(422, "FLR_TIME_INVALID", "end_at cannot be in the future; use expected_end_at.",
                       {"loc": ["body", "end_at"]})
    clash = _overlapping(s, line.id, start, end)
    if clash is not None:
        raise ApiError(409, "FLR_LINE_DOWN", f"{line.code} already has downtime from "
                       f"{as_utc(clash.start_at).isoformat()}.", {"downtime_id": clash.id, "line_id": line.id})
    row = MfgDowntimeRow(id=new_id("dtm_"), line_id=line.id, kind=inp.kind, planned=inp.planned, start_at=start,
                         end_at=end, expected_end_at=as_utc(inp.expected_end_at) if inp.expected_end_at else None,
                         reason=inp.reason, note=inp.note, reported_by=actor_id(),
                         closed_by=actor_id() if end is not None else None, idempotency_key=idem,
                         row_version=1, created_at=now, updated_at=now)
    s.add(row)
    s.flush()
    audit(s, "downtime", row.id, "create", {"line": line.code, "kind": row.kind, "planned": row.planned})
    trig = replan.on_downtime(s, row, now) if end is None or end > now else []
    return records(s, [row], trig)[0], bool(trig)


def update_downtime(ctx: AppContext, downtime_id: str, inp: DowntimeUpdate, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        row = repo.get_row(s, MfgDowntimeRow, downtime_id, what="Downtime", lock=True)
        check_version(row, if_match)
        now = utcnow()
        if inp.close or inp.end_at is not None:
            if row.end_at is not None and inp.end_at is None:
                raise ApiError(409, "MFG_INVALID_STATE", "This downtime is closed already.",
                               {"status": "closed", "action": "close", "allowed_from": ["open"]})
            end = as_utc(inp.end_at) if inp.end_at is not None else now
            if end <= as_utc(row.start_at):
                raise ApiError(422, "FLR_TIME_INVALID", "end_at must be after start_at.", {"loc": ["body", "end_at"]})
            if end > now + SLACK and not row.planned:
                raise ApiError(422, "FLR_TIME_INVALID", "end_at cannot be in the future.", {"loc": ["body", "end_at"]})
            row.end_at, row.closed_by = end, actor_id()
        if inp.expected_end_at is not None:
            if as_utc(inp.expected_end_at) <= as_utc(row.start_at):
                raise ApiError(422, "FLR_TIME_INVALID", "expected_end_at must be after start_at.",
                               {"loc": ["body", "expected_end_at"]})
            row.expected_end_at = as_utc(inp.expected_end_at)
        if inp.kind is not None:
            row.kind = inp.kind
        if inp.reason is not None:
            row.reason = inp.reason
        if inp.note is not None:
            row.note = inp.note
        touch(row, now)
        s.flush()
        audit(s, "downtime", row.id, "update", {"version": row.row_version, "closed": row.end_at is not None})
        return records(s, [row])[0]

    return run_tx(ctx, fn)
