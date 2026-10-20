"""Blank template: an empty plan with generic terminology."""

from __future__ import annotations

from datetime import date
from typing import Any

from superplanner.engine.model import Problem, Terminology

from .base import TemplateParameter, at, parse_offset, resolve_params


class BlankTemplate:
    id = "blank"
    name = "Blank plan"
    description = "Start from scratch with your own tasks and resources."
    domain = "generic"
    terminology = Terminology()
    parameters: list[TemplateParameter] = []

    def build(self, *, name: str, start_date: date, utc_offset: str, params: dict[str, Any]) -> Problem:
        p = resolve_params(self.parameters, params)
        tz = parse_offset(utc_offset)
        return Problem(name=name or self.name, domain=self.domain, horizon_start=at(start_date, tz), horizon_days=30,
                       terminology=Terminology(), metadata={"template": self.id, "parameters": p})
