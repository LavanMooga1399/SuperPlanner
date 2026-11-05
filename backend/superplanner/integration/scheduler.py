"""Scheduled duties (M5-DESIGN 4.5, 4.6, 7): enqueue per-plant jobs; called by every worker every
`FILEDROP_POLL_SECONDS` (`jobs.worker`), serialised by a session advisory lock (only one worker schedules at a time)
and by "one active run per kind and plant" (any number of workers is safe, 8).

- `integration_filedrop` per plant with file drop on;
- `integration_delivery` per plant with an active endpoint and an undelivered event (or a due retry), and when the
  periodic file export is due (`export_interval_minutes`);
- `maintenance_retention` per plant once a day when `RETENTION_ENABLED`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

log = logging.getLogger("superplanner.integration")
LOCK_KEY = 0x5350_4D35            # "SPM5"


def due_kinds(s: Any, st: Any, now: datetime, settings: Any) -> list[str]:
    from ..api.mfg.db_models_m5 import IntDeliveryRow, IntEndpointRow, IntOutboxRow, MaintenanceRunRow
    from .jobs import active_run

    owner = st.owner_id
    out = []
    if st.enabled and st.filedrop_enabled and settings.integration_root and st.plant_code and \
            not active_run(s, "integration_filedrop", owner):
        out.append("integration_filedrop")
    if st.enabled and not active_run(s, "integration_delivery", owner):
        eps = list(s.execute(select(IntEndpointRow.cursor).where(IntEndpointRow.owner_id == owner,
                                                                 IntEndpointRow.active.is_(True))).scalars())
        top = int(s.execute(select(func.max(IntOutboxRow.seq)).where(IntOutboxRow.owner_id == owner)).scalar() or 0)
        retry = s.execute(select(IntDeliveryRow.id).where(IntDeliveryRow.owner_id == owner,
                                                          IntDeliveryRow.status == "retry").limit(1)).first()
        export_due = export_is_due(st, top, now, settings)
        if any(c < top for c in eps) or retry is not None or export_due:
            out.append("integration_delivery")
    if settings.retention_enabled and not active_run(s, "maintenance_retention", owner):
        last = s.execute(select(func.max(MaintenanceRunRow.created_at)).where(
            MaintenanceRunRow.kind == "maintenance_retention", MaintenanceRunRow.owner_scope_id == owner)).scalar()
        if last is None or _aware(last) <= now - timedelta(hours=24):
            out.append("maintenance_retention")
    return out


def export_is_due(st: Any, top: int, now: datetime, settings: Any) -> bool:
    if not (st.export_enabled and settings.integration_root and st.plant_code and top > int(st.export_cursor or 0)):
        return False
    last = (st.sor or {}).get("_exported_at")
    return not last or datetime.fromisoformat(last) <= now - timedelta(minutes=int(st.export_interval_minutes))


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def tick(ctx: Any, now: datetime | None = None, duties: set[str] | None = None) -> list[tuple[str, str]]:
    """Enqueue due duties (all, or only `duties`) -> [(kind, owner)]. Safe to call from any number of workers."""
    from ..api.db.ownership import system_scope
    from ..api.mfg.db_models_m5 import IntSettingsRow
    from .jobs import new_run

    now = now or datetime.now(UTC)
    jobs: list[Any] = []
    out: list[tuple[str, str]] = []
    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        if s.get_bind().dialect.name == "postgresql":
            got = s.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar()
            if not got:
                return []
        for st in s.execute(select(IntSettingsRow).order_by(IntSettingsRow.owner_id)).scalars():
            for kind in due_kinds(s, st, now, ctx.settings):
                if duties is not None and kind not in duties:
                    continue
                _rid, job = new_run(s, ctx, kind, st.owner_id, {})
                jobs.append(job)
                out.append((kind, st.owner_id))
    for j in jobs:
        ctx.jobs.dispatch(j)
    if out:
        log.info("scheduler: %s", ", ".join(f"{k}@{o}" for k, o in out))
    return out


__all__ = ["due_kinds", "tick"]
