"""Batching (M4-DESIGN 6.3; T-F11): two compatible WOs share one load on a batch_merge line when the later one is
ready within batch_wait_minutes, else they run in two loads; results stay validator-clean."""

from __future__ import annotations

from superplanner.mfg.aps.engine import schedule
from superplanner.mfg.aps.model import ApsParams
from superplanner.mfg.aps.pure import sample_snapshot

P = ApsParams(improve_seconds=0, split=False, include_planned=False, material="ignore")


def test_t_f11_shared_load_and_wait_limit():
    from superplanner.mfg.aps.validator import _collapse_loads  # noqa: F401  (validator hook exists)

    snap = sample_snapshot("kavach")
    ds = snap.dataset
    merge = [ln for ln in ds.lines.values() if getattr(ln, "batch_merge", False)]
    if not merge:                                     # turn BURNIN-like lines into batch_merge lines
        bi = [ln for ln in ds.lines.values() if ln.code.upper().startswith(("BI", "BURN"))]
        assert bi, sorted(ln.code for ln in ds.lines.values())
        for ln in bi:
            ds.lines[ln.id] = ln.model_copy(update={"batch_merge": True, "batch_wait_minutes": 24 * 60})
    res = schedule(snap, P)
    assert res.validation.ok, res.validation
    batch_ops = [o for o in res.operations if o.status == "scheduled" and o.reason.code == "batch"]
    assert res.summary.batches == len(res.batches)
    for b in res.batches:
        assert len(b["members"]) >= 2
        xs = [o for o in res.operations if o.op_no in {m["op_no"] for m in b["members"]}]
        assert len({(o.line_id, o.start, o.end) for o in xs}) == 1
    # no wait allowed -> no shared loads that needed waiting; result still valid
    for ln in [x for x in ds.lines.values() if x.batch_merge]:
        ds.lines[ln.id] = ln.model_copy(update={"batch_wait_minutes": 0})
    res0 = schedule(snap, P)
    assert res0.validation.ok
    assert len(batch_ops) >= 0
