"""Equipment and calibration (M7-DESIGN 8)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa import equipment as EQ
from ....qa.equipment import valid
from ....qa.model import CalibrationInput, EquipmentInput, EquipmentStatusInput
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models_m7 import QaCalibrationRow, QaEquipmentRow
from . import m7_examples
from .common import check_version, ilike, read_tx, touch, unknown_ref, write_tx


def _plant_date(s: Session, at: datetime) -> date:
    from ....mfg.tz import plant_tz
    from .m2util import plant

    return at.astimezone(plant_tz(plant(s))).date()


def check_line(s: Session, line_id: str, at: datetime) -> None:
    """Floor `setup_start` / `start` on a line with linked equipment that is not valid: 409, no override (8)."""
    rows = list(s.execute(select(QaEquipmentRow).where(QaEquipmentRow.line_id == line_id,
                                                       QaEquipmentRow.status != "retired")).scalars())
    if not rows:
        return
    d = _plant_date(s, at)
    bad = [e for e in rows if not valid(e, d)]
    if bad:
        raise ApiError(409, "QA_LINE_EQUIPMENT_INVALID", f"{bad[0].code} on this line is not valid "
                       f"({'calibration overdue' if bad[0].status == 'active' else bad[0].status}); calibrate it or "
                       "remove it from the line.", {"equipment": [
                           {"id": e.id, "code": e.code, "status": e.status,
                            "due_on": e.due_on.isoformat() if e.due_on else None} for e in bad]})


# ---------------------------------------------------------------- records, content

def _today(s: Session) -> date:
    from .m2util import today

    return today(s)


def eq_content(r: QaEquipmentRow) -> dict[str, Any]:
    return {"id": r.id, "code": r.code, "name": r.name, "kind": r.kind, "equipment_class": r.equipment_class,
            "line_id": r.line_id, "tool_pool_id": r.tool_pool_id, "serial_no": r.serial_no, "status": r.status,
            "calibration_required": r.calibration_required, "interval_days": r.interval_days,
            "grace_days": r.grace_days, "last_calibrated_on": r.last_calibrated_on, "due_on": r.due_on,
            "procedure_ref": r.procedure_ref}


def _eq_loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaEquipmentRow, rid, what="Equipment", lock=lock)
    return C.Loaded(r, eq_content(r), r.row_version, None,
                    [("Equipment", f"{r.code} - {r.name}"), ("Status", r.status),
                     ("Due", r.due_on.isoformat() if r.due_on else "-")])


C.register("equipment", _eq_loader)
#: calibration.record signs the equipment's current state (preview); the stored snapshot is the calibration
C.register("calibration", _eq_loader)


def record(s: Session, r: QaEquipmentRow, full: bool = False) -> dict[str, Any]:
    from .qa_common import decorate, settings_of

    d = _today(s)
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           **{k: getattr(r, k) for k in ("code", "name", "kind", "equipment_class", "line_id", "tool_pool_id",
                                        "serial_no", "manufacturer", "location", "status", "calibration_required",
                                        "interval_days", "grace_days", "last_calibrated_on", "due_on", "failed_on",
                                        "procedure_ref", "provider", "note")},
           "valid": valid(r, d), "due_state": EQ.due_state(r, d, settings_of(s).cal_due_warning_days),
           "signatures": [], "links": [], "attachments": []}
    if full:
        decorate(s, rec, "equipment", "equipment")
    return rec


def cal_record(s: Session, c: QaCalibrationRow, full: bool = False) -> dict[str, Any]:
    rec = {"id": c.id, "row_version": c.row_version, "created_at": c.created_at, "updated_at": c.updated_at,
           "equipment_id": c.equipment_id, "performed_on": c.performed_on, "performed_by": c.performed_by,
           "provider_name": c.provider_name, "result": c.result, "as_found": c.as_found, "as_left": c.as_left,
           "certificate_ref": c.certificate_ref, "next_due_on": c.next_due_on, "signatures": [], "links": [],
           "attachments": []}
    if full:
        from . import esig
        from .qa_common import attachments_of

        rec["signatures"] = esig.manifests(s, "calibration", c.id, current_hash=esig.C.content_hash(
            calibration_content(s, c.id)[0]))
        rec["attachments"] = attachments_of(s, "calibration", c.id)
        from .qa_common import with_people

        with_people(s, rec)
    return rec


def calibration_content(s: Session, cal_id: str) -> tuple[dict[str, Any], int]:
    c = repo.get_row(s, QaCalibrationRow, cal_id, what="Calibration")
    e = s.get(QaEquipmentRow, c.equipment_id)
    return C.plain({"id": c.id, "equipment_id": c.equipment_id, "equipment_code": e.code if e else None,
                    "performed_on": c.performed_on, "performed_by": c.performed_by,
                    "provider_name": c.provider_name, "result": c.result, "as_found": c.as_found,
                    "as_left": c.as_left, "certificate_ref": c.certificate_ref,
                    "next_due_on": c.next_due_on}), c.row_version


# ---------------------------------------------------------------- CRUD (Q53-Q56)

SORTS = {"code": QaEquipmentRow.code, "due_on": QaEquipmentRow.due_on, "name": QaEquipmentRow.name}


def list_equipment(ctx: AppContext, q: str | None, status: str | None, equipment_class: str | None,
                   line_id: str | None, due_within_days: int | None, sort: str | None, limit: int, offset: int
                   ) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(or_(ilike(QaEquipmentRow.code, q), ilike(QaEquipmentRow.name, q)))
    if status:
        conds.append(QaEquipmentRow.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    if equipment_class:
        conds.append(QaEquipmentRow.equipment_class == equipment_class)
    if line_id:
        conds.append(QaEquipmentRow.line_id == line_id)
    key = (sort or "code").lstrip("-")
    col = SORTS.get(key, QaEquipmentRow.code)
    with read_tx(ctx) as s:
        if due_within_days is not None:
            conds += [QaEquipmentRow.calibration_required.is_(True),
                      QaEquipmentRow.due_on <= _today(s) + timedelta(days=due_within_days)]
        total = int(s.execute(select(func.count()).select_from(QaEquipmentRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaEquipmentRow).where(*conds).order_by(
            col.desc() if (sort or "").startswith("-") else col.asc(), QaEquipmentRow.id).limit(limit)
            .offset(offset)).scalars()
        return {"items": [record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def get_equipment(ctx: AppContext, equipment_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment"), True)


def _check_refs(s: Session, body: EquipmentInput) -> None:
    from ..db_models import MfgLineRow, MfgToolPoolRow

    if body.line_id and s.get(MfgLineRow, body.line_id) is None:
        raise unknown_ref(["body", "line_id"], body.line_id, "Line")
    if body.tool_pool_id and s.get(MfgToolPoolRow, body.tool_pool_id) is None:
        raise unknown_ref(["body", "tool_pool_id"], body.tool_pool_id, "Tool pool")


FIELDS = ("code", "name", "kind", "equipment_class", "line_id", "tool_pool_id", "serial_no", "manufacturer",
          "location", "calibration_required", "interval_days", "grace_days", "due_on", "procedure_ref", "provider",
          "note")


def create_equipment(ctx: AppContext, a: Any, body: EquipmentInput) -> dict[str, Any]:
    from .common import audit, ensure_unique

    with write_tx(ctx) as (s, _plant):
        ensure_unique(s, QaEquipmentRow, "Equipment", {"code": body.code})
        _check_refs(s, body)
        now = utcnow()
        r = QaEquipmentRow(id=new_id("eqp_"), status="active", last_calibrated_on=None, failed_on=None,
                           row_version=1, created_at=now, updated_at=now, **{k: getattr(body, k) for k in FIELDS})
        s.add(r)
        s.flush()
        audit(s, "equipment", r.id, "create", {"code": r.code})
        return record(s, r, True)


def update_equipment(ctx: AppContext, a: Any, equipment_id: str, body: EquipmentInput, if_match: str | None
                     ) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from .common import ensure_unique

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment", lock=True)
        check_version(r, if_match)
        ensure_unique(s, QaEquipmentRow, "Equipment", {"code": body.code}, exclude_id=r.id)
        _check_refs(s, body)
        # review M6: the due date moves only through calibrations; an invalid item cannot be unblocked by editing
        if body.due_on != r.due_on:
            raise ApiError(409, "QA_DUE_VIA_CALIBRATION", "The due date changes through a recorded calibration.",
                           {"due_on": r.due_on.isoformat() if r.due_on else None})
        guarded = ("calibration_required", "grace_days", "line_id", "tool_pool_id", "interval_days")
        changed = [k for k in guarded if getattr(body, k) != getattr(r, k)]
        if changed and r.status != "retired" and not valid(r, _today(s)):
            raise ApiError(409, "QA_EQUIPMENT_BLOCKING", f"{r.code} is not valid; record a calibration (or take it "
                           "out of service) before changing these fields.", {"fields": changed})
        before = eq_content(r)
        for k in FIELDS:
            if k != "due_on":
                setattr(r, k, getattr(body, k))
        touch(r)
        s.flush()
        audit_regulated(s, "equipment", r.id, "update", before=before, after=eq_content(r),
                        record_version=r.row_version)
        return record(s, r, True)


def _status_event(s: Session, r: QaEquipmentRow) -> None:
    from ....integration import outbox

    if outbox.enabled(s):
        outbox.emit(s, "qa.equipment.status", {"id": r.id, "code": r.code, "status": r.status,
                                               "due_on": r.due_on.isoformat() if r.due_on else None}, r.code)


def _passed_after_failure(s: Session, r: QaEquipmentRow) -> bool:
    """Review m11: the latest calibration record (by recording order, not by date) must be a pass."""
    last = s.execute(select(QaCalibrationRow).where(QaCalibrationRow.equipment_id == r.id)
                     .order_by(QaCalibrationRow.created_at.desc(), QaCalibrationRow.id.desc()).limit(1)
                     ).scalars().first()
    if last is None:
        return r.failed_on is None
    return last.result != "fail"


def set_status(ctx: AppContext, a: Any, equipment_id: str, body: EquipmentStatusInput, if_match: str | None
               ) -> dict[str, Any]:
    """`active` from `out_of_service` is `equipment.return_to_service` (signed; a passing calibration after the
    failure when calibration is required: 409 `QA_CALIBRATION_REQUIRED`)."""
    from ...audit_diff import audit_regulated
    from . import esig

    with read_tx(ctx) as s:
        cur = repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment").status
    back = cur == "out_of_service" and body.status == "active"
    auth = esig.authenticate(ctx, a, "equipment", "return_to_service", body.signature) if back else None
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status == "retired":
            raise ApiError(409, "MFG_INVALID_STATE", "Retired equipment stays retired.", {"status": r.status})
        if r.status == body.status:
            return record(s, r, True)
        sig_id = None
        if r.status == "out_of_service" and body.status == "active":
            if r.calibration_required and (not _passed_after_failure(s, r)
                                           or not EQ.valid_on("active", True, r.due_on, r.grace_days, _today(s))):
                raise ApiError(409, "QA_CALIBRATION_REQUIRED", "Record a passing calibration after the failure "
                               "first.", {"failed_on": r.failed_on.isoformat() if r.failed_on else None})
            out = esig.sign(s, a, auth, "equipment", r.id, "return_to_service", body.signature)
            if out.pending is not None:
                return out.pending
            sig_id = out.signature_ids[-1] if out.signature_ids else None
        before = eq_content(r)
        r.status = body.status
        touch(r)
        s.flush()
        audit_regulated(s, "equipment", r.id, "status", before=before, after=eq_content(r), reason=body.reason,
                        record_version=r.row_version, signature_id=sig_id)
        _status_event(s, r)
        return record(s, r, True)


# ---------------------------------------------------------------- calibrations (Q58-Q59)

def list_calibrations(ctx: AppContext, equipment_id: str, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment")
        conds = [QaCalibrationRow.equipment_id == equipment_id]
        total = int(s.execute(select(func.count()).select_from(QaCalibrationRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaCalibrationRow).where(*conds).order_by(QaCalibrationRow.performed_on.desc(),
                                                                        QaCalibrationRow.id)
                         .limit(limit).offset(offset)).scalars()
        return {"items": [cal_record(s, c, True) for c in rows], "total": total, "limit": limit, "offset": offset}


def record_calibration(ctx: AppContext, a: Any, equipment_id: str, body: CalibrationInput) -> dict[str, Any]:
    """Signed `calibration.record` (8): due date from next_due_on or interval; `fail` -> out of service +
    notification; the signature's snapshot is the new calibration."""
    from ...audit_diff import audit_regulated
    from . import esig
    from .common import audit

    auth = esig.authenticate(ctx, a, "calibration", "record", body.signature)
    with write_tx(ctx) as (s, _plant):
        e = repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment", lock=True)
        if e.status == "retired":
            raise ApiError(409, "MFG_INVALID_STATE", "Retired equipment is not calibrated.", {"status": e.status})
        if body.performed_on > _today(s):
            raise ApiError(422, "VALIDATION_ERROR", "performed_on is in the future.", {"errors": [
                {"loc": ["body", "performed_on"], "msg": "future date", "type": "value_error"}]})
        loaded = _eq_loader(s, e.id, False)
        now = utcnow()
        nxt = body.next_due_on or (body.performed_on + timedelta(days=e.interval_days) if e.interval_days else None)
        c = QaCalibrationRow(id=new_id("cal_"), equipment_id=e.id, performed_on=body.performed_on,
                             performed_by=body.performed_by or a.user_id, provider_name=body.provider_name,
                             result=body.result, as_found=body.as_found, as_left=body.as_left,
                             certificate_ref=body.certificate_ref, next_due_on=nxt if body.result != "fail" else None,
                             row_version=1, created_at=now, updated_at=now)
        s.add(c)
        s.flush()
        snap, ver = calibration_content(s, c.id)
        out = esig.sign(s, a, auth, "calibration", e.id, "record", body.signature, loaded=loaded,
                        stored_content=snap, store_record_id=c.id, store_version=ver)
        if out.pending is not None:                       # pragma: no cover - single-step policy (validated)
            raise ApiError(409, "ESIG_POLICY_INVALID", "Calibrations are signed in one step.", {})
        before = eq_content(e)
        if body.result == "fail":
            e.failed_on = body.performed_on
            e.status = "out_of_service"
            from .replan import notify

            notify(s, "qa_calibration_failed", "warning", f"{e.code} failed calibration",
                   f"{e.code} ({e.name}) failed calibration on {body.performed_on.isoformat()} and is out of "
                   "service. Review the impact list.", f"/mfg/qa/equipment/{e.id}")
        else:
            if body.performed_on >= (e.last_calibrated_on or body.performed_on):
                e.last_calibrated_on, e.due_on = body.performed_on, nxt
        touch(e)
        s.flush()
        audit(s, "calibration", c.id, "create", {"equipment": e.code, "result": c.result})
        audit_regulated(s, "equipment", e.id, "calibration", before=before, after=eq_content(e),
                        reason=(body.signature.comment if body.signature else None),
                        record_version=e.row_version, signature_id=out.signature_ids[-1] if out.signature_ids
                        else None)
        if before["status"] != e.status:
            _status_event(s, e)
        return cal_record(s, c, True)


