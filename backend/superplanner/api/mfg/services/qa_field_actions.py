"""Field actions (M7-DESIGN 7) built on M5 recall reports: the scope is frozen from the recall snapshot at creation
(units = finished serials and lots with customer and demand line; in-stock lots). `approve` (signed) places
`field_action` holds on the affected in-stock lots and sets `in_progress`; unit statuses are updated single/bulk
(<= 1,000) or from CSV by serial/lot code; effectiveness = share of units acknowledged or later, per customer and
overall; `complete` when no pending/notified units (or with a reason); `close` (signed) releases its holds."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa.model import (UNIT_DONE, ApproveInput, CancelInput, FaCompleteInput, FieldActionInput,
                          FieldActionUpdate, UnitsBulkInput)
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models_m2 import MfgLotRow
from ..db_models_m5 import MfgRecallRow
from ..db_models_m7 import QaFieldActionRow, QaFieldActionUnitRow
from . import m7_examples
from .common import check_version, ilike, read_tx, touch, write_tx
from .qa_common import Act, decorate, next_number

STATUSES = ("pending", "notified", "acknowledged", "returned", "corrected", "destroyed", "not_reachable")


def _units(s: Session, fa_id: str) -> list[QaFieldActionUnitRow]:
    return list(s.execute(select(QaFieldActionUnitRow).where(QaFieldActionUnitRow.field_action_id == fa_id)
                          .order_by(QaFieldActionUnitRow.customer, QaFieldActionUnitRow.code)).scalars())


def unit_record(u: QaFieldActionUnitRow) -> dict[str, Any]:
    return {"id": u.id, "kind": u.kind, "serial_id": u.serial_id, "lot_id": u.lot_id, "code": u.code,
            "item_id": u.item_id, "customer": u.customer, "demand_line_id": u.demand_line_id, "qty": u.qty,
            "in_stock": u.in_stock, "status": u.status, "note": u.note, "updated_by": u.updated_by,
            "updated_at": u.updated_at}


def effectiveness(units: list[QaFieldActionUnitRow]) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {}
    for u in units:
        if u.in_stock:
            continue
        b = by.setdefault(u.customer or "(none)", {"customer": u.customer or "(none)", "done": 0, "total": 0})
        b["total"] += 1
        b["done"] += u.status in UNIT_DONE
    for b in by.values():
        b["pct"] = round(100.0 * b["done"] / b["total"], 1) if b["total"] else 0.0
    done = sum(b["done"] for b in by.values())
    total = sum(b["total"] for b in by.values())
    return {"overall": {"done": done, "total": total, "pct": round(100.0 * done / total, 1) if total else 0.0},
            "by_customer": sorted(by.values(), key=lambda x: x["customer"])}


def content(s: Session, r: QaFieldActionRow) -> dict[str, Any]:
    units = _units(s, r.id)
    return {"id": r.id, "number": r.number, "title": r.title, "kind": r.kind, "class": r.class_,
            "regimes": r.regimes, "strategy": r.strategy, "recall_id": r.recall_id, "status": r.status,
            "units": len(units), "units_by_status": {st: sum(1 for u in units if u.status == st) for st in STATUSES
                                                     if any(u.status == st for u in units)},
            "in_stock_lots": sorted({u.code for u in units if u.in_stock})}


def _loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaFieldActionRow, rid, what="Field action", lock=lock)
    c = content(s, r)
    return C.Loaded(r, c, r.row_version, r.author_id, [("Field action", f"{r.number} - {r.title}"),
                                                       ("Kind", r.kind), ("Units", str(c["units"]))])


C.register("field_action", _loader)


def record(s: Session, r: QaFieldActionRow, full: bool = False) -> dict[str, Any]:
    rc = s.get(MfgRecallRow, r.recall_id)
    units = _units(s, r.id)
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "number": r.number, "title": r.title, "kind": r.kind, "class": r.class_, "regimes": r.regimes,
           "strategy": r.strategy, "recall_id": r.recall_id, "recall_number": rc.number if rc else None,
           "status": r.status, "complete_reason": r.complete_reason, "author_id": r.author_id,
           "closed_at": r.closed_at, "units_total": len(units), "effectiveness": effectiveness(units),
           "signatures": [], "links": [], "attachments": []}
    if full:
        decorate(s, rec, "field_action", "field_action")
    return rec


def list_field_actions(ctx: AppContext, q: str | None, status: str | None, sort: str | None, limit: int,
                       offset: int) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(or_(ilike(QaFieldActionRow.number, q), ilike(QaFieldActionRow.title, q)))
    if status:
        conds.append(QaFieldActionRow.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(QaFieldActionRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaFieldActionRow).where(*conds).order_by(QaFieldActionRow.created_at.desc(),
                                                                        QaFieldActionRow.id)
                         .limit(limit).offset(offset)).scalars()
        return {"items": [record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def get_field_action(ctx: AppContext, fa_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, repo.get_row(s, QaFieldActionRow, fa_id, what="Field action"), True)


def _scope_units(s: Session, fa: QaFieldActionRow, rep: dict[str, Any]) -> int:
    """Units from the recall snapshot: shipped serials (customer), shipments of lots (customer, demand line,
    lots on their path), in-stock lots."""
    now = utcnow()
    n = 0
    seen: set[tuple[str, str, str]] = set()

    def add(**kw: Any) -> None:
        nonlocal n
        key = (kw["kind"], kw["code"], kw.get("demand_line_id") or kw["customer"])
        if key in seen:
            return
        seen.add(key)
        s.add(QaFieldActionUnitRow(id=new_id("fau_"), field_action_id=fa.id, status="pending", note="",
                                   updated_by=None, updated_at=now, owner_id=fa.owner_id, **kw))
        n += 1

    item_ids = {}
    for u in rep.get("units", []):
        if u.get("status") in ("consumed",):
            continue
        add(kind="serial", serial_id=u["serial_id"], lot_id=None, code=u.get("serial") or u["serial_id"],
            item_id=u.get("item_id") or u.get("item") or "", customer=u.get("customer") or "", demand_line_id=None,
            qty=1.0, in_stock=not u.get("customer"))
    for sh in rep.get("shipments", []):
        lots_on_path = [x for x in (sh.get("lots") or [])]
        code = (lots_on_path[0] if lots_on_path else None) or sh.get("demand_order") or sh["demand_line_id"]
        add(kind="lot", serial_id=None, lot_id=None, code=str(code)[:64], item_id=sh.get("item") or "",
            customer=sh.get("customer") or "", demand_line_id=sh["demand_line_id"], qty=float(sh.get("qty") or 0),
            in_stock=False)
    for lt in rep.get("lots", []):
        if (lt.get("on_hand") or 0) <= 0:
            continue
        item_ids[lt["lot_id"]] = lt.get("item_id")
        add(kind="lot", serial_id=None, lot_id=lt["lot_id"], code=lt["lot_code"], item_id=lt.get("item_id") or "",
            customer="", demand_line_id=None, qty=float(lt["on_hand"]), in_stock=True)
    s.flush()
    return n


def create_field_action(ctx: AppContext, a: Act, body: FieldActionInput) -> dict[str, Any]:
    from .common import audit

    with write_tx(ctx) as (s, _plant):
        rc = repo.get_row(s, MfgRecallRow, body.recall_id, what="Recall")
        now = utcnow()
        r = QaFieldActionRow(id=new_id("fac_"), number=next_number(s, "FA", QaFieldActionRow), title=body.title,
                             kind=body.kind, class_=body.class_, regimes=list(body.regimes), strategy=body.strategy,
                             recall_id=rc.id, status="draft", complete_reason=None, author_id=a.user_id,
                             closed_at=None, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        n = _scope_units(s, r, rc.report or {})
        audit(s, "field_action", r.id, "create", {"number": r.number, "recall": rc.number, "units": n})
        return record(s, r, True)


def update_field_action(ctx: AppContext, a: Act, fa_id: str, body: FieldActionUpdate, if_match: str | None
                        ) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action", lock=True)
        check_version(r, if_match)
        if r.status in ("closed", "cancelled"):
            raise esig.locked_error(r.number)
        before = content(s, r)
        esig.supersede_pending(s, "field_action", r.id, r.row_version)
        r.title, r.kind, r.class_, r.regimes, r.strategy = body.title, body.kind, body.class_, list(body.regimes), \
            body.strategy
        touch(r)
        s.flush()
        audit_regulated(s, "field_action", r.id, "update", before=before, after=content(s, r),
                        record_version=r.row_version)
        return record(s, r, True)


def _move(s: Session, r: QaFieldActionRow, to: str, action: str, reason: str | None, sig: str | None = None) -> None:
    from ...audit_diff import audit_regulated

    before = r.status
    r.status = to
    touch(r)
    s.flush()
    audit_regulated(s, "field_action", r.id, action, before={"status": before}, after={"status": to},
                    reason=reason, record_version=r.row_version, signature_id=sig)


def _why(body: Any) -> str | None:
    sig = getattr(body, "signature", None)
    return (sig.comment.strip() if sig is not None and sig.comment.strip() else None) or \
        ((getattr(body, "note", "") or "").strip() or None)


def approve(ctx: AppContext, a: Act, fa_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    from . import esig
    from .qa_holds import place

    auth = esig.authenticate(ctx, a, "field_action", "approve", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "draft":
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} field action cannot be approved.",
                           {"status": r.status})
        out = esig.sign(s, a, auth, "field_action", r.id, "approve", body.signature)
        if out.pending is not None:
            return out.pending
        sig = out.signature_ids[-1] if out.signature_ids else None
        for u in _units(s, r.id):
            if u.in_stock and u.lot_id and s.get(MfgLotRow, u.lot_id) is not None:
                place(s, source="field_action", source_id=r.id, reason=f"Field action {r.number}", actor=a.user_id,
                      lot_id=u.lot_id)
            elif u.in_stock and u.serial_id:
                place(s, source="field_action", source_id=r.id, reason=f"Field action {r.number}", actor=a.user_id,
                      serial_id=u.serial_id)
        _move(s, r, "in_progress", "approve", _why(body), sig)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.field_action.approved", {"id": r.id, "number": r.number}, r.number)
        return record(s, r, True)


def list_units(ctx: AppContext, fa_id: str, status: str | None, customer: str | None, limit: int, offset: int
               ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        repo.get_row(s, QaFieldActionRow, fa_id, what="Field action")
        conds = [QaFieldActionUnitRow.field_action_id == fa_id]
        if status:
            conds.append(QaFieldActionUnitRow.status == status)
        if customer:
            conds.append(ilike(QaFieldActionUnitRow.customer, customer))
        total = int(s.execute(select(func.count()).select_from(QaFieldActionUnitRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaFieldActionUnitRow).where(*conds).order_by(
            QaFieldActionUnitRow.customer, QaFieldActionUnitRow.code, QaFieldActionUnitRow.id).limit(limit)
            .offset(offset)).scalars()
        return {"items": [unit_record(u) for u in rows], "total": total, "limit": limit, "offset": offset}


def bulk_units(ctx: AppContext, a: Act, fa_id: str, body: UnitsBulkInput) -> dict[str, Any]:
    from .common import audit

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action", lock=True)
        if r.status != "in_progress":
            raise ApiError(409, "MFG_INVALID_STATE", "Unit statuses change while the field action is in progress.",
                           {"status": r.status})
        units = {u.id: u for u in _units(s, r.id)}
        by_code: dict[str, list[QaFieldActionUnitRow]] = {}
        for u in units.values():
            by_code.setdefault(u.code, []).append(u)
        items = [(x.unit_id, x.status, x.note) for x in body.items]
        errors: list[dict[str, Any]] = []
        if body.csv:
            for i, row in enumerate(csv.reader(io.StringIO(body.csv))):
                if not row or (i == 0 and row[0].strip().lower() in ("code", "serial", "lot")):
                    continue
                code, st = row[0].strip(), (row[1].strip() if len(row) > 1 else "")
                note = row[2].strip() if len(row) > 2 else ""
                hits = by_code.get(code, [])
                if not hits or st not in STATUSES:
                    errors.append({"line": i + 1, "code": code, "error": "unknown code" if not hits else
                                   "unknown status"})
                    continue
                items += [(u.id, st, note) for u in hits]
        if len(items) > 1000:
            raise ApiError(422, "MFG_LIMIT", "At most 1,000 units per request.", {"limit": 1000})
        now = utcnow()
        changed = 0
        for uid, st, note in items:
            u = units.get(uid)
            if u is None:
                errors.append({"unit_id": uid, "error": "unknown unit"})
                continue
            if u.status != st or note:
                u.status, u.note, u.updated_by, u.updated_at = st, (note or u.note)[:500], a.user_id, now
                changed += 1
        touch(r)
        s.flush()
        audit(s, "field_action", r.id, "units", {"changed": changed, "errors": len(errors)})
        return {**record(s, r, True), "changed": changed, "errors": errors}


def complete(ctx: AppContext, a: Act, fa_id: str, body: FaCompleteInput, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "in_progress":
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} field action cannot be completed.",
                           {"status": r.status})
        left = [u.code for u in _units(s, r.id) if u.status in ("pending", "notified") and not u.in_stock]
        if left and not body.reason:
            raise ApiError(409, "QA_UNITS_OPEN", f"{len(left)} unit(s) are still pending or notified; complete with a "
                           "reason.", {"open": left[:50]})
        r.complete_reason = body.reason
        _move(s, r, "completed", "complete", body.reason)
        return record(s, r, True)


def close(ctx: AppContext, a: Act, fa_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    from . import esig
    from .qa_holds import release_source

    auth = esig.authenticate(ctx, a, "field_action", "close", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "completed":
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} field action cannot be closed.",
                           {"status": r.status})
        out = esig.sign(s, a, auth, "field_action", r.id, "close", body.signature)
        if out.pending is not None:
            return out.pending
        sig = out.signature_ids[-1] if out.signature_ids else None
        release_source(s, "field_action", r.id, a.user_id, f"Field action {r.number} closed", sig)
        r.closed_at = utcnow()
        _move(s, r, "closed", "close", _why(body), sig)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.field_action.closed", {"id": r.id, "number": r.number}, r.number)
        return record(s, r, True)


def cancel(ctx: AppContext, a: Act, fa_id: str, body: CancelInput, if_match: str | None) -> dict[str, Any]:
    from .qa_holds import release_source

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "draft":                      # review M8: after approval only the signed close releases
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} field action cannot be cancelled.",
                           {"status": r.status})
        release_source(s, "field_action", r.id, a.user_id, f"Field action {r.number} cancelled")
        _move(s, r, "cancelled", "cancel", body.reason)
        return record(s, r, True)


def export(ctx: AppContext, fa_id: str, fmt: str) -> tuple[bytes, str, str]:
    with read_tx(ctx) as s:
        r = repo.get_row(s, QaFieldActionRow, fa_id, what="Field action")
        rec = record(s, r)
        units = [unit_record(u) for u in _units(s, r.id)]
        number = r.number
    from .common import jsonable

    if fmt == "json":
        return (json.dumps(jsonable({"field_action": rec, "units": units}), ensure_ascii=False, indent=1).encode(),
                f"{number}.json", "application/json")
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Units"
    cols = ["code", "kind", "customer", "qty", "in_stock", "status", "note", "updated_at"]
    ws.append(cols)
    for u in units:
        ws.append([str(u[c]) if c == "updated_at" and u[c] else u[c] for c in cols])
    eff = wb.create_sheet("Effectiveness")
    eff.append(["customer", "done", "total", "pct"])
    for b in rec["effectiveness"]["by_customer"]:
        eff.append([b["customer"], b["done"], b["total"], b["pct"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"{number}.xlsx", \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


__getattr__ = m7_examples.module_getattr(__name__)
