"""M6 security review fixes (design 11, review items M1-M4, m1-m6): one regression test each."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up


def test_m1_tokens_cannot_use_the_assistant(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        c = sign_up(app, "tok@m6.example")
        r = c.post(f"{V1}/tokens", json={"name": "x", "scopes": ["view", "assistant_use"]})
        assert r.status_code == 422                                     # not a mintable scope
        raw = c.post(f"{V1}/tokens", json={"name": "x", "scopes": ["view"]}).json()["token"]
        b = TestClient(app)
        b.headers["Authorization"] = f"Bearer {raw}"
        for method, path in (("GET", "/mfg/assistant/status"), ("GET", "/mfg/assistant/quick?kind=limits"),
                             ("GET", "/mfg/assistant/conversations"), ("POST", "/mfg/assistant/conversations")):
            r = b.request(method, V1 + path, json={} if method == "POST" else None)
            assert r.status_code == 403 and r.json()["error"]["code"] == "TOKEN_SCOPE", (path, r.text)
        assert Api(c).get("/assistant/status")["code"] == "AI_DISABLED"   # sessions unaffected


def test_m1_tool_permissions_honour_scopes():
    from superplanner.assistant.tools import ToolContext, current_permissions

    t = ToolContext(ctx=None, user_id="u", owner_id="o", permissions=frozenset(), conversation_id="c",
                    allow_whatif=False, refs=None, scopes=frozenset({"view"}),       # type: ignore[arg-type]
                    reload_permissions=lambda _t: frozenset({"view", "mrp_run", "trace_view"}))
    assert current_permissions(t) == frozenset({"view"})


def test_m1_heartbeat_during_slow_calls_and_final_state_kept(db_url, monkeypatch):
    """Review m1: the heartbeat advances while a model call runs; a turn reaped meanwhile stays failed."""
    import time

    import sqlalchemy as sa

    from superplanner.assistant import loop
    from superplanner.assistant.fake import FakeClient, response, text

    monkeypatch.setattr(loop, "HEARTBEAT_SECONDS", 0.1)
    gate = {"go": False}

    def slow(kw, n):
        while not gate["go"]:
            time.sleep(0.05)
        return response(text("late answer"))

    app = acc_app(db_url, assistant_ai_enabled=True, assistant_ai_client_factory=lambda: FakeClient(slow))
    with TestClient(app):
        c = sign_up(app, "hb@m6.example")
        api = Api(c)
        conv = api.post("/assistant/conversations", {})["id"]
        tid = api.post(f"/assistant/conversations/{conv}/turns", {"text": "q"}, status=202)["turn_id"]
        eng = sa.create_engine(db_url)

        def hb():
            with eng.connect() as x:
                return x.execute(sa.text("SELECT heartbeat_at, status FROM assistant_turns WHERE id = :i"),
                                 {"i": tid}).one()
        time.sleep(0.4)
        h1 = hb()
        time.sleep(0.4)
        h2 = hb()
        assert h2[1] == "running" and h2[0] > h1[0]
        with eng.begin() as x:                                         # reaped by another instance meanwhile
            x.execute(sa.text("UPDATE assistant_turns SET status = 'failed' WHERE id = :i"), {"i": tid})
        gate["go"] = True
        time.sleep(0.5)
        t = api.get(f"/assistant/turns/{tid}")
        assert t["status"] == "failed" and t["answer"] is None
        eng.dispose()


def test_m3_no_self_approval_m5_device_moves_m6_csv(db_url):
    """Review m3 (own submissions hidden unless owner / plant_admin), m5 (a device registered by another account
    moves to the new account, never 500), m6 (CSV formula escaping)."""
    from superplanner.notify.digests import tiles_csv

    from superplanner.push import vapid

    pem = vapid.generate_private_key_pem()
    app = acc_app(db_url, webpush_vapid_private_key=pem, webpush_subject="mailto:o@x.example",
                  webpush_extra_hosts=["push.example.test"], push_post=lambda *a: posted.append(a[0]) or 201)
    posted: list[str] = []
    with TestClient(app):
        owner = sign_up(app, "own@m6.example")
        oid = owner.get(f"{V1}/auth/session").json()["user"]["id"]
        both = sign_up(app, "both@m6.example")
        api = Api(owner)
        api.post("/members", {"email": "both@m6.example", "roles": ["purchaser", "approver"]})
        it = api.item("SA-1")
        b = Api(both).at(oid)
        pr = b.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [
            {"requested_date": "2026-12-01", "qty": 1}]}]})
        b.post(f"/purchase-requests/{pr['id']}/submit", {}, status=200, version=pr["row_version"])
        assert [x for x in b.get("/approvals")["items"] if x["kind"] == "pr"] == []      # own submission
        assert [x["id"] for x in api.get("/approvals")["items"] if x["kind"] == "pr"] == [pr["id"]]
        # m5
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        k = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        dev = {"endpoint": "https://push.example.test/send/shared", "keys": {"p256dh": vapid.b64u(k),
                                                                            "auth": vapid.b64u(b"a" * 16)}}
        assert owner.post(f"{V1}/push/subscriptions", json=dev).status_code == 201
        r = both.post(f"{V1}/push/subscriptions", json=dev)
        assert r.status_code == 201
        assert owner.get(f"{V1}/push/subscriptions").json()["items"] == []
        assert len(both.get(f"{V1}/push/subscriptions").json()["items"]) == 1
        # push: the submitter (approver, not plant_admin) gets no "waits for approval" push for their own PR
        from datetime import UTC, datetime, timedelta

        from superplanner.push import delivery

        res = delivery.run_plant(app.state.ctx, oid, now=datetime.now(UTC) + timedelta(seconds=1))
        assert res["events"] >= 1 and res["sent"] == 0 and posted == []
    # m6
    out = tiles_csv({"otd": {"value": 0.9, "unit": "%", "status": "ok", "note": "=HYPERLINK(\"x\")"}}, "@plant")
    lines = out.decode().splitlines()
    assert lines[1].startswith("'@plant,otd,0.9") and "'=HYPERLINK" in lines[1]
