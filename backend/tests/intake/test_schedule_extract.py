"""Rule-based schedule extraction (PHASE2 2.7.5-2.7.10, 2.15 example; plan P2-2, P2-4)."""

from __future__ import annotations

from datetime import date

import pytest

from intake_helpers import CTX, SCHEDULE_TEXT, STUDY_TEXT
from superplanner.intake import describe_schedule
from superplanner.intake.models import ExtractContext

GENERIC = CTX.model_copy(update={"kind": None})


def tasks(r):
    return {t.key: t for t in r.draft.tasks}


def names(r):
    return [t.name for t in r.draft.tasks]


def test_example_draft_exact():
    r = describe_schedule(SCHEDULE_TEXT, CTX)
    d = r.draft.model_dump(mode="json")
    assert (d["domain"], d["kind"], d["name"], d["start_date"]) == ("schedule", "project", "Website relaunch",
                                                                    "2026-10-19")
    assert d["horizon_days"] is None and d["working_time"] is None and d["objective"] is None
    assert d["resources"] == [{"key": "r_ravi", "name": "Ravi", "kind": "person", "count": 1},
                              {"key": "r_priya", "name": "Priya", "kind": "person", "count": 1}]
    t = {x["key"]: x for x in d["tasks"]}
    assert list(t) == ["t1", "t2", "t3", "t4", "t5"]
    assert t["t1"] == {"key": "t1", "name": "Gather requirements", "milestone": False,
                       "duration": {"optimistic": 2, "likely": 2.5, "pessimistic": 3, "unit": "days"},
                       "after": [], "resources": ["r_priya"], "resource_mode": "any", "deadline": None,
                       "deadline_hard": False, "earliest_start": None, "priority": None, "group": None, "notes": ""}
    assert (t["t2"]["name"], t["t2"]["duration"], t["t2"]["after"], t["t2"]["resources"]) == (
        "Design", {"optimistic": 1, "likely": 1, "pessimistic": 1, "unit": "weeks"}, ["t1"], ["r_priya"])
    assert (t["t3"]["name"], t["t3"]["duration"], t["t3"]["after"], t["t3"]["resources"]) == (
        "Build the site", {"optimistic": 2, "likely": 2, "pessimistic": 2, "unit": "weeks"}, ["t2"], ["r_ravi"])
    assert (t["t4"]["name"], t["t4"]["duration"], t["t4"]["after"], t["t4"]["resources"]) == (
        "Testing", {"optimistic": 3, "likely": 4, "pessimistic": 5, "unit": "days"}, ["t3"], [])
    assert (t["t5"]["name"], t["t5"]["milestone"], t["t5"]["duration"], t["t5"]["after"], t["t5"]["deadline"],
            t["t5"]["deadline_hard"]) == ("Launch", True, None, ["t4"], "2026-12-15", False)
    p = d["provenance"]
    expected = {
        "/start_date": ("text", 0.8, 26, 37, "next Monday"),
        "/resources/r_ravi/name": ("text", 0.7, 39, 43, "Ravi"),
        "/tasks/t1/duration": ("text", 0.95, 96, 104, "2-3 days"),
        "/tasks/t1/resources": ("text", 0.7, 105, 112, "(Priya)"),
        "/tasks/t2/after": ("text", 0.95, 131, 149, "after requirements"),
        "/tasks/t4/after": ("text", 0.9, 210, 232, "once the build is done"),
        "/tasks/t5/deadline": ("text", 0.95, 243, 257, "by 15 Dec 2026"),
    }
    for path, (src, conf, a, b, txt) in expected.items():
        assert (p[path]["source"], p[path]["confidence"]) == (src, conf), path
        assert p[path]["span"] == {"start": a, "end": b, "text": txt}, path
        assert SCHEDULE_TEXT[a:b] == txt
    assert p["/tasks/t3/after"] == {"source": "derived", "confidence": 0.6, "span": None, "cell": None,
                                    "note": "From the order of the list"}
    assert p["/tasks/t5/milestone"]["source"] == "derived" and p["/tasks/t5/milestone"]["confidence"] == 0.7
    assert d["dismissed"] == []
    assert [q.id for q in r.questions] == ["SCHED_SEQUENTIAL:-", "SCHED_PEOPLE:-", "SCHED_WHO:/tasks/t4/resources",
                                           "SCHED_WORKING_TIME:/working_time"]
    who = r.questions[2]
    assert [o.model_dump() for o in who.options] == [{"value": "r_ravi", "label": "Ravi"},
                                                      {"value": "r_priya", "label": "Priya"}]
    assert who.default == ["r_ravi", "r_priya"] and who.default_label == "Either Ravi or Priya"
    assert r.questions[1].prompt == "Are Ravi and Priya the people doing the work?"
    assert r.notes == [] and r.ready is True
    assert r.extractor.model_dump() == {"requested": "rule", "used": "rule", "ai_available": False,
                                        "fallback_code": None, "fallback_message": None, "model": None}


