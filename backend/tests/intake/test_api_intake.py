"""`/api/v1/intake` endpoints (PHASE2 2.15; plan P2-8)."""

from __future__ import annotations

import logging

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from intake_helpers import (API, CTX_JSON, EXAMPLE_ANSWERS, FIN_CTX_JSON, FINANCE_TEXT, SCHEDULE_TEXT, TABLE_TEXT,
                            FakeClient, ai_schedule_output, make_app, pick, text_response)
from superplanner.intake import PRIVACY_NOTICE

IN = f"{API}/intake"


def err(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["error"]["code"] == code, body
    return body["error"]


def counts(db_url: str) -> dict[str, int]:
    eng = sa.create_engine(db_url)
    try:
        with eng.connect() as c:
            names = sa.inspect(eng).get_table_names()
            return {n: c.execute(sa.text(f'SELECT COUNT(*) FROM "{n}"')).scalar_one() for n in names}
    finally:
        eng.dispose()


def test_capabilities_without_ai(client):
    r = client.get(f"{IN}/capabilities")
    assert r.status_code == 200
    assert r.json() == {"ai_available": False, "ai_reason": "AI_DISABLED", "provider": "Anthropic",
                        "model": "claude-opus-5-5", "privacy_notice": PRIVACY_NOTICE,
                        "limits": {"max_text_chars": 20000, "max_table_chars": 1000000, "max_table_rows": 2000,
                                   "max_table_columns": 30},
                        "schedule_kinds": ["project", "study", "production", "generic"]}
    assert PRIVACY_NOTICE.startswith("AI assist sends the text in this box to Anthropic, an AI provider")


def test_capabilities_with_ai(db_url):
    fake = FakeClient(text_response(ai_schedule_output()))
    with TestClient(make_app(db_url, intake_ai_enabled=True, intake_ai_client_factory=lambda: fake)) as c:
        caps = c.get(f"{IN}/capabilities").json()
        assert caps["ai_available"] is True and caps["ai_reason"] is None
    with TestClient(make_app(db_url, intake_ai_enabled=True,
                             intake_ai_client_factory=lambda: FakeClient(api_key=None))) as c:
        caps = c.get(f"{IN}/capabilities").json()
        assert caps["ai_available"] is False and caps["ai_reason"] == "AI_NO_CREDENTIALS"
    assert fake.calls == []


def test_schedule_flow(client):
    r = client.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": CTX_JSON, "use_ai": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"draft", "questions", "notes", "row_notes", "extractor", "ready"}
    assert body["draft"]["provenance"]["/start_date"]["span"] == {"start": 26, "end": 37, "text": "next Monday"}
    assert pick(body["questions"], "SCHED_WHO:/tasks/t4/resources")["default_label"] == "Either Ravi or Priya"
    a = client.post(f"{IN}/schedule/answer", json={"draft": body["draft"], "answers": EXAMPLE_ANSWERS,
                                                   "context": CTX_JSON})
    assert a.status_code == 200, a.text
    ab = a.json()
    assert ab["questions"] == [] and ab["draft"]["dismissed"] == ["SCHED_PEOPLE:-"]
    b = client.post(f"{IN}/schedule/build", json={"draft": ab["draft"], "context": CTX_JSON})
    assert b.status_code == 200, b.text
    bb = b.json()
    assert bb["ready"] and bb["problem"]["horizon_days"] == 64
    assert bb["duration_summary"] == {"tasks_with_range": 2, "expected_work_minutes": 10320,
                                      "optimistic_work_minutes": 9600, "pessimistic_work_minutes": 11040}
    created = client.post(f"{API}/problems", json=bb["problem"])
    assert created.status_code == 201, created.text


def test_finance_flow(client):
    r = client.post(f"{IN}/finance/describe", json={"text": FINANCE_TEXT, "context": FIN_CTX_JSON})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] and body["draft"]["incomes"][0]["amount"] == {"low": 120000, "high": 120000}
    a = client.post(f"{IN}/finance/answer", json={"draft": body["draft"], "context": FIN_CTX_JSON, "answers": [
        {"question_id": "FIN_DISCRETIONARY:-", "value": 10000}]})
    assert a.status_code == 200, a.text
    b = client.post(f"{IN}/finance/build", json={"draft": a.json()["draft"], "context": FIN_CTX_JSON})
    assert b.status_code == 200, b.text
    bb = b.json()
    assert bb["ready"] and bb["preflight"]["ok"] and bb["cashflow"] is not None
    e1 = next(e for e in bb["plan"]["expenses"] if e["id"] == "e1")
    assert e1["amount"] == 75000 and e1["amount_range"] == {"low": 70000, "high": 80000}
    created = client.post(f"{API}/finance/plans", json=bb["plan"])
    assert created.status_code == 201, created.text


