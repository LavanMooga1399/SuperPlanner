"""Compliance (F.21; acceptance 1.21): no product names in engine-authored text, no forbidden wording in any
generated text, the exact disclaimer on every result."""

from pathlib import Path

import pytest

from fin_helpers import denylist_hits, run
from superplanner.finance import DISCLAIMER, TEMPLATES, get_template
from superplanner.finance.advisor.messages import FORBIDDEN_WORDS, MESSAGES, contains_forbidden

PKG = Path(__file__).resolve().parents[2] / "superplanner" / "finance"


@pytest.mark.parametrize("rel", ["defaults.py", "templates.py", "advisor/messages.py"])
def test_denylist_on_catalogs(rel):
    text = (PKG / rel).read_text()
    assert denylist_hits(text) == []
    if rel != "defaults.py":
        assert "PPF-like" not in text
    else:
        assert text.count("PPF-like") == 1 and "(PPF-like)" in text
        assert denylist_hits(text, allow=[]) == ["PPF"]          # the allow-list is what makes it pass [R25]


def test_denylist_helper_catches_names():
    assert denylist_hits("Buy the Nifty 50 index") == ["Nifty"]
    assert denylist_hits("an index fund and a fixed deposit, gold, a debt fund") == []
    assert denylist_hits("h_ppf holding") == []


def test_catalog_has_no_forbidden_words():
    for code, text in MESSAGES.items():
        assert not contains_forbidden(text), code
    assert contains_forbidden("This is guaranteed") == ["guarantee", "guaranteed"] or contains_forbidden(
        "This is guaranteed")
    assert contains_forbidden("make sure") == ["sure"] and not contains_forbidden("measure and ensure")


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_generated_text_of_template_runs(tid):
    p = get_template(tid).build(name="Plan", start_month="2026-11")
    r = run(p, compute_fixes=True)
    assert r.disclaimer == DISCLAIMER and r.disclaimer_version == "fin-disclaimer-1"
    e = r.explanation
    texts = list(e.summary) + e.assumptions + e.limitations + e.replanning_triggers
    texts += [b.message for b in e.binding_constraints] + [v.message for v in r.violations]
    for ge in e.goals.values():
        texts += [x.message for x in ge.reasons] + [f.message for f in ge.fixes]
        texts += [f.what_if.label for f in ge.fixes if f.what_if.label]
    for t in texts:
        assert not contains_forbidden(t), t
        assert not denylist_hits(t), t
    assert all(w == w.lower() for w in FORBIDDEN_WORDS)
