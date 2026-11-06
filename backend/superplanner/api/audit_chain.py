"""Audit hash chain (M5-DESIGN 7): `chain_hash = H(previous chain_hash of the same owner || canonical row)`, linked
on insert under the owner's transaction-scoped advisory lock; `verify` walks an owner's rows by id and reports the
first broken link (tamper evidence; `manage.py audit-verify`, `GET /audit/verify`).

Keyed chain (15.WP-S security review): when `SECRETS_KEY(S)` is configured for the database (`configure`, called by
`Database.from_settings`), H is HMAC-SHA256 with a key derived from the first secrets key and the hash is stored as
`k1:<hex>`; without a key it is plain SHA-256 (`<hex>`). Somebody with write access to the table but without the key
cannot recompute a valid chain after a change. A per-owner head row (`audit_chain_heads`: last id, last hash and a
keyed MAC over both) is written at commit, so deleting the newest rows (truncation) is detected too. `verify`
accepts every configured key (rotation) and refuses unkeyed rows after the first keyed one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import weakref
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

_KEYS: "weakref.WeakKeyDictionary[Any, list[bytes]]" = weakref.WeakKeyDictionary()


def derive(secret: str) -> bytes:
    return hashlib.sha256(b"superplanner-audit-chain|" + secret.encode()).digest()


def configure(engine: Any, secrets_keys: list[str] | None) -> None:
    """Chain keys for one engine (first = signing key; all verify)."""
    _KEYS[engine] = [derive(k) for k in (secrets_keys or []) if k]


def _keys(s: Session) -> list[bytes]:
    try:
        return _KEYS.get(s.get_bind(), [])
    except TypeError:          # pragma: no cover - unhashable bind
        return []


def canonical(row: Any) -> bytes:
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    doc = {"entity_type": row.entity_type, "entity_id": row.entity_id, "action": row.action,
           "details": row.details or {}, "actor_id": row.actor_id, "owner_id": row.owner_id,
           "created_at": created.astimezone(UTC).isoformat(timespec="microseconds")}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode()


def _hash(prev: str | None, row: Any, key: bytes | None = None) -> str:
    msg = (prev or "").encode() + b"|" + canonical(row)
    if key is None:
        return hashlib.sha256(msg).hexdigest()
    return "k1:" + hmac.new(key, msg, hashlib.sha256).hexdigest()


def _head_mac(owner_key: str, last_id: int, head: str, key: bytes | None) -> str:
    msg = f"{owner_key}|{last_id}|{head}".encode()
    if key is None:
        return hashlib.sha256(msg).hexdigest()
    return "k1:" + hmac.new(key, msg, hashlib.sha256).hexdigest()


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
    keys = _keys(s)
    row.chain_hash = _hash(cache[key], row, keys[0] if keys else None)
    cache[key] = row.chain_hash
    s.info.setdefault("sp_audit_last", {})[key] = row


def _write_heads(session: Session) -> None:
    last = session.info.pop("sp_audit_last", None)
    if not last:
        return
    from sqlalchemy.dialects.postgresql import insert

    from ..api.mfg.db_models_m5 import AuditChainHeadRow

    session.flush()
    keys = _keys(session)
    k = keys[0] if keys else None
    now = datetime.now(UTC)
    for owner_key, row in last.items():
        if row.id is None or row.chain_hash is None:
            continue
        mac = _head_mac(owner_key, int(row.id), row.chain_hash, k)
        session.execute(insert(AuditChainHeadRow.__table__).values(
            owner_key=owner_key, last_id=int(row.id), head_hash=row.chain_hash, mac=mac, updated_at=now)
            .on_conflict_do_update(index_elements=["owner_key"], set_={"last_id": int(row.id),
                                                                         "head_hash": row.chain_hash, "mac": mac,
                                                                         "updated_at": now}))


def verify(s: Session, owner_id: str | None) -> dict[str, Any]:
    """{ok, checked, first_broken_id, reason}; rows without a hash (before M5) are skipped, the chain starts at the
    first. Checks the head row (truncation) when it exists."""
    from ..api.mfg.db_models_m5 import AuditChainHeadRow
    from .db.models import AuditEventRow

    keys = _keys(s)
    cond = AuditEventRow.owner_id == owner_id if owner_id else AuditEventRow.owner_id.is_(None)
    prev = None
    n = 0
    keyed = False
    last_id = None
    for row in s.execute(select(AuditEventRow).where(cond, AuditEventRow.chain_hash.is_not(None))
                         .order_by(AuditEventRow.id)).scalars().yield_per(2000):
        h = row.chain_hash or ""
        if h.startswith("k1:"):
            keyed = True
            ok = any(hmac.compare_digest(h, _hash(prev, row, k)) for k in keys)
            reason = "keyed hash mismatch" if keys else "keyed chain, but no SECRETS_KEY is configured"
        else:
            ok = not keyed and h == _hash(prev, row)
            reason = "unkeyed row after keyed rows" if keyed else "hash mismatch"
        if not ok:
            return {"ok": False, "checked": n, "first_broken_id": int(row.id), "reason": reason}
        prev = h
        last_id = int(row.id)
        n += 1
    head = s.get(AuditChainHeadRow, owner_id or "")
    if head is not None:
        macs = [_head_mac(owner_id or "", int(head.last_id), head.head_hash, k) for k in keys] or \
            [_head_mac(owner_id or "", int(head.last_id), head.head_hash, None)]
        if not any(hmac.compare_digest(head.mac, m) for m in macs):
            return {"ok": False, "checked": n, "first_broken_id": int(head.last_id), "reason": "head MAC mismatch"}
        if last_id != int(head.last_id) or prev != head.head_hash:
            return {"ok": False, "checked": n, "first_broken_id": int(head.last_id),
                    "reason": "the newest rows are missing (truncated)"}
    return {"ok": True, "checked": n, "first_broken_id": None, "reason": None}


def _clear(session: Session, *_a: Any) -> None:
    session.info.pop("sp_audit_tail", None)
    session.info.pop("sp_audit_last", None)


from sqlalchemy import event as _event  # noqa: E402

_event.listen(Session, "before_commit", _write_heads)
_event.listen(Session, "after_commit", _clear)
_event.listen(Session, "after_rollback", _clear)
_event.listen(Session, "after_soft_rollback", _clear)
