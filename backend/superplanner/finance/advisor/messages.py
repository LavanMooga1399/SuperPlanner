"""Single catalog of every sentence the finance engine generates (FINANCE.md sections 12 and 21).

Every generated text is `render(code, **values)` of one of these templates; tests check compliance wording
on this catalog and that every sentence of a result matches one of its templates.
"""

from __future__ import annotations

import re

MESSAGES: dict[str, str] = {
    # growth-asset decision, always the first reason of a goal (PHASE2 1.10)
    "GROWTH_NONE_RESTRICTED": "{goal}: safer classes only, because you limited this goal to {names}.",
    "GROWTH_LIMITED_GLOBAL": "{goal}: about {share}% in growth assets, limited by your overall equity limit of {pct}% "
                             "(your risk level {level} of 5 would allow more).",
    "GROWTH_HIGH": "{goal}: about {share}% in growth assets ({names}) for now, because the goal is {years} away and "
                   "your risk level {level} of 5 allows up to {base}%. The share steps down from {glide_month} as the "
                   "goal gets closer.",
    "GROWTH_LIMITED_TIME": "{goal}: about {share}% in growth assets ({names}), because the goal is {years} away; at that "
                           "distance the plan allows at most {cap}% (your risk level {level} of 5 allows {base}% for "
                           "distant goals).",
    "GROWTH_NONE_SHORT": "{goal}: safer classes only, because the goal is {years} away; growth assets can fall sharply "
                         "over a few years; your risk level {level} of 5 matters for goals further away.",
    "GROWTH_NONE_RETURNS": "{goal}: safer classes only, because under your return assumptions growth assets do not beat "
                           "{safe} once the cautious margin is applied, even at your risk level {level} of 5.",
    "SAFE_RETURN": "{name} at {pct}% after inflation",
    # goal reasons (12.2)
    "ALLOCATION_SPLIT": "{goal}: {amount}/month from {start} to {end} - {mix}.",
    "ALLOCATION_NONE": "{goal}: no new monthly contributions are planned.",
    "MIX_PART": "{pct}% {name}",
    "RISK_CAP": "Growth assets are capped at {cap}%: your risk level {level} allows {base}% and the goal is {years} "
                "away.",
    "GLIDE_DOWN": "From {month} the plan moves {amount} from growth assets to safer classes as the goal gets closer "
                  "(cap {cap}%).",
    "LOCKIN_EXCLUDED": "{name} is not used: its {months}-month lock-in would end after {date}.",
    "EF_GATED": "Contributions start in {month}, after your emergency fund of {amount} is complete.",
    "CASH_LIMITED": "Your savings are fully used in {count} months before this goal ({first} to {last}).",
    "HOLDINGS_USED": "Uses {amount} of your existing {holding}.",
    "CAUTIOUS_RETURNS": "Planned with cautious returns: {name} {plan}% a year after inflation instead of the expected "
                        "{expected}%, so most outcomes beat the plan.",
    "SHORTFALL": "Even using all available cash, the plan reaches {value} of {target} (in today's money).",
    "LOW_PROBABILITY": "Estimated chance of reaching the target on time: {prob}% (you asked for at least {min}%).",
    "ON_TRACK": "On track: estimated {prob}% chance; in a weak market (low scenario) {low}.",
    # summary
    "SUMMARY_FEASIBLE": "The plan is valid: every hard rule holds. {on_track} of {total} goals are on track.",
    "SUMMARY_INFEASIBLE": "Planned spending is higher than the available cash in some months, even after using your "
                          "savings and investments; the plan below is shown for reference.",
    "SUMMARY_UNKNOWN": "The plan could not be fully checked; treat the numbers with care.",
    "SUMMARY_INVEST": "You can invest about {investable}/month now; the plan allocates {contributing}/month.",
    "SUMMARY_SURPLUS": "In the first year you have about {surplus}/month left after expenses and loans.",
    "SUMMARY_SURPLUS_EF": "In the first year you have about {surplus}/month left after expenses and loans; about "
                          "{ef}/month of it first builds your emergency fund.",
    "SUMMARY_SURPLUS_NEGATIVE": "In the first year your spending and loan payments are about {amount}/month more than "
                                "your income.",
    "SUMMARY_FUNDING": "The plan invests about {contributing}/month on average in the first year: {from_surplus} from "
                       "your monthly surplus and {from_savings} from savings you already have.",
    "SUMMARY_FUNDING_SURPLUS": "The plan invests about {contributing}/month on average in the first year, all from "
                               "your monthly surplus.",
    "SUMMARY_FUNDING_NONE": "The plan needs no new monthly investments in the first year.",
    "SUMMARY_EF": "Your emergency fund target is {target}; it is complete in {month}.",
    "SUMMARY_EF_DONE": "Your emergency fund of {target} is already complete.",
    "SUMMARY_EF_NEVER": "Your emergency fund of {target} is not complete within the plan horizon.",
    "SUMMARY_EF_NONE": "No emergency fund is planned.",
    "SUMMARY_TOP_RISK": "Main risk: {goal} has an estimated {prob}% chance of reaching its target on time.",
    "SUMMARY_LIQUIDITY": "In {prob}% of simulated outcomes there is at least one month without enough cash.",
    "SUMMARY_NO_GOALS": "No goals are entered; the plan shows your cash flow and emergency fund.",
    # binding constraints
    "CASH_DEFICIT": "Spending exceeds the available cash by a total of {amount} in {count} months ({first} to "
                    "{last}).",
    "CASH_FULLY_USED": "All free cash is used in {count} months ({first} to {last}).",
    "EF_BUILD": "From {first} to {last} your surplus first builds the emergency fund.",
    "EQUITY_CAP": "The overall equity limit of {pct}% is reached in {count} block(s).",
    "CLASS_CAP": "The limit of {pct}% for {name} is reached in {count} block(s).",
    "DEBT_PAYOFF": "{debt} is paid off in {month}, which frees about {amount}/month.",
    "SHARED_SHORTFALL": "{count} {tier} goals are each short by about {pct}% because the plan spreads an unavoidable "
                        "shortfall fairly across them; to fund one fully, lower the priority of another.",
    # assumptions
    "ASSUMPTION_INFLATION": "Inflation is assumed at {pct}% a year (your assumption).",
    "ASSUMPTION_CLASS": "{name}: assumed {expected}% a year before costs and inflation, {real}% after (your "
                        "assumption).",
    "ASSUMPTION_CAUTIOUS": "{goal} is planned with cautious returns, for example {name} at {plan}% after inflation.",
    "ASSUMPTION_SOURCE": "Source of assumptions: {note}",
    "ASSUMPTION_RANGE": "{item}: you gave a range of {low} to {high}; the plan uses {used}.",
    # limitations (fixed)
    "LIMIT_TAX": "No taxes are calculated; incomes are take-home amounts.",
    "LIMIT_PRODUCTS": "The plan uses asset classes only and does not recommend specific products.",
    "LIMIT_RETURNS": "Returns and inflation are assumptions; actual results can be lower or higher.",
    "LIMIT_RETIREMENT": "Retirement is modelled as a corpus at the retirement month; spending after retirement is not "
                        "modelled.",
    "LIMIT_BUCKETS": "Each goal is paid only from its own bucket of investments.",
    # re-planning triggers
    "TRIGGER_INCOME": "Your income changes by more than 10%.",
    "TRIGGER_DEBT": "You take on a new debt.",
    "TRIGGER_GOAL": "A goal changes (amount, date or priority).",
    "TRIGGER_YEAR": "12 months have passed since the plan start ({month}).",
    "TRIGGER_AT_RISK": "{goal} turns at risk or off track.",
    "TRIGGER_DEBT_PAYOFF": "{debt} is paid off ({month}).",
    # fixes (12.3)
    "FIX_DELAY_FLEX": "Move {goal} to {month} ({months} months later); this is within the flexibility you allowed.",
    "FIX_DELAY": "Move {goal} to {month} ({months} months later); this is more than the {flex} months of flexibility "
                 "you allowed.",
    "FIX_SAVE_MORE": "Save {amount}/month more (in today's money) to fund {goal} under the cautious plan.",
    "FIX_SPEND_LESS": "Spend {amount}/month less on non-essential items to fund {goal}.",
    "FIX_RISK": "Allow a higher risk level for {goal} ({old} to {new}); the plan can then hold more growth assets.",
    "FIX_REDUCE": "Lower the target of {goal} by {amount} (in today's money) to {new}.",
    "FIX_EF_SHARE": "Build the emergency fund with {pct}% of your surplus instead of {old}% so more cash reaches "
                    "{goal} early.",
    # what-if labels (13)
    "LABEL_EXTRA": "{sign}{amount}/month",
    "LABEL_GOAL_MONTH": "{goal} {month}",
    "LABEL_GOAL_AMOUNT": "{goal} target {amount}",
    "LABEL_GOAL_OFF": "without {goal}",
    "LABEL_GOAL_PRIORITY": "{goal} {priority}",
    "LABEL_GOAL_RISK": "{goal} risk {level}",
    "LABEL_RISK": "risk {level}",
    "LABEL_RETURNS": "returns {sign}{pct}pp",
    "LABEL_INFLATION": "inflation {pct}%",
    "LABEL_INCOME_DROP": "income -{pct}% for {months} months",
    "LABEL_EF_SHARE": "emergency fund share {pct}%",
    "LABEL_DEFAULT": "What-if",
}

