"""CSV export and send-to-planner bridge (F.16; acceptance 1.19, 1.20)."""

import csv
import io
import re

import pytest

from fin_helpers import goal, income, expense, plan, run
from superplanner.engine import preflight as engine_preflight
from superplanner.finance import DISCLAIMER, contributions_csv, get_template, to_planner_problem
from superplanner.finance.export import HEADER

ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")


@pytest.fixture(scope="module")
def results():
    out = {}
    for tid in ("young_professional", "family", "near_retirement"):
        p = get_template(tid).build(name=tid, start_month="2026-11")
        out[tid] = (p, run(p))
    return out


def test_csv_shape_order_and_disclaimer(results):
    p, r = results["family"]
    text = contributions_csv(p, r)
    lines = text.splitlines()
    assert lines[0] == "# " + DISCLAIMER
    rows = list(csv.reader(io.StringIO("\n".join(lines[1:]))))
    assert rows[0] == HEADER
    body = rows[1:]
    assert body
    actions = ["contribute", "emergency_fund", "rebalance_sell", "rebalance_buy", "goal_withdrawal"]
    gidx = {g.id: i for i, g in enumerate(p.goals)}
    cidx = {c.id: i for i, c in enumerate(p.assumptions.asset_classes)}
    keys = [(row[0], actions.index(row[1]), gidx.get(row[2], -1), cidx.get(row[5], -1)) for row in body]
    assert keys == sorted(keys)
    for row in body:
        assert float(row[7]) >= 1.0 and re.match(r"^\d+\.\d{2}$", row[7])
    assert {row[1] for row in body} >= {"contribute", "emergency_fund", "goal_withdrawal"}


def test_csv_formula_injection():
    p = plan(incomes=[income(amount=60000)], expenses=[expense(amount=20000)],
             goals=[goal("g", 100000, "2028-11", name="=SUM(A1)")])
    r = run(p)
    text = contributions_csv(p, r)
    rows = list(csv.reader(io.StringIO("\n".join(text.splitlines()[1:]))))
    names = {row[3] for row in rows[1:] if row[2] == "g"}
    assert names == {"'=SUM(A1)"}


def test_bridge_problem_passes_engine_preflight(results):
    for tid, (p, r) in results.items():
        prob, skipped = to_planner_problem(p, r, name=f"Money calendar {tid}", months=12, utc_offset="+05:30",
                                           review_every_months=3, include_rebalances=True)
        rep = engine_preflight(prob)
        assert not [i for i in rep.issues if i.severity == "error"], [i.message for i in rep.issues]
        assert prob.horizon_days <= 366 and prob.domain == "personal_finance"
        assert DISCLAIMER in prob.description
        assert all(ID_RE.match(t.id) for t in prob.tasks)
        assert len({t.id for t in prob.tasks}) == len(prob.tasks)
        assert all(len(t.name) <= 200 for t in prob.tasks)
        assert any(t.id.startswith("REV-") for t in prob.tasks)
        assert any(t.id.startswith("C-") for t in prob.tasks)
        assert set(prob.resources[0].calendar.weekly) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        assert skipped >= 0


def test_bridge_ids_and_names_with_long_user_ids():
    gid = "g" * 64
    cls = "c" * 64
    classes = [dict(id="cash", name="Cash", category="cash", expected_return_pct=3, volatility_pct=0.5),
               dict(id="fixed_deposit", name="Fixed deposit", category="debt", expected_return_pct=6.75,
                    volatility_pct=1, liquidity_days=2),
               dict(id=cls, name="N" * 200, category="debt", expected_return_pct=7, volatility_pct=1)]
    p = plan(assumptions=dict(asset_classes=classes, correlations=[]), incomes=[income(amount=80000)],
             expenses=[expense(amount=20000)], holdings=[dict(id="h", name="Cash", asset_class_id="cash",
                                                             amount=200000)],
             goals=[goal(gid, 500000, "2027-06", name="X" * 200, allowed_asset_class_ids=[cls], priority="must")])
    r = run(p)
    prob, _ = to_planner_problem(p, r, name="Y" * 300, months=12)
    assert all(ID_RE.match(t.id) for t in prob.tasks)
    assert all(len(t.name) <= 200 for t in prob.tasks) and len(prob.name) <= 200
    assert any(t.name.endswith("...") for t in prob.tasks)
    assert any(t.id == "G-g0" for t in prob.tasks)
    assert not [i for i in engine_preflight(prob).issues if i.severity == "error"]


def test_bridge_window_and_skips(results):
    p, r = results["young_professional"]
    prob, skipped = to_planner_problem(p, r, name="x", months=1, review_every_months=12, include_rebalances=False)
    assert prob.horizon_days == 30
    assert skipped > 0
    assert not any(t.id.startswith("R-") for t in prob.tasks)
    with pytest.raises(ValueError):
        to_planner_problem(p, r, name="x", months=13)
    with pytest.raises(ValueError):
        to_planner_problem(p, r, name="x", utc_offset="5:30")
