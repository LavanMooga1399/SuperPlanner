"""5-minute tool-result cache (M6-DESIGN 1.6), keyed by plant, tool, arguments and a data token (plant data version,
latest live MRP run, published schedule run). Only plan views are cached (their data is fixed per run); stock,
floor and search results are always fresh. Process-local, bounded."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any

TTL_SECONDS = 300.0
MAX_ENTRIES = 500
CACHEABLE = frozenset({"mrp_exceptions", "mrp_item_plan", "mrp_pegging", "schedule_order", "schedule_bottlenecks",
                       "overtime_options", "kpis", "demand_status"})

_lock = threading.Lock()
_entries: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()


def key(owner_id: str, tool: str, args: dict[str, Any], token: tuple[Any, ...]) -> str:
    raw = json.dumps([owner_id, tool, args, list(token)], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(k: str) -> Any | None:
    with _lock:
        hit = _entries.get(k)
        if hit is None:
            return None
        if time.monotonic() - hit[0] > TTL_SECONDS:
            _entries.pop(k, None)
            return None
        _entries.move_to_end(k)
        return hit[1]


def put(k: str, value: Any) -> None:
    with _lock:
        _entries[k] = (time.monotonic(), value)
        _entries.move_to_end(k)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear() -> None:
    with _lock:
        _entries.clear()


def data_token(s: Any) -> tuple[Any, ...]:
    from sqlalchemy import select

    from ..api.mfg.db_models import MfgPlantRow
    from ..api.mfg.db_models_m2 import MfgMrpRunRow
    from ..api.mfg.db_models_m3 import MfgApsRunRow

    dv = s.execute(select(MfgPlantRow.data_version)).scalar()
    mrp = s.execute(select(MfgMrpRunRow.id).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                    .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalar()
    aps = s.execute(select(MfgApsRunRow.id, MfgApsRunRow.row_version).where(MfgApsRunRow.is_published.is_(True))
                    .limit(1)).first()
    return (dv, mrp, tuple(aps) if aps else None)
