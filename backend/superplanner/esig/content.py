"""Signed content (M7-DESIGN 4.2 "Linking", 11.70): canonical JSON and its sha256, and the per-record-type content
registry.

Canonical JSON: sorted keys, separators `,` `:`, UTF-8 (no ASCII escaping), floats as `format(x, ".15g")` (integral
floats as integers), dates ISO, datetimes UTC with `Z`. The content of a record is its business fields (ids,
numbers, quantities, decisions, child lines, attachment sha256 list) - never `row_version`, timestamps or signatures.
Snapshots are limited to 256 KB (422 `ESIG_CONTENT_TOO_LARGE`).

Registry: `register(record_type, loader)`; a loader `(session, record_id, lock) -> Loaded` returns the row, its
content, its version, its author and summary lines. Service modules register their types at import
(`services/esig.load_registry()` imports them).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

MAX_CONTENT_BYTES = 256 * 1024


def _norm(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            return str(v)
        if v == int(v) and abs(v) < 1e15:
            return int(v)
        return _Float(v)
    if isinstance(v, datetime):
        d = v if v.tzinfo else v.replace(tzinfo=UTC)
        return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if hasattr(v, "model_dump"):
        return _norm(v.model_dump(mode="json", by_alias=True))
    return str(v)


class _Float(float):
    def __repr__(self) -> str:
        return format(float(self), ".15g")




def plain(v: Any) -> Any:
    """The JSON-safe normalised form (what is stored as the snapshot)."""
    return json.loads(canonical(v))


def canonical(v: Any) -> str:
    def enc(x: Any) -> str:
        if isinstance(x, _Float):
            return format(float(x), ".15g")
        if isinstance(x, dict):
            return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + enc(x[k]) for k in sorted(x)) + "}"
        if isinstance(x, list):
            return "[" + ",".join(enc(i) for i in x) + "]"
        return json.dumps(x, ensure_ascii=False)

    return enc(_norm(v))


def content_hash(v: Any) -> str:
    return hashlib.sha256(canonical(v).encode("utf-8")).hexdigest()


def size_ok(v: Any) -> bool:
    return len(canonical(v).encode("utf-8")) <= MAX_CONTENT_BYTES


@dataclass
class Loaded:
    row: Any
    content: dict[str, Any]
    version: int
    author_id: str | None = None
    summary: list[tuple[str, str]] = field(default_factory=list)


Loader = Callable[[Any, str, bool], Loaded]
REGISTRY: dict[str, Loader] = {}


def register(record_type: str, loader: Loader) -> Loader:
    REGISTRY[record_type] = loader
    return loader


__all__ = ["Loaded", "MAX_CONTENT_BYTES", "REGISTRY", "canonical", "content_hash", "plain", "register", "size_ok"]
