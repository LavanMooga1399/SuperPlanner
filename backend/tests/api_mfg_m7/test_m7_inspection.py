"""S2 (M7-DESIGN 5): sampling (T-Q1, T-Q2), schemes and plans, incoming inspection from PO receipts with holds
and MRP inspection supply (T-Q3), in-process gate (T-Q4), final lots from WO receipts, results rules, manual lot
holds (T-Q8 for inspection holds), signed decisions in Part 11 mode."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_mfg_m4"))

from apimfgm4_helpers import PLANT_FIELDS, cid, ev  # noqa: E402
from apimfgm2_helpers import Api  # noqa: E402
from superplanner.qa import sampling as SMP  # noqa: E402
from superplanner.qa.fixtures.build_example import TABLE  # noqa: E402

TODAY = date.today()


# ---------------------------------------------------------------- pure

def test_t_q1_example_table_resolution_and_full_inspection():
    SMP.validate_table(TABLE)
    assert SMP.resolve("table", lot_size=3200, table=TABLE, level="II", aql="0.65") == \
        {"n": 125, "ac": 2, "re": 3, "full": False}
    assert SMP.resolve("table", lot_size=3200, table=TABLE, level="II", aql="0.65", state="tightened")["n"] == 200
    assert SMP.resolve("table", lot_size=10, table=TABLE, level="II", aql="0.65") == \
        {"n": 10, "ac": 1, "re": 2, "full": True}                         # J: n 80 >= lot 10 -> 100 %
    assert SMP.resolve("fixed", lot_size=100, fixed_n=5) == {"n": 5, "ac": 0, "re": 1, "full": False}
    assert SMP.resolve("percent", lot_size=101, percent=10)["n"] == 11
    assert SMP.resolve("full", lot_size=7)["n"] == 7
    bad = {**TABLE, "lot_size_ranges": [{"min": 2, "max": None, "letters": {"S-4": "E", "II": "J"}}]}
    with pytest.raises(SMP.SchemeError):
        SMP.validate_table(bad)
    bad = {**TABLE, "plans": {"normal": {"E": {"0.65": {"n": 5, "ac": 3, "re": 3}}}}}
    with pytest.raises(SMP.SchemeError):
        SMP.validate_table(bad)


def test_t_q2_switching_rules():
    assert SMP.next_state("normal", ["A", "R", "A", "A"], None) == "normal"
    assert SMP.next_state("normal", ["A", "R", "A", "R"], None) == "tightened"
    assert SMP.next_state("tightened", ["R", "A", "A", "A", "A"], None) == "tightened"
    assert SMP.next_state("tightened", ["R", "A", "A", "A", "A", "A"], None) == "normal"


# ---------------------------------------------------------------- API helpers

def scheme(api: Api, code: str = "FIXED-3", **kw: Any) -> dict[str, Any]:
    body = {"code": code, "name": code, "kind": "fixed", "fixed_n": 3, **kw}
    sc = api.post("/qa/schemes", body)
    return api.post(f"/qa/schemes/{sc['id']}/approve", {}, status=200)


def plan(api: Api, item_id: str, scope: str, scheme_id: str, chars: list[dict[str, Any]] | None = None,
         **kw: Any) -> dict[str, Any]:
    chars = chars or [{"seq": 10, "code": "LEN", "name": "Length", "kind": "variable", "severity": "major",
                       "lsl": 9.0, "usl": 11.0, "nominal": 10.0},
                      {"seq": 20, "code": "VIS", "name": "Visual", "kind": "attribute", "severity": "minor"}]
    p = api.post("/qa/plans", {"name": f"{scope} plan", "item_id": item_id, "scope": scope, "scheme_id": scheme_id,
                               "characteristics": chars, **kw})
    return api.post(f"/qa/plans/{p['id']}/approve", {}, status=200)


def results(api: Api, lot: dict[str, Any], values: dict[str, list[Any]], batch: str | None = None,
            status: int = 200) -> Any:
    rows = []
    for c in lot["characteristics"]:
        for i, v in enumerate(values.get(c["code"], []), start=1):
            rows.append({"characteristic_id": c["id"], "sample_no": i,
                         **({"value": v} if c["kind"] == "variable" else {"passed": v})})
    r = api.req("POST", f"/qa/inspection-lots/{lot['id']}/results", status,
                json={"client_batch_id": batch or cid(), "results": rows})
    return r.json()


def incoming(api: Api, qty: float = 100) -> dict[str, Any]:
    sup = api.supplier("S1")
    it = api.item("NEEDLE", lot_controlled=True, receiving_days=2)
    api.post("/item-suppliers", {"item_id": it["id"], "supplier_id": sup["id"], "preferred": True, "unit_price": 1})
    loc = api.location("ST", receipt_default=True)
    sc = scheme(api)
    pl = plan(api, it["id"], "incoming", sc["id"])
    po = api.post("/purchase-orders", {"supplier_id": sup["id"], "lines": [{"item_id": it["id"], "schedules": [
        {"requested_date": (TODAY + timedelta(days=5)).isoformat(), "qty": 500}]}]})
    po = api.post(f"/purchase-orders/{po['id']}/issue", version=po["row_version"], status=200)
    sid = po["lines"][0]["schedules"][0]["id"]
    rec = api.post("/inventory/postings", {"type": "po_receipt", "lines": [
        {"schedule_id": sid, "qty": qty, "location_id": loc["id"], "lot_code": "L-1"}]})
    return {"sup": sup, "it": it, "loc": loc, "sc": sc, "plan": pl, "receipt": rec}


# ---------------------------------------------------------------- incoming (T-Q3)

def test_t_q3_po_receipt_creates_lot_and_hold_mrp_inspection_supply_and_accept(api, client):
    x = incoming(api)
    links = x["receipt"]["inspection_lots"]
    assert len(links) == 1 and links[0]["number"] == "IL-000001"
    lot = api.get(f"/qa/inspection-lots/{links[0]['id']}")
    assert lot["status"] == "open" and lot["hold"] and lot["lot_size"] == 100 and lot["supplier_id"] == x["sup"]["id"]
    assert {v["n"] for v in lot["sampling"].values()} == {3}
    lots = api.get("/lots", item_id=x["it"]["id"])["items"]
    assert lots[0]["hold"] is True
    holds = api.get("/qa/holds")["items"]
    assert holds[0]["source"] == "inspection" and holds[0]["source_number"] == "IL-000001"
    # MRP snapshot: the lot is inspection supply (only inspection holds)
    from superplanner.api.mfg import repo_m2

    ctx = client.app.state.ctx
    from superplanner.api.db.ownership import owner_scope
    with owner_scope("usr_local"), ctx.db.read() as s:
        t = repo_m2.load_txn(s, open_only=True)
        assert t.lots[lot["lot_id"]].inspection_hold is True
    # held material cannot be issued; releasing the hold on the lot directly is refused
    api.err("POST", "/inventory/postings", 422, "INV_LOT_ON_HOLD", json={"type": "issue_misc", "reason_code": "X",
            "lines": [{"item_id": x["it"]["id"], "location_id": x["loc"]["id"], "lot_code": "L-1", "qty": 1}]})
    lr = lots[0]
    e = api.err("PUT", f"/lots/{lr['id']}", 409, "QA_HOLD_ACTIVE", json={
        "expires_on": None, "supplier_lot": "", "hold": False, "note": ""}, headers={"If-Match": f'"{lr["row_version"]}"'})
    assert e["details"]["holds"][0]["source"] == "inspection"
    api.err("POST", f"/qa/holds/{holds[0]['id']}/release", 409, "QA_HOLD_OWNED", json={})
    # results: decision before the verdict -> 409; out-of-range sample -> 422
    api.err("POST", f"/qa/inspection-lots/{lot['id']}/decision", 409, "QA_LOT_NOT_READY", json={"decision": "accept"})
    c0 = lot["characteristics"][0]
    api.err("POST", f"/qa/inspection-lots/{lot['id']}/results", 422, "QA_SAMPLE_OUT_OF_RANGE", json={
        "client_batch_id": cid(), "results": [{"characteristic_id": c0["id"], "sample_no": 4, "value": 10}]})
    body = results(api, lot, {"LEN": [10.0, 10.5, 9.5], "VIS": [True, True]}, batch="b-1")
    assert body["status"] == "in_progress" and body["verdict"]["verdict"] == "pending"
    again = results(api, lot, {"LEN": [10.0, 10.5, 9.5], "VIS": [True, True]}, batch="b-1")
    assert again["replayed"] is True and again["accepted"] == 5
    body = results(api, lot, {"VIS": [True, True, True]}, status=409)       # samples 1-2 exist
    assert body["error"]["code"] == "QA_RESULT_EXISTS"
    rows = [{"characteristic_id": lot["characteristics"][1]["id"], "sample_no": 3, "passed": True}]
    body = api.post(f"/qa/inspection-lots/{lot['id']}/results", {"client_batch_id": cid(), "results": rows}, 200)
    assert body["status"] == "ready" and body["verdict"]["verdict"] == "accept"
    out = api.post(f"/qa/inspection-lots/{lot['id']}/decision", {"decision": "accept"}, 200)
    assert out["status"] == "accepted" and out["decision"] == "accept"
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is False
    api.post("/inventory/postings", {"type": "issue_misc", "reason_code": "X", "lines": [
        {"item_id": x["it"]["id"], "location_id": x["loc"]["id"], "lot_code": "L-1", "qty": 1}]})
    api.err("POST", f"/qa/inspection-lots/{lot['id']}/results", 409, "QA_LOT_DECIDED", json={
        "client_batch_id": cid(), "results": [{"characteristic_id": c0["id"], "sample_no": 1, "value": 10}]})


def test_corrections_supersede_and_need_a_reason(api):
    x = incoming(api)
    lot = api.get(f"/qa/inspection-lots/{x['receipt']['inspection_lots'][0]['id']}")
    body = results(api, lot, {"LEN": [12.0]})
    assert body["verdict"]["characteristics"][0]["verdict"] == "reject"
    rid = body["results"][0]["id"]
    c0 = lot["characteristics"][0]
    api.err("POST", f"/qa/inspection-lots/{lot['id']}/results", 422, "VALIDATION_ERROR", json={
        "client_batch_id": cid(), "results": [{"characteristic_id": c0["id"], "sample_no": 1, "value": 10,
                                               "corrects_result_id": rid}]})
    body = api.post(f"/qa/inspection-lots/{lot['id']}/results", {"client_batch_id": cid(), "results": [
        {"characteristic_id": c0["id"], "sample_no": 1, "value": 10.1, "corrects_result_id": rid,
         "reason": "Transcription error"}]}, 200)
    assert body["verdict"]["characteristics"][0]["verdict"] == "pending"
    full = api.get(f"/qa/inspection-lots/{lot['id']}")
    assert [r["superseded"] for r in full["results"]] == [True, False]


def test_plan_rules(api):
    it = api.item("BULK")                                           # not lot-controlled
    sc = scheme(api)
    p = api.post("/qa/plans", {"name": "x", "item_id": it["id"], "scope": "incoming", "scheme_id": sc["id"],
                               "characteristics": [{"seq": 1, "code": "A", "name": "A", "kind": "attribute",
                                                    "severity": "minor"}]})
    api.err("POST", f"/qa/plans/{p['id']}/approve", 422, "QA_ITEM_NOT_LOT_CONTROLLED", json={})
    api.err("POST", "/qa/schemes", 422, "QA_SCHEME_INVALID", json={
        "code": "BAD", "name": "Bad", "kind": "table", "table": {**TABLE, "lot_size_ranges": [
            {"min": 2, "max": None, "letters": {"S-4": "E", "II": "J"}}]}})
    s2 = api.post("/qa/schemes", {"code": "EX", "name": "Example", "kind": "table", "table": TABLE,
                                  "switching": True})
    pv = api.get(f"/qa/schemes/{s2['id']}/preview", lot_size=3200, level="II", aql="0.65")
    assert (pv["n"], pv["ac"], pv["re"]) == (125, 2, 3)
    s2 = api.post(f"/qa/schemes/{s2['id']}/approve", {}, 200)
    api.err("PUT", f"/qa/schemes/{s2['id']}", 409, "ESIG_RECORD_LOCKED", json={
        "code": "EX", "name": "Changed", "kind": "table", "table": TABLE}, headers={"If-Match": f'"{s2["row_version"]}"'})


def test_switching_on_supplier_lots(api):
    """Two rejections in five lots of one supplier tighten the next lot's sampling (T-Q2 end to end)."""
    sup = api.supplier("S1")
    it = api.item("PART", lot_controlled=True)
    loc = api.location("ST", receipt_default=True)
    sc = api.post("/qa/schemes", {"code": "EX", "name": "Example", "kind": "table", "table": TABLE,
                                  "switching": True})
    sc = api.post(f"/qa/schemes/{sc['id']}/approve", {}, 200)
    plan(api, it["id"], "incoming", sc["id"], chars=[{"seq": 1, "code": "A", "name": "A", "kind": "attribute",
                                                      "severity": "major"}], aql={"critical": "0.65",
                                                                                  "major": "0.65", "minor": "0.65"})
    po = api.post("/purchase-orders", {"supplier_id": sup["id"], "lines": [{"item_id": it["id"], "schedules": [
        {"requested_date": TODAY.isoformat(), "qty": 100000}]}]})
    po = api.post(f"/purchase-orders/{po['id']}/issue", version=po["row_version"], status=200)
    sid = po["lines"][0]["schedules"][0]["id"]

    def receive_and_decide(k: int, reject: bool) -> dict[str, Any]:
        rec = api.post("/inventory/postings", {"type": "po_receipt", "lines": [
            {"schedule_id": sid, "qty": 1000, "location_id": loc["id"], "lot_code": f"L{k}"}]})
        lot = api.get(f"/qa/inspection-lots/{rec['inspection_lots'][0]['id']}")
        return lot

    l1 = receive_and_decide(1, False)
    assert l1["sampling"][l1["characteristics"][0]["id"]]["n"] == 80            # J normal
    api.post(f"/qa/inspection-lots/{l1['id']}/cancel", {"reason": "test"}, 200)
    from superplanner.qa.sampling import next_state

    assert next_state("normal", ["R", "R"], None) == "tightened"


