"""Data residency (M10-DESIGN 9.1) and the organisation audit view (9.3).

The deployment declares `SP_REGION` (e.g. `ca`) and the regions of its archive / backup / SMTP / log / AI endpoints
(`SP_REGION_ENDPOINTS`). Every organisation has an immutable `data_region` (set at creation from `SP_REGION`; an
organisation created before M10 adopts the deployment region on its first residency check). Rules:

- a request into a plant of an organisation whose `data_region != SP_REGION` -> 409 `RESIDENCY_REGION` (the
  deployment serves its own region only; `check_workspace`, called by the mfg principal);
- Part 11 exports, renditions written to files, batch packs and validation packages are refused while the declared
  `archive` region differs from the organisation's (409 `RESIDENCY_ARCHIVE`, `check_archive`);
- outbound integration endpoints need `region` = the organisation's region or a signed `int_endpoint.cross_region`
  exception (`endpoint_allowed`);
- the assistant of a plant in Part 11 mode or with an `ai` region other than the organisation's is off until a signed
  `plant.assistant_on`.

Without `SP_REGION` (development) nothing is enforced and the report says so.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select

from ..api.db.ownership import system_scope
from ..api.errors import ApiError

_PLANT_REGION: dict[str, tuple[str | None, str | None]] = {}     # plant owner -> (org id, region); immutable


def _org_of_plant(s: Any, owner_id: str) -> tuple[str | None, str | None]:
    from ..api.mfg.db_models_m5 import OrgPlantRow, OrgRow

    hit = _PLANT_REGION.get(owner_id)
    if hit is not None:
        return hit
    row = s.execute(select(OrgRow.id, OrgRow.data_region).join(OrgPlantRow, OrgPlantRow.org_id == OrgRow.id)
                    .where(OrgPlantRow.plant_owner_id == owner_id)).first()
    out = (row[0], row[1]) if row is not None else (None, None)
    if out[1] is not None or row is None:
        _PLANT_REGION[owner_id] = out
    return out


def region_error(org_region: str, deployment: str) -> ApiError:
    return ApiError(409, "RESIDENCY_REGION", "This organisation's data belongs to another region; this deployment "
                    "serves its own region only.", {"data_region": org_region, "deployment_region": deployment})


def check_workspace(ctx: Any, owner_id: str) -> None:
    """409 `RESIDENCY_REGION` for a plant of an organisation of another region (no-op without SP_REGION)."""
    dep = getattr(ctx.settings, "sp_region", None)
    if not dep:
        return
    with system_scope(), ctx.db.read() as s:
        _org, region = _org_of_plant(s, owner_id)
    if region is not None and region != dep:
        raise region_error(region, dep)


def org_region(ctx: Any, s: Any) -> str | None:
    """The data region of the bound plant's organisation (None outside an organisation)."""
    from ..api.db.ownership import current_owner

    owner = current_owner()
    if not isinstance(owner, str):
        return getattr(ctx.settings, "sp_region", None) if ctx is not None else None
    with system_scope():
        _org, region = _org_of_plant(s, owner)
    return region or (getattr(ctx.settings, "sp_region", None) if ctx is not None else None)


def check_archive(settings: Any, region: str | None) -> None:
    """409 `RESIDENCY_ARCHIVE`: files of regulated records go to the archive only inside the data region."""
    dep = getattr(settings, "sp_region", None)
    if not dep:
        return
    want = region or dep
    arch = (getattr(settings, "sp_region_endpoints", None) or {}).get("archive", dep)
    if arch != want:
        raise ApiError(409, "RESIDENCY_ARCHIVE", "The archive is declared in another region than the "
                       "organisation's data; regulated files are not written there.",
                       {"archive_region": arch, "data_region": want})


def endpoint_allowed(settings: Any, org_reg: str | None, endpoint_region: str | None,
                     exception_signature_id: str | None) -> bool:
    dep = getattr(settings, "sp_region", None)
    if not dep:
        return True
    want = org_reg or dep
    return (endpoint_region or dep) == want or exception_signature_id is not None


def assistant_blocked(settings: Any, part11: bool, org_reg: str | None) -> bool:
    """Is the assistant off by default here (switched on only by a signed `plant.assistant_on`)?"""
    dep = getattr(settings, "sp_region", None)
    ai = (getattr(settings, "sp_region_endpoints", None) or {}).get("ai", "us")
    return part11 or (bool(dep) and ai != (org_reg or dep))


# ---------------------------------------------------------------- O1 report

def _org_admin(s: Any, org_id: str, user_id: str, roles: tuple[str, ...] = ("org_admin",)) -> Any:
    from ..api.mfg.db_models_m5 import OrgMemberRow, OrgRow

    org = s.get(OrgRow, org_id) if len(org_id) <= 64 else None
    role = s.execute(select(OrgMemberRow.org_role).where(
        OrgMemberRow.org_id == org_id, OrgMemberRow.user_id == user_id,
        OrgMemberRow.accepted_at.is_not(None))).scalar() if org is not None else None
    if org is None or role is None:
        raise ApiError(404, "NOT_FOUND", "Organisation not found.", {"id": org_id[:64]})
    if role not in roles:
        raise ApiError(403, "MFG_FORBIDDEN", "Only organisation admins can do this.",
                       {"permission": " | ".join(roles)})
    return org


