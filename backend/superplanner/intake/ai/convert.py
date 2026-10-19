"""Validated AI output -> drafts (PHASE2 2.10 step 5): same key scheme, `source="ai"` provenance, spans found by
locating `source_quote` in the text, values clipped to model limits. AI confidence is capped at 0.8 and is 0.5
when the quote is not found."""

from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError

from ..messages import note_text
from ..models import (DraftAmount, DraftDebt, DraftDuration, DraftExpense, DraftGoal, DraftHolding, DraftIncome,
                      DraftProfile, DraftResource, DraftTask, ExtractContext, FinanceDraft, IntakeNote, Provenance,
                      ScheduleDraft, SourceSpan, TimeWindow, WorkingTime)
from ..text.names import resolve, slug
from .schemas import AiAmount, AiFinanceOutput, AiScheduleOutput

AI_CAP = 0.8


def locate(quote: str, text: str) -> SourceSpan | None:
    q = (quote or "").strip()
    if not q or len(q) > 2000:
        return None
    i, j = text.find(q), -1
    if i >= 0:
        j = i + len(q)
    else:
        # case-insensitive on the original text, so offsets stay code points of `text` even when lower() would
        # change the length of a character
        m = re.search(re.escape(q), text, re.I)
        if m is None:
            return None
        i, j = m.start(), m.end()
    return SourceSpan(start=i, end=j, text=text[i:j][:300])


def ai_prov(quote: str, conf: float, text: str) -> Provenance:
    span = locate(quote, text)
    return Provenance(source="ai", confidence=min(conf, AI_CAP) if span else 0.5, span=span)


def _iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def _month(s: str | None) -> str | None:
    if s and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s.strip()):
        return s.strip()
    return None


