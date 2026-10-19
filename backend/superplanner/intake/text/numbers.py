"""Numbers, money, percent, frequency and ranges (PHASE2 2.7.2). All patterns are linear-time."""

from __future__ import annotations

import re
from dataclasses import dataclass

WORD_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
              "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
              "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}
WORD_TENS = {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SMALL = "one|two|three|four|five|six|seven|eight|nine"
_UNITS_ALT = "|".join(sorted(WORD_UNITS, key=len, reverse=True))
_TENS_ALT = "|".join(WORD_TENS)

# A number written with digits or words (bounded: at most two words).
WORD_NUM = rf"(?:(?:twenty|{_TENS_ALT})(?:[- ](?:{_SMALL}))?|{_UNITS_ALT}|hundred|dozen|a couple of|a few|half|an?)"
# Linear time: a number never starts right after a digit or comma, and the group repetitions are possessive, so
# a failed attempt never rescans ("1,21,21,..." or "111..." of 20,000 characters stay fast).
DIGITS = r"(?<![\d,])(?:\d{1,3}(?:,\d{3}(?!\d))++|\d{1,2}(?:,\d{2}(?=,\d))*+,\d{3}(?!\d)|\d++)(?:\.\d++)?(?!\d)"
NUM = rf"(?:{DIGITS}|\b{WORD_NUM}\b)"


def parse_number(token: str) -> tuple[float, float] | None:
    """(value, confidence) of a digit or word number; None if not a number."""
    s = token.strip().lower()
    if not s:
        return None
    if s[0].isdigit():
        try:
            return float(s.replace(",", "")), 0.95
        except ValueError:
            return None
    if s in ("a", "an"):
        return 1.0, 0.95
    if s == "half":
        return 0.5, 0.95
    if s == "a couple of":
        return 2.0, 0.6
    if s == "a few":
        return 3.0, 0.4
    if s == "dozen":
        return 12.0, 0.95
    if s == "hundred":
        return 100.0, 0.95
    if s in WORD_UNITS:
        return float(WORD_UNITS[s]), 0.95
    parts = re.split(r"[- ]", s)
    if parts[0] in WORD_TENS or parts[0] == "twenty":
        v = WORD_TENS.get(parts[0], 20)
        if len(parts) == 2 and parts[1] in WORD_UNITS:
            v += WORD_UNITS[parts[1]]
        return float(v), 0.95
    return None


# ---------------------------------------------------------------- money

MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "lk": 1e5,
               "lpa": 1e5, "cr": 1e7, "crore": 1e7, "crores": 1e7, "m": 1e6, "mn": 1e6, "million": 1e6,
               "b": 1e9, "bn": 1e9, "billion": 1e9}
_MULT_ALT = "|".join(sorted(MULTIPLIERS, key=len, reverse=True))
CURRENCY_WORDS = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupee": "INR", "rupees": "INR",
                  "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "€": "EUR", "eur": "EUR",
                  "euro": "EUR", "euros": "EUR", "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
                  "quid": "GBP", "sterling": "GBP", "¥": "JPY", "jpy": "JPY", "yen": "JPY", "aed": "AED",
                  "dirham": "AED", "dirhams": "AED", "sgd": "SGD", "aud": "AUD", "cad": "CAD", "chf": "CHF",
                  "francs": "CHF", "franc": "CHF"}
_CUR_PRE = r"₹|\$|€|£|¥|\brs\.?|\binr|\busd|\beur|\bgbp|\bjpy|\baed|\bsgd|\baud|\bcad|\bchf"
_CUR_SUF = (r"rupees?|inr|usd|eur|gbp|jpy|aed|sgd|aud|cad|chf|dollars?|euros?|pounds?(?:\s+sterling)?|sterling|quid|"
            r"yen|dirhams?|francs?")

_ATOM_RE = re.compile(
    rf"(?:(?P<pre>{_CUR_PRE})\s?|(?<![\w.,]))(?P<num>{DIGITS})"
    rf"(?:\s?(?P<mult>{_MULT_ALT})\b)?(?:\s?(?P<suf>{_CUR_SUF})\b|\s?(?P<sufsym>₹|\$|€|£|¥))?",
    re.IGNORECASE)
# a year-like number right after a money word ("Rent 2000", "fee of 1999") is read as money and asked
_MONEY_BEFORE_RE = re.compile(r"\b(?:rent|fees?|costs?|spend|spends|pay|pays|paid|salary|earn|earns|bills?|emi|"
                              r"groceries|price|budget|amount|insurance|premium|allowance|expenses?|maintenance|"
                              r"charges?|donations?|subscriptions?|tuition|electricity|petrol|fuel|recharge|dues|"
                              r"contribution|wages?)\s*(?:is|are|of|=|:)?\s*(?:about|around|approx\.?|roughly|nearly)?"
                              r"\s*$", re.I)
