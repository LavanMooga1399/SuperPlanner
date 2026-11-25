"""CAPA (M7-DESIGN 7): `draft -> investigation -> plan_approval -> implementation -> effectiveness_check -> closed`
(+ `cancelled`). `approve_plan` (signed) needs a root cause and >= 1 action; `implementation ->
effectiveness_check` needs every action done or cancelled; `verify` (signed) records the result (`not_effective`
returns to `investigation`); `close` (signed). With `qa_settings.capa_sor = external` CAPAs are link stubs
(`external_ref`, title, free status text) and the workflow actions are refused (409 `QA_EXTERNAL_SOR`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa.model import ApproveInput, CancelInput, CapaActionInput, CapaAdvanceInput, CapaInput, CapaVerifyInput
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models_m7 import QaCapaActionRow, QaCapaRow
from . import m7_examples
from .common import check_version, ilike, read_tx, touch, write_tx
from .qa_common import Act, decorate, next_number, settings_of

OPEN = ("draft", "investigation", "plan_approval", "implementation", "effectiveness_check")
ADVANCE = {"investigation": ("draft",), "plan_approval": ("investigation",),
           "effectiveness_check": ("implementation",)}


def _actions(s: Session, capa_id: str) -> list[QaCapaActionRow]:
    return list(s.execute(select(QaCapaActionRow).where(QaCapaActionRow.capa_id == capa_id)
                          .order_by(QaCapaActionRow.seq)).scalars())


def action_record(x: QaCapaActionRow) -> dict[str, Any]:
    return {"id": x.id, "seq": x.seq, "kind": x.kind, "description": x.description, "owner_user_id": x.owner_user_id,
            "due_on": x.due_on, "status": x.status, "done_at": x.done_at, "evidence": x.evidence, "eco_id": x.eco_id,
            "row_version": x.row_version}


def content(s: Session, r: QaCapaRow) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "title": r.title, "kind": r.kind, "problem": r.problem, "risk": r.risk,
            "owner_user_id": r.owner_user_id, "due_on": r.due_on, "root_cause": r.root_cause,
            "effectiveness": r.effectiveness, "status": r.status,
            "actions": [{k: v for k, v in action_record(x).items() if k not in ("row_version", "done_at", "id")}
                        for x in _actions(s, r.id)]}


def _loader(s: Session, rid: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, QaCapaRow, rid, what="CAPA", lock=lock)
    return C.Loaded(r, content(s, r), r.row_version, r.author_id, [("CAPA", f"{r.number} - {r.title}"),
                                                                   ("Status", r.status)])


C.register("capa", _loader)


def record(s: Session, r: QaCapaRow, full: bool = False) -> dict[str, Any]:
    from .m2util import today

    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "number": r.number, "title": r.title, "kind": r.kind, "problem": r.problem, "risk": r.risk,
           "owner_user_id": r.owner_user_id, "due_on": r.due_on, "root_cause": r.root_cause,
           "effectiveness": r.effectiveness, "status": r.status, "author_id": r.author_id, "closed_at": r.closed_at,
           "external_ref": r.external_ref, "sor": r.sor,
           "overdue": bool(r.due_on and r.status in OPEN and r.due_on < today(s)), "actions": [],
           "signatures": [], "links": [], "attachments": []}
    if full:
        rec["actions"] = [action_record(x) for x in _actions(s, r.id)]
        decorate(s, rec, "capa", "capa")
    return rec


def _level(risk: dict[str, Any] | None) -> dict[str, Any] | None:
    if not risk:
        return risk
    score = int(risk["severity"]) * int(risk["occurrence"])
    return {**risk, "level": "high" if score >= 15 else "medium" if score >= 6 else "low"}


def _external(s: Session) -> bool:
    return settings_of(s).capa_sor == "external"


def _ext_error() -> ApiError:
    return ApiError(409, "QA_EXTERNAL_SOR", "CAPAs are managed in the external quality system of this plant; "
                    "here they are links only.", {"sor": "external"})


def list_capas(ctx: AppContext, q: str | None, status: str | None, owner_user_id: str | None, overdue: bool | None,
               sort: str | None, limit: int, offset: int) -> dict[str, Any]:
    from .m2util import today

    conds = []
    if q:
        conds.append(or_(ilike(QaCapaRow.number, q), ilike(QaCapaRow.title, q)))
    if status:
        conds.append(QaCapaRow.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    if owner_user_id:
        conds.append(QaCapaRow.owner_user_id == owner_user_id)
    with read_tx(ctx) as s:
        if overdue:
            conds += [QaCapaRow.status.in_(OPEN), QaCapaRow.due_on < today(s)]
        total = int(s.execute(select(func.count()).select_from(QaCapaRow).where(*conds)).scalar() or 0)
        desc = (sort or "-created_at").startswith("-")
        col = {"number": QaCapaRow.number, "due_on": QaCapaRow.due_on}.get((sort or "").lstrip("-"),
                                                                          QaCapaRow.created_at)
        rows = s.execute(select(QaCapaRow).where(*conds).order_by(col.desc() if desc else col.asc(), QaCapaRow.id)
                         .limit(limit).offset(offset)).scalars()
        return {"items": [record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def get_capa(ctx: AppContext, capa_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, repo.get_row(s, QaCapaRow, capa_id, what="CAPA"), True)


def create_capa(ctx: AppContext, a: Act, body: CapaInput) -> dict[str, Any]:
    from .common import audit

    with write_tx(ctx) as (s, _plant):
        ext = _external(s)
        if ext and not body.external_ref:
            raise ApiError(422, "VALIDATION_ERROR", "External CAPAs need external_ref.", {"errors": [
                {"loc": ["body", "external_ref"], "msg": "required", "type": "value_error"}]})
        now = utcnow()
        r = QaCapaRow(id=new_id("cap_"), number=next_number(s, "CAPA", QaCapaRow), title=body.title, kind=body.kind,
                      problem=body.problem, risk=_level(body.risk.model_dump() if body.risk else None),
                      owner_user_id=body.owner_user_id, due_on=body.due_on,
                      root_cause=body.root_cause.model_dump() if body.root_cause else None,
                      effectiveness=body.effectiveness.model_dump(mode="json") if body.effectiveness else None,
                      status=(body.external_status or "external") if ext else "draft", author_id=a.user_id,
                      sor="external" if ext else "superplanner",
                      closed_at=None, external_ref=body.external_ref, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "capa", r.id, "create", {"number": r.number, "external": ext})
        return record(s, r, True)


def update_capa(ctx: AppContext, a: Act, capa_id: str, body: CapaInput, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaCapaRow, capa_id, what="CAPA", lock=True)
        check_version(r, if_match)
        if r.status in ("closed", "cancelled"):
            raise esig.locked_error(r.number)
        before = content(s, r)
        esig.supersede_pending(s, "capa", r.id, r.row_version)
        r.title, r.kind, r.problem = body.title, body.kind, body.problem
        r.risk = _level(body.risk.model_dump() if body.risk else None)
        r.owner_user_id, r.due_on, r.external_ref = body.owner_user_id, body.due_on, body.external_ref
        r.root_cause = body.root_cause.model_dump() if body.root_cause else None
        r.effectiveness = body.effectiveness.model_dump(mode="json") if body.effectiveness else None
        if r.sor == "external" and body.external_status:     # review M7: free status only on external rows
            r.status = body.external_status
        touch(r)
        s.flush()
        audit_regulated(s, "capa", r.id, "update", before=before, after=content(s, r), record_version=r.row_version)
        return record(s, r, True)


def _open_capa(s: Session, capa_id: str) -> QaCapaRow:
    from . import esig

    r = repo.get_row(s, QaCapaRow, capa_id, what="CAPA", lock=True)
    if r.sor == "external":
        raise _ext_error()
    if r.status not in OPEN:
        raise esig.locked_error(r.number)
    return r


def add_action(ctx: AppContext, a: Act, capa_id: str, body: CapaActionInput) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = _open_capa(s, capa_id)
        before = content(s, r)
        esig.supersede_pending(s, "capa", r.id, r.row_version)
        seq = max([x.seq for x in _actions(s, r.id)] or [0]) + 1
        now = utcnow()
        s.add(QaCapaActionRow(id=new_id("cpa_"), capa_id=r.id, seq=seq, kind=body.kind, description=body.description,
                              owner_user_id=body.owner_user_id, due_on=body.due_on, status=body.status,
                              done_at=now if body.status == "done" else None, evidence=body.evidence,
                              eco_id=body.eco_id, owner_id=r.owner_id, row_version=1, created_at=now, updated_at=now))
        touch(r)
        s.flush()
        audit_regulated(s, "capa", r.id, "action_add", before=before, after=content(s, r),
                        record_version=r.row_version, create=True)
        return record(s, r, True)


def update_action(ctx: AppContext, a: Act, capa_id: str, action_id: str, body: CapaActionInput,
                  if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    with write_tx(ctx) as (s, _plant):
        r = _open_capa(s, capa_id)
        x = repo.get_row(s, QaCapaActionRow, action_id, what="CAPA action", lock=True)
        if x.capa_id != r.id:
            raise ApiError(404, "NOT_FOUND", "CAPA action not found.", {"id": action_id})
        check_version(x, if_match)
        before = content(s, r)
        esig.supersede_pending(s, "capa", r.id, r.row_version)
        x.kind, x.description, x.owner_user_id, x.due_on = body.kind, body.description, body.owner_user_id, body.due_on
        x.evidence, x.eco_id = body.evidence, body.eco_id
        if body.status != x.status:
            x.status = body.status
            x.done_at = utcnow() if body.status == "done" else None
        touch(x)
        touch(r)
        s.flush()
        audit_regulated(s, "capa", r.id, "action_update", before=before, after=content(s, r),
                        record_version=r.row_version)
        return record(s, r, True)


def delete_action(ctx: AppContext, a: Act, capa_id: str, action_id: str, if_match: str | None) -> None:
    from ...audit_diff import audit_regulated

    with write_tx(ctx) as (s, _plant):
        r = _open_capa(s, capa_id)
        if r.status != "draft":
            raise ApiError(409, "MFG_INVALID_STATE", "Actions are cancelled, not deleted, once the CAPA left draft.",
                           {"status": r.status})
        x = repo.get_row(s, QaCapaActionRow, action_id, what="CAPA action", lock=True)
        if x.capa_id != r.id:                        # review M3: an action of another CAPA
            raise ApiError(404, "NOT_FOUND", "CAPA action not found.", {"id": action_id})
        if if_match is not None:
            check_version(x, if_match)
        before = content(s, r)
        s.delete(x)
        touch(r)
        s.flush()
        audit_regulated(s, "capa", r.id, "action_delete", before=before, after=content(s, r),
                        record_version=r.row_version)


def _move(s: Session, r: QaCapaRow, to: str, action: str, reason: str | None, sig_id: str | None = None) -> None:
    from ...audit_diff import audit_regulated

    before = r.status
    r.status = to
    if to == "closed":
        r.closed_at = utcnow()
    touch(r)
    s.flush()
    audit_regulated(s, "capa", r.id, action, before={"status": before}, after={"status": to},
                    reason=reason or f"CAPA {action}", record_version=r.row_version, signature_id=sig_id)


def advance(ctx: AppContext, a: Act, capa_id: str, body: CapaAdvanceInput, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        r = _open_capa(s, capa_id)
        if if_match is not None:
            check_version(r, if_match)
        if r.status not in ADVANCE[body.to]:
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} CAPA cannot move to {body.to}.",
                           {"status": r.status, "to": body.to})
        if body.to == "effectiveness_check":
            open_ = [x.seq for x in _actions(s, r.id) if x.status == "open"]
            if open_:
                raise ApiError(409, "QA_CAPA_ACTIONS_OPEN", "Finish or cancel every action first.", {"open": open_})
        _move(s, r, body.to, "advance", body.note or None)
        return record(s, r, True)


def _signed_step(ctx: AppContext, a: Act, capa_id: str, action: str, body: Any, if_match: str | None,
                 from_status: str, check: Any, after: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
    from . import esig

    auth = esig.authenticate(ctx, a, "capa", action, body.signature)
    with write_tx(ctx) as (s, _plant):
        r = _open_capa(s, capa_id)
        if if_match is not None:
            check_version(r, if_match)
        if r.status != from_status:
            raise ApiError(409, "MFG_INVALID_STATE", f"A {r.status} CAPA cannot be {action.replace('_', ' ')}d.",
                           {"status": r.status, "action": action})
        check(s, r)
        out = esig.sign(s, a, auth, "capa", r.id, action, body.signature, params=params)
        if out.pending is not None:
            return out.pending
        after(s, r, out.signature_ids[-1] if out.signature_ids else None)
        return record(s, r, True)


def _why(body: Any, default: str) -> str:
    sig = getattr(body, "signature", None)
    return (sig.comment.strip() if sig is not None and sig.comment.strip() else "") or \
        (getattr(body, "note", "") or "").strip() or default


def approve_plan(ctx: AppContext, a: Act, capa_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    def check(s: Session, r: QaCapaRow) -> None:
        missing = [k for k, ok in (("root_cause", bool(r.root_cause and r.root_cause.get("text"))),
                                   ("actions", bool(_actions(s, r.id)))) if not ok]
        if missing:
            raise ApiError(409, "QA_CAPA_INCOMPLETE", "The plan needs a root cause and at least one action.",
                           {"missing": missing})

    return _signed_step(ctx, a, capa_id, "approve_plan", body, if_match, "plan_approval", check,
                        lambda s, r, sid: _move(s, r, "implementation", "approve_plan",
                                                _why(body, "Plan approved"), sid))


def verify(ctx: AppContext, a: Act, capa_id: str, body: CapaVerifyInput, if_match: str | None) -> dict[str, Any]:
    def after(s: Session, r: QaCapaRow, sid: str | None) -> None:
        r.effectiveness = {**(r.effectiveness or {}), "result": body.result, "evidence": body.evidence}
        _move(s, r, "investigation" if body.result == "not_effective" else "effectiveness_check", "verify",
              _why(body, f"Effectiveness: {body.result}"), sid)

    return _signed_step(ctx, a, capa_id, "verify", body, if_match, "effectiveness_check", lambda s, r: None, after,
                        params={"result": body.result, "evidence": body.evidence})


def close(ctx: AppContext, a: Act, capa_id: str, body: ApproveInput, if_match: str | None) -> dict[str, Any]:
    def check(s: Session, r: QaCapaRow) -> None:
        if (r.effectiveness or {}).get("result") != "effective":
            raise ApiError(409, "QA_CAPA_INCOMPLETE", "Verify the effectiveness first.", {"missing": ["verify"]})

    def after(s: Session, r: QaCapaRow, sid: str | None) -> None:
        _move(s, r, "closed", "close", _why(body, "CAPA closed"), sid)
        from ....integration import outbox

        if outbox.enabled(s):
            outbox.emit(s, "qa.capa.closed", {"id": r.id, "number": r.number}, r.number)

    return _signed_step(ctx, a, capa_id, "close", body, if_match, "effectiveness_check", check, after)


def cancel(ctx: AppContext, a: Act, capa_id: str, body: CancelInput, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        r = _open_capa(s, capa_id)
        if if_match is not None:
            check_version(r, if_match)
        _move(s, r, "cancelled", "cancel", body.reason)
        return record(s, r, True)


__getattr__ = m7_examples.module_getattr(__name__)
