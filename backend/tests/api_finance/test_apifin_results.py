"""F2: results list/get, compare (route order), CSV, send-to-planner, templates -> feasible runs, independent
validator gate, OpenAPI paths (FINANCE.md 14, 16, 18.2)."""

from __future__ import annotations

import csv
import io

import pytest
from apifin_helpers import API, FAST, FIN, assert_error, minimal_plan
from sqlalchemy import select

from superplanner import finance
from superplanner.api.db import AuditEventRow
from superplanner.api.finance import run_service

CSV_HEADER = ["month", "action", "goal_id", "goal_name", "priority", "asset_class_id", "asset_class_name",
              "amount_today_money", "amount_expected_nominal"]
SUMMARY_KEYS = {"id", "plan_id", "run_id", "plan_version_id", "base_plan_version", "kind", "label", "feasibility",
                "goals_total", "goals_on_track", "goals_at_risk", "goals_off_track", "monthly_contribution_now",
                "created_at", "what_if"}


def _infeasible_plan() -> dict:
    doc = minimal_plan("Short of cash")
    doc["incomes"][0]["amount"] = 10000
    return doc


def test_results_list_get_and_kind_filter(fin):
    plan = fin.instantiate()
    pid = plan["id"]
    base = fin.solve(pid, FAST)
    wi = fin.wait(fin.what_if(pid, {"extra_monthly_savings": 3000}).json()["run_id"])
    items = fin.c.get(f"{FIN}/plans/{pid}/results").json()["items"]
    assert [i["id"] for i in items] == [wi["result_id"], base["result_id"]]   # newest first
    for i in items:
        assert set(i) == SUMMARY_KEYS and i["created_at"].endswith("Z") and i["plan_id"] == pid
    assert [i["id"] for i in fin.c.get(f"{FIN}/plans/{pid}/results?kind=baseline").json()["items"]] == \
        [base["result_id"]]
    assert [i["id"] for i in fin.c.get(f"{FIN}/plans/{pid}/results?kind=what_if").json()["items"]] == \
        [wi["result_id"]]
    assert_error(fin.c.get(f"{FIN}/plans/{pid}/results?kind=bogus"), 422, "VALIDATION_ERROR")
    assert_error(fin.c.get(f"{FIN}/plans/fp_nope/results"), 404, "NOT_FOUND")

    rec = fin.result(base["result_id"])
    assert set(rec) == SUMMARY_KEYS | {"result", "plan"}
    assert rec["kind"] == "baseline" and rec["what_if"] is None and rec["run_id"] == base["id"]
    assert rec["plan_version_id"] == base["plan_version_id"] and rec["base_plan_version"] == 1
    assert rec["plan"] == plan["plan"]
    result = finance.FinanceResult.model_validate(rec["result"])
    assert result.disclaimer == finance.DISCLAIMER and result.feasibility == rec["feasibility"] == "feasible"
    assert rec["goals_total"] == result.summary.goals_total == 2
    assert rec["monthly_contribution_now"] == result.summary.monthly_contribution_now
    # stored results are clean under the independent validator
    hard = [v for v in finance.validate_result(finance.FinancePlan.model_validate(rec["plan"]), result)
            if v.severity == "hard"]
    assert hard == []
    assert_error(fin.c.get(f"{FIN}/results/fres_nope"), 404, "NOT_FOUND")


