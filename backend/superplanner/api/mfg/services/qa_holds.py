"""First-class holds (M7-DESIGN 5.3, 0.6).

Every open `mfg_lot_holds` row keeps `mfg_lots.hold` (serials: `mfg_unit_serials.hold`) true; the flag is recomputed
on each place/release under the lot (serial) row lock. A hold is released only by its source document: inspection
and NCR holds through the inspection lot / NCR (409 `QA_HOLD_OWNED` here); manual, recall and field action holds
through `POST /qa/holds/{id}/release` (signed `hold.release` in Part 11 mode). M2 `PUT /lots/{id} {hold}` maps to
manual holds (`lot_put_hold`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ....esig import content as C
from ....qa.model import HoldInput, HoldReleaseInput
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models_m2 import MfgLotRow
from ..db_models_m4 import MfgUnitSerialRow
from ..db_models_m7 import MfgLotHoldRow
from . import m7_examples
from .common import read_tx, write_tx
from .qa_common import Act, decorate, item_ref

OWNED_SOURCES = ("inspection", "ncr")
SIGNED_SOURCES = ("manual", "recall", "field_action")


def _source_number(s: Session, r: MfgLotHoldRow) -> str | None:
    if not r.source_id:
        return None
    from ..db_models_m5 import MfgRecallRow
    from ..db_models_m7 import QaFieldActionRow, QaInspectionLotRow, QaNcrRow

    model = {"inspection": QaInspectionLotRow, "ncr": QaNcrRow, "recall": MfgRecallRow,
             "field_action": QaFieldActionRow}.get(r.source)
    if model is None:
        return None
    row = s.get(model, r.source_id)
    return getattr(row, "number", None) if row is not None else None


def hold_record(s: Session, r: MfgLotHoldRow, full: bool = False) -> dict[str, Any]:
    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    ser = s.get(MfgUnitSerialRow, r.serial_id) if r.serial_id else None
    rec = {"id": r.id, "row_version": r.row_version, "created_at": r.created_at, "updated_at": r.updated_at,
           "lot_id": r.lot_id, "lot_code": lot.lot_code if lot else None, "serial_id": r.serial_id,
           "serial": ser.serial if ser else None, "item_id": r.item_id, "item": item_ref(s, r.item_id),
           "source": r.source, "source_id": r.source_id, "source_number": _source_number(s, r), "reason": r.reason,
           "placed_by": r.placed_by, "placed_at": r.placed_at, "released_by": r.released_by,
           "released_at": r.released_at, "release_signature_id": r.release_signature_id,
           "release_note": r.release_note, "open": r.released_at is None, "signatures": [], "links": [],
           "attachments": []}
    if full:
        from . import esig

        rec["signatures"] = esig.manifests(s, "hold", r.id)
    return rec


def _content(s: Session, r: MfgLotHoldRow) -> dict[str, Any]:
    lot = s.get(MfgLotRow, r.lot_id) if r.lot_id else None
    return {"id": r.id, "lot_id": r.lot_id, "lot_code": lot.lot_code if lot else None, "serial_id": r.serial_id,
            "item_id": r.item_id, "source": r.source, "source_id": r.source_id, "reason": r.reason,
            "open": r.released_at is None}


def _loader(s: Session, record_id: str, lock: bool) -> C.Loaded:
    r = repo.get_row(s, MfgLotHoldRow, record_id, what="Hold", lock=lock)
    c = _content(s, r)
    return C.Loaded(r, c, r.row_version, r.placed_by, [("Hold", r.reason), ("Lot", str(c["lot_code"] or "-")),
                                                        ("Source", r.source)])


C.register("hold", _loader)


# ---------------------------------------------------------------- core (used by inspection, NCR, recalls, FAs)

def _recompute_lot(s: Session, lot_id: str) -> None:
    n = int(s.execute(select(func.count()).select_from(MfgLotHoldRow).where(
        MfgLotHoldRow.lot_id == lot_id, MfgLotHoldRow.released_at.is_(None))).scalar() or 0)
    # the flag is derived (holds are the record): no row_version bump, PUT /lots never writes it directly
    s.execute(update(MfgLotRow).where(MfgLotRow.id == lot_id, MfgLotRow.hold.is_not(n > 0))
              .values(hold=n > 0, updated_at=utcnow()).execution_options(synchronize_session="fetch"))


def _recompute_serial(s: Session, serial_id: str) -> None:
    n = int(s.execute(select(func.count()).select_from(MfgLotHoldRow).where(
        MfgLotHoldRow.serial_id == serial_id, MfgLotHoldRow.released_at.is_(None))).scalar() or 0)
    s.execute(update(MfgUnitSerialRow).where(MfgUnitSerialRow.id == serial_id).values(hold=n > 0)
              .execution_options(synchronize_session="fetch"))


def _lock_target(s: Session, lot_id: str | None, serial_id: str | None) -> Any:
    if lot_id:
        return s.execute(select(MfgLotRow).where(MfgLotRow.id == lot_id).with_for_update()).scalars().first()
    return s.execute(select(MfgUnitSerialRow).where(MfgUnitSerialRow.id == serial_id).with_for_update()
                     ).scalars().first()


def _emit(s: Session, event: str, r: MfgLotHoldRow) -> None:
    from ....integration import outbox

    if outbox.enabled(s):
        outbox.emit(s, event, {"hold_id": r.id, "lot_id": r.lot_id, "serial_id": r.serial_id, "item_id": r.item_id,
                               "source": r.source, "source_id": r.source_id, "reason": r.reason}, r.id)


def place(s: Session, *, source: str, reason: str, actor: str, lot_id: str | None = None,
          serial_id: str | None = None, source_id: str | None = None, item_id: str | None = None) -> MfgLotHoldRow:
    """Place one hold (idempotent per source/target: an open hold of the same source document is returned)."""
    from .common import audit

    target = _lock_target(s, lot_id, serial_id)
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Lot or serial not found.", {"lot_id": lot_id, "serial_id": serial_id})
    q = select(MfgLotHoldRow).where(MfgLotHoldRow.source == source, MfgLotHoldRow.released_at.is_(None),
                                    (MfgLotHoldRow.lot_id == lot_id) if lot_id else
                                    (MfgLotHoldRow.serial_id == serial_id))
    if source_id is not None:
        q = q.where(MfgLotHoldRow.source_id == source_id)
    found = s.execute(q).scalars().first()
    if found is not None and source != "manual":
        return found
    now = utcnow()
    r = MfgLotHoldRow(id=new_id("hld_"), lot_id=lot_id, serial_id=serial_id, item_id=item_id or target.item_id,
                      source=source, source_id=source_id, reason=reason[:500], placed_by=actor, placed_at=now,
                      released_by=None, released_at=None, release_signature_id=None, release_note="",
                      row_version=1, created_at=now, updated_at=now)
    s.add(r)
    s.flush()
    _recompute_lot(s, lot_id) if lot_id else _recompute_serial(s, serial_id)  # type: ignore[arg-type]
    audit(s, "hold", r.id, "create", {"source": source, "source_id": source_id, "lot_id": lot_id,
                                      "serial_id": serial_id, "reason": r.reason})
    _emit(s, "qa.hold.placed", r)
    return r


def _release_row(s: Session, r: MfgLotHoldRow, actor: str, note: str, signature_id: str | None = None,
                 reason: str | None = None) -> None:
    from ...audit_diff import audit_regulated

    before = _content(s, r)
    r.released_by, r.released_at = actor, utcnow()
    r.release_note, r.release_signature_id = note[:500], signature_id
    r.row_version += 1
    r.updated_at = r.released_at
    s.flush()
    if r.lot_id:
        _lock_target(s, r.lot_id, None)
        _recompute_lot(s, r.lot_id)
    else:
        _lock_target(s, None, r.serial_id)
        _recompute_serial(s, r.serial_id)  # type: ignore[arg-type]
    audit_regulated(s, "hold", r.id, "release", before=before, after=_content(s, r),
                    reason=reason or note or f"Released by its {r.source.replace('_', ' ')}",
                    record_version=r.row_version, signature_id=signature_id)
    _emit(s, "qa.hold.released", r)


def release_source(s: Session, source: str, source_id: str, actor: str, note: str = "",
                   signature_id: str | None = None, lot_id: str | None = None) -> int:
    """Release the open holds a source document placed (inspection lot, NCR, recall, field action)."""
    q = select(MfgLotHoldRow).where(MfgLotHoldRow.source == source, MfgLotHoldRow.source_id == source_id,
                                    MfgLotHoldRow.released_at.is_(None))
    if lot_id is not None:
        q = q.where(MfgLotHoldRow.lot_id == lot_id)
    rows = list(s.execute(q.order_by(MfgLotHoldRow.id).with_for_update()).scalars())
    for r in rows:
        _release_row(s, r, actor, note, signature_id)
    return len(rows)


def open_holds(s: Session, lot_id: str | None = None, serial_id: str | None = None) -> list[MfgLotHoldRow]:
    q = select(MfgLotHoldRow).where(MfgLotHoldRow.released_at.is_(None))
    q = q.where(MfgLotHoldRow.lot_id == lot_id) if lot_id else q.where(MfgLotHoldRow.serial_id == serial_id)
    return list(s.execute(q.order_by(MfgLotHoldRow.placed_at)).scalars())


def ncr_only_lots(s: Session, ncr_id: str) -> set[tuple[str, str]]:
    """(item_id, lot_code) of lots held by this NCR whose every open hold is an `ncr` hold of this NCR."""
    out: set[tuple[str, str]] = set()
    for lot in s.execute(select(MfgLotRow).join(MfgLotHoldRow, MfgLotHoldRow.lot_id == MfgLotRow.id).where(
            MfgLotHoldRow.source == "ncr", MfgLotHoldRow.source_id == ncr_id,
            MfgLotHoldRow.released_at.is_(None))).scalars():
        others = s.execute(select(MfgLotHoldRow.id).where(
            MfgLotHoldRow.lot_id == lot.id, MfgLotHoldRow.released_at.is_(None),
            (MfgLotHoldRow.source != "ncr") | (MfgLotHoldRow.source_id != ncr_id)).limit(1)).first()
        if others is None:
            out.add((lot.item_id, lot.lot_code))
    return out


def lot_put_hold(s: Session, lot: MfgLotRow, hold: bool, actor: str) -> None:
    """M2 `PUT /lots/{id} {hold}`: place a manual hold / release the manual holds (others stay: 409)."""
    cur = open_holds(s, lot_id=lot.id)
    if hold:
        if not cur:
            place(s, source="manual", reason="Hold set on the lot", actor=actor, lot_id=lot.id)
        return
    manual = [r for r in cur if r.source == "manual"]
    others = [r for r in cur if r.source != "manual"]
    if others:
        raise ApiError(409, "QA_HOLD_ACTIVE", "This lot is held by quality documents; release them there.",
                       {"holds": [{"id": r.id, "source": r.source, "source_number": _source_number(s, r)}
                                  for r in others]})
    from ...audit_diff import part11_on

    if manual and part11_on(s):
        raise ApiError(409, "QA_HOLD_OWNED", "In Part 11 mode manual holds are released with a signature "
                       "(Quality - Holds).", {"holds": [r.id for r in manual]})
    for r in manual:
        _release_row(s, r, actor, "Hold cleared on the lot")


# ---------------------------------------------------------------- API (Q21-Q23)

def list_holds(ctx: AppContext, open_: bool | None, source: str | None, lot_id: str | None, item_id: str | None,
               limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if open_ is True:
        conds.append(MfgLotHoldRow.released_at.is_(None))
    elif open_ is False:
        conds.append(MfgLotHoldRow.released_at.is_not(None))
    if source:
        conds.append(MfgLotHoldRow.source == source)
    if lot_id:
        conds.append(MfgLotHoldRow.lot_id == lot_id)
    if item_id:
        conds.append(MfgLotHoldRow.item_id == item_id)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgLotHoldRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgLotHoldRow).where(*conds).order_by(MfgLotHoldRow.placed_at.desc(),
                                                                          MfgLotHoldRow.id)
                              .limit(limit).offset(offset)).scalars())
        return {"items": [hold_record(s, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def place_manual(ctx: AppContext, a: Act, body: HoldInput) -> dict[str, Any]:
    with write_tx(ctx) as (s, _plant):
        r = place(s, source="manual", reason=body.reason, actor=a.user_id, lot_id=body.lot_id,
                  serial_id=body.serial_id)
        return decorate(s, hold_record(s, r, True), "hold")


def release(ctx: AppContext, a: Act, hold_id: str, body: HoldReleaseInput) -> dict[str, Any]:
    from . import esig

    with read_tx(ctx) as s:
        r = repo.get_row(s, MfgLotHoldRow, hold_id, what="Hold")
        src, src_id = r.source, r.source_id
    if src in OWNED_SOURCES:
        raise ApiError(409, "QA_HOLD_OWNED", f"This {src} hold is released by its document (the inspection lot or "
                       "NCR).", {"source": src, "source_id": src_id})
    auth = esig.authenticate(ctx, a, "hold", "release", body.signature)
    with write_tx(ctx) as (s, _plant):
        r = repo.get_row(s, MfgLotHoldRow, hold_id, what="Hold", lock=True)
        if r.released_at is not None:
            raise ApiError(409, "MFG_INVALID_STATE", "This hold is already released.", {"status": "released"})
        out = esig.sign(s, a, auth, "hold", r.id, "release", body.signature)
        if out.pending is not None:
            return out.pending
        sig_id = out.signature_ids[-1] if out.signature_ids else None
        _release_row(s, r, a.user_id, body.note, sig_id,
                     reason=(body.signature.comment if body.signature and body.signature.comment else None))
        return hold_record(s, r, True)


__getattr__ = m7_examples.module_getattr(__name__)
