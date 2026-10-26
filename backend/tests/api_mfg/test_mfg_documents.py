"""B2: BOM/routing documents, release/supersede/obsolete/copy, cycles, and the computed views against the pure
results (M1-DESIGN 4.2, 5, 9.3 #10-28, #39, #67; PLAN-M1 B2-1..B2-3, B2-5)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from apimfg_helpers import Mfg, err, etag, to_input
from superplanner.api.db.ownership import system_scope
from superplanner.api.mfg import repo
from superplanner.api.mfg.services.common import jsonable
from superplanner.mfg import limits as L
from superplanner.mfg import model as mm
from superplanner.mfg.bom import explode, where_used
from superplanner.mfg.calendar import line_windows, window_minutes
from superplanner.mfg.dataset import BomIndex, ParentIndex
from superplanner.mfg.health import run_health_check
from superplanner.mfg.routing import time_preview


def _parts(m: Mfg) -> dict[str, dict[str, Any]]:
    out = {"A": m.item("A", "make"), "B": m.item("B", "make"), "C": m.item("C", "make")}
    for pn in ("X", "Y", "Z"):
        out[pn] = m.item(pn)
    return out


def _bom(m: Mfg, parent: str, lines: list[tuple[str, str, float]], **kw: Any) -> dict[str, Any]:
    return m.post("/boms", {"item_id": parent, "lines": [{"find_number": fn, "child_item_id": c, "qty_per": q}
                                                         for fn, c, q in lines], **kw})


def test_bom_document_put_keeps_line_ids(mfg: Mfg):
    p = _parts(mfg)
    b = _bom(mfg, p["A"]["id"], [("10", p["X"]["id"], 1), ("20", p["Y"]["id"], 2)])
    assert b["status"] == "draft" and b["version"] == 1 and b["revision"] == "A"
    assert [ln["child"]["part_number"] for ln in b["lines"]] == ["X", "Y"] and b["lines"][0]["uom"] == "EA"
    keep, drop = b["lines"]
    body = to_input(mm.BomInput, b)
    body["lines"] = [{**to_input(mm.BomLineInput, keep), "qty_per": 5},
                     {"find_number": "30", "child_item_id": p["Z"]["id"], "qty_per": 1, "uom": "EA"}]
    nb = mfg.put(f"/boms/{b['id']}", body, 1)
    assert nb["row_version"] == 2
    ids = {ln["child"]["part_number"]: ln["id"] for ln in nb["lines"]}
    assert ids["X"] == keep["id"] and "Y" not in ids and ids["Z"] not in (keep["id"], drop["id"])
    assert [ln["qty_per"] for ln in nb["lines"]] == [5, 1]
    # swap find numbers of two kept lines (unique key moves through placeholders)
    body = to_input(mm.BomInput, nb)
    body["lines"][0]["find_number"], body["lines"][1]["find_number"] = "30", "10"
    sw = mfg.put(f"/boms/{b['id']}", body, 2)
    assert {ln["child"]["part_number"]: ln["find_number"] for ln in sw["lines"]} == {"X": "30", "Z": "10"}
    # a line id of another BOM -> 422
    other = _bom(mfg, p["B"]["id"], [("10", p["X"]["id"], 1)])
    body = to_input(mm.BomInput, sw)
    body["lines"][0]["id"] = other["lines"][0]["id"]
    e = err(mfg.req("PUT", f"/boms/{b['id']}", json=body, headers=etag(3)), 422, "VALIDATION_ERROR")
    assert e["details"]["errors"][0]["loc"] == ["body", "lines", 0, "id"]
    body = to_input(mm.BomInput, sw)
    body["item_id"] = p["B"]["id"]
    err(mfg.req("PUT", f"/boms/{b['id']}", json=body, headers=etag(3)), 422, "VALIDATION_ERROR")
    body = to_input(mm.BomInput, sw)
    body["lines"].append({"find_number": "40", "child_item_id": f"itm_{uuid.uuid4().hex}", "qty_per": 1})
    e = err(mfg.req("PUT", f"/boms/{b['id']}", json=body, headers=etag(3)), 422, "MFG_UNKNOWN_REFERENCE")
    assert e["details"]["loc"] == ["body", "lines", 2, "child_item_id"]
    body = to_input(mm.BomInput, sw)
    body["lines"].append(dict(body["lines"][0], id=None))
    err(mfg.req("PUT", f"/boms/{b['id']}", json=body, headers=etag(3)), 422, "VALIDATION_ERROR")
    assert mfg.get(f"/boms/{b['id']}")["row_version"] == 3


def test_bom_rules_and_cycles(mfg: Mfg):
    p = _parts(mfg)
    err(mfg.req("POST", "/boms", json={"item_id": p["X"]["id"]}), 422, "MFG_ITEM_NOT_MAKE")
    err(mfg.req("POST", "/boms", json={"item_id": f"itm_{uuid.uuid4().hex}"}), 422, "MFG_UNKNOWN_REFERENCE")
    err(mfg.req("POST", "/boms", json={"item_id": p["A"]["id"], "serial_from": 1, "serial_to": 5}), 422,
        "MFG_SERIAL_NOT_ALLOWED")
    e = err(mfg.req("POST", "/boms", json={"item_id": p["A"]["id"], "lines": [
        {"find_number": "10", "child_item_id": p["A"]["id"], "qty_per": 1}]}), 422, "MFG_BOM_CYCLE")
    assert e["details"]["cycle"] == ["A", "A"]
    _bom(mfg, p["A"]["id"], [("10", p["B"]["id"], 1)])
    b = _bom(mfg, p["B"]["id"], [("10", p["C"]["id"], 1)])
    e = err(mfg.req("POST", "/boms", json={"item_id": p["C"]["id"], "lines": [
        {"find_number": "10", "child_item_id": p["A"]["id"], "qty_per": 1}]}), 422, "MFG_BOM_CYCLE")
    assert e["details"]["cycle"] == ["C", "A", "B", "C"]
    c = mfg.post("/boms", {"item_id": p["C"]["id"]})
    body = {**to_input(mm.BomInput, c), "lines": [{"find_number": "10", "child_item_id": p["A"]["id"], "qty_per": 1}]}
    err(mfg.req("PUT", f"/boms/{c['id']}", json=body, headers=etag(1)), 422, "MFG_BOM_CYCLE")
    # duplicate key on create
    err(mfg.req("POST", "/boms", json={"item_id": p["B"]["id"], "version": b["version"]}), 409, "MFG_DUPLICATE_KEY")
    assert mfg.post("/boms", {"item_id": p["B"]["id"]})["version"] == 2


def test_release_supersede_obsolete_copy_and_eco_explosion(mfg: Mfg):
    p = _parts(mfg)
    v1 = _bom(mfg, p["A"]["id"], [("10", p["X"]["id"], 1)])
    err(mfg.req("POST", f"/boms/{v1['id']}/release", json={}), 428, "PRECONDITION_REQUIRED")
    r = mfg.req("POST", f"/boms/{v1['id']}/release", 200, json={"effective_from": "2026-01-01"}, headers=etag(1))
    rel = r.json()
    assert rel["bom"]["status"] == "released" and rel["superseded"] == [] and r.headers["ETag"] == '"2"'
    body = to_input(mm.BomInput, rel["bom"])
    err(mfg.req("PUT", f"/boms/{v1['id']}", json=body, headers=etag(2)), 409, "MFG_RELEASED_READONLY")
    err(mfg.req("DELETE", f"/boms/{v1['id']}", headers=etag(2)), 409, "MFG_RELEASED_READONLY")
    err(mfg.req("POST", f"/boms/{v1['id']}/release", json={}, headers=etag(2)), 409, "MFG_INVALID_STATE")
    # ECO: copy -> edit -> release with supersede at a future date
    r = mfg.req("POST", f"/boms/{v1['id']}/copy", 201, json={}, headers=etag(2))
    v2 = r.json()
    assert v2["status"] == "draft" and v2["version"] == 2 and v2["effective_from"] is None
    assert [ln["id"] for ln in v2["lines"]] != [ln["id"] for ln in v1["lines"]]
    body = to_input(mm.BomInput, v2)
    body["lines"][0]["qty_per"] = 3
    v2 = mfg.put(f"/boms/{v2['id']}", body, 1)
    e = err(mfg.req("POST", f"/boms/{v2['id']}/release", json={}, headers=etag(2)), 422, "MFG_RELEASE_BLOCKED")
    assert e["details"]["issues"][0]["code"] == "MFG_BOM_EFFECTIVITY_OVERLAP"
    err(mfg.req("POST", f"/boms/{v2['id']}/release", json={"supersede_previous": True}, headers=etag(2)), 422,
        "VALIDATION_ERROR")
    rel = mfg.post(f"/boms/{v2['id']}/release", {"effective_from": "2026-12-01", "supersede_previous": True},
                   status=200, headers=etag(2))
    assert rel["superseded"] == [{"id": v1["id"], "version": 1, "effective_to": "2026-12-01"}]
    old = mfg.get(f"/boms/{v1['id']}")
    assert old["effective_to"] == "2026-12-01" and old["row_version"] == 3
    a = p["A"]["id"]
    before = mfg.get(f"/items/{a}/explosion", params={"on": "2026-11-30"})
    after = mfg.get(f"/items/{a}/explosion", params={"on": "2026-12-01"})
    assert before["rows"][1]["extended_qty"] == 1 and after["rows"][1]["extended_qty"] == 3
    assert before["rows"][1]["bom_id"] is None and before["rows"][0]["bom_id"] == v1["id"]
    wu_all = mfg.get(f"/items/{p['X']['id']}/where-used", params={"include": "all"})
    assert sorted(r["bom_version"] for r in wu_all["rows"]) == [1, 2]
    wu = mfg.get(f"/items/{p['X']['id']}/where-used", params={"on": "2026-11-30"})
    assert [r["bom_version"] for r in wu["rows"]] == [1]
    # obsolete; obsolete -> delete allowed
    ob = mfg.post(f"/boms/{v1['id']}/obsolete", {}, status=200, headers=etag(3))
    assert ob["status"] == "obsolete" and ob["obsoleted_at"]
    err(mfg.req("POST", f"/boms/{v1['id']}/obsolete", json={}, headers=etag(4)), 409, "MFG_INVALID_STATE")
    err(mfg.req("PUT", f"/boms/{v1['id']}", json=to_input(mm.BomInput, ob), headers=etag(4)), 409,
        "MFG_RELEASED_READONLY")
    mfg.delete(f"/boms/{v1['id']}", 4)
    lst = mfg.get(f"/items/{a}/boms")["items"]
    assert [x["version"] for x in lst] == [2] and lst[0]["line_count"] == 1 and "lines" not in lst[0]


def test_routing_documents_and_time_preview(mfg: Mfg):
    mfg.load("small")
    item = mfg.by_pn("SM-100")
    rt = mfg.get(f"/items/{item['id']}/routings")["items"][0]
    assert rt["operation_count"] == 4 and "operations" not in rt
    full = mfg.get(f"/routings/{rt['id']}")
    assert [o["seq"] for o in full["operations"]] == [10, 20, 30, 40] and full["operations"][0]["group"]["code"]
    err(mfg.req("PUT", f"/routings/{rt['id']}", json=to_input(mm.RoutingInput, full), headers=etag(1)), 409,
        "MFG_RELEASED_READONLY")
    cp = mfg.post(f"/routings/{rt['id']}/copy", {"code": "ALT"}, headers=etag(rt["row_version"]))
    assert cp["code"] == "ALT" and cp["version"] == 1 and cp["status"] == "draft"
    assert len(cp["operations"]) == 4 and any(o["tools"] for o in cp["operations"])
    body = to_input(mm.RoutingInput, cp)
    body["priority"] = 2
    ops = body["operations"]
    ops[0]["seq"], ops[1]["seq"] = 20, 10                   # reorder: swap seqs of kept operations
    ops.pop()                                                 # drop op 40
    nr = mfg.put(f"/routings/{cp['id']}", body, 1)
    assert [o["name"] for o in nr["operations"]][:2] == [cp["operations"][1]["name"], cp["operations"][0]["name"]]
    assert len(nr["operations"]) == 3 and nr["operations"][1]["id"] == cp["operations"][0]["id"]
    body = to_input(mm.RoutingInput, nr)
    body["operations"].append({**body["operations"][0], "id": None})
    e = err(mfg.req("PUT", f"/routings/{cp['id']}", json=body, headers=etag(2)), 422, "VALIDATION_ERROR")
    assert e["details"]["errors"][0]["type"] == "duplicate_seq"
    err(mfg.req("POST", "/routings", json={"item_id": mfg.by_pn("SM-BPCB-100")["id"]}), 422, "MFG_ITEM_NOT_MAKE")
    tp = mfg.get(f"/routings/{rt['id']}/time-preview", params={"qty": 250})
    with system_scope(), mfg.c.app.state.ctx.db.read() as s:
        ds = repo.load_dataset(s)
    assert tp == jsonable(time_preview(ds, rt["id"], 250))
    err(mfg.req("GET", f"/routings/{rt['id']}/time-preview", params={"qty": 0}), 422, "VALIDATION_ERROR")
    rel = mfg.post(f"/routings/{cp['id']}/release", {"effective_from": "2026-01-01"}, status=200, headers=etag(2))
    assert rel["routing"]["status"] == "released" and rel["superseded"] == []
    mfg.post(f"/routings/{cp['id']}/obsolete", {}, status=200, headers=etag(3))
    mfg.delete(f"/routings/{cp['id']}", 4)


def test_views_equal_pure_results_for_kavach(mfg: Mfg):
    mfg.load("kavach")
    on = date(2026, 11, 2)
    with system_scope(), mfg.c.app.state.ctx.db.read() as s:
        ds = repo.load_dataset(s)
    top = ds.items_by_pn["KV-TPU-1000"]
    got = mfg.get(f"/items/{top.id}/explosion", params={"on": on.isoformat(), "qty": 2})
    assert got == jsonable(explode(BomIndex.from_dataset(ds, on), top.id, qty=2))
    got = mfg.get(f"/items/{top.id}/explosion", params={"on": on.isoformat(), "mode": "summarized",
                                                        "include_scrap": False})
    assert got == jsonable(explode(BomIndex.from_dataset(ds, on), top.id, mode="summarized", include_scrap=False))
    cap = ds.items_by_pn["KV-CAP-0402-100N"]
    for mode in ("single", "indented"):
        got = mfg.get(f"/items/{cap.id}/where-used", params={"mode": mode, "on": on.isoformat()})
        assert got == jsonable(where_used(ParentIndex.from_dataset(ds, on, "effective"), cap.id, mode=mode))
        assert len(got["rows"]) >= 10 or mode == "single"
    line = next(x for x in ds.lines.values() if x.code == "SMT-2")
    got = mfg.get(f"/lines/{line.id}/windows", params={"from": "2026-11-09", "to": "2026-11-16"})
    wins = line_windows(ds, line.id, date(2026, 11, 9), date(2026, 11, 16))
    assert got["windows"] == jsonable(wins) and got["totals"] == window_minutes(wins)
    assert got["utc_offset"] == "+05:30" and got["windows"][0]["start"].endswith("+05:30")
    base_only = mfg.get(f"/lines/{line.id}/windows", params={"from": "2026-11-09", "to": "2026-11-16",
                                                             "kinds": "base"})
    assert all(w["kind"] == "base" for w in base_only["windows"])
    err(mfg.req("GET", f"/lines/{line.id}/windows", params={"from": "2026-11-09", "to": "2027-01-20"}), 422,
        "MFG_RANGE_TOO_LONG")
    err(mfg.req("GET", f"/lines/{line.id}/windows", params={"from": "2026-11-09", "to": "2026-11-09"}), 422,
        "MFG_RANGE_TOO_LONG")
    err(mfg.req("GET", f"/lines/{line.id}/windows", params={"from": "2026-11-09", "to": "2026-11-10",
                                                            "kinds": "extra"}), 422, "VALIDATION_ERROR")
    h = mfg.get("/health", params={"as_of": on.isoformat(), "horizon_days": 90})
    exp = jsonable(run_health_check(ds, on, 90))
    exp["data_version"] = ds.plant.data_version
    assert h == exp and h["ok"] is True
    assert set(h["by_code"]) == {"MFG_LONG_LEAD_TIME", "MFG_SKILL_NOT_ON_SHIFT", "MFG_DUPLICATE_COMPONENT"}
    err(mfg.req("GET", "/health", params={"horizon_days": 5}), 422, "VALIDATION_ERROR")


def test_explosion_too_large_and_summarized_fallback(mfg: Mfg, monkeypatch):
    from superplanner.mfg import bom as bom_mod

    mfg.load("medium")
    top = mfg.by_pn("MD-200")
    monkeypatch.setattr(bom_mod, "MAX_EXPLOSION_ROWS", 20)
    e = err(mfg.req("GET", f"/items/{top['id']}/explosion"), 422, "MFG_EXPLOSION_TOO_LARGE")
    assert e["details"]["suggest"] == "mode=summarized"
    s = mfg.get(f"/items/{top['id']}/explosion", params={"mode": "summarized"})
    assert s["mode"] == "summarized" and len(s["rows"]) > 20
    cap = max(mfg.get("/items", params={"limit": 200, "make_buy": "buy"})["items"], key=lambda i: i["used_in_count"])
    monkeypatch.setattr(bom_mod, "MAX_EXPLOSION_ROWS", 1)
    e = err(mfg.req("GET", f"/items/{cap['id']}/where-used", params={"mode": "indented"}), 422,
            "MFG_EXPLOSION_TOO_LARGE")
    assert e["details"]["suggest"] == "mode=single"
    assert L.MAX_EXPLOSION_ROWS == 20_000
    err(mfg.req("GET", f"/items/itm_{uuid.uuid4().hex}/explosion"), 404, "NOT_FOUND")
    err(mfg.req("GET", "/items/nope/where-used"), 404, "NOT_FOUND")
