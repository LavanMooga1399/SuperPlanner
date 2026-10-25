"""BOM computations (M1-DESIGN 4.1, 4.3, 4.4, 5 and review R8).

- `explode(mode="indented")` is a depth-first generator that raises `ExplosionTooLarge` as soon as row
  `MAX_EXPLOSION_ROWS + 1` would be produced; it never builds a path list first.
- `explode(mode="summarized")` never enumerates paths: quantities and path counts are propagated level by level over
  the effective BOM graph (O(levels x edges), levels <= MAX_BOM_DEPTH), which also bounds cycles.
- Cycles: iterative Tarjan (no recursion), so 5,000-level chains are fine.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any, Literal

from .dataset import BomIndex, MfgDataset, ParentIndex, line_sort_key, pick_effective
from .limits import MAX_BOM_DEPTH, MAX_EXPLOSION_ROWS, REFDES_MAX_RANGE
from .model import (BomLineRecord, construct_fast, BomRecord, Explosion, ExplosionAlternate, ExplosionRow, ExplosionTotals,
                    ExplosionWarning, ItemRecord, OperationRecord, SummarizedRow, WhereUsed, WhereUsedRow,
                    WhereUsedTotals)
from .units import UnitMismatch, convert


class ExplosionTooLarge(Exception):
    """More than MAX_EXPLOSION_ROWS indented rows (API 422 MFG_EXPLOSION_TOO_LARGE)."""

    def __init__(self, limit: int = MAX_EXPLOSION_ROWS, what: str = "explosion"):
        super().__init__(f"The indented {what} has more than {limit} rows.")
        self.limit = limit
        self.what = what


def effective_bom(ds: MfgDataset, item_id: str, on: date, serial: int | None = None) -> BomRecord | None:
    return pick_effective(ds.boms_by_item.get(item_id, ()), on, serial)


# ---------------------------------------------------------------- quantities


def split_alternates(lines: list[BomLineRecord]) -> list[tuple[BomLineRecord, list[BomLineRecord]]]:
    """Lines in 3.5 order -> [(row line, its alternates sorted by priority)]. The row line of an alternate group is
    the priority-1 line (defensively: the lowest priority) at the position of the group's first line."""
    ordered = sorted(lines, key=line_sort_key)
    groups: dict[str, list[BomLineRecord]] = {}
    for ln in ordered:
        if ln.alt_group is not None:
            groups.setdefault(ln.alt_group, []).append(ln)
    out: list[tuple[BomLineRecord, list[BomLineRecord]]] = []
    seen: set[str] = set()
    for ln in ordered:
        if ln.alt_group is None:
            out.append((ln, []))
        elif ln.alt_group not in seen:
            seen.add(ln.alt_group)
            members = sorted(groups[ln.alt_group], key=lambda x: (x.alt_priority, line_sort_key(x)))
            out.append((members[0], members[1:]))
    return out


def _yield_factor(ops: list[OperationRecord], operation_seq: int | None) -> float:
    """Y_k of 4.4 for a line consumed at `operation_seq` (None or not found -> first operation)."""
    if not ops:
        return 1.0
    start = 0
    if operation_seq is not None:
        for i, o in enumerate(ops):
            if o.seq == operation_seq:
                start = i
                break
    y = 1.0
    for o in ops[start:]:
        y *= o.yield_pct / 100.0
    return y


def _required(q: float, ln: BomLineRecord, child_uom: str, ops: list[OperationRecord], include_scrap: bool,
              include_yield: bool) -> float:
    x = q
    if include_yield:
        x = x / _yield_factor(ops, ln.operation_seq)
    x = x * ln.qty_per
    if include_scrap:
        x = x * (1.0 + ln.scrap_pct / 100.0)
    try:
        return convert(x, ln.uom, child_uom)
    except (UnitMismatch, ValueError):
        return x       # dimension mismatch is a health error (MFG_UOM_MISMATCH); quantities stay unconverted


