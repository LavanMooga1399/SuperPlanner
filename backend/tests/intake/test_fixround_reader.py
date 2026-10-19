"""Fix round: linear-time readers, frequencies, currencies, savings, dates (PHASE2 2.7, 2.13)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from intake_helpers import API, CTX, FIN_CTX
from superplanner import intake

CTXJ = CTX.model_dump(mode="json")
FINJ = FIN_CTX.model_dump(mode="json")


def _table(rows: int, refs: int) -> str:
    refcell = ",".join(f"zz{j}" for j in range(refs))
    return "\n".join(f"Step number {i} of the work\t2 h\t{refcell}" for i in range(rows))


@pytest.mark.parametrize("refs", [2, 50])
def test_table_apply_2000_rows_is_fast_and_bounded(client, refs):
    text = _table(2000, refs)
    body = {"text": text, "delimiter": "\t", "has_header": False,
            "mapping": [{"column": 0, "field": "name"}, {"column": 1, "field": "duration"},
                        {"column": 2, "field": "predecessors"}], "context": CTXJ}
    t0 = time.monotonic()
    r = client.post(f"{API}/intake/schedule/table/apply", json=body)
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text[:300]
    assert elapsed < 2.0, elapsed
    notes = r.json()["row_notes"]
    assert len(notes) <= 201
    assert len(r.content) < 1_000_000


def test_table_apply_unmatched_refs_one_note_per_row():
    text = "A\t1 d\t\nB\t1 d\tA, nope, zip\n"
    p = intake.parse_table(text, "schedule")
    from superplanner.intake.models import ColumnMapping, TableApply
    req = TableApply(text=text, delimiter="\t", has_header=False,
                     mapping=[ColumnMapping(column=0, field="name"), ColumnMapping(column=1, field="duration"),
                              ColumnMapping(column=2, field="predecessors")])
    r = intake.apply_schedule_table(req, CTX, None)
    assert r.draft.tasks[1].after == ["row0"]
    assert [n.message for n in r.row_notes] == [
        'Row 2: "nope", "zip" do not match another row, so those links were left out.']
    assert p.row_count == 2


@pytest.mark.parametrize("text,fn", [
    (("1 to 2 lakh " * 2000)[:20000], "f"),
    (("between 1 and 2 lakh to 3 crore - " * 600)[:20000], "f"),
    (("- a 2-3 days after b\n" * 1000)[:20000], "s"),
    ("".join(f"Write chapter {i} 3 hours after chapter {i - 1}. " for i in range(600))[:20000], "s"),
    ("".join(f"Design module {i} 2 days. Test module {i} before review module {i}. " for i in range(600))[:20000],
     "s"),
    (("Rent 20k " * 3000)[:20000], "f"),
    (("EMI 5k loan " * 2000)[:20000], "f"),
])
def test_long_inputs_are_linear(text, fn):
    t0 = time.monotonic()
    if fn == "f":
        intake.describe_finance(text, FIN_CTX)
    else:
        intake.describe_schedule(text, CTX)
    assert time.monotonic() - t0 < 2.0


def _monthly(d, coll="expenses"):
    return [(x.amount.low, x.frequency) for x in getattr(d, coll) if x.amount]


def test_weekly_amount_converted_to_monthly_with_note():
    r = intake.describe_finance("I take home 1 lakh a month. I pay 5000 rupees a week for daily help.", FIN_CTX)
    assert _monthly(r.draft) == [(round(5000 * 52 / 12, 2), "monthly")]
    prov = r.draft.provenance["/expenses/e1/amount"]
    assert prov.source == "derived" and "a week" in prov.note
    assert any(n.code == "FREQUENCY_CONVERTED" for n in r.notes)


@pytest.mark.parametrize("text,expected", [
    ("Electricity 3k every 2 months.", (1500.0, "monthly")),
    ("Water bill 3k every 3 months.", (3000.0, "quarterly")),
    ("Car service 12k every 6 months.", (12000.0, "half_yearly")),
    ("Cleaning 1000 every 2 weeks.", (round(1000 * 52 / 24, 2), "monthly")),
    ("Milk 60 rupees a day.", (round(60 * 365 / 12, 2), "monthly")),
])
def test_every_n_frequencies(text, expected):
    r = intake.describe_finance(text, FIN_CTX)
    assert _monthly(r.draft) == [expected]


def test_mixed_currency_with_one_foreign_amount():
    r = intake.describe_finance("I take home 1 lakh a month. Netflix $15 a month.", FIN_CTX)
    assert any(n.code == "MIXED_CURRENCY" for n in r.notes)


def test_foreign_currency_only_text_is_flagged():
    r = intake.describe_finance("I take home $5,000 a month. Rent $2,000 a month.", FIN_CTX)
    assert any(n.code == "MIXED_CURRENCY" for n in r.notes)


def test_plain_inr_text_has_no_currency_note():
    r = intake.describe_finance("I take home ₹1 lakh a month. Rent 20k a month.", FIN_CTX)
    assert not any(n.code == "MIXED_CURRENCY" for n in r.notes)


@pytest.mark.parametrize("text,cls", [("FD of ₹5L maturing in 2028.", "fixed_deposit"),
                                      ("I hold gold worth 3 lakh.", "gold")])
def test_savings_statements_are_holdings(text, cls):
    d = intake.describe_finance(text, FIN_CTX).draft
    assert d.expenses == []
    assert [(h.asset_class_id, h.amount.low) for h in d.holdings] == [(cls, {"fixed_deposit": 500000,
                                                                            "gold": 300000}[cls])]


def test_monthly_sip_is_not_a_holding():
    d = intake.describe_finance("SIP of 10k a month.", FIN_CTX).draft
    assert d.holdings == []


@pytest.mark.parametrize("text", ["Maid salary 6,000 per month. I take home 80k a month.",
                                  "We pay the driver 15k a month. My salary is 1 lakh a month."])
def test_salary_paid_to_others_is_an_expense(text):
    d = intake.describe_finance(text, FIN_CTX).draft
    assert len(d.incomes) == 1 and len(d.expenses) == 1


# ---------------------------------------------------------------- AI values without a quote (2.10)

def _ai_opts(out):
    from intake_helpers import FakeClient, text_response
    from superplanner.intake import AiOptions
    fake = FakeClient(text_response(out))
    return AiOptions(requested=True, enabled=True, client_factory=lambda: fake)


def test_invented_ai_amounts_are_required_questions_and_can_be_dropped():
    from intake_helpers import ai_finance_output
    from superplanner.intake.models import Answer
    amt = lambda v: {"low": v, "high": v}  # noqa: E731
    out = ai_finance_output(
        incomes=[{"name": "Salary", "kind": "salary", "amount": amt(80000), "frequency": "monthly", "is_gross": False,
                  "source_quote": "I take home 80k a month.", "confidence": 0.9},
                 {"name": "Lottery", "kind": "other", "amount": amt(5_000_000), "frequency": "monthly",
                  "is_gross": False, "source_quote": "I won the lottery", "confidence": 0.95}],
        expenses=[], holdings=[{"name": "Crypto", "asset_class": "unknown", "amount": amt(9e11), "locked_until": None,
                                "source_quote": "nope", "confidence": 0.9}],
        profile={"age": None, "retirement_age": None, "risk_tolerance": None, "source_quote": ""})
    r = intake.describe_finance("I take home 80k a month.", FIN_CTX, ai=_ai_opts(out))
    assert r.extractor.used == "ai+rule"
    lottery = next(i for i in r.draft.incomes if i.name == "Lottery")
    crypto = next(h for h in r.draft.holdings if h.name == "Crypto")
    paths = {f"/incomes/{lottery.key}/amount", f"/holdings/{crypto.key}/amount"}
    req = {q.path: q for q in r.questions if q.required and q.code == "FIN_LOW_CONFIDENCE"}
    assert paths <= set(req), [(q.code, q.path, q.required) for q in r.questions]
    assert "not in your text" in req[f"/incomes/{lottery.key}/amount"].prompt
    assert not r.ready
    a = intake.answer_finance(r.draft, [Answer(question_id=req[p].id, value=False) for p in paths], FIN_CTX)
    lottery = next(i for i in a.draft.incomes if i.name == "Lottery")
    assert lottery.amount is None


def test_invented_ai_duration_is_a_required_question():
    from intake_helpers import SCHEDULE_TEXT, ai_schedule_output
    r = intake.describe_schedule(SCHEDULE_TEXT, CTX, ai=_ai_opts(ai_schedule_output()))
    t = next(t for t in r.draft.tasks if t.name == "Write release notes")
    q = [q for q in r.questions if q.path == f"/tasks/{t.key}/duration"]
    assert q and q[0].required and "not in your text" in q[0].prompt
    # only one question for that task
    assert [x.path for x in r.questions if x.code == "SCHED_LOW_CONFIDENCE" and x.path
            and x.path.startswith(f"/tasks/{t.key}/")] == [q[0].path]


# ---------------------------------------------------------------- extreme dates (2.7 robustness)

@pytest.mark.parametrize("domain,text", [
    ("schedule", "1. Design 2 days\n2. Launch in 9999 years"),
    ("schedule", "Start on 31/12/9999.\n1. Design 2 days"),
    ("finance", "Trip of 2 lakh in 9999 years."),
    ("finance", "Trip of 2 lakh in 99999999 months."),
])
def test_far_dates_are_left_out_with_a_note(client, domain, text):
    ctx = CTXJ if domain == "schedule" else FINJ
    r = client.post(f"{API}/intake/{domain}/describe", json={"text": text, "context": ctx})
    assert r.status_code == 200, r.text[:300]
    assert any(n["code"] == "DATE_OUT_OF_RANGE" for n in r.json()["notes"])
    b = client.post(f"{API}/intake/{domain}/build", json={"draft": r.json()["draft"], "context": ctx})
    assert b.status_code == 200


@pytest.mark.parametrize("today", ["9999-12-20", "1969-12-31"])
def test_extreme_context_today_is_422(client, today):
    for path, body in [("schedule/describe", {"text": "1. Design 2 days"}),
                       ("finance/describe", {"text": "I earn 1 lakh a month."}),
                       ("schedule/table/apply", {"text": "A\t2 d", "delimiter": "\t", "has_header": False,
                                                 "mapping": [{"column": 0, "field": "name"},
                                                             {"column": 1, "field": "duration"}]})]:
        r = client.post(f"{API}/intake/{path}", json={**body, "context": dict(CTXJ, today=today)})
        assert r.status_code == 422, (path, r.status_code)


@pytest.mark.parametrize("draft", [
    {"start_date": "9999-12-30", "tasks": [{"key": "t1", "name": "A", "duration": {
        "optimistic": 1, "likely": 1, "pessimistic": 1, "unit": "days"}}]},
    {"tasks": [{"key": "t1", "name": "A", "deadline": "9999-12-31", "duration": {
        "optimistic": 1, "likely": 1, "pessimistic": 1, "unit": "days"}}]},
])
def test_client_draft_with_extreme_dates_builds_not_ready(client, draft):
    r = client.post(f"{API}/intake/schedule/build", json={"draft": draft, "context": CTXJ})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["ready"] is False
    assert r.json()["report"]["issues"][0]["code"] == "DATE_OUT_OF_RANGE"


def test_date_words_still_read_normally():
    from superplanner.intake.text.dates import find_dates
    assert [d.value for d in find_dates("in 3 years", date(2026, 10, 17))] == [date(2029, 10, 17)]
