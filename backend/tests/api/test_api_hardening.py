"""Hardening fixes: CSV formula injection, CSV deadline offset, body/document size limits, replan nulls."""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from api_helpers import API, assert_error, make_app, small_problem


def _csv_rows(api, client, doc):
    rec = client.post(f"{API}/problems", json=doc)
    assert rec.status_code == 201, rec.text
    sid = api.solve(rec.json()["id"], strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    r = client.get(f"{API}/schedules/{sid}/export.csv")
    assert r.status_code == 200
    assert r.text.split("\r\n")[0] == ("task_id,task_name,group,type,start,end,duration_minutes,resource_ids,"
                                       "resource_names,deadline,deadline_hard,lateness_minutes,on_critical_chain")
    return {row["task_id"].lstrip("'"): row for row in csv.DictReader(io.StringIO(r.text))}


def test_csv_neutralises_formulas(api, client):
    doc = small_problem()
    doc["tasks"][0]["name"] = '=HYPERLINK("http://evil","x")'
    doc["tasks"][0]["group"] = "@SUM(1)"
    doc["tasks"][1]["name"] = "+cmd|' /C calc'!A0"
    doc["tasks"][1]["id"] = "-B"
    doc["dependencies"][0]["successor"] = "-B"
    doc["resources"][0]["name"] = "-2+3"
    doc["tasks"].append({"id": "C", "name": "\tTabbed", "duration_minutes": 10})
    doc["tasks"].append({"id": "D", "name": "Plain - name", "duration_minutes": 10})
    rows = _csv_rows(api, client, doc)
    assert rows["A"]["task_name"] == '\'=HYPERLINK("http://evil","x")'
    assert rows["A"]["group"] == "'@SUM(1)"
    assert rows["A"]["resource_names"] == "'-2+3"
    assert rows["-B"]["task_id"] == "'-B" and rows["-B"]["task_name"] == "'+cmd|' /C calc'!A0"
    assert rows["C"]["task_name"] == "'\tTabbed"
    assert rows["D"]["task_name"] == "Plain - name"
    assert rows["A"]["duration_minutes"] == "60"


def test_csv_deadline_in_plan_offset(api, client):
    doc = small_problem()  # horizon_start has +05:30
    doc["tasks"][0]["deadline"] = "2026-10-20T10:00:00Z"
    rows = _csv_rows(api, client, doc)
    assert rows["A"]["start"].endswith("+05:30")
    assert rows["A"]["deadline"] == "2026-10-20T15:30:00+05:30"
    assert rows["B"]["deadline"] == ""


def test_body_size_limit(db_url):
    with TestClient(make_app(db_url, max_body_bytes=64 * 1024)) as c:
        doc = small_problem(description="x" * 5000)
        assert c.post(f"{API}/problems", json=doc).status_code == 201
        big = small_problem(metadata={"blob": "x" * 70 * 1024})
        err = assert_error(c.post(f"{API}/problems", json=big), 413, "PAYLOAD_TOO_LARGE")
        assert err["details"] == {"max_bytes": 64 * 1024}

        def chunks():  # no Content-Length: counted while streaming
            yield b'{"name": "x", "horizon_start": "2026-10-19T00:00:00Z", "description": "'
            for _ in range(80):
                yield b"x" * 1024
            yield b'"}'
        r = c.post(f"{API}/problems", content=chunks(), headers={"Content-Type": "application/json"})
        assert_error(r, 413, "PAYLOAD_TOO_LARGE")
        assert c.get(f"{API}/problems").status_code == 200


def test_default_body_limit_rejects_20mb(client):
    r = client.post(f"{API}/problems", json=small_problem(description="x" * (20 * 1024 * 1024)))
    assert_error(r, 413, "PAYLOAD_TOO_LARGE")


def test_document_field_caps(client):
    def loc_of(doc):
        err = assert_error(client.post(f"{API}/problems", json=doc), 422, "VALIDATION_ERROR")
        return [e["loc"] for e in err["details"]["errors"]]

    assert ["body", "description"] in loc_of(small_problem(description="x" * 10001))
    doc = small_problem()
    doc["tasks"][0]["description"] = "x" * 10001
    assert ["body", "tasks", 0, "description"] in loc_of(doc)
    doc = small_problem()
    doc["tasks"][0]["metadata"] = {"k": "x" * 17000}
    assert ["body", "tasks", 0, "metadata"] in loc_of(doc)
    assert ["body", "metadata"] in loc_of(small_problem(metadata={"k": "x" * 70000}))
    many = small_problem(tasks=[{"id": f"T{i}", "name": "t", "duration_minutes": 1} for i in range(5001)],
                         dependencies=[])
    assert ["body", "tasks"] in loc_of(many)
    # drafts above the solve limit but within the document cap are still saveable (preflight reports it)
    ok = small_problem(tasks=[{"id": f"T{i}", "name": "t", "duration_minutes": 1} for i in range(2001)],
                       dependencies=[])
    assert client.post(f"{API}/problems", json=ok).status_code == 201


def test_replan_null_for_non_nullable_field_rejected(api, client):
    rec = client.post(f"{API}/problems", json=small_problem()).json()
    sid = api.solve(rec["id"], strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    cutoff = "2026-10-19T00:00:00+05:30"
    for field in ("requirements", "deadline_hard", "duration_minutes", "name", "priority"):
        r = client.post(f"{API}/schedules/{sid}/replan",
                        json={"cutoff": cutoff, "changes": {"task_updates": [{"id": "B", field: None}]}})
        err = assert_error(r, 422, "VALIDATION_ERROR")
        assert ["body", "changes", "task_updates", 0, field] in [e["loc"] for e in err["details"]["errors"]]
    cur = client.get(f"{API}/problems/{rec['id']}").json()
    assert cur["version"] == 1
    assert cur["problem"]["tasks"][1]["requirements"] == [{"alternatives": ["M1"], "units": 1}]
    # nullable fields may still be cleared explicitly
    r = client.post(f"{API}/schedules/{sid}/replan",
                    json={"cutoff": cutoff, "changes": {"task_updates": [{"id": "B", "deadline": None}]}})
    assert r.status_code == 202, r.text
    api.wait(r.json()["run_id"])
