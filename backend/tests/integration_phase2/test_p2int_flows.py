"""Cross-package API flows (P4 items (a), (b), (f), (g)): describe -> answer -> build -> create -> solve/run,
the mixed-version compare flag, and no DB writes / no user text in logs across every intake endpoint."""

from __future__ import annotations

import json
import logging

import sqlalchemy as sa

from p2_helpers import API, CTX_JSON, FIN, FIN_CTX_JSON, IN, fin_checker, solve_and_check, wait_fin_run

SCHEDULE_TEXT = ("Website relaunch starting next Monday. Ravi and Priya are on the team.\n"
                 "1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n"
                 "3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026")
FINANCE_TEXT = ("I'm 34, take home about 1.2 lakh a month and my wife earns 60k. Household costs are 70-80k a month, "
                "school fees 18k every quarter. Car loan EMI 10k, about 3 lakh left at 9%. We have 6 lakh in savings "
                "and 8L in mutual funds. We want 15 lakh for a flat down payment in 3 years and to retire at 60. "
                "Moderate risk.")


def counts(db_url):
    eng = sa.create_engine(db_url)
    try:
        with eng.connect() as c:
            return {n: c.execute(sa.text(f'SELECT COUNT(*) FROM "{n}"')).scalar_one()
                    for n in sa.inspect(eng).get_table_names()}
    finally:
        eng.dispose()


def accept_all(client, domain, body, ctxj):
    draft, qs = body["draft"], body["questions"]
    for _ in range(6):
        if not qs:
            return draft
        r = client.post(f"{IN}/{domain}/answer", json={"draft": draft, "context": ctxj, "answers": [
            {"question_id": q["id"], "use_default": True} for q in qs if q.get("default") is not None]})
        assert r.status_code == 200, r.text
        draft, qs = r.json()["draft"], r.json()["questions"]
        assert not [q for q in qs if q.get("error")], qs
    assert not qs, qs
    return draft


def test_a_schedule_describe_to_feasible_schedule(client):
    r = client.post(f"{IN}/schedule/describe", json={"text": SCHEDULE_TEXT, "context": CTX_JSON})
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    draft = accept_all(client, "schedule", body, CTX_JSON)
    b = client.post(f"{IN}/schedule/build", json={"draft": draft, "context": CTX_JSON}).json()
    assert b["ready"] and b["report"]["ok"]
    rec, run, sch = solve_and_check(client, b["problem"], strategy="auto")
    assert rec["problem"]["domain"] == "project"
    names = {t["name"] for t in rec["problem"]["tasks"]}
    assert "Gather requirements (1/3)" in names
    # the plan list shows it like any other plan
    items = client.get(f"{API}/problems").json()["items"]
    assert any(i["id"] == rec["id"] for i in items)


def test_b_finance_describe_to_feasible_run_with_funding_identity(client):
    r = client.post(f"{IN}/finance/describe", json={"text": FINANCE_TEXT, "context": FIN_CTX_JSON})
    assert r.status_code == 200
    draft = accept_all(client, "finance", r.json(), FIN_CTX_JSON)
    b = client.post(f"{IN}/finance/build", json={"draft": draft, "context": FIN_CTX_JSON}).json()
    assert b["ready"], b
    plan = b["plan"]
    e1 = next(e for e in plan["expenses"] if e["id"] == "e1")
    assert e1["amount"] == 75000 and e1["amount_range"] == {"low": 70000, "high": 80000}
    ret = next(g for g in plan["goals"] if g["kind"] == "retirement")
    assert ret["target_amount"] == 22_500_000
    assert all(i["inflation_linked"] for i in plan["incomes"])
    r = client.post(f"{FIN}/plans", json=plan)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    run = client.post(f"{FIN}/plans/{pid}/runs", json={"seed": 1, "simulation": {"n_paths": 1000}})
    done = wait_fin_run(client, run.json()["run_id"])
    assert done["status"] == "completed" and done["feasibility"] == "feasible", done
    rec = client.get(f"{FIN}/results/{done['result_id']}").json()
    res = rec["result"]
    s = res["summary"]
    assert abs(s["monthly_from_surplus_avg_12m"] + s["monthly_from_savings_avg_12m"]
               - s["monthly_contribution_avg_12m"]) <= 0.01
    assert fin_checker().independent_check(rec["plan"], res) == []
    # amount range assumption line (1.12)
    assert any("you gave a range of" in line for line in res["explanation"]["assumptions"]), \
        res["explanation"]["assumptions"]


