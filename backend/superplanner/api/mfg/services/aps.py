"""APS runs (M3-DESIGN 10, 11 #179-199): create (preflight, queue as job kind `aps_run`), the job handler
(snapshot -> schedule -> validate -> store, progress on the run row), list/get/update/delete/cancel/publish, manual
edits (synchronous child run) and the read views (gantt, operations, orders, demand, load, dispatch, overtime,
exceptions, bottlenecks, compare, export).

Ownership: the job handler runs in `system_scope()` (worker); it reads and writes inside `owner_scope(run.owner)`.
"""

from __future__ import annotations

import csv
import io
import logging
import threading
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....jobs import idempotency
from ....jobs.types import LeaseLost, RetryableJobError, is_transient_db_error
from ....mfg.aps.model import (APS_MAX_GANTT_BARS, APS_MAX_OPERATIONS, COPY_FIELDS, ApsParams, ApsResult,
                               PublishedOp)
from ....mfg.tz import plant_tz
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.locks import is_unique_violation
from ...db.ownership import owner_scope
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import aps_store, repo, repo_m2, repo_m3
from ..db_models import MfgGroupRow, MfgItemRow, MfgLineRow
from ..db_models_m2 import MfgMrpRunRow, MfgWoComponentRow, MfgWorkOrderRow
from ..db_models_m3 import (MfgApsExceptionRow, MfgApsLoadRow, MfgApsOpRow, MfgApsOrderRow, MfgApsOvertimeRow,
                            MfgApsRunRow, MfgWoOpProgressRow)
from .common import audit, check_version, read_tx, touch, write_tx
from .m2util import actor_id, page, run_tx, user_names

log = logging.getLogger("superplanner.mfg.aps")
RETENTION = 10
PROGRESS_EVERY = 2.0
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------- records

def _get(s: Session, run_id: str, *, lock: bool = False) -> MfgApsRunRow:
    q = select(MfgApsRunRow).where(MfgApsRunRow.id == run_id)
    if lock:
        q = q.with_for_update()
    r = s.execute(q).scalars().first()
    if r is None:
        raise not_found("Schedule run", run_id)
    return r


def _completed(s: Session, run_id: str) -> MfgApsRunRow:
    r = _get(s, run_id)
    if r.status not in ("completed", "cancelled") or r.summary is None:
        raise ApiError(409, "APS_RUN_NOT_COMPLETED", f"Schedule run {r.run_no} is {r.status}.", {"status": r.status})
    return r


def _stale(s: Session, r: MfgApsRunRow) -> dict[str, Any] | None:
    if r.status not in ("completed", "cancelled"):
        return None
    p = s.execute(select(repo.MfgPlantRow)).scalars().first()
    master = (p.data_version if p else 0) != r.data_version
    tok = repo_m3.aps_inputs_token(s)
    old = dict(r.inputs_token or {})
    tx = any(tok.get(k) != old.get(k) for k in tok if k != "data_version")
    latest = repo_m3.latest_live_mrp_run(s)
    mrp = (latest.id if latest else None) != r.mrp_run_id and r.kind == "live"
    return {"is_stale": master or tx or mrp, "master_changed": master, "transactions_changed": tx,
            "mrp_changed": mrp}


def run_record(s: Session, r: MfgApsRunRow, *, detail: bool = False, stale: bool = True) -> dict[str, Any]:
    names = user_names(s, [x for x in (r.actor_id, r.published_by) if x])
    mrp = None
    if r.mrp_run_id:
        no = s.execute(select(MfgMrpRunRow.run_no).where(MfgMrpRunRow.id == r.mrp_run_id)).scalar()
        mrp = {"id": r.mrp_run_id, "run_no": no}
    summ = r.summary
    val = r.validation
    out = {
        "id": r.id, "run_no": r.run_no, "kind": r.kind, "status": r.status, "label": r.label, "note": r.note,
        "pinned": r.pinned, "is_published": r.is_published, "published_at": as_utc(r.published_at),
        "published_by": {"id": r.published_by, "name": names.get(r.published_by, "")} if r.published_by else None,
        "parent_run_id": r.parent_run_id, "copy_of_run_id": r.copy_of_run_id, "mrp_run": mrp,
        "as_of": as_utc(r.as_of), "horizon_end": as_utc(r.horizon_end),
        "horizon_days": (r.params or {}).get("horizon_days"), "policy": (r.params or {}).get("overtime"),
        "master_fingerprint": r.master_fingerprint, "row_version": r.row_version,
        "started_at": as_utc(r.started_at), "finished_at": as_utc(r.finished_at), "duration_ms": r.duration_ms,
        "actor": {"id": r.actor_id, "name": names.get(r.actor_id, "")}, "progress": r.progress,
        "summary": summ, "score": r.score,
        "validation": {"ok": bool(val.get("ok")), "counts": val.get("counts", {})} if val else None,
        "stale": _stale(s, r) if stale else None,
        "late_demand_remains": bool(summ and summ.get("late_demand_count")),
        "publishable": r.kind == "live" and r.status == "completed" and bool(val and val.get("ok")),
        "error": r.error, "link": f"/mfg/schedule/runs/{r.id}"}
    if detail:
        out["params"] = r.params
    return out


# ---------------------------------------------------------------- create (179)

def _resolve(s: Session, body: ApsParams) -> tuple[ApsParams, str, datetime, MfgMrpRunRow | None, str | None]:
    """(stored params, kind, as_of, MRP run, copy_of id)."""
    p = s.execute(select(repo.MfgPlantRow)).scalars().first()
    if body.copy_of is not None:
        extra = set(body.model_fields_set) - COPY_FIELDS
        if extra:
            raise ApiError(422, "VALIDATION_ERROR", "With copy_of only overtime, label, note and improve_seconds may "
                           "be given.", {"errors": [{"loc": ["body", f], "msg": "not allowed with copy_of",
                                                     "type": "value_error"} for f in sorted(extra)]})
        src = _get(s, body.copy_of)
        if src.status not in ("completed", "cancelled", "failed"):
            raise ApiError(409, "APS_RUN_NOT_COMPLETED", f"Schedule run {src.run_no} is {src.status}.",
                           {"status": src.status})
        base = ApsParams.model_validate({k: v for k, v in (src.params or {}).items() if k in ApsParams.model_fields})
        upd = {f: getattr(body, f) for f in ("overtime", "label", "note", "improve_seconds")
               if f in body.model_fields_set}
        if "label" not in upd:
            upd["label"] = f"{base.label or f'Run {src.run_no}'} ({(upd.get('overtime') or base.overtime or '')})"[:100]
        params = base.model_copy(update={**upd, "edits": [], "copy_of": None})
        mrp = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.id == src.mrp_run_id)).scalars().first() \
            if src.mrp_run_id else None
        return params, src.kind, as_utc(src.as_of), mrp, src.id
    if body.edits:
        raise ApiError(422, "VALIDATION_ERROR", "Edits are made with POST /aps/runs/{id}/edits.",
                       {"errors": [{"loc": ["body", "edits"], "msg": "use the edits endpoint", "type": "value_error"}]})
    from ....mfg.aps.pure import round_up_minute

    as_of = round_up_minute(body.as_of or datetime.now(UTC))
    params = body.model_copy(update={
        "horizon_days": body.horizon_days or (p.aps_horizon_days if p else 42),
        "overtime": body.overtime or (p.aps_overtime_policy if p else "suggest")})
    if body.mrp_run_id is not None:
        mrp = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.id == body.mrp_run_id)).scalars().first()
        if mrp is None or mrp.status != "completed":
            raise ApiError(422, "APS_NO_MRP_RUN", "The MRP run was not found or has not completed.",
                           {"loc": ["body", "mrp_run_id"], "mrp_run_id": body.mrp_run_id})
    else:
        mrp = repo_m3.latest_live_mrp_run(s)
    if mrp is None and (params.include_planned or params.material == "strict"):
        raise ApiError(422, "APS_NO_MRP_RUN", "Run MRP first: the schedule needs the planned orders and the "
                       "component pegging of a completed MRP run (or set include_planned false and material "
                       "ignore).", {})
    from ....mfg.aps.engine import run_kind

    return params, run_kind(params, mrp.kind if mrp else None), as_of, mrp, None


