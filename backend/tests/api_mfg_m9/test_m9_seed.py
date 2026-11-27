"""`load-seed --profile small-network|bd-network` (M9-DESIGN 12.2): an organisation of 3 plants + 2 DCs with shared
keys, lanes and sourcing; the network run plans it validator-clean. The bd-network timing (P1 incl. snapshot) is
`pytest -m slow -s tests/api_mfg_m9/test_m9_seed.py`."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from m8_helpers import wait_for
from m9_helpers import V1, Api, app_for, sign_up


def _org(app):
    admin = sign_up(app, "seed@load.example")
    org = admin.post(f"{V1}/orgs", json={"name": "Load", "slug": "load"}).json()
    uid = admin.get(f"{V1}/auth/session").json()["user"]["id"]
    return admin, org, uid


def _seed_and_run(db_url: str, profile: str) -> tuple[dict, dict, float]:
    from superplanner.loadseed import SeedRefused, seed_network

    app = app_for(db_url)
    with TestClient(app):
        admin, _org_, uid = _org(app)
        ctx = app.state.ctx
        out = seed_network(ctx.db, ctx.settings, uid, "load", profile=profile)
        assert set(out["nodes"]) == {"P1", "P2", "P3", "D1", "D2"} and out["rules"] > 0
        net = Api(admin, out["network_owner"])
        kinds = {n["code"]: n["kind"] for n in net.get("/net/nodes")["items"]}
        assert kinds == {"P1": "plant", "P2": "plant", "P3": "plant", "D1": "dc", "D2": "dc"}
        t0 = time.monotonic()
        r = net.post("/net/runs", {}, status=202)
        r = wait_for(lambda: net.get(f"/net/runs/{r['id']}"), lambda x: x["status"] not in ("queued", "running"),
                     timeout=600)
        took = time.monotonic() - t0
        assert r["status"] == "completed" and r["validator"]["ok"], (r["error"], r["validator"])
        # the safeguard of the node seed holds: a plant with postings is refused without force
        p1 = Api(admin, next(n["owner_id"] for n in net.get("/net/nodes")["items"] if n["code"] == "P1"))
        loc = p1.get("/locations")["items"][0]
        item = p1.get("/items", limit=1)["items"][0]
        p1.receive(item["id"], loc["id"], 1)
        with pytest.raises(SeedRefused):
            seed_network(ctx.db, ctx.settings, uid, "load", profile=profile)
        return out, r, took


def test_small_network_seed_plans_clean(db_url):
    out, r, _t = _seed_and_run(db_url, "small-network")
    assert r["summary"]["nodes"] == 5 and r["summary"]["transfers"] > 0


@pytest.mark.slow
def test_bd_network_p1_timing(db_url):
    out, r, took = _seed_and_run(db_url, "bd-network")
    t = r["summary"]["timings"]
    print(f"\nbd-network seed {out['seconds']} s; P1 run {took:.1f} s (snapshot {t['snapshot_s']} s, engine "
          f"{t['engine_s']} s, validator {t['validator_s']} s); {r['summary']['keys']} keys, "
          f"{r['summary']['transfers']} transfers")
    assert took < 90
