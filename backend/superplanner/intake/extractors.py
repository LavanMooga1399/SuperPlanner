"""Extractor interface and describe orchestration (PHASE2 2.6)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from . import messages as M
from .models import (ExtractContext, ExtractorInfo, FinanceDraft, FinanceIntakeResponse, IntakeNote, IntakeTextError,
                     ScheduleDraft, ScheduleIntakeResponse)

log = logging.getLogger("superplanner.intake")
MAX_TEXT_CHARS = 20000


@dataclass
class ScheduleExtraction:
    draft: ScheduleDraft
    notes: list[IntakeNote]


@dataclass
class FinanceExtraction:
    draft: FinanceDraft
    notes: list[IntakeNote]


class Extractor(Protocol):
    name: Literal["rule", "ai"]

    def extract_schedule(self, text: str, ctx: ExtractContext) -> ScheduleExtraction: ...

    def extract_finance(self, text: str, ctx: ExtractContext) -> FinanceExtraction: ...


class AiFallback(Exception):
    """Raised by the AI extractor (and merge) only; describe falls back to the rule-based result."""

    def __init__(self, code: str, message: str | None = None, **values: object):
        self.code = code
        self.message = message or M.fallback_message(code, **values)
        super().__init__(code)


@dataclass(frozen=True)
class AiOptions:
    requested: bool
    enabled: bool
    client_factory: Callable[[], Any] | None
    timeout_seconds: float = 60.0
    max_retries: int = 2
    acquire_slot: Callable[[], bool] | None = None
    release_slot: Callable[[], None] | None = None


class RuleBasedExtractor:
    name: Literal["rule", "ai"] = "rule"

    def extract_schedule(self, text: str, ctx: ExtractContext) -> ScheduleExtraction:
        from .schedule.extract import extract_schedule
        r = extract_schedule(text, ctx)
        return ScheduleExtraction(draft=r.draft, notes=r.notes)

    def extract_finance(self, text: str, ctx: ExtractContext) -> FinanceExtraction:
        from .money.extract import extract_finance
        r = extract_finance(text, ctx)
        return FinanceExtraction(draft=r.draft, notes=r.notes)


def check_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> None:
    if len(text) > max_chars:
        raise IntakeTextError("TEXT_TOO_LONG", f"The text is longer than {max_chars} characters.",
                              {"max_chars": max_chars})
    if not text.strip():
        raise IntakeTextError("TEXT_EMPTY", "Please write a few lines about what you want to plan.")


def _run_ai(domain: str, text: str, ctx: ExtractContext, ai: AiOptions, rule: Any) -> tuple[Any, list[IntakeNote], ExtractorInfo]:
    from .ai.client import MODEL, AnthropicExtractor, ai_status_client
    from .ai.merge import merge_finance, merge_schedule

    available, code, client = ai_status_client(ai)
    if not available:
        return None, [], ExtractorInfo(requested="ai", used="rule", ai_available=False, fallback_code=code,
                                       fallback_message=M.fallback_message(code or "AI_UNEXPECTED"))
    got = ai.acquire_slot() if ai.acquire_slot is not None else True
    if not got:
        return None, [], ExtractorInfo(requested="ai", used="rule", ai_available=True, fallback_code="AI_BUSY",
                                       fallback_message=M.fallback_message("AI_BUSY"))
    try:
        ex = AnthropicExtractor(ai, client=client)
        if domain == "schedule":
            a = ex.extract_schedule(text, ctx)
            draft, notes = merge_schedule(rule.draft, a.draft, a.notes)
        else:
            a = ex.extract_finance(text, ctx)
            draft, notes = merge_finance(rule.draft, a.draft, a.notes)
    except AiFallback as fb:
        return None, [], ExtractorInfo(requested="ai", used="rule", ai_available=True, fallback_code=fb.code,
                                       fallback_message=fb.message)
    except Exception as exc:  # noqa: BLE001 - AI problems never become errors (2.15); type name only in the log
        log.warning("intake AI path failed: %s", type(exc).__name__)
        return None, [], ExtractorInfo(requested="ai", used="rule", ai_available=True, fallback_code="AI_UNEXPECTED",
                                       fallback_message=M.fallback_message("AI_UNEXPECTED"))
    finally:
        if ai.release_slot is not None:
            ai.release_slot()
    return draft, notes, ExtractorInfo(requested="ai", used="ai+rule", ai_available=True, model=MODEL)


def _ai_available(ai: AiOptions | None) -> bool:
    if ai is None:
        return False
    from .ai.client import ai_status
    return ai_status(ai)[0]


def describe_schedule(text: str, ctx: ExtractContext, *, ai: AiOptions | None = None,
                      max_chars: int = MAX_TEXT_CHARS) -> ScheduleIntakeResponse:
    from .schedule.build import build_schedule_problem
    from .schedule.questions import questions

    check_text(text, max_chars)
    t0 = time.monotonic()
    rule = RuleBasedExtractor().extract_schedule(text, ctx)
    draft, notes = rule.draft, list(rule.notes)
    if ai is not None and ai.requested:
        merged, ai_notes, info = _run_ai("schedule", text, ctx, ai, rule)
        if merged is not None:
            draft, notes = merged, notes + ai_notes
    else:
        info = ExtractorInfo(requested="rule", used="rule", ai_available=_ai_available(ai))
    qs = questions(draft, ctx)
    extractor = "ai+rule" if info.used == "ai+rule" else "rule"
    ready = not any(q.required for q in qs) and build_schedule_problem(draft, ctx, extractor=extractor).ready
    log.info("intake describe domain=schedule extractor=%s fallback=%s chars=%d tasks=%d resources=%d ms=%d",
             info.used, info.fallback_code, len(text), len(draft.tasks), len(draft.resources),
             int((time.monotonic() - t0) * 1000))
    return ScheduleIntakeResponse(draft=draft, questions=qs, notes=notes, extractor=info, ready=ready)


def describe_finance(text: str, ctx: ExtractContext, *, ai: AiOptions | None = None,
                     max_chars: int = MAX_TEXT_CHARS) -> FinanceIntakeResponse:
    from .money.build import build_finance_plan
    from .money.questions import questions

    check_text(text, max_chars)
    t0 = time.monotonic()
    rule = RuleBasedExtractor().extract_finance(text, ctx)
    draft, notes = rule.draft, list(rule.notes)
    if ai is not None and ai.requested:
        merged, ai_notes, info = _run_ai("finance", text, ctx, ai, rule)
        if merged is not None:
            draft, notes = merged, notes + ai_notes
    else:
        info = ExtractorInfo(requested="rule", used="rule", ai_available=_ai_available(ai))
    qs = questions(draft, ctx)
    extractor = "ai+rule" if info.used == "ai+rule" else "rule"
    ready = not any(q.required for q in qs) and build_finance_plan(draft, ctx, extractor=extractor)[0].ready
    log.info("intake describe domain=finance extractor=%s fallback=%s chars=%d items=%d ms=%d", info.used,
             info.fallback_code, len(text),
             len(draft.incomes) + len(draft.expenses) + len(draft.debts) + len(draft.holdings) + len(draft.goals),
             int((time.monotonic() - t0) * 1000))
    return FinanceIntakeResponse(draft=draft, questions=qs, notes=notes, extractor=info, ready=ready)
