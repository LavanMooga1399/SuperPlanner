"""Second fix round: regression tests for the tester's defects (intake reader, table import, duration risk).

Each test reproduces the reported steps first and then checks the general rule behind the fix.
"""

from __future__ import annotations

import random
import time

import pytest

from p2_helpers import API, CTX_JSON, ctx, solve_and_check
from superplanner.intake import (Answer, answer_schedule, build_schedule, describe_finance, describe_schedule)

FIN_JSON = {"today": "2026-10-17", "locale": "en-IN", "currency": "INR"}


def _sched(text: str, kind: str = "project"):
    return describe_schedule(text, ctx(kind=kind))


def _fin(text: str):
    return describe_finance(text, ctx())


def _describe(client, text: str, kind: str = "project"):
    return client.post(f"{API}/intake/schedule/describe", json={"text": text, "context": {**CTX_JSON, "kind": kind}})


def _apply(client, text: str):
    body = {"text": text, "delimiter": "\t", "has_header": False,
            "mapping": [{"column": 0, "field": "name"}, {"column": 1, "field": "duration"},
                        {"column": 2, "field": "predecessors"}], "context": CTX_JSON}
    t0 = time.monotonic()
    r = client.post(f"{API}/intake/schedule/table/apply", json=body)
    return r, time.monotonic() - t0


# ---------------------------------------------------------------- 1. table import is near-linear

def _common_words_table(rows: int) -> str:
    refs = ",".join(f"install the shared common widget module number {n}x" for n in range(40))
    return "\n".join(f"Install the shared common widget module number {i}\t2 h\t{refs}" for i in range(rows))


@pytest.mark.parametrize("rows", [125, 250, 470])
def test_table_apply_common_word_references_are_fast(client, rows):
    text = _common_words_table(rows)
    assert len(text) <= 1_000_000
    r, elapsed = _apply(client, text)
    assert r.status_code == 200, r.text[:300]
    assert elapsed < 2.0, elapsed
    assert all(t["after"] == [] for t in r.json()["draft"]["tasks"])     # every reference is ambiguous/unmatched


def test_table_apply_rare_token_references_are_fast(client):
    """Every token shared by about 50 names (below the 'common' limit) and 50 references per row: 1 MB."""
    rnd = random.Random(1)
    voc = [f"tok{j}" for j in range(80)]
    names = [" ".join(rnd.sample(voc, 8)) for _ in range(500)]
    text = "\n".join(f"{names[i]}\t2 h\t" + ",".join(" ".join(rnd.sample(voc, 6)) for _ in range(50))
                     for i in range(500))[:1_000_000]
    r, elapsed = _apply(client, text)
    assert r.status_code == 200, r.text[:300]
    assert elapsed < 2.0, elapsed


def test_table_references_still_resolve_among_common_words(client):
    rows = [f"Install the shared widget module {i}\t1 h\t" for i in range(120)]
    rows.append("Design review\t1 h\t")
    rows.append("Final check\t1 h\tinstall the shared widget module 7, design review, install the shared widget")
    r, _ = _apply(client, "\n".join(rows))
    assert r.status_code == 200
    tasks = r.json()["draft"]["tasks"]
    assert tasks[-1]["after"] == ["row7", "row120"]        # rare token "7" and the exact name; the last is ambiguous
    assert any("install the shared widget" in n["message"] for n in r.json()["row_notes"])


# ---------------------------------------------------------------- 3. prose sentences with deadline wording

def _tasks(r):
    return [(t.name, t.deadline.isoformat() if t.deadline else None, t.deadline_hard) for t in r.draft.tasks]


@pytest.mark.parametrize("prefix", ["", "Wedding planning: "])
def test_prose_deadline_sentences_give_one_task_each(prefix):
    text = (f"{prefix}{'b' if prefix else 'B'}ook the venue 1 day, must be done by 1 Dec. "
            "Send invites 2 days, should be done by 10 Dec.")
    r = _sched(text)
    assert _tasks(r) == [("Book the venue", "2026-12-01", True), ("Send invites", "2026-12-10", False)]
    assert r.draft.resources == []
    assert not any(q.code == "SCHED_PEOPLE" for q in r.questions)
    if prefix:
        assert r.draft.tasks[0].group == "Wedding planning"


def test_prose_first_sentence_with_deadline_is_a_task():
    r = _sched("Pay the advance, must be done by 20 Nov. Steps: design, build and test.")
    assert _tasks(r) == [("Pay the advance", "2026-11-20", True), ("Design", None, False), ("Build", None, False),
                         ("Test", None, False)]


