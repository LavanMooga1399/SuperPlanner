"""Management dashboards (M6-DESIGN 3.1-3.2, 5 D1-D3, D7): tiles computed from existing M2-M5 tables plus the
daily inventory value snapshot; read inside `replica_reads()` by the routers (replica when configured and fresh).

Tiles: `otd` (M4 KPIs, weekly trend, WO on-time), `backlog` (published run load: required vs base capacity next 4 /
8 weeks per stage; open WO standard hours beyond the horizon), `material_risk` (latest live MRP: items short within
4 weeks with their value at standard cost, late demand lines; latest risk run: lines with P(on time) < 80%),
`execution` (adherence, OEE-lite, FPY, scrap rate), `inventory` (on hand x standard cost by family; turns over 12
months = value of `wo_issue` + `ship` issues / average month-end snapshot value, "n/a" until 3 month-ends exist),
`late_pos` (open overdue PO schedules + 12-month receipt lateness per supplier), `quality` (recalls of the period,
ECOs by status, top scrap reasons), `integration` (dead deliveries, failed batches, stale reconciliation)."""

from __future__ import annotations

import csv
import io
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ....mfg.model_m6 import DEFAULT_THRESHOLDS, TILE_NAMES
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.ownership import current_owner
from ...errors import ApiError, not_found
from ...schemas import as_utc
from ..db_models import MfgItemRow, MfgOperationRow, MfgPlantRow
from ..db_models_m2 import (MfgInvBalanceRow, MfgInvTransactionRow, MfgLocationRow, MfgMrpDemandResultRow,
                            MfgMrpItemResultRow, MfgMrpRunRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                            MfgPurchaseScheduleRow, MfgSupplierRow, MfgWorkOrderRow)
from ..db_models_m3 import MfgApsLoadRow, MfgApsRunRow
from ..db_models_m4 import MfgApsSimulationRow
from ..db_models_m5 import MfgChangeRequestRow, MfgRecallRow
from ..db_models_m6 import MfgInventorySnapshotRow
from .common import audit, read_tx, write_tx

PERIOD_DAYS = {"4w": 28, "13w": 91, "52w": 364}
EPS = 1e-9


# ---------------------------------------------------------------- thresholds and status

def thresholds_of(raw: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    out = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
    for k, v in (raw or {}).items():
        if k in out and isinstance(v, dict):
            out[k].update({kk: vv for kk, vv in v.items() if vv is not None})
    return out


def status_of(value: float | None, th: dict[str, float]) -> str:
    if value is None:
        return "n/a"
    if "alert_below" in th and value < th["alert_below"]:
        return "alert"
    if "alert_above" in th and value > th["alert_above"]:
        return "alert"
    if "watch_below" in th and value < th["watch_below"]:
        return "watch"
    if "watch_above" in th and value > th["watch_above"]:
        return "watch"
    return "ok"


def worst(*st: str) -> str:
    order = {"alert": 3, "watch": 2, "ok": 1, "n/a": 0}
    return max(st, key=lambda x: order[x]) if st else "n/a"


def put_thresholds(ctx: AppContext, body: Any) -> dict[str, Any]:
    raw = {k: v.model_dump(exclude_none=True) for k, v in body.thresholds.items()}
    with write_tx(ctx) as (s, plant):
        assert plant is not None
        plant.dashboard_thresholds = raw
        audit(s, "plant", plant.id, "dashboard_thresholds", raw)
        s.flush()
    return {"thresholds": thresholds_of(raw)}


# ---------------------------------------------------------------- turns (T-D1)

def inventory_turns(snapshots: dict[date, float], issue_value: float) -> float | None:
    """`snapshots`: day -> plant total value; month-end = the last snapshot day of each month. Turns = issue value
    of the 12 months / average month-end value; None until 3 month-ends exist."""
    month_end: dict[tuple[int, int], tuple[date, float]] = {}
    for d, v in snapshots.items():
        k = (d.year, d.month)
        if k not in month_end or d > month_end[k][0]:
            month_end[k] = (d, v)
    vals = [v for _d, v in sorted(month_end.values())][-12:]
    if len(vals) < 3:
        return None
    avg = sum(vals) / len(vals)
    return round(issue_value / avg, 3) if avg > EPS else None


# ---------------------------------------------------------------- the plant dashboard

def _plant_row(s: Any) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow)).scalars().first()