def _preflight(s: Session, params: ApsParams, mrp: MfgMrpRunRow | None, as_of: datetime) -> tuple[str, int]:
    """Gate 1 health + APS preflight (10). Returns (fingerprint, data_version)."""
    from ....mfg.dataset import fingerprint
    from ....mfg.health import run_health_check
    from ....mfg.routing import eligible_lines
    from ..db_models_m2 import MfgMrpPlannedOrderRow

    ds = repo.load_dataset(s)
    today = as_of.astimezone(plant_tz(ds.plant)).date()
    report = run_health_check(ds, today, int(params.horizon_days or 42))
    if not report.ok:
        raise ApiError(422, "MFG_DATA_HEALTH_FAILED", "The data health check has errors; fix them before "
                       "scheduling.", {"report": report.model_dump(mode="json")})
    issues: list[dict[str, Any]] = []
    n_ops = 0
    wos = list(s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.status.in_(
        ("planned", "released", "in_progress")))).scalars())
    from ....mfg.aps.pure import wo_routing_id

    orders: list[tuple[str, str, str | None]] = [
        (w.number, w.item_id, wo_routing_id(ds, w.item_id, w.start_date, w.serial_from, w.routing_id)) for w in wos]
    if mrp is not None and params.include_planned:
        for no, iid, rid in s.execute(select(MfgMrpPlannedOrderRow.planned_no, MfgMrpPlannedOrderRow.item_id,
                                             MfgMrpPlannedOrderRow.routing_id).where(
                MfgMrpPlannedOrderRow.run_id == mrp.id, MfgMrpPlannedOrderRow.kind == "make",
                MfgMrpPlannedOrderRow.status == "open")).all():
            orders.append((f"P-{no}", iid, rid))
    checked: set[tuple[str, str]] = set()
    for num, iid, rid in orders:
        rt = ds.routings.get(rid) if rid else None
        if rt is None:
            if num.startswith("P-"):
                continue
            issues.append({"code": "APS_NO_ROUTING", "order": num, "message": f"{num} has no effective routing."})
            continue
        n_ops += len(rt.operations)
        it = ds.items.get(iid)
        for op in rt.operations:
            k = (op.group_id, iid)
            if k in checked or it is None:
                continue
            checked.add(k)
            if not eligible_lines(ds, op.group_id, it):
                g = ds.groups.get(op.group_id)
                issues.append({"code": "APS_NO_ELIGIBLE_LINE", "order": num,
                               "message": f"{it.part_number} operation {op.seq}: stage {g.code if g else '?'} has no "
                                          "eligible active line."})
    if n_ops > APS_MAX_OPERATIONS:
        raise ApiError(422, "APS_TOO_LARGE", f"The plan has {n_ops:,} operations; the limit is "
                       f"{APS_MAX_OPERATIONS:,}. Shorten the horizon or exclude planned orders.",
                       {"operations": n_ops, "limit": APS_MAX_OPERATIONS})
    if issues:
        raise ApiError(422, "APS_PREFLIGHT_FAILED", f"{len(issues)} problem(s) prevent scheduling.",
                       {"issues": issues[:200]})
    return fingerprint(ds), ds.plant.data_version


def _created_from_job(s: Session, job: Any) -> dict[str, Any]:
    run = s.get(MfgApsRunRow, job.aps_run_id) if getattr(job, "aps_run_id", None) else None
    if run is None:
        raise idempotency._mismatch()
    return run_record(s, run, stale=False)


def create_run(ctx: AppContext, body: ApsParams, idem_key: str | None) -> tuple[dict[str, Any], bool]:
    idem = idempotency.Idempotency(idem_key, idempotency.request_hash("aps_run", {}, body.model_dump(mode="json"))) \
        if idem_key else None
    try:
        return _create_run(ctx, body, idem), False
    except idempotency.Replay as rp:
        return rp.body, True
    except IntegrityError as exc:
        if idem is not None and idempotency.is_key_conflict(exc):
            try:
                idempotency.replay_after_conflict(ctx, idem, _created_from_job)
            except idempotency.Replay as rp:
                return rp.body, True
        raise


def _create_run(ctx: AppContext, body: ApsParams, idem: Any) -> dict[str, Any]:
    actor = actor_id()
    with write_tx(ctx, lock=False) as (s, _p):
        if idem is not None:
            idempotency.lookup(s, idem, ctx.settings.idempotency_ttl_hours, _created_from_job)
        params, kind, as_of, mrp, copy_of = _resolve(s, body)
        active = s.execute(select(MfgApsRunRow.run_no).where(MfgApsRunRow.status.in_(("queued", "running")))).first()
        if active is not None:
            raise _in_progress(active[0])
        fp, dv = _preflight(s, params, mrp, as_of)
        n = int(s.execute(select(func.coalesce(func.max(MfgApsRunRow.run_no), 0))).scalar() or 0) + 1
        now = utcnow()
        run = MfgApsRunRow(
            id=new_id("apr_"), run_no=n, kind=kind, status="queued", label=params.label, note=params.note,
            pinned=False, is_published=False, published_at=None, published_by=None, parent_run_id=None,
            copy_of_run_id=copy_of, mrp_run_id=mrp.id if mrp else None, params=params.model_dump(mode="json"),
            as_of=as_of, horizon_end=as_of + timedelta(days=int(params.horizon_days or 42)), master_fingerprint=fp,
            data_version=dv, inputs_token=repo_m3.aps_inputs_token(s), job_id=None, cancel_requested=False,
            progress={"phase": "queued", "percent": 0, "best_score": None, "updated_at": now.isoformat()},
            summary=None, score=None, validation=None, extras=None, error=None, actor_id=actor, started_at=None,
            finished_at=None, duration_ms=None, row_version=1, created_at=now, updated_at=now)
        try:
            with s.begin_nested():
                s.add(run)
                s.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc, "uq_mfg_aps_runs_active") or is_unique_violation(exc, "uq_mfg_aps_runs_no"):
                raise _in_progress(None) from None
            raise
        job = ctx.jobs.enqueue(s, "aps_run", run.id, run.owner_id, idempotency_key=idem.key if idem else None,
                               request_hash=idem.request_hash if idem else None)
        run.job_id = job.id
        audit(s, "aps_run", run.id, "create", {"run_no": n, "kind": kind, "policy": params.overtime,
                                               **({"copy_of": copy_of} if copy_of else {})})
        out = run_record(s, run, stale=False)
    ctx.jobs.dispatch(job)
    return out


