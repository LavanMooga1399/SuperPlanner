"""Rule-based `FinanceDraft` extraction (PHASE2 2.7.9, 2.7.10). Deterministic, linear-time patterns.

Cue lists may contain product words (`ppf`, ...): they only read the user's text. User-facing text lives in
`intake/messages.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from ..messages import note_text
from ..models import (DraftAmount, DraftDebt, DraftExpense, DraftGoal, DraftHolding, DraftIncome, DraftProfile,
                      ExtractContext, FinanceDraft, IntakeNote, Provenance)
from ..text.dates import find_dates, out_of_range_dates
from ..text.names import STOP_WORDS
from ..text.numbers import (NUM, MoneyMatch, find_money, find_percent, frequency_info_anywhere, parse_number)
from ..text.segment import Text, blank, clean_name, normalise, segments

EF_RE = re.compile(r"\bemergency\s+(?:fund|corpus|savings|buffer)\b", re.I)
AGE_RE = re.compile(r"\b(?:i'?m|i am|my age is|age|aged)\s+(?P<n>\d{2})\b(?!\s*(?:%|k\b|l\b|lakh|years?\s+(?:left|to)))"
                    r"|\b(?P<n2>\d{2})\s+(?:years?|yrs?)\s+old\b", re.I)
RETIRE_RE = re.compile(r"\bretir(?:e|ing|ement)\b", re.I)
RETIRE_AGE_RE = re.compile(r"\bretir(?:e|ing|ement)\s+(?:at|by|when\s+i'?m|when\s+i\s+am|at\s+age|at\s+the\s+age\s+of)\s+"
                           r"(?P<n>\d{2})\b", re.I)
RETIRE_IN_RE = re.compile(rf"\bretir(?:e|ing)\s+in\s+(?P<n>{NUM})\s+years?\b", re.I)
GROSS_RE = re.compile(r"\b(?:ctc|gross|cost to company|before tax|pre-?tax|lpa)\b", re.I)
# "paid" alone is not income ("I paid 50k for a fridge"); only "get / am / is ... paid" is
INCOME_RE = re.compile(r"\b(?:earn(?:s|ing)?|salary|take[- ]?home|in[- ]hand|income|"
                       r"(?:get|gets|getting|am|is|are|being)\s+paid|stipend|pension|"
                       r"freelanc\w*|business income|rent (?:income|from)|tenant pays|rental|consult\w*)\b", re.I)
PARTNER_RE = re.compile(r"\bmy\s+(?:wife|husband|partner|spouse)\b|\b(?:wife|husband|partner|spouse)\s+earns\b", re.I)
DEBT_RE = re.compile(r"\b(?:loan|emi|mortgage|credit card|outstanding|borrowed|owe)\b", re.I)
HOLDING_RE = re.compile(r"\b(?:have|saved|savings|invested|hold|holding|holdings|own|portfolio|corpus|maturing|"
                        r"matures?|maturity|in\s+(?:fds?|fixed deposits?|mutual funds?|sips?|stocks?|"
                        r"shares|equity|index funds?|ppf|epf|provident fund|nps|gold|(?:the\s+)?bank|savings account|"
                        r"debt funds?|bonds?))\b", re.I)
GOAL_RE = re.compile(r"\b(?:save|saving for|need|want|goal|target|plan(?:ning)? to|buy|for\s+(?:a|my|our|the)|"
                     r"retire|retirement|(?:must|should)\s+have|would (?:like|love)|wish|dream)\b", re.I)
# A product noun with an amount and no frequency is a statement of what is held ("FD of 5L", "gold worth 3 lakh").
PRODUCT_RE = re.compile(r"\b(?:fds?|fixed deposits?|mutual funds?|stocks?|shares|equity|index funds?|ppf|epf|"
                        r"provident fund|nps|gold|debt funds?|bonds?|savings account|bank balance)\b", re.I)
# Paying someone else's salary is spending ("maid salary 6,000"), never the user's income.
PAID_TO_OTHERS_RE = re.compile(
    r"\b(?:maid|maids|driver|cook|nanny|servant|helper|house ?help|domestic help|gardener|watchman|guard|tutor|"
    r"staff|employees?|workers?|cleaner|ayah|babysitter|caretaker)(?:'s|s')?\s+(?:salary|salaries|wages?|pay)\b"
    r"|\b(?:salary|salaries|wages?)\s+(?:of|for|to)\s+(?:the|my|our)?\s*(?:maid|driver|cook|nanny|servant|helper|"
    r"staff|employees?|workers?|cleaner|babysitter|caretaker)\b"
    r"|\bpay(?:ing)?\s+(?:the|my|our)?\s*(?:maid|driver|cook|nanny|servant|helper|staff|cleaner|babysitter)\b",
    re.I)
GOAL_NOT_HOLDING_RE = re.compile(r"\b(?:want|need|goal|target|buy|plan(?:ning)? to|(?:must|should)\s+have)\b", re.I)
NEXT_YEAR_RE = re.compile(r"\bnext\s+year\b", re.I)
EXPENSE_RE = re.compile(r"\b(?:spend|spending|expenses?|costs?|pay|rent|groceries|bills|fees|insurance|premium|"
                        r"household|living|tuition|utilities|maid|fuel|petrol|school)\b", re.I)
RISK_WORDS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bvery aggressive\b", re.I), 5),
    (re.compile(r"\b(?:aggressive|high[- ]risk|growth)\b", re.I), 4),
    (re.compile(r"\b(?:moderate|balanced|medium)\b", re.I), 3),
    (re.compile(r"\b(?:conservative|low[- ]risk|safe|cautious)\b", re.I), 2),
]
RISK_NUM_RE = re.compile(r"\b(?:risk\s*(?:level|tolerance)?\s*:?\s*)?(?P<n>[1-5])\s*(?:/|out of)\s*5\b", re.I)
RISK_CTX_RE = re.compile(r"\b(?:risk|investor|appetite|tolerance|profile)\b", re.I)
RULE_CUE_RE = re.compile(r"\b(?:only|never|not on|no more than|at most|at least|maximum|minimum|every other|alternate|"
                         r"unless|except|budget|cost limit)\b", re.I)
IN_YEARS_RE = re.compile(rf"\bin\s+(?P<n>{NUM})\s+(?P<u>years?|months?)\b", re.I)
AT_AGE_RE = re.compile(r"\b(?:at\s+age|when\s+i'?m|when\s+i\s+am|by\s+age|at\s+the\s+age\s+of)\s+(?P<n>\d{2})\b", re.I)
REMAINING_RE = re.compile(rf"\b(?P<n>{NUM})\s+(?P<u>years?|months?)\s+(?:left|remaining|to go|more)\b", re.I)
BALANCE_AFTER_RE = re.compile(r"^\s*(?:is\s+)?(?:left|outstanding|balance|remaining|pending|due|to go|still owed)\b", re.I)
BALANCE_BEFORE_RE = re.compile(r"\b(?:balance(?:\s+of)?|outstanding(?:\s+of)?|loan\s+of|borrowed|owe)\s*$", re.I)
EMI_BEFORE_RE = re.compile(r"\bemi\b[^,.;\d]{0,15}$", re.I)
YEAR_IN_RE = re.compile(r"\b(?:in|by|before|until|till)\s+(?:the\s+year\s+)?(?P<y>(?:19|20|21)\d{2})\b", re.I)
# a one-off purchase in the past is not a regular cost ("Bought a phone for 60000 last month")
# "paid" counts unless it is the present "get / am / is paid" of a salary
PAST_ONE_OFF_RE = re.compile(r"\b(?:bought|purchased|spent|splurged|gifted|got\s+(?:a|an|my|our|the)|"
                             r"(?<!get )(?<!gets )(?<!getting )(?<!am )(?<!is )(?<!are )(?<!being )paid|"
                             r"last\s+(?:week|month|year|summer|winter|diwali)|yesterday|(?:days?|weeks?|months?|"
                             r"years?)\s+ago|earlier this (?:week|month|year))\b", re.I)

# a forward-looking cue: the amount is wanted in the future, so a past or recurring reading does not apply
FORWARD_GOAL_RE = re.compile(r"\b(?:want|wants|need|needs|goal|target|plan(?:ning)?\s+to|save|saving|(?:must|should)\s+"
                             r"have|would\s+(?:like|love)|wish|dream|will|going\s+to|next)\b", re.I)
# "in 2150", "by the year 2160": a year in a date-like position (too far ones get DATE_OUT_OF_RANGE)
YEAR_POS_RE = re.compile(r"\b(?:in|by|before|until|till|after|since|during)\s+(?:the\s+year\s+)?(?P<y>\d{4})(?!\d|[,.]\d)",
                         re.I)

HOLDING_CLASS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(?:fds?|fixed deposits?)\b", re.I), "fixed_deposit", "Fixed deposit"),
    (re.compile(r"\b(?:mutual funds?|sips?|stocks?|shares|equity|index funds?)\b", re.I), "equity_index", ""),
    (re.compile(r"\b(?:ppf|epf|provident fund|nps)\b", re.I), "govt_long", ""),
    (re.compile(r"\bgold\b", re.I), "gold", "Gold"),
    (re.compile(r"\b(?:debt funds?|bonds?)\b", re.I), "short_debt", ""),
    (re.compile(r"\b(?:bank|savings account|savings|cash)\b", re.I), "cash", "Savings"),
]
GOAL_KINDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bretir\w*", re.I), "retirement"),
    (re.compile(r"\b(?:house|home|flat|apartment|down ?payment)\b", re.I), "home"),
    (re.compile(r"\b(?:car|bike|vehicle|scooter)\b", re.I), "vehicle"),
    (re.compile(r"\b(?:education|college|school|university|mba|degree|studies)\b", re.I), "education"),
    (re.compile(r"\b(?:wedding|marriage)\b", re.I), "wedding"),
    (re.compile(r"\b(?:trip|travel|vacation|holiday)\b", re.I), "travel"),
    (re.compile(r"\b(?:business|startup|shop)\b", re.I), "business"),
]
MUST_RE = re.compile(r"\b(?:must|have to|essential|non-negotiable|absolutely)\b|\bneed\b", re.I)
NICE_RE = re.compile(r"\b(?:would like|nice|maybe|if possible|dream|someday|would love)\b", re.I)
EXPENSE_CATS: list[tuple[re.Pattern[str], str, bool, float | None]] = [
    (re.compile(r"\b(?:school|tuition|fees|education)\b", re.I), "education", True, 9.0),
    (re.compile(r"\b(?:insurance|premium)\b", re.I), "insurance", True, None),
    (re.compile(r"\b(?:medical|health|medicine|doctor)\b", re.I), "health", True, None),
    (re.compile(r"\b(?:transport|fuel|petrol|diesel|commute)\b", re.I), "transport", True, None),
    (re.compile(r"\b(?:eating out|dining|shopping|entertainment|subscriptions?|travel|fun|lifestyle|movies|"
                r"holidays?)\b", re.I), "lifestyle", False, None),
    (re.compile(r"\b(?:rent|housing|household|living|groceries|food|utilities|bills|electricity|maid)\b", re.I),
     "living", True, None),
]
DEBT_KINDS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(?:home|house)\s+loan|\bmortgage\b", re.I), "home", "Home loan"),
    (re.compile(r"\b(?:car|bike|vehicle|auto)\s+loan\b", re.I), "vehicle", "Car loan"),
    (re.compile(r"\b(?:education|student)\s+loan\b", re.I), "education", "Education loan"),
    (re.compile(r"\bpersonal\s+loan\b", re.I), "personal", "Personal loan"),
    (re.compile(r"\bcredit\s+card\b", re.I), "credit_card", "Credit card"),
]
_EXP_NAME_TAIL_RE = re.compile(r"\s+(?:are|is|of|come to|comes to|run|runs|at|around|about|roughly|approximately|total|"
                               r"cost me|costs me|amount to|amounts to|take|takes|=|:)\s*$", re.I)
_EXP_NAME_HEAD_RE = re.compile(r"^(?:and|also|plus|then|our|my|the|we|i)\s+(?:(?:also\s+)?(?:spend|pay)\s+)?", re.I)
_ON_NAME_RE = re.compile(r"^\s*(?:on|for)\s+(?P<n>[a-z][a-z ,'&-]{1,60}?)(?=$|[,.;]|\s+(?:and|every|each|per|a)\b)",
                         re.I)


@dataclass
class _Clause:
    start: int
    end: int
    text: str
    sentence: int
    sent_start: int = 0
    sent_text: str = ""


@dataclass
class FinanceExtractionResult:
    draft: FinanceDraft
    notes: list[IntakeNote]


def _clauses(t: Text) -> list[_Clause]:
    out: list[_Clause] = []
    for si, seg in enumerate(segments(t)):
        s = seg.text
        cuts = [0]
        for m in re.finditer(r",\s+|;\s+|\s+and\s+|\s+but\s+|\s+plus\s+", s, re.I):
            if m.group(0).strip().lower() == "and" and re.search(r"\bbetween\s+\S{1,20}\s*$", s[max(0, m.start() - 40):m.start()], re.I):
                continue
            cuts.append(m.start())
            cuts.append(m.end())
        cuts.append(len(s))
        for a, b in zip(cuts[0::2], cuts[1::2]):
            text = s[a:b]
            if text.strip():
                lead = len(text) - len(text.lstrip())
                out.append(_Clause(seg.start + a + lead, seg.start + b, text.strip(), si, seg.start, s))
    return out


def _cap(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] if s else s


@dataclass
class _State:
    t: Text
    ctx: ExtractContext
    prov: dict[str, Provenance] = field(default_factory=dict)
    notes: list[IntakeNote] = field(default_factory=list)
    incomes: list[DraftIncome] = field(default_factory=list)
    expenses: list[DraftExpense] = field(default_factory=list)
    debts: list[DraftDebt] = field(default_factory=list)
    holdings: list[DraftHolding] = field(default_factory=list)
    goals: list[DraftGoal] = field(default_factory=list)
    profile: DraftProfile = field(default_factory=DraftProfile)
    ef_months: float | None = None
    ef_amount: tuple[float, int, int] | None = None
    currencies: set[str] = field(default_factory=set)
    retire_age_span: tuple[int, int] | None = None
    at_age: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    sent_kind: dict[int, str] = field(default_factory=dict)
    sent_dates: dict[int, tuple[re.Match[str] | None, re.Match[str] | None]] = field(default_factory=dict)
    sent_goal: dict[int, "_SentGoal"] = field(default_factory=dict)
    years_skipped: list[tuple[int, int]] = field(default_factory=list)   # of the clause read last (see _money)

    def p(self, path: str, a: int, b: int, conf: float, source: str = "text", note: str = "") -> None:
        self.prov[path] = Provenance(source=source, confidence=round(conf, 3), span=self.t.span(a, b),  # type: ignore
                                     note=note)

    def note(self, code: str, severity: str, message: str, a: int | None = None, b: int | None = None) -> None:
        self.notes.append(IntakeNote(code=code, severity=severity, message=message,  # type: ignore[arg-type]
                                     span=self.t.span(a, b) if a is not None and b is not None else None))


@dataclass
class _SentGoal:
    """Goal context of a whole sentence, computed once per sentence (linear time)."""
    kind: str | None                       # goal noun kind ("wedding", "travel", ...)
    month: tuple[str, int, int, float] | None   # future target month with its sentence-local span and confidence


def _future_month(st: _State, s: str) -> tuple[str, int, int, float] | None:
    """The first future date in `s` as a target month ("in 2035", "Dec 2030", "in 3 years")."""
    today = st.ctx.today
    iy = IN_YEARS_RE.search(s)
    best: tuple[str, int, int, float] | None = None
    if iy:
        n = parse_number(iy.group("n"))
        if n:
            months = int(round(n[0] * (12 if iy.group("u").lower().startswith("y") else 1)))
            if 0 < months <= MAX_GOAL_MONTHS:
                best = (add_months_str(_start_month(st.ctx), months), iy.start(), iy.end(), 0.95)
    for d in find_dates(s, today, st.ctx.locale):
        if d.kind in ("monyear", "dmy", "mdy", "iso", "numeric") and d.value > today:
            if best is None or d.start < best[1]:
                best = (f"{d.value.year:04d}-{d.value.month:02d}", d.start, d.end, d.confidence)
            break
    ym = YEAR_IN_RE.search(s)
    if ym and int(ym.group("y")) >= today.year and (best is None or ym.start() < best[1]) and \
            int(ym.group("y")) - today.year <= 100:
        month = f"{ym.group('y')}-{today.month:02d}" if int(ym.group("y")) > today.year else \
            f"{today.year:04d}-12"
        best = (month, ym.start(), ym.end(), 0.8)
    return best


def _sent_goal(st: _State, c: _Clause) -> _SentGoal:
    if c.sentence not in st.sent_goal:
        kind = next((k for rx, k in GOAL_KINDS if rx.search(c.sent_text)), None)
        st.sent_goal[c.sentence] = _SentGoal(kind, _future_month(st, c.sent_text))
    return st.sent_goal[c.sentence]


def _amount_conf(m: MoneyMatch, freq_known: bool = True) -> float:
    if m.year_like:
        return 0.45
    if m.approx:
        return 0.8
    return 0.95 if (m.explicit and freq_known) else 0.7


def _money(st: _State, c: _Clause) -> list[MoneyMatch]:
    # dates are masked so years are never read as money
    work = c.text
    ranges = [(d.start, d.end) for d in find_dates(work, st.ctx.today, st.ctx.locale)]
    ranges += out_of_range_dates(work, st.ctx.today, st.ctx.locale)     # "31 Dec 9999": never an amount
    for m in list(IN_YEARS_RE.finditer(work)) + list(AGE_RE.finditer(work)) + list(AT_AGE_RE.finditer(work)) + \
            list(RETIRE_AGE_RE.finditer(work)) + list(REMAINING_RE.finditer(work)):
        ranges.append((m.start(), m.end()))
    work = blank(work, ranges)
    st.years_skipped = []
    ms = find_money(work, years_skipped=st.years_skipped)
    for m in ms:
        # unmarked money uses ctx.currency (2.7.2), so it takes part in the mixed-currency check
        st.currencies.add(m.currency or st.ctx.currency)
    return ms


def _start_month(ctx: ExtractContext) -> str:
    return f"{ctx.today.year:04d}-{ctx.today.month:02d}"


def add_months_str(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    k = y * 12 + (m - 1) + n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def extract_finance(text: str, ctx: ExtractContext) -> FinanceExtractionResult:
    t = normalise(text)
    st = _State(t=t, ctx=ctx)
    st.profile = DraftProfile(currency=ctx.currency, locale=ctx.locale)
    start = _start_month(ctx)
    oor = out_of_range_dates(t.norm, ctx.today, ctx.locale)
    for a, b in oor:
        st.note("DATE_OUT_OF_RANGE", "warning", note_text("DATE_OUT_OF_RANGE", text=t.norm[a:b][:80]), a, b)
    _far_year_notes(st, oor)
    clauses = _clauses(t)
    prev_class: dict[int, str] = {}
    used_sentences: set[int] = set()
    for c in clauses:
        cls = _classify(st, c, prev_class.get(c.sentence))
        if cls:
            prev_class[c.sentence] = cls
            used_sentences.add(c.sentence)
    # deferred: retirement / at-age goal months need the age
    age = st.profile.age
    for g in st.goals:
        path = f"/goals/{g.key}/target_month"
        if g.kind == "retirement" and g.target_month is None and st.profile.retirement_age and age:
            g.target_month = add_months_str(start, 12 * (st.profile.retirement_age - age))
            a, b = st.retire_age_span or (0, 0)
            st.p(path, a, b, 0.9, "derived", f"Age {age} + {st.profile.retirement_age - age} years")
        elif g.key in st.at_age and g.target_month is None:
            n, a, b = st.at_age[g.key]
            if age:
                g.target_month = add_months_str(start, 12 * max(0, n - age))
                st.p(path, a, b, 0.9, "derived", f"Age {age} + {max(0, n - age)} years")
            else:
                st.p(path, a, b, 0.3, "text", f"AT_AGE:{n}")
    if st.ef_amount is not None and st.ef_months is None:
        ess = sum(e.amount.mid * _MONTHLY[e.frequency] for e in st.expenses if e.amount and e.essential)
        if ess > 0:
            st.ef_months = round(min(24.0, st.ef_amount[0] / ess), 1)
            st.p("/emergency_fund_months", st.ef_amount[1], st.ef_amount[2], 0.5, "derived",
                 "From the amount you gave and your essential costs")
    if len(st.currencies) > 1 or (st.currencies and st.currencies != {ctx.currency}):
        st.note("MIXED_CURRENCY", "warning", note_text("MIXED_CURRENCY", currency=ctx.currency))
    # unsupported rules: sentences with a rule cue that produced nothing
    for si, seg in enumerate(segments(t)):
        if si not in used_sentences and RULE_CUE_RE.search(seg.text):
            st.note("UNSUPPORTED_RULE", "warning", note_text("UNSUPPORTED_RULE", text=seg.text.strip()[:200]),
                    seg.start, seg.end)
    for coll, limit, what in (("incomes", 20, "incomes"), ("expenses", 100, "costs"), ("debts", 20, "loans"),
                              ("holdings", 50, "savings"), ("goals", 12, "goals")):
        items = getattr(st, coll)
        if len(items) > limit:
            dropped = {x.key for x in items[limit:]}
            st.prov = {p_: v for p_, v in st.prov.items()
                       if not (p_.startswith(f"/{coll}/") and p_.split("/")[2] in dropped)}
            st.note("LIST_CAPPED", "warning", note_text("LIST_CAPPED", limit=limit, what=what))
    draft = FinanceDraft(start_month=start, profile=st.profile, incomes=st.incomes[:20], expenses=st.expenses[:100],
                         debts=st.debts[:20], holdings=st.holdings[:50], goals=st.goals[:12],
                         emergency_fund_months=st.ef_months, provenance=st.prov)
    return FinanceExtractionResult(draft=draft, notes=st.notes)


MAX_GOAL_MONTHS = 12 * 100     # "in 9999 years" is not a plan date (left out with DATE_OUT_OF_RANGE)


def _far_year_notes(st: _State, taken: list[tuple[int, int]]) -> None:
    """DATE_OUT_OF_RANGE for a year in a date-like position that is too far to be a goal date ("Wedding in 2150"):
    the reader leaves it out (never an amount, never a month), so it says so instead of dropping it silently."""
    s, limit, n = st.t.norm, st.ctx.today.year + MAX_GOAL_MONTHS // 12, 0
    for m in YEAR_POS_RE.finditer(s):
        if int(m.group("y")) <= limit or any(a < m.end() and m.start() < b for a, b in taken):
            continue
        off = m.start("y") - m.start()
        if any(x.amount_start == off for x in find_money(s[m.start():m.end() + 40], min_bare=0.0)):
            continue        # "in 2150 rupees", "by 2150 a month": an amount, not a year
        st.note("DATE_OUT_OF_RANGE", "warning", note_text("DATE_OUT_OF_RANGE", text=m.group(0)[:80]), m.start(),
                m.end())
        n += 1
        if n >= 20:
            break

_MONTHLY = {"monthly": 1.0, "quarterly": 1 / 3, "half_yearly": 1 / 6, "yearly": 1 / 12, "once": 0.0}


def _classify(st: _State, c: _Clause, prev: str | None) -> str | None:
    s = c.text
    a0 = c.start
    money = _money(st, c)
    found = None
    # profile: age
    am = AGE_RE.search(s)
    if am and any(x.start() <= am.start() < x.end() or am.start() <= x.start() < am.end()
                  for x in list(AT_AGE_RE.finditer(s)) + list(RETIRE_AGE_RE.finditer(s))):
        am = None      # "when I'm 50" / "at age 55" date a goal; they are not the user's age
    if am and not RETIRE_RE.search(s[:am.start()][-12:]):
        n = int(am.group("n") or am.group("n2"))
        if 16 <= n <= 100 and st.profile.age is None:
            st.profile.age = n
            st.p("/profile/age", a0 + am.start(), a0 + am.end(), 0.95)
            found = "profile"
    # risk
    rn = RISK_NUM_RE.search(s)
    if rn and RISK_CTX_RE.search(s):
        st.profile.risk_tolerance = int(rn.group("n"))
        st.p("/profile/risk_tolerance", a0 + rn.start(), a0 + rn.end(), 0.95)
        found = found or "profile"
    elif RISK_CTX_RE.search(s) or (not money and len(s.split()) <= 4):
        for rx, v in RISK_WORDS:
            m = rx.search(s)
            if m and (RISK_CTX_RE.search(s) or len(s.split()) <= 3):
                st.profile.risk_tolerance = v
                st.p("/profile/risk_tolerance", a0 + m.start(), a0 + m.end(), 0.8)
                found = found or "profile"
                break
    # emergency fund
    if EF_RE.search(s):
        mm = re.search(rf"\b(?P<n>{NUM})\s+months?\b", s, re.I)
        if mm:
            n = parse_number(mm.group("n"))
            if n:
                st.ef_months = max(0.0, min(24.0, n[0]))
                st.p("/emergency_fund_months", a0 + mm.start(), a0 + mm.end(), 0.95)
        elif money:
            st.ef_amount = (money[0].high, a0 + money[0].start, a0 + money[0].end)
        return "ef"
    # retirement goal
    if RETIRE_RE.search(s) and not INCOME_RE.search(s.replace("retirement", "")):
        g = next((x for x in st.goals if x.kind == "retirement"), None)
        if g is None:
            g = DraftGoal(key=f"g{len(st.goals) + 1}", name="Retirement", kind="retirement", priority="must")
            st.goals.append(g)
            st.p(f"/goals/{g.key}/name", a0, c.end, 0.9)
        ra = RETIRE_AGE_RE.search(s)
        if ra:
            n = int(ra.group("n"))
            if 40 <= n <= 80:
                st.profile.retirement_age = n
                st.retire_age_span = (a0 + ra.start(), a0 + ra.end())
                st.p("/profile/retirement_age", a0 + ra.start(), a0 + ra.end(), 0.95)
        ri = RETIRE_IN_RE.search(s)
        if ri:
            n = parse_number(ri.group("n"))
            if n and 0 <= 12 * n[0] <= MAX_GOAL_MONTHS:
                g.target_month = add_months_str(_start_month(st.ctx), int(round(12 * n[0])))
                st.p(f"/goals/{g.key}/target_month", a0 + ri.start(), a0 + ri.end(), 0.95)
        if money:
            m = money[0]
            g.target = DraftAmount(low=m.low, high=m.high)
            st.p(f"/goals/{g.key}/target", a0 + m.start, a0 + m.end, _amount_conf(m))
        return "goal"
    if not money:
        if prev == "debt" and st.debts and _debt_terms(st, st.debts[-1], s, a0):
            return "debt"
        if found:
            return found
        if st.years_skipped:          # "Water can 2000": read as a year, which may be wrong, so say so
            a, b = st.years_skipped[0]
            st.note("YEAR_OR_AMOUNT", "info", note_text("YEAR_OR_AMOUNT", number=s[a:b], text=s[:120]),
                    a0 + a, a0 + b)
        return None
    # a one-off payment in the past ("I paid 50k for a fridge last month") is never income, a cost or a goal
    if all(m.frequency is None for m in money) and frequency_info_anywhere(s) is None and \
            PAST_ONE_OFF_RE.search(s) and not (FORWARD_GOAL_RE.search(s) or DEBT_RE.search(s)
                                              or HOLDING_RE.search(s) or PRODUCT_RE.search(s)) and \
            _future_month(st, s) is None:
        st.note("PAST_PURCHASE", "info", note_text("PAST_PURCHASE", text=s[:120]), a0, c.end)
        return "past"
    # gross pay / income
    paid_out = bool(PAID_TO_OTHERS_RE.search(s))
    if not paid_out and (GROSS_RE.search(s) or (INCOME_RE.search(s) and not DEBT_RE.search(s)) or (
            prev == "income" and not (DEBT_RE.search(s) or HOLDING_RE.search(s) or GOAL_RE.search(s)
                                      or EXPENSE_RE.search(s)))):
        gross = bool(GROSS_RE.search(s)) or any(m.lpa for m in money)
        m = money[0]
        low = s.lower()
        if PARTNER_RE.search(s):
            name, kind = "Partner's salary", "salary"
        elif "pension" in low:
            name, kind = "Pension", "pension"
        elif re.search(r"rent from|rental|tenant|rent income", low):
            name, kind = "Rental income", "rental"
        elif re.search(r"business|freelanc|consult", low):
            name, kind = "Business income", "business"
        else:
            name, kind = "Salary", "salary"
        if any(i.name == name for i in st.incomes):
            name = f"{name} {sum(1 for i in st.incomes if i.name.startswith(name)) + 1}"
        key = f"i{len(st.incomes) + 1}"
        m, freq = _with_frequency(m, s, m.lpa)
        inc = DraftIncome(key=key, name=name, kind=kind, amount=DraftAmount(low=m.low, high=m.high),  # type: ignore
                          frequency=freq or "monthly",  # type: ignore[arg-type]
                          interruptible=kind not in ("pension", "rental"))
        st.incomes.append(inc)
        conf = _amount_conf(m, freq is not None)
        st.p(f"/incomes/{key}/amount", a0 + m.start, a0 + m.end, conf, note="GROSS" if gross else "")
        _converted(st, m, f"/incomes/{key}/amount", a0)
        st.p(f"/incomes/{key}/name", a0, c.end, 0.9)
        if gross:
            st.note("GROSS_INCOME", "warning", note_text("GROSS_INCOME"), a0, c.end)
        return "income"
    # debt (a continuation clause of the same sentence adds to the previous debt)
    if DEBT_RE.search(s) or (prev == "debt" and not (HOLDING_RE.search(s) or GOAL_RE.search(s))):
        d = st.debts[-1] if (prev == "debt" and st.debts and not re.search(r"\bloan\b|\bmortgage\b|credit card", s,
                                                                             re.I)) else None
        if d is None:
            kind, name = "other", "Loan"
            for rx, k, nm in DEBT_KINDS:
                if rx.search(s):
                    kind, name = k, nm
                    break
            d = DraftDebt(key=f"d{len(st.debts) + 1}", name=name, kind=kind)  # type: ignore[arg-type]
            st.debts.append(d)
            st.p(f"/debts/{d.key}/name", a0, c.end, 0.9)
        work = s
        for m in money:
            amt = DraftAmount(low=m.low, high=m.high)
            before, after = work[max(0, m.amount_start - 60):m.amount_start], work[m.amount_end:m.amount_end + 60]
            if EMI_BEFORE_RE.search(before) or re.match(r"^\s*(?:emi|a month|per month|monthly)\b", after, re.I) \
                    or m.frequency == "monthly":
                d.emi = amt
                st.p(f"/debts/{d.key}/emi", a0 + m.start, a0 + m.end, _amount_conf(m))
            elif BALANCE_AFTER_RE.match(after) or BALANCE_BEFORE_RE.search(before) or d.balance is None:
                d.balance = amt
                end = m.end + (BALANCE_AFTER_RE.match(after).end() if BALANCE_AFTER_RE.match(after) else 0)
                st.p(f"/debts/{d.key}/balance", a0 + m.start, a0 + end, _amount_conf(m))
        _debt_terms(st, d, s, a0)
        return "debt"
    # holdings
    product_held = bool(PRODUCT_RE.search(s)) and all(m.frequency is None for m in money) and not (
        EXPENSE_RE.search(s) or DEBT_RE.search(s) or paid_out)
    if (HOLDING_RE.search(s) or product_held or (prev == "holding" and any(rx.search(s) for rx, _, _ in HOLDING_CLASS)
                                                 and not (EXPENSE_RE.search(s) or DEBT_RE.search(s)))) \
            and not GOAL_NOT_HOLDING_RE.search(s):
        for i, m in enumerate(money):
            seg_end = money[i + 1].start if i + 1 < len(money) else len(s)
            tail = s[m.end:seg_end]
            cls, name = None, ""
            for rx, cid, nm in HOLDING_CLASS:
                hm = rx.search(tail) or (rx.search(s[:m.start]) if len(money) == 1 else None)
                if hm:
                    cls = cid
                    name = nm or _cap(hm.group(0))
                    break
            key = f"h{len(st.holdings) + 1}"
            st.holdings.append(DraftHolding(key=key, name=(name or "Savings")[:200], asset_class_id=cls,
                                            amount=DraftAmount(low=m.low, high=m.high)))
            st.p(f"/holdings/{key}/amount", a0 + m.start, a0 + m.end, _amount_conf(m))
            st.p(f"/holdings/{key}/name", a0, c.end, 0.9)
            if cls:
                st.p(f"/holdings/{key}/asset_class_id", a0, c.end, 0.95 if name else 0.7)
        return "holding"
    # goals; also a cue-less amount with a goal noun or a date and no frequency ("Trip of 2 lakh in 2 years"),
    # where the noun or date may sit in another clause of the sentence ("Wedding of my daughter in 2035, 20 lakh").
    # A future date with no frequency makes even a spending phrase a goal ("We spend 10 lakh on a car in 2028").
    no_freq = all(m.frequency is None for m in money) and frequency_info_anywhere(s) is None
    no_cue = not EXPENSE_RE.search(s) and no_freq
    own_month = _future_month(st, s) if no_freq else None
    sg = _sent_goal(st, c) if no_freq else None
    sent_month = None
    goal_like = no_cue and (any(rx.search(s) for rx, _ in GOAL_KINDS) or bool(IN_YEARS_RE.search(s))
                            or bool(re.search(r"\b(?:in|by)\s+20\d{2}\b", s))
                            or any(d.kind in ("monyear", "dmy", "mdy", "iso", "numeric")
                                   for d in find_dates(s, st.ctx.today, st.ctx.locale)))
    if no_cue and not goal_like and sg is not None and (sg.kind or sg.month):
        goal_like = True
        sent_month = sg.month
    if no_freq and own_month is not None and not PAST_ONE_OFF_RE.search(s):
        goal_like = True
    if no_freq and PAST_ONE_OFF_RE.search(s) and not GOAL_RE.search(s) and own_month is None:
        st.note("PAST_PURCHASE", "info", note_text("PAST_PURCHASE", text=s[:120]), a0, c.end)
        return "past"
    # a recurring cost is not a goal because of a weak cue ("I pay 5k a month for the gym")
    recurring_cost = not no_freq and bool(EXPENSE_RE.search(s)) and not FORWARD_GOAL_RE.search(s)
    if (GOAL_RE.search(s) or prev == "goal" or goal_like) and not recurring_cost:
        m = money[0]
        kind = "other"
        for rx, k in GOAL_KINDS:
            if rx.search(s):
                kind = k
                break
        if kind == "other":       # "Wedding of my daughter when I'm 50, must have 20 lakh": kind from the sentence
            if c.sentence not in st.sent_kind:
                st.sent_kind[c.sentence] = next((k for rx, k in GOAL_KINDS if rx.search(c.sent_text)), "other")
            kind = st.sent_kind[c.sentence]

        nm = re.search(r"\bfor\s+(?:a|an|my|our|the)?\s*(?P<n>[a-z][^,.;]{1,60}?)(?=\s+(?:in|by|within|at|when|before|"
                       r"after|next|this)\b|[,.;]|$)", s, re.I)
        name = _cap(nm.group("n")) if nm else ""
        if not name:
            bm = re.search(r"\b(?:buy|save for|saving for|goal:?|target:?)\s+(?:a|an|my|our|the)?\s*"
                           r"(?P<n>[a-z][^,.;\d]{1,60}?)(?=\s+(?:in|by|for|of|worth|costing)\b|[,.;]|$)", s, re.I)
            name = _cap(bm.group("n")) if bm else {"home": "Home", "vehicle": "Car", "education": "Education",
                                                   "wedding": "Wedding", "travel": "Trip", "business": "Business",
                                                   "retirement": "Retirement"}.get(kind, "Goal")
        key = f"g{len(st.goals) + 1}"
        priority = None
        if MUST_RE.search(s):
            priority = "must"
        if NICE_RE.search(s):
            priority = "nice"
        if priority is None and kind in ("education",):
            priority = "must"
        g = DraftGoal(key=key, name=name[:200], kind=kind, target=DraftAmount(low=m.low, high=m.high),  # type: ignore
                      priority=priority)  # type: ignore[arg-type]
        st.goals.append(g)
        st.p(f"/goals/{key}/target", a0 + m.start, a0 + m.end, _amount_conf(m))
        st.p(f"/goals/{key}/name", a0, c.end, 0.9)
        if kind == "education":
            g.inflation_pct = 9.0
        iy = IN_YEARS_RE.search(s)
        dm = [d for d in find_dates(s, st.ctx.today, st.ctx.locale) if d.kind in ("monyear", "dmy", "mdy", "iso",
                                                                                     "numeric")]
        ag = AT_AGE_RE.search(s)
        ny = NEXT_YEAR_RE.search(s)
        if not (iy or dm or ag or ny):
            # the date may sit in another clause of the same sentence that has no money of its own
            if c.sentence not in st.sent_dates:      # computed once per sentence (linear time)
                st.sent_dates[c.sentence] = (AT_AGE_RE.search(c.sent_text), IN_YEARS_RE.search(c.sent_text))
            sag, siy = st.sent_dates[c.sentence]
            if siy:
                iy, a0 = siy, c.sent_start
            elif sag:
                ag, a0 = sag, c.sent_start
            elif sent_month is None and not re.search(r"\b(?:in|by)\s+20\d{2}\b", s):
                sent_month = _sent_goal(st, c).month
            if not (iy or ag) and sent_month is not None and not re.search(r"\b(?:in|by)\s+20\d{2}\b", s):
                g.target_month = sent_month[0]
                st.p(f"/goals/{key}/target_month", c.sent_start + sent_month[1], c.sent_start + sent_month[2],
                     sent_month[3])
                return "goal"
        if iy:
            n = parse_number(iy.group("n"))
            if n:
                months = int(round(n[0] * (12 if iy.group("u").lower().startswith("y") else 1)))
                if 0 <= months <= MAX_GOAL_MONTHS:
                    g.target_month = add_months_str(_start_month(st.ctx), months)
                    st.p(f"/goals/{key}/target_month", a0 + iy.start(), a0 + iy.end(), 0.95)
        elif dm:
            d = dm[0]
            g.target_month = f"{d.value.year:04d}-{d.value.month:02d}"
            st.p(f"/goals/{key}/target_month", a0 + d.start, a0 + d.end, d.confidence)
        elif ag:
            st.at_age[key] = (int(ag.group("n")), a0 + ag.start(), a0 + ag.end())
        elif ny:
            g.target_month = add_months_str(_start_month(st.ctx), 12)
            st.p(f"/goals/{key}/target_month", a0 + ny.start(), a0 + ny.end(), 0.8)
        else:
            ym = re.search(r"\b(?:in|by)\s+(?P<y>20\d{2})\b", s)
            if ym:
                g.target_month = f"{ym.group('y')}-{st.ctx.today.month:02d}"
                st.p(f"/goals/{key}/target_month", a0 + ym.start(), a0 + ym.end(), 0.8)
        return "goal"
    # expenses (also any other money phrase: its category is asked when unclear)
    if True:
        # per clause, not per amount (linear time): the category cue of the whole clause
        clause_cat = next(((cc, ess, inf) for rx, cc, ess, inf in EXPENSE_CATS if rx.search(s)), None)
        for i, m in enumerate(money):
            before = s[max(0, m.start - 200):m.start] if i == 0 else s[max(money[i - 1].end, m.start - 200):m.start]
            nxt = money[i + 1].start if i + 1 < len(money) else len(s)
            after = s[m.end:min(nxt, m.end + 200)]
            on = _ON_NAME_RE.match(after)
            if on:
                name = on.group("n")
            else:
                name = before
                for _ in range(3):
                    name = _EXP_NAME_TAIL_RE.sub("", name)
                name = _EXP_NAME_HEAD_RE.sub("", name.strip())
                name = re.sub(r"^(?:spend|pay|paying|spending)\s+", "", name, flags=re.I)
            name = clean_name(name, 80)
            words = [w for w in name.lower().split() if w not in STOP_WORDS]
            if not words:
                name = "Spending"
            cat, essential, infl = "other", None, None
            hit = next(((cc, ess, inf) for rx, cc, ess, inf in EXPENSE_CATS if rx.search(name)), None) or clause_cat
            if hit:
                cat, essential, infl = hit
            key = f"e{len(st.expenses) + 1}"
            m, freq = _with_frequency(m, after, False)
            e = DraftExpense(key=key, name=name[:200], category=cat, amount=DraftAmount(low=m.low, high=m.high),
                             frequency=freq or "monthly", essential=essential,  # type: ignore[arg-type]
                             inflation_pct=infl)
            st.expenses.append(e)
            # no spending cue and no frequency: only a guess, so it is asked (FIN_LOW_CONFIDENCE), never silent
            conf = 0.45 if (no_cue and freq is None) else _amount_conf(m, freq is not None)
            st.p(f"/expenses/{key}/amount", a0 + m.start, a0 + m.end, conf)
            _converted(st, m, f"/expenses/{key}/amount", a0)
            st.p(f"/expenses/{key}/name", a0, c.end, 0.9)
            if cat == "education":
                st.note("EDUCATION_INFLATION", "info", note_text("EDUCATION_INFLATION", name=name), a0, c.end)
        return "expense"
    return None  # pragma: no cover


def _with_frequency(m: MoneyMatch, s: str, lpa: bool) -> tuple[MoneyMatch, str | None]:
    """The amount's frequency: the phrase right after it, else the first one in `s` (converted phrases such as
    "a week" or "every 2 months" scale the amount to a supported frequency)."""
    if m.frequency:
        return m, m.frequency
    if lpa:
        return m, "yearly"
    fi = frequency_info_anywhere(s)
    if fi is None:
        return m, None
    if fi.factor != 1.0:
        m = replace(m, low=round(m.low * fi.factor, 2), high=round(m.high * fi.factor, 2), freq_factor=fi.factor,
                    freq_phrase=fi.phrase)
    return m, fi.frequency


def _converted(st: _State, m: MoneyMatch, path: str, a0: int) -> None:
    """Provenance note and info note when an amount was converted from a frequency the model has no member for."""
    if m.freq_factor == 1.0:
        return
    unit = "a year" if m.frequency == "yearly" else "a month"
    raw_low, raw_high = m.low / m.freq_factor, m.high / m.freq_factor
    raw = f"{raw_low:,.0f}" if round(raw_low) == round(raw_high) else f"{raw_low:,.0f}-{raw_high:,.0f}"
    amount = f"{m.low:,.0f}" if round(m.low) == round(m.high) else f"{m.low:,.0f}-{m.high:,.0f}"
    msg = note_text("FREQUENCY_CONVERTED", phrase=m.freq_phrase[:60], amount=amount, unit=unit, raw=raw)
    st.p(path, a0 + m.start, a0 + m.end, 0.8, "derived", msg[:300])
    st.note("FREQUENCY_CONVERTED", "info", msg, a0 + m.start, a0 + m.end)


def _debt_terms(st: _State, d: DraftDebt, s: str, a0: int) -> bool:
    """Rate (`at 9%`) and months left (`180 months left`) of a debt; True when something was read."""
    got = False
    for pm in find_percent(s):
        if 0 <= pm.value <= 60:
            d.interest_rate_pct = pm.value
            st.p(f"/debts/{d.key}/interest_rate_pct", a0 + pm.start, a0 + pm.end, 0.95)
            got = True
            break
    rm = REMAINING_RE.search(s)
    if rm:
        n = parse_number(rm.group("n"))
        if n:
            months = int(round(n[0] * (12 if rm.group("u").lower().startswith("y") else 1)))
            if 1 <= months <= 600:
                d.remaining_months = months
                st.p(f"/debts/{d.key}/remaining_months", a0 + rm.start(), a0 + rm.end(), 0.95)
                got = True
    return got
