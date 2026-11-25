"""Rate / campaign engine service (M8-DESIGN 7, 11 R4-R9): runs (job `rate_run`), blocks, grid, compare,
publish.

A run is immutable once finished. Status `completed` (validator clean) or `failed_validation` (never publishable,
V3) or `failed`. Publish (7.3): the firm zone becomes repetitive WOs (`kind repetitive`, released, the flow-line
operation pinned to the block line, `rate_run_id`), unstarted repetitive WOs of earlier runs in the zone that no
longer match are cancelled, started ones are kept; later blocks stay `rate` supplies for MRP pass 2. One run is
published at a time (the previous published run is unpublished).
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ....mfg.rate import engine
from ....mfg.rate import publish as PUB
from ....mfg.rate.build import build
from ....mfg.rate.model import RateParams
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow, MfgLineRow
from ..db_models_m2 import MfgWorkOrderRow
from ..db_models_m8 import MfgRateBlockRow, MfgRateRunRow
from . import m8_examples
from .common import audit, jsonable, read_tx, write_tx
from .m8common import next_number, page, settings_of, start_job, today


def _run_record(r: MfgRateRunRow) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "label": r.label, "params": r.params, "status": r.status,
            "mrp_run_id": r.mrp_run_id, "as_of": r.as_of, "horizon_days": r.horizon_days, "published": r.published,
            "published_at": r.published_at, "published_by": r.published_by, "objective": r.objective,
            "summary": r.summary, "explanations": r.explanations, "validator": r.validator,
            "shortages": r.shortages, "duration_ms": r.duration_ms, "error": r.error, "created_at": r.created_at,
            "finished_at": r.finished_at}


def list_runs(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        n = int(s.execute(select(func.count()).select_from(MfgRateRunRow)).scalar() or 0)
        rows = s.execute(select(MfgRateRunRow).order_by(MfgRateRunRow.created_at.desc(), MfgRateRunRow.id.desc())
                         .limit(limit).offset(offset)).scalars()
        out = []
        for r in rows:
            rec = _run_record(r)
            rec["explanations"] = None
            rec["shortages"] = None
            out.append(rec)
        return page(out, n, limit, offset)


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _run_record(repo.get_row(s, MfgRateRunRow, run_id, what="Rate run"))


def _new_run(s: Session, actor: str, body: RateParams) -> MfgRateRunRow:
    st = settings_of(s)
    now = utcnow()
    r = MfgRateRunRow(id=new_id("rrn_"), number=next_number(s, "RR", MfgRateRunRow), label=body.label,
                      params=body.model_dump(mode="json"), status="queued", mrp_run_id=body.mrp_run_id,
                      as_of=today(s), horizon_days=body.horizon_days or st.rate_horizon_days, published=False,
                      published_at=None, published_by=None, objective=None, summary=None, explanations=None,
                      shortages=None, validator=None, duration_ms=None, error=None, actor_id=actor,
                      finished_at=None, row_version=1, created_at=now, updated_at=now)
    s.add(r)
    s.flush()
    return r


def create_run(ctx: AppContext, a: Any, body: RateParams) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        r = _new_run(s, a.user_id, body)
        _rid, job = start_job(s, ctx, "rate_run", r.owner_id, {"run_id": r.id})
        audit(s, "rate_run", r.id, "create", r.params)
        rec = _run_record(r)
    ctx.jobs.dispatch(job)
    return rec


def compute(ctx: AppContext, run_id: str) -> dict[str, Any]:
    """Build (read) -> solve (no transaction) -> store (write). Used by the job and the nightly chain."""
    t0 = time.monotonic()
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgRateRunRow, run_id, with_for_update=True)
        if r is None:
            return {"error": "run gone"}
        r.status = "running"
        params = RateParams.model_validate(r.params)
    try:
        with ctx.db.read() as s:
            st = settings_of(s)
            problem, mrp = build(s, params, as_of=today(s), settings=st, today=today(s))
            mrp_id = mrp.id if mrp is not None else None
        res = engine.solve(problem)
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgRateRunRow, run_id, with_for_update=True)
            rows = [{"id": new_id("rbk_"), "owner_id": r.owner_id, "run_id": r.id, "line_id": b.line_id,
                     "kind": b.kind, "item_id": b.item_id, "campaign_no": b.campaign_no, "start": b.start,
                     "end": b.end, "qty": round(b.qty, 6), "cases": b.cases, "prod_date": b.prod_date,
                     "wo_id": b.wo_id} for b in res.blocks]
            if rows:
                s.execute(MfgRateBlockRow.__table__.insert(), rows)
            prod = [b for b in res.blocks if b.kind == "production"]
            util: dict[str, float] = {}
            for ln in problem.lines:
                av = engine.available_hours(problem, ln)
                used = sum((b.end - b.start).total_seconds() / 3600 for b in res.blocks if b.line_id == ln.id)
                util[ln.id] = round(used / av, 4) if av > 0 else 0.0
            r.mrp_run_id = mrp_id
            r.objective = res.objective
            r.validator = res.validator
            r.explanations = jsonable(res.explanations)
            r.shortages = jsonable([{"item_id": x.item_id, "due": x.due, "qty": x.qty, "cause": x.cause,
                                     "detail": x.detail} for x in res.shortages])
            r.summary = {"lines": len(problem.lines), "blocks": len(res.blocks),
                         "campaigns": len({(b.line_id, b.campaign_no) for b in prod}),
                         "production_qty": round(sum(b.qty for b in prod), 6),
                         "shortage_qty": round(sum(x.qty for x in res.shortages), 6), "utilisation": util,
                         "demands": len(problem.demands), "stats": jsonable(res.stats)}
            r.status = "completed" if res.validator["ok"] else "failed_validation"
            r.duration_ms = int((time.monotonic() - t0) * 1000)
            r.finished_at = utcnow()
            return {"run_id": run_id, "status": r.status, "blocks": len(rows)}
    except Exception as exc:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgRateRunRow, run_id, with_for_update=True)
            if r is not None:
                r.status, r.finished_at, r.error = "failed", utcnow(), f"{exc.__class__.__name__}: {exc}"[:500]
        raise


def run_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    return compute(ctx, info["params"]["run_id"])


def _block_record(b: MfgRateBlockRow, codes: dict[str, str], pns: dict[str, str]) -> dict[str, Any]:
    return {"id": b.id, "line_id": b.line_id, "line_code": codes.get(b.line_id), "kind": b.kind,
            "item_id": b.item_id, "part_number": pns.get(b.item_id or ""), "campaign_no": b.campaign_no,
            "start": b.start, "end": b.end, "qty": b.qty, "cases": b.cases, "prod_date": b.prod_date,
            "wo_id": b.wo_id}


def _names(s: Session, blocks: list[MfgRateBlockRow]) -> tuple[dict[str, str], dict[str, str]]:
    lids = {b.line_id for b in blocks}
    iids = {b.item_id for b in blocks if b.item_id}
    codes = dict(s.execute(select(MfgLineRow.id, MfgLineRow.code).where(MfgLineRow.id.in_(lids))).all()) if lids else {}
    pns = dict(s.execute(select(MfgItemRow.id, MfgItemRow.part_number).where(MfgItemRow.id.in_(iids))).all()) \
        if iids else {}
    return codes, pns


def list_blocks(ctx: AppContext, run_id: str, line_id: str | None, from_: date | None, to: date | None, limit: int,
                offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        repo.get_row(s, MfgRateRunRow, run_id, what="Rate run")
        q = select(MfgRateBlockRow).where(MfgRateBlockRow.run_id == run_id)
        if line_id:
            q = q.where(MfgRateBlockRow.line_id == line_id)
        if from_:
            q = q.where(MfgRateBlockRow.prod_date >= from_)
        if to:
            q = q.where(MfgRateBlockRow.prod_date <= to)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = list(s.execute(q.order_by(MfgRateBlockRow.line_id, MfgRateBlockRow.start).limit(limit)
                              .offset(offset)).scalars())
        codes, pns = _names(s, rows)
        return page([_block_record(b, codes, pns) for b in rows], n, limit, offset)


def grid(ctx: AppContext, run_id: str, bucket: str, line_id: str | None) -> dict[str, Any]:
    """Line x bucket x item (P8: one query, aggregated in Python)."""
    from ....mfg.tz import plant_tz

    with read_tx(ctx) as s:
        r = repo.get_row(s, MfgRateRunRow, run_id, what="Rate run")
        q = select(MfgRateBlockRow).where(MfgRateBlockRow.run_id == r.id)
        if line_id:
            q = q.where(MfgRateBlockRow.line_id == line_id)
        rows = list(s.execute(q.order_by(MfgRateBlockRow.start)).scalars())
        codes, pns = _names(s, rows)
        from .m8common import plant_row

        tz = plant_tz(plant_row(s)) if plant_row(s) is not None else None
        cells: dict[tuple[str, str, str | None], dict[str, float]] = defaultdict(lambda: {"qty": 0.0, "hours": 0.0})
        used: dict[tuple[str, str], float] = defaultdict(float)
        buckets: set[str] = set()
        for b in rows:
            if bucket == "day":
                key = b.prod_date.isoformat()
            else:
                loc = b.start.astimezone(tz) if tz else b.start
                key = loc.strftime("%Y-%m-%dT%H")
            buckets.add(key)
            h = (b.end - b.start).total_seconds() / 3600.0
            used[(b.line_id, key)] += h
            if b.kind == "production":
                c = cells[(b.line_id, key, b.item_id)]
                c["qty"] += b.qty
                c["hours"] += h
                c["cases"] = c.get("cases", 0) + (b.cases or 0)
        span = 24.0 if bucket == "day" else 8.0
        lines = sorted({b.line_id for b in rows}, key=lambda x: codes.get(x, x))
        return {"bucket": bucket, "buckets": sorted(buckets),
                "lines": [{"line_id": lid, "code": codes.get(lid),
                           "utilisation": {k: round(min(used[(lid, k)] / span, 1.0), 4) for k in sorted(buckets)
                                           if (lid, k) in used}} for lid in lines],
                "cells": [{"line_id": lid, "bucket": key, "item_id": iid, "part_number": pns.get(iid or ""),
                           "qty": round(v["qty"], 6), "cases": int(v.get("cases", 0)) or None,
                           "hours": round(v["hours"], 4)} for (lid, key, iid), v in sorted(cells.items(),
                                                                                         key=lambda kv: kv[0])]}


def compare(ctx: AppContext, a_id: str, b_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        a = repo.get_row(s, MfgRateRunRow, a_id, what="Rate run")
        b = repo.get_row(s, MfgRateRunRow, b_id, what="Rate run")
        obj = {}
        for k in ("shortage_unit_days", "changeover_cost", "changeover_hours", "excess_cover_unit_days",
                  "overtime_cost"):
            va, vb = float((a.objective or {}).get(k, 0)), float((b.objective or {}).get(k, 0))
            obj[k] = {"a": va, "b": vb, "delta": round(vb - va, 6)}
        per_line: dict[str, dict[str, Any]] = defaultdict(lambda: {"a_qty": 0.0, "b_qty": 0.0, "a_changeovers": 0,
                                                                   "b_changeovers": 0})
        per_item: dict[str, dict[str, Any]] = defaultdict(lambda: {"a_qty": 0.0, "b_qty": 0.0, "a_short": 0.0,
                                                                   "b_short": 0.0})
        for tag, run in (("a", a), ("b", b)):
            for lid, kind, iid, qty in s.execute(select(MfgRateBlockRow.line_id, MfgRateBlockRow.kind,
                                                        MfgRateBlockRow.item_id, MfgRateBlockRow.qty)
                                                 .where(MfgRateBlockRow.run_id == run.id)):
                if kind == "production":
                    per_line[lid][f"{tag}_qty"] += qty
                    per_item[iid][f"{tag}_qty"] += qty
                elif kind == "changeover":
                    per_line[lid][f"{tag}_changeovers"] += 1
            for sh in run.shortages or []:
                per_item[sh["item_id"]][f"{tag}_short"] += float(sh["qty"])
        codes = dict(s.execute(select(MfgLineRow.id, MfgLineRow.code).where(MfgLineRow.id.in_(list(per_line)))).all()) \
            if per_line else {}
        return {"a": a.id, "b": b.id, "objective": obj,
                "lines": [{"line_id": k, "code": codes.get(k), **{x: round(y, 6) if isinstance(y, float) else y
                                                                 for x, y in v.items()}}
                          for k, v in sorted(per_line.items(), key=lambda kv: codes.get(kv[0], kv[0]))],
                "items": [{"item_id": k, **{x: round(y, 6) for x, y in v.items()}} for k, v in sorted(per_item.items())]}


# ---------------------------------------------------------------- publish (7.3)

def _started(w: MfgWorkOrderRow) -> bool:
    return w.status in ("in_progress", "completed", "closed") or (w.qty_completed or 0) > 0


def publish_in(s: Session, run: MfgRateRunRow, actor: str) -> dict[str, Any]:
    from ....mfg.model_m2 import WorkOrderInput
    from . import floor as FLR
    from . import workorders as WO

    if run.status != "completed" or not (run.validator or {}).get("ok"):
        raise ApiError(409, "RATE_NOT_PUBLISHABLE", "Only a completed, validator-clean rate run can be published.",
                       {"status": run.status})
    if run.published:
        raise ApiError(409, "MFG_INVALID_STATE", "This rate run is already published.", {})
    st = settings_of(s)
    d = today(s)
    firm_end = d + timedelta(days=st.rate_firm_days)
    blocks = list(s.execute(select(MfgRateBlockRow).where(MfgRateBlockRow.run_id == run.id)
                            .order_by(MfgRateBlockRow.line_id, MfgRateBlockRow.start)).scalars())
    groups = PUB.firm_groups(blocks, firm_end, st.rate_wo_split)
    prev_rows = list(s.execute(select(MfgWorkOrderRow).where(
        MfgWorkOrderRow.kind == "repetitive", MfgWorkOrderRow.rate_run_id.is_not(None),
        MfgWorkOrderRow.status.in_(("planned", "released", "in_progress")),
        MfgWorkOrderRow.due_date >= d, MfgWorkOrderRow.due_date <= firm_end).with_for_update()).scalars())
    prev = [PUB.PrevWo(w.id, w.item_id, w.due_date, float(w.qty), _started(w)) for w in prev_rows]
    dec = PUB.decide(groups, prev)
    by_id = {w.id: w for w in prev_rows}
    now = utcnow()
    block_by_id = {b.id: b for b in blocks}
    created, cancelled, kept = [], [], []
    ds = repo.load_dataset(s) if dec.create else None
    line_group = dict(s.execute(select(MfgLineRow.id, MfgLineRow.group_id)).all())
    for g in dec.create:
        w, _warn = WO.new_wo(s, ds, WorkOrderInput(item_id=g.item_id, qty=g.qty, due_date=g.due, start_date=g.prod_date,
                                                   note=f"{run.number} rate plan"), source="rate", status="released")
        w.kind, w.rate_run_id = "repetitive", run.id
        ops = FLR.derive_rows(s, w, "rate", now)
        for op in ops:
            if op.group_id == line_group.get(g.line_id):
                op.line_id = g.line_id
        for bid in g.block_ids:
            block_by_id[bid].wo_id = w.id
        created.append(w.id)
        audit(s, "work_order", w.id, "create", {"number": w.number, "rate_run": run.number})
    for w, g in dec.keep:
        row = by_id[w.id]
        row.rate_run_id = run.id
        if g is not None:
            for bid in g.block_ids:
                block_by_id[bid].wo_id = row.id
        kept.append(row.id)
    for w in dec.cancel:
        row = by_id[w.id]
        row.status = "cancelled"
        row.row_version += 1
        row.updated_at = now
        cancelled.append(row.id)
        audit(s, "work_order", row.id, "cancel", {"number": row.number, "rate_run": run.number})
    s.execute(update(MfgRateRunRow).where(MfgRateRunRow.published.is_(True), MfgRateRunRow.id != run.id)
              .values(published=False).execution_options(synchronize_session=False))
    run.published, run.published_at, run.published_by = True, now, actor
    run.row_version += 1
    rate_supplies = sum(1 for b in blocks if b.kind == "production" and b.wo_id is None)
    out = {"run_id": run.id, "created_wo_ids": created, "cancelled_wo_ids": cancelled, "kept_wo_ids": kept,
           "rate_supplies": rate_supplies}
    audit(s, "rate_run", run.id, "publish", {k: (len(v) if isinstance(v, list) else v) for k, v in out.items()})
    return out


def publish(ctx: AppContext, a: Any, run_id: str) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        run = repo.get_row(s, MfgRateRunRow, run_id, what="Rate run", lock=True)
        return publish_in(s, run, a.user_id)


__getattr__ = m8_examples.module_getattr(__name__)
