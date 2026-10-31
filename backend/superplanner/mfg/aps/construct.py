"""Priority-driven construction (M3-DESIGN 7.1).

Serial schedule generation: an operation is *ready* when its predecessor in the order and its material providers
(child orders) are placed; among ready operations the one with the smallest `(order rank, slack, order number, seq)`
is placed next. For the chosen operation every eligible line is evaluated for its earliest feasible placement -
insertion into an idle gap is allowed if it delays nobody (the successor's setup must stay the same) - including the
setup from the preceding operation on that slot, crew and tool availability and the open windows; the minimum end
wins, ties by smaller setup, then line code. Lot splitting and overtime opening per 7.1 / 6.8.

Crew: attended time (the setup always, the run unless `labor == unattended`) needs `crew_size` distinct qualified
operators at every minute; the crew may change at shift boundaries (crew slots are finer than pieces). The
placement walks "effective windows" = line windows intersected with the times when enough qualified operators are
free, so an interruptible operation pauses while nobody qualified is on shift.
"""

from __future__ import annotations

import heapq
import math
from bisect import bisect_left, bisect_right, insort
from dataclasses import dataclass, field
from typing import Any

from ..calendar import subtract as isub
from ..calendar import union as iunion
from .build import Fixed, LineRes, Model, Op, open_windows, window_at
from .durations import run_minutes as _run
from .durations import setup_minutes as _setup

Interval = tuple[int, int]
MAX_TRIES = 400


@dataclass
class Placed:
    op: Op
    part: int
    parts: int
    qty: float
    line_id: str
    slot: int
    start: int
    end: int
    setup: int
    run: int
    pieces: list[Interval]
    crew: list[tuple[str, int, int]]
    tools: tuple[tuple[str, int], ...]
    reason: str
    reason_refs: list[dict[str, Any]]
    prev_family: str | None
    fixed: str | None = None          # frozen | in_progress | locked | edit
    opened: tuple[str, ...] = ()      # optional instances this placement opened


@dataclass
class Unsched:
    op: Op
    reason: str
    text: str
    refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Schedule:
    placed: dict[tuple[str, int], list[Placed]]       # op key -> parts
    unscheduled: dict[tuple[str, int], Unsched]
    opened: dict[str, str]                            # optional instance key -> opened | forced
    release: dict[tuple[str, int], dict[str, Any]]    # op key -> {material_at, predecessor_at, refs}
    events: list[dict[str, Any]]                      # exceptions found during construction
    order_seq: list[tuple[str, int]]                  # placement order


class EditInfeasible(Exception):
    def __init__(self, op: Op, code: str, message: str):
        super().__init__(message)
        self.op, self.code, self.message = op, code, message


class Slot:
    __slots__ = ("starts", "items")

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.items: list[Placed] = []

    def add(self, p: Placed) -> None:
        i = bisect_right(self.starts, p.start)
        self.starts.insert(i, p.start)
        self.items.insert(i, p)

    def remove(self, p: Placed) -> None:
        i = self.items.index(p)
        del self.starts[i]
        del self.items[i]

    def around(self, t: int) -> tuple[Placed | None, Placed | None, Placed | None]:
        """(booking covering t, last booking ending <= t, first booking starting > t)."""
        i = bisect_right(self.starts, t) - 1
        cover = prev = None
        if i >= 0:
            b = self.items[i]
            if b.end > t:
                cover = b
                prev = self.items[i - 1] if i >= 1 else None
            else:
                prev = b
        nxt = self.items[i + 1] if i + 1 < len(self.items) else None
        return cover, prev, nxt


class Busy:
    """Sorted, merged busy intervals of one operator; `free(a, b)`."""
    __slots__ = ("iv",)

    def __init__(self) -> None:
        self.iv: list[Interval] = []

    def add(self, a: int, b: int) -> None:
        self.iv = iunion(self.iv + [(a, b)])

    def remove(self, a: int, b: int) -> None:
        self.iv = isub(self.iv, [(a, b)])

    def free(self, a: int, b: int) -> bool:
        i = bisect_left(self.iv, (b, -1))
        j = i - 1
        while j >= 0:
            s, e = self.iv[j]
            if e <= a:
                return True
            if s < b and a < e:
                return False
            j -= 1
        return True


