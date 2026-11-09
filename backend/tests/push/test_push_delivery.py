"""S3 (M6-DESIGN 2, 9 T-P2, PU1): subscriptions, encrypted delivery through a local push-service stub, 404/410
cleanup, the per-plant `push_delivery` duty and fan-out to 1,000 subscriptions."""

from __future__ import annotations

import json
import threading
import time

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up
from superplanner.push import ece, vapid
from superplanner.push.vapid import b64u

PEM = vapid.generate_private_key_pem()


class Stub:
    """Local push service: records requests, decrypts with the device keys, answers a chosen status."""

    def __init__(self) -> None:
        self.keys: dict[str, tuple[ec.EllipticCurvePrivateKey, bytes]] = {}
        self.got: list[dict] = []
        self.status: dict[str, int] = {}
        self.lock = threading.Lock()

    def device(self, n: int) -> dict:
        k = ec.generate_private_key(ec.SECP256R1())
        auth = bytes([n % 256]) * 16
        ep = f"https://push.example.test/send/{n}"
        self.keys[ep] = (k, auth)
        pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return {"endpoint": ep, "keys": {"p256dh": b64u(pub), "auth": b64u(auth)}}

    def __call__(self, url, headers, body, timeout):
        k, auth = self.keys[url]
        with self.lock:
            self.got.append({"url": url, "headers": headers, "payload": json.loads(ece.decrypt(body, k, auth))})
        return self.status.get(url, 201)


@pytest.fixture
def stub() -> Stub:
    return Stub()


def _app(db_url, stub, **kw):
    kw.setdefault("webpush_extra_hosts", ["push.example.test"])
    return acc_app(db_url, webpush_vapid_private_key=PEM, webpush_subject="mailto:ops@hbl.example", push_post=stub,
                   **kw)


def test_subscribe_validate_list_delete(db_url, stub):
    app = _app(db_url, stub)
    a, b = sign_up(app, "a@p.example"), sign_up(app, "b@p.example")
    key = a.get(f"{V1}/push/vapid-public-key").json()
    assert key["enabled"] is True and key["public_key"] == vapid.public_key(PEM)
    dev = stub.device(1)
    r = a.post(f"{V1}/push/subscriptions", json={**dev, "topics": ["critical_alerts"]})
    assert r.status_code == 201 and r.json()["endpoint_host"] == "push.example.test"
    sid = r.json()["id"]
    again = a.post(f"{V1}/push/subscriptions", json={**dev, "topics": ["approvals"]})   # same endpoint: updated
    assert again.json()["id"] == sid and again.json()["topics"] == ["approvals"]
    bad = dict(dev, keys={"p256dh": "A" * 40, "auth": dev["keys"]["auth"]})
    r = a.post(f"{V1}/push/subscriptions", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "PUSH_SUBSCRIPTION_INVALID"
    r = a.post(f"{V1}/push/subscriptions", json=dict(dev, endpoint="http://insecure.example/x"))
    assert r.status_code == 422
    assert b.delete(f"{V1}/push/subscriptions/{sid}").status_code == 404           # not b's
    assert len(a.get(f"{V1}/push/subscriptions").json()["items"]) == 1
    # keys are not stored in clear text when SECRETS_KEYS is configured (here: none -> raw, documented)
    assert a.delete(f"{V1}/push/subscriptions/{sid}").status_code == 204


def test_delivery_encrypted_payload_and_410_cleanup(db_url, stub):
    """T-P2: an endpoint answering 410 is deleted; payload = title, short body, link path only."""
    from superplanner.push import delivery

    app = _app(db_url, stub)
    a = sign_up(app, "a@p.example")
    uid = a.get(f"{V1}/auth/session").json()["user"]["id"]
    d1, d2 = stub.device(1), stub.device(2)
    for d in (d1, d2):
        assert a.post(f"{V1}/push/subscriptions", json={**d, "topics": ["digest_ready"]}).status_code == 201
    stub.status[d2["endpoint"]] = 410
    n = delivery.send_to_user(app.state.ctx, uid, "digest_ready", "Your digest is ready", "Sent.", "/mfg/dashboard")
    assert n == 1 and len(stub.got) == 2
    g = stub.got[0]
    assert g["payload"] == {"title": "Your digest is ready", "body": "Sent.", "link": "/mfg/dashboard",
                            "topic": "digest_ready"}
    h = g["headers"]
    assert h["Content-Encoding"] == "aes128gcm" and h["TTL"] == "86400" and h["Urgency"] == "normal"
    assert h["Authorization"].startswith("vapid t=") and f"k={vapid.public_key(PEM)}" in h["Authorization"]
    items = a.get(f"{V1}/push/subscriptions").json()["items"]
    assert len(items) == 1 and items[0]["active"] is True and "failures" not in items[0]
    assert delivery.send_to_user(app.state.ctx, uid, "approvals", "x", "", "/m") == 0     # topic not subscribed


def test_plant_duty_sends_critical_alerts_and_approvals(db_url, stub):
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.services import replan
    from superplanner.integration import scheduler

    app = _app(db_url, stub)
    owner = sign_up(app, "owner@p.example")
    viewer = sign_up(app, "viewer@p.example")
    oid = owner.get(f"{V1}/auth/session").json()["user"]["id"]
    Api(owner).post("/members", {"email": "viewer@p.example", "roles": ["viewer"]})
    Api(owner).item("PU-1")                                          # the plant row exists
    dv, do = stub.device(7), stub.device(8)
    assert viewer.post(f"{V1}/push/subscriptions", json={**dv, "topics": ["critical_alerts", "approvals"]}
                       ).status_code == 201
    assert owner.post(f"{V1}/push/subscriptions", json={**do, "topics": ["approvals"]}).status_code == 201
    ctx = app.state.ctx
    with owner_scope(oid), ctx.db.write() as s:
        replan.notify(s, "line_down", "critical", "SMT-1 is down", "Feeder jam at 10:12 (operator note)",
                      "/m/lines/lin_1")
    got = scheduler.tick(ctx, duties={"push_delivery"})
    assert ("push_delivery", oid) in got
    t0 = time.monotonic()
    while not stub.got and time.monotonic() - t0 < 30:
        time.sleep(0.1)
    assert [g["url"] for g in stub.got] == [dv["endpoint"]]          # floor_view + critical_alerts only
    p = stub.got[0]
    assert p["payload"]["title"] == "SMT-1 is down" and p["payload"]["link"] == "/m/lines/lin_1"
    assert "Feeder" not in json.dumps(p["payload"]) and p["headers"]["Urgency"] == "high"
    # approvals: a submitted PR reaches the owner (pr_approve) but not the viewer
    api = Api(owner)
    it = api.get("/items", q="PU-1")["items"][0]
    pr = api.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [
        {"requested_date": "2026-12-01", "qty": 1}]}]})
    t0 = time.monotonic()
    while scheduler.tick(ctx, duties={"push_delivery"}) == [] and time.monotonic() - t0 < 10:
        time.sleep(0.2)                                              # the previous run must finish first
    api.post(f"/purchase-requests/{pr['id']}/submit", {}, status=200, version=pr["row_version"])
    stub.got.clear()
    t0 = time.monotonic()
    while not stub.got and time.monotonic() - t0 < 30:
        scheduler.tick(ctx, duties={"push_delivery"})
        time.sleep(0.2)
    assert [g["url"] for g in stub.got] == [do["endpoint"]] and stub.got[0]["payload"]["topic"] == "approvals"


