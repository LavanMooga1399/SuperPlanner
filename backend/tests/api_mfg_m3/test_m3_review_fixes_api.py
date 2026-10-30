"""M3 review fix round (API): M1/M2 freeze at edit time, M3 stale freeze basis, m1 copy_of MRP guard, m2 copy keeps
locks, m4 concurrent publish, m5 kind-aware job error, m7 offset -> zone rebase."""

from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from apimfgm3_helpers import MFG, Api, im, wait_run


def _run(api: Api, **body) -> dict:
    body.setdefault("improve_seconds", 0)
    return wait_run(api, api.post("/aps/runs", body, status=202)["id"], timeout=120)


def test_m1_m2_m3_freeze_at_edit_time_and_stale_basis(api: Api):
    api.load("kavach")
    api.post("/mrp/runs", {})
    r1 = _run(api)
    assert r1["status"] == "completed", r1["error"]
    api.post(f"/aps/runs/{r1['id']}/publish", {}, status=200, version=r1["row_version"])
    ops = api.get(f"/aps/runs/{r1['id']}/operations", limit=50, sort="start", status="scheduled")["items"]
    near = next(o for o in ops if o["start"] > r1["as_of"] and not o["frozen"])       # inside the 48 h freeze
    e = {"edits": [{"kind": "move", "op_no": near["op_no"], "start": near["start"]}]}
    api.err("POST", f"/aps/runs/{r1['id']}/edits", 422, "APS_EDIT_FROZEN", json=e)
    child = api.post(f"/aps/runs/{r1['id']}/edits", {**e, "override_freeze": True}, status=201)
    assert child["validation"]["ok"] and child["basis_published_run_id"] == r1["id"]
    # M3: r2 frozen against r1; then r3 is published -> r2 has a stale basis
    r2 = _run(api)
    r3 = _run(api)
    assert r2["basis_published_run_id"] == r1["id"]
    api.post(f"/aps/runs/{r3['id']}/publish", {}, status=200, version=r3["row_version"])
    assert api.get(f"/aps/runs/{r2['id']}")["stale"]["basis_changed"]
    api.err("POST", f"/aps/runs/{r2['id']}/publish", 409, "APS_RUN_STALE_BASIS", json={},
            headers=im(r2["row_version"]))
    ok = api.post(f"/aps/runs/{r2['id']}/publish", {"confirm_stale_basis": True}, status=200,
                  version=r2["row_version"])
    assert ok["is_published"]


def test_m1_minor_copy_of_needs_the_mrp_run_and_m2_copy_keeps_locks(api: Api):
    api.load("small")
    m1 = api.post("/mrp/runs", {})
    r = _run(api)
    first = api.get(f"/aps/runs/{r['id']}/operations", status="scheduled")["items"][0]
    child = api.post(f"/aps/runs/{r['id']}/edits", {"edits": [{"kind": "lock", "op_no": first["op_no"]}]},
                     status=201)
    cp = wait_run(api, api.post("/aps/runs", {"copy_of": child["id"], "overtime": "allow"}, status=202)["id"])
    hit = [o for o in api.get(f"/aps/runs/{cp['id']}/operations", order_id=first["order"]["id"])["items"]
           if o["seq"] == first["seq"]]
    assert hit[0]["locked"] and hit[0]["start"] == first["start"] and hit[0]["line_id"] == first["line_id"]
    api.post("/mrp/runs", {})
    api.delete(f"/mrp/runs/{m1['id']}", m1["row_version"])
    api.err("POST", "/aps/runs", 422, "APS_NO_MRP_RUN", json={"copy_of": r["id"]})


def test_m4_concurrent_publish_never_500(client: TestClient, api: Api):
    api.load("small")
    api.post("/mrp/runs", {})
    a, b = _run(api), _run(api)
    out: list[int] = []
    bar = threading.Barrier(2)

    def go(run: dict) -> None:
        bar.wait()
        out.append(client.post(f"{MFG}/aps/runs/{run['id']}/publish", json={},
                               headers=im(run["row_version"])).status_code)

    ts = [threading.Thread(target=go, args=(x,)) for x in (a, b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(c in (200, 409) for c in out), out
    assert api.get("/aps/runs/published")["id"] in (a["id"], b["id"])


def test_m5_aps_run_errors_are_objects():
    from superplanner.api.mfg.db_models_m3 import MfgApsRunRow
    from superplanner.jobs.common import set_run_error

    r = MfgApsRunRow()
    set_run_error(r, "lost")
    assert r.error == {"code": "APS_RUN_FAILED", "message": "lost"}


def test_m7_switching_to_a_zone_keeps_exception_wall_clock(api: Api):
    p = api.get("/plant")
    body = {k: p[k] for k in ("name", "planning_horizon_days", "currency", "attributes", "mrp_workdays",
                              "mrp_day_minutes", "mrp_defer_tolerance_days", "mrp_release_window_days",
                              "over_receipt_pct")}
    p = api.put("/plant", {**body, "utc_offset": "+01:00"}, p["row_version"])
    x = api.post("/calendar-exceptions", {"scope": "plant", "kind": "holiday", "start": "2026-07-01T10:00:00+01:00",
                                          "end": "2026-07-01T12:00:00+01:00", "label": "Summer"})
    api.put("/plant", {**body, "utc_offset": "+01:00", "time_zone": "Europe/Berlin"}, p["row_version"])
    y = next(e for e in api.get("/calendar-exceptions")["items"] if e["id"] == x["id"])
    st = datetime.fromisoformat(y["start"]).astimezone(ZoneInfo("Europe/Berlin"))
    assert (st.hour, st.minute) == (10, 0) and y["row_version"] == x["row_version"] + 1
