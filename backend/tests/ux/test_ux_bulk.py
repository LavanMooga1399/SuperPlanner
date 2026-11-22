"""Bulk actions: per-record results with the single call's rules (If-Match, state, shortage override,
self-approval), one audit event per record, Idempotency-Key replay / conflict, validation and permissions."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apimfgm2_helpers import Api, acc_app, sign_up
from superplanner.api.db import AuditEventRow
from superplanner.api.db.ownership import system_scope


def _due(days: int = 14) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _sched(days: int, qty: float) -> dict:
    return {"requested_date": _due(days), "qty": qty}


def _plant(api: Api) -> dict:
    g = api.post("/groups", {"code": "G", "name": "G"})
    api.post("/lines", {"code": "L", "name": "L", "group_id": g["id"]})
    c1 = api.item("C1")
    p = api.item("P", "make", lead_time_days=2)
    bom = api.post("/boms", {"item_id": p["id"], "lines": [{"find_number": "10", "child_item_id": c1["id"],
                                                             "qty_per": 1}]})
    api.post(f"/boms/{bom['id']}/release", {"effective_from": "2026-01-01"}, version=bom["row_version"], status=200)
    rt = api.post("/routings", {"item_id": p["id"], "operations": [{"seq": 10, "name": "A", "group_id": g["id"],
                                                                     "run_minutes": 1}]})
    api.post(f"/routings/{rt['id']}/release", {"effective_from": "2026-01-01"}, version=rt["row_version"], status=200)
    return {"c1": c1, "p": p, "st": api.location("ST")}


def _refs(*recs: dict) -> list[dict]:
    return [{"id": r["id"], "row_version": r["row_version"]} for r in recs]


def _audits(client: TestClient, entity: str, action: str) -> int:
    with system_scope(), client.app.state.ctx.db.read() as s:
        return int(s.execute(select(func.count()).select_from(AuditEventRow).where(
            AuditEventRow.entity_type == entity, AuditEventRow.action == action)).scalar() or 0)


def test_work_orders_release_close_cancel_with_per_record_results(api: Api, client: TestClient):
    x = _plant(api)
    api.receive(x["c1"]["id"], x["st"]["id"], 5)
    w1, w2, w3, w4 = (api.post("/work-orders", {"item_id": x["p"]["id"], "qty": q, "due_date": _due()})
                      for q in (2, 3, 50, 1))
    # w3 is short (needs the shortage override), w4 is sent with a stale version, one id is unknown
    body = {"items": _refs(w1, w2, w3) + [{"id": w4["id"], "row_version": 9}, {"id": "wo_missing", "row_version": 1}]}
    out = api.post("/bulk/work-orders/release", body, status=200)
    assert (out["action"], out["total"], out["succeeded"], out["failed"]) == ("work-orders/release", 5, 2, 3)
    res = {r["id"]: r for r in out["results"]}
    assert [r["id"] for r in out["results"]] == [w1["id"], w2["id"], w3["id"], w4["id"], "wo_missing"]
    assert res[w1["id"]]["ok"] and res[w1["id"]]["status"] == 200 and res[w1["id"]]["record_status"] == "released"
    assert res[w1["id"]]["row_version"] == api.get(f"/work-orders/{w1['id']}")["row_version"]
    assert (res[w3["id"]]["status"], res[w3["id"]]["code"]) == (409, "WO_KIT_INCOMPLETE")
    assert (res[w4["id"]]["status"], res[w4["id"]]["code"], res[w4["id"]]["row_version"]) == \
        (412, "VERSION_MISMATCH", w4["row_version"])
    assert (res["wo_missing"]["status"], res["wo_missing"]["code"]) == (404, "NOT_FOUND")
    assert set(res[w3["id"]]) == {"id", "ok", "status", "code", "message", "row_version", "record_status", "details"}
    assert _audits(client, "mfg_work_order", "release") == 2
    # with the override reason the short WO releases (the rule is the single call's)
    out = api.post("/bulk/work-orders/release", {"items": _refs(w3), "override_reason": "partial kit"}, status=200)
    assert out["succeeded"] == 1 and api.get(f"/work-orders/{w3['id']}")["status"] == "released"
    # cancel: released ones without transactions cancel; close needs completed -> state error per record
    w1 = api.get(f"/work-orders/{w1['id']}")
    out = api.post("/bulk/work-orders/close", {"items": _refs(w1)}, status=200)
    assert out["results"][0]["code"] == "MFG_INVALID_STATE" and out["results"][0]["status"] == 409
    out = api.post("/bulk/work-orders/cancel", {"items": _refs(w1, api.get(f"/work-orders/{w4['id']}"))}, status=200)
    assert out["succeeded"] == 2 and _audits(client, "mfg_work_order", "cancel") == 2


def test_idempotency_replay_conflict_and_validation(api: Api, client: TestClient):
    x = _plant(api)
    w = api.post("/work-orders", {"item_id": x["p"]["id"], "qty": 1, "due_date": _due()})
    h = {"Idempotency-Key": "bulk-1"}
    body = {"items": _refs(w), "override_reason": "ok"}
    r1 = api.req("POST", "/bulk/work-orders/release", 200, json=body, headers=h)
    assert r1.json()["succeeded"] == 1 and "Idempotent-Replay" not in r1.headers
    r2 = api.req("POST", "/bulk/work-orders/release", 200, json=body, headers=h)
    assert r2.headers["Idempotent-Replay"] == "true" and r2.json() == r1.json()
    assert _audits(client, "mfg_work_order", "release") == 1            # not applied twice
    api.err("POST", "/bulk/work-orders/release", 409, "INV_IDEMPOTENCY_CONFLICT", json={**body, "reserve": True},
            headers=h)
    api.err("POST", "/bulk/work-orders/cancel", 409, "INV_IDEMPOTENCY_CONFLICT", json={"items": _refs(w)}, headers=h)
    api.err("POST", "/bulk/work-orders/release", 422, "VALIDATION_ERROR", json=body, headers={"Idempotency-Key": "a b"})
    # body validation
    api.err("POST", "/bulk/work-orders/close", 422, "VALIDATION_ERROR", json={"items": []})
    api.err("POST", "/bulk/work-orders/close", 422, "VALIDATION_ERROR",
            json={"items": [{"id": f"x{i}", "row_version": 1} for i in range(201)]})
    api.err("POST", "/bulk/work-orders/close", 422, "VALIDATION_ERROR", json={"items": _refs(w, w)})
    api.err("POST", "/bulk/work-orders/close", 422, "VALIDATION_ERROR", json={"items": [{"id": w["id"]}]})
    api.err("POST", "/bulk/purchase-requests/reject", 422, "VALIDATION_ERROR", json={"items": _refs(w)})
    api.err("POST", "/bulk/work-orders/close", 422, "VALIDATION_ERROR", json={"items": _refs(w), "x": 1})


def test_purchasing_and_demand(api: Api, client: TestClient):
    sup = api.supplier("S1")
    it = api.item("FPGA")
    api.post("/item-suppliers", {"item_id": it["id"], "supplier_id": sup["id"], "preferred": True, "unit_price": 1})
    prs = [api.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [_sched(30, 1)]}]})
           for _ in range(3)]
    out = api.post("/bulk/purchase-requests/submit", {"items": _refs(*prs)}, status=200)
    assert out["succeeded"] == 3 and _audits(client, "mfg_purchase_doc", "submit") == 3
    prs = [api.get(f"/purchase-requests/{p['id']}") for p in prs]
    out = api.post("/bulk/purchase-requests/reject", {"items": _refs(prs[0]), "reason": "not now"}, status=200)
    assert out["succeeded"] == 1 and api.get(f"/purchase-requests/{prs[0]['id']}")["rejected_reason"] == "not now"
    out = api.post("/bulk/purchase-requests/approve", {"items": _refs(*prs)}, status=200)   # owner may self-approve
    assert [r["ok"] for r in out["results"]] == [False, True, True]
    assert out["results"][0]["code"] == "VERSION_MISMATCH"
    po = api.post("/purchase-orders", {"supplier_id": sup["id"], "lines": [{"item_id": it["id"],
                                                                             "schedules": [_sched(5, 1)]}]})
    out = api.post("/bulk/purchase-orders/cancel", {"items": _refs(po)}, status=200)
    assert out["results"][0]["record_status"] == "cancelled"
    o = api.post("/demand-orders", {"demand_type": "customer", "lines": [{"item_id": it["id"], "qty": 1,
                                                                          "due_date": _due(20)}]})
    o2 = api.post("/demand-orders", {"demand_type": "customer", "lines": [{"item_id": it["id"], "qty": 1,
                                                                           "due_date": _due(20)}]})
    o = api.post(f"/demand-orders/{o['id']}/open", version=o["row_version"], status=200)
    out = api.post("/bulk/demand-orders/close", {"items": _refs(o)}, status=200)
    assert out["results"][0]["record_status"] == "closed"
    out = api.post("/bulk/demand-orders/cancel", {"items": _refs(o2)}, status=200)
    assert out["succeeded"] == 1 and api.get(f"/demand-orders/{o2['id']}")["status"] == "cancelled"


def test_member_permissions_and_self_approval(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        owner = Api(oc)
        it = owner.item("C-1")
        both = Api(sign_up(app, "both@example.com"), oid)
        viewer = Api(sign_up(app, "view@example.com"), oid)
        for email, roles in (("both@example.com", ["planner", "approver"]), ("view@example.com", ["viewer"])):
            owner.post("/members", {"email": email, "roles": roles})
        mine = both.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [_sched(30, 1)]}]})
        theirs = owner.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [_sched(30, 1)]}]})
        mine = both.post(f"/purchase-requests/{mine['id']}/submit", version=mine["row_version"], status=200)
        theirs = owner.post(f"/purchase-requests/{theirs['id']}/submit", version=theirs["row_version"], status=200)
        out = both.post("/bulk/purchase-requests/approve", {"items": _refs(mine, theirs)}, status=200)
        assert [(r["ok"], r["code"]) for r in out["results"]] == [(False, "PUR_SELF_APPROVAL"), (True, None)]
        e = viewer.err("POST", "/bulk/purchase-requests/approve", 403, "MFG_FORBIDDEN", json={"items": _refs(mine)})
        assert e["details"]["permission"] == "pr_approve"
        # a viewer token cannot bulk-act either (token permissions are capped by scopes)
        raw = oc.post("/api/v1/tokens", json={"name": "t", "scopes": ["view"]}).json()["token"]
        t = TestClient(app)
        t.headers["Authorization"] = f"Bearer {raw}"
        r = t.post("/api/v1/mfg/bulk/demand-orders/close", json={"items": [{"id": "x", "row_version": 1}]})
        assert r.status_code == 403
        # a stranger (no membership) addressing the owner's ids in their own workspace: per-record 404, the same
        # answer as for an unknown id (nothing about the owner's data is revealed)
        stranger = Api(sign_up(app, "stranger@example.com"))
        out = stranger.post("/bulk/purchase-requests/submit", {"items": [{"id": theirs["id"], "row_version": 2},
                                                                         {"id": "pur_unknown", "row_version": 2}]},
                            status=200)
        a_, b_ = out["results"]
        assert (a_["status"], a_["code"], b_["status"], b_["code"]) == (404, "NOT_FOUND", 404, "NOT_FOUND")
        assert a_["message"].replace(theirs["id"], "<ID>") == b_["message"].replace("pur_unknown", "<ID>")
        # Idempotency-Keys are per acting user: the owner's key does not replay the member's response
        h = {"Idempotency-Key": "same"}
        mine = both.get(f"/purchase-requests/{mine['id']}")
        assert both.req("POST", "/bulk/purchase-requests/approve", 200, json={"items": _refs(mine)},
                        headers=h).json()["failed"] == 1
        r = owner.req("POST", "/bulk/purchase-requests/approve", 200, json={"items": _refs(mine)}, headers=h)
        assert "Idempotent-Replay" not in r.headers and r.json()["succeeded"] == 1


def test_running_key_is_in_progress_and_stale_running_is_taken_over(api: Api, client: TestClient):
    from datetime import UTC, datetime

    from superplanner.api.mfg.db_models_ux import MfgBulkRequestRow
    from superplanner.api.mfg.services.m2util import request_hash

    x = _plant(api)
    w = api.post("/work-orders", {"item_id": x["p"]["id"], "qty": 1, "due_date": _due()})
    body = {"items": _refs(w)}
    h = request_hash({"action": "work-orders/cancel", **body})
    now = datetime.now(UTC)
    with system_scope(), client.app.state.ctx.db.write() as s:
        s.add(MfgBulkRequestRow(id="blk_1", owner_id="usr_local", actor_id="usr_local", idempotency_key="k1",
                                action="work-orders/cancel", request_hash=h, status="running", response=None,
                                created_at=now, updated_at=now))
    e = api.err("POST", "/bulk/work-orders/cancel", 409, "MFG_BULK_IN_PROGRESS", json=body,
                headers={"Idempotency-Key": "k1"})
    assert e["details"] == {}
    with system_scope(), client.app.state.ctx.db.write() as s:
        s.get(MfgBulkRequestRow, "blk_1").updated_at = now - timedelta(minutes=11)
    r = api.req("POST", "/bulk/work-orders/cancel", 200, json=body, headers={"Idempotency-Key": "k1"})
    assert r.json()["succeeded"] == 1
    assert api.req("POST", "/bulk/work-orders/cancel", 200, json=body,
                   headers={"Idempotency-Key": "k1"}).headers["Idempotent-Replay"] == "true"
