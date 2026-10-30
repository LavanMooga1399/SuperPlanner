"""Vectors T-S1..T-S16 (M3-DESIGN 15.1); times in Asia/Kolkata unless stated."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from aps_helpers import (AS_OF, IST, MON, ApsComponent, Builder, MrpPegView, PegSupply, REG, ds_of, local, op,
                         ops_of, plant, run, shift, snap, wo)
from superplanner.mfg.samples.common import ALL_WEEK, H24X7


def _one_line(interruptible: bool = True, tpl=REG) -> Builder:
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.template("T", "Shifts", tpl)
    b.assign("T", "group", "G")
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=6, crew_size=0, labor="unattended", interruptible=interruptible)])
    return b


def test_ts1_interruptible_pieces():
    ds = ds_of(_one_line())
    res = run(snap(ds, [wo(ds, "WO-1", "P", 100, MON + timedelta(days=7))]))
    (o,) = ops_of(res, "WO-1")
    assert [(local(p.start), local(p.end)) for p in o.pieces] == [("Mon 09:00", "Mon 13:00"),
                                                                   ("Mon 13:45", "Mon 18:00"),
                                                                   ("Tue 09:00", "Tue 10:45")]
    assert res.validation.ok, res.validation.violations


def test_ts2_non_interruptible():
    ds = ds_of(_one_line(False))
    res = run(snap(ds, [wo(ds, "WO-1", "P", 100, MON + timedelta(days=7))]))
    (o,) = ops_of(res, "WO-1")
    assert o.status == "unscheduled" and o.reason.code == "no_window"
    ds = ds_of(_one_line(False, H24X7))
    res = run(snap(ds, [wo(ds, "WO-1", "P", 100, MON + timedelta(days=7))]))
    (o,) = ops_of(res, "WO-1")
    assert (local(o.start), local(o.end)) == ("Mon 09:00", "Mon 19:00") and res.validation.ok


def test_ts3_faster_line_then_slower_when_busy():
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.item("Q", "make", "Other", family="F")
    b.group("G", "Stage")
    b.line("FAST", "G", "Fast", speed_factor=1.0)
    b.line("SLOW", "G", "Slow", speed_factor=0.7)
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "G")
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=3, crew_size=0, labor="unattended")])
    b.routing("Q", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    ds = ds_of(b)
    res = run(snap(ds, [wo(ds, "WO-1", "P", 100, MON + timedelta(days=7))]), split=False)
    fast = next(x.id for x in ds.lines.values() if x.code == "FAST")
    assert ops_of(res, "WO-1")[0].line_id == fast
    # FAST busy until +200 (P1 order of 200 x 1 min), WO-2 of 300 min: slower line 429 < 500
    res = run(snap(ds, [wo(ds, "WO-0", "Q", 200, MON + timedelta(days=1), priority=1),
                        wo(ds, "WO-2", "P", 100, MON + timedelta(days=7), priority=9)]), split=False)
    o0, o2 = ops_of(res, "WO-0")[0], ops_of(res, "WO-2")[0]
    assert o0.line_id == fast and o2.line_id != fast and o2.run_minutes == 429 and res.validation.ok


def _rate_plant() -> Builder:
    b = plant()
    b.item("X", "make", "Board X", family="F")
    b.group("SMT", "SMT")
    b.line("SMT-3", "SMT", "SMT 3", speed_factor=0.7)
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "SMT")
    b.routing("X", [op(10, "Place", "SMT", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    b.b["operation_line_rates"].append({"part_number": "X", "seq": 10, "line_code": "SMT-3", "run_minutes": 2.0})
    return b


def test_ts5_line_rate_override_ignores_speed():
    ds = ds_of(_rate_plant())
    res = run(snap(ds, [wo(ds, "WO-1", "X", 50, MON + timedelta(days=7))]))
    (o,) = ops_of(res, "WO-1")
    assert o.run_minutes == 100 and res.validation.ok        # 2.0 x 50 (not / 0.7)


def _crew_plant() -> Builder:
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.template("T", "Shifts", REG)
    b.assign("T", "group", "G")
    b.skill("S", "Skill")
    b.operator("O1", "Only one", ["S"], "T")
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, skill_code="S", crew_size=1)])
    b.b["operator_absences"].append({"operator_code": "O1", "start": datetime(2026, 11, 3, 0, 0),
                                     "end": datetime(2026, 11, 4, 0, 0), "kind": "leave"})
    return b


def test_ts6_crew_absence_pauses_and_validator_rejects_a_move():
    ds = ds_of(_crew_plant())
    res = run(snap(ds, [wo(ds, "WO-1", "P", 600, MON + timedelta(days=7))]))
    (o,) = ops_of(res, "WO-1")
    assert all(p.start.astimezone(IST).date() != date(2026, 11, 3) for p in o.pieces)
    assert o.end.astimezone(IST).date() == date(2026, 11, 4) and res.validation.ok
    assert o.crew and all(c.start.astimezone(IST).date() != date(2026, 11, 3) for c in o.crew)
    # move it to Tuesday: the validator finds the absence
    from superplanner.mfg.aps.validator import validate

    s = snap(ds, [wo(ds, "WO-1", "P", 100, MON + timedelta(days=7))])
    r2 = run(s)
    (o,) = ops_of(r2, "WO-1")
    shift_ = timedelta(days=1)
    o.start, o.end = o.start + shift_, o.end + shift_
    for p in o.pieces + o.crew:
        p.start, p.end = p.start + shift_, p.end + shift_
    v = validate(s, r2)
    assert not v.ok and "APS_V_CREW_SHIFT" in v.counts


def _mat_plant() -> Builder:
    b = _one_line()
    b.item("C", "buy", "Component", lead_time_days=5)
    b.bom("P", [{"find_number": "10", "child_part_number": "C", "qty_per": 1}])
    return b


def test_ts7_material_from_a_po_schedule():
    ds = ds_of(_mat_plant())
    c = ds.items_by_pn["C"]
    w = wo(ds, "WO-1", "P", 10, MON + timedelta(days=7), comps=(ApsComponent("woc_1", c.id, 10, None),))
    mrp = MrpPegView("mrr_1", 1, "live", (), {("wo", w.id, c.id): (PegSupply("po_schedule", "psc_1", "PO-1/10/1", 10,
                                                                            date(2026, 11, 4)),)}, {}, {}, ())
    res = run(snap(ds, [w], mrp=mrp))
    (o,) = ops_of(res, "WO-1")
    assert local(o.start) == "Wed 09:00" and o.reason.code in ("material", "no_window")
    assert o.release.material_at.astimezone(IST) == datetime(2026, 11, 4, tzinfo=IST)
    res = run(snap(ds, [w], mrp=mrp), material="ignore")
    assert local(ops_of(res, "WO-1")[0].start) == "Mon 09:00" and res.kind == "what_if"


def test_ts8_parent_waits_for_child_order():
    b = plant()
    b.item("P", "make", "Parent", family="F")
    b.item("K", "make", "Child", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.line("L2", "G", "Line 2")
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "G")
    b.routing("K", [op(10, "Make", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended",
                       move_minutes=30)])
    b.routing("P", [op(10, "Assemble", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    b.bom("P", [{"find_number": "10", "child_part_number": "K", "qty_per": 1}])
    ds = ds_of(b)
    k = wo(ds, "WO-K", "K", 1800, MON + timedelta(days=3))
    kid = ds.items_by_pn["K"].id
    p = wo(ds, "WO-P", "P", 10, MON + timedelta(days=5), comps=(ApsComponent("woc_k", kid, 10, None),))
    mrp = MrpPegView("mrr_1", 1, "live", (), {("wo", p.id, kid): (PegSupply("work_order", k.id, "WO-K", 10, None),)},
                     {}, {}, ())
    res = run(snap(ds, [k, p], mrp=mrp), split=False)
    ok, op_ = ops_of(res, "WO-K")[0], ops_of(res, "WO-P")[0]
    assert local(ok.end) == "Tue 15:00" and op_.start >= ok.end + timedelta(minutes=30) and res.validation.ok
    assert op_.reason.code == "material"


def test_ts9_transfer_batch_overlap():
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G1", "One")
    b.group("G2", "Two")
    b.line("A", "G1", "A")
    b.line("B", "G2", "B")
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "G1")
    b.assign("T", "group", "G2")
    b.routing("P", [op(10, "First", "G1", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended",
                       transfer_batch=10),
                    op(20, "Second", "G2", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    ds = ds_of(b)
    res = run(snap(ds, [wo(ds, "WO-1", "P", 100, MON + timedelta(days=5))]))
    a, b2 = ops_of(res, "WO-1")
    assert b2.start == a.start + timedelta(minutes=10) and b2.end >= a.end + timedelta(minutes=10) and \
        res.validation.ok


def test_ts10_priority_first_and_weights():
    ds = ds_of(_one_line())
    res = run(snap(ds, [wo(ds, "WO-9", "P", 90, MON + timedelta(days=1), priority=9),
                        wo(ds, "WO-1", "P", 90, MON + timedelta(days=1), priority=1)]))
    o1, o9 = ops_of(res, "WO-1")[0], ops_of(res, "WO-9")[0]
    assert o1.start < o9.start
    w = {o.order.number: o.weight for o in res.orders}
    assert w == {"WO-1": 256.0, "WO-9": 1.0}


def _ot_plant() -> Builder:
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.template("REG", "Regular", REG)
    b.template("EVE", "Evening", [shift("Evening", ["mon", "tue", "wed", "thu", "fri", "sat"], "18:00", "22:00")])
    b.assign("REG", "group", "G")
    b.assign("EVE", "group", "G", kind="optional", cost_per_hour=400, max_hours_per_week=12)
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    return b


def test_ts11_overtime_off_allow_suggest():
    ds = ds_of(_ot_plant())
    s = snap(ds, [wo(ds, "WO-1", "P", 675, MON + timedelta(days=1), priority=5)])
    off = run(s, overtime="off")
    assert off.orders[0].late_minutes == 720 and off.overtime == []
    allow = run(s, overtime="allow")
    assert allow.orders[0].late_minutes == 0 and [(w.status, w.cost, w.minutes) for w in allow.overtime] == \
        [("opened", 1600.0, 240)] and allow.validation.ok
    assert allow.summary.weighted_tardiness < off.summary.weighted_tardiness
    sug = run(s, overtime="suggest")
    assert [o.start for o in sug.operations] == [o.start for o in off.operations]
    (w,) = sug.overtime
    assert w.status == "suggested" and w.tardiness_saved_minutes == 720 * 16 and sug.summary.late_demand_count == 0
    assert any(e.code == "APS_OVERTIME_SUGGESTED" for e in sug.exceptions)


def test_ts12_split_across_two_idle_lines():
    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.line("L2", "G", "Line 2")
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "G")
    b.routing("P", [op(10, "Work", "G", setup_minutes=15, run_minutes=1, crew_size=0, labor="unattended")])
    ds = ds_of(b)
    s = snap(ds, [wo(ds, "WO-1", "P", 400, MON, priority=1)])
    res = run(s)
    parts = ops_of(res, "WO-1")
    assert [p.qty for p in parts] == [200, 200] and {p.line_id for p in parts} == {x.id for x in ds.lines.values()}
    assert all(p.setup_minutes == 15 for p in parts) and res.validation.ok
    single = run(s, split=False)
    assert max(p.end for p in parts) < ops_of(single, "WO-1")[0].end
    assert any(e.code == "APS_SPLIT" for e in res.exceptions)


def test_ts13_dst_night_shift_has_real_length():
    from superplanner.mfg.samples.common import THREE_SHIFT
    from zoneinfo import ZoneInfo

    ber = ZoneInfo("Europe/Berlin")
    b = plant(tz="Europe/Berlin")
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.template("T3", "3 shifts", THREE_SHIFT)
    b.assign("T3", "group", "G")
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    ds = ds_of(b)
    as_of = datetime(2026, 10, 24, 22, 0, tzinfo=ber)
    res = run(snap(ds, [wo(ds, "WO-1", "P", 510, date(2026, 10, 30))], as_of=as_of))
    (o,) = ops_of(res, "WO-1")
    lens = [int((p.end - p.start).total_seconds() // 60) for p in o.pieces]
    assert lens == [240, 270] and (o.end - o.start) == timedelta(hours=9) and res.validation.ok


def test_ts14_freeze_keeps_published_placement():
    from superplanner.mfg.aps.model import PublishedOp, PublishedView

    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G", "Stage")
    b.line("A", "G", "A")
    b.line("B", "G", "B")
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "G")
    b.routing("P", [op(10, "Work", "G", setup_minutes=0, run_minutes=1, crew_size=0, labor="unattended")])
    ds = ds_of(b)
    w = wo(ds, "WO-1", "P", 60, MON + timedelta(days=3))
    a = next(x.id for x in ds.lines.values() if x.code == "A")
    st = AS_OF + timedelta(hours=10)
    pub = PublishedView("apr_1", 1, (PublishedOp(1, "wo", w.id, 10, 0, 1, 60, a, st, st + timedelta(minutes=60),
                                                 run_minutes=60),))
    res = run(snap(ds, [w], published=pub))
    (o,) = ops_of(res, "WO-1")
    assert o.line_id == a and o.start == st and o.frozen and o.reason.code == "frozen" and res.validation.ok
    res = run(snap(ds, [w]))
    assert ops_of(res, "WO-1")[0].start == AS_OF


def test_ts16_validator_mutations():
    from superplanner.mfg.aps.validator import validate

    b = plant()
    b.item("P", "make", "Product", family="F")
    b.group("G1", "One")
    b.group("G2", "Two")
    b.line("A", "G1", "A")
    b.line("B", "G2", "B")
    b.template("T", "Shifts", REG)
    b.assign("T", "group", "G1")
    b.assign("T", "group", "G2")
    b.skill("S", "Skill")
    b.operator("O1", "One", ["S"], "T")
    b.operator("O2", "Two", ["S"], "T")
    b.tool("FIX", "Fixture", 1)
    b.routing("P", [op(10, "First", "G1", setup_minutes=0, run_minutes=1, skill_code="S", tools=["FIX"]),
                    op(20, "Second", "G2", setup_minutes=0, run_minutes=1, skill_code="S")])
    ds = ds_of(b)
    s = snap(ds, [wo(ds, "WO-1", "P", 30, MON + timedelta(days=3)), wo(ds, "WO-2", "P", 30, MON + timedelta(days=3))])
    base = run(s)
    assert base.validation.ok, base.validation.violations

    def mutate(fn):
        r = base.model_copy(deep=True)
        fn(r)
        return validate(s, r).counts

    def closed(r):
        o = r.operations[0]
        d = timedelta(hours=10)                     # 19:00: closed
        o.start, o.end = o.start + d, o.end + d
        for p in o.pieces + o.crew:
            p.start, p.end = p.start + d, p.end + d

    assert "APS_V_WINDOW" in mutate(closed)
    a1 = [o for o in base.operations if o.seq == 10]

    def double(r):
        x, y = [o for o in r.operations if o.seq == 20][:2]
        y.crew[0].operator_id = x.crew[0].operator_id
        y.start, y.end = x.start, x.end
        y.pieces = [p.model_copy() for p in x.pieces]
        y.crew[0].start, y.crew[0].end = x.crew[0].start, x.crew[0].end
    assert "APS_V_CREW_DOUBLE" in mutate(double)

    def tool(r):
        x, y = [o for o in r.operations if o.seq == 10][:2]
        y.line_id = x.line_id
        y.start, y.end = x.start, x.end
    assert "APS_V_TOOL" in mutate(tool)

    def prec(r):
        first = next(o for o in r.operations if o.seq == 10 and o.order.number == a1[0].order.number)
        second = next(o for o in r.operations if o.seq == 20 and o.order.number == first.order.number)
        d = second.start - first.start
        for o in (second,):
            o.start, o.end = o.start - d, o.end - d
            for p in o.pieces + o.crew:
                p.start, p.end = p.start - d, p.end - d
    assert "APS_V_PRECEDENCE" in mutate(prec)


def test_ts4_setup_matrix_and_lns_groups_families():
    b = plant()
    b.item("H1", "make", "HDI board 1", family="PCBA-HDI")
    b.item("S1", "make", "STD board", family="PCBA-STD")
    b.item("H2", "make", "HDI board 2", family="PCBA-HDI")
    b.group("SMT", "SMT")
    b.line("SMT-1", "SMT", "SMT 1", setup_family="SMT")
    b.template("T", "24x7", H24X7)
    b.assign("T", "group", "SMT")
    for pn in ("H1", "S1", "H2"):
        b.routing(pn, [op(10, "Place", "SMT", setup_minutes=30, run_minutes=1, crew_size=0, labor="unattended")])
    for f, t, mins in (("*", "*", 45), ("PCBA-HDI", "PCBA-HDI", 20), ("PCBA-STD", "PCBA-STD", 20),
                       ("PCBA-HDI", "PCBA-STD", 60), ("PCBA-STD", "PCBA-HDI", 60)):
        b.b["setup_matrix"].append({"line_setup_family": "SMT", "from_family": f, "to_family": t,
                                    "setup_minutes": mins})
    ds = ds_of(b)
    due = MON + timedelta(days=10)
    s = snap(ds, [wo(ds, "WO-1", "H1", 60, due), wo(ds, "WO-2", "S1", 60, due), wo(ds, "WO-3", "H2", 60, due)])
    c = run(s)
    seq = [o.order.number for o in sorted(c.operations, key=lambda o: o.start)]
    assert seq == ["WO-1", "WO-2", "WO-3"] and [o.setup_minutes for o in sorted(c.operations, key=lambda o: o.start)
                                                ] == [45, 60, 60]
    r = run(s, improve_seconds=5)
    ops = sorted(r.operations, key=lambda o: o.start)
    assert [o.family for o in ops] == ["PCBA-HDI", "PCBA-HDI", "PCBA-STD"] and \
        [o.setup_minutes for o in ops] == [45, 20, 60]
    assert r.validation.ok and r.summary.accepted_moves >= 1 and r.score < c.score


def test_accepted_suggestion_opens_the_window_in_a_live_run():
    from superplanner.mfg.aps.model import OpenShift

    ds = ds_of(_ot_plant())
    s = snap(ds, [wo(ds, "WO-1", "P", 675, MON + timedelta(days=1), priority=5)])
    sug = run(s, overtime="suggest")
    (w,) = sug.overtime
    assert w.orders and w.orders[0].order.number == "WO-1" and w.reason.startswith("Suggested")
    acc = run(s, overtime="suggest", open_shifts=[OpenShift(line_id=w.line_id, start=w.start, end=w.end)])
    assert acc.kind == "live" and acc.orders[0].late_minutes == 0 and acc.validation.ok
    (f,) = [x for x in acc.overtime if x.status != "suggested"]
    assert f.status == "forced" and f.cost == 1600.0 and f.orders[0].op_nos and "planner" in f.reason
    allow = run(s, overtime="allow")
    assert allow.overtime[0].orders[0].late_minutes == 0 and "automatically" in allow.overtime[0].reason
