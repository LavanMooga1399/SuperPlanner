"""MRP runs (M2-DESIGN 8.14, 12.3 #148-162) and the shortage dashboard (#163).

A run: (1) insert the `running` row and commit (partial unique index: one running run per owner -> 409
`MRP_RUN_IN_PROGRESS`; a stale `running` row is first marked `failed`); (2) load the snapshot in one REPEATABLE READ
read-only transaction; (3) Gate 1 + preflight (422; the run row is deleted); (4) `run_mrp` (pure); (5) store the
results in one transaction (`mrp_store`), `completed`, retention. Conversion of planned orders works only on the
latest completed live run, all-or-nothing, each order once.
"""

from __future__ import annotations

import csv
import io
import logging
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.dataset import fingerprint, ref
from ....mfg.health import run_health_check
from ....mfg.model_m2 import EPS, WorkOrderInput
from ....mfg.mrp import views as V
from ....mfg.mrp.model import MrpParams, MrpPreflightError, MrpTooLarge
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.locks import is_unique_violation
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import mrp_store as MS
from .. import repo, repo_m2
from ..db_models import MfgItemRow
from ..db_models_m2 import (MfgItemSupplierRow, MfgMrpDemandResultRow, MfgMrpExceptionRow, MfgMrpItemResultRow,
                            MfgMrpPlannedOrderRow, MfgMrpRunRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                            MfgPurchaseScheduleRow, MfgSupplierRow)
from .common import audit, check_version, ilike, plant_today, read_tx, touch, write_tx
from .m2util import actor_id, iref, items, page, r6, request_hash, run_tx, today, user_names

log = logging.getLogger(__name__)
SEV = ("critical", "warning", "info")


# ---------------------------------------------------------------- records, staleness


def _stale(s: Session, run: MfgMrpRunRow) -> dict[str, Any]:
    tok = repo_m2.inputs_token(s)
    old = dict(run.inputs_token or {})
    master = tok.get("data_version") != run.data_version
    tx = any(tok.get(k) != old.get(k) for k in ("seq", "purchase_docs", "demand_orders", "work_orders"))
    return {"is_stale": master or tx, "master_changed": master, "transactions_changed": tx}


def run_record(s: Session, run: MfgMrpRunRow, *, with_params: bool = True, stale: bool = True) -> dict[str, Any]:
    names = user_names(s, [run.actor_id])
    out = {"id": run.id, "run_no": run.run_no, "kind": run.kind, "status": run.status, "label": run.label,
           "note": run.note, "pinned": run.pinned, "as_of": run.as_of, "horizon_days": run.horizon_days,
           "master_fingerprint": run.master_fingerprint, "row_version": run.row_version,
           "started_at": as_utc(run.started_at), "finished_at": as_utc(run.finished_at),
           "duration_ms": run.duration_ms, "actor": {"id": run.actor_id, "name": names.get(run.actor_id, "")},
           "summary": run.summary, "stale": _stale(s, run) if stale else None, "error": run.error}
    if with_params:
        out["params"] = run.params
    return out


def _get_run(s: Session, run_id: str, lock: bool = False) -> MfgMrpRunRow:
    return repo.get_row(s, MfgMrpRunRow, run_id, what="MRP run", lock=lock)


def latest_live(s: Session) -> MfgMrpRunRow | None:
    return s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                     .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalars().first()


def latest_item_shortage(s: Session, item_id: str) -> dict[str, Any] | None:
    run = latest_live(s)
    if run is None:
        return None
    row = s.execute(select(MfgMrpItemResultRow).where(MfgMrpItemResultRow.run_id == run.id,
                                                      MfgMrpItemResultRow.item_id == item_id)).scalars().first()
    return {"run_id": run.id, "run_no": run.run_no, "first_short_date": row.first_short_date if row else None,
            "short_qty": row.short_qty if row else 0.0}


def summary_latest(s: Session) -> dict[str, Any] | None:
    run = latest_live(s)
    if run is None:
        return None
    return {"id": run.id, "run_no": run.run_no, "finished_at": as_utc(run.finished_at),
            "demand_late": (run.summary or {}).get("demand_late", 0), "stale": _stale(s, run)["is_stale"]}


# ---------------------------------------------------------------- run


def _what_if(p: MrpParams, today_: date) -> bool:
    return (p.as_of is not None and p.as_of != today_) or p.what_if_inputs()