def test_compare_shape_and_route_order(fin):
    plan = fin.instantiate()
    pid = plan["id"]
    a = fin.solve(pid, FAST)["result_id"]
    b = fin.wait(fin.what_if(pid, {"extra_monthly_savings": 10000}, base_result_id=a).json()["run_id"])["result_id"]
    r = fin.c.get(f"{FIN}/results/compare", params={"a": a, "b": b})
    assert r.status_code == 200, r.text
    comp = r.json()
    finance.FinanceComparison.model_validate(comp)
    assert set(comp) == {"a", "b", "totals", "goals", "what_if_b", "engine_versions_differ"}  # PHASE2 1.13
    assert comp["engine_versions_differ"] is False
    assert comp["a"]["id"] == a and comp["b"]["id"] == b and comp["b"]["kind"] == "what_if"
    assert comp["what_if_b"]["extra_monthly_savings"] == 10000
    t = comp["totals"]
    assert t["monthly_contribution_now_delta"] == pytest.approx(
        t["monthly_contribution_now_b"] - t["monthly_contribution_now_a"], abs=0.01)
    assert [g["goal_id"] for g in comp["goals"]] == ["car", "retirement"]
    for g in comp["goals"]:
        assert g["in_a"] and g["in_b"]
        assert g["success_delta"] == pytest.approx(g["success_b"] - g["success_a"], abs=1e-6)
    # not shadowed by /results/{rid}; missing params -> 422; unknown ids -> 404
    assert_error(fin.c.get(f"{FIN}/results/compare"), 422, "VALIDATION_ERROR")
    assert_error(fin.c.get(f"{FIN}/results/compare", params={"a": a}), 422, "VALIDATION_ERROR")
    assert_error(fin.c.get(f"{FIN}/results/compare", params={"a": a, "b": "fres_nope"}), 404, "NOT_FOUND")
    assert_error(fin.c.get(f"{FIN}/results/compare", params={"a": "fres_nope", "b": b}), 404, "NOT_FOUND")


def test_contributions_csv(fin):
    plan = fin.instantiate(name="CSV =Plan")
    rid = fin.solve(plan["id"], FAST)["result_id"]
    r = fin.c.get(f"{FIN}/results/{rid}/contributions.csv")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="csv-plan-{rid}-contributions.csv"'
    text = r.text
    first, rest = text.split("\r\n", 1)
    assert first == f"# {finance.DISCLAIMER}"
    rows = list(csv.reader(io.StringIO(rest)))
    assert rows[0] == CSV_HEADER
    assert len(rows) > 1 and {row[1] for row in rows[1:]} <= {"contribute", "emergency_fund", "rebalance_sell",
                                                              "rebalance_buy", "goal_withdrawal"}
    assert_error(fin.c.get(f"{FIN}/results/fres_nope/contributions.csv"), 404, "NOT_FOUND")


def test_send_to_planner(fin):
    plan = fin.instantiate()
    rid = fin.solve(plan["id"], FAST)["result_id"]
    r = fin.c.post(f"{FIN}/results/{rid}/send-to-planner", json={"months": 6, "review_every_months": 2})
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"problem_id", "record", "task_count", "skipped", "url"}
    pid = body["problem_id"]
    assert r.headers["Location"] == f"{API}/problems/{pid}"
    assert body["url"] == f"/plans/{pid}/tasks"
    assert body["record"]["id"] == pid and body["task_count"] == len(body["record"]["problem"]["tasks"]) > 0
    assert isinstance(body["skipped"], int)
    meta = body["record"]["problem"]["metadata"]
    assert meta == {"source": "finance", "finance_plan_id": plan["id"], "finance_result_id": rid}
    assert body["record"]["problem"]["domain"] == "personal_finance"

    got = fin.c.get(f"{API}/problems/{pid}")
    assert got.status_code == 200 and got.json()["id"] == pid
    report = fin.c.post(f"{API}/problems/{pid}/validate").json()
    assert report["ok"] is True
    assert not [i for i in report["issues"] if i["severity"] == "error"]
    # the scheduling home page lists it
    assert pid in [p["id"] for p in fin.c.get(f"{API}/problems").json()["items"]]
    # default body, custom name
    r = fin.c.post(f"{FIN}/results/{rid}/send-to-planner")
    assert r.status_code == 201 and r.json()["record"]["problem"]["name"].endswith("money calendar")
    r = fin.c.post(f"{FIN}/results/{rid}/send-to-planner", json={"name": "My money month"})
    assert r.json()["record"]["problem"]["name"] == "My money month"

    with fin.ctx.db.read() as s:
        rows = s.scalars(select(AuditEventRow).where(AuditEventRow.action == "finance_result.sent_to_planner")).all()
        assert len(rows) == 3
        assert rows[0].entity_type == "finance_result" and rows[0].entity_id == rid
        assert rows[0].details == {"problem_id": pid}