def _today(p: Any) -> date:
    from ....mfg.tz import plant_tz

    return datetime.now(UTC).astimezone(plant_tz(p)).date() if p is not None else datetime.now(UTC).date()


def plant_dashboard(ctx: AppContext, period: str) -> dict[str, Any]:
    from ...db.session import _read_source
    from . import kpi

    t0 = time.monotonic()
    days = PERIOD_DAYS[period]
    with read_tx(ctx) as s:
        p = _plant_row(s)
        today = _today(p)
        th = thresholds_of(p.dashboard_thresholds if p is not None else None)
        plant = {"owner_id": str(current_owner()), "name": p.name if p else "Plant",
                 "currency": p.currency if p else "", "time_zone": (p.time_zone or p.utc_offset) if p else "+00:00"}
        cur = plant["currency"]
        tiles: dict[str, Any] = {}
        timings: dict[str, int] = {}

        def timed(name: str, fn: Any, *a: Any) -> Any:
            t1 = time.monotonic()
            out = fn(*a)
            timings[name] = int((time.monotonic() - t1) * 1000)
            return out
        tiles["backlog"] = timed("backlog", _backlog, s, today, th)
        tiles["material_risk"] = timed("material_risk", _material, s, today, th, cur)
        tiles["inventory"] = timed("inventory", _inventory, s, today, cur)
        tiles["late_pos"] = timed("late_pos", _late_pos, s, today, th)
        quality = timed("quality", _quality, s, today - timedelta(days=days))
        tiles["integration"] = timed("integration", _integration, s)
    t1 = time.monotonic()
    try:
        k = kpi.kpis(ctx, today - timedelta(days=days - 1), today, "plant", None, "week")
    except ApiError:
        k = {"metrics": {}, "series": {}, "top_scrap": []}
    timings["kpis"] = int((time.monotonic() - t1) * 1000)
    m = k["metrics"]

    def val(name: str) -> float | None:
        return (m.get(name) or {}).get("value")

    otd = val("otd")
    tiles["otd"] = {"value": otd, "unit": "%", "status": status_of(otd, th["otd"]), "thresholds": th["otd"],
                    "trend": [{"period": x["bucket"], "value": x["value"]} for x in k["series"].get("otd", [])],
                    "details": {"wo_on_time": val("wo_on_time"), "num": (m.get("otd") or {}).get("num"),
                                "den": (m.get("otd") or {}).get("den")},
                    "drill": [{"label": "Demand lines", "path": f"/mfg/demand?due_from={today - timedelta(days=days)}"}]}
    adh, fpy = val("adherence"), val("fpy")
    tiles["execution"] = {"value": adh, "unit": "%",
                          "status": worst(status_of(adh, th["adherence"]), status_of(fpy, th["fpy"])),
                          "thresholds": {"adherence": th["adherence"], "fpy": th["fpy"]},
                          "trend": [{"period": x["bucket"], "value": x["value"]}
                                    for x in k["series"].get("adherence", [])],
                          "details": {"adherence": adh, "oee": val("oee"), "fpy": fpy, "scrap_rate": val("scrap_rate")},
                          "drill": [{"label": "KPIs", "path": "/mfg/kpis"}]}
    quality["details"]["top_scrap_reasons"] = (k.get("top_scrap") or [])[:5]
    tiles["quality"] = quality
    out_tiles = {n: _tile(tiles[n]) for n in TILE_NAMES}
    src = _read_source.get()
    return {"as_of": utcnow(), "period": period, "plant": plant, "tiles": out_tiles,
            "source": "replica" if src and "replica" in src and "primary" not in src else "primary",
            "computed_ms": int((time.monotonic() - t0) * 1000), "timings_ms": timings}


def _tile(t: dict[str, Any]) -> dict[str, Any]:
    base = {"value": None, "unit": "", "trend": [], "status": "ok", "thresholds": {}, "drill": [], "details": {},
            "note": ""}
    base.update(t)
    return base


