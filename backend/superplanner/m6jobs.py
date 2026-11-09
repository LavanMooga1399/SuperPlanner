"""M6 job kinds (M6-DESIGN 6): `push_delivery`, `digest_send`, `inventory_snapshot` - duty runs on
`maintenance_runs` (M5 15 item 1), enqueued by the M5 scheduler tick (`integration.scheduler`)."""

from __future__ import annotations

from typing import Any, Callable


def handler(kind: str) -> Callable[..., None]:
    if kind == "push_delivery":
        from .push import delivery

        return delivery.run_job
    if kind == "digest_send":
        from .notify import digests

        return digests.run_job
    if kind == "inventory_snapshot":
        from .api.mfg.services import dashboard

        return dashboard.run_snapshot_job
    raise ValueError(kind)


SNAPSHOT_LOCAL_TIME = (0, 30)          # 3.2: daily at 00:30 plant time


def due_kinds(s: Any, ctx: Any, now: Any) -> list[tuple[str, str]]:
    """(kind, owner) pairs due now (called inside the scheduler tick's transaction, system scope):
    `inventory_snapshot` per plant once a day after 00:30 plant time, `push_delivery` per plant with something new
    for its subscribers, `digest_send` per person with a due digest."""
    from sqlalchemy import select

    from .api.mfg.db_models import MfgPlantRow
    from .api.mfg.db_models_m6 import MfgInventorySnapshotRow
    from .integration.jobs import active_run
    from .mfg.tz import plant_tz

    out: list[tuple[str, str]] = []
    for p in s.execute(select(MfgPlantRow)).scalars():
        local = now.astimezone(plant_tz(p))
        if (local.hour, local.minute) >= SNAPSHOT_LOCAL_TIME and not active_run(s, "inventory_snapshot", p.owner_id):
            have = s.execute(select(MfgInventorySnapshotRow.id).where(
                MfgInventorySnapshotRow.owner_id == p.owner_id, MfgInventorySnapshotRow.day == local.date())
                .limit(1)).first()
            if have is None and not _ran_today(s, p.owner_id, local.date(), plant_tz(p)):
                out.append(("inventory_snapshot", p.owner_id))
        if ctx.settings.push_enabled and not active_run(s, "push_delivery", p.owner_id):
            from .push import delivery

            if delivery.is_due(s, ctx, p.owner_id, now):
                out.append(("push_delivery", p.owner_id))
    if ctx.settings.smtp_enabled:
        from .notify import digests

        for uid in digests.due_users(s, now):
            if not active_run(s, "digest_send", uid):
                out.append(("digest_send", uid))
    return out


def _ran_today(s: Any, owner: str, day: Any, tz: Any) -> bool:
    """An empty plant writes no snapshot rows: one run per local day is enough."""
    from sqlalchemy import func, select

    from .api.mfg.db_models_m5 import MaintenanceRunRow

    last = s.execute(select(func.max(MaintenanceRunRow.created_at)).where(
        MaintenanceRunRow.kind == "inventory_snapshot", MaintenanceRunRow.owner_scope_id == owner)).scalar()
    return last is not None and last.astimezone(tz).date() == day
