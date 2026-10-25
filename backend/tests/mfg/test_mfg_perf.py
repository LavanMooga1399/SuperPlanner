"""Performance of the pure core (M1-DESIGN 12 P1; PLAN-M1 A2-5, A3-5). Best of three runs."""

from __future__ import annotations

import time
from datetime import date

from superplanner.mfg import BomIndex, bundle_to_dataset, explode, run_health_check, samples

AS_OF = date(2026, 11, 2)


def best(fn, n: int = 3) -> float:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return min(out)


def test_p1_pure_explode_kavach_and_x2():
    ds = bundle_to_dataset(samples.build("kavach"))
    idx = BomIndex.from_dataset(ds, AS_OF)
    root = ds.items_by_pn["KV-TPU-1000"].id
    assert best(lambda: explode(idx, root)) < 0.15
    ds2 = bundle_to_dataset(samples.scale("kavach", 2))
    idx2 = BomIndex.from_dataset(ds2, AS_OF)
    roots = [ds2.items_by_pn["KV-TPU-1000"].id, ds2.items_by_pn["KV2-TPU-1000"].id]
    rows = []
    assert best(lambda: rows.append(sum(explode(idx2, r).totals.rows for r in roots))) < 0.3
    assert rows[0] > 4900


def test_a3_5_health_check_on_kavach():
    ds = bundle_to_dataset(samples.build("kavach"))
    assert best(lambda: run_health_check(ds, AS_OF, 90), 2) < 1.0