def test_tables_endpoints(client):
    p = client.post(f"{IN}/schedule/table/parse", json={"text": TABLE_TEXT, "delimiter": "auto"})
    assert p.status_code == 200, p.text
    cols = p.json()["columns"]
    mapping = [{"column": c["index"], "field": c["suggested_field"]} for c in cols]
    a = client.post(f"{IN}/schedule/table/apply", json={"text": TABLE_TEXT, "delimiter": "\t", "has_header": True,
                                                        "mapping": mapping, "context": CTX_JSON})
    assert a.status_code == 200, a.text
    assert [t["key"] for t in a.json()["draft"]["tasks"]] == ["row0", "row1", "row2"]
    assert a.json()["row_notes"] == []
    again = client.post(f"{IN}/schedule/table/apply", json={
        "text": TABLE_TEXT, "delimiter": "\t", "has_header": True, "mapping": mapping, "context": CTX_JSON,
        "base": a.json()["draft"]})
    assert len(again.json()["draft"]["tasks"]) == 6
    fin = "name\tamount\ttype\nSalary\t1 lakh\tincome\nRent\t20k\texpense"
    fp = client.post(f"{IN}/finance/table/parse", json={"text": fin})
    assert fp.status_code == 200 and fp.json()["delimiter"] == "\t"
    fm = [{"column": c["index"], "field": c["suggested_field"]} for c in fp.json()["columns"]]
    fa = client.post(f"{IN}/finance/table/apply", json={"text": fin, "delimiter": "\t", "has_header": True,
                                                        "mapping": fm, "context": FIN_CTX_JSON})
    assert fa.status_code == 200, fa.text
    assert fa.json()["draft"]["incomes"][0]["amount"] == {"low": 100000, "high": 100000}


def test_error_codes(client):
    ctx = CTX_JSON
    err(client.post(f"{IN}/schedule/describe", json={"text": "  ", "context": ctx}), 422, "TEXT_EMPTY")
    e = err(client.post(f"{IN}/finance/describe", json={"text": "x" * 20001, "context": FIN_CTX_JSON}), 422,
            "TEXT_TOO_LONG")
    assert e["details"]["max_chars"] == 20000
    err(client.post(f"{IN}/schedule/table/parse", json={"text": " \n "}), 422, "TABLE_EMPTY")
    e = err(client.post(f"{IN}/schedule/table/parse", json={"text": "a\tb\n" * 2002}), 422, "TABLE_TOO_LARGE")
    assert e["details"] == {"max_rows": 2000}
    draft = client.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": ctx}).json()["draft"]
    e = err(client.post(f"{IN}/schedule/answer", json={"draft": draft, "context": ctx,
                                                       "answers": [{"question_id": "NOPE:-", "value": 1}]}),
            422, "UNKNOWN_QUESTION")
    assert e["details"] == {"question_id": "NOPE:-"}
    err(client.post(f"{IN}/schedule/table/apply", json={"text": TABLE_TEXT, "delimiter": "\t", "has_header": True,
                                                        "mapping": [{"column": 1, "field": "duration"}],
                                                        "context": ctx}), 422, "BAD_MAPPING")
    bad = dict(draft)
    bad["tasks"] = draft["tasks"] + [dict(draft["tasks"][0])]          # duplicate key
    err(client.post(f"{IN}/schedule/build", json={"draft": bad, "context": ctx}), 422, "VALIDATION_ERROR")
    dangling = dict(draft)
    dangling["tasks"] = [dict(draft["tasks"][0], after=["t99"])]
    err(client.post(f"{IN}/schedule/build", json={"draft": dangling, "context": ctx}), 422, "VALIDATION_ERROR")
    err(client.post(f"{IN}/schedule/describe", json={"text": "a", "context": ctx, "extra": 1}), 422,
        "VALIDATION_ERROR")
    err(client.post(f"{IN}/schedule/describe", json={"text": "a", "context": dict(ctx, utc_offset="5:30")}), 422,
        "VALIDATION_ERROR")
    err(client.post(f"{IN}/schedule/table/parse", json={"text": "a", "delimiter": ":"}), 422, "VALIDATION_ERROR")


def test_table_text_limit(client):
    big = "a\n" * 500_001                                               # 1,000,002 characters, under 5 MB
    e = err(client.post(f"{IN}/schedule/table/parse", json={"text": big}), 422, "TABLE_TOO_LARGE")
    assert e["details"] == {"max_chars": 1000000}
    e = err(client.post(f"{IN}/finance/table/apply", json={"text": big, "delimiter": ",", "has_header": False,
                                                           "mapping": [{"column": 0, "field": "name"}],
                                                           "context": FIN_CTX_JSON}), 422, "TABLE_TOO_LARGE")
    assert e["details"] == {"max_chars": 1000000}


