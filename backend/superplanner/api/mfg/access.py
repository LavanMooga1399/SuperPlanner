"""Workspaces, roles and permissions of `/api/v1/mfg` (M2-DESIGN 10).

- `mfg_principal` (async dependency, runs after `require_user`): `X-SP-Workspace: <owner user id>` absent or equal to
  the caller -> own workspace (role `owner`). Otherwise the active membership is loaded in `system_scope()`; found ->
  `bind_owner(owner_id)` (the central ownership filter then serves the owner's rows) and `bind_actor(user_id)`;
  else 404 `NOT_FOUND` ("Workspace not found"). In `single_user` mode a foreign workspace is always 404.
- `require_perm(p)` (async): the permission of 10.2 or 403 `MFG_FORBIDDEN`. Every mfg route declares exactly one.

Both are `async def` on purpose: a sync dependency runs in the threadpool and its context variables would not reach
the handler (as `require_user`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from ..context import AppContext, get_ctx
from ..db.ownership import bind_actor, bind_owner, system_scope
from ..errors import ApiError

PERMISSIONS: tuple[str, ...] = ("view", "master_edit", "supplier_edit", "inventory", "pr_edit", "pr_approve",
                                "po_edit", "demand_edit", "wo_edit", "mrp_run", "schedule_run", "schedule_publish",
                                "import", "owner",
                                # M4-DESIGN 11
                                "floor_view", "floor_report", "floor_supervise", "downtime_report", "replan_manage",
                                # M5-DESIGN 9
                                "trace_view", "eco_edit", "eco_approve", "transfer_edit", "integration_admin",
                                # M6-DESIGN 5
                                "assistant_use")
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(PERMISSIONS),
    "plant_admin": frozenset(PERMISSIONS),          # M5-DESIGN 3.4: owner-equivalent in an organisation's plant
    "planner": frozenset({"view", "master_edit", "supplier_edit", "pr_edit", "demand_edit", "wo_edit", "mrp_run",
                          "schedule_run", "schedule_publish", "import",   # M3-DESIGN 11
                          "floor_view", "floor_report", "downtime_report", "replan_manage", "trace_view", "eco_edit", "transfer_edit",
                          "assistant_use"}),   # M4-DESIGN 11, M6 5
    "purchaser": frozenset({"view", "supplier_edit", "pr_edit", "po_edit", "floor_view", "trace_view",
                            "assistant_use"}),
    "store_keeper": frozenset({"view", "inventory", "floor_view", "trace_view", "transfer_edit", "assistant_use"}),
    "approver": frozenset({"view", "pr_approve", "floor_view", "trace_view", "eco_approve", "assistant_use"}),
    "viewer": frozenset({"view", "floor_view", "trace_view", "assistant_use"}),
    # M4-DESIGN 0.4 / 11: tablets (personal or station accounts) and shift supervisors
    "operator": frozenset({"view", "floor_view", "floor_report", "downtime_report", "trace_view"}),
    "supervisor": frozenset({"view", "floor_view", "floor_report", "floor_supervise", "downtime_report", "trace_view",
                            "assistant_use"}),   # M6 5: every plant role except operator
}
ROLE_LABELS = {"owner": "Owner", "planner": "Planner", "purchaser": "Purchaser", "store_keeper": "Store keeper",
               "approver": "Approver", "viewer": "Viewer", "operator": "Operator", "supervisor": "Supervisor",
               "plant_admin": "Plant admin"}
WORKSPACE_HEADER = "X-SP-Workspace"


@dataclass(frozen=True)
class MfgPrincipal:
    user_id: str
    owner_id: str
    is_owner: bool
    roles: tuple[str, ...]
    permissions: frozenset[str] = field(default_factory=frozenset)
    #: M5-DESIGN 3.3: the bearer token's scopes (None for sessions); permissions are already capped by them
    scopes: frozenset[str] | None = None
    token_id: str | None = None
    #: the role permissions before the token cap (integration scopes need `integration_admin` there)
    role_permissions: frozenset[str] | None = None

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def permissions_of(roles: tuple[str, ...] | list[str]) -> frozenset[str]:
    out: set[str] = set()
    for r in roles:
        out |= ROLE_PERMISSIONS.get(r, frozenset())
    return frozenset(out)


def roles_allowed(perm: str) -> list[str]:
    return [r for r in ("owner", "plant_admin", "planner", "purchaser", "store_keeper", "approver", "viewer",
                        "operator", "supervisor") if perm in ROLE_PERMISSIONS[r]]


def workspace_not_found(owner_id: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", "Workspace not found.", {"id": owner_id})


def _membership(ctx: AppContext, owner_id: str, user_id: str) -> tuple[str, ...] | None:
    from ..auth.models import UserRow
    from .db_models_m2 import MfgPlantMemberRow

    with system_scope(), ctx.db.read() as s:
        row = s.execute(select(MfgPlantMemberRow.roles).join(UserRow, UserRow.id == MfgPlantMemberRow.owner_id)
                        .where(MfgPlantMemberRow.owner_id == owner_id, MfgPlantMemberRow.user_id == user_id,
                               MfgPlantMemberRow.active.is_(True), UserRow.disabled.is_(False))).first()
    return tuple(row[0]) if row is not None else None


async def mfg_principal(request: Request, ctx: AppContext = Depends(get_ctx)) -> MfgPrincipal:
    cached = getattr(request.state, "mfg_principal", None)
    if cached is not None:
        return cached
    principal = getattr(request.state, "principal", None)
    if principal is None:  # pragma: no cover - require_user always runs first
        raise ApiError(401, "AUTH_REQUIRED", "Please sign in to continue.")
    user_id = principal.user_id
    target = (request.headers.get(WORKSPACE_HEADER) or "").strip()
    scopes = getattr(principal, "scopes", None)
    if scopes is not None:                 # API token: its own workspace only (3.3)
        ws = principal.workspace_owner_id
        if target and target != ws:
            raise workspace_not_found(target[:64])
        target = "" if ws == user_id else ws
    if not target or target == user_id:
        p = MfgPrincipal(user_id, user_id, True, ("owner",), ROLE_PERMISSIONS["owner"])
    else:
        if ctx.settings.single_user or len(target) > 64:
            raise workspace_not_found(target[:64])
        roles = await run_in_threadpool(_membership, ctx, target, user_id)
        if not roles:
            raise workspace_not_found(target)
        p = MfgPrincipal(user_id, target, False, tuple(r for r in roles if r in ROLE_PERMISSIONS),
                         permissions_of(list(roles)))
        bind_owner(target)
    if scopes is not None:
        from dataclasses import replace

        p = replace(p, permissions=frozenset(p.permissions & scopes), scopes=scopes, token_id=principal.token_id,
                    role_permissions=p.permissions)
    bind_actor(user_id)
    request.state.mfg_principal = p
    return p


def require_integration(scope: str) -> Any:
    """M5-DESIGN 9: integration endpoints - sessions need `integration_admin`; API tokens need the scope
    (`integration.read` / `integration.write`) and a holder with `integration_admin` in the plant."""

    async def _check(p: MfgPrincipal = Depends(mfg_principal)) -> MfgPrincipal:
        if p.scopes is not None:
            if scope not in p.scopes and "integration_admin" not in p.scopes:
                raise ApiError(403, "TOKEN_SCOPE", f"This API token lacks the scope {scope!r}.",
                               {"permission": scope, "scopes": sorted(p.scopes)})
            if "integration_admin" not in (p.role_permissions or frozenset()):
                raise ApiError(403, "MFG_FORBIDDEN", "The token's holder cannot administer integration here.",
                               {"permission": "integration_admin"})
            return p
        if not p.has("integration_admin"):
            raise ApiError(403, "MFG_FORBIDDEN", "Your role in this workspace does not allow this (needs: Plant "
                           "admin).", {"permission": "integration_admin", "roles_allowed": roles_allowed(
                               "integration_admin")})
        return p

    _check.__name__ = f"require_integration_{scope.replace('.', '_')}"
    _check.mfg_permission = scope  # type: ignore[attr-defined]
    return Depends(_check)


def require_perm(perm: str) -> Any:
    if perm not in PERMISSIONS:  # pragma: no cover - programming error
        raise ValueError(perm)

    async def _check(p: MfgPrincipal = Depends(mfg_principal)) -> MfgPrincipal:
        if not p.has(perm) and p.scopes is not None and perm not in p.scopes:
            raise ApiError(403, "TOKEN_SCOPE", f"This API token lacks the scope {perm!r}.",
                           {"permission": perm, "scopes": sorted(p.scopes)})
        if not p.has(perm):
            allowed = roles_allowed(perm)
            needs = ", ".join(ROLE_LABELS[r] for r in allowed if r != "owner") or "Owner"
            raise ApiError(403, "MFG_FORBIDDEN", f"Your role in this workspace does not allow this (needs: {needs}).",
                           {"permission": perm, "roles_allowed": allowed})
        return p

    _check.__name__ = f"require_perm_{perm}"
    _check.mfg_permission = perm  # type: ignore[attr-defined]
    return Depends(_check)


def principal_of(request: Request) -> MfgPrincipal:
    p = getattr(request.state, "mfg_principal", None)
    if p is None:  # pragma: no cover
        raise RuntimeError("mfg_principal did not run")
    return p


__all__ = ["MfgPrincipal", "PERMISSIONS", "ROLE_LABELS", "ROLE_PERMISSIONS", "WORKSPACE_HEADER", "mfg_principal",
           "permissions_of", "principal_of", "require_perm", "roles_allowed"]
