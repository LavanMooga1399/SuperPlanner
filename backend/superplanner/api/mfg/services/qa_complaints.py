"""Complaints (M7-DESIGN 7): `open -> investigation -> closed` (close signed). Lot and serial codes typed in are
resolved to records (unknown codes are kept as text with a warning). Reportability is decision support:
`due_on = aware_on + days` of the matching rule per regime (QA settings); the regulatory team records `reportable`
and `report_ref`. `complaint_sor = external`: link stubs only (409 `QA_EXTERNAL_SOR` on workflow actions)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa.model import ApproveInput, ComplaintAdvanceInput, ComplaintInput
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models_m2 import MfgLotRow
from ..db_models_m4 import MfgUnitSerialRow
from ..db_models_m7 import QaComplaintRow
from . import m7_examples
from .common import check_version, ilike, read_tx, touch, write_tx
from .qa_common import Act, decorate, next_number, settings_of


def _resolve(s: Session, item_id: str | None, lots: list[str], serials: list[str]
             ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    out_l, out_s, warn = [], [], []
    for code in lots:
        q = select(MfgLotRow.id).where(MfgLotRow.lot_code == code)
        if item_id:
            q = q.where(MfgLotRow.item_id == item_id)
        ids = list(s.execute(q.limit(2)).scalars())
        out_l.append({"code": code, "lot_id": ids[0] if len(ids) == 1 else None})
        if len(ids) != 1:
            warn.append(f"Lot {code} was {'ambiguous' if ids else 'not found'}; kept as text.")
    for code in serials:
        q = select(MfgUnitSerialRow.id).where(MfgUnitSerialRow.serial == code)
        if item_id:
            q = q.where(MfgUnitSerialRow.item_id == item_id)
        ids = list(s.execute(q.limit(2)).scalars())
        out_s.append({"code": code, "serial_id": ids[0] if len(ids) == 1 else None})
        if len(ids) != 1:
            warn.append(f"Serial {code} was {'ambiguous' if ids else 'not found'}; kept as text.")
    return out_l, out_s, warn


def reporting_due(s: Session, r: QaComplaintRow) -> list[dict[str, Any]]:
    from .m2util import today

    rules = settings_of(s).reportability_rules
    regimes = (r.reportability or {}).get("regimes") or sorted({x.regime for x in rules})
    out = []
    d = today(s)
    for reg in regimes:
        match = [x for x in rules if x.regime == reg and x.event_type == r.event_type] or \
            [x for x in rules if x.regime == reg and x.event_type == "all"]
        if not match:
            continue
        days = min(x.days for x in match)
        due = r.aware_on + timedelta(days=days)
        out.append({"regime": reg, "days": days, "due_on": due,
                    "overdue": bool(r.status != "closed" and not (r.reportability or {}).get("report_ref")
                                    and (r.reportability or {}).get("reportable") is not False and due < d)})
    return out


def content(s: Session, r: QaComplaintRow) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "received_on": r.received_on, "aware_on": r.aware_on,
            "channel": r.channel, "customer": r.customer, "country": r.country, "item_id": r.item_id, "lots": r.lots,
            "serials": r.serials, "qty_affected": r.qty_affected, "description": r.description,
            "event_type": r.event_type, "reportability": r.reportability, "investigation": r.investigation,
            "status": r.status}


def _loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaComplaintRow, rid, what="Complaint", lock=lock)
    return C.Loaded(r, content(s, r), r.row_version, r.author_id, [("Complaint", r.number), ("Customer", r.customer),
                                                                   ("Event", r.event_type)])


C.register("complaint", _loader)


def record(s: Session, r: QaComplaintRow, full: bool = False) -> dict[str, Any]:
    warn = [f"Lot {x['code']} is not a known lot." for x in r.lots or [] if not x.get("lot_id")] + \
        [f"Serial {x['code']} is not a known serial." for x in r.serials or [] if not x.get("serial_id")]
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           **content(s, r), "warnings": warn, "reporting_due": reporting_due(s, r), "author_id": r.author_id,
           "closed_at": r.closed_at, "external_ref": r.external_ref, "sor": r.sor,
           "signatures": [], "links": [], "attachments": []}
    if full:
        decorate(s, rec, "complaint", "complaint")
    return rec


def list_complaints(ctx: AppContext, q: str | None, status: str | None, item_id: str | None, sort: str | None,
                    limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(or_(ilike(QaComplaintRow.number, q), ilike(QaComplaintRow.customer, q)))
    if status:
        conds.append(QaComplaintRow.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    if item_id:
        conds.append(QaComplaintRow.item_id == item_id)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(QaComplaintRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaComplaintRow).where(*conds).order_by(QaComplaintRow.created_at.desc(),
                                                                      QaComplaintRow.id)
                         .limit(limit).offset(offset)).scalars()
        return {"items": [record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def get_complaint(ctx: AppContext, complaint_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, repo.get_row(s, QaComplaintRow, complaint_id, what="Complaint"), True)


def create_complaint(ctx: AppContext, a: Act, body: ComplaintInput) -> dict[str, Any]:
    from .common import audit

    with write_tx(ctx) as (s, _plant):
        ext = settings_of(s).complaint_sor == "external"
        if ext and not body.external_ref:
            raise ApiError(422, "VALIDATION_ERROR", "External complaints need external_ref.", {"errors": [
                {"loc": ["body", "external_ref"], "msg": "required", "type": "value_error"}]})
        lots, sers, _w = _resolve(s, body.item_id, body.lots, body.serials)
        now = utcnow()
        r = QaComplaintRow(id=new_id("cmp_"), number=next_number(s, "CMP", QaComplaintRow),
                           received_on=body.received_on, aware_on=body.aware_on, channel=body.channel,
                           customer=body.customer, country=body.country, item_id=body.item_id, lots=lots,
                           serials=sers, qty_affected=body.qty_affected, description=body.description,
                           event_type=body.event_type, reportability=body.reportability.model_dump(),
                           investigation=body.investigation, status="external" if ext else "open",
                           sor="external" if ext else "superplanner",
                           author_id=a.user_id, closed_at=None, external_ref=body.external_ref, row_version=1,
                           created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "complaint", r.id, "create", {"number": r.number})
        return record(s, r, True)


def update_complaint(ctx: AppContext, a: Act, complaint_id: str, body: ComplaintInput, if_match: str | None
                     ) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaComplaintRow, complaint_id, what="Complaint", lock=True)
        check_version(r, if_match)
        if r.status == "closed":
            raise esig.locked_error(r.number)
        before = content(s, r)
        esig.supersede_pending(s, "complaint", r.id, r.row_version)
        lots, sers, _w = _resolve(s, body.item_id, body.lots, body.serials)
        for k in ("received_on", "aware_on", "channel", "customer", "country", "item_id", "qty_affected",
                  "description", "event_type", "investigation", "external_ref"):
            setattr(r, k, getattr(body, k))
        r.lots, r.serials, r.reportability = lots, sers, body.reportability.model_dump()
        touch(r)
        s.flush()
        audit_regulated(s, "complaint", r.id, "update", before=before, after=content(s, r),
                        record_version=r.row_version)
        return record(s, r, True)


def advance(ctx: AppContext, a: Act, complaint_id: str, body: ComplaintAdvanceInput, if_match: str | None
            ) -> dict[str, Any]:
    from ...audit_diff import audit_regulated

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaComplaintRow, complaint_id, what="Complaint", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.sor == "external":
            raise ApiError(409, "QA_EXTERNAL_SOR", "This complaint is managed in the external system.", {})
        if r.status != "open":
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} complaint cannot move to investigation.",
                           {"status": r.status})
        r.status = "investigation"
        touch(r)
        s.flush()
        audit_regulated(s, "complaint", r.id, "advance", before={"status": "open"},
                        after={"status": "investigation"}, reason=body.note or None,
                        record_version=r.row_version)
        return record(s, r, True)


def close(ctx: AppContext, a: Act, complaint_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    auth = esig.authenticate(ctx, a, "complaint", "close", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaComplaintRow, complaint_id, what="Complaint", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.sor == "external":
            raise ApiError(409, "QA_EXTERNAL_SOR", "This complaint is managed in the external system.", {})
        if r.status not in ("open", "investigation"):
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} complaint cannot be closed.", {"status": r.status})
        if not (r.reportability or {}).get("assessed"):
            raise ApiError(409, "QA_COMPLAINT_NOT_ASSESSED", "Record the reportability assessment first.",
                           {"missing": ["reportability"]})
        out = esig.sign(s, a, auth, "complaint", r.id, "close", body.signature)
        if out.pending is not None:
            return out.pending
        before = r.status
        r.status, r.closed_at = "closed", utcnow()
        touch(r)
        s.flush()
        sig = body.signature
        audit_regulated(s, "complaint", r.id, "close", before={"status": before}, after={"status": "closed"},
                        reason=(sig.comment if sig and sig.comment else body.note) or None,
                        record_version=r.row_version, signature_id=out.signature_ids[-1] if out.signature_ids else None)
        return record(s, r, True)


__getattr__ = m7_examples.module_getattr(__name__)
