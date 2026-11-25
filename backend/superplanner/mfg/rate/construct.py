"""Rate engine construction (M8-DESIGN 7.2 steps 1-3; pure, deterministic).

Per flow line a cursor walks through the line's shift windows. Repeatedly the assigned item with the earliest
projected run-out (ties: priority, part number) gets a campaign: changeover / cleaning / clearance blocks from the
matrix (most specific row per kind: (from, to) > (from, *) > (*, to) > (*, *); wildcards only between different
keys) plus the line's clearance minutes between any two items, then production until the cover reaches
`target_cover_days` (at least `campaign_min_hours`, at most `campaign_max_hours`, whole cases). Periodic cleaning
is inserted when the run hours since the last cleaning would exceed `clean_every_hours`. Blocks never cross a
window end or a plant-local midnight (one `prod_date` per block).

`layout(...)` lays out a given campaign sequence and is shared with the improvement step.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from .model import ChangeoverRule, RateBlock, RateItem, RateLine, RateProblem

EPS = 1e-9
MIN = timedelta(minutes=1)


def matrix_lookup(rules: Iterable[ChangeoverRule], family: str | None, a: str, b: str) -> dict[str, tuple[int, float]]:
    """kind -> (minutes, cost) of the most specific rows for a transition from key `a` to key `b`."""
    if family is None:
        return {}
    best: dict[str, tuple[int, int, float]] = {}
    for r in rules:
        if r.line_setup_family != family:
            continue
        if r.from_key == a and r.to_key == b:
            rank = 3
        elif a == b:
            continue
        elif r.from_key == a and r.to_key == "*":
            rank = 2
        elif r.from_key == "*" and r.to_key == b:
            rank = 1
        elif r.from_key == "*" and r.to_key == "*":
            rank = 0
        else:
            continue
        cur = best.get(r.kind)
        if cur is None or rank > cur[0]:
            best[r.kind] = (rank, r.minutes, r.cost)
    return {k: (v[1], v[2]) for k, v in best.items() if v[1] > 0}


def transition(problem: RateProblem, line: RateLine, prev: str | None, nxt: str) -> list[tuple[str, int, float]]:
    """Setup blocks (kind, minutes, cost) before producing `nxt` after `prev` (None = line start: none)."""
    if prev is None or prev == nxt:
        return []
    a, b = problem.items[prev].key, problem.items[nxt].key
    m = matrix_lookup(problem.changeovers, line.setup_family, a, b)
    out = []
    for kind in ("changeover", "cleaning"):
        if kind in m:
            out.append((kind, m[kind][0], m[kind][1]))
    clr = max(m.get("clearance", (0, 0.0))[0], line.clearance_minutes)
    if clr > 0:
        out.append(("clearance", clr, m.get("clearance", (0, 0.0))[1]))
    return out


def local_date(line: RateLine, t: datetime) -> date:
    return (t + timedelta(minutes=line.tz_offset_minutes)).date()


def _next_midnight(line: RateLine, t: datetime) -> datetime:
    loc = t + timedelta(minutes=line.tz_offset_minutes)
    nxt = datetime(loc.year, loc.month, loc.day, tzinfo=loc.tzinfo) + timedelta(days=1)
    return nxt - timedelta(minutes=line.tz_offset_minutes)


@dataclass
class Cursor:
    t: datetime
    prev_item: str | None = None
    run_since_clean: float = 0.0          # production hours since the last cleaning
    campaign_no: int = 0


@dataclass
class Sim:
    """Window walker of one line (UTC datetimes)."""
    line: RateLine
    end: datetime
    starts: list[datetime] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.wins = sorted((w for w in self.line.windows if w.end > w.start), key=lambda w: w.start)
        self.starts = [w.start for w in self.wins]

    def window_at(self, t: datetime) -> tuple[datetime, datetime] | None:
        """The window containing `t` (or the next one), clipped to the horizon end."""
        i = bisect_right(self.starts, t) - 1
        for j in range(max(i, 0), len(self.wins)):
            w = self.wins[j]
            if w.end <= t:
                continue
            s = max(w.start, t)
            e = min(w.end, self.end)
            if s >= e:
                return None
            return s, e
        return None

    def place(self, kind: str, item: str | None, minutes: float, cur: Cursor, campaign_no: int,
              rate: float = 0.0) -> list[RateBlock] | None:
        """Lay `minutes` of one activity from the cursor; None when the horizon ends first (blocks placed so far are
        returned through the partial attribute)."""
        out: list[RateBlock] = []
        left = minutes
        while left > EPS:
            w = self.window_at(cur.t)
            if w is None:
                self.partial = out
                return None
            s, e = w
            e = min(e, _next_midnight(self.line, s))
            span = (e - s).total_seconds() / 60.0
            take = min(span, left)
            bend = s + timedelta(minutes=take)
            out.append(RateBlock(self.line.id, kind, item, campaign_no, s, bend,
                                 qty=rate * take / 60.0 if kind == "production" else 0.0,
                                 prod_date=local_date(self.line, s)))
            left -= take
            cur.t = bend
        return out


def _cases(qty: float, case: float | None) -> float:
    if not case:
        return math.ceil(qty - 1e-6)
    return math.ceil(qty / case - 1e-6) * case


def produce(problem: RateProblem, sim: Sim, cur: Cursor, item_id: str, qty: float, *,
            costs: list[float] | None = None) -> tuple[list[RateBlock], float, bool]:
    """Setup + production of `qty` (already whole cases) from the cursor, with periodic cleaning. Returns (blocks,
    produced qty, complete). A campaign cut by the horizon end keeps whole cases only."""
    line = sim.line
    it = problem.items[item_id]
    rate = line.rates[item_id]
    blocks: list[RateBlock] = []
    cur.campaign_no += 1
    no = cur.campaign_no
    for kind, minutes, cost in transition(problem, line, cur.prev_item, item_id):
        got = sim.place(kind, None if kind != "changeover" else item_id, minutes, cur, no)
        if got is None:
            cur.campaign_no -= 1
            return [], 0.0, False
        blocks += got
        if costs is not None:
            costs.append(cost)
        if kind == "cleaning" and minutes >= float(line.clean_minutes or 0):
            cur.run_since_clean = 0.0
    need_min = qty / rate * 60.0
    placed = 0.0
    complete = True
    while need_min - placed > 1e-6:
        chunk = need_min - placed
        if line.clean_every_hours:
            room = line.clean_every_hours * 60.0 - cur.run_since_clean * 60.0
            if room <= 1e-6:
                got = sim.place("cleaning", None, float(line.clean_minutes or 0), cur, no)
                if got is None:
                    complete = False
                    break
                blocks += got
                cur.run_since_clean = 0.0
                continue
            chunk = min(chunk, room)
        got = sim.place("production", item_id, chunk, cur, no, rate)
        if got is None:
            got = sim.partial
            complete = False
        for b in got:
            mins = (b.end - b.start).total_seconds() / 60.0
            placed += mins
            cur.run_since_clean += mins / 60.0
        blocks += got
        if not complete:
            break
    prod = [b for b in blocks if b.kind == "production"]
    if not prod:
        cur.campaign_no -= 1 if not blocks else 0
        if blocks:
            cur.prev_item = item_id
        return blocks, 0.0, False
    if not complete:                               # keep whole cases: trim the last production block
        made = sum(b.qty for b in prod)
        keep = math.floor(made / it.case_qty + 1e-6) * it.case_qty if it.case_qty else math.floor(made + 1e-6)
        cut = made - keep
        while cut > 1e-6 and prod:
            last = prod[-1]
            if last.qty <= cut + 1e-6:
                cut -= last.qty
                blocks.remove(last)
                prod.pop()
                continue
            last.qty -= cut
            last.end = last.start + timedelta(minutes=last.qty / rate * 60.0)
            cut = 0.0
        if not prod:
            return blocks, 0.0, False
    raw, done = 0.0, 0.0                           # whole units per block (cumulative rounding, total unchanged)
    for b in prod:
        raw += b.qty
        b.qty = float(round(raw) - done)
        done += b.qty
    for b in prod:
        b.cases = int(round(b.qty / it.case_qty)) if it.case_qty else None
    cur.prev_item = item_id
    return blocks, sum(b.qty for b in prod), complete


# ---------------------------------------------------------------- run-out construction (step 3)

@dataclass
class ItemState:
    demands: list[tuple[date, float, int]]   # (due, qty, priority), sorted
    supply: float                            # initial stock + firm + produced

    def runout(self) -> date | None:
        cum = 0.0
        for due, q, _p in self.demands:
            cum += q
            if cum > self.supply + 1e-6:
                return due
        return None

    def demand_until(self, d: date) -> float:
        return sum(q for due, q, _p in self.demands if due <= d)

    def priority(self) -> int:
        return min((p for _d, _q, p in self.demands), default=9)


def construct_line(problem: RateProblem, line: RateLine, item_ids: list[str],
                   demands: dict[str, list[tuple[date, float, int]]], firm: list[RateBlock]
                   ) -> list[RateBlock]:
    """Greedy run-out construction of one line (after its firm blocks)."""
    sim = Sim(line, problem.horizon_end)
    blocks = sorted(firm, key=lambda b: b.start)
    start = max([problem.as_of] + [b.end for b in blocks])
    cur = Cursor(start, campaign_no=max([b.campaign_no for b in blocks], default=0))
    last_prod = [b for b in blocks if b.kind == "production"]
    if last_prod:
        cur.prev_item = last_prod[-1].item_id
    states = {}
    for i in item_ids:
        firm_qty = 0.0 if problem.firm_netted else \
            sum(b.qty for b in blocks if b.kind == "production" and b.item_id == i)
        states[i] = ItemState(sorted(demands.get(i, [])), problem.items[i].initial_stock + firm_qty)
    guard = 0
    while guard < 10_000:
        guard += 1
        if sim.window_at(cur.t) is None:
            break
        cands = []
        for i in item_ids:
            ro = states[i].runout()
            if ro is not None:
                cands.append((ro, states[i].priority(), problem.items[i].part_number, i))
        if not cands:
            break
        ro, _p, _pn, item_id = min(cands)
        it = problem.items[item_id]
        st = states[item_id]
        rate = line.rates[item_id]
        base = max(ro, (cur.t + timedelta(minutes=line.tz_offset_minutes)).date())
        need = st.demand_until(base + timedelta(days=it.target_cover_days)) - st.supply
        need = max(need, st.demand_until(ro) - st.supply, 1e-6)
        hours = need / rate
        hours = max(hours, it.campaign_min_hours)
        if it.campaign_max_hours:
            hours = min(hours, it.campaign_max_hours)
        qty = _cases(hours * rate, it.case_qty)
        if it.campaign_max_hours and qty / rate > it.campaign_max_hours + 1e-9:
            step = it.case_qty or 1.0
            qty = max(step, math.floor(it.campaign_max_hours * rate / step + 1e-9) * step)
        got, made, _complete = produce(problem, sim, cur, item_id, qty)
        blocks += got
        if made <= EPS:
            break
        st.supply += made
    return blocks
