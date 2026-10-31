"""Pure floor rules (M4-DESIGN 4.2; T-F1..T-F3 at engine level) and the barcode grammar (5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from superplanner.mfg import scan
from superplanner.mfg.floor import engine as E

T0 = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)


def ev(n: int, t: str, m: float, **kw) -> E.Ev:
    return E.Ev(f"e{n}", n, t, T0 + timedelta(minutes=m), **kw)


def test_t_f1_replay_quantities_yield_and_minutes():
    st = E.replay([ev(1, "start", 0, operators=2), ev(2, "report", 60, qty_good=40, qty_scrap=2),
                   ev(3, "pause", 70), ev(4, "resume", 100, operators=1),
                   ev(5, "complete", 130, qty_good=55, qty_scrap=3)])
    assert (st.status, st.qty_good, st.qty_scrap) == ("completed", 95, 5)
    assert st.qty_good / (st.qty_good + st.qty_scrap) == 0.95
    assert st.run_minutes == 100 and st.labour_minutes == 70 * 2 + 30 * 1
    assert st.actual_start == T0 and st.actual_end == T0 + timedelta(minutes=130)


def test_setup_time_and_resume_returns_to_the_state_before_the_pause():
    st = E.replay([ev(1, "setup_start", 0), ev(2, "pause", 10), ev(3, "resume", 20)])
    assert st.status == "setup"
    st = E.replay([ev(1, "setup_start", 0), ev(2, "pause", 10), ev(3, "resume", 20), ev(4, "start", 25),
                   ev(5, "complete", 85)])
    assert (st.setup_minutes, st.run_minutes) == (15, 60)


def test_invalid_transitions():
    with pytest.raises(E.FloorRuleError) as ei:
        E.replay([ev(1, "start", 0), ev(2, "complete", 5), ev(3, "start", 6)])
    assert ei.value.code == "FLR_INVALID_TRANSITION" and ei.value.details["allowed"] == ["reopen", "correct"]
    with pytest.raises(E.FloorRuleError):
        E.replay([ev(1, "pause", 0)])
    assert E.replay([ev(1, "skip", 0)]).status == "skipped"


def test_t_f2_chain_check():
    view = E.chain([E.ChainOp(10, "running", 100)])[10]
    with pytest.raises(E.FloorRuleError) as ei:
        E.check_quantities(view, 96, 5, 0, forced=False)
    assert ei.value.code == "FLR_QTY_EXCEEDS_INPUT"
    E.check_quantities(view, 96, 5, 0, forced=True)


def test_t_f3_rework_reopens_the_target_and_inputs_follow():
    st10 = E.replay([ev(1, "start", 0), ev(2, "complete", 10, qty_good=100)],
                    [E.Ev("rw", 9, "rework_in", T0 + timedelta(minutes=90), qty_rework=4)])
    assert (st10.status, st10.qty_rework_in) == ("paused", 4)
    ops = [E.ChainOp(10, "paused", 100, 100, 0, 0, 4), E.ChainOp(20, "completed", 100, 100),
           E.ChainOp(30, "completed", 100, 100), E.ChainOp(40, "running", 100, 96, 0, 4)]
    ch = E.chain(ops)
    assert ch[10].qty_available == 4 and ch[40].qty_available == 0 and ch[20].qty_input == 100


def test_correction_replaces_quantities_and_skipped_ops_pass_input():
    st = E.replay([ev(1, "start", 0), ev(2, "report", 10, qty_good=40),
                   ev(3, "correct", 20, qty_good=38, corrects_event_id="e2", fields=("qty_good",))])
    assert st.qty_good == 38 and st.status == "running"
    ch = E.chain([E.ChainOp(10, "completed", 10, 9, 1), E.ChainOp(20, "skipped", 9), E.ChainOp(30, "pending", 9)])
    assert ch[30].qty_input == 9 and ch[30].ready


def test_backflush_target_and_shortfall():
    assert E.backflush_target(10, 40, 10, True) == 40
    assert E.backflush_target(3, 10, 7, True) == 5            # 4.29 -> 5 (count UoM rounds up)
    assert E.backflush_target(3, 10, 7, False) == pytest.approx(4.285714, abs=1e-6)
    assert not E.shortfall(10, [E.ChainOp(10, "running", 11, 0, 1)])
    assert E.shortfall(10, [E.ChainOp(10, "running", 11, 0, 1), E.ChainOp(20, "running", 10, 0, 1)])


def test_scan_grammar():
    assert scan.parse("WO-000143/30")[0] == scan.Lookup("operation", ("WO-000143", "30"))
    assert scan.parse("  wo-000143\r\n")[0] == scan.Lookup("work_order", ("wo-000143",))
    assert scan.parse("l:KV-R-10K:LOT 7") == [scan.Lookup("lot", ("KV-R-10K", "LOT 7"))]
    assert scan.parse("S:KV-TPU:TPU-1") == [scan.Lookup("serial", ("KV-TPU", "TPU-1"))]
    assert scan.parse("loc:LS-SMT") == [scan.Lookup("location", ("LS-SMT",))]
    assert scan.parse("LIN:SMT-1") == [scan.Lookup("line", ("SMT-1",))]
    assert scan.parse("op:OP-7") == [scan.Lookup("operator", ("OP-7",))]
    assert scan.parse("BL:00ab12cd") == [scan.Lookup("batch_load", ("00ab12cd",))]
    assert scan.parse("S:broken") == [] and scan.parse("") == []