# ---------------------------------------------------------------- explosion


def _r6(x: float) -> float:
    return round(x, 6)


def explode(index: BomIndex, item_id: str, *, qty: float = 1.0,
            mode: Literal["indented", "summarized"] = "indented", include_scrap: bool = True,
            include_yield: bool = True, max_depth: int | None = None) -> Explosion:
    root = index.items[item_id]
    limit_depth = MAX_BOM_DEPTH if max_depth is None else min(max_depth, MAX_BOM_DEPTH)
    warnings: list[ExplosionWarning] = []
    warned: set[tuple[str, str]] = set()

    def warn(code: str, it: ItemRecord, message: str) -> None:
        if (code, it.id) not in warned:
            warned.add((code, it.id))
            warnings.append(ExplosionWarning.model_construct(code=code, message=message, item_id=it.id))

    def children_of(it: ItemRecord) -> list[tuple[BomLineRecord, list[BomLineRecord]]] | None:
        if it.make_buy == "buy":
            return None
        bom = index.effective.get(it.id)
        if bom is None:
            on = index.on.isoformat() if index.on else "the requested date"
            warn("MFG_NO_EFFECTIVE_BOM", it, f"{it.part_number} has no BOM effective on {on}.")
            return None
        return split_alternates(bom.lines)

    if mode == "summarized":
        return _summarized(index, root, qty, include_scrap, include_yield, limit_depth, max_depth, warnings,
                           warn, children_of)

    rows: list[ExplosionRow] = []

    def new_row(it: ItemRecord, level: int, parent_row: int | None, ln: BomLineRecord | None,
                alts: list[BomLineRecord], ext: float) -> ExplosionRow:
        if len(rows) >= MAX_EXPLOSION_ROWS:
            raise ExplosionTooLarge()
        bom = index.effective.get(it.id) if it.make_buy != "buy" else None
        r = construct_fast(ExplosionRow, dict(
            row=len(rows), parent_row=parent_row, subtree_end=len(rows) + 1, level=level,
            line_id=ln.id if ln else None, bom_id=bom.id if bom else None, item_id=it.id,
            part_number=it.part_number, revision=it.revision, description=it.description, make_buy=it.make_buy,
            uom=it.uom, family=it.family, lead_time_days=it.lead_time_days, active=it.active,
            find_number=ln.find_number if ln else None, ref_designators=ln.ref_designators if ln else "",
            qty_per=ln.qty_per if ln else None, line_uom=ln.uom if ln else None,
            scrap_pct=ln.scrap_pct if ln else None, operation_seq=ln.operation_seq if ln else None,
            extended_qty=_r6(ext),
            alternates=[construct_fast(ExplosionAlternate, dict(
                line_id=a.id, item_id=a.child_item_id, part_number=index.items[a.child_item_id].part_number
                if a.child_item_id in index.items else a.child.part_number, qty_per=a.qty_per, line_uom=a.uom,
                alt_priority=a.alt_priority)) for a in alts],
            is_phantom=it.make_buy == "phantom", has_children=False, is_shared=False,
            routing_id=index.routing_ids.get(it.id) if it.make_buy == "make" else None))
        rows.append(r)
        return r

    root_row = new_row(root, 0, None, None, [], float(qty))
    # stack frames: (row, item, quantity, iterator over child lines, path set)
    stack: list[tuple[ExplosionRow, ItemRecord, float, Any]] = []
    on_path: set[str] = {root.id}

    def push(row: ExplosionRow, it: ItemRecord, q: float) -> None:
        kids = None
        if row.level >= limit_depth:
            if children_of_peek(it):
                if max_depth is None or max_depth > MAX_BOM_DEPTH:
                    warn("MFG_BOM_TOO_DEEP", it, f"The structure below {it.part_number} is deeper than "
                                                 f"{MAX_BOM_DEPTH} levels; deeper levels are not shown.")
        else:
            kids = children_of(it)
        stack.append((row, it, q, iter(kids or ())))

    def children_of_peek(it: ItemRecord) -> bool:
        if it.make_buy == "buy":
            return False
        bom = index.effective.get(it.id)
        return bool(bom is not None and bom.lines)

    push(root_row, root, float(qty))
    while stack:
        row, it, q, kids = stack[-1]
        nxt = next(kids, None)
        if nxt is None:
            stack.pop()
            on_path.discard(it.id)
            d = row.__dict__
            d["subtree_end"] = len(rows)
            d["has_children"] = d["subtree_end"] > d["row"] + 1
            continue
        ln, alts = nxt
        child = index.items.get(ln.child_item_id)
        if child is None:
            continue
        ops = index.primary_ops.get(it.id, []) if it.make_buy == "make" else []
        req = _required(q, ln, child.uom, ops, include_scrap, include_yield)
        crow = new_row(child, row.level + 1, row.row, ln, alts, req)
        if child.id in on_path:
            warn("MFG_BOM_CYCLE", child, f"{child.part_number} contains itself; the branch is cut.")
            continue
        on_path.add(child.id)
        push(crow, child, req)

    parents: dict[str, set[str]] = {}
    for r in rows:
        if r.parent_row is not None:
            parents.setdefault(r.item_id, set()).add(rows[r.parent_row].item_id)
    distinct: dict[str, str] = {}
    for r in rows:
        r.__dict__["is_shared"] = len(parents.get(r.item_id, ())) > 1
        distinct.setdefault(r.item_id, r.make_buy)
    totals = ExplosionTotals.model_construct(
        rows=len(rows), distinct_items=len(distinct), max_level=max(r.level for r in rows),
        make_items=sum(1 for v in distinct.values() if v == "make"),
        buy_items=sum(1 for v in distinct.values() if v == "buy"),
        phantom_items=sum(1 for v in distinct.values() if v == "phantom"))
    return Explosion.model_construct(item_id=root.id, part_number=root.part_number, on=index.on,
                                     serial=index.serial, qty=float(qty), mode="indented", rows=rows,
                                     totals=totals, warnings=warnings)


