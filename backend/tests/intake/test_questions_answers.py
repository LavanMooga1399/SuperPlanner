"""Questions and answers (PHASE2 2.8; plan P2-2, P2-8)."""

from __future__ import annotations

import pytest

from intake_helpers import CTX, EXAMPLE_ANSWERS, FIN_CTX, FINANCE_TEXT, SCHEDULE_TEXT
from superplanner.intake import IntakeError, answer_finance, answer_schedule, describe_finance, describe_schedule
from superplanner.intake.models import Answer, ScheduleDraft

G = CTX.model_copy(update={"kind": None})


def A(qid, **kw):
    return Answer(question_id=qid, **kw)


def test_example_answers():
    r = describe_schedule(SCHEDULE_TEXT, CTX)
    a = answer_schedule(r.draft, [Answer.model_validate(x) for x in EXAMPLE_ANSWERS], CTX)
    t4 = next(t for t in a.draft.tasks if t.key == "t4")
    assert t4.resources == ["r_ravi"]
    assert a.draft.working_time.model_dump() == {"days": ["mon", "tue", "wed", "thu", "fri"],
                                                 "windows": [{"start": "09:00", "end": "17:00"}],
                                                 "weekend_windows": None}
    assert a.draft.dismissed == ["SCHED_PEOPLE:-"]
    assert a.questions == [] and a.ready
    for path in ("/tasks/t4/resources", "/working_time"):
        assert a.draft.provenance[path].source == "answer" and a.draft.provenance[path].confidence == 1.0


def test_questions_are_pure_and_stable():
    r1 = describe_schedule(SCHEDULE_TEXT, CTX)
    r2 = answer_schedule(r1.draft, [], CTX)
    assert [q.id for q in r1.questions] == [q.id for q in r2.questions]


def test_duration_text_answer_default_and_error():
    r = describe_schedule("1. Plan\n2. Build", G)
    qids = [q.id for q in r.questions]
    assert qids[:2] == ["SCHED_TASK_DURATION:/tasks/t1/duration", "SCHED_TASK_DURATION:/tasks/t2/duration"]
    q1 = r.questions[0]
    assert q1.required and q1.reason == "missing" and q1.prompt == 'How long will "Plan" take? A range like "2-3 days" is fine.'
    assert q1.default == {"optimistic": 1.0, "likely": 1.0, "pessimistic": 1.0, "unit": "days"}
    a = answer_schedule(r.draft, [A(qids[0], value={"text": "2-3 days"}), A(qids[1], value={"text": "banana"})], G)
    t1, t2 = a.draft.tasks
    assert (t1.duration.optimistic, t1.duration.likely, t1.duration.pessimistic) == (2, 2.5, 3)
    assert t2.duration is None
    bad = next(q for q in a.questions if q.id == qids[1])
    assert bad.error and "2-3 days" in bad.error
    assert next(q for q in a.questions).id == qids[1]          # required first
    a = answer_schedule(r.draft, [A(qids[0], use_default=True),
                                  A(qids[1], value={"optimistic": 1, "likely": 2, "pessimistic": 4, "unit": "hours"})],
                        G)
    assert a.draft.tasks[0].duration.unit == "days" and a.draft.tasks[1].duration.pessimistic == 4


def test_skip_required_is_refused_and_optional_is_dismissed():
    r = describe_schedule("1. Plan\n2. Build", G)
    a = answer_schedule(r.draft, [A("SCHED_TASK_DURATION:/tasks/t1/duration", skip=True),
                                  A("SCHED_SEQUENTIAL:-", skip=True)], G)
    assert a.draft.dismissed == ["SCHED_SEQUENTIAL:-"]
    q = next(q for q in a.questions if q.id == "SCHED_TASK_DURATION:/tasks/t1/duration")
    assert q.error
    assert not any(q.id == "SCHED_SEQUENTIAL:-" for q in a.questions)


def test_sequential_no_removes_implied_links():
    r = describe_schedule("1. Plan 1 day\n2. Build 2 days\n3. Test 1 day", G)
    a = answer_schedule(r.draft, [A("SCHED_SEQUENTIAL:-", value=False)], G)
    assert all(t.after == [] for t in a.draft.tasks)


