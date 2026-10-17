"""PHASE2 2.7.1-2.7.4 grammar, table-driven: numbers/money, durations, dates, segmentation, linear time."""

from __future__ import annotations

import time
from datetime import date

import pytest

from superplanner.intake.text.dates import find_dates, parse_month_text, role_of
from superplanner.intake.text.durations import find_durations, parse_duration_text
from superplanner.intake.text.numbers import (find_money, find_percent, frequency_anywhere, parse_money_text,
                                              parse_number)
from superplanner.intake.text.segment import normalise, segments

TODAY = date(2026, 10, 17)   # a Saturday


@pytest.mark.parametrize("text,low,high,cur", [
    ("12,50,000", 1250000, 1250000, None),
    ("1,250,000", 1250000, 1250000, None),
    ("₹1,20,000", 120000, 120000, "INR"),
    ("Rs. 5000", 5000, 5000, "INR"),
    ("Rs 5,000", 5000, 5000, "INR"),
    ("INR 2500", 2500, 2500, "INR"),
    ("$400", 400, 400, "USD"),
    ("300 USD", 300, 300, "USD"),
    ("€1.5k", 1500, 1500, "EUR"),
    ("5000 rupees", 5000, 5000, "INR"),
    ("40-50k", 40000, 50000, None),
    ("40k-50k", 40000, 50000, None),
    ("1.2 to 1.5 lakh", 120000, 150000, None),
    ("between 2 and 3 lakh", 200000, 300000, None),
    ("₹40-50k", 40000, 50000, "INR"),
    ("3 lakhs", 300000, 300000, None),
    ("2 lacs", 200000, 200000, None),
    ("8L", 800000, 800000, None),
    ("2.5 Cr", 25000000, 25000000, None),
    ("1 crore", 10000000, 10000000, None),
    ("60k", 60000, 60000, None),
    ("15 thousand", 15000, 15000, None),
    ("2 million", 2000000, 2000000, None),
    ("1.5 bn", 1.5e9, 1.5e9, None),
])
def test_money(text, low, high, cur):
    ms = find_money(text)
    assert len(ms) == 1, ms
    assert (ms[0].low, ms[0].high, ms[0].currency) == (low, high, cur)
    assert parse_money_text(text) == (low, high)


@pytest.mark.parametrize("text,freq", [
    ("20k per month", "monthly"), ("20k a month", "monthly"), ("20k monthly", "monthly"), ("20k/month", "monthly"),
    ("20k pm", "monthly"), ("2 lakh per year", "yearly"), ("2 lakh annually", "yearly"), ("2 lakh p.a.", "yearly"),
    ("18k every quarter", "quarterly"), ("18k quarterly", "quarterly"), ("9k every 6 months", "half_yearly"),
    ("9k twice a year", "half_yearly"), ("50k one-time", "once"), ("50k lump sum", "once"), ("50k", None),
])
def test_frequency(text, freq):
    assert find_money(text)[0].frequency == freq


def test_money_approx_and_spans():
    s = "take home about 1.2 lakh a month"
    m = find_money(s)[0]
    assert m.approx and m.confidence == 0.8 and s[m.start:m.end] == "about 1.2 lakh a month"
    assert find_money("~50k")[0].approx


@pytest.mark.parametrize("text", ["retire at 60", "I'm 34", "in 3 years", "3 months", "9%", "2027", "10 people"])
def test_not_money(text):
    assert find_money(text) == []


def test_percent_and_numbers():
    assert [p.value for p in find_percent("at 9% interest, 8.5 percent p.a., 3 pc")] == [9, 8.5, 3]
    assert parse_number("ten") == (10, 0.95) and parse_number("twenty five") == (25, 0.95)
    assert parse_number("a couple of") == (2, 0.6) and parse_number("a few") == (3, 0.4)
    assert parse_number("half") == (0.5, 0.95) and parse_number("dozen") == (12, 0.95)
    assert frequency_anywhere("monthly rent") == "monthly"


@pytest.mark.parametrize("text,o,m,p,unit", [
    ("2-3 weeks", 2, 2.5, 3, "weeks"), ("2 to 3 days", 2, 2.5, 3, "days"), ("between 2 and 3 days", 2, 2.5, 3, "days"),
    ("2/3/5 days", 2, 3, 5, "days"), ("optimistic 2, likely 3, pessimistic 5 days", 2, 3, 5, "days"),
    ("3 days (2-5)", 2, 3, 5, "days"), ("best 2 worst 5 days, probably 3", 2, 3, 5, "days"),
    ("90 min", 90, 90, 90, "minutes"), ("1.5h", 1.5, 1.5, 1.5, "hours"), ("3 hrs", 3, 3, 3, "hours"),
    ("half a day", 0.5, 0.5, 0.5, "days"), ("half an hour", 30, 30, 30, "minutes"),
    ("an hour and a half", 1.5, 1.5, 1.5, "hours"), ("a day", 1, 1, 1, "days"), ("a week", 1, 1, 1, "weeks"),
    ("three hours", 3, 3, 3, "hours"), ("2-3 d", 2, 2.5, 3, "days"), ("1 w", 1, 1, 1, "weeks"),
    ("2 wks", 2, 2, 2, "weeks"),
])
def test_durations(text, o, m, p, unit):
    d = find_durations(text)
    assert len(d) == 1, d
    assert (d[0].optimistic, d[0].likely, d[0].pessimistic, d[0].unit) == (o, m, p, unit)


def test_months_become_weeks_with_lower_confidence():
    d = find_durations("2 months")[0]
    assert d.unit == "weeks" and d.likely == pytest.approx(8.66) and d.confidence == 0.7 and d.note


def test_a_few_is_low_confidence():
    assert find_durations("a few days")[0].confidence == 0.4