def _backlog(s: Any, today: date, th: dict[str, Any]) -> dict[str, Any]:
    from ..db_models import MfgGroupRow

    pub = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
    if pub is None:
        return {"value": None, "unit": "%", "status": "n/a", "note": "No published schedule.",
                "drill": [{"label": "Schedule runs", "path": "/mfg/schedule"}]}
    L = MfgApsLoadRow
    groups = {g.id: g.code for g in s.execute(select(MfgGroupRow)).scalars()}
    rows = s.execute(select(L.group_id, L.day, L.required_minutes, L.base_minutes).where(
        L.run_id == pub.id, L.line_id.is_(None), L.day >= today, L.day < today + timedelta(days=56))).all()
    agg: dict[str, dict[str, float]] = defaultdict(lambda: {"r4": 0.0, "b4": 0.0, "r8": 0.0, "b8": 0.0})
    for g, d, req, base in rows:
        a = agg[g]
        a["r8"] += req
        a["b8"] += base
        if d < today + timedelta(days=28):
            a["r4"] += req
            a["b4"] += base
    tot = {k: sum(a[k] for a in agg.values()) for k in ("r4", "b4", "r8", "b8")}
    l4 = tot["r4"] / tot["b4"] if tot["b4"] > EPS else None
    l8 = tot["r8"] / tot["b8"] if tot["b8"] > EPS else None
    by_stage = sorted(({"stage": groups.get(g, g), "group_id": g,
                        "load_4w": round(a["r4"] / a["b4"], 4) if a["b4"] > EPS else None,
                        "load_8w": round(a["r8"] / a["b8"], 4) if a["b8"] > EPS else None} for g, a in agg.items()),
                      key=lambda x: -(x["load_4w"] or 0))
    horizon_end = as_utc(pub.horizon_end).date()
    beyond = 0.0
    wos = s.execute(select(MfgWorkOrderRow.qty, MfgWorkOrderRow.qty_completed, MfgWorkOrderRow.routing_id).where(
        MfgWorkOrderRow.status.in_(("planned", "released", "in_progress")),
        MfgWorkOrderRow.start_date > horizon_end)).all()
    rids = {r for _q, _c, r in wos if r}
    ops: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if rids:
        for rid, su, run in s.execute(select(MfgOperationRow.routing_id, MfgOperationRow.setup_minutes,
                                             MfgOperationRow.run_minutes).where(
                MfgOperationRow.routing_id.in_(rids))).all():
            ops[rid].append((su or 0.0, run or 0.0))
    for q, c, r in wos:
        beyond += sum(su + run * max(0.0, q - c) for su, run in ops.get(r or "", []))
    return {"value": round(l4, 4) if l4 is not None else None, "unit": "%",
            "status": status_of(l4, th["backlog_load"]), "thresholds": th["backlog_load"],
            "details": {"weeks_4": {"required_h": round(tot["r4"] / 60, 1), "capacity_h": round(tot["b4"] / 60, 1),
                                    "load": round(l4, 4) if l4 is not None else None},
                        "weeks_8": {"required_h": round(tot["r8"] / 60, 1), "capacity_h": round(tot["b8"] / 60, 1),
                                    "load": round(l8, 4) if l8 is not None else None},
                        "by_stage": by_stage, "beyond_horizon_h": round(beyond / 60, 1),
                        "beyond_horizon_wos": len(wos), "run_id": pub.id},
            "drill": [{"label": "Load view", "path": f"/mfg/schedule/runs/{pub.id}?view=load"}]}


