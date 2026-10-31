"""Risk simulations (M4-DESIGN 8, 11 #224-226): job kind `aps_simulation`. One queued/running simulation per owner
(409 `APS_SIMULATION_IN_PROGRESS`). The job loads the base run's snapshot (its as_of and MRP run, current floor
state) and the plant's history, runs `mfg.aps.simulate.risk_run` and stores the results on the row."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....jobs.types import LeaseLost, RetryableJobError, is_transient_db_error
from ....mfg.aps.model import ApsParams
from ....mfg.aps.simulate import RiskInputs, risk_run
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.locks import is_unique_violation
from ...db.ownership import owner_scope
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo, repo_m2, repo_m3
from ..db_models import MfgLineRow
from ..db_models_m2 import (MfgInvTransactionRow, MfgMrpRunRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                            MfgPurchaseScheduleRow, MfgSupplierRow)
from ..db_models_m3 import MfgApsRunRow
from ..db_models_m4 import MfgApsSimulationRow, MfgDowntimeRow
from .common import audit, read_tx, touch, write_tx
from .m2util import actor_id, page

log = logging.getLogger(__name__)
HISTORY_DAYS = 365


def record(r: MfgApsSimulationRow, *, results: bool = True) -> dict[str, Any]:
    return {"id": r.id, "row_version": r.row_version, "created_at": as_utc(r.created_at),
            "updated_at": as_utc(r.updated_at), "base_run_id": r.base_run_id, "status": r.status, "samples": r.samples,
            "params": r.params or {}, "results": r.results if results else None, "error": r.error,
            "job_id": r.job_id, "started_at": as_utc(r.started_at), "finished_at": as_utc(r.finished_at),
            "duration_ms": r.duration_ms}


def _busy() -> ApiError:
    return ApiError(409, "APS_SIMULATION_IN_PROGRESS", "A risk simulation is queued or running; wait for it to "
                    "finish.", {})


def create_simulation(ctx: AppContext, inp: Any, idem_key: str | None) -> tuple[dict[str, Any], bool]:
    with write_tx(ctx, lock=False) as (s, _p):
        base = s.get(MfgApsRunRow, inp.base_run_id)
        if base is None:
            raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Schedule run {inp.base_run_id!r} was not found.",
                           {"loc": ["body", "base_run_id"], "id": inp.base_run_id})
        if base.status != "completed":
            raise ApiError(409, "APS_RUN_NOT_COMPLETED", f"Schedule run {base.run_no} is {base.status}.",
                           {"status": base.status})
        if s.execute(select(MfgApsSimulationRow.id).where(
                MfgApsSimulationRow.status.in_(("queued", "running")))).first() is not None:
            raise _busy()
        now = utcnow()
        row = MfgApsSimulationRow(id=new_id("asm_"), base_run_id=base.id, status="queued", samples=inp.samples,
                                  params={"seed": inp.seed, "horizon_days": inp.horizon_days,
                                          "base_run_no": base.run_no},
                                  results=None, error=None, job_id=None, cancel_requested=False, actor_id=actor_id(),
                                  started_at=None, finished_at=None, duration_ms=None, row_version=1, created_at=now,
                                  updated_at=now)
        try:
            with s.begin_nested():
                s.add(row)
                s.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc, "uq_mfg_aps_simulations_active"):
                raise _busy() from None
            raise
        job = ctx.jobs.enqueue(s, "aps_simulation", row.id, row.owner_id)
        row.job_id = job.id
        audit(s, "aps_simulation", row.id, "create", {"base_run": base.run_no, "samples": inp.samples})
        out = record(row)
    ctx.jobs.dispatch(job)
    return out, False


def list_simulations(ctx: AppContext, *, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgApsSimulationRow)).scalar() or 0)
        rows = list(s.execute(select(MfgApsSimulationRow).order_by(MfgApsSimulationRow.created_at.desc(),
                                                                   MfgApsSimulationRow.id)
                              .limit(limit).offset(offset)).scalars())
        return page([record(r, results=False) for r in rows], total, limit, offset)


def get_simulation(ctx: AppContext, simulation_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(repo.get_row(s, MfgApsSimulationRow, simulation_id, what="Simulation"))


def load_inputs(s: Session, now: Any) -> RiskInputs:
    since = (now - timedelta(days=HISTORY_DAYS)).date()
    supplier_of: dict[str, str] = {}
    for sc_id, sup in s.execute(select(MfgPurchaseScheduleRow.id, MfgPurchaseDocRow.supplier_id).join(
            MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).join(
            MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)).all():
        if sup:
            supplier_of[sc_id] = sup
    lateness: dict[str, list[int]] = {}
    for t, sc in s.execute(select(MfgInvTransactionRow, MfgPurchaseScheduleRow).join(
            MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.id == MfgInvTransactionRow.schedule_id).where(
            MfgInvTransactionRow.txn_type == "po_receipt", MfgInvTransactionRow.qty > 0,
            MfgInvTransactionRow.txn_date >= since)).all():
        sup = supplier_of.get(sc.id)
        if sup is None:
            continue
        dock = sc.confirmed_date or sc.requested_date
        lateness.setdefault(sup, []).append((t.txn_date - dock).days)
    breakdowns: dict[str, list[float]] = {}
    first: dict[str, Any] = {}
    for d in s.execute(select(MfgDowntimeRow).where(MfgDowntimeRow.planned.is_(False),
                                                    MfgDowntimeRow.end_at.is_not(None),
                                                    MfgDowntimeRow.start_at >= now - timedelta(days=HISTORY_DAYS))
                       ).scalars():
        h = (as_utc(d.end_at) - as_utc(d.start_at)).total_seconds() / 3600.0
        breakdowns.setdefault(d.line_id, []).append(round(h, 4))
        first[d.line_id] = min(first.get(d.line_id, as_utc(d.start_at)), as_utc(d.start_at))
    span = {lid: max(1.0, (now - first[lid]).total_seconds() / 3600.0) for lid in first}
    sups = {x.id: {"id": x.id, "code": x.code, "name": x.name} for x in s.execute(select(MfgSupplierRow)).scalars()}
    lines = {x.id: {"id": x.id, "code": x.code, "name": x.name} for x in s.execute(select(MfgLineRow)).scalars()}
    return RiskInputs(supplier_of, lateness, breakdowns, span, sups, lines)


def run_job(ctx: Any, sim_id: str, lease: Any) -> None:
    t0 = time.monotonic()
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            row = s.get(MfgApsSimulationRow, sim_id, with_for_update={"key_share": True})
            if row is None:
                raise LeaseLost(f"simulation {sim_id} is gone")
            lease.fence(s)
            if row.status != "queued" or row.cancel_requested:
                if row.status in ("queued", "running"):
                    row.status, row.finished_at = "failed", utcnow()
                    row.error = {"code": "APS_SIMULATION_CANCELLED", "message": "Cancelled."}
                lease.finish(s, "cancelled")
                return
            row.status, row.started_at = "running", utcnow()
            touch(row)
            owner, base_id, samples, prm = row.owner_id, row.base_run_id, row.samples, dict(row.params or {})
    except LeaseLost:
        raise
    except Exception as exc:
        if is_transient_db_error(exc):
            raise RetryableJobError(str(exc)) from exc
        raise
    try:
        with owner_scope(owner):
            with repo_m2.snapshot_tx(ctx.db) as s:
                base = s.get(MfgApsRunRow, base_id)
                if base is None:
                    raise ValueError("The base schedule run is gone.")
                params = ApsParams.model_validate({k: v for k, v in (base.params or {}).items()
                                                   if k in ApsParams.model_fields})
                mrp = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.id == base.mrp_run_id)).scalars().first() \
                    if base.mrp_run_id else None
                snap = repo_m3.load_aps_snapshot(s, as_utc(base.as_of), mrp, published=False)
                inputs = load_inputs(s, utcnow())
            res = risk_run(snap, params, inputs, samples, int(prm.get("seed") or 1), prm.get("horizon_days"),
                           cancelled=lambda: lease.cancel_event.is_set())
            with ctx.write_guard(), ctx.db.write() as s:
                row = s.get(MfgApsSimulationRow, sim_id, with_for_update={"key_share": True})
                if row is None:
                    raise LeaseLost(f"simulation {sim_id} is gone")
                lease.fence(s)
                row.results = res
                row.status, row.finished_at = "completed", utcnow()
                row.duration_ms = int((time.monotonic() - t0) * 1000)
                touch(row)
                audit(s, "aps_simulation", row.id, "complete", {"samples": res["samples_done"]})
                lease.finish(s, "succeeded")
    except LeaseLost:
        raise
    except Exception as exc:
        if is_transient_db_error(exc):
            raise RetryableJobError(str(exc)) from exc
        log.exception("simulation %s failed", sim_id)
        msg = str(exc) or exc.__class__.__name__
        with owner_scope(owner), ctx.write_guard(), ctx.db.write() as s:
            row = s.get(MfgApsSimulationRow, sim_id, with_for_update={"key_share": True})
            if row is None:
                return
            lease.fence(s)
            row.status, row.finished_at = "failed", utcnow()
            row.error = {"code": "APS_SIMULATION_FAILED", "message": msg[:500]}
            row.duration_ms = int((time.monotonic() - t0) * 1000)
            touch(row)
            lease.finish(s, "failed", msg[:500])
