"""M5 job kinds (M5-DESIGN 10): target models and handlers, resolved at call time."""

from __future__ import annotations

from typing import Any, Callable


def target_model(kind: str) -> Any:
    from ..api.mfg import db_models_m5 as m

    return {"integration_import": m.IntInboxRow, "integration_filedrop": m.MaintenanceRunRow,
            "integration_delivery": m.MaintenanceRunRow, "integration_reconcile": m.IntReconciliationRow,
            "org_publish": m.OrgPublishRow, "maintenance_retention": m.MaintenanceRunRow,
            "trace_backfill": m.MaintenanceRunRow}[kind]


def handler(kind: str) -> Callable[..., None]:
    if kind == "integration_import":
        from . import inbound

        return inbound.run_job
    if kind == "integration_delivery":
        from . import outbox

        return outbox.run_delivery_job
    if kind == "integration_reconcile":
        from . import reconcile

        return reconcile.run_job
    if kind == "integration_filedrop":
        from . import filedrop

        return filedrop.run_job
    if kind == "org_publish":
        from ..orgs import service

        return service.run_publish_job
    from ..api.mfg.services import maintenance

    return maintenance.run_job


# ---------------------------------------------------------------- duty runs (maintenance_runs rows)

def new_run(s: Any, ctx: Any, kind: str, owner_id: str, params: dict[str, Any] | None = None) -> tuple[str, Any]:
    """Insert a `maintenance_runs` row and enqueue its job in the caller's transaction -> (run id, job)."""
    from ..api.db import new_id, utcnow
    from ..api.mfg.db_models_m5 import MaintenanceRunRow

    r = MaintenanceRunRow(id=new_id("mnt_"), kind=kind, owner_scope_id=owner_id, status="queued",
                          params=dict(params or {}), results=None, created_at=utcnow(), finished_at=None)
    s.add(r)
    s.flush()
    return r.id, ctx.jobs.enqueue(s, kind, r.id, owner_id)


def active_run(s: Any, kind: str, owner_id: str) -> bool:
    from sqlalchemy import select

    from ..api.mfg.db_models_m5 import MaintenanceRunRow

    return s.execute(select(MaintenanceRunRow.id).where(MaintenanceRunRow.kind == kind,
                                                        MaintenanceRunRow.owner_scope_id == owner_id,
                                                        MaintenanceRunRow.status.in_(("queued", "running")))
                     .limit(1)).first() is not None


def run_duty(ctx: Any, run_id: str, lease: Any, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Common job body of the duty kinds: mark running, run `fn({owner, params})` bound to the run's plant (all
    plants when `owner_scope_id` is None), store `results`, finish the job in the same transaction."""
    from ..api.db import utcnow
    from ..api.db.ownership import owner_scope, system_scope
    from ..api.mfg.db_models_m5 import MaintenanceRunRow
    from ..jobs.types import LeaseLost

    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MaintenanceRunRow, run_id, with_for_update=True)
        if r is None:
            raise LeaseLost(f"run {run_id} is gone")
        lease.fence(s)
        r.status = "running"
        info = {"owner": r.owner_scope_id, "params": dict(r.params or {}), "kind": r.kind}
    status, err, res = "completed", None, None
    try:
        if info["owner"]:
            with owner_scope(info["owner"]):
                res = fn(info)
        else:
            with system_scope():
                res = fn(info)
    except LeaseLost:
        raise
    except Exception as exc:
        status, err = "failed", f"{exc.__class__.__name__}: {exc}"[:500]
        res = {"error": err}
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MaintenanceRunRow, run_id, with_for_update=True)
        if r is None:
            raise LeaseLost(f"run {run_id} is gone")
        from ..api.mfg.services.common import jsonable

        r.status, r.results, r.finished_at = status, jsonable(res), utcnow()
        lease.finish(s, "succeeded" if status == "completed" else "failed", err)
