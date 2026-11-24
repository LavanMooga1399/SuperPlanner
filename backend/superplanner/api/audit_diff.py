"""Field-level audit of regulated records (M7-DESIGN 4.4).

- `diff(before, after)` -> `[{path, old, new}]` from the records' JSON dumps: dicts by key, lists of dicts by `id`,
  else `seq` / `line_no` (path `lines[line_no=3].qty`), other lists as a whole; at most `MAX_CHANGES` entries;
  strings longer than `MAX_TEXT` are truncated and carry `old_sha256` / `new_sha256`. Bookkeeping keys
  (`row_version`, `updated_at`, `created_at`, `signatures`, `links`, `attachments`) are ignored.
- `parse_reason(raw)`: the `X-SP-Change-Reason` header (percent-encoded UTF-8, 1..500 characters after decoding).
- `audit_regulated(s, entity, entity_id, action, before=, after=, reason=, ...)`: one audit event carrying `changes`,
  `reason`, `record_version` and `signature_id`; in Part 11 mode a missing reason on an update / delete / status
  action is 422 `AUDIT_REASON_REQUIRED` (creates are excepted).
- Request binding: `bind_reason(value)` / `current_reason()` (a context variable set by the mfg principal
  dependency from the header, so existing services pick the reason up without new parameters).
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import urllib.parse
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from .errors import ApiError

MAX_CHANGES = 500
MAX_TEXT = 1000
REASON_HEADER = "X-SP-Change-Reason"
IGNORED = frozenset({"row_version", "updated_at", "created_at", "signatures", "links", "attachments", "next_actions",
                     "overdue", "valid", "due_state", "verdict"})
#: M7-DESIGN 4.4 registry: audit entity types (without the `mfg_` prefix) of regulated records
PART11_ENTITIES: frozenset[str] = frozenset({
    "item", "bom", "routing", "operation", "plant", "location", "lot", "hold", "work_order", "change_request",
    "member", "plant_roles", "qa_settings", "sampling_scheme", "inspection_plan", "inspection_lot", "ncr", "capa",
    "capa_action", "complaint", "field_action", "field_action_unit", "equipment", "calibration", "esig_policy",
    "attachment", "link"})
#: actions that never need a reason (creates, postings and their replays, sample loads, imports with their own reason)
EXEMPT_ACTIONS: frozenset[str] = frozenset({"create", "post", "replay", "sample_load", "import", "add", "copy",
                                             "member_add", "results"})
_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar("sp_change_reason", default=None)


def bind_reason(value: str | None) -> None:
    _reason.set(value)


def current_reason() -> str | None:
    return _reason.get()


def parse_reason(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        text = urllib.parse.unquote(raw.strip(), encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        text = ""
    text = text.strip()
    if not 1 <= len(text) <= 500 or any(ord(ch) < 32 and ch not in "\t" for ch in text):
        raise ApiError(422, "VALIDATION_ERROR", f"{REASON_HEADER} must be 1-500 characters (percent-encoded UTF-8).",
                       {"errors": [{"loc": ["header", REASON_HEADER], "msg": "invalid change reason",
                                    "type": "value_error"}]})
    return text


def _plain(v: Any) -> Any:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "model_dump"):
        return _plain(v.model_dump(mode="json", by_alias=True))
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _key_of(xs: list[Any]) -> str | None:
    if not xs or not all(isinstance(x, dict) for x in xs):
        return None
    for k in ("id", "seq", "line_no"):
        if all(k in x for x in xs):
            return k
    return None


def _sha(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, default=str).encode()).hexdigest()


def _change(path: str, old: Any, new: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path, "old": old, "new": new}
    for side, v in (("old", old), ("new", new)):
        if isinstance(v, str) and len(v) > MAX_TEXT:
            out[side] = v[:MAX_TEXT] + "..."
            out[f"{side}_sha256"] = _sha(v)
    return out


def _walk(path: str, a: Any, b: Any, out: list[dict[str, Any]]) -> None:
    if len(out) >= MAX_CHANGES:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if not path and k in IGNORED:
                continue
            _walk(f"{path}.{k}" if path else str(k), a.get(k), b.get(k), out)
        return
    if isinstance(a, list) and isinstance(b, list):
        key = _key_of(a + b)
        if key is not None:
            ia = {x[key]: x for x in a}
            ib = {x[key]: x for x in b}
            for k in [x[key] for x in a] + [x[key] for x in b if x[key] not in ia]:
                _walk(f"{path}[{key}={k}]", ia.get(k), ib.get(k), out)
            return
    if a != b:
        out.append(_change(path, a, b))


def diff(before: Any, after: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    _walk("", _plain(before) if before is not None else {}, _plain(after) if after is not None else {}, out)
    return out[:MAX_CHANGES]


def part11_on(s: Session) -> bool:
    from .mfg.db_models import MfgPlantRow

    cache = s.info.get("sp_part11")
    if cache is None:
        from sqlalchemy import select

        cache = bool(s.execute(select(MfgPlantRow.part11_mode).limit(1)).scalar() or False)
        s.info["sp_part11"] = cache
    return cache


def require_reason(s: Session, reason: str | None) -> str | None:
    """In Part 11 mode an update / delete / status action of a regulated record needs a reason."""
    r = reason if reason is not None else current_reason()
    if r is None and part11_on(s):
        raise ApiError(422, "AUDIT_REASON_REQUIRED", "This plant runs in Part 11 mode: give a reason for the change.",
                       {"header": REASON_HEADER})
    return r


def audit_regulated(s: Session, entity: str, entity_id: str, action: str, *, before: Any = None, after: Any = None,
                    reason: str | None = None, record_version: int | None = None, signature_id: str | None = None,
                    details: dict[str, Any] | None = None, create: bool = False) -> Any:
    """Write one audit event of a regulated record (field changes + reason); returns the row (flushed: `id`)."""
    from .services.problem_service import audit_row

    r = reason if reason is not None else current_reason()
    if not create:
        r = require_reason(s, r)
    changes = diff(before, after) if (before is not None or after is not None) else []
    row = audit_row(s, f"mfg_{entity}", entity_id, action, details or {}, changes=changes, reason=r,
                    record_version=record_version, signature_id=signature_id)
    return row


__all__ = ["MAX_CHANGES", "PART11_ENTITIES", "REASON_HEADER", "audit_regulated", "bind_reason", "current_reason",
           "diff", "parse_reason", "part11_on", "require_reason"]
