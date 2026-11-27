"""Independent validator of a network plan (M9-DESIGN 5.3 step 5; N3). Own arithmetic, no engine code:

- balance: the projection equals stock + receipts + planned in - gross - planned out per vertex-week (gross and
  planned flows recomputed here from the problem and the plan); a negative projection needs a recorded shortage at
  that vertex in or before that week;
- capacity: booked hours <= available per node x cap group x week (`constrained`), hours = qty x hours/unit;
- transit: ship + transit working days (source calendar) = receive;
- transfers only along allowed rules (active, valid, plant source = transfer source) and active lanes;
- quota: per destination x key in quota mode, every source's non-spill share within one order multiple (or the
  minimum quantity) of its target over the horizon;
- pegs: every transfer's / production's pegs sum to its quantity.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .model import NetProblem, NetResult

TOL = 1e-3


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _workday(d: date, workdays: tuple[int, ...], holidays: frozenset[date]) -> bool:
    return d.weekday() in (workdays or (0, 1, 2, 3, 4)) and d not in holidays


def _add_workdays(d: date, n: int, workdays: tuple[int, ...], holidays: frozenset[date]) -> date:
    out, k = d, 0
    while k < n:
        out += timedelta(days=1)
        if _workday(out, workdays, holidays):
            k += 1
    return out


def validate(p: NetProblem, r: NetResult) -> dict[str, Any]:
    v: list[dict[str, Any]] = []
    weeks = r.weeks
    if not weeks:
        return {"ok": True, "violations": []}
    w0, wend = weeks[0], weeks[-1]
    nodes = {n.id: n for n in p.nodes}
    items = {(i.node, i.key): i for i in p.items}

    def wk(d: date) -> date | None:
        m = max(_monday(d), w0)
        return m if m <= wend else None

    # ---- balance
    verts = {(x.node, x.key) for x in r.projection}
    flow: dict[tuple[str, str, date], float] = defaultdict(float)
    for d in p.demand:
        if (d.node, d.key) in verts and (w := wk(d.week)):
            flow[(d.node, d.key, w)] -= d.qty
    for s in p.supply:
        if (s.node, s.key) in verts and (w := wk(s.week)):
            flow[(s.node, s.key, w)] += s.qty
    for t in r.transfers:
        if (w := wk(t.receive_date)):
            flow[(t.dst, t.key, w)] += t.qty
        if (t.src, t.key) in verts and (w := wk(t.ship_date)):
            flow[(t.src, t.key, w)] -= t.qty
    bom = defaultdict(list)
    for b in p.bom:
        bom[(b.node, b.parent_key)].append((b.component_key, b.qty_per))
    for pr in r.production:
        if (w := wk(pr.week)):
            flow[(pr.node, pr.key, w)] += pr.qty
        if pr.kind == "make":
            lead = items[(pr.node, pr.key)].lead_days if (pr.node, pr.key) in items else 0
            start = wk(pr.week - timedelta(days=lead)) or w0
            for comp, q in bom.get((pr.node, pr.key), []):
                if (pr.node, comp) in verts:
                    flow[(pr.node, comp, start)] -= pr.qty * q
    short_at: dict[tuple[str, str, date], float] = defaultdict(float)
    for s in r.shortages:
        short_at[(s.node, s.key, max(_monday(s.week), w0))] += s.qty
    proj = {(x.node, x.key, x.week): x.projected for x in r.projection}
    for node, key in sorted(verts):
        bal = 0.0
        cum_short = 0.0
        for w in weeks:
            cum_short += short_at.get((node, key, w), 0.0)
            bal += flow.get((node, key, w), 0.0)
            got = proj.get((node, key, w))
            if got is None or abs(got - bal) > TOL * max(1.0, abs(bal)):
                v.append({"code": "NET_V_BALANCE", "detail": {"node": node, "key": key, "week": w.isoformat(),
                                                              "expected": round(bal, 6), "got": got}})
                break
            if bal < -TOL and -bal > cum_short + TOL * max(1.0, abs(bal)):   # review m6: covered by shortages
                v.append({"code": "NET_V_NEGATIVE", "detail": {"node": node, "key": key, "week": w.isoformat(),
                                                               "projected": round(bal, 6)}})
                break

    # ---- capacity
    if p.constrained:
        avail: dict[tuple[str, str, date], float] = defaultdict(float)
        groups = set()
        for c in p.capacity:
            avail[(c.node, c.cap_group, _monday(c.week))] += c.hours
            groups.add((c.node, c.cap_group))
        hpu = defaultdict(list)
        for ld in p.load:
            hpu[(ld.node, ld.key)].append((ld.cap_group, ld.hours_per_unit))
        used: dict[tuple[str, str, date], float] = defaultdict(float)
        for pr in r.production:
            if pr.kind != "make":
                continue
            for g, h in hpu.get((pr.node, pr.key), []):
                used[(pr.node, g, _monday(pr.week))] += pr.qty * h
        for k, u in sorted(used.items()):
            if (k[0], k[1]) in groups and u > avail.get(k, 0.0) + TOL:
                v.append({"code": "NET_V_CAPACITY", "detail": {"node": k[0], "cap_group": k[1],
                                                               "week": k[2].isoformat(), "used": round(u, 4),
                                                               "available": avail.get(k, 0.0)}})

    # ---- transit, rules, lanes
    lanes = {ln.id: ln for ln in p.lanes}
    rules_at: dict[tuple[str, str | None], list[Any]] = defaultdict(list)
    for ru in p.rules:
        rules_at[(ru.dest, ru.source)].append(ru)
    for t in r.transfers:
        ln = lanes.get(t.lane_id or "")
        if ln is None or not ln.active or ln.src != t.src or ln.dst != t.dst:
            v.append({"code": "NET_V_LANE", "detail": {"src": t.src, "dst": t.dst, "key": t.key,
                                                       "lane": t.lane_id}})
            continue
        n = nodes.get(t.src)
        expect = _add_workdays(t.ship_date, ln.transit_days, n.workdays if n else (0, 1, 2, 3, 4),
                               n.holidays if n else frozenset())
        if expect != t.receive_date:
            v.append({"code": "NET_V_TRANSIT", "detail": {"src": t.src, "dst": t.dst, "key": t.key,
                                                          "ship": t.ship_date.isoformat(),
                                                          "receive": t.receive_date.isoformat(),
                                                          "expected": expect.isoformat()}})
        it = items.get((t.dst, t.key))
        ok = False
        for ru in rules_at.get((t.dst, t.src), []):
            if ru.source_kind != "plant":
                continue
            if not (ru.key == t.key or (ru.key is None and it is not None and ru.family == it.family)):
                continue
            rw = _monday(t.receive_date)
            if (ru.valid_from is None or ru.valid_from <= rw + timedelta(days=6)) and (ru.valid_to is None
                                                                                       or ru.valid_to >= rw):
                ok = True
                break
        if not ok:
            v.append({"code": "NET_V_RULE", "detail": {"src": t.src, "dst": t.dst, "key": t.key}})

    # ---- quota share over the horizon (spill excepted)
    qrules = defaultdict(list)
    for ru in p.rules:
        if ru.quota_pct is not None:
            qrules[(ru.dest, ru.key, ru.family)].append(ru)
    tr_by: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for t in r.transfers:
        tr_by[(t.dst, t.key)].append(t)
    buy_by: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for pr in r.production:
        if pr.kind == "buy":
            buy_by[(pr.node, pr.key)].append(pr)
    key_rules = {(ru.dest, ru.key) for ru in p.rules if ru.key is not None}
    keys_of: dict[tuple[str, str | None], list[str]] = defaultdict(list)
    for (n, k), it in items.items():
        keys_of[(n, k)].append(k)
        keys_of[(n, "~" + (it.family or ""))].append(k)
    for (dest, key, fam), rs in qrules.items():
        keys = keys_of.get((dest, key), []) if key is not None else keys_of.get((dest, "~" + (fam or "")), [])
        for k in keys:
            if key is None and (dest, k) in key_rules:
                continue                      # item-key rules win over this family set
            it = items[(dest, k)]
            got = defaultdict(float)
            for t in tr_by.get((dest, k), []):
                if not t.spill:
                    got[t.rule_id] += t.requested or t.qty
            for pr in buy_by.get((dest, k), []):
                if pr.supplier_code:
                    for ru in rs:
                        if ru.supplier_code == pr.supplier_code:
                            got[ru.id] += pr.qty
            total = sum(got.values())
            if total <= TOL:
                continue
            # the cumulative arrangement assigns whole receipts: within one receipt (>= one order multiple)
            biggest = max([t.requested or t.qty for t in tr_by.get((dest, k), []) if not t.spill]
                          + [pr.qty for pr in buy_by.get((dest, k), [])] + [0.0])
            band = max(it.order_multiple or 0.0, it.min_qty or 0.0, 1.0, biggest)
            for ru in rs:
                target = (ru.quota_pct or 0.0) / 100.0 * total
                if abs(got.get(ru.id, 0.0) - target) > band + TOL:
                    v.append({"code": "NET_V_QUOTA", "detail": {"dest": dest, "key": k, "rule": ru.id,
                                                                "assigned": got.get(ru.id, 0.0),
                                                                "target": round(target, 4)}})

    # ---- pegs
    for o in [*r.transfers, *r.production]:
        s = sum(pg.qty for pg in o.pegs)
        if abs(s - o.qty) > TOL * max(1.0, o.qty):
            v.append({"code": "NET_V_PEGS", "detail": {"key": o.key, "qty": o.qty, "pegged": round(s, 6)}})
    return {"ok": not v, "violations": v[:200]}
