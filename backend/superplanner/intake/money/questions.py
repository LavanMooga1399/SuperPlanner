"""Finance follow-up questions (PHASE2 2.8): a pure function of the draft."""

from __future__ import annotations

from superplanner.finance.advisor.messages import format_money

from .. import messages as M
from ..models import ExtractContext, FinanceDraft, Question, QuestionOption
from ..qa import answered, order, pathless_done, qid
from .extract import _MONTHLY, add_months_str

DEBT_RATE_DEFAULT = {"home": 8.5, "vehicle": 9.5, "education": 10.0, "personal": 13.0, "credit_card": 36.0,
                     "other": 12.0}
DEFAULT_PRIORITY = {"retirement": "must", "education": "must"}


def start_month(draft: FinanceDraft, ctx: ExtractContext) -> str:
    return draft.start_month or f"{ctx.today.year:04d}-{ctx.today.month:02d}"


def retirement_target_of(draft: FinanceDraft) -> float:
    """PHASE2 1.8 retirement preset on draft figures (midpoints); mirrors `finance.templates.retirement_target`."""
    e_rec = sum(e.amount.mid * _MONTHLY[e.frequency] for e in draft.expenses
                if e.amount is not None and e.end_month is None and e.category != "education")
    i_rec = sum(i.amount.mid * _MONTHLY[i.frequency] for i in draft.incomes
                if i.amount is not None and i.kind in ("rental", "pension") and i.end_month is None)
    return round(25 * 12 * max(0.0, e_rec - i_rec), 2)


def monthly_income(draft: FinanceDraft) -> float:
    return sum(i.amount.mid * _MONTHLY[i.frequency] for i in draft.incomes if i.amount is not None)


def emi_derivable(d) -> bool:
    return d.balance is not None and d.remaining_months is not None


def _money_label(v: float, currency: str) -> str:
    return format_money(v, currency)


