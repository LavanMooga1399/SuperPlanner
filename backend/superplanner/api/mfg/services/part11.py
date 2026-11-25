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
            "enabled_by": sig.signer_id if (on and sig) else None,
            "enabled_by_name": sig.signer_legal_name if (on and sig) else None, "signatures": sigs,
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
                                else None), record_version=plant.row_version, create=True,
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


# ---------------------------------------------------------------- exports (E8-E10, job `part11_export`)

EXPORT_MODELS = {"inspection_plan": "QaInspectionPlanRow", "sampling_scheme": "QaSamplingSchemeRow",
                 "inspection_lot": "QaInspectionLotRow", "hold": "MfgLotHoldRow", "ncr": "QaNcrRow",
                 "capa": "QaCapaRow", "complaint": "QaComplaintRow", "field_action": "QaFieldActionRow",
                 "equipment": "QaEquipmentRow", "calibration": "QaCalibrationRow"}


def _export_record(r: Any) -> dict[str, Any]:
    from datetime import UTC

    return {"id": r.id, "params": r.params, "status": r.status, "manifest": r.manifest, "sha256": r.sha256,
            "error": r.error, "requested_by": r.requested_by, "created_at": r.created_at,
            "finished_at": r.finished_at.astimezone(UTC) if r.finished_at else None,
            "download_url": f"/api/v1/mfg/part11/exports/{r.id}/download" if r.status == "completed" else None}


