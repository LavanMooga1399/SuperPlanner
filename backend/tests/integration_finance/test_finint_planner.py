"""F4: send-to-planner creates a valid scheduling plan that the existing scheduler solves (re-checked with the
scheduling suite's independent checker), and the contribution CSV agrees with the result (F.16)."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta

import pytest

from finint_helpers import API, FIN, Model, expand_lines, midx, mstr
from int_helpers import Api, independent_check as schedule_check

CSV_HEADER = ["month", "action", "goal_id", "goal_name", "priority", "asset_class_id", "asset_class_name",
              "amount_today_money", "amount_expected_nominal"]
TASK_ID = re.compile(r"^(C-(g\d+|ef)-a\d+-\d{6}|S-(g\d+|ef)-a\d+-\d{6}|R-g\d+-\d{6}|REV-\d{6}|G-g\d+|EF-DONE)$")


@pytest.fixture(scope="module")
def yp(shared_fin):
    pid = shared_fin.instantiate("young_professional", name="Planner link")["id"]
    return shared_fin.solve(pid)


def test_send_to_planner_creates_valid_solvable_scheduling_plan(shared_fin, yp):
    c = shared_fin.c
    body = {"months": 12, "utc_offset": "+05:30", "review_every_months": 3, "include_rebalances": True}
    r = c.post(f"{FIN}/results/{yp['id']}/send-to-planner", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    pid = out["problem_id"]
    assert r.headers["location"] == f"/api/v1/problems/{pid}"
    assert out["url"] == f"/plans/{pid}/tasks"
    rec = c.get(f"{API}/problems/{pid}").json()
    doc = rec["problem"]
    assert doc["name"] == "Planner link - money calendar"
    assert doc["domain"] == "personal_finance" and doc["currency"] == "INR"
    assert doc["horizon_days"] <= 366 and doc["horizon_start"].startswith(yp["result"]["start_month"] + "-01T00:00")
    assert doc["horizon_start"].endswith("+05:30")
    assert doc["metadata"]["source"] == "finance" and doc["metadata"]["finance_result_id"] == yp["id"]
    assert "educational planning tool" in doc["description"]
    tasks = doc["tasks"]
    assert out["task_count"] == len(tasks) > 0
    assert len({t["id"] for t in tasks}) == len(tasks)
    for t in tasks:
        assert TASK_ID.match(t["id"]), t["id"]
        assert len(t["name"]) <= 200
        if t.get("type", "activity") == "activity":
            assert t["requirements"] == [{"alternatives": ["YOU"], "units": 1}], t
    # reviews at months 3, 6, 9 of the window
    start = yp["result"]["start_month"]
    revs = sorted(t["id"] for t in tasks if t["id"].startswith("REV-"))
    assert revs == [f"REV-{mstr(start, k).replace('-', '')}" for k in (3, 6, 9)]
    # every goal contribution line that starts inside the window has a start task in that month
    plan = yp["plan"]
    gidx = {g["id"]: i for i, g in enumerate(plan["goals"])}
    aidx = {a["id"]: j for j, a in enumerate(plan["assumptions"]["asset_classes"])}
    ids = {t["id"] for t in tasks}
    for ln in yp["result"]["contributions"]:
        if ln["goal_id"] == "emergency_fund" or midx(start, ln["start_month"]) >= 12:
            continue
        want = f"C-g{gidx[ln['goal_id']]}-a{aidx[ln['asset_class_id']]}-{ln['start_month'].replace('-', '')}"
        assert want in ids, want
    # the scheduling engine accepts it
    v = c.post(f"{API}/problems/{pid}/validate").json()
    assert [i for i in v["issues"] if i["severity"] == "error"] == []
    # and solves it; the independent scheduling checker agrees
    api = Api(c)
    run = api.solve(pid, time_limit_seconds=5)
    assert run["feasibility"] == "feasible", run
    sch = api.schedule(run["primary_schedule_id"])
    pls = [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")} for p in sch["placements"]]
    assert schedule_check(doc, pls, sch["horizon_start"]) == []
    # every action lands in its month window (1st..5th/7th/10th of the month)
    hs = datetime.fromisoformat(sch["horizon_start"])
    for p in sch["placements"]:
        t = next(x for x in tasks if x["id"] == p["task_id"])
        if t.get("earliest_start"):
            assert hs + timedelta(minutes=p["start"]) >= datetime.fromisoformat(t["earliest_start"])
        when = hs + timedelta(minutes=p["start"])
        if p["task_id"].startswith(("C-", "S-", "R-", "REV-")):
            assert when.strftime("%Y%m") == p["task_id"][-6:], p
    # the scheduling home page lists the plan
    assert any(i["id"] == pid for i in c.get(f"{API}/problems").json()["items"])


def test_send_to_planner_options_change_the_task_set(shared_fin, yp):
    c = shared_fin.c
    a = c.post(f"{FIN}/results/{yp['id']}/send-to-planner", json={"months": 3, "review_every_months": 1,
                                                                  "include_rebalances": False, "name": "Short"})
    assert a.status_code == 201, a.text
    doc = c.get(f"{API}/problems/{a.json()['problem_id']}").json()["problem"]
    assert doc["name"] == "Short" and doc["horizon_days"] in (89, 90, 91, 92)
    assert not any(t["id"].startswith("R-") for t in doc["tasks"])
    assert sorted(t["id"] for t in doc["tasks"] if t["id"].startswith("REV-")) == [
        f"REV-{mstr(yp['result']['start_month'], k).replace('-', '')}" for k in (1, 2)]
    for bad in ({"months": 13}, {"months": 0}, {"review_every_months": 0}, {"utc_offset": "nope"}):
        r = c.post(f"{FIN}/results/{yp['id']}/send-to-planner", json=bad)
        assert r.status_code == 422, (bad, r.text)


def _csv(c, rid: str) -> tuple[str, list[dict[str, str]], str]:
    r = c.get(f"{FIN}/results/{rid}/contributions.csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    first, rest = text.split("\r\n", 1)
    rows = list(csv.DictReader(io.StringIO(rest)))
    return first, rows, r.headers["content-disposition"]


def test_contributions_csv_matches_result(shared_fin, yp):
    first, rows, cd = _csv(shared_fin.c, yp["id"])
    assert first.startswith("# SuperPlanner Finance is an educational planning tool.")
    assert "attachment" in cd and cd.endswith('-contributions.csv"')
    assert list(rows[0].keys()) == CSV_HEADER
    res, plan = yp["result"], yp["plan"]
    m = Model(plan, res["horizon_months"])
    lines = expand_lines(m, res)
    want: dict[tuple[str, str, str], float] = {}
    for (gid, cid), cells in lines.items():
        for t, amt in cells.items():
            if amt >= 1.0:
                want[(mstr(m.start, t), gid, cid)] = want.get((mstr(m.start, t), gid, cid), 0.0) + amt
    got: dict[tuple[str, str, str], float] = {}
    months = []
    for row in rows:
        assert row["action"] in ("contribute", "emergency_fund", "rebalance_sell", "rebalance_buy", "goal_withdrawal")
        months.append(row["month"])
        if row["action"] in ("contribute", "emergency_fund"):
            key = (row["month"], row["goal_id"], row["asset_class_id"])
            got[key] = got.get(key, 0.0) + float(row["amount_today_money"])
            t = midx(m.start, row["month"])
            assert float(row["amount_expected_nominal"]) == pytest.approx(
                float(row["amount_today_money"]) * m.P(t), rel=1e-3, abs=0.02)
    assert months == sorted(months)
    assert set(got) == set(want)
    for k in want:
        assert got[k] == pytest.approx(want[k], abs=0.01), k
    withdrawals = {r["goal_id"] for r in rows if r["action"] == "goal_withdrawal"}
    assert withdrawals == {g["goal_id"] for g in res["goals"] if g["target_month"] <= res["end_month"]}


def test_csv_neutralises_formula_injection(shared_fin):
    doc = {"name": "=evil", "start_month": "2026-11",
           "incomes": [{"id": "salary", "name": "Salary", "amount": 80000}],
           "expenses": [{"id": "living", "name": "Living", "amount": 30000}],
           "goals": [{"id": "car", "name": "=HYPERLINK(\"http://x\")", "target_amount": 200000,
                      "target_month": "2029-11"},
                     {"id": "trip", "name": "+1+2", "target_amount": 100000, "target_month": "2028-11"}]}
    r = shared_fin.create(doc)
    assert r.status_code == 201, r.text
    rec = shared_fin.solve(r.json()["id"])
    _, rows, _ = _csv(shared_fin.c, rec["id"])
    names = {row["goal_name"] for row in rows if row["goal_id"] in ("car", "trip")}
    assert names and all(n.startswith("'") for n in names), names