def questions(draft: FinanceDraft, ctx: ExtractContext) -> list[Question]:
    prov = draft.provenance
    cur = draft.profile.currency
    out: list[Question] = []
    dismissed = set(draft.dismissed)
    start = start_month(draft, ctx)

    def add(q: Question) -> None:
        if q.id not in dismissed:
            out.append(q)

    def span(path: str):
        p = prov.get(path)
        return p.span if p else None

    if not draft.incomes and not pathless_done(prov, "FIN_INCOME"):
        add(Question(id=qid("FIN_INCOME", None), code="FIN_INCOME", path=None, kind="money",
                     prompt=M.prompt("FIN_INCOME"), required=True, reason="missing"))
    for i in draft.incomes:
        path = f"/incomes/{i.key}/amount"
        if i.amount is None and not answered(prov, path):
            add(Question(id=qid("FIN_INCOME", path), code="FIN_INCOME", path=path, kind="money",
                         prompt=M.prompt("FIN_TAKE_HOME", name=i.name), required=True, reason="missing",
                         span=span(f"/incomes/{i.key}/name")))
        elif (p := prov.get(path)) is not None and p.note == "GROSS" and p.source not in ("answer", "edit"):
            add(Question(id=qid("FIN_TAKE_HOME", path), code="FIN_TAKE_HOME", path=path, kind="money",
                         prompt=M.prompt("FIN_TAKE_HOME", name=i.name), required=True, reason="conflict",
                         span=p.span))
    needs_age = any(g.kind == "retirement" for g in draft.goals) or any(
        (p := prov.get(f"/goals/{g.key}/target_month")) is not None and p.note.startswith("AT_AGE:")
        for g in draft.goals)
    if draft.profile.age is None and not answered(prov, "/profile/age"):
        add(Question(id=qid("FIN_AGE", "/profile/age"), code="FIN_AGE", path="/profile/age", kind="number",
                     prompt=M.prompt("FIN_AGE"), required=needs_age, reason="missing"))
    for g in draft.goals:
        base = f"/goals/{g.key}"
        if g.kind != "retirement" and g.target is None and not answered(prov, f"{base}/target"):
            add(Question(id=qid("FIN_GOAL_TARGET", f"{base}/target"), code="FIN_GOAL_TARGET", path=f"{base}/target",
                         kind="money", prompt=M.prompt("FIN_GOAL_TARGET", name=g.name), required=True,
                         reason="missing", span=span(f"{base}/name")))
        age_dep = (p := prov.get(f"{base}/target_month")) is not None and p.note.startswith("AT_AGE:")
        retire_dep = g.kind == "retirement" and draft.profile.age is None
        if g.target_month is None and not answered(prov, f"{base}/target_month") and not (
                (age_dep or retire_dep) and draft.profile.age is None):
            d = add_months_str(start, 60)
            add(Question(id=qid("FIN_GOAL_DATE", f"{base}/target_month"), code="FIN_GOAL_DATE",
                         path=f"{base}/target_month", kind="month", prompt=M.prompt("FIN_GOAL_DATE", name=g.name),
                         default=d, default_label=d, required=True, reason="missing", span=span(f"{base}/name")))
    for g in draft.goals:
        base = f"/goals/{g.key}"
        if g.kind == "retirement" and g.target is None and not answered(prov, f"{base}/target"):
            v = retirement_target_of(draft)
            if v > 0:
                add(Question(id=qid("FIN_RETIREMENT_TARGET", f"{base}/target"), code="FIN_RETIREMENT_TARGET",
                             path=f"{base}/target", kind="money",
                             prompt=M.prompt("FIN_RETIREMENT_TARGET", amount=_money_label(v, cur)), default=v,
                             default_label=_money_label(v, cur), required=False, reason="confirm_default"))
            else:
                add(Question(id=qid("FIN_GOAL_TARGET", f"{base}/target"), code="FIN_GOAL_TARGET",
                             path=f"{base}/target", kind="money", prompt=M.prompt("FIN_GOAL_TARGET", name=g.name),
                             required=True, reason="missing"))
    if not draft.expenses and not pathless_done(prov, "FIN_ESSENTIALS"):
        v = round(0.5 * monthly_income(draft), 2)
        add(Question(id=qid("FIN_ESSENTIALS", None), code="FIN_ESSENTIALS", path=None, kind="money",
                     prompt=M.prompt("FIN_ESSENTIALS"), default=v if v > 0 else None,
                     default_label=_money_label(v, cur) if v > 0 else "", required=False, reason="missing"))
    if not any(e.essential is False for e in draft.expenses) and not pathless_done(prov, "FIN_DISCRETIONARY"):
        add(Question(id=qid("FIN_DISCRETIONARY", None), code="FIN_DISCRETIONARY", path=None, kind="money",
                     prompt=M.prompt("FIN_DISCRETIONARY"), default=0, default_label="None", required=False,
                     reason="missing"))
    for e in draft.expenses:
        path = f"/expenses/{e.key}/essential"
        if e.essential is None and not answered(prov, path):
            add(Question(id=qid("FIN_EXPENSE_ESSENTIAL", path), code="FIN_EXPENSE_ESSENTIAL", path=path,
                         kind="confirm", prompt=M.prompt("FIN_EXPENSE_ESSENTIAL", name=e.name), default=True,
                         default_label="Yes", required=False, reason="missing", span=span(f"/expenses/{e.key}/name")))
    for d in draft.debts:
        base = f"/debts/{d.key}"
        if d.balance is None and not answered(prov, f"{base}/balance"):
            add(Question(id=qid("FIN_DEBT_BALANCE", f"{base}/balance"), code="FIN_DEBT_BALANCE",
                         path=f"{base}/balance", kind="money", prompt=M.prompt("FIN_DEBT_BALANCE", name=d.name),
                         required=True, reason="missing", span=span(f"{base}/name")))
        if d.emi is None and not emi_derivable(d) and not answered(prov, f"{base}/emi"):
            add(Question(id=qid("FIN_DEBT_EMI", f"{base}/emi"), code="FIN_DEBT_EMI", path=f"{base}/emi", kind="money",
                         prompt=M.prompt("FIN_DEBT_EMI", name=d.name), required=True, reason="missing",
                         span=span(f"{base}/name")))
        if d.interest_rate_pct is None and not answered(prov, f"{base}/interest_rate_pct"):
            v = DEBT_RATE_DEFAULT[d.kind]
            add(Question(id=qid("FIN_DEBT_RATE", f"{base}/interest_rate_pct"), code="FIN_DEBT_RATE",
                         path=f"{base}/interest_rate_pct", kind="percent", prompt=M.prompt("FIN_DEBT_RATE", name=d.name),
                         default=v, default_label=f"{v:g}%", required=False, reason="missing"))
    for h in draft.holdings:
        base = f"/holdings/{h.key}"
        if h.asset_class_id is None and not answered(prov, f"{base}/asset_class_id"):
            add(Question(id=qid("FIN_HOLDING_CLASS", f"{base}/asset_class_id"), code="FIN_HOLDING_CLASS",
                         path=f"{base}/asset_class_id", kind="choice", prompt=M.prompt("FIN_HOLDING_CLASS", name=h.name),
                         options=[QuestionOption(value=k, label=v) for k, v in M.HOLDING_CLASS_LABELS.items()],
                         default="cash", default_label=M.HOLDING_CLASS_LABELS["cash"], required=False,
                         reason="missing", span=span(f"{base}/name")))
        if h.asset_class_id == "govt_long" and h.locked_until_month is None \
                and not answered(prov, f"{base}/locked_until_month"):
            v = add_months_str(start, 180)
            add(Question(id=qid("FIN_HOLDING_LOCK", f"{base}/locked_until_month"), code="FIN_HOLDING_LOCK",
                         path=f"{base}/locked_until_month", kind="month",
                         prompt=M.prompt("FIN_HOLDING_LOCK", name=h.name), default=v, default_label=v, required=False,
                         reason="missing"))
    for g in draft.goals:
        path = f"/goals/{g.key}/priority"
        if g.priority is None and not answered(prov, path):
            v = DEFAULT_PRIORITY.get(g.kind, "should")
            add(Question(id=qid("FIN_GOAL_PRIORITY", path), code="FIN_GOAL_PRIORITY", path=path, kind="choice",
                         prompt=M.prompt("FIN_GOAL_PRIORITY", name=g.name),
                         options=[QuestionOption(value=k, label=v2) for k, v2 in M.PRIORITY_LABELS.items()],
                         default=v, default_label=M.PRIORITY_LABELS[v], required=False, reason="missing"))
    if draft.profile.risk_tolerance is None and not answered(prov, "/profile/risk_tolerance"):
        add(Question(id=qid("FIN_RISK", "/profile/risk_tolerance"), code="FIN_RISK", path="/profile/risk_tolerance",
                     kind="choice", prompt=M.prompt("FIN_RISK"),
                     options=[QuestionOption(value=str(k), label=v) for k, v in M.RISK_LABELS.items()],
                     default="3", default_label=M.RISK_LABELS[3], required=False, reason="missing"))
    if draft.emergency_fund_months is None and not answered(prov, "/emergency_fund_months"):
        add(Question(id=qid("FIN_EF_MONTHS", "/emergency_fund_months"), code="FIN_EF_MONTHS",
                     path="/emergency_fund_months", kind="number", prompt=M.prompt("FIN_EF_MONTHS"), default=6,
                     default_label="6 months", required=False, reason="missing"))
    for path, p in prov.items():
        if p.confidence < 0.5 and p.source in ("text", "table", "ai", "derived") and not p.note.startswith("AT_AGE:") \
                and _exists(draft, path):
            add(Question(id=qid("FIN_LOW_CONFIDENCE", path), code="FIN_LOW_CONFIDENCE", path=path, kind="confirm",
                         prompt=M.prompt("FIN_LOW_CONFIDENCE", text=p.span.text if p.span else path), default=True,
                         default_label="Yes", required=False, reason="low_confidence", span=p.span))
    return order(out)


_COLL = ("incomes", "expenses", "debts", "holdings", "goals")


def _exists(draft: FinanceDraft, path: str) -> bool:
    parts = path.strip("/").split("/")
    if parts[0] in _COLL and len(parts) == 3:
        return any(x.key == parts[1] for x in getattr(draft, parts[0]))
    return parts[0] in ("profile", "emergency_fund_months", "start_month", "name")