def test_extraction_is_deterministic():
    assert describe_schedule(SCHEDULE_TEXT, CTX) == describe_schedule(SCHEDULE_TEXT, CTX)


def test_study_example():
    r = describe_schedule(STUDY_TEXT, GENERIC)
    assert r.draft.kind == "study"
    wt = r.draft.working_time
    assert wt.days == ["mon", "tue", "wed", "thu", "fri"]
    assert [(w.start, w.end) for w in wt.windows] == [("18:00", "21:00")]
    assert [(w.start, w.end) for w in wt.weekend_windows] == [("09:00", "13:00"), ("14:00", "18:00")]
    exam = next(t for t in r.draft.tasks if t.milestone)
    assert exam.name == "Exam" and exam.deadline == date(2027, 1, 15) and exam.deadline_hard
    mocks = [t for t in r.draft.tasks if t.name.startswith("Mock test")]
    assert [t.name for t in mocks] == [f"Mock test {i}" for i in range(1, 11)]
    revisions = [t for t in r.draft.tasks if t.name.startswith("Revise")]
    assert [t.name for t in revisions] == ["Revise the syllabus (1/2)", "Revise the syllabus (2/2)"]
    keys = tasks(r)
    syllabus = next(t for t in r.draft.tasks if t.name == "Finish the syllabus")
    assert revisions[0].after == [syllabus.key] and revisions[1].after == [revisions[0].key]
    assert set(exam.after) >= {revisions[1].key} | {m.key for m in mocks}
    assert all(k in keys for k in exam.after)
    assert any(n.code == "EXPANDED_COUNT" for n in r.notes)
    dq = [q for q in r.questions if q.code == "SCHED_TASK_DURATION"]
    assert len(dq) == 13 and all(q.required for q in dq)
    assert dq[0].default == {"optimistic": 6.0, "likely": 6.0, "pessimistic": 6.0, "unit": "hours"}
    assert not r.ready


@pytest.mark.parametrize("text,expected", [
    ("Design the logo 2 days. Write copy 1 day. Design before copy.", {"t2": ["t1"]}),
    ("Write the draft 2 days\nEdit the draft 1 day after write the draft", {"t2": ["t1"]}),
    ("Pack boxes 2h. Deliver boxes 1h once packing is done", {"t2": ["t1"]}),
    ("Test the app 1 day. Build the app 3 days before test the app", {"t1": ["t2"]}),
    ("Plan 1 day, then build 2 days, then test 1 day", {"t2": ["t1"], "t3": ["t2"]}),
    ("Cut wood 1h -> Paint wood 2h -> Pack 1h", {"t2": ["t1"], "t3": ["t2"]}),
    ("Write tests 1 day. Review code 1 day. Deploy 1 hour at the end", {"t3": ["t1", "t2"]}),
])
def test_dependency_phrases(text, expected):
    r = describe_schedule(text, GENERIC)
    t = tasks(r)
    for k, after in expected.items():
        assert sorted(t[k].after) == sorted(after), (text, k, t[k].after, names(r))


def test_list_order_chain_and_sequential_question():
    r = describe_schedule("1. Plan 1 day\n2. Build 2 days\n3. Test 1 day", GENERIC)
    t = tasks(r)
    assert t["t2"].after == ["t1"] and t["t3"].after == ["t2"]
    assert r.draft.provenance["/tasks/t2/after"].confidence == 0.6
    q = next(q for q in r.questions if q.code == "SCHED_SEQUENTIAL")
    assert q.default is True and q.required is False


def test_unresolved_reference_asks():
    r = describe_schedule("Paint the fence 2 days after the shed is fixed", GENERIC)
    q = next(q for q in r.questions if q.code == "SCHED_DEP_REFERENCE")
    assert q.required and q.kind == "choice"
    assert q.options[-1].label == "None of these"
    assert not r.ready


