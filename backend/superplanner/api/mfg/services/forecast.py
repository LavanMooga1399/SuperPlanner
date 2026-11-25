"""Forecasting service (M8-DESIGN 4, 11 F1-F17): demand history, forecast runs (job `forecast_run`), versions,
overrides, consumption for MRP, item view and accuracy.

- History refresh (F3, job `history_refresh`): `ship` transactions (basis `shipments`) or customer demand lines by
  due date (basis `orders`) aggregated per item x period into `ledger` rows (manual cleaned values kept); then the
  automatic cleaned values (median +/- 5 MAD) are stored on every row of the item-period.
- A run (F5) is queued as a duty run; the body (`run_job_body`) selects the models for every forecast item and,
  by default, creates a `draft` version.
- Versions are immutable once active; overrides change drafts only (409 `FC_VERSION_LOCKED` otherwise). Every
  override create/remove is audited with the old/new final values and its reason.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ....mfg.forecast import accuracy as ACC
from ....mfg.forecast import history as H
from ....mfg.forecast import select as SEL
from ....mfg.forecast.consume import OrderDemand, consume
from ....mfg.forecast.model import ForecastSnap
from ....mfg.forecast.overrides import Override, apply
from ....mfg.invopt import classify
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow
from ..db_models_m2 import MfgDemandLineRow, MfgDemandOrderRow, MfgInvTransactionRow
from ..db_models_m8 import (MfgDemandHistoryRow, MfgForecastLineRow, MfgForecastOverrideRow, MfgForecastRunRow,
                            MfgForecastVersionRow, MfgItemPlanningRow)
from . import m8_examples
from .common import audit, check_version, jsonable, read_tx, write_tx
from .m8common import iref, item_map, next_number, page, planning_rows, settings_of, start_job, today, work_calendar


def _locked(what: str, status: str) -> ApiError:
    return ApiError(409, "FC_VERSION_LOCKED", f"{what} can only be changed while the version is a draft.",
                    {"status": status})


# ---------------------------------------------------------------- history (F1-F3)

def _hist_record(r: MfgDemandHistoryRow) -> dict[str, Any]:
    cleaned = r.manual_qty if r.manual_qty is not None else r.cleaned_qty
    return {"id": r.id, "item_id": r.item_id, "period_start": r.period_start, "bucket": r.bucket, "qty": r.qty,
            "cleaned_qty": cleaned, "source": r.source, "outlier": r.cleaned_qty is not None and r.manual_qty is None,
            "updated_at": r.updated_at}


def list_history(ctx: AppContext, item_id: str | None, bucket: str | None, from_: date | None, to: date | None,
                 limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        q = select(MfgDemandHistoryRow)
        if item_id:
            q = q.where(MfgDemandHistoryRow.item_id == item_id)
        q = q.where(MfgDemandHistoryRow.bucket == (bucket or settings_of(s).forecast_bucket))
        if from_:
            q = q.where(MfgDemandHistoryRow.period_start >= from_)
        if to:
            q = q.where(MfgDemandHistoryRow.period_start <= to)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = s.execute(q.order_by(MfgDemandHistoryRow.item_id, MfgDemandHistoryRow.period_start,
                                    MfgDemandHistoryRow.source).limit(limit).offset(offset)).scalars()
        return page([_hist_record(r) for r in rows], n, limit, offset)


def _ledger_quantities(s: Session, bucket: str, basis: str) -> dict[tuple[str, date], float]:
    unit = "week" if bucket == "w" else "month"
    if basis == "orders":
        per = func.date_trunc(unit, MfgDemandLineRow.due_date)
        q = (select(MfgDemandLineRow.item_id, per, func.sum(MfgDemandLineRow.qty))
             .join(MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id)
             .where(MfgDemandOrderRow.demand_type == "customer", MfgDemandOrderRow.status != "cancelled")
             .group_by(MfgDemandLineRow.item_id, per))
        sign = 1.0
    else:
        per = func.date_trunc(unit, MfgInvTransactionRow.txn_date)
        q = (select(MfgInvTransactionRow.item_id, per, func.sum(MfgInvTransactionRow.qty))
             .where(MfgInvTransactionRow.txn_type == "ship").group_by(MfgInvTransactionRow.item_id, per))
        sign = -1.0
    out: dict[tuple[str, date], float] = {}
    for item_id, p, qty in s.execute(q):
        d = p.date() if isinstance(p, datetime) else p
        v = sign * float(qty or 0.0)
        if v > 1e-9:
            out[(item_id, d)] = round(v, 6)
    return out


def refresh(s: Session) -> dict[str, Any]:
    """History refresh in the caller's transaction (F3 and the `history_refresh` job)."""
    st = settings_of(s)
    bucket = st.forecast_bucket
    agg = _ledger_quantities(s, bucket, st.history_basis)
    existing = {(r.item_id, r.period_start): r for r in s.execute(select(MfgDemandHistoryRow).where(
        MfgDemandHistoryRow.bucket == bucket, MfgDemandHistoryRow.source == "ledger")).scalars()}
    now = utcnow()
    written = 0
    for key, qty in agg.items():
        r = existing.pop(key, None)
        if r is None:
            s.add(MfgDemandHistoryRow(id=new_id("dhi_"), item_id=key[0], period_start=key[1], bucket=bucket, qty=qty,
                                      cleaned_qty=None, manual_qty=None, source="ledger", updated_at=now))
            written += 1
        elif abs(r.qty - qty) > 1e-9:
            r.qty, r.updated_at = qty, now
            written += 1
    for r in existing.values():                     # postings reversed away: no ledger demand left
        if r.manual_qty is None:
            s.delete(r)
            written += 1
    s.flush()
    rows = list(s.execute(select(MfgDemandHistoryRow).where(MfgDemandHistoryRow.bucket == bucket)).scalars())
    pts = H.merge_sources(H.as_points(rows))
    last = H.last_closed_period(today(s), bucket)
    outliers = 0
    by_key: dict[tuple[str, date], list[MfgDemandHistoryRow]] = defaultdict(list)
    for r in rows:
        by_key[(r.item_id, r.period_start)].append(r)
    for item_id, ip in pts.items():
        vals = H.cleaned_values(ip, bucket, last) if st.outlier_clean else {}
        for p in ip:
            cv, flag = vals.get(p, (None, False))
            outliers += int(flag)
            for r in by_key[(item_id, p)]:
                if (r.cleaned_qty or None) != cv:
                    r.cleaned_qty = cv
    return {"rows_written": written, "items": len(pts), "periods": len({p for _i, p in by_key}),
            "outliers": outliers}


