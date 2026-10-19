"""AI extractor end to end through the API with a fake client (PHASE2 2.10, 2.11; plan P2-5, P2-7, P4 (c)).

The fake is installed with `Settings.intake_ai_client_factory`, so the real request path (settings -> options
-> slots -> availability -> call -> merge) is exercised. Every failure must give HTTP 200, `used == "rule"`, a
fallback code and message, and exactly the draft the built-in reader gives without AI.
"""

from __future__ import annotations

import copy
import json
import logging
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from p2_helpers import (API, CTX_JSON, FIN_CTX_JSON, IN, FakeClient, make_app, solve_and_check, text_response,
                        wait_fin_run)

SCHEDULE_TEXT = ("Website relaunch starting next Monday. Ravi and Priya are on the team.\n"
                 "1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n"
                 "3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026")
FINANCE_TEXT = ("I'm 34, take home about 1.2 lakh a month and my wife earns 60k. Household costs are 70-80k a month, "
                "school fees 18k every quarter. Car loan EMI 10k, about 3 lakh left at 9%. We have 6 lakh in savings "
                "and 8L in mutual funds. We want 15 lakh for a flat down payment in 3 years and to retire at 60. "
                "Moderate risk.")
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
SUFFIX = "We used the built-in reader instead."


def _status(code: int) -> httpx2.Response:
    return httpx2.Response(code, request=_REQ)


def sched_ai(**over):
    def task(name, low, likely, high, unit, quote, after=(), resources=(), milestone=False, deadline=None):
        return {"name": name, "milestone": milestone,
                "duration": {"low": low, "likely": likely, "high": high, "unit": unit},
                "after": list(after), "resources": list(resources), "resource_mode": "any", "deadline": deadline,
                "deadline_hard": False, "earliest_start": None, "group": None, "source_quote": quote,
                "confidence": 0.9}
    out = {"kind": "project", "name": "Website relaunch", "start_date": "2026-10-19", "working_time": None,
           "tasks": [task("Gather requirements", 4, 4, 4, "days", "Gather requirements - 2-3 days", resources=["Priya"]),
                     task("Design", 1, 1, 1, "weeks", "Design 1 week", after=["Gather requirements"]),
                     task("Build the site", 2, 2, 2, "weeks", "Build the site: 2 weeks", after=["Design"]),
                     task("Testing", 3, None, 5, "days", "Testing 3-5 days", after=["Build the site"]),
                     task("Write release notes", 2, 2, 2, "hours", "not in the text", after=["Testing", "Ghost"]),
                     task("Launch", None, None, None, None, "Launch by 15 Dec 2026", milestone=True,
                          deadline="2026-12-15", after=["Testing"])],
           "resources": [{"name": "Ravi", "kind": "person", "count": 1, "source_quote": "Ravi", "confidence": 0.9},
                         {"name": "Priya", "kind": "person", "count": 1, "source_quote": "Priya", "confidence": 0.95}],
           "notes": ["Launch date looks fixed."]}
    out.update(over)
    return out


def fin_ai(**over):
    amt = lambda lo, hi=None: {"low": lo, "high": lo if hi is None else hi}  # noqa: E731
    out = {"profile": {"age": 34, "retirement_age": 60, "risk_tolerance": 3, "source_quote": "I'm 34"},
           "incomes": [{"name": "Salary", "kind": "salary", "amount": amt(125000), "frequency": "monthly",
                        "is_gross": False, "source_quote": "take home about 1.2 lakh a month", "confidence": 0.9}],
           "expenses": [{"name": "Household costs", "category": "living", "amount": amt(70000, 80000),
                         "frequency": "monthly", "essential": True, "source_quote": "Household costs",
                         "confidence": 0.9}],
           "debts": [], "holdings": [], "goals": [], "emergency_fund_months": None, "notes": []}
    out.update(over)
    return out


def app_with(db_url, fake):
    return TestClient(make_app(db_url, intake_ai_enabled=True, intake_ai_client_factory=lambda: fake))


def describe(c, domain: str, use_ai: bool = True):
    text, ctxj = (SCHEDULE_TEXT, CTX_JSON) if domain == "schedule" else (FINANCE_TEXT, FIN_CTX_JSON)
    r = c.post(f"{IN}/{domain}/describe", json={"text": text, "context": ctxj, "use_ai": use_ai})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def rule_drafts(client):
    return {d: describe(client, d, use_ai=False) for d in ("schedule", "finance")}


