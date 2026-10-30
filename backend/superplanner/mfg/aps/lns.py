"""Improvement by large neighbourhood search with CP-SAT (M3-DESIGN 7.2).

Neighbourhoods, in a deterministic order: (a) each bottleneck group (the three most utilised) x consecutive 2-day
windows, (b) the operations of the 10 most tardy orders' chains within one week. For one neighbourhood a CP-SAT model
re-decides line assignment and sequence of its operations: optional intervals per eligible line, cumulative
capacity per line with the rest of the plan as fixed boundary intervals, sequence-dependent setups on circuit arcs
(single-slot lines), release times from the fixed rest, weighted tardiness of the orders' last operations and setup
minutes in the objective. The model works on an elapsed-minute axis with each operation's elapsed length taken from
its current placement (stretched by its current elapsed/working ratio on another line); the exact calendar is applied
by the decoder: the CP-SAT sequence becomes construction hints (forced line + predecessor on the line) and the whole
plan is rebuilt by the priority construction. A result is accepted only if the objective tuple (7.3) improves and the
independent validator stays clean. CP-SAT: one worker, fixed seed, `max_deterministic_time` per neighbourhood; the
total deterministic budget is `improve_seconds`, with a wall-clock cap of 2 x the budget.
"""

from __future__ import annotations

import time
from typing import Any

from ortools.sat.python import cp_model

from .build import Model
from .construct import Schedule, construct

WINDOW = 2 * 1440
CHAIN_WINDOW = 7 * 1440
MAX_OPS = 40
PER_NEIGHBOURHOOD = 2.0
#: deterministic cost charged per decode (one reconstruction + validation): keeps the budget machine-independent
DECODE_COST = 1.0
SEED = 20261030


def _better(a: list[float], b: list[float]) -> bool:
    """a strictly better than b (lexicographic, smaller is better; tiny float noise ignored)."""
    for x, y in zip(a, b):
        if x < y - 1e-6:
            return True
        if x > y + 1e-6:
            return False
    return False


def _util(m: Model, sc: Schedule) -> dict[str, float]:
    used: dict[str, float] = {}
    base: dict[str, float] = {}
    H = m.horizon
    for ln in m.lines.values():
        base[ln.group_id] = base.get(ln.group_id, 0.0) + ln.capacity * sum(
            max(0, min(e, H) - s) for s, e in ln.base if s < H)
    for ps in sc.placed.values():
        for p in ps:
            g = m.lines[p.line_id].group_id
            used[g] = used.get(g, 0.0) + sum(max(0, min(b, H) - a) for a, b in p.pieces if a < H)
    return {g: used.get(g, 0.0) / base[g] for g in base if base[g] > 0}


