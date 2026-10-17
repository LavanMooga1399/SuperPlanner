"""Shared fixtures for the intake tests: example texts, a fake Anthropic client, app factory."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from superplanner.api.config import Settings
from superplanner.api.main import create_app
from superplanner.intake import ExtractContext

API = "/api/v1"
CTX = ExtractContext(today=date(2026, 10, 17), utc_offset="+05:30", locale="en-IN", currency="INR", kind="project")
CTX_JSON = {"today": "2026-10-17", "utc_offset": "+05:30", "locale": "en-IN", "currency": "INR", "kind": "project"}
FIN_CTX = ExtractContext(today=date(2026, 10, 17), locale="en-IN", currency="INR")
FIN_CTX_JSON = {"today": "2026-10-17", "locale": "en-IN", "currency": "INR"}

SCHEDULE_TEXT = ("Website relaunch starting next Monday. Ravi and Priya are on the team.\n"
                 "1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n"
                 "3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026")
FINANCE_TEXT = ("I'm 34, take home about 1.2 lakh a month and my wife earns 60k. Household costs are 70-80k a month, "
                "school fees 18k every quarter. Car loan EMI 10k, about 3 lakh left at 9%. We have 6 lakh in savings "
                "and 8L in mutual funds. We want 15 lakh for a flat down payment in 3 years and to retire at 60. "
                "Moderate risk.")
STUDY_TEXT = ("I have 90 days to prepare for an exam. I can study three hours on weekdays and eight hours on "
              "weekends. I need to finish the syllabus, revise everything twice, and complete ten mock tests.")
EXAMPLE_ANSWERS = [{"question_id": "SCHED_WHO:/tasks/t4/resources", "value": ["r_ravi"]},
                   {"question_id": "SCHED_WORKING_TIME:/working_time", "use_default": True},
                   {"question_id": "SCHED_SEQUENTIAL:-", "value": True},
                   {"question_id": "SCHED_PEOPLE:-", "skip": True}]
TABLE_TEXT = ("Task\tDuration\tAfter\tOwner\tDue\nRequirements\t2-3 d\t\tPriya\t\nDesign\t1 w\tRequirements\tPriya\t\n"
              "Build\t2 w\tDesign\tRavi\t15/12/2026")


def make_app(db_url: str, **overrides: Any):
    overrides.setdefault("intake_ai_enabled", False)
    return create_app(Settings(database_url=db_url, **overrides))


# ---------------------------------------------------------------- fake SDK client

class FakeMessages:
    def __init__(self, owner: "FakeClient"):
        self.owner = owner

    def create(self, **kwargs: Any) -> Any:
        self.owner.calls.append(kwargs)
        if self.owner.exc is not None:
            raise self.owner.exc
        return self.owner.response


class FakeClient:
    def __init__(self, response: Any = None, exc: BaseException | None = None, *, api_key: str | None = "sk-test",
                 auth_token: str | None = None, credentials: Any = None):
        self.api_key = api_key
        self.auth_token = auth_token
        self.credentials = credentials
        self.response = response
        self.exc = exc
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=FakeMessages(self))


def text_response(obj: Any, stop_reason: str = "end_turn", raw: str | None = None) -> Any:
    return SimpleNamespace(stop_reason=stop_reason, content=[
        SimpleNamespace(type="text", text=raw if raw is not None else json.dumps(obj))])


def ai_schedule_output(**over: Any) -> dict[str, Any]:
    def task(name, low, likely, high, unit, quote, after=(), resources=(), milestone=False, deadline=None):
        return {"name": name, "milestone": milestone,
                "duration": {"low": low, "likely": likely, "high": high, "unit": unit},
                "after": list(after), "resources": list(resources), "resource_mode": "any", "deadline": deadline,
                "deadline_hard": False, "earliest_start": None, "group": None, "source_quote": quote,
                "confidence": 0.9}
    out = {
        "kind": "project", "name": "Website relaunch", "start_date": "2026-10-19", "working_time": None,
        "tasks": [task("Gather requirements", 4, 4, 4, "days", "Gather requirements - 2-3 days", resources=["Priya"]),
                  task("Design", 1, 1, 1, "weeks", "Design 1 week", after=["Gather requirements"]),
                  task("Build the site", 2, 2, 2, "weeks", "Build the site: 2 weeks", after=["Design"]),
                  task("Testing", 3, None, 5, "days", "Testing 3-5 days", after=["Build the site"]),
                  task("Write release notes", 2, 2, 2, "hours", "not in the text", after=["Testing", "Ghost task"]),
                  task("Launch", None, None, None, None, "Launch by 15 Dec 2026", milestone=True,
                       deadline="2026-12-15", after=["Testing"])],
        "resources": [{"name": "Ravi", "kind": "person", "count": 1, "source_quote": "Ravi", "confidence": 0.9},
                      {"name": "Priya", "kind": "person", "count": 1, "source_quote": "Priya", "confidence": 0.95}],
        "notes": ["Launch date looks fixed."]}
    out.update(over)
    return out


def ai_finance_output(**over: Any) -> dict[str, Any]:
    amt = lambda lo, hi=None: {"low": lo, "high": hi if hi is not None else lo}  # noqa: E731
    out = {
        "profile": {"age": 34, "retirement_age": 60, "risk_tolerance": 3, "source_quote": "I'm 34"},
        "incomes": [{"name": "Salary", "kind": "salary", "amount": amt(125000), "frequency": "monthly", "is_gross": False,
                     "source_quote": "take home about 1.2 lakh a month", "confidence": 0.9}],
        "expenses": [{"name": "Household costs", "category": "living", "amount": amt(70000, 80000),
                      "frequency": "monthly", "essential": True, "source_quote": "Household costs", "confidence": 0.9},
                     {"name": "Maid and cook", "category": "living", "amount": amt(8000), "frequency": "monthly",
                      "essential": True, "source_quote": "invented", "confidence": 0.99}],
        "debts": [], "holdings": [], "goals": [], "emergency_fund_months": None, "notes": []}
    out.update(over)
    return out


def load_finance_helpers():
    """`tests/finance/fin_helpers.py` (denylist) loaded by path so module names never clash."""
    path = Path(__file__).resolve().parents[1] / "finance" / "fin_helpers.py"
    spec = importlib.util.spec_from_file_location("intake_fin_helpers", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pick(questions: list[dict], qid: str) -> dict:
    return next(q for q in questions if q["id"] == qid)