def refresh_history(ctx: AppContext, a: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        out = refresh(s)
        audit(s, "demand_history", None, "refresh", out)
        return out


def refresh_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        return refresh(s)


def update_history(ctx: AppContext, a: Any, history_id: str, body: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        r = repo.get_row(s, MfgDemandHistoryRow, history_id, what="History row", lock=True)
        before = _hist_record(r)
        # None = the planner restores the raw value (an automatic clip is undone)
        r.manual_qty = r.qty if body.cleaned_qty is None else float(body.cleaned_qty)
        r.updated_at = utcnow()
        rec = _hist_record(r)
        audit(s, "demand_history", r.id, "update", {"reason": body.reason, "item_id": r.item_id,
                                                    "period_start": r.period_start.isoformat()},
              before={"cleaned_qty": before["cleaned_qty"]}, after={"cleaned_qty": rec["cleaned_qty"]},
              reason=body.reason)
        return rec


# ---------------------------------------------------------------- runs (F4-F6)

def _run_record(r: MfgForecastRunRow, version_id: str | None = None) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "params": r.params, "status": r.status, "as_of": r.as_of,
            "bucket": r.bucket, "first_period": r.first_period, "item_count": r.item_count, "summary": r.summary,
            "version_id": version_id, "error": r.error, "started_at": r.started_at, "finished_at": r.finished_at,
            "actor_id": r.actor_id}


def _run_version(s: Session, run_ids: list[str]) -> dict[str, str]:
    if not run_ids:
        return {}
    q = select(MfgForecastVersionRow.run_id, MfgForecastVersionRow.id).where(
        MfgForecastVersionRow.run_id.in_(run_ids)).order_by(MfgForecastVersionRow.created_at)
    return {rid: vid for rid, vid in s.execute(q)}


def list_runs(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        n = int(s.execute(select(func.count()).select_from(MfgForecastRunRow)).scalar() or 0)
        rows = list(s.execute(select(MfgForecastRunRow).order_by(MfgForecastRunRow.created_at.desc(),
                                                                 MfgForecastRunRow.id.desc())
                              .limit(limit).offset(offset)).scalars())
        vers = _run_version(s, [r.id for r in rows])
        return page([_run_record(r, vers.get(r.id)) for r in rows], n, limit, offset)


def create_run(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        st = settings_of(s)
        params = body.model_dump(mode="json")
        as_of = body.as_of or today(s)
        params.update(as_of=as_of.isoformat(), bucket=body.bucket or st.forecast_bucket,
                      horizon_periods=body.horizon_periods or st.horizon_periods)
        now = utcnow()
        r = MfgForecastRunRow(id=new_id("fcr_"), number=next_number(s, "FC", MfgForecastRunRow), params=params,
                              status="queued", as_of=as_of, bucket=params["bucket"], first_period=None, item_count=0,
                              summary={}, results=None, error=None, started_at=None, finished_at=None,
                              actor_id=a.user_id, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        _rid, job = start_job(s, ctx, "forecast_run", r.owner_id, {"run_id": r.id})
        audit(s, "forecast_run", r.id, "create", params)
        rec = _run_record(r)
    ctx.jobs.dispatch(job)
    return rec


def compute(s: Session, params: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any], date]:
    """The forecast of a run (pure engine on loaded data): -> (results per item, summary, first period)."""
    st = settings_of(s)
    bucket = params.get("bucket") or st.forecast_bucket
    horizon = int(params.get("horizon_periods") or st.horizon_periods)
    as_of = date.fromisoformat(params["as_of"]) if params.get("as_of") else today(s)
    plan = planning_rows(s)
    ids = params.get("item_ids") or sorted(i for i, p in plan.items() if p.forecast)
    like = {i: (plan[i].like_item_id, float(plan[i].like_factor or 1.0)) for i in ids
            if i in plan and plan[i].like_item_id}
    need = set(ids) | {v[0] for v in like.values()}
    rows = list(s.execute(select(MfgDemandHistoryRow).where(MfgDemandHistoryRow.bucket == bucket,
                                                            MfgDemandHistoryRow.item_id.in_(need))).scalars()) \
        if need else []
    pts = H.merge_sources(H.as_points(rows))
    last = H.last_closed_period(as_of, bucket)
    series = H.build_series(pts, ids, last, bucket, st.outlier_clean, like)
    res = SEL.select({i: series[i].values for i in ids}, bucket, horizon, params.get("methods"))
    items = item_map(s, ids)
    per_year = 52 if bucket == "w" else 12
    values: dict[str, float] = {}
    no_cost: set[str] = set()
    for i, r in res.items():
        vol = sum(r["forecast"][:per_year]) or sum(series[i].values[-per_year:])
        cost = items[i].standard_cost if i in items else None
        if cost is None or cost <= 0:
            no_cost.add(i)
            cost = 1.0
        values[i] = vol * cost
    abc = classify.abc(values, st.abc_cutoffs)
    for i, r in res.items():
        r["part_number"] = items[i].part_number if i in items else None
        r["abc"] = abc.get(i)
        if any(series[i].outliers):
            r["flags"].append("FC_OUTLIER")
        if series[i].like_item_id:
            r["flags"].append("FC_LIKE_ITEM")
        if i in no_cost:
            r["flags"].append("FC_NO_COST")
        if r["abc"] == "A" and r["holdout_wape"] is not None and r["holdout_wape"] > 0.5:
            r["flags"].append("FC_HIGH_ERROR")
        nz = [v for v in series[i].values if v > 0]
        if len(nz) >= 2:
            import statistics
            m = statistics.fmean(nz)
            r["nonzero_cv"] = statistics.pstdev(nz) / m if m > 0 else 0.0
    summary = ACC.backtest_summary(res, abc)
    return res, summary, H.add_periods(last, 1, bucket)


def run_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    run_id = info["params"]["run_id"]
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgForecastRunRow, run_id, with_for_update=True)
        if r is None:
            return {"error": "run gone"}
        r.status, r.started_at = "running", utcnow()
        params = dict(r.params)
    try:
        with ctx.db.read() as s:
            res, summary, first = compute(s, params)
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgForecastRunRow, run_id, with_for_update=True)
            r.status, r.finished_at, r.first_period = "completed", utcnow(), first
            r.item_count, r.summary, r.results = len(res), summary, {"items": res}
            vid = None
            if params.get("create_version", True):
                vid = _new_version(s, r, f"{r.number} statistical", copy_overrides=True, note="",
                                   actor=r.actor_id).id
            return {"run_id": run_id, "items": len(res), "version_id": vid}
    except Exception as exc:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgForecastRunRow, run_id, with_for_update=True)
            if r is not None:
                r.status, r.finished_at, r.error = "failed", utcnow(), f"{exc.__class__.__name__}: {exc}"[:500]
        raise


