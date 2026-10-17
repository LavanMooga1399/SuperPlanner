"""PHASE2 1.5: the cautious-planning margin of the planning return (properties, table, ranking, settings)."""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest
from pydantic import ValidationError

from superplanner.finance import Assumptions, CautionSettings
from superplanner.finance.model import AssetClass
from superplanner.finance.returns import planning_return, planning_rho, real_annual, real_volatility

ND = NormalDist()
A = Assumptions()
CL = {c.id: c for c in A.asset_classes}
PI = A.inflation_pct / 100
IV = A.inflation_volatility_pct / 100
C = A.caution
Z0 = ND.inv_cdf(0.85)
SAFE = ("cash", "fixed_deposit", "short_debt", "govt_long")


def pr(cid: str, z: float, years: float, z0: float = Z0, caution: CautionSettings = C) -> float:
    return planning_return(CL[cid], PI, z, round(years * 12), IV, z0=z0, caution=caution)


def old_formula(ac: AssetClass, z: float, D: int) -> float:
    """FINANCE 8.2 as amended in F.24.3 (the rule before PHASE2), written out independently."""
    Y = max(1.0, D / 12)
    R = real_annual(ac, PI)
    sig = real_volatility(ac, IV)
    if sig <= 0:
        return max(-0.5, R)
    s = math.sqrt(math.log(1 + (sig / (1 + R)) ** 2))
    return max(-0.5, (1 + R) * math.exp(-s * s / 2 - z * s / math.sqrt(Y)) - 1)


# PHASE2 1.5 table (percent), must caution z0 = 1.036 and z0 + 0.5
TABLE = {
    3: (0.33, 0.56, -5.60, -0.18, 0.11, -10.10, -7.13),
    5: (0.57, 0.77, 0.64, -0.08, 0.14, 0.35, 0.20),
    7: (0.70, 0.89, 1.28, -0.17, 0.02, 0.70, 0.39),
    10: (0.82, 0.99, 2.23, -0.30, -0.25, 1.23, 0.69),
    25: (1.03, 1.18, 2.23, -0.15, 0.02, 1.23, 0.69),
}


@pytest.mark.parametrize("years", sorted(TABLE))
def test_design_table_to_a_hundredth_of_a_point(years):
    cols = [("fixed_deposit", Z0), ("govt_long", Z0), ("equity_index", Z0), ("fixed_deposit", Z0 + 0.5),
            ("govt_long", Z0 + 0.5), ("equity_index", Z0 + 0.5), ("gold", Z0)]
    got = [round(pr(c, z, years) * 100, 2) for c, z in cols]
    assert got == pytest.approx(list(TABLE[years]), abs=0.0051)


def test_zero_volatility_is_exactly_the_expected_real_return():
    ac = AssetClass(id="d", name="D", category="debt", expected_return_pct=8.0, volatility_pct=0.0)
    for z, D in [(0.0, 12), (2.5, 300), (Z0, 120)]:
        assert planning_return(ac, PI, z, D, 0.0, z0=Z0, caution=C) == real_annual(ac, PI)


@pytest.mark.parametrize("cid", list(CL))
def test_floor_share_zero_gives_the_old_values(cid):
    off = CautionSettings(floor_share=0)
    for D in (12, 36, 60, 120, 300, 480):
        for z in (0.0, Z0, Z0 + 0.75, 2.5):
            assert planning_return(CL[cid], PI, z, D, IV, z0=Z0, caution=off) == pytest.approx(
                old_formula(CL[cid], z, D), abs=1e-12)


@pytest.mark.parametrize("cid", list(CL))
def test_up_to_three_years_is_exactly_the_old_value(cid):
    for D in (1, 12, 24, 36):
        for z in (Z0, Z0 + 1.0):
            assert pr(cid, z, D / 12) == old_formula(CL[cid], z, D)


@pytest.mark.parametrize("cid", list(CL))
def test_non_increasing_in_z(cid):
    for years in (2, 5, 10, 25):
        vals = [pr(cid, Z0 + k * 0.25, years) for k in range(9)]
        assert all(b <= a + 1e-15 for a, b in zip(vals, vals[1:])), vals


@pytest.mark.parametrize("cid", list(CL))
def test_continuous_and_non_decreasing_in_years_at_z0(cid):
    vals = [planning_return(CL[cid], PI, Z0, D, IV, z0=Z0, caution=C) for D in range(12, 481)]
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))
    # continuous once the floor is phased in (from just above floor_start_years); at floor_start_years itself a
    # class whose honest quantile is negative steps up to about 0 (max(q, phi * med) with phi > 0, PHASE2 9.P1)
    after = vals[37 - 12:]
    assert max(abs(b - a) for a, b in zip(after, after[1:])) < 0.01
    # the calibration penalty itself is continuous at floor_start_years (ramp = 0 there)
    for z in (Z0, Z0 + 0.5, Z0 + 1.0):
        off = CautionSettings(floor_share=1e-9)
        left = planning_return(CL[cid], PI, z, 36, IV, z0=Z0, caution=off)
        right = planning_return(CL[cid], PI, z, 37, IV, z0=Z0, caution=off)
        assert right >= left - 0.01


