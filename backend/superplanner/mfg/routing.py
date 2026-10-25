"""Routings: effective routings, operation time (4.5), yields and lot inputs (4.4), line eligibility, time preview."""

from __future__ import annotations

import math
from datetime import date

from .dataset import MfgDataset, is_effective
from .model import (ItemRecord, LineRecord, OperationRecord, OpTime, Ref, RoutingRecord, TimePreview,
                    TimePreviewLine, TimePreviewOperation, TimePreviewTotals)
from .units import is_count

EPS = 1e-9


def effective_routings(ds: MfgDataset, item_id: str, on: date, serial: int | None = None) -> list[RoutingRecord]:
    """Per priority: serial-specific over generic, then the highest `(effective_from, version)`; sorted by priority."""
    by_prio: dict[int, list[RoutingRecord]] = {}
    for r in ds.routings_by_item.get(item_id, ()):
        if is_effective(r, on, serial):
            by_prio.setdefault(r.priority, []).append(r)
    out: list[RoutingRecord] = []
    for prio in sorted(by_prio):
        cands = by_prio[prio]
        specific = [r for r in cands if r.serial_from is not None]
        pool = specific or cands
        out.append(max(pool, key=lambda r: (r.effective_from or date.min, r.version, r.revision, r.code, r.id)))
    return out


def primary_routing(ds: MfgDataset, item_id: str, on: date, serial: int | None = None) -> RoutingRecord | None:
    rs = effective_routings(ds, item_id, on, serial)
    return rs[0] if rs else None


def loads(op: OperationRecord, qty: float) -> float:
    if op.run_per == "panel":
        return float(math.ceil(qty / op.units_per_panel - EPS))
    if op.run_per == "batch":
        return float(math.ceil(qty / op.units_per_batch - EPS))
    return float(qty)


def operation_minutes(op: OperationRecord, qty: float, speed_factor: float = 1.0) -> OpTime:
    n = loads(op, qty)
    setup = float(op.setup_minutes)
    run = op.run_minutes * n / speed_factor
    return OpTime.model_construct(setup=setup, run=run, total=setup + run, loads=n)


def _ops_sorted(ops: list[OperationRecord]) -> list[OperationRecord]:
    return sorted(ops, key=lambda o: o.seq)


def cumulative_yield(ops: list[OperationRecord], from_seq: int | None = None) -> float:
    """Product of the yields of the operations from `from_seq` to the end (`None` or an unknown seq: all)."""
    ops = _ops_sorted(ops)
    start = 0
    if from_seq is not None:
        for i, o in enumerate(ops):
            if o.seq == from_seq:
                start = i
                break
    y = 1.0
    for o in ops[start:]:
        y *= o.yield_pct / 100.0
    return y


def lot_inputs(ops: list[OperationRecord], qty: float, count_uom: bool) -> list[float]:
    """Input quantity per operation (ascending seq) to deliver `qty` good units (4.4)."""
    ops = _ops_sorted(ops)
    out = [0.0] * len(ops)
    nxt = float(qty)
    for k in range(len(ops) - 1, -1, -1):
        y = ops[k].yield_pct / 100.0
        nxt = float(math.ceil(nxt / y - EPS)) if count_uom else nxt / y
        out[k] = nxt
    return out


def line_eligible(line: LineRecord, item: ItemRecord) -> bool:
    if not line.eligible_families and not line.eligible_item_ids:
        return True
    return (item.family is not None and item.family in line.eligible_families) or item.id in line.eligible_item_ids


def ineligible_reason(line: LineRecord, item: ItemRecord) -> str | None:
    if line_eligible(line, item):
        return None
    if item.family is None:
        return "item has no family and is not in the line's item list"
    return f"family {item.family} not eligible"


def eligible_lines(ds: MfgDataset, group_id: str, item: ItemRecord) -> list[LineRecord]:
    return [ln for ln in ds.lines_by_group.get(group_id, ()) if ln.active and line_eligible(ln, item)]


def to_engine_minutes(x: float) -> int:
    return max(0, math.ceil(x - EPS))


def time_preview(ds: MfgDataset, routing_id: str, qty: float) -> TimePreview:
    """Per operation and per active line of its group: setup/run/total minutes for `qty` good units (9.4 #28)."""
    r = ds.routings[routing_id]
    item = ds.items[r.item_id]
    ops = _ops_sorted(r.operations)
    inputs = lot_inputs(ops, qty, is_count(item.uom))
    out_ops: list[TimePreviewOperation] = []
    fastest = slowest = passive = 0.0
    for k, op in enumerate(ops):
        inp = inputs[k]
        outp = inputs[k + 1] if k + 1 < len(ops) else float(qty)
        rows: list[TimePreviewLine] = []
        for ln in ds.lines_by_group.get(op.group_id, ()):
            if not ln.active:
                continue
            t = operation_minutes(op, inp, ln.speed_factor)
            reason = ineligible_reason(ln, item)
            rows.append(TimePreviewLine.model_construct(
                line_id=ln.id, code=ln.code, speed_factor=ln.speed_factor, eligible=reason is None, reason=reason,
                setup_minutes=round(t.setup, 6), run_minutes=round(t.run, 6), total_minutes=round(t.total, 6)))
        totals = [operation_minutes(op, inp, ln.speed_factor).total
                  for ln in ds.lines_by_group.get(op.group_id, ()) if ln.active and line_eligible(ln, item)]
        if totals:
            fastest += min(totals)
            slowest += max(totals)
        passive += op.queue_minutes + op.move_minutes + op.wait_minutes
        g = ds.groups.get(op.group_id)
        out_ops.append(TimePreviewOperation.model_construct(
            seq=op.seq, name=op.name,
            group=Ref.model_construct(id=op.group_id, code=g.code if g else "?", name=g.name if g else ""),
            input_qty=round(inp, 6), output_qty=round(outp, 6), run_per=op.run_per, loads=loads(op, inp),
            queue_minutes=op.queue_minutes, move_minutes=op.move_minutes, wait_minutes=op.wait_minutes,
            labor=op.labor, lines=rows))
    return TimePreview.model_construct(
        routing_id=r.id, item_id=item.id, qty=float(qty), uom=item.uom, operations=out_ops,
        totals=TimePreviewTotals.model_construct(fastest_minutes=round(fastest, 6), slowest_minutes=round(slowest, 6),
                                                 passive_minutes=round(passive, 6),
                                                 cumulative_yield=round(cumulative_yield(ops), 6)))
