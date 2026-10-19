"""Fix round: study subjects, exam dates, inline-list labels, deadline wording, family duration questions."""

from __future__ import annotations

from datetime import date

from intake_helpers import CTX
from superplanner import intake
from superplanner.intake.models import Answer

STUDY = CTX.model_copy(update={"kind": "study"})
PROD = CTX.model_copy(update={"kind": "production"})
PLACEHOLDER = ("My exam is in 90 days. I can study three hours on weekdays and eight hours on weekends.\n"
               "Subjects: Physics, Chemistry and Maths. I want to revise everything twice and do ten mock tests.")


def test_study_placeholder():
    r = intake.describe_schedule(PLACEHOLDER, STUDY)
    d = r.draft
    exam = [t for t in d.tasks if t.milestone]
    assert [(t.name, t.deadline, t.deadline_hard) for t in exam] == [("Exam", date(2027, 1, 15), True)]
    assert [x.name for x in d.resources] == []
    subj = [t for t in d.tasks if t.name in ("Physics", "Chemistry", "Maths")]
    assert [(t.name, t.group) for t in subj] == [("Physics", "Physics"), ("Chemistry", "Chemistry"),
                                                ("Maths", "Maths")]
    rev = [t.name for t in d.tasks if t.name.startswith("Revise")]
    assert rev == ["Revise physics (1/2)", "Revise physics (2/2)", "Revise chemistry (1/2)",
                   "Revise chemistry (2/2)", "Revise maths (1/2)", "Revise maths (2/2)"]
    codes = [q.code for q in r.questions]
    assert "SCHED_PEOPLE" not in codes and "SCHED_WHO" not in codes
    assert codes.count("SCHED_TASK_DURATION") == 7      # 3 subjects + 3 revision families + 1 mock family


def test_family_answer_applies_to_every_copy_and_builds():
    r = intake.describe_schedule(PLACEHOLDER, STUDY)
    qs = [q for q in r.questions if q.code == "SCHED_TASK_DURATION"]
    a = intake.answer_schedule(r.draft, [Answer(question_id=q.id, use_default=True) for q in qs], STUDY)
    assert all(t.duration is not None for t in a.draft.tasks if not t.milestone)
    assert not [q for q in a.questions if q.required]
    b = intake.build_schedule(a.draft, STUDY)
    assert b.problem is not None


def test_subjects_with_durations():
    r = intake.describe_schedule("Exam on 10 Feb 2027. Subjects: maths 20 hours, physics 15 hours, "
                                 "chemistry 12 hours.", STUDY)
    work = {t.group: (t.name, t.duration.likely, t.duration.unit) for t in r.draft.tasks if t.group}
    assert work == {"Maths": ("Maths", 20, "hours"), "Physics": ("Physics", 15, "hours"),
                    "Chemistry": ("Chemistry", 12, "hours")}


def test_exam_on_date_still_read():
    r = intake.describe_schedule("Exam on 10 Feb 2027.\n- Revise algebra 3 hours", STUDY)
    exam = next(t for t in r.draft.tasks if t.milestone)
    assert (exam.name, exam.deadline) == ("Exam", date(2027, 2, 10))


def names(text, ctx=CTX):
    return [t.name for t in intake.describe_schedule(text, ctx).draft.tasks]


def test_inline_list_label_dropped():
    assert names("Steps: design, build and test") == ["Design", "Build", "Test"]
    assert names("Steps: design 2 days, build 5 days and test 2 days.") == ["Design", "Build", "Test"]
    # a label that is itself a task keeps working as before
    assert names("- Build the site: 3 weeks") == ["Build the site"]
    assert names("- Gather requirements: 2-3 days") == ["Gather requirements"]


def test_deadline_wording_removed_from_names():
    t = intake.describe_schedule("- Pay the advance 1 hour, must be done by 25 Oct 2026", CTX).draft.tasks[0]
    assert (t.name, t.deadline, t.deadline_hard) == ("Pay the advance", date(2026, 10, 25), True)
    t = intake.describe_schedule("- Send the invoice 1 hour, it should be sent by 30 Oct 2026", CTX).draft.tasks[0]
    assert t.name == "Send the invoice"


def test_production_placeholder_clean_names_and_due_weekday():
    text = ("Two machines, two shifts Monday to Saturday.\n"
            "Order A: cutting 3 h, then welding 2 h, then painting 1 h, due Friday.\n"
            "Order B: cutting 2 h, then assembly 4-5 h, due next Wednesday.")
    d = intake.describe_schedule(text, PROD).draft
    assert [(t.name, t.group) for t in d.tasks] == [("Cutting", "Order A"), ("Welding", "Order A"),
                                                    ("Painting", "Order A"), ("Cutting", "Order B"),
                                                    ("Assembly", "Order B")]
    # 2026-10-17 is a Saturday: "due Friday" is 23 Oct, "next Wednesday" 21 Oct
    assert d.tasks[2].deadline == date(2026, 10, 23) and d.tasks[4].deadline == date(2026, 10, 21)


def test_bare_weekday_without_deadline_word_is_not_a_date():
    d = intake.describe_schedule("- Meet Friday team 1 hour", CTX).draft
    assert d.tasks[0].deadline is None
