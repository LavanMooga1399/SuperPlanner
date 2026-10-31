"""M4 review fixes (one test per defect, LEAD review of WP-S)."""

from __future__ import annotations

import threading

from apimfgm4_helpers import cid, ev, plant
from superplanner.api.mfg.services import floor as F


def _on_hand(api, item_id):
    return sum(b["qty_on_hand"] for b in api.get("/inventory/balances", item_id=item_id)["items"])


def test_m1_concurrent_event_does_not_double_post(api, monkeypatch):
    """A second event committed while this one waits for the WO lock: the receipt delta uses the fresh state."""
    p = plant(api, ops=1, wo_qty=10)
    op = p["ops"][0]["id"]
    ev(api, op, "start", line_id=p["l1"]["id"])
    orig = F.lock_wo
    armed = {"on": True}

    def racing(s, wo_id):
        s.execute(F.select(F.MfgWoOperationRow).where(F.MfgWoOperationRow.id == op)).scalars().first()  # cached
        if armed["on"]:
            armed["on"] = False
            t = threading.Thread(target=lambda: ev(api, op, "report", qty_good=3))
            t.start()
            t.join()
        return orig(s, wo_id)

    monkeypatch.setattr(F, "lock_wo", racing)
    r = ev(api, op, "report", qty_good=4)
    assert r["operation"]["qty_good"] == 7 and _on_hand(api, p["fg"]["id"]) == 7
    assert api.get(f"/work-orders/{p['wo']['id']}")["qty_completed"] == 7


def test_m4_skipping_the_last_op_receives_the_passed_input_and_reopen_reverses(api):
    p = plant(api, ops=2, wo_qty=10)
    o1, o2 = p["ops"][0]["id"], p["ops"][1]["id"]
    ev(api, o1, "start", line_id=p["l1"]["id"])
    ev(api, o1, "complete", qty_good=10)
    r = ev(api, o2, "skip", reason_code="NOT_NEEDED")
    assert r["operation"]["status"] == "skipped" and r["wo"]["status"] == "completed"
    assert _on_hand(api, p["fg"]["id"]) == 10
    r = ev(api, o2, "reopen")
    assert r["operation"]["status"] == "paused" and r["wo"]["status"] == "in_progress"
    assert _on_hand(api, p["fg"]["id"]) == 0


def test_m11_batch_load_id_of_another_load_is_422(api):
    p = plant(api, ops=1, wo_qty=4)
    op = p["ops"][0]["id"]
    body = {"client_event_id": cid(), "wo_operation_id": op, "event_type": "start", "line_id": p["l1"]["id"],
            "batch_load_id": "bld_" + "0" * 32}
    e = api.req("POST", "/floor/events", 422, json=body).json()["error"]
    assert e["code"] == "VALIDATION_ERROR"


def test_m3_manual_receipt_refused_on_floor_tracked_wo_and_prior_receipts_count(api):
    p = plant(api, ops=1, wo_qty=10)
    op = p["ops"][0]["id"]
    api.post("/inventory/postings", {"type": "wo_receipt", "lines": [
        {"wo_id": p["wo"]["id"], "location_id": p["fg_loc"]["id"], "qty": 4}]})          # before floor tracking
    ev(api, op, "start", line_id=p["l1"]["id"])
    e = api.err("POST", "/inventory/postings", 409, "WO_FLOOR_TRACKED", json={"type": "wo_receipt", "lines": [
        {"wo_id": p["wo"]["id"], "location_id": p["fg_loc"]["id"], "qty": 1}]})
    assert e["details"]["wo_id"] == p["wo"]["id"]
    r = ev(api, op, "complete", qty_good=10)
    assert r["wo"]["qty_completed"] == 10 and _on_hand(api, p["fg"]["id"]) == 10      # 4 manual + 6 by the floor


def _publish(api):
    from apimfgm3_helpers import wait_run

    api.post("/mrp/runs", {})
    run = wait_run(api, api.post("/aps/runs", {"improve_seconds": 0}, status=202)["id"])
    api.post(f"/aps/runs/{run['id']}/publish", {}, status=200, version=run["row_version"])
    return run


def test_m5_auto_publish_never_confirms_a_stale_basis(api, monkeypatch):
    import time

    from apimfgm4_helpers import PLANT_FIELDS
    from superplanner.api.errors import ApiError
    from superplanner.api.mfg.services import aps

    p = plant(api, ops=1, wo_qty=4)
    _publish(api)
    pl = api.get("/plant")
    body = {k: v for k, v in pl.items() if k in PLANT_FIELDS}
    body.update(replan_policy="auto_publish", replan_debounce_minutes=0)
    api.put("/plant", body, pl["row_version"])
    seen = []

    def stale(ctx, run_id, if_match, confirm_stale_basis=False):
        seen.append(confirm_stale_basis)
        raise ApiError(409, "APS_RUN_STALE_BASIS", "stale", {})

    monkeypatch.setattr(aps, "publish_run", stale)
    d = api.post("/downtime", {"line_id": p["l1"]["id"]})
    if not d["triggers"]:
        d = api.post("/downtime", {"line_id": p["l2"]["id"]})
    t = time.monotonic()
    while not any(n["kind"] == "replan.not_published" for n in api.get("/notifications")["items"]):
        assert time.monotonic() - t < 60
        time.sleep(0.3)
    assert seen and seen[0] is False


def test_m9_triggers_attach_only_while_the_run_is_queued(api):
    from superplanner.api.mfg.db_models_m3 import MfgApsRunRow
    from superplanner.api.mfg.services import replan
    from superplanner.api.mfg.services.m2util import run_tx

    p = plant(api, ops=1, wo_qty=4)
    run = _publish(api)
    ctx = api.c.app.state.ctx

    def attach(s):
        r = s.get(MfgApsRunRow, run["id"])
        return replan._attach(s, [], r.id), replan._attach(s, [], r.id, allow_running=True)

    from superplanner.api.db.ownership import owner_scope

    with owner_scope("usr_local"):
        assert run_tx(ctx, attach) == (False, False)          # completed: never
    assert p


def test_m10_concurrent_downtime_on_one_line_creates_one(api):
    import threading

    p = plant(api, ops=1, wo_qty=4)
    codes = []

    def post():
        codes.append(api.req("POST", "/downtime", None, json={"line_id": p["l1"]["id"]}).status_code)

    ts = [threading.Thread(target=post) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [201, 409, 409, 409]
    assert api.get("/downtime", open=True)["total"] == 1


def test_m2_missing_routing_operations_are_added_on_access(api):
    from sqlalchemy import delete

    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models_m4 import MfgWoOperationRow

    p = plant(api, ops=3, wo_qty=4)
    ctx = api.c.app.state.ctx
    with owner_scope("usr_local"), ctx.db.write() as s:          # a partly migrated WO: only seq 10 has a row
        s.execute(delete(MfgWoOperationRow).where(MfgWoOperationRow.wo_id == p["wo"]["id"],
                                                  MfgWoOperationRow.seq > 10))
    items = api.get(f"/work-orders/{p['wo']['id']}/operations")["items"]
    assert [(o["seq"], bool(o["id"])) for o in items] == [(10, True), (20, True), (30, True)]
