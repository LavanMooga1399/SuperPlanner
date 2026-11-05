"""Integration (M5-DESIGN 4; T-I1..T-I7, T-I9, 14 Q2 both receipt modes, SSRF guard, HMAC signing)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, V1, Api, make_app
from superplanner.identity import crypto
from superplanner.integration import outbox

KEY = crypto.new_key()
received_status: list[list[int]] = []
INT = f"{V1}/integration"


class Int:
    def __init__(self, c: TestClient):
        self.c = c

    def req(self, method, path, status=None, **kw):
        r = self.c.request(method, INT + path, **kw)
        if status is not None:
            assert r.status_code == status, (method, path, r.status_code, r.text[:2000])
        return r

    def batch(self, entity, records, key, status=200, **kw):
        return self.req("POST", "/batches", status, json={"schema": "superplanner.v1", "entity": entity,
                                                          "records": records, **kw},
                        headers={"Idempotency-Key": key}).json()


def _enable(it: Int, **kw):
    cur = it.req("GET", "/settings", 200).json()
    body = {"enabled": True, "plant_code": "HBL1", "sor": {}, "goods_receipts_owner": "superplanner", **kw}
    return it.req("PUT", "/settings", 200, json=body, headers={"If-Match": f'"{cur["row_version"]}"'}).json()


DNS: dict[str, list[str]] = {}


def fake_getaddrinfo(host, port, *a, **kw):
    """Resolver for the SSRF tests: IP literals resolve to themselves, names via `DNS` (no network)."""
    import ipaddress
    import socket

    try:
        addrs = [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        if host not in DNS:
            raise socket.gaierror(socket.EAI_NONAME, "unknown host") from None
        addrs = DNS[host]
    return [(socket.AF_INET6 if ":" in x else socket.AF_INET, socket.SOCK_STREAM, 6, "",
             (x, port) if ":" not in x else (x, port, 0, 0)) for x in addrs]


@pytest.fixture
def env(db_url, monkeypatch):
    DNS.clear()
    DNS["erp.example.com"] = ["93.184.216.34"]
    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    received = []
    status: list[int] = []

    def post(url, body, headers):
        received.append((url, body, headers))
        return status.pop(0) if status else 200, ""

    post.status = status  # type: ignore[attr-defined]
    received_status[:] = [status]
    app = make_app(db_url, secrets_keys=[KEY], webhook_post=post, integration_allow_private_targets=False)
    with TestClient(app) as c:
        yield Int(c), Api(c), app, received


ITEMS = [{"ref": "ERP-1", "part_number": "R-10K", "description": "Resistor", "uom": "EA"},
         {"ref": "ERP-2", "part_number": "C-1U", "description": "Cap", "uom": "NOS"},
         {"ref": "ERP-3", "part_number": "IC-9", "description": "IC", "uom": "EA", "make_buy": "buy"}]


def test_t_i1_t_i4_batch_idempotency_and_value_maps(env):
    it, api, _app, _r = env
    it.batch("item", ITEMS, "k1", status=409)                                 # integration disabled
    _enable(it)
    out = it.batch("item", ITEMS, "k1")
    res = {r["ref"]: r for r in out["results"]}
    assert res["ERP-1"]["status"] == "created" and res["ERP-3"]["status"] == "created"
    assert res["ERP-2"]["status"] == "rejected" and res["ERP-2"]["errors"][0]["code"] == "INT_UNMAPPED_VALUE"
    again = it.req("POST", "/batches", 200, json={"schema": "superplanner.v1", "entity": "item", "records": ITEMS},
                   headers={"Idempotency-Key": "k1"})
    assert again.headers["Idempotent-Replay"] == "true" and again.json()["results"] == out["results"]
    e = it.req("POST", "/batches", 409, json={"schema": "superplanner.v1", "entity": "item", "records": ITEMS[:1]},
               headers={"Idempotency-Key": "k1"}).json()["error"]
    assert e["code"] == "INT_IDEMPOTENCY_CONFLICT"
    it.req("PUT", "/value-maps", 200, json={"rows": [{"domain": "uom", "external_value": "NOS",
                                                      "internal_value": "EA"}]})
    out2 = it.batch("item", ITEMS, "k2")
    st = {r["ref"]: r["status"] for r in out2["results"]}
    assert st == {"ERP-1": "unchanged", "ERP-2": "created", "ERP-3": "unchanged"}
    assert api.by_pn("C-1U")["uom"] == "EA" and api.by_pn("C-1U")["external_ref"] == "ERP-2"
    it.req("POST", "/batches", 422, json={"schema": "superplanner.v9", "entity": "item", "records": ITEMS},
           headers={"Idempotency-Key": "k3"})
    it.req("POST", "/batches", 422, json={"schema": "superplanner.v1", "entity": "item", "records": ITEMS})


def test_t_i2_t_i3_system_of_record(env):
    it, api, _app, _r = env
    _enable(it)
    it.batch("item", ITEMS[:1], "s1")
    item = api.by_pn("R-10K")
    body = {k: item[k] for k in ("part_number", "revision", "description", "uom", "make_buy", "active",
                                 "external_ref", "safety_stock")}
    e = api.req("PUT", f"/items/{item['id']}", 409, json={**body, "description": "Local edit"},
                headers={"If-Match": f'"{item["row_version"]}"'}).json()["error"]
    assert e["code"] == "INT_ERP_OWNED" and e["details"]["fields"] == ["description"]
    ok = api.put(f"/items/{item['id']}", {**body, "safety_stock": 25}, item["row_version"])
    assert ok["safety_stock"] == 25
    again = it.batch("item", [{**ITEMS[0], "description": "Resistor 10k"}], "s2")
    assert again["results"][0]["status"] == "updated"
    assert api.by_pn("R-10K")["safety_stock"] == 25                         # planning field kept (SP-owned)
    pr = it.batch("purchase_request", [{"ref": "PR-1"}], "s3")
    assert pr["results"][0]["status"] == "rejected" and pr["results"][0]["errors"][0]["code"] == "INT_SOR_CONFLICT"
    _enable(it, sor={"items": "superplanner"})
    it.batch("item", ITEMS[:1], "s4")["results"][0]["errors"][0]["code"] == "INT_SOR_CONFLICT"
    edited = api.by_pn("R-10K")
    assert api.put(f"/items/{edited['id']}", {**body, "description": "Now local", "safety_stock": 25},
                   edited["row_version"])["description"] == "Now local"


LOCAL = {"items": "superplanner", "suppliers": "superplanner", "purchase_orders": "superplanner"}


def test_t_i5_outbox_is_transactional_and_ordered(env):
    it, api, _app, _r = env
    _enable(it, sor=LOCAL)
    assert it.req("GET", "/events", 200).json()["items"] == []
    loc = api.location("ST")
    item = api.item("X1")
    bad = api.req("POST", "/inventory/postings", 422, json={"type": "receipt_misc", "lines": [
        {"item_id": item["id"], "location_id": loc["id"], "qty": 0.5}]})          # rolled back -> no event
    assert bad.status_code == 422
    assert it.req("GET", "/events", 200).json()["items"] == []
    api.receive(item["id"], loc["id"], 5)
    api.receive(item["id"], loc["id"], 7)
    ev = it.req("GET", "/events", 200).json()
    assert [e["type"] for e in ev["items"]] == ["inventory.posting", "inventory.posting"]
    assert ev["items"][0]["id"] < ev["items"][1]["id"] and ev["items"][0]["plant"]["code"] == "HBL1"
    nxt = it.req("GET", "/events", 200, params={"after": ev["next_after"]}).json()
    assert nxt["items"] == [] and nxt["next_after"] == ev["next_after"]
    assert ev["items"][1]["data"]["lines"][0]["qty"] == 7 and ev["items"][0]["schema"] == "superplanner.v1"


def test_t_i6_t_i7_webhooks_fifo_backoff_and_signature(env):
    from superplanner.api.mfg.services import integration as svc

    it, api, app, received = env
    _enable(it, sor=LOCAL)
    secret = "s" * 32
    bad = it.req("POST", "/endpoints", 422, json={"name": "lan", "url": "https://127.0.0.1/hook", "secret": secret})
    assert bad.json()["error"]["code"] == "INT_URL_NOT_ALLOWED"
    assert it.req("POST", "/endpoints", 422, json={"name": "x", "url": "http://erp.example.com/hook",
                                                   "secret": secret}).json()["error"]["code"] == "INT_URL_NOT_ALLOWED"
    ep = it.req("POST", "/endpoints", 201, json={"name": "erp", "url": "https://erp.example.com/hook",
                                                 "secret": secret}).json()
    loc = api.location("ST")
    item = api.item("X1")
    for q in (1, 2):
        api.receive(item["id"], loc["id"], q)
    ctx = app.state.ctx
    from superplanner.api.db.ownership import owner_scope

    received_status[0][:] = [500, 500, 500]
    t0 = datetime.now(UTC)
    with owner_scope("usr_local"):
        r1 = svc.deliver_now(ctx, now=t0)
        assert r1 == {"delivered": 0, "failed": 1, "dead": 0} and len(received) == 1
        assert svc.deliver_now(ctx, now=t0 + timedelta(seconds=10))["failed"] == 0   # backoff 30 s: not yet
        svc.deliver_now(ctx, now=t0 + timedelta(seconds=31))                          # 2nd attempt (500)
        svc.deliver_now(ctx, now=t0 + timedelta(seconds=92))                          # 3rd attempt (500)
        done = svc.deliver_now(ctx, now=t0 + timedelta(seconds=300))                  # 4th: 200, then event 2
    assert done["delivered"] == 2 and len(received) == 5
    seqs = [int(h["SP-Event-Id"]) for _u, _b, h in received]
    assert seqs[:4] == [seqs[0]] * 4 and seqs[4] > seqs[0]                           # FIFO: event 2 waited
    d = it.req("GET", "/deliveries", 200).json()["items"]
    first = next(x for x in d if x["event_seq"] == seqs[0])
    assert first["attempts"] == 4 and first["status"] == "delivered"
    _u, body, h = received[-1]
    assert outbox.verify_signature(secret, body, h["SP-Signature"], now=int(t0.timestamp()) + 300)
    assert not outbox.verify_signature("wrong-secret-xxxxxxxxxxxxxxxx", body, h["SP-Signature"],
                                       now=int(t0.timestamp()) + 300)
    assert not outbox.verify_signature(secret, body + b" ", h["SP-Signature"], now=int(t0.timestamp()) + 300)
    assert not outbox.verify_signature(secret, body, h["SP-Signature"], now=int(t0.timestamp()) + 5000)
    assert json.loads(body)["type"] == "inventory.posting"
    assert it.req("GET", "/endpoints", 200).json()["items"][0]["cursor"] == seqs[4]
    import sqlalchemy as sa

    eng = sa.create_engine(app.state.ctx.settings.database_url)
    with eng.connect() as conn:
        assert secret not in conn.execute(sa.text("SELECT secret_enc FROM int_endpoints")).scalar()   # I4
    eng.dispose()
    assert ep["secret_set"] and "secret" not in ep


def test_q2_goods_receipts_owner_both_modes_and_t_i9_reconciliation(env):
    it, api, _app, _r = env
    _enable(it, sor=LOCAL)
    sup = api.supplier("SUP")
    item = api.item("X1")
    loc = api.location("STORES", receipt_default=True)
    po = api.post("/purchase-orders", {"supplier_id": sup["id"], "lines": [
        {"item_id": item["id"], "schedules": [{"requested_date": "2026-12-01", "qty": 10}]}]})
    po = api.post(f"/purchase-orders/{po['id']}/issue", {}, status=200, version=po["row_version"])
    sched = po["lines"][0]["schedules"][0]["id"]
    rec = {"ref": "GR-1", "po_ref": po["number"], "line_no": po["lines"][0]["line_no"], "schedule_seq": 1,
           "location_code": "STORES", "qty": 4, "received_on": "2026-11-04"}
    r = it.batch("po_receipt", [rec], "g1")["results"][0]
    assert r["status"] == "rejected" and r["errors"][0]["code"] == "INT_SOR_CONFLICT"        # SP books receipts
    api.post("/inventory/postings", {"type": "po_receipt", "lines": [{"schedule_id": sched, "qty": 2,
                                                                      "location_id": loc["id"]}]})
    _enable(it, sor=LOCAL, goods_receipts_owner="erp")
    e = api.req("POST", "/inventory/postings", 409, json={"type": "po_receipt", "lines": [
        {"schedule_id": sched, "qty": 1, "location_id": loc["id"]}]}).json()["error"]
    assert e["code"] == "INT_ERP_OWNED"
    assert it.batch("po_receipt", [rec], "g2")["results"][0]["status"] == "created"
    assert it.batch("po_receipt", [rec], "g3")["results"][0]["status"] == "unchanged"         # ref idempotent
    assert it.req("GET", "/settings", 200).json()["sor"]["po_receipts"] == "erp"
    onhand = sum(b["qty_on_hand"] for b in api.get("/inventory/balances", item_id=item["id"])["items"])
    assert onhand == 6
    rc = it.req("POST", "/reconciliations", 201, json={"entities": ["stock"], "records": {"stock": [
        {"ref": "S1", "item_ref": "X1", "location_code": "STORES", "qty": 8, "as_at": "2026-11-05T00:00:00Z"}]}})
    s = rc.json()
    assert s["summary"]["stock"]["different"] == 1 and s["results"]["stock"]["different"][0]["delta"] == 2
    assert sum(b["qty_on_hand"] for b in api.get("/inventory/balances", item_id=item["id"])["items"]) == 6


def test_integration_permissions_and_token_scopes(db_url):
    from apimfgm2_helpers import acc_app, sign_up

    app = acc_app(db_url, secrets_keys=[KEY])
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        oid = oc.get(f"{V1}/auth/session").json()["user"]["id"]
        Int(oc).req("PUT", "/settings", 200, json={"enabled": True, "plant_code": "P1"},
                    headers={"If-Match": '"0"'})
        vc = sign_up(app, "view@example.com")
        oc.post(f"{MFG}/members", json={"email": "view@example.com", "roles": ["planner"]})
        vc.headers["X-SP-Workspace"] = oid
        e = Int(vc).req("GET", "/settings", 403).json()["error"]
        assert e["details"]["permission"] == "integration_admin"
        t = oc.post(f"{V1}/tokens", json={"name": "erp", "scopes": ["integration.read"]}).json()["token"]
        b = TestClient(app)
        b.headers["Authorization"] = f"Bearer {t}"
        assert Int(b).req("GET", "/events", 200).json()["items"] == []
        e = Int(b).req("POST", "/batches", 403, json={"schema": "superplanner.v1", "entity": "item",
                                                       "records": ITEMS}, headers={"Idempotency-Key": "x"})
        assert e.json()["error"]["code"] == "TOKEN_SCOPE"
        vt = vc.post(f"{V1}/tokens", json={"name": "v", "scopes": ["integration.read"],
                                           "workspace_owner_id": oid}).json()["token"]
        bv = TestClient(app)
        bv.headers["Authorization"] = f"Bearer {vt}"
        assert Int(bv).req("GET", "/events", 403).json()["error"]["code"] == "MFG_FORBIDDEN"   # holder no admin
