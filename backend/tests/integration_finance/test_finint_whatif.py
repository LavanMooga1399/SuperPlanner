"""F4: what-if monotonicity (more savings / later goal / higher returns never make a goal worse beyond Monte
Carlo noise), what-if results pass the independent checker, compare deltas, and the replace_active race
(acceptance 4.7)."""

from __future__ import annotations

import threading

import pytest

from finint_helpers import FIN, hard_violations, independent_check, mstr

RUN = {"time_limit_seconds": 30, "seed": 5, "simulation": {"n_paths": 1000}, "compute_fixes": False,
       "calibration_rounds": 0}
NOISE = 0.03     # 1000 paths, same seed: well above the observed run-to-run differences


@pytest.fixture(scope="module")
def yp(shared_fin):
    pid = shared_fin.instantiate("young_professional")["id"]
    return pid, shared_fin.solve(pid, RUN)


@pytest.fixture(scope="module")
def family(shared_fin):
    # PHASE2 1.8 made the family template affordable; a lower take-home pay keeps every goal short (9.P1)
    pid = shared_fin.instantiate("family", take_home=120000)["id"]
    return pid, shared_fin.solve(pid, RUN)


def _goals(rec):
    return {g["goal_id"]: g for g in rec["result"]["goals"]}


def _check_whatif(rec):
    res = rec["result"]
    assert rec["kind"] == "what_if"
    assert res["feasibility"] == "feasible", [v["code"] for v in hard_violations(res)]
    assert independent_check(rec["plan"], res) == []


@pytest.mark.parametrize("fixture", ["yp", "family"])
def test_more_savings_never_lowers_success_or_raises_shortfall(shared_fin, request, fixture):
    pid, base = request.getfixturevalue(fixture)
    ladder = [base]
    for extra in (5000, 15000, 40000):
        rec = shared_fin.solve_what_if(pid, {"extra_monthly_savings": extra}, run=RUN, base_result_id=base["id"])
        _check_whatif(rec)
        assert rec["what_if"]["extra_monthly_savings"] == extra
        assert any(i["id"] == "whatif_extra" for i in rec["plan"]["incomes"])
        ladder.append(rec)
    for lo, hi in zip(ladder, ladder[1:]):
        glo, ghi = _goals(lo), _goals(hi)
        for gid in glo:
            assert ghi[gid]["success_probability"] >= glo[gid]["success_probability"] - NOISE, gid
            assert ghi[gid]["shortfall_real"] <= glo[gid]["shortfall_real"] + 1.0, gid
    if fixture == "family":
        # every goal is short at the baseline, so extra money must strictly reduce the total shortfall
        tot = [sum(g["shortfall_real"] for g in _goals(r).values()) for r in ladder]
        assert all(b < a - 1000 for a, b in zip(tot, tot[1:])), tot


def test_less_savings_never_raises_success(shared_fin, family):
    pid, base = family
    rec = shared_fin.solve_what_if(pid, {"extra_monthly_savings": -5000}, run=RUN, base_result_id=base["id"])
    _check_whatif(rec)
    assert any(e["id"] == "whatif_less" for e in rec["plan"]["expenses"])
    gb, gw = _goals(base), _goals(rec)
    for gid in gb:
        assert gw[gid]["success_probability"] <= gb[gid]["success_probability"] + NOISE
        assert gw[gid]["shortfall_real"] >= gb[gid]["shortfall_real"] - 1.0


def test_delaying_a_short_goal_does_not_make_it_worse(shared_fin, family):
    pid, base = family
    home = _goals(base)["home"]
    later = mstr(home["target_month"], 24)
    rec = shared_fin.solve_what_if(pid, {"goal_overrides": [{"goal_id": "home", "target_month": later}]}, run=RUN,
                                   base_result_id=base["id"])
    _check_whatif(rec)
    gh = _goals(rec)["home"]
    assert gh["target_month"] == later
    assert gh["shortfall_fraction"] < home["shortfall_fraction"]
    assert gh["success_probability"] >= home["success_probability"] - NOISE


@pytest.mark.parametrize("shift", [-2.0, 2.0])
def test_return_shift_moves_outcomes_in_the_right_direction(shared_fin, family, shift):
    pid, base = family
    rec = shared_fin.solve_what_if(pid, {"return_shift_pct": shift}, run=RUN, base_result_id=base["id"])
    _check_whatif(rec)
    tb = sum(g["shortfall_real"] for g in _goals(base).values())
    tw = sum(g["shortfall_real"] for g in _goals(rec).values())
    assert (tw < tb) if shift > 0 else (tw > tb), (tb, tw)
    eq = next(c for c in rec["plan"]["assumptions"]["asset_classes"] if c["id"] == "equity_index")
    assert eq["expected_return_pct"] == pytest.approx(12.0 + shift)


