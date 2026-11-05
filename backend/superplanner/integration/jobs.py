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
