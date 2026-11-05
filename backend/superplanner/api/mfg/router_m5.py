"""M5 `/api/v1/mfg` endpoints (M5-DESIGN 9: traceability #227.., ECO, transfers) and `/api/v1/audit`.

Services: `services/trace.py` (genealogy, recalls), `services/eco.py`, `services/transfers.py`; audit below."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select

from ...mfg.model_m5 import (ChangeRequestInput, ChangeRequestItemInput, EcoActionInput, QuarantineInput,
                             RecallInput, TransferOrderInput)
from ..context import AppContext, get_ctx
from ..errors import ApiError
from .access import MfgPrincipal, mfg_principal
from .router_m2 import P, Id, Limit, Offset, _if_match, _ok

router = APIRouter(prefix="/mfg", tags=["mfg-m5"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])


# ---------------------------------------------------------------- traceability (6)

@router.get("/trace", dependencies=P("trace_view"))
def trace(kind: Literal["lot", "serial", "wo"] = "serial", id: str = Query(max_length=64),  # noqa: A002
          direction: Literal["backward", "forward"] = "backward", depth: int = Query(default=30, ge=1, le=30),
          include_possible: bool = True, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trace as svc

    return _ok(svc.trace(ctx, kind, id, direction, depth, include_possible))


@router.get("/trace/where-used", dependencies=P("trace_view"))
def where_used(item_id: str = Query(max_length=64), lot_code: str | None = Query(default=None, max_length=64),
               supplier_lot: str | None = Query(default=None, max_length=64),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trace as svc

    return _ok(svc.where_used(ctx, item_id, lot_code, supplier_lot))


@router.get("/recalls", dependencies=P("trace_view"))
def list_recalls(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trace as svc

    return _ok(svc.list_recalls(ctx, limit, offset))


@router.post("/recalls", status_code=201, dependencies=P("trace_view"))
def create_recall(body: RecallInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trace as svc

    return _ok(svc.create_recall(ctx, body), 201)


@router.get("/recalls/{recall_id}", dependencies=P("trace_view"))
def get_recall(recall_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trace as svc

    return _ok(svc.get_recall(ctx, recall_id))


@router.get("/recalls/{recall_id}/export", dependencies=P("trace_view"))
def export_recall(recall_id: str, format: Literal["xlsx", "json"] = "xlsx",  # noqa: A002
                  ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import trace as svc

    if format == "json":
        return _ok((svc.get_recall(ctx, recall_id)["report"] or {}))
    data, name = svc.export_recall(ctx, recall_id)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/recalls/{recall_id}/quarantine", dependencies=P("inventory"))
def quarantine(recall_id: str, body: QuarantineInput | None = None, ctx: AppContext = Depends(get_ctx)
               ) -> JSONResponse:
    from .services import trace as svc

    return _ok(svc.quarantine(ctx, recall_id, body or QuarantineInput()))


# ---------------------------------------------------------------- ECO (5)

@router.get("/eco", dependencies=P("view"))
def list_eco(status: str | None = Query(default=None, max_length=16), q: str | None = Query(default=None,
                                                                                         max_length=100),
             limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    return _ok(svc.list_(ctx, status, q, limit, offset))


@router.post("/eco", status_code=201, dependencies=P("eco_edit"))
def create_eco(body: ChangeRequestInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    rec = svc.create(ctx, body)
    return _ok(rec, 201, etag=rec["row_version"])


@router.get("/eco/{cr_id}", dependencies=P("view"))
def get_eco(cr_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    rec = svc.get(ctx, cr_id)
    return _ok(rec, etag=rec["row_version"])


@router.put("/eco/{cr_id}", dependencies=P("eco_edit"))
def put_eco(cr_id: str, body: ChangeRequestInput, if_match: str | None = _if_match(),
            ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    rec = svc.update(ctx, cr_id, body, if_match)
    return _ok(rec, etag=rec["row_version"])


@router.delete("/eco/{cr_id}", status_code=204, dependencies=P("eco_edit"))
def delete_eco(cr_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import eco as svc

    svc.delete(ctx, cr_id, if_match)
    return Response(status_code=204)


@router.post("/eco/{cr_id}/items", status_code=201, dependencies=P("eco_edit"))
def add_eco_item(cr_id: str, body: ChangeRequestItemInput, if_match: str | None = _if_match(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    rec = svc.add_item(ctx, cr_id, body, if_match)
    return _ok(rec, 201, etag=rec["row_version"])


@router.delete("/eco/{cr_id}/items/{item_id}", dependencies=P("eco_edit"))
def delete_eco_item(cr_id: str, item_id: str, if_match: str | None = _if_match(),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    rec = svc.delete_item(ctx, cr_id, item_id, if_match)
    return _ok(rec, etag=rec["row_version"])


@router.get("/eco/{cr_id}/impact", dependencies=P("view"))
def eco_impact(cr_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import eco as svc

    return _ok(svc.impact(ctx, cr_id))


def _eco_action(name: str, perm: str) -> None:
    @router.post(f"/eco/{{cr_id}}/{name}", dependencies=P(perm), name=f"eco_{name}")
    def act(cr_id: str, body: EcoActionInput | None = None, if_match: str | None = _if_match(),
            p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
        from .services import eco as svc

        rec = svc.act(ctx, cr_id, name, (body.note if body else ""), if_match,
                      privileged=p.is_owner or "plant_admin" in p.roles)
        return _ok(rec, etag=rec["row_version"])


for _n, _p in (("submit", "eco_edit"), ("approve", "eco_approve"), ("reject", "eco_approve"),
               ("cancel", "eco_edit"), ("implement", "eco_edit")):
    _eco_action(_n, _p)


# ---------------------------------------------------------------- transfers (3.5)

@router.get("/transfer-orders", dependencies=P("view"))
def list_transfers(direction: Literal["out", "in"] | None = None,
                   status: str | None = Query(default=None, max_length=16), limit: int = Limit(),
                   offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import transfers as svc

    return _ok(svc.list_(ctx, direction, status, limit, offset))


@router.post("/transfer-orders", status_code=201, dependencies=P("transfer_edit"))
def create_transfer(body: TransferOrderInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import transfers as svc

    rec = svc.create(ctx, body)
    return _ok(rec, 201, etag=rec["row_version"])


@router.get("/transfer-orders/{to_id}", dependencies=P("view"))
def get_transfer(to_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import transfers as svc

    rec = svc.get(ctx, to_id)
    return _ok(rec, etag=rec["row_version"])


@router.put("/transfer-orders/{to_id}", dependencies=P("transfer_edit"))
def put_transfer(to_id: str, body: TransferOrderInput, if_match: str | None = _if_match(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import transfers as svc

    rec = svc.update(ctx, to_id, body, if_match)
    return _ok(rec, etag=rec["row_version"])


@router.delete("/transfer-orders/{to_id}", status_code=204, dependencies=P("transfer_edit"))
def delete_transfer(to_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import transfers as svc

    svc.delete(ctx, to_id, if_match)
    return Response(status_code=204)


def _to_action(name: str) -> None:
    @router.post(f"/transfer-orders/{{to_id}}/{name}", dependencies=P("transfer_edit"), name=f"transfer_{name}")
    def act(to_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
        from .services import transfers as svc

        rec = svc.action(ctx, to_id, name, if_match)
        return _ok(rec, etag=rec["row_version"])


for _n in ("open", "close", "cancel"):
    _to_action(_n)


# ---------------------------------------------------------------- audit (7): owner / plant_admin of the workspace

def _audit_principal(p: MfgPrincipal = Depends(mfg_principal)) -> MfgPrincipal:
    if not (p.is_owner or "plant_admin" in p.roles) or (p.scopes is not None and "owner" not in p.scopes):
        raise ApiError(403, "MFG_FORBIDDEN", "Only the plant owner or a plant admin can read the audit log.",
                       {"permission": "owner"})
    return p


def _conds(p: MfgPrincipal, frm: datetime | None, to: datetime | None, entity_type: str | None,
           actor: str | None) -> list[Any]:
    from ..db.models import AuditEventRow

    c = [AuditEventRow.owner_id == p.owner_id]
    if frm is not None:
        c.append(AuditEventRow.created_at >= frm)
    if to is not None:
        c.append(AuditEventRow.created_at < to)
    if entity_type:
        c.append(AuditEventRow.entity_type == entity_type)
    if actor:
        c.append(AuditEventRow.actor_id == actor)
    return c


def _row(r: Any) -> dict[str, Any]:
    from ..schemas import as_utc

    return {"id": int(r.id), "entity_type": r.entity_type, "entity_id": r.entity_id, "action": r.action,
            "details": r.details or {}, "actor_id": r.actor_id, "owner_id": r.owner_id,
            "created_at": as_utc(r.created_at), "chain_hash": r.chain_hash}


@audit_router.get("/events")
def audit_events(frm: datetime | None = Query(default=None, alias="from"), to: datetime | None = None,
                 entity_type: str | None = Query(default=None, max_length=32), actor: str | None = Id(),
                 limit: int = Limit(), offset: int = Offset(), p: MfgPrincipal = Depends(_audit_principal),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ..db.models import AuditEventRow
    from ..db.ownership import system_scope

    conds = _conds(p, frm, to, entity_type, actor)
    with system_scope(), ctx.db.read() as s:
        total = int(s.execute(select(func.count()).select_from(AuditEventRow).where(*conds)).scalar() or 0)
        rows = [_row(r) for r in s.execute(select(AuditEventRow).where(*conds).order_by(AuditEventRow.id.desc())
                                           .limit(limit).offset(offset)).scalars()]
    return _ok({"items": rows, "total": total, "limit": limit, "offset": offset})


@audit_router.get("/verify")
def audit_verify(p: MfgPrincipal = Depends(_audit_principal), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    """7: the `manage.py audit-verify` check of the workspace's chain -> {ok, checked, first_broken {id, at}}."""
    from ..audit_chain import verify
    from ..db.models import AuditEventRow
    from ..db.ownership import system_scope
    from ..schemas import as_utc

    with system_scope(), ctx.db.read() as s:
        r = verify(s, p.owner_id)
        fb = None
        if r["first_broken_id"] is not None:
            row = s.get(AuditEventRow, r["first_broken_id"])
            fb = {"id": r["first_broken_id"], "at": as_utc(row.created_at) if row else None}
    return _ok({"ok": r["ok"], "checked": r["checked"], "first_broken": fb})


