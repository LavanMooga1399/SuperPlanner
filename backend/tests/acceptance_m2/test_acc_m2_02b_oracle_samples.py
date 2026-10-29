"""Gate 2 #2 (sample part): on `small`, `medium` and `kavach` (master + transactions, anchor 2026-11-02) the engine
equals the oracle. The snapshot is the one the API plans from (`repo_m2.load_mrp_snapshot` inside
`repo_m2.snapshot_tx`), so loading, snapshotting and planning are all on the real path; both allocation policies
and both alternates modes are compared.
"""

from __future__ import annotations

import warnings
from datetime import date

import pytest

from accm2_helpers import need_module
from oracle import run_oracle
from oracle.adapters import Unavailable, diff_canon, engine, engine_canon, find_cls, oracle_canon, snapshot_to_oplant

ANCHOR = date(2026, 11, 2)


def _snapshot(app, as_of: date):
    repo_m2 = need_module("superplanner.api.mfg.repo_m2", "load_mrp_snapshot")
    from superplanner.api.db.ownership import LOCAL_USER_ID, owner_scope

    with owner_scope(LOCAL_USER_ID), repo_m2.snapshot_tx(app.state.ctx.db) as s:
        return repo_m2.load_mrp_snapshot(s, as_of)


@pytest.mark.parametrize("sample", ["small", "medium", "kavach"])
def test_engine_equals_oracle_on_samples(api, app, sample):
    api.need("POST /samples/{sample_id}/load")
    try:
        eng = engine()
        MrpParams = find_cls("MrpParams")
    except Unavailable as exc:
        pytest.skip(f"MRP engine not available yet: {exc}")
    api.load(sample)
    snap = _snapshot(app, ANCHOR)
    for body in ({}, {"allocation": "due_date"}, {"alternates": "never"}):
        params = MrpParams.model_validate(body)
        plant = snapshot_to_oplant(snap, params)
        got = engine_canon(eng.run_mrp(snap, params), plant)
        want = oracle_canon(run_oracle(plant), plant)
        diffs = diff_canon(got, want)
        strict = diffs.pop("pegs", None)
        if strict and "pegs_tie" not in diffs:
            warnings.warn(f"{sample} {body}: strict peg pairs differ only among exact ties: {strict[:5]}")
        assert not diffs, f"{sample} {body}\n" + "\n".join(f"[{k}] {x}" for k, v in diffs.items() for x in v)
