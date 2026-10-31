"""KPI formulas (M4-DESIGN 9; T-F14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from superplanner.mfg import kpi as K
from superplanner.mfg.floor import engine as E

T0 = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)


def t(m: float) -> datetime:
    return T0 + timedelta(minutes=m)


def test_t_f14_adherence_fpy_oee_by_hand():
    rows = []
    for i in range(10):          # 7 started within 120 min and done by plan end + 120
        ps, pe = t(i * 60), t(i * 60 + 300)
        if i < 7:
            rows.append((ps, pe, ps + timedelta(minutes=30), pe + timedelta(minutes=60)))
        elif i == 7:
            rows.append((ps, pe, ps + timedelta(minutes=200), pe))           # started too late
        elif i == 8:
            rows.append((ps, pe, ps, pe + timedelta(minutes=200)))           # finished too late
        else:
            rows.append((ps, pe, None, None))                                # not started
    n, d = K.adherence(rows, 120)
    assert (n, d) == (7, 10) and K.ratio(n, d) == 0.7
    fn, fd = K.fpy(good=97, rework_in=0, scrap=2, rework_out=1)
    assert K.ratio(fn, fd) == 0.97
    assert K.oee(0.9, 0.8, 0.97) == pytest.approx(0.9 * 0.8 * 0.97)
    assert K.oee(None, 0.8, 0.9) is None
    assert K.standard_minutes(10, 3, "batch", None, 8, 1.0) == 6        # 2 loads x 3 min
    assert K.standard_minutes(10, 2, "unit", None, None, 2.0) == 10


def test_work_intervals_from_events():
    evs = [E.Ev("1", 1, "setup_start", t(0), "L1"), E.Ev("2", 2, "start", t(20)),
           E.Ev("3", 3, "pause", t(50), reason_code=None) if False else E.Ev("3", 3, "pause", t(50)),
           E.Ev("4", 4, "resume", t(60)), E.Ev("5", 5, "complete", t(90), qty_good=5)]
    ivs = K.work_intervals(evs, op_id="o")
    assert [(i.kind, (i.end - i.start).total_seconds() / 60) for i in ivs] == \
        [("setup", 20), ("running", 30), ("running", 30)]
    assert {i.line_id for i in ivs} == {"L1"}
    open_ = K.work_intervals(evs[:2], op_id="o", until=t(45))
    assert open_[-1].kind == "running" and open_[-1].end == t(45)
    assert K.clip_minutes(t(0), t(100), t(30), t(60)) == 30
