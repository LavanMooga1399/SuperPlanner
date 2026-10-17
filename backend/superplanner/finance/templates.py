"""Finance templates (FINANCE.md section 15): deterministic, relative to `start_month`, asset classes only."""

from __future__ import annotations

from typing import Callable

from . import timegrid as tg
from .model import (Debt, Earmark, EmergencyFundSettings, Expense, FinancePlan, FinanceTemplateParameter, Goal,
                    Holding, IncomeStream, Profile)

P = FinanceTemplateParameter


def resolve(parameters: list[FinanceTemplateParameter], params: dict | None) -> dict[str, float]:
    """Defaults for missing parameters; `ValueError` for unknown names or invalid values."""
    params = dict(params or {})
    known = {p.name: p for p in parameters}
    unknown = sorted(set(params) - set(known))
    if unknown:
        raise ValueError(f"unknown template parameter(s): {', '.join(unknown)}")
    out: dict[str, float] = {}
    for p in parameters:
        v = params.get(p.name, p.default)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"parameter {p.name!r} must be a number")
        if p.type in ("int", "month_offset_years"):
            if float(v) != int(v):
                raise ValueError(f"parameter {p.name!r} must be a whole number")
            v = int(v)
        if (p.min is not None and v < p.min) or (p.max is not None and v > p.max):
            raise ValueError(f"parameter {p.name!r} must be between {p.min:g} and {p.max:g}")
        out[p.name] = v
    return out


def _years(start: str, years: int) -> str:
    return tg.add_months(start, 12 * max(1, int(years)))


def _years_to_retirement(p: dict[str, float]) -> int:
    """`retirement_age - age`; the parameter ranges overlap, so a retirement age at or below the age is rejected
    here (`ValueError`, mapped to 422 VALIDATION_ERROR) instead of being clamped to a goal one year out."""
    years = int(p["retirement_age"]) - int(p["age"])
    if years <= 0:
        raise ValueError(f"parameter 'retirement_age' ({int(p['retirement_age'])}) must be greater than "
                         f"'age' ({int(p['age'])})")
    return years


def retirement_target(expenses: list[Expense], incomes: list[IncomeStream]) -> float:
    """Retirement preset (PHASE2 1.8): `25 x 12 x max(0, E_rec - I_rec)`.

    `E_rec` is the monthly equivalent of the open-ended expenses (no start or end month) except education,
    `I_rec` the monthly equivalent of open-ended rental and pension incomes. Used by the templates and intake."""
    e_rec = sum(e.amount * tg.MONTHLY_FACTOR[e.frequency] for e in expenses
                if e.start_month is None and e.end_month is None and e.category != "education")
    i_rec = sum(i.amount * tg.MONTHLY_FACTOR[i.frequency] for i in incomes
                if i.kind in ("rental", "pension") and i.end_month is None)
    return round(25 * 12 * max(0.0, e_rec - i_rec), 2)


class FinanceTemplate:
    def __init__(self, id: str, name: str, description: str, parameters: list[FinanceTemplateParameter],
                 builder: Callable[[str, str, dict[str, float]], FinancePlan]):
        self.id = id
        self.name = name
        self.description = description
        self.parameters = parameters
        self._builder = builder

    def build(self, *, name: str, start_month: str, params: dict[str, float] | None = None) -> FinancePlan:
        p = resolve(self.parameters, params)
        return self._builder(name, start_month, p)


def _young(name: str, start: str, p: dict[str, float]) -> FinancePlan:
    exps = [Expense(id="living", name="Living costs", category="living", amount=p["essentials"], essential=True),
            Expense(id="lifestyle", name="Lifestyle", category="lifestyle", amount=p["discretionary"],
                    essential=False)]
    incs = [IncomeStream(id="salary", name="Salary", kind="salary", amount=p["take_home"], growth_pct=3.0,
                         inflation_linked=True)]
    goals = [
        Goal(id="car", name="Car", kind="vehicle", target_amount=p["car_price"],
             target_month=_years(start, p["car_in_years"]), priority="should", flexibility_months=12),
        Goal(id="retirement", name="Retirement", kind="retirement", target_amount=retirement_target(exps, incs),
             target_month=_years(start, _years_to_retirement(p)), priority="must"),
    ]
    return FinancePlan(
        name=name, start_month=start,
        profile=Profile(age=int(p["age"]), retirement_age=int(p["retirement_age"]), risk_tolerance=4),
        incomes=incs, expenses=exps,
        holdings=[Holding(id="h_cash", name="Savings account", asset_class_id="cash", amount=100000),
                  Holding(id="h_eq", name="Equity investments", asset_class_id="equity_index", amount=50000)],
        goals=goals, emergency_fund=EmergencyFundSettings(months_of_essentials=6))


