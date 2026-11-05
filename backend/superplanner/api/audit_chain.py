"""Audit hash chain (M5-DESIGN 7): `chain_hash = sha256(previous chain_hash of the same owner || canonical row)`,
linked on insert under the owner's transaction-scoped advisory lock; `verify` walks an owner's rows by id and
reports the first broken link (tamper evidence; `manage.py audit-verify`)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session


def canonical(row: Any) -> bytes:
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    doc = {"entity_type": row.entity_type, "entity_id": row.entity_id, "action": row.action,
           "details": row.details or {}, "actor_id": row.actor_id, "owner_id": row.owner_id,
           "created_at": created.astimezone(UTC).isoformat(timespec="microseconds")}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode()


def _hash(prev: str | None, row: Any) -> str:
    return hashlib.sha256((prev or "").encode() + b"|" + canonical(row)).hexdigest()


def link(s: Session, row: Any) -> None:
    """Set `row.chain_hash` (call before adding the row; one chain per owner, platform rows share the '' chain)."""
    from .db.models import AuditEventRow

    key = row.owner_id or ""
    cache = s.info.setdefault("sp_audit_tail", {})
    if key not in cache:
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": "sp-audit:" + key})
        s.flush()
        cond = AuditEventRow.owner_id == row.owner_id if row.owner_id else AuditEventRow.owner_id.is_(None)
        cache[key] = s.execute(select(AuditEventRow.chain_hash).where(cond, AuditEventRow.chain_hash.is_not(None))
                               .order_by(AuditEventRow.id.desc()).limit(1)).scalar()
    row.chain_hash = _hash(cache[key], row)
    cache[key] = row.chain_hash


def verify(s: Session, owner_id: str | None) -> dict[str, Any]:
    """{ok, checked, first_broken_id}; rows without a hash (before M5) are skipped, the chain starts at the first."""
    from .db.models import AuditEventRow

    cond = AuditEventRow.owner_id == owner_id if owner_id else AuditEventRow.owner_id.is_(None)
    prev = None
    n = 0
    for row in s.execute(select(AuditEventRow).where(cond, AuditEventRow.chain_hash.is_not(None))
                         .order_by(AuditEventRow.id)).scalars().yield_per(2000):
        if row.chain_hash != _hash(prev, row):
            return {"ok": False, "checked": n, "first_broken_id": int(row.id)}
        prev = row.chain_hash
        n += 1
    return {"ok": True, "checked": n, "first_broken_id": None}


def _clear(session: Session, *_a: Any) -> None:
    session.info.pop("sp_audit_tail", None)


from sqlalchemy import event as _event  # noqa: E402

_event.listen(Session, "after_commit", _clear)
_event.listen(Session, "after_rollback", _clear)
_event.listen(Session, "after_soft_rollback", _clear)
