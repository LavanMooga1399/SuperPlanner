"""Gate 2 #2 (pure part): `superplanner.mfg.mrp.run_mrp` equals the independent oracle on the 8.15 hand vectors and
200 seeded random plants: identical planned orders (item, kind, qty, need/start dates, segment), identical peg
quantities per (requirement, supply) pair, identical demand projected dates. (The `small`/`medium`/`kavach`
samples are compared through the database snapshot in `test_acc_m2_02b_oracle_samples.py`.)

Peg pairs are compared twice: `pegs_tie` aggregates requirements with equal (item, rank, need_date) and supplies
with equal (item, kind, avail_date, expiry) - the order among exact ties depends on node numbering, which 8.8 uses
as the last sort key but does not define. `pegs_tie` must match; strict `pegs` differences are reported as
warnings (a spec ambiguity, not an engine defect) unless the tie view differs too.

Skips (naming the missing module/class) until WP-E/WP-A provide the contract of 8.2/3.
"""

from __future__ import annotations

import warnings

import pytest

from oracle import run_oracle
from oracle import vectors as V
from oracle.adapters import (ContractMismatch, Unavailable, diff_canon, engine, engine_canon, oplant_to_snapshot,
                             oracle_canon)
from oracle.randplant import random_plant

SEEDS = range(200)


def _engine_or_skip():
    try:
        return engine()
    except Unavailable as exc:
        pytest.skip(f"MRP engine not available yet: {exc}")


def compare(plant, label: str) -> None:
    eng = _engine_or_skip()
    try:
        snap, params = oplant_to_snapshot(plant)
    except Unavailable as exc:
        pytest.skip(f"M2 contract types not available yet: {exc}")
    result = eng.run_mrp(snap, params)
    expected = run_oracle(plant)
    got = engine_canon(result, plant)
    want = oracle_canon(expected, plant)
    diffs = diff_canon(got, want)
    strict = diffs.pop("pegs", None)
    if strict and "pegs_tie" not in diffs:
        warnings.warn(f"{label}: strict peg pairs differ only among exact ties (node order): {strict[:5]}")
    assert not diffs, f"{label}: engine != oracle\n" + "\n".join(f"[{k}] {x}" for k, v in diffs.items() for x in v)


@pytest.mark.parametrize("name", sorted(V.ALL))
def test_engine_equals_oracle_on_hand_vectors(name):
    compare(V.ALL[name]().plant, name)


@pytest.mark.parametrize("seed", SEEDS)
def test_engine_equals_oracle_on_random_plants(seed):
    compare(random_plant(seed), f"seed {seed}")


def test_engine_is_deterministic_on_a_random_plant():
    """P10 / T-M14 (pure part): same inputs -> identical canonical result (two runs, fresh snapshots)."""
    eng = _engine_or_skip()
    plant = random_plant(7)
    try:
        a = engine_canon(eng.run_mrp(*oplant_to_snapshot(plant)), plant)
        b = engine_canon(eng.run_mrp(*oplant_to_snapshot(random_plant(7))), plant)
    except Unavailable as exc:
        pytest.skip(f"M2 contract types not available yet: {exc}")
    assert a == b


def test_adapter_round_trip_keeps_every_oracle_input():
    """snapshot_to_oplant(oplant_to_snapshot(p)) gives the oracle the same answer as p (guards the adapters, so a
    comparison failure is never an adapter artefact). Needs only the contract types, not the engine."""
    from oracle.adapters import snapshot_to_oplant

    for seed in SEEDS:
        plant = random_plant(seed)
        try:
            snap, params = oplant_to_snapshot(plant)
        except Unavailable as exc:
            pytest.skip(f"M2 contract types not available yet: {exc}")
        except ContractMismatch:
            raise
        back = snapshot_to_oplant(snap, params)
        assert oracle_canon(run_oracle(back), back) == oracle_canon(run_oracle(plant), plant), seed


def test_oracle_invariants_on_random_plants():
    """T-M15 invariants on the oracle itself (runs today): every requirement fully pegged, no supply over-pegged,
    planned qty >= the residuals pegged to it, deterministic."""
    for seed in SEEDS:
        a = run_oracle(random_plant(seed))
        for rs in a.requirements.values():
            for r in rs:
                assert abs(r.pegged - r.qty) < 1e-6, (seed, r)
        for ss in a.supplies.values():
            for s in ss:
                assert s.pegged <= s.qty + 1e-6, (seed, s)
        b = run_oracle(random_plant(seed))
        assert oracle_canon(a, random_plant(seed)) == oracle_canon(b, random_plant(seed)), seed
