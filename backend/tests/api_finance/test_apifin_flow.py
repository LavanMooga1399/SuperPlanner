"""F2 full flow: template -> edit -> validate -> run (live SSE) -> result -> what-if on the baseline snapshot ->
compare -> CSV -> send to planner -> export/import -> delete (FINANCE.md 18.2, PLAN-FINANCE F4 step 3)."""

from __future__ import annotations

from apifin_helpers import API, FIN, START, assert_error, sse_frames

from superplanner import finance


def test_full_finance_flow(fin):
    c = fin.c
    # 1. defaults + templates, instantiate
    assert c.get(f"{FIN}/defaults").json()["disclaimer"] == finance.DISCLAIMER
    assert "young_professional" in [t["id"] for t in c.get(f"{FIN}/templates").json()["items"]]
    r = c.post(f"{FIN}/templates/young_professional/instantiate",
               json={"name": "Flow plan", "start_month": START, "parameters": {"take_home": 90000}})
    assert r.status_code == 201
    rec = r.json()
    pid = rec["id"]

    # 2. edit with If-Match, preview + validate
    doc = rec["plan"]
    doc["one_offs"] = [{"id": "trip", "name": "Trip", "month": "2027-12", "amount": 40000}]
    preview = c.post(f"{FIN}/preview", json=doc).json()
    assert preview["ok"] is True and preview["cashflow"] is not None
    r = c.put(f"{FIN}/plans/{pid}", json=doc, headers={"If-Match": r.headers["ETag"]})
    assert r.status_code == 200 and r.headers["ETag"] == '"2"'
    v = c.post(f"{FIN}/plans/{pid}/validate").json()
    assert v["ok"] is True and v["plan_version"] == 2

    # 3. baseline run with default settings, followed live over SSE
    created = c.post(f"{FIN}/plans/{pid}/runs", json={"seed": 7}).json()
    with c.stream("GET", created["events_url"]) as stream:
        assert stream.status_code == 200
        frames = sse_frames("".join(stream.iter_text()))
    types = [f["event"] for f in frames]
    assert types[0] == "run_queued" and types[-1] == "run_completed"
    assert {"run_started", "stage_started", "stage_completed"} <= set(types)
    run = c.get(created["status_url"]).json()
    assert run["status"] == "completed" and run["feasibility"] == "feasible" and run["request"]["seed"] == 7
    base_id = run["result_id"]

    # 4. result: contract fields
    res = fin.result(base_id)
    result = finance.FinanceResult.model_validate(res["result"])
    assert result.horizon_months == len(result.series.months) == len(result.cashflow.surplus)
    assert {g.goal_id for g in result.goals} == {"car", "retirement"}
    assert result.explanation.summary
    assert res["plan"]["one_offs"][0]["id"] == "trip"
    assert c.get(f"{FIN}/plans").json()["items"][0]["latest_result"]["id"] == base_id

    # 5. user edits the plan again, then a what-if on the baseline snapshot
    doc2 = c.get(f"{FIN}/plans/{pid}").json()["plan"]
    doc2["one_offs"] = []
    assert c.put(f"{FIN}/plans/{pid}", json=doc2, headers={"If-Match": "2"}).status_code == 200
    wi = c.post(f"{FIN}/plans/{pid}/what-if",
                json={"changes": {"extra_monthly_savings": 10000,
                                  "goal_overrides": [{"goal_id": "car", "risk_tolerance": 5}]},
                      "base_result_id": base_id}).json()
    wrun = fin.wait(wi["run_id"])
    assert wrun["status"] == "completed"
    wres = fin.result(wrun["result_id"])
    assert wres["plan"]["one_offs"][0]["id"] == "trip"          # snapshot of the baseline, not the edit
    assert [g["risk_tolerance"] for g in wres["plan"]["goals"] if g["id"] == "car"] == [5]

    # 6. compare
    comp = c.get(f"{FIN}/results/compare", params={"a": base_id, "b": wrun["result_id"]}).json()
    assert comp["totals"]["monthly_contribution_now_b"] >= comp["totals"]["monthly_contribution_now_a"] - 0.01
    assert comp["b"]["label"] == wrun["label"]

    # 7. CSV + send to planner
    csv_resp = c.get(f"{FIN}/results/{base_id}/contributions.csv")
    assert csv_resp.text.startswith(f"# {finance.DISCLAIMER}")
    sent = c.post(f"{FIN}/results/{base_id}/send-to-planner", json={"months": 12})
    assert sent.status_code == 201
    problem_id = sent.json()["problem_id"]
    assert c.post(f"{API}/problems/{problem_id}/validate").json()["ok"] is True

    # 8. export / import round trip
    exported = c.get(f"{FIN}/plans/{pid}/export").json()
    imported = c.post(f"{FIN}/plans/import", json=exported).json()
    assert imported["id"] != pid
    assert {k: v for k, v in imported["plan"].items() if k != "id"} == \
        {k: v for k, v in exported["plan"].items() if k != "id"}

    # 9. delete: results and runs go with the plan; the scheduling plan stays
    assert c.delete(f"{FIN}/plans/{pid}").status_code == 204
    assert_error(c.get(f"{FIN}/results/{base_id}"), 404, "NOT_FOUND")
    assert_error(c.get(f"{FIN}/runs/{run['id']}"), 404, "NOT_FOUND")
    assert c.get(f"{API}/problems/{problem_id}").status_code == 200
