"""Template outcome bands and growth-asset use through the API (PHASE2 1.9-1.11, 1.14; plan P1-2, P1-3,
P1-5, P1-6; P4 item (d)). instantiate -> run -> result record, then the independent finance checker."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from p2_helpers import FIN, fin_checker, make_app, wait_fin_run

TEMPLATES = ("young_professional", "family", "near_retirement")
RISKY = {"equity_index", "gold"}
LEVEL_RE = r"risk level \d of 5"


@pytest.fixture(scope="module")
def fin(db_url_factory_module):
    with TestClient(make_app(db_url_factory_module("t"))) as c:
        yield {"c": c, "cache": {}}


def run_template(fin, tid: str, seed: int, start: str = "2026-11", **req) -> tuple[dict, dict]:
    key = (tid, seed, start, tuple(sorted(req.items())))
    if key not in fin["cache"]:
        c = fin["c"]
        r = c.post(f"{FIN}/templates/{tid}/instantiate", json={"start_month": start, "parameters": {}})
        assert r.status_code == 201, r.text
        rec = r.json()
        body = {"seed": seed, "simulation": {"n_paths": 1000}, **req}
        r = c.post(f"{FIN}/plans/{rec['id']}/runs", json=body)
        assert r.status_code == 202, r.text
        run = wait_fin_run(c, r.json()["run_id"])
        assert run["status"] == "completed", run
        res = c.get(f"{FIN}/results/{run['result_id']}").json()
        fin["cache"][key] = (res["plan"], res["result"])
    return fin["cache"][key]


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize("tid", TEMPLATES)
def test_common_bands_and_independent_check(fin, tid, seed):
    plan, res = run_template(fin, tid, seed)
    assert res["engine_version"] == "fin-0.2.0"
    assert res["feasibility"] == "feasible"
    assert not [v for v in res["violations"] if v["severity"] == "hard"]
    assert fin_checker().independent_check(plan, res) == []
    s = res["summary"]
    assert min(res["cashflow"]["surplus"][:12]) >= 0
    assert s["monthly_surplus_avg_12m"] > 0
    assert s["monthly_investable_now"] >= 0
    # funding split identity (1.11, P1-6)
    assert abs(s["monthly_from_surplus_avg_12m"] + s["monthly_from_savings_avg_12m"]
               - s["monthly_contribution_avg_12m"]) <= 0.01
    assert s["monthly_from_surplus_avg_12m"] <= s["monthly_investable_avg_12m"] + 0.01
    # SUMMARY_INVEST is no longer emitted; no "you can invest -X" sentence
    text = " ".join(res["explanation"]["summary"])
    assert "-₹" not in text and "₹-" not in text


@pytest.mark.parametrize("seed", [0, 1])
def test_family_bands(fin, seed):
    _, res = run_template(fin, "family", seed)
    goals = res["goals"]
    assert sum(1 for g in goals if g["success_probability"] >= 0.5) >= 2
    assert all(g["status"] != "off_track" for g in goals if g["priority"] == "must")
    assert res["summary"]["monthly_investable_now"] > 0      # month 0 with quarterly fees (57,000)


@pytest.mark.parametrize("seed", [0, 1])
def test_near_retirement_bands(fin, seed):
    _, res = run_template(fin, "near_retirement", seed)
    g = {x["goal_id"]: x for x in res["goals"]}
    assert g["retirement"]["status"] == "on_track"
    assert sum(1 for x in res["goals"] if x["success_probability"] >= 0.5) >= 1


@pytest.mark.parametrize("seed", [0, 1])
def test_young_professional_bands(fin, seed):
    _, res = run_template(fin, "young_professional", seed)
    g = {x["goal_id"]: x for x in res["goals"]}
    assert g["retirement"]["success_probability"] >= 0.5
    car = g["car"]
    assert car["status"] == "at_risk" and car["shortfall_fraction"] <= 0.10
    assert len(res["explanation"]["goals"]["car"]["fixes"]) >= 1


def test_seed_seven_spot_check_same_statuses(fin):
    for tid in TEMPLATES:
        a = {g["goal_id"]: g["status"] for g in run_template(fin, tid, 1)[1]["goals"]}
        b = {g["goal_id"]: g["status"] for g in run_template(fin, tid, 7)[1]["goals"]}
        assert a == b, tid


@pytest.mark.parametrize("tid", TEMPLATES)
def test_current_month_start_gives_the_same_bands(fin, tid):
    """The UI instantiates with the current month (2026-10 today), not the 2026-11 of the 1.9 table."""
    a = {g["goal_id"]: g["status"] for g in run_template(fin, tid, 0)[1]["goals"]}
    plan, res = run_template(fin, tid, 0, start="2026-10")
    assert {g["goal_id"]: g["status"] for g in res["goals"]} == a
    assert fin_checker().independent_check(plan, res) == []


def _tolerance(plan, goal) -> int:
    gid = goal["goal_id"]
    pg = next(g for g in plan["goals"] if g["id"] == gid)
    return pg.get("risk_tolerance") or plan["profile"]["risk_tolerance"]


@pytest.mark.parametrize("tid", TEMPLATES)
def test_growth_assets_used_for_long_goals(fin, tid):
    plan, res = run_template(fin, tid, 1)
    long_goals = [g for g in res["goals"] if g["months_to_goal"] >= 120 and _tolerance(plan, g) >= 3]
    for g in long_goals:
        assert g["growth_cap_now_pct"] > 0, g["goal_id"]
        assert g["growth_share_now_pct"] >= 0.8 * g["growth_cap_now_pct"], g
        risky_now = sum(v for k, v in g["allocation_now_pct"].items() if k in RISKY)
        assert abs(risky_now - g["growth_share_now_pct"]) <= 0.5, g
        assert g["allocation_now_pct"].get("equity_index", 0) > 0, g
        pts = [p for p in res["glide_paths"][g["goal_id"]] if p["months_to_goal"] >= 120]
        assert max(p["risky_share_pct"] for p in pts) >= 0.8 * max(p["risky_cap_pct"] for p in pts)
    for g in res["goals"]:
        if g["months_to_goal"] < 36:
            for p in res["glide_paths"][g["goal_id"]]:
                assert p["risky_share_pct"] <= p["risky_cap_pct"] + 1e-6, (g["goal_id"], p)


def test_family_has_long_goals_with_equity(fin):
    _, res = run_template(fin, "family", 1)
    g = {x["goal_id"]: x for x in res["goals"]}
    for gid in ("education", "retirement"):
        assert g[gid]["allocation_now_pct"].get("equity_index", 0) >= 50, g[gid]["allocation_now_pct"]


def test_family_calibration_rounds_four_keeps_growth(fin):
    _, res = run_template(fin, "family", 1, calibration_rounds=4)
    g = {x["goal_id"]: x for x in res["goals"]}["retirement"]
    assert g["growth_share_now_pct"] >= 0.8 * g["growth_cap_now_pct"]


@pytest.mark.parametrize("tid", TEMPLATES)
def test_first_reason_is_growth_and_names_goal(fin, tid):
    import re
    plan, res = run_template(fin, tid, 1)
    for g in res["goals"]:
        reasons = res["explanation"]["goals"][g["goal_id"]]["reasons"]
        assert reasons and reasons[0]["code"].startswith("GROWTH_"), (g["goal_id"], reasons[:1])
        msg = reasons[0]["message"]
        assert msg.startswith(g["name"]), msg
        if g["growth_share_now_pct"] >= 1:
            assert re.search(LEVEL_RE, msg), msg


def test_family_retirement_reason_reads_like_the_example(fin):
    _, res = run_template(fin, "family", 1)
    msg = res["explanation"]["goals"]["retirement"]["reasons"][0]["message"]
    assert msg.startswith("Retirement: about 60% in growth assets (")
    assert "because the goal is 25 years away and your risk level 3 of 5 allows up to 60%" in msg
    assert "The share steps down from 20" in msg