def test_body_limit_413(db_url):
    with TestClient(make_app(db_url, max_body_bytes=2048)) as c:
        r = c.post(f"{IN}/schedule/describe", json={"text": "x" * 5000, "context": CTX_JSON})
        assert r.status_code == 413


def test_ai_problems_are_never_errors(db_url):
    fake = FakeClient(exc=RuntimeError("boom"))
    with TestClient(make_app(db_url, intake_ai_enabled=True, intake_ai_client_factory=lambda: fake)) as c:
        r = c.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": CTX_JSON, "use_ai": True})
        assert r.status_code == 200
        assert r.json()["extractor"]["fallback_code"] == "AI_UNEXPECTED"
        r = c.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": CTX_JSON})
        assert r.json()["extractor"] == {"requested": "rule", "used": "rule", "ai_available": True,
                                         "fallback_code": None, "fallback_message": None, "model": None}
    with TestClient(make_app(db_url)) as c:
        r = c.post(f"{IN}/finance/describe", json={"text": FINANCE_TEXT, "context": FIN_CTX_JSON, "use_ai": True})
        assert r.status_code == 200 and r.json()["extractor"]["fallback_code"] == "AI_DISABLED"
        assert r.json()["extractor"]["fallback_message"] == ("AI assist is turned off on this server. We used the "
                                                             "built-in reader instead.")


def test_ai_success_through_settings_factory(db_url):
    fake = FakeClient(text_response(ai_schedule_output()))
    with TestClient(make_app(db_url, intake_ai_enabled=True, intake_ai_client_factory=lambda: fake)) as c:
        r = c.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": CTX_JSON, "use_ai": True})
        body = r.json()
        assert body["extractor"]["used"] == "ai+rule" and body["extractor"]["model"] == "claude-opus-5-5"
        assert any(n["code"] == "KEPT_TYPED_NUMBER" for n in body["notes"])
        b = c.post(f"{IN}/schedule/build", json={"draft": body["draft"], "context": CTX_JSON}).json()
        assert b["ready"] and b["problem"]["metadata"]["intake"]["extractor"] == "ai+rule"
    assert len(fake.calls) == 1


def test_ai_slots_are_per_app(db_url, tmp_path):
    a1 = make_app(db_url, intake_ai_enabled=True)
    a2 = make_app(f"sqlite:///{tmp_path / 'b.db'}", intake_ai_enabled=True)
    assert a1.state.intake_ai_slots is not a2.state.intake_ai_slots


def test_no_db_writes_and_no_text_in_logs(db_url, caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeClient(text_response(ai_schedule_output()))
    with TestClient(make_app(db_url, intake_ai_enabled=True, intake_ai_client_factory=lambda: fake)) as c:
        c.get(f"{API}/health")
        before = counts(db_url)
        assert before
        d = c.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": CTX_JSON, "use_ai": True}).json()
        a = c.post(f"{IN}/schedule/answer", json={"draft": d["draft"], "answers": [], "context": CTX_JSON}).json()
        c.post(f"{IN}/schedule/build", json={"draft": a["draft"], "context": CTX_JSON})
        f = c.post(f"{IN}/finance/describe", json={"text": FINANCE_TEXT, "context": FIN_CTX_JSON}).json()
        c.post(f"{IN}/finance/answer", json={"draft": f["draft"], "answers": [], "context": FIN_CTX_JSON})
        c.post(f"{IN}/finance/build", json={"draft": f["draft"], "context": FIN_CTX_JSON})
        c.post(f"{IN}/schedule/table/parse", json={"text": TABLE_TEXT})
        c.post(f"{IN}/schedule/table/apply", json={"text": TABLE_TEXT, "delimiter": "\t", "has_header": True,
                                                   "mapping": [{"column": 0, "field": "name"}], "context": CTX_JSON})
        c.post(f"{IN}/schedule/describe", json={"text": "  ", "context": CTX_JSON})
        assert counts(db_url) == before
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("Gather requirements", "Website relaunch", "Priya", "1.2 lakh", "Household costs", "mutual funds",
                   "Requirements\t", "Launch date looks fixed", "You convert a user's description"):
        assert secret not in logged, secret


@pytest.mark.parametrize("path", ["/intake/schedule/describe", "/intake/finance/describe"])
def test_openapi_lists_intake_paths(client, path):
    spec = client.get("/openapi.json").json()
    assert f"/api/v1{path}" in spec["paths"]