def _material(s: Any, today: date, th: dict[str, Any], cur: str) -> dict[str, Any]:
    run = s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                    .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalars().first()
    if run is None:
        return {"value": None, "unit": "count", "status": "n/a", "note": "No live MRP run.",
                "drill": [{"label": "MRP", "path": "/mfg/mrp"}]}
    I = MfgMrpItemResultRow
    short = s.execute(select(I.item_id, I.short_qty, MfgItemRow.standard_cost).join(
        MfgItemRow, MfgItemRow.id == I.item_id, isouter=True).where(
        I.run_id == run.id, I.first_short_date.is_not(None), I.first_short_date <= today + timedelta(days=28),
        I.short_qty > EPS)).all()
    value = sum(q * (c or 0.0) for _i, q, c in short)
    D = MfgMrpDemandResultRow
    late = int(s.execute(select(func.count()).select_from(D).where(D.run_id == run.id, D.late_days > 0)).scalar() or 0)
    sim = s.execute(select(MfgApsSimulationRow).where(MfgApsSimulationRow.status == "completed")
                    .order_by(MfgApsSimulationRow.created_at.desc()).limit(1)).scalars().first()
    risk = None
    if sim is not None:
        risk = sum(1 for d in (sim.results or {}).get("demand", []) if (d.get("p_on_time") or 0) < 0.8)
    n = len(short)
    return {"value": n, "unit": "count", "status": status_of(float(n), th["material_risk"]),
            "thresholds": th["material_risk"],
            "details": {"items_short_4w": n, "value_short_4w": round(value, 2), "currency": cur,
                        "late_lines_material": late, "risk_lines_below_80": risk, "run_id": run.id,
                        "risk_run_id": sim.id if sim else None},
            "drill": [{"label": "Short items", "path": f"/mfg/mrp/runs/{run.id}?short_only=1"},
                      {"label": "Exceptions", "path": f"/mfg/mrp/runs/{run.id}/exceptions"}]}


def _inventory_now(s: Any) -> list[tuple[str, str, float, int]]:
    """[(family, location kind, value, items)] of the current on-hand stock at standard cost."""
    from sqlalchemy import literal_column

    B = MfgInvBalanceRow
    fam = func.coalesce(MfgItemRow.family, literal_column("''"))
    rows = s.execute(select(fam, MfgLocationRow.kind,
                            func.sum(B.qty_on_hand * func.coalesce(MfgItemRow.standard_cost, 0.0)),
                            func.count(func.distinct(B.item_id)))
                     .join(MfgItemRow, MfgItemRow.id == B.item_id).join(MfgLocationRow,
                                                                         MfgLocationRow.id == B.location_id)
                     .where(B.qty_on_hand > EPS).group_by(fam, MfgLocationRow.kind)).all()
    return [(f, k, float(v or 0.0), int(n)) for f, k, v, n in rows]


def issue_value(s: Any, d0: date, d1: date) -> float:
    T = MfgInvTransactionRow
    v = s.execute(select(func.sum(func.abs(T.qty) * func.coalesce(MfgItemRow.standard_cost, 0.0))).join(
        MfgItemRow, MfgItemRow.id == T.item_id).where(T.txn_type.in_(("wo_issue", "ship")), T.qty < 0,
                                                      T.txn_date > d0, T.txn_date <= d1)).scalar()
    return float(v or 0.0)


def snapshot_totals(s: Any, d0: date) -> dict[date, float]:
    S = MfgInventorySnapshotRow
    return {d: float(v or 0.0) for d, v in s.execute(select(S.day, func.sum(S.qty_value)).where(S.day >= d0)
                                                     .group_by(S.day)).all()}


def _inventory(s: Any, today: date, cur: str) -> dict[str, Any]:
    rows = _inventory_now(s)
    total = sum(v for _f, _k, v, _n in rows)
    fam: dict[str, float] = defaultdict(float)
    for f, _k, v, _n in rows:
        fam[f or "(none)"] += v
    turns = inventory_turns(snapshot_totals(s, today - timedelta(days=366)),
                            issue_value(s, today - timedelta(days=365), today))
    return {"value": round(total, 2), "unit": cur, "status": "ok",
            "details": {"turns": turns, "turns_note": "" if turns is not None else
                        "n/a until 3 monthly snapshots exist",
                        "by_family": sorted(({"family": f, "value": round(v, 2)} for f, v in fam.items()),
                                            key=lambda x: -x["value"])[:20]},
            "drill": [{"label": "Stock by family", "path": "/mfg/inventory?by=family"}]}


