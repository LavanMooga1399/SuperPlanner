"""KPIs and adherence (M4-DESIGN 9, 11 #222-223). Per local day and dimension (plant / group / line) every metric
is a `(num, den)` pair; closed days (before plant today) are cached in `mfg_kpi_daily` on first request, today is
always live. A period aggregates the pairs exactly. WIP is a snapshot (now)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....mfg import kpi as K
from ....mfg.floor import engine as E
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from ...schemas import as_utc
from ..db_models import MfgGroupRow, MfgItemRow, MfgLineRow, MfgOperationRow, MfgPlantRow
from ..db_models_m2 import (MfgDemandLineRow, MfgInvTransactionRow, MfgWoComponentRow, MfgWorkOrderRow)
from ..db_models_m3 import MfgApsOpRow, MfgApsRunRow
from ..db_models_m4 import MfgDowntimeRow, MfgFloorEventRow, MfgKpiDailyRow, MfgWoOperationRow
from .common import read_tx
from .m2util import run_tx

RATIO_METRICS = ("otd", "wo_on_time", "utilisation", "availability", "performance", "fpy", "adherence",
                 "scrap_rate", "setup", "setup_planned")
MAX_DAYS = 400
Key = tuple[str, str]          # (dim_type, dim_id)


def _tz(s: Session) -> Any:
    from ....mfg.tz import plant_tz

    p = s.execute(select(MfgPlantRow)).scalars().first()
    return plant_tz(p) if p is not None else UTC, p


def _period(s: Session, frm: date | None, to: date | None) -> tuple[date, date, Any, Any]:
    tz, p = _tz(s)
    today = utcnow().astimezone(tz).date()
    to = to or today
    frm = frm or (to - timedelta(days=29))
    if frm > to:
        raise ApiError(422, "VALIDATION_ERROR", "from must not be after to.",
                       {"errors": [{"loc": ["query", "from"], "msg": "after to", "type": "value_error"}]})
    if (to - frm).days + 1 > MAX_DAYS:
        raise ApiError(422, "VALIDATION_ERROR", f"A KPI period spans at most {MAX_DAYS} days.",
                       {"errors": [{"loc": ["query", "from"], "msg": "period too long", "type": "value_error"}]})
    return frm, to, tz, p


# ---------------------------------------------------------------- per-day computation

class _Data:
    """Everything the days of [d0, d1] need, loaded once."""

    def __init__(self, s: Session, d0: date, d1: date, tz: Any, plant: Any):
        from .. import repo_m3

        self.tz, self.plant = tz, plant
        lo, _x = K.day_bounds(d0, tz)
        _y, hi = K.day_bounds(d1, tz)
        self.lo, self.hi = lo, hi
        self.lines = {ln.id: ln for ln in s.execute(select(MfgLineRow)).scalars()}
        self.group_of = {lid: ln.group_id for lid, ln in self.lines.items()}
        self.ds = repo_m3.calendar_dataset(s)
        self.downtime = list(s.execute(select(MfgDowntimeRow).where(
            MfgDowntimeRow.start_at < hi, (MfgDowntimeRow.end_at.is_(None)) | (MfgDowntimeRow.end_at > lo))).scalars())
        op_ids = set(s.execute(select(MfgFloorEventRow.wo_operation_id).where(
            MfgFloorEventRow.event_at >= lo - timedelta(days=7), MfgFloorEventRow.event_at < hi)).scalars())
        op_ids |= set(s.execute(select(MfgWoOperationRow.id).where(
            MfgWoOperationRow.status.in_(("setup", "running", "paused")))).scalars())
        self.ops = {o.id: o for o in s.execute(select(MfgWoOperationRow).where(
            MfgWoOperationRow.id.in_(op_ids))).scalars()} if op_ids else {}
        evs: dict[str, list[MfgFloorEventRow]] = defaultdict(list)
        if op_ids:
            for e in s.execute(select(MfgFloorEventRow).where(MfgFloorEventRow.wo_operation_id.in_(op_ids),
                                                              MfgFloorEventRow.event_at < hi)
                               .order_by(MfgFloorEventRow.seq)).scalars():
                evs[e.wo_operation_id].append(e)
        self.events = evs
        wos = {w.id: w for w in s.execute(select(MfgWorkOrderRow).where(
            MfgWorkOrderRow.id.in_({o.wo_id for o in self.ops.values()}))).scalars()} if self.ops else {}
        self.wos = wos
        self.items = {i.id: i for i in s.execute(select(MfgItemRow).where(
            MfgItemRow.id.in_({w.item_id for w in wos.values()}))).scalars()} if wos else {}
        rids = {w.routing_id for w in wos.values() if w.routing_id}
        self.rops = {(o.routing_id, o.seq): o for o in s.execute(select(MfgOperationRow).where(
            MfgOperationRow.routing_id.in_(rids))).scalars()} if rids else {}
        now = utcnow()
        self.intervals: list[K.Interval] = []
        for oid, lst in evs.items():
            o = self.ops.get(oid)
            if o is None:
                continue
            from .floor import _ev

            self.intervals += K.work_intervals([_ev(e) for e in lst], op_id=oid, until=min(now, hi))
        pub = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
        self.pub_ops = list(s.execute(select(MfgApsOpRow).where(
            MfgApsOpRow.run_id == pub.id, MfgApsOpRow.status == "scheduled", MfgApsOpRow.order_type == "wo",
            MfgApsOpRow.start_at >= lo, MfgApsOpRow.start_at < hi)).scalars()) if pub is not None else []
        self.pub_run_id = pub.id if pub is not None else None
        pub_wo = {o.order_id for o in self.pub_ops}
        self.pub_rows = {(r.wo_id, r.seq): r for r in s.execute(select(MfgWoOperationRow).where(
            MfgWoOperationRow.wo_id.in_(pub_wo))).scalars()} if pub_wo else {}
        self.tol = int(plant.adherence_tolerance_minutes if plant is not None else 120)
        self.dlines = list(s.execute(select(MfgDemandLineRow).where(MfgDemandLineRow.due_date >= d0,
                                                                    MfgDemandLineRow.due_date <= d1)).scalars())
        ship: dict[str, list[tuple[date, float]]] = defaultdict(list)
        if self.dlines:
            for t in s.execute(select(MfgInvTransactionRow).where(
                    MfgInvTransactionRow.demand_line_id.in_([x.id for x in self.dlines]),
                    MfgInvTransactionRow.txn_type == "ship")).scalars():
                ship[t.demand_line_id].append((t.txn_date, -t.qty))
        self.ship = ship
        self.due_wos = list(s.execute(select(MfgWorkOrderRow).where(
            MfgWorkOrderRow.due_date >= d0, MfgWorkOrderRow.due_date <= d1,
            MfgWorkOrderRow.status != "cancelled")).scalars())
        rec: dict[str, list[tuple[date, float]]] = defaultdict(list)
        if self.due_wos:
            for t in s.execute(select(MfgInvTransactionRow).where(
                    MfgInvTransactionRow.wo_id.in_([w.id for w in self.due_wos]),
                    MfgInvTransactionRow.txn_type == "wo_receipt")).scalars():
                rec[t.wo_id].append((t.txn_date, t.qty))
        self.receipts = rec

    def keys_of_line(self, line_id: str | None) -> list[Key]:
        out: list[Key] = [("plant", "")]
        if line_id:
            out.append(("line", line_id))
            g = self.group_of.get(line_id)
            if g:
                out.append(("group", g))
        return out


def _day(dd: _Data, d: date) -> dict[str, dict[Key, list[float]]]:
    """metric -> dim key -> [num, den] for one local day."""
    from ....mfg.calendar import line_windows
    from .floor import _ev

    lo, hi = K.day_bounds(d, dd.tz)
    m: dict[str, dict[Key, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))

    def add(metric: str, keys: list[Key], num: float, den: float) -> None:
        for k in keys:
            v = m[metric][k]
            v[0] += num
            v[1] += den

    # windows, availability (unplanned downtime), utilisation, setup
    for lid, ln in dd.lines.items():
        if not ln.active:
            continue
        wins = [w for w in line_windows(dd.ds, lid, d, d + timedelta(days=1)) if w.kind == "base"]
        win = [(max(as_utc(w.start), lo), min(as_utc(w.end), hi)) for w in wins]
        win = [(a, b) for a, b in win if b > a]
        planned_down = unplanned = 0.0
        for dt in dd.downtime:
            if dt.line_id != lid:
                continue
            end = as_utc(dt.end_at) if dt.end_at else min(utcnow(), hi)
            mins = sum(K.clip_minutes(as_utc(dt.start_at), end, a, b) for a, b in win)
            if dt.planned:
                planned_down += mins
            else:
                unplanned += mins
        base = sum((b - a).total_seconds() / 60.0 for a, b in win) - planned_down
        if base <= 1e-9:
            continue
        keys = dd.keys_of_line(lid)
        add("availability", keys, max(0.0, base - unplanned), base)
        work = sum(K.clip_minutes(iv.start, iv.end, lo, hi) for iv in dd.intervals if iv.line_id == lid)
        add("utilisation", keys, work, base)
    for iv in dd.intervals:
        if iv.kind == "setup" and lo <= iv.start < hi:
            add("setup", dd.keys_of_line(iv.line_id), K.clip_minutes(iv.start, iv.end, iv.start, iv.end), 1.0)
    # performance, fpy, scrap from reports / completes of the day
    run_by_op: dict[tuple[str, str | None], float] = defaultdict(float)
    for iv in dd.intervals:
        if iv.kind == "running":
            run_by_op[(iv.wo_operation_id, iv.line_id)] += K.clip_minutes(iv.start, iv.end, lo, hi)
    std_by: dict[tuple[str, str | None], float] = defaultdict(float)
    for oid, evs in dd.events.items():
        o = dd.ops.get(oid)
        w = dd.wos.get(o.wo_id) if o else None
        if o is None or w is None:
            continue
        ro = dd.rops.get((w.routing_id or "", o.seq))
        for e in E.corrected([_ev(x) for x in evs]):
            if e.event_type not in E.QTY_EVENTS or not (lo <= e.event_at < hi):
                continue
            g, sc, rw = e.qty_good or 0.0, e.qty_scrap or 0.0, e.qty_rework or 0.0
            line = e.line_id or o.line_id
            keys = dd.keys_of_line(line)
            add("scrap_rate", keys, sc, g + sc)
            if ro is not None:
                ln = dd.lines.get(line or "")
                std_by[(oid, line)] += K.standard_minutes(g + sc, ro.run_minutes, ro.run_per, ro.units_per_panel,
                                                          ro.units_per_batch, ln.speed_factor if ln else 1.0)
                if ro.inspection_gate:
                    add("fpy", keys, *K.fpy(g, 0.0, sc, rw))
    for (oid, line), std in std_by.items():
        act = run_by_op.get((oid, line), 0.0)
        if act > 1e-9:
            add("performance", dd.keys_of_line(line), std, act)
    # adherence + planned setup (published run, planned to start this day)
    for p in dd.pub_ops:
        ps = as_utc(p.start_at)
        if not (lo <= ps < hi) or p.split_index != 0:
            continue
        keys = dd.keys_of_line(p.line_id)
        r = dd.pub_rows.get((p.order_id, p.seq))
        num, den = K.adherence([(ps, as_utc(p.end_at), as_utc(r.actual_start) if r and r.actual_start else None,
                                 as_utc(r.actual_end) if r and r.actual_end else None)], dd.tol)
        add("adherence", keys, num, den)
        add("setup_planned", keys, float(p.setup_minutes), 1.0 if p.setup_minutes else 0.0)
    # OTD (demand lines due this day) and WO on-time (plant only)
    for dl in dd.dlines:
        if dl.due_date != d:
            continue
        shipped = sum(q for t, q in dd.ship.get(dl.id, []) if t <= dl.due_date)
        add("otd", [("plant", "")], 1.0 if shipped + 1e-6 >= dl.qty else 0.0, 1.0)
    for w in dd.due_wos:
        if w.due_date != d:
            continue
        got = sum(q for t, q in dd.receipts.get(w.id, []) if t <= w.due_date)
        add("wo_on_time", [("plant", "")], 1.0 if got + 1e-6 >= w.qty else 0.0, 1.0)
    return m


# ---------------------------------------------------------------- cache

def _load_cache(s: Session, d0: date, d1: date) -> dict[date, dict[str, dict[Key, list[float]]]]:
    out: dict[date, dict[str, dict[Key, list[float]]]] = {}
    for r in s.execute(select(MfgKpiDailyRow).where(MfgKpiDailyRow.day >= d0, MfgKpiDailyRow.day <= d1)).scalars():
        out.setdefault(r.day, {}).setdefault(r.metric, {})[(r.dim_type, r.dim_id)] = [r.num, r.den]
    return out


def _store(ctx: AppContext, days: dict[date, dict[str, dict[Key, list[float]]]]) -> None:
    def fn(s: Session) -> None:
        now = utcnow()
        for d, metrics in days.items():
            s.execute(delete(MfgKpiDailyRow).where(MfgKpiDailyRow.day == d).execution_options(
                synchronize_session=False))
            rows = [MfgKpiDailyRow(id=new_id("kpd_"), day=d, metric=mt, dim_type=k[0], dim_id=k[1], num=v[0],
                                   den=v[1], value=K.ratio(v[0], v[1]), computed_at=now)
                    for mt, by in metrics.items() for k, v in by.items()]
            rows.append(MfgKpiDailyRow(id=new_id("kpd_"), day=d, metric="_computed", dim_type="plant", dim_id="",
                                       num=0.0, den=0.0, value=None, computed_at=now))
            s.add_all(rows)
        s.flush()

    try:
        run_tx(ctx, fn)
    except IntegrityError:        # a concurrent request cached the same days
        pass


def daily(ctx: AppContext, d0: date, d1: date) -> tuple[dict[date, dict[str, dict[Key, list[float]]]], Any, Any]:
    with read_tx(ctx) as s:
        _f, _t, tz, p = _period(s, d0, d1)
        today = utcnow().astimezone(tz).date()
        cache = _load_cache(s, d0, d1)
        missing = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
        missing = [d for d in missing if d >= today or "_computed" not in cache.get(d, {})]
        out = {d: v for d, v in cache.items() if d < today}
        if missing:
            dd = _Data(s, min(missing), max(missing), tz, p)
            fresh = {d: _day(dd, d) for d in missing}
            out.update(fresh)
        else:
            fresh = {}
    closed = {d: v for d, v in fresh.items() if d < today}
    if closed:
        _store(ctx, closed)
    return out, tz, p


def _agg(days: dict[date, dict[str, dict[Key, list[float]]]], metric: str, key: Key,
         pick: list[date] | None = None) -> tuple[float, float]:
    n = d = 0.0
    for day, ms in days.items():
        if pick is not None and day not in pick:
            continue
        v = ms.get(metric, {}).get(key)
        if v:
            n += v[0]
            d += v[1]
    return n, d


def _value(n: float, den: float) -> dict[str, Any]:
    return {"value": K.ratio(n, den), "num": round(n, 6), "den": round(den, 6), "unit": "ratio"}


def kpis(ctx: AppContext, frm: date | None, to: date | None, dim: str, dim_id: str | None, bucket: str
         ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        frm, to, _tz_, _p = _period(s, frm, to)
        if dim != "plant":
            model = MfgLineRow if dim == "line" else MfgGroupRow
            if not dim_id or s.get(model, dim_id) is None:
                raise ApiError(422, "VALIDATION_ERROR", f"dim_id must be an existing {dim}.",
                               {"errors": [{"loc": ["query", "dim_id"], "msg": "unknown", "type": "value_error"}]})
    days, tz, _p = daily(ctx, frm, to)
    key: Key = (dim, dim_id or "") if dim != "plant" else ("plant", "")
    metrics: dict[str, Any] = {}
    for mt in ("otd", "wo_on_time", "utilisation", "availability", "performance", "fpy", "adherence",
               "scrap_rate"):
        metrics[mt] = _value(*_agg(days, mt, key if mt not in ("otd", "wo_on_time") else ("plant", "")))
    a, pf, fq = (metrics[k]["value"] for k in ("availability", "performance", "fpy"))
    o = K.oee(a, pf, fq)
    metrics["oee"] = {"value": o, "num": o or 0.0, "den": 1.0 if o is not None else 0.0, "unit": "ratio"}
    sn, sd = _agg(days, "setup", key)
    pn, _pd = _agg(days, "setup_planned", key)
    metrics["setup"] = {"actual_minutes": round(sn, 3), "planned_minutes": round(pn, 3), "changeovers": int(sd)}
    with read_tx(ctx) as s:
        metrics["wip"] = _wip(s)
        top_scrap, top_down = _tops(s, frm, to, tz, key)
    # series
    all_days = [frm + timedelta(days=i) for i in range((to - frm).days + 1)]
    buckets: dict[str, list[date]] = defaultdict(list)
    for d in all_days:
        b = d if bucket == "day" else d - timedelta(days=d.weekday())
        buckets[b.isoformat()].append(d)
    series: dict[str, list[dict[str, Any]]] = {}
    for mt in ("otd", "utilisation", "availability", "performance", "fpy", "adherence", "scrap_rate"):
        k2 = key if mt != "otd" else ("plant", "")
        series[mt] = [{"bucket": b, "value": K.ratio(*_agg(days, mt, k2, ds))} for b, ds in sorted(buckets.items())]
    series["oee"] = [{"bucket": x["bucket"], "value": K.oee(x["value"], y["value"], z["value"])}
                     for x, y, z in zip(series["availability"], series["performance"], series["fpy"])]
    by_dim, worst = [], []
    with read_tx(ctx) as s:
        from types import SimpleNamespace

        lines = [SimpleNamespace(id=ln.id, code=ln.code, name=ln.name)
                 for ln in s.execute(select(MfgLineRow).order_by(MfgLineRow.code)).scalars()]
        ref = {ln.id: {"id": ln.id, "code": ln.code, "name": ln.name} for ln in lines}
    if dim == "plant":
        for ln in lines:
            k3: Key = ("line", ln.id)
            u, av, pfm, fp = (K.ratio(*_agg(days, mt, k3)) for mt in ("utilisation", "availability",
                                                                         "performance", "fpy"))
            if u is None and av is None:
                continue
            by_dim.append({"dim": "line", "ref": ref[ln.id], "utilisation": u, "availability": av,
                           "oee": K.oee(av, pfm, fp)})
            n, d = _agg(days, "adherence", k3)
            if d > 0:
                worst.append({"line": ref[ln.id], "value": K.ratio(n, d), "num": n, "den": d})
    worst.sort(key=lambda x: (x["value"], x["line"]["code"]))
    return {"period": {"from": frm.isoformat(), "to": to.isoformat(), "bucket": bucket, "dim": dim,
                       "dim_id": dim_id, "time_zone": str(tz)},
            "metrics": metrics, "series": series, "top_scrap": top_scrap, "top_downtime": top_down,
            "worst_adherence_lines": worst[:5], "by_dim": by_dim}


def _wip(s: Session) -> dict[str, Any]:
    wos = list(s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.status.in_(("released", "in_progress"))))
               .scalars())
    if not wos:
        return {"count": 0, "value": 0.0, "avg_age_days": 0.0}
    ids = [w.id for w in wos]
    its = {i.id: i for i in s.execute(select(MfgItemRow)).scalars()}
    value = 0.0
    for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id.in_(ids))).scalars():
        value += c.issued_qty * float(its[c.item_id].standard_cost or 0.0) if c.item_id in its else 0.0
    for w in wos:
        value += w.qty_completed * float(its[w.item_id].standard_cost or 0.0) if w.item_id in its else 0.0
    now = utcnow()
    ages = [(now - as_utc(w.released_at or w.created_at)).total_seconds() / 86400.0 for w in wos]
    return {"count": len(wos), "value": round(value, 2), "avg_age_days": round(sum(ages) / len(ages), 2)}


def _tops(s: Session, frm: date, to: date, tz: Any, key: Key) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lo, _x = K.day_bounds(frm, tz)
    _y, hi = K.day_bounds(to, tz)
    q = select(MfgFloorEventRow.reason_code, func.sum(MfgFloorEventRow.qty_scrap)).where(
        MfgFloorEventRow.event_at >= lo, MfgFloorEventRow.event_at < hi, MfgFloorEventRow.qty_scrap > 0,
        MfgFloorEventRow.event_type.in_(("report", "complete")))
    if key[0] == "line":
        q = q.where(MfgFloorEventRow.line_id == key[1])
    scrap = [{"reason_code": rc or "", "qty": float(qt or 0)} for rc, qt in
             s.execute(q.group_by(MfgFloorEventRow.reason_code).order_by(func.sum(MfgFloorEventRow.qty_scrap).desc())
                       .limit(5)).all()]
    dts = list(s.execute(select(MfgDowntimeRow).where(MfgDowntimeRow.start_at < hi,
                                                      (MfgDowntimeRow.end_at.is_(None)) |
                                                      (MfgDowntimeRow.end_at > lo))).scalars())
    agg: dict[tuple[str, str], float] = defaultdict(float)
    now = utcnow()
    for d in dts:
        if key[0] == "line" and d.line_id != key[1]:
            continue
        agg[(d.reason or d.kind, d.kind)] += K.clip_minutes(as_utc(d.start_at), as_utc(d.end_at) if d.end_at else now,
                                                            lo, hi)
    down = [{"reason": r, "kind": k, "minutes": round(v, 1)} for (r, k), v in
            sorted(agg.items(), key=lambda kv: -kv[1])[:5]]
    return scrap, down


def adherence(ctx: AppContext, frm: date | None, to: date | None, line_id: str | None, limit: int, offset: int
              ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        frm, to, tz, p = _period(s, frm, to)
        lo, _x = K.day_bounds(frm, tz)
        _y, hi = K.day_bounds(to, tz)
        tol = int(p.adherence_tolerance_minutes if p is not None else 120)
        pub = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
        if pub is None:
            return {"items": [], "total": 0, "limit": limit, "offset": offset, "run_id": None,
                    "tolerance_minutes": tol}
        conds = [MfgApsOpRow.run_id == pub.id, MfgApsOpRow.status == "scheduled", MfgApsOpRow.order_type == "wo",
                 MfgApsOpRow.split_index == 0, MfgApsOpRow.start_at >= lo, MfgApsOpRow.start_at < hi]
        if line_id:
            conds.append(MfgApsOpRow.line_id == line_id)
        total = int(s.execute(select(func.count()).select_from(MfgApsOpRow).where(*conds)).scalar() or 0)
        ops = list(s.execute(select(MfgApsOpRow).where(*conds).order_by(MfgApsOpRow.start_at, MfgApsOpRow.op_no)
                             .limit(limit).offset(offset)).scalars())
        rows = {(r.wo_id, r.seq): r for r in s.execute(select(MfgWoOperationRow).where(
            MfgWoOperationRow.wo_id.in_({o.order_id for o in ops}))).scalars()} if ops else {}
        lines = {ln.id: ln for ln in s.execute(select(MfgLineRow)).scalars()}
        items = []
        for o in ops:
            r = rows.get((o.order_id, o.seq))
            ps, pe = as_utc(o.start_at), as_utc(o.end_at)
            a_s = as_utc(r.actual_start) if r and r.actual_start else None
            a_e = as_utc(r.actual_end) if r and r.actual_end else None
            n, _d = K.adherence([(ps, pe, a_s, a_e)], tol)
            ln = lines.get(o.line_id or "")
            items.append({"wo_operation_id": r.id if r else None, "wo": {"id": o.order_id, "number": o.order_number},
                          "seq": o.seq, "line": {"id": ln.id, "code": ln.code, "name": ln.name} if ln else None,
                          "planned_start": ps, "planned_end": pe, "actual_start": a_s, "actual_end": a_e,
                          "start_delta_minutes": round((a_s - ps).total_seconds() / 60, 1) if a_s else None,
                          "end_delta_minutes": round((a_e - pe).total_seconds() / 60, 1) if a_e else None,
                          "adherent": bool(n)})
        return {"items": items, "total": total, "limit": limit, "offset": offset, "run_id": pub.id,
                "tolerance_minutes": tol}
