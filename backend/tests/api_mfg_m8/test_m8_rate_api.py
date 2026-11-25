"""S3 API (M8-DESIGN 7, 11 R1-R9): line rates, MRP pass 1 -> rate run (job) -> grid / blocks -> publish twice
(repetitive WOs created / kept / cancelled; started WOs untouched) -> MRP pass 2 uses rate supplies."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from m8_helpers import owner_db, wait_for


def setup_flow(api):
    g = api.post("/groups", {"code": "ASM", "name": "Assembly"})
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    tpl = api.post("/shift-templates", {"code": "24X7", "name": "24x7", "shifts": [
        {"name": "A", "days": days, "start": "00:00", "end": "12:00"},
        {"name": "B", "days": days, "start": "12:00", "end": "24:00"}]})
    api.post("/shift-assignments", {"shift_template_id": tpl["id"], "target_type": "group", "group_id": g["id"],
                                    "effective_from": "2026-01-01"})
    ln = api.post("/lines", {"group_id": g["id"], "code": "ASM-01", "name": "Assembly 1", "setup_family": "ASM"})
    items = {}
    for pn in ("SYR-3", "SYR-5"):
        it = api.item(pn, "make", family="SYR", lead_time_days=1)
        rt = api.post("/routings", {"item_id": it["id"], "operations": [
            {"seq": 10, "name": "Assemble", "group_id": g["id"], "setup_minutes": 0, "run_minutes": 0.01}]})
        api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
        api.put(f"/items/{it['id']}/planning", {"replenishment": "rate", "campaign_key": pn,
                                                "target_cover_days": 0}, 0)
        api.put(f"/items/{it['id']}/packaging", {"levels": [{"level": "each", "code": "EA", "qty_base": 1},
                                                             {"level": "case", "code": "CS", "qty_base": 100}]}, 1)
        items[pn] = it
    rates = api.put(f"/lines/{ln['id']}/rates", {"line": {"planning": "flow", "oee": 0.8, "clearance_minutes": 15},
                                                 "rates": [{"item_family": "SYR", "units_per_hour": 1000}]},
                    ln["row_version"])
    assert rates["line"]["planning"] == "flow" and rates["rates"][0]["units_per_hour"] == 1000
    api.put("/changeover-matrix", {"rows": [{"line_setup_family": "ASM", "from_key": "*", "to_key": "*",
                                             "minutes": 60, "cost": 200}]}, 0)
    return ln, items


def demand(api, items, qty, offset_days, number):
    d = date.today() + timedelta(days=offset_days)
    o = api.post("/demand-orders", {"number": number, "demand_type": "customer", "lines": [
        {"item_id": items["SYR-3"]["id"], "qty": qty, "due_date": d.isoformat()},
        {"item_id": items["SYR-5"]["id"], "qty": qty, "due_date": (d + timedelta(days=1)).isoformat()}]})
    if o["status"] == "draft":
        o = api.post(f"/demand-orders/{o['id']}/open", {}, status=200, version=o["row_version"])
    return o


def rate_run(api, **kw):
    mrp = api.post("/mrp/runs", {"label": "nightly-1", "rate_supply": False, "horizon_days": 60})
    assert mrp["status"] == "completed", mrp
    r = api.post("/rate/runs", {"horizon_days": 14, "time_budget_s": 10, **kw}, 202)
    return wait_for(lambda: api.get(f"/rate/runs/{r['id']}"), lambda x: x["status"] not in ("queued", "running"),
                    timeout=120)


@pytest.mark.req("M8-RATE-06", "M8-MRP-04")
def test_rate_run_publish_twice(api, client):
    ln, items = setup_flow(api)
    demand(api, items, 5000, 3, "DO-R1")
    run = rate_run(api)
    assert run["status"] == "completed", run["error"]
    assert run["validator"]["ok"] and run["summary"]["demands"] == 2
    blocks = api.get(f"/rate/runs/{run['id']}/blocks")["items"]
    prod = [b for b in blocks if b["kind"] == "production"]
    assert sum(b["qty"] for b in prod) == pytest.approx(10_000)
    assert any(b["kind"] in ("changeover", "clearance") for b in blocks)
    grid = api.get(f"/rate/runs/{run['id']}/grid", bucket="day")
    assert sum(c["qty"] for c in grid["cells"]) == pytest.approx(10_000)
    pub = api.post(f"/rate/runs/{run['id']}/publish", None, 200)
    assert api.get("/dashboard")["tiles"]["rate_shortages"]["details"]["number"] == run["number"]
    assert pub["created_wo_ids"] and pub["cancelled_wo_ids"] == []
    wo = api.get(f"/work-orders/{pub['created_wo_ids'][0]}")
    assert wo["status"] == "released"
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models_m2 import MfgWorkOrderRow
    from superplanner.api.mfg.db_models_m4 import MfgWoOperationRow
    with owner_scope("usr_local"), owner_db(client).read() as s:
        w = s.get(MfgWorkOrderRow, wo["id"])
        assert w.kind == "repetitive" and w.rate_run_id == run["id"]
        ops = s.query(MfgWoOperationRow).filter(MfgWoOperationRow.wo_id == w.id).all()
        assert ops and ops[0].line_id == ln["id"]
    api.err("POST", f"/rate/runs/{run['id']}/publish", 409, "MFG_INVALID_STATE")
    # second run, same demand, firm blocks kept -> WOs kept and re-linked
    run2 = rate_run(api)
    pub2 = api.post(f"/rate/runs/{run2['id']}/publish", None, 200)
    assert pub2["created_wo_ids"] == [] and sorted(pub2["kept_wo_ids"]) == sorted(pub["created_wo_ids"])
    assert api.get(f"/rate/runs/{run['id']}")["published"] is False
    # start one WO, then a run without firm blocks and changed demand: unstarted cancelled, started kept
    with owner_scope("usr_local"), owner_db(client).write() as s:
        w = s.get(MfgWorkOrderRow, pub["created_wo_ids"][0])
        w.status, w.qty_completed = "in_progress", 1.0
    demand(api, items, 3000, 2, "DO-R2")
    run3 = rate_run(api, keep_firm=False)
    assert run3["status"] == "completed", run3
    pub3 = api.post(f"/rate/runs/{run3['id']}/publish", None, 200)
    assert pub["created_wo_ids"][0] in pub3["kept_wo_ids"]
    assert set(pub3["cancelled_wo_ids"]) == set(pub["created_wo_ids"]) - {pub["created_wo_ids"][0]}
    for wid in pub3["cancelled_wo_ids"]:
        assert api.get(f"/work-orders/{wid}")["status"] == "cancelled"
    cmp = api.get("/rate/compare", a=run["id"], b=run3["id"])
    assert set(cmp["objective"]) >= {"changeover_cost", "shortage_unit_days"}
    # MRP pass 2: rate supplies of the published run (blocks beyond the firm zone)
    mrp2 = api.post("/mrp/runs", {"label": "nightly-2", "horizon_days": 60})
    plan = api.get(f"/mrp/runs/{mrp2['id']}/items/{items['SYR-3']['id']}")
    kinds = {x["kind"] for x in plan["supplies"]}
    assert "wo" in kinds or "rate" in kinds


def test_nightly_chain_run_now(api, client):
    from superplanner.api.db.ownership import system_scope
    from superplanner.api.mfg.db_models_m5 import MaintenanceRunRow

    ln, items = setup_flow(api)
    demand(api, items, 4000, 3, "DO-N1")
    api.put("/plant/planning-settings", {**{k: v for k, v in api.get("/plant/planning-settings").items()
                                            if k != "row_version"}, "rate_time_budget_s": 10, "auto_publish": True},
            api.get("/plant/planning-settings")["row_version"])
    out = api.post("/planning/nightly/run-now", None, 202)

    def get():
        with system_scope(), owner_db(client).read() as s:
            r = s.get(MaintenanceRunRow, out["run_id"])
            return {"status": r.status, "results": r.results}
    r = wait_for(get, lambda x: x["status"] in ("completed", "failed"), timeout=120)
    steps = {x["step"]: x for x in r["results"]["steps"]}
    assert r["status"] == "completed", r
    assert [k for k in steps] in (["history_refresh", "mrp_pass1", "rate_run", "ster_plan", "mrp_pass2"],
                                  ["history_refresh", "forecast_run", "ss_run", "mrp_pass1", "rate_run", "ster_plan",
                                   "mrp_pass2"])
    assert all(x["status"] == "completed" for x in steps.values()), steps
    assert steps["ster_plan"]["ref_id"] == "skipped"
    runs = api.get("/rate/runs")["items"]
    assert runs[0]["published"] is True                          # auto_publish
    labels = [x["label"] for x in api.get("/mrp/runs")["items"]][:2]
    assert labels == ["nightly-2", "nightly-1"]
