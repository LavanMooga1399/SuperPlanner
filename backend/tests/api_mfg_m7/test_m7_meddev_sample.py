"""M7-DESIGN 12: the `meddev` sample gains schemes, plans, equipment and a quality history; health stays as the
M1-M4 sample expects (no QA errors), and loading twice does not duplicate the M7 data."""

from __future__ import annotations


def test_meddev_m7_sample(api):
    out = api.load("meddev")
    assert out["health"]["ok"] is True
    sch = {x["code"] for x in api.get("/qa/schemes")["items"]}
    assert sch == {"EXAMPLE-TABLE", "FIXED-5", "FULL"}
    plans = api.get("/qa/plans", limit=50)["items"]
    assert {p["scope"] for p in plans} == {"incoming", "in_process", "final"} and len(plans) == 5
    eq = api.get("/qa/equipment", limit=50)["items"]
    assert len(eq) == 12
    states = {e["code"]: e["due_state"] for e in eq}
    assert states["CAL-0004"] == "overdue" and states["CAL-0003"] == "due_soon"
    lots = api.get("/qa/inspection-lots", limit=200)
    assert lots["total"] >= 20
    assert sum(1 for x in lots["items"] if x["overdue"]) >= 1
    ncrs = api.get("/qa/ncrs")["items"]
    assert sorted(n["status"] for n in ncrs) == ["approved", "closed", "proposed"]
    assert [c["status"] for c in api.get("/qa/capas")["items"]] == ["implementation"]
    assert api.get("/qa/complaints")["total"] == 2
    fas = api.get("/qa/field-actions")["items"]
    assert len(fas) == 1 and fas[0]["units_total"] > 0
    h = api.get("/health")
    assert not [i for i in h["issues"] if i["code"].startswith("QA_") and i["severity"] == "error"]
    held = [x for x in api.get("/lots", hold=True, limit=200)["items"]]
    holds = api.get("/qa/holds", limit=200)["items"]
    assert {x["lot_id"] for x in holds} >= {x["id"] for x in held}
    api.load("meddev")
    assert len(api.get("/qa/schemes")["items"]) == 3