def neighbourhoods(m: Model, sc: Schedule) -> list[tuple[str, list[tuple[str, int]]]]:
    from .engine import order_ends

    util = _util(m, sc)
    groups = sorted(util, key=lambda g: (-util[g], g))[:3]
    out: list[tuple[str, list[tuple[str, int]]]] = []
    for g in groups:
        lines = {lid for lid, ln in m.lines.items() if ln.group_id == g}
        cand = [(p.start, k) for k, ps in sc.placed.items() for p in ps
                if p.line_id in lines and len(ps) == 1 and p.fixed is None]
        if len(cand) < 2:
            continue
        lo = min(s for s, _ in cand)
        hi = max(s for s, _ in cand)
        w = (lo // WINDOW) * WINDOW
        while w <= hi:
            ks = sorted({k for s, k in cand if w <= s < w + WINDOW}, key=lambda k: (m.orders[k[0]].rank, k))
            if len(ks) >= 2:
                out.append((f"group:{g}:{w}", ks[:MAX_OPS]))
            w += WINDOW
    ends = order_ends(m, sc)
    tardy = sorted((o for o in m.orders.values() if o.due is not None and ends[o.key][1] is not None and
                    ends[o.key][1] > o.due), key=lambda o: (-(ends[o.key][1] - o.due) * o.weight, o.number))[:10]
    for o in tardy:
        mine = [op.key for op in o.ops if op.key in sc.placed and len(sc.placed[op.key]) == 1 and
                sc.placed[op.key][0].fixed is None]
        if not mine:
            continue
        last_end = ends[o.key][1] or 0
        lines = {sc.placed[k][0].line_id for k in mine}
        others = [k for k, ps in sc.placed.items() if k not in mine and len(ps) == 1 and ps[0].fixed is None and
                  ps[0].line_id in lines and last_end - CHAIN_WINDOW <= ps[0].start < last_end]
        ks = sorted(set(mine) | set(others), key=lambda k: (m.orders[k[0]].rank, k))[:MAX_OPS]
        if len(ks) >= 2:
            out.append((f"chain:{o.key}", ks))
    return out


def solve(m: Model, sc: Schedule, keys: list[tuple[str, int]], max_time: float
          ) -> tuple[dict[tuple[str, int], tuple[str, tuple[str, int] | None]] | None, float]:
    """CP-SAT on one neighbourhood -> hints (line, predecessor on the line) or None; deterministic time used."""
    ops = {op.key: op for op in m.ops}
    keyset = set(keys)
    pl = {k: sc.placed[k][0] for k in keys}
    w0 = min(p.start for p in pl.values())
    lines = sorted({lid for k in keys for lid in ops[k].lines if m.lines[lid].group_id ==
                    m.lines[pl[k].line_id].group_id})
    horizon = max(p.end for p in pl.values()) - w0 + 3 * 1440
    md = cp_model.CpModel()
    starts: dict[tuple[str, int], Any] = {}
    ends: dict[tuple[str, int], Any] = {}
    pres: dict[tuple[tuple[str, int], str], Any] = {}
    ivs: dict[str, list[Any]] = {lid: [] for lid in lines}
    from .durations import run_minutes, setup_minutes

    for k in keys:
        op, p = ops[k], pl[k]
        rel = sc.release.get(k, {})
        r = max(rel.get("material_at") or 0, rel.get("predecessor_at") or 0, 0) - w0
        r = max(0, r)
        span = p.end - p.start
        work = max(1, p.setup + p.run)
        ratio = span / work
        s = md.NewIntVar(r, horizon, f"s{op.no}")
        e = md.NewIntVar(0, horizon + 10 * 1440, f"e{op.no}")
        starts[k], ends[k] = s, e
        lits = []
        for lid in op.lines:
            if lid not in ivs:
                continue
            ln = m.lines[lid]
            run = run_minutes(op.rec, ln, m.rates.get((op.rec.id, lid)), p.qty)
            dur = max(1, int(round((run if ln.capacity == 1 else run + p.setup) * ratio)))
            x = md.NewBoolVar(f"x{op.no}_{ln.code}")
            iv = md.NewOptionalIntervalVar(s, dur, e, x, f"i{op.no}_{ln.code}")
            ivs[lid].append((iv, k, x))
            pres[(k, lid)] = x
            lits.append(x)
        md.AddExactlyOne(lits)
    # boundary: other placements on these lines near the window
    fixed_iv: dict[str, list[Any]] = {lid: [] for lid in lines}
    for k2, ps in sc.placed.items():
        if k2 in keyset:
            continue
        for p in ps:
            if p.line_id in fixed_iv and p.end > w0 and p.start < w0 + horizon:
                a, b = max(0, p.start - w0), max(1, min(horizon, p.end - w0))
                if b > a:
                    fixed_iv[p.line_id].append(md.NewIntervalVar(a, b - a, b, f"f{p.op.no}_{p.part}"))
    setup_cost = []
    for lid in lines:
        ln = m.lines[lid]
        items = ivs[lid]
        if not items:
            continue
        all_iv = [iv for iv, _k, _x in items] + fixed_iv[lid]
        if ln.capacity == 1:
            md.AddNoOverlap(all_iv)
            # circuit with node 0 = boundary predecessor (last operation before the window on this line)
            prev_b = None
            for k2, ps in sc.placed.items():
                for p in ps:
                    if p.line_id == lid and k2 not in keyset and p.end <= w0:
                        if prev_b is None or p.end > prev_b.end:
                            prev_b = p
            arcs = []
            n = len(items)
            for i, (_iv, ki, xi) in enumerate(items, 1):
                arcs.append((i, i, xi.Not()))
                oi = ops[ki]
                lit0 = md.NewBoolVar("")
                arcs.append((0, i, lit0))
                st0 = setup_minutes(oi.rec, ln, m.rates.get((oi.rec.id, lid)), m.matrix,
                                    prev_b.op.family if prev_b else None, oi.family)
                md.Add(starts[ki] >= (max(0, prev_b.end - w0) if prev_b else 0) + st0).OnlyEnforceIf(lit0)
                setup_cost.append(st0 * lit0)
                litN = md.NewBoolVar("")
                arcs.append((i, 0, litN))
                for j, (_iv2, kj, xj) in enumerate(items, 1):
                    if i == j:
                        continue
                    oj = ops[kj]
                    lit = md.NewBoolVar("")
                    arcs.append((i, j, lit))
                    st = setup_minutes(oj.rec, ln, m.rates.get((oj.rec.id, lid)), m.matrix, oi.family, oj.family,
                                       continuation=oi.key == oj.key)
                    md.Add(starts[kj] >= ends[ki] + st).OnlyEnforceIf(lit)
                    setup_cost.append(st * lit)
            if n >= 1:
                md.AddCircuit(arcs)
        else:
            md.AddCumulative(all_iv, [1] * len(all_iv), ln.capacity)
    # precedence inside the neighbourhood (same order)
    for k in keys:
        op = ops[k]
        if op.idx > 0:
            pk = op.order.ops[op.idx - 1].key
            if pk in keyset:
                md.Add(starts[k] >= ends[pk] + op.gap_before)
    tard = []
    for k in keys:
        op = ops[k]
        o = op.order
        if o.due is None:
            continue
        last_here = max((x for x in o.ops if x.key in keyset), key=lambda x: x.idx)
        if last_here.key != k:
            continue
        tail = sum(x.min_duration for x in o.ops[op.idx + 1:])
        due = o.due - w0 - tail
        t = md.NewIntVar(0, horizon + 10 * 1440, f"t{op.no}")
        md.Add(t >= ends[k] - due)
        tard.append(int(o.weight) * t)
    mk = md.NewIntVar(0, horizon + 10 * 1440, "mk")
    for k in keys:
        md.Add(mk >= ends[k])
    md.Minimize(1000 * sum(tard) + 10 * sum(setup_cost) + mk)
    sol = cp_model.CpSolver()
    sol.parameters.num_workers = 1
    sol.parameters.random_seed = SEED
    sol.parameters.max_deterministic_time = max_time
    sol.parameters.max_time_in_seconds = max(30.0, 20 * max_time)   # safety only: the deterministic limit binds
    st_ = sol.Solve(md)
    used = sol.deterministic_time
    if st_ not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, used
    hints: dict[tuple[str, int], tuple[str, tuple[str, int] | None]] = {}
    for lid in lines:
        seq = sorted(((sol.Value(starts[k]), ops[k].no, k) for _iv, k, x in ivs[lid] if sol.Value(x)))
        prev = None
        for _s, _n, k in seq:
            hints[k] = (lid, prev)
            prev = k
    return hints, used


def improve(m: Model, sc: Schedule, policy: str, hints: Any, budget: int, progress: Any, cancelled: Any, *,
            wall_cap: float | None = None) -> tuple[Schedule, list[float], int, int, float, bool]:
    from .engine import score

    best = sc
    best_score = score(m, sc)
    base_hints = dict(hints or {})
    cur_hints = dict(base_hints)
    used = 0.0
    it = acc = 0
    cut = False
    t0 = time.monotonic()
    cap = wall_cap if wall_cap is not None else 2.0 * budget
    tried: set[str] = set()
    rounds = 0
    while used < budget and rounds < 3:
        rounds += 1
        improved_round = False
        for name, keys in neighbourhoods(m, best):
            if used >= budget:
                break
            if time.monotonic() - t0 > cap:
                cut = True
                break
            if cancelled is not None and cancelled():
                break
            sig = f"{name}:{','.join(f'{a}/{b}' for a, b in keys)}"
            if sig in tried:
                continue
            tried.add(sig)
            it += 1
            h, du = solve(m, best, keys, min(PER_NEIGHBOURHOOD, budget - used))
            used += du
            if not h:
                continue
            trial_hints = {**cur_hints, **h}
            if all(cur_hints.get(k) == v for k, v in h.items()):
                continue
            used += DECODE_COST
            cand = construct(m, policy, trial_hints)
            s = score(m, cand)
            if _better(s, best_score) and _clean(m, cand, policy):
                best, best_score, cur_hints = cand, s, trial_hints
                acc += 1
                improved_round = True
                if progress:
                    progress("improve", 30.0 + 60.0 * min(1.0, used / max(budget, 1)), best_score)
        if cut or not improved_round:
            break
    return best, best_score, it, acc, used, cut


def _clean(m: Model, sc: Schedule, policy: str) -> bool:
    """The candidate passes the independent validator (S1)."""
    from .engine import assemble
    from .validator import validate

    snap = getattr(m, "snapshot", None)
    if snap is None:
        return True
    res = assemble(snap, m.params, m, sc, policy, [], 0, 0, 0.0, False)
    return validate(snap, res).ok


__all__ = ["improve", "neighbourhoods", "solve"]
