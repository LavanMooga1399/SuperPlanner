"""Rule-based + AI merge (PHASE2 2.11; plan P2-7)."""

from __future__ import annotations

import pytest

from intake_helpers import (CTX, FIN_CTX, FINANCE_TEXT, SCHEDULE_TEXT, FakeClient, ai_finance_output,
                            ai_schedule_output, text_response)
from superplanner.intake import AiFallback, AiOptions, describe_finance, describe_schedule
from superplanner.intake.ai.merge import merge_finance, merge_schedule
from superplanner.intake.models import DraftTask, ScheduleDraft


def _ai(out) -> AiOptions:
    fake = FakeClient(text_response(out))
    return AiOptions(requested=True, enabled=True, client_factory=lambda: fake)


def test_typed_numbers_win_schedule():
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=_ai(ai_schedule_output()))
    assert r.extractor.used == "ai+rule"
    t1 = r.draft.tasks[0]
    assert t1.name == "Gather requirements"
    assert (t1.duration.optimistic, t1.duration.pessimistic, t1.duration.unit) == (2, 3, "days")
    kept = [n for n in r.notes if n.code == "KEPT_TYPED_NUMBER"]
    assert kept and kept[0].message == "AI assist read 4 days; we kept the 2-3 days you typed."
    assert r.draft.provenance["/tasks/t1/duration"].source == "text"


def test_ai_only_items_appended_with_capped_confidence_and_dropped_refs():
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=_ai(ai_schedule_output()))
    keys = [t.key for t in r.draft.tasks]
    assert keys[:5] == ["t1", "t2", "t3", "t4", "t5"]
    added = r.draft.tasks[5]
    assert added.key == "t6" and added.name == "Write release notes"
    assert added.after == ["t4"]                       # "Ghost task" did not resolve
    dropped = [n for n in r.notes if n.code == "AI_REFERENCE_DROPPED"]
    assert len(dropped) == 1 and "Ghost task" in dropped[0].message
    for path, p in r.draft.provenance.items():
        if path.startswith("/tasks/t6/"):
            assert p.source == "ai" and p.confidence <= 0.8
    assert any(n.code == "AI_NOTE" and n.message == "Launch date looks fixed." for n in r.notes)


def test_typed_number_wins_finance_and_ai_only_expense_added():
    r = describe_finance(FINANCE_TEXT, FIN_CTX, ai=_ai(ai_finance_output()))
    assert r.extractor.used == "ai+rule"
    i1 = next(i for i in r.draft.incomes if i.key == "i1")
    assert i1.amount.low == i1.amount.high == 120000
    assert any(n.code == "KEPT_TYPED_NUMBER" and "1,25,000" not in n.message and "125,000" in n.message
               for n in r.notes)
    maid = next(e for e in r.draft.expenses if e.name == "Maid and cook")
    assert maid.key == "e3"
    prov = r.draft.provenance[f"/expenses/{maid.key}/amount"]
    assert prov.source == "ai" and prov.confidence == 0.3   # quote "invented" not found in the text (fix round)
    assert len(r.draft.incomes) == 2                         # AI salary matched the typed one


def test_ai_fills_only_missing_fields():
    text = "Write the report\nReview the report"
    out = ai_schedule_output(tasks=[
        {"name": "Write the report", "milestone": False,
         "duration": {"low": 2, "likely": 3, "high": 4, "unit": "hours"}, "after": [], "resources": [],
         "resource_mode": "any", "deadline": None, "deadline_hard": False, "earliest_start": None, "group": None,
         "source_quote": "Write the report", "confidence": 0.95}], resources=[], notes=[])
    r = describe_schedule(text, CTX, ai=_ai(out))
    t = r.draft.tasks[0]
    assert (t.duration.optimistic, t.duration.likely, t.duration.pessimistic, t.duration.unit) == (2, 3, 4, "hours")
    p = r.draft.provenance["/tasks/t1/duration"]
    assert p.source == "ai" and p.confidence == 0.8 and p.span is not None


def test_invalid_merged_draft_discards_ai():
    R = ScheduleDraft(tasks=[DraftTask(key="t1", name="A")])
    A = ScheduleDraft(tasks=[DraftTask(key="t1", name="Totally different"), DraftTask(key="t2", name="Other")])
    A.tasks[1].__dict__["after"] = ["t1"]
    A.tasks[1].__dict__["resources"] = ["r_nobody"]   # bypassed validation: a broken AI draft
    # the appended task drops the unknown resource, so the merge stays valid
    merged, notes = merge_schedule(R, A, [])
    assert [t.key for t in merged.tasks] == ["t1", "t2", "t3"]
    # force an invalid merged result: two tasks with the same key
    bad = ScheduleDraft(tasks=[DraftTask(key="t1", name="A")])
    bad.tasks.append(DraftTask(key="t1", name="A again"))
    with pytest.raises(AiFallback) as e:
        merge_schedule(bad, ScheduleDraft(), [])
    assert e.value.code == "AI_SCHEMA_MISMATCH"


def test_invalid_merge_falls_back_in_describe(monkeypatch):
    import superplanner.intake.ai.merge as merge_mod

    def broken(*a, **kw):
        raise AiFallback("AI_SCHEMA_MISMATCH")

    monkeypatch.setattr(merge_mod, "merge_schedule", broken)
    rule = describe_schedule(SCHEDULE_TEXT, CTX)
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=_ai(ai_schedule_output()))
    assert r.extractor.used == "rule" and r.extractor.fallback_code == "AI_SCHEMA_MISMATCH"
    assert r.draft == rule.draft


def test_merge_finance_profile_typed_wins():
    rule = describe_finance(FINANCE_TEXT, FIN_CTX)
    out = ai_finance_output()
    out["profile"]["age"] = 43
    r = describe_finance(FINANCE_TEXT, FIN_CTX, ai=_ai(out))
    assert r.draft.profile.age == 34
    assert any(n.code == "KEPT_TYPED_NUMBER" and "43" in n.message for n in r.notes)
    assert merge_finance(rule.draft, rule.draft, [])[0].incomes == rule.draft.incomes
