"""S3 (M3-DESIGN 10, 11): run lifecycle through the job queue, views, publish, copy_of escalation, edits."""

from __future__ import annotations

from apimfgm3_helpers import Api, im, wait_run


def _small(api: Api, **body):
    api.load("small")
    api.post("/mrp/runs", {})
    body.setdefault("improve_seconds", 0)
    run = api.post("/aps/runs", body, status=202)
    assert run["status"] == "queued" and run["progress"]["phase"] == "queued"
    return wait_run(api, run["id"])


def test_run_lifecycle_views_publish(api: Api):
    r = _small(api, overtime="off")
    assert r["status"] == "completed", r["error"]
    assert r["validation"]["ok"] and r["publishable"] and r["policy"] == "off", r
    rid = r["id"]
    s = r["summary"]
    assert s["operations"] > 0 and set(s["timings_ms"]) >= {"construct", "validate", "load", "store"}
    ops = api.get(f"/aps/runs/{rid}/operations", limit=200)
    assert ops["total"] == s["operations"] and ops["items"][0]["line"] is not None
    one = api.get(f"/aps/runs/{rid}/operations/{ops['items'][0]['op_no']}")
    assert one["op"]["op_no"] == ops["items"][0]["op_no"] and "neighbours" in one
    assert api.get(f"/aps/runs/{rid}/orders")["total"] == s["orders"]
    assert "items" in api.get(f"/aps/runs/{rid}/demand")
    g = api.get(f"/aps/runs/{rid}/gantt", **{"from": ops["items"][0]["start"]})
    assert g["bars"] and g["rows"][0]["kind"] == "group" and any(b["kind"] == "base" for b in g["bands"])
    assert api.get(f"/aps/runs/{rid}/gantt", view="order", **{"from": ops["items"][0]["start"]})["rows"]
    load = api.get(f"/aps/runs/{rid}/load", bucket="week")
    assert load["items"] and all(x["line_id"] is None for x in load["items"])
    line = ops["items"][0]["line"]["id"]
    d = api.get(f"/aps/runs/{rid}/dispatch", line_id=line, date=ops["items"][0]["start"][:10])
    assert "items" in d
    assert "totals" in api.get(f"/aps/runs/{rid}/overtime")
    assert "counts" in api.get(f"/aps/runs/{rid}/exceptions")
    assert "items" in api.get(f"/aps/runs/{rid}/bottlenecks")
    assert api.req("GET", f"/aps/runs/{rid}/export", 200, params={"format": "zip"}).content[:2] == b"PK"
    pub = api.post(f"/aps/runs/{rid}/publish", {}, status=200, version=r["row_version"])
    assert pub["is_published"]
    assert api.get("/aps/runs/published")["id"] == rid and api.get("/summary")["published_schedule"]["id"] == rid
    api.err("DELETE", f"/aps/runs/{rid}", 409, "MFG_IN_USE", headers=im(pub["row_version"]))
    # copy_of escalation: identical inputs, allow
    c = api.post("/aps/runs", {"copy_of": rid, "overtime": "allow"}, status=202)
    c = wait_run(api, c["id"])
    assert c["copy_of_run_id"] == rid and c["policy"] == "allow" and c["as_of"] == r["as_of"] and c["kind"] == "live"
    cmp = api.get(f"/aps/runs/{rid}/compare", **{"with": c["id"]})
    assert set(cmp["tradeoff"]) == {"weighted_tardiness_saved", "late_minutes_saved", "late_demand_saved",
                                    "overtime_hours_added", "overtime_cost_added"}
    api.err("POST", "/aps/runs", 422, "VALIDATION_ERROR", json={"copy_of": rid, "split": False})
    # edits: lock + move to its own start (a no-op move) -> child run
    first = ops["items"][0]
    child = api.post(f"/aps/runs/{rid}/edits", {"edits": [{"kind": "lock", "op_no": first["op_no"]}]},
                     status=201)
    assert child["parent_run_id"] == rid and child["status"] == "completed" and child["validation"]["ok"]
    api.err("POST", f"/aps/runs/{rid}/edits", 422, "APS_UNKNOWN_OPERATION", json={"edits": [{"kind": "lock",
                                                                                            "op_no": 99999}]})
