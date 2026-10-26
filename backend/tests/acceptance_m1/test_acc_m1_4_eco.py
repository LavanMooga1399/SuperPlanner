"""15.3 #4: ECO flow - copy the released BOM -> edit the draft -> release with supersede at a future date ->
explosion before/after that date differs exactly as edited; where-used `include=all` shows both versions; the
released documents are read-only."""

from __future__ import annotations

from accm1_helpers import Api, bom_input, check_link, im


def _qty(api: Api, item_id: str, on: str) -> dict[str, float]:
    ex = api.get(f"/items/{item_id}/explosion", on=on, mode="summarized")
    return {r["part_number"]: r["total_qty"] for r in ex["rows"]}


def test_eco_copy_edit_release_supersede(api: Api):
    api.load("small")
    top = api.item("SM-100")
    v1 = api.released_bom("SM-100")
    before = _qty(api, top["id"], "2026-11-30")

    v2 = api.post(f"/boms/{v1['id']}/copy", {"revision": None}, version=v1["row_version"])
    assert (v2["status"], v2["version"], v2["effective_from"], v2["effective_to"]) == ("draft", 2, None, None)
    assert {ln["id"] for ln in v2["lines"]}.isdisjoint({ln["id"] for ln in v1["lines"]})

    r10k, lbl, mcu = api.item("SM-RES-10K"), api.item("SM-LBL-01"), api.item("SM-MCU-01")
    body = bom_input(v2)
    for ln in body["lines"]:
        if ln["child_item_id"] == r10k["id"]:
            ln["qty_per"] += 2                                     # 4 -> 6 resistors
            ln["ref_designators"] = "R1-R4, R7-R8"
    body["lines"] = [ln for ln in body["lines"] if ln["child_item_id"] != mcu["id"]]   # MCU removed
    body["lines"].append({"find_number": "95", "child_item_id": lbl["id"], "qty_per": 1})  # second label
    v2 = api.put(f"/boms/{v2['id']}", body, v2["row_version"])
    assert len(v2["lines"]) == len(v1["lines"])

    # drafts are never effective
    assert _qty(api, top["id"], "2026-12-15") == before
    rel = api.post(f"/boms/{v2['id']}/release", {"effective_from": "2026-12-01", "supersede_previous": True},
                   status=200, version=v2["row_version"])
    assert rel["bom"]["status"] == "released" and rel["bom"]["effective_from"] == "2026-12-01"
    assert rel["superseded"] == [{"id": v1["id"], "version": 1, "effective_to": "2026-12-01"}]
    v1_after = api.get(f"/boms/{v1['id']}")
    assert v1_after["effective_to"] == "2026-12-01" and v1_after["status"] == "released"

    after = _qty(api, top["id"], "2026-12-01")
    assert _qty(api, top["id"], "2026-11-30") == before
    y = 0.98                                                       # FCT yield; every line is consumed before it
    assert abs(before["SM-RES-10K"] - round(4 / y, 6)) < 1e-9 and abs(after["SM-RES-10K"] - round(6 / y, 6)) < 1e-9
    assert "SM-MCU-01" in before and "SM-MCU-01" not in after
    assert abs(before["SM-LBL-01"] - round(1 / y, 6)) < 1e-9 and abs(after["SM-LBL-01"] - round(2 / y, 6)) < 1e-9
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {"SM-RES-10K", "SM-MCU-01", "SM-LBL-01"}, changed

    wu = api.get(f"/items/{r10k['id']}/where-used", include="all")
    versions = sorted((r["bom_version"], r["bom_status"], r["qty_per"]) for r in wu["rows"])
    assert versions == [(1, "released", 4.0), (2, "released", 6.0)], versions
    wu_eff = api.get(f"/items/{r10k['id']}/where-used", include="effective", on="2026-11-15")
    assert [(r["bom_version"], r["qty_per"]) for r in wu_eff["rows"]] == [(1, 4.0)]
    wu_eff2 = api.get(f"/items/{r10k['id']}/where-used", include="effective", on="2026-12-01")
    assert [(r["bom_version"], r["qty_per"]) for r in wu_eff2["rows"]] == [(2, 6.0)]
    wu_mcu = api.get(f"/items/{mcu['id']}/where-used", include="effective", on="2026-12-02")
    assert wu_mcu["rows"] == []

    # released documents are read-only: PUT/DELETE 409, a second release 409
    for bid, ver in ((v1["id"], v1_after["row_version"]), (v2["id"], rel["bom"]["row_version"])):
        r = api.raw("PUT", f"/boms/{bid}", json=bom_input(api.get(f"/boms/{bid}")), headers=im(ver))
        assert r.status_code == 409 and r.json()["error"]["code"] == "MFG_RELEASED_READONLY", r.text
        r = api.raw("DELETE", f"/boms/{bid}", headers=im(ver))
        assert r.status_code == 409 and r.json()["error"]["code"] == "MFG_RELEASED_READONLY", r.text
    r = api.raw("POST", f"/boms/{v2['id']}/release", json={}, headers=im(rel["bom"]["row_version"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "MFG_INVALID_STATE", r.text

    h = api.health()
    assert h["ok"], h["by_code"]
    assert h["by_code"] == {"MFG_DUPLICATE_COMPONENT": 1}, h["by_code"]   # the second label line (info)
    for i in h["issues"]:
        check_link(api, i)


def test_eco_on_kavach_explosion_differs_only_where_edited(api: Api):
    api.load("kavach")
    top = api.item("KV-TPU-1000")
    v1 = api.released_bom("KV-PCB-LED")
    before = _qty(api, top["id"], "2026-12-31")
    v2 = api.post(f"/boms/{v1['id']}/copy", {"revision": "B"}, version=v1["row_version"])
    assert v2["revision"] == "B"
    body = bom_input(v2)
    body["lines"][0]["qty_per"] *= 2
    child_pn = v2["lines"][0]["child"]["part_number"]
    v2 = api.put(f"/boms/{v2['id']}", body, v2["row_version"])
    api.post(f"/boms/{v2['id']}/release", {"effective_from": "2027-01-01", "supersede_previous": True},
             status=200, version=v2["row_version"])
    assert _qty(api, top["id"], "2026-12-31") == before
    after = _qty(api, top["id"], "2027-01-01")
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed == {child_pn}, changed
    assert after[child_pn] > before[child_pn]