def test_fanout_1000_subscriptions_pu1(db_url, stub):
    from superplanner.api.db import new_id, utcnow
    from superplanner.push import delivery

    app = _app(db_url, stub)
    with TestClient(app):
        a = sign_up(app, "a@p.example")
        uid = a.get(f"{V1}/auth/session").json()["user"]["id"]
        rows = []
        for i in range(1000):
            d = stub.device(1000 + i)
            rows.append({"id": new_id("psb_"), "user_id": uid, "endpoint": d["endpoint"], "endpoint_hash": f"h{i}",
                         "p256dh_enc": "raw:" + d["keys"]["p256dh"], "auth_enc": "raw:" + d["keys"]["auth"],
                         "topics": json.dumps(["critical_alerts"]), "user_agent": "", "created_at": utcnow(),
                         "failures": 0})
        eng = sa.create_engine(db_url)
        with eng.begin() as c:
            c.execute(sa.text("INSERT INTO push_subscriptions (id, user_id, endpoint, endpoint_hash, p256dh_enc, "
                              "auth_enc, topics, user_agent, created_at, failures) VALUES (:id, :user_id, :endpoint, "
                              ":endpoint_hash, :p256dh_enc, :auth_enc, CAST(:topics AS jsonb), :user_agent, "
                              ":created_at, :failures)"), rows)
        eng.dispose()
        t0 = time.monotonic()
        n = delivery.send_to_user(app.state.ctx, uid, "critical_alerts", "Line down", "", "/m/alerts")
        dt = time.monotonic() - t0
        print(f"PU1 fan-out 1000 subscriptions {dt:.2f}s")
        assert n == 1000 and len(stub.got) == 1000 and dt < 60


def test_m3_push_hosts_are_allow_listed(db_url, stub):
    """M6 review M3: only browser push services (+ WEBPUSH_EXTRA_HOSTS in development); delivery re-checks."""
    from superplanner.api.config import ConfigError, Settings
    from superplanner.push import delivery
    from superplanner.push.service import endpoint_allowed

    app = _app(db_url, stub, webpush_extra_hosts=[])
    a = sign_up(app, "a@p.example")
    dev = stub.device(1)
    for ep in ("https://169.254.169.254/latest", "https://intranet.hbl.example/x", "https://fcm.googleapis.com.evil"
               ".example/x", "https://push.example.test/send/1", "https://user:pw@fcm.googleapis.com/x",
               "https://fcm.googleapis.com:8443/x"):
        r = a.post(f"{V1}/push/subscriptions", json=dict(dev, endpoint=ep))
        assert r.status_code == 422 and r.json()["error"]["code"] == "PUSH_SUBSCRIPTION_INVALID", ep
    s = app.state.ctx.settings
    for ok in ("https://fcm.googleapis.com/fcm/send/x", "https://updates.push.services.mozilla.com/wpush/v2/x",
               "https://wns2-par02p.notify.windows.com/w/?token=x", "https://web.push.apple.com/abc"):
        assert endpoint_allowed(ok, s), ok
    # a stored endpoint that is no longer allowed is dropped at delivery, nothing is posted
    assert delivery._post(s, "https://intranet.hbl.example/x", {}, b"") == 410 and stub.got == []
    with pytest.raises(ConfigError):
        Settings(database_url="postgresql+psycopg://u:LongPassw0rd!x@localhost/x", sp_env="production",
                 webpush_extra_hosts=["stub.local"], metrics_token="m" * 10 + "abcdefghijklmnopqrstuvwxyz",
                 public_base_url="https://sp.example")
