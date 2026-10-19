"""Single catalog of user-facing intake text (PHASE2 2.7.10, 2.8, 2.10, 2.12).

No product names live here (the finance denylist and FORBIDDEN_WORDS checks run over this file).
"""

from __future__ import annotations

MODEL = "claude-opus-5-5"
PROVIDER = "Anthropic"

PRIVACY_NOTICE = ("AI assist sends the text in this box to Anthropic, an AI provider, to turn it into a draft. "
                  "Nothing else from your plans is sent. Do not include account numbers, ID numbers, passwords or "
                  "anything you do not want to share. Without AI assist your text is read only on this server.")

_FALLBACK_SUFFIX = " We used the built-in reader instead."

FALLBACK_PREFIX: dict[str, str] = {
    "AI_DISABLED": "AI assist is turned off on this server.",
    "AI_SDK_MISSING": "AI assist is not installed on this server.",
    "AI_NO_CREDENTIALS": "AI assist is not set up on this server (no credentials).",
    "AI_RATE_LIMITED": "AI assist is busy right now (rate limit); try again in a minute.",
    "AI_AUTH_FAILED": "AI assist is not set up correctly (the credentials were rejected).",
    "AI_API_ERROR": "AI assist returned an error (status {status}).",
    "AI_CONNECTION_ERROR": "AI assist could not be reached.",
    "AI_REFUSED": "AI assist declined to process this text.",
    "AI_TRUNCATED": "The answer from AI assist was cut off; try a shorter description.",
    "AI_NO_TEXT": "AI assist returned something we could not use.",
    "AI_BAD_JSON": "AI assist returned something we could not use.",
    "AI_SCHEMA_MISMATCH": "AI assist returned something we could not use.",
    "AI_BUSY": "AI assist is handling other requests.",
    "AI_UNEXPECTED": "AI assist failed unexpectedly.",
}
FALLBACK_CODES = tuple(FALLBACK_PREFIX)


def fallback_message(code: str, **values: object) -> str:
    prefix = FALLBACK_PREFIX[code]
    if "{status}" in prefix:
        prefix = prefix.format(status=values.get("status", "unknown"))
    return prefix + _FALLBACK_SUFFIX


# ---------------------------------------------------------------- notes

NOTES: dict[str, str] = {
    "UNSUPPORTED_RULE": "I could not turn this into a plan rule: \"{text}\". Add it by hand after creating the plan, "
                        "or rephrase it.",
    "MIXED_CURRENCY": "The text mentions a currency other than {currency}, or more than one currency; all amounts "
                      "are read as {currency} without conversion.",
    "FREQUENCY_CONVERTED": "\"{raw} {phrase}\" was counted as about {amount} {unit}.",
    "EXPANDED_COUNT": "\"{text}\" became {count} separate items; you can rename or remove them.",
    "MONTHS_AS_WEEKS": "A month was counted as about 4.33 weeks.",
    "PARALLEL": "\"{text}\" can happen at the same time as other work, so no order was added.",
    "GROSS_INCOME": "Pay before tax was mentioned. Taxes are not modelled, so enter the amount you take home.",
    "EDUCATION_INFLATION": "{name} are assumed to rise 9% a year; you can change this.",
    "DEBT_EMI_DERIVED": "The monthly payment of {name} was worked out from the balance, rate and months left.",
    "KEPT_TYPED_NUMBER": "AI assist read {a}; we kept the {r} you typed.",
    "AI_REFERENCE_DROPPED": "AI assist linked \"{name}\" to something that is not in the draft, so that link was left out.",
    "AI_NOTE": "{text}",
    "TABLE_ROW": "Row {n}: {text}",
    "DATE_OUT_OF_RANGE": "\"{text}\" is too far from today to plan with, so this date was left out.",
    "TABLE_MORE_NOTES": "{n} more row problems are not listed; check the imported rows.",
}


def note_text(code: str, **values: object) -> str:
    return NOTES[code].format(**values)


# ---------------------------------------------------------------- question prompts (2.8)