PPF_LOCK_YEARS = 10


def _family(name: str, start: str, p: dict[str, float]) -> FinancePlan:
    # The long lock-in holding is earmarked to education only when it unlocks by the education date; otherwise
    # the earmark would fail preflight (EARMARK_LOCKED_PAST_GOAL) and the holding stays in the pool.
    edu_earmarks = ([Earmark(holding_id="h_ppf", amount=300000)]
                    if int(p["education_in_years"]) >= PPF_LOCK_YEARS else [])
    edu_month = _years(start, p["education_in_years"])
    exps = [Expense(id="living", name="Household costs", category="living", amount=p["essentials"], essential=True),
            Expense(id="school_fees", name="School fees", category="education", amount=18000, frequency="quarterly",
                    essential=True, inflation_pct=9.0, end_month=tg.add_months(edu_month, -1)),
            Expense(id="lifestyle", name="Lifestyle", category="lifestyle", amount=p["discretionary"],
                    essential=False)]
    incs = [IncomeStream(id="salary", name="Salary", kind="salary", amount=p["take_home"], growth_pct=2.5,
                         inflation_linked=True)]
    goals = [
        Goal(id="home", name="Home down payment", kind="home", target_amount=p["home_down_payment"],
             target_month=_years(start, p["home_in_years"]), priority="must", flexibility_months=6),
        Goal(id="education", name="Child education", kind="education", target_amount=p["education_cost"],
             target_month=edu_month, priority="must", inflation_pct=9.0, earmarked=edu_earmarks),
        Goal(id="retirement", name="Retirement", kind="retirement", target_amount=retirement_target(exps, incs),
             target_month=_years(start, _years_to_retirement(p)), priority="must"),
    ]
    return FinancePlan(
        name=name, start_month=start,
        profile=Profile(age=int(p["age"]), retirement_age=int(p["retirement_age"]), risk_tolerance=3),
        incomes=incs, expenses=exps,
        debts=[Debt(id="car_loan", name="Car loan", kind="vehicle", balance=300000, interest_rate_pct=9.0,
                    emi=10000)],
        holdings=[Holding(id="h_cash", name="Savings account", asset_class_id="cash", amount=600000),
                  Holding(id="h_eq", name="Equity investments", asset_class_id="equity_index", amount=800000),
                  Holding(id="h_ppf", name="Long lock-in savings", asset_class_id="govt_long", amount=400000,
                          locked_until_month=_years(start, PPF_LOCK_YEARS))],
        goals=goals, emergency_fund=EmergencyFundSettings(months_of_essentials=6))


def _near(name: str, start: str, p: dict[str, float]) -> FinancePlan:
    ret_month = _years(start, _years_to_retirement(p))
    work_end = tg.add_months(ret_month, -1)
    exps = [Expense(id="living", name="Living costs", category="living", amount=p["essentials"], essential=True),
            Expense(id="work_costs", name="Work-related costs", category="work", amount=10000, essential=True,
                    end_month=work_end),
            Expense(id="lifestyle", name="Lifestyle", category="lifestyle", amount=p["discretionary"],
                    essential=False)]
    incs = [IncomeStream(id="salary", name="Salary", kind="salary", amount=p["take_home"], growth_pct=1.5,
                         inflation_linked=True, end_month=work_end),
            IncomeStream(id="rent_in", name="Rent from second flat", kind="rental", amount=20000, growth_pct=0.0,
                         inflation_linked=True, interruptible=False)]
    goals = [
        Goal(id="retirement", name="Retirement", kind="retirement", target_amount=retirement_target(exps, incs),
             target_month=ret_month, priority="must"),
        Goal(id="wedding", name="Wedding", kind="wedding", target_amount=p["wedding_cost"],
             target_month=_years(start, p["wedding_in_years"]), priority="nice", flexibility_months=12),
    ]
    return FinancePlan(
        name=name, start_month=start,
        profile=Profile(age=int(p["age"]), retirement_age=int(p["retirement_age"]), risk_tolerance=2),
        incomes=incs, expenses=exps,
        holdings=[Holding(id="h_cash", name="Savings account", asset_class_id="cash", amount=600000),
                  Holding(id="h_eq", name="Equity investments", asset_class_id="equity_index", amount=5500000),
                  Holding(id="h_debt", name="Debt investments", asset_class_id="short_debt", amount=2500000),
                  Holding(id="h_lock", name="Long lock-in savings", asset_class_id="govt_long", amount=4500000,
                          locked_until_month=_years(start, 3))],
        goals=goals, emergency_fund=EmergencyFundSettings(months_of_essentials=9))


