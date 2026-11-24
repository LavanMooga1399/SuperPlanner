"""Inspection (M7-DESIGN 5): sampling schemes, inspection plans, inspection lots, results, verdicts, switching,
usage decisions, and the hooks that create inspection lots (PO receipts, first start of an inspection-gate
operation, WO receipts) or block gate completion.

Locks: write paths lock the plant (`write_tx`) for master data (schemes, plans); inspection lots are locked by row
(`FOR UPDATE`) under `write_tx(lock=False)` so results of different lots do not serialise; holds lock the lot row
after the inspection lot (lock order: inspection lot -> mfg lot).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa import evaluate as EV
from ....qa import sampling as SMP
from ....qa.equipment import valid as eq_valid
from ....qa.model import (ApproveInput, CancelInput, DecisionInput, InspectionLotInput, PlanInput, ResultsBatch,
                          SchemeInput, SchemeTable)
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow, MfgOperationRow, MfgRoutingRow
from ..db_models_m2 import MfgLotRow, MfgWorkOrderRow
from ..db_models_m7 import (QaCharacteristicRow, QaEquipmentRow, QaInspectionLotRow, QaInspectionPlanRow,
                            QaResultBatchRow, QaResultRow, QaSamplingSchemeRow, QaSwitchingStateRow)
from . import m7_examples
from .common import check_version, ilike, jsonable, read_tx, touch, unknown_ref, write_tx
from .qa_common import Act, decorate, item_ref, next_number, settings_of

SCHEME_SORTS = {"code": QaSamplingSchemeRow.code}
OPEN_LOT = ("open", "in_progress", "ready")


def _invalid_state(what: str, status: str, action: str) -> ApiError:
    return ApiError(409, "MFG_INVALID_STATE", f"A {status} {what} cannot be {action}.",
                    {"status": status, "action": action})


def _db_now(s: Session) -> datetime:
    from .esig import db_now

    return db_now(s)


# ---------------------------------------------------------------- schemes (5.1)

def scheme_record(s: Session | None, r: QaSamplingSchemeRow, full: bool = False) -> dict[str, Any]:
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "code": r.code, "name": r.name, "kind": r.kind, "fixed_n": r.fixed_n, "percent": r.percent,
           "table": r.table, "switching": r.switching, "status": r.status, "approved_at": r.approved_at,
           "note": r.note, "signatures": [], "links": [], "attachments": []}
    if full and s is not None:
        from . import esig

        rec["signatures"] = esig.manifests(s, "sampling_scheme", r.id)
    return rec


def _scheme_content(r: QaSamplingSchemeRow) -> dict[str, Any]:
    return {"id": r.id, "code": r.code, "name": r.name, "kind": r.kind, "fixed_n": r.fixed_n, "percent": r.percent,
            "table": r.table, "switching": r.switching, "note": r.note}


def _scheme_loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaSamplingSchemeRow, rid, what="Sampling scheme", lock=lock)
    return C.Loaded(r, _scheme_content(r), r.row_version, r.author_id, [("Scheme", f"{r.code} - {r.name}"),
                                                                       ("Kind", r.kind)])


C.register("sampling_scheme", _scheme_loader)


def _check_table(body: SchemeInput) -> dict[str, Any] | None:
    if body.table is None:
        return None
    t = body.table.model_dump(mode="json")
    try:
        SMP.validate_table(t)
    except SMP.SchemeError as e:
        raise ApiError(422, "QA_SCHEME_INVALID", f"The sampling table is invalid: {e}.", {"loc": e.loc}) from None
    return t


def list_schemes(ctx: AppContext, q: str | None, status: str | None, limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(or_(ilike(QaSamplingSchemeRow.code, q), ilike(QaSamplingSchemeRow.name, q)))
    if status:
        conds.append(QaSamplingSchemeRow.status == status)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(QaSamplingSchemeRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaSamplingSchemeRow).where(*conds).order_by(QaSamplingSchemeRow.code)
                         .limit(limit).offset(offset)).scalars()
        return {"items": [scheme_record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def create_scheme(ctx: AppContext, a: Act, body: SchemeInput) -> dict[str, Any]:
    from .common import audit, ensure_unique

    t = _check_table(body)
    with write_tx(ctx) as (s, _plant):
        ensure_unique(s, QaSamplingSchemeRow, "A sampling scheme", {"code": body.code})
        now = utcnow()
        r = QaSamplingSchemeRow(id=new_id("ssc_"), code=body.code, name=body.name, kind=body.kind,
                                fixed_n=body.fixed_n, percent=body.percent, table=t, switching=body.switching,
                                status="draft", approved_at=None, author_id=a.user_id, note=body.note, row_version=1,
                                created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "sampling_scheme", r.id, "create", {"code": r.code})
        return scheme_record(s, r, True)


def get_scheme(ctx: AppContext, scheme_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return scheme_record(s, repo.get_row(s, QaSamplingSchemeRow, scheme_id, what="Sampling scheme"), True)


def update_scheme(ctx: AppContext, a: Act, scheme_id: str, body: SchemeInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig
    from .common import ensure_unique

    t = _check_table(body)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaSamplingSchemeRow, scheme_id, what="Sampling scheme", lock=True)
        check_version(r, if_match)
        if r.status != "draft":
            raise ApiError(409, "ESIG_RECORD_LOCKED", "Approved schemes are immutable; create a scheme with a new "
                           "code.", {"status": r.status})
        ensure_unique(s, QaSamplingSchemeRow, "A sampling scheme", {"code": body.code}, exclude_id=r.id)
        before = _scheme_content(r)
        esig.supersede_pending(s, "sampling_scheme", r.id, r.row_version)
        r.code, r.name, r.kind, r.fixed_n, r.percent = body.code, body.name, body.kind, body.fixed_n, body.percent
        r.table, r.switching, r.note = t, body.switching, body.note
        touch(r)
        s.flush()
        audit_regulated(s, "sampling_scheme", r.id, "update", before=before, after=_scheme_content(r),
                        record_version=r.row_version)
        return scheme_record(s, r, True)


def delete_scheme(ctx: AppContext, a: Act, scheme_id: str, if_match: str | None) -> None:
    from ...audit_diff import audit_regulated
    from .part11 import delete_not_allowed, regulated_delete_blocked

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaSamplingSchemeRow, scheme_id, what="Sampling scheme", lock=True)
        check_version(r, if_match)
        if r.status != "draft":
            raise _invalid_state("sampling scheme", r.status, "deleted")
        used = s.execute(select(QaInspectionPlanRow.id).where(QaInspectionPlanRow.scheme_id == r.id).limit(1)).first()
        if used is not None:
            from .common import in_use

            raise in_use("This scheme", {"inspection_plans": 1})
        if regulated_delete_blocked(s, "sampling_scheme", r.id):
            raise delete_not_allowed()
        audit_regulated(s, "sampling_scheme", r.id, "delete", before=_scheme_content(r), after={})
        s.delete(r)


def approve_scheme(ctx: AppContext, a: Act, scheme_id: str, body: ApproveInput, if_match: str | None
                   ) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    auth = esig.authenticate(ctx, a, "sampling_scheme", "approve", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaSamplingSchemeRow, scheme_id, what="Sampling scheme", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "draft":
            raise _invalid_state("sampling scheme", r.status, "approved")
        if r.kind == "table":
            try:
                SMP.validate_table(SchemeTable.model_validate(r.table).model_dump(mode="json"))
            except SMP.SchemeError as e:
                raise ApiError(422, "QA_SCHEME_INVALID", f"The sampling table is invalid: {e}.",
                               {"loc": e.loc}) from None
        out = esig.sign(s, a, auth, "sampling_scheme", r.id, "approve", body.signature)
        if out.pending is not None:
            return out.pending
        r.status, r.approved_at = "approved", _db_now(s)
        touch(r)
        s.flush()
        audit_regulated(s, "sampling_scheme", r.id, "approve", before={"status": "draft"},
                        after={"status": "approved"}, reason=_why(body), record_version=r.row_version,
                        signature_id=out.signature_ids[-1] if out.signature_ids else None)
        return scheme_record(s, r, True)


def _why(body: Any) -> str:
    sig = getattr(body, "signature", None)
    return (sig.comment.strip() if sig is not None and sig.comment.strip() else "") or \
        (getattr(body, "note", "") or "").strip() or "Signed action"


def resolve(sch: QaSamplingSchemeRow, lot_size: float, level: str, aql: str, state: str) -> dict[str, Any]:
    try:
        return SMP.resolve(sch.kind, lot_size=lot_size, fixed_n=sch.fixed_n, percent=sch.percent, table=sch.table,
                           level=level, aql=aql, state=state)
    except SMP.SchemeError as e:
        raise ApiError(422, "QA_SCHEME_INVALID", f"{sch.code}: {e}.", {"loc": e.loc}) from None


def preview_scheme(ctx: AppContext, scheme_id: str, lot_size: float, level: str, aql: str, state: str
                   ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        sch = repo.get_row(s, QaSamplingSchemeRow, scheme_id, what="Sampling scheme")
        r = resolve(sch, lot_size, level, aql, state if sch.switching else "normal")
        return {"lot_size": lot_size, "level": level, "aql": aql, "state": state, **r}


# ---------------------------------------------------------------- plans (5.1)

def _chars(s: Session, plan_id: str) -> list[QaCharacteristicRow]:
    return list(s.execute(select(QaCharacteristicRow).where(QaCharacteristicRow.plan_id == plan_id)
                          .order_by(QaCharacteristicRow.seq)).scalars())


def char_record(c: QaCharacteristicRow) -> dict[str, Any]:
    return {"id": c.id, "seq": c.seq, "code": c.code, "name": c.name, "kind": c.kind, "severity": c.severity,
            "unit": c.unit, "nominal": c.nominal, "lsl": c.lsl, "usl": c.usl, "method": c.method,
            "equipment_class": c.equipment_class, "sample_override": c.sample_override, "destructive": c.destructive}


def plan_content(s: Session, r: QaInspectionPlanRow) -> dict[str, Any]:
    from .qa_common import attachments_of

    return {"id": r.id, "number": r.number, "version": r.version, "name": r.name, "item_id": r.item_id,
            "scope": r.scope, "operation_seq": r.operation_seq, "supplier_id": r.supplier_id, "customer": r.customer,
            "scheme_id": r.scheme_id, "inspection_level": r.inspection_level, "aql": r.aql,
            "effective_from": r.effective_from, "note": r.note,
            "characteristics": [{k: v for k, v in char_record(c).items()} for c in _chars(s, r.id)],
            "attachments": [x["sha256"] for x in attachments_of(s, "inspection_plan", r.id)]}


def _plan_loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaInspectionPlanRow, rid, what="Inspection plan", lock=lock)
    it = item_ref(s, r.item_id) or {}
    return C.Loaded(r, plan_content(s, r), r.row_version, r.author_id,
                    [("Plan", f"{r.number} v{r.version}"), ("Item", str(it.get("part_number"))), ("Scope", r.scope),
                     ("Characteristics", str(len(_chars(s, r.id))))])


C.register("inspection_plan", _plan_loader)


def plan_record(s: Session, r: QaInspectionPlanRow, full: bool = False) -> dict[str, Any]:
    sch = s.get(QaSamplingSchemeRow, r.scheme_id)
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "number": r.number, "version": r.version, "name": r.name, "item_id": r.item_id,
           "item": item_ref(s, r.item_id), "scope": r.scope, "operation_seq": r.operation_seq,
           "supplier_id": r.supplier_id, "customer": r.customer, "scheme_id": r.scheme_id,
           "scheme_code": sch.code if sch else None, "inspection_level": r.inspection_level, "aql": r.aql,
           "status": r.status, "effective_from": r.effective_from, "supersedes_id": r.supersedes_id,
           "approved_at": r.approved_at, "note": r.note, "characteristics": [], "signatures": [], "links": [],
           "attachments": []}
    if full:
        rec["characteristics"] = [char_record(c) for c in _chars(s, r.id)]
        decorate(s, rec, "inspection_plan", "inspection_plan")
    return rec


def _check_plan_refs(s: Session, body: PlanInput) -> None:
    from ..db_models_m2 import MfgSupplierRow

    if s.get(MfgItemRow, body.item_id) is None:
        raise unknown_ref(["body", "item_id"], body.item_id, "Item")
    if s.get(QaSamplingSchemeRow, body.scheme_id) is None:
        raise unknown_ref(["body", "scheme_id"], body.scheme_id, "Sampling scheme")
    if body.supplier_id and s.get(MfgSupplierRow, body.supplier_id) is None:
        raise unknown_ref(["body", "supplier_id"], body.supplier_id, "Supplier")
    for i, c in enumerate(body.characteristics):
        ov = c.sample_override or {}
        if ov.get("scheme_id") and s.get(QaSamplingSchemeRow, ov["scheme_id"]) is None:
            raise unknown_ref(["body", "characteristics", i, "sample_override", "scheme_id"], ov["scheme_id"])


def _write_chars(s: Session, plan: QaInspectionPlanRow, body: PlanInput) -> None:
    existing = {c.id: c for c in _chars(s, plan.id)}
    keep: set[str] = set()
    for c in body.characteristics:
        vals = c.model_dump(exclude={"id"})
        row = existing.get(c.id) if c.id else None
        if row is None:
            row = QaCharacteristicRow(id=new_id("ich_"), plan_id=plan.id, owner_id=plan.owner_id, **vals)
            s.add(row)
        else:
            for k, v in vals.items():
                setattr(row, k, v)
        keep.add(row.id)
    for cid, row in existing.items():
        if cid not in keep:
            s.delete(row)
    s.flush()


def list_plans(ctx: AppContext, q: str | None, item_id: str | None, scope: str | None, status: str | None,
               sort: str | None, limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(or_(ilike(QaInspectionPlanRow.number, q), ilike(QaInspectionPlanRow.name, q)))
    for col, v in ((QaInspectionPlanRow.item_id, item_id), (QaInspectionPlanRow.scope, scope),
                   (QaInspectionPlanRow.status, status)):
        if v:
            conds.append(col == v)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(QaInspectionPlanRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaInspectionPlanRow).where(*conds).order_by(
            QaInspectionPlanRow.number, QaInspectionPlanRow.version.desc()).limit(limit).offset(offset)).scalars()
        return {"items": [plan_record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def create_plan(ctx: AppContext, a: Act, body: PlanInput) -> dict[str, Any]:
    from .common import audit

    with write_tx(ctx) as (s, _plant):
        _check_plan_refs(s, body)
        now = utcnow()
        r = QaInspectionPlanRow(id=new_id("ipl_"), number=next_number(s, "IP", QaInspectionPlanRow), version=1,
                                name=body.name, item_id=body.item_id, scope=body.scope,
                                operation_seq=body.operation_seq, supplier_id=body.supplier_id,
                                customer=body.customer, scheme_id=body.scheme_id,
                                inspection_level=body.inspection_level, aql=dict(body.aql), status="draft",
                                effective_from=body.effective_from, supersedes_id=None, approved_at=None,
                                author_id=a.user_id, note=body.note, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        _write_chars(s, r, body)
        audit(s, "inspection_plan", r.id, "create", {"number": r.number})
        return plan_record(s, r, True)


def get_plan(ctx: AppContext, plan_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return plan_record(s, repo.get_row(s, QaInspectionPlanRow, plan_id, what="Inspection plan"), True)


def update_plan(ctx: AppContext, a: Act, plan_id: str, body: PlanInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaInspectionPlanRow, plan_id, what="Inspection plan", lock=True)
        check_version(r, if_match)
        if r.status != "draft":
            raise ApiError(409, "ESIG_RECORD_LOCKED", "Approved plans change through a new version (copy).",
                           {"status": r.status})
        _check_plan_refs(s, body)
        before = plan_content(s, r)
        esig.supersede_pending(s, "inspection_plan", r.id, r.row_version)
        for k in ("name", "item_id", "scope", "operation_seq", "supplier_id", "customer", "scheme_id",
                  "inspection_level", "effective_from", "note"):
            setattr(r, k, getattr(body, k))
        r.aql = dict(body.aql)
        _write_chars(s, r, body)
        touch(r)
        s.flush()
        audit_regulated(s, "inspection_plan", r.id, "update", before=before, after=plan_content(s, r),
                        record_version=r.row_version)
        return plan_record(s, r, True)


def delete_plan(ctx: AppContext, a: Act, plan_id: str, if_match: str | None) -> None:
    from ...audit_diff import audit_regulated
    from .part11 import delete_not_allowed, regulated_delete_blocked

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaInspectionPlanRow, plan_id, what="Inspection plan", lock=True)
        check_version(r, if_match)
        if r.status != "draft":
            raise _invalid_state("inspection plan", r.status, "deleted")
        if regulated_delete_blocked(s, "inspection_plan", r.id):
            raise delete_not_allowed()
        audit_regulated(s, "inspection_plan", r.id, "delete", before=plan_content(s, r), after={})
        s.delete(r)


def copy_plan(ctx: AppContext, a: Act, plan_id: str) -> dict[str, Any]:
    from .common import audit

    with write_tx(ctx) as (s, _plant):
        src = repo.get_row(s, QaInspectionPlanRow, plan_id, what="Inspection plan")
        ver = int(s.execute(select(func.max(QaInspectionPlanRow.version)).where(
            QaInspectionPlanRow.number == src.number)).scalar() or 0) + 1
        now = utcnow()
        r = QaInspectionPlanRow(id=new_id("ipl_"), number=src.number, version=ver, name=src.name,
                                item_id=src.item_id, scope=src.scope, operation_seq=src.operation_seq,
                                supplier_id=src.supplier_id, customer=src.customer, scheme_id=src.scheme_id,
                                inspection_level=src.inspection_level, aql=dict(src.aql), status="draft",
                                effective_from=None, supersedes_id=src.id, approved_at=None, author_id=a.user_id,
                                note=src.note, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        for c in _chars(s, src.id):
            s.add(QaCharacteristicRow(id=new_id("ich_"), plan_id=r.id, owner_id=r.owner_id,
                                      **{k: v for k, v in char_record(c).items() if k != "id"}))
        s.flush()
        audit(s, "inspection_plan", r.id, "copy", {"from": src.id, "version": ver})
        return plan_record(s, r, True)


def _released_routing_has_seq(s: Session, item_id: str, seq: int) -> bool:
    return s.execute(select(MfgOperationRow.id).join(MfgRoutingRow, MfgRoutingRow.id == MfgOperationRow.routing_id)
                     .where(MfgRoutingRow.item_id == item_id, MfgRoutingRow.status == "released",
                            MfgOperationRow.seq == seq).limit(1)).first() is not None


def approve_plan(ctx: AppContext, a: Act, plan_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig
    from .m2util import today

    auth = esig.authenticate(ctx, a, "inspection_plan", "approve", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaInspectionPlanRow, plan_id, what="Inspection plan", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "draft":
            raise _invalid_state("inspection plan", r.status, "approved")
        chars = _chars(s, r.id)
        if not chars:
            raise ApiError(422, "VALIDATION_ERROR", "Add at least one characteristic.", {"errors": [
                {"loc": ["characteristics"], "msg": "at least one", "type": "value_error"}]})
        sch = s.get(QaSamplingSchemeRow, r.scheme_id)
        if sch is None or sch.status != "approved":
            raise ApiError(422, "VALIDATION_ERROR", "The plan's sampling scheme must be approved.", {"errors": [
                {"loc": ["scheme_id"], "msg": "scheme not approved", "type": "value_error"}]})
        item = s.get(MfgItemRow, r.item_id)
        if r.scope in ("incoming", "final") and not (item and item.lot_controlled):
            raise ApiError(422, "QA_ITEM_NOT_LOT_CONTROLLED", "Incoming and final inspection need a lot-controlled "
                           "item.", {"item_id": r.item_id})
        if r.scope == "in_process" and not _released_routing_has_seq(s, r.item_id, int(r.operation_seq or 0)):
            raise ApiError(422, "QA_PLAN_OPERATION_UNKNOWN", f"Operation {r.operation_seq} is not on a released "
                           "routing of the item.", {"operation_seq": r.operation_seq})
        out = esig.sign(s, a, auth, "inspection_plan", r.id, "approve", body.signature)
        if out.pending is not None:
            return out.pending
        eff = r.effective_from or today(s)
        r.effective_from = eff
        r.status, r.approved_at = "approved", _db_now(s)
        # the previous approved version with the same key becomes obsolete (from `effective_from`; 14: at approval)
        for old in s.execute(select(QaInspectionPlanRow).where(
                QaInspectionPlanRow.id != r.id, QaInspectionPlanRow.status == "approved",
                QaInspectionPlanRow.item_id == r.item_id, QaInspectionPlanRow.scope == r.scope,
                _eq(QaInspectionPlanRow.operation_seq, r.operation_seq),
                _eq(QaInspectionPlanRow.supplier_id, r.supplier_id), _eq(QaInspectionPlanRow.customer, r.customer))
                .with_for_update()).scalars():
            old.status = "obsolete"
            touch(old)
            audit_regulated(s, "inspection_plan", old.id, "obsolete", before={"status": "approved"},
                            after={"status": "obsolete"}, reason=f"Superseded by {r.number} v{r.version}")
        touch(r)
        s.flush()
        audit_regulated(s, "inspection_plan", r.id, "approve", before={"status": "draft"},
                        after={"status": "approved", "effective_from": eff}, reason=_why(body),
                        record_version=r.row_version,
                        signature_id=out.signature_ids[-1] if out.signature_ids else None)
        return plan_record(s, r, True)


def _eq(col: Any, v: Any) -> Any:
    return col.is_(None) if v is None else col == v


def obsolete_plan(ctx: AppContext, a: Act, plan_id: str, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaInspectionPlanRow, plan_id, what="Inspection plan", lock=True)
        check_version(r, if_match)
        if r.status != "approved":
            raise _invalid_state("inspection plan", r.status, "made obsolete")
        r.status = "obsolete"
        touch(r)
        s.flush()
        audit_regulated(s, "inspection_plan", r.id, "obsolete", before={"status": "approved"},
                        after={"status": "obsolete"}, record_version=r.row_version)
        return plan_record(s, r, True)


def find_plan(s: Session, item_id: str, scope: str, on: date, *, supplier_id: str | None = None,
              customer: str | None = None, operation_seq: int | None = None) -> QaInspectionPlanRow | None:
    """The effective approved plan: specific (supplier for incoming, customer for final) beats generic."""
    q = select(QaInspectionPlanRow).where(
        QaInspectionPlanRow.item_id == item_id, QaInspectionPlanRow.scope == scope,
        QaInspectionPlanRow.status == "approved",
        or_(QaInspectionPlanRow.effective_from.is_(None), QaInspectionPlanRow.effective_from <= on))
    if operation_seq is not None:
        q = q.where(QaInspectionPlanRow.operation_seq == operation_seq)
    rows = list(s.execute(q.order_by(QaInspectionPlanRow.version.desc())).scalars())
    spec = [r for r in rows if (scope == "incoming" and supplier_id and r.supplier_id == supplier_id) or
            (scope == "final" and customer and r.customer == customer)]
    gen = [r for r in rows if r.supplier_id is None and r.customer is None]
    return (spec or gen or [None])[0]


# ---------------------------------------------------------------- inspection lots (5.2)

def _switch_key(plan: QaInspectionPlanRow, supplier_id: str | None) -> str:
    return f"{plan.number}|{supplier_id or '-'}"


def _switch_state(s: Session, plan: QaInspectionPlanRow, supplier_id: str | None, lock: bool = False
                  ) -> QaSwitchingStateRow | None:
    q = select(QaSwitchingStateRow).where(QaSwitchingStateRow.plan_key == _switch_key(plan, supplier_id))
    if lock:
        q = q.with_for_update()
    return s.execute(q).scalars().first()


def freeze_sampling(s: Session, plan: QaInspectionPlanRow, lot_size: float, supplier_id: str | None
                    ) -> dict[str, Any]:
    sch = s.get(QaSamplingSchemeRow, plan.scheme_id)
    st = _switch_state(s, plan, supplier_id)
    state = st.state if (st is not None and sch is not None and sch.switching) else "normal"
    out: dict[str, Any] = {}
    for c in _chars(s, plan.id):
        ov = c.sample_override or {}
        csch = s.get(QaSamplingSchemeRow, ov["scheme_id"]) if ov.get("scheme_id") else sch
        level = ov.get("level") or plan.inspection_level
        aql = str(ov.get("aql") or plan.aql.get(c.severity) or "0.65")
        cstate = state if csch is not None and csch.switching else "normal"
        r = resolve(csch, lot_size, level, aql, cstate)  # type: ignore[arg-type]
        out[c.id] = {"n": r["n"], "ac": r["ac"], "re": r["re"], "severity_state": cstate, "aql": aql,
                     "level": level, "full": r["full"]}
    return out


def create_lot_in(s: Session, plan: QaInspectionPlanRow, *, lot_size: float, source: str, actor: str,
                  lot_id: str | None = None, wo_id: str | None = None, wo_operation_id: str | None = None,
                  posting_id: str | None = None, supplier_id: str | None = None, customer: str | None = None,
                  hold: bool = False, note: str = "") -> QaInspectionLotRow:
    from .common import audit

    now = _db_now(s)
    hours = getattr(settings_of(s).inspection_due_hours, plan.scope)
    r = QaInspectionLotRow(
        id=new_id("ilt_"), number=next_number(s, "IL", QaInspectionLotRow), plan_id=plan.id,
        plan_version=plan.version, scope=plan.scope, item_id=plan.item_id, lot_id=lot_id, wo_id=wo_id,
        wo_operation_id=wo_operation_id, posting_id=posting_id, supplier_id=supplier_id, customer=customer,
        lot_size=round(float(lot_size), 6), sampling=freeze_sampling(s, plan, lot_size, supplier_id), status="open",
        verdict=None, decision=None, decided_by=None, decided_at=None, decision_note=note[:500], ncr_id=None,
        hold=bool(hold and lot_id), source=source, due_at=now + timedelta(hours=hours), row_version=1,
        created_at=now, updated_at=now)
    s.add(r)
    s.flush()
    r.verdict = _verdict(s, r)
    audit(s, "inspection_lot", r.id, "create", {"number": r.number, "plan": plan.number, "source": source,
                                               "lot_size": r.lot_size})
    if r.hold:
        from .qa_holds import place

        place(s, source="inspection", source_id=r.id, reason=f"{plan.scope.replace('_', '-')} inspection {r.number}",
              actor=actor, lot_id=lot_id)
    return r


def _results(s: Session, lot_id: str, include_superseded: bool = True) -> list[QaResultRow]:
    q = select(QaResultRow).where(QaResultRow.inspection_lot_id == lot_id)
    if not include_superseded:
        q = q.where(QaResultRow.superseded.is_(False))
    return list(s.execute(q.order_by(QaResultRow.characteristic_id, QaResultRow.sample_no, QaResultRow.entered_at,
                                      QaResultRow.id)).scalars())


def _verdict(s: Session, r: QaInspectionLotRow, results: list[QaResultRow] | None = None) -> dict[str, Any]:
    chars = {c.id: c for c in _chars(s, r.plan_id)}
    res = results if results is not None else _results(s, r.id, include_superseded=False)
    per: dict[str, dict[int, bool]] = {}
    for x in res:
        if not x.superseded:
            per.setdefault(x.characteristic_id, {})[x.sample_no] = not x.passed
    out = []
    for cid, sp in (r.sampling or {}).items():
        c = chars.get(cid)
        v, entered, d = EV.characteristic_verdict(sp["n"], sp["ac"], sp["re"], per.get(cid, {}))
        out.append({"characteristic_id": cid, "code": c.code if c else cid, "n": sp["n"], "ac": sp["ac"],
                    "re": sp["re"], "entered": entered, "defective": d, "verdict": v})
    out.sort(key=lambda x: (chars[x["characteristic_id"]].seq if x["characteristic_id"] in chars else 0))
    return {"verdict": EV.lot_verdict(out), "characteristics": out}


def result_record(x: QaResultRow) -> dict[str, Any]:
    return {"id": x.id, "characteristic_id": x.characteristic_id, "sample_no": x.sample_no, "value": x.value,
            "passed": x.passed, "defects": x.defects, "equipment_id": x.equipment_id, "note": x.note,
            "reason": x.reason, "entered_by": x.entered_by, "entered_at": x.entered_at,
            "corrects_result_id": x.corrects_result_id, "superseded": x.superseded}


def lot_content(s: Session, r: QaInspectionLotRow) -> dict[str, Any]:
    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    v = r.verdict or _verdict(s, r)
    return {"id": r.id, "number": r.number, "plan_id": r.plan_id, "plan_version": r.plan_version, "scope": r.scope,
            "item_id": r.item_id, "lot_id": r.lot_id, "lot_code": lot.lot_code if lot else None, "wo_id": r.wo_id,
            "wo_operation_id": r.wo_operation_id, "supplier_id": r.supplier_id, "lot_size": r.lot_size,
            "sampling": r.sampling, "verdict": v, "ncr_id": r.ncr_id, "status": r.status,
            "results": len(_results(s, r.id, include_superseded=False))}


def _lot_loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaInspectionLotRow, rid, what="Inspection lot", lock=lock)
    c = lot_content(s, r)
    it = item_ref(s, r.item_id) or {}
    return C.Loaded(r, c, r.row_version, None,
                    [("Inspection lot", r.number), ("Item", str(it.get("part_number"))),
                     ("Lot", str(c["lot_code"] or "-")), ("Lot size", f"{r.lot_size:g}"),
                     ("Verdict", c["verdict"]["verdict"])])


C.register("inspection_lot", _lot_loader)


def lot_record(s: Session, r: QaInspectionLotRow, full: bool = False) -> dict[str, Any]:
    from .m2util import plant
    from ....mfg.tz import plant_now

    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    wo = s.get(MfgWorkOrderRow, r.wo_id) if r.wo_id else None
    plan = s.get(QaInspectionPlanRow, r.plan_id)
    now = plant_now(plant(s))
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "number": r.number, "plan_id": r.plan_id, "plan_number": plan.number if plan else None,
           "plan_version": r.plan_version, "scope": r.scope, "item_id": r.item_id, "item": item_ref(s, r.item_id),
           "lot_id": r.lot_id, "lot_code": lot.lot_code if lot else None, "wo_id": r.wo_id,
           "wo_number": wo.number if wo else None, "wo_operation_id": r.wo_operation_id,
           "operation_seq": plan.operation_seq if plan else None, "posting_id": r.posting_id,
           "supplier_id": r.supplier_id, "customer": r.customer, "lot_size": r.lot_size, "sampling": r.sampling,
           "status": r.status, "verdict": r.verdict, "decision": r.decision, "decided_by": r.decided_by,
           "decided_at": r.decided_at, "decision_note": r.decision_note, "ncr_id": r.ncr_id, "hold": r.hold,
           "source": r.source, "due_at": r.due_at,
           "overdue": bool(r.status in OPEN_LOT and r.due_at is not None and r.due_at < now),
           "characteristics": [], "results": [], "signatures": [], "links": [], "attachments": []}
    if full:
        rec["characteristics"] = [char_record(c) for c in _chars(s, r.plan_id) if c.id in (r.sampling or {})]
        rec["results"] = [result_record(x) for x in _results(s, r.id)]
        decorate(s, rec, "inspection_lot", "inspection_lot")
    return rec


LOT_SORTS = {"number": QaInspectionLotRow.number, "due_at": QaInspectionLotRow.due_at,
             "created_at": QaInspectionLotRow.created_at, "status": QaInspectionLotRow.status}


def list_lots(ctx: AppContext, q: str | None, status: str | None, scope: str | None, item_id: str | None,
              supplier_id: str | None, overdue: bool | None, sort: str | None, limit: int, offset: int
              ) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(ilike(QaInspectionLotRow.number, q))
    if status:
        conds.append(QaInspectionLotRow.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    for col, v in ((QaInspectionLotRow.scope, scope), (QaInspectionLotRow.item_id, item_id),
                   (QaInspectionLotRow.supplier_id, supplier_id)):
        if v:
            conds.append(col == v)
    if overdue:
        conds += [QaInspectionLotRow.status.in_(OPEN_LOT), QaInspectionLotRow.due_at < utcnow()]
    key = (sort or "-created_at").lstrip("-")
    if key not in LOT_SORTS:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown sort {sort!r}.", {"errors": [
            {"loc": ["query", "sort"], "msg": "unknown sort", "type": "value_error"}]})
    col = LOT_SORTS[key]
    order = [col.desc() if (sort or "-created_at").startswith("-") else col.asc(), QaInspectionLotRow.id]
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(QaInspectionLotRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaInspectionLotRow).where(*conds).order_by(*order).limit(limit).offset(offset)
                         ).scalars()
        return {"items": [lot_record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def get_lot(ctx: AppContext, lot_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return lot_record(s, repo.get_row(s, QaInspectionLotRow, lot_id, what="Inspection lot"), True)


def create_lot(ctx: AppContext, a: Act, body: InspectionLotInput) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        plan = repo.get_row(s, QaInspectionPlanRow, body.plan_id, what="Inspection plan")
        if plan.status != "approved":
            raise ApiError(422, "VALIDATION_ERROR", "Inspection lots need an approved plan.", {"errors": [
                {"loc": ["body", "plan_id"], "msg": "plan not approved", "type": "value_error"}]})
        if body.lot_id:
            lot = s.get(MfgLotRow, body.lot_id)
            if lot is None or lot.item_id != plan.item_id:
                raise unknown_ref(["body", "lot_id"], body.lot_id, "Lot of the plan's item")
        if body.wo_id and s.get(MfgWorkOrderRow, body.wo_id) is None:
            raise unknown_ref(["body", "wo_id"], body.wo_id, "Work order")
        r = create_lot_in(s, plan, lot_size=body.lot_size, source="manual", actor=a.user_id, lot_id=body.lot_id,
                          wo_id=body.wo_id, hold=body.hold, note=body.note)
        return lot_record(s, r, True)


def _lock_lot(s: Session, lot_id: str) -> QaInspectionLotRow:
    return repo.get_row(s, QaInspectionLotRow, lot_id, what="Inspection lot", lock=True)


def _req_hash(body: ResultsBatch) -> str:
    return hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def post_results(ctx: AppContext, a: Act, lot_id: str, body: ResultsBatch) -> dict[str, Any]:
    h = _req_hash(body)
    with write_tx(ctx, lock=False) as (s, _):
        r = _lock_lot(s, lot_id)
        prev = s.execute(select(QaResultBatchRow).where(QaResultBatchRow.client_batch_id == body.client_batch_id)
                         ).scalars().first()
        if prev is not None:
            if prev.request_hash != h or prev.inspection_lot_id != lot_id:
                raise ApiError(409, "QA_BATCH_CONFLICT", "This client_batch_id was used for different results.",
                               {"client_batch_id": body.client_batch_id})
            return {**prev.response, "replayed": True}
        if r.status not in OPEN_LOT:
            raise ApiError(409, "QA_LOT_DECIDED", f"{r.number} is {r.status}; it takes no more results.",
                           {"status": r.status})
        chars = {c.id: c for c in _chars(s, r.plan_id)}
        now = _db_now(s)
        today_ = now.date()
        eq_cache: dict[str, QaEquipmentRow | None] = {}
        existing = {x.id: x for x in _results(s, r.id)}
        current = {(x.characteristic_id, x.sample_no): x for x in existing.values() if not x.superseded}
        new_rows: list[QaResultRow] = []
        for i, x in enumerate(body.results):
            loc = ["body", "results", i]
            c = chars.get(x.characteristic_id)
            sp = (r.sampling or {}).get(x.characteristic_id)
            if c is None or sp is None:
                raise unknown_ref(loc + ["characteristic_id"], x.characteristic_id, "Characteristic of this lot")
            if not 1 <= x.sample_no <= int(sp["n"]):
                raise ApiError(422, "QA_SAMPLE_OUT_OF_RANGE", f"{c.code}: sample numbers run from 1 to {sp['n']}.",
                               {"loc": loc + ["sample_no"], "n": sp["n"]})
            if c.kind == "variable" and x.value is None:
                raise ApiError(422, "VALIDATION_ERROR", f"{c.code} is measured: give a value.",
                               {"errors": [{"loc": loc + ["value"], "msg": "value required", "type": "value_error"}]})
            if c.kind == "attribute" and x.passed is None:
                raise ApiError(422, "VALIDATION_ERROR", f"{c.code} is pass/fail: give passed.",
                               {"errors": [{"loc": loc + ["passed"], "msg": "passed required",
                                            "type": "value_error"}]})
            if c.equipment_class:
                if x.equipment_id is None:
                    raise ApiError(422, "VALIDATION_ERROR", f"{c.code} needs the gauge used ({c.equipment_class}).",
                                   {"errors": [{"loc": loc + ["equipment_id"], "msg": "equipment required",
                                                "type": "value_error"}]})
                if x.equipment_id not in eq_cache:
                    eq_cache[x.equipment_id] = s.get(QaEquipmentRow, x.equipment_id)
                e = eq_cache[x.equipment_id]
                if e is None or e.equipment_class != c.equipment_class:
                    raise unknown_ref(loc + ["equipment_id"], x.equipment_id, f"{c.equipment_class} equipment")
                if not eq_valid(e, today_):
                    raise ApiError(409, "QA_EQUIPMENT_NOT_CALIBRATED", f"{e.code} is not in calibration.",
                                   {"equipment": {"id": e.id, "code": e.code}, "due_on": jsonable(e.due_on),
                                    "status": e.status, "loc": loc})
            key = (x.characteristic_id, x.sample_no)
            if x.corrects_result_id is not None:
                old = existing.get(x.corrects_result_id)
                if old is None or (old.characteristic_id, old.sample_no) != key or old.superseded:
                    raise unknown_ref(loc + ["corrects_result_id"], x.corrects_result_id, "Current result")
                old.superseded = True
            elif key in current:
                raise ApiError(409, "QA_RESULT_EXISTS", f"{c.code} sample {x.sample_no} has a result; correct it "
                               "with corrects_result_id and a reason.", {"loc": loc, "result_id": current[key].id})
            passed = not EV.defective(c.kind, x.value, x.passed, c.lsl, c.usl)
            if c.kind == "attribute" and x.defects:
                passed = passed and x.defects == 0
            row = QaResultRow(id=new_id("irs_"), inspection_lot_id=r.id, characteristic_id=c.id,
                              sample_no=x.sample_no, value=x.value, passed=passed,
                              defects=int(x.defects or (0 if passed else 1)), equipment_id=x.equipment_id,
                              note=x.note, reason=x.reason, entered_by=a.user_id, entered_at=now,
                              corrects_result_id=x.corrects_result_id, superseded=False,
                              client_batch_id=body.client_batch_id, owner_id=r.owner_id)
            new_rows.append(row)
            current[key] = row
            existing[row.id] = row
        s.add_all(new_rows)
        s.flush()
        v = _verdict(s, r, list(existing.values()))
        r.verdict = v
        r.status = "ready" if v["verdict"] != "pending" else "in_progress"
        touch(r)
        s.flush()
        from .common import audit

        audit(s, "inspection_lot", r.id, "results", {"count": len(new_rows), "batch": body.client_batch_id,
                                                     "verdict": v["verdict"],
                                                     "corrections": sum(1 for x in new_rows if x.corrects_result_id)})
        resp = jsonable({"inspection_lot_id": r.id, "client_batch_id": body.client_batch_id,
                         "accepted": len(new_rows), "replayed": False,
                         "results": [result_record(x) for x in new_rows], "verdict": v, "status": r.status,
                         "row_version": r.row_version})
        s.add(QaResultBatchRow(id=new_id("irb_"), client_batch_id=body.client_batch_id, inspection_lot_id=r.id,
                               request_hash=h, response=resp, created_at=now, owner_id=r.owner_id))
        s.flush()
        return resp


def _usable_ncr(s: Session, r: QaInspectionLotRow, ncr_id: str | None) -> bool:
    from ..db_models_m7 import QaNcrDispositionRow, QaNcrRow

    if not ncr_id:
        return False
    n = s.get(QaNcrRow, ncr_id)
    if n is None or n.status not in ("approved", "implemented", "closed"):
        return False
    if not (n.inspection_lot_id == r.id or (r.lot_id is not None and n.lot_id == r.lot_id)):
        return False
    return s.execute(select(QaNcrDispositionRow.id).where(QaNcrDispositionRow.ncr_id == n.id,
                                                          QaNcrDispositionRow.kind == "use_as_is").limit(1)
                     ).first() is not None


def _update_switching(s: Session, r: QaInspectionLotRow, plan: QaInspectionPlanRow, decision: str) -> None:
    sch = s.get(QaSamplingSchemeRow, plan.scheme_id)
    if sch is None or not sch.switching:
        return
    sup = r.supplier_id if plan.scope == "incoming" else None
    st = _switch_state(s, plan, sup, lock=True)
    if st is None:
        now = utcnow()
        st = QaSwitchingStateRow(id=new_id("qss_"), plan_key=_switch_key(plan, sup), plan_number=plan.number,
                                 item_id=plan.item_id, supplier_id=sup, state="normal", history=[], row_version=1,
                                 created_at=now, updated_at=now)
        s.add(st)
    hist = (list(st.history or []) + ["A" if decision == "accept" else "R"])[-10:]
    rules = (sch.table or {}).get("switching") if sch.kind == "table" else None
    new = SMP.next_state(st.state, hist, rules)
    if new != st.state:
        hist = hist[-1:] if new == "tightened" else []      # each state counts from its switch
    st.state, st.history = new, hist
    touch(st)
    s.flush()


def decide(ctx: AppContext, a: Act, lot_id: str, body: DecisionInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with read_tx(ctx) as s:
        pre = repo.get_row(s, QaInspectionLotRow, lot_id, what="Inspection lot")
        action = "decide_final" if pre.scope == "final" else "decide"
    auth = esig.authenticate(ctx, a, "inspection_lot", action, body.signature)
    with write_tx(ctx, lock=False) as (s, _):
        r = _lock_lot(s, lot_id)
        if if_match is not None:
            check_version(r, if_match)
        if r.status not in OPEN_LOT:
            raise ApiError(409, "QA_LOT_DECIDED", f"{r.number} is already {r.status}.", {"status": r.status})
        v = _verdict(s, r)
        if body.decision == "accept":
            if v["verdict"] == "pending":
                raise ApiError(409, "QA_LOT_NOT_READY", "Not all samples are entered yet.", {"verdict": v})
            if v["verdict"] == "reject" and not _usable_ncr(s, r, body.ncr_id):
                raise ApiError(409, "QA_DECISION_CONTRADICTS", "The verdict is reject: accept only with an approved "
                               "NCR that dispositions this lot use-as-is.", {"verdict": "reject"})
        out = esig.sign(s, a, auth, "inspection_lot", r.id, action, body.signature, decision=body.decision)
        if out.pending is not None:
            return out.pending
        sig_id = out.signature_ids[-1] if out.signature_ids else None
        before = lot_content(s, r)
        plan = s.get(QaInspectionPlanRow, r.plan_id)
        now = _db_now(s)
        r.verdict, r.decision, r.decided_by, r.decided_at = v, body.decision, a.user_id, now
        r.decision_note = body.note[:500]
        if body.decision == "accept":
            r.status = "accepted"
            if body.ncr_id:
                r.ncr_id = body.ncr_id
            if r.hold:
                from .qa_holds import release_source

                release_source(s, "inspection", r.id, a.user_id, f"Accepted ({r.number})", sig_id)
        else:
            r.status = "rejected"
            from .qa_ncr import create_from_inspection

            ncr = create_from_inspection(s, r, plan, a.user_id)
            r.ncr_id = ncr.id
        touch(r)
        s.flush()
        if plan is not None:
            _update_switching(s, r, plan, body.decision)
        audit_regulated(s, "inspection_lot", r.id, "decision", before=before, after=lot_content(s, r),
                        reason=_why(body) if body.signature or body.note else f"Usage decision: {body.decision}",
                        record_version=r.row_version, signature_id=sig_id)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.inspection_decided", {"id": r.id, "number": r.number, "decision": r.decision,
                                                     "item_id": r.item_id, "lot_id": r.lot_id, "ncr_id": r.ncr_id,
                                                     "scope": r.scope}, r.number)
        return lot_record(s, r, True)


def cancel_lot(ctx: AppContext, a: Act, lot_id: str, body: CancelInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated

    with write_tx(ctx, lock=False) as (s, _):
        r = _lock_lot(s, lot_id)
        if if_match is not None:
            check_version(r, if_match)
        if r.status not in OPEN_LOT:
            raise _invalid_state("inspection lot", r.status, "cancelled")
        before = lot_content(s, r)
        r.status = "cancelled"
        touch(r)
        if r.hold:
            from .qa_holds import release_source

            release_source(s, "inspection", r.id, a.user_id, f"Inspection lot {r.number} cancelled: {body.reason}")
        s.flush()
        audit_regulated(s, "inspection_lot", r.id, "cancel", before=before, after=lot_content(s, r),
                        reason=body.reason, record_version=r.row_version)
        return lot_record(s, r, True)


# ---------------------------------------------------------------- hooks (5.2 triggers)

def on_posting(s: Session, posting: Any) -> list[str]:
    """PO receipts -> incoming lots (+ inspection hold); WO receipts -> final lots per (WO, lot) (+ hold).
    Called in the posting's transaction (after the ledger rows). Returns the created/extended lot ids."""
    from ..db_models_m2 import MfgInvTransactionRow, MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow
    from .m2util import today

    if posting.type not in ("po_receipt", "wo_receipt"):
        return []
    has_plans = s.execute(select(QaInspectionPlanRow.id).where(QaInspectionPlanRow.status == "approved",
                                                              QaInspectionPlanRow.scope.in_(("incoming", "final")))
                          .limit(1)).first()
    if has_plans is None:
        return []
    rows = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == posting.id,
                                                            MfgInvTransactionRow.qty > 0)
                          .order_by(MfgInvTransactionRow.line_no)).scalars())
    d = today(s)
    out: list[str] = []
    agg: dict[tuple[str, str | None, str | None], float] = {}
    meta: dict[tuple[str, str | None, str | None], tuple[str | None, str | None]] = {}
    for t in rows:
        sup = None
        if posting.type == "po_receipt" and t.schedule_id:
            sc = s.get(MfgPurchaseScheduleRow, t.schedule_id)
            ln = s.get(MfgPurchaseLineRow, sc.line_id) if sc else None
            doc = s.get(MfgPurchaseDocRow, ln.doc_id) if ln else None
            sup = doc.supplier_id if doc else None
        k = (t.item_id, t.lot_id, t.wo_id)
        agg[k] = agg.get(k, 0.0) + float(t.qty)
        meta[k] = (sup, t.location_id)
    for (item_id, lot_id, wo_id), qty in agg.items():
        sup, _loc = meta[(item_id, lot_id, wo_id)]
        if posting.type == "po_receipt":
            plan = find_plan(s, item_id, "incoming", d, supplier_id=sup)
            if plan is None or lot_id is None:
                continue
            r = create_lot_in(s, plan, lot_size=qty, source="po_receipt", actor=posting.actor_id, lot_id=lot_id,
                              posting_id=posting.id, supplier_id=sup, hold=True)
            out.append(r.id)
        else:
            wo = s.get(MfgWorkOrderRow, wo_id) if wo_id else None
            customer = _wo_customer(s, wo)
            plan = find_plan(s, item_id, "final", d, customer=customer)
            if plan is None or lot_id is None:
                continue
            ex = s.execute(select(QaInspectionLotRow).where(
                QaInspectionLotRow.wo_id == wo_id, QaInspectionLotRow.lot_id == lot_id,
                QaInspectionLotRow.scope == "final").order_by(QaInspectionLotRow.created_at.desc()).limit(1)
                .with_for_update()).scalars().first()
            if ex is not None and ex.status in OPEN_LOT:
                ex.lot_size = round(ex.lot_size + qty, 6)
                ex.sampling = freeze_sampling(s, plan, ex.lot_size, None) if not _results(s, ex.id) else ex.sampling
                touch(ex)
                ex.verdict = _verdict(s, ex)
                out.append(ex.id)
                continue
            if ex is not None and ex.status in ("accepted", "rejected"):
                lot = s.get(MfgLotRow, lot_id)
                raise ApiError(409, "QA_LOT_DECIDED", f"Lot {lot.lot_code if lot else lot_id} of "
                               f"{wo.number if wo else ''} was already decided by {ex.number}; receive into a new "
                               "lot code.", {"inspection_lot_id": ex.id})
            r = create_lot_in(s, plan, lot_size=qty, source="wo_receipt", actor=posting.actor_id, lot_id=lot_id,
                              wo_id=wo_id, customer=customer, hold=True)
            out.append(r.id)
    return out


