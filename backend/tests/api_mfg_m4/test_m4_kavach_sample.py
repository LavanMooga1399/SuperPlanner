"""Kavach M4 sample (M4-DESIGN 14): flags, floor history and the pinned dashboard outcomes."""

from __future__ import annotations

import time

SERIALS = 35          # ICT good of the three history WOs (yield-inflated inputs 12 / 12 / 12, one scrapped)
FPY = 70 / 73         # plant: ICT 35 / 36 and FCT 35 / 37 (two rework loops)

from apimfgm3_helpers import wait_run


def test_kavach_m4_sample(api):
    api.load("kavach")
    pl = api.get("/plant")
    assert pl["wo_receipt_location_id"] and pl["backflush_location_id"]
    lines = {ln["code"]: ln for ln in api.get("/lines", limit=200)["items"]}
    assert lines["BI-1"]["batch_merge"] and lines["SMT-2"]["location_id"] == pl["backflush_location_id"]
    hist = [w for w in api.get("/work-orders", q="WO-KV-H", limit=50)["items"]]
    assert len(hist) == 3 and {w["status"] for w in hist} == {"closed"}
    assert api.get("/floor/events", limit=1)["total"] > 50
    n_ser = api.get("/serials")["total"]
    k = api.get("/kpis")
    m = k["metrics"]
    print("KAVACH M4 KPIs", n_ser, {x: (m[x]["value"], m[x]["num"], m[x]["den"]) for x in
                                   ("otd", "fpy", "availability", "utilisation", "scrap_rate")})
    assert n_ser == SERIALS
    assert m["otd"]["value"] == 0.5 and m["otd"]["den"] == 2          # DO-KV-H02 shipped 3 days late
    assert abs(m["fpy"]["value"] - FPY) < 1e-6
    ict = api.get("/kpis", dim="line", dim_id=lines["ICT-1"]["id"])["metrics"]["fpy"]
    assert (ict["num"], ict["den"]) == (35, 36)                        # ICT FPY 0.972
    smt2 = api.get("/kpis", dim="line", dim_id=lines["SMT-2"]["id"])["metrics"]["availability"]["value"]
    smt1 = api.get("/kpis", dim="line", dim_id=lines["SMT-1"]["id"])["metrics"]["availability"]["value"]
    assert smt2 < smt1
    # the risk run names the FPGA supplier as the top contributor (its late-receipt history)
    api.post("/mrp/runs", {})
    run = wait_run(api, api.post("/aps/runs", {"improve_seconds": 0}, status=202)["id"])
    assert run["status"] == "completed" and run["validation"]["ok"], run.get("validation")
    sim = api.post("/aps/simulations", {"base_run_id": run["id"], "samples": 5, "seed": 1}, status=202)
    while (x := api.get(f"/aps/simulations/{sim['id']}"))["status"] in ("queued", "running"):
        time.sleep(0.3)
    sups = x["results"]["suppliers"]
    print("KAVACH M4 suppliers", [(y["supplier"]["code"], y["late_lines"], y["history_receipts"]) for y in sups][:4])
    # pinned (recorded in 16.WP-S): SUP-SEMI-2 holds the open FPGA PO (PO-KV-0101) and, with fewer than 5 own
    # receipts, draws from the plant-wide history (SUP-SEMI-1's late FPGA receipts) -> the FPGA supplier on top
    assert sups[0]["supplier"]["code"] == "SUP-SEMI-2" and sups[0]["late_lines"] >= 1   # (as_of = now: 4-5)
    assert next(y for y in sups if y["supplier"]["code"] == "SUP-SEMI-1")["history_receipts"] == 6