def create_run(ctx: AppContext, params: MrpParams) -> dict[str, Any]:
    t0 = time.monotonic()
    actor = actor_id()

    def start(s: Session) -> tuple[str, date, int, str]:
        p = repo.plant_or_default(s)
        d = plant_today(p.utc_offset)
        stale_before = utcnow() - timedelta(minutes=L.MRP_STALE_RUNNING_MINUTES)
        for r in s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.status == "running",
                                                      MfgMrpRunRow.started_at < stale_before).with_for_update()
                           ).scalars():
            r.status, r.finished_at = "failed", utcnow()
            r.error = {"code": "MRP_RUN_ABANDONED", "message": "The run did not finish."}
            touch(r)
        s.flush()
        n = int(s.execute(select(func.coalesce(func.max(MfgMrpRunRow.run_no), 0))).scalar() or 0) + 1
        as_of = params.as_of or d
        now = utcnow()
        run = MfgMrpRunRow(id=new_id("mrr_"), run_no=n, kind="what_if" if _what_if(params, d) else "live",
                           status="running", label=params.label, note=params.note, pinned=False,
                           params=params.model_dump(mode="json"), as_of=as_of,
                           horizon_days=params.horizon_days or p.planning_horizon_days, master_fingerprint="",
                           data_version=p.data_version, inputs_token={}, started_at=now, finished_at=None,
                           duration_ms=None, actor_id=actor, summary=None, error=None, row_version=1,
                           created_at=now, updated_at=now)
        try:
            with s.begin_nested():
                s.add(run)
                s.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc, "uq_mfg_mrp_runs_running"):
                raise ApiError(409, "MRP_RUN_IN_PROGRESS", "An MRP run is in progress for this plant; wait for it to "
                               "finish.", {}) from None
            if is_unique_violation(exc, "uq_mfg_mrp_runs_no"):
                raise ApiError(409, "MFG_BUSY", "Another MRP run started at the same time.", {},
                               headers={"Retry-After": "5"}) from None
            raise
        audit(s, "mrp_run", run.id, "run", {"run_no": n, "kind": run.kind})
        return run.id, as_of, run.horizon_days, run.kind

    run_id, as_of, horizon, kind = run_tx(ctx, start)

    def drop(code: str, message: str, details: dict[str, Any]) -> ApiError:
        def fn(s: Session) -> None:
            r = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.id == run_id)).scalars().first()
            if r is not None:
                audit(s, "mrp_run", run_id, "delete", {"reason": code})
                s.delete(r)
                s.flush()
        run_tx(ctx, fn)
        return ApiError(422, code, message, details)

    try:
        t1 = time.monotonic()
        with repo_m2.snapshot_tx(ctx.db) as s:
            snap = repo_m2.load_mrp_snapshot(s, as_of)
            token = repo_m2.inputs_token(s)
        ds = snap.dataset
        load_ms = int((time.monotonic() - t1) * 1000)
        if len(snap.demand) > L.MAX_OPEN_DEMAND_LINES or len(snap.work_orders) > L.MAX_OPEN_WORK_ORDERS or \
                len(snap.schedules) > L.MAX_OPEN_SCHEDULES:
            raise drop("MRP_TOO_LARGE", "The plant has more open demand, work orders or schedules than one MRP run "
                       "can plan.", {"demand_lines": len(snap.demand), "work_orders": len(snap.work_orders),
                                     "schedules": len(snap.schedules)})
        report = run_health_check(ds, as_of, horizon)
        if not report.ok:
            raise drop("MFG_DATA_HEALTH_FAILED", "The data health check has errors; fix them before running MRP.",
                       {"report": report.model_dump(mode="json")})
        from ....mfg.mrp import run_mrp

        t2 = time.monotonic()
        try:
            result = run_mrp(snap, params)
        except MrpPreflightError as e:
            raise drop("MRP_PREFLIGHT_FAILED", "MRP cannot run on this data.", {"issues": e.issues}) from None
        except MrpTooLarge as e:
            raise drop("MRP_TOO_LARGE", str(e), {"limit": e.limit}) from None
        compute_ms = int((time.monotonic() - t2) * 1000)
        fp = fingerprint(ds)
    except ApiError:
        raise
    except Exception:
        log.exception("MRP run %s failed", run_id)
        _fail(ctx, run_id)
        raise

    def finish(s: Session) -> dict[str, Any]:
        run = _get_run(s, run_id, lock=True)
        t3 = time.monotonic()
        info = MS.store(s, run, result, snap)
        store_ms = int((time.monotonic() - t3) * 1000)
        summ = MS._jsonable(result.summary)
        summ["exceptions_truncated"] = bool(summ.get("exceptions_truncated")) or info["exceptions_truncated"]
        summ["timings_ms"] = {"load": load_ms, "compute": compute_ms, "store": store_ms}
        run.summary = summ
        run.status = "completed"
        run.master_fingerprint = fp
        run.inputs_token = token
        run.data_version = token["data_version"]
        run.finished_at = utcnow()
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        run.kind = kind
        touch(run)
        s.flush()
        old = list(s.execute(select(MfgMrpRunRow.id).where(MfgMrpRunRow.pinned.is_(False), MfgMrpRunRow.id != run.id,
                                                           MfgMrpRunRow.status != "running")
                             .order_by(MfgMrpRunRow.run_no.desc())).scalars())[L.MRP_RUNS_KEPT - 1:]
        latest = latest_live(s)
        old = [x for x in old if latest is None or x != latest.id]
        if old:
            s.execute(delete(MfgMrpRunRow).where(MfgMrpRunRow.id.in_(old)).execution_options(synchronize_session=False))
        audit(s, "mrp_run", run.id, "run_completed", {"run_no": run.run_no, "deleted_runs": len(old),
                                                       "demand_late": summ.get("demand_late")})
        return run_record(s, run)

    try:
        return run_tx(ctx, finish)
    except Exception:
        log.exception("MRP run %s could not be stored", run_id)
        _fail(ctx, run_id)
        raise


def _fail(ctx: AppContext, run_id: str) -> None:
    def fn(s: Session) -> None:
        r = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.id == run_id).with_for_update()).scalars().first()
        if r is not None and r.status == "running":
            r.status, r.finished_at = "failed", utcnow()
            r.error = {"code": "MRP_RUN_FAILED", "message": "The MRP run failed unexpectedly."}
            touch(r)
            audit(s, "mrp_run", run_id, "fail", {})
    try:
        run_tx(ctx, fn)
    except Exception:  # pragma: no cover - best effort
        log.exception("could not mark run %s failed", run_id)


def list_runs(ctx: AppContext, kind: str | None, pinned: bool | None, limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if kind:
        conds.append(MfgMrpRunRow.kind == kind)
    if pinned is not None:
        conds.append(MfgMrpRunRow.pinned.is_(pinned))
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgMrpRunRow).where(*conds).order_by(MfgMrpRunRow.run_no.desc())
                              .limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(MfgMrpRunRow).where(*conds)).scalar() or 0)
        return page([run_record(s, r, with_params=False) for r in rows], total, limit, offset)


def get_latest(ctx: AppContext, kind: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.kind == kind, MfgMrpRunRow.status == "completed")
                      .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalars().first()
        if r is None:
            raise not_found("MRP run", "latest")
        return run_record(s, r)


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return run_record(s, _get_run(s, run_id))


