"""Bulk actions on the main lists (docs/UX-STANDARD.md "Backend support").

Each bulk action calls the existing single-record service function once per id - same rule checks (state machine,
self-approval, shortage override, integration ownership), same If-Match (`row_version` per entry), same audit event
and outbox message, one transaction per record. A failing record never rolls back the others; the response lists
every record's outcome in request order. The route permission is the single call's permission.

Idempotency-Key (optional, per plant and acting user, 24 h): the first request stores a `running` row in
`mfg_bulk_requests`, then the final response; a retry with the same key and body replays the stored response
(`Idempotent-Replay: true`), a different body is 409 `INV_IDEMPOTENCY_CONFLICT`, a retry while the first request is
still running is 409 `MFG_BULK_IN_PROGRESS` (Retry-After 5; a `running` row older than 10 minutes is taken over).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ...db import new_id
from ...context import AppContext
from ...errors import ApiError
from ..db_models_ux import MfgBulkRequestRow
from . import demand, purchasing, workorders
from .common import write_tx
from .m2util import actor_id, request_hash

log = logging.getLogger(__name__)

MAX_BULK = 200
STALE_RUNNING = timedelta(minutes=10)

Single = Callable[[AppContext, str, str], dict[str, Any]]   # (ctx, id, if_match) -> record

#: action name -> the permission of the single call (and of the bulk route)
ACTIONS: dict[str, str] = {
    "work-orders/release": "wo_edit", "work-orders/close": "wo_edit", "work-orders/cancel": "wo_edit",
    "purchase-requests/submit": "pr_edit", "purchase-requests/approve": "pr_approve",
    "purchase-requests/reject": "pr_approve", "purchase-orders/cancel": "po_edit",
    "demand-orders/close": "demand_edit", "demand-orders/cancel": "demand_edit",
}


def single_call(action: str, params: dict[str, Any]) -> Single:
    coll, act = action.split("/")
    if coll == "work-orders":
        if act == "release":
            return lambda ctx, i, im: workorders.action(ctx, i, "release", im, reserve=bool(params.get("reserve")),
                                                        override_reason=params.get("override_reason"))
        return lambda ctx, i, im: workorders.action(ctx, i, act, im)
    if coll == "purchase-requests":
        return lambda ctx, i, im: purchasing.action(ctx, "pr", i, act, im, reason=params.get("reason"))
    if coll == "purchase-orders":
        return lambda ctx, i, im: purchasing.action(ctx, "po", i, act, im)
    if coll == "demand-orders":
        return lambda ctx, i, im: demand.action(ctx, i, act, im)
    raise KeyError(action)  # pragma: no cover


def _result(rid: str, rec: dict[str, Any] | None = None, err: ApiError | None = None) -> dict[str, Any]:
    if err is None:
        assert rec is not None
        return {"id": rid, "ok": True, "status": 200, "code": None, "message": None,
                "row_version": rec.get("row_version"), "record_status": rec.get("status"), "details": None}
    cur = err.details.get("current_version") if isinstance(err.details, dict) else None
    return {"id": rid, "ok": False, "status": err.status, "code": err.code, "message": err.message,
            "row_version": cur, "record_status": None, "details": err.details or None}


def run_items(ctx: AppContext, action: str, items: list[tuple[str, int]], params: dict[str, Any]) -> dict[str, Any]:
    call = single_call(action, params)
    results = []
    for rid, version in items:
        try:
            results.append(_result(rid, call(ctx, rid, f'"{version}"')))
        except ApiError as e:
            results.append(_result(rid, err=e))
        except Exception:  # noqa: BLE001 - one record's crash must not hide the others' outcomes
            log.exception("bulk.record_failed", extra={"action": action, "record_id": rid})
            results.append(_result(rid, err=ApiError(500, "INTERNAL_ERROR", "This record could not be processed; "
                                                     "try it on its own.")))
    ok = sum(1 for r in results if r["ok"])
    return {"action": action, "total": len(results), "succeeded": ok, "failed": len(results) - ok,
            "results": results}


def _in_progress() -> ApiError:
    return ApiError(409, "MFG_BULK_IN_PROGRESS", "This bulk action is still running. Try again in a moment.", {},
                    headers={"Retry-After": "5"})


def _claim(ctx: AppContext, key: str, action: str, h: str) -> tuple[str, dict[str, Any] | None]:
    """(row id, stored response to replay or None). Raises 409 on conflict / in progress."""
    now = datetime.now(UTC)
    me = actor_id()
    ttl = timedelta(hours=int(getattr(ctx.settings, "idempotency_ttl_hours", 24) or 24))
    B = MfgBulkRequestRow
    try:
        with write_tx(ctx, lock=False) as (s, _):
            s.execute(delete(B).where(B.created_at < now - ttl).execution_options(synchronize_session=False))
            row = s.execute(select(B).where(B.actor_id == me, B.idempotency_key == key).with_for_update()
                            ).scalars().first()
            if row is None:
                row = B(id=new_id("blk_"), actor_id=me, idempotency_key=key, action=action, request_hash=h,
                        status="running", response=None, created_at=now, updated_at=now)
                s.add(row)
                s.flush()
                return row.id, None
            if row.action != action or row.request_hash != h:
                raise ApiError(409, "INV_IDEMPOTENCY_CONFLICT", "This Idempotency-Key was already used for another "
                               "request.", {"action": row.action})
            if row.status == "done":
                return row.id, row.response
            if row.updated_at > now - STALE_RUNNING:
                raise _in_progress()
            row.updated_at = now           # the first attempt died; take over (records already done now fail 412)
            return row.id, None
    except IntegrityError:
        raise _in_progress() from None


def _finish(ctx: AppContext, row_id: str, response: dict[str, Any]) -> None:
    with write_tx(ctx, lock=False) as (s, _):
        row = s.execute(select(MfgBulkRequestRow).where(MfgBulkRequestRow.id == row_id).with_for_update()
                        ).scalars().first()
        if row is not None:
            row.status, row.response, row.updated_at = "done", response, datetime.now(UTC)


def run(ctx: AppContext, action: str, body: dict[str, Any], idem: str | None) -> tuple[dict[str, Any], bool]:
    """(response, replayed). `body` is the validated request (`items` + action parameters)."""
    items = [(x["id"], int(x["row_version"])) for x in body["items"]]
    params = {k: v for k, v in body.items() if k != "items"}
    if not idem:
        return run_items(ctx, action, items, params), False
    row_id, stored = _claim(ctx, idem, action, request_hash({"action": action, **body}))
    if stored is not None:
        return stored, True
    out = run_items(ctx, action, items, params)
    _finish(ctx, row_id, out)
    return out, False
