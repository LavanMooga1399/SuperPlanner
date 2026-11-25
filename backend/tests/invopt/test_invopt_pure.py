"""Safety stock and ABC/XYZ (M8-DESIGN 5; pure)."""

from __future__ import annotations

import pytest

from superplanner.mfg.invopt import classify, safety


@pytest.mark.req("M8-SS-01")
def test_safety_stock_hand_case():
    z = safety.z_of(0.98)
    assert z == pytest.approx(2.0537489, abs=1e-6)
    raw = safety.safety_stock(z, 1000, 200, 10, 2)
    assert raw == pytest.approx(z * (10 * 200 ** 2 + 1000 ** 2 * 2 ** 2) ** 0.5, rel=1e-12)
    assert round(raw) == 4308
    p = safety.propose(z, 1000, 200, 10, 2, 1000, 60)
    assert p.proposed == 5000 and p.flags == []
    capped = safety.propose(z, 1000, 200, 10, 2, 1000, 3)       # cap 3,000
    assert capped.proposed == 3000 and capped.flags == ["SS_CAPPED"]


def test_inverse_normal_accuracy_and_symmetry():
    for p, z in ((0.5, 0.0), (0.9, 1.2815516), (0.95, 1.6448536), (0.99, 2.3263479), (0.999, 3.0902323),
                 (0.01, -2.3263479)):
        assert safety.z_of(p) == pytest.approx(z, abs=1e-6)
    with pytest.raises(ValueError):
        safety.z_of(1.0)


def test_lead_time_sigma_needs_five_receipts():
    assert safety.lt_sigma([1, 2, 3, 4]) == 0.0
    assert safety.lt_sigma([0, 2, 0, 2, 0, 2]) == pytest.approx((6 * 1 / 5) ** 0.5)


@pytest.mark.req("M8-SS-02")
def test_abc_xyz_hand_table():
    values = {"i01": 5000, "i02": 2000, "i03": 1000, "i04": 600, "i05": 500, "i06": 300, "i07": 250, "i08": 150,
              "i09": 120, "i10": 80}                                    # total 10,000
    got = classify.abc(values)
    # cumulative: .50 .70 .80 | .86 .91 .94 | .965 .98 .992 1.0
    assert got == {"i01": "A", "i02": "A", "i03": "A", "i04": "B", "i05": "B", "i06": "B", "i07": "C", "i08": "C",
                   "i09": "C", "i10": "C"}
    assert classify.abc({"big": 95, "small": 5}) == {"big": "A", "small": "C"}
    assert [classify.xyz(c) for c in (0.1, 0.49, 0.5, 0.99, 1.0, 3.0)] == ["X", "X", "Y", "Y", "Z", "Z"]
    assert classify.cv(50, 100) == 0.5
    assert classify.cv(0, 0, "lumpy", 0.5, 4.0) == pytest.approx(1.0)
