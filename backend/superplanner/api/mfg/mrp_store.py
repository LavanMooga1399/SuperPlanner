"""MRP results <-> rows (M2-DESIGN 9.3 #17-21, 12.4). Runs are immutable snapshots: master ids are plain strings
(no FKs) with denormalised part numbers. `mfg_mrp_item_results.detail` = `{"v": 1, "plan": to_jsonable(ItemPlan)}`
(internal format; the API shapes of 12.4 are the contract). Server-built links (14.3) are computed when the run is
stored (document ids of schedules come from the snapshot) and kept in the stored subject JSON.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...mfg.limits import MRP_MAX_EXCEPTIONS_STORED
from ...mfg.mrp.model import MrpResult, item_plan_from_jsonable, to_jsonable
from ..db import new_id
from .db_models_m2 import (MfgMrpDemandResultRow, MfgMrpExceptionRow, MfgMrpItemResultRow, MfgMrpPlannedOrderRow,
                           MfgMrpRunRow)

SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}
DETAIL_VERSION = 1


def _jsonable(x: Any) -> Any:
    return to_jsonable(x)


class Linker:
    """Builds the 14.3 links of one run."""

    def __init__(self, run_id: str, snapshot: Any, planned_ids: dict[str, str]):
        self.run_id = run_id
        self.sched_doc = {sc.schedule_id: (sc.doc_type, sc.doc_id) for sc in snapshot.schedules}
        self.order_of_line = {d.line_id: d.order_id for d in snapshot.demand}
        self.planned_ids = planned_ids          # str(planned_no) -> planned order row id

    def link(self, type_: str, id_: str | None) -> str | None:
        r = self.run_id
        if id_ is None and type_ != "plant":
            return None
        if type_ == "demand_line":
            oid = self.order_of_line.get(id_ or "")
            return f"/mfg/demand/{oid}?line={id_}" if oid else None
        if type_ == "item":
            return f"/mfg/mrp/runs/{r}/items/{id_}"
        if type_ == "planned_order":
            pid = self.planned_ids.get(id_ or "")
            return f"/mfg/mrp/runs/{r}/planned?order={pid}" if pid else None
        if type_ in ("po_schedule", "pr_schedule"):
            x = self.sched_doc.get(id_ or "")
            if x is None:
                return None
            return f"/mfg/purchasing/{'orders' if x[0] == 'po' else 'requests'}/{x[1]}?schedule={id_}"
        if type_ == "purchase_request":
            return f"/mfg/purchasing/requests/{id_}"
        if type_ == "work_order":
            return f"/mfg/work-orders/{id_}"
        if type_ == "lot":
            return f"/mfg/inventory/lots?lot={id_}"
        if type_ == "plant":
            return "/mfg/plant/settings"
        return None

    def ref(self, x: Any) -> dict[str, Any]:
        return {"type": x.type, "id": x.id, "label": x.label, "link": self.link(x.type, x.id)}


def _seg(x: Any) -> Any:
    return {"serial_from": x.serial_from, "serial_to": x.serial_to} if x is not None else None


def store(s: Session, run: MfgMrpRunRow, result: MrpResult, snapshot: Any) -> dict[str, Any]:
    """Write the result rows of a run (one `add_all` + flush per table); returns `{exceptions_truncated}`."""
    owner = run.owner_id
    po_rows = []
    planned_ids: dict[str, str] = {}
    for p in result.planned_orders:
        rid = new_id("mpo_")
        planned_ids[str(p.planned_no)] = rid
        po_rows.append(MfgMrpPlannedOrderRow(
            id=rid, owner_id=owner, run_id=run.id, planned_no=p.planned_no, kind=p.kind, item_id=p.item_id,
            part_number=p.part_number, supplier_id=p.supplier_id, qty=p.qty, need_date=p.need_date,
            start_date=p.start_date, dock_date=p.dock_date, projected_start=p.projected_start,
            projected_due=p.projected_due, late_days=p.late_days, release_status=p.release_status,
            segment=_seg(p.segment), bom_id=p.bom_id, routing_id=p.routing_id, llc=p.llc, lot_note=p.lot_note[:200],
            peg_summary={"pegs": _jsonable(p.peg_summary), "directives": dict(p.directives or {})},
            order_key=p.order_key[:200], status="open", converted_type=None,
            converted_id=None, converted_number=None, converted_at=None, converted_by=None))
    s.add_all(po_rows)
    s.flush()
    lk = Linker(run.id, snapshot, planned_ids)
    exc = list(result.exceptions)
    truncated = len(exc) > MRP_MAX_EXCEPTIONS_STORED
    if truncated:
        keep = sorted(range(len(exc)), key=lambda i: (SEV_ORDER.get(exc[i].severity, 3), i))[:MRP_MAX_EXCEPTIONS_STORED]
        exc = [exc[i] for i in sorted(keep)]
    ex_rows = []
    for n, e in enumerate(exc, 1):
        ex_rows.append(MfgMrpExceptionRow(
            id=new_id("mex_"), owner_id=owner, run_id=run.id, ex_no=n, code=e.code, severity=e.severity,
            item_id=e.item_id, part_number=e.part_number, demand_line_id=e.demand_line_id, subject=lk.ref(e.subject),
            ex_date=e.date, qty=e.qty, days=e.days, message=e.message[:1000], action=e.action[:500],
            suggested=_jsonable(e.suggested) if e.suggested else None, related=[lk.ref(x) for x in e.related]))
    s.add_all(ex_rows)
    s.flush()
    ex_count: dict[str, int] = {}
    for e in result.exceptions:
        if e.item_id:
            ex_count[e.item_id] = ex_count.get(e.item_id, 0) + 1
    items = {i.id: i for i in snapshot.dataset.items.values()}
    it_rows = []
    for p in result.items:
        it = items.get(p.item_id)
        st = p.stats
        it_rows.append(MfgMrpItemResultRow(
            id=new_id("mir_"), owner_id=owner, run_id=run.id, item_id=p.item_id, part_number=p.part_number,
            description=(it.description if it else "")[:500], make_buy=p.make_buy, uom=p.uom, llc=p.llc,
            on_hand=st.on_hand, gross_qty=st.gross_qty, existing_supply_qty=st.existing_supply_qty,
            planned_qty=st.planned_qty, planned_count=st.planned_count, first_short_date=st.first_short_date,
            short_qty=st.short_qty, late_qty=st.late_qty, min_balance=st.min_balance,
            exception_count=ex_count.get(p.item_id, st.exception_count),
            detail={"v": DETAIL_VERSION, "plan": _jsonable(p), "family": it.family if it else None,
                    "revision": it.revision if it else "", "active": it.active if it else True}))
    s.add_all(it_rows)
    s.flush()
    dm_rows = []
    for d in result.demand:
        dm_rows.append(MfgMrpDemandResultRow(
            id=new_id("mdr_"), owner_id=owner, run_id=run.id, demand_line_id=d.demand_line_id, order_id=d.order_id,
            order_number=d.order_number[:32], line_no=d.line_no, extra=d.extra, item_id=d.item_id,
            part_number=d.part_number, qty=d.qty, due_date=d.due_date, projected_date=d.projected_date,
            late_days=d.late_days, priority=d.priority, status=d.status, program=d.program, segment=_seg(d.segment),
            limiting={"steps": _jsonable(d.limiting), "label": d.label, "demand_type": d.demand_type,
                      "customer": d.customer, "node": d.node, "extra_index": d.extra_index}))
    s.add_all(dm_rows)
    s.flush()
    return {"exceptions_truncated": truncated}


# ---------------------------------------------------------------- rows -> API views


def item_ref_of(row: MfgMrpItemResultRow) -> dict[str, Any]:
    det = row.detail or {}
    return {"id": row.item_id, "part_number": row.part_number, "revision": det.get("revision", ""),
            "description": row.description, "uom": row.uom, "make_buy": row.make_buy,
            "active": det.get("active", True)}


def item_row(run_id: str, row: MfgMrpItemResultRow) -> dict[str, Any]:
    plan = (row.detail or {}).get("plan") or {}
    lt = plan.get("lead_time") or {}
    return {"item": item_ref_of(row), "llc": row.llc, "make_buy": row.make_buy, "uom": row.uom,
            "on_hand": row.on_hand, "gross_qty": row.gross_qty, "existing_supply_qty": row.existing_supply_qty,
            "planned_qty": row.planned_qty, "planned_count": row.planned_count,
            "first_short_date": row.first_short_date, "short_qty": row.short_qty, "late_qty": row.late_qty,
            "min_balance": row.min_balance, "exception_count": row.exception_count,
            "lead_time": {"source": lt.get("source"), "days": lt.get("days"), "unit": lt.get("unit")},
            "link": f"/mfg/mrp/runs/{run_id}/items/{row.item_id}"}


def plan_of(row: MfgMrpItemResultRow) -> Any:
    return item_plan_from_jsonable((row.detail or {})["plan"])


def planned_row(run_id: str, r: MfgMrpPlannedOrderRow, item: dict[str, Any], supplier: Any) -> dict[str, Any]:
    return {"id": r.id, "planned_no": r.planned_no, "kind": r.kind, "item": item, "supplier": supplier,
            "qty": r.qty, "need_date": r.need_date, "start_date": r.start_date, "dock_date": r.dock_date,
            "projected_start": r.projected_start, "projected_due": r.projected_due, "late_days": r.late_days,
            "release_status": r.release_status, "segment": r.segment, "lot_note": r.lot_note,
            "peg_summary": peg_list(r), "status": r.status,
            "converted": {"type": r.converted_type, "id": r.converted_id, "number": r.converted_number}
            if r.converted_type else None,
            "link": f"/mfg/mrp/runs/{run_id}/planned?order={r.id}"}


def peg_list(r: MfgMrpPlannedOrderRow) -> list[dict[str, Any]]:
    v = r.peg_summary
    return list(v.get("pegs") or []) if isinstance(v, dict) else list(v or [])


def directives_of(r: MfgMrpPlannedOrderRow) -> dict[tuple[str, str], float]:
    v = r.peg_summary
    d = v.get("directives") if isinstance(v, dict) else None
    return {(r.order_key, k): float(q) for k, q in (d or {}).items()}


def exception_row(r: MfgMrpExceptionRow, item: dict[str, Any] | None) -> dict[str, Any]:
    subj = dict(r.subject or {})
    link = subj.pop("link", None)
    return {"id": r.id, "ex_no": r.ex_no, "code": r.code, "severity": r.severity, "item": item, "subject": subj,
            "demand_line_id": r.demand_line_id, "date": r.ex_date, "qty": r.qty, "days": r.days,
            "message": r.message, "action": r.action, "suggested": r.suggested or {}, "related": r.related or [],
            "link": link}


def demand_row(r: MfgMrpDemandResultRow, item: dict[str, Any]) -> dict[str, Any]:
    lim = r.limiting or {}
    steps = []
    for st in lim.get("steps") or []:
        steps.append({"item": {"id": st["item_id"], "part_number": st["part_number"]}, "label": st["label"],
                      "date": st["date"], "reason": st["reason"]})
    order = None
    if r.order_id:
        order = {"id": r.order_id, "number": r.order_number, "demand_type": lim.get("demand_type"),
                 "customer": lim.get("customer", ""), "program": r.program}
    return {"demand_line_id": r.demand_line_id, "extra": r.extra, "order": order, "line_no": r.line_no,
            "item": item, "qty": r.qty, "due_date": r.due_date, "priority": r.priority, "segment": r.segment,
            "projected_date": r.projected_date, "late_days": r.late_days, "status": r.status, "limiting": steps,
            "label": lim.get("label", ""), "node": lim.get("node"),
            "link": f"/mfg/demand/{r.order_id}?line={r.demand_line_id}" if r.order_id else None}


def load_item_plan(s: Session, run_id: str, item_id: str) -> Any:
    row = s.execute(select(MfgMrpItemResultRow).where(MfgMrpItemResultRow.run_id == run_id,
                                                      MfgMrpItemResultRow.item_id == item_id)).scalars().first()
    return plan_of(row) if row is not None else None


def date_or_none(v: Any) -> date | None:
    return date.fromisoformat(v) if isinstance(v, str) else v


__all__ = ["Linker", "demand_row", "exception_row", "item_ref_of", "item_row", "load_item_plan", "plan_of",
           "planned_row", "store"]
