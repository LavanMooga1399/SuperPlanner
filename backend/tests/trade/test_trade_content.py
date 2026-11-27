"""Domestic-content roll-up through genealogy and BOM share (M9-DESIGN 8.2, 8.3; M9-TRD-02, M9-TRD-03). Pure."""

from __future__ import annotations

import pytest

from superplanner.mfg.trade.content import EdgeT, Graph, ItemT, LotT, Rule, bom_share, rollup


def needle_graph() -> Graph:
    items = {"NDL": ItemT("NDL", "NDL-25G", std_cost=0.06), "STA": ItemT("STA", "STEEL-A", material_class="steel",
                                                                         weight=1.0, std_cost=15.0),
             "STB": ItemT("STB", "STEEL-B", material_class="steel", weight=1.0, std_cost=10.0),
             "RES": ItemT("RES", "RESIN", material_class="resin", weight=1.0, std_cost=10.0),
             "CAP": ItemT("CAP", "CAP", material_class="cap", weight=0.4 / 1000, coo="JP", std_cost=8 / 1000)}
    lots = {"L": LotT("L", "N1", "NDL", coo="US", wo_id="WO1", wo_share=1.0, out_qty=1000),
            "A": LotT("A", "KA", "STA", coo="US", unit_value=15.0), "B": LotT("B", "AB", "STB", coo="CN",
                                                                             unit_value=10.0),
            "R": LotT("R", "R1", "RES", coo="CA", unit_value=10.0)}
    wo = {"WO1": [EdgeT("lot", "A", "STA", 2.0), EdgeT("lot", "B", "STB", 1.0), EdgeT("lot", "R", "RES", 0.5),
                  EdgeT("stock", None, "CAP", 1000.0)]}
    return Graph(items, lots, wo)


@pytest.mark.req("M9-TRD-02")
def test_needle_lot_value_weight_and_steel_only():
    g = needle_graph()
    out = rollup(g, "L", Rule("US"))
    assert out["share_value"] == pytest.approx(30 / 53, abs=1e-4) and out["share_weight"] == pytest.approx(2 / 3.9,
                                                                                                           abs=1e-4)
    assert out["estimated"] is True and len(out["tree"]["children"]) == 4
    steel = rollup(g, "L", Rule("US", frozenset({"steel"})))
    assert steel["share_value"] == pytest.approx(0.75) and steel["share_weight"] == pytest.approx(2 / 3, abs=1e-4)
    assert steel["estimated"] is False


@pytest.mark.req("M9-TRD-03")
def test_made_subassembly_share_is_value_weighted():
    items = {"F": ItemT("F", "FIN", std_cost=10), "S": ItemT("S", "SUB", std_cost=4),
             "X": ItemT("X", "XUS", std_cost=1, coo="US"), "Y": ItemT("Y", "YCN", std_cost=1, coo="CN"),
             "Z": ItemT("Z", "ZUS", std_cost=6, coo="US")}
    lots = {"FL": LotT("FL", "F1", "F", wo_id="W1", out_qty=1), "SL": LotT("SL", "S1", "S", wo_id="W2", out_qty=1,
                                                                            unit_value=4.0),
            "XL": LotT("XL", "X1", "X", coo="US", unit_value=2), "YL": LotT("YL", "Y1", "Y", coo="CN", unit_value=2),
            "ZL": LotT("ZL", "Z1", "Z", coo="US", unit_value=6)}
    g = Graph(items, lots, {"W2": [EdgeT("lot", "XL", "X", 1), EdgeT("lot", "YL", "Y", 1)],
                            "W1": [EdgeT("lot", "SL", "S", 1), EdgeT("lot", "ZL", "Z", 1)]})
    assert rollup(g, "SL", Rule("US"))["share_value"] == 0.5
    out = rollup(g, "FL", Rule("US"))
    assert out["share_value"] == pytest.approx((0.5 * 4 + 6) / 10) and out["estimated"] is False


def test_bom_share_with_supplier_split():
    items = {"F": ItemT("F", "F"), "ST": ItemT("ST", "ST", std_cost=1.0, material_class="steel")}
    num, den = bom_share("F", {"F": [("ST", 2.0)]}, items, {"ST": [("US", 0.6), ("CN", 0.4)]},
                         Rule("US", frozenset({"steel"})))
    assert num / den == pytest.approx(0.6)


def test_bom_share_follows_scenario_supplier_split():
    """M9 8.3 projection: a dual-source split 60 / 40 (US / CN) gives a 60 % steel share."""
    items = {"F": ItemT("F", "F"), "ST": ItemT("ST", "ST", std_cost=1.0, material_class="steel")}
    for split, expect in (([("US", 0.6), ("CN", 0.4)], 0.6), ([("CN", 1.0)], 0.0)):
        num, den = bom_share("F", {"F": [("ST", 1.0)]}, items, {"ST": split}, Rule("US", frozenset({"steel"})))
        assert num / den == pytest.approx(expect)


def test_genealogy_cycle_is_flagged_not_followed():
    """Review m5: a lot that (indirectly) consumes itself stops at the back edge, flagged and estimated."""
    items = {"A": ItemT("A", "A", std_cost=1), "B": ItemT("B", "B", std_cost=1), "X": ItemT("X", "X", std_cost=1,
                                                                                         coo="US")}
    lots = {"LA": LotT("LA", "A1", "A", wo_id="W1", out_qty=1), "LB": LotT("LB", "B1", "B", wo_id="W2", out_qty=1),
            "LX": LotT("LX", "X1", "X", coo="US", unit_value=1)}
    g = Graph(items, lots, {"W1": [EdgeT("lot", "LB", "B", 1), EdgeT("lot", "LX", "X", 1)],
                            "W2": [EdgeT("lot", "LA", "A", 1)]})
    out = rollup(g, "LA", Rule("US"))
    assert out["flags"] == ["TRADE_GENEALOGY_CYCLE"] and out["estimated"] is True
