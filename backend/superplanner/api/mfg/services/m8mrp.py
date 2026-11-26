"""M8 inputs of an MRP run (M8-DESIGN 6): forecast requirements after consumption, item planning (replenishment,
order packs, kanban loops), rate supplies of the published (or given) rate run.

Rate supply availability: block `prod_date` + `post_days` (item planning), or - for sterilised items - the
release date of the planned sterilisation load the block is in.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....mfg.mrp.model import MrpSnapshot, PlanningSnap, RateSupplySnap
from ...errors import ApiError
from ..db_models_m8 import (MfgItemPackagingRow, MfgItemPlanningRow, MfgKanbanLoopRow, MfgRateBlockRow,
                            MfgRateRunRow, MfgSterLoadMemberRow, MfgSterLoadRow)
from .m8common import settings_of


def planning_snaps(s: Session) -> dict[str, PlanningSnap]:
    packs: dict[str, dict[str, float]] = {}
    for item_id, level, qty in s.execute(select(MfgItemPackagingRow.item_id, MfgItemPackagingRow.level,
                                                MfgItemPackagingRow.qty_base)):
        packs.setdefault(item_id, {})[level] = float(qty)
    loops = {r.item_id: r for r in s.execute(select(MfgKanbanLoopRow).where(MfgKanbanLoopRow.status == "active")
                                             .order_by(MfgKanbanLoopRow.number)).scalars()}
    out: dict[str, PlanningSnap] = {}
    for r in s.execute(select(MfgItemPlanningRow)).scalars():
        pk = packs.get(r.item_id, {})
        lp = loops.get(r.item_id)
        out[r.item_id] = PlanningSnap(
            r.item_id, r.replenishment, pk.get(r.order_pack_level) if r.order_pack_level else None, pk.get("case"),
            pk.get("pallet"), lp.cards if lp else None, lp.container_qty if lp else None,
            lp.lead_time_days if lp else None)
    for item_id, pk in packs.items():
        out.setdefault(item_id, PlanningSnap(item_id, "mrp", None, pk.get("case"), pk.get("pallet")))
    return out


def published_rate_run(s: Session) -> MfgRateRunRow | None:
    return s.execute(select(MfgRateRunRow).where(MfgRateRunRow.published.is_(True))
                     .order_by(MfgRateRunRow.published_at.desc())).scalars().first()


def rate_supplies(s: Session, run_id: str | None) -> list[RateSupplySnap]:
    run = s.get(MfgRateRunRow, run_id) if run_id else published_rate_run(s)
    if run is None:
        if run_id:
            raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Rate run {run_id!r} was not found.",
                           {"loc": ["body", "rate_run_id"], "id": run_id})
        return []
    post = {i: p for i, p in s.execute(select(MfgItemPlanningRow.item_id, MfgItemPlanningRow.post_days))}
    release = {}
    for bid, due in s.execute(select(MfgSterLoadMemberRow.rate_block_id, MfgSterLoadRow.release_due)
                              .join(MfgSterLoadRow, MfgSterLoadRow.id == MfgSterLoadMemberRow.load_id)
                              .where(MfgSterLoadMemberRow.rate_block_id.is_not(None),
                                     MfgSterLoadRow.status.not_in(("cancelled", "failed")))):
        release[bid] = due
    out = []
    for b in s.execute(select(MfgRateBlockRow).where(MfgRateBlockRow.run_id == run.id,
                                                     MfgRateBlockRow.kind == "production",
                                                     MfgRateBlockRow.wo_id.is_(None))
                       .order_by(MfgRateBlockRow.start)).scalars():
        avail = release.get(b.id) or (b.prod_date + timedelta(days=int(post.get(b.item_id) or 0)))
        out.append(RateSupplySnap(b.item_id, avail, float(b.qty), b.id, f"{run.number} block", b.prod_date))
    return out


def release_balances(s: Session, snap: MrpSnapshot) -> tuple[list[Any], list[RateSupplySnap]]:
    """Review 1: stock of lots whose only open hold is `sterility` is no free stock; it is supply at the planned
    release date (pending lots: as_of + 1 cycle day + aeration + release days of the item)."""
    import math

    from ..db_models_m7 import MfgLotHoldRow

    holds: dict[str, list[Any]] = {}
    for h in s.execute(select(MfgLotHoldRow).where(MfgLotHoldRow.released_at.is_(None),
                                                   MfgLotHoldRow.lot_id.is_not(None))).scalars():
        holds.setdefault(h.lot_id, []).append(h)
    ster = {lot: hs[0] for lot, hs in holds.items() if all(h.source == "sterility" for h in hs)}
    if not ster:
        return snap.balances, []
    plan = {r.item_id: r for r in s.execute(select(MfgItemPlanningRow)).scalars()}
    keep, out = [], []
    for b in snap.balances:
        h = ster.get(b.lot_id or "")
        if h is None or b.kind not in ("stores", "line_side"):
            keep.append(b)
            continue
        pr = plan.get(b.item_id)
        est = snap.as_of + timedelta(days=1 + math.ceil(((pr.aeration_hours or 0) / 24.0) if pr else 0)
                                     + math.ceil(pr.release_days if pr else 0))
        avail = h.planned_release or est
        out.append(RateSupplySnap(b.item_id, avail, float(b.qty_on_hand), b.id, "Awaiting sterility release",
                                  None))
    return keep, out


def add_inputs(s: Session, snap: MrpSnapshot, params: Any) -> MrpSnapshot:
    from .forecast import forecast_requirements

    st = settings_of(s)
    snaps, _over, _vid = forecast_requirements(s, params.forecast_version_id, snap.as_of)
    rs = rate_supplies(s, params.rate_run_id) if params.rate_supply else []
    from .ster import release_dates

    rel = release_dates(s)                     # M8 8: sterilised WOs are available at their planned release
    wos = [replace(w, due_date=max(w.due_date, rel[w.id])) if w.id in rel else w for w in snap.work_orders] \
        if rel else snap.work_orders
    bals, rel_sup = release_balances(s, snap)
    return replace(snap, work_orders=wos, balances=bals, release_supplies=rel_sup, forecasts=snaps, planning=planning_snaps(s), rate_supplies=rs,
                   forecast_priority=st.forecast_priority, zones=(st.daily_days, st.weekly_weeks))
