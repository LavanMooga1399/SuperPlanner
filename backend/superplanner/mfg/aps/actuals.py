"""APS with execution actuals (M4-DESIGN 6.1, 8). Pure helpers shared by the model builder and the independent
validator, so both derive the same inputs from the snapshot:

- `ActualOp`: an operation's floor state. `completed` / `skipped` operations are dropped (they are in the WO's
  `done_seqs`); `running` / `setup` / `paused` ones are planned first on their line from `as_of` with the remaining
  quantity (`qty_planned - good - scrap + rework_in`), a paused one resumes first;
- `closures`: open / planned downtime (end = `end_at`, else `expected_end_at`, else `as_of + 4 h`) and the what-if
  `line_breakdowns` close their line;
- `moved_by_downtime`: frozen (published, inside the freeze) operations overlapping a closure on their line are no
  longer frozen - feasibility first;
- `apply_supply_delays`: what-if `supply_delays` shift the availability of pegged / open supply.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

EPS = 1e-6
NO_END_HOURS = 4
ACTIVE = ("setup", "running", "paused")


@dataclass(frozen=True)
class ActualOp:
    wo_id: str
    seq: int
    wo_operation_id: str
    status: str                       # pending | setup | running | paused (completed / skipped are done_seqs)
    line_id: str | None
    remaining: float                  # remaining input quantity
    actual_start: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE and self.line_id is not None


@dataclass(frozen=True)
class Downtime:
    id: str
    line_id: str
    start: datetime
    end: datetime | None
    expected_end: datetime | None
    planned: bool = False


def closure_end(d: Downtime, as_of: datetime) -> tuple[datetime, bool]:
    """(end, guessed): a missing end and expected end -> as_of + 4 h (`FLR_DOWNTIME_NO_END`)."""
    if d.end is not None:
        return d.end, False
    if d.expected_end is not None:
        return max(d.expected_end, as_of), False
    return max(as_of, d.start) + timedelta(hours=NO_END_HOURS), True


def closures(snap: Any, params: Any) -> dict[str, list[tuple[datetime, datetime]]]:
    out: dict[str, list[tuple[datetime, datetime]]] = {}
    for d in getattr(snap, "downtime", ()) or ():
        end, _g = closure_end(d, snap.as_of)
        if end > snap.as_of and end > d.start:
            out.setdefault(d.line_id, []).append((d.start, end))
    for b in getattr(params, "line_breakdowns", ()) or ():
        out.setdefault(b.line_id, []).append((b.start, b.start + timedelta(hours=float(b.hours))))
    return out


def overlaps(spans: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    return any(a < end and start < b for a, b in spans)


def moved_by_downtime(snap: Any, params: Any) -> set[tuple[str, int, int]]:
    """(order_id, seq, split_index) of published operations overlapping a closure on their line."""
    cl = closures(snap, params)
    pub = getattr(snap, "published", None)
    out: set[tuple[str, int, int]] = set()
    if pub is None or not cl:
        return out
    for p in pub.ops:
        if p.line_id in cl and p.start is not None and p.end is not None and overlaps(cl[p.line_id], p.start, p.end):
            out.add((p.order_id, p.seq, p.split_index))
    return out


def superseded(snap: Any) -> set[tuple[str, int]]:
    """(wo_id, seq) whose published placement the floor state replaces (active operations)."""
    return {k for k, a in (getattr(snap, "actuals", {}) or {}).items() if a.active}


def apply_supply_delays(snap: Any, delays: Any) -> Any:
    """A snapshot copy with delayed pegged / open supply (what-if, 8). `schedule_id` -> that PO/PR schedule,
    `item_id` -> every buy supply of the item, `wo_id` -> the WO's output pegs."""
    if not delays:
        return snap
    by_sched = {d.schedule_id: d.days for d in delays if d.schedule_id}
    by_item = {d.item_id: d.days for d in delays if d.item_id}
    by_wo = {d.wo_id: d.days for d in delays if d.wo_id}

    def shift(day: Any, n: int) -> Any:
        return day + timedelta(days=n) if day is not None else day

    supply = []
    for s in snap.open_supply:
        n = by_sched.get(s.ref_id, 0) or by_item.get(s.item_id, 0)
        supply.append(replace(s, available_date=shift(s.available_date, n)) if n else s)
    mrp = snap.mrp
    if mrp is not None:
        pegs = {}
        for key, sups in mrp.pegs.items():
            item = key[2]
            new = []
            for p in sups:
                n = 0
                if p.kind in ("po_schedule", "pr_schedule"):
                    n = by_sched.get(p.ref_id or "", 0) or by_item.get(item, 0)
                elif p.kind in ("work_order", "wo"):
                    n = by_wo.get(p.ref_id or "", 0)
                new.append(replace(p, available_date=shift(p.available_date, n)) if n else p)
            pegs[key] = tuple(new)
        mrp = replace(mrp, pegs=pegs)
    return replace(snap, open_supply=sorted(supply, key=lambda s: (s.item_id, s.available_date, s.ref_id)), mrp=mrp)


__all__ = ["ACTIVE", "ActualOp", "Downtime", "apply_supply_delays", "closure_end", "closures", "moved_by_downtime",
           "overlaps", "superseded"]