# ---------------------------------------------------------------- in-process gate (T-Q4) and final lots

def gate_plant(api: Api, lot_fg: bool = True) -> dict[str, Any]:
    fg_loc = api.location("FG")
    g = api.post("/groups", {"code": "G", "name": "Group"})
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    tpl = api.post("/shift-templates", {"code": "24X7", "name": "24x7", "shifts": [
        {"name": "A", "days": days, "start": "00:00", "end": "12:00"},
        {"name": "B", "days": days, "start": "12:00", "end": "24:00"}]})
    api.post("/shift-assignments", {"shift_template_id": tpl["id"], "target_type": "group", "group_id": g["id"],
                                    "effective_from": "2026-01-01"})
    l1 = api.post("/lines", {"group_id": g["id"], "code": "L1", "name": "Line 1"})
    fg = api.item("FG", "make", lot_controlled=lot_fg)
    rt = api.post("/routings", {"item_id": fg["id"], "operations": [
        {"seq": 10, "name": "Assemble", "group_id": g["id"], "run_minutes": 1, "labor": "unattended",
         "crew_size": 0},
        {"seq": 20, "name": "QC gate", "group_id": g["id"], "run_minutes": 1, "labor": "unattended", "crew_size": 0,
         "inspection_gate": True}]})
    api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
    p = api.get("/plant")
    body = {k: v for k, v in p.items() if k in PLANT_FIELDS}
    body["wo_receipt_location_id"] = fg_loc["id"]
    api.put("/plant", body, p["row_version"])
    wo = api.post("/work-orders", {"item_id": fg["id"], "qty": 10, "due_date": "2026-12-01",
                                   "start_date": "2026-11-02"})
    wo = api.post(f"/work-orders/{wo['id']}/release", {"override_reason": "test"}, status=200,
                  version=wo["row_version"])
    ops = api.get(f"/work-orders/{wo['id']}/operations")["items"]
    return {"fg": fg, "l1": l1, "wo": wo, "ops": ops, "fg_loc": fg_loc}


