"""Engineering change requests (M5-DESIGN 5): prepare, impact, submit / approve / reject / cancel, implement.

- Adding a draft BOM / routing to a CR locks it (`locked_by_cr_id`): edits only while the CR is `draft`; release
  and delete only through the CR (409 `ECO_DOC_LOCKED`). Reject / cancel / removing the item unlocks.
- Approve: `eco_approve`, approver != submitter unless owner / plant_admin (409 `ECO_SELF_APPROVAL`).
- Implement: all drafts released in one transaction with `supersede_previous` at the effectivity date (or from
  `serial_from`); dispositions: `refresh_planned` regenerates components of planned WOs, `flag` raises an
  `ECO_WO_DIFFERS` replan trigger per released WO, `flag_cancel` an `ECO_PO_NOT_NEEDED` trigger per open PO line of a
  removed component; outbox `eco.implemented`. Any release rule failing -> 422 `ECO_RELEASE_BLOCKED`
  (`details.issues`), nothing is released.
- ERP-sourced structure changes (`implement_erp`) create a CR with `source erp`, approved and implemented at once.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg.eco import impact as IMP
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import repo
from ..db_models import MfgBomLineRow, MfgBomRow, MfgItemRow, MfgOperationRow, MfgRoutingRow
from ..db_models_m5 import MfgChangeRequestItemRow, MfgChangeRequestRow
from .common import audit, check_version, read_tx, touch
from .m2util import actor_id, is_workspace_owner, page, run_tx, user_names

EPS = 1e-9
DOC = {"bom": (MfgBomRow, "BOM"), "routing": (MfgRoutingRow, "Routing")}


# ---------------------------------------------------------------- locks (called from boms / routings)

def lock_info(s: Session, row: Any) -> dict[str, Any]:
    cid = getattr(row, "locked_by_cr_id", None)
    if not cid:
        return {"locked_by_cr_id": None, "locked_by_cr": None}
    cr = s.get(MfgChangeRequestRow, cid)
    return {"locked_by_cr_id": cid, "locked_by_cr": {"id": cid, "number": cr.number, "status": cr.status}
            if cr is not None else None}


def check_eco_lock(s: Session, row: Any, action: str) -> None:
    cid = getattr(row, "locked_by_cr_id", None)
    if not cid or s.info.get("sp_eco_implement") == cid:
        return
    cr = s.get(MfgChangeRequestRow, cid)
    if cr is None or cr.status in ("rejected", "cancelled", "implemented"):
        return
    if action == "edit" and cr.status == "draft":
        return
    raise ApiError(409, "ECO_DOC_LOCKED", f"This document is part of {cr.number} ({cr.status}); "
                   + ("edit it only while the change request is a draft." if action == "edit"
                      else f"it is {'released' if action == 'release' else 'removed'} through the change request."),
                   {"cr_id": cr.id, "number": cr.number, "status": cr.status})


# ---------------------------------------------------------------- records

def _items(s: Session, cr_id: str) -> list[MfgChangeRequestItemRow]:
    return list(s.execute(select(MfgChangeRequestItemRow).where(MfgChangeRequestItemRow.cr_id == cr_id)
                          .order_by(MfgChangeRequestItemRow.doc_type, MfgChangeRequestItemRow.id)).scalars())


def record(s: Session, r: MfgChangeRequestRow) -> dict[str, Any]:
    names = user_names(s, [x for x in (r.requested_by, r.approved_by, r.submitted_by) if x])

    def who(u: str | None) -> dict[str, Any] | None:
        return {"id": u, "name": names.get(u, u)} if u else None

    return {"id": r.id, "number": r.number, "title": r.title, "reason": r.reason, "kind": r.kind, "source": r.source,
            "status": r.status, "priority": r.priority, "effectivity": r.effectivity or {}, "note": r.note,
            "requested_by": who(r.requested_by), "submitted_by": who(r.submitted_by),
            "approved_by": who(r.approved_by), "approved_at": as_utc(r.approved_at),
            "implemented_at": as_utc(r.implemented_at),
            "items": [{"id": i.id, "doc_type": i.doc_type, "doc_id": i.doc_id, "supersedes_doc_id": i.supersedes_doc_id,
                       "disposition": i.disposition} for i in _items(s, r.id)],
            "row_version": r.row_version, "created_at": as_utc(r.created_at), "updated_at": as_utc(r.updated_at)}


def _get(s: Session, cr_id: str, lock: bool = False) -> MfgChangeRequestRow:
    return repo.get_row(s, MfgChangeRequestRow, cr_id, what="Change request", lock=lock)


def _eff(inp: Any) -> dict[str, Any]:
    e = inp.effectivity.model_dump(mode="json", exclude_none=True)
    return e


def _new(s: Session, inp: Any, source: str = "manual") -> MfgChangeRequestRow:
    from .. import repo_m2

    number = repo_m2.next_number(s, "ECO", repo_m2.number_taken(s, MfgChangeRequestRow))
    now = utcnow()
    r = MfgChangeRequestRow(id=new_id("ecr_"), number=number, title=inp.title, reason=inp.reason, kind=inp.kind,
                            source=source, status="draft", priority=inp.priority, requested_by=actor_id(),
                            submitted_by=None, approved_by=None, approved_at=None, implemented_at=None,
                            effectivity=_eff(inp), note=inp.note, row_version=1, created_at=now, updated_at=now)
    s.add(r)
    s.flush()
    return r


def create(ctx: AppContext, inp: Any) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _new(s, inp)
        audit(s, "eco", r.id, "create", {"number": r.number})
        return record(s, r)

    return run_tx(ctx, fn, lock=True)


def get(ctx: AppContext, cr_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, _get(s, cr_id))


def list_(ctx: AppContext, status: str | None, q: str | None, limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if status:
        conds.append(MfgChangeRequestRow.status == status)
    if q:
        from .common import ilike

        conds.append(ilike(MfgChangeRequestRow.number, q) | ilike(MfgChangeRequestRow.title, q))
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgChangeRequestRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgChangeRequestRow).where(*conds).order_by(
            MfgChangeRequestRow.created_at.desc(), MfgChangeRequestRow.id).limit(limit).offset(offset)).scalars())
        return page([record(s, r) for r in rows], total, limit, offset)


def _draft(r: MfgChangeRequestRow, action: str) -> None:
    if r.status != "draft":
        raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} change request cannot be changed.",
                       {"status": r.status, "action": action, "allowed_from": ["draft"]})


def update(ctx: AppContext, cr_id: str, inp: Any, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, cr_id, lock=True)
        check_version(r, if_match)
        _draft(r, "edit")
        r.title, r.reason, r.kind, r.priority, r.note = inp.title, inp.reason, inp.kind, inp.priority, inp.note
        r.effectivity = _eff(inp)
        touch(r)
        s.flush()
        audit(s, "eco", r.id, "update", {"version": r.row_version})
        return record(s, r)

    return run_tx(ctx, fn, lock=True)


def _unlock_all(s: Session, r: MfgChangeRequestRow) -> None:
    for i in _items(s, r.id):
        model, _w = DOC[i.doc_type]
        d = s.get(model, i.doc_id)
        if d is not None and d.locked_by_cr_id == r.id:
            d.locked_by_cr_id = None
            touch(d)


def delete(ctx: AppContext, cr_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        r = _get(s, cr_id, lock=True)
        check_version(r, if_match)
        _draft(r, "delete")
        _unlock_all(s, r)
        for i in _items(s, r.id):
            s.delete(i)
        s.flush()
        s.delete(r)
        audit(s, "eco", cr_id, "delete", {"number": r.number})

    run_tx(ctx, fn, lock=True)


def _latest_released(s: Session, doc_type: str, d: Any) -> str | None:
    model, _w = DOC[doc_type]
    q = select(model.id).where(model.item_id == d.item_id, model.status == "released", model.id != d.id)
    if doc_type == "routing":
        q = q.where(model.code == d.code)
    return s.execute(q.order_by(model.effective_from.desc().nulls_last(), model.version.desc())).scalars().first()


def add_item(ctx: AppContext, cr_id: str, inp: Any, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, cr_id, lock=True)
        if if_match is not None:
            check_version(r, if_match)
        _draft(r, "add_item")
        model, what = DOC[inp.doc_type]
        d = repo.get_row(s, model, inp.doc_id, what=what, lock=True)
        if d.status != "draft":
            raise ApiError(422, "VALIDATION_ERROR", f"Only draft documents can be part of a change request "
                           f"({what} is {d.status}).", {"errors": [{"loc": ["body", "doc_id"], "msg": "not a draft",
                                                                     "type": "value_error"}]})
        if d.locked_by_cr_id and d.locked_by_cr_id != r.id:
            other = s.get(MfgChangeRequestRow, d.locked_by_cr_id)
            if other is not None and other.status not in ("rejected", "cancelled", "implemented"):
                raise ApiError(409, "ECO_DOC_LOCKED", f"This draft is already part of {other.number}.",
                               {"cr_id": other.id, "number": other.number, "status": other.status})
        if s.execute(select(MfgChangeRequestItemRow.id).where(MfgChangeRequestItemRow.cr_id == r.id,
                                                              MfgChangeRequestItemRow.doc_id == d.id)).first():
            raise ApiError(409, "MFG_DUPLICATE", "This document is already part of the change request.",
                           {"doc_id": d.id})
        sup = inp.supersedes_doc_id or _latest_released(s, inp.doc_type, d)
        if sup:
            o = repo.get_row(s, model, sup, what=what)
            if o.item_id != d.item_id:
                raise ApiError(422, "VALIDATION_ERROR", "The superseded document is of another item.",
                               {"errors": [{"loc": ["body", "supersedes_doc_id"], "msg": "other item",
                                            "type": "value_error"}]})
        s.add(MfgChangeRequestItemRow(id=new_id("eci_"), cr_id=r.id, doc_type=inp.doc_type, doc_id=d.id,
                                      supersedes_doc_id=sup, disposition=inp.disposition.model_dump()))
        d.locked_by_cr_id = r.id
        touch(d)
        touch(r)
        s.flush()
        audit(s, "eco", r.id, "add_item", {"doc_type": inp.doc_type, "doc_id": d.id})
        return record(s, r)

    return run_tx(ctx, fn, lock=True)


def delete_item(ctx: AppContext, cr_id: str, item_id: str, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, cr_id, lock=True)
        if if_match is not None:
            check_version(r, if_match)
        _draft(r, "remove_item")
        it = s.execute(select(MfgChangeRequestItemRow).where(MfgChangeRequestItemRow.cr_id == r.id,
                                                             MfgChangeRequestItemRow.id == item_id)).scalars().first()
        if it is None:
            raise not_found("Change request item", item_id)
        model, _w = DOC[it.doc_type]
        d = s.get(model, it.doc_id)
        if d is not None and d.locked_by_cr_id == r.id:
            d.locked_by_cr_id = None
            touch(d)
        s.delete(it)
        touch(r)
        s.flush()
        audit(s, "eco", r.id, "remove_item", {"doc_id": it.doc_id})
        return record(s, r)

    return run_tx(ctx, fn, lock=True)


# ---------------------------------------------------------------- workflow

def act(ctx: AppContext, cr_id: str, name: str, note: str, if_match: str | None, privileged: bool,
        ) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, cr_id, lock=True)
        if if_match is not None:
            check_version(r, if_match)
        allowed, target = IMP.ACTIONS[name]
        if r.status not in allowed:
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} change request cannot be {target}.",
                           {"status": r.status, "action": name, "allowed_from": list(allowed)})
        me = actor_id()
        now = utcnow()
        if name == "submit":
            if not _items(s, r.id):
                raise ApiError(422, "VALIDATION_ERROR", "Add at least one draft BOM or routing first.", {})
            r.submitted_by = me
        elif name == "approve":
            if IMP.self_approval(r.submitted_by, me, privileged):
                raise ApiError(409, "ECO_SELF_APPROVAL", "A change request cannot be approved by the person who "
                               "submitted it.", {"submitted_by": r.submitted_by})
            r.approved_by, r.approved_at = me, now
        elif name in ("reject", "cancel"):
            _unlock_all(s, r)
        elif name == "implement":
            implement_in_session(s, r)
        if note:
            r.note = (r.note + ("\n" if r.note else "") + f"{name}: {note}")[:1000]
        r.status = target
        touch(r, now)
        s.flush()
        audit(s, "eco", r.id, name, {"number": r.number, **({"note": note} if note else {})})
        return record(s, r)

    return run_tx(ctx, fn, lock=True)


def _eff_date(r: MfgChangeRequestRow) -> date | None:
    e = r.effectivity or {}
    d = e.get("date")
    return date.fromisoformat(d) if isinstance(d, str) else d


def implement_in_session(s: Session, r: MfgChangeRequestRow) -> dict[str, Any]:
    """Release every draft (all or nothing), apply dispositions, outbox `eco.implemented`."""
    from ....integration import outbox
    from .boms import release_in_session as release_bom
    from .routings import release_in_session as release_routing

    items = _items(s, r.id)
    e = r.effectivity or {}
    eff = _eff_date(r)
    serial_from = e.get("serial_from") if e.get("mode") == "serial" else None
    s.info["sp_eco_implement"] = r.id
    issues: list[dict[str, Any]] = []
    released: list[dict[str, Any]] = []
    try:
        ds = repo.load_dataset(s)
        for k, it in enumerate(items):
            model, what = DOC[it.doc_type]
            d = s.get(model, it.doc_id, with_for_update=True)
            if d is None or d.status != "draft":
                issues.append({"doc_id": it.doc_id, "code": "MFG_INVALID_STATE",
                               "message": f"{what} is no longer a draft."})
                continue
            if serial_from is not None:
                d.serial_from = int(serial_from)
                if it.supersedes_doc_id:
                    o = s.get(model, it.supersedes_doc_id, with_for_update=True)
                    if o is not None and o.serial_to is None:
                        o.serial_to = int(serial_from) - 1
                        o.serial_from = o.serial_from or 1
                s.flush()
                ds = repo.load_dataset(s)
            try:
                sup = (release_bom if it.doc_type == "bom" else release_routing)(
                    s, d, eff if serial_from is None else None, serial_from is None and eff is not None, ds)
                released.append({"doc_type": it.doc_type, "doc_id": d.id, "superseded": [x["id"] for x in sup]})
                if k + 1 < len(items):              # the next release sees this one
                    ds = repo.load_dataset(s)
            except ApiError as exc:
                for x in (exc.details or {}).get("issues", []) or [{"code": exc.code, "message": exc.message}]:
                    issues.append({"doc_id": it.doc_id, "doc_type": it.doc_type, **x})
    finally:
        s.info.pop("sp_eco_implement", None)
    if issues:
        raise ApiError(422, "ECO_RELEASE_BLOCKED", f"{len(issues)} release issue(s) block this change request; "
                       "nothing was released.", {"issues": issues[:100]})
    flags = _dispositions(s, r, items, eff)
    for it in items:
        model, _w = DOC[it.doc_type]
        d = s.get(model, it.doc_id)
        if d is not None:
            d.locked_by_cr_id = r.id          # kept: the released document names its change request
    r.implemented_at = utcnow()
    if outbox.enabled(s):
        outbox.emit(s, "eco.implemented", {"number": r.number, "title": r.title, "source": r.source,
                                           "effectivity": r.effectivity, "released": released, **flags}, r.number)
    return {"released": released, **flags}


def _components(s: Session, bom_id: str | None) -> dict[str, float]:
    if not bom_id:
        return {}
    out: dict[str, float] = {}
    for ln in s.execute(select(MfgBomLineRow).where(MfgBomLineRow.bom_id == bom_id)).scalars():
        out[ln.child_item_id] = out.get(ln.child_item_id, 0.0) + ln.qty_per
    return out


def _dispositions(s: Session, r: MfgChangeRequestRow, items: list[MfgChangeRequestItemRow], eff: date | None
                  ) -> dict[str, Any]:
    from ..db_models_m2 import MfgPurchaseDocRow, MfgPurchaseLineRow, MfgWoComponentRow, MfgWorkOrderRow
    from .replan import notify

    def raise_trigger(s: Session, kind: str, sev: str, ref_type: str, ref_id: str, key: str, details: dict) -> None:
        """5: the flag is an M4 notification with the exception code as its kind (not an APS replan trigger)."""
        if kind == "ECO_WO_DIFFERS":
            notify(s, kind, sev, f"{details['wo']} differs from {details['cr']}",
                   f"The components of {details['wo']} differ from the structure released by {details['cr']}.",
                   f"/mfg/work-orders/{ref_id}")
        else:
            notify(s, kind, sev, f"{details['po']}/{details['line_no']} may not be needed",
                   f"{details['cr']} removes this component; check {details['po']} line {details['line_no']}.",
                   f"/mfg/purchase-orders/{ref_id}")

    flagged_wos, refreshed, flagged_pos = [], [], []
    for it in items:
        if it.doc_type != "bom":
            continue
        new = s.get(MfgBomRow, it.doc_id)
        old_c, new_c = _components(s, it.supersedes_doc_id), _components(s, it.doc_id)
        removed = sorted(k for k in old_c if k not in new_c)
        disp = it.disposition or {}
        wos = list(s.execute(select(MfgWorkOrderRow).where(
            MfgWorkOrderRow.item_id == new.item_id, MfgWorkOrderRow.status.in_(("planned", "released",
                                                                                 "in_progress")))).scalars())
        for w in wos:
            if eff is not None and w.due_date < eff:
                continue
            comps = {}
            for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == w.id)).scalars():
                comps[c.item_id] = comps.get(c.item_id, 0.0) + c.required_qty
            differs = set(comps) != set(new_c)
            if not differs:
                continue
            if w.status == "planned" and disp.get("open_wos") == "refresh_planned":
                from .workorders import regenerate_components

                regenerate_components(s, w)
                refreshed.append(w.number)
            elif disp.get("open_wos", "flag") != "keep":
                raise_trigger(s, "ECO_WO_DIFFERS", "warning", "wo", w.id, f"eco:{r.id}:{w.id}",
                              {"cr": r.number, "wo": w.number})
                flagged_wos.append(w.number)
        if removed and disp.get("open_pos", "flag_cancel") == "flag_cancel":
            for doc, ln in s.execute(select(MfgPurchaseDocRow, MfgPurchaseLineRow).join(
                    MfgPurchaseLineRow, MfgPurchaseLineRow.doc_id == MfgPurchaseDocRow.id).where(
                    MfgPurchaseLineRow.item_id.in_(removed), MfgPurchaseDocRow.doc_type == "po",
                    MfgPurchaseDocRow.status.in_(("draft", "open", "partially_received")))).all():
                raise_trigger(s, "ECO_PO_NOT_NEEDED", "info", "po", doc.id, f"eco:{r.id}:{ln.id}",
                              {"cr": r.number, "po": doc.number, "line_no": ln.line_no})
                flagged_pos.append(f"{doc.number}/{ln.line_no}")
    return {"flagged_wos": flagged_wos, "refreshed_wos": refreshed, "flagged_pos": flagged_pos}


def implement_erp(s: Session, title: str, docs: list[tuple[str, Any, str | None]], eff: date | None) -> Any:
    """4.4 / 5: an ERP-sourced structure change -> CR `source erp`, approved and implemented in this transaction.
    `docs` = [(doc_type, draft row, superseded id)]."""
    from ....mfg.model_m5 import ChangeRequestInput

    r = _new(s, ChangeRequestInput(title=title[:200], reason="ERP structure change", kind="ecn",
                                   effectivity={"mode": "date", "date": eff} if eff else {"mode": "date"}),
             source="erp")
    for t, d, sup in docs:
        s.add(MfgChangeRequestItemRow(id=new_id("eci_"), cr_id=r.id, doc_type=t, doc_id=d.id, supersedes_doc_id=sup,
                                      disposition={"open_wos": "flag", "open_pos": "flag_cancel", "stock": "use_up"}))
        d.locked_by_cr_id = r.id
    s.flush()
    r.submitted_by = r.approved_by = "erp"
    r.approved_at = utcnow()
    implement_in_session(s, r)
    r.status = "implemented"
    touch(r)
    s.flush()
    audit(s, "eco", r.id, "implement", {"number": r.number, "source": "erp"})
    return r


# ---------------------------------------------------------------- impact (5)

def impact(ctx: AppContext, cr_id: str) -> dict[str, Any]:
    from ....mfg.mrp import run_mrp
    from ....mfg.mrp.model import MrpParams
    from .. import repo_m2
    from ..db_models_m2 import (MfgInvBalanceRow, MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow,
                                MfgWoComponentRow, MfgWorkOrderRow)

    t0 = time.monotonic()
    with read_tx(ctx) as s:
        r = _get(s, cr_id)
        items = _items(s, r.id)
        eff = _eff_date(r)
        e = r.effectivity or {}
        effectivity = dict(e)
        docs_t = [(i.doc_type, i.doc_id, i.supersedes_doc_id) for i in items]
        names: dict[str, str] = {}
        delta, removed_all = [], set()
        parents = []
        for it in items:
            model, _w = DOC[it.doc_type]
            d = s.get(model, it.doc_id)
            if d is None:
                continue
            parent = s.get(MfgItemRow, d.item_id)
            parents.append(d.item_id)
            if it.doc_type != "bom":
                old_ops = [o.seq for o in s.execute(select(MfgOperationRow).where(
                    MfgOperationRow.routing_id == it.supersedes_doc_id)).scalars()] if it.supersedes_doc_id else []
                new_ops = [o.seq for o in s.execute(select(MfgOperationRow).where(
                    MfgOperationRow.routing_id == d.id)).scalars()]
                delta.append({"parent": parent.part_number if parent else d.item_id, "doc_type": "routing",
                              "added": [f"op {x}" for x in sorted(set(new_ops) - set(old_ops))],
                              "removed": [f"op {x}" for x in sorted(set(old_ops) - set(new_ops))], "changed": []})
                continue
            old_c, new_c = _components(s, it.supersedes_doc_id), _components(s, d.id)
            for k in set(old_c) | set(new_c):
                if k not in names:
                    x = s.get(MfgItemRow, k)
                    names[k] = x.part_number if x else k
            dd = IMP.bom_delta(old_c.items(), new_c.items(), names)
            removed_all |= set(dd["removed_ids"]) | {c["item_id"] for c in dd["changed"]}
            delta.append({"parent": parent.part_number if parent else d.item_id, "doc_type": "bom",
                          "added": dd["added"], "removed": dd["removed"], "changed": dd["changed"]})
        open_wos = []
        if parents:
            for w, c in s.execute(select(MfgWorkOrderRow, MfgWoComponentRow).join(
                    MfgWoComponentRow, MfgWoComponentRow.wo_id == MfgWorkOrderRow.id).where(
                    MfgWorkOrderRow.item_id.in_(parents), MfgWorkOrderRow.status.in_(
                        ("planned", "released", "in_progress")), MfgWoComponentRow.item_id.in_(
                        sorted(removed_all) or ["-"])).order_by(MfgWorkOrderRow.number)).all():
                open_wos.append({"id": w.id, "number": w.number, "status": w.status, "due_date": w.due_date.isoformat(),
                                 "component": names.get(c.item_id, c.item_id),
                                 "qty": round(max(0.0, c.required_qty - c.issued_qty), 6),
                                 "after_effectivity": eff is None or w.due_date >= eff})
        purchases, stock = [], []
        for k in sorted(removed_all):
            on_hand = float(s.execute(select(func.coalesce(func.sum(MfgInvBalanceRow.qty_on_hand), 0.0)).where(
                MfgInvBalanceRow.item_id == k)).scalar() or 0.0)
            on_order = 0.0
            for doc, ln, sc in s.execute(select(MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow).join(
                    MfgPurchaseLineRow, MfgPurchaseLineRow.doc_id == MfgPurchaseDocRow.id).join(
                    MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.line_id == MfgPurchaseLineRow.id).where(
                    MfgPurchaseLineRow.item_id == k, MfgPurchaseDocRow.status.in_(
                        ("draft", "submitted", "approved", "open", "partially_received")),
                    MfgPurchaseScheduleRow.closed.is_(False))).all():
                left = round(sc.qty - sc.received_qty, 6)
                if left <= EPS:
                    continue
                on_order += left
                due = sc.confirmed_date or sc.requested_date
                purchases.append({"doc_type": doc.doc_type, "number": doc.number, "line_no": ln.line_no,
                                  "item": names.get(k, k), "open_qty": left, "due": due.isoformat(),
                                  "after_effectivity": eff is None or due >= eff})
            it_row = s.get(MfgItemRow, k)
            cost = float(it_row.standard_cost or 0.0) if it_row else 0.0
            stock.append({"item_id": k, "item": names.get(k, k), "on_hand": round(on_hand, 6),
                          "on_order": round(on_order, 6), "value": round((on_hand + on_order) * cost, 2)})
    # MRP what-if: the drafts treated as released at the effectivity (in memory)
    mrp_delta, planned, use_up = [], [], None
    try:
        with repo_m2.snapshot_tx(ctx.db) as s:
            base = repo_m2.load_mrp_snapshot(s, _today(s))
            what = repo_m2.load_mrp_snapshot(s, base.as_of)
        on = eff or base.as_of
        ds = what.dataset
        for dt, did, sid in docs_t:
            docs = ds.boms if dt == "bom" else ds.routings
            d = docs.get(did)
            if d is None:
                continue
            docs[did] = d.model_copy(update={"status": "released", "effective_from": on})
            if sid and sid in docs:
                o = docs[sid]
                if o.effective_from is None or o.effective_from < on:
                    docs[sid] = o.model_copy(update={"effective_to": on})   # M1: exclusive end
        ds.invalidate()
        rb = run_mrp(base, MrpParams())
        rw = run_mrp(what, MrpParams())
        before = {x.demand_line_id or x.label: x for x in rb.demand}
        for x in rw.demand:
            b = before.get(x.demand_line_id or x.label)
            if b is not None and b.projected_date != x.projected_date:
                mrp_delta.append({"demand": b.label, "order": b.order_number, "line_no": b.line_no,
                                  "item": b.part_number, "due_date": b.due_date.isoformat(),
                                  "before": b.projected_date.isoformat() if b.projected_date else None,
                                  "after": x.projected_date.isoformat() if x.projected_date else None})
        for p in rb.planned_orders:
            if p.item_id in parents:
                planned.append({"planned_no": p.planned_no, "item": getattr(p, "part_number", p.item_id),
                                "qty": p.qty, "need_date": p.need_date.isoformat()})
        if e.get("mode") == "use_up" or removed_all:
            dates = []
            for k in sorted(removed_all):
                pl = rb.item(k)
                if pl is not None:
                    u = IMP.use_up_date(pl.timeline, rb.as_of)
                    if u is not None:
                        dates.append(u)
            use_up = min(dates) if dates else None
    except ApiError:
        raise
    except Exception as exc:  # pragma: no cover - a plant whose MRP cannot run still gets the structural impact
        mrp_delta = [{"error": str(exc)[:200]}]
    return {"cr_id": cr_id, "effectivity": effectivity, "explosion_delta": delta, "open_wos": open_wos,
            "planned_orders": planned, "open_purchases": purchases, "phase_out_stock": stock, "mrp_delta": mrp_delta,
            "use_up_date": use_up.isoformat() if use_up else None, "computed_ms": int((time.monotonic() - t0) * 1000)}


def _today(s: Session) -> date:
    from .m2util import today

    return today(s)


__all__ = ["act", "add_item", "check_eco_lock", "create", "delete", "delete_item", "get", "impact", "implement_erp",
           "list_", "lock_info", "update"]
_ = is_workspace_owner
