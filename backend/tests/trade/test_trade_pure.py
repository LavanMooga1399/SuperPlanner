"""Landed cost and FX (M9-DESIGN 8.4; register M9-TRD-06, M9-TRD-07). Pure, no database."""

from __future__ import annotations

from datetime import date

import pytest

from superplanner.mfg.trade.fx import FxTable
from superplanner.mfg.trade.landed import SupplierTerms, Tariff, duty_layers, landed

NOV = date(2026, 11, 1)


def tariffs() -> list[Tariff]:
    return [Tariff("CA", "9018", "*", "mfn", 0.0, None, None, date(2020, 1, 1), None),
            Tariff("CA", "9018", "CN", "surtax", 25.0, None, None, date(2026, 1, 1), None),
            Tariff("CA", "90", "CN", "surtax", 5.0, None, None, date(2026, 1, 1), None),          # shorter prefix
            Tariff("CA", "9018", "*", "surtax", 1.0, None, None, date(2026, 1, 1), None),          # * after exact
            Tariff("CA", "9018", "CN", "s301", 7.5, None, None, date(2027, 1, 1), None)]           # not yet valid


@pytest.mark.req("M9-TRD-06")
def test_landed_cost_hand_example():
    fx = FxTable([("USD", "CAD", NOV, 1.40)])
    t = SupplierTerms(unit_price=100.0, currency="USD", units_per_purchase_unit=1000, coo="CN", hts_code="901832",
                      freight_per_unit=0.005)
    out = landed(t, "CA", "CAD", NOV, fx, tariffs(), duty_base={"*": "fob"}, other_cost_pct=0.5)
    assert out["unit_price"] == pytest.approx(0.14) and out["customs_value"] == pytest.approx(0.14)
    assert {d["layer"]: d["amount"] for d in out["duty"]} == {"mfn": 0.0, "surtax": pytest.approx(0.035)}
    assert out["other"] == pytest.approx(0.0007) and out["total"] == pytest.approx(0.1807)
    assert out["currency"] == "CAD" and out["fx_rate"] == 1.4 and out["flags"] == []
    cif = landed(t, "CA", "CAD", NOV, fx, tariffs(), duty_base={"CA": "cif"}, other_cost_pct=0.5)
    assert cif["customs_value"] == pytest.approx(0.145)
    dom = landed(SupplierTerms(1.0, "CAD", coo="CA", hts_code="901832"), "CA", "CAD", NOV, fx, tariffs())
    assert dom["duty"] == [] and "FREIGHT_MISSING" in dom["flags"]
    nohts = landed(SupplierTerms(1.0, "CAD", coo="CN"), "CA", "CAD", NOV, fx, tariffs())
    assert "HTS_MISSING" in nohts["flags"] and nohts["duty"] == []
    assert [x.layer for x in duty_layers(tariffs(), "CA", "901832", "CN", date(2027, 2, 1))] == ["mfn", "s301",
                                                                                                  "surtax"]


@pytest.mark.req("M9-TRD-07")
def test_fx_inverse_via_usd_stale_missing():
    fx = FxTable([("USD", "CAD", NOV, 1.40), ("EUR", "USD", NOV, 1.10), ("USD", "INR", date(2026, 9, 1), 83.0)])
    assert fx.rate("CAD", "USD", NOV) == (pytest.approx(1 / 1.40), [])
    assert fx.rate("EUR", "CAD", NOV) == (pytest.approx(1.10 * 1.40), [])
    assert fx.rate("USD", "INR", NOV) == (83.0, ["FX_STALE"])
    assert fx.rate("USD", "JPY", NOV) == (None, ["FX_MISSING"])
    assert fx.rate("USD", "USD", NOV) == (1.0, [])
    out = landed(SupplierTerms(1.0, "JPY", coo="JP", hts_code="901832", freight_per_unit=0.0), "CA", "CAD", NOV, fx,
                 tariffs())
    assert out["total"] is None and out["unit_price"] is None and "FX_MISSING" in out["flags"]


@pytest.mark.req("M9-TRD-05")
def test_milestone_status_met_at_risk_missed():
    from superplanner.mfg.trade.milestones import month_cell, status

    eff = date(2027, 7, 1)
    assert [status(x, 100, date(2027, 8, 1), eff) for x in (100, 97, 80)] == ["met", "at_risk", "missed"]
    assert status(80, 100, date(2027, 6, 1), eff) is None
    cell = month_cell([{"share": 1.0, "denom": 30, "qty": 600, "estimated": False},
                       {"share": 0.5, "denom": 10, "qty": 400, "estimated": True}], 100, date(2027, 8, 1), eff)
    assert cell["share_pct"] == 87.5 and cell["status"] == "missed" and cell["lots_below"] == 1
    assert cell["qty_below_pct"] == 40 and cell["estimated_pct"] == 40


@pytest.mark.req("M9-TRD-08")
def test_supplier_risk_score_and_suggestion():
    from superplanner.mfg.trade.risk import score, suggestions

    row = {"supplier_code": "ATUBE", "coo": "CN", "family": "CAN", "hts": "730411", "spend_12m": 1000.0,
           "otd_pct": 88.0, "lead_days": 75, "duty_pct": 25.0, "landed": 0.012}
    out = score(row, n_suppliers=1, countries={"CN"}, country_risk={"CN": 20}, domestic="US",
                milestone_families=set())
    assert out["score"] == 35 + 20 + 15 + 15 + 10 and out["flags"] == ["single_source"]
    sug = suggestions(row, [{"supplier_code": "KTUBE", "node_owner_id": "n", "coo": "US", "family": "OTHER",
                             "hts": "730419", "landed": 0.011, "score": 5},
                            {"supplier_code": "ZZ", "node_owner_id": "n", "family": "X", "hts": "9999", "landed": 0.001}])
    assert [s["supplier_code"] for s in sug] == ["KTUBE"] and sug[0]["basis"] == "heading"
    assert sug[0]["landed_delta"] == pytest.approx(-0.001)


def test_landed_without_plant_country_has_no_total():
    """Review M4: the destination country is never guessed."""
    fx = FxTable([("USD", "CAD", NOV, 1.40)])
    out = landed(SupplierTerms(100.0, "USD", 1000, "CN", "901832", 0.005), None, "CAD", NOV, fx, tariffs())
    assert out["total"] is None and "COUNTRY_MISSING" in out["flags"] and out["unit_price"] == pytest.approx(0.14)
