"""MRP run -> `MrpPegView` (M3-DESIGN 6.2, 6.4): planned make orders, component pegs per consuming order, best demand
rank per order, demand lines with their pegged supplies. Works on the JSON form of `ItemPlan` (`mrp.to_jsonable`), so
the pure path (samples, tests: an `MrpResult` in memory) and the API path (stored item-result details) share it."""

from __future__ import annotations

from datetime import date
from typing import Any

from .model import ApsComponent, DemandPeg, MrpPegView, PegSupply, PlannedMake

_KIND = {"balance": "stock", "po_schedule": "po_schedule", "pr_schedule": "pr_schedule", "work_order": "work_order",
         "planned_order": "planned"}


def _d(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _rank(v: Any) -> tuple[Any, ...]:
    return tuple(v) if isinstance(v, (list, tuple)) else (v,)


def build_peg_view(run_id: str, run_no: int, kind: str, plans: list[dict[str, Any]], planned: list[dict[str, Any]],
                   demand: list[dict[str, Any]], ds: Any) -> MrpPegView:
    sup: dict[tuple[str, int], dict[str, Any]] = {}
    for p in plans:
        for s in p.get("supplies", ()):
            sup[(p["item_id"], s["node"])] = s
    pegs: dict[tuple[str, str, str], list[PegSupply]] = {}
    ranks: dict[tuple[str, str], tuple[Any, ...]] = {}
    labels: dict[tuple[str, str], str] = {}
    comps_of_planned: dict[str, dict[str, float]] = {}
    demand_sup: dict[str, list[PegSupply]] = {}

    def to_peg(pg: dict[str, Any]) -> tuple[PegSupply, dict[str, Any]] | None:
        s = sup.get((pg["supply_item_id"], pg["supply_node"]))
        if s is None:
            return None
        ref = s.get("ref") or {}
        k = _KIND.get(ref.get("type"), str(ref.get("type")))
        if s.get("kind") == "planned":
            k = "planned"
        return PegSupply(kind=k, ref_id=ref.get("id"), label=str(ref.get("label") or ""), qty=float(pg["qty"]),
                         available_date=_d(s.get("avail_date")), planned_no=s.get("planned_no")), s

    for p in plans:
        for r in p.get("requirements", ()):
            src = r.get("source") or {}
            rk = _rank(r.get("rank"))
            got = [x for x in (to_peg(pg) for pg in r.get("pegs", ())) if x is not None]
            for ps, s in got:
                ref = s.get("ref") or {}
                okey = None
                if ref.get("type") == "work_order":
                    okey = ("wo", str(ref.get("id")))
                elif s.get("kind") == "planned" or ref.get("type") == "planned_order":
                    okey = ("planned", str(s.get("planned_no") if s.get("planned_no") is not None else ref.get("id")))
                if okey is not None and (okey not in ranks or rk < ranks[okey]):
                    ranks[okey] = rk
                    labels[okey] = str(r.get("rank_label") or "")
            if r.get("kind") == "wo_component" and src.get("type") == "work_order":
                pegs.setdefault(("wo", str(src.get("id")), p["item_id"]), []).extend(x[0] for x in got)
            elif r.get("kind") == "planned_component" and src.get("type") == "planned_order":
                no = str(src.get("id"))
                pegs.setdefault(("planned", no, p["item_id"]), []).extend(x[0] for x in got)
                c = comps_of_planned.setdefault(no, {})
                c[p["item_id"]] = c.get(p["item_id"], 0.0) + float(r.get("qty") or 0.0)
            elif src.get("type") == "demand_line" and src.get("id"):
                demand_sup.setdefault(str(src.get("id")), []).extend(x[0] for x in got)
    # planned make orders with their components (operation_seq from the BOM line)
    out_planned = []
    for po in sorted(planned, key=lambda x: x["planned_no"]):
        if po.get("kind") != "make" or po.get("status", "open") != "open":
            continue
        bom = ds.boms.get(po.get("bom_id")) if po.get("bom_id") else None
        opseq = {ln.child_item_id: ln.operation_seq for ln in (bom.lines if bom else ())}
        no = str(po["planned_no"])
        comps = tuple(ApsComponent(f"{no}:{iid}", iid, q, opseq.get(iid))
                      for iid, q in sorted(comps_of_planned.get(no, {}).items()))
        seg = po.get("segment") or None
        out_planned.append(PlannedMake(planned_no=int(po["planned_no"]), id=str(po["id"]), item_id=po["item_id"],
                                       qty=float(po["qty"]), need_date=_d(po["need_date"]),
                                       start_date=_d(po["start_date"]), routing_id=po.get("routing_id"),
                                       bom_id=po.get("bom_id"),
                                       serial_from=(seg or {}).get("serial_from") if isinstance(seg, dict) else None,
                                       order_key=str(po.get("order_key") or ""), components=comps))
    dem = []
    for d in demand:
        if d.get("extra"):
            continue
        lid = d.get("demand_line_id")
        dem.append(DemandPeg(demand_line_id=lid, order_id=d.get("order_id"), order_number=str(d.get("order_number")),
                             line_no=int(d.get("line_no") or 0), item_id=d["item_id"], qty=float(d["qty"]),
                             due_date=_d(d["due_date"]), priority=int(d.get("priority") or 5),
                             program=d.get("program"), supplies=tuple(demand_sup.get(str(lid), ()))))
    return MrpPegView(run_id=run_id, run_no=run_no, kind=kind, planned=tuple(out_planned),
                      pegs={k: tuple(v) for k, v in pegs.items()}, ranks=ranks, rank_labels=labels,
                      demand=tuple(dem))


def peg_view_of_result(run_id: str, run_no: int, result: Any, ds: Any) -> MrpPegView:
    """The pure path: an in-memory `MrpResult`."""
    from ..mrp.model import to_jsonable

    plans = [to_jsonable(p) for p in result.items]
    planned = [{"planned_no": p.planned_no, "id": f"mpo_{p.planned_no:032x}", "kind": p.kind, "item_id": p.item_id,
                "qty": p.qty, "need_date": p.need_date, "start_date": p.start_date, "routing_id": p.routing_id,
                "bom_id": p.bom_id, "segment": to_jsonable(p.segment), "order_key": p.order_key, "status": "open"}
               for p in result.planned_orders]
    demand = [to_jsonable(d) for d in result.demand]
    return build_peg_view(run_id, run_no, result.kind, plans, planned, demand, ds)


__all__ = ["build_peg_view", "peg_view_of_result"]
