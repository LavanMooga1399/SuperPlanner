"""M7-DESIGN 4.3: `eco.approve` is signable; the content loader of change requests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ....esig import content as C


def _loader(s: Session, record_id: str, lock: bool) -> C.Loaded:
    from .eco import _get, _items

    r = _get(s, record_id, lock=lock)
    items = [{"doc_type": i.doc_type, "doc_id": i.doc_id, "supersedes_doc_id": i.supersedes_doc_id,
              "disposition": i.disposition} for i in _items(s, r.id)]
    content = {"id": r.id, "number": r.number, "title": r.title, "reason": r.reason, "kind": r.kind,
               "effectivity": r.effectivity or {}, "status": r.status, "items": items}
    return C.Loaded(r, content, r.row_version, r.submitted_by,
                    [("Change request", r.number), ("Title", r.title), ("Items", str(len(items)))])


C.register("eco", _loader)