def impact(ctx: AppContext, equipment_id: str) -> dict[str, Any]:
    """Results measured with the equipment since its last passing calibration before the latest failure."""
    from ..db_models_m2 import MfgLotRow
    from ..db_models_m7 import QaInspectionLotRow, QaResultRow

    with read_tx(ctx) as s:
        e = repo.get_row(s, QaEquipmentRow, equipment_id, what="Equipment")
        upto = e.failed_on
        q = select(QaCalibrationRow.performed_on).where(QaCalibrationRow.equipment_id == e.id,
                                                        QaCalibrationRow.result != "fail")
        if upto is not None:
            q = q.where(QaCalibrationRow.performed_on < upto)
        since = s.execute(q.order_by(QaCalibrationRow.performed_on.desc()).limit(1)).scalar()
        conds = [QaResultRow.equipment_id == e.id, QaResultRow.superseded.is_(False)]
        if since is not None:
            from datetime import UTC
            conds.append(QaResultRow.entered_at >= datetime.combine(since, datetime.min.time(), UTC))
        rows = s.execute(select(QaResultRow.inspection_lot_id, func.count()).where(*conds)
                         .group_by(QaResultRow.inspection_lot_id)).all()
        lots = []
        for lid, n in rows:
            il = s.get(QaInspectionLotRow, lid)
            if il is None:
                continue
            lot = s.get(MfgLotRow, il.lot_id) if il.lot_id else None
            lots.append({"id": il.id, "number": il.number, "status": il.status, "decision": il.decision,
                         "lot_id": il.lot_id, "lot_code": lot.lot_code if lot else None, "item_id": il.item_id,
                         "results": int(n)})
        lots.sort(key=lambda x: x["number"])
        return {"equipment_id": e.id, "since": since, "results": sum(x["results"] for x in lots),
                "inspection_lots": lots}