def _in_progress(no: int | None) -> ApiError:
    return ApiError(409, "APS_RUN_IN_PROGRESS", "A schedule run is queued or running for this plant; wait for it "
                    "to finish or cancel it." if no is None else f"Schedule run {no} is queued or running; wait for "
                    "it to finish or cancel it.", {"run_no": no})


# ---------------------------------------------------------------- job (aps_run)

class _Progress:
    def __init__(self, ctx: Any, run_id: str, owner: str, lease: Any):
        self.ctx, self.run_id, self.owner, self.lease = ctx, run_id, owner, lease
        self.last = 0.0

    def __call__(self, phase: str, percent: float, best: list[float] | None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last < PROGRESS_EVERY:
            return
        self.last = now
        try:
            with owner_scope(self.owner), self.ctx.write_guard(), self.ctx.db.write() as s:
                r = s.get(MfgApsRunRow, self.run_id, with_for_update={"key_share": True})
                if r is None:
                    return
                self.lease.fence(s)
                r.progress = {"phase": phase, "percent": round(percent, 1), "best_score": best,
                              "updated_at": utcnow().isoformat()}
        except LeaseLost:
            raise
        except Exception:   # pragma: no cover - progress is best effort
            log.debug("progress write failed", exc_info=True)


def _parents(snap: Any, res: ApsResult) -> dict[str, str]:
    """child order id -> parent order id (pegging), for the order Gantt."""
    out: dict[str, str] = {}
    if snap.mrp is None:
        return out
    planned_id = {str(p.planned_no): p.id for p in snap.mrp.planned}
    for (ptype, pid, _item), sups in snap.mrp.pegs.items():
        parent = pid if ptype == "wo" else planned_id.get(pid)
        if parent is None:
            continue
        for x in sups:
            child = x.ref_id if x.kind in ("work_order", "wo") else (
                planned_id.get(str(x.planned_no if x.planned_no is not None else x.ref_id)) if x.kind == "planned"
                else None)
            if child:
                out.setdefault(child, parent)
    return out


def _snapshot(ctx: Any, s: Session, r: MfgApsRunRow, params: ApsParams, **kw: Any) -> Any:
    mrp = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.id == r.mrp_run_id)).scalars().first() \
        if r.mrp_run_id else None
    return repo_m3.load_aps_snapshot(s, as_utc(r.as_of), mrp, **kw)


def run_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ....mfg.aps.engine import schedule

    t0 = time.monotonic()
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            run = s.get(MfgApsRunRow, run_id, with_for_update={"key_share": True})
            if run is None:
                raise LeaseLost(f"APS run {run_id} is gone")
            lease.fence(s)
            if run.status != "queued" or run.cancel_requested:
                if run.status in ("queued", "running"):
                    run.status, run.finished_at = "cancelled", utcnow()
                lease.finish(s, "cancelled" if run.status == "cancelled" else "succeeded")
                return
            run.status = "running"
            run.started_at = run.started_at or utcnow()
            run.progress = {"phase": "load", "percent": 1, "best_score": None, "updated_at": utcnow().isoformat()}
            owner = run.owner_id
            params = ApsParams.model_validate(run.params)
    except LeaseLost:
        raise
    except Exception as exc:
        if is_transient_db_error(exc):
            raise RetryableJobError(str(exc)) from exc
        raise
    prog = _Progress(ctx, run_id, owner, lease)
    try:
        with owner_scope(owner):
            t1 = time.monotonic()
            with repo_m2.snapshot_tx(ctx.db) as s:
                run = s.get(MfgApsRunRow, run_id)
                snap = _snapshot(ctx, s, run, params)
            load_ms = int((time.monotonic() - t1) * 1000)
            prog("construct", 5, None, force=True)
            res = schedule(snap, params, prog, lambda: lease.cancel_event.is_set())
            res.summary.timings_ms["load"] = load_ms
            parents = _parents(snap, res)
            prog("store", 95, list(res.score), force=True)
            t2 = time.monotonic()
            with ctx.write_guard(), ctx.db.write() as s:
                run = s.get(MfgApsRunRow, run_id, with_for_update={"key_share": True})
                if run is None:
                    raise LeaseLost(f"APS run {run_id} is gone")
                lease.fence(s)
                res.summary.timings_ms["store"] = 0
                aps_store.store(s, run, res, parents)
                run.status = "cancelled" if run.cancel_requested else "completed"
                run.finished_at = utcnow()
                run.duration_ms = int((time.monotonic() - t0) * 1000)
                store_ms = int((time.monotonic() - t2) * 1000)
                summ = dict(run.summary)
                summ["timings_ms"] = {**summ.get("timings_ms", {}), "store": store_ms}
                run.summary = summ
                run.progress = {"phase": "done", "percent": 100, "best_score": list(res.score),
                                "updated_at": utcnow().isoformat()}
                touch(run)
                audit(s, "aps_run", run.id, "complete", {"run_no": run.run_no, "status": run.status,
                                                         "validation_ok": res.validation.ok})
                _retention(s)
                lease.finish(s, "succeeded" if run.status == "completed" else "cancelled")
    except LeaseLost:
        raise
    except Exception as exc:
        if is_transient_db_error(exc):
            raise RetryableJobError(str(exc)) from exc
        log.exception("APS run %s failed", run_id)
        msg = str(exc) or exc.__class__.__name__
        with owner_scope(owner), ctx.write_guard(), ctx.db.write() as s:
            run = s.get(MfgApsRunRow, run_id, with_for_update={"key_share": True})
            if run is None:
                return
            lease.fence(s)
            run.status, run.finished_at = "failed", utcnow()
            run.error = {"code": "APS_RUN_FAILED", "message": msg[:500]}
            run.duration_ms = int((time.monotonic() - t0) * 1000)
            touch(run)
            audit(s, "aps_run", run.id, "fail", {"run_no": run.run_no})
            lease.finish(s, "failed", msg[:500])


def _retention(s: Session) -> None:
    """Keep the 10 newest unpinned finished runs; the published run and the parents of kept runs survive."""
    runs = list(s.execute(select(MfgApsRunRow.id, MfgApsRunRow.pinned, MfgApsRunRow.is_published,
                                 MfgApsRunRow.parent_run_id, MfgApsRunRow.status)
                          .order_by(MfgApsRunRow.run_no.desc())).all())
    keep_parents = {r.parent_run_id for r in runs if r.parent_run_id}
    n = 0
    drop = []
    for r in runs:
        if r.status in ("queued", "running") or r.pinned or r.is_published or r.id in keep_parents:
            continue
        n += 1
        if n > RETENTION:
            drop.append(r.id)
    for rid in drop:
        row = s.get(MfgApsRunRow, rid)
        if row is not None:
            audit(s, "aps_run", rid, "delete", {"reason": "retention"})
            s.delete(row)
    s.flush()


def recover_interrupted_runs(ctx: Any) -> int:
    """Inline mode: every queued/running APS run -> failed (+ its job), as the other run kinds."""
    from ....jobs import common as job_common
    from ....jobs.types import RESTART_ERROR
    from ...db.ownership import system_scope

    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        runs = list(s.scalars(select(MfgApsRunRow).where(MfgApsRunRow.status.in_(("queued", "running")))).all())
        now = utcnow()
        for run in runs:
            run.status = "failed"
            run.error = {"code": "APS_RESTARTED", "message": RESTART_ERROR}
            run.finished_at = now
        job_common.mark_jobs_failed(s, "aps_run", [r.id for r in runs], RESTART_ERROR)
        return len(runs)


