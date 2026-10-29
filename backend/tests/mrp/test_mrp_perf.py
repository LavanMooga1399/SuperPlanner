"""M2-DESIGN 15 MP1-MP3: pure `run_mrp` on the Kavach-scale scenario (incl. the alternates pass).
Measured numbers are printed (`pytest -s`) and recorded as test properties."""

from __future__ import annotations

import time

import pytest

from mrp_kavach_helpers import kavach_snapshot
from superplanner.mfg.mrp import MrpParams, run_mrp

CASES = {
    "MP1": ({}, None, 1.5),                                    # kavach sample: 7 lines (37 units + spares)
    "MP2": ({"extra_lines": 50}, 210, 5.0),                    # + 50 synthetic lines, distinct serials, 180 days
    "MP3": ({"factor": 2, "extra_lines": 100}, 210, 10.0),     # kavach x2 + 100 lines
}


@pytest.mark.slow
@pytest.mark.parametrize("case", sorted(CASES))
def test_mrp_performance(case, record_property):
    kw, horizon, target = CASES[case]
    snap = kavach_snapshot(**kw)
    t0 = time.perf_counter()
    r = run_mrp(snap, MrpParams(horizon_days=horizon))
    secs = time.perf_counter() - t0
    bom_lines = sum(len(b.lines) for b in snap.dataset.boms.values())
    record_property("seconds", round(secs, 3))
    print(f"\n{case}: {secs:.2f} s (target < {target} s); bom lines {bom_lines}, demand lines {r.summary.demand_lines},"
          f" requirements {r.summary.requirements}, planned make {r.summary.planned_make} / buy "
          f"{r.summary.planned_buy}, iterations {r.iterations}")
    assert r.iterations == 2                    # the alternates pass ran
    assert secs < target
