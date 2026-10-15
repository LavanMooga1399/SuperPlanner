"""Dependency graph analysis: cycles, topological order, CPM (ARCHITECTURE section 9.2)."""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel

from .compiled import CompiledProblem, kahn_order


class CycleError(ValueError):
    pass


class CpmTask(BaseModel):
    es: int
    ef: int
    ls: int
    lf: int
    slack: int
    critical: bool


class CpmResult(BaseModel):
    lower_bound_makespan_minutes: int
    tasks: dict[str, CpmTask]
    critical_path: list[str]


def find_cycles(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    """Tarjan SCC (iterative); for every SCC of size > 1 return one simple cycle in order."""
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
    index = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    sccs: list[list[int]] = []
    counter = 0
    for root in range(n):
        if index[root] != -1:
            continue
        work = [(root, 0)]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            v, i = work[-1]
            if i < len(adj[v]):
                work[-1] = (v, i + 1)
                w = adj[v][i]
                if index[w] == -1:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack[w] = True
                    work.append((w, 0))
                elif on_stack[w]:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        sccs.append(comp)
    cycles: list[list[int]] = []
    for comp in sccs:
        members = set(comp)
        start = min(comp)
        # BFS inside the SCC from start back to start gives a shortest simple cycle.
        parent: dict[int, int] = {}
        frontier = [start]
        found = None
        seen = {start}
        while frontier and found is None:
            nxt = []
            for v in frontier:
                for w in sorted(adj[v]):
                    if w not in members:
                        continue
                    if w == start:
                        found = v
                        break
                    if w not in seen:
                        seen.add(w)
                        parent[w] = v
                        nxt.append(w)
                if found is not None:
                    break
            frontier = nxt
        if found is None:
            continue
        path = [found]
        while path[-1] != start:
            path.append(parent[path[-1]])
        path.reverse()
        cycles.append(path)
    cycles.sort(key=lambda c: c[0])
    return cycles


def topological_order(n: int, edges: list[tuple[int, int]]) -> list[int]:
    order = kahn_order(n, edges)
    if order is None:
        raise CycleError("dependency graph contains a cycle")
    return order


def dep_lower_bound(dtype: str, lag: int, pred_start: int, pred_end: int, succ_duration: int) -> int:
    """Lower bound on the successor start given its predecessor (section 5.3)."""
    if dtype == "FS":
        return pred_end + lag
    if dtype == "SS":
        return pred_start + lag
    if dtype == "FF":
        return pred_end + lag - succ_duration
    return pred_start + lag - succ_duration  # SF


def cpm_core(durations: Sequence[int], releases: Sequence[int], locked: Sequence[int | None],
             deps: Sequence[tuple[int, int, str, int]], order: Sequence[int]):
    """Forward/backward pass. Returns (es, ef, ls, lf, project_end, binding_preds)."""
    n = len(durations)
    preds: list[list[tuple[int, str, int]]] = [[] for _ in range(n)]
    succs: list[list[tuple[int, str, int]]] = [[] for _ in range(n)]
    for a, b, t, lag in deps:
        preds[b].append((a, t, lag))
        succs[a].append((b, t, lag))
    es = [0] * n
    ef = [0] * n
    for v in order:
        d = durations[v]
        if locked[v] is not None:
            es[v] = locked[v]  # type: ignore[assignment]
        else:
            lb = max(releases[v], 0)
            for a, t, lag in preds[v]:
                lb = max(lb, dep_lower_bound(t, lag, es[a], ef[a], d))
            es[v] = lb
        ef[v] = es[v] + d
    pe = max(ef) if n else 0
    lf = [pe] * n
    ls = [0] * n
    for v in reversed(order):
        d = durations[v]
        if locked[v] is not None:
            ls[v] = es[v]
            lf[v] = ef[v]
            continue
        bound = pe
        for b, t, lag in succs[v]:
            if t == "FS":
                bound = min(bound, ls[b] - lag)
            elif t == "SS":
                bound = min(bound, ls[b] - lag + d)
            elif t == "FF":
                bound = min(bound, lf[b] - lag)
            else:
                bound = min(bound, lf[b] - lag + d)
        lf[v] = bound
        ls[v] = bound - d
    return es, ef, ls, lf, pe, preds


def _critical_path(es, ef, pe, preds, durations, ids) -> list[str]:
    n = len(es)
    if n == 0:
        return []
    end_tasks = [i for i in range(n) if ef[i] == pe]
    cur = min(end_tasks)
    chain = [cur]
    seen = {cur}
    while True:
        nxt = None
        for a, t, lag in preds[cur]:
            if dep_lower_bound(t, lag, es[a], ef[a], durations[cur]) == es[cur] and a not in seen:
                nxt = a if nxt is None else min(nxt, a)
        if nxt is None:
            break
        chain.append(nxt)
        seen.add(nxt)
        cur = nxt
    chain.reverse()
    return [ids[i] for i in chain]


def cpm(problem: CompiledProblem) -> CpmResult:
    tasks = problem.tasks
    durations = [t.duration for t in tasks]
    releases = [t.release for t in tasks]
    locked = [t.locked_start for t in tasks]
    deps = [(d.pred, d.succ, d.type, d.lag) for d in problem.deps]
    es, ef, ls, lf, pe, preds = cpm_core(durations, releases, locked, deps, problem.topo_order)
    ids = [t.id for t in tasks]
    out = {}
    for i, t in enumerate(tasks):
        slack = max(0, ls[i] - es[i])
        out[t.id] = CpmTask(es=es[i], ef=ef[i], ls=ls[i], lf=lf[i], slack=slack, critical=slack == 0)
    return CpmResult(lower_bound_makespan_minutes=pe, tasks=out,
                     critical_path=_critical_path(es, ef, pe, preds, durations, ids))
