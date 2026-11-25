"""M8-DESIGN 14.1: sample `meddev_m8` = meddev + the M8 planning layer (history, forecast with overrides, SS
proposals, flow lines with a published rate plan, EtO loads with one awaiting release, kanban loops)."""

from __future__ import annotations

import pytest


@pytest.mark.req("M8-SAMPLE-01")
def test_meddev_m8_sample(api):
    out = api.load("meddev_m8")
    assert out["health"]["ok"] is True
    m8 = out["result"]["after_load_m8"]
    assert "error" not in m8, m8
    hist = api.get("/forecast/history", limit=2000)
    assert hist["total"] >= 6 * 30
    act = api.get("/forecast/versions", status="active")["items"]
    assert len(act) == 1 and act[0]["override_count"] == 3
    run = api.get("/forecast/runs")["items"][0]
    res = {x["part_number"]: x for x in api.get(f"/forecast/runs/{run['id']}", limit=50)["results"]["items"]}
    assert res["MDV-SYR-03"]["method"] in ("hw_add", "hw_mul", "snaive", "holt_damped")
    assert "FC_LIKE_ITEM" in res["MDV-SYR-10"]["flags"]
    assert res["MDV-IVC-22"]["demand_class"] in ("intermittent", "lumpy")
    ss = api.get("/invopt/runs")["items"][0]
    assert ss["status"] == "completed" and ss["summary"]["pending"] >= 5
    rr = api.get("/rate/runs")["items"][0]
    assert rr["published"] is True and rr["validator"]["ok"], rr
    assert api.get(f"/rate/runs/{rr['id']}/grid")["cells"]
    loads = api.get("/ster/loads", limit=200)["items"]
    assert loads and any(x["status"] == "awaiting_release" for x in loads)
    loops = api.get("/kanban/loops")["items"]
    assert len(loops) == 2 and sum(lp["card_counts"]["empty"] for lp in loops) == 1
    assert {x["label"] for x in api.get("/mrp/runs")["items"]} >= {"nightly-1", "nightly-2"}
