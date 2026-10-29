"""Workspace members, `/me` and `/workspaces` (M2-DESIGN 3.8, 10, 12.3 #78-83).

Memberships are rows of the owner's workspace (`mfg_plant_members`, owned by the workspace owner); only the owner
manages them (permission `owner`). Users are looked up in `system_scope()` (the users table is not owned).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ....mfg import limits as L
from ....mfg.model_m2 import MemberInput, MemberRecord, MemberUpdate, MemberUser
from ...auth.models import UserRow
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.ownership import system_scope
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo
from ..access import MfgPrincipal
from ..db_models import MfgPlantRow
from ..db_models_m2 import MfgPlantMemberRow
from .common import audit, check_version, read_tx, touch, write_tx


def _unavailable(ctx: AppContext) -> None:
    if ctx.settings.single_user:
        raise ApiError(422, "MBR_UNAVAILABLE", "Workspace members need accounts mode (AUTH_MODE=accounts).")


def _users(s: Any, ids: list[str]) -> dict[str, UserRow]:
    if not ids:
        return {}
    with system_scope():
        return {u.id: u for u in s.execute(select(UserRow).where(UserRow.id.in_(sorted(set(ids))))).scalars()}


def _record(row: MfgPlantMemberRow, user: UserRow | None) -> MemberRecord:
    mu = MemberUser.model_construct(id=row.user_id, email=user.email if user else None,
                                    display_name=user.display_name if user else None)
    return MemberRecord.model_construct(id=row.id, user=mu, roles=list(row.roles or []), active=row.active,
                                        row_version=row.row_version, created_at=as_utc(row.created_at),
                                        updated_at=as_utc(row.updated_at))


def list_members(ctx: AppContext) -> dict[str, Any]:
    _unavailable(ctx)
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgPlantMemberRow).order_by(MfgPlantMemberRow.created_at,
                                                                 MfgPlantMemberRow.id)).scalars())
        users = _users(s, [r.user_id for r in rows])
        recs = [_record(r, users.get(r.user_id)) for r in rows]
        recs.sort(key=lambda m: ((m.user.email or ""), m.id))
        return {"items": recs}


def add_member(ctx: AppContext, inp: MemberInput, owner_id: str) -> MemberRecord:
    _unavailable(ctx)
    email = inp.email.strip().lower()
    with write_tx(ctx, lock=False) as (s, _):
        with system_scope():
            user = s.execute(select(UserRow).where(UserRow.email == email)).scalars().first()
        if user is None or user.disabled or user.is_local:
            raise ApiError(422, "MBR_USER_NOT_FOUND", f"No active account uses {email!r}. Ask them to sign up first.",
                           {"loc": ["body", "email"]})
        if user.id == owner_id:
            raise ApiError(422, "MBR_SELF", "You own this workspace already.", {"loc": ["body", "email"]})
        dup = s.execute(select(MfgPlantMemberRow.id).where(MfgPlantMemberRow.user_id == user.id)).scalar()
        if dup is not None:
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"{email} is already a member of this workspace.",
                           {"key": {"email": email}, "existing_id": dup})
        n = int(s.execute(select(func.count()).select_from(MfgPlantMemberRow)).scalar() or 0)
        if n >= L.MAX_MEMBERS:
            raise ApiError(422, "MFG_LIMIT", f"A workspace can have at most {L.MAX_MEMBERS} members.",
                           {"limit": L.MAX_MEMBERS, "count": n})
        now = utcnow()
        row = MfgPlantMemberRow(id=new_id("mbr_"), user_id=user.id, roles=list(inp.roles), active=inp.active,
                                invited_by=owner_id, row_version=1, created_at=now, updated_at=now)
        s.add(row)
        s.flush()
        audit(s, "member", row.id, "member_add", {"user_id": user.id, "roles": list(inp.roles)})
        return _record(row, user)


def update_member(ctx: AppContext, member_id: str, inp: MemberUpdate, if_match: str | None) -> MemberRecord:
    _unavailable(ctx)
    with write_tx(ctx, lock=False) as (s, _):
        row = repo.get_row(s, MfgPlantMemberRow, member_id, what="Member", lock=True)
        check_version(row, if_match)
        row.roles = list(inp.roles)
        row.active = inp.active
        touch(row)
        s.flush()
        audit(s, "member", row.id, "member_update", {"roles": list(inp.roles), "active": inp.active,
                                                      "version": row.row_version})
        return _record(row, _users(s, [row.user_id]).get(row.user_id))


def remove_member(ctx: AppContext, member_id: str, if_match: str | None) -> None:
    _unavailable(ctx)
    with write_tx(ctx, lock=False) as (s, _):
        row = repo.get_row(s, MfgPlantMemberRow, member_id, what="Member", lock=True)
        check_version(row, if_match)
        audit(s, "member", row.id, "member_remove", {"user_id": row.user_id})
        s.delete(row)
        s.flush()


# ---------------------------------------------------------------- me, workspaces


def me(ctx: AppContext, p: MfgPrincipal) -> dict[str, Any]:
    with read_tx(ctx) as s:
        name = repo.plant_or_default(s).name
    from ..access import PERMISSIONS

    return {"user_id": p.user_id, "workspace_owner_id": p.owner_id, "workspace_name": name, "is_owner": p.is_owner,
            "roles": list(p.roles), "permissions": [x for x in PERMISSIONS if x in p.permissions]}


def workspaces(ctx: AppContext, user_id: str) -> dict[str, Any]:
    """Own workspace first, then active memberships (by plant name)."""
    with system_scope(), ctx.db.read() as s:
        own = s.execute(select(MfgPlantRow.name).where(MfgPlantRow.owner_id == user_id)).scalar()
        out = [{"owner_id": user_id, "plant_name": own or "Plant", "is_owner": True, "roles": ["owner"]}]
        if not ctx.settings.single_user:
            rows = s.execute(select(MfgPlantMemberRow.owner_id, MfgPlantMemberRow.roles, MfgPlantRow.name,
                                    UserRow.email)
                             .join(UserRow, UserRow.id == MfgPlantMemberRow.owner_id)
                             .outerjoin(MfgPlantRow, MfgPlantRow.owner_id == MfgPlantMemberRow.owner_id)
                             .where(MfgPlantMemberRow.user_id == user_id, MfgPlantMemberRow.active.is_(True),
                                    UserRow.disabled.is_(False))).all()
            others = [{"owner_id": r[0], "plant_name": r[2] or f"Plant of {r[3] or r[0]}", "is_owner": False,
                       "roles": list(r[1] or [])} for r in rows]
            others.sort(key=lambda w: (w["plant_name"], w["owner_id"]))
            out += others
    return {"items": out}
