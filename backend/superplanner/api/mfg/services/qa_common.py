"""Shared M7 service helpers (M7-DESIGN 9): the request's acting context (`Act`), QA settings, record decorations
(signatures, links, attachments), attachments and links."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....qa.model import LinkInput, QaSettings
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from ..access import MfgPrincipal, mfg_principal
from ..db_models_m7 import QaAttachmentRow, QaLinkRow
from . import m7_examples
from .common import audit, check_version, read_tx, touch, unknown_ref, write_tx


@dataclass(frozen=True)
class Act:
    """Who acts, from where (signatures record the session reference and client address, 4.2)."""
    p: MfgPrincipal
    session_id: str | None
    client_ip: str | None

    @property
    def user_id(self) -> str:
        return self.p.user_id

    @property
    def session_ref(self) -> str | None:
        return hashlib.sha256(self.session_id.encode()).hexdigest() if self.session_id else None


async def act(request: Request, p: MfgPrincipal = Depends(mfg_principal)) -> Act:
    principal = getattr(request.state, "principal", None)
    return Act(p, getattr(principal, "session_id", None), request.client.host if request.client else None)


# ---------------------------------------------------------------- QA settings (3)

def settings_of(s: Session) -> QaSettings:
    from ..db_models import MfgPlantRow

    cache = s.info.get("sp_qa_settings")
    if cache is None:
        raw = s.execute(select(MfgPlantRow.qa_settings)).scalar()
        cache = QaSettings.model_validate(raw) if raw else QaSettings()
        s.info["sp_qa_settings"] = cache
    return cache


def _settings_record(row: Any) -> dict[str, Any]:
    st = QaSettings.model_validate(row.qa_settings) if row is not None and row.qa_settings else QaSettings()
    return {**st.model_dump(mode="json"), "row_version": row.row_version if row is not None else 0}


def get_settings(ctx: AppContext) -> dict[str, Any]:
    from ..db_models import MfgPlantRow

    with read_tx(ctx) as s:
        return _settings_record(s.execute(select(MfgPlantRow)).scalars().first())


def put_settings(ctx: AppContext, a: Act, body: QaSettings, if_match: str | None) -> dict[str, Any]:
    from ...audit_diff import audit_regulated

    with write_tx(ctx) as (s, plant):
        check_version(plant, if_match)
        if body.mrb_location_id is not None:
            from ..db_models_m2 import MfgLocationRow

            if s.get(MfgLocationRow, body.mrb_location_id) is None:
                raise unknown_ref(["body", "mrb_location_id"], body.mrb_location_id, "Location")
        before = _settings_record(plant)
        plant.qa_settings = body.model_dump(mode="json")
        touch(plant)
        s.info.pop("sp_qa_settings", None)
        s.flush()
        after = _settings_record(plant)
        audit_regulated(s, "qa_settings", plant.id, "update", before=before, after=after,
                        record_version=plant.row_version)
        return after


# ---------------------------------------------------------------- numbering, records

SERIES = {"IP": "IP-", "IL": "IL-", "NCR": "NCR-", "CAPA": "CAPA-", "CMP": "CMP-", "FA": "FA-"}


def next_number(s: Session, kind: str, model: Any) -> str:
    from .. import repo_m2

    return repo_m2.next_number(s, kind, repo_m2.number_taken(s, model))


def stamp(row: Any) -> dict[str, Any]:
    return {"id": row.id, "row_version": row.row_version, "created_at": row.created_at,
            "updated_at": row.updated_at}


def item_ref(s: Session, item_id: str | None) -> dict[str, Any] | None:
    if not item_id:
        return None
    from ..db_models import MfgItemRow

    it = s.get(MfgItemRow, item_id)
    if it is None:
        return {"id": item_id, "part_number": None, "revision": None, "name": None}
    return {"id": it.id, "part_number": it.part_number, "revision": it.revision, "name": it.name}


def decorate(s: Session, record: dict[str, Any], entity_type: str, record_type: str | None = None,
             content: dict[str, Any] | None = None) -> dict[str, Any]:
    """signatures (with the current-content check), links and attachments of one record."""
    rid = record["id"]
    if record_type is not None:
        from . import esig

        record["signatures"] = esig.manifests(s, record_type, rid, current_hash=None if content is None else
                                              esig.C.content_hash(content))
    record["links"] = links_of(s, entity_type, rid)
    record["attachments"] = attachments_of(s, entity_type, rid)
    return record


# ---------------------------------------------------------------- links (Q63-Q64)

LINK_MODELS: dict[str, tuple[str, str]] = {
    "ncr": ("db_models_m7", "QaNcrRow"), "capa": ("db_models_m7", "QaCapaRow"),
    "complaint": ("db_models_m7", "QaComplaintRow"), "field_action": ("db_models_m7", "QaFieldActionRow"),
    "eco": ("db_models_m5", "MfgChangeRequestRow"), "inspection_lot": ("db_models_m7", "QaInspectionLotRow"),
    "equipment": ("db_models_m7", "QaEquipmentRow")}
EDIT_PERM = {"ncr": "ncr_edit", "capa": "capa_edit", "complaint": "complaint_edit",
             "field_action": "field_action_edit", "eco": "eco_edit", "inspection_lot": "qa_inspect",
             "equipment": "equipment_edit"}


def _model(kind: str) -> Any:
    import importlib

    mod, cls = LINK_MODELS[kind]
    return getattr(importlib.import_module(f"..{mod}", __package__), cls)


def _label(s: Session, kind: str, rid: str) -> str | None:
    r = s.get(_model(kind), rid)
    if r is None:
        return None
    return getattr(r, "number", None) or getattr(r, "code", None)


def link_record(s: Session, r: QaLinkRow, side: str = "to") -> dict[str, Any]:
    other_t, other_id = (r.to_type, r.to_id) if side == "to" else (r.from_type, r.from_id)
    return {"id": r.id, "from_type": r.from_type, "from_id": r.from_id, "to_type": r.to_type, "to_id": r.to_id,
            "label": _label(s, other_t, other_id), "created_by": r.created_by, "created_at": r.created_at}


def links_of(s: Session, kind: str, rid: str) -> list[dict[str, Any]]:
    out = [link_record(s, r, "to") for r in s.execute(select(QaLinkRow).where(
        QaLinkRow.from_type == kind, QaLinkRow.from_id == rid).order_by(QaLinkRow.created_at)).scalars()]
    out += [link_record(s, r, "from") for r in s.execute(select(QaLinkRow).where(
        QaLinkRow.to_type == kind, QaLinkRow.to_id == rid).order_by(QaLinkRow.created_at)).scalars()]
    return out


def add_link(s: Session, from_type: str, from_id: str, to_type: str, to_id: str, actor: str) -> QaLinkRow:
    found = s.execute(select(QaLinkRow).where(QaLinkRow.from_type == from_type, QaLinkRow.from_id == from_id,
                                              QaLinkRow.to_type == to_type, QaLinkRow.to_id == to_id)
                      ).scalars().first()
    if found is not None:
        return found
    r = QaLinkRow(id=new_id("qlk_"), from_type=from_type, from_id=from_id, to_type=to_type, to_id=to_id,
                  created_by=actor, created_at=utcnow())
    s.add(r)
    s.flush()
    return r


def create_link(ctx: AppContext, a: Act, body: LinkInput) -> dict[str, Any]:
    perm = EDIT_PERM[body.from_type]
    if not a.p.has(perm):
        raise ApiError(403, "MFG_FORBIDDEN", "Your role does not allow linking from this record.",
                       {"permission": perm})
    if body.from_type == body.to_type and body.from_id == body.to_id:
        raise ApiError(422, "VALIDATION_ERROR", "A record cannot be linked to itself.", {"errors": []})
    with write_tx(ctx) as (s, _plant):
        for t, i in ((body.from_type, body.from_id), (body.to_type, body.to_id)):
            if s.get(_model(t), i) is None:
                raise unknown_ref(["body", f"{'from' if t == body.from_type else 'to'}_id"], i)
        r = add_link(s, body.from_type, body.from_id, body.to_type, body.to_id, a.user_id)
        audit(s, "link", r.id, "create", {"from": f"{r.from_type}:{r.from_id}", "to": f"{r.to_type}:{r.to_id}"})
        return link_record(s, r)


def delete_link(ctx: AppContext, a: Act, link_id: str) -> None:
    from .. import repo

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaLinkRow, link_id, what="Link")
        perm = EDIT_PERM[r.from_type]
        if not a.p.has(perm):
            raise ApiError(403, "MFG_FORBIDDEN", "Your role does not allow unlinking this record.",
                           {"permission": perm})
        from ...audit_diff import audit_regulated

        audit_regulated(s, "link", r.id, "delete", before={"from": f"{r.from_type}:{r.from_id}",
                                                           "to": f"{r.to_type}:{r.to_id}"}, after={})
        s.delete(r)


# ---------------------------------------------------------------- attachments (Q60-Q62)

MAX_ATTACHMENT = 10 * 1024 * 1024
MAX_PER_RECORD = 50
ATT_MODELS = {"inspection_plan": "QaInspectionPlanRow", "inspection_lot": "QaInspectionLotRow", "ncr": "QaNcrRow",
              "capa": "QaCapaRow", "complaint": "QaComplaintRow", "field_action": "QaFieldActionRow",
              "equipment": "QaEquipmentRow", "calibration": "QaCalibrationRow"}
#: parent states in which attachments may still change (9: immutable once the parent leaves draft/open)
OPEN_STATES = {"inspection_plan": {"draft"}, "inspection_lot": {"open", "in_progress", "ready"},
               "ncr": {"draft", "open", "proposed"}, "capa": {"draft", "investigation", "plan_approval",
                                                              "implementation", "effectiveness_check"},
               "complaint": {"open", "investigation"}, "field_action": {"draft", "approved", "in_progress"},
               "equipment": {"active", "out_of_service"}, "calibration": None}


def sniff(data: bytes, filename: str) -> str | None:
    """Content type by magic bytes (pdf, png, jpeg, xlsx) or text checks (csv, txt); None = refused."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"PK\x03\x04") and filename.lower().endswith(".xlsx") and b"xl/" in data[:4096]:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\x00" in txt:
        return None
    return "text/csv" if filename.lower().endswith(".csv") else "text/plain"


