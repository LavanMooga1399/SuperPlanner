"""Third fix round: rule-based reader defects that silently produced wrong numbers.

Each group reproduces the reported steps first and then checks variations of the general rule behind the fix:
- a duration range ("10-15 hours", "2-3 weeks") is never a clock window;
- a 4-digit number is a year only in a date-like position; next to a frequency anywhere in its clause it is money;
  out-of-range years are never money and never a second goal;
- a one-off payment in the past ("paid", "spent", "bought", "last month") is never income, an expense or a goal.
"""

from __future__ import annotations

import time

import pytest

from p2_helpers import ctx
from superplanner.intake import describe_finance, describe_schedule
from superplanner.intake.text.numbers import find_money

SALARY = "I earn 1 lakh a month. "


def _sched(text: str, kind: str = "project"):
    return describe_schedule(text, ctx(kind=kind))


def _fin(text: str):
    return describe_finance(text, ctx())


def _dur(t) -> tuple[float, float, float, str] | None:
    d = t.duration
    return None if d is None else (d.optimistic, d.likely, d.pessimistic, d.unit)


def _codes(r) -> list[str]:
    return [n.code for n in r.notes]


# ---------------------------------------------------------------- 1. two-digit duration ranges

@pytest.mark.parametrize("text,kind,name,dur", [
    # reported steps
    ("- Physics 10-15 hours", "study", "Physics", (10, 12.5, 15, "hours")),
    ("- Physics 10 to 15 hours", "study", "Physics", (10, 12.5, 15, "hours")),
    ("- Chemistry 8-12 hours", "study", "Chemistry", (8, 10, 12, "hours")),
    ("- Wiring 8-12 hours", "project", "Wiring", (8, 10, 12, "hours")),
    ("- Wiring 13-20 hours", "project", "Wiring", (13, 16.5, 20, "hours")),
    ("Study physics 10-15 hours.", "study", "Study physics", (10, 12.5, 15, "hours")),
    # variations
    ("- Wiring 10-15 hours", "project", "Wiring", (10, 12.5, 15, "hours")),
    ("- Review 12 - 16 hrs", "project", "Review", (12, 14, 16, "hours")),
    ("- Testing 10 to 12 h", "project", "Testing", (10, 11, 12, "hours")),
    ("- Paint the hall 10-14 days", "project", "Paint the hall", (10, 12, 14, "days")),
    ("- Build the site 2-3 weeks", "project", "Build the site", (2, 2.5, 3, "weeks")),
    ("- Plumbing work 11-12 hours", "project", "Plumbing work", (11, 11.5, 12, "hours")),
    ("Write the report 10-12 hours.", "project", "Write the report", (10, 11, 12, "hours")),
    ("- Shift the furniture 9-11 hours", "project", "Shift the furniture", (9, 10, 11, "hours")),
    ("- Revise algebra 2-3 hours", "study", "Revise algebra", (2, 2.5, 3, "hours")),
])
def test_duration_range_is_never_a_clock_window(text, kind, name, dur):
    r = _sched(text, kind)
    tasks = [t for t in r.draft.tasks if not t.milestone]
    assert [(t.name, _dur(t)) for t in tasks] == [(name, dur)]
    assert r.draft.working_time is None


@pytest.mark.parametrize("text,window", [
    ("We work 9 to 5, Monday to Friday. Write report 2 days", ("09:00", "17:00")),
    ("I work 10am-6pm. Write report 10-15 hours", ("10:00", "18:00")),
    ("Office hours 09:00-17:00. Paint 2-3 weeks", ("09:00", "17:00")),
    ("Available from 10 to 4. Wiring 13-20 hours", ("10:00", "16:00")),
])
def test_clock_windows_still_read_next_to_duration_ranges(text, window):
    r = _sched(text)
    wt = r.draft.working_time
    assert wt is not None and (wt.windows[0].start, wt.windows[0].end) == window
    assert all(t.duration is not None for t in r.draft.tasks)


# ---------------------------------------------------------------- 2. years 2101-2200 (and beyond) are not money

@pytest.mark.parametrize("text,kind,target,month,far", [
    # reported steps
    ("Wedding in 2150, 20 lakh.", "wedding", 2_000_000, None, True),
    ("Goal: house in 2150, 50 lakh.", "home", 5_000_000, None, True),
    ("Want a house by 2101, 50 lakh.", "home", 5_000_000, "2101-10", False),
    ("Trip to Europe by 2120 for 3 lakh.", "travel", 300_000, "2120-10", False),
    ("Daughter's education in the year 2130: 25 lakh.", "education", 2_500_000, None, True),
    ("Car in December 2140, 8 lakh", "vehicle", 800_000, "2140-12", False),
    # variations
    ("House in 2199, Rs. 80 lakh.", "home", 8_000_000, None, True),
    ("Trip in 2105 for 5 lakh.", "travel", 500_000, "2105-10", False),
    ("Holiday in 9999, about 2 lakh.", "travel", 200_000, None, True),
    ("World trip by the year 2160: 40 lakh.", "travel", 4_000_000, None, True),
    ("Want to buy a car after 2180, 12 lakh.", "vehicle", 1_200_000, None, True),
])
def test_out_of_range_year_is_one_goal_with_the_stated_amount(text, kind, target, month, far):
    r = _fin(SALARY + text)
    assert [(g.kind, g.target.low, g.target_month) for g in r.draft.goals] == [(kind, target, month)]
    assert r.draft.expenses == [] and len(r.draft.incomes) == 1
    assert ("DATE_OUT_OF_RANGE" in _codes(r)) is far
    assert [q.code for q in r.questions].count("FIN_GOAL_DATE") == (1 if month is None else 0)


