"""F2: what-if runs (FINANCE.md 13, 18.2): defaults, base_result_id snapshot [R14], replace_active, 409/412/404/422,
the stored plan never changes."""

from __future__ import annotations

import copy

import pytest

from apifin_helpers import FAST, FIN, SLOW, assert_error
from sqlalchemy import func, select

from superplanner import finance
from superplanner.api.finance.db_models import FinancePlanVersionRow, FinanceResultRow

EXTRA = {"extra_monthly_savings": 5000}


def _count(fin, model, **where) -> int:
    with fin.ctx.db.read() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return int(s.scalar(q))


def test_what_if_defaults_label_and_plan_unchanged(fin):
    plan = fin.instantiate()
    before = fin.c.get(f"{FIN}/plans/{plan['id']}").json()
    r = fin.c.post(f"{FIN}/plans/{plan['id']}/what-if", json={"changes": EXTRA})
    assert r.status_code == 202, r.text
    created = r.json()
    assert set(created) == {"run_id", "status", "plan_version_id", "status_url", "events_url"}
    run = fin.wait(created["run_id"])
    assert run["status"] == "completed" and run["kind"] == "what_if"
    # what-if defaults (18.2)
    assert run["request"]["simulation"]["n_paths"] == 1000
    assert run["request"]["compute_fixes"] is False and run["request"]["calibration_rounds"] == 1
    assert run["what_if"]["extra_monthly_savings"] == 5000
    assert run["label"] and "5,000" in run["label"]
    events = fin.events(run["id"])
    assert events[0]["type"] == "run_queued" and events[0]["kind"] == "what_if"
    # the editable plan is untouched
    assert fin.c.get(f"{FIN}/plans/{plan['id']}").json() == before
    # what-if snapshot kind, derived document contains the whatif_ income
    with fin.ctx.db.read() as s:
        pv = s.get(FinancePlanVersionRow, run["plan_version_id"])
        assert pv.kind == "what_if" and pv.base_version == 1
        assert any(i["id"] == "whatif_extra" for i in pv.document["incomes"])
    res = fin.result(run["result_id"])
    assert res["kind"] == "what_if" and res["what_if"]["extra_monthly_savings"] == 5000
    assert res["label"] == run["label"] and res["base_plan_version"] == 1
    assert any(i["id"] == "whatif_extra" for i in res["plan"]["incomes"])


def test_explicit_run_fields_override_what_if_defaults(fin):
    plan = fin.instantiate()
    body = {"changes": {**EXTRA, "label": "My label"},
            "run": {"simulation": {"n_paths": 300}, "calibration_rounds": 0, "compute_fixes": False}}
    run = fin.wait(fin.c.post(f"{FIN}/plans/{plan['id']}/what-if", json=body).json()["run_id"])
    assert run["request"]["simulation"]["n_paths"] == 300 and run["request"]["calibration_rounds"] == 0
    assert run["label"] == "My label"
    # only `run.time_limit_seconds` given: what-if defaults still apply to the rest
    body = {"changes": EXTRA, "run": {"time_limit_seconds": 20}}
    run = fin.wait(fin.c.post(f"{FIN}/plans/{plan['id']}/what-if", json=body).json()["run_id"])
    assert run["request"]["time_limit_seconds"] == 20 and run["request"]["simulation"]["n_paths"] == 1000


def test_what_if_snapshots_never_reused(fin):
    plan = fin.instantiate()
    a = fin.wait(fin.what_if(plan["id"], EXTRA).json()["run_id"])
    b = fin.wait(fin.what_if(plan["id"], EXTRA).json()["run_id"])
    assert a["plan_version_id"] != b["plan_version_id"]
    assert _count(fin, FinancePlanVersionRow, kind="what_if") == 2


def test_base_result_id_uses_baseline_snapshot(fin):
    """[R14]: edit the plan between baseline and what-if; the what-if is derived from the baseline snapshot."""
    plan = fin.instantiate()
    pid = plan["id"]
    base = fin.solve(pid, FAST)
    base_res = fin.result(base["result_id"])
    doc = copy.deepcopy(plan["plan"])
    doc["incomes"][0]["amount"] = doc["incomes"][0]["amount"] + 7777
    doc["goals"][0]["target_amount"] = 123456
    assert fin.put(pid, doc, 1).status_code == 200

    changes = {**EXTRA, "goal_overrides": [{"goal_id": "car", "target_month": "2032-06"}]}
    snap_run = fin.wait(fin.what_if(pid, changes, base_result_id=base["result_id"]).json()["run_id"])
    assert snap_run["status"] == "completed"
    got = fin.result(snap_run["result_id"])
    expected = finance.apply_what_if(finance.FinancePlan.model_validate(base_res["plan"]),
                                     finance.WhatIfChanges.model_validate(changes)).model_dump(mode="json")
    assert got["plan"] == expected
    assert got["base_plan_version"] == 1
    assert got["plan"]["goals"][0]["target_amount"] != 123456

    # without base_result_id: the current document (version 2) is the base
    cur_run = fin.wait(fin.what_if(pid, changes).json()["run_id"])
    cur = fin.result(cur_run["result_id"])
    assert cur["plan"]["goals"][0]["target_amount"] == 123456 and cur["base_plan_version"] == 2
    # the stored plan is unchanged by both what-ifs
    rec = fin.c.get(f"{FIN}/plans/{pid}").json()
    assert rec["version"] == 2 and rec["plan"]["goals"][0]["target_month"] == plan["plan"]["goals"][0]["target_month"]
    assert not any(i["id"].startswith("whatif_") for i in rec["plan"]["incomes"])