def test_income_drop_does_not_raise_success(shared_fin, yp):
    pid, base = yp
    start = base["result"]["start_month"]
    rec = shared_fin.solve_what_if(pid, {"income_drop": {"start_month": mstr(start, 6), "months": 12, "percent": 20}},
                                   run=RUN, base_result_id=base["id"])
    _check_whatif(rec)
    gb, gw = _goals(base), _goals(rec)
    for gid in gb:
        assert gw[gid]["success_probability"] <= gb[gid]["success_probability"] + NOISE, gid
    # the drop does not change the emergency fund target (F.13 [R15])
    assert rec["result"]["summary"]["emergency_fund_target"] == base["result"]["summary"]["emergency_fund_target"]


def test_compare_deltas_are_b_minus_a(shared_fin, yp):
    pid, base = yp
    rec = shared_fin.solve_what_if(pid, {"extra_monthly_savings": 15000}, run=RUN, base_result_id=base["id"])
    r = shared_fin.c.get(f"{FIN}/results/compare", params={"a": base["id"], "b": rec["id"]})
    assert r.status_code == 200, r.text
    cmp = r.json()
    assert cmp["a"]["id"] == base["id"] and cmp["b"]["id"] == rec["id"]
    assert cmp["what_if_b"]["extra_monthly_savings"] == 15000
    t = cmp["totals"]
    assert t["monthly_contribution_now_delta"] == pytest.approx(
        t["monthly_contribution_now_b"] - t["monthly_contribution_now_a"], abs=0.01)
    ga, gb = _goals(base), _goals(rec)
    for row in cmp["goals"]:
        gid = row["goal_id"]
        assert row["success_a"] == ga[gid]["success_probability"] and row["success_b"] == gb[gid]["success_probability"]
        assert row["success_delta"] == pytest.approx(row["success_b"] - row["success_a"], abs=1e-9)
        assert row["p50_delta"] == pytest.approx(row["p50_b"] - row["p50_a"], abs=0.01)
        assert row["status_a"] == ga[gid]["status"] and row["status_b"] == gb[gid]["status"]


def test_replace_active_sequential_keeps_only_latest(shared_fin, yp):
    pid, base = yp
    slow = {**RUN, "simulation": {"n_paths": 10000}, "calibration_rounds": 4, "compute_fixes": True}
    r1 = shared_fin.what_if(pid, {"extra_monthly_savings": 1000}, run=slow, base_result_id=base["id"])
    assert r1.status_code == 202, r1.text
    r2 = shared_fin.what_if(pid, {"extra_monthly_savings": 2000}, run=RUN, base_result_id=base["id"],
                            replace_active=True)
    assert r2.status_code == 202, r2.text
    first, second = shared_fin.wait(r1.json()["run_id"]), shared_fin.wait(r2.json()["run_id"])
    assert first["status"] == "cancelled" and first["result_id"] is None
    assert second["status"] == "completed" and second["result_id"]
    items = shared_fin.c.get(f"{FIN}/plans/{pid}/results?kind=what_if").json()["items"]
    assert [i["run_id"] for i in items if i["run_id"] in (first["id"], second["id"])] == [second["id"]]


def test_replace_active_concurrent_requests_end_with_one_completed_latest(shared_fin, yp):
    pid, base = yp
    slow = {**RUN, "simulation": {"n_paths": 8000}, "calibration_rounds": 3}
    out: dict[int, object] = {}
    barrier = threading.Barrier(2)

    def post(i: int) -> None:
        barrier.wait()
        out[i] = shared_fin.what_if(pid, {"extra_monthly_savings": 3000 + i}, run=slow, base_result_id=base["id"],
                                    replace_active=True)

    th = [threading.Thread(target=post, args=(i,)) for i in range(2)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    codes = sorted(r.status_code for r in out.values())
    assert codes == [202, 202], [r.text for r in out.values()]
    runs = [shared_fin.wait(r.json()["run_id"]) for r in out.values()]
    runs.sort(key=lambda x: (x["created_at"], x["id"]))
    statuses = [x["status"] for x in runs]
    assert statuses.count("completed") == 1, statuses
    latest = runs[-1]
    assert latest["status"] == "completed", statuses
    assert runs[0]["status"] == "cancelled" and runs[0]["result_id"] is None
    res_ids = [i["id"] for i in shared_fin.c.get(f"{FIN}/plans/{pid}/results?kind=what_if").json()["items"]
               if i["run_id"] in (runs[0]["id"], latest["id"])]
    assert res_ids == [latest["result_id"]]
