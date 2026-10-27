"""Explosion of one order (M2-DESIGN 8.7), shared by MRP planned orders and WO creation.

`order_components(ds, item_id, qty, on=, serial=)`:
- BOM = effective BOM at `on` for `serial`; routing = primary effective routing (M1 4.1).
- Per primary line `need = qty / Y_k x qty_per x (1 + scrap/100)` in the child UoM (M1 4.4); phantom children are
  expanded recursively in place (Y of a phantom = 1, its own effective BOM at the same `on`/`serial`); then
  count-UoM children are rounded up per line (`ceil(need - 1e-9)`), others to 6 decimals.
- One `ComponentNeed` per line (MRP sums per child for the order).
- `directives[(order_key, alt_key)] = primary-equivalent qty` moves that part of the primary's need to the group's
  first alternate; `directives[(order_key, f"{alt_key}:{alt_priority}")]` to that specific alternate (8.9).
  Alternate need = moved x (alt factor / primary factor), i.e. `alt.qty_per / primary.qty_per x (1 + alt.scrap) /
  (1 + primary.scrap)`, UoM-converted. `alt_key` = the line's `alt_group` (top level) or
  `"<phantom item id>>" + alt_group` for groups inside a phantom.

The unit structure (continuous need per parent unit) is cached per `(item, on, serial)` by `StructureCache`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..bom import _yield_factor, effective_bom, split_alternates
from ..dataset import MfgDataset
from ..limits import MAX_BOM_DEPTH
from ..model import BomLineRecord
from ..routing import primary_routing
from ..units import UnitMismatch, convert, is_count


@dataclass(frozen=True, slots=True)
class ComponentNeed:
    item_id: str
    qty: float
    bom_line_id: str | None
    find_number: str | None
    operation_seq: int | None
    alt_group: str | None
    substitute_for: str | None        # the primary line id when this need is an alternate
    alt_key: str | None = None        # directive key of the group (8.9)


@dataclass(frozen=True, slots=True)
class OrderExplosion:
    bom_id: str | None
    routing_id: str | None
    components: tuple[ComponentNeed, ...]
    warnings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class _Pos:
    """One line position of the unit structure: `factor` = continuous child need per parent unit."""
    item_id: str
    factor: float
    line: BomLineRecord
    operation_seq: int | None


@dataclass(frozen=True, slots=True)
class _Group:
    primary: _Pos
    alternates: tuple[tuple[int, _Pos], ...]      # (alt_priority, position)
    alt_key: str | None


@dataclass(frozen=True, slots=True)
class UnitStructure:
    bom_id: str | None
    routing_id: str | None
    groups: tuple[_Group, ...]
    warnings: tuple[dict[str, Any], ...] = ()


def _conv(x: float, ln: BomLineRecord, child_uom: str) -> float:
    try:
        return convert(x, ln.uom, child_uom)
    except (UnitMismatch, ValueError):
        return x


def unit_structure(ds: MfgDataset, item_id: str, on: date, serial: int | None) -> UnitStructure:
    item = ds.items[item_id]
    bom = effective_bom(ds, item_id, on, serial)
    routing = primary_routing(ds, item_id, on, serial) if item.make_buy == "make" else None
    if bom is None:
        w = {"code": "WO_NO_EFFECTIVE_BOM", "item_id": item_id,
             "message": f"{item.part_number} has no BOM effective on {on.isoformat()}."}
        return UnitStructure(None, routing.id if routing else None, (), (w,))
    ops = sorted(routing.operations, key=lambda o: o.seq) if routing is not None else []
    groups: list[_Group] = []
    warnings: list[dict[str, Any]] = []

    def pos(ln: BomLineRecord, base: float, y_ops: list[Any], op_seq: int | None) -> _Pos:
        child = ds.items[ln.child_item_id]
        y = _yield_factor(y_ops, ln.operation_seq) if y_ops else 1.0
        f = _conv(base / y * ln.qty_per * (1.0 + ln.scrap_pct / 100.0), ln, child.uom)
        return _Pos(child.id, f, ln, op_seq if op_seq is not None else ln.operation_seq)

    def walk(lines: list[BomLineRecord], base: float, y_ops: list[Any], prefix: str, op_seq: int | None,
             depth: int, stack: tuple[str, ...]) -> None:
        for primary, alts in split_alternates(lines):
            p = pos(primary, base, y_ops, op_seq)
            child = ds.items[p.item_id]
            if child.make_buy == "phantom" and not alts and depth < MAX_BOM_DEPTH and child.id not in stack:
                pb = effective_bom(ds, child.id, on, serial)
                if pb is not None:
                    walk(pb.lines, p.factor, [], f"{prefix}{child.id}>", p.operation_seq, depth + 1,
                         stack + (child.id,))
                    continue
                warnings.append({"code": "WO_NO_EFFECTIVE_BOM", "item_id": child.id,
                                 "message": f"Phantom {child.part_number} has no BOM effective on {on.isoformat()}."})
            key = f"{prefix}{primary.alt_group}" if primary.alt_group is not None else None
            groups.append(_Group(p, tuple((a.alt_priority, pos(a, base, y_ops, op_seq)) for a in alts), key))

    walk(bom.lines, 1.0, ops, "", None, 0, (item_id,))
    return UnitStructure(bom.id, routing.id if routing else None, tuple(groups), tuple(warnings))


class StructureCache:
    def __init__(self, ds: MfgDataset):
        self.ds = ds
        self._memo: dict[tuple[str, date, int | None], UnitStructure] = {}

    def get(self, item_id: str, on: date, serial: int | None) -> UnitStructure:
        k = (item_id, on, serial)
        s = self._memo.get(k)
        if s is None:
            s = self._memo[k] = unit_structure(self.ds, item_id, on, serial)
        return s


def round_need(x: float, count: bool) -> float:
    if count:
        return float(math.ceil(x - 1e-9))
    return round(x, 6)


def apply_structure(ds: MfgDataset, st: UnitStructure, qty: float, *,
                    directives: Mapping[tuple[str, str], float] | None = None,
                    order_key: str | None = None) -> list[ComponentNeed]:
    out: list[ComponentNeed] = []
    items = ds.items
    for g in st.groups:
        p = g.primary
        need_p = qty * p.factor
        moved: list[tuple[_Pos, float]] = []
        if directives and order_key is not None and g.alt_key is not None and g.alternates:
            total = 0.0
            for i, (prio, a) in enumerate(g.alternates):
                m = directives.get((order_key, f"{g.alt_key}:{prio}"), 0.0)
                if i == 0:
                    m += directives.get((order_key, g.alt_key), 0.0)
                m = max(0.0, min(m, need_p - total))
                if m > 1e-9:
                    total += m
                    moved.append((a, m))
            need_p -= total
        pl = p.line
        if need_p > 1e-9:
            q = round_need(need_p, is_count(items[p.item_id].uom))
            if q > 0:
                out.append(ComponentNeed(p.item_id, q, pl.id, pl.find_number, p.operation_seq, pl.alt_group, None,
                                         g.alt_key))
        for a, m in moved:
            need_a = m / p.factor * a.factor if p.factor > 0 else 0.0
            q = round_need(need_a, is_count(items[a.item_id].uom))
            if q > 0:
                al = a.line
                out.append(ComponentNeed(a.item_id, q, al.id, al.find_number, a.operation_seq, al.alt_group, pl.id,
                                         g.alt_key))
    return out


def order_components(ds: MfgDataset, item_id: str, qty: float, *, on: date, serial: int | None,
                     directives: Mapping[tuple[str, str], float] | None = None,
                     order_key: str | None = None) -> OrderExplosion:
    st = unit_structure(ds, item_id, on, serial)
    comps = apply_structure(ds, st, qty, directives=directives, order_key=order_key)
    return OrderExplosion(st.bom_id, st.routing_id, tuple(comps), st.warnings)


__all__ = ["ComponentNeed", "OrderExplosion", "StructureCache", "UnitStructure", "apply_structure",
           "order_components", "round_need", "unit_structure"]