def test_month_abbreviation_with_full_stop_still_reads():
    r = _sched("- Deliver the report by Dec. 5\n- Plan the launch, due 3 Jan. Then relax")
    assert [t.deadline.isoformat() if t.deadline else None for t in r.draft.tasks][0] == "2026-12-05"


# ---------------------------------------------------------------- 4. goals, past purchases

def test_goal_noun_and_date_in_another_clause_is_a_goal():
    r = _fin("I earn 1 lakh a month. Wedding of my daughter in 2035, 20 lakh.")
    assert r.draft.expenses == []
    assert [(g.kind, g.target.low, g.target_month) for g in r.draft.goals] == [("wedding", 2_000_000, "2035-10")]


def test_spending_with_a_future_date_is_a_goal_not_monthly():
    r = _fin("I earn 1 lakh a month. Rent 20k. We spend 10 lakh on a car in 2028.")
    assert [(e.name, e.amount.low) for e in r.draft.expenses] == [("Rent", 20_000)]
    assert [(g.name, g.target.low, g.target_month) for g in r.draft.goals] == [("Car", 1_000_000, "2028-10")]


@pytest.mark.parametrize("text", ["Bought a phone for 60000 last month.", "We spent 50k on a sofa two months ago.",
                                  "Purchased a laptop for 80000 yesterday."])
def test_past_one_off_purchase_is_not_a_regular_cost(text):
    r = _fin(text)
    assert r.draft.expenses == [] and r.draft.goals == []
    assert [n.code for n in r.notes] == ["PAST_PURCHASE"]


def test_uncued_amount_is_asked_never_silent():
    r = _fin("I earn 1 lakh a month. Something 5000.")
    exp = r.draft.expenses
    assert len(exp) == 1
    assert any(q.code == "FIN_LOW_CONFIDENCE" for q in r.questions)


# ---------------------------------------------------------------- 5./6. no 422 for valid text

@pytest.mark.parametrize("text", [
    "My exam is in 90 days. " + "Do ten mock tests. " * 51,
    "Exam on 10 Feb 2027.\n" + "".join(f"- Topic {i} 2 hours\n" for i in range(600)),
], ids=["510-mock-tests", "600-topics"])
def test_long_study_lists_are_capped_with_a_note(client, text):
    r = _describe(client, text, "study")
    assert r.status_code == 200, r.text[:400]
    d = r.json()["draft"]
    assert len(d["tasks"]) <= 500
    assert all(len(t["after"]) <= 500 for t in d["tasks"])
    keys = {t["key"] for t in d["tasks"]}
    assert all(a in keys for t in d["tasks"] for a in t["after"])
    exam = [t for t in d["tasks"] if t["name"] == "Exam"]
    assert len(exam) == 1 and exam[0]["after"]
    assert any(n["code"] == "LIST_CAPPED" for n in r.json()["notes"])


@pytest.mark.parametrize("text,kind,code", [
    ("- Build 999999 days", "project", "DURATION_TOO_LONG"),
    ("- Build 2000000 hours", "project", "DURATION_TOO_LONG"),
    ("- Build 70000 weeks", "project", "DURATION_TOO_LONG"),
    ("Launch in 99999999 days", "project", "DATE_OUT_OF_RANGE"),
    ("Exam is in 999999 days", "study", "DATE_OUT_OF_RANGE"),
    ("I have 99999999 days to prepare for the exam. Study physics.", "study", "DATE_OUT_OF_RANGE"),
    ("Subjects: physics 99999 hours, chemistry 3 hours", "study", "DURATION_TOO_LONG"),
])
def test_huge_durations_are_left_out_with_a_note(client, text, kind, code):
    r = _describe(client, text, kind)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert code in [n["code"] for n in body["notes"]]
    for t in body["draft"]["tasks"]:
        assert t["duration"] is None or t["duration"]["pessimistic"] <= 10000
        assert "optimistic" not in str([n["message"] for n in body["notes"]])
    assert all(t["name"] not in ("Exam is", "Launch in") for t in body["draft"]["tasks"])


def test_many_finance_items_are_capped_with_a_note():
    r = _fin("".join(f"Rent {i + 1}k a month. " for i in range(150)))
    assert len(r.draft.expenses) == 100
    assert "LIST_CAPPED" in [n.code for n in r.notes]
    assert not any(p.startswith("/expenses/e101/") for p in r.draft.provenance)


# ---------------------------------------------------------------- 7. year-like amounts with a frequency