def test_replace_active_cancels_running_what_if(fin):
    plan = fin.instantiate()
    pid = plan["id"]
    first = fin.what_if(pid, EXTRA, run=copy.deepcopy(SLOW)).json()["run_id"]
    fin.wait_status(first, "running")
    # without replace_active: 409 with the active run id
    err = assert_error(fin.what_if(pid, {"extra_monthly_savings": 6000}), 409, "RUN_ALREADY_ACTIVE")
    assert err["details"]["run_id"] == first
    r = fin.what_if(pid, {"extra_monthly_savings": 7000}, replace_active=True)
    assert r.status_code == 202, r.text
    second = r.json()["run_id"]
    assert fin.run(first)["cancel_requested"] is True
    a, b = fin.wait(first, timeout=20), fin.wait(second)
    assert a["status"] == "cancelled" and a["result_id"] is None
    assert b["status"] == "completed" and b["result_id"]
    items = fin.c.get(f"{FIN}/plans/{pid}/results?kind=what_if").json()["items"]
    assert [i["run_id"] for i in items] == [second]


@pytest.mark.inline_jobs
def test_replace_active_cancels_queued_what_if(fin):
    plan = fin.instantiate()
    pid = plan["id"]
    # occupy both workers so the first what-if stays queued
    import threading

    gate = threading.Event()
    for i in range(fin.ctx.settings.run_workers):
        fin.ctx.executor.submit(f"blocker_{i}", lambda _r, _e: gate.wait(20))
    try:
        first = fin.what_if(pid, EXTRA).json()["run_id"]
        assert fin.run(first)["status"] == "queued"
        second = fin.what_if(pid, {"extra_monthly_savings": 9000}, replace_active=True).json()["run_id"]
        run = fin.run(first)
        assert run["status"] == "cancelled" and run["started_at"] is None
        assert [e["type"] for e in fin.events(first)] == ["run_queued", "run_cancelled"]
    finally:
        gate.set()
    assert fin.wait(second)["status"] == "completed"
    fin.worker_done(first)
    assert fin.run(first)["status"] == "cancelled"


def test_active_baseline_blocks_what_if_even_with_replace(fin):
    plan = fin.instantiate()
    rid = fin.start_run(plan["id"], SLOW)["run_id"]
    err = assert_error(fin.what_if(plan["id"], EXTRA, replace_active=True), 409, "RUN_ALREADY_ACTIVE")
    assert err["details"]["run_id"] == rid
    assert fin.run(rid)["cancel_requested"] is False
    fin.c.post(f"{FIN}/runs/{rid}/cancel")
    assert fin.wait(rid)["status"] == "cancelled"


def test_what_if_errors(fin):
    plan = fin.instantiate()
    pid = plan["id"]
    assert_error(fin.what_if("fp_nope", EXTRA), 404, "NOT_FOUND")
    assert_error(fin.what_if(pid, EXTRA, base_result_id="fres_nope"), 404, "NOT_FOUND")
    err = assert_error(fin.what_if(pid, EXTRA, expected_plan_version=5), 412, "VERSION_MISMATCH")
    assert err["details"]["current_version"] == 1
    assert fin.what_if(pid, {"extra_monthly_savings": 1}, expected_plan_version=1).status_code == 202
    fin.wait(fin.c.get(f"{FIN}/plans/{pid}/runs").json()["items"][0]["id"])
    err = assert_error(fin.what_if(pid, {"goal_overrides": [{"goal_id": "nope", "target_amount": 1}]}), 422,
                       "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", "changes"]
    assert_error(fin.what_if(pid, {"risk_tolerance": 9}), 422, "VALIDATION_ERROR")
    assert_error(fin.what_if(pid, {"bogus": 1}), 422, "VALIDATION_ERROR")
    assert_error(fin.c.post(f"{FIN}/plans/{pid}/what-if", json={}), 422, "VALIDATION_ERROR")
    # derived plan fails preflight -> 422 PREFLIGHT_FAILED, nothing queued or snapshotted
    n_runs = len(fin.c.get(f"{FIN}/plans/{pid}/runs").json()["items"])
    err = assert_error(fin.what_if(pid, {"goal_overrides": [{"goal_id": "car", "target_month": "2020-01"}]}), 422,
                       "PREFLIGHT_FAILED")
    assert any(i["code"] == "GOAL_TOO_SOON" for i in err["details"]["issues"])
    assert len(fin.c.get(f"{FIN}/plans/{pid}/runs").json()["items"]) == n_runs
    # base_result_id of another plan -> 404; a what-if result as base -> 422
    other = fin.instantiate()
    other_res = fin.solve(other["id"])["result_id"]
    assert_error(fin.what_if(pid, EXTRA, base_result_id=other_res), 404, "NOT_FOUND")
    wi = fin.wait(fin.what_if(pid, EXTRA).json()["run_id"])
    err = assert_error(fin.what_if(pid, EXTRA, base_result_id=wi["result_id"]), 422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", "base_result_id"]


def test_preflight_failure_does_not_cancel_replaced_run(fin):
    plan = fin.instantiate()
    pid = plan["id"]
    first = fin.what_if(pid, EXTRA, run=copy.deepcopy(SLOW)).json()["run_id"]
    bad = {"goal_overrides": [{"goal_id": "car", "target_month": "2020-01"}]}
    assert_error(fin.what_if(pid, bad, replace_active=True), 422, "PREFLIGHT_FAILED")
    assert fin.run(first)["cancel_requested"] is False   # the rejected request rolled back entirely
    fin.c.post(f"{FIN}/runs/{first}/cancel")
    assert fin.wait(first)["status"] == "cancelled"
    assert _count(fin, FinanceResultRow) == 0