def _bad_schema_variants(domain: str):
    good = sched_ai() if domain == "schedule" else fin_ai()
    extra = copy.deepcopy(good)
    extra["unexpected"] = 1
    missing = copy.deepcopy(good)
    missing.pop("notes")
    wrong_type = copy.deepcopy(good)
    if domain == "schedule":
        wrong_type["tasks"][0]["duration"]["low"] = "four"
        enum = copy.deepcopy(good)
        enum["kind"] = "wedding"
    else:
        wrong_type["incomes"][0]["amount"]["low"] = "lots"
        enum = copy.deepcopy(good)
        enum["incomes"][0]["frequency"] = "fortnightly"
    return {"extra_key": extra, "missing_key": missing, "wrong_type": wrong_type, "bad_enum": enum,
            "array_root": [good], "null_root": None}


RESPONSE_CASES = [
    ("refusal", lambda d: text_response({}, stop_reason="refusal"), "AI_REFUSED"),
    ("max_tokens", lambda d: text_response(raw='{"kind": "proj', stop_reason="max_tokens"), "AI_TRUNCATED"),
    ("no_text_block", lambda d: text_response(blocks=[SimpleNamespace(type="thinking", thinking="...")]), "AI_NO_TEXT"),
    ("empty_content", lambda d: text_response(blocks=[]), "AI_NO_TEXT"),
    ("invalid_json", lambda d: text_response(raw="Here is the JSON: {not json"), "AI_BAD_JSON"),
    ("fenced_json", lambda d: text_response(raw="```json\n" + json.dumps(sched_ai() if d == "schedule" else fin_ai())
                                            + "\n```"), "AI_BAD_JSON"),
    ("empty_text", lambda d: text_response(raw=""), "AI_BAD_JSON"),
]

EXC_CASES = [
    ("rate_limit", anthropic.RateLimitError("slow", response=_status(429), body=None), "AI_RATE_LIMITED"),
    ("auth", anthropic.AuthenticationError("bad key", response=_status(401), body=None), "AI_AUTH_FAILED"),
    ("permission", anthropic.PermissionDeniedError("no", response=_status(403), body=None), "AI_API_ERROR"),
    ("server_500", anthropic.InternalServerError("boom", response=_status(500), body=None), "AI_API_ERROR"),
    ("overloaded_529", anthropic.APIStatusError("overloaded", response=_status(529), body=None), "AI_API_ERROR"),
    ("connection", anthropic.APIConnectionError(request=_REQ), "AI_CONNECTION_ERROR"),
    ("timeout", anthropic.APITimeoutError(request=_REQ), "AI_CONNECTION_ERROR"),
    ("unexpected", RuntimeError("kaboom"), "AI_UNEXPECTED"),
]


def assert_fell_back(body, rule_body, code):
    ex = body["extractor"]
    assert ex["requested"] == "ai" and ex["used"] == "rule", ex
    assert ex["fallback_code"] == code, ex
    assert ex["fallback_message"] and ex["fallback_message"].endswith(SUFFIX), ex
    assert ex["model"] is None
    assert body["draft"] == rule_body["draft"]
    assert [q["id"] for q in body["questions"]] == [q["id"] for q in rule_body["questions"]]
    assert body["ready"] == rule_body["ready"]


@pytest.mark.parametrize("domain", ["schedule", "finance"])
@pytest.mark.parametrize("name,make,code", RESPONSE_CASES, ids=[c[0] for c in RESPONSE_CASES])
def test_response_problems_fall_back(db_url, rule_drafts, domain, name, make, code):
    fake = FakeClient(make(domain))
    with app_with(db_url, fake) as c:
        body = describe(c, domain)
    assert len(fake.calls) == 1
    assert_fell_back(body, rule_drafts[domain], code)


@pytest.mark.parametrize("domain", ["schedule", "finance"])
@pytest.mark.parametrize("variant", ["extra_key", "missing_key", "wrong_type", "bad_enum", "array_root", "null_root"])
def test_schema_invalid_json_falls_back(db_url, rule_drafts, domain, variant):
    fake = FakeClient(text_response(_bad_schema_variants(domain)[variant]))
    with app_with(db_url, fake) as c:
        body = describe(c, domain)
    assert_fell_back(body, rule_drafts[domain], "AI_SCHEMA_MISMATCH")


@pytest.mark.parametrize("domain", ["schedule", "finance"])
@pytest.mark.parametrize("name,exc,code", EXC_CASES, ids=[c[0] for c in EXC_CASES])
def test_sdk_exceptions_fall_back(db_url, rule_drafts, domain, name, exc, code):
    fake = FakeClient(exc=exc)
    with app_with(db_url, fake) as c:
        body = describe(c, domain)
    assert_fell_back(body, rule_drafts[domain], code)
    if code == "AI_API_ERROR":
        assert str(exc.status_code) in body["extractor"]["fallback_message"]


