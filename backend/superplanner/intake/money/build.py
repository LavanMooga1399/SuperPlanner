"""`FinanceDraft` -> `FinancePlan` (PHASE2 2.9.2). Nothing is stored."""

from __future__ import annotations

import logging

from superplanner import finance
from superplanner.finance import templates as fin_templates
from superplanner.finance.model import (AmountRange, Debt, EmergencyFundSettings, Expense, FinancePlan, Goal, Holding,
                                        IncomeStream, Profile)

from ..messages import note_text
from ..models import DraftAmount, ExtractContext, FinanceBuildResult, FinanceDraft, IntakeNote
from .questions import DEBT_RATE_DEFAULT, DEFAULT_PRIORITY, questions, start_month

log = logging.getLogger(__name__)
KNOWN_CLASSES = {"cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold"}


class BuilderBug(Exception):
    """The builder produced an invalid FinancePlan (a bug: 500 + log)."""


def _rng(a: DraftAmount) -> AmountRange | None:
    return AmountRange(low=a.low, high=a.high) if a.low < a.high else None


def annuity_emi(balance: float, rate_pct: float, months: int) -> float:
    r = rate_pct / 1200
    if r <= 0:
        return round(balance / months, 2)
    return round(balance * r / (1 - (1 + r) ** -months), 2)


def build_finance_plan(draft: FinanceDraft, ctx: ExtractContext, *, source: str = "describe",
                       extractor: str = "rule") -> tuple[FinanceBuildResult, list[IntakeNote]]:
    notes: list[IntakeNote] = []
    blocking = [q for q in questions(draft, ctx) if q.required]
    if blocking:
        return FinanceBuildResult(ready=False, plan=None, preflight=None, cashflow=None, blocking=blocking), notes
    start = start_month(draft, ctx)
    try:
        incomes = [IncomeStream(id=i.key, name=i.name, kind=i.kind, amount=i.amount.mid, frequency=i.frequency,
                                growth_pct=i.growth_pct or 0.0, end_month=i.end_month, interruptible=i.interruptible,
                                inflation_linked=i.inflation_linked, amount_range=_rng(i.amount))
                   for i in draft.incomes if i.amount is not None and i.amount.high > 0]
        expenses = [Expense(id=e.key, name=e.name, category=e.category, amount=e.amount.mid, frequency=e.frequency,
                            essential=True if e.essential is None else e.essential, inflation_pct=e.inflation_pct,
                            end_month=e.end_month, amount_range=_rng(e.amount))
                    for e in draft.expenses if e.amount is not None and e.amount.high > 0]
        debts = []
        for d in draft.debts:
            assert d.balance is not None
            rate = d.interest_rate_pct if d.interest_rate_pct is not None else DEBT_RATE_DEFAULT[d.kind]
            if d.emi is not None:
                emi = d.emi.mid
            else:
                assert d.remaining_months is not None
                emi = annuity_emi(d.balance.mid, rate, d.remaining_months)
                notes.append(IntakeNote(code="DEBT_EMI_DERIVED", severity="info",
                                        message=note_text("DEBT_EMI_DERIVED", name=d.name)))
            debts.append(Debt(id=d.key, name=d.name, kind=d.kind, balance=d.balance.mid, interest_rate_pct=rate,
                              emi=emi, remaining_months=d.remaining_months))
        holdings = [Holding(id=h.key, name=h.name,
                            asset_class_id=h.asset_class_id if h.asset_class_id in KNOWN_CLASSES else "cash",
                            amount=h.amount.mid, locked_until_month=h.locked_until_month)
                    for h in draft.holdings if h.amount is not None and h.amount.high > 0]
        goals = []
        for g in draft.goals:
            assert g.target_month is not None
            if g.target is not None and g.target.high > 0:
                target, trange = g.target.mid, _rng(g.target)
            else:
                target, trange = fin_templates.retirement_target(expenses, incomes), None
            if target <= 0:
                continue
            goals.append(Goal(id=g.key, name=g.name, kind=g.kind, target_amount=target, target_month=g.target_month,
                              priority=g.priority or DEFAULT_PRIORITY.get(g.kind, "should"),  # type: ignore[arg-type]
                              flexibility_months=g.flexibility_months, inflation_pct=g.inflation_pct,
                              target_range=trange))
        prof = draft.profile
        plan = FinancePlan(
            name=draft.name, start_month=start,
            profile=Profile(currency=prof.currency, locale=prof.locale, age=prof.age,
                            retirement_age=prof.retirement_age or 60, risk_tolerance=prof.risk_tolerance or 3),
            incomes=incomes, expenses=expenses, debts=debts, holdings=holdings, goals=goals,
            emergency_fund=EmergencyFundSettings(months_of_essentials=6.0 if draft.emergency_fund_months is None
                                                 else draft.emergency_fund_months),
            metadata={"intake": {"version": 1, "source": source, "extractor": extractor}})
    except (ValueError, AssertionError) as exc:
        log.error("intake finance builder produced an invalid plan: %s", type(exc).__name__)
        raise BuilderBug("invalid plan from the intake builder") from None
    report = finance.preflight(plan)
    cash = finance.summarize_cashflow(finance.project_cashflow(plan)) if report.ok else None
    return FinanceBuildResult(ready=report.ok, plan=plan, preflight=report, cashflow=cash, blocking=[]), notes