def test_t_q4_gate_complete_blocked_until_accepted_then_final_lot_from_receipt(api):
    x = gate_plant(api)
    sc = scheme(api)
    plan(api, x["fg"]["id"], "in_process", sc["id"], operation_seq=20)
    plan(api, x["fg"]["id"], "final", sc["id"])
    op10, op20 = x["ops"]
    ev(api, op10["id"], "start", line_id=x["l1"]["id"])
    ev(api, op10["id"], "complete", qty_good=10)
    r = ev(api, op20["id"], "start", line_id=x["l1"]["id"])
    il_id = r["event"].get("details", {}).get("inspection_lot_id") or \
        api.get("/qa/inspection-lots", scope="in_process")["items"][0]["id"]
    lot = api.get(f"/qa/inspection-lots/{il_id}")
    assert lot["scope"] == "in_process" and lot["lot_size"] == 10 and lot["hold"] is False
    e = ev(api, op20["id"], "complete", 409, qty_good=10)
    assert e["error"]["code"] == "QA_INSPECTION_OPEN"
    results(api, lot, {"LEN": [10, 10, 10], "VIS": [True, True, True]})
    api.post(f"/qa/inspection-lots/{lot['id']}/decision", {"decision": "accept"}, 200)
    out = ev(api, op20["id"], "complete", qty_good=10)
    assert out["operation"]["status"] == "completed"
    finals = api.get("/qa/inspection-lots", scope="final")["items"]
    assert len(finals) == 1 and finals[0]["hold"] and finals[0]["lot_size"] == 10 and finals[0]["source"] == \
        "wo_receipt"