@pytest.mark.parametrize("domain", ["schedule", "finance"])
def test_factory_raising_and_missing_credentials_fall_back(db_url, rule_drafts, domain):
    def boom():
        raise RuntimeError("no config")
    with TestClient(make_app(db_url, intake_ai_enabled=True, intake_ai_client_factory=boom)) as c:
        assert c.get(f"{IN}/capabilities").json()["ai_reason"] == "AI_NO_CREDENTIALS"
        assert_fell_back(describe(c, domain), rule_drafts[domain], "AI_NO_CREDENTIALS")
    nocred = FakeClient(text_response(sched_ai()), api_key=None)
    with app_with(db_url, nocred) as c:
        assert_fell_back(describe(c, domain), rule_drafts[domain], "AI_NO_CREDENTIALS")
    assert nocred.calls == []


@pytest.mark.parametrize("domain", ["schedule", "finance"])
def test_ai_disabled_on_server_and_not_requested(db_url, rule_drafts, domain):
    fake = FakeClient(text_response(sched_ai()))
    with TestClient(make_app(db_url, intake_ai_enabled=False, intake_ai_client_factory=lambda: fake)) as c:
        assert_fell_back(describe(c, domain), rule_drafts[domain], "AI_DISABLED")
    with app_with(db_url, fake) as c:
        body = describe(c, domain, use_ai=False)
        assert body["extractor"]["requested"] == "rule" and body["extractor"]["fallback_code"] is None
        assert body["draft"] == rule_drafts[domain]["draft"]
    assert fake.calls == []


def test_success_schedule_typed_numbers_win_and_flow_solves(db_url):
    fake = FakeClient(text_response(sched_ai()))
    with app_with(db_url, fake) as c:
        body = describe(c, "schedule")
        ex = body["extractor"]
        assert ex["used"] == "ai+rule" and ex["model"] == "claude-opus-5-5" and ex["fallback_code"] is None
        kw = fake.calls[0]
        assert kw["messages"] == [{"role": "user", "content": SCHEDULE_TEXT}]
        for banned in ("thinking", "temperature", "top_p", "top_k", "tool_choice", "tools"):
            assert banned not in kw
        tasks = {t["name"]: t for t in body["draft"]["tasks"]}
        # typed "2-3 days" wins over the AI's 4 days
        gr = tasks["Gather requirements"]["duration"]
        assert (gr["optimistic"], gr["likely"], gr["pessimistic"], gr["unit"]) == (2, 2.5, 3, "days")
        codes = [n["code"] for n in body["notes"]]
        assert "KEPT_TYPED_NUMBER" in codes and "AI_REFERENCE_DROPPED" in codes and "AI_NOTE" in codes
        # AI-only task added with capped confidence, not found in the text -> 0.5
        key = tasks["Write release notes"]["key"]
        prov = body["draft"]["provenance"]
        ai_conf = [p["confidence"] for k, p in prov.items() if k.startswith(f"/tasks/{key}/") and p["source"] == "ai"]
        assert ai_conf and max(ai_conf) <= 0.8
        assert tasks["Write release notes"]["after"] == [tasks["Testing"]["key"]]
        # answer every question with its default, build, create, solve, independent check
        draft, qs = body["draft"], body["questions"]
        r = c.post(f"{IN}/schedule/answer", json={"draft": draft, "context": CTX_JSON,
                                                  "answers": [{"question_id": q["id"], "use_default": True}
                                                              for q in qs if q.get("default") is not None]})
        assert r.status_code == 200, r.text
        b = c.post(f"{IN}/schedule/build", json={"draft": r.json()["draft"], "context": CTX_JSON}).json()
        assert b["ready"], b
        assert b["problem"]["metadata"]["intake"]["extractor"] == "ai+rule"
        solve_and_check(c, b["problem"])