def test_people_no_removes_detected_people():
    r = describe_schedule("Write report 2 days (Ravi). Ravi and Priya will review it together 1 day", G)
    assert any(q.code == "SCHED_PEOPLE" for q in r.questions)
    a = answer_schedule(r.draft, [A("SCHED_PEOPLE:-", value=False)], G)
    assert a.draft.resources == [] and all(t.resources == [] for t in a.draft.tasks)


def test_dependency_reference_choice():
    r = describe_schedule("Paint the fence 2 days after the barn is fixed\nFix the shed 1 day", G)
    q = r.questions[0]
    assert q.code == "SCHED_DEP_REFERENCE" and q.required
    assert [o.value for o in q.options] == ["t2", "none"]
    a = answer_schedule(r.draft, [A(q.id, value="t2")], G)
    assert a.draft.tasks[0].after == ["t2"]
    a = answer_schedule(r.draft, [A(q.id, value="none")], G)
    assert a.draft.tasks[0].after == [] and not any(x.code == "SCHED_DEP_REFERENCE" for x in a.questions)


def test_date_and_working_time_answers():
    r = describe_schedule("Write report 2 days", G)
    a = answer_schedule(r.draft, [A("SCHED_START_DATE:/start_date", value="2026-11-02"),
                                  A("SCHED_WORKING_TIME:/working_time",
                                    value={"days": ["mon"], "windows": [{"start": "10:00", "end": "12:00"}]})], G)
    assert str(a.draft.start_date) == "2026-11-02" and a.draft.working_time.days == ["mon"]
    a = answer_schedule(r.draft, [A("SCHED_START_DATE:/start_date", value={"text": "next Monday"})], G)
    assert str(a.draft.start_date) == "2026-10-19"
    a = answer_schedule(r.draft, [A("SCHED_START_DATE:/start_date", value="13/13/2026")], G)
    assert next(q for q in a.questions if q.code == "SCHED_START_DATE").error


def test_who_question_only_with_two_or_more_resources():
    r = describe_schedule("Write report 2 days (Ravi). Review it 1 day", G)
    assert not any(q.code == "SCHED_WHO" for q in r.questions)


def test_edit_provenance_suppresses_question():
    r = describe_schedule("1. Plan\n2. Build 1 day", G)
    d = r.draft.model_dump(mode="json")
    d["provenance"]["/start_date"] = {"source": "edit", "confidence": 1}
    d["start_date"] = "2026-10-20"
    r2 = answer_schedule(ScheduleDraft.model_validate(d), [], G)
    assert not any(q.code == "SCHED_START_DATE" for q in r2.questions)


def test_unknown_question():
    r = describe_schedule(SCHEDULE_TEXT, CTX)
    with pytest.raises(IntakeError) as e:
        answer_schedule(r.draft, [A("NOPE:-", value=1)], CTX)
    assert e.value.code == "UNKNOWN_QUESTION" and e.value.details == {"question_id": "NOPE:-"}
    f = describe_finance(FINANCE_TEXT, FIN_CTX)
    with pytest.raises(IntakeError):
        answer_finance(f.draft, [A("FIN_NOPE:-", value=1)], FIN_CTX)


def test_finance_answers():
    r = describe_finance(FINANCE_TEXT, FIN_CTX)
    a = answer_finance(r.draft, [A("FIN_RETIREMENT_TARGET:/goals/g2/target", value={"text": "3 crore"}),
                                 A("FIN_DISCRETIONARY:-", value=15000),
                                 A("FIN_GOAL_PRIORITY:/goals/g1/priority", value="must"),
                                 A("FIN_EF_MONTHS:/emergency_fund_months", use_default=True)], FIN_CTX)
    g1, g2 = a.draft.goals
    assert (g2.target.low, g2.target.high) == (30000000, 30000000) and g1.priority == "must"
    assert a.draft.emergency_fund_months == 6
    disc = [e for e in a.draft.expenses if e.essential is False]
    assert len(disc) == 1 and disc[0].amount.low == 15000
    assert a.questions == [] and a.ready


def test_finance_money_range_answer_and_bad_text():
    r = describe_finance("Rent 20k a month.", FIN_CTX)
    q = r.questions[0]
    a = answer_finance(r.draft, [A(q.id, value={"low": 90000, "high": 110000})], FIN_CTX)
    assert (a.draft.incomes[0].amount.low, a.draft.incomes[0].amount.high) == (90000, 110000)
    a = answer_finance(r.draft, [A(q.id, value={"text": "lots"})], FIN_CTX)
    assert a.questions[0].error and a.draft.incomes == []