def _wo_customer(s: Session, wo: Any) -> str | None:
    if wo is None or not wo.demand_line_id:
        return None
    from ..db_models_m2 import MfgDemandLineRow, MfgDemandOrderRow

    dl = s.get(MfgDemandLineRow, wo.demand_line_id)
    do = s.get(MfgDemandOrderRow, dl.order_id) if dl else None
    return getattr(do, "customer", None) if do else None


def _gate(s: Session, wo: Any, seq: int) -> bool:
    if not wo.routing_id:
        return False
    return bool(s.execute(select(MfgOperationRow.inspection_gate).where(MfgOperationRow.routing_id == wo.routing_id,
                                                                        MfgOperationRow.seq == seq)).scalar())


def gate_lot(s: Session, op_id: str) -> QaInspectionLotRow | None:
    return s.execute(select(QaInspectionLotRow).where(QaInspectionLotRow.wo_operation_id == op_id,
                                                      QaInspectionLotRow.status != "cancelled")
                     .order_by(QaInspectionLotRow.created_at.desc()).limit(1)).scalars().first()


def floor_before(s: Session, wo: Any, op: Any, event_type: str) -> None:
    """A gate operation cannot complete before its in-process lot is accepted (or its NCR implemented)."""
    if event_type != "complete" or not _gate(s, wo, op.seq):
        return
    r = gate_lot(s, op.id)
    if r is None or r.status == "accepted":
        return
    if r.status == "rejected" and r.ncr_id:
        from ..db_models_m7 import QaNcrRow

        n = s.get(QaNcrRow, r.ncr_id)
        if n is not None and n.status in ("implemented", "closed"):
            return
    raise ApiError(409, "QA_INSPECTION_OPEN", f"Inspection {r.number} must be accepted before operation {op.seq} "
                   "completes.", {"inspection_lot_id": r.id, "number": r.number, "status": r.status})


def floor_after(s: Session, wo: Any, op: Any, event: Any, qty_input: float) -> str | None:
    """First start of a gate operation with an effective in-process plan -> an in-process inspection lot."""
    from .m2util import today

    if event.event_type != "start" or not _gate(s, wo, op.seq) or gate_lot(s, op.id) is not None:
        return None
    plan = find_plan(s, wo.item_id, "in_process", today(s), operation_seq=op.seq)
    if plan is None:
        return None
    r = create_lot_in(s, plan, lot_size=max(1.0, qty_input), source="floor", actor=event.actor_id, wo_id=wo.id,
                      wo_operation_id=op.id)
    return r.id


__getattr__ = m7_examples.module_getattr(__name__)