def supplier_lateness_rows(s: Any, today: date, supplier_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Per supplier: receipts of the last 12 months against their schedule's dock date (confirmed or requested)."""
    T, S, Ln, Dc = MfgInvTransactionRow, MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow
    q = select(Dc.supplier_id, T.txn_date, func.coalesce(S.confirmed_date, S.requested_date)).join(
        S, S.id == T.schedule_id).join(Ln, Ln.id == S.line_id).join(Dc, Dc.id == Ln.doc_id).where(
        T.txn_type == "po_receipt", T.qty > 0, T.txn_date > today - timedelta(days=365))
    if supplier_id:
        q = q.where(Dc.supplier_id == supplier_id)
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"receipts": 0, "late": 0, "late_days": 0})
    for sid, got, dock in s.execute(q).all():
        if not sid:
            continue
        o = out[sid]
        o["receipts"] += 1
        if dock is not None and got > dock:
            o["late"] += 1
            o["late_days"] += (got - dock).days
    for o in out.values():
        o["lateness_12m"] = round(o["late"] / o["receipts"], 4) if o["receipts"] else None
    return out


def _overdue(s: Any, today: date) -> dict[str, int]:
    S, Ln, Dc = MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow
    rows = s.execute(select(Dc.supplier_id, func.count()).select_from(S).join(Ln, Ln.id == S.line_id).join(
        Dc, Dc.id == Ln.doc_id).where(Dc.doc_type == "po", Dc.status.in_(("open", "partially_received")),
                                      Ln.status == "open", S.closed.is_(False), S.qty - S.received_qty > EPS,
                                      func.coalesce(S.confirmed_date, S.requested_date) < today)
                     .group_by(Dc.supplier_id)).all()
    return {sid or "": int(n) for sid, n in rows}


def _late_pos(s: Any, today: date, th: dict[str, Any]) -> dict[str, Any]:
    over = _overdue(s, today)
    hist = supplier_lateness_rows(s, today)
    sups = {x.id: x for x in s.execute(select(MfgSupplierRow)).scalars()}
    by = []
    for sid in sorted(set(over) | set(hist)):
        sp = sups.get(sid)
        by.append({"supplier": {"id": sid, "code": sp.code if sp else "", "name": sp.name if sp else ""},
                   "open_overdue": over.get(sid, 0), "lateness_12m": hist.get(sid, {}).get("lateness_12m"),
                   "receipts_12m": hist.get(sid, {}).get("receipts", 0)})
    by.sort(key=lambda x: (-x["open_overdue"], -(x["lateness_12m"] or 0)))
    n = sum(over.values())
    return {"value": n, "unit": "count", "status": status_of(float(n), th["late_pos"]), "thresholds": th["late_pos"],
            "details": {"by_supplier": by[:20]},
            "drill": [{"label": "Delivery board", "path": "/mfg/purchasing/schedule?overdue=1"}]}


def _quality(s: Any, since: date) -> dict[str, Any]:
    rec = int(s.execute(select(func.count()).select_from(MfgRecallRow).where(
        MfgRecallRow.created_at >= datetime.combine(since, datetime.min.time(), UTC))).scalar() or 0)
    ecos = dict(s.execute(select(MfgChangeRequestRow.status, func.count()).where(
        MfgChangeRequestRow.status.not_in(("implemented", "cancelled", "rejected")))
        .group_by(MfgChangeRequestRow.status)).all())
    return {"value": rec, "unit": "count", "status": "alert" if rec else "ok",
            "details": {"open_recalls": rec, "ecos_by_status": {k: int(v) for k, v in ecos.items()}},
            "drill": [{"label": "Recalls", "path": "/mfg/recalls"}, {"label": "ECOs", "path": "/mfg/eco"}]}


def _integration(s: Any) -> dict[str, Any]:
    from ..db_models_m5 import IntDeliveryRow, IntInboxRow, IntReconciliationRow, IntSettingsRow

    st = s.execute(select(IntSettingsRow)).scalars().first()
    dead = int(s.execute(select(func.count()).select_from(IntDeliveryRow).where(IntDeliveryRow.status == "dead"))
               .scalar() or 0)
    failed = int(s.execute(select(func.count()).select_from(IntInboxRow).where(
        IntInboxRow.received_at >= utcnow() - timedelta(days=7), IntInboxRow.status == "failed")).scalar() or 0)
    last_rec = s.execute(select(func.max(IntReconciliationRow.created_at))).scalar()
    stale = bool(st and st.enabled and (last_rec is None or as_utc(last_rec) < utcnow() - timedelta(days=7)))
    n = dead + failed
    return {"value": n, "unit": "count", "status": "n/a" if not (st and st.enabled) else
            ("alert" if n else "watch" if stale else "ok"),
            "details": {"enabled": bool(st and st.enabled), "dead_deliveries": dead, "failed_batches_7d": failed,
                        "stale_reconciliation": stale, "last_reconciliation_at": as_utc(last_rec)},
            "drill": [{"label": "Integration console", "path": "/mfg/integration"}]}