def _summarized(index: BomIndex, root: ItemRecord, qty: float, include_scrap: bool, include_yield: bool,
                limit_depth: int, max_depth: int | None, warnings: list[ExplosionWarning], warn: Callable,
                children_of: Callable) -> Explosion:
    total: dict[str, float] = {}
    occ: dict[str, int] = {}
    lo: dict[str, int] = {}
    hi: dict[str, int] = {}
    frontier: dict[str, tuple[float, int]] = {root.id: (float(qty), 1)}
    kids_cache: dict[str, Any] = {}
    distinct: dict[str, str] = {root.id: root.make_buy}
    level = 0
    max_level = 0
    while frontier:
        nxt: dict[str, tuple[float, int]] = {}
        for item_id, (q, n) in frontier.items():
            it = index.items[item_id]
            if it.make_buy == "buy":
                continue
            if level >= limit_depth:
                bom = index.effective.get(it.id)
                if bom is not None and bom.lines and (max_depth is None or max_depth > MAX_BOM_DEPTH):
                    warn("MFG_BOM_TOO_DEEP", it, f"The structure below {it.part_number} is deeper than "
                                                 f"{MAX_BOM_DEPTH} levels; deeper levels are not shown.")
                continue
            if item_id not in kids_cache:
                kids_cache[item_id] = children_of(it) or []
            ops = index.primary_ops.get(it.id, []) if it.make_buy == "make" else []
            for ln, _alts in kids_cache[item_id]:
                child = index.items.get(ln.child_item_id)
                if child is None:
                    continue
                req = _required(q, ln, child.uom, ops, include_scrap, include_yield)
                pq, pn = nxt.get(child.id, (0.0, 0))
                nxt[child.id] = (pq + req, pn + n)
        level += 1
        for cid, (q, n) in nxt.items():
            child = index.items[cid]
            distinct.setdefault(cid, child.make_buy)
            max_level = max(max_level, level)
            if child.make_buy == "phantom":
                continue
            total[cid] = total.get(cid, 0.0) + q
            occ[cid] = occ.get(cid, 0) + n
            lo.setdefault(cid, level)
            hi[cid] = level
        frontier = nxt
    rows = [SummarizedRow.model_construct(
        item_id=cid, part_number=index.items[cid].part_number, description=index.items[cid].description,
        make_buy=index.items[cid].make_buy, uom=index.items[cid].uom, total_qty=_r6(total[cid]), min_level=lo[cid],
        max_level=hi[cid], occurrences=occ[cid], lead_time_days=index.items[cid].lead_time_days) for cid in total]
    rows.sort(key=lambda r: (r.min_level, r.part_number))
    totals = ExplosionTotals.model_construct(
        rows=len(rows), distinct_items=len(distinct), max_level=max_level,
        make_items=sum(1 for v in distinct.values() if v == "make"),
        buy_items=sum(1 for v in distinct.values() if v == "buy"),
        phantom_items=sum(1 for v in distinct.values() if v == "phantom"))
    return Explosion.model_construct(item_id=root.id, part_number=root.part_number, on=index.on,
                                     serial=index.serial, qty=float(qty), mode="summarized", rows=rows,
                                     totals=totals, warnings=warnings)