def update_run(ctx: AppContext, run_id: str, label: str, note: str, pinned: bool, if_match: str | None
               ) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        r = _get_run(s, run_id, lock=True)
        check_version(r, if_match)
        if pinned and not r.pinned:
            n = int(s.execute(select(func.count()).select_from(MfgMrpRunRow).where(MfgMrpRunRow.pinned.is_(True)))
                    .scalar() or 0)
            if n >= L.MRP_PINNED_MAX:
                raise ApiError(422, "MFG_LIMIT", f"At most {L.MRP_PINNED_MAX} runs can be pinned.",
                               {"limit": L.MRP_PINNED_MAX, "count": n})
        r.label, r.note, r.pinned = label, note, pinned
        touch(r)
        s.flush()
        audit(s, "mrp_run", r.id, "update", {"pinned": pinned, "version": r.row_version})
        return run_record(s, r)

    return run_tx(ctx, fn)


def delete_run(ctx: AppContext, run_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        r = _get_run(s, run_id, lock=True)
        check_version(r, if_match)
        latest = latest_live(s)
        if latest is not None and latest.id == r.id:
            raise ApiError(409, "MFG_IN_USE", "The latest live run cannot be deleted; run MRP again first.",
                           {"references": {"latest_live": 1}})
        if r.status == "running":
            raise ApiError(409, "MRP_RUN_IN_PROGRESS", "This run is still in progress.", {})
        audit(s, "mrp_run", r.id, "delete", {"run_no": r.run_no})
        s.delete(r)
        s.flush()

    run_tx(ctx, fn)


# ---------------------------------------------------------------- result views


def _completed(s: Session, run_id: str) -> MfgMrpRunRow:
    r = _get_run(s, run_id)
    if r.status != "completed":
        raise ApiError(409, "MRP_RUN_NOT_COMPLETED", f"Run {r.run_no} is {r.status}.", {"status": r.status})
    return r


def _run_head(s: Session, r: MfgMrpRunRow) -> dict[str, Any]:
    return {"id": r.id, "run_no": r.run_no, "as_of": r.as_of, "stale": _stale(s, r)}


def list_items(ctx: AppContext, run_id: str, *, q: str | None, make_buy: str | None, family: str | None,
               short_only: bool, has_exceptions: bool, planned_only: bool, llc: int | None, sort: str, limit: int,
               offset: int) -> dict[str, Any]:
    R = MfgMrpItemResultRow
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        conds: list[Any] = [R.run_id == r.id]
        if q:
            conds.append(ilike(R.part_number, q) | ilike(R.description, q))
        if make_buy:
            conds.append(R.make_buy == make_buy)
        if family:
            conds.append(R.detail["family"].astext == family)
        if short_only:
            conds.append(R.short_qty > EPS)
        if has_exceptions:
            conds.append(R.exception_count > 0)
        if planned_only:
            conds.append(R.planned_count > 0)
        if llc is not None:
            conds.append(R.llc == llc)
        order = {"llc": (R.llc, R.part_number), "part_number": (R.part_number,),
                 "first_short_date": (R.first_short_date.asc().nulls_last(), R.part_number),
                 "-short_qty": (R.short_qty.desc(), R.part_number)}[sort]
        rows = list(s.execute(select(R).where(*conds).order_by(*order).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(R).where(*conds)).scalar() or 0)
        return page([MS.item_row(r.id, x) for x in rows], total, limit, offset)


def item_plan(ctx: AppContext, run_id: str, item_id: str, bucket: str, d0: date | None, d1: date | None
              ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        row = s.execute(select(MfgMrpItemResultRow).where(MfgMrpItemResultRow.run_id == r.id,
                                                          MfgMrpItemResultRow.item_id == item_id)).scalars().first()
        if row is None:
            raise not_found("Item", item_id)
        plan = MS.plan_of(row)
        tl = V.item_timeline(plan, r.as_of)
        start = d0 or r.as_of
        end = d1 or (r.as_of + timedelta(days=r.horizon_days))
        buckets = V.bucketize(tl, bucket, start, end)
        sup = None
        if plan.supplier_id:
            sp = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id == plan.supplier_id)).scalars().first()
            sup = ref(sp) if sp else {"id": plan.supplier_id, "code": "?", "name": ""}
        lk_planned = {str(p.planned_no): p.id for p in s.execute(select(MfgMrpPlannedOrderRow).where(
            MfgMrpPlannedOrderRow.run_id == r.id, MfgMrpPlannedOrderRow.item_id == item_id)).scalars()}
        ex_codes: dict[str, list[str]] = {}
        for e in s.execute(select(MfgMrpExceptionRow).where(MfgMrpExceptionRow.run_id == r.id,
                                                            MfgMrpExceptionRow.item_id == item_id)).scalars():
            sid = (e.subject or {}).get("id")
            if sid:
                ex_codes.setdefault(sid, []).append(e.code)
        sup_by_node = {x.node: x for x in plan.supplies}
        reqs = []
        for q in plan.requirements:
            src = q.source
            link = None
            if src.type == "demand_line":
                link = f"/mfg/demand/?line={src.id}"
            elif src.type in ("planned_order", "work_order") and src.item_id:
                link = f"/mfg/mrp/runs/{r.id}/items/{src.item_id}"
            reqs.append({"node": q.node, "kind": q.kind, "need_date": q.need_date, "qty": q.qty,
                         "rank_label": q.rank_label, "segment": MS._seg(q.segment),
                         "source": {"type": src.type, "id": src.id, "label": src.label, "item_id": src.item_id,
                                    "node": src.node, "link": link},
                         "satisfied_date": q.satisfied_date, "late_days": q.late_days,
                         "pegs": [{"supply_node": pg.supply_node,
                                   "supply_label": sup_by_node[pg.supply_node].ref.label
                                   if pg.supply_node in sup_by_node else "", "qty": pg.qty, "late_days": pg.late_days}
                                  for pg in q.pegs]})
        sups = []
        for x in plan.supplies:
            rf = x.ref
            link = None
            if rf.type == "planned_order":
                link = f"/mfg/mrp/runs/{r.id}/planned?order={lk_planned.get(rf.id or '', '')}"
            elif rf.type == "work_order":
                link = f"/mfg/work-orders/{rf.id}"
            sups.append({"node": x.node, "kind": x.kind, "label": rf.label, "avail_date": x.avail_date,
                         "projected_date": x.projected_date, "qty": x.qty, "pegged_qty": x.pegged_qty,
                         "expires_on": x.expires_on,
                         "ref": {"type": rf.type, "id": rf.id, "number": rf.number, "link": link},
                         "planned_no": x.planned_no, "exception_codes": ex_codes.get(rf.id or "", [])})
        lot = plan.lot
        return {"run": _run_head(s, r), "row": MS.item_row(r.id, row),
                "lot": {"rule": lot.rule, "moq": lot.moq, "multiple": lot.multiple, "pack": lot.pack,
                        "period_days": lot.period_days, "fixed_qty": lot.fixed_qty},
                "supplier": sup,
                "timeline": [{"date": e.date, "kind": e.kind, "node": e.node, "label": e.label, "qty": e.qty,
                              "balance_existing": e.balance_existing, "balance_planned": e.balance_planned}
                             for e in tl],
                "buckets": buckets, "requirements": reqs, "supplies": sups}


