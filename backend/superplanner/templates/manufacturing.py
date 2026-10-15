"""Manufacturing template: jobs with cut -> mill -> assemble on machines with shifts."""

from __future__ import annotations

from datetime import date
from typing import Any

from superplanner.engine.model import (BlockedInterval, Calendar, Dependency, Problem, Requirement, Resource, Task,
                                       Terminology)

from .base import TemplateParameter, at, parse_offset, resolve_params

TERMS = Terminology(task="Operation", tasks="Operations", resource="Machine", resources="Machines", group="Job",
                    milestone="Milestone", schedule="Production schedule", deadline="Due date")

_SHIFTS = [("06:00", "14:00"), ("14:00", "22:00")]


def _calendar(blocked: list[BlockedInterval] | None = None) -> Calendar:
    weekly = {d: list(_SHIFTS) for d in ("mon", "tue", "wed", "thu", "fri")}
    weekly["sat"] = [("06:00", "14:00")]
    return Calendar(weekly=weekly, blocked=blocked or [])


class ManufacturingTemplate:
    id = "manufacturing"
    name = "Manufacturing"
    description = "Jobs with operations on machines, alternative machines, shifts and due dates."
    domain = "manufacturing"
    terminology = TERMS
    parameters = [
        TemplateParameter(name="jobs", label="Number of jobs", type="int", default=5, min=1, max=20),
        TemplateParameter(name="due_in_days", label="Latest due date (days)", type="int", default=5, min=2, max=30),
    ]

    def build(self, *, name: str, start_date: date, utc_offset: str, params: dict[str, Any]) -> Problem:
        p = resolve_params(self.parameters, params)
        tz = parse_offset(utc_offset)
        jobs, due = p["jobs"], p["due_in_days"]
        maintenance = BlockedInterval(start=at(start_date, tz, 1, "10:00"), end=at(start_date, tz, 1, "12:00"),
                                      reason="Maintenance")
        resources = [
            Resource(id="CUT1", name="Saw 1", kind="machine", capacity=1, cost_per_hour=900.0, calendar=_calendar()),
            Resource(id="MILL1", name="Mill 1", kind="machine", capacity=1, cost_per_hour=1200.0,
                     calendar=_calendar([maintenance])),
            Resource(id="MILL2", name="Mill 2", kind="machine", capacity=1, cost_per_hour=1500.0,
                     calendar=_calendar()),
            Resource(id="ASM1", name="Assembly bench", kind="machine", capacity=1, cost_per_hour=800.0,
                     calendar=_calendar()),
            Resource(id="OPS", name="Operators", kind="person", capacity=2, cost_per_hour=300.0,
                     calendar=_calendar()),
        ]
        tasks: list[Task] = []
        deps: list[Dependency] = []
        for k in range(1, jobs + 1):
            job = f"J{k}"
            due_dt = at(start_date, tz, min(due, 1 + k), "18:00")
            prio = 10 - k % 5
            ops = [
                (f"{job}-1", f"{job} Cutting", 60 + 15 * (k % 4), [Requirement(alternatives=["CUT1"])]),
                (f"{job}-2", f"{job} Milling", 90 + 15 * (k % 3), [Requirement(alternatives=["MILL1", "MILL2"])]),
                (f"{job}-3", f"{job} Assembly", 45 + 15 * (k % 2),
                 [Requirement(alternatives=["ASM1"]), Requirement(alternatives=["OPS"])]),
            ]
            for j, (tid, tname, dur, reqs) in enumerate(ops):
                tasks.append(Task(id=tid, name=tname, group=job, duration_minutes=dur, priority=prio,
                                  deadline=due_dt if j == 2 else None, deadline_hard=False, requirements=reqs))
                if j > 0:
                    deps.append(Dependency(predecessor=ops[j - 1][0], successor=tid, type="FS"))
        return Problem(name=name or self.name, domain=self.domain, horizon_start=at(start_date, tz),
                       horizon_days=max(14, due + 7), currency="USD", terminology=TERMS, tasks=tasks,
                       resources=resources, dependencies=deps,
                       metadata={"template": self.id, "parameters": p})
