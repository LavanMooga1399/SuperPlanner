"""Regression tests for the M1 fix round (tester D1, team-lead review F2-F7; M1-DESIGN 17.WP-B "Fix round"). Each
test failed on the code before the fix. F1 (BOM loader) is in tests/mfg_db/test_mfg_repo_bfs.py; the new health
codes are covered by tests/mfg/test_mfg_health.py."""

from __future__ import annotations

import io
import json
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from apimfg_helpers import MFG, Mfg, err, etag, make_app, row_counts

OCTET = {"content-type": "application/octet-stream"}
JSON = {"content-type": "application/json"}


def _zip(sheets: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in sheets.items():
            z.writestr(f"{name}.csv", text)
    return buf.getvalue()


def _preview(m: Mfg, data: bytes, filename: str = "f.zip", sheet: str | None = None) -> tuple[dict, dict]:
    params = {"filename": filename} | ({"sheet": sheet} if sheet else {})
    rec = m.req("POST", "/imports", 201, params=params, content=data, headers=OCTET).json()
    mapping = {"sheets": {s["name"]: s["suggested"] or {"target": None, "columns": {}} for s in rec["sheets"]},
               "options": {}}
    p = m.put(f"/imports/{rec['id']}/mapping", mapping, rec["row_version"])
    return p, p["preview"]


def _commit(m: Mfg, data: bytes, filename: str = "f.zip", sheet: str | None = None) -> dict:
    p, pv = _preview(m, data, filename, sheet)
    assert pv["ok"], pv["row_errors"][:5]
    return m.post(f"/imports/{p['id']}/commit", {}, status=200, headers=etag(p["row_version"]))


def _by_id(m: Mfg, path: str, id_: str) -> dict:
    return next(x for x in m.get(path)["items"] if x["id"] == id_)


# ---------------------------------------------------------------- D1: non-finite numbers


NON_FINITE = ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"]


@pytest.mark.parametrize("value", NON_FINITE)
def test_d1_item_attributes_reject_non_finite_on_create_and_update(mfg: Mfg, value: str):
    r = mfg.req("POST", "/items", content='{"part_number":"J1","make_buy":"buy","lead_time_days":1,'
                                          '"attributes":{"x":%s}}' % value, headers=JSON)
    e = err(r, 422, "VALIDATION_ERROR")
    assert "attributes" in json.dumps(e["details"])
    assert mfg.get("/items")["total"] == 0
    it = mfg.item("J2", attributes={"x": 1.5})
    r = mfg.req("PUT", f"/items/{it['id']}", headers={**JSON, **etag(it["row_version"])},
                content='{"part_number":"J2","make_buy":"buy","lead_time_days":1,"attributes":{"x":%s}}' % value)
    err(r, 422, "VALIDATION_ERROR")
    got = mfg.get(f"/items/{it['id']}")
    assert got["attributes"] == {"x": 1.5} and got["row_version"] == it["row_version"]
    for path in ("/items", "/health", "/summary", "/plant", "/export?format=zip"):
        assert mfg.req("GET", path).status_code == 200, path


@pytest.mark.parametrize("value", NON_FINITE)
def test_d1_plant_attributes_reject_non_finite(mfg: Mfg, value: str):
    r = mfg.req("PUT", "/plant", headers={**JSON, **etag(0)},
                content='{"name":"P","utc_offset":"+05:30","attributes":{"a":%s}}' % value)
    err(r, 422, "VALIDATION_ERROR")
    plant = mfg.get("/plant")
    assert plant["row_version"] == 0 and plant["attributes"] == {}
    p = mfg.put("/plant", {"name": "P", "attributes": {"a": 1}}, 0)
    r = mfg.req("PUT", "/plant", headers={**JSON, **etag(p["row_version"])},
                content='{"name":"P","attributes":{"a":%s}}' % value)
    err(r, 422, "VALIDATION_ERROR")
    assert mfg.get("/plant")["attributes"] == {"a": 1}


def test_d1_attribute_numbers_finite_and_integers_bounded(mfg: Mfg):
    it = mfg.item("K1", attributes={"f": 1e308, "i": 2**53 - 1, "n": -(2**53 - 1), "b": True, "s": "x"})
    assert it["attributes"] == {"f": 1e308, "i": 2**53 - 1, "n": -(2**53 - 1), "b": True, "s": "x"}
    for big in (2**53, -(2**53), 10**400):
        r = mfg.req("POST", "/items", content='{"part_number":"K2","make_buy":"buy","lead_time_days":1,'
                                              '"attributes":{"i":%d}}' % big, headers=JSON)
        err(r, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("field,value", [("qty_per", "NaN"), ("qty_per", "Infinity"), ("scrap_pct", "NaN")])
def test_d1_bounded_floats_of_documents_reject_non_finite(mfg: Mfg, field: str, value: str):
    a, c = mfg.item("A", "make"), mfg.item("C")
    line = {"find_number": "10", "child_item_id": c["id"], "qty_per": 1}
    body = json.dumps({"item_id": a["id"], "lines": [line]}).replace(
        f'"{field}": 1' if field == "qty_per" else '"qty_per": 1',
        f'"{field}": {value}' if field == "qty_per" else f'"qty_per": 1, "{field}": {value}')
    err(mfg.req("POST", "/boms", content=body, headers=JSON), 422, "VALIDATION_ERROR")
    assert row_counts(mfg.c.app)["mfg_boms"] == 0


# ---------------------------------------------------------------- F2: shift names still in use


def _shift_setup(m: Mfg) -> dict:
    g = m.group("G")
    ln = m.line("L1", g["id"])
    t = m.post("/shift-templates", {"code": "T", "name": "T", "shifts": [
        {"name": "Day", "days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "16:00"},
        {"name": "Night", "days": ["mon"], "start": "22:00", "end": "06:00"}]})
    a = m.post("/shift-assignments", {"shift_template_id": t["id"], "target_type": "group", "group_id": g["id"],
                                      "kind": "base", "shift_names": ["Day"], "effective_from": "2026-01-01"})
    o = m.post("/operators", {"code": "OP1", "name": "Op", "shift_template_id": t["id"], "shift_names": ["Night"]})
    return {"g": g, "line": ln, "t": t, "a": a, "o": o}


def _tpl(names: list[str]) -> dict:
    return {"code": "T", "name": "T", "shifts": [
        {"name": n, "days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "16:00"} if i == 0 else
        {"name": n, "days": ["mon"], "start": "22:00", "end": "06:00"} for i, n in enumerate(names)]}


def test_f2_template_rename_or_removal_of_a_used_shift_is_refused(mfg: Mfg):
    x = _shift_setup(mfg)
    t = x["t"]
    before = mfg.get(f"/lines/{x['line']['id']}/windows", params={"from": "2026-11-02", "to": "2026-11-09"})["totals"]
    e = err(mfg.req("PUT", f"/shift-templates/{t['id']}", json=_tpl(["A", "Night"]), headers=etag(t["row_version"])),
            409, "MFG_IN_USE")
    assert e["details"]["references"] == {"shift_assignments": 1}
    assert e["details"]["shift_names"] == ["Day"]
    assert [(u["type"], u["id"], u["shift_names"]) for u in e["details"]["used_by"]] == \
        [("shift_assignment", x["a"]["id"], ["Day"])]
    assert "T on G (base)" in e["message"]
    e = err(mfg.req("PUT", f"/shift-templates/{t['id']}", json=_tpl(["Day"]), headers=etag(t["row_version"])),
            409, "MFG_IN_USE")
    assert e["details"]["references"] == {"operators": 1} and e["details"]["used_by"][0]["label"] == "OP1"
    e = err(mfg.req("PUT", f"/shift-templates/{t['id']}", json=_tpl(["X", "Y"]), headers=etag(t["row_version"])),
            409, "MFG_IN_USE")
    assert e["details"]["references"] == {"shift_assignments": 1, "operators": 1}
    assert e["details"]["shift_names"] == ["Day", "Night"]
    assert mfg.get(f"/shift-templates/{t['id']}")["row_version"] == t["row_version"]
    assert mfg.get(f"/lines/{x['line']['id']}/windows",
                   params={"from": "2026-11-02", "to": "2026-11-09"})["totals"] == before
    # an unused shift may be removed; after moving the users the rename is allowed
    mfg.put(f"/operators/{x['o']['id']}", {"code": "OP1", "name": "Op", "shift_template_id": t["id"],
                                           "shift_names": []}, x["o"]["row_version"])
    t2 = mfg.put(f"/shift-templates/{t['id']}", _tpl(["Day"]), t["row_version"])
    assert [s["name"] for s in t2["shifts"]] == ["Day"]
    a = x["a"]
    body = {k: a[k] for k in ("shift_template_id", "target_type", "group_id", "line_id", "kind", "effective_from",
                              "effective_to", "cost_per_hour", "max_hours_per_week", "note")}
    mfg.put(f"/shift-assignments/{a['id']}", {**body, "shift_names": []}, a["row_version"])
    t3 = mfg.put(f"/shift-templates/{t['id']}", _tpl(["A"]), t2["row_version"])
    assert [s["name"] for s in t3["shifts"]] == ["A"]
    assert "MFG_ASSIGNMENT_UNKNOWN_SHIFT" not in mfg.get("/health")["by_code"]


SHIFTS_RENAMED = "template_code,shift_name,days,start,end\nT,A,mon;tue;wed;thu;fri,08:00,16:00\n" \
                 "T,Night,mon,22:00,06:00\n"


def test_f2_import_rename_of_a_used_shift_is_a_row_error(mfg: Mfg):
    x = _shift_setup(mfg)
    data = _zip({"shift_templates": "code,name\nT,T\n", "shifts": SHIFTS_RENAMED})
    _, pv = _preview(mfg, data)
    errs = [(e["sheet"], e["code"]) for e in pv["row_errors"]]
    assert errs == [("shift_templates", "IMP_IN_USE")], pv["row_errors"]
    assert "assignment on G (base)" in pv["row_errors"][0]["message"]
    # shifts sheet alone (no header row): the error lands on the first shift row
    _, pv = _preview(mfg, _zip({"shifts": SHIFTS_RENAMED}))
    assert [(e["sheet"], e["code"]) for e in pv["row_errors"]] == [("shifts", "IMP_IN_USE")]
    # renaming together with the assignment in the same file is fine
    asg = "template_code,target_type,target_code,kind,effective_from,shift_names\nT,group,G,base,2026-01-01,A\n"
    _commit(mfg, _zip({"shift_templates": "code,name\nT,T\n", "shifts": SHIFTS_RENAMED, "shift_assignments": asg}))
    assert _by_id(mfg, "/shift-assignments", x["a"]["id"])["shift_names"] == ["A"]
    assert not {"MFG_ASSIGNMENT_UNKNOWN_SHIFT", "MFG_OPERATOR_UNKNOWN_SHIFT"} & set(mfg.get("/health")["by_code"])


# ---------------------------------------------------------------- F3: copy of an obsolete BOM


def test_f3_copy_of_an_obsolete_bom_runs_the_cycle_check(mfg: Mfg):
    a, b = mfg.item("A", "make"), mfg.item("B", "make")
    ba = mfg.post("/boms", {"item_id": a["id"], "lines": [{"find_number": "10", "child_item_id": b["id"],
                                                           "qty_per": 1}]})
    r = mfg.post(f"/boms/{ba['id']}/release", {}, status=200, headers=etag(1))
    o = mfg.post(f"/boms/{ba['id']}/obsolete", {}, status=200, headers=etag(r["bom"]["row_version"]))
    mfg.post("/boms", {"item_id": b["id"], "lines": [{"find_number": "10", "child_item_id": a["id"], "qty_per": 1}]})
    n = row_counts(mfg.c.app)["mfg_boms"]
    e = err(mfg.req("POST", f"/boms/{ba['id']}/copy", json={}, headers=etag(o["row_version"])), 422, "MFG_BOM_CYCLE")
    assert e["details"]["cycle"] in (["A", "B", "A"], ["B", "A", "B"])
    assert row_counts(mfg.c.app)["mfg_boms"] == n
    assert "MFG_BOM_CYCLE" not in mfg.get("/health")["by_code"]


def test_f3_copy_without_a_cycle_still_works(mfg: Mfg):
    a, b = mfg.item("A", "make"), mfg.item("B")
    ba = mfg.post("/boms", {"item_id": a["id"], "lines": [{"find_number": "10", "child_item_id": b["id"],
                                                           "qty_per": 1}]})
    r = mfg.post(f"/boms/{ba['id']}/release", {}, status=200, headers=etag(1))
    o = mfg.post(f"/boms/{ba['id']}/obsolete", {}, status=200, headers=etag(r["bom"]["row_version"]))
    r = mfg.req("POST", f"/boms/{ba['id']}/copy", json={}, headers=etag(o["row_version"]))
    assert r.status_code in (200, 201), r.text
    assert r.json()["status"] == "draft" and r.json()["version"] == 2


# ---------------------------------------------------------------- F4: concurrent first-time PUT /plant


def test_f4_concurrent_first_plant_puts_do_not_both_succeed(db_url: str):
    with TestClient(make_app(db_url)) as c:
        m = Mfg(c)
        for trial in range(4):
            if trial:
                m.post("/reset", {"confirm": "DELETE ALL MANUFACTURING DATA"}, status=200)
            bar = threading.Barrier(2)
            out: list[tuple[str, int]] = []

            def go(name: str) -> None:
                bar.wait()
                r = c.put(MFG + "/plant", json={"name": name}, headers={"If-Match": '"0"'})
                out.append((name, r.status_code))

            ts = [threading.Thread(target=go, args=(f"P{i}",)) for i in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            codes = sorted(code for _n, code in out)
            assert codes in ([200, 412], [200, 503], [200, 409]), out
            winner = next(n for n, code in out if code == 200)
            plant = m.get("/plant")
            assert plant["name"] == winner and plant["row_version"] == 1


def test_f4_if_match_zero_after_an_implicit_create_is_412(mfg: Mfg):
    mfg.item("A")                                     # creates the plant row implicitly (row_version 1)
    err(mfg.req("PUT", "/plant", json={"name": "P"}, headers=etag(0)), 412, "VERSION_MISMATCH")
    assert mfg.put("/plant", {"name": "P"}, 1)["row_version"] == 2


# ---------------------------------------------------------------- F5: serialized flag vs serial documents


def test_f5_item_cannot_stop_being_serialized_while_documents_use_serials(mfg: Mfg):
    a, c = mfg.item("A", "make", serialized=True), mfg.item("C")
    g = mfg.group("G")
    b = mfg.post("/boms", {"item_id": a["id"], "serial_from": 1, "serial_to": 99,
                           "lines": [{"find_number": "10", "child_item_id": c["id"], "qty_per": 1}]})
    rt = mfg.post("/routings", {"item_id": a["id"], "serial_from": 100, "serial_to": 199,
                                "operations": [{"seq": 10, "name": "Op", "group_id": g["id"]}]})
    body = {"part_number": "A", "make_buy": "make", "serialized": False}
    e = err(mfg.req("PUT", f"/items/{a['id']}", json=body, headers=etag(a["row_version"])), 409, "MFG_IN_USE")
    assert e["details"]["references"] == {"boms": 1, "routings": 1}
    assert {u["id"] for u in e["details"]["used_by"]} == {b["id"], rt["id"]}
    assert mfg.get(f"/items/{a['id']}")["serialized"] is True
    # import path: the same change is a row error
    _, pv = _preview(mfg, b"part_number,make_buy,serialized\nA,make,false\n", "items.csv", "items")
    assert [(e["column"], e["code"]) for e in pv["row_errors"]] == [("serialized", "IMP_IN_USE")]
    # other edits keep working; once the ranges are gone the flag may be cleared
    mfg.put(f"/items/{a['id']}", {**body, "serialized": True, "description": "x"}, a["row_version"])
    mfg.delete(f"/boms/{b['id']}", b["row_version"])
    mfg.delete(f"/routings/{rt['id']}", rt["row_version"])
    assert mfg.put(f"/items/{a['id']}", body, a["row_version"] + 1)["serialized"] is False


# ---------------------------------------------------------------- F6: date bounds


@pytest.mark.parametrize("start,end", [("9999-12-31T20:00:00-05:00", "9999-12-31T23:00:00-05:00"),
                                       ("0001-01-01T00:00:00+05:00", "0001-01-01T03:00:00+05:00"),
                                       ("2199-12-31T20:00:00-05:00", "2199-12-31T23:00:00-05:00"),
                                       ("1899-12-31T23:00:00+00:00", "1900-01-01T03:00:00+00:00")])
def test_f6_exception_datetimes_out_of_range_are_422(mfg: Mfg, start: str, end: str):
    r = mfg.req("POST", "/calendar-exceptions", json={"scope": "plant", "kind": "holiday", "start": start, "end": end})
    err(r, 422, "VALIDATION_ERROR")
    assert mfg.get("/calendar-exceptions")["items"] == []


def test_f6_query_and_body_dates_are_bounded(mfg: Mfg):
    g = mfg.group("G")
    ln = mfg.line("L1", g["id"])
    a, c = mfg.item("A", "make"), mfg.item("C")
    bad = ["9999-12-31", "0001-01-01", "1899-12-31", "2200-01-01"]
    for d in bad:
        err(mfg.req("GET", "/health", params={"as_of": d}), 422, "VALIDATION_ERROR")
        err(mfg.req("GET", f"/lines/{ln['id']}/windows", params={"from": d, "to": d}), 422, "VALIDATION_ERROR")
        err(mfg.req("GET", f"/items/{a['id']}/explosion", params={"on": d}), 422, "VALIDATION_ERROR")
        err(mfg.req("GET", f"/items/{c['id']}/where-used", params={"on": d}), 422, "VALIDATION_ERROR")
        err(mfg.req("GET", "/calendar-exceptions", params={"from": d}), 422, "VALIDATION_ERROR")
        err(mfg.req("GET", "/calendar-exceptions", params={"to": d}), 422, "VALIDATION_ERROR")
        line = [{"find_number": "1", "child_item_id": c["id"], "qty_per": 1}]
        err(mfg.req("POST", "/boms", json={"item_id": a["id"], "effective_from": d, "lines": line}), 422,
            "VALIDATION_ERROR")
        err(mfg.req("POST", "/boms", json={"item_id": a["id"], "effective_to": d, "lines": line}), 422,
            "VALIDATION_ERROR")
        err(mfg.req("POST", "/routings", json={"item_id": a["id"], "effective_from": d}), 422, "VALIDATION_ERROR")
    t = mfg.post("/shift-templates", {"code": "T", "name": "T", "shifts": [
        {"name": "Day", "days": ["mon"], "start": "08:00", "end": "16:00"}]})
    for d in bad:
        err(mfg.req("POST", "/shift-assignments", json={"shift_template_id": t["id"], "target_type": "group",
                                                        "group_id": g["id"], "effective_from": d}),
            422, "VALIDATION_ERROR")
    assert row_counts(mfg.c.app)["mfg_boms"] == 0 and row_counts(mfg.c.app)["mfg_shift_assignments"] == 0
    # the edges of the range work end to end
    mfg.post("/shift-assignments", {"shift_template_id": t["id"], "target_type": "group", "group_id": g["id"],
                                    "effective_from": "1900-01-01"})
    mfg.post("/calendar-exceptions", {"scope": "plant", "kind": "holiday", "start": "2199-12-30T00:00:00+00:00",
                                      "end": "2199-12-31T23:59:00+00:00"})
    b = mfg.post("/boms", {"item_id": a["id"], "effective_from": "2199-12-30", "effective_to": "2199-12-31",
                           "lines": [{"find_number": "1", "child_item_id": c["id"], "qty_per": 1}]})
    mfg.post(f"/boms/{b['id']}/release", {}, status=200, headers=etag(1))
    assert mfg.get("/health", params={"as_of": "2199-12-31", "horizon_days": 730})["as_of"] == "2199-12-31"
    assert mfg.get("/health", params={"as_of": "1900-01-01"})["as_of"] == "1900-01-01"
    w = mfg.get(f"/lines/{ln['id']}/windows", params={"from": "2199-12-25", "to": "2199-12-31"})
    assert w["windows"] == [] or all(x["start"] < x["end"] for x in w["windows"])
    mfg.get(f"/lines/{ln['id']}/windows", params={"from": "1900-01-01", "to": "1900-01-08"})
    assert mfg.get(f"/items/{a['id']}/explosion", params={"on": "2199-12-30"})["totals"]["rows"] == 2
    assert len(mfg.get("/calendar-exceptions", params={"from": "2199-12-31"})["items"]) == 1


def test_f6_import_dates_out_of_range_are_row_errors(mfg: Mfg):
    data = (b"scope,target_code,kind,start,end,label\nplant,,holiday,9999-12-31,9999-12-31,x\n"
            b"plant,,holiday,0001-01-01 00:00,0001-01-01 05:00,y\nplant,,holiday,2026-12-25,2026-12-25,ok\n"
            b"plant,,holiday,9999-12-31T20:00:00-05:00,9999-12-31T23:00:00-05:00,z\n")
    _, pv = _preview(mfg, data, "calendar_exceptions.csv", "calendar_exceptions")
    assert sorted((e["row"], e["code"]) for e in pv["row_errors"]) == \
        [(2, "IMP_BAD_DATE"), (3, "IMP_BAD_DATE"), (5, "IMP_BAD_DATE")], pv["row_errors"]
    mfg.item("A", "make")
    _, pv = _preview(mfg, b"parent_part_number,version,effective_from\nA,1,9999-01-01\n", "boms.csv", "boms")
    assert [e["row"] for e in pv["row_errors"]] == [2] and pv["row_errors"][0]["column"] == "effective_from"


# ---------------------------------------------------------------- F7: plant offset change keeps local times


def _offset_setup(m: Mfg) -> dict:
    p = m.put("/plant", {"name": "P", "utc_offset": "+05:30"}, 0)
    g = m.group("G")
    ln = m.line("L1", g["id"])
    t = m.post("/shift-templates", {"code": "T", "name": "T", "shifts": [
        {"name": "Day", "days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "16:00"}]})
    m.post("/shift-assignments", {"shift_template_id": t["id"], "target_type": "group", "group_id": g["id"],
                                  "kind": "base", "effective_from": "2026-01-01"})
    x = m.post("/calendar-exceptions", {"scope": "plant", "kind": "holiday", "start": "2026-12-25T00:00:00+05:30",
                                        "end": "2026-12-26T00:00:00+05:30", "label": "Xmas"})
    return {"plant": p, "line": ln, "exc": x}


def _windows(m: Mfg, line_id: str) -> list[tuple[str, str]]:
    w = m.get(f"/lines/{line_id}/windows", params={"from": "2026-12-24", "to": "2026-12-27"})
    return [(x["start"][:16], x["end"][:16]) for x in w["windows"]]


def test_f7_offset_change_keeps_exception_wall_clock(mfg: Mfg):
    x = _offset_setup(mfg)
    assert _windows(mfg, x["line"]["id"]) == [("2026-12-24T08:00", "2026-12-24T16:00")]
    mfg.put("/plant", {"name": "P", "utc_offset": "-08:00"}, x["plant"]["row_version"])
    assert _windows(mfg, x["line"]["id"]) == [("2026-12-24T08:00", "2026-12-24T16:00")]
    e = _by_id(mfg, "/calendar-exceptions", x["exc"]["id"])
    assert (e["start"], e["end"]) == ("2026-12-25T00:00:00-08:00", "2026-12-26T00:00:00-08:00")
    assert e["row_version"] == x["exc"]["row_version"] + 1
    # an unchanged offset leaves exceptions alone
    mfg.put("/plant", {"name": "Q", "utc_offset": "-08:00"}, x["plant"]["row_version"] + 1)
    assert _by_id(mfg, "/calendar-exceptions", x["exc"]["id"])["row_version"] == e["row_version"]


def test_f7_import_offset_change_keeps_exception_wall_clock(mfg: Mfg):
    x = _offset_setup(mfg)
    _commit(mfg, b"name,utc_offset\nP,+00:00\n", "plant.csv", "plant")
    e = _by_id(mfg, "/calendar-exceptions", x["exc"]["id"])
    assert (e["start"], e["end"]) == ("2026-12-25T00:00:00Z", "2026-12-26T00:00:00Z")
    assert _windows(mfg, x["line"]["id"]) == [("2026-12-24T08:00", "2026-12-24T16:00")]
    # the file changes the offset back and lists the same holiday in local time: no duplicate, still one row
    data = _zip({"plant": "name,utc_offset\nP,+05:30\n",
                 "calendar_exceptions": "scope,target_code,kind,start,end,label\n"
                                        "plant,,holiday,2026-12-25 00:00,2026-12-26 00:00,Xmas\n"})
    p, pv = _preview(mfg, data)
    assert pv["ok"] and pv["counts"]["calendar_exceptions"]["create"] == 0, pv
    assert "IMP_EXCEPTIONS_REBASED" in {w["code"] for w in pv["warnings"]}
    mfg.post(f"/imports/{p['id']}/commit", {}, status=200, headers=etag(p["row_version"]))
    items = mfg.get("/calendar-exceptions")["items"]
    assert [(i["start"], i["end"]) for i in items] == [("2026-12-25T00:00:00+05:30", "2026-12-26T00:00:00+05:30")]
    assert _windows(mfg, x["line"]["id"]) == [("2026-12-24T08:00", "2026-12-24T16:00")]