def _item_refs_from_results(s: Session, run_id: str, item_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({i for i in item_ids if i})
    if not ids:
        return {}
    return {x.item_id: MS.item_ref_of(x) for x in s.execute(select(MfgMrpItemResultRow).where(
        MfgMrpItemResultRow.run_id == run_id, MfgMrpItemResultRow.item_id.in_(ids))).scalars()}


def list_planned(ctx: AppContext, run_id: str, *, kind: str | None, item_id: str | None, supplier_id: str | None,
                 release_status: str | None, status: str | None, q: str | None, sort: str, limit: int, offset: int
                 ) -> dict[str, Any]:
    P = MfgMrpPlannedOrderRow
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        conds: list[Any] = [P.run_id == r.id]
        for col, v in ((P.kind, kind), (P.item_id, item_id), (P.supplier_id, supplier_id),
                       (P.release_status, release_status), (P.status, status)):
            if v:
                conds.append(col == v)
        if q:
            conds.append(ilike(P.part_number, q))
        order = {"start_date": (P.start_date, P.planned_no), "need_date": (P.need_date, P.planned_no),
                 "part_number": (P.part_number, P.planned_no),
                 "supplier": (P.supplier_id.asc().nulls_last(), P.start_date, P.planned_no)}[sort]
        rows = list(s.execute(select(P).where(*conds).order_by(*order).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(P).where(*conds)).scalar() or 0)
        counts = {f"{k}": int(v) for k, v in s.execute(select(P.release_status, func.count())
                                                        .where(P.run_id == r.id).group_by(P.release_status)).all()}
        kinds = {k: int(v) for k, v in s.execute(select(P.kind, func.count()).where(P.run_id == r.id)
                                                 .group_by(P.kind)).all()}
        irefs = _item_refs_from_results(s, r.id, [x.item_id for x in rows])
        sids = sorted({x.supplier_id for x in rows if x.supplier_id})
        sups = {x.id: ref(x) for x in s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id.in_(sids))).scalars()} \
            if sids else {}
        out = [MS.planned_row(r.id, x, irefs.get(x.item_id) or {"id": x.item_id, "part_number": x.part_number},
                              sups.get(x.supplier_id or "")) for x in rows]
        return page(out, total, limit, offset, counts={"by_release_status": counts, "by_kind": kinds})


def list_exceptions(ctx: AppContext, run_id: str, *, code: list[str] | None, severity: list[str] | None,
                    item_id: str | None, demand_line_id: str | None, q: str | None, limit: int, offset: int
                    ) -> dict[str, Any]:
    E = MfgMrpExceptionRow
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        conds: list[Any] = [E.run_id == r.id]
        if code:
            conds.append(E.code.in_(code))
        if severity:
            conds.append(E.severity.in_(severity))
        if item_id:
            conds.append(E.item_id == item_id)
        if demand_line_id:
            conds.append(E.demand_line_id == demand_line_id)
        if q:
            conds.append(ilike(E.message, q) | ilike(func.coalesce(E.part_number, ""), q))
        rows = list(s.execute(select(E).where(*conds).order_by(E.ex_no).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(E).where(*conds)).scalar() or 0)
        by_sev = {k: int(v) for k, v in s.execute(select(E.severity, func.count()).where(E.run_id == r.id)
                                                  .group_by(E.severity)).all()}
        by_code = {k: int(v) for k, v in s.execute(select(E.code, func.count()).where(E.run_id == r.id)
                                                   .group_by(E.code)).all()}
        irefs = _item_refs_from_results(s, r.id, [x.item_id for x in rows])
        out = [MS.exception_row(x, irefs.get(x.item_id) if x.item_id else None) for x in rows]
        return page(out, total, limit, offset, counts={"by_severity": by_sev, "by_code": by_code})


def list_demand(ctx: AppContext, run_id: str, *, status: str | None, program: str | None, order_id: str | None,
                late_only: bool, sort: str, limit: int, offset: int) -> dict[str, Any]:
    D = MfgMrpDemandResultRow
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        conds: list[Any] = [D.run_id == r.id]
        for col, v in ((D.status, status), (D.program, program), (D.order_id, order_id)):
            if v:
                conds.append(col == v)
        if late_only:
            conds.append(D.late_days > 0)
        order = (D.late_days.desc(), D.due_date, D.order_number, D.line_no) if sort == "-late_days" else \
            (D.due_date, D.order_number, D.line_no)
        rows = list(s.execute(select(D).where(*conds).order_by(*order).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(D).where(*conds)).scalar() or 0)
        irefs = _item_refs_from_results(s, r.id, [x.item_id for x in rows] +
                                        [st["item_id"] for x in rows for st in (x.limiting or {}).get("steps") or []])
        out = []
        for x in rows:
            d = MS.demand_row(x, irefs.get(x.item_id) or {"id": x.item_id, "part_number": x.part_number})
            for st in d["limiting"]:
                st["item"] = irefs.get(st["item"]["id"]) or st["item"]
            out.append(d)
        return page(out, total, limit, offset)


