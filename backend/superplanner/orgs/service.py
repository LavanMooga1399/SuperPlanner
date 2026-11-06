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


def _role(s: Any, org_id: str, user_id: str, *, accepted_only: bool = True) -> str | None:
    """The caller's org role; an invitation not yet accepted grants nothing (15.WP-S)."""
    q = select(OrgMemberRow.org_role).where(OrgMemberRow.org_id == org_id, OrgMemberRow.user_id == user_id)
    if accepted_only:
        q = q.where(OrgMemberRow.accepted_at.is_not(None))
    return s.execute(q).scalar()


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
        rows = s.execute(select(OrgRow, OrgMemberRow.org_role, OrgMemberRow.accepted_at).join(
            OrgMemberRow, OrgMemberRow.org_id == OrgRow.id).where(OrgMemberRow.user_id == user_id)
            .order_by(OrgRow.name)).all()
        return {"items": [{**org_record(s, o, r), "invited": a is None} for o, r, a in rows]}


def create_org(ctx: AppContext, user_id: str, inp: Any, *, operator: bool = False) -> dict[str, Any]:
    """`ORG_SELF_SERVICE=false` (default): only operators (`manage.py create-org`) create organisations."""
    if not operator and not ctx.settings.org_self_service:
        raise ApiError(403, "ORG_CREATE_DISABLED", "Organisations are created by the operator of this server.", {})
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        if s.execute(select(OrgRow.id).where(OrgRow.slug == inp.slug)).first():
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"An organisation with slug {inp.slug!r} exists.",
                           {"key": {"slug": inp.slug}})
        o = OrgRow(id=new_id("org_"), name=inp.name, slug=inp.slug, require_2fa=inp.require_2fa, created_at=now,
                   updated_at=now, row_version=1)
        s.add(o)
        s.flush()
        s.add(OrgMemberRow(id=new_id("orm_"), org_id=o.id, user_id=user_id, org_role="org_admin", accepted_at=now,
                           created_at=now,
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
            "org_role": m.org_role, "invited": m.accepted_at is None, "accepted_at": as_utc(m.accepted_at),
            "plants": _member_plants(s, m.org_id, m.user_id), "row_version": m.row_version,
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
        if _role(s, org_id, u.id, accepted_only=False) is not None:
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"{email} is already a member.", {"key": {"email": email}})
        accepted = utcnow() if ctx.settings.org_self_service else None
        if not ctx.settings.org_self_service and s.execute(select(OrgMemberRow.id).where(
                OrgMemberRow.user_id == u.id)).first() is not None:
            raise ApiError(409, "ORG_USER_IN_OTHER_ORG", f"{email} belongs to another organisation.",
                           {"loc": ["body", "email"]})
        m = OrgMemberRow(id=new_id("orm_"), org_id=org_id, user_id=u.id, org_role=inp.org_role, accepted_at=accepted,
                         created_at=utcnow(),
                         row_version=1)
        s.add(m)
        s.flush()
        return member_record(s, m, u)


def accept(ctx: AppContext, user_id: str, org_id: str) -> dict[str, Any]:
    """The invited user accepts the membership (15.WP-S: then the organisation manages the account)."""
    with system_scope(), ctx.db.write() as s:
        m = s.execute(select(OrgMemberRow).where(OrgMemberRow.org_id == org_id, OrgMemberRow.user_id == user_id)
                      .with_for_update()).scalars().first()
        if m is None:
            raise ApiError(404, "NOT_FOUND", "Organisation not found.", {"id": org_id[:64]})
        if m.accepted_at is None:
            m.accepted_at, m.row_version = utcnow(), m.row_version + 1
        s.flush()
        return member_record(s, m, s.get(UserRow, user_id))


def _member(s: Any, org_id: str, member_id: str) -> OrgMemberRow:
    m = s.get(OrgMemberRow, member_id) if len(member_id) <= 64 else None
    if m is None or m.org_id != org_id:
        raise ApiError(404, "NOT_FOUND", "Member not found.", {"id": member_id[:64]})
    return m


def update_member(ctx: AppContext, user_id: str, org_id: str, member_id: str, inp: Any) -> dict[str, Any]:
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        m = _member(s, org_id, member_id)
        role = inp.org_role or m.org_role
        if m.org_role == "org_admin" and role != "org_admin" and _admins(s, org_id) <= 1:
            raise ApiError(409, "ORG_LAST_ADMIN", "An organisation keeps at least one admin.", {})
        m.org_role, m.row_version = role, m.row_version + 1
        if inp.disabled is not None:
            if m.user_id == user_id:
                raise ApiError(422, "VALIDATION_ERROR", "You cannot disable your own account.", {})
            from ..identity.service import managed_by

            o = s.get(OrgRow, org_id)
            if not managed_by(s, o, m.user_id, ctx.settings.oidc_org_slug):
                raise ApiError(403, "ORG_USER_NOT_MANAGED", "This account also belongs to other organisations; "
                               "only an organisation that manages it can disable it.", {"user_id": m.user_id})
            from ..api.auth import sessions as sess

            u = s.get(UserRow, m.user_id)
            if u is not None and u.disabled != inp.disabled:
                now = utcnow()
                u.disabled, u.updated_at = inp.disabled, now
                if inp.disabled:
                    sess.revoke_all(s, u.id, now=now)
                from ..api.mfg.services.common import audit

                audit(s, "user", u.id, "disable" if inp.disabled else "enable", {"org_id": org_id})
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
        org = {"id": o.id, "name": o.name, "slug": o.slug}
    for x in out:
        if x["visible"]:
            x.update(plant_health(ctx, x["plant"]["owner_id"]))
    return {"org": org, "plants": out}


def plant_health(ctx: Any, owner: str) -> dict[str, Any]:
    """3.4 org overview of one plant: M4 KPIs (default period), late open demand lines, open replan triggers and
    integration health (pending / dead deliveries, failed batches and files of the last 7 days)."""
    from datetime import timedelta

    from ..api.mfg.db_models_m2 import MfgDemandLineRow, MfgDemandOrderRow
    from ..api.mfg.db_models_m4 import MfgNotificationRow, MfgReplanTriggerRow
    from ..api.mfg.db_models_m5 import IntDeliveryRow, IntInboxRow, IntSettingsRow
    from ..api.mfg.services import kpi
    from ..api.mfg.services.common import read_tx
    from ..api.mfg.services.m2util import today

    with owner_scope(owner):
        try:
            m = kpi.kpis(ctx, None, None, "plant", None, "day")["metrics"]
            kp = {k: (m.get(k) or {}).get("value") for k in ("otd", "oee", "adherence", "utilisation", "fpy")}
        except ApiError:
            kp = {}
        with read_tx(ctx) as s:
            d = today(s)
            late = int(s.execute(select(func.count()).select_from(MfgDemandLineRow).join(
                MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id).where(
                MfgDemandOrderRow.status == "open", MfgDemandLineRow.due_date < d,
                MfgDemandLineRow.qty - MfgDemandLineRow.shipped_qty > 1e-9)).scalar() or 0)
            trig = int(s.execute(select(func.count()).select_from(MfgReplanTriggerRow).where(
                MfgReplanTriggerRow.status == "open")).scalar() or 0)
            st = s.execute(select(IntSettingsRow)).scalars().first()
            dl = dict(s.execute(select(IntDeliveryRow.status, func.count()).group_by(IntDeliveryRow.status)).all())
            since = utcnow() - timedelta(days=7)
            failed = int(s.execute(select(func.count()).select_from(IntInboxRow).where(
                IntInboxRow.received_at >= since, IntInboxRow.status == "failed")).scalar() or 0)
            files = int(s.execute(select(func.count()).select_from(MfgNotificationRow).where(
                MfgNotificationRow.kind == "INTEGRATION_FILE_ERROR", MfgNotificationRow.created_at >= since))
                .scalar() or 0)
            last = s.execute(select(func.max(IntInboxRow.received_at))).scalar()
    integ = {"enabled": bool(st and st.enabled), "pending_deliveries": int(dl.get("pending", 0)),
             "dead_deliveries": int(dl.get("dead", 0)), "failed_batches_7d": failed, "failed_files_7d": files,
             "last_batch_at": as_utc(last)}
    integ["status"] = ("off" if not integ["enabled"] else "error" if integ["dead_deliveries"] or failed or files
                       else "ok")
    return {"kpis": kp, "late_demand": late, "open_triggers": trig, "integration": integ}


def publish_record(r: OrgPublishRow) -> dict[str, Any]:
    return {"id": r.id, "org_id": r.org_id, "source_owner_id": r.source_owner_id,
            "target_owner_ids": r.target_owner_ids, "scope": r.scope, "part_number_prefix": r.part_number_prefix,
            "status": r.status, "results": r.results, "created_at": as_utc(r.created_at),
            "finished_at": as_utc(r.finished_at)}


def publish(ctx: AppContext, user_id: str, org_id: str, inp: Any) -> dict[str, Any]:
    """3.4 master-data publish: a run (job kind `org_publish`) exporting the source bundle and importing it into
    every target plant (per-plant results; ERP-owned entities of a target follow 4.4)."""
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        _org(s, org_id, user_id, admin=True)
        src = _plant(s, org_id, inp.source_plant).plant_owner_id
        targets = []
        for x in inp.target_plants:
            t = _plant(s, org_id, x).plant_owner_id
            if t != src and t not in targets:
                targets.append(t)
        if not targets:
            raise ApiError(422, "VALIDATION_ERROR", "Choose at least one target plant other than the source.", {})
        r = OrgPublishRow(id=new_id("opb_"), org_id=org_id, source_owner_id=src, target_owner_ids=targets,
                          scope=inp.scope, part_number_prefix=inp.part_number_prefix, status="queued", results=None,
                          actor_id=user_id, created_at=now, finished_at=None)
        s.add(r)
        s.flush()
        job = ctx.jobs.enqueue(s, "org_publish", r.id, src)
        rec = publish_record(r)
    ctx.jobs.dispatch(job)
    return rec


def publish_bundle(ds: Any, scope: str, prefix: str | None) -> dict[str, list[dict[str, Any]]]:
    from ..mfg.bundle import M2_MASTER_SHEETS, dataset_to_bundle

    b = dataset_to_bundle(ds, "master")
    b.pop("plant", None)
    if scope == "items":
        b = {"items": b.get("items", [])}
    if prefix:
        keep = {r["part_number"] for r in b.get("items", []) if str(r["part_number"]).startswith(prefix)}
        for name, rows in list(b.items()):
            col = next((c for c in ("part_number", "parent_part_number") if rows and c in rows[0]), None)
            if col is not None:
                b[name] = [r for r in rows if r[col] in keep]
            elif name not in M2_MASTER_SHEETS and name != "items":
                pass
    return b


ERP_SHEETS = {"items": "items", "boms": "boms", "bom_lines": "boms", "routings": "routings",
              "operations": "routings", "suppliers": "suppliers", "item_suppliers": "item_suppliers"}
ITEM_ERP_COLUMNS = ("revision", "description", "uom", "make_buy", "active", "external_ref", "standard_cost")


def publish_into(ctx: Any, target: str, bundle: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Import `bundle` into the target plant (its own transaction, plant lock, audit); sheets of ERP-owned
    entities are skipped, ERP-owned item fields are not published."""
    from ..api.mfg import repo, repo_m2, writer
    from ..api.mfg.services import integration as isvc
    from ..api.mfg.services.common import audit, write_tx
    from ..mfg.io.plan import ImportOptions, plan_import

    with owner_scope(target):
        with write_tx(ctx) as (s, plant):
            if plant is None:
                plant = repo.plant_row_unlocked(s)
            b = {k: list(v) for k, v in bundle.items()}
            skipped = []
            for sheet, ent in ERP_SHEETS.items():
                if b.get(sheet) and isvc.sor_of(s, ent) == "erp":
                    if sheet == "items":
                        b["items"] = [{k: v for k, v in r.items() if k not in ITEM_ERP_COLUMNS} for r in b["items"]]
                        skipped.append("items:erp_fields")
                    else:
                        b[sheet] = []
                        skipped.append(sheet)
            plan = plan_import(b, repo_m2.load_import_dataset(s, with_txn=False), ImportOptions(release=True),
                               id_factory=new_id)
            if not plan.ok:
                return {"ok": False, "error_count": len(plan.row_errors), "row_errors": plan.row_errors[:50],
                        "skipped": skipped}
            if plan.has_writes():
                writer.apply(s, plan, plant)
            else:
                plant.data_version -= 1
            counts = {k: v for k, v in plan.result_counts().items() if any(v.values())}
            audit(s, "org_publish", None, "import", {"counts": counts})
            return {"ok": True, "counts": counts, "skipped": skipped}


def run_publish_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ..api.mfg import repo
    from ..jobs.types import LeaseLost

    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(OrgPublishRow, run_id, with_for_update=True)
        if r is None:
            raise LeaseLost(f"publish {run_id} is gone")
        lease.fence(s)
        r.status = "running"
        src, targets, scope, prefix = r.source_owner_id, list(r.target_owner_ids), r.scope, r.part_number_prefix
    results: dict[str, Any] = {}
    status, err = "completed", None
    try:
        with owner_scope(src), ctx.db.read() as s:
            bundle = publish_bundle(repo.load_dataset(s), scope, prefix)
        for t in targets:
            try:
                results[t] = publish_into(ctx, t, bundle)
            except ApiError as e:
                results[t] = {"ok": False, "error": {"code": e.code, "message": e.message}}
        if any(not x.get("ok") for x in results.values()):
            status = "failed" if all(not x.get("ok") for x in results.values()) else "completed"
    except Exception as exc:
        status, err = "failed", str(exc)[:500]
        results["error"] = err
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(OrgPublishRow, run_id, with_for_update=True)
        if r is None:
            raise LeaseLost(f"publish {run_id} is gone")
        r.status, r.results, r.finished_at = status, results, utcnow()
        lease.finish(s, "succeeded" if status == "completed" else "failed", err)


def get_publish(ctx: AppContext, user_id: str, org_id: str, publish_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        _org(s, org_id, user_id, admin=True)
        r = s.get(OrgPublishRow, publish_id) if len(publish_id) <= 64 else None
        if r is None or r.org_id != org_id:
            raise ApiError(404, "NOT_FOUND", "Publish run not found.", {"id": publish_id[:64]})
        return publish_record(r)


# ---------------------------------------------------------------- convert-plant (3.4, T-O2)

def convert_plant(db: Any, person_id: str, org_slug: str, code: str, name: str | None = None,
                  dry_run: bool = False) -> dict[str, Any]:
    """Move a personal plant (every owned row of `person_id` except the audit chain) to a new plant principal of
    organisation `org_slug`; members kept; the person becomes `plant_admin` (and an org member). One transaction.
    The old workspace id then has no data (other members get 404 there)."""
    import sqlalchemy as sa

    from ..api.db import load_all_models

    md = load_all_models()
    now = utcnow()
    with system_scope(), db.write() as s:
        org = s.execute(select(OrgRow).where(OrgRow.slug == org_slug)).scalars().first()
        if org is None:
            raise ApiError(404, "NOT_FOUND", f"No organisation {org_slug!r}.", {})
        person = s.get(UserRow, person_id)
        if person is None or person.kind != "person":
            raise ApiError(404, "NOT_FOUND", "No such person.", {})
        if s.execute(select(OrgPlantRow.id).where(OrgPlantRow.org_id == org.id, OrgPlantRow.code == code)).first():
            raise ApiError(409, "MFG_DUPLICATE_KEY", f"Plant {code!r} exists.", {})
        principal = UserRow(id=new_id("usr_"), email=None, display_name=f"Plant {code}"[:100], password_hash=None,
                            is_local=False, disabled=False, created_at=now, updated_at=now, kind="plant")
        s.add(principal)
        s.flush()
        counts: dict[str, int] = {}
        skip = {"audit_events", "jobs", "sessions", "api_tokens"}
        for t in md.sorted_tables:
            if "owner_id" not in t.c or t.name in skip or not (t.name.startswith(("mfg_", "int_"))):
                continue
            res = s.execute(sa.update(t).where(t.c.owner_id == person_id).values(owner_id=principal.id))
            counts[t.name] = int(res.rowcount or 0)
        plant_name = name
        if plant_name is None:
            from ..api.mfg.db_models import MfgPlantRow

            plant_name = s.execute(select(MfgPlantRow.name).where(MfgPlantRow.owner_id == principal.id)).scalar() \
                or code
        s.add(OrgPlantRow(id=new_id("orp_"), org_id=org.id, plant_owner_id=principal.id, code=code,
                          name=plant_name, created_at=now, row_version=1))
        s.add(MfgPlantMemberRow(id=new_id("mbr_"), owner_id=principal.id, user_id=person_id, roles=["plant_admin"],
                                active=True, invited_by=person_id, row_version=1, created_at=now, updated_at=now))
        if _role(s, org.id, person_id, accepted_only=False) is None:
            s.add(OrgMemberRow(id=new_id("orm_"), org_id=org.id, user_id=person_id, org_role="org_member",
                               accepted_at=now,
                               created_at=now, row_version=1))
        s.flush()
        if dry_run:
            s.rollback()
        return {"plant_owner_id": principal.id, "org_id": org.id, "code": code, "rows": counts,
                "dry_run": dry_run}
