"""Shared question/answer helpers (PHASE2 2.8): question ids, ordering, answer-value parsing, the apply loop."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from pydantic import ValidationError

from . import messages as M
from .models import Answer, DraftDuration, ExtractContext, IntakeError, Provenance, Question, WorkingTime
from .text.dates import parse_date_text, parse_month_text
from .text.durations import parse_duration_text
from .text.numbers import parse_money_text, parse_number_text, parse_percent_text

ANSWERED_SOURCES = ("answer", "edit")


def qid(code: str, path: str | None) -> str:
    return f"{code}:{path or '-'}"


def answered(prov: dict[str, Provenance], path: str) -> bool:
    p = prov.get(path)
    return p is not None and p.source in ANSWERED_SOURCES


def pathless_done(prov: dict[str, Provenance], code: str) -> bool:
    """Path-less questions (SCHED_SEQUENTIAL, ...) are recorded under `/answers/<code>` once answered."""
    return f"/answers/{code}" in prov


def mark_answered(prov: dict[str, Provenance], path: str, keep_span: bool = True) -> None:
    old = prov.get(path)
    prov[path] = Provenance(source="answer", confidence=1.0, span=old.span if (old and keep_span) else None)


def order(questions: list[Question]) -> list[Question]:
    return [q for q in questions if q.required] + [q for q in questions if not q.required]


class AnswerError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def unparsed(kind: str) -> AnswerError:
    return AnswerError(M.QUESTION_ERRORS["UNPARSED"].format(example=M.EXAMPLES.get(kind, "a value")))


_YES = {"yes", "y", "true", "ok", "okay", "sure", "correct", "right", "1", "yep", "yeah"}
_NO = {"no", "n", "false", "0", "nope", "wrong", "incorrect"}


def value_text(value: Any) -> str | None:
    if isinstance(value, dict) and set(value) == {"text"} and isinstance(value["text"], str):
        return value["text"][:2000]
    return None


def as_confirm(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    t = value_text(value) if not isinstance(value, str) else value
    if isinstance(t, str) and t.strip().lower() in _YES:
        return True
    if isinstance(t, str) and t.strip().lower() in _NO:
        return False
    raise unparsed("confirm")


def as_number(value: Any, kind: str = "number") -> float:
    if isinstance(value, bool):
        raise unparsed(kind)
    if isinstance(value, (int, float)):
        return float(value)
    t = value_text(value) if not isinstance(value, str) else value
    if t is not None:
        v = parse_percent_text(t) if kind == "percent" else parse_number_text(t)
        if v is not None:
            return v
    raise unparsed(kind)


def as_money(value: Any) -> tuple[float, float]:
    if isinstance(value, bool):
        raise unparsed("money")
    if isinstance(value, (int, float)):
        if value < 0:
            raise AnswerError(M.QUESTION_ERRORS["OUT_OF_RANGE"])
        return float(value), float(value)
    if isinstance(value, dict) and set(value) == {"low", "high"}:
        try:
            lo, hi = float(value["low"]), float(value["high"])
        except (TypeError, ValueError):
            raise unparsed("money") from None
        if lo < 0 or hi < lo:
            raise AnswerError(M.QUESTION_ERRORS["OUT_OF_RANGE"])
        return lo, hi
    t = value_text(value) if not isinstance(value, str) else value
    if t is not None:
        r = parse_money_text(t)
        if r is not None:
            return r
        if t.strip().lower() in ("none", "nothing", "no", "0", "zero", "nil"):
            return 0.0, 0.0
    raise unparsed("money")


def as_duration(value: Any, default_unit: str) -> DraftDuration:
    if isinstance(value, dict) and "text" not in value:
        try:
            return DraftDuration.model_validate(value)
        except ValidationError:
            raise unparsed("duration") from None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return DraftDuration.single(float(value), default_unit)
    t = value_text(value) if not isinstance(value, str) else value
    if t is not None:
        d = parse_duration_text(t, default_unit)
        if d is not None and d.unit in ("minutes", "hours", "days", "weeks"):
            try:
                return DraftDuration(optimistic=min(d.optimistic, 10000), likely=min(d.likely, 10000),
                                     pessimistic=min(d.pessimistic, 10000), unit=d.unit)  # type: ignore[arg-type]
            except ValidationError:
                pass
    raise unparsed("duration")


def as_date(value: Any, ctx: ExtractContext) -> date:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    t = value_text(value) if not isinstance(value, str) else value
    if t is not None:
        d = parse_date_text(t, ctx.today, ctx.locale)
        if d is not None:
            return d
    raise unparsed("date")


def as_month(value: Any, ctx: ExtractContext) -> str:
    t = value_text(value) if not isinstance(value, str) else value
    if t is not None:
        m = parse_month_text(t, ctx.today, ctx.locale)
        if m is not None:
            return m
    raise unparsed("month")


def as_choice(value: Any, q: Question) -> str:
    opts = {o.value for o in q.options}
    if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value) in opts:
        return str(value)
    t = value_text(value)
    if t is not None:
        low = t.strip().lower()
        for o in q.options:
            if low in (o.value.lower(), o.label.lower()):
                return o.value
    raise AnswerError(M.QUESTION_ERRORS["BAD_OPTION"])


def as_multi(value: Any, q: Question) -> list[str]:
    opts = [o.value for o in q.options]
    if isinstance(value, list) and value and all(isinstance(v, str) and v in opts for v in value):
        return list(dict.fromkeys(value))
    t = value_text(value)
    if t is not None:
        parts = [p.strip().lower() for p in re.split(r",|\band\b|/|&", t) if p.strip()]
        out = []
        for p in parts:
            hit = next((o.value for o in q.options if p in (o.value.lower(), o.label.lower())), None)
            if hit is None:
                raise AnswerError(M.QUESTION_ERRORS["BAD_OPTION"])
            out.append(hit)
        if out:
            return list(dict.fromkeys(out))
    raise AnswerError(M.QUESTION_ERRORS["BAD_OPTION"])


def as_working_time(value: Any, parse_text: Callable[[str], WorkingTime | None]) -> WorkingTime:
    if isinstance(value, dict) and "text" not in value:
        try:
            return WorkingTime.model_validate(value)
        except ValidationError:
            raise unparsed("working_time") from None
    t = value_text(value) if not isinstance(value, str) else value
    if t is not None:
        wt = parse_text(t)
        if wt is not None:
            return wt
    raise unparsed("working_time")


@dataclass
class ApplyOutcome:
    errors: dict[str, str]


def apply_answers(draft: Any, answers: list[Answer], questions: list[Question],
                  apply_one: Callable[[Any, Question, Any], None]) -> ApplyOutcome:
    """Validate ids (UNKNOWN_QUESTION), then apply each answer in order; per-question errors are collected."""
    by_id = {q.id: q for q in questions}
    for a in answers:
        if a.question_id not in by_id:
            raise IntakeError("UNKNOWN_QUESTION", f"There is no open question {a.question_id!r}.",
                              {"question_id": a.question_id})
    errors: dict[str, str] = {}
    for a in answers:
        q = by_id[a.question_id]
        if a.skip:
            if q.required:
                errors[q.id] = "This question needs an answer."
                continue
            if q.id not in draft.dismissed:
                draft.dismissed.append(q.id)
            continue
        value = a.value
        if a.use_default:
            if q.default is None and q.kind not in ("confirm",):
                errors[q.id] = "There is no suggestion for this question; please enter a value."
                continue
            value = q.default
        if value is None:
            errors[q.id] = "Please enter a value."
            continue
        try:
            apply_one(draft, q, value)
        except AnswerError as exc:
            errors[q.id] = exc.message
    return ApplyOutcome(errors=errors)


def attach_errors(questions: list[Question], errors: dict[str, str]) -> list[Question]:
    return [q.model_copy(update={"error": errors[q.id]}) if q.id in errors else q for q in questions]
