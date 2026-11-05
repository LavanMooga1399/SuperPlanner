"""Organisations and plants (M5-DESIGN 3.4). Platform tables in system scope; plant data stays owned by the plant
principal (`users.kind = plant`), reached through M2 workspace memberships (`plant_admin` = owner-equivalent).
Cross-plant isolation is the M2 one: a person sees a plant only through an active membership of that plant."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ..api.auth.models import UserRow
from ..api.context import AppContext
from ..api.db import new_id, utcnow
from ..api.db.ownership import owner_scope, system_scope
from ..api.errors import ApiError
from ..api.mfg.db_models_m2 import MfgPlantMemberRow
from ..api.mfg.db_models_m5 import OrgMemberRow, OrgPlantRow, OrgPublishRow, OrgRow
from ..api.schemas import as_utc


def _role(s: Any, org_id: str, user_id: str) -> str | None:
    return s.execute(select(OrgMemberRow.org_role).where(OrgMemberRow.org_id == org_id,
                                                         OrgMemberRow.user_id == user_id)).scalar()


def _org(s: Any, org_id: str, user_id: str, *, admin: bool) -> tuple[OrgRow, str]:
    org = s.get(OrgRow, org_id) if len(org_id) <= 64 else None
    role = _role(s, org_id, user_id) if org is not None else None
    if org is None or role is None:
        raise ApiError(404, "NOT_FOUND", "Organisation not found.", {"id": org_id[:64]})
    if admin and role != "org_admin":
        raise ApiError(403, "MFG_FORBIDDEN", "Only organisation admins can do this.", {"permission": "org_admin"})
    return org, role


def org_record(s: Any, o: OrgRow, role: str | None) -> dict[str, Any]:
    return {"id": o.id, "name": o.name, "slug": o.slug, "require_2fa": o.require_2fa, "my_role": role,
            "plants": int(s.execute(select(func.count()).select_from(OrgPlantRow).where(OrgPlantRow.org_id == o.id))
                          .scalar() or 0),
            "members": int(s.execute(select(func.count()).select_from(OrgMemberRow).where(
                OrgMemberRow.org_id == o.id)).scalar() or 0),
            "row_version": o.row_version, "created_at": as_utc(o.created_at)}


def list_orgs(ctx: AppContext, user_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        rows = s.execute(select(OrgRow, OrgMemberRow.org_role).join(OrgMemberRow, OrgMemberRow.org_id == OrgRow.id)
                         .where(OrgMemberRow.user_id == user_id).order_by(OrgRow.name)).all()
        return {"items": [org_record(s, o, r) for o, r in rows]}


def create_org(ctx: AppContext, user_id: str, inp: Any) -> dict[str, Any]:
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        if s.execute(select(OrgRow.id).where(OrgRow.slug == inp.slug)).first():
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"An organisation with slug {inp.slug!r} exists.",
                           {"key": {"slug": inp.slug}})
        o = OrgRow(id=new_id("org_"), name=inp.name, slug=inp.slug, require_2fa=inp.require_2fa, created_at=now,
                   updated_at=now, row_version=1)
        s.add(o)
        s.flush()
        s.add(OrgMemberRow(id=new_id("orm_"), org_id=o.id, user_id=user_id, org_role="org_admin", created_at=now,
                           row_version=1))
        s.flush()
        return org_record(s, o, "org_admin")


def get_org(ctx: AppContext, user_id: str, org_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        o, role = _org(s, org_id, user_id, admin=False)
        return org_record(s, o, role)


def update_org(ctx: AppContext, user_id: str, org_id: str, inp: Any) -> dict[str, Any]:
    with system_scope(), ctx.db.write() as s:
        o, role = _org(s, org_id, user_id, admin=True)
        o.name, o.require_2fa, o.updated_at, o.row_version = inp.name, inp.require_2fa, utcnow(), o.row_version + 1
        s.flush()
        return org_record(s, o, role)


def _plants(s: Any, org_id: str) -> list[OrgPlantRow]:
    return list(s.execute(select(OrgPlantRow).where(OrgPlantRow.org_id == org_id).order_by(OrgPlantRow.code))
                .scalars())


def _member_plants(s: Any, org_id: str, user_id: str) -> list[dict[str, Any]]:
    out = []
    for p in _plants(s, org_id):
        roles = s.execute(select(MfgPlantMemberRow.roles).where(MfgPlantMemberRow.owner_id == p.plant_owner_id,
                                                                MfgPlantMemberRow.user_id == user_id,
                                                                MfgPlantMemberRow.active.is_(True))).scalar()
        if roles:
            out.append({"plant_owner_id": p.plant_owner_id, "code": p.code, "roles": list(roles)})
    return out


def member_record(s: Any, m: OrgMemberRow, u: UserRow | None) -> dict[str, Any]:
    return {"id": m.id, "user": {"id": m.user_id, "email": u.email if u else None,
                                 "display_name": u.display_name if u else None, "disabled": bool(u and u.disabled)},
            "org_role": m.org_role, "plants": _member_plants(s, m.org_id, m.user_id), "row_version": m.row_version,
            "created_at": as_utc(m.created_at)}


def list_members(ctx: AppContext, user_id: str, org_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        _org(s, org_id, user_id, admin=True)
        rows = s.execute(select(OrgMemberRow, UserRow).join(UserRow, UserRow.id == OrgMemberRow.user_id)
                         .where(OrgMemberRow.org_id == org_id).order_by(UserRow.email)).all()
        return {"items": [member_record(s, m, u) for m, u in rows]}


def add_member(ctx: AppContext, user_id: str, org_id: str, inp: Any) -> dict[str, Any]:
    email = inp.email.strip().lower()
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        u = s.execute(select(UserRow).where(UserRow.email == email)).scalars().first()
        if u is None or u.disabled or u.kind != "person":
            raise ApiError(422, "MBR_USER_NOT_FOUND", f"No active account uses {email!r}.", {"loc": ["body", "email"]})
        if _role(s, org_id, u.id) is not None:
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"{email} is already a member.", {"key": {"email": email}})
        m = OrgMemberRow(id=new_id("orm_"), org_id=org_id, user_id=u.id, org_role=inp.org_role, created_at=utcnow(),
                         row_version=1)
        s.add(m)
        s.flush()
        return member_record(s, m, u)


def _member(s: Any, org_id: str, member_id: str) -> OrgMemberRow:
    m = s.get(OrgMemberRow, member_id) if len(member_id) <= 64 else None
    if m is None or m.org_id != org_id:
        raise ApiError(404, "NOT_FOUND", "Member not found.", {"id": member_id[:64]})
    return m


def update_member(ctx: AppContext, user_id: str, org_id: str, member_id: str, inp: Any) -> dict[str, Any]:
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        m = _member(s, org_id, member_id)
        if m.org_role == "org_admin" and inp.org_role != "org_admin" and _admins(s, org_id) <= 1:
            raise ApiError(409, "ORG_LAST_ADMIN", "An organisation keeps at least one admin.", {})
        m.org_role, m.row_version = inp.org_role, m.row_version + 1
        s.flush()
        return member_record(s, m, s.get(UserRow, m.user_id))


def _admins(s: Any, org_id: str) -> int:
    return int(s.execute(select(func.count()).select_from(OrgMemberRow).where(
        OrgMemberRow.org_id == org_id, OrgMemberRow.org_role == "org_admin")).scalar() or 0)


def remove_member(ctx: AppContext, user_id: str, org_id: str, member_id: str) -> None:
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        m = _member(s, org_id, member_id)
        if m.org_role == "org_admin" and _admins(s, org_id) <= 1:
            raise ApiError(409, "ORG_LAST_ADMIN", "An organisation keeps at least one admin.", {})
        for p in _plants(s, org_id):          # their plant memberships of this organisation go too
            for mm in s.execute(select(MfgPlantMemberRow).where(MfgPlantMemberRow.owner_id == p.plant_owner_id,
                                                                MfgPlantMemberRow.user_id == m.user_id)).scalars():
                s.delete(mm)
        s.delete(m)


def plant_record(s: Any, p: OrgPlantRow, user_id: str) -> dict[str, Any]:
    roles = s.execute(select(MfgPlantMemberRow.roles).where(MfgPlantMemberRow.owner_id == p.plant_owner_id,
                                                            MfgPlantMemberRow.user_id == user_id,
                                                            MfgPlantMemberRow.active.is_(True))).scalar()
    return {"id": p.id, "code": p.code, "name": p.name, "plant_owner_id": p.plant_owner_id,
            "my_roles": list(roles or []), "row_version": p.row_version, "created_at": as_utc(p.created_at)}


def list_plants(ctx: AppContext, user_id: str, org_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        _o, role = _org(s, org_id, user_id, admin=False)
        items = [plant_record(s, p, user_id) for p in _plants(s, org_id)]
        if role != "org_admin":                # members see only plants they belong to
            items = [x for x in items if x["my_roles"]]
        return {"items": items}


def create_plant(ctx: AppContext, user_id: str, org_id: str, inp: Any) -> dict[str, Any]:
    from ..api.mfg import repo

    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        if s.execute(select(OrgPlantRow.id).where(OrgPlantRow.org_id == org_id, OrgPlantRow.code == inp.code)).first():
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"Plant {inp.code!r} exists.", {"key": {"code": inp.code}})
        principal = UserRow(id=new_id("usr_"), email=None, display_name=f"Plant {inp.code}"[:100], password_hash=None,
                            is_local=False, disabled=False, created_at=now, updated_at=now, kind="plant")
        s.add(principal)
        s.flush()
        p = OrgPlantRow(id=new_id("orp_"), org_id=org_id, plant_owner_id=principal.id, code=inp.code, name=inp.name,
                        created_at=now, row_version=1)
        s.add(p)
        s.flush()
    with owner_scope(principal.id), ctx.db.write() as s:
        plant = repo.lock_plant(s)
        plant.name, plant.utc_offset = inp.name, inp.utc_offset
        if inp.time_zone:
            plant.time_zone = inp.time_zone
        s.add(MfgPlantMemberRow(id=new_id("mbr_"), user_id=user_id, roles=["plant_admin"], active=True,
                                invited_by=user_id, row_version=1, created_at=now, updated_at=now))
    with system_scope(), ctx.db.read() as s:
        return plant_record(s, s.get(OrgPlantRow, p.id), user_id)


def _plant(s: Any, org_id: str, plant: str) -> OrgPlantRow:
    p = s.execute(select(OrgPlantRow).where(OrgPlantRow.org_id == org_id, (OrgPlantRow.id == plant) |
                                            (OrgPlantRow.plant_owner_id == plant) | (OrgPlantRow.code == plant))
                  ).scalars().first()
    if p is None:
        raise ApiError(404, "NOT_FOUND", "Plant not found.", {"id": plant[:64]})
    return p


def update_plant(ctx: AppContext, user_id: str, org_id: str, plant: str, inp: Any) -> dict[str, Any]:
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        p = _plant(s, org_id, plant)
        p.name, p.row_version = inp.name, p.row_version + 1
        s.flush()
        return plant_record(s, p, user_id)


def grant_roles(ctx: AppContext, user_id: str, org_id: str, plant: str, inp: Any) -> dict[str, Any]:
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        p = _plant(s, org_id, plant)
        if _role(s, org_id, inp.user_id) is None:
            raise ApiError(422, "MBR_USER_NOT_FOUND", "Plant roles are granted to members of the organisation.",
                           {"loc": ["body", "user_id"]})
        m = s.execute(select(MfgPlantMemberRow).where(MfgPlantMemberRow.owner_id == p.plant_owner_id,
                                                      MfgPlantMemberRow.user_id == inp.user_id)).scalars().first()
        if not inp.roles:
            if m is not None:
                s.delete(m)
        elif m is None:
            s.add(MfgPlantMemberRow(id=new_id("mbr_"), owner_id=p.plant_owner_id, user_id=inp.user_id,
                                    roles=list(inp.roles), active=True, invited_by=user_id, row_version=1,
                                    created_at=now, updated_at=now))
        else:
            m.roles, m.active, m.row_version, m.updated_at = list(inp.roles), True, m.row_version + 1, now
        s.flush()
        return {"plant_owner_id": p.plant_owner_id, "user_id": inp.user_id, "roles": list(inp.roles)}


def overview(ctx: AppContext, user_id: str, org_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        o, role = _org(s, org_id, user_id, admin=False)
        out = []
        for p in _plants(s, org_id):
            rec = plant_record(s, p, user_id)
            visible = bool(rec["my_roles"]) or role == "org_admin"
            out.append({"plant": {"code": p.code, "name": p.name, "owner_id": p.plant_owner_id}, "visible": visible,
                        "kpis": {}, "late_demand": None, "open_triggers": None, "integration": {}})
        return {"org": {"id": o.id, "name": o.name, "slug": o.slug}, "plants": out}


def publish(ctx: AppContext, user_id: str, org_id: str, inp: Any) -> dict[str, Any]:
    """Recorded as a publish run (job kind `org_publish`); S0: queued, executed in S1/S4 (15.WP-S)."""
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        for x in [inp.source_plant, *inp.target_plants]:
            _plant(s, org_id, x)
        r = OrgPublishRow(id=new_id("opb_"), org_id=org_id, source_owner_id=inp.source_plant,
                          target_owner_ids=list(inp.target_plants), scope=inp.scope,
                          part_number_prefix=inp.part_number_prefix, status="queued", results=None, actor_id=user_id,
                          created_at=now, finished_at=None)
        s.add(r)
        s.flush()
        return {"id": r.id, "org_id": org_id, "source_owner_id": r.source_owner_id,
                "target_owner_ids": r.target_owner_ids, "scope": r.scope, "part_number_prefix": r.part_number_prefix,
                "status": r.status, "results": None, "created_at": as_utc(now), "finished_at": None}


def run_publish_job(ctx: Any, run_id: str, lease: Any) -> None:  # pragma: no cover - S1 publish execution
    raise NotImplementedError
