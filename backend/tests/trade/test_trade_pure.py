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
