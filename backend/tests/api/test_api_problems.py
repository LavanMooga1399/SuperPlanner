"""Health, templates, problems CRUD, optimistic concurrency, export/import, validate (A.14.1-14.4)."""

from __future__ import annotations

import copy

from api_helpers import API, assert_error, small_problem


# ---------------------------------------------------------------- health + templates (2.2, 2.5)

def test_api_health(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0", "ortools_version": "9.15.6755", "database": "ok"}


def test_api_templates_list(client):
    r = client.get(f"{API}/templates")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {t["id"] for t in items} == {"manufacturing", "exam_prep", "project", "blank"}
    manu = next(t for t in items if t["id"] == "manufacturing")
    assert manu["terminology"]["task"] == "Operation"
    jobs = next(p for p in manu["parameters"] if p["name"] == "jobs")
    assert jobs == {"name": "jobs", "label": jobs["label"], "type": "int", "default": 5, "min": 1, "max": 20,
                    "help": jobs["help"]}
    exam = next(t for t in items if t["id"] == "exam_prep")
    assert any(p["type"] == "string_list" for p in exam["parameters"])


def test_api_instantiate(client):
    r = client.post(f"{API}/templates/manufacturing/instantiate",
                    json={"name": "Workshop week 43", "start_date": "2026-10-19", "utc_offset": "+05:30",
                          "parameters": {"jobs": 4}})
    assert r.status_code == 201
    rec = r.json()
    assert r.headers["etag"] == '"1"'
    assert r.headers["location"] == f"{API}/problems/{rec['id']}"
    assert rec["id"].startswith("p_") and rec["problem"]["id"] == rec["id"]
    assert rec["version"] == 1 and rec["template_id"] == "manufacturing"
    assert rec["problem"]["name"] == "Workshop week 43"
    assert rec["problem"]["horizon_start"] == "2026-10-19T00:00:00+05:30"
    assert rec["created_at"].endswith("Z")
    assert len({t["group"] for t in rec["problem"]["tasks"]}) == 4


def test_api_instantiate_defaults_and_errors(client):
    r = client.post(f"{API}/templates/blank/instantiate")  # no body at all
    assert r.status_code == 201, r.text
    assert r.json()["problem"]["name"]
    r = client.post(f"{API}/templates/exam_prep/instantiate", json={})
    assert r.status_code == 201
    assert_error(client.post(f"{API}/templates/nope/instantiate", json={}), 404, "NOT_FOUND")
    assert_error(client.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 0}}),
                 422, "VALIDATION_ERROR")
    assert_error(client.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"bogus": 1}}),
                 422, "VALIDATION_ERROR")
    assert_error(client.post(f"{API}/templates/manufacturing/instantiate", json={"utc_offset": "5:30"}),
                 422, "VALIDATION_ERROR")


# ---------------------------------------------------------------- CRUD (2.4, 2.6)

def test_api_create_get_list(client):
    r = client.post(f"{API}/problems", json=small_problem(id="whatever"))
    assert r.status_code == 201 and r.headers["etag"] == '"1"'
    rec = r.json()
    assert rec["problem"]["id"] == rec["id"] != "whatever"
    assert rec["template_id"] is None
    g = client.get(f"{API}/problems/{rec['id']}")
    assert g.status_code == 200 and g.headers["etag"] == '"1"'
    assert g.json() == rec
    items = client.get(f"{API}/problems").json()["items"]
    assert items == [{"id": rec["id"], "name": "Small", "domain": "generic", "version": 1, "task_count": 2,
                      "resource_count": 1, "updated_at": rec["updated_at"], "approved_schedule_id": None,
                      "latest_run": None}]
    assert_error(client.get(f"{API}/problems/p_missing"), 404, "NOT_FOUND")


def test_api_unknown_field_is_422_with_loc(client):
    doc = small_problem()
    doc["tasks"][0]["durration"] = 5
    err = assert_error(client.post(f"{API}/problems", json=doc), 422, "VALIDATION_ERROR")
    locs = [e["loc"] for e in err["details"]["errors"]]
    assert any("durration" in loc for loc in locs), locs
    naive = small_problem(horizon_start="2026-10-19T00:00:00")
    assert_error(client.post(f"{API}/problems", json=naive), 422, "VALIDATION_ERROR")