# a year-like number (1900-2100) right after one of these words is a year ("in 2035", "since 2019")
_YEAR_BEFORE_RE = re.compile(r"\b(?:in|by|of|since|from|until|till|before|after|year|during|around the year|born|"
                             r"batch|graduated|joined|married|"
                             r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|"
                             r"july|august|september|october|november|december)\s*,?\s*$", re.I)
_APPROX_RE = re.compile(r"(?:\b(?:about|around|approx(?:imately)?\.?|roughly|nearly|almost|some)|~)\s*$", re.I)
_RANGE_SEP_RE = re.compile(r"^\s*(?:-|to)\s*$", re.I)
_BETWEEN_RE = re.compile(r"\bbetween\s*$", re.I)
_AND_RE = re.compile(r"^\s*and\s*$", re.I)
_NON_MONEY_UNIT_RE = re.compile(
    r"^\s*(?:%|percent\b|pc\b|years?\b|yrs?\b|months?\b|mos?\b|weeks?\b|days?\b|hours?\b|hrs?\b|minutes?\b|mins?\b|"
    r"times\b|people\b|persons?\b|kids?\b|children\b|members?\b|x\b|th\b|st\b|nd\b|rd\b|am\b|:\d)", re.I)

_NON_MONEY_UNIT_AT_RE = re.compile(_NON_MONEY_UNIT_RE.pattern[1:], re.I)   # same, for match(s, pos)
_LOOKBACK = 40   # "between" / "about" are looked for only this far back (keeps find_money linear)

FREQ_PATTERNS: list[tuple[str, str]] = [
    ("half_yearly", r"half[- ]yearly|half[- ]annually|every (?:6|six) months|twice a year|semi[- ]annually"),
    ("quarterly", r"per quarter|a quarter|quarterly|every quarter|each quarter|every (?:3|three) months"),
    ("monthly", r"per month|a month|each month|every month|monthly|/\s?month|/\s?mo\b|\bpm\b|p\.m\.|per mon\b|"
                r"in a month|month on month"),
    ("yearly", r"per year|a year|annually|yearly|per annum|p\.a\.?|/\s?yr\b|/\s?year|every year|each year|annual\b|"
               r"\bpa\b"),
    ("once", r"one[- ]time|one[- ]off|lump ?sum|\bonce\b"),
]
# Frequencies the finance model has no member for (fix round): converted to a supported one with a factor.
_EVERY_NUM = r"\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|other"
FREQ_CONVERTED: list[tuple[str, str]] = [
    ("every_n_weeks", rf"every\s+(?P<nw>{_EVERY_NUM})\s+weeks?\b"),
    ("every_n_months", rf"every\s+(?P<nm>{_EVERY_NUM})\s+months?\b"),
    ("every_n_years", rf"every\s+(?P<ny>{_EVERY_NUM})\s+years?\b"),
    ("weekly", r"(?:per week|a week|each week|every week|weekly|/\s?week|/\s?wk|per wk|a wk)\b"),
    ("fortnightly", r"(?:fortnightly|every fortnight|a fortnight|per fortnight|bi-?weekly)\b"),
    ("daily", r"(?:per day|a day|each day|every day|daily|/\s?day)\b"),
]
_FREQ_ALT = "|".join(f"(?P<{k}>{p})" for k, p in FREQ_PATTERNS + FREQ_CONVERTED)
_FREQ_ADJ_RE = re.compile(rf"\s*(?:{_FREQ_ALT})", re.I)   # used with match(s, pos)
_FREQ_ANY_RE = re.compile(rf"(?:{_FREQ_ALT})", re.I)
_EVERY_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "other": 2}


@dataclass(frozen=True)
class FreqInfo:
    """A frequency phrase: the supported `frequency`, the factor applied to the amount and the phrase itself
    (factor != 1 means the amount was converted, e.g. 5000 a week -> 5000 * 52 / 12 a month)."""

    frequency: str
    factor: float
    phrase: str


def _every_n(token: str) -> int:
    t = token.lower()
    return int(t) if t.isdigit() else _EVERY_WORDS.get(t, 1)