def attachment_record(r: QaAttachmentRow) -> dict[str, Any]:
    return {"id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id, "filename": r.filename,
            "content_type": r.content_type, "size": r.size, "sha256": r.sha256, "uploaded_by": r.uploaded_by,
            "uploaded_at": r.uploaded_at}


def attachments_of(s: Session, kind: str, rid: str) -> list[dict[str, Any]]:
    cols = [c for c in QaAttachmentRow.__table__.columns if c.name != "data"]
    rows = s.execute(select(*cols).where(QaAttachmentRow.entity_type == kind, QaAttachmentRow.entity_id == rid)
                     .order_by(QaAttachmentRow.uploaded_at)).all()
    return [attachment_record(r) for r in rows]  # type: ignore[arg-type]


def _parent(s: Session, kind: str, rid: str, lock: bool = False) -> Any:
    from .. import db_models_m7 as m7, repo

    if kind not in ATT_MODELS:
        raise ApiError(422, "VALIDATION_ERROR", f"Attachments are not supported on {kind!r}.", {"errors": [
            {"loc": ["query", "entity_type"], "msg": "unsupported", "type": "value_error"}]})
    return repo.get_row(s, getattr(m7, ATT_MODELS[kind]), rid, what="Record", lock=lock)


def _check_open(kind: str, parent: Any) -> None:
    states = OPEN_STATES.get(kind)
    st = getattr(parent, "status", None)
    if states is None or (st is not None and st not in states):
        raise ApiError(409, "QA_ATTACHMENT_LOCKED", "Attachments of this record cannot change any more.",
                       {"status": st})