# ---------------------------------------------------------------- list / get / update / delete / cancel / publish

def list_runs(ctx: AppContext, *, kind: str | None, status: str | None, pinned: bool | None, limit: int,
              offset: int) -> dict[str, Any]:
    conds = []
    if kind:
        conds.append(MfgApsRunRow.kind == kind)
    if status:
        conds.append(MfgApsRunRow.status == status)
    if pinned is not None:
        conds.append(MfgApsRunRow.pinned.is_(pinned))
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgApsRunRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgApsRunRow).where(*conds).order_by(MfgApsRunRow.run_no.desc())
                              .limit(limit).offset(offset)).scalars())
        return page([run_record(s, r, stale=False) for r in rows], total, limit, offset)


def published_run(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
        if r is None:
            raise ApiError(404, "NOT_FOUND", "No schedule is published.", {"id": "published"})
        return run_record(s, r, detail=True)


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return run_record(s, _get(s, run_id), detail=True)


def update_run(ctx: AppContext, run_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, run_id, lock=True)
        check_version(r, if_match)
        if body.label is not None:
            r.label = body.label
        if body.note is not None:
            r.note = body.note
        if body.pinned is not None:
            r.pinned = body.pinned
        touch(r)
        s.flush()
        audit(s, "aps_run", r.id, "update", {"version": r.row_version})
        return run_record(s, r, detail=True)

    return run_tx(ctx, fn)


def delete_run(ctx: AppContext, run_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        r = _get(s, run_id, lock=True)
        check_version(r, if_match)
        if r.is_published:
            raise ApiError(409, "MFG_IN_USE", f"Schedule run {r.run_no} is published; publish another run first.",
                           {"references": {"published": 1}})
        if r.status in ("queued", "running"):
            raise ApiError(409, "APS_RUN_IN_PROGRESS", f"Schedule run {r.run_no} is {r.status}; cancel it first.",
                           {"run_no": r.run_no})
        audit(s, "aps_run", r.id, "delete", {"run_no": r.run_no})
        s.delete(r)
        s.flush()

    run_tx(ctx, fn)


def cancel_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, run_id, lock=True)
        if r.status not in ("queued", "running"):
            raise ApiError(409, "APS_RUN_NOT_COMPLETED" if r.status == "completed" else "MFG_INVALID_STATE",
                           f"Schedule run {r.run_no} has already finished ({r.status}).", {"status": r.status})
        r.cancel_requested = True
        if r.status == "queued":
            r.status, r.finished_at = "cancelled", utcnow()
        ctx.jobs.request_cancel(s, "aps_run", r.id)
        touch(r)
        audit(s, "aps_run", r.id, "cancel", {"run_no": r.run_no})
        return run_record(s, r, detail=True)

    out = run_tx(ctx, fn)
    ctx.jobs.notify_cancel(run_id)
    return out


def publish_run(ctx: AppContext, run_id: str, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get(s, run_id, lock=True)
        check_version(r, if_match)
        ok = r.kind == "live" and r.status == "completed" and bool(r.validation and r.validation.get("ok"))
        if not ok:
            why = "a what-if run" if r.kind != "live" else (f"{r.status}" if r.status != "completed" else
                                                             "not validator-clean")
            raise ApiError(409, "APS_NOT_PUBLISHABLE", f"Schedule run {r.run_no} cannot be published ({why}).",
                           {"kind": r.kind, "status": r.status})
        if r.is_published:
            return run_record(s, r, detail=True)
        for old in s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))
                             .with_for_update()).scalars():
            old.is_published = False
            touch(old)
        s.flush()
        r.is_published, r.published_at, r.published_by = True, utcnow(), actor_id()
        touch(r)
        s.flush()
        audit(s, "aps_run", r.id, "publish", {"run_no": r.run_no})
        return run_record(s, r, detail=True)

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- edits (187)

def create_edits(ctx: AppContext, run_id: str, body: Any) -> dict[str, Any]:
    from ....mfg.aps.construct import EditInfeasible
    from ....mfg.aps.engine import schedule

    actor = actor_id()
    with read_tx(ctx) as s:
        parent = _completed(s, run_id)
        from types import SimpleNamespace

        cols = ("op_no", "order_type", "order_id", "seq", "split_index", "line_id", "status", "locked", "frozen")
        rows = {r.op_no: SimpleNamespace(**{c: getattr(r, c) for c in cols}, pub=repo_m3.published_op(r))
                for r in s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == parent.id)).scalars()}
        pparams = ApsParams.model_validate(parent.params)
        parent_no = parent.run_no
    key = lambda r: (r.order_type, r.order_id, r.seq, r.split_index)  # noqa: E731
    locked: dict[tuple[str, str, int, int], PublishedOp] = {key(r): r.pub for r in rows.values()
                                                             if r.locked and r.status == "scheduled"}
    moves: dict[tuple[str, str, int, int], tuple[str | None, datetime | None]] = {}
    reseq: list[tuple[str, tuple[tuple[str, str, int], ...]]] = []
    for i, e in enumerate(body.edits):
        nos = e.op_nos if e.kind == "resequence" else [e.op_no]
        for n in nos:
            r = rows.get(n)
            if r is None:
                raise ApiError(422, "APS_UNKNOWN_OPERATION", f"Operation {n} is not in schedule run "
                               f"{parent_no}.", {"loc": ["body", "edits", i], "op_no": n})
            if r.frozen and not body.override_freeze and e.kind in ("move", "resequence"):
                raise ApiError(422, "APS_EDIT_FROZEN", f"Operation {n} is frozen (published, inside the freeze "
                               "window); set override_freeze to move it.", {"loc": ["body", "edits", i], "op_no": n})
        if e.kind == "lock":
            r = rows[e.op_no]
            if r.status == "scheduled":
                locked[key(r)] = r.pub
        elif e.kind == "unlock":
            locked.pop(key(rows[e.op_no]), None)
        elif e.kind == "move":
            r = rows[e.op_no]
            locked.pop(key(r), None)
            moves[key(r)] = (e.line_id or r.line_id, e.start)
        else:
            reseq.append((e.line_id, tuple((rows[n].order_type, rows[n].order_id, rows[n].seq) for n in e.op_nos)))
            for n in e.op_nos:
                locked.pop(key(rows[n]), None)
    params = pparams.model_copy(update={"edits": list(pparams.edits) + list(body.edits), "improve_seconds": 0})
    t0 = time.monotonic()
    with repo_m2.snapshot_tx(ctx.db) as s:
        parent = _get(s, run_id)
        snap = _snapshot(ctx, s, parent, params, published=not body.override_freeze, edits=tuple(body.edits),
                         locked=locked, override_freeze=body.override_freeze, moves=moves, resequence=tuple(reseq))
    try:
        res = schedule(snap, params)
    except EditInfeasible as ex:
        raise ApiError(422, "APS_EDIT_INFEASIBLE", f"The edit breaks a hard constraint: {ex.message}",
                       {"violations": [{"code": ex.code, "op_no": None, "message": ex.message, "refs": {}}]}) from None
    if not res.validation.ok:
        raise ApiError(422, "APS_EDIT_INFEASIBLE", f"The edit breaks {len(res.validation.violations)} hard "
                       "constraint(s).", {"violations": [v.model_dump(mode="json")
                                                         for v in res.validation.violations[:50]]})
    parents = _parents(snap, res)

    def fn(s: Session) -> dict[str, Any]:
        p = _get(s, run_id, lock=True)
        n = int(s.execute(select(func.coalesce(func.max(MfgApsRunRow.run_no), 0))).scalar() or 0) + 1
        now = utcnow()
        run = MfgApsRunRow(
            id=new_id("apr_"), run_no=n, kind=p.kind, status="completed", label=f"{p.label or f'Run {p.run_no}'} "
            "(edited)"[:100], note=p.note, pinned=False, is_published=False, published_at=None, published_by=None,
            parent_run_id=p.id, copy_of_run_id=None, mrp_run_id=p.mrp_run_id, params=params.model_dump(mode="json"),
            as_of=p.as_of, horizon_end=p.horizon_end, master_fingerprint=p.master_fingerprint,
            data_version=p.data_version, inputs_token=p.inputs_token, job_id=None, cancel_requested=False,
            progress={"phase": "done", "percent": 100, "best_score": list(res.score), "updated_at": now.isoformat()},
            summary=None, score=None, validation=None, extras=None, error=None, actor_id=actor, started_at=now,
            finished_at=now, duration_ms=int((time.monotonic() - t0) * 1000), row_version=1, created_at=now,
            updated_at=now)
        s.add(run)
        s.flush()
        aps_store.store(s, run, res, parents)
        audit(s, "aps_run", run.id, "edit", {"run_no": n, "parent_run_id": p.id, "edits": len(body.edits)})
        return run_record(s, run, detail=True)

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- views

