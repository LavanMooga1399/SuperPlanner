"""Part 11 mode, record audit trails, inspection-readiness packages and exports (M7-DESIGN 0.5, 4.4, 4.5).

- Part 11 mode is switched on by a signed owner action (`plant.part11_on`, always signed) and never off through the
  API (409 `PART11_MODE_LOCKED`). It needs SECRETS_KEY(S) (signature MACs, keyed audit chain).
- `record_audit`: a record's audit events (oldest first) with field changes, reasons and signatures.
- `package`: `{record, signatures, audit, attachments, links, generated_at, generated_by, package_sha256}`.
- Exports (`part11_export` job on `maintenance_runs`): see `run_export_job`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....esig import content as C
from ....esig.model import Part11ModeInput
from ...context import AppContext
from ...db.models import AuditEventRow
from ...errors import ApiError
from ..db_models_m7 import EsigSignatureRow
from . import m7_examples
from .common import read_tx, write_tx

#: package record types -> (attachment/link entity type, audit entity types)
ENTITY = {"inspection_plan": "inspection_plan", "sampling_scheme": "sampling_scheme",
          "inspection_lot": "inspection_lot", "hold": "hold", "ncr": "ncr", "capa": "capa", "complaint": "complaint",
          "field_action": "field_action", "equipment": "equipment", "calibration": "calibration", "eco": "eco",
          "esig_policy": "esig_policy", "plant": "plant"}


def _plant_loader(s: Session, record_id: str, lock: bool) -> C.Loaded:
    from ..db_models import MfgPlantRow

    q = select(MfgPlantRow)
    if lock:
        q = q.with_for_update(key_share=True)
    p = s.execute(q).scalars().first()
    if p is None or (record_id not in ("plant", p.id)):
        raise ApiError(404, "NOT_FOUND", "Plant not found.", {"id": record_id})
    content = {"plant_id": p.id, "name": p.name, "part11_mode": bool(p.part11_mode), "action": "part11_on",
               "statement": "Switch this plant to Part 11 mode: signature policies are enforced, regulated changes "
                            "need a reason, signed or referenced regulated records cannot be deleted. It cannot be "
                            "switched off through the application."}
    return C.Loaded(p, content, p.row_version, None, [("Plant", p.name), ("Part 11 mode", "on")])


C.register("plant", _plant_loader)


def _mode(s: Session, ctx: AppContext) -> dict[str, Any]:
    from ..db_models import MfgPlantRow
    from . import esig

    p = s.execute(select(MfgPlantRow)).scalars().first()
    sig = None
    sigs: list[dict[str, Any]] = []
    if p is not None:
        sigs = esig.manifests(s, "plant", p.id, current_hash="-")
        for m in sigs:
            m["content_matches_current"] = True            # the switch is one-way; the snapshot is historical
        sig = next((x for x in s.execute(select(EsigSignatureRow).where(
            EsigSignatureRow.record_type == "plant", EsigSignatureRow.action == "part11_on",
            EsigSignatureRow.status == "valid").order_by(EsigSignatureRow.signed_at.desc())).scalars()), None)
    skew = None
    try:
        skew = round(esig.measure_skew(ctx)[0], 3)
    except Exception:                                      # pragma: no cover - diagnostics only
        skew = None
    on = bool(p is not None and p.part11_mode)
    return {"enabled": on, "enabled_at": sig.signed_at if (on and sig) else None,
            "enabled_by": sig.signer_id if (on and sig) else None, "signatures": sigs,
            "esig_enabled": bool(ctx.settings.esig_enabled), "secrets_configured": bool(ctx.settings.secrets_keys),
            "clock_skew_ms": skew, "max_clock_skew_ms": float(ctx.settings.esig_max_clock_skew_ms)}


def get_mode(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _mode(s, ctx)


def enable(ctx: AppContext, a: Any, body: Part11ModeInput) -> dict[str, Any]:
    from ...audit_diff import audit_regulated
    from . import esig

    if not ctx.settings.secrets_keys:
        raise ApiError(409, "PART11_SECRETS_REQUIRED", "Part 11 mode needs SECRETS_KEY (signature MACs and the keyed "
                       "audit chain). Ask your administrator to configure it.", {})
    if not ctx.settings.esig_enabled:
        raise ApiError(409, "ESIG_DISABLED", "Electronic signatures are switched off on this server.", {})
    with read_tx(ctx) as s:
        from ..db_models import MfgPlantRow

        cur = s.execute(select(MfgPlantRow.part11_mode)).scalar()
    if cur:
        raise ApiError(409, "PART11_MODE_LOCKED", "Part 11 mode is already on; it cannot be changed here.", {})
    auth = esig.authenticate(ctx, a, "plant", "part11_on", body.signature)
    with write_tx(ctx) as (s, plant):
        if plant.part11_mode:
            raise ApiError(409, "PART11_MODE_LOCKED", "Part 11 mode is already on.", {})
        out = esig.sign(s, a, auth, "plant", plant.id, "part11_on", body.signature)
        if out.pending is not None:
            return out.pending
        before = {"part11_mode": False}
        plant.part11_mode = True
        plant.row_version += 1
        s.info["sp_part11"] = True
        esig.seed_policies(s)
        s.flush()
        audit_regulated(s, "plant", plant.id, "part11_on", before=before, after={"part11_mode": True},
                        reason=(body.signature.comment.strip() if body.signature and body.signature.comment
                                else "Part 11 mode switched on"), record_version=plant.row_version,
                        signature_id=out.signature_ids[-1] if out.signature_ids else None)
        return _mode(s, ctx)


# ---------------------------------------------------------------- record audit trail (E6)

def _entity_types(entity_type: str) -> list[str]:
    base = entity_type[4:] if entity_type.startswith("mfg_") else entity_type
    return [base, f"mfg_{base}", f"esig_{base}"[:32]]


def _event(s: Session, e: AuditEventRow, sigs: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return {"id": int(e.id), "at": e.created_at, "actor_id": e.actor_id, "actor_name": names.get(e.actor_id or ""),
            "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id,
            "record_version": e.record_version, "reason": e.reason, "changes": e.changes or [],
            "signature": sigs.get(e.signature_id) if e.signature_id else None, "details": e.details or {}}


def _names(s: Session, ids: set[str]) -> dict[str, str]:
    from ...auth.models import UserRow
    from ...db.ownership import system_scope

    if not ids:
        return {}
    with system_scope():
        rows = s.execute(select(UserRow.id, UserRow.legal_name, UserRow.display_name, UserRow.email)
                         .where(UserRow.id.in_(sorted(ids)))).all()
    return {r[0]: r[1] or r[2] or r[3] or r[0] for r in rows}


def _events(s: Session, entity_type: str, entity_id: str, limit: int, offset: int) -> tuple[list[dict[str, Any]],
                                                                                            int]:
    from . import esig

    cond = [AuditEventRow.entity_type.in_(_entity_types(entity_type)), AuditEventRow.entity_id == entity_id,
            AuditEventRow.owner_id == _owner()]
    total = int(s.execute(select(func.count()).select_from(AuditEventRow).where(*cond)).scalar() or 0)
    rows = list(s.execute(select(AuditEventRow).where(*cond).order_by(AuditEventRow.id).limit(limit)
                          .offset(offset)).scalars())
    sig_ids = sorted({r.signature_id for r in rows if r.signature_id})
    sigs = {}
    if sig_ids:
        for r in s.execute(select(EsigSignatureRow).where(EsigSignatureRow.id.in_(sig_ids))).scalars():
            sigs[r.id] = esig.manifest(s, r, None)
    names = _names(s, {r.actor_id for r in rows if r.actor_id})
    return [_event(s, r, sigs, names) for r in rows], total


def _owner() -> Any:
    from ...db.ownership import current_owner

    return current_owner()


def record_audit(ctx: AppContext, entity_type: str, entity_id: str, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        items, total = _events(s, entity_type, entity_id, limit, offset)
        return {"entity_type": entity_type, "entity_id": entity_id, "items": items, "total": total, "limit": limit,
                "offset": offset}


# ---------------------------------------------------------------- package (E7)

def build_package(s: Session, record_type: str, record_id: str, generated_by: str) -> dict[str, Any]:
    from . import esig
    from .qa_common import attachments_of, links_of

    if record_type not in ENTITY:
        raise ApiError(404, "NOT_FOUND", f"Unknown record type {record_type!r}.", {})
    if record_type == "calibration":
        from .qa_equipment import calibration_content

        content, _v = calibration_content(s, record_id)
    else:
        content = esig.load(s, record_type, record_id).content
    ent = ENTITY[record_type]
    h = C.content_hash(content)
    sigs = esig.manifests(s, record_type, record_id, current_hash=h)
    events, _n = _events(s, ent, record_id, 100_000, 0)
    pkg = {"record_type": record_type, "record_id": record_id, "record": C.plain(content), "signatures": sigs,
           "audit": events, "attachments": [{"id": x["id"], "filename": x["filename"], "size": x["size"],
                                              "sha256": x["sha256"]} for x in attachments_of(s, ent, record_id)],
           "links": links_of(s, ent, record_id) if ent in ("ncr", "capa", "complaint", "field_action", "eco",
                                                           "inspection_lot", "equipment") else [],
           "generated_at": datetime.now(UTC), "generated_by": generated_by}
    pkg["package_sha256"] = C.content_hash(pkg)
    return pkg


def package(ctx: AppContext, a: Any, record_type: str, record_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return build_package(s, record_type, record_id, a.user_id)


def regulated_delete_blocked(s: Session, record_type: str, record_id: str) -> bool:
    """4.4: in Part 11 mode a signed or referenced record is not deleted (409 `PART11_DELETE_NOT_ALLOWED`)."""
    from ...audit_diff import part11_on
    from ..db_models_m7 import QaLinkRow

    if not part11_on(s):
        return False
    signed = s.execute(select(EsigSignatureRow.id).where(EsigSignatureRow.record_type == record_type,
                                                         EsigSignatureRow.record_id == record_id).limit(1)).first()
    linked = s.execute(select(QaLinkRow.id).where(or_(QaLinkRow.from_id == record_id, QaLinkRow.to_id == record_id))
                       .limit(1)).first()
    return signed is not None or linked is not None


def delete_not_allowed() -> ApiError:
    return ApiError(409, "PART11_DELETE_NOT_ALLOWED", "This regulated record is signed or referenced; obsolete or "
                    "cancel it instead.", {})


__getattr__ = m7_examples.module_getattr(__name__)
