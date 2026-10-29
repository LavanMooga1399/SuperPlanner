"""M2-DESIGN 8.15 hand-calculated vectors T-M1..T-M13 (T-M14/T-M15: test_mrp_properties.py).
as_of Mon 2026-11-02, workdays Mon-Sat, no holidays unless stated."""

from __future__ import annotations

from datetime import date

from mrp_helpers import AS_OF, D, Plant, Snap, codes, peg_view, plan, planned, reqs


def _buy_c(**kw):
    p = Plant().item("C", "buy", lead_time_days=10, receiving_days=2, **kw)
    return p.dataset()


def _t_m1(**kw):
    ds = _buy_c(**kw)
    s = Snap(ds)
    s.stock("C", 100)
    s.schedule("C", 50, D("11-10"))
    s.dem("C", 120, D("11-15"))
    s.dem("C", 80, D("11-20"))
    return ds, s.run()


def test_t_m1_stock_po_and_planned_pr():
    ds, r = _t_m1()
    assert peg_view(r, ds, "C") == [[("stock", 100, 0), ("po", 20, 0)], [("po", 30, 0), ("planned", 50, 0)]]
    (po,) = planned(r, ds, "C")
    assert (po.kind, po.qty, po.need_date, po.dock_date, po.start_date, po.release_status) == \
        ("buy", 50, D("11-20"), D("11-18"), D("11-08"), "release_now")
    assert not codes(r, "MRP_EXPEDITE") and not codes(r, "MRP_SHORTAGE")
    assert codes(r, "MRP_RELEASE_NOW")[0].subject.label == "P-1"
    assert r.summary.demand_on_time == 2 and r.iterations == 1


def test_t_m2_moq_and_multiple():
    ds, r = _t_m1(min_order_qty=5000, order_multiple=5000)
    (po,) = planned(r, ds, "C")
    assert po.qty == 5000
    sup = next(s for s in plan(r, ds, "C").supplies if s.kind == "planned")
    assert sup.pegged_qty == 50 and sup.qty - sup.pegged_qty == 4950
    assert "MOQ 5,000" in po.lot_note and "multiple 5,000" in po.lot_note


def test_t_m3_phase2_late_peg_expedite_reduce_shortage():
    ds = Plant().item("D", "buy", lead_time_days=60).dataset()
    s = Snap(ds)
    s.schedule("D", 200, D("12-01"))
    s.dem("D", 150, D("11-20"))
    r = s.run()
    assert peg_view(r, ds, "D") == [[("po", 150, 11)]]
    assert not planned(r, ds, "D")
    (ex,) = codes(r, "MRP_EXPEDITE")
    assert ex.suggested == {"date": "2026-11-20"} and ex.subject.type == "po_schedule"
    (red,) = codes(r, "MRP_REDUCE")
    assert red.suggested == {"qty": 150}
    (sh,) = codes(r, "MRP_SHORTAGE")
    assert sh.part_number == "D" and sh.qty == 150
    assert r.demand[0].late_days == 11 and r.demand[0].status == "late"


def test_t_m4_per_order_component_rounding():
    p = Plant().item("P", "make", lead_time_days=0).item("C", "buy", lead_time_days=10)
    p.bom("P", [("C", 4, {"scrap_pct": 2, "operation_seq": 10})])
    p.routing("P", [{"seq": 10, "run_minutes": 1}, {"seq": 20, "run_minutes": 1, "yield_pct": 97},
                    {"seq": 30, "run_minutes": 1, "yield_pct": 98}])
    ds = p.dataset()
    s = Snap(ds)
    s.dem("P", 100, D("11-30"))
    r = s.run()
    (wo,) = planned(r, ds, "P")
    assert wo.kind == "make" and wo.qty == 100 and wo.start_date == wo.need_date == D("11-30")
    (cr,) = reqs(r, ds, "C")
    assert cr.qty == 430 and cr.kind == "planned_component"


def _t_m5(holidays=()):
    p = Plant().item("P", "make").item("C", "buy", lead_time_days=1)
    p.bom("P", [("C", 1)])
    p.routing("P", [{"seq": 10, "setup_minutes": 60, "run_minutes": 3},
                    {"seq": 20, "run_minutes": 1.2, "wait_minutes": 1440}])
    ds = p.dataset()
    s = Snap(ds)
    s.stock("C", 1000)
    s.holidays = set(holidays)
    s.dem("P", 100, D("11-20"))
    return ds, s.run()