def _refs(s: Session) -> dict[str, Any]:
    items = {r.id: {"id": r.id, "part_number": r.part_number, "revision": r.revision, "description": r.description,
                    "uom": r.uom, "make_buy": r.make_buy, "active": r.active}
             for r in s.execute(select(MfgItemRow)).scalars()}
    return {"items": items, "lines": {r.id: r for r in s.execute(select(MfgLineRow)).scalars()},
            "groups": {r.id: r for r in s.execute(select(MfgGroupRow)).scalars()}}


def _ops(s: Session, run_id: str, *conds: Any) -> list[MfgApsOpRow]:
    return list(s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == run_id, *conds)
                          .order_by(MfgApsOpRow.op_no)).scalars())


def operations(ctx: AppContext, run_id: str, *, line_id: str | None, group_id: str | None, order_id: str | None,
               status: str | None, late_only: bool, frozen: bool | None, frm: datetime | None, to: datetime | None,
               sort: str, limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if line_id:
        conds.append(MfgApsOpRow.line_id == line_id)
    if group_id:
        conds.append(MfgApsOpRow.group_id == group_id)
    if order_id:
        conds.append(MfgApsOpRow.order_id == order_id)
    if status:
        conds.append(MfgApsOpRow.status == status)
    if late_only:
        conds.append(MfgApsOpRow.late_minutes > 0)
    if frozen is not None:
        conds.append(MfgApsOpRow.frozen.is_(frozen))
    if frm is not None:
        conds.append(MfgApsOpRow.end_at > frm)
    if to is not None:
        conds.append(MfgApsOpRow.start_at < to)
    order = {"start": (MfgApsOpRow.start_at.asc().nulls_last(), MfgApsOpRow.op_no),
             "-late_minutes": (MfgApsOpRow.late_minutes.desc(), MfgApsOpRow.op_no),
             "op_no": (MfgApsOpRow.op_no,), "line": (MfgApsOpRow.line_id, MfgApsOpRow.start_at, MfgApsOpRow.op_no)
             }[sort]
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        total = int(s.execute(select(func.count()).select_from(MfgApsOpRow).where(MfgApsOpRow.run_id == r.id,
                                                                                 *conds)).scalar() or 0)
        rows = list(s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == r.id, *conds).order_by(*order)
                              .limit(limit).offset(offset)).scalars())
        refs = _refs(s)
        return page([aps_store.op_view(x, refs, r.id) for x in rows], total, limit, offset)


def operation(ctx: AppContext, run_id: str, op_no: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        x = s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == r.id, MfgApsOpRow.op_no == op_no)
                      ).scalars().first()
        if x is None:
            raise ApiError(404, "NOT_FOUND", f"Operation {op_no} is not in schedule run {r.run_no}.",
                           {"id": str(op_no)})
        refs = _refs(s)
        before = after = None
        if x.line_id and x.start_at is not None:
            before = s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == r.id, MfgApsOpRow.line_id == x.line_id,
                                                         MfgApsOpRow.start_at < x.start_at)
                               .order_by(MfgApsOpRow.start_at.desc(), MfgApsOpRow.op_no.desc()).limit(1)
                               ).scalars().first()
            after = s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == r.id, MfgApsOpRow.line_id == x.line_id,
                                                        MfgApsOpRow.start_at > x.start_at)
                              .order_by(MfgApsOpRow.start_at, MfgApsOpRow.op_no).limit(1)).scalars().first()
        v = aps_store.op_view(x, refs, r.id)
        return {"op": v, "reason": x.reason, "release": x.release,
                "neighbours": {"before": aps_store.op_view(before, refs, r.id) if before else None,
                               "after": aps_store.op_view(after, refs, r.id) if after else None}}


def orders(ctx: AppContext, run_id: str, *, late_only: bool, order_type: str | None, q: str | None, sort: str,
           limit: int, offset: int) -> dict[str, Any]:
    from .common import ilike

    conds: list[Any] = []
    if late_only:
        conds.append(MfgApsOrderRow.late_minutes > 0)
    if order_type:
        conds.append(MfgApsOrderRow.order_type == order_type)
    if q:
        conds.append(or_(ilike(MfgApsOrderRow.number, q), ilike(MfgApsOrderRow.part_number, q)))
    order = (MfgApsOrderRow.late_minutes.desc(), MfgApsOrderRow.number) if sort == "-late_minutes" else \
        (MfgApsOrderRow.due_at.asc().nulls_last(), MfgApsOrderRow.number)
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        total = int(s.execute(select(func.count()).select_from(MfgApsOrderRow).where(
            MfgApsOrderRow.run_id == r.id, *conds)).scalar() or 0)
        rows = s.execute(select(MfgApsOrderRow).where(MfgApsOrderRow.run_id == r.id, *conds).order_by(*order)
                         .limit(limit).offset(offset)).scalars()
        return page([aps_store.order_view(x) for x in rows], total, limit, offset)