def test_fuzzy_reference_resolves():
    r = describe_schedule("Prepare the slides 1 day\nRehearse the talk 2 hours after preparing slides", GENERIC)
    t = tasks(r)
    assert t["t2"].after == ["t1"]
    assert r.draft.provenance["/tasks/t2/after"].confidence in (0.8, 0.95)


def test_parallel_note_and_named_assignment():
    r = describe_schedule("Cook dinner 2h. Clean kitchen 1h in parallel with cook dinner. Ravi will clean kitchen.",
                          GENERIC)
    t = tasks(r)
    assert t["t2"].after == [] and t["t2"].resources == ["r_ravi"]
    assert any(n.code == "PARALLEL" for n in r.notes)
    assert [x.name for x in r.draft.resources] == ["Ravi"]


def test_counted_resources_production_chains_and_unsupported_rule():
    text = ("We have two machines and a team of 3. 4 orders each needs cutting, welding and painting. "
            "No more than 2 overtime hours.")
    r = describe_schedule(text, GENERIC)
    assert r.draft.kind == "production"
    res = {x.key: (x.name, x.kind, x.count) for x in r.draft.resources}
    assert res == {"r_machine": ("Machine", "machine", 2), "r_team_member": ("Team member", "person", 3)}
    assert len(r.draft.tasks) == 12
    t = tasks(r)
    assert t["t1"].name == "Order 1: Cutting" and t["t2"].after == ["t1"] and t["t3"].after == ["t2"]
    assert t["t1"].group == "Order 1" and t["t4"].after == []
    rule = [n for n in r.notes if n.code == "UNSUPPORTED_RULE"]
    assert len(rule) == 1 and rule[0].severity == "warning"
    assert rule[0].message == ('I could not turn this into a plan rule: "No more than 2 overtime hours". Add it by '
                               'hand after creating the plan, or rephrase it.')
    assert text[rule[0].span.start:rule[0].span.end].startswith("No more than")


def test_three_point_and_hard_deadline():
    r = describe_schedule("Write tests 2/3/5 days\nReview code 3 days (2-5)\nDeploy half a day, no later than "
                          "2026-11-20", GENERIC)
    t = tasks(r)
    assert (t["t1"].duration.optimistic, t["t1"].duration.likely, t["t1"].duration.pessimistic) == (2, 3, 5)
    assert (t["t2"].duration.optimistic, t["t2"].duration.likely, t["t2"].duration.pessimistic) == (2, 3, 5)
    assert t["t3"].duration.likely == 0.5 and t["t3"].duration.unit == "days"
    assert t["t3"].deadline == date(2026, 11, 20) and t["t3"].deadline_hard is True


def test_kind_detection():
    assert describe_schedule("Revise chapter 1 for the exam 2 hours", GENERIC).draft.kind == "study"
    assert describe_schedule("Write a poem 1 hour", GENERIC).draft.kind == "generic"
    assert describe_schedule("Design the release, build and deploy 2 days", GENERIC).draft.kind == "project"
    # an explicit kind wins
    assert describe_schedule("Revise chapter 1 for the exam 2 hours", CTX).draft.kind == "project"


def test_working_time_phrases():
    r = describe_schedule("We work 9 to 5, Monday to Friday. Write report 2 days", GENERIC)
    wt = r.draft.working_time
    assert wt.days == ["mon", "tue", "wed", "thu", "fri"] and [(w.start, w.end) for w in wt.windows] == [
        ("09:00", "17:00")]


def test_empty_of_tasks_asks():
    r = describe_schedule("Hello there.", GENERIC)
    assert [q.code for q in r.questions][0] == "SCHED_NO_TASKS"
    assert not r.ready


def test_text_errors():
    from superplanner.intake import IntakeTextError

    with pytest.raises(IntakeTextError) as e:
        describe_schedule("   \n ", CTX)
    assert e.value.code == "TEXT_EMPTY"
    with pytest.raises(IntakeTextError) as e:
        describe_schedule("x" * 20001, CTX)
    assert e.value.code == "TEXT_TOO_LONG" and e.value.details == {"max_chars": 20000}


def test_spans_are_code_points_with_emoji():
    text = "🚀 Launch prep ₹ budget\n1. Write copy 2 days (Priya)"
    r = describe_schedule(text, ExtractContext(today=date(2026, 10, 17), kind="project"))
    for p in r.draft.provenance.values():
        if p.span:
            assert text[p.span.start:p.span.end] == p.span.text
