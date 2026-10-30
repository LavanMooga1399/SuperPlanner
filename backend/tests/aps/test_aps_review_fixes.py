"""M3 review fix round (pure): M1/M2 freeze vs edits, M4 validator re-derivation, m6 DST, m8 split moves."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from aps_helpers import AS_OF, MON, REG, ds_of, op, ops_of, plant, run, snap, wo
from superplanner.mfg.aps.construct import EditInfeasible
from superplanner.mfg.aps.model import PublishedOp, PublishedView, ScheduleEdit
from superplanner.mfg.aps.validator import validate
from superplanner.mfg.samples.common import H24X7, THREE_SHIFT


def _two_lines():
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("A", "G", "A")
    b.line("B", "G", "B")
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "G")
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    ds = ds_of(b)
    lid = {x.code: x.id for x in ds.lines.values()}
    return ds, lid


def test_m1_m2_move_inside_the_freeze_is_rejected_unless_overridden_and_in_progress_never_moves():
    ds, lid = _two_lines()
    w = wo(ds, "WO-1", "P", 60, MON + timedelta(days=3))
    st = AS_OF + timedelta(hours=10)
    pub = PublishedView("apr_1", 1, (PublishedOp(1, "wo", w.id, 10, 0, 1, 60, lid["A"], st,
                                                 st + timedelta(minutes=60), run_minutes=60),))
    tgt = AS_OF + timedelta(hours=12)
    e = ScheduleEdit(kind="move", op_no=1, line_id=lid["B"], start=tgt)
    mv = {("wo", w.id, 10, 0): (lid["B"], tgt)}
    with pytest.raises(EditInfeasible) as ex:
        run(snap(ds, [w], published=pub, edits=(e,), moves=mv), edits=[e])
    assert ex.value.code == "APS_EDIT_FROZEN"
    s = snap(ds, [w], published=pub, edits=(e,), moves=mv, override_freeze=True)
    r = run(s, edits=[e])
    (o,) = ops_of(r, "WO-1")
    assert o.line_id == lid["B"] and o.start == tgt and o.locked and not o.frozen and r.validation.ok
    # a line-only move (hint) of a frozen op is rejected too
    e2 = ScheduleEdit(kind="move", op_no=1, line_id=lid["B"])
    with pytest.raises(EditInfeasible):
        run(snap(ds, [w], published=pub, edits=(e2,), moves={("wo", w.id, 10, 0): (lid["B"], None)}), edits=[e2])
    # in progress at as_of: never released, even with override_freeze
    st2 = AS_OF - timedelta(minutes=10)
    pub2 = PublishedView("apr_1", 1, (PublishedOp(1, "wo", w.id, 10, 0, 1, 60, lid["A"], st2,
                                                  st2 + timedelta(minutes=60), run_minutes=60),))
    with pytest.raises(EditInfeasible) as ex:
        run(snap(ds, [w], published=pub2, edits=(e,), moves=mv, override_freeze=True), edits=[e])
    assert ex.value.code == "APS_EDIT_FROZEN"
    # the validator checks the move was placed as requested
    r2 = r.model_copy(deep=True)
    (o2,) = ops_of(r2, "WO-1")
    o2.line_id = lid["A"]
    assert "APS_V_EDIT" in validate(s, r2).counts


def test_m8_moving_one_part_of_a_split_operation():
    ds, lid = _two_lines()
    w = wo(ds, "WO-1", "P", 400, MON, priority=1)
    s0 = snap(ds, [w])
    base = run(s0)
    parts = ops_of(base, "WO-1")
    assert len(parts) == 2
    p0, p1 = parts
    tgt = p1.start + timedelta(hours=1)
    locked = {("wo", w.id, 10, 0): PublishedOp(1, "wo", w.id, 10, 0, 2, p0.qty, p0.line_id, p0.start, p0.end,
                                               pieces=tuple((x.start, x.end) for x in p0.pieces),
                                               run_minutes=p0.run_minutes)}
    e = ScheduleEdit(kind="move", op_no=2, start=tgt)
    s = snap(ds, [w], edits=(e,), locked=locked, moves={("wo", w.id, 10, 1): (p1.line_id, tgt, p1.qty, 2)})
    r = run(s, edits=[e])
    q0, q1 = ops_of(r, "WO-1")
    assert (q0.start, q0.line_id) == (p0.start, p0.line_id) and q1.start == tgt and q1.split.count == 2
    assert r.validation.ok, r.validation.violations
    bad = snap(ds, [w], edits=(e,), locked=locked, moves={("wo", w.id, 10, 1): (p0.line_id, p0.start, p1.qty, 2)})
    with pytest.raises(EditInfeasible) as ex:
        run(bad, edits=[e])
    assert ex.value.code == "APS_EDIT_SPLIT"


def _crew_plant():
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G1", "One")
    b.group("G2", "Two")
    b.line("A", "G1", "A")
    b.line("B", "G2", "B")
    b.line("C", "G2", "C")
    b.template("T", "Shifts", REG)
    b.assign("T", "group", "G1")
    b.assign("T", "group", "G2")
    b.skill("S", "Skill")
    for c in ("O1", "O2", "O3"):
        b.operator(c, c, ["S"], "T")
    b.tool("FIX", "Fixture", 1)
    b.routing("P", [op(10, "First", "G1", setup_minutes=0, run_minutes=1, skill_code="S", tools=["FIX"]),
                    op(20, "Second", "G2", setup_minutes=0, run_minutes=1, skill_code="S")])
    ds = ds_of(b)
    return ds, snap(ds, [wo(ds, f"WO-{i}", "P", 30, MON + timedelta(days=3)) for i in range(3)])


def test_m4_validator_rederives_freeze_tools_quantities_presence_and_non_adjacent_double_booking():
    ds, s = _crew_plant()
    base = run(s)
    assert base.validation.ok

    def counts(fn):
        r = base.model_copy(deep=True)
        fn(r)
        return validate(s, r).counts

    def frz(r):                     # frozen flag without a published plan hides nothing
        o = r.operations[0]
        d = timedelta(hours=10)
        o.start, o.end = o.start + d, o.end + d
        for p in o.pieces + o.crew:
            p.start, p.end = p.start + d, p.end + d
        o.frozen = True
    assert {"APS_V_FROZEN", "APS_V_WINDOW"} <= set(counts(frz))

    def notool(r):
        next(o for o in r.operations if o.seq == 10).tools = []
    assert "APS_V_TOOL" in counts(notool)

    def lessqty(r):
        o = r.operations[0]
        o.qty = 1
    assert "APS_V_QTY" in counts(lessqty)

    def drop(r):
        r.operations.remove(next(o for o in r.operations if o.seq == 20))
    assert "APS_V_MISSING" in counts(drop)

    def dbl(r):                     # X 0-100, Y 10-20 (other line), Z 30-40: Z overlaps X, not adjacent to it
        x, y, z = sorted((o for o in r.operations if o.seq == 20), key=lambda o: o.start)[:3]
        emp, t0 = x.crew[0].operator_id, x.start
        other = next(i for i, ln in ds.lines.items() if ln.group_id == ds.lines[x.line_id].group_id and i != x.line_id)
        for o, a, b, line in ((x, 0, 100, x.line_id), (y, 10, 20, other), (z, 30, 40, other)):
            o.start, o.end, o.line_id = t0 + timedelta(minutes=a), t0 + timedelta(minutes=b), line
            o.pieces = [o.pieces[0].model_copy(update={"start": o.start, "end": o.end})]
            o.crew = [o.crew[0].model_copy(update={"operator_id": emp, "start": o.start, "end": o.end})]
    assert counts(dbl).get("APS_V_CREW_DOUBLE", 0) >= 2

    def ot(r):                      # opened optional time in an off run
        from superplanner.mfg.aps.model import OvertimeWindow

        r.overtime.append(OvertimeWindow(line_id=r.operations[0].line_id, assignment_id=None, start=AS_OF,
                                         end=AS_OF + timedelta(hours=1), minutes=60, cost=0, status="opened"))
    assert "APS_V_OVERTIME_POLICY" in counts(ot)


def test_m6_absence_in_the_dst_fall_back_hour():
    ber = ZoneInfo("Europe/Berlin")
    b = plant(tz="Europe/Berlin")
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.template("T3", "3 shifts", THREE_SHIFT)
    b.assign("T3", "group", "G")
    b.skill("S", "Skill")
    b.operator("O1", "Night", ["S"], "T3", ["C"])
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, skill_code="S")])
    ds = ds_of(b)
    # the second 02:xx (CET) of 25 Oct 2026: 01:00-01:30 UTC
    a0, a1 = datetime(2026, 10, 25, 1, 0, tzinfo=UTC), datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    from superplanner.mfg.model_m3 import OperatorAbsenceRecord

    emp = next(iter(ds.operators.values()))
    ds.operator_absences["oab_1"] = OperatorAbsenceRecord.model_construct(
        id="oab_1", operator_id=emp.id, start=a0, end=a1, kind="leave", note="", row_version=1, created_at=a0,
        updated_at=a0, operator=None)
    as_of = datetime(2026, 10, 24, 22, 0, tzinfo=ber)
    r = run(snap(ds, [wo(ds, "WO-1", "P", 400, datetime(2026, 10, 30).date())], as_of=as_of))
    (o,) = ops_of(r, "WO-1")
    assert not any(c.start < a1 and a0 < c.end for c in o.crew) and r.validation.ok