def create_export(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    from ...db.models import new_id, utcnow
    from ..db_models_m7 import Part11ExportRow
    from ....integration.jobs import new_run

    if not ctx.settings.archive_dir:
        raise ApiError(422, "PART11_NO_ARCHIVE_DIR", "Exports need ARCHIVE_DIR on the server.", {})
    params = {"from": body.from_.isoformat(), "to": body.to.isoformat(),
              "record_types": list(body.record_types) or sorted(EXPORT_MODELS)}
    with write_tx(ctx, lock=False) as (s, _):
        now = utcnow()
        r = Part11ExportRow(id=new_id("p1x_"), params=params, status="queued", file_path=None, manifest=None,
                            sha256=None, error=None, requested_by=a.user_id, finished_at=None, row_version=1,
                            created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        _rid, job = new_run(s, ctx, "part11_export", r.owner_id, {"export_id": r.id})
        from .common import audit

        audit(s, "part11_export", r.id, "create", params)
        rec = _export_record(r)
    ctx.jobs.dispatch(job)
    return rec


def list_exports(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    from ..db_models_m7 import Part11ExportRow

    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(Part11ExportRow)).scalar() or 0)
        rows = s.execute(select(Part11ExportRow).order_by(Part11ExportRow.created_at.desc(), Part11ExportRow.id)
                         .limit(limit).offset(offset)).scalars()
        return {"items": [_export_record(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def download_export(ctx: AppContext, export_id: str) -> tuple[bytes, str]:
    from pathlib import Path

    from .. import repo
    from ..db_models_m7 import Part11ExportRow

    with read_tx(ctx) as s:
        r = repo.get_row(s, Part11ExportRow, export_id, what="Export")
        if r.status != "completed" or not r.file_path:
            raise ApiError(409, "MFG_INVALID_STATE", "The export is not ready.", {"status": r.status})
        path = r.file_path
    return Path(path).read_bytes(), f"part11-{export_id}.zip"


def write_export(s: Session, owner: str, export_id: str, params: dict[str, Any], archive_dir: str,
                 generated_by: str) -> dict[str, Any]:
    """Stream the archive (constant memory: rows by `yield_per`, members written incrementally): `records.jsonl`,
    `signatures.jsonl`, `audit.jsonl`, `attachments/<id>-<name>`, `manifest.json` (counts and sha256 per file)."""
    import hashlib
    import json
    import zipfile
    from datetime import UTC, date, datetime, time, timedelta
    from pathlib import Path

    from .. import db_models_m7 as m7
    from . import esig
    from .common import jsonable

    d0 = datetime.combine(date.fromisoformat(params["from"]), time(0), UTC)
    d1 = datetime.combine(date.fromisoformat(params["to"]) + timedelta(days=1), time(0), UTC)
    out_dir = Path(archive_dir) / owner / "part11"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{export_id}.zip"
    counts: dict[str, int] = {}
    shas: dict[str, str] = {}
    ids: dict[str, set[str]] = {}

    def member(zf: Any, name: str, rows: Any) -> None:
        h = hashlib.sha256()
        n = 0
        with zf.open(name, "w") as f:
            for row in rows:
                line = (json.dumps(jsonable(row), ensure_ascii=False, sort_keys=True) + "\n").encode()
                h.update(line)
                f.write(line)
                n += 1
        counts[name], shas[name] = n, h.hexdigest()

    def records() -> Any:
        for rt in params["record_types"]:
            model = getattr(m7, EXPORT_MODELS[rt])
            q = select(model.id).where(model.updated_at >= d0, model.updated_at < d1).order_by(model.id)
            for (rid,) in s.execute(q).yield_per(500):
                ids.setdefault(rt, set()).add(rid)
                if rt == "calibration":
                    from .qa_equipment import calibration_content

                    content = calibration_content(s, rid)[0]
                else:
                    content = esig.load(s, rt, rid).content
                yield {"record_type": rt, "record_id": rid, "record": C.plain(content)}
                s.expunge_all()

    def signatures() -> Any:
        q = select(EsigSignatureRow).where(EsigSignatureRow.signed_at >= d0, EsigSignatureRow.signed_at < d1) \
            .order_by(EsigSignatureRow.signed_at, EsigSignatureRow.id)
        for r in s.execute(q).scalars().yield_per(500):
            yield {**esig.manifest(s, r, None), "record_type": r.record_type, "record_id": r.record_id,
                   "content_hash": r.content_hash, "mac": r.mac, "content": r.content}

    def audit() -> Any:
        q = select(AuditEventRow).where(AuditEventRow.owner_id == owner, AuditEventRow.created_at >= d0,
                                        AuditEventRow.created_at < d1).order_by(AuditEventRow.id)
        for e in s.execute(q).scalars().yield_per(1000):
            yield {"id": int(e.id), "at": e.created_at, "actor_id": e.actor_id, "entity_type": e.entity_type,
                   "entity_id": e.entity_id, "action": e.action, "reason": e.reason, "changes": e.changes,
                   "signature_id": e.signature_id, "record_version": e.record_version, "details": e.details,
                   "chain_hash": e.chain_hash}

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        member(zf, "records.jsonl", records())
        member(zf, "signatures.jsonl", signatures())
        member(zf, "audit.jsonl", audit())
        n_att = 0
        all_ids = sorted({i for v in ids.values() for i in v})
        for k in range(0, len(all_ids), 500):
            chunk = all_ids[k:k + 500]
            for a in s.execute(select(m7.QaAttachmentRow).where(m7.QaAttachmentRow.entity_id.in_(chunk))
                               .order_by(m7.QaAttachmentRow.id)).scalars():
                name = f"attachments/{a.id}-{a.filename}"
                zf.writestr(name, bytes(a.data))
                counts[name], shas[name] = 1, a.sha256
                n_att += 1
                s.expunge(a)
        manifest = {"export_id": export_id, "owner_id": owner, "params": params,
                    "generated_at": datetime.now(UTC).isoformat(), "generated_by": generated_by,
                    "counts": {"records": counts.get("records.jsonl", 0),
                               "signatures": counts.get("signatures.jsonl", 0),
                               "audit_events": counts.get("audit.jsonl", 0), "attachments": n_att},
                    "files": [{"name": k, "rows": counts[k], "sha256": v} for k, v in sorted(shas.items())]}
        zf.writestr("manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"file_path": str(path), "manifest": manifest, "sha256": h.hexdigest()}


def run_export_job(ctx: AppContext, run_id: str, lease: Any) -> None:
    from ....integration.jobs import run_duty
    from ...db.models import utcnow
    from ..db_models_m7 import Part11ExportRow

    def fn(info: dict[str, Any]) -> dict[str, Any]:
        eid = info["params"]["export_id"]
        with ctx.db.write() as s:
            r = s.get(Part11ExportRow, eid)
            r.status = "running"
            params, who = dict(r.params), r.requested_by
        try:
            with ctx.db.read() as s:
                res = write_export(s, info["owner"], eid, params, ctx.settings.archive_dir, who)
        except Exception as exc:
            with ctx.db.write() as s:
                r = s.get(Part11ExportRow, eid)
                r.status, r.error, r.finished_at = "failed", f"{exc.__class__.__name__}: {exc}"[:500], utcnow()
            raise
        with ctx.db.write() as s:
            r = s.get(Part11ExportRow, eid)
            r.status, r.file_path, r.manifest, r.sha256 = "completed", res["file_path"], res["manifest"], res["sha256"]
            r.finished_at = utcnow()
        return {"export_id": eid, "counts": res["manifest"]["counts"]}

    run_duty(ctx, run_id, lease, fn)


__getattr__ = m7_examples.module_getattr(__name__)
