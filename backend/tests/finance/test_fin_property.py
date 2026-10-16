"""Property test (acceptance 1.22): 100 random small plans either solve clean or are honestly infeasible."""

import random

import pytest

from fin_helpers import hard, quick_request
from superplanner.finance import FinancePlan, preflight, run_plan, timegrid as tg

CLASSES = ["cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold"]


def random_plan(seed: int) -> FinancePlan:
    rnd = random.Random(seed)
    start = f"{rnd.randint(2025, 2030)}-{rnd.randint(1, 12):02d}"
    incomes = [dict(id=f"i{k}", name=f"Income {k}", amount=round(rnd.uniform(5000, 200000), 2),
                    frequency=rnd.choice(["monthly", "monthly", "quarterly", "yearly"]),
                    growth_pct=rnd.choice([0, 3, 6, 10]), interruptible=rnd.random() < 0.7,
                    start_month=rnd.choice([None, tg.add_months(start, -rnd.randint(1, 30)),
                                            tg.add_months(start, rnd.randint(1, 30))]))
               for k in range(rnd.randint(0, 3))]
    expenses = [dict(id=f"e{k}", name=f"Expense {k}", amount=round(rnd.uniform(1000, 80000), 2),
                     frequency=rnd.choice(["monthly", "monthly", "half_yearly", "yearly", "once"]),
                     essential=rnd.random() < 0.6, inflation_linked=rnd.random() < 0.8,
                     inflation_pct=rnd.choice([None, None, 9.0]),
                     end_month=rnd.choice([None, tg.add_months(start, rnd.randint(1, 80))]))
                for k in range(rnd.randint(0, 4))]
    debts = []
    for k in range(rnd.randint(0, 2)):
        bal = round(rnd.uniform(10000, 2000000), 2)
        rate = rnd.choice([0, 8, 12, 18])
        emi = round(bal * rate / 1200 + rnd.uniform(500, 30000), 2)
        debts.append(dict(id=f"d{k}", name=f"Debt {k}", balance=bal, interest_rate_pct=rate, emi=emi))
    holdings = [dict(id=f"h{k}", name=f"Holding {k}", asset_class_id=rnd.choice(CLASSES),
                     amount=round(rnd.uniform(1000, 1000000), 2),
                     locked_until_month=rnd.choice([None, None, tg.add_months(start, rnd.randint(1, 60))]))
                for k in range(rnd.randint(0, 3))]
    one_offs = [dict(id=f"o{k}", name=f"One-off {k}", kind=rnd.choice(["expense", "inflow"]),
                     month=tg.add_months(start, rnd.randint(0, 60)), amount=round(rnd.uniform(1000, 500000), 2),
                     inflation_linked=rnd.random() < 0.5)
                for k in range(rnd.randint(0, 2))]
    goals = []
    used: dict[str, float] = {}
    for k in range(rnd.randint(0, 4)):
        month = tg.add_months(start, rnd.randint(3, 180))
        allowed = rnd.choice([None, None, rnd.sample(["fixed_deposit", "short_debt", "equity_index", "gold"],
                                                     rnd.randint(1, 3))])
        earmarks = []
        for h in holdings:
            if rnd.random() < 0.3 and (h["locked_until_month"] is None or h["locked_until_month"] <= month):
                free = h["amount"] - used.get(h["id"], 0.0)
                amt = round(free * rnd.uniform(0.1, 0.5), 2)
                if amt > 0:
                    used[h["id"]] = used.get(h["id"], 0.0) + amt
                    earmarks.append(dict(holding_id=h["id"], amount=amt))
        goals.append(dict(id=f"g{k}", name=f"Goal {k}", target_amount=round(rnd.uniform(10000, 5000000), 2),
                          target_month=month, priority=rnd.choice(["must", "should", "nice"]),
                          risk_tolerance=rnd.choice([None, 1, 3, 5]), allowed_asset_class_ids=allowed,
                          inflation_pct=rnd.choice([None, 8.0]), earmarked=earmarks))
    constraints = dict(contribution_block_months=rnd.choice([6, 12]),
                       max_equity_pct=rnd.choice([None, None, 40]),
                       min_cash_buffer=rnd.choice([0, 0, 5000]),
                       max_class_pct=rnd.choice([{}, {}, {"gold": 15}]))
    return FinancePlan.model_validate(dict(
        name=f"Random {seed}", start_month=start, profile=dict(risk_tolerance=rnd.randint(1, 5)),
        incomes=incomes, expenses=expenses, debts=debts, holdings=holdings, one_offs=one_offs, goals=goals,
        emergency_fund=dict(months_of_essentials=rnd.choice([0, 3, 6]), build_share=rnd.choice([1.0, 0.5])),
        constraints=constraints))


@pytest.mark.slow
def test_random_plans_clean_or_honestly_infeasible():
    outcomes = {"feasible": 0, "infeasible": 0}
    for seed in range(100):
        p = random_plan(seed)
        rep = preflight(p)
        assert rep.ok, (seed, [i.message for i in rep.issues if i.severity == "error"])
        r = run_plan(p, quick_request(simulation={"n_paths": 100}, compute_fixes=(seed % 10 == 0),
                                      calibration_rounds=(1 if seed % 5 == 0 else 0)))
        h = hard(p, r)
        if r.feasibility == "infeasible":
            assert r.diagnostics.cash_deficit_real > 1.0, seed
            assert {v.code for v in h} <= {"CASH_NEGATIVE"}, (seed, [(v.code, v.message) for v in h])
        else:
            assert not h, (seed, [(v.code, v.message, v.months, v.amount) for v in h])
            assert r.feasibility == "feasible"
        outcomes[r.feasibility] += 1
    assert outcomes["feasible"] > 20 and outcomes["infeasible"] > 0, outcomes
