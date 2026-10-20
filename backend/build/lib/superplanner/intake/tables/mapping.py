"""Header synonyms and column suggestions (PHASE2 2.13)."""

from __future__ import annotations

import re
from datetime import date

from ..models import Domain
from ..text.dates import find_dates
from ..text.durations import find_durations
from ..text.numbers import find_money

SCHEDULE_FIELDS: dict[str, list[str]] = {
    "id": ["id", "#", "no", "number", "key", "wbs"],
    "name": ["task", "name", "activity", "item", "title", "step", "operation", "description"],
    "duration": ["duration", "time", "effort", "estimate", "length", "est", "hours", "days"],
    "optimistic": ["optimistic", "min", "best case"],
    "likely": ["likely", "most likely", "expected"],
    "pessimistic": ["pessimistic", "max", "worst case"],
    "predecessors": ["predecessors", "depends on", "dependencies", "after", "prereqs", "requires", "predecessor",
                     "depends"],
    "resources": ["resources", "assignee", "owner", "who", "person", "machine", "team", "resource"],
    "deadline": ["deadline", "due", "due date", "finish by", "end date"],
    "earliest_start": ["start", "start date", "earliest start", "not before"],
    "priority": ["priority", "importance"],
    "group": ["group", "phase", "workstream", "job", "subject", "category"],
    "notes": ["notes", "comments", "note", "comment"],
}
FINANCE_FIELDS: dict[str, list[str]] = {
    "row_kind": ["type", "kind", "row type"],
    "name": ["name", "item", "description", "title", "what", "particulars"],
    "amount": ["amount", "value", "monthly", "rs", "inr", "₹", "cost", "target"],
    "frequency": ["frequency", "how often", "period", "per"],
    "category": ["category", "group"],
    "essential": ["essential", "need", "must"],
    "date": ["date", "when", "by", "target date", "year"],
    "priority": ["priority", "importance"],
    "asset_class": ["asset", "held in", "account type", "asset class"],
    "interest_rate": ["interest rate", "rate", "interest", "roi"],
    "emi": ["emi", "installment", "instalment", "monthly payment"],
    "balance": ["balance", "outstanding", "principal"],
}


def fields_of(domain: Domain) -> dict[str, list[str]]:
    return SCHEDULE_FIELDS if domain == "schedule" else FINANCE_FIELDS


def norm_header(h: str) -> str:
    h = h.lower().strip()
    h = re.sub(r"[^a-z0-9#₹ ]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def header_field(header: str | None, domain: Domain) -> tuple[str | None, float]:
    if not header:
        return None, 0.0
    h = norm_header(header)
    if not h:
        return None, 0.0
    best: tuple[str | None, float] = (None, 0.0)
    for f, syns in fields_of(domain).items():
        for i, s in enumerate(syns):
            if h == s:
                c = 0.95 if (i == 0 or s == f.replace("_", " ")) else 0.9
                if c > best[1]:
                    best = (f, c)
    if best[0] is not None:
        return best
    toks = set(h.split())
    for f, syns in fields_of(domain).items():
        for s in syns:
            if " " not in s and s in toks and len(s) > 2:
                return f, 0.6
    return None, 0.0


def _share(values: list[str], test) -> float:
    vals = [v for v in values if v.strip()]
    if not vals:
        return 0.0
    return sum(1 for v in vals if test(v)) / len(vals)


def suggest(headers: list[str | None], rows: list[list[str]], domain: Domain, today: date) \
        -> list[tuple[str | None, float]]:
    n = len(headers)
    out: list[tuple[str | None, float]] = [header_field(h, domain) for h in headers]
    # each field once: keep the most confident (first on ties)
    taken: dict[str, int] = {}
    for j, (f, c) in enumerate(out):
        if f is None:
            continue
        if f in taken and out[taken[f]][1] >= c:
            out[j] = (None, 0.0)
        else:
            if f in taken:
                out[taken[f]] = (None, 0.0)
            taken[f] = j
    if all(h is None for h in headers):
        sample = rows[:20]
        cols = [[r[j] for r in sample] for j in range(n)]
        used: set[str] = set()
        for j, col in enumerate(cols):
            if "duration" not in used and domain == "schedule" and _share(col, lambda v: bool(find_durations(v))) >= 0.6:
                out[j] = ("duration", 0.6)
                used.add("duration")
            elif ("deadline" if domain == "schedule" else "date") not in used and \
                    _share(col, lambda v: bool(find_dates(v, today))) >= 0.6:
                fld = "deadline" if domain == "schedule" else "date"
                out[j] = (fld, 0.6)
                used.add(fld)
            elif domain == "finance" and "amount" not in used and \
                    _share(col, lambda v: bool(find_money(v, min_bare=0.0))) >= 0.6:
                out[j] = ("amount", 0.6)
                used.add("amount")
        text_cols = [j for j in range(n) if out[j][0] is None]
        if text_cols:
            j = max(text_cols, key=lambda k: (sum(len(x) for x in cols[k]), -k))
            if any(x.strip() for x in cols[j]):
                out[j] = ("name", 0.6)
    return out
