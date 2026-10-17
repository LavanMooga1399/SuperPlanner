"""Templates (F.15; acceptance 1.18)."""

import pytest

from fin_helpers import assert_clean, denylist_hits, run
from superplanner.finance import TEMPLATES, get_template, preflight


def test_template_ids_and_get():
    assert set(TEMPLATES) == {"young_professional", "family", "near_retirement", "blank"}
    with pytest.raises(KeyError):
        get_template("nope")


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_deterministic_preflight_clean_and_feasible(tid):
    t = get_template(tid)
    a = t.build(name="Plan", start_month="2026-11", params={})
    b = t.build(name="Plan", start_month="2026-11", params={})
    assert a == b and a.start_month == "2026-11"
    rep = preflight(a)
    assert rep.ok, [i.message for i in rep.issues if i.severity == "error"]
    if tid != "blank":
        r = run(a, compute_fixes=True, calibration_rounds=1)
        assert r.feasibility == "feasible"
        assert_clean(a, r)
        assert not [v for v in r.violations if v.code == "BUCKET_MISMATCH"]
    for c in a.assumptions.asset_classes:
        assert c.id in {"cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold"}


def test_parameters_and_relative_dates():
    t = get_template("young_professional")
    p = t.build(name="x", start_month="2030-01", params={"car_in_years": 2, "age": 30, "retirement_age": 50})
    g = {x.id: x for x in p.goals}
    assert g["car"].target_month == "2032-01" and g["retirement"].target_month == "2050-01"
    assert g["retirement"].target_amount == 25 * 12 * (26000 + 12000)
    with pytest.raises(ValueError):
        t.build(name="x", start_month="2030-01", params={"bogus": 1})
    with pytest.raises(ValueError):
        t.build(name="x", start_month="2030-01", params={"age": 10})
    with pytest.raises(ValueError):
        t.build(name="x", start_month="2030-01", params={"age": 30.5})
    for tpl in TEMPLATES.values():
        for prm in tpl.parameters:
            assert prm.type in ("int", "money", "month_offset_years")
            assert prm.min is None or prm.min <= prm.default <= prm.max
        assert not denylist_hits(tpl.name + tpl.description + " ".join(p.label for p in tpl.parameters))


def test_family_contents():
    p = get_template("family").build(name="x", start_month="2026-11")
    assert {h.id for h in p.holdings} == {"h_cash", "h_eq", "h_ppf"}
    edu = next(g for g in p.goals if g.id == "education")
    assert edu.inflation_pct == 9 and edu.earmarked[0].holding_id == "h_ppf"
    assert p.debts[0].emi == 10000 and p.profile.risk_tolerance == 3