def test_t_m5_routing_lead_time_and_holiday():
    ds, r = _t_m5()
    (wo,) = planned(r, ds, "P")
    assert wo.start_date == D("11-16")
    assert plan(r, ds, "P").lead_time.unit == "working"
    ds, r = _t_m5([D("11-17")])
    assert planned(r, ds, "P")[0].start_date == D("11-14")
    from superplanner.mfg.mrp import manufacturing_lead_days
    assert manufacturing_lead_days(ds, ds.items_by_pn["P"].id, 100, AS_OF) == 4


def _t_m6(allocation):
    ds = Plant().item("X", "buy", lead_time_days=90).dataset()
    s = Snap(ds)
    s.stock("X", 10)
    d1 = s.dem("X", 8, D("11-30"), priority=1)
    d2 = s.dem("X", 8, D("11-20"), priority=5)
    r = s.run(allocation=allocation)
    return ds, r, {d.demand_line_id: d for d in r.demand}, d1, d2


def test_t_m6_priority_allocation():
    ds, r, dem, d1, d2 = _t_m6("priority")
    assert peg_view(r, ds, "X") == [[("stock", 8, 0)], [("stock", 2, 0), ("planned", 6, 72)]]
    (po,) = planned(r, ds, "X")
    assert po.qty == 6 and po.release_status == "start_in_past"
    assert dem[d2].projected_date == date(2027, 1, 31) and dem[d2].late_days == 72
    assert dem[d1].late_days == 0
    assert codes(r, "MRP_START_IN_PAST")


def test_t_m6_due_date_allocation():
    ds, r, dem, d1, d2 = _t_m6("due_date")
    assert dem[d2].late_days == 0
    assert dem[d1].late_days == 62 and dem[d1].projected_date == date(2027, 1, 31)


def _t_m7(alt_qty=1, alternates="when_short"):
    p = Plant().item("P", "make", lead_time_days=2).item("A1", "buy", lead_time_days=120)
    p.item("A2", "buy", lead_time_days=120)
    p.bom("P", [("A1", 1, {"alt_group": "G1", "alt_priority": 1}),
                ("A2", alt_qty, {"alt_group": "G1", "alt_priority": 2})])
    p.routing("P", [{"seq": 10, "run_minutes": 1}])
    ds = p.dataset()
    s = Snap(ds)
    s.stock("A2", 500)
    s.dem("P", 300, D("11-20"))
    return ds, s.run(alternates=alternates)


def test_t_m7_alternate_when_short():
    ds, r = _t_m7()
    assert r.iterations == 2
    (wo,) = planned(r, ds, "P")
    assert wo.start_date == D("11-18") and wo.directives == {"G1": 300}
    (a2,) = reqs(r, ds, "A2")
    assert a2.qty == 300 and peg_view(r, ds, "A2") == [[("stock", 300, 0)]]
    assert plan(r, ds, "A1") is None or not reqs(r, ds, "A1")
    assert r.demand[0].status == "on_time"
    (alt,) = codes(r, "MRP_ALTERNATE_USED")
    assert alt.qty == 300 and alt.subject.type == "planned_order"
    assert r.summary.alternates_used == 1


def test_t_m7_alternate_qty_per_2():
    ds, r = _t_m7(alt_qty=2)
    assert planned(r, ds, "P")[0].directives == {"G1": 250}
    assert reqs(r, ds, "A2")[0].qty == 500
    (a1,) = reqs(r, ds, "A1")
    assert a1.qty == 50 and a1.late_days > 0
    assert r.demand[0].status == "late"


def test_t_m7_alternates_never():
    ds, r = _t_m7(alternates="never")
    assert r.iterations == 1 and reqs(r, ds, "A1")[0].qty == 300 and not reqs(r, ds, "A2")


def test_t_m8_serial_eco_split():
    p = Plant().item("E", "make", serialized=True).item("K1", "buy", lead_time_days=5)
    p.item("K2", "buy", lead_time_days=5)
    p.bom("E", [("K1", 1)])
    p.serial_bom("E", [("K2", 1)], 106, 1_000_000_000)
    ds = p.dataset()
    s = Snap(ds)
    s.dem("E", 10, D("11-30"), serials=(101, 110))
    r = s.run()
    wos = planned(r, ds, "E")
    assert [(w.qty, w.segment.serial_from, w.segment.serial_to) for w in wos] == [(5, 101, 105), (5, 106, 110)]
    boms = {b.id: b for b in ds.boms.values()}
    assert [boms[w.bom_id].version for w in wos] == [1, 2]
    assert [x.qty for x in reqs(r, ds, "K1")] == [5] and [x.qty for x in reqs(r, ds, "K2")] == [5]


