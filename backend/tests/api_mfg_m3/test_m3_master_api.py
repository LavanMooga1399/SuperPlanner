"""S1 (M3-DESIGN 3, 11 #164-178): line rates, setup matrix, absences (CRUD, rules, audit), plant time zone, WO
operation progress, M3 import sheets and export round trip."""

from __future__ import annotations

import io
import zipfile

from apimfgm3_helpers import Api, im

OCTET = {"content-type": "application/octet-stream"}


def _import(api: Api, data: bytes, filename: str) -> dict:
    r = api.req("POST", "/imports", 201, params={"filename": filename}, content=data, headers=OCTET).json()
    m = api.put(f"/imports/{r['id']}/mapping", {"sheets": {s["name"]: s["suggested"] for s in r["sheets"]},
                                                "options": {}}, r["row_version"])
    assert m["preview"]["ok"], m["preview"]["row_errors"][:5]
    return api.req("POST", f"/imports/{r['id']}/commit", 200, json={},
                   headers={"If-Match": f'"{m["row_version"]}"'}).json()


def test_rates_matrix_absences_crud_and_rules(api: Api):
    api.load("small", include_transactions=False)
    rt = next(r for r in api.get("/routings")["items"] if r["operations"]) if False else None
    items = api.get("/items", limit=200)["items"]
    make = next(i for i in items if i["make_buy"] == "make" and i["has_routing"])
    rtg = api.get(f"/items/{make['id']}/routings")["items"][0]
    rtg = api.get(f"/routings/{rtg['id']}")
    op = rtg["operations"][0]
    lines = api.get("/lines")["items"]
    same = next(ln for ln in lines if ln["group_id"] == op["group_id"])
    other = next((ln for ln in lines if ln["group_id"] != op["group_id"]), None)
    rate = api.post("/operation-line-rates", {"operation_id": op["id"], "line_id": same["id"], "run_minutes": 2.5})
    assert rate["line"]["code"] == same["code"] and rate["seq"] == op["seq"] and rate["routing_id"] == rtg["id"]
    api.err("POST", "/operation-line-rates", 409, "MFG_DUPLICATE_KEY",
            json={"operation_id": op["id"], "line_id": same["id"]})
    if other is not None:
        api.err("POST", "/operation-line-rates", 422, "MFG_LINE_NOT_IN_GROUP",
                json={"operation_id": op["id"], "line_id": other["id"]})
    up = api.put(f"/operation-line-rates/{rate['id']}", {"operation_id": op["id"], "line_id": same["id"],
                                                          "setup_minutes": 5, "run_minutes": None}, rate["row_version"])
    assert up["setup_minutes"] == 5 and up["run_minutes"] is None
    assert api.get("/operation-line-rates", routing_id=rtg["id"])["items"][0]["id"] == rate["id"]
    row = api.post("/setup-matrix", {"line_setup_family": "SMT", "from_family": "A", "to_family": "*",
                                     "setup_minutes": 30})
    api.err("POST", "/setup-matrix", 409, "MFG_DUPLICATE_KEY", json={"line_setup_family": "SMT", "from_family": "A",
                                                                       "to_family": "*", "setup_minutes": 1})
    api.err("POST", "/setup-matrix", 422, "VALIDATION_ERROR", json={"line_setup_family": "SMT", "from_family": "a b",
                                                                      "to_family": "*", "setup_minutes": 1})
    emp = api.get("/operators")["items"][0]
    ab = api.post("/operator-absences", {"operator_id": emp["id"], "start": "2026-11-09T00:00:00+05:30",
                                         "end": "2026-11-11T00:00:00+05:30", "kind": "sick"})
    assert ab["operator"]["code"] == emp["code"]
    api.err("POST", "/operator-absences", 422, "VALIDATION_ERROR", json={
        "operator_id": emp["id"], "start": "2026-11-11T00:00:00+05:30", "end": "2026-11-09T00:00:00+05:30"})
    assert len(api.get("/operator-absences", operator_id=emp["id"], **{"from": "2026-11-10T00:00:00Z"})["items"]) == 1
    # master data: data_version moves; export -> import into the same plant: unchanged
    zipped = api.req("GET", "/export", 200, params={"format": "zip"}).content
    names = zipfile.ZipFile(io.BytesIO(zipped)).namelist()
    assert {"operation_line_rates.csv", "setup_matrix.csv", "operator_absences.csv"} <= set(names)
    res = _import(api, zipped, "x.zip")
    for sheet in ("operation_line_rates", "setup_matrix", "operator_absences"):
        c = res["result"]["counts"][sheet]
        assert c["create"] == 0 and c["update"] == 0 and c["unchanged"] == 1, (sheet, c)
    api.delete(f"/setup-matrix/{row['id']}", row["row_version"])
    api.delete(f"/operator-absences/{ab['id']}", ab["row_version"])
    api.delete(f"/operation-line-rates/{rate['id']}", up["row_version"])
    assert api.get("/setup-matrix")["items"] == []


def test_plant_time_zone(api: Api):
    p = api.get("/plant")
    body = {k: p[k] for k in ("name", "utc_offset", "planning_horizon_days", "currency", "attributes",
                              "mrp_workdays", "mrp_day_minutes", "mrp_defer_tolerance_days",
                              "mrp_release_window_days", "over_receipt_pct")}
    api.err("PUT", "/plant", 422, "MFG_TZ_INVALID", json={**body, "time_zone": "Mars/Olympus"},
            headers=im(p["row_version"]))
    r = api.put("/plant", {**body, "time_zone": "Asia/Kolkata", "aps_freeze_hours": 24,
                           "aps_overtime_policy": "allow"}, p["row_version"])
    assert r["time_zone"] == "Asia/Kolkata" and r["utc_offset"] == "+05:30" and r["aps_freeze_hours"] == 24


def test_wo_operations_done_and_reopen(api: Api):
    api.load("kavach")
    wo = api.doc("/work-orders", "WO-KV-0001")
    ops = api.get(f"/work-orders/{wo['id']}/operations")
    assert [x["seq"] for x in ops["items"] if x["done"]] == [10, 20, 30, 40]     # sample progress
    v = ops["wo"]["row_version"]
    out = api.post(f"/work-orders/{wo['id']}/operations/50/done", {}, status=200, version=v)
    assert next(x for x in out["items"] if x["seq"] == 50)["done"] and out["wo"]["row_version"] == v + 1
    api.req("POST", f"/work-orders/{wo['id']}/operations/50/reopen", 412, json={}, headers=im(v))
    out = api.post(f"/work-orders/{wo['id']}/operations/50/reopen", {}, status=200, version=v + 1)
    assert not next(x for x in out["items"] if x["seq"] == 50)["done"]
    api.err("POST", f"/work-orders/{wo['id']}/operations/999/done", 404, "NOT_FOUND", json={},
            headers=im(out["wo"]["row_version"]))
