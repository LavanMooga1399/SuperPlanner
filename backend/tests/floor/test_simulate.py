"""Risk-run sampling (M4-DESIGN 8; T-F15 at the sampling level)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from superplanner.mfg.aps.simulate import RiskInputs, draw

AS_OF = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)


def _inputs(hist):
    return RiskInputs({"psc_1": "sup_a", "psc_2": "sup_b"}, {"sup_a": hist}, {"lin_1": [5.0, 3.0]},
                      {"lin_1": 400.0})


def test_t_f15_supplier_delays_follow_the_history_and_are_seeded():
    inp = _inputs([0, 7, 14, 0, 7, 14])
    a = draw(random.Random(42), inp, ["psc_1", "psc_2"], AS_OF, 24 * 42)
    b = draw(random.Random(42), inp, ["psc_1", "psc_2"], AS_OF, 24 * 42)
    assert a == b
    days = []
    for i in range(3000):
        delays, _b, _l = draw(random.Random(i), inp, ["psc_1"], AS_OF, 1)
        days.append(delays[0].days if delays else 0)
    p_on_time = days.count(0) / len(days)          # hand value: 1/3 of the history is on time
    assert abs(p_on_time - 1 / 3) < 0.03 and set(days) == {0, 7, 14}


def test_plant_wide_fallback_and_no_history():
    few = _inputs([7, 7])                           # < 5 receipts: plant-wide distribution (here the same)
    d, _b, _l = draw(random.Random(1), few, ["psc_2"], AS_OF, 1)
    assert [x.days for x in d] == [7]
    none = RiskInputs({}, {}, {}, {})
    assert draw(random.Random(1), none, ["psc_1"], AS_OF, 100) == ([], [], {})


def test_breakdowns_mtbf_and_lost_hours():
    inp = _inputs([0] * 5)
    tot = 0.0
    for i in range(500):
        _d, brk, lost = draw(random.Random(i), inp, [], AS_OF, 1000)
        tot += lost.get("lin_1", 0.0)
        assert all(b.line_id == "lin_1" and b.hours in (5.0, 3.0) for b in brk)
    assert 5 < tot / 500 < 30                       # MTBF 200 h over 1000 h: about 5 x 4 h