FORBIDDEN_WORDS = ("guarantee", "guaranteed", "assured", "risk-free", "sure", "will earn", "will grow to",
                   "you should buy")


def render(code: str, **values: object) -> str:
    return MESSAGES[code].format(**values)


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{[a-z_]+\}", template)
    return re.compile("^" + "(.+?)".join(re.escape(p) for p in parts) + "$", re.S)


_PATTERNS = {code: _pattern(t) for code, t in MESSAGES.items()}


def matching_codes(text: str) -> list[str]:
    """Catalog codes whose template matches `text` (placeholders match any non-empty text)."""
    return [c for c, p in _PATTERNS.items() if p.match(text)]


def contains_forbidden(text: str) -> list[str]:
    low = text.lower()
    return [w for w in FORBIDDEN_WORDS if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)]


_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _group_indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def format_money(amount: float, currency: str = "INR") -> str:
    """`₹1,20,000` for INR (lakh/crore grouping), `$120,000` style elsewhere; whole currency units."""
    n = int(round(abs(amount)))
    sign = "-" if amount < 0 and n != 0 else ""
    if currency == "INR":
        body = _group_indian(n)
    else:
        body = f"{n:,}"
    sym = _SYMBOLS.get(currency)
    return f"{sign}{sym}{body}" if sym else f"{sign}{currency} {body}"


def pct(v: float, digits: int = 0) -> str:
    """A percentage number without the % sign (0.62 -> "62")."""
    s = f"{v * 100:.{digits}f}"
    return "0" if s in ("-0", "-0.0") else s


def duration_text(months: int) -> str:
    """"25 years", "3 years 6 months", "1 year", "8 months" (PHASE2 1.10)."""
    months = max(0, int(months))
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} year" + ("s" if y != 1 else ""))
    if m or not y:
        parts.append(f"{m} month" + ("s" if m != 1 else ""))
    return " ".join(parts)


def years_text(months: int) -> str:
    if months < 12:
        return f"{months} months"
    y = months / 12
    return f"{y:.0f} years" if abs(y - round(y)) < 0.05 else f"{y:.1f} years"
