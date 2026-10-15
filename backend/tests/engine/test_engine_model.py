"""A.3 / A.3.0: only field-local rules reject a document; relational checks are preflight's job."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from engine_helpers import HS, at, dep, problem, res, task
from superplanner.engine import Problem, preflight
from superplanner.engine.model import Calendar, Objectives, Requirement, Weights


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        Problem(name="x", horizon_start=datetime(2026, 10, 19, 8, 0))
    with pytest.raises(ValidationError):
        task("A", 30, deadline=datetime(2026, 10, 20))


def test_milestone_rules():
    with pytest.raises(ValidationError):
        Problem.model_validate({"name": "x", "horizon_start": HS.isoformat(),
                                "tasks": [{"id": "M", "name": "M", "type": "milestone", "duration_minutes": 5}]})
    with pytest.raises(ValidationError):
        Problem.model_validate({"name": "x", "horizon_start": HS.isoformat(),
                                "tasks": [{"id": "M", "name": "M", "type": "milestone",
                                           "requirements": [{"alternatives": ["R"]}]}]})


def test_activity_needs_positive_duration():
    with pytest.raises(ValidationError):
        Problem.model_validate({"name": "x", "horizon_start": HS.isoformat(),
                                "tasks": [{"id": "A", "name": "A", "duration_minutes": 0}]})


def test_requirement_rules():
    with pytest.raises(ValidationError):
        Requirement(alternatives=[])
    with pytest.raises(ValidationError):
        Requirement(alternatives=["A", "A"])
    with pytest.raises(ValidationError):
        Requirement(alternatives=["A"], units=0)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Problem.model_validate({"name": "x", "horizon_start": HS.isoformat(), "taks": []})


def test_custom_weights_not_all_zero():
    with pytest.raises(ValidationError):
        Objectives(preset="custom", weights=Weights(makespan=0, tardiness=0, cost=0))
    Objectives(preset="balanced", weights=Weights(makespan=0, tardiness=0, cost=0))  # ignored for presets


def test_id_defaults_to_draft_and_regex():
    p = Problem(name="x", horizon_start=HS)
    assert p.id == "draft"
    with pytest.raises(ValidationError):
        Problem(id="bad id!", name="x", horizon_start=HS)


def test_relational_problems_are_saveable_and_reported_by_preflight():
    bad_cal = Calendar(weekly={"mon": [("10:00", "09:00")]})
    p = problem([task("A", 30, ["R"]), task("B", 30, ["NOPE"])], [res("R", calendar=bad_cal)],
                [dep("A", "A"), dep("A", "B", lag=10 ** 6)])
    codes = {i.code for i in preflight(p).issues}
    assert {"SELF_DEPENDENCY", "INVALID_CALENDAR", "UNKNOWN_RESOURCE", "LAG_OUT_OF_RANGE"} <= codes


def test_hhmm_regex():
    Calendar(weekly={"mon": [("00:00", "24:00")]})
    with pytest.raises(ValidationError):
        Calendar(weekly={"mon": [("25:00", "26:00")]})
    with pytest.raises(ValidationError):
        Calendar(weekly={"mon": [("9:00", "10:00")]})


def test_example_round_trip():
    p = problem([task("A", 30, ["R"], deadline=at(100))], [res("R")])
    again = Problem.model_validate_json(p.model_dump_json())
    assert again == p