class State:
    def __init__(self, m: Model, policy: str):
        self.m = m
        self.policy = policy
        self.opened: dict[str, str] = {k: "forced" for k in m.forced_open}
        self.week_used: dict[tuple[str, tuple[int, int]], float] = {}
        for ln in m.lines.values():
            for x in ln.optional:
                if x.key in self.opened:
                    self._count(x, +1)
        self.windows: dict[str, list[Interval]] = {lid: open_windows(ln, set(self.opened)) for lid, ln in
                                                   m.lines.items()}
        self.slots: dict[str, list[Slot]] = {lid: [Slot() for _ in range(ln.capacity)] for lid, ln in m.lines.items()}
        self.busy: dict[str, Busy] = {e: Busy() for e in m.operators}
        self.tool_use: dict[str, list[tuple[int, int, int]]] = {t: [] for t in m.tools}
        self.qualified: dict[str | None, list[str]] = {}
        self.instances = {x.key: x for ln in m.lines.values() for x in ln.optional}

    def _count(self, x: Any, sign: int) -> None:
        k = (x.assignment_id, x.week)
        self.week_used[k] = self.week_used.get(k, 0.0) + sign * x.minutes

    def quals(self, skill: str | None) -> list[str]:
        q = self.qualified.get(skill)
        if q is None:
            q = self.qualified[skill] = [e.id for e in sorted(self.m.operators.values(), key=lambda x: x.code)
                                         if skill is None or skill in e.skills]
        return q

    def open_instance(self, key: str) -> None:
        if key in self.opened:
            return
        x = self.instances[key]
        self.opened[key] = "opened"
        self._count(x, +1)
        ln = self.m.lines[x.line_id]
        self.windows[ln.id] = open_windows(ln, set(self.opened))

    def close_instance(self, key: str) -> None:
        if self.opened.get(key) != "opened":
            return
        x = self.instances[key]
        del self.opened[key]
        self._count(x, -1)
        ln = self.m.lines[x.line_id]
        self.windows[ln.id] = open_windows(ln, set(self.opened))


# ---------------------------------------------------------------- geometry

def walk(windows: list[Interval], t: int, minutes: int, continuous: bool) -> list[Interval] | None:
    """Pieces consuming `minutes` of open time from t (None: does not fit / no window). `continuous`: one window."""
    if minutes <= 0:
        i = window_at(windows, t)
        if i >= len(windows):
            return None
        s = max(t, windows[i][0])
        return [(s, s)]
    i = window_at(windows, t)
    out: list[Interval] = []
    left = minutes
    while i < len(windows) and left > 0:
        s, e = windows[i]
        s = max(s, t)
        if continuous:
            if e - s >= left:
                return [(s, s + left)]
            return None
        take = min(left, e - s)
        if take > 0:
            if out and out[-1][1] == s:
                out[-1] = (out[-1][0], s + take)
            else:
                out.append((s, s + take))
            left -= take
        i += 1
        t = e
    return out if left <= 0 else None


def intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        s = max(a[i][0], b[j][0])
        e = min(a[i][1], b[j][1])
        if s < e:
            out.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def clip(iv: list[Interval], lo: int, hi: int) -> list[Interval]:
    i = bisect_right(iv, (lo, 1 << 60)) - 1
    out = []
    for s, e in iv[max(i, 0):]:
        if s >= hi:
            break
        if e > lo:
            out.append((max(s, lo), min(e, hi)))
    return out


# ---------------------------------------------------------------- the engine

