"""Risk run (M4-DESIGN 8): N sampled scenarios of supplier delays and line breakdowns drawn from the plant's own
history, construction only (no LNS), deterministic for a seed.

- supplier lateness: per supplier the empirical delays (receipt date - dock date, last 12 months of `po_receipt`);
  fewer than `MIN_HISTORY` receipts -> the plant-wide distribution; no history -> no delay. A sample draws one delay
  per open PO/PR schedule (early receipts count 0);
- breakdowns: per line the observed MTBF (history span / breakdowns) with exponential inter-arrival from as_of over
  the horizon, durations resampled from the history; no history -> none;
- per demand line: on-time probability, P50 / P90 completion (unscheduled -> beyond the horizon end); per line:
  expected lost hours; per supplier: late demand lines of samples in which one of its delayed schedules feeds the
  line's orders (MRP pegging, one level).
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .model import ApsParams, LineBreakdown, SupplyDelay

MIN_HISTORY = 5


@dataclass
class RiskInputs:
    supplier_of: dict[str, str]                      # schedule id -> supplier id
    lateness: dict[str, list[int]]                   # supplier id -> delays (days) of past receipts
    breakdowns: dict[str, list[float]]               # line id -> durations (hours) of past breakdowns
    history_hours: dict[str, float]                  # line id -> observed history span (hours)
    supplier_names: dict[str, dict[str, Any]] = field(default_factory=dict)
    line_names: dict[str, dict[str, Any]] = field(default_factory=dict)


def _pct(values: list[datetime], q: float) -> datetime | None:
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[k]


def draw(rng: random.Random, inputs: RiskInputs, schedule_ids: list[str], as_of: datetime, horizon_hours: float
         ) -> tuple[list[SupplyDelay], list[LineBreakdown], dict[str, float]]:
    plant = [d for v in inputs.lateness.values() for d in v]
    delays = []
    for sid in sorted(schedule_ids):
        sup = inputs.supplier_of.get(sid)
        hist = inputs.lateness.get(sup or "", [])
        pool = hist if len(hist) >= MIN_HISTORY else plant
        if not pool:
            continue
        d = max(0, int(rng.choice(sorted(pool))))
        if d > 0:
            delays.append(SupplyDelay.model_construct(schedule_id=sid, wo_id=None, item_id=None, days=min(d, 365)))
    brk: list[LineBreakdown] = []
    lost: dict[str, float] = {}
    for lid in sorted(inputs.breakdowns):
        durs = inputs.breakdowns[lid]
        span = inputs.history_hours.get(lid, 0.0)
        if not durs or span <= 0:
            continue
        mtbf = span / len(durs)
        t = 0.0
        total = 0.0
        while True:
            t += rng.expovariate(1.0 / mtbf)
            if t >= horizon_hours:
                break
            h = float(rng.choice(sorted(durs)))
            brk.append(LineBreakdown.model_construct(line_id=lid, start=as_of + timedelta(hours=t), hours=max(0.1, h)))
            total += h
            t += h
        lost[lid] = total
    return delays, brk, lost


def risk_run(snap: Any, base: ApsParams, inputs: RiskInputs, samples: int, seed: int, horizon_days: int | None = None,
             progress: Callable[[int], None] | None = None, cancelled: Callable[[], bool] | None = None
             ) -> dict[str, Any]:
    from .engine import schedule

    hd = int(horizon_days or base.horizon_days or 42)
    params0 = base.model_copy(update={"improve_seconds": 0, "horizon_days": hd, "edits": [], "copy_of": None,
                                      "as_of": None})
    sched_ids = sorted({s.ref_id for s in snap.open_supply})
    if snap.mrp is not None:
        sched_ids = sorted(set(sched_ids) | {p.ref_id for ps in snap.mrp.pegs.values() for p in ps
                                             if p.kind in ("po_schedule", "pr_schedule") and p.ref_id})
    feeds: dict[tuple[str, str], set[str]] = defaultdict(set)           # (type, order id) -> schedule ids
    if snap.mrp is not None:
        for (otype, oid, _item), ps in snap.mrp.pegs.items():
            for p in ps:
                if p.kind in ("po_schedule", "pr_schedule") and p.ref_id:
                    feeds[(otype, oid)].add(p.ref_id)
    horizon_end = snap.as_of + timedelta(days=hd)
    ends: dict[str, list[datetime]] = defaultdict(list)
    on_time: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}
    lost_tot: dict[str, float] = defaultdict(float)
    brk_n: dict[str, int] = defaultdict(int)
    late_by_sup: dict[str, int] = defaultdict(int)
    done = 0
    late_minutes: dict[str, list[int]] = defaultdict(list)
    base_res = schedule(snap, params0)          # the unperturbed plan (base_end per demand line)
    base_end = {(d.demand_line_id or f"{d.order_number}/{d.line_no}"): d.scheduled_end for d in base_res.demand}
    for i in range(samples):
        if cancelled is not None and cancelled():
            break
        rng = random.Random(seed * 1_000_003 + i)
        delays, brk, lost = draw(rng, inputs, sched_ids, snap.as_of, hd * 24.0)
        for lid, h in lost.items():
            lost_tot[lid] += h
        for b in brk:
            brk_n[b.line_id] += 1
        res = schedule(snap, params0.model_copy(update={"supply_delays": delays, "line_breakdowns": brk}))
        delayed = {d.schedule_id for d in delays}
        for d in res.demand:
            k = d.demand_line_id or f"{d.order_number}/{d.line_no}"
            meta.setdefault(k, {"demand_line_id": d.demand_line_id, "order": f"{d.order_number}/{d.line_no}",
                                "part_number": d.part_number, "due": d.due, "priority": d.priority})
            end = d.scheduled_end or horizon_end
            ends[k].append(end)
            late_minutes[k].append(int(d.late_minutes) if d.scheduled_end is not None else
                                   int(max(0.0, (horizon_end - d.due).total_seconds() / 60)))
            if d.late_minutes <= 0 and d.scheduled_end is not None:
                on_time[k] += 1
            else:
                sups = set()
                for o in d.orders:
                    for sid in feeds.get((o.type if o.type == "wo" else "planned",
                                          o.id if o.type == "wo" else str(o.planned_no)), ()):
                        if sid in delayed and sid in inputs.supplier_of:
                            sups.add(inputs.supplier_of[sid])
                for sp in sups:
                    late_by_sup[sp] += 1
        done += 1
        if progress is not None:
            progress(done)
    n = max(1, done)
    demand = []
    for k in sorted(meta, key=lambda x: (meta[x]["due"], meta[x]["order"])):
        mt = meta[k]
        demand.append({**mt, "due": mt["due"].isoformat(), "p_on_time": round(on_time[k] / n, 4),
                       "p50": (_pct(ends[k], 0.5) or horizon_end).isoformat(),
                       "p90": (_pct(ends[k], 0.9) or horizon_end).isoformat(),
                       "base_end": base_end[k].isoformat() if base_end.get(k) else None,
                       "samples_late_minutes": late_minutes[k]})
    lines = [{"line": inputs.line_names.get(lid, {"id": lid, "code": "", "name": ""}),
              "expected_lost_hours": round(lost_tot[lid] / n, 3),
              "mtbf_hours": round(inputs.history_hours[lid] / len(inputs.breakdowns[lid]), 3),
              "breakdowns_sampled": brk_n[lid]}
             for lid in sorted(inputs.breakdowns) if inputs.breakdowns[lid] and inputs.history_hours.get(lid)]
    sups = sorted(set(inputs.lateness) | set(late_by_sup), key=lambda x: (-late_by_sup.get(x, 0), x))
    plant_hist = [d for v in inputs.lateness.values() for d in v]
    suppliers = [{"supplier": inputs.supplier_names.get(sp, {"id": sp, "code": "", "name": ""}),
                  "late_lines": late_by_sup.get(sp, 0),
                  "mean_delay_days": round(sum(inputs.lateness.get(sp) or plant_hist or [0]) /
                                           max(1, len(inputs.lateness.get(sp) or plant_hist or [0])), 3),
                  "history_receipts": len(inputs.lateness.get(sp, []))} for sp in sups]
    return {"samples_done": done, "seed": seed, "horizon_days": hd, "demand": demand, "lines": lines,
            "suppliers": suppliers}


__all__ = ["MIN_HISTORY", "RiskInputs", "draw", "risk_run"]