def _blank(name: str, start: str, p: dict[str, float]) -> FinancePlan:
    return FinancePlan(name=name, start_month=start)


TEMPLATES: dict[str, FinanceTemplate] = {
    "young_professional": FinanceTemplate(
        "young_professional", "Young professional",
        "First job: build an emergency fund, a car in three years (a stretch) and retirement saving.",
        [P(name="age", label="Your age", type="int", default=25, min=18, max=40),
         P(name="take_home", label="Monthly take-home pay", type="money", default=60000, min=10000, max=1e7),
         P(name="essentials", label="Essential monthly spending", type="money", default=26000, min=0, max=1e7),
         P(name="discretionary", label="Other monthly spending", type="money", default=12000, min=0, max=1e7),
         P(name="car_price", label="Car price (today's money)", type="money", default=900000, min=1, max=1e9),
         P(name="car_in_years", label="Car in how many years", type="month_offset_years", default=3, min=1,
           max=15),
         P(name="retirement_age", label="Retirement age", type="int", default=60, min=45, max=70)],
        _young),
    "family": FinanceTemplate(
        "family", "Family",
        "Two earners with a car loan and school fees, saving for a home, a child's education and retirement.",
        [P(name="age", label="Your age", type="int", default=35, min=25, max=55),
         P(name="take_home", label="Household take-home pay (all earners)", type="money", default=180000,
           min=10000, max=1e7),
         P(name="essentials", label="Essential monthly spending", type="money", default=75000, min=0, max=1e7),
         P(name="discretionary", label="Other monthly spending", type="money", default=20000, min=0, max=1e7),
         P(name="home_down_payment", label="Home down payment (today's money)", type="money", default=1500000,
           min=1, max=1e10),
         P(name="home_in_years", label="Home in how many years", type="month_offset_years", default=3, min=1,
           max=10),
         P(name="education_cost", label="Education cost (today's money)", type="money", default=2500000, min=1,
           max=1e10),
         P(name="education_in_years", label="Education in how many years", type="month_offset_years", default=15,
           min=3, max=20),
         P(name="retirement_age", label="Retirement age", type="int", default=60, min=45, max=70)],
        _family),
    "near_retirement": FinanceTemplate(
        "near_retirement", "Near retirement",
        "Eight years from retirement with substantial savings and rent from a second flat, planning a family "
        "wedding.",
        [P(name="age", label="Your age", type="int", default=52, min=45, max=65),
         P(name="take_home", label="Monthly take-home pay", type="money", default=200000, min=10000, max=1e7),
         P(name="essentials", label="Essential monthly spending", type="money", default=70000, min=0, max=1e7),
         P(name="discretionary", label="Other monthly spending", type="money", default=25000, min=0, max=1e7),
         P(name="retirement_age", label="Retirement age", type="int", default=60, min=50, max=75),
         P(name="wedding_cost", label="Wedding cost (today's money)", type="money", default=1500000, min=1,
           max=1e10),
         P(name="wedding_in_years", label="Wedding in how many years", type="month_offset_years", default=3,
           min=1, max=10)],
        _near),
    "blank": FinanceTemplate("blank", "Start from scratch", "An empty plan with default assumptions.", [], _blank),
}


def get_template(template_id: str) -> FinanceTemplate:
    return TEMPLATES[template_id]
