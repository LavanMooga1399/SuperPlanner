"""S2 (M6-DESIGN 3, 9 T-D1..T-D3, DB1/DB2): dashboard tiles against the underlying endpoints, turns, thresholds,
export, the snapshot duty, org dashboard visibility and totals, digests with a fake SMTP."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up
from m6_helpers import World, build_world
from superplanner.api.mfg.services.dashboard import inventory_turns, status_of


@pytest.fixture(scope="module")
def world(db_url_factory_module) -> World:
    return build_world(db_url_factory_module("m6dash"), assistant_ai_enabled=False)


def _all(api, path, **kw):
    out, off = [], 0
    while True:
        page = api.get(path, limit=200, offset=off, **kw)
        out += page["items"]
        off += 200
        if off >= page["total"]:
            return out


def test_turns_hand_value():
    """T-D1: month-end rows only; 3 month-ends needed."""
    snaps = {date(2026, 1, 15): 999.0, date(2026, 1, 31): 100.0, date(2026, 2, 28): 200.0, date(2026, 3, 31): 300.0}
    assert inventory_turns(snaps, 400.0) == 2.0             # 400 / mean(100, 200, 300)
    assert inventory_turns({date(2026, 1, 31): 100.0, date(2026, 2, 28): 200.0}, 400.0) is None
    assert status_of(0.84, {"alert_below": 0.85, "watch_below": 0.95}) == "alert"
    assert status_of(0.9, {"alert_below": 0.85, "watch_below": 0.95}) == "watch"
    assert status_of(None, {}) == "n/a"


def test_plant_dashboard_matches_the_endpoints(world: World):
    api = world.api()
    t0 = time.monotonic()
    cold = api.get("/dashboard", period="13w")               # first request warms the M4 closed-day KPI cache
    cold_ms = (time.monotonic() - t0) * 1000
    t0 = time.monotonic()
    d = api.get("/dashboard", period="13w")
    ms13 = (time.monotonic() - t0) * 1000
    tiles = d["tiles"]
    assert set(tiles) == {"otd", "backlog", "material_risk", "execution", "inventory", "late_pos", "quality",
                          "integration"}
    # OTD equals the M4 KPI of the same period
    today = date.fromisoformat(api.get("/kpis")["period"]["to"])
    k = api.get("/kpis", **{"from": (today - timedelta(days=90)).isoformat(), "to": today.isoformat()},
                bucket="week")["metrics"]
    assert tiles["otd"]["value"] == k["otd"]["value"] and tiles["execution"]["details"]["fpy"] == k["fpy"]["value"]
    # material risk equals the MRP item list (short within 4 weeks)
    run = api.get("/mrp/runs/latest")
    items = _all(api, f"/mrp/runs/{run['id']}/items", short_only=True)
    hand = [x for x in items if x.get("first_short_date") and
            date.fromisoformat(x["first_short_date"]) <= today + timedelta(days=28)]
    assert tiles["material_risk"]["value"] == len(hand)
    late = api.get(f"/mrp/runs/{run['id']}/demand", late_only=True, limit=200)["total"]
    assert tiles["material_risk"]["details"]["late_lines_material"] == late
    # inventory value = on hand x standard cost
    costs = {i["id"]: i.get("standard_cost") or 0 for i in _all(api, "/items")}
    bal = _all(api, "/inventory/balances")
    hand_value = sum(b["qty_on_hand"] * costs.get(b["item"]["id"], 0) for b in bal if b["qty_on_hand"] > 0)
    assert abs(tiles["inventory"]["value"] - hand_value) < 0.01
    assert tiles["inventory"]["details"]["turns"] is None and "n/a" in tiles["inventory"]["details"]["turns_note"]
    assert tiles["backlog"]["details"]["run_id"] == world.run_id and tiles["backlog"]["value"] is not None
    assert tiles["otd"]["trend"] and all(t["drill"] for t in tiles.values())
    assert all(x["path"].startswith("/mfg/") for t in tiles.values() for x in t["drill"])   # app routes (WP-U)
    # regression (WP-U): the inventory-by-family GROUP BY answered 500 once
    assert tiles["inventory"]["details"]["by_family"]
    api.get("/dashboard", period="52w")
    t0 = time.monotonic()
    d52 = api.get("/dashboard", period="52w")
    ms52 = (time.monotonic() - t0) * 1000
    print(f"DB1 plant dashboard 13w cold {cold_ms:.0f} ms {cold['timings_ms']}, warm {ms13:.0f} ms "
          f"{d['timings_ms']}; 52w warm {ms52:.0f} ms {d52['timings_ms']}")
    assert ms13 < 1500


def test_thresholds_export_and_snapshot_duty(world: World):
    api = world.api()
    base = api.get("/dashboard")["tiles"]["otd"]
    out = api.put("/plant/dashboard-thresholds", {"thresholds": {"otd": {"alert_below": 0.0, "watch_below": 0.0}}},
                  0)
    assert out["thresholds"]["otd"] == {"alert_below": 0.0, "watch_below": 0.0}
    t = api.get("/dashboard")["tiles"]["otd"]
    assert t["thresholds"]["alert_below"] == 0.0 and (base["value"] is None or t["status"] == "ok")
    world.api("viewer").err("PUT", "/plant/dashboard-thresholds", 403, "MFG_FORBIDDEN",
                            json={"thresholds": {"otd": {"alert_below": 0.5}}})
    r = api.req("GET", "/dashboard/export", 200, params={"format": "csv"})
    assert r.text.splitlines()[0] == "tile,value,unit,status,note" and len(r.text.splitlines()) == 9
    r = api.req("GET", "/dashboard/export", 200, params={"format": "xlsx"})
    assert r.content[:2] == b"PK"
    # 3.2: the scheduler enqueues inventory_snapshot (00:30 plant time); the job writes the day's rows once
    from superplanner.integration import scheduler

    ctx = world.app.state.ctx
    noon = datetime.now(UTC).replace(hour=12, minute=0)
    got = scheduler.tick(ctx, now=noon, duties={"inventory_snapshot"})
    assert ("inventory_snapshot", world.owner_id) in got
    t0 = time.monotonic()
    while True:
        eng = sa.create_engine(ctx.settings.database_url)
        with eng.connect() as c:
            n = c.execute(sa.text("SELECT count(*), coalesce(sum(qty_value), 0) FROM mfg_inventory_snapshots "
                                  "WHERE owner_id = :o"), {"o": world.owner_id}).one()
        eng.dispose()
        if n[0] or time.monotonic() - t0 > 30:
            break
        time.sleep(0.2)
        dbg = None
    eng = sa.create_engine(ctx.settings.database_url)
    with eng.connect() as c:
        dbg = c.execute(sa.text("SELECT status, results FROM maintenance_runs WHERE kind = 'inventory_snapshot'")).all()
    eng.dispose()
    assert n[0] > 0, dbg
    assert abs(float(n[1]) - api.get("/dashboard")["tiles"]["inventory"]["value"]) < 0.01
    assert scheduler.tick(ctx, now=noon, duties={"inventory_snapshot"}) == []


def test_dashboard_with_a_year_of_snapshots_db1(world: World):
    """DB1 with 1 year of synthetic snapshot history (12 families x 2 location kinds x 365 days)."""
    ctx = world.app.state.ctx
    eng = sa.create_engine(ctx.settings.database_url)
    today = date.fromisoformat(world.api().get("/kpis")["period"]["to"])
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO mfg_inventory_snapshots (id, owner_id, day, item_family, location_kind, qty_value, items, "
            "created_at) SELECT 'ivs_syn_' || d || '_' || f || '_' || k, :o, :t - d, 'F' || f, "
            "CASE WHEN k = 0 THEN 'stores' ELSE 'wip' END, 1000 + d, 3, now() FROM generate_series(1, 365) d, "
            "generate_series(1, 12) f, generate_series(0, 1) k ON CONFLICT DO NOTHING"), {"o": world.owner_id,
                                                                                       "t": today})
    eng.dispose()
    ms = 1e9
    for _ in range(2):                                       # best of two (timing noise of a shared test machine)
        t0 = time.monotonic()
        d = world.api().get("/dashboard", period="52w")
        ms = min(ms, (time.monotonic() - t0) * 1000)
    print(f"DB1 52w with a year of snapshots {ms:.0f} ms, turns {d['tiles']['inventory']['details']['turns']}")
    assert d["tiles"]["inventory"]["details"]["turns"] is not None
    assert ms < 1500


def test_org_dashboard_two_of_three_plants_and_digests(db_url):
    """T-D2 + T-D3 (+ DB2 timing on small plants)."""
    mails = []
    app = acc_app(db_url, org_self_service=True)
    with TestClient(app):
        admin = sign_up(app, "admin@hbl.example")
        org = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl"}).json()
        plants = [admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": c, "name": c}).json()
                  for c in ("HYD", "BLR", "PUN")]
        u = sign_up(app, "ravi@hbl.example")
        uid = u.get(f"{V1}/auth/session").json()["user"]["id"]
        admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "ravi@hbl.example"})
        for p in plants[:2]:
            assert admin.post(f"{V1}/orgs/{org['id']}/plants/{p['code']}/roles",
                              json={"user_id": uid, "roles": ["viewer"]}).status_code == 200
        for i, p in enumerate(plants):
            Api(admin, p["plant_owner_id"]).item(f"P{i}", standard_cost=10.0 * (i + 1))
        t0 = time.monotonic()
        r = u.get(f"{V1}/orgs/{org['id']}/dashboard")
        ms = (time.monotonic() - t0) * 1000
        assert r.status_code == 200, r.text
        d = r.json()
        assert [p["plant"]["code"] for p in d["plants"]] == ["BLR", "HYD"]
        for name in ("material_risk", "late_pos", "inventory"):
            vals = [p["tiles"][name]["value"] for p in d["plants"] if p["tiles"][name]["value"] is not None]
            assert d["totals"][name]["value"] == (round(sum(vals), 2) if vals else None)
        assert "weights" in d["totals"]["otd"]["details"]
        assert len(admin.get(f"{V1}/orgs/{org['id']}/dashboard").json()["plants"]) == 3
        out = sign_up(app, "out@x.example")
        assert out.get(f"{V1}/orgs/{org['id']}/dashboard").status_code == 404
        print(f"DB2 org dashboard (2 small plants) {ms:.0f} ms")
        # T-D3: without SMTP refused
        r = u.post(f"{V1}/digests", json={"scope": "org", "scope_id": org["id"]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "DIGEST_NO_SMTP"
    app2 = acc_app(db_url, org_self_service=True, smtp_send=mails.append, smtp_from="sp@hbl.example")
    with TestClient(app2):
        from apimfgm2_helpers import PASSWORD

        c = TestClient(app2)
        r = c.post(f"{V1}/auth/sign-in", json={"email": "ravi@hbl.example", "password": PASSWORD})
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        dg = c.post(f"{V1}/digests", json={"scope": "org", "scope_id": org["id"], "local_time": "06:00"})
        assert dg.status_code == 201, dg.text
        dp = c.post(f"{V1}/digests", json={"scope": "plant", "scope_id": plants[0]["plant_owner_id"],
                                           "frequency": "weekly", "local_time": "06:00", "weekday": 0})
        assert dp.status_code == 201
        r = c.post(f"{V1}/digests", json={"scope": "plant", "scope_id": plants[2]["plant_owner_id"]})
        assert r.status_code == 404                                  # PUN is not visible to the user
        assert len(c.get(f"{V1}/digests").json()["items"]) == 2
        from superplanner.notify import digests

        ctx = app2.state.ctx
        eng = sa.create_engine(ctx.settings.database_url)
        with eng.begin() as conn:
            conn.execute(sa.text("UPDATE digest_subscriptions SET created_at = now() - interval '9 days'"))
        eng.dispose()
        res = digests.send_due(ctx)
        assert res == {"sent": 2, "failed": 0, "due": 2}, res
        assert len(mails) == 2 and all(m["To"] == "ravi@hbl.example" for m in mails)
        org_mail = next(m for m in mails if "HBL" in m["Subject"])
        body = org_mail.get_body(("html",)).get_content()
        assert "HYD" in body and "BLR" in body and "PUN" not in body          # the recipient's scope only
        att = [p for p in org_mail.iter_attachments()]
        assert att and att[0].get_filename() == "dashboard.csv"
        assert digests.send_due(ctx) == {"sent": 0, "failed": 0, "due": 0}   # sent once per slot
        assert c.delete(f"{V1}/digests/{dg.json()['id']}").status_code == 204


def test_approvals_inbox_and_downtime_ack(world: World):
    """M4 / M5 (mobile): approvals the user can act on, each with its exact action; downtime acknowledgement."""
    api = world.api()
    item = next(i for i in _all(api, "/items") if i["make_buy"] == "buy")
    pr = api.post("/purchase-requests", {"lines": [{"item_id": item["id"], "schedules": [
        {"requested_date": "2026-12-01", "qty": 5}]}]})
    api.post(f"/purchase-requests/{pr['id']}/submit", {}, status=200, version=pr["row_version"])
    inbox = api.get("/approvals")
    prs = [x for x in inbox["items"] if x["kind"] == "pr"]
    assert prs and prs[0]["id"] == pr["id"] and prs[0]["actions"][0]["path"].endswith(f"/{pr['id']}/approve")
    assert inbox["counts"]["pr"] == len(prs)
    ot = api.get(f"/aps/runs/{world.run_id}/overtime", status="suggested")["items"]
    assert inbox["counts"]["overtime"] == len(ot)
    # the viewer (no approval permissions) sees nothing to act on
    assert world.api("viewer").get("/approvals")["items"] == []
    planner_kinds = {x["kind"] for x in world.api("planner").get("/approvals")["items"]}
    assert "pr" not in planner_kinds                                # planner has no pr_approve
    # the action from the card works through the normal API
    act = prs[0]["actions"][0]
    r = world.owner.post(act["path"], json=act["body"], headers={"If-Match": f'"{prs[0]["row_version"]}"'})
    assert r.status_code == 200, r.text
    assert all(x["id"] != pr["id"] for x in api.get("/approvals")["items"])
    # downtime: reported, acknowledged by the supervisor-like viewer (floor_view), idempotent
    line = api.get("/lines", limit=1)["items"][0]
    dt = api.post("/downtime", {"line_id": line["id"], "kind": "breakdown",
                                "start_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                                "reason": "Feeder jam"})
    a1 = world.api("viewer").post(f"/downtime/{dt['id']}/acknowledge", {"client_id": "c-1"}, status=200)
    assert a1["acknowledged_by"]["id"] != world.owner_id and a1["acknowledged_at"]
    a2 = world.api("planner").post(f"/downtime/{dt['id']}/acknowledge", {}, status=200)
    assert a2["acknowledged_by"] == a1["acknowledged_by"] and a2["row_version"] == a1["row_version"]
    assert api.get("/downtime", open=True)["items"][0]["acknowledged_at"]
    api.put(f"/downtime/{dt['id']}", {"close": True}, a2["row_version"])
