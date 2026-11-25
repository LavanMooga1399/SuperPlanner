"""Helpers of the M8 API tests: direct history rows, job polling, audit rows."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

from sqlalchemy import select


def owner_db(client: Any) -> Any:
    return client.app.state.ctx.db


def add_history(client: Any, item_id: str, values: list[float], start: date, source: str = "ledger",
                owner: str = "usr_local") -> None:
    from superplanner.api.db.models import new_id, utcnow
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models_m8 import MfgDemandHistoryRow
    from superplanner.mfg.forecast.history import add_periods

    with owner_scope(owner), owner_db(client).write() as s:
        for k, v in enumerate(values):
            s.add(MfgDemandHistoryRow(id=new_id("dhi_"), item_id=item_id, period_start=add_periods(start, k, "m"),
                                      bucket="m", qty=float(v), cleaned_qty=None, manual_qty=None, source=source,
                                      updated_at=utcnow()))


def wait_for(fn: Callable[[], Any], done: Callable[[Any], bool], timeout: float = 60.0) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        v = fn()
        if done(v) or time.monotonic() > deadline:
            return v
        time.sleep(0.1)


def audit_rows(client: Any, entity: str, entity_id: str | None = None, owner: str = "usr_local"
               ) -> list[dict[str, Any]]:
    from superplanner.api.db.models import AuditEventRow
    from superplanner.api.db.ownership import system_scope

    with system_scope(), owner_db(client).read() as s:
        q = select(AuditEventRow).where(AuditEventRow.entity_type == f"mfg_{entity}")
        if entity_id:
            q = q.where(AuditEventRow.entity_id == entity_id)
        return [{"action": r.action, "details": r.details, "reason": r.reason, "changes": r.changes,
                 "entity_id": r.entity_id} for r in s.execute(q.order_by(AuditEventRow.id)).scalars()]
