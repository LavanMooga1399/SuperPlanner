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


def due_kinds(s: Any, ctx: Any, now: Any) -> list[tuple[str, str]]:
    """(kind, owner) pairs due now; filled in S2/S3."""
    return []
