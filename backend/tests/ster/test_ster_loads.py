"""Sterilisation load planner and validator (M8-DESIGN 8; pure)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from superplanner.mfg.ster.loads import plan
from superplanner.mfg.ster.model import AerationRoom, Chamber, SterCandidate
from superplanner.mfg.ster.validator import validate

T = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)


def cand(key, pallets, ready_h=0.0, code="ETO", pallet_qty=1000.0, **kw):
    return SterCandidate(key=key, item_id="itm_" + key, qty=pallets * (pallet_qty or 1000.0), ready=T + timedelta(hours=ready_h),
                         cycle_code=code, pallet_qty=pallet_qty, aeration_hours=kw.pop("aer", 48.0),
                         release_mode=kw.pop("mode", "bi"), release_days=kw.pop("rel", 7.0), **kw)


CH = Chamber("lin_eto1", "ETO-01", 24, 14.0)


@pytest.mark.req("M8-STER-01")
def test_thirty_pallets_two_loads_and_aeration_bound():
    room = AerationRoom("lin_aer", "AER-1", 24)
    p = plan([cand("a", 20), cand("b", 10, 1.0)], [CH], [room], max_wait_hours=8)
    assert p.validator["ok"], p.validator
    assert [ld.pallets for ld in p.loads] == [20, 10]
    first, second = p.loads
    assert first.start == T + timedelta(hours=0) or first.start >= T
    # chamber free after 14 h, but the room (24 positions) holds 20 pallets for 48 h: 10 more do not fit
    assert second.start >= first.aeration_end - timedelta(hours=14)
    assert "STER_AERATION_BOUND" in second.flags and p.warnings[0]["code"] == "STER_AERATION_BOUND"
    assert first.release_due == (first.aeration_end + timedelta(days=7)).date()
    # with a large room the second load only waits for the chamber
    p2 = plan([cand("a", 20), cand("b", 10, 1.0)], [CH], [AerationRoom("lin_aer", "AER-1", 96)], max_wait_hours=8)
    assert p2.loads[1].start == p2.loads[0].end and not p2.loads[1].flags


def test_split_big_candidate_wait_close_no_pallet_and_cycle_codes():
    p = plan([cand("big", 30)], [CH], [], max_wait_hours=8)
    assert [ld.pallets for ld in p.loads] == [24, 6]
    assert sum(m.qty for ld in p.loads for m in ld.members) == pytest.approx(30_000)
    # second candidate ready 10 h after the first (> 8 h wait) -> separate loads
    p = plan([cand("a", 5), cand("b", 5, 10.0)], [CH], [], max_wait_hours=8)
    assert len(p.loads) == 2
    p = plan([cand("a", 5), cand("b", 5, 2.0)], [CH], [], max_wait_hours=8)
    assert len(p.loads) == 1 and p.loads[0].start == T + timedelta(hours=2)
    p = plan([cand("x", 5, pallet_qty=None)], [CH], [], max_wait_hours=8)
    assert p.skipped == [{"key": "x", "item_id": "itm_x", "code": "STER_NO_PALLET"}]
    p = plan([cand("a", 5, code="ETO"), cand("b", 5, code="GAMMA")], [CH, Chamber("lin_g", "GAM", 10, 5.0,
                                                                                    frozenset({"GAMMA"}))],
             [], max_wait_hours=8)
    assert {(ld.cycle_code, ld.chamber_id) for ld in p.loads} == {("ETO", "lin_eto1"), ("GAMMA", "lin_g")}


def test_validator_catches_overload_and_overlap():
    room = AerationRoom("lin_aer", "AER-1", 24)
    p = plan([cand("a", 20), cand("b", 10, 1.0)], [CH], [room], max_wait_hours=8)
    loads = p.loads
    loads[1].start, loads[1].end = loads[0].start, loads[0].end
    loads[1].aeration_end = loads[0].aeration_end
    codes = {v["code"] for v in validate(loads, [CH], [room], {}, {}, {})["violations"]}
    assert {"STER_V_OVERLAP", "STER_V_AERATION_CAPACITY"} <= codes
