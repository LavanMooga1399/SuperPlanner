"""Acceptance 3 (M5-DESIGN 13): genealogy of the Kavach M4 sample - every captured CPU serial traces back to
supplier lots; a coating lot traces forward to the units; the recall report matches."""

from __future__ import annotations

from trace_helpers import flat


def test_kavach_serials_reach_supplier_lots(api):
    api.load("kavach")
    sers = api.get("/serials", limit=200)["items"]
    assert len(sers) == 35
    for s in sers:
        nodes = flat(api.get("/trace", kind="serial", id=s["id"], direction="backward")["root"])
        lots = [n for n in nodes if n["kind"] == "lot"]
        assert lots and all(n["precision"] == "possible" for n in lots), s["serial"]
    coat = api.by_pn("KV-COAT-UR")
    lot = next(x for x in api.get("/lots", item_id=coat["id"], limit=50)["items"] if x["lot_code"].startswith("H01"))
    fw = flat(api.get("/trace", kind="lot", id=lot["id"], direction="forward")["root"])
    units = {n["label"] for n in fw if n["kind"] == "serial"}
    assert len(units) == 12 and all(u.startswith("CPU-H") for u in units)   # WO-KV-H01: 12 good boards (yield)
    rec = api.post("/recalls", {"name": "coating", "sources": [{"item_id": coat["id"],
                                                                "supplier_lot": lot["supplier_lot"]}]})
    assert {u["serial"] for u in rec["report"]["units"]} == units
    assert {w["number"] for w in rec["report"]["wos"]} == {"WO-KV-H01"}
    ships = rec["report"]["shipments"]       # shipped from the shared FG stock: possible links only
    assert "DO-KV-H01" in {x["demand_order"] for x in ships} and {x["precision"] for x in ships} == {"possible"}
