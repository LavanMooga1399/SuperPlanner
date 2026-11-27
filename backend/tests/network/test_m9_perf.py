"""M9 performance (M9-DESIGN 12.2, P1-P3) on synthetic problems of the `bd-network` size: 3 plants + 2 DCs,
3,000 keys, 26 weeks (DRP); 5 nodes x 60 families x 18 months (S&OP LP). Run: `pytest -m slow -s tests/network`."""

from __future__ import annotations

import random
import resource
import time
from datetime import date, timedelta

import pytest

from superplanner.mfg.network.engine import solve
from superplanner.mfg.network.model import (NetCap, NetDemand, NetItem, NetLane, NetLoad, NetNode, NetProblem,
                                            NetRule, NetSupply)
from superplanner.mfg.network.validator import validate
from superplanner.mfg.sop import lp
from superplanner.mfg.sop.model import SopBuy, SopLane, SopProblem
from superplanner.mfg.sop.validator import validate as sop_validate

AS_OF = date(2026, 11, 30)


def drp_problem(keys: int = 3000) -> NetProblem:
    rnd = random.Random(7)
    plants, dcs = ["P1", "P2", "P3"], ["D1", "D2"]
    nodes = [NetNode(p, p, "plant") for p in plants] + [NetNode(d, d, "dc") for d in dcs]
    items, demand, supply, rules, load, cap = [], [], [], [], [], []
    lanes = [NetLane(f"{p}>{d}", p, d, "road", rnd.randint(1, 4)) for p in plants for d in dcs]
    weeks = [AS_OF + timedelta(days=7 * k) for k in range(26)]
    for k in range(keys):
        key = f"K{k:05d}"
        fam = f"F{k % 60:02d}"
        a, b = plants[k % 3], plants[(k + 1) % 3]
        for n in plants + dcs:
            items.append(NetItem(n, key, f"i{n}{k}", fam, ss=50.0 if n in dcs else 0.0, lead_days=7,
                                 order_multiple=10.0))
        for d in dcs:
            if k % 4 == 0:
                rules += [NetRule(f"r{d}{k}a", d, key, None, "plant", a, None, 1, 60.0, None),
                          NetRule(f"r{d}{k}b", d, key, None, "plant", b, None, 2, 40.0, None)]
            else:
                rules += [NetRule(f"r{d}{k}a", d, key, None, "plant", a, None, 1, None, None),
                          NetRule(f"r{d}{k}b", d, key, None, "plant", b, None, 2, None, None)]
            for w in weeks:
                demand.append(NetDemand(d, key, w, float(rnd.randint(0, 40)), "forecast", f"FC:{d}:{key}:{w}"))
            supply.append(NetSupply(d, key, AS_OF, float(rnd.randint(0, 200)), "stock", f"B{d}{k}"))
        for p in (a, b):
            load.append(NetLoad(p, f"G{k % 20}", key, 0.01))
    for p in plants:
        for g in range(20):
            for w in weeks:
                cap.append(NetCap(p, f"G{g}", w, 80.0))
    return NetProblem(AS_OF, 26, True, 4, 14, nodes, items, demand, supply, rules, lanes, [], cap, load)


@pytest.mark.slow
def test_p1_p2_drp_engine_and_validator():
    p = drp_problem()
    t0 = time.monotonic()
    res = solve(p)
    t1 = time.monotonic()
    rep = validate(p, res)
    t2 = time.monotonic()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"\nP1 engine {t1 - t0:.1f} s ({len(res.transfers)} transfers, {len(res.production)} production, "
          f"{len(res.shortages)} shortages); P2 validator {t2 - t1:.1f} s; max RSS {rss:.0f} MB; ok={rep['ok']}")
    assert rep["ok"], rep["violations"][:5]
    assert t1 - t0 < 30 and t2 - t1 < 10


def sop_problem() -> SopProblem:
    rnd = random.Random(3)
    months = [date(2027 + (m // 12), m % 12 + 1, 1) for m in range(18)]
    nodes, fams = ["P1", "P2", "P3", "D1", "D2"], [f"F{k:02d}" for k in range(60)]
    demand, hours, hpu, conv, std = {}, {}, {}, {}, {}
    make = set()
    for f in fams:
        for d in ("D1", "D2"):
            for t in months:
                demand[(d, f, t)] = float(rnd.randint(500, 3000))
        for p in ("P1", "P2", "P3"):
            make.add((p, f))
            hpu[(p, f"G{int(f[1:]) % 10}", f)] = 0.01 + rnd.random() * 0.01
            conv[(p, f)] = 1.0 + rnd.random()
            std[(p, f)] = 2.0
        std[("D1", f)] = std[("D2", f)] = 2.0
    for p in ("P1", "P2", "P3"):
        for g in range(10):
            for t in months:
                hours[(p, f"G{g}", t)] = 400.0
    lanes = [SopLane(f"{p}>{d}", p, d, 0, 0.05) for p in ("P1", "P2", "P3") for d in ("D1", "D2")]
    buys = [SopBuy("D1", f, "EXT", 4.0, 500.0) for f in fams[:20]]
    return SopProblem(months, nodes, fams, demand, {}, {}, {(d, f): 200.0 for d in ("D1", "D2") for f in fams},
                      hours, hpu, frozenset(make), conv, std, buys, lanes)


@pytest.mark.slow
def test_p3_sop_lp_three_solves_and_validator():
    p = sop_problem()
    t0 = time.monotonic()
    r = lp.solve(p)
    t1 = time.monotonic()
    rep = sop_validate(p, r)
    t2 = time.monotonic()
    print(f"\nP3 LP {t1 - t0:.1f} s (status {r.status}, unmet {sum(r.unmet.values()):.0f}) + validator "
          f"{t2 - t1:.2f} s; ok={rep['ok']}")
    assert r.status == "optimal" and rep["ok"], rep["violations"][:5]
    assert t2 - t0 < 30
