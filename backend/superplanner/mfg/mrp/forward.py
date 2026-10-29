"""Projected dates, limiting path and result assembly (M2-DESIGN 8.10, 8.11).

The forward pass itself (projected dates, satisfied dates, late days) runs in `engine.Pass.forward` (bottom-up by
low-level code). Here: demand projections with the **limiting path** (from the demand requirement follow the peg
with the latest projected supply; at a make supply whose component readiness decided its start follow the latest
component requirement, else stop with `lead_time` / `start_in_past`; at a buy or existing supply stop with
`supply_date`), demand attribution of supplies (`peg_summary`), and conversion to the contract dataclasses.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..limits import MRP_LIMITING_PATH_MAX, MRP_MAX_EXCEPTIONS_STORED
from .exceptions import CODES, SEVERITY_ORDER, build_exceptions
from .model import (EPS, DemandProjection, ItemPlan, ItemStats, LimitStep, MrpResult, MrpSummary, Peg, PegSummary,
                    PlannedOrder, Requirement, SerialRange, Supply)
from .views import item_timeline

SHARE_TOP = 10


def _q(x: float) -> float:
    return round(x, 6) + 0.0


def _seg(s: SerialRange | None) -> SerialRange | None:
    return SerialRange(s.serial_from, s.serial_to) if s is not None else None


class _Proj:
    __slots__ = ("projected_date", "late_days", "status", "limiting")

    def __init__(self, projected_date: date | None, late_days: int, status: str, limiting: list[LimitStep]):
        self.projected_date = projected_date
        self.late_days = late_days
        self.status = status
        self.limiting = limiting


def _is_make(s: Any) -> bool:
    return s.kind == "wo" or (s.kind == "planned" and s.po.kind == "make")


def limiting_path(c: Any, r: Any) -> list[LimitStep]:
    items = c.ds.items
    as_of = c.as_of
    steps: list[LimitStep] = []
    cur = r
    while len(steps) < MRP_LIMITING_PATH_MAX and cur is not None and cur.pegs:
        pg = max(cur.pegs, key=lambda p: (p.sup.proj or date.min, -p.sup.node))
        s = pg.sup
        pn = items[s.item_id].part_number
        if _is_make(s):
            label = f"{s.ref.label}, {s.mlt} working days"
            base = max(s.start, as_of)
            if s.comp_ready is not None and s.comp_ready > base and s.comps:
                steps.append(LimitStep(s.item_id, pn, label, s.proj, "component"))
                cur = max((x for x in s.comps if x.sat is not None),
                          key=lambda x: (x.sat, x.late, items[x.item_id].part_number, -x.node), default=None)
                continue
            steps.append(LimitStep(s.item_id, pn, label, s.proj, "start_in_past" if s.start < as_of else "lead_time"))
            break
        if s.kind == "planned":
            reason = "start_in_past" if s.start < as_of else "supply_date"
        else:
            reason = "supply_date"
        steps.append(LimitStep(s.item_id, pn, s.ref.label, s.proj, reason))
        break
    return steps


def compute_shares(c: Any, p: Any) -> None:
    """Demand attribution (top-down): requirement share = its own demand (1.0) or its parent supply's share; supply
    share = peg-weighted shares of its requirements (top `SHARE_TOP` kept)."""
    for iid in c.order:
        st = p.states.get(iid)
        if st is None:
            continue
        for r in st.reqs:
            k = r.kind
            if k == "demand":
                r.share = [((r.source.id, r.source.label), 1.0)]
            elif k in ("extra_demand", "safety_stock"):
                r.share = [((None, r.source.label), 1.0)]
            elif r.parent is not None and r.parent.share:
                r.share = r.parent.share
            else:
                r.share = [((None, r.source.label), 1.0)]
        for s in st.sups:
            if not s.pegs:
                s.share = None
                continue
            acc: dict[tuple[str | None, str], float] = {}
            for pg in s.pegs:
                for key, f in (pg.req.share or ()):
                    acc[key] = acc.get(key, 0.0) + pg.qty * f
            tot = s.pegged if s.pegged > EPS else 1.0
            top = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0][1], kv[0][0] or ""))[:SHARE_TOP]
            s.share = [(key, v / tot) for key, v in top]


def build_result(c: Any, p: Any, iterations: int, alt_records: list[dict[str, Any]]) -> MrpResult:
    items = c.ds.items
    as_of = c.as_of
    compute_shares(c, p)

    # demand projections
    demand: list[DemandProjection] = []
    info: dict[int, _Proj] = {}
    for r, d, idx in p.demand_reqs:
        late = r.late
        if r.need < as_of:
            status = "past_due"
        elif late > 0:
            status = "late"
        else:
            status = "on_time"
        lim = limiting_path(c, r) if late > 0 else []
        info[id(r)] = _Proj(r.sat, late, status, lim)
        extra = idx is not None
        demand.append(DemandProjection(
            demand_line_id=None if extra else d.line_id, extra=extra, extra_index=idx,
            order_id=None if extra else d.order_id, order_number="" if extra else d.number,
            demand_type=None if extra else d.demand_type, customer="" if extra else d.customer,
            program=None if extra else d.program, line_no=0 if extra else d.line_no, item_id=r.item_id,
            part_number=items[r.item_id].part_number, qty=_q(r.qty), due_date=r.need,
            priority=d.priority if extra else d.effective_priority, segment=_seg(r.segment),
            projected_date=r.sat, late_days=late, status=status, limiting=lim, node=r.node, label=r.source.label))

    exceptions = build_exceptions(c, p, alt_records, info)
    by_sev = {s: 0 for s in SEVERITY_ORDER}
    by_code = {code: 0 for code, _s in CODES}
    per_item: dict[str, int] = {}
    for e in exceptions:
        by_sev[e.severity] += 1
        by_code[e.code] += 1
        if e.item_id:
            per_item[e.item_id] = per_item.get(e.item_id, 0) + 1
    truncated = len(exceptions) > MRP_MAX_EXCEPTIONS_STORED
    if truncated:
        exceptions = exceptions[:MRP_MAX_EXCEPTIONS_STORED]

    # planned orders
    planned: list[PlannedOrder] = []
    for po in p.planned:
        s = po.sup
        proj = s.proj or po.need
        if po.start < as_of:
            rel = "start_in_past"
        elif (po.start - as_of).days <= c.settings.release_window_days:
            rel = "release_now"
        else:
            rel = "later"
        summ = [PegSummary(key[0], key[1], _q(f * s.pegged)) for key, f in (s.share or [])[:5]]
        planned.append(PlannedOrder(
            planned_no=po.no, kind=po.kind, item_id=po.item_id, part_number=items[po.item_id].part_number,
            llc=c.llc.get(po.item_id, 0), qty=_q(po.qty), need_date=po.need, start_date=po.start, dock_date=po.dock,
            projected_start=max(po.start, as_of), projected_due=proj, late_days=max(0, (proj - po.need).days),
            release_status=rel, supplier_id=po.supplier_id, segment=_seg(po.segment), bom_id=po.bom_id,
            routing_id=po.routing_id, lot_note=po.lot_note, peg_summary=summ, order_key=po.order_key,
            supply_node=s.node, directives={k: _q(v) for k, v in sorted(po.directives.items())}))

    # items
    plans: list[ItemPlan] = []
    items_short = 0
    for iid in c.order:
        st = p.states.get(iid)
        if st is None:
            continue
        it = st.item
        reqs = []
        short = late_qty = 0.0
        first_short: date | None = None
        for r in st.reqs:                                   # creation order == node order
            pegs = []
            q_late = 0.0
            n = r.need if r.need > as_of else as_of
            for pg in r.pegs:
                pegs.append(Peg(iid, pg.sup.node, iid, r.node, round(pg.qty, 6) + 0.0, pg.late))
                pj = pg.sup.proj
                if pj is not None and pj > n:
                    q_late += pg.qty
            reqs.append(Requirement(r.node, r.kind, r.need, round(r.qty, 6) + 0.0, r.rank, r.rank_label, r.source,
                                    _seg(r.segment), pegs, r.sat, r.late))
            if q_late > EPS and r.kind != "safety_stock":
                short += q_late
                late_qty += r.qty
                if first_short is None or r.need < first_short:
                    first_short = r.need
        sups = [Supply(s.node, s.kind, round(s.qty, 6) + 0.0, s.avail, s.proj, s.exp, s.ref,
                       round(s.pegged, 6) + 0.0, [(x.item_id, x.node) for x in s.comps], s.planned_no, s.start,
                       s.due)
                for s in st.sups]
        if short > EPS:
            items_short += 1
        pl = [s for s in st.sups if s.kind == "planned"]
        plan = ItemPlan(item_id=iid, part_number=it.part_number, llc=st.llc, uom=it.uom, make_buy=it.make_buy,
                        lead_time=c.lead_info(it), lot=c.lot(it).info(), requirements=reqs, supplies=sups,
                        timeline=[], stats=None,  # type: ignore[arg-type]
                        supplier_id=c.source(it).supplier_id if it.make_buy == "buy" else None)
        plan.timeline = item_timeline(plan, as_of)
        min_bal = min((e.balance_planned for e in plan.timeline), default=0.0)
        plan.stats = ItemStats(
            on_hand=_q(sum(s.qty for s in st.sups if s.kind == "stock")), gross_qty=_q(sum(r.qty for r in st.reqs)),
            existing_supply_qty=_q(sum(s.qty for s in st.sups if s.kind not in ("stock", "planned"))),
            planned_qty=_q(sum(s.qty for s in pl)), planned_count=len(pl), first_short_date=first_short,
            short_qty=_q(short), late_qty=_q(late_qty), min_balance=_q(min_bal),
            exception_count=per_item.get(iid, 0))
        plans.append(plan)

    summary = MrpSummary(
        demand_lines=len(demand), demand_on_time=sum(1 for d in demand if d.status == "on_time"),
        demand_late=sum(1 for d in demand if d.status == "late"),
        demand_past_due=sum(1 for d in demand if d.status == "past_due"),
        max_late_days=max((d.late_days for d in demand), default=0), items=len(plans), items_short=items_short,
        planned_make=sum(1 for x in planned if x.kind == "make"),
        planned_buy=sum(1 for x in planned if x.kind == "buy"),
        release_now=sum(1 for x in planned if x.release_status == "release_now"),
        start_in_past=sum(1 for x in planned if x.release_status == "start_in_past"),
        alternates_used=by_code["MRP_ALTERNATE_USED"], iterations=iterations, exceptions_truncated=truncated,
        exceptions={"by_severity": by_sev, "by_code": by_code}, requirements=p.n_reqs,
        demand_outside_horizon=p.outside)
    return MrpResult(params=c.params, as_of=as_of, horizon_end=c.horizon_end, kind=c.kind, summary=summary,
                     items=plans, planned_orders=planned, exceptions=exceptions, demand=demand,
                     iterations=iterations)


__all__ = ["build_result", "compute_shares", "limiting_path"]
