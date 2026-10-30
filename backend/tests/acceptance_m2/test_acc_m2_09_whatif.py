"""Gate 2 #9: what-if. On `kavach` (anchor = the Monday on or before today, so the live run is current) a run that
delays one FPGA schedule (PO-KV-0101) by +30 days is a `what_if` run; compare (live vs what-if) shows exactly the
demand deltas the oracle predicts from the same snapshot; the live run stays the latest live run and the live
data (the PO schedule) is unchanged; a staleness banner appears only after a real data change.

The schedule is chosen with the oracle: the first PO-KV-0101 schedule whose delay changes any demand projection
(on the pinned sample schedule 1 is not on a critical path, so +30 days on it changes nothing).
"""

from __future__ import annotations

from datetime import date, timedelta

from accm2_helpers import MRP_ENDPOINTS, need_module
from oracle import run_oracle
from oracle.adapters import find_cls, snapshot_to_oplant


def test_fpga_delay_what_if_and_compare(api, app):
    api.need(*MRP_ENDPOINTS, "POST /samples/{sample_id}/load", "GET /mrp/runs/{run_id}/compare",
             "GET /mrp/runs/latest")
    repo_m2 = need_module("superplanner.api.mfg.repo_m2", "load_mrp_snapshot")
    MrpParams = find_cls("MrpParams")
    from superplanner.api.db.ownership import LOCAL_USER_ID, owner_scope

    api.load("kavach", anchor=None)
    live = api.run_mrp(label="live")
    assert live["kind"] == "live" and live["stale"]["is_stale"] is False
    with owner_scope(LOCAL_USER_ID), repo_m2.snapshot_tx(app.state.ctx.db) as s:
        snap = repo_m2.load_mrp_snapshot(s, date.fromisoformat(live["as_of"]))
    base = {dp.key[1]: dp.projected_date for dp in run_oracle(snapshot_to_oplant(snap, MrpParams.model_validate({})))
            .demand}
    po = api.doc("/purchase-orders", "PO-KV-0101")
    chosen = None
    for sc in sorted(po["lines"][0]["schedules"], key=lambda s: s["seq"]):
        if sc["open_qty"] <= 0:
            continue
        new_dock = (date.fromisoformat(sc["dock_date"]) + timedelta(days=30)).isoformat()
        what = run_oracle(snapshot_to_oplant(snap, MrpParams.model_validate(
            {"supply_date_overrides": [{"schedule_id": sc["id"], "date": new_dock}]})))
        w = {dp.key[1]: dp.projected_date for dp in what.demand}
        expected = {k: (w[k] - base[k]).days for k in base if w[k] != base[k]}
        if expected:
            chosen = (sc, new_dock, expected)
            break
    assert chosen, "no PO-KV-0101 schedule delay changes any demand line (oracle) - sample cannot show #9"
    sc, new_dock, expected = chosen
    wi = api.run_mrp(label="FPGA +30", supply_date_overrides=[{"schedule_id": sc["id"], "date": new_dock}])
    assert wi["kind"] == "what_if"
    cmp = api.get(f"/mrp/runs/{live['id']}/compare", **{"with": wi["id"]})
    deltas = {d["demand_line_id"]: d["delta_days"] for d in cmp["demand"]}
    assert deltas == expected, (deltas, expected)
    assert all(v > 0 for v in deltas.values())
    # live run and live data unchanged
    assert api.get("/mrp/runs/latest")["id"] == live["id"]
    po2 = api.doc("/purchase-orders", "PO-KV-0101")
    assert {s["id"]: s["dock_date"] for s in po2["lines"][0]["schedules"]} == \
        {s["id"]: s["dock_date"] for s in po["lines"][0]["schedules"]}
    assert api.get(f"/mrp/runs/{live['id']}")["stale"]["is_stale"] is False
    # a real change makes the live run stale (transactions_changed), never blocks reading
    loc = api.by_code("/locations", "STORES-MAIN")
    api.post_stock(api.item("KV-MOD-GSM")["id"], loc["id"], 1, lot="ACC-STALE")
    st = api.get(f"/mrp/runs/{live['id']}")["stale"]
    assert st["is_stale"] and st["transactions_changed"] and not st["master_changed"]