@pytest.mark.parametrize("text", ["Holiday in 1990", "We moved here in 2150.", "Since 2101 nothing."])
def test_year_in_a_date_position_is_never_money(text):
    r = _fin(SALARY + text)
    assert r.draft.goals == [] and r.draft.expenses == [] and len(r.draft.incomes) == 1


# ---------------------------------------------------------------- 3. year-like amounts with a frequency elsewhere

@pytest.mark.parametrize("text,amount", [
    # reported steps
    ("I give 2000 to my parents each month.", 2000),
    ("I send 2000 home every month.", 2000),
    ("We give 1950 to the temple monthly.", 1950),
    ("2000 to the newspaper guy every month.", 2000),
    ("Paying 2000 towards chit fund every month.", 2000),
    # variations (Indian and plain English, different word orders)
    ("I send home 2000 rupees a month.", 2000),
    ("Rs. 2,000 every month to my sister.", 2000),
    ("2000/month for the maid.", 2000),
    ("I spend about 2000 monthly on the gym.", 2000),
    ("Every month I pay 2000 for tuition.", 2000),
    ("Monthly 1999 goes to the milkman.", 1999),
    ("We give 2050 to the church every month.", 2050),
])
def test_year_like_amount_with_a_frequency_in_the_clause_is_money(text, amount):
    r = _fin(SALARY + text)
    assert [(e.amount.low, e.frequency) for e in r.draft.expenses] == [(amount, "monthly")]
    assert r.draft.goals == [] and len(r.draft.incomes) == 1


@pytest.mark.parametrize("text", ["Society maintenance is 2000.", "Water can 2000", "Electricity bill is around 2000.",
                                  "Maid charges 1990.", "Newspaper 2000"])
def test_year_like_amount_without_frequency_is_asked_or_noted_never_dropped(text):
    r = _fin(SALARY + text)
    asked = [e.amount.low for e in r.draft.expenses] in ([2000], [1990]) and any(
        q.code == "FIN_LOW_CONFIDENCE" for q in r.questions)
    assert asked or "YEAR_OR_AMOUNT" in _codes(r)


def test_years_in_date_positions_stay_years_next_to_money():
    r = _fin(SALARY + "Since 2019 I pay rent of 20k a month.")
    assert [e.amount.low for e in r.draft.expenses] == [20_000]
    r = _fin(SALARY + "We moved in 2019, rent 20k.")
    assert [e.amount.low for e in r.draft.expenses] == [20_000]
    assert "YEAR_OR_AMOUNT" not in _codes(r)
    assert find_money("2027") == [] and find_money("in 2150") == [] and find_money("by the year 2160") == []
    assert [m.low for m in find_money("I give 2000 to my parents each month")] == [2000]


# ---------------------------------------------------------------- 4. past one-off payments

@pytest.mark.parametrize("text", [
    # reported steps
    "I paid 50k for a fridge last month.",
    "Paid 2 lakh for repairs last year.",
    "We paid 3 lakh for the wedding in 2024.",
    # variations
    "I spent 50k for a fridge last month.",
    "Last month we paid Rs. 15,000 for the car service.",
    "Paid 20k for the school trip two months ago.",
    "Bought a bike for ₹90,000 last year.",
    "Spent about 2 lakh on my sister's wedding.",
    "We paid 40000 rupees to the plumber yesterday.",
])
def test_past_payment_is_a_note_only(text):
    r = _fin(SALARY + text)
    assert [(i.name, i.amount.low) for i in r.draft.incomes] == [("Salary", 100_000)]
    assert r.draft.expenses == [] and r.draft.goals == [] and r.draft.holdings == []
    assert "PAST_PURCHASE" in _codes(r)


@pytest.mark.parametrize("text,income,expense", [
    ("I get paid 80k a month.", [80_000], []),
    ("I pay 2000 every month for the gym.", [100_000], [2000]),
    ("I pay 5k a month for the gym.", [100_000], [5000]),
])
def test_present_payments_still_read(text, income, expense):
    r = _fin(text if text.startswith("I get") else SALARY + text)
    assert [i.amount.low for i in r.draft.incomes] == income
    assert [e.amount.low for e in r.draft.expenses] == expense


# ---------------------------------------------------------------- linear time on long inputs

@pytest.mark.parametrize("text,fn", [
    (("10-15 hours " * 2000)[:20000], "s"),
    (("- Physics 10-15 hours\n" * 1000)[:20000], "s"),
    (("1" * 20000), "s"),
    (("12-" * 7000)[:20000], "s"),
    (("I give 2000 to my parents each month. " * 600)[:20000], "f"),
    (("Wedding in 2150, 20 lakh. " * 800)[:20000], "f"),
    (("I paid 50k for a fridge last month. " * 600)[:20000], "f"),
    (("2000 " * 4000)[:20000], "f"),
])
def test_long_inputs_stay_fast(text, fn):
    t0 = time.monotonic()
    _sched(text) if fn == "s" else _fin(text)
    assert time.monotonic() - t0 < 2.0
