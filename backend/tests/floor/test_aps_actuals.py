"""APS with actuals (M4-DESIGN 6.1; T-F9, T-F10) on the pure Kavach sample: downtime moves frozen work
(`moved_by_downtime`), running operations are planned first on their line with the remaining quantity, what-if
breakdowns / supply delays; every result is validator-clean."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from superplanner.mfg.aps.actuals import ActualOp, Downtime
from superplanner.mfg.aps.engine import schedule
from superplanner.mfg.aps.model import ApsParams, LineBreakdown, PublishedOp, PublishedView
from superplanner.mfg.aps.pure import sample_snapshot

P = ApsParams(improve_seconds=0, split=False)   # (frozen split parts: M3 behaviour, not under test here)


@pytest.fixture(scope="module")
def base():
    snap = sample_snapshot("kavach")
    res = schedule(snap, P)
    assert res.validation.ok
    return snap, res


def _published(res) -> PublishedView:
    ops = tuple(PublishedOp(o.op_no, o.order.type, o.order.id, o.seq, o.split.index, o.split.count, o.qty, o.line_id,
                            o.start, o.end, tuple((c.operator_id, c.start, c.end) for c in o.crew),
                            tuple((p.start, p.end) for p in o.pieces), o.setup_minutes, o.run_minutes)
                for o in res.operations if o.status == "scheduled")
    return PublishedView("apr_pub", 1, ops)


def test_t_f9_downtime_moves_frozen_ops_and_stays_valid(base):
    snap, res = base
    pub = _published(res)
    first = min((o for o in res.operations if o.status == "scheduled" and o.order.type == "wo"),
                key=lambda o: o.start)
    snap2 = replace(snap, published=pub)
    r_frozen = schedule(snap2, P)
    assert r_frozen.validation.ok
    same = next(o for o in r_frozen.operations if (o.order.id, o.seq) == (first.order.id, first.seq))
    assert same.frozen and same.start == first.start
    down = Downtime("dtm_1", first.line_id, snap.as_of - timedelta(minutes=5), None,
                    first.end + timedelta(hours=2), False)
    r = schedule(replace(snap2, downtime=(down,)), P)
    assert r.validation.ok, r.validation
    moved = next(o for o in r.operations if (o.order.id, o.seq) == (first.order.id, first.seq))
    assert moved.moved_by_downtime and not moved.frozen
    assert moved.status != "scheduled" or moved.line_id != first.line_id or moved.start >= down.expected_end
    assert r.summary.moved_by_downtime >= 1 and r.summary.frozen_moved == 0
    on_line = [o for o in r.operations if o.status == "scheduled" and o.line_id == first.line_id]
    assert all(o.end <= down.start or o.start >= down.expected_end for o in on_line)


def test_t_f10_running_op_first_on_its_line_with_the_remaining_quantity(base):
    snap, res = base
    o = next(x for x in res.operations if x.status == "scheduled" and x.order.type == "wo" and x.qty >= 2
             and x.split.count == 1)
    half = o.qty / 2
    a = ActualOp(o.order.id, o.seq, "wop_1", "running", o.line_id, half, snap.as_of - timedelta(minutes=280))
    r = schedule(replace(snap, actuals={(o.order.id, o.seq): a}), P)
    assert r.validation.ok, r.validation
    x = next(y for y in r.operations if (y.order.id, y.seq) == (o.order.id, o.seq))
    assert x.line_id == o.line_id and x.qty == half and x.actual["status"] == "running"
    assert x.frozen and x.reason.code == "in_progress"
    assert r.summary.actual_ops == 1
    first_on_line = min((y for y in r.operations if y.line_id == o.line_id and y.status == "scheduled"),
                        key=lambda y: y.start)
    assert first_on_line.op_no == x.op_no


def test_what_if_breakdown_closes_the_line(base):
    snap, res = base
    o = min((x for x in res.operations if x.status == "scheduled"), key=lambda x: x.start)
    params = P.model_copy(update={"line_breakdowns": [LineBreakdown(line_id=o.line_id, start=snap.as_of,
                                                                    hours=12)]})
    r = schedule(snap, params)
    assert r.kind == "what_if" and r.validation.ok
    end = snap.as_of + timedelta(hours=12)
    assert all(y.start >= end or y.end <= snap.as_of for y in r.operations
               if y.status == "scheduled" and y.line_id == o.line_id)
