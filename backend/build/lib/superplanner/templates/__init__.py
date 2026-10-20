"""Template registry (ARCHITECTURE section 12). Adding a domain = a module + a registry entry."""

from __future__ import annotations

from .base import DomainTemplate, TemplateParameter
from .blank import BlankTemplate
from .exam_prep import ExamPrepTemplate
from .manufacturing import ManufacturingTemplate
from .project import ProjectTemplate

TEMPLATES: dict[str, DomainTemplate] = {
    t.id: t for t in (ManufacturingTemplate(), ExamPrepTemplate(), ProjectTemplate(), BlankTemplate())
}


def get_template(template_id: str) -> DomainTemplate:
    """KeyError for unknown ids (the API maps it to 404)."""
    return TEMPLATES[template_id]


__all__ = ["TEMPLATES", "get_template", "DomainTemplate", "TemplateParameter"]
