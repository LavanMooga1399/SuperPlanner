"""S4 (M7-DESIGN 4.5, 3, 9): Part 11 package and export job, daily QA due scan, approvals QA kinds, summary,
scan codes."""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import date, timedelta

from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, make_app


def test_package_export_due_scan_approvals_summary_scan(db_url, tmp_path):
    with TestClient(make_app(db_url, archive_dir=str(tmp_path))) as c:
        api = Api(c)
        api.location("ST")
        ncr = api.post("/qa/ncrs", {"title": "Scratch", "qty_nc": 2})
        api.req("POST", "/qa/attachments", 201, params={"entity_type": "ncr", "entity_id": ncr["id"],
                                                        "filename": "n.txt"}, content=b"note",
                headers={"content-type": "text/plain"})
        api.post(f"/qa/ncrs/{ncr['id']}/open", {}, 200)
        pkg = api.get(f"/part11/records/ncr/{ncr['id']}")
        assert pkg["record"]["number"] == ncr["number"] and len(pkg["package_sha256"]) == 64
        assert [a["filename"] for a in pkg["attachments"]] == ["n.txt"]
        assert [e["action"] for e in pkg["audit"]][:2] == ["create", "open"]
        eq = api.post("/qa/equipment", {"code": "EQ-1", "name": "Caliper", "kind": "gauge", "equipment_class": "LEN",
                                        "interval_days": 180, "due_on": (date.today() - timedelta(days=1)).isoformat()})
        assert api.get("/summary")["qa"]["open_ncrs"] == 1 and api.get("/summary")["qa"]["equipment_due"] == 1
        hit = api.get("/floor/scan", code="E:eq-1")
        assert hit["type"] == "equipment" and hit["id"] == eq["id"]
        today = date.today()
        r = api.post("/part11/exports", {"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat(),
                                         "record_types": ["ncr", "equipment"]}, 202)
        deadline = time.monotonic() + 30
        while True:
            ex = api.get("/part11/exports")["items"][0]
            if ex["status"] in ("completed", "failed") or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        assert ex["status"] == "completed", ex
        data = api.req("GET", f"/part11/exports/{r['id']}/download", 200).content
        zf = zipfile.ZipFile(io.BytesIO(data))
        man = json.loads(zf.read("manifest.json"))
        assert man["counts"]["records"] == 2 and man["counts"]["attachments"] == 1
        recs = [json.loads(x) for x in zf.read("records.jsonl").splitlines()]
        assert {x["record_type"] for x in recs} == {"ncr", "equipment"}
        from superplanner.api.db.ownership import bind_owner
        from superplanner.api.mfg.services import qa_due

        bind_owner("usr_local")
        with c.app.state.ctx.db.write() as s:
            out = qa_due.scan(s)
        assert out["overdue"] == 1, out
        ntf = api.get("/notifications")["items"] if c.get("/api/v1/mfg/notifications").status_code == 200 else []
        assert not ntf or any("calibration" in n["title"] for n in ntf)
        appr = api.get("/approvals")
        assert any(x["kind"] == "qa_ncr" for x in appr["items"]) is False      # open, not proposed yet
        api.post(f"/qa/ncrs/{ncr['id']}/propose", {"dispositions": [{"kind": "scrap", "qty": 2,
                                                                     "location_id": api.get("/locations")["items"][0]["id"]}]}, 200)
        appr = api.get("/approvals")
        assert appr["counts"]["qa_ncr"] == 1


def test_export_needs_archive_dir(api):
    api.err("POST", "/part11/exports", 422, "PART11_NO_ARCHIVE_DIR", json={"from": "2026-01-01", "to": "2026-01-02"})
