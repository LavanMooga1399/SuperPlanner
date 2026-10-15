"""A.12 templates: deterministic, preflight-clean at defaults, optimizable."""

from datetime import date

import pytest

from superplanner.engine import OptimizeRequest, optimize, preflight, validate_schedule
from superplanner.templates import TEMPLATES, get_template

START = date(2026, 10, 19)


def test_registry():
    assert set(TEMPLATES) == {"manufacturing", "exam_prep", "project", "blank"}
    with pytest.raises(KeyError):
        get_template("nope")
    for t in TEMPLATES.values():
        assert t.id and t.name and t.description and t.terminology


@pytest.mark.parametrize("tid", ["manufacturing", "exam_prep", "project", "blank"])
def test_defaults_deterministic_and_clean(tid):
    t = get_template(tid)
    a = t.build(name="Plan", start_date=START, utc_offset="+05:30", params={})
    b = t.build(name="Plan", start_date=START, utc_offset="+05:30", params={})
    assert a == b
    rep = preflight(a)
    assert rep.ok, [i.message for i in rep.issues if i.severity == "error"]
    assert a.horizon_start.isoformat() == "2026-10-19T00:00:00+05:30"
    assert a.terminology == t.terminology
    assert a.domain == t.domain


@pytest.mark.parametrize("tid", ["manufacturing", "exam_prep", "project"])
def test_optimize_feasible(tid):
    p = get_template(tid).build(name="Plan", start_date=START, utc_offset="+05:30", params={})
    out = optimize(p, OptimizeRequest(strategy="auto", time_limit_seconds=10))
    assert out.result.feasibility == "feasible"
    assert validate_schedule(p, out.result.placements).feasibility == "feasible"


@pytest.mark.parametrize("tid", ["manufacturing", "exam_prep", "project", "blank"])
def test_unknown_param_rejected(tid):
    with pytest.raises(ValueError):
        get_template(tid).build(name="x", start_date=START, utc_offset="+00:00", params={"bogus": 1})


@pytest.mark.parametrize("tid,params", [
    ("manufacturing", {"jobs": 0}), ("manufacturing", {"jobs": "5"}), ("exam_prep", {"subjects": []}),
    ("exam_prep", {"exam_in_days": 3}), ("project", {"team_size": 9}),
])
def test_bad_param_values_rejected(tid, params):
    with pytest.raises(ValueError):
        get_template(tid).build(name="x", start_date=START, utc_offset="+00:00", params=params)


def test_bad_offset_rejected():
    with pytest.raises(ValueError):
        get_template("blank").build(name="x", start_date=START, utc_offset="0530", params={})


def test_manufacturing_shape():
    p = get_template("manufacturing").build(name="W", start_date=START, utc_offset="+00:00", params={"jobs": 3})
    assert [t.id for t in p.tasks][:3] == ["J1-1", "J1-2", "J1-3"]
    asm = next(t for t in p.tasks if t.id == "J1-3")
    assert [r.alternatives for r in asm.requirements] == [["ASM1"], ["OPS"]]
    assert next(t for t in p.tasks if t.id == "J2-2").requirements[0].alternatives == ["MILL1", "MILL2"]
    mill1 = next(r for r in p.resources if r.id == "MILL1")
    assert mill1.calendar.blocked[0].start.isoformat() == "2026-10-20T10:00:00+00:00"
    assert p.terminology.task == "Operation"


def test_exam_prep_shape_and_param_variants():
    t = get_template("exam_prep")
    p = t.build(name="S", start_date=START, utc_offset="+05:30",
                params={"subjects": ["Maths", "Physics"], "topics_per_subject": 2, "exam_in_days": 14})
    assert preflight(p).ok
    ids = {x.id for x in p.tasks}
    assert {"MATHS-T1-S", "MATHS-T2-R2", "PHYSICS-MOCK", "FULL-MOCK", "EXAM"} <= ids
    exam = next(x for x in p.tasks if x.id == "EXAM")
    assert exam.type == "milestone" and exam.deadline_hard and exam.earliest_start == exam.deadline
    assert all(x.metadata.get("difficulty") in range(1, 6) for x in p.tasks if x.id.endswith("-S"))
    out = optimize(p, OptimizeRequest(strategy="auto", time_limit_seconds=5))
    assert out.result.feasibility == "feasible"


def test_project_splits_long_work_and_skills():
    p = get_template("project").build(name="P", start_date=START, utc_offset="+00:00", params={"team_size": 3})
    names = [t.name for t in p.tasks]
    assert "Build API (1/2)" in names and "Build API (2/2)" in names
    assert all(t.duration_minutes <= 480 for t in p.tasks)
    members = {r.id: r.metadata["skills"] for r in p.resources}
    for t in p.tasks:
        for rq in t.requirements:
            assert all(t.metadata["skill"] in members[a] for a in rq.alternatives)
    release = next(t for t in p.tasks if t.id == "RELEASE")
    assert release.deadline_hard and release.deadline.isoformat() == "2026-11-08T17:00:00+00:00"
