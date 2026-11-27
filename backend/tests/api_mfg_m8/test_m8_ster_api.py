"""S4 API (M8-DESIGN 8, 11 S1-S7): plan -> load (M4 batch load) -> cycle complete puts sterility holds with the
planned release date and co-sterilisation trace edges -> signed release lifts them; a failed load keeps the holds
and opens one NCR with all lots; MRP availability of a sterilised WO = the load's release date."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api_mfg_m7"))

from m7_helpers import World, signature  # noqa: E402


@pytest.fixture
def world(db_url):
    w = World(db_url)
    yield w
    w.close()


def _setup(api, n_wos: int = 2):
    g = api.post("/groups", {"code": "ETO", "name": "EtO"})
    gaer = api.post("/groups", {"code": "AER", "name": "Aeration", "kind": "aeration"})
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    tpl = api.post("/shift-templates", {"code": "24X7", "name": "24x7", "shifts": [
        {"name": "A", "days": days, "start": "00:00", "end": "12:00"},
        {"name": "B", "days": days, "start": "12:00", "end": "24:00"}]})
    api.post("/shift-assignments", {"shift_template_id": tpl["id"], "target_type": "group", "group_id": g["id"],
                                    "effective_from": "2026-01-01"})
    ch = api.post("/lines", {"group_id": g["id"], "code": "ETO-01", "name": "Chamber 1"})
    api.put(f"/lines/{ch['id']}/rates", {"line": {"planning": "sterilisation", "chamber_pallets": 24,
                                                  "cycle_hours": 14}, "rates": []}, ch["row_version"])
    room = api.post("/lines", {"group_id": gaer["id"], "code": "AER-1", "name": "Aeration 1"})
    api.put(f"/lines/{room['id']}/rates", {"line": {"planning": "discrete", "chamber_pallets": 96}, "rates": []},
            room["row_version"])
    st = api.location("FG")
    it = api.item("SYR-ST", "make", lead_time_days=1, lot_controlled=True)
    rt = api.post("/routings", {"item_id": it["id"], "operations": [
        {"seq": 10, "name": "Sterilise", "group_id": g["id"], "setup_minutes": 0, "run_minutes": 0.001}]})
    api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
    api.put(f"/items/{it['id']}/planning", {"ster_cycle_code": "ETO-STD", "aeration_hours": 48,
                                            "release_mode": "bi", "release_days": 7}, 0)
    api.put(f"/items/{it['id']}/packaging", {"levels": [{"level": "each", "code": "EA", "qty_base": 1},
                                                         {"level": "pallet", "code": "PL", "qty_base": 1000}]}, 1)
    wos = []
    for k in range(n_wos):
        wo = api.post("/work-orders", {"item_id": it["id"], "qty": 5000, "due_date": (
            date.today() + timedelta(days=1)).isoformat(), "start_date": date.today().isoformat()})
        wo = api.post(f"/work-orders/{wo['id']}/release", {"override_reason": "test"}, status=200,
                      version=wo["row_version"])
        api.post("/inventory/postings", {"type": "wo_receipt", "lines": [
            {"wo_id": wo["id"], "location_id": st["id"], "qty": 5000, "lot_code": f"L-ST-{k}"}]})
        wos.append(wo)
    return it, wos


@pytest.mark.req("M8-STER-02", "M8-STER-03")
def test_cycle_holds_release_signed_and_fail_ncr(world):
    o = world.owner.api
    qa = world.member("qa", ["qa_approver"])
    it, wos = _setup(o, 2)
    pending = o.get("/qa/holds", source="sterility")["items"]           # review 1: held from receipt
    assert len(pending) == 2 and all(h["source_id"] is None for h in pending)
    out = o.post("/ster/plan", {"days": 7}, 200)
    assert out["loads"] == 1 and out["pallets"] == 10, out
    load = o.get(f"/ster/loads/{out['load_ids'][0]}")
    assert load["status"] == "planned" and {m["wo_id"] for m in load["members"]} == {w["id"] for w in wos}
    load = o.post(f"/ster/loads/{load['id']}/load", None, 200, version=load["row_version"])
    assert load["status"] == "loaded" and load["batch_load_id"]
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def at(hours: float) -> str:
        return (now + timedelta(hours=hours)).isoformat()
    o.err("POST", f"/ster/loads/{load['id']}/advance", 422, "STER_TIME_INVALID", json={"to": "cycling",
                                                                                      "at": at(2)})
    load = o.post(f"/ster/loads/{load['id']}/advance", {"to": "cycling", "at": at(-70)}, 200)
    o.err("POST", f"/ster/loads/{load['id']}/advance", 422, "STER_TIME_INVALID", json={"to": "aerating",
                                                                                      "at": at(-80)})
    load = o.post(f"/ster/loads/{load['id']}/advance", {"to": "aerating", "at": at(-56)}, 200)
    holds = o.get("/qa/holds", source="sterility")["items"]
    assert len(holds) == 2 and all(h["planned_release"] == load["release_due"] for h in holds)
    assert {h["id"] for h in holds} == {h["id"] for h in pending}            # the receipt holds were taken over
    assert all(h["source_number"] == load["number"] for h in holds)
    lst = o.get("/ster/loads")
    assert lst["aeration"]["positions"] == 96 and lst["chambers"][0]["pallets"] == 24
    # co-sterilised: forward trace from one lot reaches the other lot through the load
    tr = o.get("/trace", kind="lot", id=holds[0]["lot_id"], direction="forward")
    import json
    assert holds[1]["lot_id"] in json.dumps(tr) and '"ster_load"' in json.dumps(tr)
    # MRP pass sees the WO available at the release date (WOs are received here, so check the plan input only)
    o.err("POST", f"/qa/holds/{holds[0]['id']}/release", 409, "QA_HOLD_OWNED", json={"note": "x"})
    o.err("POST", f"/ster/loads/{load['id']}/advance", 409, "STER_AERATION_INCOMPLETE",
          json={"to": "awaiting_release", "at": at(-50)})
    load = o.post(f"/ster/loads/{load['id']}/advance", {"to": "awaiting_release", "at": at(-1)}, 200)
    # M9 follow-up (M8 15): the record lists the held lots; the signature preview's "Lots" row shows their codes
    assert {x["lot_id"] for x in load["lots"]} == {h["lot_id"] for h in holds} and all(x["lot_code"]
                                                                                      for x in load["lots"])
    pv = qa.api.get("/esig/preview", record_type="ster_load", record_id=load["id"], action="release")
    lots_row = [r for r in pv["summary"] if r.get("label") == "Lots"]
    assert lots_row and lots_row[0]["value"] == ", ".join(sorted(x["lot_code"] for x in load["lots"])), pv
    assert o.get("/dashboard")["tiles"]["ster_release"]["value"] == 1
    qa.api.err("POST", f"/ster/loads/{load['id']}/release", 422, "ESIG_REQUIRED", json={"early_release_reason": "x"})
    sig = signature(qa, "ster_load", load["id"], "release", "approved")
    qa.api.err("POST", f"/ster/loads/{load['id']}/release", 409, "STER_RELEASE_TOO_EARLY",
               json={"signature": sig})                               # release_due is days ahead
    sig = signature(qa, "ster_load", load["id"], "release", "approved")
    rel = qa.api.post(f"/ster/loads/{load['id']}/release", {"signature": sig, "note": "BI negative",
                                                            "early_release_reason": "Parametric release approved"},
                      200)
    assert rel["status"] == "released" and rel["release_signature_id"] and rel["signatures"]
    assert o.get("/qa/holds", source="sterility", open="true")["total"] == 0
    # STER-03: a second load fails -> holds kept, one NCR with all lots
    it2, wos2 = it, []
    wo = o.post("/work-orders", {"item_id": it["id"], "qty": 3000, "due_date": (date.today() + timedelta(days=2))
                                 .isoformat(), "start_date": date.today().isoformat()})
    wo = o.post(f"/work-orders/{wo['id']}/release", {"override_reason": "t"}, status=200, version=wo["row_version"])
    fg = o.get("/locations", q="FG")["items"][0]
    o.post("/inventory/postings", {"type": "wo_receipt", "lines": [{"wo_id": wo["id"], "location_id": fg["id"],
                                                                    "qty": 3000, "lot_code": "L-ST-9"}]})
    p2 = o.post("/ster/plan", {"days": 7}, 200)
    l2 = o.get(f"/ster/loads/{p2['load_ids'][0]}")
    l2 = o.post(f"/ster/loads/{l2['id']}/load", None, 200)
    l2 = o.post(f"/ster/loads/{l2['id']}/advance", {"to": "cycling"}, 200)
    failed = qa.api.post(f"/ster/loads/{l2['id']}/fail", {"reason": "BI positive"}, 200)
    assert failed["status"] == "failed" and failed["ncr_id"]
    ncr = o.get(f"/qa/ncrs/{failed['ncr_id']}")
    assert "L-ST-9" in ncr["description"] and ncr["severity"] == "critical"
    assert o.get("/qa/holds", source="sterility", open="true")["total"] == 1
    lot9 = o.get("/qa/holds", source="sterility", open="true")["items"][0]["lot_id"]
    assert any(x["to_type"] == "lot" and x["to_id"] == lot9 for x in ncr["links"])            # review 8
    # review 8: the failed member is planned again; the new load takes over its hold at cycle complete
    p3 = o.post("/ster/plan", {"days": 7}, 200)
    assert p3["loads"] == 1
    l3 = o.post(f"/ster/loads/{p3['load_ids'][0]}/load", None, 200)
    l3 = o.post(f"/ster/loads/{l3['id']}/advance", {"to": "cycling"}, 200)
    l3 = o.post(f"/ster/loads/{l3['id']}/advance", {"to": "aerating"}, 200)
    h9 = o.get("/qa/holds", source="sterility", open="true")["items"]
    assert len(h9) == 1 and h9[0]["source_id"] == l3["id"]
    _ = (it2, wos2)


def test_mrp_avail_is_release_date(world):
    o = world.owner.api
    it, wos = _setup(o, 0)
    wo = o.post("/work-orders", {"item_id": it["id"], "qty": 2000, "due_date": (date.today() + timedelta(days=1))
                                 .isoformat(), "start_date": date.today().isoformat()})
    p = o.post("/ster/plan", {"days": 7}, 200)
    load = o.get(f"/ster/loads/{p['load_ids'][0]}")
    run = o.post("/mrp/runs", {"label": "t", "horizon_days": 60})
    plan = o.get(f"/mrp/runs/{run['id']}/items/{it['id']}")
    sup = next(x for x in plan["supplies"] if x["kind"] == "wo")
    assert sup["avail_date"] == load["release_due"]
    # review 1: received lots under sterility hold are no free stock; supply at the planned release date
    fg = o.get("/locations", q="FG")["items"][0]
    o.post(f"/work-orders/{wo['id']}/release", {"override_reason": "t"}, status=200, version=wo["row_version"])
    o.post("/inventory/postings", {"type": "wo_receipt", "lines": [{"wo_id": wo["id"], "location_id": fg["id"],
                                                                    "qty": 2000, "lot_code": "L-RS-1"}]})
    o.post("/ster/plan", {"days": 7}, 200)
    due = o.get("/ster/loads", status="planned")["items"][0]["release_due"]
    run = o.post("/mrp/runs", {"label": "t2", "horizon_days": 60})
    plan = o.get(f"/mrp/runs/{run['id']}/items/{it['id']}")
    assert not [x for x in plan["supplies"] if x["kind"] == "stock"]
    held = [x for x in plan["supplies"] if x["kind"] == "inspection"]
    assert held and held[0]["avail_date"] == due and held[0]["qty"] == 2000


def test_ster_fields_need_quality_permission(world):
    o = world.owner.api
    pl = world.member("pl", ["planner"], enroll=False)
    it = o.item("STF-1", "make", lead_time_days=1)
    pl.api.err("PUT", f"/items/{it['id']}/planning", 403, "MFG_FORBIDDEN",
               json={"ster_cycle_code": "ETO-STD"}, headers={"If-Match": '"0"'})
    pl.api.put(f"/items/{it['id']}/planning", {"forecast": True}, 0)                   # other fields: fine
    qa = world.member("qe", ["qa_engineer", "planner"], enroll=False)
    qa.api.put(f"/items/{it['id']}/planning", {"forecast": True, "ster_cycle_code": "ETO-STD"}, 1)
