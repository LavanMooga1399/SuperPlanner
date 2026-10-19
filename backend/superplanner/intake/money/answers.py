"""Apply answers to a `FinanceDraft` (PHASE2 2.8)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..models import (Answer, DraftAmount, DraftExpense, DraftIncome, ExtractContext, FinanceDraft, IntakeError,
                      Provenance, Question)
from ..qa import (AnswerError, ApplyOutcome, apply_answers, as_choice, as_confirm, as_money, as_month, as_number,
                  mark_answered)
from .extract import add_months_str
from .questions import questions, start_month


def _item(draft: FinanceDraft, path: str):
    _, coll, key, *_ = path.split("/")
    x = next((i for i in getattr(draft, coll) if i.key == key), None)
    if x is None:
        raise AnswerError("That item no longer exists.")
    return x


def _next_key(items, prefix: str) -> str:
    n = len(items) + 1
    keys = {i.key for i in items}
    while f"{prefix}{n}" in keys:
        n += 1
    return f"{prefix}{n}"


def recompute_age_months(draft: FinanceDraft, ctx: ExtractContext) -> None:
    """Goal months that depend on the age (retirement, "at age N") once the age is known."""
    age = draft.profile.age
    if age is None:
        return
    start = start_month(draft, ctx)
    for g in draft.goals:
        path = f"/goals/{g.key}/target_month"
        p = draft.provenance.get(path)
        if p is not None and p.source in ("answer", "edit"):
            continue
        if p is not None and p.note.startswith("AT_AGE:"):
            n = int(p.note.split(":", 1)[1])
            g.target_month = add_months_str(start, 12 * max(0, n - age))
            draft.provenance[path] = Provenance(source="derived", confidence=0.9, span=p.span,
                                                note=f"Age {age} + {max(0, n - age)} years")
        elif g.kind == "retirement" and (g.target_month is None or (p is not None and p.source == "derived")):
            ra = draft.profile.retirement_age or 60
            g.target_month = add_months_str(start, 12 * max(1, ra - age))
            draft.provenance[path] = Provenance(source="derived", confidence=0.9,
                                                note=f"Age {age} + {max(1, ra - age)} years")


def _apply_one(ctx: ExtractContext):
    def apply(draft: FinanceDraft, q: Question, value: Any) -> None:
        prov = draft.provenance
        code, path = q.code, q.path or ""
        if code in ("FIN_INCOME", "FIN_TAKE_HOME") and path:
            lo, hi = as_money(value)
            if hi <= 0:
                raise AnswerError("Please enter an amount above zero.")
            inc = _item(draft, path)
            inc.amount = DraftAmount(low=lo, high=hi)
            inc.frequency = "monthly"            # both prompts ask for the amount taken home each month
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_INCOME":
            lo, hi = as_money(value)
            if hi <= 0:
                raise AnswerError("Please enter an amount above zero.")
            key = _next_key(draft.incomes, "i")
            draft.incomes.append(DraftIncome(key=key, name="Salary", amount=DraftAmount(low=lo, high=hi)))
            mark_answered(prov, f"/incomes/{key}/amount")
            prov["/answers/FIN_INCOME"] = Provenance(source="answer", confidence=1.0)
        elif code in ("FIN_GOAL_TARGET", "FIN_RETIREMENT_TARGET", "FIN_DEBT_BALANCE", "FIN_DEBT_EMI"):
            lo, hi = as_money(value)
            if code in ("FIN_GOAL_TARGET", "FIN_RETIREMENT_TARGET") and hi <= 0:
                raise AnswerError("Please enter an amount above zero.")
            setattr(_item(draft, path), path.split("/")[-1], DraftAmount(low=lo, high=hi))
            mark_answered(prov, path, keep_span=False)
        elif code in ("FIN_GOAL_DATE", "FIN_HOLDING_LOCK"):
            setattr(_item(draft, path), path.split("/")[-1], as_month(value, ctx))
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_AGE":
            v = int(round(as_number(value)))
            if not 16 <= v <= 100:
                raise AnswerError("Please enter an age between 16 and 100.")
            draft.profile.age = v
            mark_answered(prov, path, keep_span=False)
            recompute_age_months(draft, ctx)
        elif code == "FIN_ESSENTIALS":
            lo, hi = as_money(value)
            if hi > 0:
                key = _next_key(draft.expenses, "e")
                draft.expenses.append(DraftExpense(key=key, name="Essential spending", category="living",
                                                   amount=DraftAmount(low=lo, high=hi), essential=True))
                mark_answered(prov, f"/expenses/{key}/amount")
            prov["/answers/FIN_ESSENTIALS"] = Provenance(source="answer", confidence=1.0)
        elif code == "FIN_DISCRETIONARY":
            lo, hi = as_money(value)
            if hi > 0:
                key = _next_key(draft.expenses, "e")
                draft.expenses.append(DraftExpense(key=key, name="Other spending", category="lifestyle",
                                                   amount=DraftAmount(low=lo, high=hi), essential=False))
                mark_answered(prov, f"/expenses/{key}/amount")
            prov["/answers/FIN_DISCRETIONARY"] = Provenance(source="answer", confidence=1.0)
        elif code == "FIN_EXPENSE_ESSENTIAL":
            _item(draft, path).essential = as_confirm(value)
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_DEBT_RATE":
            v = as_number(value, "percent")
            if not 0 <= v <= 60:
                raise AnswerError("Please enter a rate between 0 and 60%.")
            _item(draft, path).interest_rate_pct = v
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_HOLDING_CLASS":
            _item(draft, path).asset_class_id = as_choice(value, q)
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_GOAL_PRIORITY":
            _item(draft, path).priority = as_choice(value, q)
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_RISK":
            draft.profile.risk_tolerance = int(as_choice(str(value) if isinstance(value, int) else value, q))
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_EF_MONTHS":
            v = as_number(value)
            if not 0 <= v <= 24:
                raise AnswerError("Please enter between 0 and 24 months.")
            draft.emergency_fund_months = v
            mark_answered(prov, path, keep_span=False)
        elif code == "FIN_LOW_CONFIDENCE":
            yes = as_confirm(value)
            parts = path.strip("/").split("/")
            if not yes and len(parts) == 3 and parts[2] in ("amount", "target", "balance", "emi"):
                setattr(_item(draft, path), parts[2], None)
                prov.pop(path, None)
                return
            mark_answered(prov, path)
        else:  # pragma: no cover
            raise AnswerError("This question cannot be answered here.")
    return apply


def answer_finance_draft(draft: FinanceDraft, answers: list[Answer], ctx: ExtractContext) \
        -> tuple[FinanceDraft, ApplyOutcome]:
    work = draft.model_copy(deep=True)
    outcome = apply_answers(work, answers, questions(work, ctx), _apply_one(ctx))
    recompute_age_months(work, ctx)        # goal months that follow from the age, whichever answer set it
    try:
        work = FinanceDraft.model_validate(work.model_dump())
    except ValidationError as exc:  # pragma: no cover
        raise IntakeError("VALIDATION_ERROR", "The answers would make the draft invalid.",
                          {"errors": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                                      for e in exc.errors()]}) from None
    return work, outcome