@audit_router.get("/export")
def audit_export(format: Literal["jsonl", "csv"] = "jsonl",  # noqa: A002
                 frm: datetime | None = Query(default=None, alias="from"), to: datetime | None = None,
                 p: MfgPrincipal = Depends(_audit_principal), ctx: AppContext = Depends(get_ctx)) -> Response:
    """Streamed in id order with a keyset cursor (constant memory, AP2)."""
    from ..db.models import AuditEventRow
    from ..db.ownership import system_scope
    from .services.common import jsonable

    conds = _conds(p, frm, to, None, None)
    cols = ["id", "entity_type", "entity_id", "action", "actor_id", "owner_id", "created_at", "chain_hash",
            "details"]

    def gen() -> Iterator[bytes]:
        last = 0
        if format == "csv":
            yield (",".join(cols) + "\n").encode()
        while True:
            with system_scope(), ctx.db.read() as s:
                rows = [_row(r) for r in s.execute(select(AuditEventRow).where(*conds, AuditEventRow.id > last)
                                                   .order_by(AuditEventRow.id).limit(5000)).scalars()]
            if not rows:
                return
            last = rows[-1]["id"]
            buf = io.StringIO()
            if format == "csv":
                w = csv.writer(buf)
                for r in rows:
                    j = jsonable(r)
                    w.writerow([j[c] if c != "details" else json.dumps(j[c], sort_keys=True) for c in cols])
            else:
                for r in rows:
                    buf.write(json.dumps(jsonable(r), sort_keys=True) + "\n")
            yield buf.getvalue().encode()

    media = "text/csv" if format == "csv" else "application/x-ndjson"
    return StreamingResponse(gen(), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="audit.{format}"'})