def _freq_info(m: re.Match[str]) -> FreqInfo | None:
    phrase = m.group(0).strip()
    for k, _ in FREQ_PATTERNS:
        if m.group(k):
            return FreqInfo(k, 1.0, phrase)
    if m.group("weekly"):
        return FreqInfo("monthly", 52 / 12, phrase)
    if m.group("fortnightly"):
        return FreqInfo("monthly", 26 / 12, phrase)
    if m.group("daily"):
        return FreqInfo("monthly", 365 / 12, phrase)
    if m.group("every_n_weeks"):
        n = max(1, _every_n(m.group("nw")))
        return FreqInfo("monthly", 52 / (12 * n), phrase)
    if m.group("every_n_months"):
        n = max(1, _every_n(m.group("nm")))
        named = {1: "monthly", 3: "quarterly", 6: "half_yearly", 12: "yearly"}
        if n in named:
            return FreqInfo(named[n], 1.0, phrase)
        return FreqInfo("monthly", 1 / n, phrase)
    if m.group("every_n_years"):
        n = max(1, _every_n(m.group("ny")))
        return FreqInfo("yearly", 1 / n, phrase)
    return None  # pragma: no cover


def frequency_info_at(s: str, pos: int) -> tuple[FreqInfo, int] | None:
    m = _FREQ_ADJ_RE.match(s, pos)
    if not m:
        return None
    fi = _freq_info(m)
    return (fi, m.end()) if fi else None


def frequency_info_anywhere(s: str) -> FreqInfo | None:
    m = _FREQ_ANY_RE.search(s)
    return _freq_info(m) if m else None


@dataclass
class MoneyMatch:
    start: int          # local offsets in the searched string (span incl. approx word and frequency)
    end: int
    low: float
    high: float
    currency: str | None
    approx: bool
    frequency: str | None
    explicit: bool      # had a currency marker or multiplier
    amount_start: int   # start of the number itself (without approx word)
    amount_end: int     # end of the amount (without the frequency)
    lpa: bool = False
    freq_factor: float = 1.0     # != 1: low/high were converted from `freq_phrase` (e.g. weekly -> monthly)
    freq_phrase: str = ""
    year_like: bool = False      # a bare 1900-2100 number read as money: asked, since it could be a year

    @property
    def confidence(self) -> float:
        if self.year_like:
            return 0.45
        if self.approx:
            return 0.8
        return 0.95 if self.explicit else 0.7


def _atom_value(m: re.Match[str]) -> float:
    v = float(m.group("num").replace(",", ""))
    mult = m.group("mult")
    return round(v * MULTIPLIERS[mult.lower()], 6) if mult else v


def _atom_currency(m: re.Match[str]) -> str | None:
    for g in ("pre", "suf", "sufsym"):
        c = m.group(g)
        if c:
            low = c.lower().split()[0]
            return CURRENCY_WORDS.get(low.rstrip("."), CURRENCY_WORDS.get(low))
    return None


def frequency_at(s: str, pos: int) -> tuple[str, int] | None:
    """Frequency phrase starting at `pos` (after optional spaces): (frequency, end). Converted phrases (weekly,
    every N months, ...) are reported with their target frequency; use `frequency_info_at` for the factor."""
    r = frequency_info_at(s, pos)
    return (r[0].frequency, r[1]) if r else None


def frequency_anywhere(s: str) -> str | None:
    fi = frequency_info_anywhere(s)
    return fi.frequency if fi and fi.factor == 1.0 else None