def _clip_name(s: str, fallback: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()[:200]
    return s or fallback


def _windows(ws) -> list[TimeWindow] | None:
    out = []
    for w in ws[:4]:
        try:
            out.append(TimeWindow(start=w.start, end=w.end))
        except ValidationError:
            return None
    return out or None


def ai_notes(notes: list[str]) -> list[IntakeNote]:
    return [IntakeNote(code="AI_NOTE", severity="info", message=note_text("AI_NOTE", text=n.strip()[:300]))
            for n in notes[:5] if n and n.strip()]


def ai_to_schedule_draft(out: AiScheduleOutput, text: str, ctx: ExtractContext) -> tuple[ScheduleDraft, list[IntakeNote]]:
    prov: dict[str, Provenance] = {}
    notes = ai_notes(out.notes)
    resources: list[DraftResource] = []
    for r in out.resources[:100]:
        key = "r_" + slug(r.name or "resource")
        base, k = key, 2
        while any(x.key == key for x in resources):
            key = f"{base[:28]}_{k}"
            k += 1
        resources.append(DraftResource(key=key, name=_clip_name(r.name, "Resource"), kind=r.kind,
                                       count=max(1, min(50, r.count))))
        prov[f"/resources/{key}/name"] = ai_prov(r.source_quote, r.confidence, text)
    rnames = [(r.key, r.name) for r in resources]
    tasks: list[DraftTask] = []
    raw_after: list[list[str]] = []
    for i, t in enumerate(out.tasks[:500], start=1):
        key = f"t{i}"
        dur = None
        d = t.duration
        vals = [v for v in (d.low, d.likely, d.high) if v is not None and v > 0]
        if vals and d.unit is not None and not t.milestone:
            lo = d.low if d.low and d.low > 0 else min(vals)
            hi = d.high if d.high and d.high > 0 else max(vals)
            lk = d.likely if d.likely and d.likely > 0 else (lo + hi) / 2
            o, lk, p = sorted(min(10000.0, v) for v in (lo, lk, hi))
            dur = DraftDuration(optimistic=o, likely=lk, pessimistic=p, unit=d.unit)
        res_keys = []
        for nm in t.resources:
            hit = next((k for k, n in rnames if n.lower() == nm.strip().lower()), None)
            if hit is None:
                hit = resolve(nm, rnames).key
            if hit is None:
                notes.append(IntakeNote(code="AI_REFERENCE_DROPPED", severity="info",
                                        message=note_text("AI_REFERENCE_DROPPED", name=nm[:80])))
            elif hit not in res_keys:
                res_keys.append(hit)
        tasks.append(DraftTask(key=key, name=_clip_name(t.name, f"Task {i}"), milestone=t.milestone, duration=dur,
                               resources=[] if t.milestone else res_keys, resource_mode=t.resource_mode,
                               deadline=_iso(t.deadline), deadline_hard=t.deadline_hard and _iso(t.deadline) is not None,
                               earliest_start=_iso(t.earliest_start),
                               group=(t.group or "").strip()[:200] or None))
        raw_after.append(list(t.after))
        p = ai_prov(t.source_quote, t.confidence, text)
        prov[f"/tasks/{key}/name"] = p
        for fld, present in (("duration", dur is not None), ("deadline", t.deadline), ("earliest_start", t.earliest_start),
                             ("resources", res_keys), ("after", t.after)):
            if present:
                prov[f"/tasks/{key}/{fld}"] = p
    names = [(t.key, t.name) for t in tasks]
    for t, after in zip(tasks, raw_after):
        for nm in after:
            hit = next((k for k, n in names if n.lower() == nm.strip().lower()), None) or resolve(nm, names,
                                                                                                    exclude=t.key).key
            if hit is None or hit == t.key:
                notes.append(IntakeNote(code="AI_REFERENCE_DROPPED", severity="info",
                                        message=note_text("AI_REFERENCE_DROPPED", name=nm[:80])))
            elif hit not in t.after:
                t.after.append(hit)
    wt = None
    if out.working_time is not None and out.working_time.days:
        win = _windows(out.working_time.windows)
        if win:
            try:
                wt = WorkingTime(days=list(dict.fromkeys(out.working_time.days)), windows=win,
                                 weekend_windows=_windows(out.working_time.weekend_windows))
                prov["/working_time"] = ai_prov(out.working_time.source_quote, 0.8, text)
            except ValidationError:
                wt = None
    draft = ScheduleDraft(kind=ctx.kind or out.kind, name=_clip_name(out.name or "", "My plan"),
                          start_date=_iso(out.start_date), working_time=wt, tasks=tasks, resources=resources,
                          provenance=prov)
    return draft, notes


def _amount(a: AiAmount) -> DraftAmount | None:
    vals = [v for v in (a.low, a.high) if v is not None and v >= 0]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    return DraftAmount(low=min(lo, 1e12), high=min(hi, 1e12))


def _add_months(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    k = y * 12 + m - 1 + n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def ai_to_finance_draft(out: AiFinanceOutput, text: str, ctx: ExtractContext) -> tuple[FinanceDraft, list[IntakeNote]]:
    prov: dict[str, Provenance] = {}
    notes = ai_notes(out.notes)
    start = f"{ctx.today.year:04d}-{ctx.today.month:02d}"
    pr = out.profile
    age = pr.age if pr.age is not None and 16 <= pr.age <= 100 else None
    profile = DraftProfile(age=age,
                           retirement_age=pr.retirement_age if pr.retirement_age and 40 <= pr.retirement_age <= 80 else None,
                           risk_tolerance=pr.risk_tolerance if pr.risk_tolerance and 1 <= pr.risk_tolerance <= 5 else None,
                           currency=ctx.currency, locale=ctx.locale)
    for fld in ("age", "retirement_age", "risk_tolerance"):
        if getattr(profile, fld) is not None:
            prov[f"/profile/{fld}"] = ai_prov(pr.source_quote, 0.8, text)
    incomes = []
    for i, x in enumerate(out.incomes[:20], start=1):
        key = f"i{i}"
        incomes.append(DraftIncome(key=key, name=_clip_name(x.name, "Income"), kind=x.kind, amount=_amount(x.amount),
                                   frequency=x.frequency, interruptible=x.kind not in ("pension", "rental")))
        p = ai_prov(x.source_quote, x.confidence, text)
        prov[f"/incomes/{key}/name"] = p
        if incomes[-1].amount is not None:
            prov[f"/incomes/{key}/amount"] = p.model_copy(update={"note": "GROSS" if x.is_gross else ""})
    expenses = []
    for i, x in enumerate(out.expenses[:100], start=1):
        key = f"e{i}"
        cat = re.sub(r"[^a-z_]+", "_", (x.category or "other").lower()).strip("_")[:64] or "other"
        expenses.append(DraftExpense(key=key, name=_clip_name(x.name, "Expense"), category=cat, amount=_amount(x.amount),
                                     frequency=x.frequency, essential=x.essential,
                                     inflation_pct=9.0 if cat == "education" else None))
        p = ai_prov(x.source_quote, x.confidence, text)
        prov[f"/expenses/{key}/name"] = p
        if expenses[-1].amount is not None:
            prov[f"/expenses/{key}/amount"] = p
    debts = []
    for i, x in enumerate(out.debts[:20], start=1):
        key = f"d{i}"
        rate = x.interest_rate_pct if x.interest_rate_pct is not None and 0 <= x.interest_rate_pct <= 60 else None
        rem = x.remaining_months if x.remaining_months and 1 <= x.remaining_months <= 600 else None
        debts.append(DraftDebt(key=key, name=_clip_name(x.name, "Loan"), kind=x.kind, balance=_amount(x.balance),
                               interest_rate_pct=rate, emi=_amount(x.emi), remaining_months=rem))
        p = ai_prov(x.source_quote, x.confidence, text)
        prov[f"/debts/{key}/name"] = p
        for fld in ("balance", "emi", "interest_rate_pct", "remaining_months"):
            if getattr(debts[-1], fld) is not None:
                prov[f"/debts/{key}/{fld}"] = p
    holdings = []
    for i, x in enumerate(out.holdings[:50], start=1):
        key = f"h{i}"
        holdings.append(DraftHolding(key=key, name=_clip_name(x.name, "Savings"),
                                     asset_class_id=None if x.asset_class == "unknown" else x.asset_class,
                                     amount=_amount(x.amount), locked_until_month=_month(x.locked_until)))
        p = ai_prov(x.source_quote, x.confidence, text)
        prov[f"/holdings/{key}/name"] = p
        if holdings[-1].amount is not None:
            prov[f"/holdings/{key}/amount"] = p
        if holdings[-1].asset_class_id is not None:
            prov[f"/holdings/{key}/asset_class_id"] = p
    goals = []
    for i, x in enumerate(out.goals[:12], start=1):
        key = f"g{i}"
        p = ai_prov(x.source_quote, x.confidence, text)
        month = _month(x.target_month)
        mprov = p
        if month is None and x.in_years is not None and 0 < x.in_years <= 80:
            month = _add_months(start, int(round(12 * x.in_years)))
        if month is None and x.at_age is not None:
            if age is not None and x.at_age > age:
                month = _add_months(start, 12 * (x.at_age - age))
            else:
                mprov = Provenance(source="ai", confidence=0.3, span=p.span, note=f"AT_AGE:{x.at_age}")
        goals.append(DraftGoal(key=key, name=_clip_name(x.name, "Goal"), kind=x.kind, target=_amount(x.target),
                               target_month=month, priority=x.priority,
                               inflation_pct=9.0 if x.kind == "education" else None))
        prov[f"/goals/{key}/name"] = p
        if goals[-1].target is not None:
            prov[f"/goals/{key}/target"] = p
        if month is not None or mprov is not p:
            prov[f"/goals/{key}/target_month"] = mprov
        if x.priority is not None:
            prov[f"/goals/{key}/priority"] = p
    ef = out.emergency_fund_months if out.emergency_fund_months is not None and 0 <= out.emergency_fund_months <= 24 \
        else None
    draft = FinanceDraft(start_month=start, profile=profile, incomes=incomes, expenses=expenses, debts=debts,
                         holdings=holdings, goals=goals, emergency_fund_months=ef, provenance=prov)
    return draft, notes
