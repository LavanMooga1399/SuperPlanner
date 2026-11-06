"""`/api/v1/orgs` (M5-DESIGN 3.4, 9): org admins manage organisations, members, plants and plant roles; org
members see the overview of the plants they can view. Sessions only (API tokens are plant-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from ..api.auth.deps import Principal, require_user
from ..api.context import AppContext, get_ctx
from ..api.errors import ApiError
from ..api.mfg.router_m2 import _ok
from . import service as svc
from .model import (OrgIn, OrgMemberIn, OrgMemberUpdate, OrgPlantIn, OrgPlantUpdate, OrgUpdate, PlantRolesIn,
                    PublishIn)

router = APIRouter(prefix="/orgs", tags=["orgs"])


def person(p: Principal = Depends(require_user), ctx: AppContext = Depends(get_ctx)) -> str:
    if p.token_id is not None:
        raise ApiError(403, "TOKEN_SCOPE", "Organisations are managed with a signed-in session.",
                       {"permission": "session"})
    if ctx.settings.single_user:
        raise ApiError(404, "NOT_FOUND", "Organisations need accounts mode.", {})
    return p.user_id


@router.get("")
def list_orgs(u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_orgs(ctx, u))


@router.post("", status_code=201)
def create_org(body: OrgIn, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.create_org(ctx, u, body), 201)


@router.get("/{org_id}")
def get_org(org_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.get_org(ctx, u, org_id))


@router.put("/{org_id}")
def put_org(org_id: str, body: OrgUpdate, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)
            ) -> JSONResponse:
    return _ok(svc.update_org(ctx, u, org_id, body))


@router.get("/{org_id}/members")
def list_members(org_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_members(ctx, u, org_id))


@router.post("/{org_id}/members", status_code=201)
def add_member(org_id: str, body: OrgMemberIn, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)
               ) -> JSONResponse:
    return _ok(svc.add_member(ctx, u, org_id, body), 201)


@router.put("/{org_id}/members/{member_id}")
def put_member(org_id: str, member_id: str, body: OrgMemberUpdate, u: str = Depends(person),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.update_member(ctx, u, org_id, member_id, body))


@router.delete("/{org_id}/members/{member_id}", status_code=204)
def delete_member(org_id: str, member_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)
                  ) -> Response:
    svc.remove_member(ctx, u, org_id, member_id)
    return Response(status_code=204)


@router.get("/{org_id}/plants")
def list_plants(org_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_plants(ctx, u, org_id))


@router.post("/{org_id}/plants", status_code=201)
def create_plant(org_id: str, body: OrgPlantIn, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)
                 ) -> JSONResponse:
    return _ok(svc.create_plant(ctx, u, org_id, body), 201)


@router.put("/{org_id}/plants/{plant}")
def put_plant(org_id: str, plant: str, body: OrgPlantUpdate, u: str = Depends(person),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.update_plant(ctx, u, org_id, plant, body))


@router.post("/{org_id}/plants/{plant}/roles")
def grant_roles(org_id: str, plant: str, body: PlantRolesIn, u: str = Depends(person),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.grant_roles(ctx, u, org_id, plant, body))


@router.post("/{org_id}/publish", status_code=202)
def publish(org_id: str, body: PublishIn, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)
            ) -> JSONResponse:
    return _ok(svc.publish(ctx, u, org_id, body), 202)


@router.get("/{org_id}/overview")
def overview(org_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.overview(ctx, u, org_id))


@router.get("/{org_id}/publish/{publish_id}")
def get_publish(org_id: str, publish_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    return _ok(svc.get_publish(ctx, u, org_id, publish_id))


@router.post("/{org_id}/accept")
def accept(org_id: str, u: str = Depends(person), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    """An invited member accepts the organisation's invitation."""
    return _ok(svc.accept(ctx, u, org_id))