def find_money(s: str, *, min_bare: float = 100.0,
               years_skipped: list[tuple[int, int]] | None = None) -> list[MoneyMatch]:
    """Money expressions (single amounts and ranges) in `s`, left to right. `years_skipped`, when given, receives
    the spans of bare 1900-2100 numbers read as years only because nothing marked them as money."""
    atoms = list(_ATOM_RE.finditer(s))
    freq_any: bool | None = None      # a frequency anywhere in `s`: searched at most once (linear time)
    out: list[MoneyMatch] = []
    i = 0
    while i < len(atoms):
        a = atoms[i]
        b = None
        between = False
        if i + 1 < len(atoms):
            gap = s[a.end():atoms[i + 1].start()]
            if _RANGE_SEP_RE.match(gap):
                b = atoms[i + 1]
            elif _AND_RE.match(gap) and _BETWEEN_RE.search(s[max(0, a.start() - _LOOKBACK):a.start()]):
                b = atoms[i + 1]
                between = True
        parts = [a] if b is None else [a, b]
        mult = next((p.group("mult") for p in reversed(parts) if p.group("mult")), None)
        cur = next((c for c in (_atom_currency(p) for p in parts) if c), None)
        lpa = any((p.group("mult") or "").lower() == "lpa" for p in parts)
        vals = []
        for p in parts:
            v = float(p.group("num").replace(",", ""))
            pm = p.group("mult") or mult
            vals.append(round(v * MULTIPLIERS[pm.lower()], 6) if pm else v)   # 1.1 lakh == 110000 exactly
        explicit = bool(mult or cur)
        last = parts[-1]
        if not explicit:
            if _NON_MONEY_UNIT_AT_RE.match(s, last.end()) or max(vals) < min_bare:
                i += 1
                continue
            # Bare 4-digit numbers (PHASE2 2.7.2, fix round 3), in this order:
            # 1. a frequency right after it is money ("Rent 2000 a month", "2000/month");
            # 2. in a date-like position ("in 2150", "by the year 2130", "since 2019") it is a year, whatever its
            #    value: never money, so an out-of-range year never becomes a second goal amount;
            # 3. a 1900-2100 number is money when a frequency is anywhere in the searched clause ("I give 2000 to
            #    my parents each month"), asked (year_like) right after a money word ("Rent 2000."), and otherwise
            #    a year ("2027"); the caller gets that span in `years_skipped` so it can add a note.
            four = all(1900 <= v <= 9999 and float(v).is_integer() for v in vals) and "," not in a.group("num") \
                and "." not in a.group("num")
            year_like = four and all(1900 <= v <= 2100 for v in vals)
            if four and frequency_info_at(s, last.end()) is None:
                before = s[max(0, a.start() - 24):a.start()]
                money_word = bool(_MONEY_BEFORE_RE.search(before))
                if _YEAR_BEFORE_RE.search(before) and not money_word:
                    i += 1 + (b is not None)
                    continue
                if year_like:
                    if freq_any is None:
                        freq_any = _FREQ_ANY_RE.search(s) is not None
                    if freq_any:
                        year_like = False
                    elif b is not None or not money_word:
                        if years_skipped is not None:
                            years_skipped.append((a.start(), last.end()))
                        i += 1 + (b is not None)
                        continue
            else:
                year_like = False
        else:
            year_like = False
        start = a.start()
        if between:
            w0 = max(0, a.start() - _LOOKBACK)
            bm = _BETWEEN_RE.search(s[w0:a.start()])
            start = w0 + bm.start() if bm else start
        amount_start = start
        w0 = max(0, start - _LOOKBACK)
        am = _APPROX_RE.search(s[w0:start])
        approx = bool(am)
        if am:
            start = w0 + am.start()
        end = last.end()
        amount_end = end
        freq = frequency_info_at(s, end)
        frequency = None
        factor, phrase = 1.0, ""
        if freq:
            frequency, end = freq[0].frequency, freq[1]
            factor, phrase = freq[0].factor, freq[0].phrase
        if lpa:
            frequency = frequency or "yearly"
        if max(vals) > 1e12:   # not a plausible amount (also keeps drafts valid)
            i += len(parts)
            continue
        low, high = (vals[0], vals[-1]) if len(vals) == 2 else (vals[0], vals[0])
        if low > high:
            low, high = high, low
        if factor != 1.0:
            low, high = round(low * factor, 2), round(high * factor, 2)
        out.append(MoneyMatch(start=start, end=end, low=low, high=high, currency=cur, approx=approx,
                              frequency=frequency, explicit=explicit, amount_start=amount_start,
                              amount_end=amount_end, lpa=lpa, freq_factor=factor, freq_phrase=phrase,
                              year_like=year_like))
        i += len(parts)
    return out


def parse_money_text(s: str) -> tuple[float, float] | None:
    """A whole answer or cell such as "40-50k", "₹1,20,000", "1.2 lakh" -> (low, high)."""
    ms = find_money(s, min_bare=0.0)
    if not ms:
        return None
    m = ms[0]
    return m.low, m.high


# ---------------------------------------------------------------- percent

_PCT_RE = re.compile(r"(?P<num>\d{1,3}(?:\.\d{1,4})?)\s?(?:%|percent\b|pc\b|per cent\b)(?:\s?p\.?a\.?)?", re.I)


@dataclass
class PercentMatch:
    start: int
    end: int
    value: float


def find_percent(s: str) -> list[PercentMatch]:
    return [PercentMatch(m.start(), m.end(), float(m.group("num"))) for m in _PCT_RE.finditer(s)]


def parse_percent_text(s: str) -> float | None:
    ps = find_percent(s)
    if ps:
        return ps[0].value
    m = re.fullmatch(r"\s*(\d{1,3}(?:\.\d{1,4})?)\s*", s)
    return float(m.group(1)) if m else None


def parse_number_text(s: str) -> float | None:
    m = re.search(NUM, s, re.I)
    if not m:
        return None
    r = parse_number(m.group(0))
    return r[0] if r else None