def pegging(ctx: AppContext, run_id: str, item_id: str, node: int, kind: str, direction: str, max_depth: int
            ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        cache: dict[str, Any] = {}

        def lookup(iid: str) -> Any:
            if iid not in cache:
                cache[iid] = MS.load_item_plan(s, r.id, iid)
            return cache[iid]

        try:
            out = V.pegging(lookup, item_id, node, kind, direction, max_depth)
        except KeyError:
            raise not_found("Pegging node", f"{item_id}/{node}") from None
        irefs = _item_refs_from_results(s, r.id, [x["item_id"] for x in out["rows"]])
        for x in out["rows"]:
            x["item"] = irefs.get(x["item_id"]) or {"id": x["item_id"]}
            x["link"] = f"/mfg/mrp/runs/{r.id}/items/{x['item_id']}"
            x.pop("item_id")
        return out


def compare(ctx: AppContext, run_id: str, other_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        a = _completed(s, run_id)
        b = _completed(s, other_id)

        def dem(r: MfgMrpRunRow) -> dict[str, MfgMrpDemandResultRow]:
            return {(x.demand_line_id or f"extra:{(x.limiting or {}).get('extra_index')}"): x for x in s.execute(
                select(MfgMrpDemandResultRow).where(MfgMrpDemandResultRow.run_id == r.id)).scalars()}

        da, db = dem(a), dem(b)
        demand = []
        for k in sorted(set(da) | set(db)):
            x, y = da.get(k), db.get(k)
            ap, bp = (x.projected_date if x else None), (y.projected_date if y else None)
            if ap == bp:
                continue
            rf = x or y
            demand.append({"demand_line_id": rf.demand_line_id, "label": (rf.limiting or {}).get("label", ""),
                           "due_date": rf.due_date, "a_projected": ap, "b_projected": bp,
                           "delta_days": (bp - ap).days if ap and bp else None})
        demand.sort(key=lambda d: (-abs(d["delta_days"] or 10**6), d["label"]))

        def planned(r: MfgMrpRunRow) -> dict[str, Any]:
            out = {"make": 0, "buy": 0, "make_qty": 0.0, "buy_value": 0.0}
            price_missing = False
            rows = list(s.execute(select(MfgMrpPlannedOrderRow).where(MfgMrpPlannedOrderRow.run_id == r.id)).scalars())
            prices = {x.item_id: x.unit_price for x in s.execute(select(MfgItemSupplierRow).where(
                MfgItemSupplierRow.preferred.is_(True))).scalars()}
            for x in rows:
                if x.kind == "make":
                    out["make"] += 1
                    out["make_qty"] += x.qty
                else:
                    out["buy"] += 1
                    p = prices.get(x.item_id)
                    if p is None:
                        price_missing = True
                    else:
                        out["buy_value"] += p * x.qty
            out["make_qty"] = r6(out["make_qty"])
            out["buy_value"] = None if price_missing else r6(out["buy_value"])
            return out

        def codes(r: MfgMrpRunRow) -> dict[str, int]:
            return {k: int(v) for k, v in s.execute(select(MfgMrpExceptionRow.code, func.count()).where(
                MfgMrpExceptionRow.run_id == r.id).group_by(MfgMrpExceptionRow.code)).all()}

        ca, cb = codes(a), codes(b)
        exc = [{"code": c, "a": ca.get(c, 0), "b": cb.get(c, 0)} for c in sorted(set(ca) | set(cb))
               if ca.get(c, 0) != cb.get(c, 0)]

        def its(r: MfgMrpRunRow) -> dict[str, MfgMrpItemResultRow]:
            return {x.item_id: x for x in s.execute(select(MfgMrpItemResultRow).where(
                MfgMrpItemResultRow.run_id == r.id)).scalars()}

        ia, ib = its(a), its(b)
        rows = []
        for k in sorted(set(ia) | set(ib)):
            x, y = ia.get(k), ib.get(k)
            v = (x.planned_qty if x else 0.0, y.planned_qty if y else 0.0, x.short_qty if x else 0.0,
                 y.short_qty if y else 0.0)
            if abs(v[0] - v[1]) > EPS or abs(v[2] - v[3]) > EPS:
                rows.append({"item": MS.item_ref_of(x or y), "a_planned_qty": v[0], "b_planned_qty": v[1],
                             "a_short_qty": v[2], "b_short_qty": v[3]})
        rows.sort(key=lambda r: (-abs(r["b_planned_qty"] - r["a_planned_qty"]), r["item"]["part_number"]))
        M = L.COMPARE_MAX_ROWS
        return {"a": run_record(s, a), "b": run_record(s, b), "demand": demand[:M],
                "planned": {"a": planned(a), "b": planned(b)}, "exceptions_by_code": exc, "items": rows[:M],
                "truncated": {"demand": len(demand) > M, "items": len(rows) > M}}


# ---------------------------------------------------------------- export (#162)


def export(ctx: AppContext, run_id: str, fmt: str) -> tuple[bytes, str, str]:
    with read_tx(ctx) as s:
        r = _completed(s, run_id)
        sheets: dict[str, list[list[Any]]] = {}
        sheets["planned_orders"] = [["planned_no", "kind", "part_number", "supplier_id", "qty", "need_date",
                                     "start_date", "dock_date", "projected_due", "late_days", "release_status",
                                     "status", "converted_number", "lot_note"]] + [
            [x.planned_no, x.kind, x.part_number, x.supplier_id, x.qty, x.need_date, x.start_date, x.dock_date,
             x.projected_due, x.late_days, x.release_status, x.status, x.converted_number, x.lot_note]
            for x in s.execute(select(MfgMrpPlannedOrderRow).where(MfgMrpPlannedOrderRow.run_id == r.id)
                               .order_by(MfgMrpPlannedOrderRow.planned_no)).scalars()]
        sheets["exceptions"] = [["ex_no", "code", "severity", "part_number", "subject", "date", "qty", "days",
                                 "message", "action"]] + [
            [x.ex_no, x.code, x.severity, x.part_number, (x.subject or {}).get("label"), x.ex_date, x.qty, x.days,
             x.message, x.action]
            for x in s.execute(select(MfgMrpExceptionRow).where(MfgMrpExceptionRow.run_id == r.id)
                               .order_by(MfgMrpExceptionRow.ex_no)).scalars()]
        sheets["demand"] = [["order_number", "line_no", "part_number", "qty", "due_date", "projected_date",
                             "late_days", "status", "priority", "program"]] + [
            [x.order_number, x.line_no, x.part_number, x.qty, x.due_date, x.projected_date, x.late_days, x.status,
             x.priority, x.program]
            for x in s.execute(select(MfgMrpDemandResultRow).where(MfgMrpDemandResultRow.run_id == r.id)
                               .order_by(MfgMrpDemandResultRow.due_date, MfgMrpDemandResultRow.order_number,
                                         MfgMrpDemandResultRow.line_no)).scalars()]
        sheets["items"] = [["part_number", "description", "make_buy", "uom", "llc", "on_hand", "gross_qty",
                            "existing_supply_qty", "planned_qty", "planned_count", "first_short_date", "short_qty",
                            "late_qty", "exception_count"]] + [
            [x.part_number, x.description, x.make_buy, x.uom, x.llc, x.on_hand, x.gross_qty, x.existing_supply_qty,
             x.planned_qty, x.planned_count, x.first_short_date, x.short_qty, x.late_qty, x.exception_count]
            for x in s.execute(select(MfgMrpItemResultRow).where(MfgMrpItemResultRow.run_id == r.id)
                               .order_by(MfgMrpItemResultRow.llc, MfgMrpItemResultRow.part_number)).scalars()]
        name = f"superplanner-mrp-run-{r.run_no}.{fmt}"
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
        return buf.getvalue(), name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
    return buf.getvalue(), name, "application/zip"


# ---------------------------------------------------------------- planned-order conversion (8.14)


def _convert_response(s: Session, rows: list[MfgMrpPlannedOrderRow]) -> dict[str, Any]:
    converted = []
    wos: dict[str, dict[str, Any]] = {}
    prs: dict[str, dict[str, Any]] = {}
    pr_lines: dict[str, int] = {}
    for p in sorted(rows, key=lambda x: x.planned_no):
        c = {"planned_order_id": p.id, "type": p.converted_type, "id": p.converted_id, "number": p.converted_number}
        if p.converted_type == "pr" and p.converted_id:
            ln = s.execute(select(MfgPurchaseLineRow.line_no).join(
                MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.line_id == MfgPurchaseLineRow.id, isouter=True).where(
                MfgPurchaseLineRow.doc_id == p.converted_id, MfgPurchaseLineRow.item_id == p.item_id)
                .order_by(MfgPurchaseLineRow.line_no)).scalars().first()
            c["line_no"] = ln
            pr_lines[p.converted_id] = pr_lines.get(p.converted_id, 0) + 1
            prs[p.converted_id] = {"id": p.converted_id, "number": p.converted_number}
        elif p.converted_type == "wo":
            wos[p.converted_id] = {"id": p.converted_id, "number": p.converted_number}
        converted.append(c)
    docs = {d.id: d for d in s.execute(select(MfgPurchaseDocRow).where(MfgPurchaseDocRow.id.in_(sorted(prs))))
            .scalars()} if prs else {}
    sids = sorted({d.supplier_id for d in docs.values() if d.supplier_id})
    sups = {x.id: ref(x) for x in s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id.in_(sids))).scalars()} \
        if sids else {}
    pr_out = []
    for pid, v in prs.items():
        d = docs.get(pid)
        n = int(s.execute(select(func.count()).select_from(MfgPurchaseLineRow).where(
            MfgPurchaseLineRow.doc_id == pid)).scalar() or 0)
        pr_out.append({**v, "supplier": sups.get(d.supplier_id) if d and d.supplier_id else None, "line_count": n})
    return {"converted": converted, "created": {"work_orders": list(wos.values()), "purchase_requests": pr_out}}


