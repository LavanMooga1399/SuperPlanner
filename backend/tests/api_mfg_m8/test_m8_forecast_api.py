"""S1 API (M8-DESIGN 4, 11 F1-F17): history refresh/cleaning, forecast run -> draft version, overrides with audit,
activation archives the previous version, item view, accuracy."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

import numpy as np
import pytest

from m8_helpers import add_history, audit_rows, wait_for


def _setup(api, client):
    items = {}
    for pn, fam in (("SYR-3", "SYR"), ("SYR-5", "SYR"), ("NDL-21", "NDL")):
        it = api.item(pn, "make", family=fam, lead_time_days=5, standard_cost=0.1)
        api.put(f"/items/{it['id']}/planning", {"replenishment": "mrp", "forecast": True}, 0)
        items[pn] = it
    t = np.arange(30)
    start = date(2024, 5, 1)
    add_history(client, items["SYR-3"]["id"], list(10000 + 50 * t + 2500 * np.cos(2 * np.pi * t / 12)), start)
    add_history(client, items["SYR-5"]["id"], list(4000 + 0 * t + 800 * np.cos(2 * np.pi * t / 12)), start)
    vals = [3000.0] * 30
    vals[20] = 30000.0                                            # outlier (10 x median)
    add_history(client, items["NDL-21"]["id"], vals, start, source="import")
    return items


def _run(api):
    r = api.post("/forecast/runs", {"label": "t", "as_of": "2026-11-25", "horizon_periods": 6}, 202)
    run = wait_for(lambda: api.get(f"/forecast/runs/{r['id']}"), lambda x: x["status"] in ("completed", "failed"))
    assert run["status"] == "completed", run
    return run


@pytest.mark.req("M8-FC-04", "M8-FC-05", "M8-FC-06")
def test_forecast_run_versions_overrides_activate(api, client):
    items = _setup(api, client)
    hist = api.get("/forecast/history", item_id=items["NDL-21"]["id"])
    assert hist["total"] == 30
    run = _run(api)
    assert run["item_count"] == 3 and run["first_period"] == "2026-11-01"
    res = {x["item_id"]: x for x in run["results"]["items"]}
    assert "FC_OUTLIER" in res[items["NDL-21"]["id"]]["flags"]
    assert res[items["SYR-3"]["id"]]["abc"] == "A"
    v1 = api.get(f"/forecast/versions/{run['version_id']}")
    assert v1["status"] == "draft" and v1["periods"] == 6 and v1["item_count"] == 3
    lines = {x["item_id"]: x for x in api.get(f"/forecast/versions/{v1['id']}/lines")["items"]}
    syr3, syr5 = lines[items["SYR-3"]["id"]], lines[items["SYR-5"]["id"]]
    assert "name" in syr3 and syr3["holdout_wape"] is not None and isinstance(syr3["flags"], list)
    assert "FC_OUTLIER" in lines[items["NDL-21"]["id"]]["flags"]
    # M8-FC-05: family +10 %, then item absolute 5,000 for one period
    o1 = api.post(f"/forecast/versions/{v1['id']}/overrides", {"item_family": "SYR", "period_from": "2026-11-01",
                                                                "period_to": "2027-04-01", "mode": "pct", "value": 10,
                                                                "reason": "Flu season"})
    assert len(o1["changes"]) == 12
    o2 = api.post(f"/forecast/versions/{v1['id']}/overrides", {"item_id": items["SYR-5"]["id"],
                                                                "period_from": "2026-12-01", "period_to": "2026-12-01",
                                                                "mode": "abs", "value": 5000, "reason": "Tender"})
    assert o2["changes"] == [{"item_id": items["SYR-5"]["id"], "period_start": "2026-12-01",
                              "old": pytest.approx(syr5["stat"][1] * 1.1, rel=1e-6), "new": 5000.0}]
    after = {x["item_id"]: x for x in api.get(f"/forecast/versions/{v1['id']}/lines")["items"]}
    assert after[items["SYR-3"]["id"]]["final"] == pytest.approx([v * 1.1 for v in syr3["stat"]], rel=1e-6)
    assert after[items["SYR-5"]["id"]]["final"][1] == 5000.0
    assert after[items["NDL-21"]["id"]]["final"] == after[items["NDL-21"]["id"]]["stat"]
    ev = audit_rows(client, "forecast_override", o2["id"])
    assert ev[0]["reason"] == "Tender" and ev[0]["details"]["changes"][0]["new"] == 5000.0
    # remove o2 needs a reason (header); final goes back to family +10 %
    api.err("DELETE", f"/forecast/overrides/{o2['id']}", 422, "VALIDATION_ERROR")
    r = api.req("DELETE", f"/forecast/overrides/{o2['id']}", 200, headers={"X-SP-Change-Reason": quote("Withdrawn")})
    assert r.json()["changes"][0]["new"] == pytest.approx(syr5["stat"][1] * 1.1, rel=1e-6)
    # M8-FC-06: activate v1; a second run's version activated archives v1
    assert api.get(f"/forecast/versions/{v1['id']}")["row_version"] == v1["row_version"] + 3   # 2 adds, 1 remove
    api.err("POST", f"/forecast/versions/{v1['id']}/activate", 412, "VERSION_MISMATCH", headers={"If-Match": '"1"'})
    v1 = api.post(f"/forecast/versions/{v1['id']}/activate", None, 200, version=v1["row_version"] + 3)
    assert v1["status"] == "active"
    api.err("POST", f"/forecast/versions/{v1['id']}/overrides", 409, "FC_VERSION_LOCKED",
            json={"item_family": "SYR", "period_from": "2026-11-01", "period_to": "2026-11-01", "mode": "pct",
                  "value": 1, "reason": "x"})
    run2 = _run(api)
    v2 = api.get(f"/forecast/versions/{run2['version_id']}")
    assert v2["override_count"] == 1                     # copied from the active version (o1 only)
    api.post(f"/forecast/versions/{v2['id']}/activate", None, 200)
    assert api.get(f"/forecast/versions/{v1['id']}")["status"] == "archived"
    assert [x["id"] for x in api.get("/forecast/versions", status="active")["items"]] == [v2["id"]]
    # MRP uses the new active version (forecast requirements carry its id)
    mrp = api.post("/mrp/runs", {"label": "fc", "horizon_days": 120}, None)
    assert mrp["status"] == "completed", mrp
    plan = api.get(f"/mrp/runs/{mrp['id']}/items/{items['SYR-3']['id']}")
    fc = [r for r in plan["requirements"] if r["kind"] == "forecast"]
    assert fc and {r["source"]["id"].split(":")[0] for r in fc} == {v2["id"]}
    # item view and accuracy answer
    view = api.get(f"/forecast/items/{items['SYR-3']['id']}")
    assert view["result"]["method"] and view["consumption"] and len(view["history"]) == 30
    acc = api.get("/forecast/accuracy", lag=1, group_by="abc")
    assert acc["backtest"]["by_abc"]["A"]["items"] >= 1
    assert len(acc["trend"]) == 6 and {"period_start", "wape", "bias"} <= set(acc["trend"][0])
    tiles = api.get("/dashboard")["tiles"]
    assert {"forecast_accuracy", "rate_shortages", "ster_release"} <= set(tiles)
    assert tiles["rate_shortages"]["status"] == "n/a" and tiles["ster_release"]["value"] == 0


@pytest.mark.req("M8-FC-04")
def test_history_reset_restores_outlier(api, client):
    items = _setup(api, client)
    api.post("/forecast/history/refresh", None, 200)
    rows = api.get("/forecast/history", item_id=items["NDL-21"]["id"])["items"]
    hit = [r for r in rows if r["qty"] == 30000.0]
    assert hit and hit[0]["outlier"] and 3000.0 < hit[0]["cleaned_qty"] < 10000.0   # clipped to the 5-MAD bound
    out = api.put(f"/forecast/history/{hit[0]['id']}", {"cleaned_qty": None, "reason": "Real tender"}, 0)
    assert out["cleaned_qty"] == 30000.0 and out["outlier"] is False
    run = _run(api)
    res = {x["item_id"]: x for x in run["results"]["items"]}
    assert "FC_OUTLIER" not in res[items["NDL-21"]["id"]]["flags"]
