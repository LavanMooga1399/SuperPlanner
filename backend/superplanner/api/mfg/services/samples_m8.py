"""Applies `mfg.samples.meddev_m8` (M8-DESIGN 14.1) for sample `meddev_m8` (= meddev + the M8 layer).

`apply(s, anchor, actor)` runs in the sample load transaction after the meddev history: groups, flow lines with
rates and shift assignments, EtO chambers and the aeration room, changeover matrix, item planning, packaging,
demand history (`import` rows), a forecast run with an active version and 3 overrides, a safety-stock run with
pending proposals, kanban loops (one empty card). `after_load(ctx, actor)` runs after the commit: MRP pass 1
(`rate_supply false`), a 30-day rate run (published), the sterilisation plan with one load moved to awaiting
release, MRP pass 2.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....mfg.samples import meddev_m8 as D
from ...context import AppContext
from ...db.models import new_id, utcnow
from ..db_models import MfgGroupRow, MfgItemRow, MfgLineRow, MfgShiftAssignmentRow, MfgShiftTemplateRow
from ..db_models_m2 import MfgLocationRow
from ..db_models_m8 import (MfgChangeoverRow, MfgDemandHistoryRow, MfgItemPackagingRow, MfgItemPlanningRow,
                            MfgKanbanCardRow, MfgKanbanLoopRow, MfgLineRateRow)
from .m8common import PLANNING_DEFAULTS, next_number

MARKER = "FLA-01"


def apply(s: Session, anchor: date, actor: str) -> dict[str, Any]:
    if s.execute(select(MfgLineRow.id).where(MfgLineRow.code == MARKER)).first() is not None:
        return {"skipped": True}
    now = utcnow()
    items = {r.part_number: r for r in s.execute(select(MfgItemRow).where(MfgItemRow.part_number.like("MDV-%")))
             .scalars()}
    tpl = {t.code: t for t in s.execute(select(MfgShiftTemplateRow)).scalars()}
    groups = {}
    for code, name, kind, fam in D.GROUPS:
        g = MfgGroupRow(id=new_id("grp_"), code=code, name=name, description="M8 sample", kind=kind, active=True,
                        row_version=1, created_at=now, updated_at=now)
        s.add(g)
        groups[code] = (g, fam)
    s.flush()
    for code, base in (("FLOW", "3X8-5"), ("FLOWPK", "2X8-5"), ("EOS", "24X7"), ("AER", "24X7")):
        if base in tpl:
            s.add(MfgShiftAssignmentRow(id=new_id("sha_"), shift_template_id=tpl[base].id, target_type="group",
                                        group_id=groups[code][0].id, line_id=None, kind="base", shift_names=[],
                                        effective_from=anchor - timedelta(days=60), effective_to=None,
                                        cost_per_hour=None, max_hours_per_week=None, note="M8 sample",
                                        row_version=1, created_at=now, updated_at=now))
    lines = {}
    for code, name, grp, planning, oee, clr, every, cmin, pallets, cycle in D.LINES:
        g, fam = groups[grp]
        ln = MfgLineRow(id=new_id("lin_"), group_id=g.id, code=code, name=name, speed_factor=1.0, parallel_capacity=1,
                        setup_family=fam, eligible_families=[], cost_per_hour=90.0, location_id=None,
                        batch_merge=False, batch_wait_minutes=0, active=True, planning=planning, oee=oee,
                        clearance_minutes=clr, clean_every_hours=every, clean_minutes=cmin, chamber_pallets=pallets,
                        cycle_hours=cycle, row_version=1, created_at=now, updated_at=now)
        s.add(ln)
        lines[code] = ln
    s.flush()
    for code, rates in D.RATES.items():
        for fam, uph in rates:
            s.add(MfgLineRateRow(id=new_id("lrt_"), line_id=lines[code].id, item_id=None, item_family=fam,
                                 units_per_hour=uph, oee=None, row_version=1, created_at=now, updated_at=now))
    for r in D.MATRIX:
        s.add(MfgChangeoverRow(id=new_id("chg_"), row_version=1, created_at=now, updated_at=now, **r))
    for pn in D.FORECAST_ITEMS:
        it = items.get(pn)
        if it is None:
            continue
        vals = dict(PLANNING_DEFAULTS)
        vals.update(forecast=True, order_pack_level="case", target_cover_days=10)
        if pn in D.RATE_ITEMS:
            vals.update(replenishment="rate", campaign_key=D.RATE_ITEMS[pn], campaign_min_hours=8.0,
                        campaign_max_hours=96.0)
        if pn in D.STERILE:
            vals.update(ster_cycle_code=D.STER["cycle"], aeration_hours=D.STER["aeration_hours"],
                        release_mode=D.STER["release_mode"], release_days=D.STER["release_days"])
        if pn in D.LIKE:
            vals.update(like_item_id=items[D.LIKE[pn][0]].id, like_factor=D.LIKE[pn][1])
        s.add(MfgItemPlanningRow(id=new_id("ipn_"), item_id=it.id, abc=None, xyz=None, row_version=1, created_at=now,
                                 updated_at=now, **vals))
        for k, lv in enumerate(D.packaging(pn)):
            s.add(MfgItemPackagingRow(id=new_id("pkg_"), item_id=it.id, seq=k + 1, gtin=None, weight_kg=None,
                                      row_version=1, created_at=now, updated_at=now, **lv))
    rows = [{"id": new_id("dhi_"), "owner_id": items[pn].owner_id, "item_id": items[pn].id, "period_start": per,
             "bucket": "m", "qty": float(q), "cleaned_qty": None, "manual_qty": None, "source": "import",
             "updated_at": now} for pn, per, q in D.history(anchor) if pn in items]
    if rows:
        s.execute(MfgDemandHistoryRow.__table__.insert(), rows)
    loc = MfgLocationRow(id=new_id("loc_"), code="LS-FLA", name="Line side, flow assembly", kind="line_side",
                         receipt_default=False, active=True, external_ref=None, note="M8 sample", row_version=1,
                         created_at=now, updated_at=now)
    s.add(loc)
    s.flush()
    for k in D.KANBAN:
        it = items.get(k["item"])
        if it is None:
            continue
        lp = MfgKanbanLoopRow(id=new_id("kbl_"), number=next_number(s, "KB", MfgKanbanLoopRow), item_id=it.id,
                              location_id=loc.id, source="buy", supplier_id=None, line_id=None, cards=k["cards"],
                              container_qty=float(k["container_qty"]), lead_time_days=k["lead"], trigger="scan",
                              status="active", consumed=0.0, row_version=1, created_at=now, updated_at=now)
        s.add(lp)
        s.flush()
        for n in range(1, k["cards"] + 1):
            s.add(MfgKanbanCardRow(id=new_id("kbc_"), loop_id=lp.id, card_no=n,
                                   state="empty" if n <= k["empty"] else "full", doc_type=None, doc_id=None,
                                   changed_at=now))
    s.flush()
    # forecast run -> version with overrides -> active; safety-stock proposals
    from ....mfg.forecast.history import add_periods
    from . import forecast, invopt

    s.info.pop("sp_planning_settings", None)
    run = forecast.run_now(s, actor, {"as_of": anchor.isoformat(), "label": "Sample"})
    from ..db_models_m8 import MfgForecastOverrideRow, MfgForecastVersionRow

    v = s.execute(select(MfgForecastVersionRow).where(MfgForecastVersionRow.run_id == run.id)).scalars().one()
    for seq, o in enumerate(D.OVERRIDES, start=1):
        a, b = o["periods"]
        s.add(MfgForecastOverrideRow(id=new_id("fco_"), version_id=v.id,
                                     item_id=items[o["item"]].id if "item" in o else None,
                                     item_family=o.get("item_family"), period_from=add_periods(v.start, a, "m"),
                                     period_to=add_periods(v.start, b, "m"), mode=o["mode"], value=o["value"],
                                     reason=o["reason"], seq=seq, created_by=actor, created_at=now, removed_at=None))
    s.flush()
    forecast._recompute(s, v, None)
    v.status, v.activated_by, v.activated_at, v.name = "active", actor, now, "Sample consensus"
    ss = invopt._new_run(s, actor, {}, "running")
    invopt.run_sync(s, ss)
    return {"lines": len(lines), "history_rows": len(rows), "forecast_run": run.number, "ss_run": ss.number}


def after_load(ctx: AppContext, actor: str) -> dict[str, Any]:
    """MRP pass 1 -> rate run (published) -> sterilisation plan (one load awaiting release) -> MRP pass 2."""
    from ....mfg.mrp.model import MrpParams
    from ....mfg.rate.model import RateParams
    from ..db_models_m8 import MfgRateRunRow, MfgSterLoadRow
    from . import mrp, rate, ster

    out: dict[str, Any] = {}
    try:
        out["mrp_pass1"] = mrp.create_run(ctx, MrpParams(label="nightly-1", rate_supply=False))["id"]
        with ctx.write_guard(), ctx.db.write() as s:
            rid = rate._new_run(s, actor, RateParams(label="Sample", horizon_days=30, time_budget_s=20)).id
        res = rate.compute(ctx, rid)
        out["rate_run"] = res
        if res.get("status") == "completed":
            with ctx.write_guard(), ctx.db.write() as s:
                rate.publish_in(s, s.get(MfgRateRunRow, rid), actor)
        with ctx.write_guard(), ctx.db.write() as s:
            plan = ster.plan_in(s, actor, None)
            out["ster_loads"] = plan["loads"]
            if plan["load_ids"]:
                ld = s.get(MfgSterLoadRow, plan["load_ids"][0])
                t0 = utcnow() - timedelta(days=3)
                ld.status, ld.actual_start, ld.actual_end = "awaiting_release", t0, t0 + timedelta(hours=14)
                ld.actual_aeration_end = t0 + timedelta(hours=62)
                ld.flags = list(ld.flags or []) + ["SAMPLE"]
        out["mrp_pass2"] = mrp.create_run(ctx, MrpParams(label="nightly-2"))["id"]
    except Exception as exc:                       # the sample stays loaded; the planner can run the chain
        out["error"] = f"{exc.__class__.__name__}: {exc}"[:300]
    return out
