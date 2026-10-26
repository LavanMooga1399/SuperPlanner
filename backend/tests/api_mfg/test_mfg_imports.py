"""B3: import flow (xlsx, csv, zip), atomicity, round trip, file headers and body limits, export, templates
(M1-DESIGN 8, 9.3 #68-74; PLAN-M1 B3-2, B3-3, B3-4, B3-6)."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apimfg_helpers import MFG, Mfg, err, etag, make_app, row_counts
from superplanner.api.db.ownership import system_scope
from superplanner.api.mfg import writer
from superplanner.api.mfg.db_models import MfgImportRow, MfgItemRow
from superplanner.mfg.io import export, read
from superplanner.mfg.io.mapping import apply_mapping

OCTET = {"content-type": "application/octet-stream"}


def upload(m: Mfg, data: bytes, filename: str = "f.csv", sheet: str | None = None, status: int = 201) -> dict:
    params = {"filename": filename} | ({"sheet": sheet} if sheet else {})
    r = m.req("POST", "/imports", status, params=params, content=data, headers=OCTET)
    return r.json()


def suggested(rec: dict, **options) -> dict:
    return {"sheets": {s["name"]: s["suggested"] or {"target": None, "columns": {}} for s in rec["sheets"]},
            "options": options}


def map_and_commit(m: Mfg, rec: dict, **options) -> dict:
    p = m.put(f"/imports/{rec['id']}/mapping", suggested(rec, **options), rec["row_version"])
    assert p["preview"]["ok"], p["preview"]["row_errors"][:5]
    return m.post(f"/imports/{rec['id']}/commit", {}, status=200, headers=etag(p["row_version"]))


def test_csv_flow_errors_then_fixed_then_reimport_unchanged(mfg: Mfg):
    bad = b"part_number,make_buy,lead_time_days\nA-1,buy,5\nA-2,bogus,5\nA-3,buy,1,000\n"
    rec = upload(mfg, bad, "items.csv", sheet="items")
    assert rec["status"] == "uploaded" and rec["format"] == "csv" and rec["sheets"][0]["name"] == "items"
    assert rec["sheets"][0]["suggested"]["target"] == "items" and len(rec["sheets"][0]["sample_rows"]) == 3
    r = mfg.req("GET", f"/imports/{rec['id']}", 200)
    assert r.headers["ETag"] == '"1"'
    err(mfg.req("POST", f"/imports/{rec['id']}/commit", json={}, headers=etag(1)), 409, "MFG_IMPORT_NOT_MAPPED")
    err(mfg.req("PUT", f"/imports/{rec['id']}/mapping", json=suggested(rec)), 428, "PRECONDITION_REQUIRED")
    p = mfg.put(f"/imports/{rec['id']}/mapping", suggested(rec), 1)
    pv = p["preview"]
    assert p["status"] == "mapped" and p["row_version"] == 2 and not pv["ok"]
    assert {(e["row"], e["column"], e["code"]) for e in pv["row_errors"]} == {(3, "make_buy", "IMP_BAD_ENUM")}
    assert pv["error_count"] == 1
    assert pv["counts"]["items"]["create"] == 2 and pv["counts"]["items"]["error"] == 1
    e = err(mfg.req("POST", f"/imports/{rec['id']}/commit", json={}, headers=etag(2)), 409, "MFG_IMPORT_HAS_ERRORS")
    assert e["details"]["error_count"] == 1
    err(mfg.req("POST", f"/imports/{rec['id']}/commit", json={}, headers=etag(1)), 412, "VERSION_MISMATCH")
    # mapping two columns to one field -> 422
    two = {"sheets": {"items": {"target": "items", "columns": {"part_number": "part_number",
                                                              "make_buy": "part_number"}}}, "options": {}}
    err(mfg.req("PUT", f"/imports/{rec['id']}/mapping", json=two, headers=etag(2)), 422, "VALIDATION_ERROR")
    good = b"part_number,make_buy,lead_time_days\nA-1,buy,5\nA-2,buy,5\n"
    rec = upload(mfg, good, "items.csv", sheet="items")
    done = map_and_commit(mfg, rec)
    assert done["status"] == "committed" and done["committed_at"] and done["result"]["counts"]["items"]["create"] == 2
    assert done["sheets"][0]["row_count"] == 2 and done["sheets"][0]["headers"]
    with system_scope(), mfg.c.app.state.ctx.db.read() as s:
        staged = s.get(MfgImportRow, rec["id"]).sheets
        assert staged[0]["rows"] == []
    e = err(mfg.req("POST", f"/imports/{rec['id']}/commit", json={}, headers=etag(done["row_version"])), 409,
            "MFG_IMPORT_ALREADY_COMMITTED")
    assert e["details"]["result"]["counts"]["items"]["create"] == 2
    err(mfg.req("PUT", f"/imports/{rec['id']}/mapping", json=suggested(rec), headers=etag(done["row_version"])),
        409, "MFG_IMPORT_ALREADY_COMMITTED")
    versions = {i["part_number"]: i["row_version"] for i in mfg.get("/items")["items"]}
    dv = mfg.get("/summary")["data_version"]
    again = map_and_commit(mfg, upload(mfg, good, "items.csv", sheet="items"))
    assert again["result"]["counts"]["items"] == {"create": 0, "update": 0, "unchanged": 2, "delete": 0}
    assert {i["part_number"]: i["row_version"] for i in mfg.get("/items")["items"]} == versions
    assert mfg.get("/summary")["data_version"] == dv
    mfg.delete(f"/imports/{rec['id']}")
    err(mfg.req("GET", f"/imports/{rec['id']}"), 404, "NOT_FOUND")


def test_expired_session_is_404(mfg: Mfg):
    rec = upload(mfg, b"part_number,make_buy\nX,buy\n", "x.csv", sheet="items")
    with system_scope(), mfg.c.app.state.ctx.db.write() as s:
        s.get(MfgImportRow, rec["id"]).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    err(mfg.req("GET", f"/imports/{rec['id']}"), 404, "NOT_FOUND")
    err(mfg.req("PUT", f"/imports/{rec['id']}/mapping", json=suggested(rec), headers=etag(1)), 404, "NOT_FOUND")
    err(mfg.req("POST", f"/imports/{rec['id']}/commit", json={}, headers=etag(1)), 404, "NOT_FOUND")
    upload(mfg, b"part_number,make_buy\nY,buy\n", "y.csv", sheet="items")         # prunes the expired one
    with system_scope(), mfg.c.app.state.ctx.db.read() as s:
        assert s.get(MfgImportRow, rec["id"]) is None


def test_open_sessions_are_capped(mfg: Mfg):
    ids = [upload(mfg, b"part_number,make_buy\nX,buy\n", "x.csv", sheet="items")["id"] for _ in range(7)]
    with system_scope(), mfg.c.app.state.ctx.db.read() as s:
        from sqlalchemy import select

        left = set(s.execute(select(MfgImportRow.id)).scalars())
    assert left == set(ids[-5:])


def test_xlsx_and_zip_flows_with_documents(mfg: Mfg):
    data = export.bundle_to_xlsx(__import__("superplanner.mfg.samples", fromlist=["build"]).build("small"))
    rec = upload(mfg, data, "small.xlsx")
    assert rec["format"] == "xlsx" and {s["name"] for s in rec["sheets"]} >= {"items", "bom_lines", "README"}
    done = map_and_commit(mfg, rec)
    assert done["result"]["counts"]["bom_lines"]["create"] == 9
    assert mfg.get("/health", params={"as_of": "2026-11-02"})["ok"] is True
    zipped = mfg.req("GET", "/export", 200, params={"format": "zip"}).content
    rec = upload(mfg, zipped, "small.zip")
    assert rec["format"] == "zip"
    p = mfg.put(f"/imports/{rec['id']}/mapping", suggested(rec), 1)
    assert p["preview"]["ok"] and all(c["create"] == c["update"] == c["delete"] == 0
                                      for c in p["preview"]["counts"].values())
    # a released BOM cannot be changed by an import
    z = zipfile.ZipFile(io.BytesIO(zipped))
    lines = z.read("bom_lines.csv").decode("utf-8-sig").replace(",1.0,EA,", ",2.0,EA,", 1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        out.writestr("bom_lines.csv", lines)
    rec = upload(mfg, buf.getvalue(), "lines.zip")
    p = mfg.put(f"/imports/{rec['id']}/mapping", suggested(rec), 1)
    assert [e["code"] for e in p["preview"]["row_errors"]] == ["IMP_RELEASED_READONLY"]


def test_commit_is_atomic(client, monkeypatch):
    from superplanner.mfg import samples

    mfg = Mfg(TestClient(client.app, raise_server_exceptions=False))
    data = export.bundle_to_csv_zip(samples.build("medium"))
    rec = upload(mfg, data, "m.zip")
    p = mfg.put(f"/imports/{rec['id']}/mapping", suggested(rec), 1)
    calls: list[str] = []

    def boom(table: str) -> None:
        calls.append(table)
        if table == "lines":
            raise RuntimeError("injected fault")

    monkeypatch.setattr(writer, "FAULT_HOOK", boom)
    r = mfg.req("POST", f"/imports/{rec['id']}/commit", json={}, headers=etag(p["row_version"]))
    assert r.status_code == 500 and "items" in calls
    counts = row_counts(client.app)
    assert {k: v for k, v in counts.items() if k != "mfg_imports" and v} == {}
    assert mfg.get(f"/imports/{rec['id']}")["status"] == "mapped"
    monkeypatch.setattr(writer, "FAULT_HOOK", None)
    done = mfg.post(f"/imports/{rec['id']}/commit", {}, status=200, headers=etag(p["row_version"]))
    assert done["status"] == "committed"


def test_round_trip_kavach_into_second_owner(db_url_factory):
    from superplanner.mfg import samples

    a_app, b_app = make_app(db_url_factory("apimfg_a")), make_app(db_url_factory("apimfg_b"))
    with TestClient(a_app) as ca, TestClient(b_app) as cb:
        a, b = Mfg(ca), Mfg(cb)
        a.load("kavach")
        # include a draft and an obsolete document
        item = a.by_pn("KV-PCB-LED")
        bom = a.get(f"/items/{item['id']}/boms")["items"][0]
        a.post(f"/boms/{bom['id']}/copy", {}, headers=etag(bom["row_version"]))
        rt = a.get(f"/items/{item['id']}/routings")["items"][0]
        cp = a.post(f"/routings/{rt['id']}/copy", {"code": "OLD"}, headers=etag(rt["row_version"]))
        cp = a.post(f"/routings/{cp['id']}/release", {"effective_from": "2030-01-01", "supersede_previous": True},
                    status=200, headers=etag(1))["routing"]
        a.post(f"/routings/{cp['id']}/obsolete", {}, status=200, headers=etag(cp["row_version"]))
        zipped = a.req("GET", "/export", 200, params={"format": "zip"}).content
        xl = a.req("GET", "/export", 200, params={"format": "xlsx"}).content
        map_and_commit(b, upload(b, xl, "kv.xlsx"))
        assert b.req("GET", "/export", 200, params={"format": "zip"}).content == zipped
        # parsed xlsx bundles equal as well
        def parsed(data: bytes) -> dict:
            raw = read.read_upload(data)
            m = {"sheets": {s["name"]: {"target": s["name"], "columns": {h: h for h in s["headers"]}}
                            for s in raw.sheets if s["name"] != "README"}}
            return apply_mapping(raw.sheets, m)[0]
        assert parsed(b.req("GET", "/export", 200, params={"format": "xlsx"}).content) == parsed(xl)
        top_a, top_b = a.by_pn("KV-TPU-1000"), b.by_pn("KV-TPU-1000")
        ea = a.get(f"/items/{top_a['id']}/explosion", params={"on": "2026-11-02"})
        eb = b.get(f"/items/{top_b['id']}/explosion", params={"on": "2026-11-02"})
        strip = lambda rows: [(r["part_number"], r["level"], r["extended_qty"]) for r in rows]  # noqa: E731
        assert strip(ea["rows"]) == strip(eb["rows"])
        assert samples


def test_headers_body_types_and_limits(db_url_factory):
    app = make_app(db_url_factory("apimfg"), max_body_bytes=200_000)
    with TestClient(app) as c:
        m = Mfg(c)
        m.put("/plant", {"name": 'Werk "Süd" 東京 X', "utc_offset": "+01:00"}, 0)
        r = m.req("GET", "/export", 200, params={"format": "xlsx"})
        cd = r.headers["content-disposition"]
        cd.encode("latin-1")
        assert cd.startswith('attachment; filename="superplanner-mfg-Werk-S-d-X-') and cd.endswith('.xlsx"')
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
        data = export.bundle_to_xlsx(export.template_bundle())
        r = m.req("POST", "/imports", params={"filename": "t.xlsx"}, content=data,
                  headers={"content-type": "application/json"})
        assert r.status_code in (413, 422) and r.status_code != 201
        if r.status_code == 422:
            assert "NUL" in r.text or r.json()["error"]["code"] in ("VALIDATION_ERROR", "MFG_IMPORT_FILE_INVALID")
        upload(m, data, "t.xlsx")
        r = m.req("POST", "/imports", params={"filename": "big.csv"}, content=b"x" * 300_000, headers=OCTET)
        err(r, 413, "PAYLOAD_TOO_LARGE")
        err(m.req("POST", "/imports", params={"filename": "a.xls"}, content=b"\xd0\xcf\x11\xe0" + b"\0" * 64,
                  headers=OCTET), 422, "MFG_IMPORT_FILE_INVALID")
        e = err(m.req("POST", "/imports", params={"filename": "e.csv"}, content=b"", headers=OCTET), 422,
                "MFG_IMPORT_FILE_INVALID")
        assert e["details"]["reason"]
        err(m.req("POST", "/imports", content=b"a,b\n", headers=OCTET), 422, "VALIDATION_ERROR")
        r = m.req("GET", "/import-templates", 200, params={"format": "zip"})
        assert r.headers["content-disposition"] == 'attachment; filename="superplanner-mfg-template.zip"'
        assert zipfile.ZipFile(io.BytesIO(r.content)).namelist()[0] == "plant.csv"
        err(m.req("GET", "/export", params={"format": "pdf"}), 422, "VALIDATION_ERROR")


def test_json_content_type_binary_body_hits_the_middleware(mfg: Mfg):
    nul_body = b"PK\x03\x04\x00\x00binary"
    r = mfg.req("POST", "/imports", params={"filename": "x.xlsx"}, content=nul_body,
                headers={"content-type": "application/json"})
    err(r, 422, "VALIDATION_ERROR")
    assert "NUL" in r.json()["error"]["message"]
    r = mfg.req("POST", "/imports", params={"filename": "x.xlsx"}, content=nul_body, headers=OCTET)
    err(r, 422, "MFG_IMPORT_FILE_INVALID")


def test_staged_size_limit(mfg: Mfg, monkeypatch):
    from superplanner.mfg import limits as L

    monkeypatch.setattr(L, "IMPORT_MAX_STAGED_BYTES", 100)
    e = err(mfg.req("POST", "/imports", params={"filename": "x.csv", "sheet": "items"},
                    content=b"part_number,make_buy\n" + b"ABCDEFGHIJ,buy\n" * 20, headers=OCTET), 422,
            "MFG_IMPORT_TOO_LARGE")
    assert e["details"]["limit"] == "IMPORT_MAX_STAGED_BYTES"


@pytest.mark.parametrize("fmt", ["xlsx", "zip"])
def test_template_downloads(mfg: Mfg, fmt: str):
    r = mfg.req("GET", "/import-templates", 200, params={"format": fmt})
    rec = upload(mfg, r.content, f"t.{fmt}")
    assert {s["name"] for s in rec["sheets"]} >= {"items", "boms"}
    with system_scope(), mfg.c.app.state.ctx.db.read() as s:
        from sqlalchemy import func, select

        assert s.execute(select(func.count()).select_from(MfgItemRow)).scalar() == 0
    assert MFG
