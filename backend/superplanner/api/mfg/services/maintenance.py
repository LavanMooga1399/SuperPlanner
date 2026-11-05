"""Retention, archival and trace backfill (M5-DESIGN 7, 6.1; job kinds `maintenance_retention`, `trace_backfill`).

Classes (7): `ledger` (postings + transactions), `floor_events`, `trace_edges`, `serials`, `lots`, `audit` are kept
indefinitely - `archive` only exports them. Purgeable after archiving: `notifications` / `replan_triggers`
(handled) after 180 days, `outbox` (events delivered to every active endpoint and exported) after 90 days,
`inbox_payloads` (the payload column only) after 30 days, `kpi_daily` after 3 years.

`archive(s, owner, before, classes, dir)` writes `ARCHIVE_DIR/<owner>/<class>/<yyyy-mm>.jsonl.gz` (one line per
row, canonical JSON) plus `manifest.json` (files, counts, sha256) and returns the manifest; `purge=True` then
deletes only the purgeable classes' rows it archived. Archive files are never overwritten: a second run for the
same month writes `<yyyy-mm>.<n>.jsonl.gz`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

INDEFINITE = ("ledger", "floor_events", "trace_edges", "serials", "lots", "audit")
PURGEABLE = {"notifications": 180, "replan_triggers": 180, "outbox": 90, "inbox_payloads": 30,
             "kpi_daily": 3 * 365}
CLASSES = INDEFINITE + tuple(PURGEABLE)


def _model(cls: str) -> tuple[Any, Any, list[Any]]:
    """(model, date column, extra conditions)."""
    from ...db.models import AuditEventRow
    from ..db_models_m2 import MfgInvPostingRow, MfgLotRow
    from ..db_models_m4 import (MfgFloorEventRow, MfgKpiDailyRow, MfgNotificationRow, MfgReplanTriggerRow,
                                MfgUnitSerialRow)
    from ..db_models_m5 import IntInboxRow, IntOutboxRow, MfgTraceEdgeRow

    return {"ledger": (MfgInvPostingRow, MfgInvPostingRow.created_at, []),
            "floor_events": (MfgFloorEventRow, MfgFloorEventRow.recorded_at, []),
            "trace_edges": (MfgTraceEdgeRow, MfgTraceEdgeRow.event_at, []),
            "serials": (MfgUnitSerialRow, MfgUnitSerialRow.created_at, []),
            "lots": (MfgLotRow, MfgLotRow.created_at, []),
            "audit": (AuditEventRow, AuditEventRow.created_at, []),
            "notifications": (MfgNotificationRow, MfgNotificationRow.created_at, []),
            "replan_triggers": (MfgReplanTriggerRow, MfgReplanTriggerRow.detected_at,
                                [MfgReplanTriggerRow.status.in_(("handled", "ignored"))]),
            "outbox": (IntOutboxRow, IntOutboxRow.occurred_at, []),
            "inbox_payloads": (IntInboxRow, IntInboxRow.received_at, [IntInboxRow.payload.is_not(None)]),
            "kpi_daily": (MfgKpiDailyRow, MfgKpiDailyRow.computed_at, [])}[cls]


def _row_dict(r: Any) -> dict[str, Any]:
    from .common import jsonable

    return {c.key: jsonable(getattr(r, c.key)) for c in r.__table__.columns}


def _outbox_floor(s: Session, owner: str) -> int:
    """Highest seq delivered to every active endpoint and exported (when export is on)."""
    from ..db_models_m5 import IntEndpointRow, IntOutboxRow, IntSettingsRow

    top = int(s.execute(select(func.max(IntOutboxRow.seq)).where(IntOutboxRow.owner_id == owner)).scalar() or 0)
    cur = [int(c) for c in s.execute(select(IntEndpointRow.cursor).where(IntEndpointRow.owner_id == owner,
                                                                         IntEndpointRow.active.is_(True))).scalars()]
    st = s.execute(select(IntSettingsRow).where(IntSettingsRow.owner_id == owner)).scalars().first()
    if st is not None and st.export_enabled:
        cur.append(int(st.export_cursor or 0))
    return min(cur) if cur else top


def _conds(s: Session, cls: str, owner: str | None, before: datetime) -> list[Any]:
    model, col, extra = _model(cls)
    c = [col < before, *extra]
    if owner is not None:
        c.append(model.owner_id == owner)
    if cls == "outbox" and owner is not None:
        from ..db_models_m5 import IntOutboxRow

        c.append(IntOutboxRow.seq <= _outbox_floor(s, owner))
    return c


def _write(base: Path, rows_by_month: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    files = []
    base.mkdir(parents=True, exist_ok=True)
    for month, rows in sorted(rows_by_month.items()):
        p = base / f"{month}.jsonl.gz"
        n = 1
        while p.exists():
            p = base / f"{month}.{n}.jsonl.gz"
            n += 1
        raw = "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) + "\n" for r in rows).encode()
        with gzip.open(p, "wb") as f:
            f.write(raw)
        files.append({"file": p.name, "rows": len(rows), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return files


def archive(s: Session, owner: str, before: datetime, classes: Iterable[str], archive_dir: str | None,
            purge: bool = False) -> dict[str, Any]:
    """Export (and with `purge`, delete the purgeable) rows older than `before` of one plant (caller in system
    scope). Purge without an archive directory is allowed for the purgeable classes only (7: "before deletion
    when ARCHIVE_DIR is set")."""
    from ..db_models_m5 import IntDeliveryRow, IntOutboxRow, IntSettingsRow

    manifest: dict[str, Any] = {"owner_id": owner, "before": before.isoformat(), "created_at":
                                datetime.now(UTC).isoformat(), "classes": {}}
    for cls in classes:
        if cls not in CLASSES:
            raise ValueError(f"unknown class {cls!r}")
        model, col, _extra = _model(cls)
        conds = _conds(s, cls, owner, before)
        info: dict[str, Any] = {"rows": 0, "files": [], "purged": 0}
        ids: list[Any] = []
        if archive_dir:
            by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in s.execute(select(model).where(*conds).order_by(col)).scalars().yield_per(5000):
                d = _row_dict(r)
                v = getattr(r, col.key)
                by_month[(v.strftime("%Y-%m") if v else "undated")].append(d)
                ids.append(r.id)
            info["rows"] = len(ids)
            info["files"] = _write(Path(archive_dir) / owner / cls, by_month)
        if purge and cls in PURGEABLE:
            if cls == "inbox_payloads":
                n = s.execute(update(model).where(*conds).values(payload=None)
                              .execution_options(synchronize_session=False)).rowcount
            elif cls == "outbox":
                top = s.execute(select(func.max(IntOutboxRow.seq)).where(*conds)).scalar()
                if top is not None:
                    s.execute(delete(IntDeliveryRow).where(IntDeliveryRow.owner_id == owner,
                                                           IntDeliveryRow.event_seq <= top)
                              .execution_options(synchronize_session=False))
                n = s.execute(delete(model).where(*conds).execution_options(synchronize_session=False)).rowcount
                if top is not None:
                    st = s.execute(select(IntSettingsRow).where(IntSettingsRow.owner_id == owner)
                                   .with_for_update()).scalars().first()
                    if st is not None:
                        prev = int((st.sor or {}).get("_purged_through", 0) or 0)
                        st.sor = {**(st.sor or {}), "_purged_through": max(prev, int(top))}
            else:
                n = s.execute(delete(model).where(*conds).execution_options(synchronize_session=False)).rowcount
            info["purged"] = int(n or 0)
        manifest["classes"][cls] = info
    if archive_dir:
        base = Path(archive_dir) / owner
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        (base / f"manifest-{stamp}.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    s.flush()
    return manifest


def retention(s: Session, owner: str, archive_dir: str | None, now: datetime | None = None) -> dict[str, Any]:
    """The nightly defaults (7): each purgeable class older than its retention, archived first when configured."""
    now = now or datetime.now(UTC)
    out = {}
    for cls, days in PURGEABLE.items():
        out[cls] = archive(s, owner, now - timedelta(days=days), [cls], archive_dir, purge=True)["classes"][cls]
    return out


def run_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ....integration.jobs import run_duty
    from ...db.ownership import system_scope

    def fn(info: dict[str, Any]) -> dict[str, Any]:
        with system_scope(), ctx.db.write() as s:
            if info["kind"] == "trace_backfill":
                from .trace import backfill

                return backfill(s, info["owner"])
            if not info["owner"]:
                return {"skipped": "no plant"}
            return retention(s, info["owner"], ctx.settings.archive_dir)

    run_duty(ctx, run_id, lease, fn)


_ = date