def _replay_convert(s: Session, run_id: str, key: str, h: str) -> dict[str, Any] | None:
    from ...db.models import AuditEventRow

    ev = s.execute(select(AuditEventRow.details).where(
        AuditEventRow.entity_type == "mfg_mrp_run", AuditEventRow.action == "convert",
        AuditEventRow.entity_id == run_id, AuditEventRow.created_at > utcnow() - timedelta(hours=24),
        AuditEventRow.details["idempotency_key"].astext == key)).scalars().first()
    if ev is None:
        return None
    if ev.get("request_hash") != h:
        raise ApiError(409, "INV_IDEMPOTENCY_CONFLICT", "This Idempotency-Key was already used for another request.",
                       {})
    rows = list(s.execute(select(MfgMrpPlannedOrderRow).where(
        MfgMrpPlannedOrderRow.id.in_(ev.get("planned_order_ids") or []))).scalars())
    return _convert_response(s, rows)


def convert(ctx: AppContext, run_id: str, body: Any, idem: str | None) -> tuple[dict[str, Any], bool]:
    """Firm / release planned orders of the latest live run into WOs and PRs, exactly once, all-or-nothing.
    Returns `(response, replayed)` (C17: a replay answers 200 with `Idempotent-Replay: true`)."""
    h = request_hash({"run": run_id, **body.model_dump(mode="json")})
    if idem:
        with read_tx(ctx) as s:
            out = _replay_convert(s, run_id, idem, h)
            if out is not None:
                return out, True

    def fn(s: Session) -> tuple[dict[str, Any], bool]:
        from .purchasing import doc_record  # noqa: F401  (import side effects none; keeps module load lazy)
        from .workorders import new_wo, reserve_in

        run = _get_run(s, run_id, lock=True)
        if idem:
            out = _replay_convert(s, run_id, idem, h)
            if out is not None:
                return out, True
        if run.status != "completed":
            raise ApiError(409, "MRP_RUN_NOT_COMPLETED", f"Run {run.run_no} is {run.status}.", {"status": run.status})
        latest = latest_live(s)
        if run.kind != "live" or latest is None or latest.id != run.id:
            raise ApiError(409, "MRP_RUN_NOT_LATEST", "Planned orders can only be converted from the latest live MRP "
                           "run.", {"latest_run_id": latest.id if latest else None})
        ids = [o.id for o in body.orders]
        if len(set(ids)) != len(ids):
            raise ApiError(422, "VALIDATION_ERROR", "Each planned order may be listed once.",
                           {"errors": [{"loc": ["body", "orders"], "msg": "duplicate ids", "type": "value_error"}]})
        rows = {p.id: p for p in s.execute(select(MfgMrpPlannedOrderRow).where(
            MfgMrpPlannedOrderRow.run_id == run.id, MfgMrpPlannedOrderRow.id.in_(sorted(ids)))
            .order_by(MfgMrpPlannedOrderRow.id).with_for_update().execution_options(populate_existing=True)).scalars()}
        for i, oid in enumerate(ids):
            if oid not in rows:
                raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Planned order {oid!r} is not part of this run.",
                               {"loc": ["body", "orders", i, "id"], "id": oid})
        done = sorted(p.id for p in rows.values() if p.status == "converted")
        if done:
            raise ApiError(409, "MRP_ALREADY_CONVERTED", f"{len(done)} planned order(s) were converted already.",
                           {"ids": done})
        ds = repo.load_dataset(s)
        d = today(s)
        now = utcnow()
        actor = actor_id()
        add_pr = None
        if body.add_to_pr_id:
            add_pr = repo_m2.lock_docs(s, MfgPurchaseDocRow, [body.add_to_pr_id])
            if not add_pr or add_pr[0].doc_type != "pr":
                raise not_found("Purchase request", body.add_to_pr_id)
            add_pr = add_pr[0]
            if add_pr.status != "draft":
                raise ApiError(422, "MFG_INVALID_STATE", "Planned orders can only be added to a draft purchase "
                               "request.", {"status": add_pr.status})
        from ....mfg.workorders import generate_components

        wo_reserve: list[Any] = []
        buys: list[tuple[MfgMrpPlannedOrderRow, Any]] = []
        for o in sorted(body.orders, key=lambda o: rows[o.id].planned_no):
            p = rows[o.id]
            if p.kind == "make":
                qty = o.qty or p.qty
                due = o.need_date or p.need_date
                start = o.start_date or (p.start_date if o.need_date is None else None)
                seg = p.segment or {}
                serial = seg.get("serial_from")
                if serial is not None and o.qty is not None and abs(o.qty - p.qty) > EPS:
                    raise ApiError(422, "DEM_SERIAL_QTY_MISMATCH", "The quantity of a serial-segment order cannot "
                                   "change.", {"loc": ["body", "orders", ids.index(o.id), "qty"]})
                pegs = MS.peg_list(p)
                peg = pegs[0] if pegs else {}
                inp = WorkOrderInput(item_id=p.item_id, qty=qty, due_date=due,
                                     start_date=min(start, due) if start else None, priority=5,
                                     serial_from=serial, serial_to=seg.get("serial_to"),
                                     demand_line_id=peg.get("demand_line_id"), note=f"MRP run {run.run_no} P-{p.planned_no}")
                from ....mfg.mrp.explode import order_components

                dirs = MS.directives_of(p)
                if dirs and abs(qty - p.qty) <= EPS:
                    gen = order_components(ds, p.item_id, qty, on=max(inp.start_date or p.start_date, run.as_of),
                                           serial=serial, directives=dirs, order_key=p.order_key)
                else:
                    gen = generate_components(ds, p.item_id, qty, on=max(inp.start_date or p.start_date, run.as_of),
                                              serial=serial)
                w, _warn = new_wo(s, ds, inp, source="mrp", status="released" if body.mode == "release" else "planned",
                                  run_no=run.run_no, planned_no=p.planned_no, bom_id=p.bom_id, routing_id=p.routing_id,
                                  generated=gen)
                p.converted_type, p.converted_id, p.converted_number = "wo", w.id, w.number
                if body.mode == "release" and body.reserve:
                    wo_reserve.append(w)
            else:
                buys.append((p, o))
            p.status, p.converted_at, p.converted_by = "converted", now, actor
        # buy orders -> PRs
        groups: dict[str, list[tuple[MfgMrpPlannedOrderRow, Any]]] = {}
        for p, o in buys:
            sup = o.supplier_id or p.supplier_id
            if add_pr is not None:
                if add_pr.supplier_id and sup and sup != add_pr.supplier_id:
                    raise ApiError(422, "PUR_SUPPLIER_REQUIRED", "The purchase request has another supplier.",
                                   {"loc": ["body", "add_to_pr_id"]})
                key = add_pr.id
            else:
                key = (sup or "-") if body.pr_grouping == "per_supplier" else p.id
            groups.setdefault(key, []).append((p, o))
        its = items(s, [p.item_id for p, _o in buys])
        prices = {(r.item_id, r.supplier_id): r.unit_price for r in s.execute(select(MfgItemSupplierRow).where(
            MfgItemSupplierRow.item_id.in_(sorted({p.item_id for p, _o in buys})))).scalars()} if buys else {}
        for key in sorted(groups):
            members = groups[key]
            if add_pr is not None:
                doc = add_pr
                base_no = int(s.execute(select(func.coalesce(func.max(MfgPurchaseLineRow.line_no), 0)).where(
                    MfgPurchaseLineRow.doc_id == doc.id)).scalar() or 0)
            else:
                sup = members[0][1].supplier_id or members[0][0].supplier_id
                number = repo_m2.next_number(s, "PR", repo_m2.number_taken(s, MfgPurchaseDocRow, doc_type="pr"))
                sp = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id == sup)).scalars().first() if sup \
                    else None
                doc = MfgPurchaseDocRow(id=new_id("pdc_"), doc_type="pr", number=number,
                                        status="submitted" if body.mode == "release" else "draft",
                                        supplier_id=sp.id if sp else None, currency=sp.currency if sp else "",
                                        order_date=None, note=f"MRP run {run.run_no}", source="mrp",
                                        source_run_no=run.run_no,
                                        submitted_at=now if body.mode == "release" else None,
                                        submitted_by=actor if body.mode == "release" else None, approved_at=None,
                                        approved_by=None, rejected_reason="", external_ref=None, idempotency_key=None,
                                        row_version=1, created_at=now, updated_at=now)
                s.add(doc)
                s.flush()
                base_no = 0
            lines, scheds = [], []
            for k, (p, o) in enumerate(members, 1):
                it = its.get(p.item_id)
                qty = o.qty or p.qty
                rd = it.receiving_days if it else 0
                dock = (o.need_date - timedelta(days=rd)) if o.need_date else (p.dock_date or p.need_date)
                ln = MfgPurchaseLineRow(id=new_id("pln_"), doc_id=doc.id, line_no=base_no + 10 * k, item_id=p.item_id,
                                        unit_price=prices.get((p.item_id, doc.supplier_id)), status="open",
                                        source_pr_line_id=None, note=f"P-{p.planned_no}", row_version=1,
                                        created_at=now, updated_at=now)
                lines.append(ln)
                scheds.append(MfgPurchaseScheduleRow(id=new_id("psc_"), line_id=ln.id, seq=1, requested_date=dock,
                                                     confirmed_date=None, qty=qty, received_qty=0.0, closed=False,
                                                     row_version=1, created_at=now, updated_at=now))
                p.converted_type, p.converted_id, p.converted_number = "pr", doc.id, doc.number
            s.add_all(lines)
            s.flush()
            s.add_all(scheds)
            touch(doc, now)
            s.flush()
        for w in wo_reserve:
            from ..db_models_m2 import MfgWoComponentRow

            comps = list(s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == w.id)).scalars())
            reserve_in(s, w, comps, None)
        s.flush()
        del d
        audit(s, "mrp_run", run.id, "convert", {"mode": body.mode, "orders": len(ids), "idempotency_key": idem,
                                                "request_hash": h, "planned_order_ids": ids})
        return _convert_response(s, list(rows.values())), False

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- shortage dashboard (#163)


def shortages(ctx: AppContext, horizon_days: int) -> dict[str, Any]:
    from .purchasing import schedule_rows
    from .workorders import kitting_check_in

    with read_tx(ctx) as s:
        run = latest_live(s)
        d = today(s)
        late: list[dict[str, Any]] = []
        short: list[dict[str, Any]] = []
        counts = {"late_demand": 0, "short_items": 0, "overdue_schedules": 0, "wo_short": 0}
        if run is not None:
            D = MfgMrpDemandResultRow
            rows = list(s.execute(select(D).where(D.run_id == run.id, D.late_days > 0)
                                  .order_by(D.late_days.desc(), D.due_date, D.order_number).limit(50)).scalars())
            counts["late_demand"] = int(s.execute(select(func.count()).select_from(D).where(
                D.run_id == run.id, D.late_days > 0)).scalar() or 0)
            irefs = _item_refs_from_results(s, run.id, [x.item_id for x in rows])
            late = [MS.demand_row(x, irefs.get(x.item_id) or {"id": x.item_id, "part_number": x.part_number})
                    for x in rows]
            R = MfgMrpItemResultRow
            irows = list(s.execute(select(R).where(R.run_id == run.id, R.short_qty > EPS)
                                   .order_by(R.first_short_date.asc().nulls_last(), R.part_number).limit(100)).scalars())
            counts["short_items"] = int(s.execute(select(func.count()).select_from(R).where(
                R.run_id == run.id, R.short_qty > EPS)).scalar() or 0)
            short = [MS.item_row(run.id, x) for x in irows]
        S, Ln, Dc = MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow
        from ....mfg import purchasing as PUR
        from sqlalchemy import or_

        dock = func.coalesce(S.confirmed_date, S.requested_date)
        conds = [S.closed.is_(False), S.qty - S.received_qty > EPS, Ln.status == "open", dock < d,
                 or_((Dc.doc_type == "po") & Dc.status.in_(PUR.PO_SUPPLY_STATUSES),
                     (Dc.doc_type == "pr") & Dc.status.in_(PUR.PR_SUPPLY_STATUSES))]
        orows = s.execute(select(S, Ln, Dc).join(Ln, Ln.id == S.line_id).join(Dc, Dc.id == Ln.doc_id).where(*conds)
                          .order_by(dock, Dc.number, Ln.line_no, S.seq).limit(100)).all()
        counts["overdue_schedules"] = int(s.execute(select(func.count()).select_from(S).join(Ln, Ln.id == S.line_id)
                                                    .join(Dc, Dc.id == Ln.doc_id).where(*conds)).scalar() or 0)
        overdue = schedule_rows(s, orows, d)
        kit = kitting_check_in(s, None, "start_date", horizon_days, statuses=("released", "in_progress", "planned"))
        counts["wo_short"] = sum(1 for r in kit["rows"] if not r["kit_complete"])
        return {"run": _run_head(s, run) if run is not None else None, "counts": counts, "late_demand": late,
                "short_items": short, "overdue_supply": overdue, "wo_shortages": kit["items_short"][:100]}


def _unused() -> None:  # pragma: no cover - keeps imports referenced for static checkers
    _ = (MfgItemRow, iref, datetime, UTC)
