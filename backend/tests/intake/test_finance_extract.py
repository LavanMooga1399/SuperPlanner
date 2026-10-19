"""Rule-based finance extraction (PHASE2 2.7.9, 2.15 example; plan P2-3)."""

from __future__ import annotations

import pytest

from intake_helpers import FIN_CTX, FINANCE_TEXT
from superplanner.intake import answer_finance, describe_finance
from superplanner.intake.models import Answer


def coll(r, name):
    return {x.key: x for x in getattr(r.draft, name)}


def amt(x):
    return (x.low, x.high) if x is not None else None


def test_example_draft_exact():
    r = describe_finance(FINANCE_TEXT, FIN_CTX)
    d = r.draft
    assert (d.domain, d.name, d.start_month) == ("finance", "My financial plan", "2026-10")
    assert d.profile.model_dump() == {"age": 34, "retirement_age": 60, "risk_tolerance": 3, "currency": "INR",
                                      "locale": "en-IN"}
    inc = coll(r, "incomes")
    assert [(i.key, i.name, i.kind, amt(i.amount), i.frequency, i.inflation_linked, i.growth_pct)
            for i in inc.values()] == [("i1", "Salary", "salary", (120000, 120000), "monthly", True, None),
                                       ("i2", "Partner's salary", "salary", (60000, 60000), "monthly", True, None)]
    exp = coll(r, "expenses")
    assert [(e.key, e.name, e.category, amt(e.amount), e.frequency, e.essential, e.inflation_pct)
            for e in exp.values()] == [("e1", "Household costs", "living", (70000, 80000), "monthly", True, None),
                                       ("e2", "School fees", "education", (18000, 18000), "quarterly", True, 9.0)]
    (debt,) = d.debts
    assert (debt.key, debt.name, debt.kind, amt(debt.balance), debt.interest_rate_pct, amt(debt.emi)) == (
        "d1", "Car loan", "vehicle", (300000, 300000), 9.0, (10000, 10000))
    assert [(h.key, h.name, h.asset_class_id, amt(h.amount)) for h in d.holdings] == [
        ("h1", "Savings", "cash", (600000, 600000)), ("h2", "Mutual funds", "equity_index", (800000, 800000))]
    assert [(g.key, g.name, g.kind, amt(g.target), g.target_month, g.priority) for g in d.goals] == [
        ("g1", "Flat down payment", "home", (1500000, 1500000), "2029-10", None),
        ("g2", "Retirement", "retirement", None, "2052-10", "must")]
    p = d.provenance
    for path, (src, conf, a, b, txt) in {
        "/profile/age": ("text", 0.95, 0, 6, "I'm 34"),
        "/incomes/i1/amount": ("text", 0.8, 18, 40, "about 1.2 lakh a month"),
        "/expenses/e1/amount": ("text", 0.95, 84, 98, "70-80k a month"),
        "/goals/g2/target_month": ("derived", 0.9, 282, 294, "retire at 60"),
    }.items():
        assert (p[path].source, p[path].confidence) == (src, conf), path
        assert (p[path].span.start, p[path].span.end, p[path].span.text) == (a, b, txt), path
        assert FINANCE_TEXT[a:b] == txt
    assert p["/goals/g2/target_month"].note == "Age 34 + 26 years"
    qs = r.questions
    assert [q.id for q in qs] == ["FIN_RETIREMENT_TARGET:/goals/g2/target", "FIN_DISCRETIONARY:-",
                                  "FIN_GOAL_PRIORITY:/goals/g1/priority", "FIN_EF_MONTHS:/emergency_fund_months"]
    assert qs[0].kind == "money" and qs[0].default == 22500000 and not qs[0].required
    assert qs[0].reason == "confirm_default"
    assert qs[0].prompt == ("For retirement we suggest saving ₹2,25,00,000 (25 years of your regular spending, in "
                            "today's money). Keep it or enter your own amount.")
    assert (qs[1].default, qs[1].default_label) == (0, "None")
    assert qs[1].prompt == "Anything else you spend each month, such as eating out, shopping or trips?"
    assert qs[2].default == "should" and qs[3].default == 6
    assert [n.model_dump(exclude={"span"}) for n in r.notes] == [
        {"code": "EDUCATION_INFLATION", "severity": "info",
         "message": "School fees are assumed to rise 9% a year; you can change this."}]
    assert r.ready is True


def test_gross_pay_asks_take_home():
    r = describe_finance("My CTC is 18 LPA. Rent 25k pm.", FIN_CTX)
    assert any(n.code == "GROSS_INCOME" for n in r.notes)
    q = next(q for q in r.questions if q.code == "FIN_TAKE_HOME")
    assert q.required and q.path == "/incomes/i1/amount" and not r.ready
    a = answer_finance(r.draft, [Answer(question_id=q.id, value={"text": "1.1 lakh"})], FIN_CTX)
    i1 = a.draft.incomes[0]
    assert amt(i1.amount) == (110000, 110000) and i1.frequency == "monthly"
    assert not any(q.code == "FIN_TAKE_HOME" for q in a.questions)