def add_attachment(ctx: AppContext, a: Act, entity_type: str, entity_id: str, filename: str, content_type: str,
                   data: bytes) -> dict[str, Any]:
    if len(data) > MAX_ATTACHMENT:
        raise ApiError(413, "QA_ATTACHMENT_TOO_LARGE", "Attachments are limited to 10 MB.",
                       {"max_bytes": MAX_ATTACHMENT})
    if not data:
        raise ApiError(422, "VALIDATION_ERROR", "The file is empty.", {"errors": []})
    name = filename.replace("/", "_").replace("\\", "_").replace('"', "_").strip()[:200] or "file"
    sniffed = sniff(data, name)
    if sniffed is None:
        raise ApiError(415, "QA_ATTACHMENT_TYPE", "Allowed files: PDF, PNG, JPEG, CSV, XLSX, text.",
                       {"content_type": content_type[:64]})
    with write_tx(ctx) as (s, _plant):
        parent = _parent(s, entity_type, entity_id, lock=True)
        _check_open(entity_type, parent)
        n = int(s.execute(select(func.count()).select_from(QaAttachmentRow).where(
            QaAttachmentRow.entity_type == entity_type, QaAttachmentRow.entity_id == entity_id)).scalar() or 0)
        if n >= MAX_PER_RECORD:
            raise ApiError(422, "MFG_LIMIT", f"At most {MAX_PER_RECORD} attachments per record.",
                           {"limit": MAX_PER_RECORD})
        r = QaAttachmentRow(id=new_id("att_"), entity_type=entity_type, entity_id=entity_id, filename=name,
                            content_type=sniffed, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            data=data, uploaded_by=a.user_id, uploaded_at=utcnow())
        s.add(r)
        s.flush()
        audit(s, "attachment", r.id, "create", {"entity": f"{entity_type}:{entity_id}", "filename": name,
                                                "sha256": r.sha256, "size": r.size})
        return attachment_record(r)


def get_attachment(ctx: AppContext, attachment_id: str) -> tuple[bytes, str, str]:
    from .. import repo

    with read_tx(ctx) as s:
        r = repo.get_row(s, QaAttachmentRow, attachment_id, what="Attachment")
        return bytes(r.data), r.filename, r.content_type


def delete_attachment(ctx: AppContext, a: Act, attachment_id: str) -> None:
    from .. import repo
    from ...audit_diff import audit_regulated, part11_on

    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, QaAttachmentRow, attachment_id, what="Attachment", lock=True)
        parent = _parent(s, r.entity_type, r.entity_id, lock=True)
        _check_open(r.entity_type, parent)
        if part11_on(s) and getattr(parent, "status", None) not in ("draft", "open", None):
            raise ApiError(409, "PART11_DELETE_NOT_ALLOWED", "In Part 11 mode attachments of records in work "
                           "cannot be deleted.", {})
        audit_regulated(s, "attachment", r.id, "delete", before=attachment_record(r), after={})
        s.delete(r)


__getattr__ = m7_examples.module_getattr(__name__)