def test_send_to_planner_errors(fin):
    plan = fin.create(_infeasible_plan())
    run = fin.solve(plan["id"], FAST)
    assert run["feasibility"] == "infeasible"
    res = fin.result(run["result_id"])
    assert any(v["code"] == "CASH_NEGATIVE" for v in res["result"]["violations"])
    n_problems = len(fin.c.get(f"{API}/problems").json()["items"])
    err = assert_error(fin.c.post(f"{FIN}/results/{run['result_id']}/send-to-planner", json={}), 422, "NOT_FEASIBLE")
    assert err["details"]["feasibility"] == "infeasible"
    assert len(fin.c.get(f"{API}/problems").json()["items"]) == n_problems
    assert_error(fin.c.post(f"{FIN}/results/fres_nope/send-to-planner", json={}), 404, "NOT_FOUND")
    ok = fin.instantiate()
    rid = fin.solve(ok["id"], FAST)["result_id"]
    for bad in ({"months": 13}, {"months": 0}, {"utc_offset": "5:30"}, {"review_every_months": 0}, {"bogus": 1}):
        assert_error(fin.c.post(f"{FIN}/results/{rid}/send-to-planner", json=bad), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("tid", ["young_professional", "family", "near_retirement", "blank"])
def test_every_template_instantiates_and_runs(fin, tid):
    rec = fin.instantiate(tid)
    run = fin.solve(rec["id"], FAST)
    if tid == "blank":
        assert run["feasibility"] in ("feasible", "infeasible")
    else:
        assert run["feasibility"] == "feasible"


def test_independent_validator_gate(fin, monkeypatch):
    """A result the engine calls feasible but the validator rejects is stored as `unknown` with the violations."""
    bad = finance.FinanceViolation(code="CASH_NEGATIVE", severity="hard", message="Cash would go below zero.")
    monkeypatch.setattr(run_service.finance, "validate_result", lambda plan, result: [bad])
    plan = fin.instantiate()
    run = fin.solve(plan["id"], FAST)
    assert run["feasibility"] == "unknown"
    res = fin.result(run["result_id"])
    assert res["feasibility"] == "unknown" and res["result"]["feasibility"] == "unknown"
    assert [v["code"] for v in res["result"]["violations"]] == ["CASH_NEGATIVE"]
    assert fin.events(run["id"])[-1]["feasibility"] == "unknown"
    assert_error(fin.c.post(f"{FIN}/results/{run['result_id']}/send-to-planner", json={}), 422, "NOT_FEASIBLE")


def test_openapi_lists_existing_and_finance_paths(fin):
    paths = set(fin.c.get("/openapi.json").json()["paths"])
    existing = {f"{API}/health", f"{API}/templates", f"{API}/problems", f"{API}/problems/{{problem_id}}",
                f"{API}/problems/{{problem_id}}/solver-runs", f"{API}/solver-runs/{{run_id}}/events"}
    assert existing <= paths
    finance_paths = {"/defaults", "/templates", "/templates/{template_id}/instantiate", "/preview", "/plans",
                     "/plans/import", "/plans/{plan_id}", "/plans/{plan_id}/export", "/plans/{plan_id}/validate",
                     "/plans/{plan_id}/runs", "/plans/{plan_id}/what-if", "/runs/{run_id}",
                     "/runs/{run_id}/cancel", "/runs/{run_id}/events", "/plans/{plan_id}/results",
                     "/results/compare", "/results/{result_id}", "/results/{result_id}/contributions.csv",
                     "/results/{result_id}/send-to-planner"}
    assert {f"{FIN}{p}" for p in finance_paths} <= paths