# ---------------------------------------------------------------- where-used


def where_used(index: ParentIndex, item_id: str, *, mode: Literal["single", "indented"] = "single") -> WhereUsed:
    root = index.items[item_id]

    def parents(child_id: str) -> list[tuple[BomRecord, BomLineRecord]]:
        out = [(b, ln) for b, ln in index.parent_lines.get(child_id, ()) if b.item_id in index.items]
        out.sort(key=lambda bl: (index.items[bl[0].item_id].part_number, bl[0].revision, bl[0].version,
                                 line_sort_key(bl[1])))
        return out

    rows: list[WhereUsedRow] = []

    def add(b: BomRecord, ln: BomLineRecord, level: int, parent_row: int | None) -> WhereUsedRow:
        if len(rows) >= MAX_EXPLOSION_ROWS:
            raise ExplosionTooLarge(what="where-used list")
        p = index.items[b.item_id]
        r = WhereUsedRow.model_construct(
            row=len(rows), level=level, parent_row=parent_row, item_id=p.id, part_number=p.part_number,
            revision=p.revision, description=p.description, make_buy=p.make_buy, bom_id=b.id,
            bom_revision=b.revision, bom_version=b.version, bom_status=b.status, line_id=ln.id,
            find_number=ln.find_number, qty_per=ln.qty_per, line_uom=ln.uom,
            is_top=not index.parent_lines.get(p.id))
        rows.append(r)
        return r

    if mode == "single":
        for b, ln in parents(root.id):
            add(b, ln, 1, None)
    else:
        stack: list[tuple[WhereUsedRow | None, Any, set[str]]] = [(None, iter(parents(root.id)), {root.id})]
        while stack:
            prow, it, path = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                continue
            b, ln = nxt
            level = 1 if prow is None else prow.level + 1
            r = add(b, ln, level, prow.row if prow else None)
            if b.item_id in path or level >= MAX_BOM_DEPTH:
                continue
            stack.append((r, iter(parents(b.item_id)), path | {b.item_id}))
    tops = {r.item_id for r in rows if r.is_top}
    return WhereUsed.model_construct(item_id=root.id, part_number=root.part_number, mode=mode,
                                     include=index.include, on=index.on, rows=rows,
                                     totals=WhereUsedTotals.model_construct(rows=len(rows), top_items=len(tops)))


# ---------------------------------------------------------------- graph