def test_f_mixed_engine_version_compare_flag(client, db_url):
    rec = client.post(f"{FIN}/templates/family/instantiate", json={"start_month": "2026-11", "parameters": {}}).json()
    ids = []
    for seed in (0, 1):
        run = client.post(f"{FIN}/plans/{rec['id']}/runs", json={"seed": seed, "simulation": {"n_paths": 300},
                                                                 "calibration_rounds": 0, "compute_fixes": False})
        ids.append(wait_fin_run(client, run.json()["run_id"])["result_id"])
    same = client.get(f"{FIN}/results/compare", params={"a": ids[0], "b": ids[1]}).json()
    assert same["engine_versions_differ"] is False
    eng = sa.create_engine(db_url)
    with eng.begin() as c:
        row = c.execute(sa.text("SELECT result FROM finance_results WHERE id = :i"), {"i": ids[0]}).scalar_one()
        doc = json.loads(row) if isinstance(row, str) else row
        doc["engine_version"] = "fin-0.1.0"
        c.execute(sa.text("UPDATE finance_results SET result = :r WHERE id = :i"), {"r": json.dumps(doc), "i": ids[0]})
    eng.dispose()
    diff = client.get(f"{FIN}/results/compare", params={"a": ids[0], "b": ids[1]}).json()
    assert diff["engine_versions_differ"] is True


def test_g_no_db_writes_and_no_user_text_in_logs(client, db_url, caplog):
    caplog.set_level(logging.DEBUG)
    before = counts(db_url)
    secret_s = SCHEDULE_TEXT + "\n6. Call Zebulon-Quixote-991 2 hours"
    secret_f = FINANCE_TEXT + " Locker code Zebulon-Quixote-991 has 2 lakh in gold."
    r = client.post(f"{IN}/schedule/describe", json={"text": secret_s, "context": CTX_JSON, "use_ai": True})
    d = accept_all(client, "schedule", r.json(), CTX_JSON)
    client.post(f"{IN}/schedule/build", json={"draft": d, "context": CTX_JSON})
    r = client.post(f"{IN}/finance/describe", json={"text": secret_f, "context": FIN_CTX_JSON, "use_ai": True})
    d = accept_all(client, "finance", r.json(), FIN_CTX_JSON)
    client.post(f"{IN}/finance/build", json={"draft": d, "context": FIN_CTX_JSON})
    table = "Task\tDuration\nZebulon-Quixote-991 prep\t2 d\n"
    for dom, cj in (("schedule", CTX_JSON), ("finance", FIN_CTX_JSON)):
        p = client.post(f"{IN}/{dom}/table/parse", json={"text": table}).json()
        client.post(f"{IN}/{dom}/table/apply", json={
            "text": table, "delimiter": p["delimiter"], "has_header": p["has_header"], "context": cj,
            "mapping": [{"column": c["index"], "field": c["suggested_field"]} for c in p["columns"]]})
    # error paths must not echo text either
    client.post(f"{IN}/schedule/describe", json={"text": "Zebulon-Quixote-991 " * 1200, "context": CTX_JSON})
    client.post(f"{IN}/schedule/answer", json={"draft": {"tasks": [{"key": "t1", "name": "Zebulon-Quixote-991"}]},
                                               "context": CTX_JSON, "answers": [{"question_id": "nope"}]})
    assert counts(db_url) == before
    logged = "\n".join(f"{r.name} {r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    assert "Zebulon-Quixote-991" not in logged
    assert "Gather requirements" not in logged and "Household costs" not in logged
