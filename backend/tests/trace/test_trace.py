"""Genealogy (M5-DESIGN 6; T-T1, T-T2) on a plant built through the API, plus the backfill (6.1)."""

from __future__ import annotations

from trace_helpers import build, flat


def test_t_t1_forward_backward_where_used_and_backfill(api, client):
    d = build(api)
    lot = d["lot"]
    fwd = api.get("/trace", kind="lot", id=lot["id"], direction="forward")
    nodes = flat(fwd["root"])
    by = {(n["kind"], n["label"]): n for n in nodes}
    wos = [n for n in nodes if n["kind"] == "wo"]
    assert {w["label"] for w in wos} >= {d["pcb_wos"][0]["number"], d["pcb_wos"][1]["number"]}
    for p in ("P1", "P2", "P3"):
        assert by[("serial", p)]["precision"] == "possible"                    # lot -> unit through the WO
    for t in ("T1", "T2", "T3"):
        assert by[("serial", t)]["precision"] == "exact"                       # child -> parent serial link
    ships = [n for n in nodes if n["kind"] == "demand_line"]
    assert len(ships) == 2 and {"Rail zone A", "Rail zone B"} <= {n["label"].split(" ", 1)[1] for n in ships}
    # backward from a TPU: its WO, its PCB (exact), the capacitor lot (possible for the unit)
    t1 = d["serials"]["T1"]
    back = flat(api.get("/trace", kind="serial", id=t1["id"], direction="backward")["root"])
    kb = {(n["kind"], n["label"]): n for n in back}
    assert kb[("serial", "P1")]["precision"] == "exact"
    lots = [n for n in back if n["kind"] == "lot"]
    assert lots and lots[0]["label"] == "CAP lot L-2611" and lots[0]["precision"] == "possible"
    exact_only = flat(api.get("/trace", kind="serial", id=t1["id"], direction="backward",
                              include_possible=False)["root"])
    assert not [n for n in exact_only if n["kind"] == "lot"]
    wu = api.get("/trace/where-used", item_id=d["cap"]["id"], supplier_lot="SUPP-2611")
    assert {x["label"] for x in wu["items"] if x["depth"] == 1} == {w["number"] for w in d["pcb_wos"]}
    api.err("GET", "/trace", 404, "NOT_FOUND", params={"kind": "lot", "id": "lot_nope"})
    # backfill is idempotent and rebuilds the same edges
    from superplanner.api.db.ownership import system_scope
    from superplanner.api.mfg.db_models_m5 import MfgTraceEdgeRow
    from superplanner.api.mfg.services.trace import backfill
    from sqlalchemy import delete, func, select

    ctx = client.app.state.ctx
    with system_scope(), ctx.db.write() as s:
        n0 = s.execute(select(func.count()).select_from(MfgTraceEdgeRow)).scalar()
        assert backfill(s)["edges_added"] == 0
        s.execute(delete(MfgTraceEdgeRow))
        r = backfill(s)
        assert r["edges_added"] == n0, (r, n0)
    again = flat(api.get("/trace", kind="lot", id=lot["id"], direction="forward")["root"])
    assert sorted((n["kind"], n["label"], n["precision"]) for n in again) == \
        sorted((n["kind"], n["label"], n["precision"]) for n in nodes)


def test_t_t2_recall_and_quarantine(api):
    d = build(api)
    rec = api.post("/recalls", {"name": "Cap lot", "sources": [{"item_id": d["cap"]["id"],
                                                              "supplier_lot": "SUPP-2611"}]})
    assert rec["number"] == "RCL-000001"
    rep = rec["report"]
    assert {u["serial"] for u in rep["units"]} == {"P1", "P2", "P3", "T1", "T2", "T3"}
    assert {c["customer"]: c["shipments"] for c in rep["by_customer"]} == {"Rail zone A": 1, "Rail zone B": 1}
    lots = [x for x in rep["lots"] if x["on_hand"] > 0]
    assert len(lots) == 1 and lots[0]["on_hand"] == 94 and lots[0]["location"] == "ST"
    assert api.get("/recalls")["total"] == 1
    x = api.req("GET", f"/recalls/{rec['id']}/export", 200)
    assert x.content[:2] == b"PK"
    q = api.post(f"/recalls/{rec['id']}/quarantine", {}, status=200)
    assert q["moved"] == 1 and q["lots_on_hold"] == 1 and len(q["postings"]) == 1
    bal = api.get("/inventory/balances", item_id=d["cap"]["id"])["items"]
    assert {(b["location"]["code"], b["qty_on_hand"]) for b in bal if b["qty_on_hand"]} == {("QA", 94)}
    assert api.get("/lots", item_id=d["cap"]["id"])["items"][0]["hold"] is True
    assert api.get(f"/recalls/{rec['id']}")["quarantined_at"] is not None