def bom_edges(ds: MfgDataset) -> list[tuple[str, str]]:
    """(parent item, child item) over draft + released BOMs, deduplicated, deterministic order."""
    out: dict[tuple[str, str], None] = {}
    for b in sorted(ds.boms.values(), key=lambda b: b.id):
        if b.status == "obsolete":
            continue
        for ln in b.lines:
            out[(b.item_id, ln.child_item_id)] = None
    return list(out)


def _adjacency(edges: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, [])
    return adj


def strongly_connected(edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    """Iterative Tarjan: every SCC (also singletons)."""
    adj = _adjacency(edges)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for start in adj:
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            v, i = work[-1]
            succ = adj[v]
            if i < len(succ):
                work[-1] = (v, i + 1)
                w = succ[i]
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, 0))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(comp)
    return out


def _shortest_path(adj: dict[str, list[str]], src: str, dst: str, allowed: set[str] | None = None) -> list[str] | None:
    prev: dict[str, str | None] = {src: None}
    q = deque([src])
    while q:
        v = q.popleft()
        for w in adj.get(v, ()):
            if allowed is not None and w not in allowed:
                continue
            if w == dst:
                path = [w, v]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])  # type: ignore[arg-type]
                return path[::-1]
            if w not in prev:
                prev[w] = v
                q.append(w)
    return None


def find_cycles(edges: Iterable[tuple[str, str]], key: Callable[[str], Any] | None = None) -> list[list[str]]:
    """One closed cycle path `[a, b, ..., a]` per SCC of size > 1 or self-loop, starting at the SCC's smallest node
    (by `key`, e.g. the part number; default the id); SCCs sorted by that node."""
    edges = list(edges)
    key = key or (lambda x: x)
    adj = _adjacency(edges)
    self_loops = {a for a, b in edges if a == b}
    out: list[list[str]] = []
    for comp in strongly_connected(edges):
        if len(comp) == 1 and comp[0] not in self_loops:
            continue
        start = min(comp, key=lambda x: (key(x), x))
        if len(comp) == 1:
            out.append([start, start])
            continue
        path = _shortest_path(adj, start, start, set(comp))
        out.append(path or [start, start])
    out.sort(key=lambda p: (key(p[0]), p[0]))
    return out


def would_create_cycle(edges: Iterable[tuple[str, str]], new_edges: Iterable[tuple[str, str]]) -> list[str] | None:
    """The closed path `parent -> child -> ... -> parent` that the new edges would create, else None."""
    new_edges = list(new_edges)
    adj = _adjacency(list(edges) + new_edges)
    for p, c in new_edges:
        if p == c:
            return [p, p]
        back = _shortest_path(adj, c, p)
        if back is not None:
            return [p] + back
    return None


# ---------------------------------------------------------------- reference designators

_SINGLE = re.compile(r"^[A-Za-z]+[A-Za-z0-9_.]*$")
_RANGE = re.compile(r"^([A-Za-z]+)(\d{1,12})-([A-Za-z]+)?(\d{1,12})$")
_SPLIT = re.compile(r"[\s,;]+")


def refdes_count(text: str) -> tuple[int, list[str]]:
    """`"R1, R2, R5-R9"` -> (7, []). Ranges (`X5-X9`, `X5-9`) are counted arithmetically, never expanded; a range
    wider than REFDES_MAX_RANGE, a reversed range, a prefix change or any other bad token goes to the invalid list."""
    count = 0
    invalid: list[str] = []
    for tok in _SPLIT.split(text.strip()):
        if not tok:
            continue
        m = _RANGE.match(tok)
        if m:
            p1, a, p2, b = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            if (p2 is not None and p2 != p1) or b < a or b - a + 1 > REFDES_MAX_RANGE:
                invalid.append(tok)
            else:
                count += b - a + 1
        elif _SINGLE.match(tok):
            count += 1
        else:
            invalid.append(tok)
    return count, invalid
