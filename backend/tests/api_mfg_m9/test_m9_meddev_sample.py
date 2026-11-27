"""Organisation sample `meddev_m9` (M9-DESIGN 12.1, Gate 9 acceptance 1-4 data)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from m9_helpers import V1, Api, app_for, sign_up


def test_meddev_m9_org_sample(db_url):
    from superplanner.api.mfg.services.samples_m9 import load_org_sample

    app = app_for(db_url)
    with TestClient(app):
        admin = sign_up(app, "demo@meddev.example")
        org = admin.post(f"{V1}/orgs", json={"name": "Demo Meddev", "slug": "demo-meddev"}).json()
        uid = admin.get(f"{V1}/auth/session").json()["user"]["id"]
        out = load_org_sample(app.state.ctx, uid, "demo-meddev")
        assert out["net_run"]["status"] == "completed" and out["net_run"]["validator_ok"], out
        assert out["published_cycle"].startswith("SOP-") and out["cycle"] == "pre_sop"
        assert set(out["scenarios"].values()) == {"completed"}, out["scenarios"]
        nodes = out["nodes"]
        net = Api(admin, nodes["NET"] if "NET" in nodes else None)
        plants = {p["code"]: p for p in admin.get(f"{V1}/orgs/{org['id']}/plants").json()["items"]}
        net = Api(admin, plants["NET"]["plant_owner_id"])
        qc, us, dc = (Api(admin, plants[c]["plant_owner_id"]) for c in ("QC", "US1", "DCUS"))
        # network: published run, TOs in the plants, network demand in plant MRP
        runs = net.get("/net/runs")["items"]
        assert runs[0]["published"] and runs[0]["publish_result"]["created"]
        assert [t for t in dc.get("/transfer-orders")["items"] if t["source"] == "network"]
        # pegging from a DC needle order down to US1 production
        peg = net.get(f"/net/runs/{runs[0]['id']}/pegging", node=plants["DCUS"]["plant_owner_id"], key="MDV-NDL-25")
        assert "production" in str(peg) and plants["US1"]["plant_owner_id"] in str(peg)
        # trade: needle lots mixing CN steel miss the US-steel milestone; landed cost of the CN supplier
        ms = net.get("/trade/milestones")["items"][0]
        shares = []
        for lot in us.get("/lots", q="N25-")["items"]:
            c = net.get(f"/trade/lots/{plants['US1']['plant_owner_id']}/{lot['id']}/content", milestone_id=ms["id"])
            shares.append(c["share_value"])
        assert 1.0 in shares and min(shares) < 1.0
        steel = us.get("/items", q="MDV-CAN-STL")["items"][0]
        landed = {r["supplier_code"]: r["landed"] for r in us.get("/trade/landed", item_id=steel["id"])["items"]}
        assert landed["ATUBE"]["total"] is not None and any(d["layer"] == "s301" for d in landed["ATUBE"]["duty"])
        # S&OP publish wrote MPS targets in the plants
        assert us.get("/mps/targets")["items"] or qc.get("/mps/targets")["items"]
