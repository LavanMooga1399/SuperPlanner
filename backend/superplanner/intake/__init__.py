"""SuperPlanner intake: free text and pasted/CSV tables -> drafts, questions and plan documents (PHASE2 2).

Pure package: no FastAPI, Starlette, SQLAlchemy or `superplanner.api` imports. All functions are synchronous,
deterministic for the rule-based path and keep no module state.
"""

from __future__ import annotations

from .extractors import (AiFallback, AiOptions, Extractor, FinanceExtraction, RuleBasedExtractor, ScheduleExtraction,
                         describe_finance, describe_schedule)
from .messages import MODEL, PRIVACY_NOTICE, PROVIDER
from .models import (Answer, ColumnMapping, Domain, ExtractContext, ExtractorInfo, FinanceBuildResult, FinanceDraft,
                     FinanceIntakeResponse, IntakeError, IntakeNote, IntakeTextError, Provenance, Question,
                     ScheduleBuildResult, ScheduleDraft, ScheduleIntakeResponse, TableApply, TableOptions,
                     TableParseRequest, TableParseResult)
from .models import MAX_TABLE_CHARS, MAX_TABLE_COLUMNS, MAX_TABLE_ROWS, SCHEDULE_KINDS
from .qa import attach_errors
from .schedule.build import DOMAIN_OF_KIND, BuilderBug

_RULE = ExtractorInfo(requested="rule", used="rule", ai_available=False)


def _origin(prov: dict[str, Provenance]) -> tuple[str, str]:
    sources = {p.source for p in prov.values()}
    return ("table" if "table" in sources else "describe"), ("ai+rule" if "ai" in sources else "rule")


def answer_schedule(draft: ScheduleDraft, answers: list[Answer], ctx: ExtractContext, *,
                    ai_available: bool = False) -> ScheduleIntakeResponse:
    from .schedule.answers import answer_schedule_draft
    from .schedule.questions import questions

    new, outcome = answer_schedule_draft(draft, answers, ctx)
    qs = attach_errors(questions(new, ctx), outcome.errors)
    ready = not any(q.required for q in qs) and build_schedule(new, ctx).ready
    return ScheduleIntakeResponse(draft=new, questions=qs, notes=[], extractor=_RULE.model_copy(
        update={"ai_available": ai_available}), ready=ready)


def answer_finance(draft: FinanceDraft, answers: list[Answer], ctx: ExtractContext, *,
                   ai_available: bool = False) -> FinanceIntakeResponse:
    from .money.answers import answer_finance_draft
    from .money.questions import questions

    new, outcome = answer_finance_draft(draft, answers, ctx)
    qs = attach_errors(questions(new, ctx), outcome.errors)
    ready = not any(q.required for q in qs) and build_finance(new, ctx).ready
    return FinanceIntakeResponse(draft=new, questions=qs, notes=[], extractor=_RULE.model_copy(
        update={"ai_available": ai_available}), ready=ready)


def build_schedule(draft: ScheduleDraft, ctx: ExtractContext) -> ScheduleBuildResult:
    from .schedule.build import build_schedule_problem

    source, extractor = _origin(draft.provenance)
    return build_schedule_problem(draft, ctx, source=source, extractor=extractor)


def build_finance(draft: FinanceDraft, ctx: ExtractContext) -> FinanceBuildResult:
    from .money.build import build_finance_plan

    source, extractor = _origin(draft.provenance)
    return build_finance_plan(draft, ctx, source=source, extractor=extractor)[0]


def parse_table(text: str, domain: Domain, *, delimiter: str = "auto", has_header: bool | None = None,
                today=None, max_chars: int = MAX_TABLE_CHARS) -> TableParseResult:
    from .tables.parse import parse_table as _parse

    return _parse(text, domain, delimiter=delimiter, has_header=has_header, today=today, max_chars=max_chars)


def apply_schedule_table(req: TableApply, ctx: ExtractContext, base: ScheduleDraft | None, *,
                         max_chars: int = MAX_TABLE_CHARS, ai_available: bool = False) -> ScheduleIntakeResponse:
    from .schedule.questions import questions
    from .tables.apply import apply_schedule_rows

    draft, row_notes = apply_schedule_rows(req, ctx, base, max_chars=max_chars)
    qs = questions(draft, ctx)
    ready = not any(q.required for q in qs) and build_schedule(draft, ctx).ready
    return ScheduleIntakeResponse(draft=draft, questions=qs, notes=[], row_notes=row_notes,
                                  extractor=_RULE.model_copy(update={"ai_available": ai_available}), ready=ready)


def apply_finance_table(req: TableApply, ctx: ExtractContext, base: FinanceDraft | None, *,
                        max_chars: int = MAX_TABLE_CHARS, ai_available: bool = False) -> FinanceIntakeResponse:
    from .money.questions import questions
    from .tables.apply import apply_finance_rows

    draft, row_notes = apply_finance_rows(req, ctx, base, max_chars=max_chars)
    qs = questions(draft, ctx)
    ready = not any(q.required for q in qs) and build_finance(draft, ctx).ready
    return FinanceIntakeResponse(draft=draft, questions=qs, notes=[], row_notes=row_notes,
                                 extractor=_RULE.model_copy(update={"ai_available": ai_available}), ready=ready)


__all__ = [
    "describe_schedule", "describe_finance", "answer_schedule", "answer_finance", "build_schedule", "build_finance",
    "parse_table", "apply_schedule_table", "apply_finance_table", "AiFallback", "AiOptions", "Extractor",
    "RuleBasedExtractor", "ScheduleExtraction", "FinanceExtraction", "MODEL", "PROVIDER", "PRIVACY_NOTICE",
    "Answer", "ColumnMapping", "Domain", "ExtractContext", "ExtractorInfo", "FinanceBuildResult", "FinanceDraft",
    "FinanceIntakeResponse", "IntakeError", "IntakeNote", "IntakeTextError", "Provenance", "Question",
    "ScheduleBuildResult", "ScheduleDraft", "ScheduleIntakeResponse", "TableApply", "TableOptions",
    "TableParseRequest", "TableParseResult", "MAX_TABLE_CHARS", "MAX_TABLE_COLUMNS", "MAX_TABLE_ROWS",
    "SCHEDULE_KINDS", "DOMAIN_OF_KIND", "BuilderBug",
]