def run_now(s: Session, actor: str, params: dict[str, Any]) -> MfgForecastRunRow:
    """Synchronous run in the caller's transaction (sample data, nightly chain step)."""
    st = settings_of(s)
    params = {"as_of": today(s).isoformat(), "bucket": st.forecast_bucket, "horizon_periods": st.horizon_periods,
              "create_version": True, **params}
    now = utcnow()
    r = MfgForecastRunRow(id=new_id("fcr_"), number=next_number(s, "FC", MfgForecastRunRow), params=params,
                          status="running", as_of=date.fromisoformat(params["as_of"]), bucket=params["bucket"],
                          first_period=None, item_count=0, summary={}, results=None, error=None, started_at=now,
                          finished_at=None, actor_id=actor, row_version=1, created_at=now, updated_at=now)
    s.add(r)
    s.flush()
    res, summary, first = compute(s, params)
    r.status, r.finished_at, r.first_period = "completed", utcnow(), first
    r.item_count, r.summary, r.results = len(res), summary, {"items": res}
    if params.get("create_version", True):
        _new_version(s, r, f"{r.number} statistical", copy_overrides=True, note="", actor=actor)
    s.flush()
    return r


def get_run(ctx: AppContext, run_id: str, item_id: str | None, method: str | None, flag: str | None, limit: int,
            offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = repo.get_row(s, MfgForecastRunRow, run_id, what="Forecast run")
        items = list(((r.results or {}).get("items") or {}).values())
        items.sort(key=lambda x: (x.get("part_number") or "", x["item_id"]))
        if item_id:
            items = [x for x in items if x["item_id"] == item_id]
        if method:
            items = [x for x in items if x["method"] == method]
        if flag:
            items = [x for x in items if flag in x["flags"]]
        out = _run_record(r, _run_version(s, [r.id]).get(r.id))
        out["results"] = page(items[offset:offset + limit], len(items), limit, offset)
        return out


# ---------------------------------------------------------------- versions (F7-F12)

def _version_record(s: Session, v: MfgForecastVersionRow) -> dict[str, Any]:
    agg = s.execute(select(func.count(func.distinct(MfgForecastLineRow.item_id)),
                           func.coalesce(func.sum(MfgForecastLineRow.stat_qty), 0.0),
                           func.coalesce(func.sum(MfgForecastLineRow.final_qty), 0.0))
                    .where(MfgForecastLineRow.version_id == v.id)).one()
    nov = int(s.execute(select(func.count()).select_from(MfgForecastOverrideRow).where(
        MfgForecastOverrideRow.version_id == v.id, MfgForecastOverrideRow.removed_at.is_(None))).scalar() or 0)
    return {"id": v.id, "number": v.number, "name": v.name, "run_id": v.run_id, "status": v.status,
            "bucket": v.bucket, "start": v.start, "periods": v.periods, "item_count": int(agg[0] or 0),
            "total_stat": round(float(agg[1] or 0), 6), "total_final": round(float(agg[2] or 0), 6),
            "override_count": nov, "activated_by": v.activated_by, "activated_at": v.activated_at, "note": v.note,
            "row_version": v.row_version, "created_at": v.created_at, "updated_at": v.updated_at}


def list_versions(ctx: AppContext, status: str | None, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        q = select(MfgForecastVersionRow)
        if status:
            q = q.where(MfgForecastVersionRow.status == status)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = s.execute(q.order_by(MfgForecastVersionRow.created_at.desc(), MfgForecastVersionRow.id.desc())
                         .limit(limit).offset(offset)).scalars()
        return page([_version_record(s, v) for v in rows], n, limit, offset)


def active_version(s: Session) -> MfgForecastVersionRow | None:
    return s.execute(select(MfgForecastVersionRow).where(MfgForecastVersionRow.status == "active")
                     .order_by(MfgForecastVersionRow.activated_at.desc())).scalars().first()


def _new_version(s: Session, run: MfgForecastRunRow, name: str, *, copy_overrides: bool, note: str, actor: str
                 ) -> MfgForecastVersionRow:
    if run.status != "completed" or not run.first_period:
        raise ApiError(409, "MFG_INVALID_STATE", "Versions can only be made from a completed forecast run.",
                       {"status": run.status})
    results = (run.results or {}).get("items") or {}
    horizon = int(run.params.get("horizon_periods") or 18)
    now = utcnow()
    v = MfgForecastVersionRow(id=new_id("fcv_"), number=next_number(s, "FCV", MfgForecastVersionRow), name=name,
                              run_id=run.id, status="draft", bucket=run.bucket, start=run.first_period,
                              periods=horizon, activated_by=None, activated_at=None, archived_at=None, note=note,
                              row_version=1, created_at=now, updated_at=now)
    s.add(v)
    s.flush()
    lines = []
    for item_id in sorted(results):
        for k, q in enumerate(results[item_id]["forecast"][:horizon]):
            q = round(float(q), 6)
            lines.append({"id": new_id("fcl_"), "owner_id": v.owner_id, "version_id": v.id, "item_id": item_id,
                          "period_start": H.add_periods(v.start, k, v.bucket), "stat_qty": q, "final_qty": q})
    if lines:
        s.execute(MfgForecastLineRow.__table__.insert(), lines)
    if copy_overrides:
        act = active_version(s)
        if act is not None and act.bucket == v.bucket:
            end = H.add_periods(v.start, horizon - 1, v.bucket)
            seq = 0
            for o in s.execute(select(MfgForecastOverrideRow).where(
                    MfgForecastOverrideRow.version_id == act.id, MfgForecastOverrideRow.removed_at.is_(None))
                    .order_by(MfgForecastOverrideRow.seq)).scalars():
                if o.period_to < v.start or o.period_from > end:
                    continue
                seq += 1
                s.add(MfgForecastOverrideRow(id=new_id("fco_"), version_id=v.id, item_id=o.item_id,
                                             item_family=o.item_family, period_from=max(o.period_from, v.start),
                                             period_to=o.period_to, mode=o.mode, value=o.value, reason=o.reason,
                                             seq=seq, created_by=actor, created_at=now, removed_at=None))
            if seq:
                s.flush()
                _recompute(s, v, None)
    audit(s, "forecast_version", v.id, "create", {"run_id": run.id, "name": name})
    return v


def create_version(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        run = repo.get_row(s, MfgForecastRunRow, body.run_id, what="Forecast run")
        v = _new_version(s, run, body.name, copy_overrides=body.copy_overrides, note=body.note, actor=a.user_id)
        return _version_record(s, v)


def get_version(ctx: AppContext, version_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _version_record(s, repo.get_row(s, MfgForecastVersionRow, version_id, what="Forecast version"))


def version_lines(ctx: AppContext, version_id: str, item_id: str | None, family: str | None, abc: str | None,
                  q: str | None, limit: int, offset: int) -> dict[str, Any]:
    from .common import ilike

    with read_tx(ctx) as s:
        v = repo.get_row(s, MfgForecastVersionRow, version_id, what="Forecast version")
        iq = select(MfgItemRow.id, MfgItemRow.part_number, MfgItemRow.family, MfgItemPlanningRow.abc,
                    MfgItemPlanningRow.xyz, MfgItemRow.description).join(MfgItemPlanningRow, MfgItemPlanningRow.item_id == MfgItemRow.id,
                                                 isouter=True).where(
            MfgItemRow.id.in_(select(MfgForecastLineRow.item_id).where(MfgForecastLineRow.version_id == v.id)))
        if item_id:
            iq = iq.where(MfgItemRow.id == item_id)
        if family:
            iq = iq.where(MfgItemRow.family == family)
        if abc:
            iq = iq.where(MfgItemPlanningRow.abc == abc)
        if q:
            iq = iq.where(or_(ilike(MfgItemRow.part_number, q), ilike(MfgItemRow.description, q)))
        n = int(s.execute(select(func.count()).select_from(iq.subquery())).scalar() or 0)
        heads = list(s.execute(iq.order_by(MfgItemRow.part_number, MfgItemRow.id).limit(limit).offset(offset)))
        ids = [h[0] for h in heads]
        lines: dict[str, list[MfgForecastLineRow]] = defaultdict(list)
        if ids:
            for ln in s.execute(select(MfgForecastLineRow).where(MfgForecastLineRow.version_id == v.id,
                                                                 MfgForecastLineRow.item_id.in_(ids))
                                .order_by(MfgForecastLineRow.period_start)).scalars():
                lines[ln.item_id].append(ln)
        res: dict[str, Any] = {}
        if v.run_id:
            run = s.get(MfgForecastRunRow, v.run_id)
            res = ((run.results or {}).get("items") or {}) if run else {}
        methods = {i: res[i]["method"] for i in ids if i in res}
        items = [{"item_id": h[0], "part_number": h[1], "family": h[2], "abc": h[3], "xyz": h[4],
                  "method": methods.get(h[0]), "periods": [ln.period_start for ln in lines[h[0]]],
                  "stat": [ln.stat_qty for ln in lines[h[0]]], "final": [ln.final_qty for ln in lines[h[0]]],
                  "overridden": [abs(ln.final_qty - ln.stat_qty) > 1e-9 for ln in lines[h[0]]],
                  "name": h[5], "holdout_wape": (res.get(h[0]) or {}).get("holdout_wape"),
                  "bias": (res.get(h[0]) or {}).get("bias"), "flags": list((res.get(h[0]) or {}).get("flags") or [])}
                 for h in heads]
        return page(items, n, limit, offset)


def activate_version(ctx: AppContext, a: Any, version_id: str, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx, lock=True) as (s, _):
        v = repo.get_row(s, MfgForecastVersionRow, version_id, what="Forecast version", lock=True)
        if if_match is not None:
            check_version(v, if_match)
        if v.status != "draft":
            raise ApiError(409, "MFG_INVALID_STATE", "Only a draft version can be activated.", {"status": v.status})
        now = utcnow()
        prev = []
        for old in s.execute(select(MfgForecastVersionRow).where(MfgForecastVersionRow.status == "active")
                             .with_for_update()).scalars():
            old.status, old.archived_at = "archived", now
            old.row_version += 1
            old.updated_at = now
            prev.append(old.id)
        v.status, v.activated_by, v.activated_at = "active", a.user_id, now
        v.row_version += 1
        v.updated_at = now
        audit(s, "forecast_version", v.id, "activate", {"archived": prev, "version": v.row_version})
        return _version_record(s, v)


def delete_version(ctx: AppContext, a: Any, version_id: str, if_match: str | None) -> None:
    with write_tx(ctx, lock=False) as (s, _):
        v = repo.get_row(s, MfgForecastVersionRow, version_id, what="Forecast version", lock=True)
        if if_match is not None:
            check_version(v, if_match)
        if v.status != "draft":
            raise _locked("A version", v.status)
        s.execute(delete(MfgForecastOverrideRow).where(MfgForecastOverrideRow.version_id == v.id))
        s.delete(v)
        audit(s, "forecast_version", version_id, "delete", {})


# ---------------------------------------------------------------- overrides (F13-F15)

def _override_record(o: MfgForecastOverrideRow, changes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"id": o.id, "version_id": o.version_id, "item_id": o.item_id, "item_family": o.item_family,
            "period_from": o.period_from, "period_to": o.period_to, "mode": o.mode, "value": o.value,
            "reason": o.reason, "seq": o.seq, "created_by": o.created_by, "created_at": o.created_at,
            "removed_at": o.removed_at, "changes": changes or []}


def _family_of(s: Session, ids: Iterable[str]) -> dict[str, str | None]:
    ids = list(ids)
    if not ids:
        return {}
    return {i: f for i, f in s.execute(select(MfgItemRow.id, MfgItemRow.family).where(MfgItemRow.id.in_(ids)))}


def _recompute(s: Session, v: MfgForecastVersionRow, items: set[str] | None) -> dict[str, list[dict[str, Any]]]:
    """Re-apply every active override of the version to the stat values of `items` (None = all); returns the
    per-override changes. Only lines whose final value moves are updated."""
    q = select(MfgForecastLineRow).where(MfgForecastLineRow.version_id == v.id)
    if items is not None:
        if not items:
            return {}
        q = q.where(MfgForecastLineRow.item_id.in_(sorted(items)))
    lines = {(ln.item_id, ln.period_start): ln for ln in s.execute(q).scalars()}
    fam = _family_of(s, {i for i, _p in lines})
    ovs = [Override(o.id, o.seq, o.item_id, o.item_family, o.period_from, o.period_to, o.mode, o.value)
           for o in s.execute(select(MfgForecastOverrideRow).where(
               MfgForecastOverrideRow.version_id == v.id, MfgForecastOverrideRow.removed_at.is_(None))).scalars()]
    final, changes = apply({k: ln.stat_qty for k, ln in lines.items()}, ovs, fam)
    for k, ln in lines.items():
        if abs(ln.final_qty - final[k]) > 1e-9:
            ln.final_qty = final[k]
    s.flush()
    return changes


def _affected(s: Session, v: MfgForecastVersionRow, item_id: str | None, family: str | None) -> set[str]:
    if item_id is not None:
        return {item_id}
    return set(s.execute(select(MfgForecastLineRow.item_id).distinct().join(
        MfgItemRow, MfgItemRow.id == MfgForecastLineRow.item_id).where(
        MfgForecastLineRow.version_id == v.id, MfgItemRow.family == family)).scalars())


def _finals(s: Session, v: MfgForecastVersionRow, items: set[str]) -> dict[tuple[str, date], float]:
    if not items:
        return {}
    return {(i, p): q for i, p, q in s.execute(select(MfgForecastLineRow.item_id, MfgForecastLineRow.period_start,
                                                       MfgForecastLineRow.final_qty).where(
        MfgForecastLineRow.version_id == v.id, MfgForecastLineRow.item_id.in_(sorted(items))))}


def _diff(before: dict[tuple[str, date], float], after: dict[tuple[str, date], float]) -> list[dict[str, Any]]:
    return [{"item_id": k[0], "period_start": k[1], "old": round(before[k], 6), "new": round(after[k], 6)}
            for k in sorted(after) if k in before and abs(before[k] - after[k]) > 1e-9]


def _with_family_items(s: Session, v: MfgForecastVersionRow, items: set[str]) -> set[str]:
    """Items plus every item sharing a family with them (family overrides span the family)."""
    fams = {f for f in _family_of(s, items).values() if f}
    out = set(items)
    for f in fams:
        out |= _affected(s, v, None, f)
    return out


def list_overrides(ctx: AppContext, version_id: str, include_removed: bool) -> dict[str, Any]:
    with read_tx(ctx) as s:
        v = repo.get_row(s, MfgForecastVersionRow, version_id, what="Forecast version")
        q = select(MfgForecastOverrideRow).where(MfgForecastOverrideRow.version_id == v.id)
        if not include_removed:
            q = q.where(MfgForecastOverrideRow.removed_at.is_(None))
        return {"items": [_override_record(o) for o in s.execute(q.order_by(MfgForecastOverrideRow.seq)).scalars()]}


def create_override(ctx: AppContext, a: Any, version_id: str, body: Any) -> dict[str, Any]:
    from .common import unknown_ref

    with write_tx(ctx, lock=False) as (s, _):
        v = repo.get_row(s, MfgForecastVersionRow, version_id, what="Forecast version", lock=True)
        if v.status != "draft":
            raise _locked("Overrides", v.status)
        items = _affected(s, v, body.item_id, body.item_family)
        if not items:
            raise unknown_ref(["body", "item_id" if body.item_id else "item_family"], body.item_id or
                              body.item_family, "Item or family in this version")
        scope = _with_family_items(s, v, items)
        before = _finals(s, v, scope)
        seq = int(s.execute(select(func.coalesce(func.max(MfgForecastOverrideRow.seq), 0)).where(
            MfgForecastOverrideRow.version_id == v.id)).scalar() or 0) + 1
        o = MfgForecastOverrideRow(id=new_id("fco_"), version_id=v.id, item_id=body.item_id,
                                   item_family=body.item_family, period_from=body.period_from,
                                   period_to=body.period_to, mode=body.mode, value=body.value, reason=body.reason,
                                   seq=seq, created_by=a.user_id, created_at=utcnow(), removed_at=None)
        s.add(o)
        s.flush()
        _recompute(s, v, scope)
        changes = _diff(before, _finals(s, v, scope))
        v.row_version += 1
        v.updated_at = utcnow()
        audit(s, "forecast_override", o.id, "create", {"version_id": v.id, "reason": body.reason, "mode": body.mode,
                                                       "value": body.value, "changes": jsonable(changes[:500])},
              reason=body.reason)
        return _override_record(o, changes)


def remove_override(ctx: AppContext, a: Any, override_id: str) -> dict[str, Any]:
    from ...audit_diff import REASON_HEADER, current_reason

    reason = current_reason()
    if not reason:
        raise ApiError(422, "VALIDATION_ERROR", f"Removing an override needs a reason ({REASON_HEADER}).",
                       {"header": REASON_HEADER})
    with write_tx(ctx, lock=False) as (s, _):
        o = repo.get_row(s, MfgForecastOverrideRow, override_id, what="Override", lock=True)
        v = repo.get_row(s, MfgForecastVersionRow, o.version_id, what="Forecast version", lock=True)
        if v.status != "draft":
            raise _locked("Overrides", v.status)
        if o.removed_at is not None:
            return _override_record(o)
        scope = _with_family_items(s, v, _affected(s, v, o.item_id, o.item_family))
        before = _finals(s, v, scope)
        o.removed_at = utcnow()
        s.flush()
        _recompute(s, v, scope)
        changes = _diff(before, _finals(s, v, scope))
        v.row_version += 1
        v.updated_at = utcnow()
        audit(s, "forecast_override", o.id, "remove", {"version_id": v.id, "reason": reason,
                                                       "changes": jsonable(changes[:500])}, reason=reason)
        return _override_record(o, changes)


# ---------------------------------------------------------------- consumption for MRP (4.4)

def open_customer_orders(s: Session, item_ids: Iterable[str] | None = None) -> list[OrderDemand]:
    q = (select(MfgDemandLineRow.item_id, MfgDemandLineRow.due_date, MfgDemandLineRow.qty,
                MfgDemandLineRow.shipped_qty, MfgDemandLineRow.id)
         .join(MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id)
         .where(MfgDemandOrderRow.status == "open", MfgDemandOrderRow.demand_type == "customer"))
    if item_ids is not None:
        ids = list(item_ids)
        if not ids:
            return []
        q = q.where(MfgDemandLineRow.item_id.in_(ids))
    return [OrderDemand(i, d, max(0.0, float(qty) - float(sh or 0)), ref) for i, d, qty, sh, ref in s.execute(q)]


def version_lines_map(s: Session, version_id: str, item_ids: Iterable[str] | None = None
                      ) -> dict[str, list[tuple[date, float]]]:
    q = select(MfgForecastLineRow.item_id, MfgForecastLineRow.period_start, MfgForecastLineRow.final_qty).where(
        MfgForecastLineRow.version_id == version_id)
    if item_ids is not None:
        q = q.where(MfgForecastLineRow.item_id.in_(list(item_ids)))
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for i, p, f in s.execute(q):
        out[i].append((p, float(f)))
    return out


def forecast_requirements(s: Session, version_id: str | None, as_of: date) -> tuple[list[ForecastSnap],
                                                                                     list[dict[str, Any]], str | None]:
    """MRP feed (6): (snaps, over-consumed orders, version id). `version_id` None = the active version, "none" =
    no forecast."""
    if version_id == "none":
        return [], [], None
    v = s.get(MfgForecastVersionRow, version_id) if version_id else active_version(s)
    if v is None:
        if version_id:
            raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Forecast version {version_id!r} was not found.",
                           {"loc": ["body", "forecast_version_id"], "id": version_id})
        return [], [], None
    st = settings_of(s)
    lines = version_lines_map(s, v.id)
    cal = work_calendar(s)
    res = consume(lines, open_customer_orders(s, list(lines)), bucket=v.bucket, as_of=as_of,
                  is_workday=cal.is_workday, version_id=v.id, back_days=st.consume_back_days,
                  fwd_days=st.consume_fwd_days, daily_days=st.daily_days, weekly_weeks=st.weekly_weeks)
    return res.snaps, res.overconsumed, v.id


# ---------------------------------------------------------------- item view, accuracy (F16-F17)

def _versions_spans(s: Session) -> list[ACC.VersionSpan]:
    return [ACC.VersionSpan(vid, at, arch) for vid, at, arch in s.execute(
        select(MfgForecastVersionRow.id, MfgForecastVersionRow.activated_at, MfgForecastVersionRow.archived_at)
        .where(MfgForecastVersionRow.activated_at.is_not(None)))]


def _accuracy_rows(s: Session, lag: int, group_by: str, periods: int, item_ids: list[str] | None = None,
                   last: date | None = None) -> list[dict[str, Any]]:
    st = settings_of(s)
    bucket = st.forecast_bucket
    last = last or H.last_closed_period(today(s), bucket)
    pers = [H.add_periods(last, -k, bucket) for k in range(periods)]
    spans = _versions_spans(s)
    vids = [sp.id for sp in spans]
    if not vids:
        return []
    q = select(MfgForecastLineRow.version_id, MfgForecastLineRow.item_id, MfgForecastLineRow.period_start,
               MfgForecastLineRow.final_qty).where(MfgForecastLineRow.version_id.in_(vids),
                                                   MfgForecastLineRow.period_start.in_(pers))
    if item_ids is not None:
        q = q.where(MfgForecastLineRow.item_id.in_(item_ids))
    final = {(v, i, p): float(f) for v, i, p, f in s.execute(q)}
    items = sorted({i for _v, i, _p in final})
    fc = ACC.lag_forecasts(spans, final, items, pers, lag, bucket)
    hq = select(MfgDemandHistoryRow).where(MfgDemandHistoryRow.bucket == bucket,
                                           MfgDemandHistoryRow.period_start.in_(pers))
    if items:
        hq = hq.where(MfgDemandHistoryRow.item_id.in_(items))
    merged = H.merge_sources(H.as_points(s.execute(hq).scalars()))
    actual = {(i, p): h.qty for i, d in merged.items() for p, h in d.items()}
    if group_by == "item":
        ref = item_map(s, items)
        grp = {i: i for i in items}
        labels = {i: (ref[i].part_number if i in ref else i) for i in items}
    elif group_by == "family":
        fam = _family_of(s, items)
        grp = {i: fam.get(i) or "-" for i in items}
        labels = None
    elif group_by == "abc":
        pl = planning_rows(s, items)
        grp = {i: (pl[i].abc if i in pl and pl[i].abc else "C") for i in items}
        labels = None
    else:
        grp = {i: "all" for i in items}
        labels = None
    return ACC.report(actual, fc, grp, labels)


def accuracy_trend(s: Session, lag: int, periods: int) -> list[dict[str, Any]]:
    """All items, one row per closed period (oldest first): actual, lag forecast, WAPE, bias."""
    st = settings_of(s)
    last = H.last_closed_period(today(s), st.forecast_bucket)
    out = []
    for k in range(periods - 1, -1, -1):
        p = H.add_periods(last, -k, st.forecast_bucket)
        rows = _accuracy_rows(s, lag, "all", 1, None, last=p)
        r = rows[0] if rows else None
        out.append({"period_start": p, "actual": r["actual"] if r else None, "forecast": r["forecast"] if r else None,
                    "wape": r["wape"] if r else None, "bias": r["bias"] if r else None})
    return out


def accuracy(ctx: AppContext, lag: int, group_by: str, periods: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        rows = _accuracy_rows(s, lag, group_by, periods)
        run = s.execute(select(MfgForecastRunRow).where(MfgForecastRunRow.status == "completed")
                        .order_by(MfgForecastRunRow.finished_at.desc())).scalars().first()
        return {"lag": lag, "group_by": group_by, "rows": rows, "backtest": run.summary if run else None,
                "trend": accuracy_trend(s, lag, periods)}


def item_view(ctx: AppContext, item_id: str, version_id: str | None) -> dict[str, Any]:
    from .m8common import planning_of

    with read_tx(ctx) as s:
        it = repo.get_row(s, MfgItemRow, item_id, what="Item")
        st = settings_of(s)
        hist = list(s.execute(select(MfgDemandHistoryRow).where(
            MfgDemandHistoryRow.item_id == item_id, MfgDemandHistoryRow.bucket == st.forecast_bucket)
            .order_by(MfgDemandHistoryRow.period_start, MfgDemandHistoryRow.source)).scalars())
        result = None
        for run in s.execute(select(MfgForecastRunRow).where(MfgForecastRunRow.status == "completed")
                             .order_by(MfgForecastRunRow.finished_at.desc()).limit(5)).scalars():
            r = ((run.results or {}).get("items") or {}).get(item_id)
            if r is not None:
                result = {k: r[k] for k in ("item_id", "part_number", "demand_class", "adi", "cv2", "method",
                                            "params", "holdout_wape", "bias", "rmse1", "mean", "n_periods", "abc",
                                            "flags", "fitted_tail", "forecast", "candidates") if k in r}
                break
        vq = select(MfgForecastVersionRow).where(or_(MfgForecastVersionRow.status.in_(("active", "draft")),
                                                     MfgForecastVersionRow.id == (version_id or "")))
        versions = []
        act = None
        for v in s.execute(vq.order_by(MfgForecastVersionRow.created_at.desc()).limit(6)).scalars():
            ln = version_lines_map(s, v.id, [item_id]).get(item_id, [])
            ln.sort()
            versions.append({"version_id": v.id, "number": v.number, "status": v.status,
                             "periods": [p for p, _q in ln], "final": [q for _p, q in ln]})
            if (version_id and v.id == version_id) or (not version_id and v.status == "active"):
                act = v
        consumption: list[dict[str, Any]] = []
        if act is not None:
            cal = work_calendar(s)
            lines = version_lines_map(s, act.id, [item_id])
            res = consume(lines, open_customer_orders(s, [item_id]), bucket=act.bucket, as_of=today(s),
                          is_workday=cal.is_workday, version_id=act.id, back_days=st.consume_back_days,
                          fwd_days=st.consume_fwd_days, daily_days=st.daily_days, weekly_weeks=st.weekly_weeks)
            consumption = res.view
        acc = {}
        for lag in (1, 3):
            rows = _accuracy_rows(s, lag, "all", 6, [item_id])
            acc[f"lag{lag}"] = {"wape": rows[0]["wape"], "bias": rows[0]["bias"], "periods": rows[0]["periods"]} \
                if rows else {"wape": None, "bias": None, "periods": 0}
        pl = planning_rows(s, [item_id]).get(item_id)
        return {"item": iref(it), "planning": planning_of(pl), "history": [_hist_record(h) for h in hist],
                "result": result, "versions": versions, "consumption": consumption, "accuracy": acc}


__getattr__ = m8_examples.module_getattr(__name__)