class Engine:
    def __init__(self, m: Model, policy: str, hints: dict[tuple[str, int], tuple[str, tuple[str, int] | None]]
                 | None = None, split: bool | None = None):
        self.m = m
        self.st = State(m, policy)
        self.allow = policy == "allow"
        self.split = m.params.split if split is None else split
        self.hints = hints or {}
        self.placed: dict[tuple[str, int], list[Placed]] = {}
        self.uns: dict[tuple[str, int], Unsched] = {}
        self.release: dict[tuple[str, int], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.order_seq: list[tuple[str, int]] = []
        self.ops = {op.key: op for op in m.ops}
        self.cw_cache: dict[tuple[str | None, int], tuple[int, int, int, list[Interval]]] = {}
        self.busy_version = 0
        self.free: dict[str, list[Interval]] = {}

    # ------------------------------------------------------------ crew
    def crew_windows(self, op: Op, lo: int, hi: int) -> list[Interval]:
        """Times in [lo, hi) with >= crew_size qualified operators available and free (cached per skill and crew
        size until an operator booking changes)."""
        k = op.crew_size
        if k <= 0:
            return [(lo, hi)]
        key = (op.skill_id, k)
        c = self.cw_cache.get(key)
        if c is not None and c[0] == self.busy_version and c[1] <= lo and hi <= c[2]:
            return clip(c[3], lo, hi)
        wide_hi = hi
        out = self._crew_windows(op, lo, wide_hi)
        self.cw_cache[key] = (self.busy_version, lo, wide_hi, out)
        return clip(out, lo, hi)

    def _crew_windows(self, op: Op, lo: int, hi: int) -> list[Interval]:
        k = op.crew_size
        ev: list[tuple[int, int]] = []
        for e in self.st.quals(op.skill_id):
            for s, t in clip(self.free_of(e), lo, hi):
                ev.append((s, 1))
                ev.append((t, -1))
        if not ev:
            return []
        ev.sort()
        out: list[Interval] = []
        n = 0
        cur = None
        for t, d in ev:
            n += d
            if n >= k and cur is None:
                cur = t
            elif n < k and cur is not None:
                if t > cur:
                    out.append((cur, t))
                cur = None
        return iunion(out)

    def free_of(self, e: str) -> list[Interval]:
        """Availability minus bookings of one operator, maintained incrementally."""
        f = self.free.get(e)
        if f is None:
            f = self.free[e] = isub(self.m.operators[e].avail, self.st.busy[e].iv)
        return f

    def assign_crew(self, op: Op, segs: list[Interval]) -> list[tuple[str, int, int]] | None:
        k = op.crew_size
        if k <= 0 or not segs:
            return []
        quals = self.st.quals(op.skill_id)
        out: list[tuple[str, int, int]] = []
        last: list[str] = []
        for a, b in segs:
            pts = {a, b}
            for e in quals:
                for s, t in clip(self.m.operators[e].avail, a, b):
                    pts.add(s)
                    pts.add(t)
                for s, t in clip(self.st.busy[e].iv, a, b):
                    pts.add(s)
                    pts.add(t)
            cuts = sorted(p for p in pts if a <= p <= b)
            for x, y in zip(cuts, cuts[1:]):
                if y <= x:
                    continue
                ok = [e for e in quals if self._avail(e, x, y) and self.st.busy[e].free(x, y)]
                if len(ok) < k:
                    return None
                pick = [e for e in last if e in ok][:k]
                pick += [e for e in ok if e not in pick][:k - len(pick)]
                for e in pick:
                    if out and out[-1][0] == e and out[-1][2] == x:
                        out[-1] = (e, out[-1][1], y)
                    else:
                        j = next((i for i in range(len(out) - 1, -1, -1) if out[i][0] == e and out[i][2] == x), None)
                        if j is not None:
                            out[j] = (e, out[j][1], y)
                        else:
                            out.append((e, x, y))
                last = pick
        out.sort(key=lambda c: (c[1], c[0]))
        return out

    def _avail(self, e: str, a: int, b: int) -> bool:
        iv = self.m.operators[e].avail
        i = bisect_right(iv, (a, 1 << 60)) - 1
        return i >= 0 and iv[i][0] <= a and iv[i][1] >= b

    # ------------------------------------------------------------ tools
    def tools_ok(self, op: Op, a: int, b: int) -> int | None:
        """None if the tools are available over [a, b), else the earliest time something is released."""
        nxt = None
        for pool, q in op.tools:
            cap = self.m.tools.get(pool, 0)
            if q > cap:
                return -1
            use = [(s, e, n) for s, e, n in self.st.tool_use[pool] if s < b and a < e]
            if not use:
                continue
            pts = sorted({a} | {s for s, _, _ in use if s > a})
            for t in pts:
                tot = sum(n for s, e, n in use if s <= t < e)
                if tot + q > cap:
                    ends = [e for s, e, n in use if s <= t < e]
                    c = min(ends)
                    nxt = c if nxt is None else min(nxt, c)
                    break
        return nxt

    # ------------------------------------------------------------ durations
    def setup_on(self, op: Op, ln: LineRes, prev: Placed | None) -> int:
        cont = prev is not None and prev.op.key == op.key
        pf = prev.op.family if prev is not None else None
        return _setup(op.rec, ln, self.m.rates.get((op.rec.id, ln.id)), self.m.matrix, pf, op.family,
                      continuation=cont)

    def run_on(self, op: Op, ln: LineRes, qty: float) -> int:
        return _run(op.rec, ln, self.m.rates.get((op.rec.id, ln.id)), qty)

    # ------------------------------------------------------------ one line
    def place_on_line(self, op: Op, qty: float, ln: LineRes, t0: int, min_end: int, extra: set[str] | None
                      ) -> tuple[Placed, str] | tuple[None, str]:
        windows = self.st.windows[ln.id]
        if extra:
            windows = open_windows(ln, set(self.st.opened) | extra)
        best: Placed | None = None
        why = "no_window"
        run = self.run_on(op, ln, qty)
        for si, slot in enumerate(self.st.slots[ln.id]):
            p, w = self._place_slot(op, qty, ln, si, slot, windows, t0, min_end, run)
            if p is None:
                if why == "no_window":
                    why = w
                continue
            if best is None or (p.end, p.setup) < (best.end, best.setup):
                best = p
        return (best, "") if best is not None else (None, why)

    def _place_slot(self, op: Op, qty: float, ln: LineRes, si: int, slot: Slot, windows: list[Interval], t0: int,
                    min_end: int, run: int) -> tuple[Placed | None, str]:
        t = t0
        reason = ""
        hi = self.m.window_end
        cont = not op.interruptible
        needs_crew = op.crew_size > 0
        cw_cache: list[Interval] | None = None
        cw_hi = -1
        span = 0
        for _ in range(MAX_TRIES):
            if t >= hi:
                return None, reason or "no_window"
            cover, prev, nxt = slot.around(t)
            if cover is not None:
                t = cover.end
                reason = "line_busy"
                continue
            setup = self.setup_on(op, ln, prev)
            dur = setup + run
            if nxt is not None and nxt.start - t < dur:      # the idle gap is shorter than the work: skip it
                t = nxt.end
                reason = "line_busy"
                continue
            span = max(span, 7 * 1440, 4 * dur)
            whi = min(hi, t + span)        # look ahead in a bounded range (extended when nothing fits)
            lw = clip(windows, t, whi)
            if needs_crew:
                if cw_cache is None or cw_hi < whi:
                    cw_hi = min(hi, whi + span)
                    cw_cache = self.crew_windows(op, t0, cw_hi)
                eff = intersect(lw, cw_cache)
            else:
                eff = lw
            if op.attended or setup == 0 or not needs_crew:
                pieces = walk(eff if op.attended else lw, t, dur, cont)
                att = (pieces or []) if (op.attended and needs_crew) else []
                if not op.attended and needs_crew and setup > 0:      # pragma: no cover - guarded above
                    att = []
            else:
                sp = walk(eff, t, setup, cont)
                pieces, att = None, sp or []
                if sp is not None:
                    if cont:
                        pieces = walk(lw, sp[0][0], dur, True)
                        if pieces is not None and pieces[0][0] != sp[0][0]:
                            pieces = None
                    else:
                        rp = walk(lw, sp[-1][1], run, False) if run > 0 else []
                        pieces = iunion(sp + rp) if rp is not None else None
            if pieces is None and whi < hi:
                span *= 3
                continue
            if pieces is None:
                if not cont:
                    return None, ("crew" if needs_crew and len(eff) < len(lw) else "no_window")
                k = window_at(eff, t)
                nt = None
                if k < len(eff) and eff[k][0] > t:
                    nt = eff[k][0]
                elif k + 1 < len(eff):
                    nt = eff[k + 1][0]
                if nt is None:
                    return None, "no_window"
                inside = window_at(lw, t) < len(lw) and lw[window_at(lw, t)][0] <= t
                reason = "crew" if needs_crew and inside else "no_window"
                t = nt
                continue
            start, end = pieces[0][0], pieces[-1][1]
            if start > t:
                inside = window_at(lw, t) < len(lw) and lw[window_at(lw, t)][0] <= t
                reason = "crew" if needs_crew and inside else "no_window"
                t = start
                continue
            if end > hi:
                return None, "no_window"
            if nxt is not None and nxt.start < end:
                t = nxt.end
                reason = "line_busy"
                continue
            if nxt is not None:
                fake = Placed(op, 0, 1, qty, ln.id, si, start, end, setup, run, pieces, [], op.tools, "", [], None)
                if self.setup_on(nxt.op, ln, fake) != nxt.setup:
                    t = nxt.end
                    reason = "line_busy"
                    continue
            if end < min_end:
                t = start + (min_end - end)
                reason = reason or "predecessor"
                continue
            if op.tools:
                nt2 = self.tools_ok(op, start, end)
                if nt2 == -1:
                    return None, "tool"
                if nt2 is not None:
                    t = max(nt2, t + 1)
                    reason = "tool"
                    continue
            crew: list[tuple[str, int, int]] | None = []
            if needs_crew and att:
                crew = self.assign_crew(op, att)
                if crew is None:
                    t = start + 1
                    reason = "crew"
                    continue
            pf = prev.op.family if prev is not None else None
            return Placed(op, 0, 1, qty, ln.id, si, start, end, setup, run, pieces, crew, op.tools, reason, [],
                          pf), ""
        return None, reason or "no_window"

    # ------------------------------------------------------------ commit / undo
    def commit(self, p: Placed) -> None:
        if p.crew:
            self.busy_version += 1
        self.st.slots[p.line_id][p.slot].add(p)
        for e, a, b in p.crew:
            self.st.busy[e].add(a, b)
            if e in self.free:
                self.free[e] = isub(self.free[e], [(a, b)])
        for pool, q in p.tools:
            self.st.tool_use.setdefault(pool, []).append((p.start, p.end, q))
        for k in p.opened:
            self.st.open_instance(k)

    def undo(self, p: Placed) -> None:
        if p.crew:
            self.busy_version += 1
        self.st.slots[p.line_id][p.slot].remove(p)
        for e, a, b in p.crew:
            self.st.busy[e].remove(a, b)
            self.free.pop(e, None)
        for pool, q in p.tools:
            self.st.tool_use[pool].remove((p.start, p.end, q))
        for k in p.opened:
            self.st.close_instance(k)

    # ------------------------------------------------------------ release of an op
    def es(self, op: Op) -> tuple[int, int, str, list[dict[str, Any]], dict[str, Any]] | Unsched:
        """(earliest start, min end, binding reason, refs, release info) or Unsched."""
        refs: list[dict[str, Any]] = []
        es, why, min_end = 0, "as_of", 0
        mat = op.material
        rel: dict[str, Any] = {"material_at": None, "predecessor_at": None, "refs": []}
        if mat is not None:
            if mat.at is None:
                return Unsched(op, "material_missing", f"No supply for {', '.join(sorted(set(mat.missing)))}.",
                               [{"type": "item", "id": None, "label": x} for x in sorted(set(mat.missing))])
            at = mat.at
            for prov, mv in mat.providers:
                child = self.m.orders[prov]
                if not child.ops:
                    continue
                last = child.ops[-1]
                if last.key in self.uns:
                    u = self.uns[last.key]
                    return Unsched(op, "beyond_horizon" if u.reason == "beyond_horizon" else "material_missing",
                                   f"Waits for {child.number}, which is not scheduled ({u.reason}).",
                                   [{"type": "work_order" if child.type == "wo" else "planned", "id": child.id,
                                     "label": child.number}])
                end = max(p.end for p in self.placed[last.key]) + mv
                if end > at:
                    at = end
            rel["material_at"] = at
            rel["refs"] = [r for r in mat.refs]
            if at > es:
                es, why = at, "material"
                refs = [r for r in mat.refs if r.get("at_min", at) == at or r["type"] in ("work_order", "planned")][:3]
        o = op.order
        if op.idx > 0:
            pred = o.ops[op.idx - 1]
            if pred.key in self.uns:
                u = self.uns[pred.key]
                return Unsched(op, u.reason, f"The previous operation {pred.seq} is not scheduled ({u.reason}).",
                               [{"type": "operation", "id": str(pred.no), "label": f"op {pred.seq}"}])
            pp = self.placed[pred.key]
            ps, pe = min(p.start for p in pp), max(p.end for p in pp)
            g = op.gap_before
            if pred.transfer_batch and not pred.gate and pred.transfer_batch < sum(p.qty for p in pp):
                b = pred.transfer_batch
                first = min(pp, key=lambda p: p.start)
                ln = self.m.lines[first.line_id]
                tb = first.setup + self.run_on(pred, ln, b)
                bound = _after_work(first.pieces, tb) + g
                ln2 = self.m.lines[op.lines[0]] if op.lines else ln
                min_end = max(min_end, pe + self.run_on(op, ln2, min(b, op.qty)) + g)
            else:
                bound = pe + g
            rel["predecessor_at"] = bound
            if bound > es or (bound == es and why == "as_of"):
                es, why = bound, "predecessor"
                refs = [{"type": "operation", "id": str(pred.no), "label": f"{o.number} op {pred.seq} {pred.rec.name}"}]
        h = self.hints.get(op.key)
        if h is not None and h[1] is not None and h[1] in self.placed:
            hp = self.placed[h[1]]
            ln = self.m.lines.get(h[0])
            bound = max(p.end for p in hp) if ln is not None and ln.capacity == 1 else min(p.start for p in hp)
            if bound > es:
                es, why = bound, "edit"
                refs = [{"type": "operation", "id": str(self.ops[h[1]].no), "label": "resequenced before"}]
        return es, min_end, why, refs, rel

    # ------------------------------------------------------------ choose a line for one op (or part)
    def best(self, op: Op, qty: float, t0: int, min_end: int, lines: list[str]) -> tuple[Placed | None, str]:
        best: Placed | None = None
        why = "no_window"
        for lid in lines:
            ln = self.m.lines[lid]
            p, w = self.place_on_line(op, qty, ln, t0, min_end, None)
            if p is None:
                why = w if why == "no_window" else why
                continue
            if best is None or (p.end, p.setup, ln.code) < (best.end, best.setup, self.m.lines[best.line_id].code):
                best = p
        return best, why

    def late(self, op: Op, end: int) -> bool:
        return end > op.latest_start + op.min_duration

    def overtime_try(self, op: Op, qty: float, t0: int, min_end: int, lines: list[str], base: Placed | None
                     ) -> Placed | None:
        """`allow` (6.8): optional instances of a candidate line opened if the operation finishes earlier."""
        best = base
        for lid in lines:
            ln = self.m.lines[lid]
            cand = {x.key for x in ln.optional if x.key not in self.st.opened}
            if not cand:
                continue
            p, _ = self.place_on_line(op, qty, ln, t0, min_end, cand)
            if p is None or (best is not None and p.end >= best.end):
                continue
            used = [x for x in ln.optional if x.key in cand and any(
                a < pe and ps < b for a, b in x.intervals for ps, pe in p.pieces)]
            ok = True
            per: dict[tuple[str, tuple[int, int]], float] = {}
            for x in used:
                k = (x.assignment_id, x.week)
                per[k] = per.get(k, 0.0) + x.minutes
                if x.max_week_minutes is not None and self.st.week_used.get(k, 0.0) + per[k] > x.max_week_minutes:
                    ok = False
            if not ok:
                self.events.append({"code": "APS_OVERTIME_LIMIT", "op": op, "line_id": lid})
                continue
            if not used:
                continue
            p.opened = tuple(sorted(x.key for x in used))
            best = p
        return best if best is not base else None

    def place_op(self, op: Op) -> None:
        r = self.es(op)
        if isinstance(r, Unsched):
            self.uns[op.key] = r
            return
        es, min_end, why, refs, rel = r
        self.release[op.key] = rel
        if es >= self.m.horizon:
            self.uns[op.key] = Unsched(op, "beyond_horizon", "Cannot start before the horizon end.", refs)
            return
        lines = op.lines
        h = self.hints.get(op.key)
        if h is not None and h[0] in self.m.lines:
            lines = [h[0]]
        if not lines:
            self.uns[op.key] = Unsched(op, "no_line", f"No active eligible line in the stage of operation {op.seq}.")
            return
        single, w = self.best(op, op.qty, es, min_end, lines)
        if single is not None and self.allow and (self.late(op, single.end) or op.latest_start < es):
            ot = self.overtime_try(op, op.qty, es, min_end, lines, single)
            if ot is not None:
                single = ot
        elif single is None and self.allow:
            single = self.overtime_try(op, op.qty, es, min_end, lines, None)
        if single is None:
            self.uns[op.key] = Unsched(op, w if w in ("no_window", "crew", "tool") else "no_window",
                                       {"crew": "No qualified operators available on the eligible lines.",
                                        "tool": "The tool pool cannot supply the required quantity."}.get(
                                           w, "No open window fits the operation on its eligible lines."))
            return
        if single.start >= self.m.horizon:
            self.uns[op.key] = Unsched(op, "beyond_horizon", "Cannot start before the horizon end.", refs)
            return
        parts = [single]
        if self.split and h is None and len(lines) >= 2 and (self.late(op, single.end) or op.latest_start < es):
            parts = self.try_split(op, es, min_end, lines, single)
        for i, p in enumerate(parts):
            p.part, p.parts = i, len(parts)
            if p is single and len(parts) == 1:
                self.commit(p)
            if not p.reason or p.start <= es:
                p.reason = why
                p.reason_refs = refs
            elif p.reason in ("line_busy",):
                cover, prev, _ = self.st.slots[p.line_id][p.slot].around(p.start - 1) if p.start > 0 else \
                    (None, None, None)
                b = cover or prev
                if b is not None:
                    p.reason_refs = [{"type": "operation", "id": str(b.op.no),
                                      "label": f"{b.op.order.number} op {b.op.seq}"}]
        if len(parts) > 1:
            self.events.append({"code": "APS_SPLIT", "op": op, "parts": len(parts)})
        self.placed[op.key] = parts
        self.order_seq.append(op.key)

    def try_split(self, op: Op, es: int, min_end: int, lines: list[str], single: Placed) -> list[Placed]:
        q = op.qty
        ms = max(op.transfer_batch or 1, math.ceil(0.1 * q - 1e-9))
        if q < 2 * ms:
            self.commit(single)
            return [single]
        best_parts = None
        best_end = single.end
        for n in (2, 3):
            if q < n * ms:
                break
            if op.order.count_uom:
                base = int(q // n)
                qs = [float(base)] * (n - 1) + [float(q - base * (n - 1))]
            else:
                qs = [q / n] * n
            got: list[Placed] = []
            ok = True
            for qi in qs:
                p, _ = self.best(op, qi, es, 0, lines)
                if p is None:
                    ok = False
                    break
                self.commit(p)
                got.append(p)
            extra = sum(p.setup for p in got) - single.setup
            end = max((p.end for p in got), default=1 << 60)
            for p in reversed(got):
                self.undo(p)
            if ok and end + extra < best_end and end >= min_end:
                best_parts, best_end = qs, end + extra
        if best_parts is None:
            self.commit(single)
            return [single]
        out = []
        for qi in best_parts:
            p, _ = self.best(op, qi, es, 0, lines)
            if p is None:           # pragma: no cover - same state as the trial
                for x in out:
                    self.undo(x)
                self.commit(single)
                return [single]
            self.commit(p)
            out.append(p)
        return out

    # ------------------------------------------------------------ fixed placements
    def place_fixed(self) -> None:
        by_op: dict[tuple[str, int], list[Fixed]] = {}
        for (k, _si), f in sorted(self.m.fixed.items()):
            by_op.setdefault(k, []).append(f)
        for k, fs in by_op.items():
            op = self.ops.get(k)
            if op is None:
                continue
            parts = []
            for f in sorted(fs, key=lambda x: x.split_index):
                slots = self.st.slots[f.line_id]
                si = next((i for i, sl in enumerate(slots) if sl.around(f.start)[0] is None and
                           all(not (b.start < f.end and f.start < b.end) for b in sl.items)), 0)
                p = Placed(op, f.split_index, f.split_count, f.qty, f.line_id, si, f.start, f.end, f.setup, f.run,
                           list(f.pieces), list(f.crew), op.tools, f.kind, [], None, fixed=f.kind)
                self.commit(p)
                parts.append(p)
            self.placed[k] = parts
            self.order_seq.append(k)

    def place_moves(self) -> None:
        """Timed `move` edits (6.7): placed exactly at the requested start on the requested line (a start in a
        closed window or on a busy slot is rejected, never snapped) and locked. A move of one part of a split
        operation places that part (its siblings are locked by the caller). An edit of a frozen / in-progress
        operation is rejected (`APS_EDIT_FROZEN`)."""
        moves = getattr(self.m, "moves", {})
        by_id = {(op.order.type, op.order.id, op.seq): op for op in self.m.ops}
        for (otype, oid, seq, si), val in sorted(moves.items(), key=lambda kv: str(kv[0])):
            line_id, start = val[0], val[1]
            qty = val[2] if len(val) > 2 else None
            count = val[3] if len(val) > 3 else 1
            op = by_id.get((otype, oid, seq))
            if op is None:
                continue
            fx = self.m.fixed.get((op.key, si))
            if fx is not None and fx.kind in ("frozen", "in_progress"):
                raise EditInfeasible(op, "APS_EDIT_FROZEN", f"Operation {op.seq} of {op.order.number} is "
                                     f"{'in progress' if fx.kind == 'in_progress' else 'frozen'} in the published "
                                     "plan; set override_freeze to move it (in-progress work never moves).")
            if start is None:
                continue
            parts = self.placed.get(op.key, [])
            if any(p.part == si for p in parts):
                continue
            ln = self.m.lines.get(line_id or (op.lines[0] if op.lines else ""))
            if ln is None:
                raise EditInfeasible(op, "APS_V_ELIGIBLE", "The line is not available for this operation.")
            p, _w = self.place_on_line(op, qty or op.qty, ln, start, 0, None)
            if p is None or p.start != start:
                code = "APS_EDIT_SPLIT" if count > 1 else "APS_V_WINDOW"
                raise EditInfeasible(op, code, f"{ln.code} cannot run this {'part of a split ' if count > 1 else ''}"
                                     "operation from the requested start (closed window, busy line or no crew).")
            p.fixed, p.reason, p.part, p.parts = "edit", "edit", si, count
            self.commit(p)
            if op.key not in self.placed:
                self.order_seq.append(op.key)
            self.placed[op.key] = sorted(parts + [p], key=lambda x: x.part)

    def check_hints(self) -> None:
        """Resequence / line-only moves must not target frozen or in-progress work (M1 fix)."""
        for k in self.hints:
            for (fk, _si), fx in self.m.fixed.items():
                if fk == k and fx.kind in ("frozen", "in_progress"):
                    op = self.ops[k]
                    raise EditInfeasible(op, "APS_EDIT_FROZEN", f"Operation {op.seq} of {op.order.number} is "
                                         "frozen in the published plan; set override_freeze to move it.")

    # ------------------------------------------------------------ main loop
    def place_actuals(self) -> None:
        """M4 6.1: running / setup / paused floor operations first on their line from as_of (remaining qty)."""
        for k, a in sorted(getattr(self.m, "actual_first", {}).items(), key=lambda kv: str(kv[0])):
            op = self.ops.get(k)
            if op is None or k in self.placed:
                continue
            ln = self.m.lines[a.line_id]
            p, _w = self.place_on_line(op, op.qty, ln, 0, 0, None)
            if p is None:
                continue
            p.fixed, p.reason = "in_progress", "in_progress"
            self.commit(p)
            self.placed[k] = [p]
            self.order_seq.append(k)

    def run(self) -> Schedule:
        self.place_fixed()
        self.place_actuals()
        self.check_hints()
        self.place_moves()
        deps: dict[tuple[str, int], set[tuple[str, int]]] = {}
        users: dict[tuple[str, int], list[tuple[str, int]]] = {}
        for op in self.m.ops:
            if op.key in self.placed:
                continue
            d: set[tuple[str, int]] = set()
            if op.idx > 0:
                d.add(op.order.ops[op.idx - 1].key)
            if op.material is not None:
                for prov, _mv in op.material.providers:
                    ch = self.m.orders[prov]
                    if ch.ops:
                        d.add(ch.ops[-1].key)
            h = self.hints.get(op.key)
            if h is not None and h[1] is not None and h[1] in self.ops:
                d.add(h[1])
            d = {x for x in d if x not in self.placed}
            deps[op.key] = d
            for x in d:
                users.setdefault(x, []).append(op.key)
        heap: list[tuple[Any, ...]] = []

        def push(k: tuple[str, int]) -> None:
            op = self.ops[k]
            r = self._quick_es(op)
            heapq.heappush(heap, (op.order.rank, op.latest_start - r, op.order.number, op.seq, op.no, k))

        for k, d in deps.items():
            if not d:
                push(k)
        done: set[tuple[str, int]] = set(self.placed)
        while heap:
            *_x, k = heapq.heappop(heap)
            if k in done:
                continue
            self.place_op(self.ops[k])
            done.add(k)
            for u in users.get(k, ()):
                deps[u].discard(k)
                if not deps[u] and u not in done:
                    push(u)
        # cycles / leftovers (should not happen: routings are linear, BOMs acyclic) -> unscheduled
        for k in deps:
            if k not in done:
                self.uns[k] = Unsched(self.ops[k], "material_missing", "Circular material dependency.")
        if self.allow:
            self._close_unused()
        return Schedule(self.placed, self.uns, dict(self.st.opened), self.release, self.events, self.order_seq)

    def _quick_es(self, op: Op) -> int:
        es = 0
        if op.material is not None and op.material.at is not None:
            es = op.material.at
        if op.idx > 0:
            pk = op.order.ops[op.idx - 1].key
            if pk in self.placed:
                es = max(es, max(p.end for p in self.placed[pk]) + op.gap_before)
        return es

    def _close_unused(self) -> None:
        used: set[str] = set()
        for parts in self.placed.values():
            for p in parts:
                ln = self.m.lines[p.line_id]
                for x in ln.optional:
                    if x.key in self.st.opened and any(a < pe and ps < b for a, b in x.intervals
                                                       for ps, pe in p.pieces):
                        used.add(x.key)
        for k in [k for k, v in self.st.opened.items() if v == "opened" and k not in used]:
            self.st.close_instance(k)


def _after_work(pieces: list[Interval], minutes: int) -> int:
    left = minutes
    for a, b in pieces:
        if b - a >= left:
            return a + left
        left -= b - a
    return pieces[-1][1] if pieces else 0


def construct(m: Model, policy: str, hints: dict[tuple[str, int], tuple[str, tuple[str, int] | None]] | None = None,
              split: bool | None = None) -> Schedule:
    return Engine(m, policy, hints, split).run()


__all__ = ["Engine", "Placed", "Schedule", "Unsched", "construct", "walk"]
