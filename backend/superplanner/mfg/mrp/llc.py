"""Low-level codes (M2-DESIGN 8.4).

Graph: `parent -> child` of every released BOM whose effectivity window intersects `[as_of, window_end]` (generic
and serial-specific, phantoms included, all lines incl. alternates) plus every existing WO component edge.
`llc(item)` = longest path from any root (Kahn order + DP). A WO edge that would close a cycle is dropped (the WO is
reported `MRP_WO_COMPONENT_CYCLE`); the same defence drops BOM back edges (impossible after Gate 1).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..dataset import MfgDataset


def bom_edges_in_window(ds: MfgDataset, start: date, end: date) -> list[tuple[str, str]]:
    edges: dict[tuple[str, str], None] = {}
    for b in sorted(ds.boms.values(), key=lambda b: b.id):
        if b.status != "released":
            continue
        if b.effective_from is not None and b.effective_from > end:
            continue
        if b.effective_to is not None and b.effective_to <= start:
            continue
        for ln in b.lines:
            if ln.child_item_id != b.item_id:
                edges.setdefault((b.item_id, ln.child_item_id), None)
    return list(edges)


def _topo(nodes: list[str], adj: dict[str, list[str]]) -> dict[str, int] | None:
    indeg = {n: 0 for n in nodes}
    for n in nodes:
        for c in adj.get(n, ()):
            indeg[c] = indeg.get(c, 0) + 1
    level = {n: 0 for n in indeg}
    queue = [n for n in sorted(indeg) if indeg[n] == 0]
    seen = 0
    i = 0
    while i < len(queue):
        n = queue[i]
        i += 1
        seen += 1
        for c in adj.get(n, ()):
            if level[n] + 1 > level[c]:
                level[c] = level[n] + 1
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    return level if seen == len(indeg) else None


def _reaches(adj: dict[str, list[str]], src: str, dst: str) -> bool:
    if src == dst:
        return True
    stack = [src]
    seen = {src}
    while stack:
        n = stack.pop()
        for c in adj.get(n, ()):
            if c == dst:
                return True
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return False


def low_level_codes(items: Iterable[str], bom_edges: list[tuple[str, str]],
                    wo_edges: list[tuple[str, str, str]]) -> tuple[dict[str, int], list[str]]:
    """-> (llc per item, ids of WOs whose edges were dropped because they close a cycle). `wo_edges` =
    `(wo_id, parent_item, child_item)` in a deterministic order."""
    nodes = sorted(set(items) | {a for a, _ in bom_edges} | {b for _, b in bom_edges}
                   | {e[1] for e in wo_edges} | {e[2] for e in wo_edges})
    adj: dict[str, list[str]] = {}
    for a, b in bom_edges:
        adj.setdefault(a, []).append(b)
    level = _topo(nodes, adj)
    if level is None:                          # BOM cycle (Gate 1 prevents it): drop back edges in order
        adj = {}
        for a, b in bom_edges:
            if not _reaches(adj, b, a):
                adj.setdefault(a, []).append(b)
    full = {k: list(v) for k, v in adj.items()}
    wo_pairs: dict[tuple[str, str], None] = {}
    for _wo, a, b in wo_edges:
        if a != b:
            wo_pairs.setdefault((a, b), None)
    for a, b in wo_pairs:
        full.setdefault(a, []).append(b)
    level = _topo(nodes, full)
    broken: list[str] = []
    if level is None:
        full = {k: list(v) for k, v in adj.items()}
        bad_pairs: set[tuple[str, str]] = set()
        for a, b in wo_pairs:
            if b in full.get(a, ()):
                continue
            if _reaches(full, b, a):
                bad_pairs.add((a, b))
            else:
                full.setdefault(a, []).append(b)
        level = _topo(nodes, full) or {n: 0 for n in nodes}
        seen: set[str] = set()
        for wo, a, b in wo_edges:
            if (a, b) in bad_pairs or a == b:
                if wo not in seen:
                    seen.add(wo)
                    broken.append(wo)
    else:
        seen = set()
        for wo, a, b in wo_edges:
            if a == b and wo not in seen:
                seen.add(wo)
                broken.append(wo)
    return level, broken


__all__ = ["bom_edges_in_window", "low_level_codes"]
