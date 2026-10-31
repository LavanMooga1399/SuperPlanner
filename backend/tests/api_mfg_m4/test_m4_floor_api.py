"""S1 floor engine over the API (M4-DESIGN 4, 10; T-F1..T-F8 end to end)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apimfgm4_helpers import cid, ev, plant


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_release_creates_operations_and_t_f1_quantities_and_minutes(api):
    p = plant(api, wo_qty=100, comp_qty_per=1)
    ops = p["ops"]
    assert [o["seq"] for o in ops] == [10, 20] and ops[0]["status"] == "ready" and ops[1]["status"] == "pending"
    assert ops[0]["source"] == "release" and ops[0]["qty_planned"] == 100
    op = ops[0]["id"]
    t0 = datetime.now(UTC) - timedelta(hours=3)
    r = ev(api, op, "start", event_at=_iso(t0), line_id=p["l1"]["id"], operator_codes=["X"], status=422)
    assert r["error"]["code"] == "FLR_OPERATOR_UNKNOWN"
    r = ev(api, op, "start", event_at=_iso(t0), line_id=p["l1"]["id"])
    assert r["operation"]["status"] == "running" and r["wo"]["status"] == "in_progress"
    r = ev(api, op, "report", event_at=_iso(t0 + timedelta(minutes=60)), qty_good=40, qty_scrap=2)
    assert r["operation"]["qty_good"] == 40 and r["wo"]["qty_scrapped"] == 2
    assert ev(api, op, "pause", event_at=_iso(t0 + timedelta(minutes=70)), status=422)["error"]["code"] == \
        "FLR_REASON_REQUIRED"
    ev(api, op, "pause", event_at=_iso(t0 + timedelta(minutes=70)), reason_code="BREAK")
    ev(api, op, "resume", event_at=_iso(t0 + timedelta(minutes=100)))
    r = ev(api, op, "complete", event_at=_iso(t0 + timedelta(minutes=130)), qty_good=55, qty_scrap=3)
    o = r["operation"]
    assert (o["status"], o["qty_good"], o["qty_scrap"]) == ("completed", 95, 5)
    assert abs(o["run_minutes_actual"] - 100) < 1e-6          # 130 minus the 30 min pause
    nxt = r["operations"][0]
    assert nxt["seq"] == 20 and nxt["status"] == "ready" and nxt["qty_input"] == 95
    # T-F2: good 96 on input 95 is refused, a supervisor (owner) can force it
    op2 = nxt["id"]
    ev(api, op2, "start", line_id=p["l2"]["id"])
    e = ev(api, op2, "report", qty_good=96, status=422)["error"]
    assert e["code"] == "FLR_QTY_EXCEEDS_INPUT" and e["details"]["available"] == 95
    r = ev(api, op2, "report", qty_good=96, force={"reason": "found 1 extra board"})
    assert r["operation"]["qty_good"] == 96 and r["postings"][0]["type"] == "wo_receipt"


def test_t_f4_last_op_receipt_and_t_f8_reopen_reverses_it(api):
    p = plant(api, ops=1, wo_qty=10)
    op = p["ops"][0]["id"]
    ev(api, op, "start", line_id=p["l1"]["id"])
    r = ev(api, op, "complete", qty_good=10)
    assert r["wo"]["status"] == "completed" and r["wo"]["qty_completed"] == 10
    rec = [x for x in r["postings"] if x["type"] == "wo_receipt"]
    assert len(rec) == 1 and rec[0]["lines"][0]["qty"] == 10 and rec[0]["lines"][0]["location_id"] == p["fg_loc"]["id"]
    bal = api.get("/inventory/balances", item_id=p["fg"]["id"])["items"]
    assert sum(b["qty_on_hand"] for b in bal) == 10
    r = ev(api, op, "reopen")
    assert r["operation"]["status"] == "paused" and r["wo"]["status"] == "in_progress" and r["wo"]["qty_completed"] == 0
    assert any(x.get("reversal_of_id") for x in r["postings"])
    assert sum(b["qty_on_hand"] for b in api.get("/inventory/balances", item_id=p["fg"]["id"])["items"]) == 0
    r = ev(api, op, "complete")
    assert r["wo"]["status"] == "completed" and r["wo"]["qty_completed"] == 10


def test_t_f6_replay_and_t_f3_rework(api):
    p = plant(api, ops=3, wo_qty=100)
    o10, o20, o30 = (o["id"] for o in p["ops"])
    ev(api, o10, "start", line_id=p["l1"]["id"])
    k = cid()
    r1 = ev(api, o10, "complete", qty_good=100, client_event_id=k)
    r2 = api.req("POST", "/floor/events", 200, json={"client_event_id": k, "wo_operation_id": o10,
                                                       "event_type": "complete", "qty_good": 100})
    assert r2.headers["Idempotent-Replay"] == "true" and r2.json()["event"]["id"] == r1["event"]["id"]
    assert len(api.get("/floor/events", wo_operation_id=o10)["items"]) == 2
    ev(api, o20, "start", line_id=p["l1"]["id"])
    ev(api, o20, "complete", qty_good=100)
    ev(api, o30, "start", line_id=p["l1"]["id"])
    r = ev(api, o30, "report", qty_good=96, qty_rework=4, rework_to_seq=10)
    back = {o["seq"]: o for o in r["operations"]}
    assert 10 in back, (r["operation"], [(o["seq"], o["status"]) for o in r["operations"]], r["event"])
    assert back[10]["status"] == "paused" and back[10]["qty_rework_in"] == 4 and back[10]["qty_available"] == 4
    assert r["operation"]["qty_rework_out"] == 4 and r["operation"]["qty_available"] == 0
    ev(api, o10, "complete", qty_good=4)
    ops = {o["seq"]: o for o in api.get(f"/work-orders/{p['wo']['id']}/operations")["items"]}
    assert ops[20]["qty_input"] == 104 and ops[20]["qty_available"] == 4 and ops[20]["status"] == "completed"


def test_t_f5_backflush_pending_then_retry(api):
    p = plant(api, ops=1, wo_qty=10, backflush=True, bf_stock=30, comp_qty_per=4)
    op = p["ops"][0]["id"]
    ev(api, op, "start", line_id=p["l1"]["id"])
    r = ev(api, op, "report", qty_good=10)
    assert [w["code"] for w in r["warnings"]] == ["FLR_BACKFLUSH_PENDING"]
    assert not [x for x in r["postings"] if x["type"] == "wo_issue"]
    d = api.get(f"/floor/operations/{op}")
    c = d["components"][0]
    assert c["backflush"] and c["backflush_pending"] == 40 and c["backflush_posted"] == 0
    assert api.post("/floor/backflush/retry", {}, status=200)["pending"] == 1
    api.receive(p["comp"]["id"], p["ls"]["id"], 10)
    out = api.post("/floor/backflush/retry", {"wo_id": p["wo"]["id"]}, status=200)
    assert out["posted"] == 1 and out["results"][0]["qty"] == 40
    assert api.get(f"/floor/operations/{op}")["components"][0]["backflush_posted"] == 40


def test_t_f7_serials(api):
    p = plant(api, ops=1, wo_qty=3, serialized=True, capture_seq=10)
    op = p["ops"][0]["id"]
    ev(api, op, "start", line_id=p["l1"]["id"])
    e = ev(api, op, "complete", qty_good=3, serials={"produced": ["S1", "S2"]}, status=422)["error"]
    assert e["code"] == "FLR_SERIALS_REQUIRED"
    r = ev(api, op, "complete", qty_good=3, serials={"produced": ["S1", "S2", "S3"]})
    assert r["wo"]["status"] == "completed"
    page = api.get("/serials", item_id=p["fg"]["id"])
    assert page["total"] == 3 and {u["status"] for u in page["items"]} == {"in_stock"}


def test_scan_queue_and_line_rules(api):
    p = plant(api, ops=2, wo_qty=5)
    wo = p["wo"]
    hit = api.get("/floor/scan", code=f"  {wo['number'].lower()}/20\r\n")
    assert hit["type"] == "operation" and hit["context"]["seq"] == 20
    assert api.get("/floor/scan", code="OP:NOPE", _status=404)["error"]["code"] == "FLR_SCAN_UNKNOWN"
    assert api.get("/floor/scan", code="LIN:l1")["type"] == "line"
    op = p["ops"][0]["id"]
    e = ev(api, op, "start", status=422)["error"]            # two eligible lines: choose one
    assert e["code"] == "FLR_LINE_NOT_ELIGIBLE" and len(e["details"]["eligible"]) == 2
    r = api.req("POST", "/floor/events", 201, json={"client_event_id": cid(), "scan": f"{wo['number']}/10",
                                                     "event_type": "start", "line_id": p["l1"]["id"]}).json()
    assert r["operation"]["status"] == "running"
    q = api.get("/floor/queue", line_id=p["l1"]["id"])
    assert [x["wo_operation_id"] for x in q["items"]] == [op] and q["items"][0]["status"] == "running"
    e = ev(api, op, "start", status=409)["error"]
    assert e["code"] == "FLR_INVALID_TRANSITION" and e["details"]["status"] == "running"
