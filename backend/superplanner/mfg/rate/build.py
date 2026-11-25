"""Rate problem snapshot (M8-DESIGN 7.1-7.2 step 1): database -> `RateProblem` in one read transaction.

- Lines: active lines with `planning flow` (or the given ids); windows from M1 `calendar.line_windows` (`base`;
  plus `optional` windows marked overtime when `overtime allow`), horizon = as_of 00:00 plant time + horizon days.
  The plant UTC offset at `as_of` is used for plant-local dates (DST changes inside the horizon shift prod_date
  boundaries by one hour; accepted).
- Rates: item row > family row; effective = units_per_hour x (row oee, else line oee). No row -> not eligible.
- Items: `replenishment rate` items; key = campaign_key, else setup_family, else part number; case = packaging
  `case` qty_base.
- Demand: planned orders of rate items in the MRP pass-1 run (given, else the latest completed live run planned
  with `rate_supply false`, else the latest live run), due = need date - post_days; source from the order's pegs
  (order / forecast / ss / dependent). Planned orders are net of stock and existing WOs, so initial stock is 0 and
  firm blocks (WOs) are already netted (`firm_netted`).
- Firm blocks (keep_firm): production / setup blocks of the published run with prod_date <= today + firm days.
- Material: components (BOM lines) of rate items that are short in the pass-1 run; their projected availability =
  as_of + the component's lead time (earliest new supply) -> `RATE_MATERIAL_SHORT` for earlier blocks.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .model import ChangeoverRule, RateBlock, RateDemand, RateItem, RateLine, RateParams, RateProblem, Window


def pass1_run(s: Session, mrp_run_id: str | None) -> Any:
    from ...api.mfg.db_models_m2 import MfgMrpRunRow

    if mrp_run_id:
        return s.get(MfgMrpRunRow, mrp_run_id)
    runs = list(s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                          .order_by(MfgMrpRunRow.run_no.desc()).limit(20)).scalars())
    for r in runs:
        if (r.params or {}).get("rate_supply") is False:
            return r
    return runs[0] if runs else None


def _source(peg_summary: Any) -> str:
    best = None
    for p in peg_summary or []:
        if isinstance(p, dict):
            lid, label, qty = p.get("demand_line_id"), p.get("label", ""), p.get("qty", 0)
        else:
            lid, label, qty = p[0], p[1], p[2]
        if best is None or qty > best[0]:
            best = (qty, lid, label)
    if best is None:
        return "dependent"
    if best[1]:
        return "order"
    if str(best[2]).startswith("Forecast"):
        return "forecast"
    if str(best[2]).startswith("Safety stock"):
        return "ss"
    return "dependent"


def build(s: Session, params: RateParams, *, as_of: date, settings: Any, today: date) -> tuple[RateProblem, Any]:
    from ...api.mfg import repo
    from ...api.mfg.db_models import MfgBomLineRow, MfgBomRow, MfgItemRow, MfgLineRow
    from ...api.mfg.db_models_m2 import MfgMrpItemResultRow, MfgMrpPlannedOrderRow
    from ...api.mfg.db_models_m8 import (MfgChangeoverRow, MfgItemPackagingRow, MfgItemPlanningRow, MfgLineRateRow,
                                         MfgRateBlockRow, MfgRateRunRow)
    from ..calendar import line_windows
    from ..tz import plant_tz

    ds = repo.load_dataset(s)
    tz = plant_tz(ds.plant)
    t0 = datetime.combine(as_of, time(0), tz).astimezone(UTC)
    days = params.horizon_days or settings.rate_horizon_days
    t1 = t0 + timedelta(days=days)
    off = int(datetime.combine(as_of, time(12), tz).utcoffset().total_seconds() // 60)
    q = select(MfgLineRow).where(MfgLineRow.active.is_(True))
    if params.line_ids:
        q = q.where(MfgLineRow.id.in_(params.line_ids))
    else:
        q = q.where(MfgLineRow.planning == "flow")
    line_rows = list(s.execute(q.order_by(MfgLineRow.code)).scalars())
    plan = {r.item_id: r for r in s.execute(select(MfgItemPlanningRow).where(
        MfgItemPlanningRow.replenishment == "rate")).scalars()}
    items_rows = {r.id: r for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(list(plan)))).scalars()} \
        if plan else {}
    cases = {i: q for i, q in s.execute(select(MfgItemPackagingRow.item_id, MfgItemPackagingRow.qty_base).where(
        MfgItemPackagingRow.level == "case"))}
    rates_by_line: dict[str, list[Any]] = {}
    for r in s.execute(select(MfgLineRateRow)).scalars():
        rates_by_line.setdefault(r.line_id, []).append(r)
    kinds = ("base", "optional") if params.overtime == "allow" else ("base",)
    lines = []
    for ln in line_rows:
        wins = []
        for w in line_windows(ds, ln.id, as_of - timedelta(days=1), as_of + timedelta(days=days + 1), kinds=kinds):
            a, b = max(w.start, t0), min(w.end, t1)
            if b > a:
                wins.append(Window(a, b, w.kind == "optional"))
        by_item = {r.item_id: r for r in rates_by_line.get(ln.id, []) if r.item_id}
        by_fam = {r.item_family: r for r in rates_by_line.get(ln.id, []) if r.item_family}
        rates = {}
        for i, it in items_rows.items():
            row = by_item.get(i) or (by_fam.get(it.family) if it.family else None)
            if row is not None:
                rates[i] = float(row.units_per_hour) * float(row.oee if row.oee is not None else ln.oee)
        lines.append(RateLine(id=ln.id, code=ln.code, setup_family=ln.setup_family, windows=tuple(wins), rates=rates,
                              clearance_minutes=int(ln.clearance_minutes or 0), clean_every_hours=ln.clean_every_hours,
                              clean_minutes=ln.clean_minutes, overtime_cost_per_hour=float(ln.cost_per_hour or 0) * 0.5,
                              tz_offset_minutes=off))
    items = {}
    for i, it in items_rows.items():
        p = plan[i]
        items[i] = RateItem(id=i, part_number=it.part_number, key=p.campaign_key or it.setup_family or it.part_number,
                            case_qty=float(cases[i]) if i in cases else None,
                            campaign_min_hours=float(p.campaign_min_hours or 0), campaign_max_hours=p.campaign_max_hours,
                            target_cover_days=int(p.target_cover_days or 0), initial_stock=0.0,
                            post_days=int(p.post_days or 0))
    run = pass1_run(s, params.mrp_run_id)
    demands = []
    comp_avail: dict[str, list[tuple[str, date]]] = {}
    if run is not None and items:
        for po in s.execute(select(MfgMrpPlannedOrderRow).where(MfgMrpPlannedOrderRow.run_id == run.id,
                                                                MfgMrpPlannedOrderRow.item_id.in_(list(items)))
                            .order_by(MfgMrpPlannedOrderRow.need_date, MfgMrpPlannedOrderRow.planned_no)).scalars():
            it = items[po.item_id]
            src = _source(po.peg_summary)
            prio = {"order": 5, "forecast": int(settings.forecast_priority), "ss": 9}.get(src, 6)
            demands.append(RateDemand(po.item_id, po.need_date - timedelta(days=it.post_days), float(po.qty), prio,
                                      src))
        short = {r.item_id for r in s.execute(select(MfgMrpItemResultRow).where(
            MfgMrpItemResultRow.run_id == run.id, MfgMrpItemResultRow.short_qty > 0)).scalars()}
        if short:
            comps = s.execute(select(MfgBomRow.item_id, MfgBomLineRow.child_item_id).join(
                MfgBomLineRow, MfgBomLineRow.bom_id == MfgBomRow.id).where(MfgBomRow.item_id.in_(list(items)),
                                                                         MfgBomLineRow.child_item_id.in_(short)))
            lead = {r.id: r.lead_time_days or 0 for r in s.execute(select(MfgItemRow).where(
                MfgItemRow.id.in_(short))).scalars()}
            for parent, child in comps:
                comp_avail.setdefault(parent, []).append((child, as_of + timedelta(days=int(lead.get(child, 0)))))
    firm: list[RateBlock] = []
    if params.keep_firm:
        pub = s.execute(select(MfgRateRunRow).where(MfgRateRunRow.published.is_(True))
                        .order_by(MfgRateRunRow.published_at.desc())).scalars().first()
        if pub is not None:
            ids = [ln.id for ln in lines]
            for b in s.execute(select(MfgRateBlockRow).where(
                    MfgRateBlockRow.run_id == pub.id, MfgRateBlockRow.line_id.in_(ids),
                    MfgRateBlockRow.prod_date <= today + timedelta(days=settings.rate_firm_days),
                    MfgRateBlockRow.end > t0).order_by(MfgRateBlockRow.start)).scalars():
                if b.item_id is not None and b.item_id not in items:
                    continue
                firm.append(RateBlock(b.line_id, b.kind, b.item_id, b.campaign_no, b.start, b.end, b.qty, b.cases,
                                      b.prod_date, True, b.wo_id))
    rules = tuple(ChangeoverRule(r.line_setup_family, r.from_key, r.to_key, r.minutes, r.cost, r.kind)
                  for r in s.execute(select(MfgChangeoverRow)).scalars())
    budget = params.time_budget_s or settings.rate_time_budget_s
    problem = RateProblem(as_of=t0, horizon_end=t1, lines=tuple(lines), items=items, demands=tuple(demands),
                          changeovers=rules, firm_blocks=tuple(firm), component_avail=comp_avail,
                          time_budget_s=float(budget), workers=int(os.environ.get("RATE_WORKERS", "4") or 4),
                          firm_netted=True)
    return problem, run
