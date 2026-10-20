"""Exam preparation template: study sessions, spaced revisions and mock tests before an exam."""

from __future__ import annotations

from datetime import date
from typing import Any

from superplanner.engine.model import Calendar, Dependency, Problem, Requirement, Resource, Task, Terminology

from .base import TemplateParameter, at, parse_offset, resolve_params, slug

TERMS = Terminology(task="Study session", tasks="Study sessions", resource="Study time", resources="Study time",
                    group="Subject", milestone="Exam", schedule="Study plan", deadline="Target date")


class ExamPrepTemplate:
    id = "exam_prep"
    name = "Exam preparation"
    description = "Study, spaced revision and mock tests per subject, fitted into your free time before the exam."
    domain = "exam_prep"
    terminology = TERMS
    parameters = [
        TemplateParameter(name="exam_in_days", label="Days until the exam", type="int", default=30, min=7, max=180),
        TemplateParameter(name="subjects", label="Subjects", type="string_list",
                          default=["Polity", "History", "Geography"], min=1, max=10),
        TemplateParameter(name="topics_per_subject", label="Topics per subject", type="int", default=3, min=1,
                          max=10),
    ]

    def build(self, *, name: str, start_date: date, utc_offset: str, params: dict[str, Any]) -> Problem:
        p = resolve_params(self.parameters, params)
        tz = parse_offset(utc_offset)
        exam_days, subjects, topics = p["exam_in_days"], p["subjects"], p["topics_per_subject"]
        weekday = [("06:00", "08:00"), ("18:00", "21:00")]
        weekend = [("09:00", "13:00"), ("15:00", "19:00")]
        weekly = {d: list(weekday) for d in ("mon", "tue", "wed", "thu", "fri")}
        weekly.update({d: list(weekend) for d in ("sat", "sun")})
        student = Resource(id="STUDENT", name="My study time", kind="time", capacity=1, cost_per_hour=0.0,
                           calendar=Calendar(weekly=weekly))
        need = [Requirement(alternatives=["STUDENT"])]
        exam_at = at(start_date, tz, exam_days, "10:00")
        rev2_deadline = at(start_date, tz, exam_days - 2, "10:00")
        full_mock_deadline = at(start_date, tz, exam_days - 1, "10:00")
        rev1_lag = 2 * 1440 if exam_days >= 14 else 1440
        rev2_lag = min(7, exam_days // 4) * 1440
        tasks: list[Task] = []
        deps: list[Dependency] = []
        used_ids: set[str] = set()
        mock_ids: list[str] = []
        for s_i, subject in enumerate(subjects):
            sid = slug(subject)
            while sid in used_ids:
                sid = f"{sid}_{s_i}"
            used_ids.add(sid)
            prev_study = None
            rev1_ids = []
            for j in range(1, topics + 1):
                diff = (s_i * 7 + j * 3) % 5 + 1
                study, rev1, rev2 = f"{sid}-T{j}-S", f"{sid}-T{j}-R1", f"{sid}-T{j}-R2"
                tasks.append(Task(id=study, name=f"{subject} topic {j}: study", group=subject, duration_minutes=90,
                                  priority=min(10, 4 + diff), requirements=need, metadata={"difficulty": diff}))
                tasks.append(Task(id=rev1, name=f"{subject} topic {j}: revision 1", group=subject,
                                  duration_minutes=45, priority=5, requirements=need, metadata={"difficulty": diff}))
                tasks.append(Task(id=rev2, name=f"{subject} topic {j}: revision 2", group=subject,
                                  duration_minutes=30, priority=5, deadline=rev2_deadline, deadline_hard=False,
                                  requirements=need, metadata={"difficulty": diff}))
                if prev_study is not None:
                    deps.append(Dependency(predecessor=prev_study, successor=study, type="FS"))
                deps.append(Dependency(predecessor=study, successor=rev1, type="FS", lag_minutes=rev1_lag))
                deps.append(Dependency(predecessor=rev1, successor=rev2, type="FS", lag_minutes=rev2_lag))
                prev_study = study
                rev1_ids.append(rev1)
            mock = f"{sid}-MOCK"
            tasks.append(Task(id=mock, name=f"{subject} mock test", group=subject, duration_minutes=120, priority=7,
                              requirements=need))
            for r in rev1_ids:
                deps.append(Dependency(predecessor=r, successor=mock, type="FS"))
            mock_ids.append(mock)
        tasks.append(Task(id="FULL-MOCK", name="Full mock exam", group="All subjects", duration_minutes=180,
                          priority=9, deadline=full_mock_deadline, deadline_hard=True, requirements=need))
        for m in mock_ids:
            deps.append(Dependency(predecessor=m, successor="FULL-MOCK", type="FS"))
        tasks.append(Task(id="EXAM", name="Exam", type="milestone", duration_minutes=0, priority=10,
                          earliest_start=exam_at, deadline=exam_at, deadline_hard=True))
        deps.append(Dependency(predecessor="FULL-MOCK", successor="EXAM", type="FS"))
        return Problem(name=name or self.name, domain=self.domain, horizon_start=at(start_date, tz),
                       horizon_days=exam_days + 1, currency="USD", terminology=TERMS, tasks=tasks,
                       resources=[student], dependencies=deps,
                       objectives={"preset": "meet_deadlines"},  # type: ignore[arg-type]
                       metadata={"template": self.id, "parameters": p})
