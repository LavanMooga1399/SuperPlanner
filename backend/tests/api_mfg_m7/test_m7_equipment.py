"""S4 (M7-DESIGN 8): calibration blocks results (T-Q5), floor and APS/health (T-Q9); failed calibration -> out of
service with impact (T-Q11); return to service rules."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_mfg_m4"))

from apimfgm4_helpers import ev  # noqa: E402
from test_m7_inspection import gate_plant, incoming, plan, scheme  # noqa: E402

TODAY = date.today()


def _gauge(api, code="EQ-0042", due=TODAY + timedelta(days=30), **kw):
    return api.post("/qa/equipment", {"code": code, "name": "Force gauge", "kind": "gauge",
                                      "equipment_class": "FORCE", "interval_days": 365, "due_on": due.isoformat(),
                                      **kw})


def test_t_q5_and_t_q11_results_need_a_calibrated_gauge_failure_impact(api):
    x = incoming(api)
    sc = scheme(api, "F2")
    pl = plan(api, x["it"]["id"], "incoming", sc["id"], chars=[
        {"seq": 1, "code": "PULL", "name": "Pull", "kind": "variable", "severity": "critical", "lsl": 22,
         "equipment_class": "FORCE"}], supplier_id=x["sup"]["id"])
    lot = api.get("/lots", item_id=x["it"]["id"])["items"][0]
    il = api.post("/qa/inspection-lots", {"plan_id": pl["id"], "lot_id": lot["id"], "lot_size": 50})
    cid = il["characteristics"][0]["id"]
    late = _gauge(api, "EQ-OLD", due=TODAY - timedelta(days=3))
    assert late["valid"] is False and late["due_state"] == "overdue"
    good = _gauge(api)
    e = api.err("POST", f"/qa/inspection-lots/{il['id']}/results", 409, "QA_EQUIPMENT_NOT_CALIBRATED", json={
        "client_batch_id": "g1", "results": [{"characteristic_id": cid, "sample_no": 1, "value": 30,
                                              "equipment_id": late["id"]}]})
    assert e["details"]["equipment"]["code"] == "EQ-OLD"
    api.err("POST", f"/qa/inspection-lots/{il['id']}/results", 422, "VALIDATION_ERROR", json={
        "client_batch_id": "g2", "results": [{"characteristic_id": cid, "sample_no": 1, "value": 30}]})
    api.post(f"/qa/inspection-lots/{il['id']}/results", {"client_batch_id": "g3", "results": [
        {"characteristic_id": cid, "sample_no": k, "value": 30, "equipment_id": good["id"]} for k in (1, 2)]}, 200)
    cal = api.post(f"/qa/equipment/{good['id']}/calibrations", {"performed_on": TODAY.isoformat(),
                                                                 "result": "fail", "as_found": "+4 %"})
    assert cal["result"] == "fail"
    g = api.get(f"/qa/equipment/{good['id']}")
    assert g["status"] == "out_of_service" and g["valid"] is False
    imp = api.get(f"/qa/equipment/{good['id']}/impact")
    assert imp["results"] == 2 and imp["inspection_lots"][0]["number"] == il["number"]
    api.err("POST", f"/qa/equipment/{good['id']}/status", 409, "QA_CALIBRATION_REQUIRED",
            json={"status": "active", "reason": "repaired"})
    api.post(f"/qa/equipment/{good['id']}/calibrations", {"performed_on": TODAY.isoformat(), "result": "adjusted_pass"})
    g = api.post(f"/qa/equipment/{good['id']}/status", {"status": "active", "reason": "repaired, recalibrated"}, 200)
    assert g["status"] == "active" and g["valid"] and g["due_on"] == (TODAY + timedelta(days=365)).isoformat()


def test_t_q9_line_equipment_blocks_floor_aps_and_health(api, client):
    x = gate_plant(api, lot_fg=False)
    eq = _gauge(api, "EQ-L1", due=TODAY - timedelta(days=2), kind="line_equipment", line_id=x["l1"]["id"])
    soon = _gauge(api, "EQ-SOON", due=TODAY + timedelta(days=3))
    e = ev(api, x["ops"][0]["id"], "start", 409, line_id=x["l1"]["id"])
    assert e["error"]["code"] == "QA_LINE_EQUIPMENT_INVALID" and e["error"]["details"]["equipment"][0]["code"] == \
        "EQ-L1"
    h = api.get("/health")
    codes = {i["code"]: i for i in h["issues"]}
    assert codes["QA_LINE_BLOCKED"]["entity"]["label"] == "L1" and h["ok"] is False
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg import repo_m3
    from datetime import UTC, datetime
    with owner_scope("usr_local"), client.app.state.ctx.db.read() as s:
        snap = repo_m3.load_aps_snapshot(s, datetime.now(UTC), None)
        blocks = [d for d in snap.downtime if d.id.startswith("qa:")]
        assert [b.line_id for b in blocks] == [x["l1"]["id"]]
    api.err("PUT", f"/qa/equipment/{eq['id']}", 409, "QA_EQUIPMENT_BLOCKING", json={   # review M6: no unlink
        **{k: eq[k] for k in ("code", "name", "kind", "equipment_class", "interval_days", "due_on")}, "line_id": None},
        headers={"If-Match": f'"{eq["row_version"]}"'})
    api.post(f"/qa/equipment/{eq['id']}/calibrations", {"performed_on": TODAY.isoformat(), "result": "pass"})
    ev(api, x["ops"][0]["id"], "start", line_id=x["l1"]["id"])
    soon_l = api.get("/qa/equipment", due_within_days=14)["items"]
    assert {e["code"] for e in soon_l} >= {"EQ-SOON"} and soon["due_state"] == "due_soon"
