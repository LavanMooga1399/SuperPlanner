"""NCR / MRB (M7-DESIGN 6).

States `draft -> open -> proposed -> approved -> implemented -> closed` (+ `cancelled` from draft/open/proposed).
Stock NCRs hold their lot (`ncr` hold placed on open); WIP NCRs come from floor `qty_nc`. Implementation moves
material through the existing ledger and floor log only (one transaction):

| kind | stock | WIP |
|---|---|---|
| scrap | `issue_misc` reason `SCRAP` (held lot exempt for this posting) | `nc_disposition` (stays scrap) |
| rework | rework WO (`kind rework`, item 1:1, may consume the held lot) | `nc_disposition` scrap -> rework to seq |
| use_as_is | nothing posted | `nc_disposition` scrap -> good (last op: receipt) |
| return_to_supplier | `issue_misc` reason `RTV` + outbox `qa.rtv` | refused |

WIP nonconforming quantity counts as scrap in the operation state until dispositioned (14). The `ncr` hold is
released when every stock disposition is implemented and no rework WO is open.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa.model import ApproveInput, CancelInput, NcrInput, ProposeInput
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models_m2 import MfgLotRow, MfgWorkOrderRow
from ..db_models_m7 import QaInspectionLotRow, QaNcrDispositionRow, QaNcrRow
from . import m7_examples
from .common import check_version, ilike, read_tx, touch, unknown_ref, write_tx
from .qa_common import Act, decorate, item_ref, next_number

EDITABLE = ("draft", "open", "proposed")
EPS = 1e-6


def _bad_state(r: QaNcrRow, action: str) -> ApiError:
    return ApiError(409, "MFG_INVALID_STATE", f"{r.number} is {r.status}; it cannot be {action}.",
                    {"status": r.status, "action": action})


def _disps(s: Session, ncr_id: str) -> list[QaNcrDispositionRow]:
    return list(s.execute(select(QaNcrDispositionRow).where(QaNcrDispositionRow.ncr_id == ncr_id)
                          .order_by(QaNcrDispositionRow.line_no)).scalars())


def disp_record(d: QaNcrDispositionRow) -> dict[str, Any]:
    return {"id": d.id, "line_no": d.line_no, "kind": d.kind, "qty": d.qty, "location_id": d.location_id,
            "rework_routing_id": d.rework_routing_id, "rework_to_seq": d.rework_to_seq,
            "instructions": d.instructions, "justification": d.justification, "implemented_at": d.implemented_at,
            "refs": d.refs or {}}


def content(s: Session, r: QaNcrRow) -> dict[str, Any]:
    from .qa_common import attachments_of

    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    return {"id": r.id, "number": r.number, "title": r.title, "source": r.source, "severity": r.severity,
            "item_id": r.item_id, "lot_id": r.lot_id, "lot_code": lot.lot_code if lot else None,
            "serial_ids": r.serials or [], "supplier_id": r.supplier_id, "wo_id": r.wo_id,
            "wo_operation_id": r.wo_operation_id, "inspection_lot_id": r.inspection_lot_id, "place": r.place,
            "qty_nc": r.qty_nc, "defect_codes": r.defect_codes or [], "description": r.description,
            "containment": r.containment, "investigation": r.investigation, "capa_required": r.capa_required,
            "dispositions": [{k: v for k, v in disp_record(d).items() if k not in ("implemented_at", "refs", "id")}
                             for d in _disps(s, r.id)],
            "attachments": [x["sha256"] for x in attachments_of(s, "ncr", r.id)]}


def _loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaNcrRow, rid, what="NCR", lock=lock)
    c = content(s, r)
    disp = ", ".join(f"{d['kind'].replace('_', ' ')} {d['qty']:g}" for d in c["dispositions"]) or "-"
    return C.Loaded(r, c, r.row_version, r.author_id, [("NCR", f"{r.number} - {r.title}"),
                                                       ("Quantity", f"{r.qty_nc:g}"), ("Dispositions", disp)])


C.register("ncr", _loader)


def _next_actions(r: QaNcrRow) -> list[str]:
    return {"draft": ["open", "cancel"], "open": ["propose", "cancel"], "proposed": ["approve", "propose", "cancel"],
            "approved": ["implement"], "implemented": ["close"]}.get(r.status, [])


def record(s: Session, r: QaNcrRow, full: bool = False) -> dict[str, Any]:
    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "number": r.number, "title": r.title, "source": r.source, "severity": r.severity, "item_id": r.item_id,
           "item": item_ref(s, r.item_id), "lot_id": r.lot_id, "lot_code": lot.lot_code if lot else None,
           "serial_ids": r.serials or [], "supplier_id": r.supplier_id, "wo_id": r.wo_id,
           "wo_operation_id": r.wo_operation_id, "operation_seq": r.operation_seq,
           "inspection_lot_id": r.inspection_lot_id, "complaint_id": r.complaint_id, "place": r.place,
           "location_id": r.location_id, "qty_nc": r.qty_nc, "defect_codes": r.defect_codes or [],
           "description": r.description, "containment": r.containment, "investigation": r.investigation,
           "status": r.status, "capa_required": r.capa_required, "author_id": r.author_id,
           "closed_at": r.closed_at, "external_ref": r.external_ref, "dispositions": [], "rework_wos": [],
           "next_actions": _next_actions(r), "signatures": [], "links": [], "attachments": []}
    if full:
        rec["dispositions"] = [disp_record(d) for d in _disps(s, r.id)]
        rec["rework_wos"] = [{"id": w.id, "number": w.number, "status": w.status} for w in _rework_wos(s, r.id)]
        decorate(s, rec, "ncr", "ncr")
    return rec


def _rework_wos(s: Session, ncr_id: str) -> list[MfgWorkOrderRow]:
    return list(s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.ncr_id == ncr_id,
                                                        MfgWorkOrderRow.kind == "rework")
                          .order_by(MfgWorkOrderRow.number)).scalars())


SORTS = {"number": QaNcrRow.number, "created_at": QaNcrRow.created_at, "status": QaNcrRow.status}


def list_ncrs(ctx: AppContext, q: str | None, status: str | None, item_id: str | None, place: str | None,
              sort: str | None, limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if q:
        conds.append(or_(ilike(QaNcrRow.number, q), ilike(QaNcrRow.title, q)))
    if status:
        conds.append(QaNcrRow.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    if item_id:
        conds.append(QaNcrRow.item_id == item_id)
    if place:
        conds.append(QaNcrRow.place == place)
    key = (sort or "-created_at").lstrip("-")
    if key not in SORTS:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown sort {sort!r}.", {"errors": [
            {"loc": ["query", "sort"], "msg": "unknown sort", "type": "value_error"}]})
    col = SORTS[key]
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(QaNcrRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(QaNcrRow).where(*conds).order_by(
            col.desc() if (sort or "-created_at").startswith("-") else col.asc(), QaNcrRow.id)
            .limit(limit).offset(offset)).scalars()
        return {"items": [record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def get_ncr(ctx: AppContext, ncr_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, repo.get_row(s, QaNcrRow, ncr_id, what="NCR"), True)


def _new(s: Session, *, title: str, source: str, severity: str, author: str, place: str, qty: float,
         status: str = "draft", **kw: Any) -> QaNcrRow:
    from .common import audit

    now = utcnow()
    vals = {"item_id": None, "lot_id": None, "serials": [], "supplier_id": None, "wo_id": None,
            "wo_operation_id": None, "operation_seq": None, "inspection_lot_id": None, "complaint_id": None,
            "location_id": None, "defect_codes": [], "description": "", "containment": "", "investigation": "",
            "capa_required": False, "external_ref": None, **kw}
    r = QaNcrRow(id=new_id("ncr_"), number=next_number(s, "NCR", QaNcrRow), title=title[:200], source=source,
                 severity=severity, place=place, qty_nc=round(float(qty), 6), status=status, author_id=author,
                 closed_at=None, row_version=1, created_at=now, updated_at=now, **vals)
    s.add(r)
    s.flush()
    audit(s, "ncr", r.id, "create", {"number": r.number, "source": source, "qty_nc": r.qty_nc})
    return r


def _check_refs(s: Session, body: NcrInput) -> None:
    from ..db_models import MfgItemRow

    if body.item_id and s.get(MfgItemRow, body.item_id) is None:
        raise unknown_ref(["body", "item_id"], body.item_id, "Item")
    if body.lot_id:
        lot = s.get(MfgLotRow, body.lot_id)
        if lot is None or (body.item_id and lot.item_id != body.item_id):
            raise unknown_ref(["body", "lot_id"], body.lot_id, "Lot of the item")
    if body.wo_id and s.get(MfgWorkOrderRow, body.wo_id) is None:
        raise unknown_ref(["body", "wo_id"], body.wo_id, "Work order")


def create_ncr(ctx: AppContext, a: Act, body: NcrInput) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        _check_refs(s, body)
        item_id = body.item_id
        if body.lot_id and not item_id:
            item_id = s.get(MfgLotRow, body.lot_id).item_id
        r = _new(s, title=body.title, source=body.source, severity=body.severity, author=a.user_id,
                 place=body.place, qty=body.qty_nc, item_id=item_id, lot_id=body.lot_id, serials=body.serial_ids,
                 supplier_id=body.supplier_id, wo_id=body.wo_id, complaint_id=body.complaint_id,
                 location_id=body.location_id, defect_codes=body.defect_codes, description=body.description,
                 containment=body.containment, investigation=body.investigation, capa_required=body.capa_required,
                 external_ref=body.external_ref)
        if body.complaint_id:
            from .qa_common import add_link

            add_link(s, "complaint", body.complaint_id, "ncr", r.id, a.user_id)
        return record(s, r, True)


def update_ncr(ctx: AppContext, a: Act, ncr_id: str, body: NcrInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        check_version(r, if_match)
        if r.status not in EDITABLE:
            raise esig.locked_error(r.number)
        _check_refs(s, body)
        before = content(s, r)
        esig.supersede_pending(s, "ncr", r.id, r.row_version)
        r.title, r.severity, r.description = body.title, body.severity, body.description
        r.containment, r.investigation, r.capa_required = body.containment, body.investigation, body.capa_required
        r.defect_codes, r.external_ref, r.supplier_id = list(body.defect_codes), body.external_ref, body.supplier_id
        if r.status == "draft":
            r.item_id, r.lot_id, r.serials, r.qty_nc = body.item_id, body.lot_id, list(body.serial_ids), body.qty_nc
            r.place, r.location_id, r.wo_id = body.place, body.location_id, body.wo_id
        touch(r)
        s.flush()
        audit_regulated(s, "ncr", r.id, "update", before=before, after=content(s, r), record_version=r.row_version)
        return record(s, r, True)


def _hold_targets(r: QaNcrRow) -> list[tuple[str | None, str | None]]:
    if r.place != "stock":
        return []
    if r.lot_id:
        return [(r.lot_id, None)]
    return [(None, sid) for sid in (r.serials or [])]


def _place_holds(s: Session, r: QaNcrRow, actor: str) -> None:
    from .qa_holds import place

    for lot_id, serial_id in _hold_targets(r):
        place(s, source="ncr", source_id=r.id, reason=f"{r.number}: {r.title}", actor=actor, lot_id=lot_id,
              serial_id=serial_id)


def _transition(s: Session, r: QaNcrRow, to: str, action: str, reason: str | None = None,
                signature_id: str | None = None) -> None:
    from ...audit_diff import audit_regulated

    before = r.status
    r.status = to
    touch(r)
    s.flush()
    audit_regulated(s, "ncr", r.id, action, before={"status": before}, after={"status": to},
                    reason=reason or f"NCR {action}", record_version=r.row_version, signature_id=signature_id)


def open_ncr(ctx: AppContext, a: Act, ncr_id: str, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        check_version(r, if_match)
        if r.status != "draft":
            raise _bad_state(r, "opened")
        if r.qty_nc <= EPS:
            raise ApiError(422, "VALIDATION_ERROR", "Give the nonconforming quantity.", {"errors": [
                {"loc": ["qty_nc"], "msg": "must be > 0", "type": "value_error"}]})
        _place_holds(s, r, a.user_id)
        _transition(s, r, "open", "open")
        return record(s, r, True)


def propose(ctx: AppContext, a: Act, ncr_id: str, body: ProposeInput, if_match: str | None) -> dict[str, Any]:
    from ..db_models import MfgRoutingRow
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        check_version(r, if_match)
        if r.status not in ("open", "proposed"):
            raise _bad_state(r, "proposed")
        total = round(sum(d.qty for d in body.dispositions), 6)
        if abs(total - r.qty_nc) > EPS:
            raise ApiError(422, "QA_DISPOSITION_QTY", f"Dispositions add up to {total:g}; the NCR has {r.qty_nc:g}.",
                           {"total": total, "qty_nc": r.qty_nc})
        for i, d in enumerate(body.dispositions):
            loc = ["body", "dispositions", i]
            if d.kind == "use_as_is" and not d.justification.strip():
                raise ApiError(422, "QA_JUSTIFICATION_REQUIRED", "Use-as-is needs a justification.",
                               {"loc": loc + ["justification"]})
            if d.kind == "return_to_supplier":
                if r.place == "wip":
                    raise ApiError(422, "VALIDATION_ERROR", "WIP cannot be returned to the supplier.",
                                   {"errors": [{"loc": loc + ["kind"], "msg": "not for WIP", "type": "value_error"}]})
                if not r.supplier_id:
                    raise ApiError(422, "VALIDATION_ERROR", "Return to supplier needs the NCR's supplier.",
                                   {"errors": [{"loc": loc + ["kind"], "msg": "no supplier", "type": "value_error"}]})
            if d.kind == "rework":
                if r.place == "stock":
                    rt = s.get(MfgRoutingRow, d.rework_routing_id) if d.rework_routing_id else None
                    if rt is None:
                        raise ApiError(422, "VALIDATION_ERROR", "Stock rework needs rework_routing_id.",
                                       {"errors": [{"loc": loc + ["rework_routing_id"], "msg": "required",
                                                    "type": "value_error"}]})
                elif d.rework_to_seq is None or (r.operation_seq is not None and d.rework_to_seq > r.operation_seq):
                    raise ApiError(422, "VALIDATION_ERROR", "WIP rework needs rework_to_seq at or before the "
                                   "operation.", {"errors": [{"loc": loc + ["rework_to_seq"], "msg": "invalid",
                                                              "type": "value_error"}]})
            if r.place == "stock" and d.kind in ("scrap", "return_to_supplier") and not (d.location_id or
                                                                                       r.location_id):
                raise ApiError(422, "VALIDATION_ERROR", "Give the location the material is taken from.",
                               {"errors": [{"loc": loc + ["location_id"], "msg": "required", "type": "value_error"}]})
        before = content(s, r)
        esig.supersede_pending(s, "ncr", r.id, r.row_version)
        for d in _disps(s, r.id):
            s.delete(d)
        s.flush()
        now = utcnow()
        for i, d in enumerate(body.dispositions, start=1):
            s.add(QaNcrDispositionRow(id=new_id("ncd_"), ncr_id=r.id, line_no=i, kind=d.kind, qty=d.qty,
                                      location_id=d.location_id or r.location_id,
                                      rework_routing_id=d.rework_routing_id, rework_to_seq=d.rework_to_seq,
                                      instructions=d.instructions, justification=d.justification,
                                      implemented_at=None, refs={}, owner_id=r.owner_id, row_version=1,
                                      created_at=now, updated_at=now))
        r.status = "proposed"
        touch(r)
        s.flush()
        audit_regulated(s, "ncr", r.id, "propose", before=before, after=content(s, r), reason="Dispositions proposed",
                        record_version=r.row_version)
        return record(s, r, True)


def approve(ctx: AppContext, a: Act, ncr_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    from . import esig

    auth = esig.authenticate(ctx, a, "ncr", "approve", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "proposed":
            raise _bad_state(r, "approved")
        out = esig.sign(s, a, auth, "ncr", r.id, "approve", body.signature)
        if out.pending is not None:
            return out.pending
        _transition(s, r, "approved", "approve", _why(body), out.signature_ids[-1] if out.signature_ids else None)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.ncr.approved", {"id": r.id, "number": r.number}, r.number)
        return record(s, r, True)


def _why(body: Any) -> str:
    sig = getattr(body, "signature", None)
    return (sig.comment.strip() if sig is not None and sig.comment.strip() else "") or \
        (getattr(body, "note", "") or "").strip() or "Signed action"


# ---------------------------------------------------------------- implementation (ledger / floor)

def _issue(s: Session, r: QaNcrRow, d: QaNcrDispositionRow, reason: str) -> str:
    from ....mfg.model_m2 import IssueMiscLine, IssueMiscPosting
    from .inventory import post_in_session

    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    inp = IssueMiscPosting.model_construct(
        type="issue_misc", txn_date=None, note=f"{r.number} {d.kind.replace('_', ' ')}", reason_code=reason,
        lines=[IssueMiscLine.model_construct(item_id=r.item_id, location_id=d.location_id,
                                             lot_code=lot.lot_code if lot else None, qty=d.qty)])
    exempt = {(r.item_id, lot.lot_code)} if lot else set()
    row, _w = post_in_session(s, inp, hold_exempt=exempt, ncr_id=r.id)
    return row.id


def _rework_wo(s: Session, r: QaNcrRow, d: QaNcrDispositionRow, actor: str) -> MfgWorkOrderRow:
    from ....mfg.model_m2 import WoComponentInput, WorkOrderInput
    from .m2util import today
    from .workorders import new_wo

    d0 = today(s)
    inp = WorkOrderInput.model_construct(
        number=None, item_id=r.item_id, qty=d.qty, due_date=d0 + timedelta(days=7), start_date=d0, priority=3,
        serial_from=None, serial_to=None, demand_line_id=None, note=f"Rework {r.number}", external_ref=None,
        components=[WoComponentInput.model_construct(id=None, item_id=r.item_id, required_qty=d.qty,
                                                     operation_seq=None, find_number=None, note=f"{r.number}")],
        receipt_location_id=d.location_id)
    w, _warn = new_wo(s, None, inp, source="manual", status="planned", routing_id=d.rework_routing_id,
                      generated=SimpleNamespace(bom_id=None, routing_id=d.rework_routing_id, components=[]))
    w.kind, w.ncr_id = "rework", r.id
    s.flush()
    return w


def _nc_event(s: Session, r: QaNcrRow, d: QaNcrDispositionRow, actor: str) -> str:
    """WIP: one append-only `nc_disposition` floor event; operation states and receipts follow the log."""
    from ..db_models import MfgItemRow
    from ..db_models_m4 import MfgFloorEventRow
    from . import floor, floor_effects

    now = utcnow()
    wo = floor.lock_wo(s, r.wo_id)
    rows = floor.wo_rows(s, wo.id, lock=True)
    op = next((x for x in rows if x.id == r.wo_operation_id), None)
    if op is None:
        raise ApiError(409, "MFG_INVALID_STATE", "The NCR's operation no longer exists.", {})
    events = floor.wo_events(s, wo.id)
    before = floor.replay_wo(rows, events)
    q = d.qty
    vals = {"scrap": (0.0, 0.0, None), "rework": (0.0, -q, q), "use_as_is": (q, -q, None)}[d.kind]
    ev = MfgFloorEventRow(id=new_id("fev_"), wo_operation_id=op.id, wo_id=wo.id, event_type="nc_disposition",
                          event_at=now, recorded_at=now, line_id=None, operator_ids=[], qty_good=vals[0] or None,
                          qty_scrap=vals[1] or None, qty_rework=vals[2], rework_to_seq=d.rework_to_seq if
                          d.kind == "rework" else None, reason_code=None, note=f"{r.number} {d.kind}",
                          client_event_id=None, batch_load_id=None, serials=None, corrects_event_id=None,
                          forced=None, details={"ncr_id": r.id, "disposition": d.kind}, actor_id=actor, ncr_id=r.id,
                          qty_nc=None, defect_code=None)
    s.add(ev)
    s.flush()
    events.append(ev)
    after = floor.replay_wo(rows, events)
    for x in rows:
        floor._store_state(x, after[x.id], now)
    c = floor._Ctx(s, None, now)
    floor_effects._scrap(s, wo, rows)
    item = s.get(MfgItemRow, wo.item_id)
    if op.id == rows[-1].id and d.kind == "use_as_is":
        floor_effects._receipt(c, wo, rows[-1], item, now, rows)
    del before
    s.flush()
    return ev.id


def implement(ctx: AppContext, a: Act, ncr_id: str, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "approved":
            raise _bad_state(r, "implemented")
        now = utcnow()
        for d in _disps(s, r.id):
            if d.implemented_at is not None:
                continue
            refs: dict[str, Any] = {}
            if r.place == "wip":
                refs["floor_event_id"] = _nc_event(s, r, d, a.user_id)
            elif d.kind == "scrap":
                refs["posting_id"] = _issue(s, r, d, "SCRAP")
            elif d.kind == "return_to_supplier":
                refs["posting_id"] = _issue(s, r, d, "RTV")
                from ....integration import outbox

                if outbox.enabled(s):
                    outbox.emit(s, "qa.rtv", {"ncr_id": r.id, "number": r.number, "supplier_id": r.supplier_id,
                                              "item_id": r.item_id, "lot_id": r.lot_id, "qty": d.qty}, r.number)
            elif d.kind == "rework":
                w = _rework_wo(s, r, d, a.user_id)
                refs["wo_id"], refs["wo_number"] = w.id, w.number
            d.implemented_at, d.refs = now, refs
            touch(d, now)
        s.flush()
        _transition(s, r, "implemented", "implement", "Dispositions implemented")
        _maybe_release(s, r, a.user_id)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.ncr.implemented", {"id": r.id, "number": r.number}, r.number)
        return record(s, r, True)


def _maybe_release(s: Session, r: QaNcrRow, actor: str) -> None:
    if r.place != "stock" or r.status not in ("implemented", "closed"):
        return
    if any(w.status not in ("completed", "closed", "cancelled") for w in _rework_wos(s, r.id)):
        return
    from .qa_holds import release_source

    release_source(s, "ncr", r.id, actor, f"{r.number} dispositions implemented")


def on_rework_done(s: Session, ncr_id: str) -> None:
    r = s.get(QaNcrRow, ncr_id)
    if r is not None:
        from .m2util import actor_id

        _maybe_release(s, r, actor_id())


def close(ctx: AppContext, a: Act, ncr_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    from ..db_models_m7 import QaLinkRow
    from . import esig

    auth = esig.authenticate(ctx, a, "ncr", "close", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != "implemented":
            raise _bad_state(r, "closed")
        missing = []
        if any(d.implemented_at is None for d in _disps(s, r.id)):
            missing.append("dispositions")
        if any(w.status not in ("completed", "closed") for w in _rework_wos(s, r.id)):
            missing.append("rework_work_orders")
        if r.capa_required and s.execute(select(QaLinkRow.id).where(or_(
                (QaLinkRow.from_id == r.id) & (QaLinkRow.to_type == "capa"),
                (QaLinkRow.to_id == r.id) & (QaLinkRow.from_type == "capa"))).limit(1)).first() is None:
            missing.append("capa")
        if missing:
            raise ApiError(409, "QA_NCR_NOT_CLOSABLE", f"{r.number} cannot close yet: {', '.join(missing)}.",
                           {"missing": missing})
        out = esig.sign(s, a, auth, "ncr", r.id, "close", body.signature)
        if out.pending is not None:
            return out.pending
        r.closed_at = utcnow()
        _transition(s, r, "closed", "close", _why(body), out.signature_ids[-1] if out.signature_ids else None)
        _maybe_release(s, r, a.user_id)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.ncr.closed", {"id": r.id, "number": r.number}, r.number)
        return record(s, r, True)


def cancel(ctx: AppContext, a: Act, ncr_id: str, body: CancelInput, if_match: str | None) -> dict[str, Any]:
    from .qa_holds import release_source

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaNcrRow, ncr_id, what="NCR", lock=True)
        if if_match is not None:
            check_version(r, if_match)
        if r.status not in EDITABLE:
            raise _bad_state(r, "cancelled")
        if r.inspection_lot_id and r.place == "stock":
            raise ApiError(409, "MFG_INVALID_STATE", "An NCR of a rejected inspection lot is dispositioned, not "
                           "cancelled.", {"inspection_lot_id": r.inspection_lot_id})
        release_source(s, "ncr", r.id, a.user_id, f"{r.number} cancelled: {body.reason}")
        _transition(s, r, "cancelled", "cancel", body.reason)
        return record(s, r, True)


# ---------------------------------------------------------------- sources (inspection reject, floor qty_nc)

def create_from_inspection(s: Session, lot: QaInspectionLotRow, plan: Any, actor: str) -> QaNcrRow:
    """5.2 reject: an open NCR for the lot size; the inspection hold becomes an NCR hold (stock)."""
    from ..db_models_m2 import MfgInvBalanceRow
    from .qa_holds import release_source

    place = "wip" if lot.scope == "in_process" else "stock"
    loc = None
    if lot.lot_id:
        loc = s.execute(select(MfgInvBalanceRow.location_id).where(MfgInvBalanceRow.lot_id == lot.lot_id,
                                                                   MfgInvBalanceRow.qty_on_hand > EPS)
                        .order_by(MfgInvBalanceRow.qty_on_hand.desc()).limit(1)).scalar()
    seq = plan.operation_seq if plan is not None else None
    r = _new(s, title=f"{lot.number} rejected", source="inspection", severity="major", author=actor, place=place,
             qty=lot.lot_size, status="open", item_id=lot.item_id, lot_id=lot.lot_id, supplier_id=lot.supplier_id,
             wo_id=lot.wo_id, wo_operation_id=lot.wo_operation_id, operation_seq=seq, inspection_lot_id=lot.id,
             location_id=loc)
    if place == "stock":
        _place_holds(s, r, actor)
        if lot.hold:
            release_source(s, "inspection", lot.id, actor, f"Moved to {r.number}")
    from .qa_common import add_link

    add_link(s, "inspection_lot", lot.id, "ncr", r.id, actor)
    return r


def wip_nc(s: Session, wo: Any, op: Any, ev: Any, item: Any) -> QaNcrRow:
    """Floor `qty_nc`: append to the open NCR of the operation, else create one (6)."""
    r = s.execute(select(QaNcrRow).where(QaNcrRow.wo_operation_id == op.id, QaNcrRow.status == "open",
                                         QaNcrRow.place == "wip").with_for_update().limit(1)).scalars().first()
    if r is not None:
        r.qty_nc = round(r.qty_nc + float(ev.qty_nc), 6)
        if ev.defect_code and ev.defect_code not in (r.defect_codes or []):
            r.defect_codes = list(r.defect_codes or []) + [ev.defect_code]
        touch(r)
        s.flush()
        return r
    return _new(s, title=f"{wo.number}/{op.seq} nonconforming", source="floor", severity="major",
                author=ev.actor_id, place="wip", qty=float(ev.qty_nc), status="open", item_id=wo.item_id,
                wo_id=wo.id, wo_operation_id=op.id, operation_seq=op.seq,
                defect_codes=[ev.defect_code] if ev.defect_code else [])


__getattr__ = m7_examples.module_getattr(__name__)
