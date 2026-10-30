"""Persistence of APS results (M3-DESIGN 10) and row -> API view builders (11 #188-199)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...mfg.aps.model import ApsResult
from ..db import new_id
from ..schemas import as_utc
from .db_models_m3 import (MfgApsExceptionRow, MfgApsLoadRow, MfgApsOpRow, MfgApsOrderRow, MfgApsOvertimeRow,
                           MfgApsRunRow)


def _j(m: Any) -> Any:
    return m.model_dump(mode="json") if hasattr(m, "model_dump") else m


def store(s: Session, run: MfgApsRunRow, res: ApsResult, parents: dict[str, str]) -> None:
    owner = run.owner_id
    s.add_all([MfgApsOpRow(
        id=new_id("aop_"), owner_id=owner, run_id=run.id, op_no=o.op_no, order_type=o.order.type,
        order_id=o.order.id, order_number=o.order.number[:32], planned_no=o.order.planned_no, item_id=o.order.item_id,
        part_number=_pn(res, o)[:64], seq=o.seq, name=o.name[:100], group_id=o.group_id, line_id=o.line_id,
        split_index=o.split.index, split_count=o.split.count, qty=o.qty, start_at=o.start, end_at=o.end,
        setup_minutes=o.setup_minutes, run_minutes=o.run_minutes, pieces=[_j(p) for p in o.pieces],
        crew=[_j(c) for c in o.crew], tools=[_j(t) for t in o.tools], release=_j(o.release), locked=o.locked,
        frozen=o.frozen, status=o.status, reason=_j(o.reason), due_at=o.due, late_minutes=o.late_minutes,
        family=(o.family or "")[:32], setup_from_family=(o.setup_from_family or None))
        for o in res.operations])
    s.flush()
    s.add_all([MfgApsOrderRow(
        id=new_id("aor_"), owner_id=owner, run_id=run.id, order_type=o.order.type, order_id=o.order.id,
        number=o.order.number[:32], planned_no=o.order.planned_no, item_id=o.order.item_id,
        part_number=o.part_number[:64], qty=o.qty, due_at=o.due, start_at=o.start, end_at=o.end,
        late_minutes=o.late_minutes, weight=o.weight, priority=o.priority, rank_label=o.rank_label[:100],
        demand_refs=[_j(d) for d in o.demand_refs], late_chain=[_j(x) for x in o.late_chain],
        late_text=o.late_text[:1000], unscheduled_ops=o.unscheduled_ops) for o in res.orders])
    s.flush()
    s.add_all([MfgApsOvertimeRow(
        id=new_id("aot_"), owner_id=owner, run_id=run.id, line_id=w.line_id, assignment_id=w.assignment_id,
        start_at=w.start, end_at=w.end, minutes=w.minutes, cost=w.cost, status=w.status,
        tardiness_saved_minutes=w.tardiness_saved_minutes, reason=w.reason[:500],
        orders=[_j(o) for o in w.orders]) for w in res.overtime])
    s.add_all([MfgApsExceptionRow(
        id=new_id("aex_"), owner_id=owner, run_id=run.id, ex_no=n, code=e.code, severity=e.severity,
        subject=_j(e.subject), op_no=e.op_no, order_ref=_j(e.order) if e.order else None, message=e.message[:1000],
        refs=[_j(r) for r in e.refs]) for n, e in enumerate(res.exceptions, 1)])
    s.add_all([MfgApsLoadRow(
        id=new_id("ald_"), owner_id=owner, run_id=run.id, group_id=x.group_id, line_id=x.line_id, day=x.day,
        scheduled_minutes=x.scheduled_minutes, required_minutes=x.required_minutes, base_minutes=x.base_minutes,
        optional_minutes=x.optional_minutes, opened_minutes=x.opened_minutes) for x in res.load])
    s.flush()
    run.summary = res.summary.model_dump(mode="json")
    run.score = list(res.score)
    run.validation = res.validation.model_dump(mode="json")
    run.extras = {"demand": [_j(d) for d in res.demand], "bottlenecks": [_j(b) for b in res.bottlenecks],
                  "parents": parents}


def _pn(res: ApsResult, o: Any) -> str:
    return next((x.part_number for x in res.orders if x.order.id == o.order.id), "")


# ---------------------------------------------------------------- row -> views

def op_view(r: MfgApsOpRow, refs: dict[str, Any], run_id: str) -> dict[str, Any]:
    item = refs["items"].get(r.item_id)
    line = refs["lines"].get(r.line_id) if r.line_id else None
    grp = refs["groups"].get(r.group_id)
    return {
        "op_no": r.op_no,
        "order": {"type": r.order_type, "id": r.order_id, "number": r.order_number, "planned_no": r.planned_no,
                  "item_id": r.item_id},
        "seq": r.seq, "name": r.name, "group_id": r.group_id, "qty": r.qty,
        "split": {"index": r.split_index, "count": r.split_count}, "line_id": r.line_id,
        "start": as_utc(r.start_at) if r.start_at else None, "end": as_utc(r.end_at) if r.end_at else None,
        "setup_minutes": r.setup_minutes, "run_minutes": r.run_minutes, "pieces": r.pieces, "crew": r.crew,
        "tools": r.tools, "release": r.release, "locked": r.locked, "frozen": r.frozen, "status": r.status,
        "reason": r.reason, "due": as_utc(r.due_at) if r.due_at else None, "late_minutes": r.late_minutes,
        "family": r.family, "setup_from_family": r.setup_from_family,
        "item": item, "line": {"id": line.id, "code": line.code} if line else None,
        "group": {"id": r.group_id, "code": grp.code if grp else ""},
        "link": f"/mfg/schedule/runs/{run_id}/gantt?op={r.op_no}"}


def order_view(r: MfgApsOrderRow) -> dict[str, Any]:
    return {"order": {"type": r.order_type, "id": r.order_id, "number": r.number, "planned_no": r.planned_no,
                      "item_id": r.item_id},
            "part_number": r.part_number, "qty": r.qty, "due": as_utc(r.due_at) if r.due_at else None,
            "start": as_utc(r.start_at) if r.start_at else None, "end": as_utc(r.end_at) if r.end_at else None,
            "late_minutes": r.late_minutes, "weight": r.weight, "priority": r.priority, "rank_label": r.rank_label,
            "demand_refs": r.demand_refs, "late_chain": r.late_chain, "late_text": r.late_text,
            "unscheduled_ops": r.unscheduled_ops,
            "link": f"/mfg/work-orders/{r.order_id}" if r.order_type == "wo" else None}


def overtime_view(r: MfgApsOvertimeRow) -> dict[str, Any]:
    return {"line_id": r.line_id, "assignment_id": r.assignment_id, "start": as_utc(r.start_at),
            "end": as_utc(r.end_at), "minutes": r.minutes, "cost": r.cost, "status": r.status,
            "tardiness_saved_minutes": r.tardiness_saved_minutes, "reason": r.reason, "orders": r.orders}


def exception_view(r: MfgApsExceptionRow) -> dict[str, Any]:
    return {"id": r.id, "ex_no": r.ex_no, "code": r.code, "severity": r.severity, "subject": r.subject,
            "op_no": r.op_no, "order": r.order_ref, "message": r.message, "refs": r.refs}


def load_view(r: MfgApsLoadRow) -> dict[str, Any]:
    return {"group_id": r.group_id, "line_id": r.line_id, "day": r.day, "scheduled_minutes": r.scheduled_minutes,
            "required_minutes": r.required_minutes, "base_minutes": r.base_minutes,
            "optional_minutes": r.optional_minutes, "opened_minutes": r.opened_minutes}


def week_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def bucket_load(rows: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    if bucket == "day":
        return rows
    agg: dict[tuple[str, str | None, date], dict[str, Any]] = {}
    for r in rows:
        k = (r["group_id"], r["line_id"], week_of(r["day"]))
        a = agg.get(k)
        if a is None:
            a = agg[k] = {**r, "day": k[2]}
            continue
        for f in ("scheduled_minutes", "required_minutes", "base_minutes", "optional_minutes", "opened_minutes"):
            a[f] += r[f]
    return [agg[k] for k in sorted(agg, key=lambda k: (k[0], k[1] or "", k[2]))]


def parse_dt(v: Any) -> datetime:
    return datetime.fromisoformat(v) if isinstance(v, str) else v


__all__ = ["bucket_load", "exception_view", "load_view", "op_view", "order_view", "overtime_view", "parse_dt",
           "store"]
