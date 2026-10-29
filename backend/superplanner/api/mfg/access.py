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
                                "po_edit", "demand_edit", "wo_edit", "mrp_run", "import", "owner")
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(PERMISSIONS),
    "planner": frozenset({"view", "master_edit", "supplier_edit", "pr_edit", "demand_edit", "wo_edit", "mrp_run",
                          "import"}),
    "purchaser": frozenset({"view", "supplier_edit", "pr_edit", "po_edit"}),
    "store_keeper": frozenset({"view", "inventory"}),
    "approver": frozenset({"view", "pr_approve"}),
    "viewer": frozenset({"view"}),
}
ROLE_LABELS = {"owner": "Owner", "planner": "Planner", "purchaser": "Purchaser", "store_keeper": "Store keeper",
               "approver": "Approver", "viewer": "Viewer"}
WORKSPACE_HEADER = "X-SP-Workspace"


@dataclass(frozen=True)
class MfgPrincipal:
    user_id: str
    owner_id: str
    is_owner: bool
    roles: tuple[str, ...]
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def permissions_of(roles: tuple[str, ...] | list[str]) -> frozenset[str]:
    out: set[str] = set()
    for r in roles:
        out |= ROLE_PERMISSIONS.get(r, frozenset())
    return frozenset(out)


def roles_allowed(perm: str) -> list[str]:
    return [r for r in ("owner", "planner", "purchaser", "store_keeper", "approver", "viewer")
            if perm in ROLE_PERMISSIONS[r]]


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
    bind_actor(user_id)
    request.state.mfg_principal = p
    return p


def require_perm(perm: str) -> Any:
    if perm not in PERMISSIONS:  # pragma: no cover - programming error
        raise ValueError(perm)

    async def _check(p: MfgPrincipal = Depends(mfg_principal)) -> MfgPrincipal:
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
