"""Network DRP engine (M9-DESIGN 5.3). Pure and deterministic (ties by node code, key, week).

Vertices are (node, key). Edges: destination -> plant source (sourcing rules), parent -> component at the same node
(networked BOM lines). Low-level codes by DFS (a cycle -> `NetError NET_CYCLE` with the path). Vertices are
processed by (llc, node code, key) from a work queue:

1. Requirements = independent demand (orders, forecast, open transfers out) + dependent requirements emitted by
   other vertices (planned transfers out, BOM explosion) + safety stock (a requirement at the first week, after the
   orders of that week). Each requirement carries pegs to the demand it serves.
2. Weekly netting: requirements consume existing supply (FIFO by availability) then planned receipts; a shortfall
   creates (or grows) the week's planned receipt, lot-sized (`min_qty`, multiple of `order_multiple`); lot excess
   stays available to later requirements. The receipt's source follows 4: item-key rules win over family rules;
   quota mode = cumulative quota arrangement (largest `quota x (assigned_total + req) - assigned_source`, ties by
   priority), else the primary rule. Plant source -> planned transfer (ship = receive - transit working days of the
   source calendar), supplier source -> planned buy; no rule -> make (plant) / buy (`make_buy buy`) / `NET_NO_SOURCE`
   (DC). Starts before `as_of` move to the earliest feasible date; the lateness is a `NET_LEAD_TIME` shortage.
3. Capacity (`constrained`): a vertex's planned production is booked per node x cap group x week in rank order
   (order > forecast > ss, earlier week first; lot excess last). Overload: (a) pre-build up to `prebuild_weeks`
   earlier (not before the first week), (b) spill the part serving a transfer to the destination's next source
   (that source re-plans; quota sources too, reported `NET_SPILL`), (c) cut: `NET_CAPACITY_SHORT` at the vertex and,
   for transfers, at the pegged destination demand. Capacity is never exceeded; `constrained false` only reports.
4. Emission: transfers -> requirement at the source vertex in the ship week; production -> BOM requirements of the
   networked components in the start week. A re-planned vertex retracts what it emitted before (bounded loop).

Projection (gross = independent + BOM demand, planned_out = transfers out), utilisation and KPIs come last.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .calendar import NodeCalendar, monday, weeks as horizon_weeks
from .model import (NetError, NetItem, NetPeg, NetProblem, NetProduction, NetProjection, NetResult, NetRule,
                    NetShortage, NetTransfer, NetUtil)

EPS = 1e-6
RANK = {"order": 0, "transfer": 0, "transfer_open": 0, "forecast": 1, "dependent": 1, "ss": 2}
PEG_KIND = {"order": "order", "forecast": "forecast", "transfer_open": "transfer"}
MAX_PASSES = 60


@dataclass
class Req:
    week: date
    qty: float
    rank: int
    pegs: list[NetPeg]
    origin: Any = None            # NetTransfer (this vertex is its source) | ("bom", NetProduction) | None
    ref: str = ""


@dataclass
class Planned:
    """A planned receipt while netting: transfer in, production (make / buy)."""
    obj: Any
    week: date                    # need week (availability for netting)
    qty: float
    cons: list[tuple[int, date, Req, float]] = field(default_factory=list)   # (rank, week, req, qty)
    rule: NetRule | None = None


def _round(x: float) -> float:
    return round(x, 6)


def lot(q: float, item: NetItem) -> float:
    out = max(q, item.min_qty or 0.0)
    m = item.order_multiple or 0.0
    if m > EPS:
        out = math.ceil(out / m - 1e-9) * m
    return _round(out)


def scale_pegs(pegs: list[NetPeg], factor: float) -> list[NetPeg]:
    return [NetPeg(p.node, p.kind, p.ref, _round(p.qty * factor), p.late_weeks) for p in pegs if p.qty * factor > EPS]


def merge_pegs(pegs: list[NetPeg]) -> list[NetPeg]:
    acc: dict[tuple[str, str, str], NetPeg] = {}
    for p in pegs:
        k = (p.node, p.kind, p.ref)
        if k in acc:
            acc[k].qty = _round(acc[k].qty + p.qty)
            acc[k].late_weeks = max(acc[k].late_weeks, p.late_weeks)
        else:
            acc[k] = NetPeg(p.node, p.kind, p.ref, _round(p.qty), p.late_weeks)
    return list(acc.values())


class _Vertex:
    __slots__ = ("node", "key", "item", "llc", "indep", "dep", "transfers", "production", "shortages", "spills",
                 "emitted", "assigned", "explanations")

    def __init__(self, node: str, key: str, item: NetItem):
        self.node, self.key, self.item = node, key, item
        self.llc = 0
        self.indep: list[Req] = []
        self.dep: dict[Any, list[Req]] = {}          # emitter -> requirements
        self.transfers: list[NetTransfer] = []         # in (this vertex is the destination)
        self.production: list[NetProduction] = []
        self.shortages: list[NetShortage] = []         # owned by this vertex's processing
        self.spills: list[tuple[NetTransfer, Any, "_Vertex"]] = []   # (cut transfer, replacement, its dest vertex)
        self.emitted: set[tuple[str, str]] = set()
        self.assigned: dict[str, float] = {}
        self.explanations: list[dict[str, Any]] = []


class Engine:
    def __init__(self, p: NetProblem):
        self.p = p
        self.weeks = horizon_weeks(p.as_of, p.horizon_weeks)
        self.w0, self.wend = self.weeks[0], self.weeks[-1]
        self.nodes = {n.id: n for n in p.nodes}
        self.cal = {n.id: NodeCalendar(n.workdays, n.holidays) for n in p.nodes}
        self.code = {n.id: n.code for n in p.nodes}
        self.items = {(i.node, i.key): i for i in p.items}
        self.lanes = [ln for ln in p.lanes if ln.active]
        self.lane_by_id = {ln.id: ln for ln in p.lanes}
        self.rules_by_dest: dict[str, list[NetRule]] = defaultdict(list)
        for r in p.rules:
            self.rules_by_dest[r.dest].append(r)
        self.bom: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
        for b in p.bom:
            self.bom[(b.node, b.parent_key)].append((b.component_key, b.qty_per))
        self.load: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
        for ld in p.load:
            if ld.hours_per_unit > 0:
                self.load[(ld.node, ld.key)].append((ld.cap_group, ld.hours_per_unit))
        for v in self.load.values():
            v.sort()
        self.cap_avail: dict[tuple[str, str, date], float] = defaultdict(float)
        self.cap_groups: set[tuple[str, str]] = set()
        for c in p.capacity:
            self.cap_avail[(c.node, c.cap_group, monday(c.week))] += c.hours
            self.cap_groups.add((c.node, c.cap_group))
        self.cap_used: dict[tuple[str, str, date], float] = defaultdict(float)
        self.bookings: dict[int, list[tuple[tuple[str, str, date], float]]] = {}   # id(production) -> bookings
        self.explanations: list[dict[str, Any]] = list(p.warnings)
        self.V: dict[tuple[str, str], _Vertex] = {}

    # ------------------------------------------------------------ rules

    def rules_of(self, node: str, key: str, week: date | None = None) -> list[NetRule]:
        item = self.items.get((node, key))
        rs = self.rules_by_dest.get(node, [])
        by_key = [r for r in rs if r.key == key]
        chosen = by_key or [r for r in rs if r.key is None and item is not None and item.family
                            and r.family == item.family]
        if week is not None:
            end = week + timedelta(days=6)
            chosen = [r for r in chosen if (r.valid_from is None or r.valid_from <= end)
                      and (r.valid_to is None or r.valid_to >= week)]
        out = sorted(chosen, key=lambda r: (r.priority, r.id))
        if any(r.quota_pct is not None for r in out):
            total = sum(r.quota_pct or 0.0 for r in out)
            if abs(total - 100.0) > 0.01:
                raise NetError("NET_QUOTA_SUM", f"The quotas for {key} at {self.code.get(node, node)} sum to "
                               f"{total:g} %, not 100 %.", {"node": node, "key": key, "sum": total})
        return out

    def lane(self, r: NetRule) -> Any:
        if r.lane_id:
            ln = self.lane_by_id.get(r.lane_id)
            if ln is not None and ln.active:
                return ln
        cands = sorted((ln for ln in self.lanes if ln.src == r.source and ln.dst == r.dest),
                       key=lambda ln: (ln.transit_days, ln.id))
        if not cands:
            raise NetError("NET_NO_LANE", f"No active lane from {self.code.get(r.source or '', r.source)} to "
                           f"{self.code.get(r.dest, r.dest)}.", {"from": r.source, "to": r.dest, "rule": r.id})
        return cands[0]

    # ------------------------------------------------------------ graph

    def build_graph(self) -> None:
        todo: list[tuple[str, str]] = []
        for (node, key) in sorted(self.items, key=lambda x: (self.code.get(x[0], x[0]), x[1])):
            if self.rules_of(node, key):
                todo.append((node, key))
        edges: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        while todo:
            vk = todo.pop()
            if vk in seen:
                continue
            seen.add(vk)
            node, key = vk
            for r in self.rules_of(node, key):
                if r.source_kind == "plant" and r.source:
                    u = (r.source, key)
                    if u not in self.items:
                        self.explanations.append({"code": "NET_ITEM_MISSING", "node": r.source, "key": key,
                                                  "detail": {"dest": node, "rule": r.id}})
                        continue
                    edges[vk].append(u)
                    todo.append(u)
            for comp, _q in self.bom.get(vk, []):
                u = (node, comp)
                if u in self.items:
                    edges[vk].append(u)
                    todo.append(u)
        for vk in seen:
            self.V[vk] = _Vertex(vk[0], vk[1], self.items[vk])
        # DFS: cycle detection with the path, then longest-path levels
        state: dict[tuple[str, str], int] = {}
        stack: list[tuple[str, str]] = []

        def dfs(v: tuple[str, str]) -> None:
            state[v] = 1
            stack.append(v)
            for u in sorted(set(edges.get(v, [])), key=lambda x: (self.code.get(x[0], x[0]), x[1])):
                if state.get(u) == 1:
                    path = stack[stack.index(u):] + [u]
                    raise NetError("NET_CYCLE", "The sourcing rules form a loop: " + " -> ".join(
                        f"{self.code.get(n, n)}/{k}" for n, k in path) + ".",
                        {"path": [{"node": n, "code": self.code.get(n, n), "key": k} for n, k in path]})
                if state.get(u) is None:
                    dfs(u)
            stack.pop()
            state[v] = 2

        import sys

        sys.setrecursionlimit(max(sys.getrecursionlimit(), 10_000))
        for v in sorted(self.V, key=lambda x: (self.code.get(x[0], x[0]), x[1])):
            if state.get(v) is None:
                dfs(v)
        # levels: Kahn on the DAG
        indeg: dict[tuple[str, str], int] = defaultdict(int)
        for v, us in edges.items():
            for u in set(us):
                indeg[u] += 1
        q = [v for v in self.V if indeg[v] == 0]
        while q:
            v = q.pop()
            for u in set(edges.get(v, [])):
                self.V[u].llc = max(self.V[u].llc, self.V[v].llc + 1)
                indeg[u] -= 1
                if indeg[u] == 0:
                    q.append(u)

    # ------------------------------------------------------------ inputs

    def load_inputs(self) -> dict[tuple[str, str], list[tuple[date, float, str]]]:
        supplies: dict[tuple[str, str], list[tuple[date, float, str]]] = defaultdict(list)
        for d in self.p.demand:
            v = self.V.get((d.node, d.key))
            if v is None or d.qty <= EPS:
                continue
            wk = max(monday(d.week), self.w0)
            if wk > self.wend:
                continue
            kind = PEG_KIND.get(d.kind, "order")
            v.indep.append(Req(wk, d.qty, RANK.get(d.kind, 1) * 10 + min(max(d.priority, 0), 9), [
                NetPeg(d.node, kind, d.ref, d.qty)], None, d.ref))
        for s in self.p.supply:
            if (s.node, s.key) in self.V and s.qty > EPS:
                supplies[(s.node, s.key)].append((max(monday(s.week), self.w0), s.qty, s.ref))
        for v in self.V.values():
            if v.item.ss > EPS:
                v.indep.append(Req(self.w0, v.item.ss, RANK["ss"] * 10, [NetPeg(v.node, "ss", f"SS:{v.key}",
                                                                                v.item.ss)], None, "~SS"))
            v.indep.sort(key=lambda r: (r.week, r.rank, r.ref))
        for k in supplies:
            supplies[k].sort()
        return supplies

    # ------------------------------------------------------------ processing

    def run(self) -> NetResult:
        self.build_graph()
        self.supplies = self.load_inputs()
        heap = [(v.llc, self.code.get(v.node, v.node), v.key) for v in self.V.values()]
        heapq.heapify(heap)
        dirty = set(self.V)
        passes: dict[tuple[str, str], int] = defaultdict(int)
        code_to_node = {self.code.get(n, n): n for n in self.nodes}
        while heap:
            llc, code, key = heapq.heappop(heap)
            vk = (code_to_node.get(code, code), key)
            if vk not in dirty:
                continue
            dirty.discard(vk)
            passes[vk] += 1
            if passes[vk] > MAX_PASSES:      # pragma: no cover - spills are finite; a guard against bugs
                raise NetError("NET_NOT_CONVERGED", "The network plan did not converge.", {"node": vk[0],
                                                                                            "key": vk[1]})
            for u in self.process(self.V[vk]):
                if u not in dirty:
                    dirty.add(u)
                    uv = self.V[u]
                    heapq.heappush(heap, (uv.llc, self.code.get(uv.node, uv.node), uv.key))
        return self.result()

    def _undo(self, v: _Vertex) -> set[tuple[str, str]]:
        touched: set[tuple[str, str]] = set()
        for _t, repl, dv in v.spills:
            if isinstance(repl, NetTransfer):
                if repl in dv.transfers:
                    dv.transfers.remove(repl)
                src = self.V.get((repl.src, repl.key))
                if src is not None and src.dep.pop(("spill", id(repl)), None) is not None:
                    touched.add((src.node, src.key))
            elif repl in dv.production:
                dv.production.remove(repl)
        v.spills = []
        for u in v.emitted:
            uv = self.V.get(u)
            if uv is not None and uv.dep.pop((v.node, v.key), None) is not None:
                touched.add(u)
        v.emitted = set()
        for pr in v.production:
            for k, h in self.bookings.pop(id(pr), []):
                self.cap_used[k] -= h
        v.transfers, v.production, v.shortages, v.assigned, v.explanations = [], [], [], {}, []
        return touched

    def _choose(self, v: _Vertex, week: date, qty: float) -> NetRule | None:
        rs = [r for r in self.rules_of(v.node, v.key, week) if r.source_kind == "supplier"
              or (r.source, v.key) in self.V]
        if not rs:
            return None
        quota = [r for r in rs if r.quota_pct is not None]
        if quota:
            total = sum(v.assigned.values())
            return max(quota, key=lambda r: ((r.quota_pct or 0) / 100.0 * (total + qty) - v.assigned.get(r.id, 0.0),
                                             -r.priority, r.id))
        return rs[0]

    def _new_receipt(self, v: _Vertex, week: date, qty: float) -> Planned | None:
        it = v.item
        node = self.nodes[v.node]
        has_rules = bool(self.rules_of(v.node, v.key))
        rule = self._choose(v, week, qty) if has_rules else None
        if has_rules and rule is None:
            v.shortages.append(NetShortage(v.node, v.key, week, qty, "NET_NO_SOURCE", {"final": True}))
            return None
        if rule is not None and rule.source_kind == "plant":
            ln = self.lane(rule)
            src_cal = self.cal[rule.source]
            ship = src_cal.back(week, ln.transit_days)
            recv = week
            if ship < self.p.as_of:
                ship = src_cal.next_working(self.p.as_of)
                recv = src_cal.forward(ship, ln.transit_days)
            t = NetTransfer(rule.source, v.node, v.key, ln.id, ship, recv, qty,
                            ship <= self.p.as_of + timedelta(days=self.p.firm_days), rule.id, [], qty)
            v.transfers.append(t)
            v.assigned[rule.id] = v.assigned.get(rule.id, 0.0) + qty
            return Planned(t, week, qty, rule=rule)
        if rule is None and node.kind == "dc":
            v.shortages.append(NetShortage(v.node, v.key, week, qty, "NET_NO_SOURCE", {"final": True}))
            return None
        kind = "buy" if (rule is not None or it.make_buy == "buy") else "make"
        due = week
        start = week - timedelta(days=it.lead_days)
        if start < self.p.as_of:
            due = self.p.as_of + timedelta(days=it.lead_days)
            due = due if due.weekday() == 0 else monday(due) + timedelta(days=7)
        groups = self.load.get((v.node, v.key), []) if kind == "make" else []
        pr = NetProduction(v.node, v.key, due, qty, kind, groups[0][0] if groups else None,
                           _round(sum(h for _g, h in groups) * qty) if groups else 0.0, None,
                           rule.supplier_code if rule is not None else None, [])
        v.production.append(pr)
        if rule is not None:
            v.assigned[rule.id] = v.assigned.get(rule.id, 0.0) + qty
        return Planned(pr, week, qty, rule=rule)

    def process(self, v: _Vertex) -> set[tuple[str, str]]:
        touched = self._undo(v)
        it = v.item
        reqs = list(v.indep)
        for rs in v.dep.values():
            reqs.extend(rs)
        reqs.sort(key=lambda r: (r.week, r.rank, r.ref))
        for r in reqs:                       # transfers this vertex supplies start uncut (cuts are re-decided)
            if isinstance(r.origin, NetTransfer):
                r.origin.qty = r.origin.requested
        pool: list[list[Any]] = [[w, q, None] for w, q, _ref in self.supplies.get((v.node, v.key), [])]
        planned: list[Planned] = []
        by_week: dict[date, Planned] = {}
        for r in reqs:
            need = r.qty
            for e in pool:
                if need <= EPS:
                    break
                if e[0] > r.week or e[1] <= EPS:
                    continue
                take = min(e[1], need)
                e[1] = _round(e[1] - take)
                need = _round(need - take)
                if e[2] is not None:
                    e[2].cons.append((r.rank, r.week, r, take))
            if need <= EPS:
                continue
            pl = by_week.get(r.week)                       # one receipt (one source decision) per week
            if pl is not None:
                used = _round(pl.qty - sum(e[1] for e in pool if e[2] is pl))
                new_qty = lot(used + need, it)
                d = _round(new_qty - pl.qty)
                pl.qty = new_qty
                pl.obj.qty = new_qty
                if isinstance(pl.obj, NetTransfer):
                    pl.obj.requested = new_qty
                if pl.rule is not None:
                    v.assigned[pl.rule.id] = v.assigned.get(pl.rule.id, 0.0) + d
                for e in pool:
                    if e[2] is pl:
                        e[1] = _round(e[1] + d)
                        break
            else:
                pl = self._new_receipt(v, r.week, lot(need, it))
                if pl is None:
                    continue
                planned.append(pl)
                by_week.setdefault(r.week, pl)
                pool.append([r.week, pl.qty, pl])
                pool.sort(key=lambda e: e[0])
            for e in pool:
                if e[2] is pl:
                    take = min(e[1], need)
                    e[1] = _round(e[1] - take)
                    pl.cons.append((r.rank, r.week, r, take))
                    need = _round(need - take)
                    break
        excess = {id(e[2]): e[1] for e in pool if e[2] is not None}
        for pl in planned:
            self._lateness(v, pl)
        # capacity (3)
        for pl in sorted((p for p in planned if isinstance(p.obj, NetProduction) and p.obj.kind == "make"),
                         key=lambda p: (min((c[0] for c in p.cons), default=99), p.week)):
            touched |= self._capacity(v, pl, excess.get(id(pl), 0.0))
        # pegs of every receipt
        for pl in planned:
            if pl.obj not in v.transfers and pl.obj not in v.production:
                continue
            pegs = [pg for _rk, _wk, r, q in pl.cons for pg in scale_pegs(r.pegs, q / r.qty if r.qty else 0)]
            rest = _round(pl.obj.qty - sum(pg.qty for pg in pegs))
            if rest > EPS:
                pegs.append(NetPeg(v.node, "ss", f"SS:{v.key}", rest))
            pl.obj.pegs = merge_pegs(pegs)
        # emission (4)
        for t in v.transfers:
            u = (t.src, t.key)
            uv = self.V.get(u)
            if uv is None:
                continue
            uv.dep.setdefault((v.node, v.key), []).append(Req(monday(t.ship_date), t.requested, min(
                (RANK.get(pg.kind, 1) * 10 for pg in t.pegs), default=10), t.pegs, t, f"T:{v.node}:{t.ship_date}"))
            v.emitted.add(u)
            touched.add(u)
        for pr in v.production:
            if pr.kind != "make":
                continue
            start = max(monday(pr.week - timedelta(days=it.lead_days)), self.w0)
            for comp, qper in self.bom.get((v.node, v.key), []):
                u = (v.node, comp)
                uv = self.V.get(u)
                if uv is None:
                    continue
                q = _round(pr.qty * qper)
                if q <= EPS:
                    continue
                uv.dep.setdefault((v.node, v.key), []).append(Req(start, q, min(
                    (RANK.get(pg.kind, 1) * 10 for pg in pr.pegs), default=10), scale_pegs(pr.pegs, qper),
                    ("bom", pr), f"B:{v.key}:{pr.week}"))
                v.emitted.add(u)
                touched.add(u)
        return touched

    def _lateness(self, v: _Vertex, pl: Planned) -> None:
        o = pl.obj
        actual = monday(o.receive_date) if isinstance(o, NetTransfer) else o.week
        if actual > pl.week:
            late = (actual - pl.week).days // 7
            covered = sum(q for _rk, _wk, r, q in pl.cons if r.rank < 20)
            if covered > EPS:
                v.shortages.append(NetShortage(v.node, v.key, pl.week, _round(covered), "NET_LEAD_TIME", {
                    "final": True, "late_weeks": late, "available": actual.isoformat()}))
            for _rk, _wk, r, _q in pl.cons:
                for pg in r.pegs:
                    pg.late_weeks = max(pg.late_weeks, late)

    # ------------------------------------------------------------ capacity

    def _fit(self, node: str, groups: list[tuple[str, float]], week: date) -> float:
        fit = math.inf
        for g, h in groups:
            if (node, g) not in self.cap_groups:
                continue
            rem = self.cap_avail.get((node, g, week), 0.0) - self.cap_used.get((node, g, week), 0.0)
            fit = min(fit, max(rem, 0.0) / h)
        return fit

    def _book(self, pr: NetProduction, groups: list[tuple[str, float]]) -> None:
        bk = []
        for g, h in groups:
            k = (pr.node, g, pr.week)
            self.cap_used[k] += h * pr.qty
            bk.append((k, h * pr.qty))
        self.bookings[id(pr)] = self.bookings.get(id(pr), []) + bk
        pr.hours = _round(sum(h for _g, h in groups) * pr.qty)

    def _capacity(self, v: _Vertex, pl: Planned, excess: float) -> set[tuple[str, str]]:
        pr: NetProduction = pl.obj
        groups = self.load.get((v.node, v.key), [])
        if not groups:
            return set()
        if not any((v.node, g) in self.cap_groups for g, _h in groups):
            self.explanations.append({"code": "NET_CAP_UNKNOWN", "node": v.node, "key": v.key,
                                      "detail": {"cap_group": groups[0][0]}})
            self._book(pr, groups)
            return set()
        if not self.p.constrained:
            self._book(pr, groups)
            return set()
        # consumptions in rank order, lot excess last
        parts: list[tuple[int, date, Req | None, float]] = sorted(
            ((rk, wk, r, q) for rk, wk, r, q in pl.cons), key=lambda c: (c[0], c[1], c[2].ref if c[2] else ""))
        if excess > EPS:
            parts.append((99, pl.week, None, excess))
        fit = self._fit(v.node, groups, pr.week)
        fit = math.floor(fit + 1e-9) if fit is not math.inf else fit
        served: list[tuple[int, date, Req | None, float]] = []
        rest: list[tuple[int, date, Req | None, float]] = []
        cap = fit
        for c in parts:
            take = min(c[3], cap)
            if take > EPS:
                served.append((c[0], c[1], c[2], take))
                cap -= take
            if c[3] - take > EPS:
                rest.append((c[0], c[1], c[2], _round(c[3] - take)))
        pr.qty = _round(sum(c[3] for c in served))
        pl.cons = [c for c in served if c[2] is not None]          # type: ignore[misc]
        if pr.qty > EPS:
            self._book(pr, groups)
        else:
            v.production.remove(pr)
        # (a) pre-build into earlier weeks with spare capacity
        for k in range(1, self.p.prebuild_weeks + 1):
            if not rest:
                break
            wk = pr.week - timedelta(days=7 * k)
            if wk < self.w0:
                break
            cap = self._fit(v.node, groups, wk)
            cap = math.floor(cap + 1e-9)
            if cap <= EPS:
                continue
            got, left = [], []
            for c in rest:
                take = min(c[3], cap)
                if take > EPS:
                    got.append((c[0], c[1], c[2], take))
                    cap -= take
                if c[3] - take > EPS:
                    left.append((c[0], c[1], c[2], _round(c[3] - take)))
            if got:
                q = _round(sum(c[3] for c in got))
                pb = NetProduction(v.node, v.key, wk, q, "make", pr.cap_group, 0.0, pr.week, None, [])
                v.production.append(pb)
                self._book(pb, groups)
                pegs = [pg for _rk, _wk, r, qq in got if r is not None for pg in scale_pegs(r.pegs, qq / r.qty)]
                rest_ex = _round(q - sum(pg.qty for pg in pegs))
                if rest_ex > EPS:
                    pegs.append(NetPeg(v.node, "ss", f"SS:{v.key}", rest_ex))
                pb.pegs = merge_pegs(pegs)
                v.explanations.append({"code": "NET_PREBUILD", "node": v.node, "key": v.key,
                                       "week": wk.isoformat(), "detail": {"for_week": pr.week.isoformat(), "qty": q}})
            rest = left
        # (b) spill / (c) cut
        touched: set[tuple[str, str]] = set()
        for rk, wk, r, q in rest:
            if r is None:
                continue                                           # lot excess is simply not built
            if isinstance(r.origin, NetTransfer):
                touched |= self._spill_or_cut(v, r, q)
            elif rk < 20:
                v.shortages.append(NetShortage(v.node, v.key, wk, q, "NET_CAPACITY_SHORT", {
                    "final": True, "cap_group": groups[0][0], "pegs": [_peg_json(p) for p in scale_pegs(
                        r.pegs, q / r.qty)][:5]}))
        return touched

    def _spill_or_cut(self, v: _Vertex, r: Req, q: float) -> set[tuple[str, str]]:
        t: NetTransfer = r.origin
        dv = self.V[(t.dst, t.key)]
        week = monday(t.receive_date)
        tried = {self._rule_source(x) for x in self._tried(t)}
        rules = [x for x in self.rules_of(t.dst, t.key, week) if self._rule_source(x) not in tried
                 and (x.source_kind == "supplier" or (x.source, t.key) in self.V)]
        pegs = scale_pegs(r.pegs, q / r.qty) if r.qty else []
        t.qty = _round(t.qty - q)
        if rules:
            nxt = sorted(rules, key=lambda x: (x.priority, x.id))[0]
            if nxt.source_kind == "plant":
                ln = self.lane(nxt)
                cal = self.cal[nxt.source]
                ship = cal.back(week, ln.transit_days)
                recv = week
                if ship < self.p.as_of:
                    ship = cal.next_working(self.p.as_of)
                    recv = cal.forward(ship, ln.transit_days)
                t2 = NetTransfer(nxt.source, t.dst, t.key, ln.id, ship, recv, q,
                                 ship <= self.p.as_of + timedelta(days=self.p.firm_days), nxt.id, merge_pegs(pegs), q,
                                 True)
                t2._tried = self._tried(t) | {t.rule_id}          # type: ignore[attr-defined]
                dv.transfers.append(t2)
                v.spills.append((t, t2, dv))
                u = (nxt.source, t.key)
                self.V[u].dep[("spill", id(t2))] = [Req(monday(ship), q, r.rank, t2.pegs, t2, f"S:{t.dst}:{ship}")]
                v.explanations.append({"code": "NET_SPILL", "node": v.node, "key": v.key,
                                       "week": week.isoformat(), "detail": {"to": nxt.source, "dest": t.dst,
                                                                            "qty": q, "quota": nxt.quota_pct
                                                                            is not None}})
                return {u}
            pr = NetProduction(t.dst, t.key, week, q, "buy", None, 0.0, None, nxt.supplier_code, merge_pegs(pegs))
            dv.production.append(pr)
            v.spills.append((t, pr, dv))
            v.explanations.append({"code": "NET_SPILL", "node": v.node, "key": v.key, "week": week.isoformat(),
                                   "detail": {"to": nxt.supplier_code, "dest": t.dst, "qty": q}})
            return set()
        v.shortages.append(NetShortage(v.node, v.key, monday(t.ship_date), q, "NET_CAPACITY_SHORT", {
            "final": False, "dest": t.dst, "pegs": [_peg_json(p) for p in pegs][:5]}))
        v.shortages.append(NetShortage(t.dst, t.key, week, q, "NET_CAPACITY_SHORT", {
            "final": True, "at": v.node, "pegs": [_peg_json(p) for p in pegs][:5]}))
        return set()

    @staticmethod
    def _tried(t: NetTransfer) -> set[str | None]:
        return set(getattr(t, "_tried", set())) | {t.rule_id}

    def _rule_source(self, rid: Any) -> Any:
        if isinstance(rid, NetRule):
            return rid.source or rid.supplier_code
        for rs in self.rules_by_dest.values():
            for x in rs:
                if x.id == rid:
                    return x.source or x.supplier_code
        return rid

    # ------------------------------------------------------------ result

    def result(self) -> NetResult:
        res = NetResult(weeks=list(self.weeks))
        for vk in sorted(self.V, key=lambda x: (self.code.get(x[0], x[0]), x[1])):
            v = self.V[vk]
            res.transfers.extend(t for t in v.transfers if t.qty > EPS)
            res.production.extend(p for p in v.production if p.qty > EPS)
            res.shortages.extend(v.shortages)
            res.explanations.extend(v.explanations)
        for t in res.transfers:
            t.qty = _round(t.qty)
            if abs(sum(p.qty for p in t.pegs) - t.qty) > 1e-4:
                _fit_pegs(t)
        for p in res.production:
            if abs(sum(x.qty for x in p.pegs) - p.qty) > 1e-4:
                _fit_pegs(p)
        res.transfers.sort(key=lambda t: (self.code.get(t.src, t.src), self.code.get(t.dst, t.dst), t.key,
                                          t.ship_date))
        res.production.sort(key=lambda p: (self.code.get(p.node, p.node), p.key, p.week))
        res.shortages.sort(key=lambda s: (self.code.get(s.node, s.node), s.key, s.week, s.cause))
        res.projection = projection(self.p, self.weeks, set(self.V), res)
        for (node, g, wk), avail in sorted(self.cap_avail.items(), key=lambda x: (self.code.get(x[0][0], ""),
                                                                                  x[0][1], x[0][2])):
            if self.w0 <= wk <= self.wend:
                res.utilisation.append(NetUtil(node, g, wk, _round(avail), _round(self.cap_used.get((node, g, wk),
                                                                                                     0.0))))
        res.explanations = self.explanations + res.explanations
        res.kpis = kpis(self.p, res, self.items)
        return res


def _peg_json(p: NetPeg) -> dict[str, Any]:
    return {"node": p.node, "kind": p.kind, "ref": p.ref, "qty": p.qty}


def _fit_pegs(o: Any) -> None:
    """After a cut the remaining quantity keeps its highest-ranked pegs (FIFO by rank)."""
    left = o.qty
    out = []
    for p in sorted(o.pegs, key=lambda p: (RANK.get(p.kind, 1), p.ref)):
        take = min(p.qty, left)
        if take > EPS:
            out.append(NetPeg(p.node, p.kind, p.ref, _round(take), p.late_weeks))
        left = _round(left - take)
    if left > EPS:
        out.append(NetPeg(o.dst if isinstance(o, NetTransfer) else o.node, "ss", f"SS:{o.key}", left))
    o.pegs = out


def projection(p: NetProblem, wks: list[date], vertices: set[tuple[str, str]], res: NetResult
               ) -> list[NetProjection]:
    w0, wend = wks[0], wks[-1]
    items = {(i.node, i.key): i for i in p.items}

    def wk(d: date) -> date | None:
        m = max(monday(d), w0)
        return m if m <= wend else None

    acc: dict[tuple[str, str, date], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for d in p.demand:
        if (d.node, d.key) in vertices and (w := wk(d.week)) is not None:
            acc[(d.node, d.key, w)][0] += d.qty
    for s in p.supply:
        if (s.node, s.key) in vertices and (w := wk(s.week)) is not None:
            acc[(s.node, s.key, w)][1] += s.qty
    bom: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for b in p.bom:
        bom[(b.node, b.parent_key)].append((b.component_key, b.qty_per))
    for t in res.transfers:
        if (w := wk(t.receive_date)) is not None:
            acc[(t.dst, t.key, w)][2] += t.qty
        if (t.src, t.key) in vertices and (w := wk(t.ship_date)) is not None:
            acc[(t.src, t.key, w)][3] += t.qty
    for pr in res.production:
        if (w := wk(pr.week)) is not None:
            acc[(pr.node, pr.key, w)][2] += pr.qty
        if pr.kind == "make":
            it = items.get((pr.node, pr.key))
            start = wk(pr.week - timedelta(days=it.lead_days if it else 0)) or w0
            for comp, q in bom.get((pr.node, pr.key), []):
                if (pr.node, comp) in vertices:
                    acc[(pr.node, comp, start)][0] += pr.qty * q
    out = []
    for node, key in sorted(vertices):
        it = items[(node, key)]
        proj = 0.0
        for w in wks:
            g, r, pi, po = acc.get((node, key, w), (0.0, 0.0, 0.0, 0.0))
            proj = proj + r + pi - g - po
            out.append(NetProjection(node, key, w, _round(g), _round(r), _round(pi), _round(po), _round(proj),
                                     it.ss))
    return out


def kpis(p: NetProblem, res: NetResult, items: dict[tuple[str, str], NetItem]) -> dict[str, Any]:
    vert = {(x.node, x.key) for x in res.projection}
    w0, wend = res.weeks[0], res.weeks[-1]
    indep = sum(d.qty for d in p.demand if (d.node, d.key) in vert and d.kind in ("order", "forecast")
                and monday(d.week) <= wend)
    short = sum(s.qty for s in res.shortages if s.detail.get("final") and s.cause != "NET_LEAD_TIME")
    inv: dict[tuple[str, str], list[float]] = defaultdict(list)
    for x in res.projection:
        inv[(x.node, x.key)].append(max(x.projected, 0.0))
    value = sum((sum(v) / len(v)) * (items[k].std_cost or 0.0) for k, v in inv.items() if v)
    util = [u.used / u.available for u in res.utilisation if u.available > EPS]
    return {"fill_rate": round(1 - short / indep, 6) if indep > EPS else None, "shortage_units": _round(short),
            "inventory_value": round(value, 2), "transfer_units": _round(sum(t.qty for t in res.transfers)),
            "currency": p.currency, "nodes": len({n for n, _k in vert}), "keys": len({k for _n, k in vert}),
            "transfers": len(res.transfers), "firm_transfers": sum(1 for t in res.transfers if t.firm),
            "shortages": len(res.shortages), "max_utilisation": round(max(util), 4) if util else None}


def solve(p: NetProblem) -> NetResult:
    """Plan the network; the caller runs `validator.validate` on the result (N3)."""
    return Engine(p).run()