@pytest.mark.parametrize("text,cls,name", [
    ("We have 3 lakh in FD", "fixed_deposit", "Fixed deposit"),
    ("I have 2 lakh in PPF", "govt_long", "PPF"),
    ("1 lakh in gold", "gold", "Gold"),
    ("I invested 5L in index funds", "equity_index", "Index funds"),
    ("We have 50k in the bank", "cash", "Savings"),
    ("I have 2 lakh in debt funds", "short_debt", "Debt funds"),
])
def test_holding_classes(text, cls, name):
    r = describe_finance(text, FIN_CTX)
    (h,) = r.draft.holdings
    assert h.asset_class_id == cls and h.name == name
    if cls == "govt_long":
        assert any(q.code == "FIN_HOLDING_LOCK" for q in r.questions)


def test_continued_holdings_and_debt_terms():
    r = describe_finance("Home loan outstanding 40 lakh at 8.5%, 180 months left. Credit card balance 50,000. "
                         "I have 2 lakh in PPF and 1L in gold and 3 lakh FD.", FIN_CTX)
    d1, d2 = r.draft.debts
    assert (d1.kind, amt(d1.balance), d1.interest_rate_pct, d1.remaining_months, d1.emi) == (
        "home", (4000000, 4000000), 8.5, 180, None)
    assert (d2.kind, amt(d2.balance)) == ("credit_card", (50000, 50000))
    assert [h.asset_class_id for h in r.draft.holdings] == ["govt_long", "gold", "fixed_deposit"]
    assert r.draft.expenses == []
    codes = {q.id for q in r.questions}
    assert "FIN_DEBT_EMI:/debts/d1/emi" not in codes          # derived at build from balance, rate and months
    assert "FIN_DEBT_RATE:/debts/d2/interest_rate_pct" in codes
    rate_q = next(q for q in r.questions if q.code == "FIN_DEBT_RATE")
    assert rate_q.default == 36.0


@pytest.mark.parametrize("text,kind,priority", [
    ("We want 15 lakh for a flat down payment in 3 years", "home", None),
    ("I want to buy a car for 8 lakh in 2 years", "vehicle", None),
    ("Need 10 lakh for my son's college in 8 years", "education", "must"),
    ("Would like a trip to Europe for 3L next year", "travel", "nice"),
    ("Wedding of my daughter in 10 years, must have 20 lakh", "wedding", "must"),
    ("Goal: start a business with 25 lakh in 5 years", "business", None),
])
def test_goal_kinds_and_priorities(text, kind, priority):
    r = describe_finance(text, FIN_CTX)
    (g,) = r.draft.goals
    assert g.kind == kind and g.priority == priority, (g, text)
    assert g.target is not None and g.target_month is not None


def test_goal_dates():
    r = describe_finance("Would like a trip to Europe for 3L next year", FIN_CTX)
    assert r.draft.goals[0].target_month == "2027-10"
    r = describe_finance("I want a car for 8 lakh in 18 months", FIN_CTX)
    assert r.draft.goals[0].target_month == "2028-04"
    r = describe_finance("Save 5 lakh for a bike by March 2028", FIN_CTX)
    assert r.draft.goals[0].target_month == "2028-03"


def test_age_based_goal_and_retirement_age_are_not_profile_age():
    r = describe_finance("I earn 80k. Wedding of my daughter when I'm 50, must have 20 lakh.", FIN_CTX)
    assert r.draft.profile.age is None
    (g,) = r.draft.goals
    assert g.kind == "wedding" and g.target_month is None
    q = next(q for q in r.questions if q.code == "FIN_AGE")
    assert q.required
    a = answer_finance(r.draft, [Answer(question_id=q.id, value=40)], FIN_CTX)
    assert a.draft.profile.age == 40 and a.draft.goals[0].target_month == "2036-10"

    r = describe_finance("Salary 1 lakh per month. Save 1.5 crore for retirement at age 55.", FIN_CTX)
    assert r.draft.profile.age is None and r.draft.profile.retirement_age == 55
    a = answer_finance(r.draft, [Answer(question_id="FIN_AGE:/profile/age", value=30)], FIN_CTX)
    assert a.draft.goals[0].target_month == "2051-10" and a.ready


def test_ranges_and_frequencies():
    r = describe_finance("I earn 80k. Kids school fees 1.2 to 1.5 lakh per year. Groceries 8-10k a month.", FIN_CTX)
    e1, e2 = r.draft.expenses
    assert (amt(e1.amount), e1.frequency, e1.category) == ((120000, 150000), "yearly", "education")
    assert (amt(e2.amount), e2.frequency, e2.category, e2.essential) == ((8000, 10000), "monthly", "living", True)


def test_currencies_and_mixed_note():
    r = describe_finance("Salary $5,000 per month. Eating out €200 a month.", FIN_CTX)
    assert any(n.code == "MIXED_CURRENCY" for n in r.notes)
    assert r.draft.expenses[0].essential is False and r.draft.expenses[0].category == "lifestyle"


def test_risk_and_emergency_fund():
    r = describe_finance("I'm 40, conservative. Emergency fund 6 months. Salary 1L.", FIN_CTX)
    assert r.draft.profile.risk_tolerance == 2 and r.draft.emergency_fund_months == 6
    r = describe_finance("Salary 1L. Risk 4/5.", FIN_CTX)
    assert r.draft.profile.risk_tolerance == 4


def test_unsupported_rule_note():
    r = describe_finance("Salary 1 lakh a month. Never touch the gold.", FIN_CTX)
    assert [n.code for n in r.notes] == ["UNSUPPORTED_RULE"]


def test_no_income_asks():
    r = describe_finance("Rent 20k a month.", FIN_CTX)
    q = r.questions[0]
    assert q.code == "FIN_INCOME" and q.required and not r.ready