def test_step_at_floor_start_is_upwards_and_keeps_short_goals_on_safe_classes():
    """Recorded in PHASE2 9.P1: the floor makes the value jump up just after 3 years, but at that distance every
    growth class stays below the best safe class, so the LP's choice does not change."""
    for D in range(37, 61):
        eq = planning_return(CL["equity_index"], PI, Z0, D, IV, z0=Z0, caution=C)
        gold = planning_return(CL["gold"], PI, Z0, D, IV, z0=Z0, caution=C)
        best_safe = max(planning_return(CL[c], PI, Z0, D, IV, z0=Z0, caution=C) for c in SAFE)
        assert eq < best_safe and gold < best_safe, D


@pytest.mark.parametrize("cid", ["equity_index", "gold", "fixed_deposit", "govt_long"])
def test_floor_at_half_the_median_from_ten_years(cid):
    ac = CL[cid]
    R = real_annual(ac, PI)
    s = math.sqrt(math.log(1 + (real_volatility(ac, IV) / (1 + R)) ** 2))
    med = (1 + R) * math.exp(-s * s / 2) - 1
    for years in (10, 15, 25, 35):
        assert pr(cid, Z0, years) >= 0.5 * med - 1e-12


@pytest.mark.parametrize("p", [0.5, 0.7, 0.85, 0.95, 0.99])
@pytest.mark.parametrize("years", [10, 15, 25, 35])
def test_equity_beats_every_safe_class_at_every_calibration_level(p, years):
    z0 = ND.inv_cdf(p)
    gap0 = pr("equity_index", z0, years, z0=z0) - max(pr(c, z0, years, z0=z0) for c in SAFE)
    for dz in (0.0, 0.25, 0.5, 0.75, 1.0):
        z = z0 + dz
        gap = pr("equity_index", z, years, z0=z0) - max(pr(c, z, years, z0=z0) for c in SAFE)
        assert gap >= 0.0025, (p, years, dz, gap)
        if p >= 0.85:
            # equity sits on its floor from z0 on, so the common shift keeps (or widens) its lead
            assert gap >= gap0 - 1e-12


def test_each_calibration_step_lowers_every_class_by_at_least_the_common_shift():
    """A step of +0.25 z subtracts 0.5 pp x ramp(Y) from every class (2.0 pp per unit of z); the honest quantile
    can fall further, so the drop is at least the shift (PHASE2 9.P1)."""
    from superplanner.finance.returns import caution_ramp
    for cid in CL:
        if CL[cid].volatility_pct == 0:
            continue
        for years in (5, 10, 25):
            shift = 0.005 * caution_ramp(C, years)
            for k in range(4):
                a, b = pr(cid, Z0 + 0.25 * k, years), pr(cid, Z0 + 0.25 * (k + 1), years)
                assert a - b >= shift - 1e-12


def test_planning_rho_matches_planning_return():
    for cid in CL:
        v = pr(cid, Z0 + 0.25, 12)
        assert planning_rho(CL[cid], PI, Z0 + 0.25, 144, IV, z0=Z0, caution=C) == pytest.approx((1 + v) ** (1 / 12))


def test_keyword_arguments_are_required():
    with pytest.raises(TypeError):
        planning_return(CL["equity_index"], PI, Z0, 120, IV)        # type: ignore[call-arg]
    with pytest.raises(TypeError):
        planning_rho(CL["equity_index"], PI, Z0, 120, IV, Z0, C)    # type: ignore[misc]


def test_caution_settings_defaults_and_validation():
    c = CautionSettings()
    assert (c.floor_share, c.floor_start_years, c.floor_full_years, c.floor_step_pct_per_z) == (0.5, 3.0, 10.0, 2.0)
    assert Assumptions().caution == c
    for bad in (dict(floor_share=1.1), dict(floor_share=-0.1), dict(floor_start_years=-1),
                dict(floor_full_years=0.2), dict(floor_step_pct_per_z=11), dict(floor_start_years=10,
                                                                                floor_full_years=10),
                dict(floor_start_years=12, floor_full_years=10), dict(unknown=1)):
        with pytest.raises(ValidationError):
            CautionSettings(**bad)
    # stored documents without the field get the defaults
    doc = Assumptions().model_dump()
    doc.pop("caution")
    assert Assumptions.model_validate(doc).caution == c