def test_api_put_concurrency(api, client):
    rec = client.post(f"{API}/problems", json=small_problem()).json()
    pid = rec["id"]
    doc = copy.deepcopy(rec["problem"])
    doc["description"] = "v2"
    assert_error(api.put(pid, doc, None), 428, "PRECONDITION_REQUIRED")
    err = assert_error(api.put(pid, doc, 7), 412, "VERSION_MISMATCH")
    assert err["details"]["current_version"] == 1
    r = api.put(pid, doc, '"1"')
    assert r.status_code == 200 and r.headers["etag"] == '"2"' and r.json()["version"] == 2
    doc["id"] = "spoofed"
    r = api.put(pid, doc, "2")
    assert r.status_code == 200 and r.json()["version"] == 3 and r.json()["problem"]["id"] == pid
    r = api.put(pid, doc, 'W/"3"')
    assert r.status_code == 200 and r.json()["version"] == 4
    assert_error(api.put("p_missing", doc, 1), 404, "NOT_FOUND")
    bad = copy.deepcopy(doc)
    bad["tasks"][0]["duration_minutes"] = 0
    assert_error(api.put(pid, bad, 4), 422, "VALIDATION_ERROR")
    assert client.get(f"{API}/problems/{pid}").json()["version"] == 4


def test_api_drafts_saveable_and_validate(api, client):
    rec = client.post(f"{API}/problems", json=small_problem()).json()
    doc = copy.deepcopy(rec["problem"])
    doc["dependencies"].append({"predecessor": "A", "successor": "A"})
    doc["tasks"][1]["requirements"] = [{"alternatives": ["GHOST"]}]
    r = api.put(rec["id"], doc, 1)
    assert r.status_code == 200
    v = client.post(f"{API}/problems/{rec['id']}/validate")
    assert v.status_code == 200
    body = v.json()
    assert body["problem_version"] == 2 and body["ok"] is False and body["cpm"] is None
    codes = {i["code"] for i in body["issues"]}
    assert {"SELF_DEPENDENCY", "UNKNOWN_RESOURCE"} <= codes
    assert_error(client.post(f"{API}/problems/p_missing/validate"), 404, "NOT_FOUND")


def test_api_validate_ok_has_cpm(client):
    rec = client.post(f"{API}/problems", json=small_problem()).json()
    body = client.post(f"{API}/problems/{rec['id']}/validate").json()
    assert body["ok"] is True
    assert body["cpm"]["lower_bound_makespan_minutes"] == 90
    assert body["cpm"]["critical_path"] == ["A", "B"]


def test_api_export_import(client):
    rec = client.post(f"{API}/problems", json=small_problem(name="My Plan!")).json()
    r = client.get(f"{API}/problems/{rec['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="my-plan.superplanner.json"'
    exp = r.json()
    assert exp["format"] == "superplanner.problem" and exp["format_version"] == 1
    assert exp["exported_at"].endswith("Z") and exp["problem"] == rec["problem"]
    imp = client.post(f"{API}/problems/import", json=exp)
    assert imp.status_code == 201 and imp.headers["etag"] == '"1"'
    new = imp.json()
    assert new["id"] != rec["id"] and new["problem"]["id"] == new["id"]
    assert [t["id"] for t in new["problem"]["tasks"]] == ["A", "B"]
    bad = dict(exp, format_version=2)
    assert_error(client.post(f"{API}/problems/import", json=bad), 422, "VALIDATION_ERROR")
    assert_error(client.post(f"{API}/problems/import", json={"problem": exp["problem"]}), 422, "VALIDATION_ERROR")
    assert_error(client.get(f"{API}/problems/p_missing/export"), 404, "NOT_FOUND")


def test_api_delete_cascades(api, client):
    rec = api.instantiate(jobs=2)
    pid = rec["id"]
    run = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    sid = run["primary_schedule_id"]
    assert sid
    r = client.delete(f"{API}/problems/{pid}")
    assert r.status_code == 204
    assert_error(client.get(f"{API}/problems/{pid}"), 404)
    assert_error(client.get(f"{API}/solver-runs/{run['id']}"), 404)
    assert_error(client.get(f"{API}/schedules/{sid}"), 404)
    from sqlalchemy import text
    ctx = client.app.state.ctx
    with ctx.db.engine.connect() as c:
        for table in ("problem_versions", "solver_runs", "solver_run_events", "schedules"):
            assert c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0, table
    assert_error(client.delete(f"{API}/problems/{pid}"), 404)


def test_api_delete_with_active_run_409(api, client):
    pid = api.instantiate(jobs=20)["id"]
    run = api.start_run(pid, strategy="ga", time_limit_seconds=20,
                        ga={"max_generations": 10000, "stagnation_generations": 1000})
    assert_error(client.delete(f"{API}/problems/{pid}"), 409)
    client.post(f"{API}/solver-runs/{run['run_id']}/cancel")
    api.wait(run["run_id"])
    assert client.delete(f"{API}/problems/{pid}").status_code == 204


def test_api_method_not_allowed_keeps_default(client):
    r = client.patch(f"{API}/problems")
    assert r.status_code == 405
