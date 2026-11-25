"""S2 API (M8-DESIGN 5, 6.2): safety-stock proposals and approval with audit reason; kanban loops, scan signal,
receipt refills the card; MRP run uses the active forecast version."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from m8_helpers import add_history, audit_rows, wait_for


@pytest.mark.req("M8-SS-03")
def test_ss_run_and_approval_updates_item_with_reason(api, client):
    it = api.item("SYR-SS", "make", lead_time_days=8, standard_cost=0.2)
    api.put(f"/items/{it['id']}/planning", {"forecast": True, "order_pack_level": "case"}, 0)
    api.put(f"/items/{it['id']}/packaging", {"levels": [{"level": "each", "code": "EA", "qty_base": 1},
                                                         {"level": "case", "code": "CS", "qty_base": 1000}]}, 1)
    t = np.arange(24)
    add_history(client, it["id"], list(20000 + 3000 * np.sin(t)), date(2024, 11, 1), source="import")
    r = api.post("/forecast/runs", {"as_of": "2026-11-25", "horizon_periods": 6}, 202)
    run = wait_for(lambda: api.get(f"/forecast/runs/{r['id']}"), lambda x: x["status"] != "queued" and
                   x["status"] != "running")
    api.post(f"/forecast/versions/{run['version_id']}/activate", None, 200)
    ss = api.post("/invopt/runs", {}, 202)
    ss = wait_for(lambda: api.get(f"/invopt/runs/{ss['id']}"), lambda x: x["status"] in ("completed", "failed"))
    assert ss["status"] == "completed", ss
    assert ss["summary"]["lines"] == 1 and ss["summary"]["matrix"]["AX"]["count"] + \
        ss["summary"]["matrix"]["AY"]["count"] + ss["summary"]["matrix"]["AZ"]["count"] == 1
    ln = api.get(f"/invopt/runs/{ss['id']}/lines")["items"][0]
    assert ln["abc"] == "A" and ln["proposed_ss"] > 0 and ln["proposed_ss"] % 1000 == 0
    assert ln["lt_days"] == 8 and ln["decision"] == "pending"
    assert api.get(f"/items/{it['id']}/planning")["abc"] == "A"
    out = api.post(f"/invopt/runs/{ss['id']}/decide", {"line_ids": [ln["id"]], "decision": "approved",
                                                       "reason": "Q4 review"}, 200)
    assert out == {"decided": 1, "skipped": 0, "items_updated": 1}
    assert api.get(f"/items/{it['id']}")["safety_stock"] == ln["proposed_ss"]
    ev = [e for e in audit_rows(client, "item", it["id"]) if e["details"].get("source") == ss["number"]]
    assert ev and ev[0]["reason"] == f"{ss['number']} approved"
    again = api.post(f"/invopt/runs/{ss['id']}/decide", {"line_ids": [ln["id"]], "decision": "rejected",
                                                         "reason": "x"}, 200)
    assert again["skipped"] == 1


@pytest.mark.req("M8-KB-01")
def test_kanban_scan_creates_pr_and_receipt_refills(api, client):
    sup = api.supplier("SUP-TC")
    it = api.item("TIP-CAP", "buy", lead_time_days=5)
    api.post("/item-suppliers", {"item_id": it["id"], "supplier_id": sup["id"], "preferred": True,
                                 "lead_time_days": 5})
    loc = api.location("LS-ASM", "line_side")
    lp = api.post("/kanban/loops", {"item_id": it["id"], "location_id": loc["id"], "source": "buy", "cards": 3,
                                    "container_qty": 5000, "lead_time_days": 5})
    assert lp["number"].startswith("KB-") and lp["card_counts"] == {"full": 3, "empty": 0, "in_process": 0}
    cards = api.get(f"/kanban/loops/{lp['id']}/cards")["items"]
    hit = api.get("/floor/scan", code=cards[0]["code"])
    assert hit["type"] == "kanban_card" and hit["id"] == cards[0]["id"]
    out = api.post("/kanban/scan", {"code": cards[0]["code"]}, 200)
    sig = out["signal"]
    assert out["card"]["state"] == "empty" and sig["doc_type"] == "pr" and sig["qty"] == 5000
    pr = api.get(f"/purchase-requests/{sig['doc_id']}")
    assert pr["status"] == "submitted" and pr["supplier_id"] == sup["id"]
    assert pr["lines"][0]["schedules"][0]["qty"] == 5000
    api.err("POST", "/kanban/scan", 409, "KANBAN_CARD_STATE", json={"code": cards[0]["code"]})
    api.err("POST", "/kanban/scan", 422, "KANBAN_CODE_INVALID", json={"code": "WO-1234"})
    api.receive(it["id"], loc["id"], 5000)
    after = {c["id"]: c for c in api.get(f"/kanban/loops/{lp['id']}/cards")["items"]}
    assert after[cards[0]["id"]]["state"] == "full" and after[cards[0]["id"]]["doc_id"] is None
    api.err("PUT", f"/kanban/loops/{lp['id']}", 412, "VERSION_MISMATCH",
            json={**{k: lp[k] for k in ("item_id", "location_id", "source", "cards", "container_qty",
                                         "lead_time_days")}, "cards": 2}, headers={"If-Match": '"9"'})
    lp2 = api.put(f"/kanban/loops/{lp['id']}", {**{k: lp[k] for k in ("item_id", "location_id", "source",
                                                                      "container_qty", "lead_time_days")},
                                                "cards": 2}, lp["row_version"])
    assert lp2["cards"] == 2 and lp2["card_counts"]["full"] == 2
