"""Genealogy traversal rules (M5-DESIGN 6.1-6.2), pure: edge -> (neighbour, link precision) and the tree assembly.

Edges are stored `from -> to` in material-flow direction (supplier lot -> WO -> output lot / serial -> demand
line). A forward trace follows `from -> to`, a backward trace `to -> from`.

Link precision (shown per node, relative to its parent in the tree):
- the stored edge precision (`exact`, or `possible` for quantity-only `item_stock` links);
- crossing a WO between a unit and lot-level material is `possible` (6.1: "WO consumed lot, WO produced serials:
  lot -> each serial possible, derived at query time"): lot/stock -> WO -> serial, serial -> WO -> lot/stock and
  serial -> WO -> serial (another unit of the same WO) are possible; a direct child -> parent serial link stays
  exact. A node reached both ways keeps the exact link (exact links are expanded first).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOT_LIKE = ("lot", "item_stock")


@dataclass
class Edge:
    owner_id: str
    from_kind: str
    from_id: str
    from_item_id: str | None
    to_kind: str
    to_id: str
    to_item_id: str | None
    qty: float | None
    precision: str
    event_at: Any
    plant_owner_id: str | None = None


@dataclass
class Node:
    owner_id: str
    kind: str
    id: str
    item_id: str | None
    qty: float | None
    precision: str
    at: Any
    depth: int
    via: "Node | None" = None          # parent in the tree
    children: list["Node"] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.owner_id, self.kind, self.id)

    def path(self) -> list["Node"]:
        out, n = [], self
        while n is not None:
            out.append(n)
            n = n.via
        return out[::-1]

    def cumulative(self) -> str:
        return "possible" if any(n.precision == "possible" for n in self.path()) else "exact"


def link_precision(parent: Node, edge_precision: str, child_kind: str) -> str:
    if edge_precision == "possible":
        return "possible"
    if parent.kind == "wo" and parent.via is not None:
        before = parent.via.kind
        if (before in LOT_LIKE and child_kind == "serial") or (before == "serial" and child_kind in LOT_LIKE) or \
                (before == "serial" and child_kind == "serial"):
            return "possible"
    return "exact"


def merge_parallel(edges: list[Edge], forward: bool) -> list[Edge]:
    """Edges of one (from, to) pair are summed (issues net of returns, reversals); a pair whose net quantity is
    not positive is dropped (fully returned / reversed)."""
    acc: dict[tuple[str, str, str, str, str], Edge] = {}
    for e in edges:
        k = (e.owner_id, e.from_kind, e.from_id, e.to_kind, e.to_id)
        if k in acc:
            a = acc[k]
            a.qty = (a.qty or 0.0) + (e.qty or 0.0) if (a.qty is not None or e.qty is not None) else None
            if e.precision == "exact":
                a.precision = "exact"
            if e.event_at is not None and (a.event_at is None or e.event_at < a.event_at):
                a.event_at = e.event_at
        else:
            acc[k] = Edge(**{f: getattr(e, f) for f in e.__dataclass_fields__})
    out = [e for e in acc.values() if e.qty is None or e.qty > 1e-9]
    out.sort(key=lambda e: (0 if e.precision == "exact" and (e.from_kind == "serial" and e.to_kind == "serial")
                            else 1, e.precision != "exact", e.to_id if forward else e.from_id))
    return out


__all__ = ["Edge", "LOT_LIKE", "Node", "link_precision", "merge_parallel"]