def test_duration_cells_with_default_unit():
    assert parse_duration_text("4", "hours").likely == 4
    d = parse_duration_text("2-6", "days")
    assert (d.optimistic, d.likely, d.pessimistic, d.unit) == (2, 4, 6, "days")


@pytest.mark.parametrize("text,locale,value,alt", [
    ("2026-11-03", "en-IN", date(2026, 11, 3), None),
    ("03/11/2026", "en-IN", date(2026, 11, 3), None),
    ("03/11/2026", "en-GB", date(2026, 11, 3), None),
    ("03/11/2026", "en-US", date(2026, 3, 11), None),
    ("03/11/2026", "other", date(2026, 11, 3), date(2026, 3, 11)),
    ("25/12/2026", "other", date(2026, 12, 25), None),
    ("12 Nov 2026", "en-IN", date(2026, 11, 12), None),
    ("Nov 12, 2026", "en-US", date(2026, 11, 12), None),
    ("12th November", "en-IN", date(2026, 11, 12), None),
    ("12 Jan", "en-IN", date(2027, 1, 12), None),
    ("17 Oct", "en-IN", date(2026, 10, 17), None),
])
def test_absolute_dates(text, locale, value, alt):
    d = find_dates(text, TODAY, locale)
    assert len(d) == 1, d
    assert d[0].value == value and d[0].alternative == alt


@pytest.mark.parametrize("text,value", [
    ("today", date(2026, 10, 17)), ("tomorrow", date(2026, 10, 18)), ("next Monday", date(2026, 10, 19)),
    ("next Saturday", date(2026, 10, 24)), ("this Saturday", date(2026, 10, 17)), ("this Friday", date(2026, 10, 23)),
    ("in 10 days", date(2026, 10, 27)), ("in 2 weeks", date(2026, 10, 31)), ("in 3 months", date(2027, 1, 17)),
    ("in 2 years", date(2028, 10, 17)), ("within 3 weeks", date(2026, 11, 7)),
    ("end of this month", date(2026, 10, 31)), ("end of next month", date(2026, 11, 30)),
    ("end of this week", date(2026, 10, 18)), ("end of next year", date(2027, 12, 31)),
    ("3 years from now", date(2029, 10, 17)), ("next year", date(2027, 10, 17)),
    ("March 2027", date(2027, 3, 31)), ("Mar '27", date(2027, 3, 31)),
])
def test_relative_and_month_dates(text, value):
    d = find_dates(text, TODAY)
    assert len(d) == 1, (text, d)
    assert d[0].value == value


def test_roles_and_months():
    s = "Launch by 15 Dec 2026"
    d = find_dates(s, TODAY)[0]
    role, start = role_of(s, d.start)
    assert role == "deadline" and s[start:d.end] == "by 15 Dec 2026"
    s2 = "Website relaunch starting next Monday"
    d2 = find_dates(s2, TODAY)[0]
    assert role_of(s2, d2.start)[0] == "start"
    assert role_of("no later than 2026-11-03", 14)[0] == "deadline"
    assert parse_month_text("March 2027", TODAY) == "2027-03" and parse_month_text("2028-02", TODAY) == "2028-02"


def test_segments_and_offsets():
    text = "Plan “A” – start.\n1. First step (₹ 500)\n- second\nThird thing; fourth one. Costs Rs. 50 p.a. ok"
    t = normalise(text)
    segs = segments(t)
    assert [s.text for s in segs] == ['Plan "A" - start', "First step (₹ 500)", "second", "Third thing",
                                      "fourth one", "Costs Rs. 50 p.a. ok"]
    assert segs[1].numbered and segs[1].bullet and segs[2].bullet and not segs[2].numbered
    sp = t.span(segs[1].start, segs[1].end)
    assert text[sp.start:sp.end] == "First step (₹ 500)"


def test_code_point_offsets_with_emoji():
    text = "🚀 Launch by 15 Dec 2026"
    t = normalise(text)
    d = find_dates(t.norm, TODAY)[0]
    sp = t.span(d.start, d.end)
    assert text[sp.start:sp.end] == "15 Dec 2026" and sp.start == 12


ADVERSARIAL = [
    "1" * 20000,
    ",".join(["1"] * 10000),
    " ".join(["Ravi"] * 4000),
    "\n".join(["- " + "a" * 20] * 850),
    ("1,2" * 7000)[:20000],
    ("after " * 4000)[:20000],
    ("12/12/" * 4000)[:20000],
    ("between 1 and " * 2000)[:20000],
    ("Aa Bb Cc, " * 2500)[:20000],
    ("once the " * 2500)[:20000],
    ("a " * 10000)[:20000],
    ("( " * 10000)[:20000],
    ("2-3-4-5-6-" * 2000)[:20000],
    ("9 to 5 " * 3000)[:20000],
    ("1.2.3.4." * 2500)[:20000],
    ("twenty five " * 1700)[:20000],
    ("- Task (Ravi, Priya, " * 1000)[:20000],
    ("I need 5 lakh, " * 1400)[:20000],
    ("x" * 19990) + " 3 days",
]


@pytest.mark.parametrize("text", ADVERSARIAL, ids=[f"adv{i}" for i in range(len(ADVERSARIAL))])
def test_linear_time_on_adversarial_text(text):
    from intake_helpers import CTX, FIN_CTX
    from superplanner import intake

    assert len(text) <= 20000
    t0 = time.perf_counter()
    try:
        intake.describe_schedule(text, CTX)
    except intake.IntakeError:
        pass
    t1 = time.perf_counter()
    try:
        intake.describe_finance(text, FIN_CTX)
    except intake.IntakeError:
        pass
    t2 = time.perf_counter()
    assert t1 - t0 < 2.0 and t2 - t1 < 2.0, (t1 - t0, t2 - t1)
