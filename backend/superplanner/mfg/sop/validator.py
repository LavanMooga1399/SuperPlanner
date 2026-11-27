"""Independent validator of an S&OP plan (M9-DESIGN 6.3; N3): own arithmetic over the stored series.

Checks: balance per node x family x month (inventory = previous + make + buy + arrivals - shipments - delivered),
non-negativity, unmet = consensus - delivered (0.5 unit), capacity (hours <= effective hours + one unit's hours),
supplier caps, allocation / sourcing shares over the horizon (one unit per month of slack), shipments only on lanes
allowed for the family, milestones when enforced (within one unit per month)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .model import SopProblem, SopResult

TOL = 0.5


def validate(p: SopProblem, r: SopResult) -> dict[str, Any]:
    v: list[dict[str, Any]] = []
    T = list(p.months)
    idx = {t: i for i, t in enumerate(T)}
    lanes = {ln.id: ln for ln in p.lanes}
    for k, q in [*r.make.items(), *r.buy.items(), *r.ship.items(), *r.inv.items(), *r.unmet.items()]:
        if q < -1e-6:
            v.append({"code": "SOP_V_NEGATIVE", "detail": {"key": [str(x) for x in k], "qty": q}})
    arr: dict[tuple[str, str, Any], float] = defaultdict(float)
    out: dict[tuple[str, str, Any], float] = defaultdict(float)
    for (lid, f, t), q in r.ship.items():
        ln = lanes.get(lid)
        if ln is None or (ln.families is not None and f not in ln.families):
            v.append({"code": "SOP_V_LANE", "detail": {"lane": lid, "family": f}})
            continue
        out[(ln.src, f, t)] += q
        j = idx[t] + ln.transit_months
        if j < len(T):
            arr[(ln.dst, f, T[j])] += q
    buy_by: dict[tuple[str, str, Any], float] = defaultdict(float)
    for (n, f, _c, t), q in r.buy.items():
        buy_by[(n, f, t)] += q
    for n in p.nodes:
        for f in p.families:
            prev = p.init_inv.get((n, f), 0.0)
            for t in T:
                d = p.demand.get((n, f, t), 0.0)
                um = r.unmet.get((n, f, t), 0.0)
                if um > d + TOL:
                    v.append({"code": "SOP_V_UNMET", "detail": {"node": n, "family": f, "month": t.isoformat()}})
                delivered = d - um
                exp = prev + r.make.get((n, f, t), 0.0) + buy_by[(n, f, t)] + arr[(n, f, t)] - out[(n, f, t)] \
                    - delivered
                got = r.inv.get((n, f, t), 0.0)
                if abs(exp - got) > TOL:
                    v.append({"code": "SOP_V_BALANCE", "detail": {"node": n, "family": f, "month": t.isoformat(),
                                                                  "expected": round(exp, 3), "got": got}})
                prev = got
    used: dict[tuple[str, str, Any], float] = defaultdict(float)
    hmax: dict[tuple[str, str], float] = defaultdict(float)
    for (n, g, f), h in p.hpu.items():
        hmax[(n, g)] = max(hmax[(n, g)], h)
        for t in T:
            used[(n, g, t)] += r.make.get((n, f, t), 0.0) * h
    for (n, g, t), u in used.items():
        if u > p.hours.get((n, g, t), 0.0) + hmax[(n, g)] + 1e-6:
            v.append({"code": "SOP_V_CAPACITY", "detail": {"node": n, "cap_group": g, "month": t.isoformat(),
                                                           "used": round(u, 3),
                                                           "available": round(p.hours.get((n, g, t), 0.0), 3)}})
    tot_buy: dict[tuple[str, str], float] = defaultdict(float)
    by_code: dict[tuple[str, str, str], float] = defaultdict(float)
    for (n, f, c, t), q in r.buy.items():
        tot_buy[(n, f)] += q
        by_code[(n, f, c)] += q
    for b in p.buys:
        if b.cap_per_month is not None:
            for t in T:
                q = r.buy.get((b.node, b.family, b.code, t), 0.0)
                if q > b.cap_per_month + TOL:
                    v.append({"code": "SOP_V_SUPPLIER_CAP", "detail": {"code": b.code, "month": t.isoformat()}})
        tot = tot_buy[(b.node, b.family)]
        slack = len(T) * 1.0
        q = by_code[(b.node, b.family, b.code)]
        if tot > 0 and (q < b.min_share * tot - slack or q > b.max_share * tot + slack):
            v.append({"code": "SOP_V_SHARE", "detail": {"code": b.code, "family": b.family, "qty": q,
                                                        "total": tot}})
    for (dest, f), rows in p.ship_shares.items():
        per = {lid: sum(q for (l2, ff, _t), q in r.ship.items() if l2 == lid and ff == f) for lid, _a, _b in rows}
        tot = sum(per.values())
        for lid, mn, mx in rows:
            if tot > 0 and (per[lid] < mn * tot - len(T) or per[lid] > mx * tot + len(T)):
                v.append({"code": "SOP_V_SHARE", "detail": {"lane": lid, "family": f, "qty": per[lid],
                                                            "total": tot}})
    for m in p.milestones:
        f, mn = m["family"], float(m["min_share"])
        dom = tot = 0.0
        for (n, ff, t), q in r.make.items():
            if ff == f:
                dom += q * p.make_domestic.get((n, f), 0.0)
                tot += q
        for b in p.buys:
            if b.family == f:
                q = by_code[(b.node, f, b.code)]
                dom += q * b.domestic
                tot += q
        if tot > 0 and dom < mn * tot - len(T):
            v.append({"code": "SOP_V_MILESTONE", "detail": {"family": f, "share": round(dom / tot, 4),
                                                            "min": mn}})
    return {"ok": not v, "violations": v[:200]}