def demand(ctx: AppContext, run_id: str, *, late_only: bool, program: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        items = [d for d in (r.extras or {}).get("demand", []) if (not late_only or d["late_minutes"] > 0) and
                 (program is None or d.get("program") == program)]
        late = sum(1 for d in items if d["late_minutes"] > 0)
        return {"items": items, "counts": {"on_time": len(items) - late, "late": late}}


def load(ctx: AppContext, run_id: str, *, group_id: str | None, line_id: str | None, bucket: str,
         frm: date | None, to: date | None) -> dict[str, Any]:
    conds: list[Any] = []
    if group_id:
        conds.append(MfgApsLoadRow.group_id == group_id)
    if line_id:
        conds.append(MfgApsLoadRow.line_id == line_id)
    elif not group_id:
        conds.append(MfgApsLoadRow.line_id.is_(None))
    if frm is not None:
        conds.append(MfgApsLoadRow.day >= frm)
    if to is not None:
        conds.append(MfgApsLoadRow.day < to)
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        rows = [aps_store.load_view(x) for x in s.execute(select(MfgApsLoadRow).where(
            MfgApsLoadRow.run_id == r.id, *conds).order_by(MfgApsLoadRow.group_id, MfgApsLoadRow.line_id,
                                                          MfgApsLoadRow.day)).scalars()]
        return {"bucket": bucket, "items": aps_store.bucket_load(rows, bucket)}


def overtime(ctx: AppContext, run_id: str, *, status: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        rows = [aps_store.overtime_view(x) for x in s.execute(select(MfgApsOvertimeRow).where(
            MfgApsOvertimeRow.run_id == r.id).order_by(MfgApsOvertimeRow.start_at, MfgApsOvertimeRow.line_id))
            .scalars()]
        lines = {x.id: x.code for x in s.execute(select(MfgLineRow)).scalars()}
    for x in rows:
        x["line"] = {"id": x["line_id"], "code": lines.get(x["line_id"], "")}
    sel = [x for x in rows if status is None or x["status"] == status]
    op = [x for x in rows if x["status"] != "suggested"]
    sg = [x for x in rows if x["status"] == "suggested"]
    return {"items": sel, "totals": {
        "opened_minutes": sum(x["minutes"] for x in op), "opened_cost": round(sum(x["cost"] for x in op), 2),
        "suggested_minutes": sum(x["minutes"] for x in sg), "suggested_cost": round(sum(x["cost"] for x in sg), 2),
        "tardiness_saved_minutes": round(sum(x["tardiness_saved_minutes"] or 0 for x in sg), 2)}}


def exceptions(ctx: AppContext, run_id: str, *, code: list[str] | None, severity: list[str] | None,
               order_id: str | None, q: str | None, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        allx = list(s.execute(select(MfgApsExceptionRow).where(MfgApsExceptionRow.run_id == r.id)
                              .order_by(MfgApsExceptionRow.ex_no)).scalars())
    counts = {"by_severity": {k: 0 for k in ("critical", "warning", "info")}, "by_code": {}}
    for x in allx:
        counts["by_severity"][x.severity] = counts["by_severity"].get(x.severity, 0) + 1
        counts["by_code"][x.code] = counts["by_code"].get(x.code, 0) + 1
    sel = [x for x in allx if (not code or x.code in code) and (not severity or x.severity in severity) and
           (order_id is None or (x.order_ref or {}).get("id") == order_id) and
           (not q or q.lower() in x.message.lower())]
    out = page([aps_store.exception_view(x) for x in sel[offset:offset + limit]], len(sel), limit, offset)
    out["counts"] = counts
    return out


def bottlenecks(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        groups = {g.id: g for g in s.execute(select(MfgGroupRow)).scalars()}
        out = []
        for b in (r.extras or {}).get("bottlenecks", []):
            g = groups.get(b["group_id"])
            out.append({**b, "group": {"id": b["group_id"], "code": g.code if g else "", "name": g.name if g else ""}})
        return {"items": out}


def dispatch(ctx: AppContext, run_id: str, *, line_id: str, day: date | None, shift: str | None) -> dict[str, Any]:
    from ....mfg.calendar import line_windows

    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        line = s.execute(select(MfgLineRow).where(MfgLineRow.id == line_id)).scalars().first()
        if line is None:
            raise not_found("Line", line_id)
        p = s.execute(select(repo.MfgPlantRow)).scalars().first()
        tz = plant_tz(p) if p is not None else UTC
        day = day or as_utc(r.as_of).astimezone(tz).date()
        lo = datetime(day.year, day.month, day.day, tzinfo=tz)
        hi = lo + timedelta(days=1)
        rows = list(s.execute(select(MfgApsOpRow).where(
            MfgApsOpRow.run_id == r.id, MfgApsOpRow.line_id == line_id, MfgApsOpRow.start_at >= lo,
            MfgApsOpRow.start_at < hi).order_by(MfgApsOpRow.start_at, MfgApsOpRow.op_no)).scalars())
        ds = repo.load_dataset(s)
        wins = line_windows(ds, line_id, day - timedelta(days=1), day + timedelta(days=1))
        if shift:
            wins = [w for w in wins if shift in w.shift_label.split("/")[-1].split("+")]
            rows = [x for x in rows if any(w.start <= as_utc(x.start_at) < w.end for w in wins)]
        wo_ids = sorted({x.order_id for x in rows if x.order_type == "wo"})
        done = {(w, q) for w, q in s.execute(select(MfgWoOpProgressRow.wo_id, MfgWoOpProgressRow.seq).where(
            MfgWoOpProgressRow.wo_id.in_(wo_ids), MfgWoOpProgressRow.done.is_(True))).all()} if wo_ids else set()
        kit: dict[str, str] = {}
        if wo_ids:
            from ..db_models_m2 import MfgInvReservationRow

            res = {cid: q for cid, q in s.execute(select(MfgInvReservationRow.wo_component_id,
                                                         func.sum(MfgInvReservationRow.qty))
                                                  .group_by(MfgInvReservationRow.wo_component_id)).all()}
            for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id.in_(wo_ids))).scalars():
                need = max(0.0, c.required_qty - c.issued_qty)
                have = res.get(c.id, 0.0)
                st = "kitted" if have + 1e-6 >= need else ("partial" if have > 0 or c.issued_qty > 0 else "short")
                prev = kit.get(c.wo_id, "kitted")
                order = {"kitted": 0, "partial": 1, "short": 2}
                kit[c.wo_id] = st if order[st] > order[prev] else prev
        all_ops = {(x.order_id, x.seq): x for x in s.execute(select(MfgApsOpRow).where(
            MfgApsOpRow.run_id == r.id, MfgApsOpRow.order_id.in_({x.order_id for x in rows}))).scalars()} \
            if rows else {}
        items = []
        for i, x in enumerate(rows, 1):
            seqs = sorted(q for (o, q) in all_ops if o == x.order_id)
            prev_seq = max((q for q in seqs if q < x.seq), default=None)
            if prev_seq is None:
                ps = "none"
            elif (x.order_id, prev_seq) in done:
                ps = "done"
            else:
                pv = all_ops.get((x.order_id, prev_seq))
                ps = "scheduled_before" if pv is not None and pv.end_at is not None and pv.end_at <= x.start_at \
                    else "open"
            label = next((w.shift_label for w in wins if w.start <= as_utc(x.start_at) < w.end), "")
            items.append({
                "op_no": x.op_no, "position": i, "start": as_utc(x.start_at), "end": as_utc(x.end_at),
                "order": {"type": x.order_type, "id": x.order_id, "number": x.order_number,
                          "planned_no": x.planned_no, "item_id": x.item_id},
                "part_number": x.part_number, "qty": x.qty, "seq": x.seq, "name": x.name,
                "setup_minutes": x.setup_minutes, "run_minutes": x.run_minutes,
                "setup_from_family": x.setup_from_family, "family": x.family, "crew": x.crew, "tools": x.tools,
                "predecessor_status": ps,
                "material_status": kit.get(x.order_id, "n/a") if x.order_type == "wo" else "n/a",
                "done": (x.order_id, x.seq) in done, "shift_label": label})
        return {"line": {"id": line.id, "code": line.code}, "date": day.isoformat(), "shift": shift, "run_id": r.id,
                "items": items}


def gantt(ctx: AppContext, run_id: str, *, view: str, frm: datetime | None, to: datetime | None,
          group_id: str | None, line_id: str | None, order_id: str | None, demand_order_id: str | None
          ) -> dict[str, Any]:
    from ....mfg.calendar import line_windows

    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        frm = frm or as_utc(r.as_of)
        to = to or min(as_utc(r.horizon_end), frm + timedelta(days=14))
        conds = [MfgApsOpRow.status == "scheduled", MfgApsOpRow.end_at > frm, MfgApsOpRow.start_at < to]
        if group_id:
            conds.append(MfgApsOpRow.group_id == group_id)
        if line_id:
            conds.append(MfgApsOpRow.line_id == line_id)
        if order_id:
            conds.append(MfgApsOpRow.order_id == order_id)
        rows = list(s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == r.id, *conds)
                              .order_by(MfgApsOpRow.start_at, MfgApsOpRow.op_no).limit(APS_MAX_GANTT_BARS + 1))
                    .scalars())
        truncated = len(rows) > APS_MAX_GANTT_BARS
        rows = rows[:APS_MAX_GANTT_BARS]
        lines = {x.id: x for x in s.execute(select(MfgLineRow)).scalars()}
        groups = {x.id: x for x in s.execute(select(MfgGroupRow)).scalars()}
        extras = r.extras or {}
        out_rows: list[dict[str, Any]] = []
        bands: list[dict[str, Any]] = []
        row_of: dict[int, str] = {}
        if view == "line":
            used = sorted({x.line_id for x in rows if x.line_id} | ({line_id} if line_id else set()),
                          key=lambda i: (groups[lines[i].group_id].code if i in lines and lines[i].group_id in groups
                                         else "", lines[i].code if i in lines else i))
            if group_id:
                used = sorted({lid for lid, ln in lines.items() if ln.group_id == group_id and ln.active} | set(used),
                              key=lambda i: lines[i].code)
            seen_g: set[str] = set()
            ds = repo.load_dataset(s)
            p_tz = plant_tz(ds.plant)
            d0, d1 = frm.astimezone(p_tz).date() - timedelta(days=1), to.astimezone(p_tz).date() + timedelta(days=1)
            ot = list(s.execute(select(MfgApsOvertimeRow).where(MfgApsOvertimeRow.run_id == r.id)).scalars())
            for lid in used:
                ln = lines[lid]
                if ln.group_id not in seen_g:
                    seen_g.add(ln.group_id)
                    g = groups.get(ln.group_id)
                    out_rows.append({"key": f"group:{ln.group_id}", "label": g.code if g else "", "kind": "group",
                                     "parent_key": None})
                out_rows.append({"key": f"line:{lid}", "label": ln.code, "kind": "line",
                                 "parent_key": f"group:{ln.group_id}"})
                for w in line_windows(ds, lid, d0, d1, kinds=("base",)):
                    if w.end > frm and w.start < to:
                        bands.append({"row_key": f"line:{lid}", "start": as_utc(w.start), "end": as_utc(w.end),
                                      "kind": "base"})
                for o in ot:
                    if o.line_id == lid and o.end_at > frm and o.start_at < to:
                        bands.append({"row_key": f"line:{lid}", "start": as_utc(o.start_at), "end": as_utc(o.end_at),
                                      "kind": "optional_suggested" if o.status == "suggested" else "optional_opened"})
                for ov in (r.params or {}).get("capacity_overrides", []):
                    if ov.get("mode") == "close" and (ov.get("target_id") in (lid, ln.group_id)):
                        bands.append({"row_key": f"line:{lid}", "start": aps_store.parse_dt(ov["start"]),
                                      "end": aps_store.parse_dt(ov["end"]), "kind": "closed"})
            for x in rows:
                row_of[x.op_no] = f"line:{x.line_id}"
        elif view == "order":
            parents = extras.get("parents", {})
            ords = {}
            for x in rows:
                ords.setdefault(x.order_id, x)
            for oid, x in sorted(ords.items(), key=lambda kv: kv[1].order_number):
                par = parents.get(oid)
                out_rows.append({"key": f"order:{x.order_type}:{oid}", "label": f"{x.order_number} {x.part_number}",
                                 "kind": "order", "parent_key": None})
                out_rows[-1]["parent_key"] = next((f"order:{y.order_type}:{par}" for y in rows if y.order_id == par),
                                                  None) if par else None
            for x in rows:
                row_of[x.op_no] = f"order:{x.order_type}:{x.order_id}"
        else:
            dem = [d for d in extras.get("demand", []) if demand_order_id is None or d.get("order_id") ==
                   demand_order_id]
            want: dict[str, str] = {}
            for d in dem:
                key = f"demand:{d.get('demand_line_id')}"
                out_rows.append({"key": key, "label": f"{d['order_number']}/{d['line_no']} {d['part_number']}",
                                 "kind": "demand", "parent_key": None})
                for o in d.get("orders", []):
                    want.setdefault(o["id"], key)
            rows = [x for x in rows if x.order_id in want]
            for x in rows:
                row_of[x.op_no] = want[x.order_id]
        bars = []
        for x in rows:
            if x.op_no not in row_of:
                continue
            st, en = as_utc(x.start_at), as_utc(x.end_at)
            setup_end = st
            left = x.setup_minutes
            for pc in x.pieces or []:
                a, b = aps_store.parse_dt(pc["start"]), aps_store.parse_dt(pc["end"])
                take = min(left, int((b - a).total_seconds() // 60))
                setup_end = a + timedelta(minutes=take)
                left -= take
                if left <= 0:
                    break
            color = "frozen" if x.frozen else "locked" if x.locked else "late" if x.late_minutes > 0 else "on_time"
            bars.append({"op_no": x.op_no, "row_key": row_of[x.op_no], "start": st, "end": en, "setup_end": setup_end,
                         "pieces": x.pieces, "label": f"{x.order_number} {x.seq} {x.name}" + (
                             f" ({x.split_index + 1}/{x.split_count})" if x.split_count > 1 else ""),
                         "order_number": x.order_number, "item_part_number": x.part_number, "qty": x.qty,
                         "late_minutes": x.late_minutes, "frozen": x.frozen, "locked": x.locked,
                         "split": {"index": x.split_index, "count": x.split_count}, "status_color": color})
        return {"view": view, "rows": out_rows, "bars": bars, "bands": bands, "truncated": truncated}


def compare(ctx: AppContext, run_id: str, with_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        a = _completed(s, run_id)
        b = _completed(s, with_id)
        sa, sb = a.summary or {}, b.summary or {}
        ha = {"id": a.id, "run_no": a.run_no, "label": a.label, "policy": sa.get("policy")}
        hb = {"id": b.id, "run_no": b.run_no, "label": b.label, "policy": sb.get("policy")}
        oa = {x.order_id: aps_store.order_view(x) for x in s.execute(select(MfgApsOrderRow).where(
            MfgApsOrderRow.run_id == a.id)).scalars()}
        ob = {x.order_id: aps_store.order_view(x) for x in s.execute(select(MfgApsOrderRow).where(
            MfgApsOrderRow.run_id == b.id)).scalars()}
    keys = ("late_demand_count", "late_orders", "weighted_tardiness", "max_lateness_minutes", "overtime_minutes",
            "overtime_cost", "suggested_overtime_minutes", "setup_minutes", "changeovers", "avg_flow_days",
            "makespan_minutes", "scheduled_operations")
    num = (int, float)
    kpis = [{"key": k, "a": sa.get(k), "b": sb.get(k),
             "delta": (sb.get(k) - sa.get(k)) if isinstance(sa.get(k), num) and isinstance(sb.get(k), num) else None}
            for k in keys]
    deltas = []
    late_a = sum(x["late_minutes"] for x in oa.values())
    late_b = sum(x["late_minutes"] for x in ob.values())
    for oid in sorted(set(oa) | set(ob), key=lambda i: ((oa.get(i) or ob.get(i))["order"]["number"], i)):
        x, y = oa.get(oid), ob.get(oid)
        ea, eb = (x or {}).get("end"), (y or {}).get("end")
        la, lb = (x or {}).get("late_minutes", 0), (y or {}).get("late_minutes", 0)
        if ea == eb and la == lb:
            continue
        deltas.append({"order": (x or y)["order"], "end_a": ea, "end_b": eb,
                       "delta_minutes": int((eb - ea).total_seconds() // 60) if ea and eb else None,
                       "late_a": la, "late_b": lb})
    ua, ub = sa.get("utilisation", {}), sb.get("utilisation", {})
    util = [{"key": g, "a": ua.get(g), "b": ub.get(g),
             "delta": round((ub.get(g) or 0) - (ua.get(g) or 0), 4)} for g in sorted(set(ua) | set(ub))]
    tradeoff = {"weighted_tardiness_saved": round((sa.get("weighted_tardiness") or 0) -
                                                  (sb.get("weighted_tardiness") or 0), 2),
                "late_minutes_saved": float(late_a - late_b),
                "late_demand_saved": float((sa.get("late_demand_count") or 0) - (sb.get("late_demand_count") or 0)),
                "overtime_hours_added": round(((sb.get("overtime_minutes") or 0) - (sa.get("overtime_minutes") or 0))
                                              / 60.0, 2),
                "overtime_cost_added": round((sb.get("overtime_cost") or 0) - (sa.get("overtime_cost") or 0), 2)}
    return {"a": ha, "b": hb, "kpis": kpis, "tradeoff": tradeoff, "orders": deltas[:500], "utilisation": util,
            "truncated": len(deltas) > 500}


def export(ctx: AppContext, run_id: str, fmt: str) -> tuple[bytes, str, str]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        lines = {x.id: x.code for x in s.execute(select(MfgLineRow)).scalars()}
        groups = {x.id: x.code for x in s.execute(select(MfgGroupRow)).scalars()}
        p = s.execute(select(repo.MfgPlantRow)).scalars().first()
        tz = plant_tz(p) if p is not None else UTC
        ops = _ops(s, r.id)
        ords = list(s.execute(select(MfgApsOrderRow).where(MfgApsOrderRow.run_id == r.id)
                              .order_by(MfgApsOrderRow.number)).scalars())
        loads = list(s.execute(select(MfgApsLoadRow).where(MfgApsLoadRow.run_id == r.id)
                               .order_by(MfgApsLoadRow.group_id, MfgApsLoadRow.line_id, MfgApsLoadRow.day)).scalars())
        no = r.run_no

        def t(v: Any) -> Any:
            return as_utc(v).astimezone(tz).strftime("%Y-%m-%d %H:%M") if v is not None else None

        sheets: dict[str, list[list[Any]]] = {
            "operations": [["op_no", "order", "part_number", "seq", "name", "stage", "line", "qty", "split", "start",
                            "end", "setup_minutes", "run_minutes", "status", "reason", "late_minutes", "frozen",
                            "locked"]] + [
                [x.op_no, x.order_number, x.part_number, x.seq, x.name, groups.get(x.group_id, ""),
                 lines.get(x.line_id or "", ""), x.qty, f"{x.split_index + 1}/{x.split_count}", t(x.start_at),
                 t(x.end_at), x.setup_minutes, x.run_minutes, x.status, (x.reason or {}).get("text", ""),
                 x.late_minutes, x.frozen, x.locked] for x in ops],
            "dispatch": [["line", "position", "start", "end", "order", "part_number", "seq", "name", "qty",
                          "setup_from_family", "family"]] + [
                [lines.get(x.line_id or "", ""), i, t(x.start_at), t(x.end_at), x.order_number, x.part_number, x.seq,
                 x.name, x.qty, x.setup_from_family, x.family]
                for i, x in enumerate(sorted((o for o in ops if o.line_id and o.start_at is not None),
                                             key=lambda o: (lines.get(o.line_id, ""), o.start_at, o.op_no)), 1)],
            "orders": [["order", "type", "part_number", "qty", "due", "start", "end", "late_minutes", "priority",
                        "late_text"]] + [
                [x.number, x.order_type, x.part_number, x.qty, t(x.due_at), t(x.start_at), t(x.end_at), x.late_minutes,
                 x.priority, x.late_text] for x in ords],
            "load": [["stage", "line", "day", "scheduled_minutes", "required_minutes", "base_minutes",
                      "optional_minutes", "opened_minutes"]] + [
                [groups.get(x.group_id, ""), lines.get(x.line_id or "", ""), x.day, x.scheduled_minutes,
                 x.required_minutes, x.base_minutes, x.optional_minutes, x.opened_minutes] for x in loads]}
        name = f"superplanner-schedule-run-{no}.{fmt}"
    return _file(sheets, fmt), name, (XLSX if fmt == "xlsx" else "application/zip")


def _file(sheets: dict[str, list[list[Any]]], fmt: str) -> bytes:
    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell

        wb = Workbook(write_only=True)
        for sname, rows in sheets.items():
            ws = wb.create_sheet(sname)
            for row in rows:
                cells = []
                for v in row:
                    if isinstance(v, str):
                        c = WriteOnlyCell(ws, value=v)
                        c.data_type = "s"
                        cells.append(c)
                    else:
                        cells.append(v)
                ws.append(cells)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sname, rows in sheets.items():
            out = io.StringIO(newline="")
            w = csv.writer(out, lineterminator="\r\n")
            for row in rows:
                w.writerow(["" if v is None else (v.isoformat() if isinstance(v, date) else v) for v in row])
            info = zipfile.ZipInfo(f"{sname}.csv", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, ("﻿" + out.getvalue()).encode("utf-8"))
    return buf.getvalue()


def published_summary(s: Session) -> dict[str, Any] | None:
    """`GET /summary` -> `published_schedule` (11)."""
    r = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
    if r is None:
        return None
    st = _stale(s, r)
    return {"id": r.id, "run_no": r.run_no, "published_at": as_utc(r.published_at),
            "late_orders": (r.summary or {}).get("late_orders", 0), "stale": bool(st and st["is_stale"])}


__all__ = ["bottlenecks", "cancel_run", "compare", "create_edits", "create_run", "delete_run", "demand", "dispatch",
           "exceptions", "export", "gantt", "get_run", "list_runs", "load", "operation", "operations", "orders",
           "overtime", "publish_run", "published_run", "published_summary", "recover_interrupted_runs", "run_job",
           "run_record", "update_run"]
_unused = (threading, IntegrityError, MfgWorkOrderRow)