def _t_m9(need):
    ds = Plant().item("G", "buy", lead_time_days=5, lot_controlled=True).dataset()
    s = Snap(ds)
    s.stock("G", 100, lot="L1", expires=D("11-15"))
    s.dem("G", 50, need)
    return ds, s.run()


def test_t_m9_lot_expiry():
    ds, r = _t_m9(D("11-20"))
    assert peg_view(r, ds, "G") == [[("planned", 50, 0)]]
    (ex,) = codes(r, "MRP_EXPIRING_STOCK")
    assert ex.qty == 100 and ex.subject.label == "L1"
    ds, r = _t_m9(D("11-10"))
    assert peg_view(r, ds, "G") == [[("stock", 50, 0)]]
    assert codes(r, "MRP_EXPIRING_STOCK")[0].qty == 50


def test_t_m10_safety_stock():
    ds = Plant().item("S", "buy", lead_time_days=5, safety_stock=20).dataset()
    s = Snap(ds)
    s.stock("S", 15)
    r = s.run()
    (po,) = planned(r, ds, "S")
    assert po.qty == 5 and po.need_date == D("11-07") and po.late_days == 0
    (ss,) = reqs(r, ds, "S")
    assert ss.kind == "safety_stock" and ss.late_days == 0
    assert codes(r, "MRP_BELOW_SAFETY_STOCK")[0].qty == 5
    assert not codes(r, "MRP_SHORTAGE")
    r2 = s.run(safety_stock=False)
    assert not r2.planned_orders


def test_t_m11_reservations_prepegged():
    ds = Plant().item("W", "make").item("R", "buy", lead_time_days=30).dataset()
    s = Snap(ds)
    bal = s.stock("R", 50, reserved=40)
    w1 = s.wo("W", 1, D("11-05"), D("11-10"), [("R", 40)])
    s.wo("W", 1, D("11-04"), D("11-10"), [("R", 30)])
    s.reserve(w1.components[0].component_id, bal, 40)
    r = s.run()
    p = plan(r, ds, "R")
    by_src = {x.source.number: x for x in p.requirements}
    sups = {x.node: x for x in p.supplies}
    w1r, w2r = by_src["WO-001"], by_src["WO-002"]
    assert [(sups[pg.supply_node].kind, pg.qty) for pg in w1r.pegs] == [("stock", 40)]
    assert "reserved" in sups[w1r.pegs[0].supply_node].ref.label
    assert [(sups[pg.supply_node].kind, pg.qty) for pg in w2r.pegs] == [("stock", 10), ("planned", 20)]


def test_t_m12_defer_and_cancel():
    ds = Plant().item("J", "buy", lead_time_days=30).dataset()
    s = Snap(ds)
    s.schedule("J", 100, D("11-10"), number="PO-A")
    s.schedule("J", 50, D("11-12"), number="PO-B")
    s.dem("J", 100, D("12-20"))
    r = s.run()
    (df,) = codes(r, "MRP_DEFER")
    assert df.subject.label == "PO-A/10/1" and df.suggested == {"date": "2026-12-20"}
    (cn,) = codes(r, "MRP_CANCEL")
    assert cn.subject.label == "PO-B/10/1"


def test_t_m13_forward_pass_and_limiting_path():
    p = Plant().item("P", "make", lead_time_days=5).item("C", "buy", lead_time_days=60)
    p.bom("P", [("C", 1)])
    ds = p.dataset()
    s = Snap(ds)
    s.schedule("C", 10, D("12-03"), number="PO-C")
    s.dem("P", 10, D("12-04"))
    r = s.run()
    (wo,) = planned(r, ds, "P")
    assert wo.start_date == D("11-28") and wo.projected_due == D("12-09")
    assert peg_view(r, ds, "C") == [[("po", 10, 5)]]
    (dp,) = r.demand
    assert dp.late_days == 5 and dp.projected_date == D("12-09")
    assert [(x.part_number, x.reason) for x in dp.limiting] == [("P", "component"), ("C", "supply_date")]
    assert dp.limiting[1].label == "PO-C/10/1"
    (late,) = codes(r, "MRP_DEMAND_LATE")
    assert "5 days late" in late.message and "PO-C/10/1" in late.message