def supplier_lateness(ctx: AppContext, supplier_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        today = _today(_plant_row(s))
        return dict(supplier_lateness_rows(s, today, supplier_id).get(supplier_id) or
                    {"receipts": 0, "late": 0, "late_days": 0, "lateness_12m": None})


def top_alerts(ctx: AppContext) -> list[dict[str, Any]]:
    """Digest list: open critical / warning replan triggers and MRP critical exceptions (top 10)."""
    from ..db_models_m2 import MfgMrpExceptionRow
    from ..db_models_m4 import MfgReplanTriggerRow

    out: list[dict[str, Any]] = []
    with read_tx(ctx) as s:
        for t in s.execute(select(MfgReplanTriggerRow).where(MfgReplanTriggerRow.status == "open")
                           .order_by(MfgReplanTriggerRow.detected_at.desc()).limit(10)).scalars():
            out.append({"text": f"{t.kind.replace('_', ' ')} ({t.severity})", "link": "/mfg/replan"})
        run = s.execute(select(MfgMrpRunRow.id).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                        .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalar()
        if run:
            for x in s.execute(select(MfgMrpExceptionRow).where(MfgMrpExceptionRow.run_id == run,
                                                                MfgMrpExceptionRow.severity == "critical")
                               .limit(10)).scalars():
                out.append({"text": f"{x.code}: {x.message[:120]}", "link": f"/mfg/mrp/runs/{run}/exceptions"})
    return out[:10]


# ---------------------------------------------------------------- export (D2)

def export(ctx: AppContext, period: str, fmt: str) -> tuple[bytes, str, str]:
    d = plant_dashboard(ctx, period)
    rows = [["tile", "value", "unit", "status", "note"]]
    for name, t in d["tiles"].items():
        rows.append([name, "" if t["value"] is None else t["value"], t["unit"], t["status"], t["note"]])
    stamp = d["as_of"].strftime("%Y%m%d")
    if fmt == "csv":
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        return buf.getvalue().encode("utf-8"), f"dashboard-{stamp}.csv", "text/csv"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Tiles"
    for r in rows:
        ws.append(r)
    for name, t in d["tiles"].items():
        if t["trend"]:
            sh = wb.create_sheet(f"{name} trend"[:31])
            sh.append(["period", "value"])
            for x in t["trend"]:
                sh.append([x["period"], x["value"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"dashboard-{stamp}.xlsx", \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------- org dashboard (D3)

#: totals: sums for counts / values, weighted averages for ratios (weights stated in details.weights)
SUM_TILES = ("material_risk", "late_pos", "quality", "integration", "inventory")


def org_dashboard(ctx: AppContext, user_id: str, org_id: str, period: str) -> dict[str, Any]:
    from ...db.ownership import bind_actor, owner_scope, system_scope
    from ..access import permissions_of
    from ..db_models_m2 import MfgPlantMemberRow
    from ..db_models_m5 import OrgMemberRow, OrgPlantRow, OrgRow

    t0 = time.monotonic()
    with system_scope(), ctx.db.read() as s:
        org = s.get(OrgRow, org_id)
        mem = s.execute(select(OrgMemberRow).where(OrgMemberRow.org_id == org_id, OrgMemberRow.user_id == user_id,
                                                   OrgMemberRow.accepted_at.is_not(None))).scalars().first() \
            if org is not None else None
        if org is None or mem is None:
            raise not_found("Organisation", org_id)
        plants = list(s.execute(select(OrgPlantRow).where(OrgPlantRow.org_id == org_id)
                                .order_by(OrgPlantRow.code)).scalars())
        roles = {m.owner_id: list(m.roles or []) for m in s.execute(select(MfgPlantMemberRow).where(
            MfgPlantMemberRow.user_id == user_id, MfgPlantMemberRow.active.is_(True))).scalars()}
        s.expunge_all()
    visible = [p for p in plants if p.plant_owner_id == user_id or "view" in permissions_of(
        roles.get(p.plant_owner_id, []))]
    out = []
    for p in visible:
        with owner_scope(p.plant_owner_id):
            bind_actor(user_id)
            d = plant_dashboard(ctx, period)
        out.append({"plant": {"owner_id": p.plant_owner_id, "code": p.code, "name": p.name,
                              "currency": d["plant"]["currency"]}, "tiles": d["tiles"],
                    "_den": {"otd": ((d["tiles"]["otd"]["details"] or {}).get("den") or 0)}})
    totals = _totals(out)
    for x in out:
        x.pop("_den", None)
    return {"as_of": utcnow(), "period": period, "org": {"id": org.id, "name": org.name}, "plants": out,
            "totals": totals, "computed_ms": int((time.monotonic() - t0) * 1000)}


def _totals(plants: list[dict[str, Any]]) -> dict[str, Any]:
    tot: dict[str, Any] = {}
    for name in SUM_TILES:
        vals = [x["tiles"][name]["value"] for x in plants if x["tiles"][name]["value"] is not None]
        currencies = {x["plant"]["currency"] for x in plants}
        note = "" if name != "inventory" or len(currencies) <= 1 else "plants use different currencies"
        tot[name] = _tile({"value": round(sum(vals), 2) if vals else None,
                           "unit": plants[0]["tiles"][name]["unit"] if plants else "",
                           "status": worst(*[x["tiles"][name]["status"] for x in plants]) if plants else "n/a",
                           "details": {"weights": "sum over plants", "plants": len(vals)}, "note": note})
    w = [(x["tiles"]["otd"]["value"], x["_den"]["otd"]) for x in plants if x["tiles"]["otd"]["value"] is not None]
    den = sum(d for _v, d in w)
    tot["otd"] = _tile({"value": round(sum(v * d for v, d in w) / den, 4) if den > 0 else None, "unit": "%",
                        "status": worst(*[x["tiles"]["otd"]["status"] for x in plants]) if plants else "n/a",
                        "details": {"weights": "due demand lines per plant (KPI denominators)", "den": den}})
    for name, key in (("execution", "adherence"), ("backlog", "load")):
        vals = [x["tiles"][name]["value"] for x in plants if x["tiles"][name]["value"] is not None]
        tot[name] = _tile({"value": round(sum(vals) / len(vals), 4) if vals else None, "unit": "%",
                           "status": worst(*[x["tiles"][name]["status"] for x in plants]) if plants else "n/a",
                           "details": {"weights": f"unweighted mean of plant {key}", "plants": len(vals)}})
    return {n: tot[n] for n in TILE_NAMES}


# ---------------------------------------------------------------- daily inventory snapshot (3.2)

def snapshot(s: Any, owner_id: str, day: date) -> int:
    """Write (upsert) the day's rows of one plant (caller bound to the plant)."""
    now = utcnow()
    n = 0
    for fam, kind, value, items in _inventory_now(s):
        stmt = pg_insert(MfgInventorySnapshotRow).values(
            id=new_id("ivs_"), owner_id=owner_id, day=day, item_family=(fam or "")[:32], location_kind=kind[:16],
            qty_value=round(value, 4), items=items, created_at=now)
        s.execute(stmt.on_conflict_do_update(constraint="uq_mfg_inventory_snapshots_key",
                                             set_={"qty_value": stmt.excluded.qty_value,
                                                   "items": stmt.excluded["items"]}))
        n += 1
    return n


def run_snapshot_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ....integration.jobs import run_duty

    def fn(info: dict[str, Any]) -> dict[str, Any]:
        with ctx.write_guard(), ctx.db.write() as s:
            day = _today(_plant_row(s))
            out = {"day": day.isoformat(), "rows": snapshot(s, info["owner"], day)}
        # warm the M4 closed-day KPI cache for the 52-week dashboard (DB1: the first view of the day stays fast)
        from . import kpi

        try:
            kpi.daily(ctx, day - timedelta(days=PERIOD_DAYS["52w"] - 1), day)
            out["kpi_cache_days"] = PERIOD_DAYS["52w"]
        except ApiError:
            pass
        return out

    run_duty(ctx, run_id, lease, fn)
