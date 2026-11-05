"""`integration_reconcile` job (M5-DESIGN 4.8): a queued `int_reconciliations` row whose `snapshot` holds
`{entities, records}` is computed with the same comparison as the synchronous `POST /reconciliations`."""

from __future__ import annotations

from typing import Any


def run_job(ctx: Any, rec_id: str, lease: Any) -> None:
    from types import SimpleNamespace

    from ..api.db import utcnow
    from ..api.db.ownership import owner_scope
    from ..api.mfg.db_models_m5 import IntReconciliationRow
    from ..api.mfg.services import integration as svc
    from ..api.mfg.services.common import read_tx
    from ..jobs.types import LeaseLost

    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(IntReconciliationRow, rec_id, with_for_update=True)
        if r is None:
            raise LeaseLost(f"reconciliation {rec_id} is gone")
        lease.fence(s)
        r.status = "running"
        owner, snap, ents = r.owner_id, dict(r.snapshot or {}), list(r.entities or [])
    status, err, summary, results = "completed", None, {}, {}
    try:
        with owner_scope(owner), read_tx(ctx) as s:
            maps = svc._maps(s)
            records = snap.get("records") or {}
            for ent in ents:
                fn = {"stock": svc._rec_stock, "items": svc._rec_items, "purchase_orders": svc._rec_pos}[ent]
                results[ent] = fn(s, records.get(ent, []), maps)
                results[ent]["sor_conflicts"] = []
                summary[ent] = {k: len(v) for k, v in results[ent].items()}
    except Exception as exc:
        status, err = "failed", str(exc)[:500]
    _ = SimpleNamespace
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(IntReconciliationRow, rec_id, with_for_update=True)
        if r is None:
            raise LeaseLost(f"reconciliation {rec_id} is gone")
        r.status, r.summary, r.results, r.finished_at = status, summary, results, utcnow()
        r.snapshot = {k: v for k, v in snap.items() if k != "records"}
        lease.finish(s, "succeeded" if status == "completed" else "failed", err)
