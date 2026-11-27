"""S&OP cycle end to end (M9-DESIGN 6; M9-SOP-07, M9-SOP-08, publish incl. M9-SOP-09 through the API)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from m8_helpers import wait_for
from m9_helpers import Api, app_for, enroll, make_world, signature
from test_m9_network_api import network_setup


def _next_month() -> date:
    t = date.today()
    return date(t.year + (t.month == 12), t.month % 12 + 1, 1)


def _run(net: Api, sid: str) -> dict:
    net.post(f"/sop/scenarios/{sid}/run", None, status=202)
    return wait_for(lambda: net.get(f"/sop/scenarios/{sid}"), lambda x: x["status"] not in ("draft", "running"))


@pytest.mark.req("M9-SOP-07")
@pytest.mark.req("M9-SOP-08")
def test_cycle_demand_scenarios_signed_approval_reopen_publish(db_url):
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        s = network_setup(w)
        net = w.net
        period = _next_month()
        cyc = net.post("/sop/cycles", {"period": period.isoformat(), "horizon_months": 6})
        assert cyc["number"] == f"SOP-{period.year}-{period.month:02d}" and cyc["status"] == "draft"
        net.err("POST", "/sop/cycles", 409, "SOP_CYCLE_EXISTS", json={"period": period.isoformat()})
        dem = net.get(f"/sop/cycles/{cyc['id']}/demand")
        assert dem["families"] == ["SYR"] and len(dem["months"]) == 6
        # demand review: all-node +10 % (audited with its reason)
        o = net.post(f"/sop/cycles/{cyc['id']}/demand/overrides", {
            "node_owner_id": None, "family": "SYR", "month_from": period.isoformat(), "month_to": period.isoformat(),
            "mode": "pct", "value": 10, "reason": "Flu season"})
        rows = net.get(f"/sop/cycles/{cyc['id']}/demand", family="SYR")["items"]
        first = [r for r in rows if r["month"] == period.isoformat()]
        assert all(r["consensus_qty"] == pytest.approx(r["base_qty"] * 1.1) for r in first)
        net.err("DELETE", f"/sop/demand-overrides/{o['id']}", 422, "REASON_REQUIRED")
        for step in ("demand_review", "supply_review"):
            cyc = net.post(f"/sop/cycles/{cyc['id']}/advance", {"note": ""}, status=200)
            assert cyc["status"] == step
        net.err("POST", f"/sop/cycles/{cyc['id']}/advance", 409, "SOP_NO_BASELINE", json={})
        base = net.post("/sop/scenarios", {"cycle_id": cyc["id"], "name": "Baseline"})
        assert base["baseline"] is True
        base = _run(net, base["id"])
        assert base["status"] == "completed" and base["validator"]["ok"], base["error"]
        assert base["kpis"]["horizon"]["unmet_units"] == 0
        exp = net.post("/sop/scenarios", {"cycle_id": cyc["id"], "name": "Demand +20 %", "changes": [
            {"kind": "demand_change", "id": "d1", "label": "Promo", "from": period.isoformat(), "pct": 20}]})
        exp = _run(net, exp["id"])
        cmp = net.get("/sop/compare", ids=f"{base['id']},{exp['id']}")
        assert cmp["items"][1]["delta"]["horizon"]["consensus_units"] > 0
        assert net.get(f"/sop/scenarios/{base['id']}/plan")["items"]
        assert net.get(f"/sop/scenarios/{base['id']}/financial", group_by="node")["rows"]
        assert isinstance(net.get(f"/sop/scenarios/{base['id']}/rough-cut")["items"], list)
        assert net.get(f"/sop/scenarios/{base['id']}/make-buy")["items"]
        cyc = net.post(f"/sop/cycles/{cyc['id']}/advance", {"note": "Supply ok"}, status=200)
        net.err("POST", f"/sop/cycles/{cyc['id']}/advance", 409, "SOP_NO_RECOMMENDATION", json={})
        # review M2: a demand change after the run makes the scenario stale until it runs again
        net.post(f"/sop/cycles/{cyc['id']}/demand/overrides", {
            "node_owner_id": None, "family": "SYR", "month_from": period.isoformat(), "month_to": period.isoformat(),
            "mode": "pct", "value": 2, "reason": "Late order"})
        net.err("POST", f"/sop/cycles/{cyc['id']}/recommend", 409, "SOP_SCENARIO_STALE",
                json={"scenario_id": base["id"], "note": "Baseline"})
        base = _run(net, base["id"])
        cyc = net.post(f"/sop/cycles/{cyc['id']}/recommend", {"scenario_id": base["id"], "note": "Baseline"},
                       status=200)
        cyc = net.post(f"/sop/cycles/{cyc['id']}/advance", {"note": ""}, status=200)
        assert cyc["status"] == "executive"
        # signed two-step approval: plant manager reviews, executive approves, distinct people
        pm = w.person("pm@demo.example", {"NET": ["plant_manager"]})
        ex = w.person("exec@demo.example", {"NET": ["executive"]})
        both = w.person("both@demo.example", {"NET": ["plant_manager", "executive"]})
        for c, name in ((pm, "Paula Manager"), (ex, "Eric Executive"), (both, "Bea Both")):
            enroll(c, name)
        apm, aex, aboth = Api(pm, w.net_owner), Api(ex, w.net_owner), Api(both, w.net_owner)
        aex.err("POST", f"/sop/cycles/{cyc['id']}/approve", 422, "ESIG_REQUIRED", json={"scenario_id": base["id"]})
        sig = signature(both, aboth, "both@demo.example", "sop_cycle", cyc["id"], "approve", "reviewed")
        r = aboth.req("POST", f"/sop/cycles/{cyc['id']}/approve", 202, json={"scenario_id": base["id"],
                                                                            "signature": sig}).json()
        assert r["status"] == "pending_signatures"
        net.err("POST", f"/sop/cycles/{cyc['id']}/demand/overrides", 409, "SOP_CYCLE_LOCKED", json={
            "node_owner_id": None, "family": "SYR", "month_from": period.isoformat(), "month_to": period.isoformat(),
            "mode": "pct", "value": 5, "reason": "late change"})
        sig = signature(both, aboth, "both@demo.example", "sop_cycle", cyc["id"], "approve", "approved")
        aboth.err("POST", f"/sop/cycles/{cyc['id']}/approve", 409, "ESIG_SAME_SIGNER",
                  json={"scenario_id": base["id"], "signature": sig})
        # M9-SOP-08: reopen with a reason supersedes the signatures; the content hash changes after an edit
        h1 = net.get("/esig/preview", record_type="sop_cycle", record_id=cyc["id"], action="approve")["content_hash"]
        cyc = net.post(f"/sop/cycles/{cyc['id']}/reopen", {"to_step": "pre_sop", "reason": "Exec asked for more"},
                       status=200)
        assert cyc["status"] == "pre_sop" and all(x["status"] == "superseded" for x in cyc["signatures"])
        net.post(f"/sop/cycles/{cyc['id']}/demand/overrides", {
            "node_owner_id": None, "family": "SYR", "month_from": period.isoformat(), "month_to": period.isoformat(),
            "mode": "pct", "value": 5, "reason": "Exec feedback"})
        assert net.get("/esig/preview", record_type="sop_cycle", record_id=cyc["id"],
                       action="approve")["content_hash"] != h1
        base = _run(net, base["id"])
        cyc = net.get(f"/sop/cycles/{cyc['id']}")
        cyc = net.post(f"/sop/cycles/{cyc['id']}/advance", {"note": ""}, status=200)
        sig = signature(pm, apm, "pm@demo.example", "sop_cycle", cyc["id"], "approve", "reviewed")
        apm.req("POST", f"/sop/cycles/{cyc['id']}/approve", 202, json={"scenario_id": base["id"], "signature": sig})
        sig = signature(pm, apm, "pm@demo.example", "sop_cycle", cyc["id"], "approve", "approved")
        apm.err("POST", f"/sop/cycles/{cyc['id']}/approve", 403, "ESIG_ROLE",
                json={"scenario_id": base["id"], "signature": sig})
        sig = signature(ex, aex, "exec@demo.example", "sop_cycle", cyc["id"], "approve", "approved")
        cyc = aex.post(f"/sop/cycles/{cyc['id']}/approve", {"scenario_id": base["id"], "signature": sig}, status=200)
        assert cyc["status"] == "approved" and cyc["approved_scenario_id"] == base["id"] and cyc["content_hash"]
        assert [x["meaning"] for x in cyc["signatures"] if x["status"] == "valid"] == ["reviewed", "approved"]
        net.err("POST", f"/sop/cycles/{cyc['id']}/demand/overrides", 409, "SOP_CYCLE_LOCKED", json={
            "node_owner_id": None, "family": "SYR", "month_from": period.isoformat(), "month_to": period.isoformat(),
            "mode": "pct", "value": 5, "reason": "x"})
        # review m3: cancelling an approved (signed) cycle needs S&OP publish rights
        pl = w.person("pl@demo.example", {"NET": ["planner"]})
        Api(pl, w.net_owner).err("POST", f"/sop/cycles/{cyc['id']}/cancel", 403, "MFG_FORBIDDEN",
                                 json={"reason": "x"})
        # publish: consensus forecast version per node + MPS targets in the making plant
        cyc = net.post(f"/sop/cycles/{cyc['id']}/publish", None, status=202)
        assert cyc["status"] == "published"
        res = {n["node"]: n for n in cyc["publish_result"]["nodes"]}
        dcv = res[w.owner("DCUS")]["forecast_version_id"]
        assert dcv and res[w.owner("QC")]["targets"] >= 1
        v = w.api("DCUS").get(f"/forecast/versions/{dcv}")
        assert v["status"] == "active" and v["name"].endswith("consensus")
        tg = w.api("QC").get("/mps/targets")["items"]
        assert tg and tg[0]["family"] == "SYR"
        assert net.post(f"/sop/cycles/{cyc['id']}/publish", None, status=202)["status"] == "published"


def test_overdue_steps_notify_and_m9_tiles(db_url):
    from sqlalchemy import select

    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models_m4 import MfgNotificationRow
    from superplanner.api.mfg.services import qa_due

    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        network_setup(w)
        t = date.today()
        past = date(t.year - (t.month == 1), (t.month - 2) % 12 + 1, 1)
        w.net.post("/sop/cycles", {"period": past.isoformat(), "horizon_months": 3})
        tiles = w.net.get("/dashboard")["tiles"]
        assert tiles["sop_cycle"]["status"] == "alert" and tiles["sop_cycle"]["details"]["overdue"]
        assert tiles["net_shortages"]["status"] == "n/a" and "tariff_milestones" in tiles
        assert "mps_attainment" in w.api("QC").get("/dashboard")["tiles"]
        db = app.state.ctx.db
        from datetime import UTC, datetime
        assert w.net_owner in qa_due.due_plants_now(db, datetime.now(UTC)) if hasattr(qa_due, "due_plants_now") \
            else True
        with owner_scope(w.net_owner), db.write() as s:
            res = qa_due.scan(s)
        assert res["sop_overdue"] >= 1
        with owner_scope(w.net_owner), db.read() as s:
            kinds = [n.kind for n in s.execute(select(MfgNotificationRow)).scalars()]
        assert "sop_overdue" in kinds


def test_publish_keeps_other_lines_of_the_pinned_version(db_url):
    """Review M3: only family-month cells with a consensus value change; other items / months keep their finals."""
    from superplanner.api.db.models import new_id, utcnow
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models_m8 import MfgForecastLineRow, MfgForecastVersionRow
    from superplanner.api.mfg.db_models_m9 import MfgSopCycleRow

    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        s_ = network_setup(w)
        dc = w.api("DCUS")
        other = dc.item("OTHER-1", external_ref="OTH", family="OTHER")
        period = _next_month()
        far = date(period.year + 1, period.month, 1)
        db = app.state.ctx.db
        with owner_scope(w.owner("DCUS")), db.write() as s:
            now = utcnow()
            v = MfgForecastVersionRow(id=new_id("fcv_"), number="FCV-900001", name="pinned", run_id=None,
                                      status="active", bucket="m", start=period, periods=18, activated_by=None,
                                      activated_at=now, archived_at=None, note="", row_version=1, created_at=now,
                                      updated_at=now)
            s.add(v)
            s.flush()
            for iid, m, q in ((s_["dc_item"]["id"], period, 1000.0), (other["id"], period, 77.0),
                              (s_["dc_item"]["id"], far, 55.0)):
                s.add(MfgForecastLineRow(id=new_id("fcl_"), version_id=v.id, item_id=iid, period_start=m,
                                         stat_qty=q, final_qty=q))
        cyc = w.net.post("/sop/cycles", {"period": period.isoformat(), "horizon_months": 3})
        sc = w.net.post("/sop/scenarios", {"cycle_id": cyc["id"], "name": "Baseline"})
        sc = _run(w.net, sc["id"])
        assert sc["status"] == "completed", sc["error"]
        with owner_scope(w.net_owner), db.write() as s:
            c = s.get(MfgSopCycleRow, cyc["id"])
            c.status, c.approved_scenario_id = "approved", sc["id"]
        out = w.net.post(f"/sop/cycles/{cyc['id']}/publish", None, status=202)
        vid = {n["node"]: n for n in out["publish_result"]["nodes"]}[w.owner("DCUS")]["forecast_version_id"]
        with owner_scope(w.owner("DCUS")), db.read() as s:
            lines = {(ln.item_id, ln.period_start): ln.final_qty for ln in s.query(MfgForecastLineRow).filter(
                MfgForecastLineRow.version_id == vid)}
            n_active = s.query(MfgForecastVersionRow).filter(MfgForecastVersionRow.status == "active").count()
        assert lines[(other["id"], period)] == 77.0                  # other family untouched
        assert lines[(s_["dc_item"]["id"], far)] == 55.0             # month outside the consensus untouched
        assert lines[(s_["dc_item"]["id"], period)] > 0              # the consensus cell replaced
        assert n_active == 1
