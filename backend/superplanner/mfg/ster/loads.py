"""Sterilisation load planner (M8-DESIGN 8, 0.9; pure, greedy, deterministic).

- Pallets per member = ceil(qty / pallet qty_base); no pallet level -> skipped (`STER_NO_PALLET`). A candidate
  larger than every chamber is split into chamber-sized parts.
- Candidates by ready time; first-fit into the open load of the same cycle code. A load closes when the next
  member does not fit (capacity = the largest chamber that runs the cycle code), when the next candidate is ready
  later than the oldest member's ready + `max_wait_hours`, or at the end.
- A closed load goes to the chamber (with enough pallets) giving the earliest start >= the latest member ready
  time and the chamber's free time; duration = chamber `cycle_hours`. Aeration = max member `aeration_hours` in one
  aeration room with free pallet positions over the whole period (cumulative check over time); when no room has
  room, the load start is delayed to the earliest feasible time (`STER_AERATION_BOUND`). Without aeration rooms
  aeration is not capacity-checked.
- Release due = date of (aeration end + max member `release_days`) for `bi` / `parametric` members, else the date
  of the aeration end.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .model import AerationRoom, Chamber, PlannedLoad, PlannedMember, SterCandidate, SterPlan
from .validator import validate


def _room_free(busy: list[tuple[datetime, datetime, int]], positions: int, start: datetime, end: datetime,
               need: int) -> bool:
    points = sorted({start} | {a for a, _b, _n in busy if start <= a < end})
    for t in points:
        used = sum(n for a, b, n in busy if a <= t < b)
        if used + need > positions:
            return False
    return True


def _room_next(busy: list[tuple[datetime, datetime, int]], after: datetime) -> datetime | None:
    ends = sorted(b for _a, b, _n in busy if b > after)
    return ends[0] if ends else None


def plan(cands: list[SterCandidate], chambers: list[Chamber], rooms: list[AerationRoom], *, max_wait_hours: float,
         busy_chambers: dict[str, list[tuple[datetime, datetime]]] | None = None,
         busy_rooms: dict[str, list[tuple[datetime, datetime, int]]] | None = None, tz_offset_minutes: int = 0
         ) -> SterPlan:
    skipped: list[dict] = []
    warnings: list[dict] = []
    chamber_busy = {c.id: sorted(list((busy_chambers or {}).get(c.id, []))) for c in chambers}
    room_busy = {r.id: list((busy_rooms or {}).get(r.id, [])) for r in rooms}
    items: list[tuple[SterCandidate, int, float]] = []
    for c in sorted(cands, key=lambda x: (x.ready, x.key)):
        if not c.pallet_qty:
            skipped.append({"key": c.key, "item_id": c.item_id, "code": "STER_NO_PALLET"})
            continue
        able = [ch for ch in chambers if ch.cycle_codes is None or c.cycle_code in ch.cycle_codes]
        if not able:
            skipped.append({"key": c.key, "item_id": c.item_id, "code": "STER_NO_CHAMBER"})
            continue
        cap = max(ch.pallets for ch in able)
        pallets = math.ceil(c.qty / c.pallet_qty - 1e-9)
        left_q, left_p = c.qty, pallets
        while left_p > 0:
            p = min(cap, left_p)
            q = left_q if p == left_p else p * c.pallet_qty
            items.append((c, p, q))
            left_p -= p
            left_q -= q
    loads: list[PlannedLoad] = []
    open_: dict[str, list[tuple[SterCandidate, int, float]]] = {}

    def close(code: str) -> None:
        members = open_.pop(code, [])
        if not members:
            return
        ready = max(m[0].ready for m in members)
        pallets = sum(m[1] for m in members)
        aer_h = max(m[0].aeration_hours for m in members)
        rel_days = max((m[0].release_days for m in members if m[0].release_mode in ("bi", "parametric")),
                       default=0.0)
        best = None
        for ch in chambers:
            if ch.pallets < pallets or (ch.cycle_codes is not None and code not in ch.cycle_codes):
                continue
            t = ready
            for a, b in chamber_busy[ch.id]:
                if b > t and a < t + timedelta(hours=ch.cycle_hours):
                    t = max(t, b)
            delayed = False
            t_free = t
            room_id = None
            if rooms:
                guard = 0
                while guard < 1000:
                    guard += 1
                    end = t + timedelta(hours=ch.cycle_hours)
                    a_end = end + timedelta(hours=aer_h)
                    ok = [r for r in rooms if r.positions >= pallets and
                          _room_free(room_busy[r.id], r.positions, end, a_end, pallets)]
                    if ok:
                        room_id = sorted(ok, key=lambda r: r.code)[0].id
                        break
                    nxt = min((x for x in (_room_next(room_busy[r.id], end) for r in rooms) if x is not None),
                              default=None)
                    if nxt is None:
                        break
                    t = t + (nxt - end)
                    delayed = True
                    for a, b in chamber_busy[ch.id]:
                        if b > t and a < t + timedelta(hours=ch.cycle_hours):
                            t = max(t, b)
            key = (t, ch.code)
            if best is None or key < best[0]:
                best = (key, ch, t, room_id, delayed, t_free)
        if best is None:
            for m in members:
                skipped.append({"key": m[0].key, "item_id": m[0].item_id, "code": "STER_NO_CHAMBER"})
            return
        _k, ch, t, room_id, delayed, t_free = best
        end = t + timedelta(hours=ch.cycle_hours)
        a_end = end + timedelta(hours=aer_h)
        rel = a_end + timedelta(days=rel_days)
        load = PlannedLoad(ch.id, code, t, end, a_end, room_id,
                           (rel + timedelta(minutes=tz_offset_minutes)).date(),
                           [PlannedMember(m[0].key, m[0].item_id, round(m[2], 6), m[1], m[0].wo_id,
                                          m[0].rate_block_id, m[0].lot_id) for m in members])
        if delayed:
            load.flags.append("STER_AERATION_BOUND")
            warnings.append({"code": "STER_AERATION_BOUND", "load_ix": len(loads),
                             "detail": {"delay_hours": round((t - t_free).total_seconds() / 3600, 3)}})
        chamber_busy[ch.id].append((t, end))
        chamber_busy[ch.id].sort()
        if room_id is not None:
            room_busy[room_id].append((end, a_end, load.pallets))
        loads.append(load)

    for c, p, q in items:
        code = c.cycle_code
        cur = open_.get(code)
        cap = max((ch.pallets for ch in chambers if ch.cycle_codes is None or code in ch.cycle_codes), default=0)
        if cur:
            oldest = min(m[0].ready for m in cur)
            if sum(m[1] for m in cur) + p > cap or c.ready > oldest + timedelta(hours=max_wait_hours):
                close(code)
        open_.setdefault(code, []).append((c, p, q))
        if sum(m[1] for m in open_[code]) >= cap:
            close(code)
    for code in sorted(open_):
        close(code)
    val = validate(loads, chambers, rooms, busy_chambers or {}, busy_rooms or {},
                   {c.key: c.ready for c in cands})
    return SterPlan(loads, skipped, warnings, val)
