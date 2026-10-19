"""Specific grammar rules of PHASE2 2.7 checked one by one (each test cites its rule), plus reader speed on
20,000-character realistic and adversarial texts (2.7 safety rule)."""

from __future__ import annotations

import random
import time

import pytest

from p2_helpers import ctx
from superplanner.intake import describe_finance, describe_schedule


def names(text, kind=None):
    return [t.name for t in describe_schedule(text, ctx(kind=kind)).draft.tasks]


def test_inline_list_after_colon_drops_the_label():
    """2.7.1: inline lists after a colon - "Steps: design, build and test" gives three tasks."""
    assert names("Steps: design, build and test") == ["Design", "Build", "Test"]
    assert names("Steps: design 2 days, build 5 days and test 2 days.") == ["Design", "Build", "Test"]


def test_study_subjects_list_becomes_groups():
    """2.7.5 study: `subjects?: a, b, c` -> groups (one per subject); nothing is dropped silently (2.1)."""
    r = describe_schedule("Exam on 10 Feb 2027. Subjects: maths 20 hours, physics 15 hours, chemistry 12 hours.",
                          ctx(kind="study"))
    groups = {t.group for t in r.draft.tasks if not t.milestone}
    assert {"Maths", "Physics", "Chemistry"} <= {g.capitalize() for g in groups if g}, \
        [(t.name, t.group) for t in r.draft.tasks]
    work = {t.group.capitalize(): t.duration.likely for t in r.draft.tasks if not t.milestone and t.group}
    assert work.get("Physics") == 15 and work.get("Chemistry") == 12, work


def test_subjects_without_durations_are_not_silently_dropped():
    r = describe_schedule("Exam on 10 Feb 2027. Subjects: maths, physics, chemistry.", ctx(kind="study"))
    texts = " ".join([t.name + " " + (t.group or "") for t in r.draft.tasks] + [n.message for n in r.notes])
    for s in ("maths", "physics", "chemistry"):
        assert s in texts.lower(), [(t.name, t.group) for t in r.draft.tasks]


def test_hard_deadline_phrase_is_removed_from_the_name():
    """2.7.5: the name is the item text with recognised date phrases removed ("must be done by <date>")."""
    r = describe_schedule("- Pay the advance 1 hour, must be done by 25 Oct 2026", ctx())
    t = r.draft.tasks[0]
    assert t.deadline is not None and t.deadline.isoformat() == "2026-10-25" and t.deadline_hard
    assert t.name == "Pay the advance"


@pytest.mark.parametrize("text,amount", [
    ("FD of ₹5L maturing in 2028.", 500000),
    ("I hold gold worth 3 lakh.", 300000),
])
def test_savings_phrases_never_become_monthly_expenses(text, amount):
    """A statement about money already held (FD, gold) must not be read as spending of that amount every
    month: the reader has no expense cue here (2.7.9), and a 5 lakh/month expense makes the plan absurd."""
    d = describe_finance(text, ctx()).draft
    bad = [(e.name, e.amount, e.frequency) for e in d.expenses if e.amount and e.amount.high == amount]
    assert not bad, bad


def test_paying_a_maid_salary_is_spending_not_income():
    d = describe_finance("Maid salary 6,000 per month. I take home 80k a month.", ctx()).draft
    assert [i.amount.low for i in d.incomes if i.amount] == [80000], [(i.name, i.amount) for i in d.incomes]
    assert any(e.amount and e.amount.low == 6000 for e in d.expenses)


def _realistic_long(seed: int, domain: str) -> str:
    rnd = random.Random(seed)
    if domain == "schedule":
        parts = ["- Design module {n} 2-3 days after module {m}, Ravi", "{n}. Test build {n} 4 hours (Priya)",
                 "Review chapter {n} by 12 Nov 2026.", "Ravi and Priya will review module {m} together.",
                 "Cut batch {n} 3/4/6 hours then paint batch {n} 2 hours"]
    else:
        parts = ["I earn 1.{n} lakh a month.", "Rent {n}k per month, school fees 18k every quarter.",
                 "We have {n} lakh in FD and {m}L in mutual funds.", "Car loan EMI {n},000, {m} lakh left at 9%.",
                 "We want {n} lakh for a flat in {m} years."]
    out, n = [], 0
    while sum(len(x) + 1 for x in out) < 19_800:
        n += 1
        out.append(rnd.choice(parts).format(n=n % 97 + 1, m=max(1, n % 13)))
    return "\n".join(out)[:20_000]


@pytest.mark.parametrize("domain", ["schedule", "finance"])
@pytest.mark.parametrize("kind", ["realistic", "digits", "commas", "caps", "bullets", "ranges"])
def test_long_texts_finish_under_two_seconds(domain, kind):
    text = {"realistic": _realistic_long(3, domain),
            "digits": "1" * 20_000,
            "commas": "1," * 10_000,
            "caps": ("Ravi Priya Anil Meena " * 1000)[:20_000],
            "bullets": ("- a 2-3 days after b\n" * 1000)[:20_000],
            "ranges": ("between 1 and 2 lakh to 3 crore - " * 600)[:20_000]}[kind]
    fn = describe_schedule if domain == "schedule" else describe_finance
    t0 = time.monotonic()
    fn(text, ctx())
    assert time.monotonic() - t0 < 2.0


# The example texts the Describe page shows as placeholders (frontend/src/intake/pages/DescribePage.tsx
# PLACEHOLDER): a user who copies the app's own example must get a sensible draft.
STUDY_PLACEHOLDER = ("My exam is in 90 days. I can study three hours on weekdays and eight hours on weekends.\n"
                     "Subjects: Physics, Chemistry and Maths. I want to revise everything twice and do ten mock tests.")
PRODUCTION_PLACEHOLDER = ("Two machines, two shifts Monday to Saturday.\n"
                          "Order A: cutting 3 h, then welding 2 h, then painting 1 h, due Friday.\n"
                          "Order B: cutting 2 h, then assembly 4-5 h, due next Wednesday.")


def test_study_placeholder_gives_exam_subjects_and_revisions():
    """2.7.5 study: `exam ... in <date>` -> milestone "Exam" with a hard deadline; subjects -> groups (not
    people); `revise everything twice` -> revision tasks."""
    r = describe_schedule(STUDY_PLACEHOLDER, ctx(kind="study"))
    d = r.draft
    exam = [t for t in d.tasks if t.milestone]
    assert len(exam) == 1 and exam[0].name == "Exam", [t.name for t in exam]
    assert exam[0].deadline is not None and exam[0].deadline.isoformat() == "2027-01-15" and exam[0].deadline_hard
    people = [x.name for x in d.resources if x.kind == "person"]
    assert not {"Physics", "Chemistry", "Maths"} & set(people), people
    assert "SCHED_PEOPLE" not in {q.code for q in r.questions}
    assert any(t.name.startswith("Revise") for t in d.tasks), [t.name for t in d.tasks]


def test_production_placeholder_names_are_clean():
    """2.7.5: names drop recognised date phrases; 2.7.1: a "label:" before an inline list is not part of a name."""
    d = describe_schedule(PRODUCTION_PLACEHOLDER, ctx(kind="production")).draft
    bad = [t.name for t in d.tasks if "due" in t.name.lower() or ":" in t.name]
    assert not bad, [t.name for t in d.tasks]
