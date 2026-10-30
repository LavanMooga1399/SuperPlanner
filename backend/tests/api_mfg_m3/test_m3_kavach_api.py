"""Kavach end to end (M3-DESIGN 13, 15.2): AP5 run through the queue with the default budget, AP6 edit repair, AP8
views; roles (15.2 #8); MRP `use_schedule` (15.2 #7)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from apimfgm3_helpers import Api, acc_app, sign_up, wait_run

pytestmark = pytest.mark.slow


def _timed(fn):
    t = time.monotonic()
    out = fn()
    return out, time.monotonic() - t


def test_kavach_ap5_ap6_ap8_and_mrp_feedback(api: Api):
    api.load("kavach")
    api.post("/mrp/runs", {})
    t = time.monotonic()
    run = api.post("/aps/runs", {}, status=202)                       # plant default: suggest, 30 s budget
    run = wait_run(api, run["id"], timeout=180)
    total = time.monotonic() - t
    assert run["status"] == "completed" and run["validation"]["ok"], run.get("error")
    tm = run["summary"]["timings_ms"]
    print(f"[perf] AP5 {total:.1f} s, timings {tm}")
    assert total < 45 and tm["store"] < 3000
    rid = run["id"]
    ops = api.get(f"/aps/runs/{rid}/operations", limit=200, sort="start")["items"]
    smt = next(o for o in ops if o["line"] and o["line"]["code"].startswith("SMT") and not o["frozen"])
    first_day = smt["start"]
    g, dt_g = _timed(lambda: api.get(f"/aps/runs/{rid}/gantt", group_id=smt["group"]["id"]))
    ld, dt_l = _timed(lambda: api.get(f"/aps/runs/{rid}/load", bucket="day"))
    d, dt_d = _timed(lambda: api.get(f"/aps/runs/{rid}/dispatch", line_id=smt["line"]["id"], date=first_day[:10]))
    print(f"[perf] AP8 gantt {dt_g:.3f} load {dt_l:.3f} dispatch {dt_d:.3f}")
    assert g["bars"] and dt_g < 0.3 and dt_l < 0.3 and dt_d < 0.2 and d["shifts"]
    assert all("wo_row_version" in x for x in d["items"])
    # AP6: edit repair -> child run (lock one operation)
    child, dt_e = _timed(lambda: api.post(f"/aps/runs/{rid}/edits", {"edits": [{"kind": "lock",
                                                                              "op_no": smt["op_no"]}]},
                                          status=201))
    print(f"[perf] AP6 {dt_e:.2f} s")
    assert child["validation"]["ok"] and dt_e < 5
    pub = api.post(f"/aps/runs/{rid}/publish", {}, status=200, version=run["row_version"])
    # MRP feedback: WO due dates in MRP come from the published schedule
    m = api.post("/mrp/runs", {})
    assert m["kind"] == "live" and pub["is_published"]
    wo_orders = [o for o in api.get(f"/aps/runs/{rid}/orders", order_type="wo", limit=50)["items"] if o["end"]]
    assert wo_orders
    pos = api.get(f"/mrp/runs/{m['id']}/items/{wo_orders[0]['order']['item_id']}")
    sup = [s for s in pos["supplies"] if (s.get("ref") or {}).get("id") == wo_orders[0]["order"]["id"]]
    assert sup and sup[0]["avail_date"] > wo_orders[0]["end"][:10]


def test_roles_run_publish_edit(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        owner = Api(oc)
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        owner.load("small")
        owner.post("/mrp/runs", {})
        users = {}
        for role in ("planner", "viewer", "store_keeper"):
            c = sign_up(app, f"{role}@example.com")
            owner.post("/members", {"email": f"{role}@example.com", "roles": [role]})
            users[role] = Api(c, oid)
        run = users["planner"].post("/aps/runs", {"improve_seconds": 0}, status=202)
        run = wait_run(users["planner"], run["id"])
        for role in ("viewer", "store_keeper"):
            a = users[role]
            assert a.get(f"/aps/runs/{run['id']}/gantt")["view"] == "line"
            a.err("POST", "/aps/runs", 403, "MFG_FORBIDDEN", json={})
            a.err("POST", f"/aps/runs/{run['id']}/publish", 403, "MFG_FORBIDDEN", json={})
            a.err("POST", f"/aps/runs/{run['id']}/edits", 403, "MFG_FORBIDDEN", json={"edits": []})
        assert users["planner"].post(f"/aps/runs/{run['id']}/publish", {}, status=200,
                                     version=run["row_version"])["is_published"]
