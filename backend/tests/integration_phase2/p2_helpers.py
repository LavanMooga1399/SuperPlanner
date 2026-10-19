"""Phase 2 integration helpers: app factory, contexts, fake Anthropic client, corpus scoring, and the two
independent checkers of the earlier work packages loaded by path (read-only reuse, no name clashes)."""

from __future__ import annotations

import importlib.util
import json
import re
import time
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from superplanner.api.config import Settings
from superplanner.api.main import create_app
from superplanner.intake import ExtractContext

API = "/api/v1"
IN = f"{API}/intake"
FIN = f"{API}/finance"
TODAY = date(2026, 10, 17)
CTX_JSON = {"today": "2026-10-17", "utc_offset": "+05:30", "locale": "en-IN", "currency": "INR", "kind": "project"}
FIN_CTX_JSON = {"today": "2026-10-17", "locale": "en-IN", "currency": "INR"}
TESTS = Path(__file__).resolve().parents[1]


def ctx(locale: str = "en-IN", kind: str | None = None) -> ExtractContext:
    return ExtractContext(today=TODAY, utc_offset="+05:30", locale=locale, currency="INR", kind=kind)


def make_app(db_url: str, **overrides: Any):
    overrides.setdefault("intake_ai_enabled", False)
    return create_app(Settings(database_url=db_url, **overrides))


