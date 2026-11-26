"""Inventory optimisation service (M8-DESIGN 5, 11 I1-I4): ABC/XYZ classes and safety-stock proposals.

A run (job `ss_run`) proposes for every forecast item of the version (active by default) and every item with
history; dependent-only items are skipped. Classes are written to the item planning rows (computed, read-only).
Proposals change nothing until approved: `decide` (bulk) writes `mfg_items.safety_stock` with the audit reason
`SSP-000123 approved`. Never automatic (0.5).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg.forecast import history as H
from ....mfg.forecast.consume import spread
from ....mfg.invopt import classify, safety
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow
from ..db_models_m2 import MfgItemSupplierRow, MfgInvTransactionRow, MfgPurchaseScheduleRow
from ..db_models_m8 import MfgDemandHistoryRow, MfgForecastRunRow, MfgForecastVersionRow, MfgItemPlanningRow, \
    MfgSsLineRow, MfgSsRunRow
from . import m8_examples
from .common import audit, ilike, read_tx, write_tx
from .m8common import (PLANNING_DEFAULTS, item_map, next_number, packaging, page, planning_rows, settings_of,
                       start_job, today, work_calendar)

D_DAYS = 90


def _run_record(r: MfgSsRunRow) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "params": r.params, "status": r.status,
            "forecast_version_id": r.forecast_version_id, "summary": r.summary, "error": r.error,
            "created_at": r.created_at, "finished_at": r.finished_at}


def list_runs(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        n = int(s.execute(select(func.count()).select_from(MfgSsRunRow)).scalar() or 0)
        rows = s.execute(select(MfgSsRunRow).order_by(MfgSsRunRow.created_at.desc(), MfgSsRunRow.id.desc())
                         .limit(limit).offset(offset)).scalars()
        return page([_run_record(r) for r in rows], n, limit, offset)


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _run_record(repo.get_row(s, MfgSsRunRow, run_id, what="Safety-stock run"))


def _new_run(s: Session, actor: str, params: dict[str, Any], status: str) -> MfgSsRunRow:
    from .forecast import active_version

    vid = params.get("forecast_version_id")
    if vid:
        repo.get_row(s, MfgForecastVersionRow, vid, what="Forecast version")
    else:
        v = active_version(s)
        vid = v.id if v else None
    now = utcnow()
    r = MfgSsRunRow(id=new_id("ssp_"), number=next_number(s, "SSP", MfgSsRunRow), params=params, status=status,
                    forecast_version_id=vid, summary={}, error=None, actor_id=actor, finished_at=None, row_version=1,
                    created_at=now, updated_at=now)
    s.add(r)
    s.flush()
    return r


def create_run(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        r = _new_run(s, a.user_id, body.model_dump(mode="json"), "queued")
        _rid, job = start_job(s, ctx, "ss_run", r.owner_id, {"run_id": r.id})
        audit(s, "ss_run", r.id, "create", r.params)
        rec = _run_record(r)
    ctx.jobs.dispatch(job)
    return rec


def _receipt_delays(s: Session, item_ids: list[str]) -> dict[str, list[float]]:
    """item -> (receipt date - confirmed (else requested) date) in days of the PO receipts, oldest first."""
    if not item_ids:
        return {}
    q = (select(MfgInvTransactionRow.item_id, MfgInvTransactionRow.txn_date,
                func.coalesce(MfgPurchaseScheduleRow.confirmed_date, MfgPurchaseScheduleRow.requested_date))
         .join(MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.id == MfgInvTransactionRow.schedule_id)
         .where(MfgInvTransactionRow.txn_type == "po_receipt", MfgInvTransactionRow.qty > 0,
                MfgInvTransactionRow.item_id.in_(item_ids))
         .order_by(MfgInvTransactionRow.seq))
    out: dict[str, list[float]] = defaultdict(list)
    for item_id, got, due in s.execute(q):
        out[item_id].append(float((got - due).days))
    return out


def compute(s: Session, run: MfgSsRunRow) -> list[dict[str, Any]]:
    from .forecast import version_lines_map

    st = settings_of(s)
    asof = today(s)
    cal = work_calendar(s)
    params = run.params or {}
    lines: dict[str, list[tuple[date, float]]] = {}
    bucket = st.forecast_bucket
    results: dict[str, dict[str, Any]] = {}
    if run.forecast_version_id:
        v = s.get(MfgForecastVersionRow, run.forecast_version_id)
        bucket = v.bucket
        lines = version_lines_map(s, v.id)
        fr = s.get(MfgForecastRunRow, v.run_id) if v.run_id else None
        results = ((fr.results or {}).get("items") or {}) if fr else {}
    hist_items = set(s.execute(select(MfgDemandHistoryRow.item_id).distinct().where(
        MfgDemandHistoryRow.bucket == bucket)).scalars())
    ids = sorted(set(lines) | hist_items)
    if params.get("item_ids"):
        ids = [i for i in ids if i in set(params["item_ids"])]
    items = item_map(s, ids)
    plan = planning_rows(s, ids)
    packs = packaging(s, ids)
    hist = H.merge_sources(H.as_points(s.execute(select(MfgDemandHistoryRow).where(
        MfgDemandHistoryRow.bucket == bucket, MfgDemandHistoryRow.item_id.in_(ids))).scalars())) if ids else {}
    last = H.last_closed_period(asof, bucket)
    per_year = 52 if bucket == "w" else 12
    # working days per period (next 12 periods) and in the 90-day window
    p0 = H.period_start(asof, bucket)
    wd_period = sum(1 for k in range(per_year) for d in spread(H.add_periods(p0, k, bucket), 1.0, bucket,
                                                               cal.is_workday)) / per_year
    window = [asof + timedelta(days=k) for k in range(D_DAYS)]
    wd_window = sum(1 for d in window if cal.is_workday(d)) or 1
    sup = {}
    for r in s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.item_id.in_(ids),
                                                        MfgItemSupplierRow.active.is_(True))
                       .order_by(MfgItemSupplierRow.preferred.desc(), MfgItemSupplierRow.id)).scalars() if ids else []:
        sup.setdefault(r.item_id, r)
    delays = _receipt_delays(s, ids)
    values: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}
    for i in ids:
        it = items.get(i)
        if it is None:
            continue
        ser = H.build_series(hist, [i], last, bucket, st.outlier_clean)[i]
        if i in lines:
            daily: dict[date, float] = defaultdict(float)
            for p, q in lines[i]:
                for d, v in spread(p, q, bucket, cal.is_workday).items():
                    daily[d] += v
            d_day = sum(daily.get(d, 0.0) for d in window) / wd_window
            vol = sum(q for _p, q in sorted(lines[i])[:per_year])
        else:
            tail = ser.values[-per_year:]
            vol = sum(tail)
            d_day = (sum(tail) / max(len(tail), 1)) / max(wd_period, 1.0)
        if d_day <= 0 and not ser.values:
            continue                                    # dependent-only item
        res = results.get(i)
        if res is not None:
            rmse1, mean, cls, adi = res["rmse1"], res["mean"], res["demand_class"], res.get("adi")
            nz_cv = res.get("nonzero_cv")
        else:
            vals = ser.values
            mean = sum(vals) / len(vals) if vals else 0.0
            rmse1 = math.sqrt(sum((x - mean) ** 2 for x in vals) / max(len(vals) - 1, 1)) if vals else 0.0
            cls, adi, nz_cv = None, None, None
        cost = it.standard_cost
        values[i] = vol * (cost if cost and cost > 0 else 1.0)
        pl = plan.get(i)
        if it.make_buy == "buy":
            srow = sup.get(i)
            lt = float((srow.lead_time_days if srow and srow.lead_time_days is not None else it.lead_time_days) or 0)
            lt += float(it.receiving_days or 0)
        else:
            lt = float(it.lead_time_days or 0) + float((pl.post_days if pl and pl.post_days is not None else 0))
        pack_level = (pl.order_pack_level if pl else None)
        pk = packs.get(i, {})
        rows[i] = {"item": it, "d": d_day, "sigma_d": rmse1 / math.sqrt(max(wd_period, 1.0)), "lt": lt,
                   "sigma_lt": safety.lt_sigma(delays.get(i, [])), "cv": classify.cv(rmse1, mean, cls, nz_cv, adi),
                   "pack": pk.get(pack_level) if pack_level else None, "sl_override": pl.service_level if pl else None,
                   "no_cost": not (cost and cost > 0)}
    abc = classify.abc(values, st.abc_cutoffs)
    out = []
    for i, r in rows.items():
        a, x = abc[i], classify.xyz(r["cv"], st.xyz_cutoffs)
        sl = r["sl_override"] or st.sl_matrix[a + x]
        z = safety.z_of(sl)
        prop = safety.propose(z, r["d"], r["sigma_d"], r["lt"], r["sigma_lt"], r["pack"], st.ss_max_cover_days)
        it = r["item"]
        flags = list(prop.flags) + (["FC_NO_COST"] if r["no_cost"] else [])
        out.append({"item_id": i, "abc": a, "xyz": x, "service_level": sl, "z": round(z, 6),
                    "d_day": round(r["d"], 6), "sigma_d_day": round(r["sigma_d"], 6), "lt_days": r["lt"],
                    "sigma_lt_days": round(r["sigma_lt"], 6), "current_ss": float(it.safety_stock or 0),
                    "proposed_ss": prop.proposed,
                    "delta_value": round((prop.proposed - float(it.safety_stock or 0)) * float(it.standard_cost or 0),
                                         6), "flags": flags})
    return out


def _summary(lines: list[dict[str, Any]], costs: dict[str, float]) -> dict[str, Any]:
    matrix: dict[str, dict[str, float]] = {a + x: {"count": 0, "value": 0.0} for a in "ABC" for x in "XYZ"}
    for ln in lines:
        m = matrix[ln["abc"] + ln["xyz"]]
        m["count"] += 1
        m["value"] = round(m["value"] + ln["proposed_ss"] * costs.get(ln["item_id"], 0.0), 6)
    return {"lines": len(lines), "pending": len(lines), "delta_value": round(sum(x["delta_value"] for x in lines), 6),
            "capped": sum(1 for x in lines if "SS_CAPPED" in x["flags"]), "matrix": matrix}


def run_sync(s: Session, run: MfgSsRunRow) -> None:
    lines = compute(s, run)
    plan = planning_rows(s, [x["item_id"] for x in lines])
    costs = {i: float(r.standard_cost or 0) for i, r in item_map(s, [x["item_id"] for x in lines]).items()}
    now = utcnow()
    rows = [{"id": new_id("ssl_"), "owner_id": run.owner_id, "run_id": run.id, **ln, "decision": "pending",
             "decided_by": None, "decided_at": None} for ln in lines]
    if rows:
        s.execute(MfgSsLineRow.__table__.insert(), rows)
    for ln in lines:                                  # computed classes on the item planning rows
        pr = plan.get(ln["item_id"])
        if pr is None:
            pr = MfgItemPlanningRow(id=new_id("ipn_"), item_id=ln["item_id"], **PLANNING_DEFAULTS, abc=None,
                                    xyz=None, row_version=1, created_at=now, updated_at=now)
            s.add(pr)
        pr.abc, pr.xyz = ln["abc"], ln["xyz"]
    run.status, run.finished_at, run.summary = "completed", now, _summary(lines, costs)
    s.flush()


def run_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    run_id = info["params"]["run_id"]
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgSsRunRow, run_id, with_for_update=True)
            if r is None:
                return {"error": "run gone"}
            r.status = "running"
            run_sync(s, r)
            return {"run_id": run_id, "lines": r.summary.get("lines", 0)}
    except Exception as exc:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgSsRunRow, run_id, with_for_update=True)
            if r is not None:
                r.status, r.finished_at, r.error = "failed", utcnow(), f"{exc.__class__.__name__}: {exc}"[:500]
        raise


def _line_record(ln: MfgSsLineRow, pn: str | None) -> dict[str, Any]:
    cover = round(ln.proposed_ss / ln.d_day, 6) if ln.d_day > 0 else None
    return {"id": ln.id, "run_id": ln.run_id, "item_id": ln.item_id, "part_number": pn, "abc": ln.abc, "xyz": ln.xyz,
            "service_level": ln.service_level, "z": ln.z, "d_day": ln.d_day, "sigma_d_day": ln.sigma_d_day,
            "lt_days": ln.lt_days, "sigma_lt_days": ln.sigma_lt_days, "current_ss": ln.current_ss,
            "proposed_ss": ln.proposed_ss, "delta_value": ln.delta_value, "cover_days": cover, "flags": ln.flags,
            "decision": ln.decision, "decided_by": ln.decided_by, "decided_at": ln.decided_at}


def list_lines(ctx: AppContext, run_id: str, decision: str | None, abc: str | None, xyz: str | None, q: str | None,
               limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        repo.get_row(s, MfgSsRunRow, run_id, what="Safety-stock run")
        qq = select(MfgSsLineRow, MfgItemRow.part_number).join(MfgItemRow, MfgItemRow.id == MfgSsLineRow.item_id) \
            .where(MfgSsLineRow.run_id == run_id)
        if decision:
            qq = qq.where(MfgSsLineRow.decision == decision)
        if abc:
            qq = qq.where(MfgSsLineRow.abc == abc)
        if xyz:
            qq = qq.where(MfgSsLineRow.xyz == xyz)
        if q:
            qq = qq.where(ilike(MfgItemRow.part_number, q))
        n = int(s.execute(select(func.count()).select_from(qq.subquery())).scalar() or 0)
        rows = s.execute(qq.order_by(MfgSsLineRow.delta_value.desc(), MfgItemRow.part_number).limit(limit)
                         .offset(offset)).all()
        return page([_line_record(ln, pn) for ln, pn in rows], n, limit, offset)


def decide(ctx: AppContext, a: Any, run_id: str, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        run = repo.get_row(s, MfgSsRunRow, run_id, what="Safety-stock run", lock=True)
        if run.status != "completed":
            raise ApiError(409, "MFG_INVALID_STATE", "Only a completed run can be decided.", {"status": run.status})
        lines = list(s.execute(select(MfgSsLineRow).where(MfgSsLineRow.run_id == run.id,
                                                          MfgSsLineRow.id.in_(body.line_ids))
                               .with_for_update()).scalars())
        found = {ln.id for ln in lines}
        missing = [i for i in body.line_ids if i not in found]
        if missing:
            raise ApiError(404, "NOT_FOUND", "Proposal line not found.", {"id": missing[0]})
        now = utcnow()
        decided = skipped = updated = 0
        reason = f"{run.number} {body.decision}: {body.reason}"[:500]
        items = item_map(s, [ln.item_id for ln in lines if ln.decision == "pending"])
        for ln in lines:
            if ln.decision != "pending":
                skipped += 1
                continue
            ln.decision, ln.decided_by, ln.decided_at = body.decision, a.user_id, now
            decided += 1
            if body.decision == "approved":
                it = items[ln.item_id]
                old = it.safety_stock
                it.safety_stock = ln.proposed_ss
                it.row_version += 1
                it.updated_at = now
                updated += 1
                audit(s, "item", it.id, "update", {"source": run.number, "line_id": ln.id},
                      before={"safety_stock": old}, after={"safety_stock": ln.proposed_ss},
                      reason=f"{run.number} approved: {body.reason}"[:500])
        pending = int(s.execute(select(func.count()).select_from(MfgSsLineRow).where(
            MfgSsLineRow.run_id == run.id, MfgSsLineRow.decision == "pending")).scalar() or 0)
        run.summary = {**(run.summary or {}), "pending": pending}
        audit(s, "ss_run", run.id, "decide", {"decision": body.decision, "lines": decided, "skipped": skipped},
              reason=reason)
        return {"decided": decided, "skipped": skipped, "items_updated": updated}


__getattr__ = m8_examples.module_getattr(__name__)