@pytest.mark.parametrize("text,amount", [
    ("I earn 1 lakh a month. Rent 2000 a month.", 2000),
    ("I earn 1 lakh a month. Rent 1999 a month.", 1999),
    ("I earn 1 lakh a month. Rent 2050 a month.", 2050),
    ("I earn 1 lakh a month. Groceries 2000 a week.", round(2000 * 52 / 12, 2)),
    ("I earn 1 lakh a month. I spend 2000 a week on groceries.", round(2000 * 52 / 12, 2)),
    ("I earn 1 lakh a month. School fees 2100 every quarter.", 2100),
])
def test_number_followed_by_frequency_is_money(text, amount):
    r = _fin(text)
    assert [e.amount.low for e in r.draft.expenses] == [amount]


def test_year_like_amount_without_frequency_is_asked():
    r = _fin("I earn 1 lakh a month. Rent 2000.")
    assert [e.amount.low for e in r.draft.expenses] == [2000]
    assert any(q.code == "FIN_LOW_CONFIDENCE" for q in r.questions)
    r = _fin("I earn 1 lakh a month. We moved in 2019, rent 20k.")
    assert [e.amount.low for e in r.draft.expenses] == [20000]


# ---------------------------------------------------------------- 8. a year is never a goal amount

def test_out_of_range_year_is_not_a_goal_amount():
    r = _fin("I earn 1 lakh a month. Holiday in Goa on 31 Dec 9999, about 2 lakh.")
    assert [(g.kind, g.target.low) for g in r.draft.goals] == [("travel", 200_000)]
    assert [n.code for n in r.notes].count("DATE_OUT_OF_RANGE") == 1
    assert [q.code for q in r.questions].count("FIN_GOAL_DATE") == 1


# ---------------------------------------------------------------- 9. currency words

@pytest.mark.parametrize("phrase", ["200 pounds", "£200", "GBP 200", "200 GBP", "200 euros", "EUR 200", "€200",
                                    "200 dollars", "USD 200", "$200", "200 yen", "AED 200"])
def test_foreign_currency_words_raise_mixed_currency(phrase):
    r = _fin(f"I earn 1 lakh a month. Rent 20k. Course fee {phrase}.")
    assert "MIXED_CURRENCY" in [n.code for n in r.notes]
    assert any(e.amount.low == 200 for e in r.draft.expenses)


def test_rupees_only_raise_no_currency_note():
    r = _fin("I earn Rs 1 lakh a month. Rent ₹20k. Course fee 200 rupees.")
    assert "MIXED_CURRENCY" not in [n.code for n in r.notes]


# ---------------------------------------------------------------- 10. duration range message counts user tasks

def test_duration_risk_counts_user_tasks_not_parts(client):
    c = ctx(kind="project")
    r = describe_schedule("- Write 3-5 days (Ravi)", c)
    d = answer_schedule(r.draft, [Answer(question_id=q.id, use_default=True) for q in r.questions
                                  if q.default is not None], c).draft
    b = build_schedule(d, c)
    assert b.ready, b.blocking
    parts = [t for t in b.problem.tasks if t.duration_estimate is not None]
    assert len(parts) > 1                                   # the task is split into parts
    _, _, sch = solve_and_check(client, b.problem.model_dump(mode="json"), strategy="heuristic")
    risk = sch["explanation"]["duration_risk"]
    assert risk["tasks_with_range"] == 1
    assert risk["message"].startswith("1 task has a duration range")


# ---------------------------------------------------------------- 11. "due Friday" is no person; study sentences

@pytest.mark.parametrize("text", ["- Painting, due Friday", "- Painting, 2 days, due 23 Oct",
                                  "- Cleaning, due Monday", "Painting, 2 days."])
def test_item_before_due_is_not_a_person(text):
    r = _sched(text)
    assert r.draft.resources == []
    assert not any(q.code == "SCHED_PEOPLE" for q in r.questions)
    assert r.draft.tasks[0].name in ("Painting", "Cleaning")


def test_names_before_a_comma_are_still_people():
    r = _sched("Ravi, Priya and Anil are on the team.\n- Design 2 days (Ravi)")
    assert sorted(x.name for x in r.draft.resources) == ["Anil", "Priya", "Ravi"]


def test_study_context_sentence_is_not_a_task():
    r = _sched("I'm studying for the exam. Subjects: physics, chemistry", "study")
    assert [t.name for t in r.draft.tasks] == ["Physics", "Chemistry"]


def test_study_revise_twice_without_object_gives_revisions():
    r = _sched("Subjects: physics, chemistry\nI revise twice.", "study")
    assert [t.name for t in r.draft.tasks] == ["Physics", "Revise physics (1/2)", "Revise physics (2/2)",
                                              "Chemistry", "Revise chemistry (1/2)", "Revise chemistry (2/2)"]