# ---------------------------------------------------------------- APS / health (8 blocking (3))

def line_blocks(s: Session, as_of: date, horizon_end: date | None = None) -> dict[str, dict[str, Any]]:
    """line_id -> {from: date, equipment, reason}: lines with linked equipment invalid at `as_of` (from as_of) or
    becoming invalid inside the horizon (from due_on + grace + 1)."""
    out: dict[str, dict[str, Any]] = {}
    for e in s.execute(select(QaEquipmentRow).where(QaEquipmentRow.line_id.is_not(None),
                                                    QaEquipmentRow.status != "retired")).scalars():
        start = EQ.blocked_from(e)
        if start is None:
            continue
        start = max(start, as_of)
        if horizon_end is not None and start > horizon_end:
            continue
        why = (f"{e.code} calibration overdue since {(e.due_on + timedelta(days=e.grace_days + 1)).isoformat()}"
               if e.status == "active" and e.due_on else f"{e.code} {e.status.replace('_', ' ')}")
        cur = out.get(e.line_id)
        if cur is None or start < cur["from"]:
            out[e.line_id] = {"from": start, "equipment": e.code, "equipment_id": e.id, "reason": why}
    return out


def tool_pool_valid_units(s: Session, as_of: date) -> dict[str, int]:
    """tool_pool_id -> valid linked units (pools with linked equipment use min(quantity, valid units))."""
    out: dict[str, int] = {}
    for e in s.execute(select(QaEquipmentRow).where(QaEquipmentRow.tool_pool_id.is_not(None),
                                                    QaEquipmentRow.status != "retired")).scalars():
        out.setdefault(e.tool_pool_id, 0)
        out[e.tool_pool_id] += 1 if valid(e, as_of) else 0
    return out


__getattr__ = m7_examples.module_getattr(__name__)
