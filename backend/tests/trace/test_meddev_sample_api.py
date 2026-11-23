"""Meddev sample loaded through the API (`POST /samples/meddev/load`): health ok and idempotent, the floor history
gives a two-level lot genealogy (finished IV-set lot -> drip-chamber and tubing lots -> resin supplier lots), lot
shipments to two customers, a recall from the resin supplier lot that quarantines the sets still in stock, floor
KPIs from the history and a released work order in progress for the floor."""

from __future__ import annotations

from trace_helpers import flat


def test_meddev_load_genealogy_recall_and_floor(api):
    out = api.load("meddev")
    assert out["health"]["ok"] is True
    again = api.load("meddev")                              # idempotent: no second history
    assert all(c["create"] == c["update"] == c["delete"] == 0 for c in again["result"]["counts"].values())
    assert len([w for w in api.get("/work-orders", q="WO-MDV-H", limit=50)["items"]]) == 5

    lot = next(x for x in api.get("/lots", q="WO-MDV-H03", limit=50)["items"] if x["lot_code"] == "WO-MDV-H03")
    back = flat(api.get("/trace", kind="lot", id=lot["id"], direction="backward")["root"])
    labels = {n["label"] for n in back}
    assert {"MDV-DCH lot WO-MDV-H01", "MDV-TUB-IV lot WO-MDV-H02", "MDV-RES-PP lot H01-RES-PP",
            "MDV-RES-PVC lot H02-RES-PVC", "MDV-SOLV lot H03-SOLV", "MDV-LBL-UDI lot H03-LBL-UDI"} <= labels
    assert {n["precision"] for n in back} == {"exact"}
    fw = flat(api.get("/trace", kind="lot", id=lot["id"], direction="forward")["root"])
    assert {n["label"] for n in fw if n["kind"] == "demand_line"} == {
        "DO-MDV-H01/10 Northern regional hospital network (fictional)",
        "DO-MDV-H02/10 US distributor Alpha (fictional)"}

    pp = api.by_pn("MDV-RES-PP")
    rec = api.post("/recalls", {"name": "PP resin lot RSN-PP-88412",
                                "sources": [{"item_id": pp["id"], "supplier_lot": "RSN-PP-88412"}]})
    rep = rec["report"]
    # the same resin supplier lot went into drip chambers (IV sets) and 10 mL barrels (syringes)
    assert {w["number"] for w in rep["wos"]} == {"WO-MDV-H01", "WO-MDV-H03", "WO-MDV-H04", "WO-MDV-H05"}
    assert {x["demand_order"] for x in rep["shipments"]} == {"DO-MDV-H01", "DO-MDV-H02", "DO-MDV-H03"}
    assert {x["precision"] for x in rep["shipments"]} == {"exact"}
    q = api.post(f"/recalls/{rec['id']}/quarantine", {}, status=200)
    assert q["moved"] >= 1
    held = next(x for x in api.get("/lots", q="WO-MDV-H03", limit=50)["items"] if x["lot_code"] == "WO-MDV-H03")
    assert held["hold"] is True

    k = api.get("/kpis")
    assert k is not None
    wo = api.doc("/work-orders", "WO-MDV-0001")
    assert wo["status"] == "in_progress"
    ops = api.get(f"/work-orders/{wo['id']}/operations")["items"]
    assert [o["status"] for o in ops][:2] == ["completed", "ready"]
