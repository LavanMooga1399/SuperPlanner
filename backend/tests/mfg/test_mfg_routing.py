"""Routings and operation time (M1-DESIGN 4.4, 4.5; T-T1, T-Q1 lot inputs)."""

from __future__ import annotations

from datetime import date

import pytest

from mfgpure_helpers import AS_OF, Builder, by_code, ds_of, item, line, op
from superplanner.mfg import (cumulative_yield, effective_routings, eligible_lines, lot_inputs, operation_minutes,
                              primary_routing, time_preview, to_engine_minutes)
from superplanner.mfg.model import OperationRecord

GID = "wcg_" + "0" * 32


def _op(**kw) -> OperationRecord:
    base = {"id": "opr_" + "1" * 32, "seq": 10, "name": "x", "group_id": GID,
            "group": {"id": GID, "code": "G", "name": "G"}}
    return OperationRecord.model_validate({**base, **kw})


def test_tt1_panel_time_on_a_slow_line():
    t = operation_minutes(_op(setup_minutes=45, run_minutes=1.2, run_per="panel", units_per_panel=4), 250, 0.7)
    assert t.loads == 63
    assert round(t.run, 6) == 108.0 and round(t.total, 6) == 153.0 and t.setup == 45


def test_unit_and_batch_loads_and_speed():
    assert operation_minutes(_op(run_minutes=2), 10).model_dump() == {"setup": 0.0, "run": 20.0, "total": 20.0,
                                                                     "loads": 10.0}
    t = operation_minutes(_op(setup_minutes=5, run_minutes=30, run_per="batch", units_per_batch=20), 41, 2.0)
    assert t.loads == 3 and t.run == 45.0 and t.total == 50.0
    assert operation_minutes(_op(run_minutes=30, run_per="batch", units_per_batch=20), 40).loads == 2  # exact fit


def _tq1_ops():
    return [_op(seq=10, yield_pct=100), _op(id="opr_" + "2" * 32, seq=20, yield_pct=97),
            _op(id="opr_" + "3" * 32, seq=30, yield_pct=98)]


def test_tq1_lot_inputs_and_cumulative_yield():
    ops = _tq1_ops()
    assert lot_inputs(ops, 100, True) == [107.0, 107.0, 103.0]
    cont = lot_inputs(ops, 100, False)
    assert cont[2] == pytest.approx(100 / 0.98) and cont[0] == pytest.approx(100 / 0.9506)
    assert cumulative_yield(ops) == pytest.approx(0.9506)
    assert cumulative_yield(ops, 30) == pytest.approx(0.98)
    assert cumulative_yield(ops, 77) == pytest.approx(0.9506)
    assert lot_inputs(list(reversed(ops)), 100, True) == [107.0, 107.0, 103.0]       # sorted by seq


@pytest.mark.parametrize("x,n", [(0, 0), (1.0, 1), (1.0000000001, 1), (1.01, 2), (59.5, 60)])
def test_to_engine_minutes(x, n):
    assert to_engine_minutes(x) == n


def _plant() -> Builder:
    b = Builder()
    b.plant("P")
    b.item("P", "make", "Board", family="HDI")
    b.item("Q", "make", "Other", family="STD")
    b.item("C", "buy", "C", lead_time_days=1)
    b.bom("P", [line(10, "C", 1)])
    b.group("G", "Stage")
    b.line("L1", "G", "Fast", speed_factor=1.0)
    b.line("L2", "G", "Slow", speed_factor=0.5, eligible_families=["STD"])
    b.line("L3", "G", "Item list", eligible_part_numbers=["P"])
    b.line("L4", "G", "Inactive", active=False)
    return b


def test_eligible_lines():
    ds = ds_of(_plant())
    g = by_code(ds, "G").id
    assert [ln.code for ln in eligible_lines(ds, g, item(ds, "P"))] == ["L1", "L3"]
    assert [ln.code for ln in eligible_lines(ds, g, item(ds, "Q"))] == ["L1", "L2"]


def test_effective_routings_per_priority():
    b = _plant()
    b.routing("P", [op(10, "a", "G", run_minutes=1)], code="STD", version=1)
    b.routing("P", [op(10, "a", "G", run_minutes=2)], code="STD", version=2, effective_from=date(2026, 6, 1))
    b.routing("P", [op(10, "alt", "G", run_minutes=3)], code="ALT", priority=2)
    b.routing("P", [op(10, "draft", "G", run_minutes=3)], code="DRF", status="draft")
    ds = ds_of(b)
    rs = effective_routings(ds, item(ds, "P").id, AS_OF)
    assert [(r.code, r.version, r.priority) for r in rs] == [("STD", 2, 1), ("ALT", 1, 2)]
    assert primary_routing(ds, item(ds, "P").id, date(2026, 3, 1)).version == 1
    assert primary_routing(ds, item(ds, "Q").id, AS_OF) is None


def test_time_preview():
    b = _plant()
    b.routing("P", [op(10, "SMT", "G", setup_minutes=45, run_minutes=1.2, run_per="panel", units_per_panel=4,
                       move_minutes=5),
                    op(20, "Test", "G", run_minutes=2, yield_pct=98, queue_minutes=10)])
    ds = ds_of(b)
    r = ds.routings_by_item[item(ds, "P").id][0]
    tp = time_preview(ds, r.id, 250)
    o1, o2 = tp.operations
    assert (o1.input_qty, o1.output_qty, o1.loads) == (256.0, 256.0, 64.0)
    assert (o2.input_qty, o2.output_qty) == (256.0, 250.0)
    lines = {ln.code: ln for ln in o1.lines}
    assert set(lines) == {"L1", "L2", "L3"}                                      # active lines only
    assert lines["L2"].eligible is False and lines["L2"].reason == "family HDI not eligible"
    assert lines["L1"].run_minutes == round(1.2 * 64, 6) and lines["L1"].reason is None
    assert tp.totals.fastest_minutes == round(45 + 1.2 * 64 + 2 * 256, 6)
    assert tp.totals.passive_minutes == 15 and tp.totals.cumulative_yield == 0.98
    assert tp.uom == "EA" and tp.qty == 250.0