def report(ctx: Any, user_id: str, org_id: str) -> dict[str, Any]:
    from ..api.mfg.db_models import MfgPlantRow
    from ..api.mfg.db_models_m5 import IntEndpointRow, OrgPlantRow

    st = ctx.settings
    dep = st.sp_region
    eps = st.sp_region_endpoints or {}
    with system_scope(), ctx.db.write() as s:
        org = _org_admin(s, org_id, user_id)
        if org.data_region is None and dep:            # pre-M10 organisation: adopts the deployment region once
            org.data_region = dep
        region = org.data_region or dep or "-"
        items: list[dict[str, Any]] = [
            {"kind": "deployment", "name": "SP_REGION", "region": dep, "ok": bool(dep),
             "detail": "" if dep else "SP_REGION is not set: residency is not enforced (development).",
             "exception_signature_id": None},
            {"kind": "org", "name": org.name, "region": region, "ok": not dep or region == dep, "detail": "",
             "exception_signature_id": None}]
        for k, label in (("archive", "ARCHIVE_DIR"), ("backup", "Backups"), ("smtp", "SMTP relay"),
                         ("logs", "Log shipping"), ("ai", "Assistant model endpoint")):
            r = eps.get(k)
            if r is None and k == "ai":
                r = "us"                                  # the public model API (9.1)
            ok = r is None or not dep or r == region
            detail = "" if r is not None else "Not declared (SP_REGION_ENDPOINTS)."
            if k == "ai" and not ok:
                detail = "The assistant stays off in this organisation's plants unless signed on."
            items.append({"kind": k, "name": label, "region": r, "ok": ok if k != "ai" else True if not dep else ok,
                          "detail": detail, "exception_signature_id": None})
        plants = list(s.execute(select(OrgPlantRow).where(OrgPlantRow.org_id == org.id)).scalars())
        for p in plants:
            for ep in s.execute(select(IntEndpointRow).where(IntEndpointRow.owner_id == p.plant_owner_id,
                                                             IntEndpointRow.active.is_(True))).scalars():
                ok = endpoint_allowed(st, region, ep.region, ep.cross_region_signature_id)
                items.append({"kind": "endpoint", "name": f"{p.code}: {ep.name}", "region": ep.region or dep,
                              "ok": ok, "detail": "" if ok else "Delivery refused until a signed cross-region "
                              "exception exists.", "exception_signature_id": ep.cross_region_signature_id})
            pl = s.execute(select(MfgPlantRow.part11_mode, MfgPlantRow.assistant_enabled).where(
                MfgPlantRow.owner_id == p.plant_owner_id)).first()
            if pl is not None and pl[1] and assistant_blocked(st, bool(pl[0]), region):
                items.append({"kind": "assistant", "name": f"{p.code}: assistant", "region": eps.get("ai", "us"),
                              "ok": False, "detail": "The assistant is on although it is off by default here; "
                              "check the signed plant.assistant_on.", "exception_signature_id": None})
        mism = [i for i in items if not i["ok"]]
        return {"org_id": org.id, "data_region": region, "deployment_region": dep or "-", "ok": not mism,
                "mismatches": mism, "items": items}


def readiness(settings: Any) -> dict[str, Any]:
    """`/health/ready` addition: residency {ok, mismatches[]} of the deployment's declared endpoints."""
    dep = getattr(settings, "sp_region", None)
    if not dep:
        return {"ok": True, "enforced": False, "mismatches": []}
    eps = getattr(settings, "sp_region_endpoints", None) or {}
    mism = [k for k in ("archive", "backup", "smtp", "logs") if eps.get(k) not in (None, dep)]
    return {"ok": not mism, "enforced": True, "region": dep, "mismatches": mism}


# ---------------------------------------------------------------- O2 org audit

def org_audit(ctx: Any, user_id: str, org_id: str, from_: date | None, to: date | None, plant: str | None,
              entity_type: str | None, actor: str | None, page: int, limit: int) -> dict[str, Any]:
    """Merged, read-only view of the plant audit chains of the organisation (org_admin, org_auditor)."""
    from ..api.db.models import AuditEventRow
    from ..api.mfg.db_models_m5 import OrgPlantRow

    with system_scope(), ctx.db.read() as s:
        org = _org_admin(s, org_id, user_id, ("org_admin", "org_auditor"))
        plants = {p.plant_owner_id: p.code for p in s.execute(select(OrgPlantRow).where(
            OrgPlantRow.org_id == org.id)).scalars()}
        owners = [o for o, c in plants.items() if plant is None or c == plant]
        conds: list[Any] = [AuditEventRow.owner_id.in_(owners or ["-"])]
        if from_:
            conds.append(AuditEventRow.created_at >= datetime.combine(from_, time.min, UTC))
        if to:
            conds.append(AuditEventRow.created_at < datetime.combine(to + timedelta(days=1), time.min, UTC))
        if entity_type:
            conds.append(AuditEventRow.entity_type == entity_type)
        if actor:
            conds.append(AuditEventRow.actor_id == actor)
        total = int(s.execute(select(func.count()).select_from(AuditEventRow).where(*conds)).scalar() or 0)
        rows = s.execute(select(AuditEventRow).where(*conds).order_by(AuditEventRow.created_at.desc(),
                                                                      AuditEventRow.id.desc())
                         .limit(limit).offset((page - 1) * limit)).scalars()
        items = [{"id": r.id, "plant": plants.get(r.owner_id or ""), "owner_id": r.owner_id,
                  "entity_type": r.entity_type, "entity_id": r.entity_id, "action": r.action, "actor_id": r.actor_id,
                  "created_at": r.created_at, "reason": r.reason, "signature_id": r.signature_id,
                  "details": r.details or {}} for r in rows]
        return {"items": items, "total": total, "page": page, "limit": limit}


__all__ = ["assistant_blocked", "check_archive", "check_workspace", "endpoint_allowed", "org_audit", "org_region",
           "readiness", "region_error", "report"]
