"""B1: CRUD, ETag / If-Match / 428 / 412, check order, natural-key 409, delete-in-use 409, reads insert nothing,
search escaping, meta (M1-DESIGN 9.1-9.6, PLAN-M1 B1-2..B1-4, B1-6)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from apimfg_helpers import MFG, Mfg, err, etag, row_counts, to_input
from superplanner.mfg import limits as L
from superplanner.mfg import model as mm

TEMPLATE = {"code": "REG", "name": "Regular", "shifts": [
    {"name": "Day", "days": ["mon", "tue", "wed", "thu", "fri", "sat"], "start": "09:00", "end": "18:00",
     "breaks": [{"name": "Lunch", "start": "13:00", "end": "13:45"}]}]}


def _world(m: Mfg) -> dict[str, Any]:
    g = m.group("SMT")
    ln = m.line("SMT-1", g["id"])
    t = m.post("/shift-templates", TEMPLATE)
    sk = m.post("/skills", {"code": "SMT-OP", "name": "SMT operator"})
    tp = m.post("/tool-pools", {"code": "STN-1", "name": "Stencil", "quantity": 1})
    return {"group": g, "line": ln, "template": t, "skill": sk, "pool": tp}


def _cases(m: Mfg) -> list[tuple[str, str, dict[str, Any], dict[str, Any], type]]:
    w = _world(m)
    return [
        ("/items", "/items/{}", {"part_number": "P-1", "make_buy": "buy", "lead_time_days": 5},
         {"description": "changed"}, mm.ItemInput),
        ("/groups", "/groups/{}", {"code": "AOI", "name": "AOI"}, {"name": "Optical"}, mm.GroupInput),
        ("/lines", "/lines/{}", {"code": "SMT-2", "name": "Line 2", "group_id": w["group"]["id"]},
         {"speed_factor": 0.7}, mm.LineInput),
        ("/shift-templates", "/shift-templates/{}", {**TEMPLATE, "code": "REG2"}, {"name": "Changed"},
         mm.ShiftTemplateInput),
        ("/shift-assignments", "/shift-assignments/{}",
         {"shift_template_id": w["template"]["id"], "target_type": "group", "group_id": w["group"]["id"],
          "effective_from": "2026-01-01"}, {"note": "n"}, mm.ShiftAssignmentInput),
        ("/calendar-exceptions", "/calendar-exceptions/{}",
         {"scope": "plant", "kind": "holiday", "start": "2026-11-09T00:00:00+00:00",
          "end": "2026-11-10T00:00:00+00:00", "label": "Holiday"}, {"label": "Changed"}, mm.CalendarExceptionInput),
        ("/skills", "/skills/{}", {"code": "TEST", "name": "Tester"}, {"name": "Test eng"}, mm.SkillInput),
        ("/operators", "/operators/{}", {"code": "OP-1", "name": "Operator 1", "skill_ids": [w["skill"]["id"]],
                                         "shift_template_id": w["template"]["id"], "shift_names": ["Day"]},
         {"active": False}, mm.OperatorInput),
        ("/tool-pools", "/tool-pools/{}", {"code": "JIG", "name": "Jig", "quantity": 2}, {"quantity": 3},
         mm.ToolPoolInput),
    ]


def test_crud_etag_if_match_for_every_entity(mfg: Mfg):
    for coll, one, body, change, cls in _cases(mfg):
        r = mfg.req("POST", coll, 201, json=body)
        rec = r.json()
        assert r.headers["ETag"] == '"1"' and r.headers["Location"] == f"{MFG}{one.format(rec['id'])}"
        assert rec["row_version"] == 1 and rec["created_at"].endswith("Z")
        listed = mfg.get(coll)["items"]
        assert rec["id"] in [x["id"] for x in listed], coll
        if "{}" in one and coll in ("/items", "/groups", "/lines", "/shift-templates", "/operators"):
            r = mfg.req("GET", one.format(rec["id"]), 200)
            assert r.headers["ETag"] == '"1"'
        path = one.format(rec["id"])
        new = {**to_input(cls, rec), **change}
        err(mfg.req("PUT", path, json=new), 428, "PRECONDITION_REQUIRED")
        e = err(mfg.req("PUT", path, json=new, headers=etag(7)), 412, "VERSION_MISMATCH")
        assert e["details"] == {"current_version": 1}
        r = mfg.req("PUT", path, 200, json=new, headers={"If-Match": 'W/"1"'})
        assert r.headers["ETag"] == '"2"' and r.json()["row_version"] == 2
        for k, v in change.items():
            assert r.json()[k] == v, (coll, k)
        err(mfg.req("DELETE", path), 428, "PRECONDITION_REQUIRED")
        err(mfg.req("DELETE", path, headers=etag(1)), 412, "VERSION_MISMATCH")
        # unknown / malformed id: 404 before the precondition
        for bad in (f"{rec['id'][:4]}{uuid.uuid4().hex}", "not-an-id", "x" * 80):
            err(mfg.req("PUT", one.format(bad), json=new), 404, "NOT_FOUND")
            err(mfg.req("DELETE", one.format(bad)), 404, "NOT_FOUND")
        mfg.delete(path, 2)
        assert rec["id"] not in [x["id"] for x in mfg.get(coll)["items"]]


def test_reads_insert_nothing_and_plant_if_match_zero(client, mfg: Mfg):
    app = client.app
    for path in ("/plant", "/summary", "/items", "/meta", "/health", "/groups", "/lines", "/shift-templates",
                 "/skills", "/operators", "/tool-pools", "/samples", "/shift-assignments", "/calendar-exceptions"):
        mfg.get(path)
    assert all(v == 0 for v in row_counts(app).values()), row_counts(app)
    r = mfg.req("GET", "/plant", 200)
    assert r.headers["ETag"] == '"0"' and r.json()["id"] is None and r.json()["row_version"] == 0
    body = {"name": "Werk 1", "utc_offset": "+05:30", "planning_horizon_days": 60, "currency": "INR"}
    err(mfg.req("PUT", "/plant", json=body), 428, "PRECONDITION_REQUIRED")
    err(mfg.req("PUT", "/plant", json=body, headers=etag(1)), 412, "VERSION_MISMATCH")
    assert row_counts(app)["mfg_plant"] == 0
    r = mfg.req("PUT", "/plant", 200, json=body, headers=etag(0))
    assert r.json()["row_version"] == 1 and r.json()["id"].startswith("plt_") and r.headers["ETag"] == '"1"'
    assert mfg.get("/plant")["name"] == "Werk 1"
    e = err(mfg.req("PUT", "/plant", json=body, headers=etag(0)), 412, "VERSION_MISMATCH")
    assert e["details"]["current_version"] == 1
    assert mfg.get("/summary")["data_version"] >= 1


def test_duplicate_keys_and_limit_order(mfg: Mfg):
    a = mfg.item("DUP-1")
    e = err(mfg.req("POST", "/items", json={"part_number": "DUP-1", "make_buy": "buy"}), 409, "MFG_DUPLICATE_KEY")
    assert e["details"] == {"key": {"part_number": "DUP-1"}, "existing_id": a["id"]}
    b = mfg.item("DUP-2")
    body = {**to_input(mm.ItemInput, b), "part_number": "DUP-1"}
    err(mfg.req("PUT", f"/items/{b['id']}", json=body, headers=etag(1)), 409, "MFG_DUPLICATE_KEY")
    g = mfg.group("G1")
    err(mfg.req("POST", "/groups", json={"code": "G1", "name": "x"}), 409, "MFG_DUPLICATE_KEY")
    mfg.line("L1", g["id"])
    err(mfg.req("POST", "/lines", json={"code": "L1", "name": "x", "group_id": g["id"]}), 409, "MFG_DUPLICATE_KEY")


def test_entity_limit(mfg: Mfg, monkeypatch):
    monkeypatch.setattr(L, "MAX_SKILLS", 2)
    mfg.post("/skills", {"code": "S1", "name": "a"})
    mfg.post("/skills", {"code": "S2", "name": "a"})
    e = err(mfg.req("POST", "/skills", json={"code": "S3", "name": "a"}), 422, "MFG_LIMIT")
    assert e["details"]["limit"] == 2


def test_unknown_references_are_422(mfg: Mfg):
    ghost = f"wcg_{uuid.uuid4().hex}"
    e = err(mfg.req("POST", "/lines", json={"code": "L", "name": "L", "group_id": ghost}), 422,
            "MFG_UNKNOWN_REFERENCE")
    assert e["details"] == {"loc": ["body", "group_id"], "id": ghost}
    g = mfg.group("G")
    itm = f"itm_{uuid.uuid4().hex}"
    e = err(mfg.req("POST", "/lines", json={"code": "L", "name": "L", "group_id": g["id"],
                                            "eligible_item_ids": [itm]}), 422, "MFG_UNKNOWN_REFERENCE")
    assert e["details"]["loc"] == ["body", "eligible_item_ids", 0]
    err(mfg.req("POST", "/operators", json={"code": "O", "name": "O", "skill_ids": [f"skl_{uuid.uuid4().hex}"]}),
        422, "MFG_UNKNOWN_REFERENCE")
    t = mfg.post("/shift-templates", TEMPLATE)
    e = err(mfg.req("POST", "/shift-assignments", json={
        "shift_template_id": t["id"], "target_type": "group", "group_id": g["id"], "effective_from": "2026-01-01",
        "shift_names": ["Night"]}), 422, "VALIDATION_ERROR")
    assert e["details"]["errors"][0]["loc"] == ["body", "shift_names", 0]
    err(mfg.req("POST", "/lines", json={"code": "L", "name": "L", "group_id": "bad"}), 422, "VALIDATION_ERROR")


def test_shift_template_rules_and_preview(mfg: Mfg):
    bad = {"code": "BAD", "name": "Bad", "shifts": [
        {"name": "A", "days": ["mon"], "start": "06:00", "end": "14:00"},
        {"name": "B", "days": ["mon"], "start": "13:00", "end": "20:00"}]}
    e = err(mfg.req("POST", "/shift-templates", json=bad), 422, "MFG_SHIFT_INVALID")
    assert e["details"]["errors"]
    err(mfg.req("POST", "/shift-templates/preview", json=bad), 422, "MFG_SHIFT_INVALID")
    three = {"code": "3S", "name": "Three", "shifts": [
        {"name": n, "days": ["mon", "tue", "wed", "thu", "fri", "sat"], "start": s, "end": e2,
         "breaks": [{"name": "Meal", "start": b, "end": b2}]}
        for n, s, e2, b, b2 in (("A", "06:00", "14:00", "10:00", "10:30"), ("B", "14:00", "22:00", "18:00", "18:30"),
                                ("C", "22:00", "06:00", "02:00", "02:30"))]}
    p = mfg.post("/shift-templates/preview", three, status=200)
    assert p["total_minutes"] == 8100 and p["minutes_per_day"]["mon"] == 1350 and p["minutes_per_day"]["sun"] == 0
    assert p["week_windows"][0] == {"shift": "A", "day": "mon", "start_minute": 360, "end_minute": 600}
    assert mfg.get("/shift-templates")["items"] == []                        # preview stores nothing


def test_delete_in_use_matrix(mfg: Mfg):
    mfg.load("small")
    item = mfg.by_pn("SM-100")
    child = mfg.by_pn("SM-BPCB-100")
    e = err(mfg.req("DELETE", f"/items/{child['id']}", headers=etag(child["row_version"])), 409, "MFG_IN_USE")
    assert e["details"]["references"] == {"bom_lines": 1}
    e = err(mfg.req("DELETE", f"/items/{item['id']}", headers=etag(item["row_version"])), 409, "MFG_IN_USE")
    assert e["details"]["references"] == {"boms": 1, "routings": 1}
    groups = {g["code"]: g for g in mfg.get("/groups")["items"]}
    smt = groups["SMT"]
    e = err(mfg.req("DELETE", f"/groups/{smt['id']}", headers=etag(smt["row_version"])), 409, "MFG_IN_USE")
    assert e["details"]["references"] == {"lines": 1, "operations": 1}
    tpls = {t["code"]: t for t in mfg.get("/shift-templates")["items"]}
    reg = tpls["REG"]
    assert reg["assignment_count"] > 0 and reg["operator_count"] > 0
    e = err(mfg.req("DELETE", f"/shift-templates/{reg['id']}", headers=etag(1)), 409, "MFG_IN_USE")
    assert set(e["details"]["references"]) == {"shift_assignments", "operators"}
    skills = {s["code"]: s for s in mfg.get("/skills")["items"]}
    assert skills["SMT-OP"]["operator_count"] == 2 and skills["SMT-OP"]["operation_count"] >= 1
    e = err(mfg.req("DELETE", f"/skills/{skills['SMT-OP']['id']}", headers=etag(1)), 409, "MFG_IN_USE")
    assert e["details"]["references"]["operations"] >= 1
    pools = {p["code"]: p for p in mfg.get("/tool-pools")["items"]}
    err(mfg.req("DELETE", f"/tool-pools/{pools['SM-JIG-FCT']['id']}", headers=etag(1)), 409, "MFG_IN_USE")
    # line delete cascades its assignments/exceptions/eligibility; operator delete cascades skill links
    ops = mfg.get("/operators")["items"]
    mfg.delete(f"/operators/{ops[0]['id']}", ops[0]["row_version"])
    lines = {x["code"]: x for x in mfg.get("/lines")["items"]}
    fct = lines["FCT-1"]
    before = len(mfg.get("/shift-assignments")["items"])
    mfg.delete(f"/lines/{fct['id']}", fct["row_version"])
    assert len(mfg.get("/shift-assignments")["items"]) <= before
    # a group whose lines are gone and that no operation uses can be deleted
    g = mfg.group("EMPTY")
    mfg.delete(f"/groups/{g['id']}", 1)


@pytest.mark.parametrize("q", ["%", "_", "\\"])
def test_search_escapes_like_wildcards(mfg: Mfg, q: str):
    mfg.item("PLAIN-1")
    mfg.item(f"ODD{q}1")
    got = [i["part_number"] for i in mfg.get("/items", params={"q": q})["items"]]
    assert got == [f"ODD{q}1"]
    mfg.group("G" + ("1" if q != "_" else "_X"), name="n")
    if q == "_":
        assert [g["code"] for g in mfg.get("/groups", params={"q": "_"})["items"]] == ["G_X"]


def test_items_paging_filters_sort(mfg: Mfg):
    mfg.load("medium")
    page = mfg.get("/items", params={"limit": 50, "offset": 0})
    assert page["limit"] == 50 and page["offset"] == 0 and len(page["items"]) == 50 and page["total"] == 171
    pns = [i["part_number"] for i in page["items"]]
    assert pns == sorted(pns)
    nxt = mfg.get("/items", params={"limit": 50, "offset": 150})
    assert len(nxt["items"]) == 21
    makes = mfg.get("/items", params={"make_buy": "make", "limit": 200})
    assert makes["total"] == len(makes["items"]) and all(i["make_buy"] == "make" for i in makes["items"])
    with_bom = mfg.get("/items", params={"has_bom": True, "limit": 200})["items"]
    assert with_bom and all(i["has_bom"] for i in with_bom)
    no_rtg = mfg.get("/items", params={"has_routing": False, "make_buy": "make", "limit": 200})["items"]
    assert all(not i["has_routing"] for i in no_rtg)
    used = [i for i in mfg.get("/items", params={"limit": 200})["items"] if i["used_in_count"] > 1]
    assert used
    err(mfg.req("GET", "/items", params={"limit": 201}), 422, "VALIDATION_ERROR")
    err(mfg.req("GET", "/items", params={"limit": 0}), 422, "VALIDATION_ERROR")
    desc = mfg.get("/items", params={"sort": "-updated_at", "limit": 5})["items"]
    assert len(desc) == 5


def test_meta_has_every_field(mfg: Mfg, client):
    m = mfg.get("/meta")
    assert set(m) == {"uoms", "enums", "limits", "import_spec", "samples", "health_codes"}
    assert {u["code"] for u in m["uoms"]} >= {"EA", "M", "MM", "ML"}
    assert set(m["enums"]) == {"make_buy", "lot_rule", "status", "run_per", "labor", "assignment_kind",
                               "target_type", "exception_scope", "exception_kind", "weekday"}
    assert m["limits"]["max_body_bytes"] == client.app.state.settings.max_body_bytes
    assert set(L.all_limits()) <= set(m["limits"])
    names = [s["name"] for s in m["import_spec"]["sheets"]]
    assert names[0] == "plant" and "bom_lines" in names
    col = m["import_spec"]["sheets"][1]["columns"][0]
    assert set(col) == {"field", "type", "required_on_create", "key", "enum_values", "synonyms"}
    assert {s["id"] for s in m["samples"]} == {"small", "medium", "kavach"}
    assert len(m["health_codes"]) >= 40


def test_summary_counts_and_end_items(mfg: Mfg):
    mfg.load("small")
    s = mfg.get("/summary")
    assert s["counts"]["items"] == 10 and s["counts"]["make"] == 1 and s["counts"]["bom_lines"] == 9
    assert [i["part_number"] for i in s["end_items"]] == ["SM-100"]
    assert set(s["end_items"][0]) == {"id", "part_number", "revision", "description", "uom", "make_buy", "active"}


def test_group_detail_and_line_records(mfg: Mfg):
    mfg.load("small")
    g = next(x for x in mfg.get("/groups")["items"] if x["code"] == "FCT")
    assert g["line_count"] == 1
    d = mfg.req("GET", f"/groups/{g['id']}", 200)
    body = d.json()
    assert d.headers["ETag"] == f'"{g["row_version"]}"'
    assert [x["code"] for x in body["lines"]] == ["FCT-1"] and body["lines"][0]["group"]["code"] == "FCT"
    assert body["assignments"] and all("template" in a and "target" in a for a in body["assignments"])
    item = mfg.by_pn("SM-100")
    ln = body["lines"][0]
    upd = {**to_input(mm.LineInput, ln), "eligible_item_ids": [item["id"]]}
    rec = mfg.put(f"/lines/{ln['id']}", upd, ln["row_version"])
    assert rec["eligible_item_ids"] == [item["id"]] and rec["eligible_items"][0]["part_number"] == "SM-100"
    rec = mfg.put(f"/lines/{ln['id']}", {**upd, "eligible_item_ids": []}, rec["row_version"])
    assert rec["eligible_items"] == []
    exc = mfg.get("/calendar-exceptions")["items"][0]
    assert exc["start"].endswith("+05:30")
    assert mfg.get("/calendar-exceptions", params={"from": "2030-01-01"})["items"] == []
    sk = mfg.get("/skills")["items"][0]
    holders = mfg.get("/operators", params={"skill_id": sk["id"]})["items"]
    assert holders and all(sk["id"] in o["skill_ids"] for o in holders)
    assert all(o["skills"] and o["shift_template"] for o in holders)
