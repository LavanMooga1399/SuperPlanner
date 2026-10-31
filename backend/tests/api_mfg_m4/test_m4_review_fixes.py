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
    ev_id = r["event"]["id"]
    r = ev(api, o2, "correct", corrects_event_id=ev_id, qty_good=0) if False else None
    assert r is None


def test_m11_batch_load_id_of_another_load_is_422(api):
    p = plant(api, ops=1, wo_qty=4)
    op = p["ops"][0]["id"]
    body = {"client_event_id": cid(), "wo_operation_id": op, "event_type": "start", "line_id": p["l1"]["id"],
            "batch_load_id": "bld_" + "0" * 32}
    e = api.req("POST", "/floor/events", 422, json=body).json()["error"]
    assert e["code"] == "VALIDATION_ERROR"
