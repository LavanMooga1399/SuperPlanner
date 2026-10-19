"""Rule-based reader accuracy on a realistic corpus (PHASE2 2.7): 35 schedule and 34 finance descriptions in
Indian and plain English (lakh/crore/L/k, ranges, three-point durations, DMY/MDY/relative dates,
dependencies, people). Field accuracy is measured per field and asserted against thresholds.
"""

from __future__ import annotations

import pytest

from p2_corpus import FINANCE_CORPUS, SCHEDULE_CORPUS
from p2_helpers import Score, ctx, score_finance, score_schedule
from superplanner.intake import build_finance, build_schedule, describe_finance, describe_schedule

# Thresholds: the reader is the only extractor on a server without AI, so it must be reliable on plain text.
SCHED_OVERALL = 0.95
FIN_OVERALL = 0.92
SCHED_FIELDS = {"task_found": 0.97, "duration": 0.95, "after": 0.92, "deadline": 0.95, "deadline_hard": 0.95,
                "milestone": 0.95, "resources": 0.9, "task_name": 0.9}
FIN_FIELDS = {"incomes_found": 0.95, "incomes.amount": 0.95, "incomes.frequency": 0.95, "goals_found": 0.95,
              "goals.target": 0.95, "goals.target_month": 0.95, "debts_found": 0.95, "debts.balance": 0.95,
              "debts.emi": 0.95, "expenses_found": 0.9, "expenses.amount": 0.9, "holdings_found": 0.85,
              "holdings.asset_class_id": 0.85, "profile.age": 0.95, "no_spurious_item": 0.9}


def test_corpus_size():
    assert len(SCHEDULE_CORPUS) >= 30 and len(FINANCE_CORPUS) >= 30
    assert len({c.id for c in SCHEDULE_CORPUS}) == len(SCHEDULE_CORPUS)
    assert len({c.id for c in FINANCE_CORPUS}) == len(FINANCE_CORPUS)


def test_schedule_field_accuracy():
    sc = Score()
    for case in SCHEDULE_CORPUS:
        r = describe_schedule(case.text, ctx(case.locale, case.kind))
        score_schedule(case, r.draft, sc)
    report = sc.table() + "\nmisses:\n" + "\n".join(sc.misses)
    print(report)
    assert sc.ratio() >= SCHED_OVERALL, report
    for fld, th in SCHED_FIELDS.items():
        assert sc.ratio(fld) >= th, f"{fld} {sc.ratio(fld):.2f} < {th}\n{report}"


def test_finance_field_accuracy():
    sc = Score()
    for case in FINANCE_CORPUS:
        r = describe_finance(case.text, ctx(case.locale))
        score_finance(case, r, sc)
    report = sc.table() + "\nmisses:\n" + "\n".join(sc.misses)
    print(report)
    assert sc.ratio() >= FIN_OVERALL, report
    for fld, th in FIN_FIELDS.items():
        assert sc.ratio(fld) >= th, f"{fld} {sc.ratio(fld):.2f} < {th}\n{report}"


@pytest.mark.parametrize("case", SCHEDULE_CORPUS, ids=lambda c: c.id)
def test_schedule_case_is_deterministic_and_spans_are_code_points(case):
    c = ctx(case.locale, case.kind)
    a = describe_schedule(case.text, c)
    b = describe_schedule(case.text, c)
    assert a.model_dump() == b.model_dump()
    cps = list(case.text)
    for path, prov in a.draft.provenance.items():
        if prov.span is not None:
            assert 0 <= prov.span.start <= prov.span.end <= len(cps), path
            assert "".join(cps[prov.span.start:prov.span.end]) == prov.span.text, path


@pytest.mark.parametrize("case", FINANCE_CORPUS, ids=lambda c: c.id)
def test_finance_case_is_deterministic_and_spans_are_code_points(case):
    c = ctx(case.locale)
    a = describe_finance(case.text, c)
    b = describe_finance(case.text, c)
    assert a.model_dump() == b.model_dump()
    cps = list(case.text)
    for path, prov in a.draft.provenance.items():
        if prov.span is not None:
            assert 0 <= prov.span.start <= prov.span.end <= len(cps), path
            assert "".join(cps[prov.span.start:prov.span.end]) == prov.span.text, path


def _answer_all_defaults(answer, draft, qs, c):
    from superplanner.intake import Answer
    for _ in range(10):
        if not qs:
            break
        ans = [Answer(question_id=q.id, use_default=True) if q.default is not None
               else Answer(question_id=q.id, value=_fallback_value(q)) for q in qs]
        r = answer(draft, ans, c)
        draft, qs = r.draft, r.questions
    return draft, qs


def _fallback_value(q):
    return {"duration": {"optimistic": 1, "likely": 1, "pessimistic": 1, "unit": "days"}, "money": 50000,
            "number": 35, "text": "Task one 1 day", "month": "2030-01", "choice": (q.options[0].value if q.options else None),
            "confirm": True}.get(q.kind)


@pytest.mark.parametrize("case", SCHEDULE_CORPUS, ids=lambda c: c.id)
def test_every_schedule_case_builds_after_default_answers(case):
    """Describe -> accept suggestions (or a plain answer for required ones) -> build gives a valid Problem."""
    from superplanner.intake import answer_schedule
    c = ctx(case.locale, case.kind)
    r = describe_schedule(case.text, c)
    draft, qs = _answer_all_defaults(answer_schedule, r.draft, r.questions, c)
    assert not [q for q in qs if q.required], [(q.code, q.prompt) for q in qs]
    b = build_schedule(draft, c)
    assert b.problem is not None and b.report is not None
    issues = [i.code for i in b.report.issues if i.severity == "error"]
    # a deadline that the expected work cannot meet is a legitimate user-facing error; anything else is not
    assert set(issues) <= {"DEADLINE_INFEASIBLE", "HARD_DEADLINE_UNREACHABLE"}, issues


@pytest.mark.parametrize("case", FINANCE_CORPUS, ids=lambda c: c.id)
def test_every_finance_case_builds_after_default_answers(case):
    from superplanner.intake import answer_finance
    c = ctx(case.locale)
    r = describe_finance(case.text, c)
    draft, qs = _answer_all_defaults(answer_finance, r.draft, r.questions, c)
    assert not [q for q in qs if q.required], [(q.code, q.prompt) for q in qs]
    b = build_finance(draft, c)
    assert b.plan is not None and b.preflight is not None
