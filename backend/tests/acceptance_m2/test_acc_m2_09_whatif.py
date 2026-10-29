"""Gate 2 #9: what-if. On `kavach` (anchor = the Monday on or before today, so the live run is current) a run that
delays one FPGA schedule by +30 days is a `what_if` run; compare (live vs what-if) shows exactly the demand deltas
the oracle predicts from the same snapshot; the live run stays the latest live run and the live data (the PO
schedule) is unchanged; a staleness banner appears only after a real data change.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from accm2_helpers import MRP_ENDPOINTS, need_module
from oracle import run_oracle
from oracle.adapters import Unavailable, find_cls, snapshot_to_oplant


def test_fpga_delay_what_if_and_compare(api, app):
    api.need(*MRP_ENDPOINTS, "POST /samples/{sample_id}/load", "GET /mrp/runs/{run_id}/compare",
             "GET /mrp/runs/latest")
    api.load("kavach", anchor=None)
    live = api.run_mrp(label="live")
    assert live["kind"] == "live" and live["stale"]["is_stale"] is False
    po = api.doc("/purchase-orders", "PO-KV-0101")
    s1 = min(po["lines"][0]["schedules"], key=lambda s: s["seq"])
    new_dock = (date.fromisoformat(s1["dock_date"]) + timedelta(days=30)).isoformat()
    wi = api.run_mrp(label="FPGA +30", supply_date_overrides=[{"schedule_id": s1["id"], "date": new_dock}])
    assert wi["kind"] == "what_if"
    cmp = api.get(f"/mrp/runs/{live['id']}/compare", **{"with": wi["id"]})
    deltas = {d["demand_line_id"]: d["delta_days"] for d in cmp["demand"]}
    assert deltas and all(v > 0 for v in deltas.values()), cmp["demand"]
    # the oracle on the same snapshot predicts exactly these changed lines and deltas
    try:
        repo_m2 = need_module("superplanner.api.mfg.repo_m2", "load_mrp_snapshot")
        MrpParams = find_cls("MrpParams")
    except Unavailable as exc:
        pytest.skip(str(exc))
    from superplanner.api.db.ownership import LOCAL_USER_ID, owner_scope

    with owner_scope(LOCAL_USER_ID), repo_m2.snapshot_tx(app.state.ctx.db) as s:
        snap = repo_m2.load_mrp_snapshot(s, date.fromisoformat(live["as_of"]))
    base = run_oracle(snapshot_to_oplant(snap, MrpParams.model_validate({})))
    what = run_oracle(snapshot_to_oplant(snap, MrpParams.model_validate(
        {"supply_date_overrides": [{"schedule_id": s1["id"], "date": new_dock}]})))
    b = {dp.key[1]: dp.projected_date for dp in base.demand}
    w = {dp.key[1]: dp.projected_date for dp in what.demand}
    expected = {k: (w[k] - b[k]).days for k in b if w[k] != b[k]}
    assert deltas == expected
    # live run and live data unchanged
    assert api.get("/mrp/runs/latest")["id"] == live["id"]
    po2 = api.doc("/purchase-orders", "PO-KV-0101")
    assert min(po2["lines"][0]["schedules"], key=lambda s: s["seq"])["dock_date"] == s1["dock_date"]
    assert api.get(f"/mrp/runs/{live['id']}")["stale"]["is_stale"] is False
    # a real change makes the live run stale (transactions_changed), never blocks reading
    loc = api.by_code("/locations", "STORES-MAIN")
    api.post_stock(api.item("KV-MOD-GSM")["id"], loc["id"], 1, lot="ACC-STALE")
    st = api.get(f"/mrp/runs/{live['id']}")["stale"]
    assert st["is_stale"] and st["transactions_changed"] and not st["master_changed"]