PROMPTS: dict[str, str] = {
    "SCHED_NO_TASKS": "What needs to be done? List the tasks, one per line.",
    "SCHED_TASK_DURATION": "How long will \"{task}\" take? A range like \"2-3 days\" is fine.",
    "SCHED_DEP_REFERENCE": "\"{task}\" comes after \"{ref}\". Which item did you mean?",
    "SCHED_DATE_AMBIGUOUS": "Which date did you mean by \"{text}\"?",
    "SCHED_START_DATE": "When should the plan start?",
    "SCHED_SEQUENTIAL": "Should the numbered steps happen one after another?",
    "SCHED_PEOPLE": "Are {names} the people doing the work?",
    "SCHED_WHO": "Who does \"{task}\"?",
    "SCHED_WORKING_TIME": "When does the team work?",
    "SCHED_LOW_CONFIDENCE": "Is this right: \"{text}\"?",
    "FIN_INCOME": "How much do you take home each month, after tax?",
    "FIN_TAKE_HOME": "How much of \"{name}\" do you take home each month, after tax?",
    "FIN_GOAL_TARGET": "How much do you need for \"{name}\", in today's money?",
    "FIN_GOAL_DATE": "When do you need the money for \"{name}\"?",
    "FIN_AGE": "How old are you?",
    "FIN_RETIREMENT_TARGET": "For retirement we suggest saving {amount} (25 years of your regular spending, in today's "
                             "money). Keep it or enter your own amount.",
    "FIN_ESSENTIALS": "About how much do you spend each month on essentials such as housing, food and bills?",
    "FIN_DISCRETIONARY": "Anything else you spend each month, such as eating out, shopping or trips?",
    "FIN_EXPENSE_ESSENTIAL": "Is \"{name}\" an essential cost?",
    "FIN_DEBT_BALANCE": "How much is still owed on \"{name}\"?",
    "FIN_DEBT_EMI": "What is the monthly payment for \"{name}\"?",
    "FIN_DEBT_RATE": "What interest rate does \"{name}\" charge, per year?",
    "FIN_HOLDING_CLASS": "What kind of savings is \"{name}\"?",
    "FIN_HOLDING_LOCK": "Until when is \"{name}\" locked in?",
    "FIN_GOAL_PRIORITY": "How important is \"{name}\"?",
    "FIN_RISK": "How much ups and downs in value can you live with?",
    "FIN_EF_MONTHS": "How many months of essential costs should your emergency fund cover?",
    "FIN_LOW_CONFIDENCE": "Is this right: \"{text}\"?",
    "FIN_AI_UNQUOTED": "The assistant added {value} for \"{name}\", but this is not in your text. Keep it? "
                       "Choose No to remove the amount.",
    "SCHED_AI_UNQUOTED": "The assistant suggested {value} for \"{name}\", but this is not in your text. Keep it? "
                         "Choose No to enter the duration yourself.",
}

QUESTION_ERRORS: dict[str, str] = {
    "UNPARSED": "We could not read that answer. Please try again, for example {example}.",
    "OUT_OF_RANGE": "That value is outside the allowed range.",
    "BAD_OPTION": "Please choose one of the options.",
}

EXAMPLES: dict[str, str] = {
    "number": "\"6\"", "money": "\"40-50k\"", "percent": "\"9%\"", "duration": "\"2-3 days\"",
    "date": "\"2026-11-02\"", "month": "\"March 2027\"", "choice": "one of the options",
    "multi_choice": "one or more options", "text": "a short text", "confirm": "yes or no",
    "people": "\"Ravi, Priya\"", "working_time": "\"Mon-Fri 09:00-17:00\"",
}

PRIORITY_LABELS = {"must": "Must have", "should": "Should have", "nice": "Nice to have"}
RISK_LABELS = {1: "1 - very low", 2: "2 - low", 3: "3 - medium", 4: "4 - high", 5: "5 - very high"}
HOLDING_CLASS_LABELS = {
    "cash": "Cash or savings account", "fixed_deposit": "Fixed deposit", "short_debt": "Short-term debt fund",
    "govt_long": "Government long lock-in savings", "equity_index": "Equity fund or shares", "gold": "Gold",
}


def prompt(code: str, **values: object) -> str:
    return PROMPTS[code].format(**values)


def join_names(names: list[str], word: str = "and") -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" {word} " + names[-1]


def all_texts() -> list[str]:
    """Every user-facing string of this catalog (compliance tests)."""
    return [PRIVACY_NOTICE, *FALLBACK_PREFIX.values(), *NOTES.values(), *PROMPTS.values(), *QUESTION_ERRORS.values(),
            *PRIORITY_LABELS.values(), *RISK_LABELS.values(), *HOLDING_CLASS_LABELS.values()]
