"""Kavach M3 sample (M3-DESIGN 13): pinned outcomes, AP1/AP2/AP7, determinism T-S15."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

import pytest

from superplanner.mfg.aps.engine import schedule
from superplanner.mfg.aps.model import ApsParams, canonical
from superplanner.mfg.aps.pure import sample_snapshot
from superplanner.mfg.aps.validator import validate


@lru_cache(maxsize=1)
def _snap():
    return sample_snapshot("kavach")


@lru_cache(maxsize=4)
def _run(policy: str, improve: int = 0):
    return schedule(_snap(), ApsParams(overtime=policy, improve_seconds=improve))


def _code(ds, lid):
    return ds.lines[lid].code


def test_pinned_outcomes_off_suggest_allow():
    s = _snap()
    ds = s.dataset
    off, sug, allow = _run("off"), _run("suggest"), _run("allow")
    assert off.validation.ok and sug.validation.ok and allow.validation.ok
    assert not any(o.reason.code == "material_missing" for o in off.operations)          # all pegged
    late = [(d.order_number, d.line_no) for d in off.demand if d.late_minutes > 0]
    assert late == [("DO-KV-003", 10)]                # KV-PCB-CPU behind the FPGA buy (beyond the horizon)
    assert off.summary.late_demand_count == 1 and off.summary.unscheduled == {"beyond_horizon": 13}
    # suggest = off plan + suggested EVE windows with positive saved tardiness (FCT among them)
    assert [o.start for o in sug.operations] == [o.start for o in off.operations]
    sw = [w for w in sug.overtime if w.status == "suggested"]
    assert sw and all(w.tardiness_saved_minutes > 0 for w in sw)
    assert any(_code(ds, w.line_id).startswith("FCT") for w in sw) and all(w.orders for w in sw)
    assert allow.summary.weighted_tardiness < off.summary.weighted_tardiness and allow.summary.overtime_minutes > 0
    # SMT setups grouped by family: same-family changeovers dominate
    smt = sorted((o for o in off.operations if o.line_id and _code(ds, o.line_id).startswith("SMT")),
                 key=lambda o: (o.line_id, o.start))
    same = sum(1 for a, b in zip(smt, smt[1:]) if a.line_id == b.line_id and a.family == b.family)
    assert same > 0.7 * (len(smt) - 3)
    # the coating absence (A+7..A+11, two-person coating): COAT-1 work pauses - no piece in the leave, one
    # operation spans it
    from datetime import datetime, timedelta

    a7 = datetime(2026, 11, 9, tzinfo=s.tz)
    a12 = a7 + timedelta(days=5)
    coat = [o for o in off.operations if o.line_id and _code(ds, o.line_id) == "COAT-1"]
    assert not any(p.start < a12 and a7 < p.end for o in coat for p in o.pieces)
    assert any(o.start < a7 and o.end > a12 for o in coat)
    # WO-KV-0001 operations 10-40 are done (progress): not scheduled again
    assert {o.seq for o in off.operations if o.order.number == "WO-KV-0001"} == {50, 60, 70, 80, 90, 100, 110}


def test_ap1_construct_and_ap7_validator_times():
    s = _snap()
    t = time.monotonic()
    r = schedule(s, ApsParams(overtime="off", improve_seconds=0))
    assert time.monotonic() - t < 5.0
    t = time.monotonic()
    assert validate(s, r).ok
    assert time.monotonic() - t < 1.0


def test_ts15_determinism_in_process():
    a = schedule(_snap(), ApsParams(overtime="suggest", improve_seconds=4))
    b = schedule(_snap(), ApsParams(overtime="suggest", improve_seconds=4))
    assert canonical(a) == canonical(b) and a.summary.iterations > 0


@pytest.mark.slow
def test_ts15_determinism_across_hash_seeds_and_ap2():
    code = ("import hashlib,sys;from superplanner.mfg.aps.pure import sample_snapshot;"
            "from superplanner.mfg.aps.engine import schedule;from superplanner.mfg.aps.model import ApsParams,canonical;"
            "r=schedule(sample_snapshot('kavach'),ApsParams(overtime='suggest',improve_seconds=10));"
            "print(hashlib.sha256(canonical(r).encode()).hexdigest(), r.score[1])")
    root = Path(__file__).resolve().parents[2]
    outs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
        outs.append(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                   check=True, timeout=600).stdout.split())
    assert outs[0][0] == outs[1][0]
    assert float(outs[0][1]) <= _run("suggest").score[1]            # AP2: never worse than construction
