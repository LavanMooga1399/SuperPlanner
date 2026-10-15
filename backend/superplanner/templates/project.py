"""Project template: a small software project with skills-based team assignment."""

from __future__ import annotations

from datetime import date
from typing import Any

from superplanner.engine.model import Calendar, Dependency, Problem, Requirement, Resource, Task, Terminology

from .base import TemplateParameter, at, parse_offset, resolve_params

TERMS = Terminology(task="Task", tasks="Tasks", resource="Team member", resources="Team", group="Workstream",
                    milestone="Milestone", schedule="Project schedule", deadline="Deadline")

MAX_PART = 480

_MEMBERS = [
    ("Asha", ["analysis", "design", "docs"], 55.0),
    ("Ben", ["backend", "devops"], 65.0),
    ("Chen", ["frontend", "design", "qa"], 60.0),
    ("Dara", ["backend", "qa", "docs"], 50.0),
    ("Eli", ["frontend", "backend"], 70.0),
    ("Fatima", ["qa", "analysis"], 45.0),
    ("Goran", ["devops", "backend"], 60.0),
    ("Hana", ["design", "frontend", "docs"], 40.0),
]

# (id, name, workstream, skill, minutes, predecessors)
_WORK = [
    ("REQ", "Gather requirements", "Planning", "analysis", 480, []),
    ("UX", "UX design", "Design", "design", 720, ["REQ"]),
    ("DESIGN_OK", "Design approved", "Design", None, 0, ["UX"]),
    ("DB", "Database schema", "Backend", "backend", 480, ["DESIGN_OK"]),
    ("API", "Build API", "Backend", "backend", 960, ["DB"]),
    ("UI", "Build UI", "Frontend", "frontend", 960, ["DESIGN_OK"]),
    ("INT", "Integration", "Backend", "backend", 480, ["API", "UI"]),
    ("TEST", "Testing", "Quality", "qa", 960, ["INT"]),
    ("DOCS", "User documentation", "Docs", "docs", 480, ["UI"]),
    ("DEPLOY", "Deployment", "Ops", "devops", 240, ["TEST"]),
    ("RELEASE", "Release", "Ops", None, 0, ["DEPLOY", "DOCS"]),
]


class ProjectTemplate:
    id = "project"
    name = "Project"
    description = "A small software project: tasks assigned to team members by skill, with milestones."
    domain = "project"
    terminology = TERMS
    parameters = [
        TemplateParameter(name="team_size", label="Team size", type="int", default=4, min=3, max=8),
    ]

    def build(self, *, name: str, start_date: date, utc_offset: str, params: dict[str, Any]) -> Problem:
        p = resolve_params(self.parameters, params)
        tz = parse_offset(utc_offset)
        cal = Calendar(weekly={d: [("09:00", "17:00")] for d in ("mon", "tue", "wed", "thu", "fri")})
        members = _MEMBERS[: p["team_size"]]
        resources = [Resource(id=f"M{i + 1}", name=nm, kind="person", capacity=1, cost_per_hour=cost, calendar=cal,
                              metadata={"skills": skills}) for i, (nm, skills, cost) in enumerate(members)]
        tasks: list[Task] = []
        deps: list[Dependency] = []
        first_part: dict[str, str] = {}
        last_part: dict[str, str] = {}
        release_deadline = at(start_date, tz, 20, "17:00")
        for wid, wname, stream, skill, minutes, preds in _WORK:
            if skill is None:
                tasks.append(Task(id=wid, name=wname, group=stream, type="milestone", duration_minutes=0,
                                  priority=8, deadline=release_deadline if wid == "RELEASE" else None,
                                  deadline_hard=wid == "RELEASE"))
                first_part[wid] = last_part[wid] = wid
            else:
                alts = [r.id for r in resources if skill in r.metadata["skills"]]
                parts = max(1, -(-minutes // MAX_PART))
                prev = None
                for k in range(parts):
                    dur = min(MAX_PART, minutes - k * MAX_PART)
                    tid = wid if parts == 1 else f"{wid}-{k + 1}"
                    label = wname if parts == 1 else f"{wname} ({k + 1}/{parts})"
                    tasks.append(Task(id=tid, name=label, group=stream, duration_minutes=dur, priority=6,
                                      requirements=[Requirement(alternatives=alts)], metadata={"skill": skill}))
                    if prev is not None:
                        deps.append(Dependency(predecessor=prev, successor=tid, type="FS"))
                    prev = tid
                    if k == 0:
                        first_part[wid] = tid
                last_part[wid] = prev  # type: ignore[assignment]
            for pr in preds:
                deps.append(Dependency(predecessor=last_part[pr], successor=first_part[wid], type="FS"))
        return Problem(name=name or self.name, domain=self.domain, horizon_start=at(start_date, tz), horizon_days=30,
                       currency="USD", terminology=TERMS, tasks=tasks, resources=resources, dependencies=deps,
                       metadata={"template": self.id, "parameters": p})
