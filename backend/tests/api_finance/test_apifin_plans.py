"""F2: defaults, templates, plans CRUD, If-Match, drafts, `whatif_` rejection, export/import, preview, validate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apifin_helpers import FIN, START, assert_error, minimal_plan
from sqlalchemy import select

from superplanner import finance
from superplanner.api.db import AuditEventRow


def test_defaults_shape(fin):
    r = fin.c.get(f"{FIN}/defaults")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"plan", "disclaimer", "disclaimer_version", "limits"}
    assert body["disclaimer"] == finance.DISCLAIMER
    assert body["disclaimer_version"] == finance.DISCLAIMER_VERSION
    assert body["plan"]["start_month"] == datetime.now(UTC).strftime("%Y-%m")
    finance.FinancePlan.model_validate(body["plan"])
    assert body["limits"] == {"goals": 12, "incomes": 20, "expenses": 100, "debts": 20, "holdings": 50,
                              "one_offs": 200, "asset_classes": 10, "horizon_months": 600}


def test_templates_list(fin):
    items = fin.c.get(f"{FIN}/templates").json()["items"]
    assert [t["id"] for t in items] == ["young_professional", "family", "near_retirement", "blank"]
    for t in items:
        assert set(t) == {"id", "name", "description", "parameters"}
    yp = items[0]
    assert {p["name"] for p in yp["parameters"]} >= {"age", "take_home", "car_price"}


def test_instantiate_headers_and_errors(fin):
    r = fin.c.post(f"{FIN}/templates/family/instantiate", json={"name": "Our family", "start_month": START,
                                                               "parameters": {"age": 40}})
    assert r.status_code == 201
    rec = r.json()
    assert r.headers["ETag"] == '"1"'
    assert r.headers["Location"] == f"{FIN}/plans/{rec['id']}"
    assert rec["id"].startswith("fp_") and rec["template_id"] == "family" and rec["version"] == 1
    assert rec["plan"]["id"] == rec["id"] and rec["plan"]["name"] == "Our family"
    assert rec["plan"]["start_month"] == START
    # no body at all: defaults (current UTC month)
    r = fin.c.post(f"{FIN}/templates/blank/instantiate")
    assert r.status_code == 201
    assert r.json()["plan"]["start_month"] == datetime.now(UTC).strftime("%Y-%m")
    assert_error(fin.c.post(f"{FIN}/templates/nope/instantiate", json={}), 404, "NOT_FOUND")
    err = assert_error(fin.c.post(f"{FIN}/templates/family/instantiate", json={"parameters": {"bogus": 1}}),
                       422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", "parameters"]
    assert_error(fin.c.post(f"{FIN}/templates/family/instantiate", json={"parameters": {"age": 99}}),
                 422, "VALIDATION_ERROR")
    assert_error(fin.c.post(f"{FIN}/templates/family/instantiate", json={"start_month": "2026-13"}),
                 422, "VALIDATION_ERROR")


def test_create_with_only_name_fills_start_month(fin):
    r = fin.c.post(f"{FIN}/plans", json={"name": "Draft"})
    assert r.status_code == 201, r.text
    assert r.headers["ETag"] == '"1"'
    rec = r.json()
    assert rec["plan"]["start_month"] == datetime.now(UTC).strftime("%Y-%m")
    assert rec["plan"]["id"] == rec["id"] and rec["template_id"] is None
    got = fin.c.get(f"{FIN}/plans/{rec['id']}")
    assert got.status_code == 200 and got.headers["ETag"] == '"1"'
    assert got.json() == rec


def test_create_model_errors(fin):
    assert_error(fin.c.post(f"{FIN}/plans", json={}), 422, "VALIDATION_ERROR")
    assert_error(fin.c.post(f"{FIN}/plans", json={"name": "x", "bogus": 1}), 422, "VALIDATION_ERROR")
    assert_error(fin.c.post(f"{FIN}/plans", json={"name": "x", "profile": {"risk_tolerance": 9}}), 422,
                 "VALIDATION_ERROR")


@pytest.mark.parametrize("lst,item", [
    ("incomes", {"id": "whatif_x", "name": "Bonus", "amount": 1}),
    ("expenses", {"id": "whatif_x", "name": "Rent", "amount": 1}),
    ("goals", {"id": "whatif_x", "name": "Trip", "target_amount": 1, "target_month": "2030-01"}),
    ("holdings", {"id": "whatif_x", "name": "Cash", "asset_class_id": "cash", "amount": 1}),
])
def test_whatif_ids_rejected_on_post_put_import(fin, lst, item):
    doc = minimal_plan()
    doc[lst] = list(doc.get(lst, [])) + [item]
    idx = len(doc[lst]) - 1
    err = assert_error(fin.c.post(f"{FIN}/plans", json=doc), 422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", lst, idx, "id"]

    rec = fin.create()
    err = assert_error(fin.put(rec["id"], doc, 1), 422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", lst, idx, "id"]
    assert fin.c.get(f"{FIN}/plans/{rec['id']}").json()["version"] == 1

    file = {"format": "superplanner.finance_plan", "format_version": 1, "plan": doc}
    err = assert_error(fin.c.post(f"{FIN}/plans/import", json=file), 422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", "plan", lst, idx, "id"]


def test_whatif_ids_rejected_on_instantiate(fin, monkeypatch):
    tpl = finance.TEMPLATES["blank"]

    class Bad:
        id, name, description, parameters = "bad", "Bad", "", []

        def build(self, *, name, start_month, params):
            plan = tpl.build(name=name, start_month=start_month, params=params)
            return plan.model_copy(update={"incomes": [finance.IncomeStream(id="whatif_extra", name="x", amount=1)]})

    monkeypatch.setitem(finance.TEMPLATES, "bad", Bad())
    err = assert_error(fin.c.post(f"{FIN}/templates/bad/instantiate", json={}), 422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", "plan", "incomes", 0, "id"]
    assert fin.c.get(f"{FIN}/plans").json()["items"] == []


def test_put_versioning(fin):
    rec = fin.create()
    pid = rec["id"]
    doc = rec["plan"]
    doc["name"] = "Renamed"
    assert_error(fin.put(pid, doc, None), 428, "PRECONDITION_REQUIRED")
    assert_error(fin.put(pid, doc, "abc"), 428, "PRECONDITION_REQUIRED")
    err = assert_error(fin.put(pid, doc, 7), 412, "VERSION_MISMATCH")
    assert err["details"]["current_version"] == 1
    r = fin.put(pid, doc, '"1"')
    assert r.status_code == 200 and r.headers["ETag"] == '"2"'
    assert r.json()["version"] == 2 and r.json()["plan"]["name"] == "Renamed"
    r = fin.put(pid, doc, "2")
    assert r.status_code == 200 and r.json()["version"] == 3
    r = fin.put(pid, doc, 'W/"3"')
    assert r.status_code == 200 and r.json()["version"] == 4
    # body id is ignored; record id wins; start_month null is filled again
    doc["id"] = "something_else"
    doc["start_month"] = None
    r = fin.put(pid, doc, 4)
    assert r.status_code == 200
    assert r.json()["plan"]["id"] == pid
    assert r.json()["plan"]["start_month"] == datetime.now(UTC).strftime("%Y-%m")
    assert fin.c.get(f"{FIN}/plans").json()["items"][0]["name"] == "Renamed"
    assert_error(fin.put("fp_missing", doc, 1), 404, "NOT_FOUND")
    assert_error(fin.c.put(f"{FIN}/plans/{pid}", json={"name": "x", "bogus": 1}, headers={"If-Match": "5"}),
                 422, "VALIDATION_ERROR")


def test_get_and_delete_404_and_delete_204(fin):
    assert_error(fin.c.get(f"{FIN}/plans/fp_nope"), 404, "NOT_FOUND")
    assert_error(fin.c.delete(f"{FIN}/plans/fp_nope"), 404, "NOT_FOUND")
    rec = fin.create()
    r = fin.c.delete(f"{FIN}/plans/{rec['id']}")
    assert r.status_code == 204 and r.content == b""
    assert_error(fin.c.get(f"{FIN}/plans/{rec['id']}"), 404)


def test_list_summaries_order_and_shape(fin):
    a = fin.create(minimal_plan("A"))
    b = fin.instantiate("young_professional", name="B")
    items = fin.c.get(f"{FIN}/plans").json()["items"]
    assert [i["id"] for i in items] == [b["id"], a["id"]]
    s = items[0]
    assert set(s) == {"id", "name", "version", "currency", "goal_count", "template_id", "updated_at", "latest_run",
                      "latest_result"}
    assert s["goal_count"] == 2 and s["currency"] == "INR" and s["latest_run"] is None and s["latest_result"] is None
    assert s["updated_at"].endswith("Z")
    doc = a["plan"]
    doc["name"] = "A2"
    fin.put(a["id"], doc, 1)
    assert fin.c.get(f"{FIN}/plans").json()["items"][0]["id"] == a["id"]


def test_export_import_round_trip(fin):
    rec = fin.instantiate("family", name="Family export")
    r = fin.c.get(f"{FIN}/plans/{rec['id']}/export")
    assert r.status_code == 200
    assert r.headers["Content-Disposition"] == 'attachment; filename="family-export.finance.json"'
    file = r.json()
    assert file["format"] == "superplanner.finance_plan" and file["format_version"] == 1
    assert file["exported_at"].endswith("Z")
    r = fin.c.post(f"{FIN}/plans/import", json=file)
    assert r.status_code == 201 and r.headers["ETag"] == '"1"'
    new = r.json()
    assert new["id"] != rec["id"] and new["version"] == 1
    a, b = dict(rec["plan"]), dict(new["plan"])
    assert a.pop("id") == rec["id"] and b.pop("id") == new["id"]
    assert a == b
    assert_error(fin.c.get(f"{FIN}/plans/fp_nope/export"), 404)
    assert_error(fin.c.post(f"{FIN}/plans/import", json={"format": "other", "format_version": 1, "plan": a}), 422)


def test_preview(fin):
    r = fin.c.post(f"{FIN}/preview", json={**minimal_plan(), "start_month": None})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["cashflow"] is not None
    assert body["cashflow"]["avg_monthly_surplus_first_year"] > 0
    bad = minimal_plan()
    bad["goals"][0]["target_month"] = START
    body = fin.c.post(f"{FIN}/preview", json=bad).json()
    assert body["ok"] is False and body["cashflow"] is None
    assert any(i["code"] == "GOAL_TOO_SOON" and "Car" in i["message"] for i in body["issues"])
    assert_error(fin.c.post(f"{FIN}/preview", json={"name": ""}), 422, "VALIDATION_ERROR")


def test_validate(fin):
    rec = fin.create()
    r = fin.c.post(f"{FIN}/plans/{rec['id']}/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["plan_version"] == 1 and body["ok"] is True and body["cashflow"]["ef_target"] > 0
    doc = rec["plan"]
    doc["goals"][0]["target_month"] = "2020-01"
    fin.put(rec["id"], doc, 1)
    body = fin.c.post(f"{FIN}/plans/{rec['id']}/validate").json()
    assert body["plan_version"] == 2 and body["ok"] is False and body["cashflow"] is None
    assert_error(fin.c.post(f"{FIN}/plans/fp_nope/validate"), 404)


def test_audit_rows_have_no_amounts_or_names(fin):
    rec = fin.instantiate("young_professional", name="Secret name")
    doc = rec["plan"]
    fin.put(rec["id"], doc, 1)
    fin.c.post(f"{FIN}/plans/import", json=fin.c.get(f"{FIN}/plans/{rec['id']}/export").json())
    fin.c.delete(f"{FIN}/plans/{rec['id']}")
    with fin.ctx.db.read() as s:
        rows = s.scalars(select(AuditEventRow).where(AuditEventRow.entity_type == "finance_plan")).all()
        actions = sorted(r.action for r in rows)
        details = [r.details for r in rows]
    assert actions == ["finance_plan.created", "finance_plan.deleted", "finance_plan.imported",
                       "finance_plan.updated"]
    for d in details:
        assert "Secret" not in str(d)
        for k, v in d.items():
            assert k in ("version", "template_id"), d