def test_success_finance_typed_numbers_win_and_plan_runs(db_url):
    out = fin_ai()
    out["expenses"].append({"name": "Maid and cook", "category": "living", "amount": {"low": 8000, "high": 8000},
                            "frequency": "monthly", "essential": True, "source_quote": "invented",
                            "confidence": 0.99})
    fake = FakeClient(text_response(out))
    with app_with(db_url, fake) as c:
        body = describe(c, "finance")
        assert body["extractor"]["used"] == "ai+rule"
        maid = next(e for e in body["draft"]["expenses"] if e["name"] == "Maid and cook")
        prov = body["draft"]["provenance"][f"/expenses/{maid['key']}/amount"]
        assert prov["source"] == "ai" and prov["confidence"] <= 0.5     # quote not in the text
        inc = body["draft"]["incomes"][0]
        assert inc["amount"] == {"low": 120000, "high": 120000}        # typed "1.2 lakh" beats AI 125000
        assert any(n["code"] == "KEPT_TYPED_NUMBER" for n in body["notes"])
        b = c.post(f"{IN}/finance/build", json={"draft": body["draft"], "context": FIN_CTX_JSON}).json()
        assert b["ready"], b
        assert b["plan"]["metadata"]["intake"]["extractor"] == "ai+rule"
        r = c.post(f"{API}/finance/plans", json=b["plan"])
        assert r.status_code == 201, r.text
        r = c.post(f"{API}/finance/plans/{r.json()['id']}/runs", json={"seed": 0, "simulation": {"n_paths": 300}})
        run = wait_fin_run(c, r.json()["run_id"])
        assert run["status"] == "completed" and run["feasibility"] == "feasible", run


def test_merged_draft_invalid_discards_ai(db_url, rule_drafts):
    """An AI task that depends on itself makes the merged draft invalid -> AI result discarded."""
    out = sched_ai()
    out["tasks"].append({"name": "Loop", "milestone": False,
                         "duration": {"low": 1, "likely": 1, "high": 1, "unit": "days"}, "after": ["Loop"],
                         "resources": [], "resource_mode": "any", "deadline": None, "deadline_hard": False,
                         "earliest_start": None, "group": None, "source_quote": "x", "confidence": 0.9})
    fake = FakeClient(text_response(out))
    with app_with(db_url, fake) as c:
        body = describe(c, "schedule")
    ex = body["extractor"]
    if ex["used"] == "ai+rule":
        # acceptable only if the self-reference was dropped as an unresolved reference
        loop = next(t for t in body["draft"]["tasks"] if t["name"] == "Loop")
        assert loop["key"] not in loop["after"]
    else:
        assert_fell_back(body, rule_drafts["schedule"], "AI_SCHEMA_MISMATCH")


def test_untrusted_ai_values_are_clipped(db_url):
    out = sched_ai()
    out["tasks"][4]["duration"] = {"low": 1e12, "likely": 1e12, "high": 1e12, "unit": "weeks"}
    out["tasks"][4]["confidence"] = 7.0
    out["resources"].append({"name": "Robot", "kind": "machine", "count": 100000, "source_quote": "Robot",
                             "confidence": 0.9})
    fake = FakeClient(text_response(out))
    with app_with(db_url, fake) as c:
        body = describe(c, "schedule")
        assert body["extractor"]["used"] == "ai+rule", body["extractor"]
        t = next(t for t in body["draft"]["tasks"] if t["name"] == "Write release notes")
        assert t["duration"]["pessimistic"] <= 10000
        robot = next(r for r in body["draft"]["resources"] if r["name"] == "Robot")
        assert robot["count"] <= 50
        assert all(p["confidence"] <= 1 for p in body["draft"]["provenance"].values())
        b = c.post(f"{IN}/schedule/build", json={"draft": body["draft"], "context": CTX_JSON})
        assert b.status_code == 200, b.text


def test_no_user_text_or_ai_output_in_logs(db_url, caplog):
    marker_out = sched_ai(notes=["SECRET-AI-NOTE-42"])
    fake = FakeClient(text_response(marker_out))
    secret = SCHEDULE_TEXT + "\n6. Pay vendor ZQX-UNIQUE-7781 2 hours"
    caplog.set_level(logging.DEBUG)
    logging.getLogger("anthropic").setLevel(logging.DEBUG)
    with app_with(db_url, fake) as c:
        r = c.post(f"{IN}/schedule/describe", json={"text": secret, "context": CTX_JSON, "use_ai": True})
        assert r.status_code == 200
        fake.exc = anthropic.RateLimitError("ZQX-UNIQUE-7781", response=_status(429), body=None)
        r = c.post(f"{IN}/schedule/describe", json={"text": secret, "context": CTX_JSON, "use_ai": True})
        assert r.json()["extractor"]["fallback_code"] == "AI_RATE_LIMITED"
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "ZQX-UNIQUE-7781" not in logged
    assert "SECRET-AI-NOTE-42" not in logged
    assert "Gather requirements" not in logged