def _load(name: str, rel: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TESTS / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SCHED_CHECK: ModuleType | None = None
_FIN_CHECK: ModuleType | None = None


def sched_checker() -> ModuleType:
    """`tests/integration/int_helpers.py` (independent schedule checker, A 5.1)."""
    global _SCHED_CHECK
    if _SCHED_CHECK is None:
        _SCHED_CHECK = _load("p2_int_helpers", "integration/int_helpers.py")
    return _SCHED_CHECK


def fin_checker() -> ModuleType:
    """`tests/integration_finance/finint_helpers.py` (independent finance checker, updated by P1)."""
    global _FIN_CHECK
    if _FIN_CHECK is None:
        _FIN_CHECK = _load("p2_finint_helpers", "integration_finance/finint_helpers.py")
    return _FIN_CHECK


# ---------------------------------------------------------------- polling

def wait_run(client, run_id: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run = client.get(f"{API}/solver-runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"run {run_id} still {run['status']}"
        time.sleep(0.1)


def wait_fin_run(client, run_id: str, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run = client.get(f"{FIN}/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"finance run {run_id} still {run['status']}"
        time.sleep(0.1)


def solve_and_check(client, problem: dict[str, Any], **req: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """POST /problems, run the solver, fetch the primary schedule and run the independent checker on it."""
    r = client.post(f"{API}/problems", json=problem)
    assert r.status_code == 201, r.text
    rec = r.json()
    req.setdefault("time_limit_seconds", 3)
    r = client.post(f"{API}/problems/{rec['id']}/solver-runs", json=req)
    assert r.status_code == 202, r.text
    run = wait_run(client, r.json()["run_id"])
    assert run["status"] == "completed", run
    assert run["feasibility"] == "feasible", run
    sch = client.get(f"{API}/schedules/{run['primary_schedule_id']}").json()
    pls = [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")} for p in sch["placements"]]
    errs = sched_checker().independent_check(rec["problem"], pls, sch["horizon_start"])
    assert errs == [], errs
    return rec, run, sch


# ---------------------------------------------------------------- fake SDK client

class _FakeMessages:
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
        self.api_key, self.auth_token, self.credentials = api_key, auth_token, credentials
        self.response, self.exc = response, exc
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=_FakeMessages(self))


def text_response(obj: Any = None, stop_reason: str = "end_turn", raw: str | None = None, blocks=None) -> Any:
    if blocks is None:
        blocks = [SimpleNamespace(type="text", text=raw if raw is not None else json.dumps(obj))]
    return SimpleNamespace(stop_reason=stop_reason, content=blocks)


# ---------------------------------------------------------------- corpus scoring

_UNIT_MIN = {"minutes": 1, "hours": 60, "days": 480, "weeks": 2400}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def dur_minutes(o: float, m: float, p: float, unit: str) -> tuple[float, float, float]:
    f = _UNIT_MIN[unit]
    return (round(o * f, 3), round(m * f, 3), round(p * f, 3))


class Score:
    def __init__(self) -> None:
        self.by_field: dict[str, list[int]] = {}
        self.misses: list[str] = []

    def add(self, fld: str, ok: bool, where: str, detail: str = "") -> None:
        tot = self.by_field.setdefault(fld, [0, 0])
        tot[0] += int(ok)
        tot[1] += 1
        if not ok:
            self.misses.append(f"{where} {fld}: {detail}")

    def ratio(self, fld: str | None = None) -> float:
        if fld is not None:
            ok, n = self.by_field.get(fld, [0, 0])
            return ok / n if n else 1.0
        ok = sum(v[0] for v in self.by_field.values())
        n = sum(v[1] for v in self.by_field.values())
        return ok / n if n else 1.0

    def table(self) -> str:
        rows = [f"{k:<16} {v[0]:>3}/{v[1]:<3} {v[0] / v[1]:.2f}" for k, v in sorted(self.by_field.items())]
        return "\n".join(rows + [f"{'TOTAL':<16} {self.ratio():.3f}"])


def _find_task(tasks, name: str):
    n = norm(name)
    exact = [t for t in tasks if norm(t.name) == n]
    if exact:
        return exact[0], True
    fuzzy = [t for t in tasks if n in norm(t.name) or norm(t.name) in n]
    return (fuzzy[0], False) if fuzzy else (None, False)


def score_schedule(case, draft, sc: Score) -> None:
    w = case.id
    by_key = {t.key: t for t in draft.tasks}
    res_by_key = {r.key: r for r in draft.resources}
    for name, exp in case.tasks.items():
        t, exact = _find_task(draft.tasks, name)
        sc.add("task_found", t is not None, w, name)
        if t is None:
            for f in exp:
                sc.add(f, False, w, f"{name}: task missing")
            continue
        sc.add("task_name", exact, w, f"expected {name!r}, got {t.name!r}")
        for f, v in exp.items():
            if f == "duration":
                got = None if t.duration is None else dur_minutes(t.duration.optimistic, t.duration.likely,
                                                                  t.duration.pessimistic, t.duration.unit)
                sc.add(f, got == dur_minutes(*v), w, f"{name}: expected {v}, got {t.duration}")
            elif f == "after":
                got = {norm(by_key[k].name) for k in t.after if k in by_key}
                sc.add(f, got == {norm(x) for x in v}, w, f"{name}: expected {v}, got {sorted(got)}")
            elif f == "resources":
                got = {norm(res_by_key[k].name) for k in t.resources if k in res_by_key}
                sc.add(f, got == {norm(x) for x in v}, w, f"{name}: expected {v}, got {sorted(got)}")
            elif f == "deadline":
                got = None if t.deadline is None else t.deadline.isoformat()
                sc.add(f, got == v, w, f"{name}: expected {v}, got {got}")
            else:
                sc.add(f, getattr(t, f) == v, w, f"{name}: expected {v}, got {getattr(t, f)}")
    for rname, count in case.resources.items():
        r = next((x for x in draft.resources if norm(x.name) == norm(rname)), None)
        sc.add("resource", r is not None and r.count == count, w,
               f"expected {rname} x{count}, got {[(x.name, x.count) for x in draft.resources]}")
    for f, v in case.top.items():
        wt = draft.working_time
        if f == "kind":
            got: Any = draft.kind
        elif f == "start_date":
            got = None if draft.start_date is None else draft.start_date.isoformat()
        elif f == "n_tasks":
            got = len(draft.tasks)
        elif f == "days":
            got = None if wt is None else list(wt.days)
        elif f == "windows":
            got = None if wt is None else [(x.start, x.end) for x in wt.windows]
        elif f == "weekend_windows":
            got = None if wt is None or wt.weekend_windows is None else [(x.start, x.end) for x in wt.weekend_windows]
        else:
            raise KeyError(f)
        sc.add(f, got == v, w, f"expected {v}, got {got}")


def _item_value(it, f: str) -> Any:
    v = getattr(it, f)
    if f in ("amount", "balance", "emi", "target") and v is not None:
        return (round(v.low, 2), round(v.high, 2))
    return v


def score_finance(case, resp, sc: Score) -> None:
    w = case.id
    d = resp.draft
    used: set[tuple[str, str]] = set()
    for coll, exp in case.items:
        cands = [it for it in getattr(d, coll) if (coll, it.key) not in used]

        def hits(it) -> int:
            return sum(1 for f, v in exp.items() if _item_value(it, f) == (tuple(v) if isinstance(v, tuple) else v))
        best = max(cands, key=hits, default=None)
        if best is not None and hits(best) == 0:
            best = None         # nothing in common: the expected item was not read
        sc.add(f"{coll}_found", best is not None, w, f"{exp}")
        if best is None:
            for f in exp:
                sc.add(f"{coll}.{f}", False, w, "item missing")
            continue
        used.add((coll, best.key))
        for f, v in exp.items():
            got = _item_value(best, f)
            sc.add(f"{coll}.{f}", got == (tuple(v) if isinstance(v, tuple) else v), w,
                   f"expected {v}, got {got} ({best.name!r})")
    for coll in ("incomes", "expenses", "debts", "holdings", "goals"):
        for it in getattr(d, coll):
            sc.add("no_spurious_item", (coll, it.key) in used, w,
                   f"unexpected {coll[:-1]} {it.name!r} {_item_value(it, 'amount' if coll != 'goals' and coll != 'debts' else ('target' if coll == 'goals' else 'balance'))}")
    for f, v in case.profile.items():
        got = getattr(d.profile, f)
        sc.add(f"profile.{f}", got == v, w, f"expected {v}, got {got}")
    for f, v in case.top.items():
        if f == "emergency_fund_months":
            got: Any = d.emergency_fund_months
            sc.add(f, got is not None and abs(got - v) < 0.01, w, f"expected {v}, got {got}")
        elif f == "questions":
            codes = {q.code for q in resp.questions}
            for code in v:
                sc.add("question", code in codes, w, f"expected {code} in {sorted(codes)}")
        elif f == "notes":
            codes = {n.code for n in resp.notes}
            for code in v:
                sc.add("note", code in codes, w, f"expected {code} in {sorted(codes)}")
        else:
            raise KeyError(f)
