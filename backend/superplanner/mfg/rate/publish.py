"""Publish rules of a rate run (M8-DESIGN 7.3; pure): which blocks become repetitive WOs and what happens to the
previous run's repetitive WOs in the firm zone.

- Firm zone: production blocks with `prod_date <= today + firm_days` -> one WO per (line, item, prod_date)
  (`split day`, one lot per line-day) or per (line, campaign) (`split campaign`); later blocks stay rate supplies.
- Previous unstarted repetitive WOs in the zone: a WO matching a new group (same item, line when known, due date
  and quantity within 1e-6) is kept and re-linked; others are cancelled. Started WOs (in progress or with output)
  are kept as they are; a group of the same item, line and day is never created again (review 3: the started WO
  stands for it; the quantity difference is reported in `skipped`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable


@dataclass
class Group:
    key: tuple
    line_id: str
    item_id: str
    prod_date: date            # first production day (WO start); due = last production day
    due: date
    qty: float
    block_ids: list[str] = field(default_factory=list)


@dataclass
class PrevWo:
    id: str
    item_id: str
    due: date
    qty: float
    started: bool
    line_id: str | None = None


@dataclass
class Decision:
    create: list[Group]
    keep: list[tuple[PrevWo, Group | None]]
    cancel: list[PrevWo]
    skipped: list[dict] = field(default_factory=list)


def firm_groups(blocks: Iterable[Any], firm_end: date, split: str = "day") -> list[Group]:
    acc: dict[tuple, Group] = {}
    for b in sorted(blocks, key=lambda x: (x.line_id, x.start)):
        if b.kind != "production" or not b.item_id or b.prod_date > firm_end:
            continue
        key = (b.line_id, b.item_id, b.prod_date) if split == "day" else (b.line_id, b.campaign_no)
        g = acc.get(key)
        if g is None:
            g = acc[key] = Group(key, b.line_id, b.item_id, b.prod_date, b.prod_date, 0.0)
        g.qty = round(g.qty + b.qty, 6)
        g.due = max(g.due, b.prod_date)
        g.block_ids.append(b.id)
    return list(acc.values())


def decide(groups: list[Group], previous: list[PrevWo]) -> Decision:
    open_groups = list(groups)
    keep: list[tuple[PrevWo, Group | None]] = []
    cancel: list[PrevWo] = []
    by_item: dict[str, list[Group]] = defaultdict(list)
    for g in open_groups:
        by_item[g.item_id].append(g)
    def same_place(g: Group, w: PrevWo) -> bool:
        return g.due == w.due and (w.line_id is None or g.line_id == w.line_id)

    skipped: list[dict] = []
    for w in sorted(previous, key=lambda x: (not x.started, x.due, x.id)):     # started WOs claim groups first
        if w.started:
            match = next((g for g in by_item[w.item_id] if same_place(g, w)), None)
            keep.append((w, match))
            if match is not None:
                by_item[w.item_id].remove(match)
                if abs(match.qty - w.qty) > 1e-6:
                    skipped.append({"wo_id": w.id, "item_id": w.item_id, "due": w.due, "planned_qty": match.qty,
                                    "wo_qty": w.qty})
            continue
        match = next((g for g in by_item[w.item_id] if same_place(g, w) and abs(g.qty - w.qty) <= 1e-6), None)
        if match is not None:
            keep.append((w, match))
            by_item[w.item_id].remove(match)
        else:
            cancel.append(w)
    create = [g for lst in by_item.values() for g in lst]
    create.sort(key=lambda g: (g.prod_date, g.line_id, g.item_id))
    return Decision(create, keep, cancel, skipped)
