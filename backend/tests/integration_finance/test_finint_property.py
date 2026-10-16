"""F4 (acceptance 4.7): random plans through the API. Every completed result either has no hard violation
(engine validator) and passes the independent checker, or is `infeasible` with a real T0 cash deficit that
matches the zero-contribution deficit derived independently (F.8.5 T0: "with zero contributions and every
unlocked holding sold into cash the deficit is the same")."""

from __future__ import annotations

import pytest

from finint_helpers import FAST, Model, hard_violations, independent_check, random_plan

N_PLANS = 100


def _sweep(fin, seeds, hard: bool) -> tuple[list[str], dict[str, int]]:
    failures: list[str] = []
    counts = {"feasible": 0, "infeasible": 0, "preflight": 0}
    pending = []
    for s in seeds:
        r = fin.create(random_plan(s, hard=hard))
        assert r.status_code == 201, (s, r.text)
        rr = fin.post_run(r.json()["id"], FAST)
        if rr.status_code == 422 and rr.json()["error"]["code"] == "PREFLIGHT_FAILED":
            counts["preflight"] += 1
            continue
        assert rr.status_code == 202, (s, rr.text)
        pending.append((s, rr.json()["run_id"]))
    for s, run_id in pending:
        run = fin.wait(run_id)
        if run["status"] != "completed":
            failures.append(f"seed {s}: run {run['status']} {run['error']}")
            continue
        rec = fin.result(run["result_id"])
        res, plan = rec["result"], rec["plan"]
        feas = res["feasibility"]
        counts[feas] = counts.get(feas, 0) + 1
        hv = [v["code"] for v in hard_violations(res)]
        if feas == "feasible":
            if hv:
                failures.append(f"seed {s}: feasible but engine validator reports {hv}")
            errs = independent_check(plan, res)
        elif feas == "infeasible":
            m = Model(plan, res["horizon_months"])
            mine = m.zero_contribution_deficit()
            theirs = res["diagnostics"]["cash_deficit_real"]
            if theirs <= 1.0 or mine <= 1.0:
                failures.append(f"seed {s}: infeasible but deficit engine={theirs} independent={mine:.2f}")
            if abs(theirs - mine) > max(1.0, 0.002 * mine):
                failures.append(f"seed {s}: T0 deficit {theirs} != zero-contribution deficit {mine:.2f}")
            if "CASH_NEGATIVE" not in hv:
                failures.append(f"seed {s}: infeasible without CASH_NEGATIVE")
            extra = [c for c in hv if c != "CASH_NEGATIVE"]
            if extra:
                failures.append(f"seed {s}: infeasible plan also breaks other hard rules {extra}")
            errs = independent_check(plan, res, check_cash=False)
        else:
            failures.append(f"seed {s}: feasibility {feas} (engine bug per F.10.2) violations {hv}")
            errs = []
        failures += [f"seed {s}: {e}" for e in errs]
    return failures, counts


def test_random_plans_standard(shared_fin):
    failures, counts = _sweep(shared_fin, range(N_PLANS), hard=False)
    assert counts["feasible"] >= 40 and counts["infeasible"] >= 10, counts
    assert counts["preflight"] <= 5, counts
    assert failures == [], "\n".join(failures)


def test_random_plans_hard_cases(shared_fin):
    """Locked risky holdings, MILP minimum contributions, zero rebalance cost, tight equity / class caps."""
    failures, counts = _sweep(shared_fin, range(N_PLANS), hard=True)
    assert counts["feasible"] >= 30, counts
    assert failures == [], "\n".join(failures)
