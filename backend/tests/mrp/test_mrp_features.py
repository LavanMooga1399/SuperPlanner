"""What-if inputs, lot rules and rounding chain, phantoms, explosion API, lead times, views, JSON round trip."""

from __future__ import annotations

from datetime import date, timedelta

from mrp_helpers import AS_OF, D, Plant, Snap, codes, peg_view, plan, planned, reqs
from superplanner.mfg.mrp import (bucketize, canonical_json, compare, item_plan_from_jsonable, item_timeline,
                                  order_components, pegging, to_jsonable)
from superplanner.mfg.mrp.lotsize import LotParams, round_order_qty


# ---------------------------------------------------------------- what-if (8.2, 8.14)

def _po_scenario():
    ds = Plant().item("B", "buy", lead_time_days=60).dataset()
    s = Snap(ds)
    sid = s.schedule("B", 10, D("11-10"))
    pr = s.schedule("B", 10, D("11-12"), doc_type="pr", number="PR-1")
    s.dem("B", 20, D("11-20"), program="KVP-1")
    s.dem("B", 5, D("11-25"), number="DO-X", priority=1)
    return ds, s, sid, pr


def test_kind_live_and_what_if():
    ds, s, sid, _ = _po_scenario()
    assert s.run().kind == "live"
    assert s.run(as_of=AS_OF).kind == "live"
    assert s.run(as_of=AS_OF + timedelta(days=1)).kind == "what_if"
    assert s.run(include_pr_supply=False).kind == "what_if"


def test_supply_date_override_moves_supply():
    ds, s, sid, _ = _po_scenario()
    r = s.run(supply_date_overrides=[{"schedule_id": sid, "date": "2026-12-10"}])
    po = next(x for x in plan(r, ds, "B").supplies if x.kind == "po")
    assert po.avail_date == D("12-10")


def test_include_pr_supply_false():
    ds, s, _, _ = _po_scenario()
    assert any(x.kind == "pr" for x in plan(s.run(), ds, "B").supplies)
    assert not any(x.kind == "pr" for x in plan(s.run(include_pr_supply=False), ds, "B").supplies)


def test_lead_time_override_and_exclusions_and_extra_demand():
    ds, s, _, _ = _po_scenario()
    iid = ds.items_by_pn["B"].id
    r = s.run(lead_time_overrides=[{"item_id": iid, "lead_time_days": 3}])
    assert plan(r, ds, "B").lead_time.source == "override" and plan(r, ds, "B").lead_time.days == 3
    line = s.demand[0].line_id
    r = s.run(exclude_demand_line_ids=[line])
    assert [d.demand_line_id for d in r.demand] == [s.demand[1].line_id]
    r = s.run(demand_filter={"programs": ["KVP-1"]})
    assert [d.label for d in r.demand] == ["DO-001/10"]
    r = s.run(extra_demand=[{"item_id": iid, "qty": 7, "due_date": "2026-12-15", "label": "Trial"}])
    ex = [d for d in r.demand if d.extra]
    assert len(ex) == 1 and ex[0].label == "Trial" and ex[0].qty == 7 and r.kind == "what_if"


def test_protect_programs_rank_first():
    ds, s, _, _ = _po_scenario()
    r = s.run()
    first = plan(r, ds, "B").requirements
    # without protection DO-X (priority 1) is served first from the 11-10 PO
    assert first[1].pegs[0].supply_node == 1
    r = s.run(protect_programs=["KVP-1"])
    rr = plan(r, ds, "B").requirements
    assert rr[0].rank[0] == 0 and rr[0].pegs[0].supply_node == 1


# ---------------------------------------------------------------- lot sizing (8.6)

def test_rounding_chain():
    lp = LotParams("lot_for_lot", 1, None, moq=100, multiple=30, pack=50, count=True)
    assert round_order_qty(7, lp) == 150          # MOQ 100 -> multiple 120 -> pack 150
    lp = LotParams("lot_for_lot", 1, None, moq=0, multiple=0, pack=1, count=False)
    assert round_order_qty(1.2345678, lp) == 1.234568
    lp = LotParams("lot_for_lot", 1, None, moq=0, multiple=0, pack=1, count=True)
    assert round_order_qty(2.0000000001, lp) == 2 and round_order_qty(2.1, lp) == 3


def _lots(**kw):
    ds = Plant().item("B", "buy", lead_time_days=1, **kw).dataset()
    s = Snap(ds)
    for day, q in ((10, 3), (12, 4), (20, 5), (21, 6)):
        s.dem("B", q, D(f"11-{day}"))
    return ds, s.run()


def test_lot_rules():
    ds, r = _lots()
    assert [(p.need_date.day, p.qty) for p in r.planned_orders] == [(10, 3), (12, 4), (20, 5), (21, 6)]
    ds, r = _lots(lot_rule="period", lot_period_days=7)
    assert [(p.need_date.day, p.qty) for p in r.planned_orders] == [(10, 7), (20, 11)]
    ds, r = _lots(lot_rule="fixed", fixed_lot_qty=5)
    # 3 -> 5 (surplus 2 serves 2 of 4) -> residual 2 -> 5 (surplus 3) -> 5 needs 2 more -> 5 ...
    assert [p.qty for p in r.planned_orders] == [5, 5, 5, 5]
    assert sum(p.qty for p in r.planned_orders) >= 18
    for req in reqs(r, ds, "B"):
        assert abs(sum(pg.qty for pg in req.pegs) - req.qty) < 1e-9


# ---------------------------------------------------------------- explosion (8.7)

def test_phantom_blow_through_and_order_components():
    p = Plant().item("P", "make", lead_time_days=1).item("KIT", "phantom").item("S", "buy", uom="EA")
    p.item("W", "buy", uom="M")
    p.bom("KIT", [("S", 3, {"scrap_pct": 10})])
    p.bom("P", [("KIT", 2), ("W", 250, {"uom": "MM"})])
    ds = p.dataset()
    ex = order_components(ds, ds.items_by_pn["P"].id, 5, on=AS_OF, serial=None)
    got = {ds.items[c.item_id].part_number: c.qty for c in ex.components}
    assert got == {"S": 33, "W": 1.25}                # 5 x 2 x 3 x 1.1 = 33.0 ; 5 x 0.25 m
    s = Snap(ds)
    s.dem("P", 5, D("11-20"))
    r = s.run()
    assert not planned(r, ds, "KIT") and reqs(r, ds, "S")[0].qty == 33


def test_order_components_directive_moves_to_alternate():
    p = Plant().item("P", "make", lead_time_days=1).item("A1", "buy").item("A2", "buy")
    p.bom("P", [("A1", 2, {"alt_group": "X", "alt_priority": 1}), ("A2", 4, {"alt_group": "X", "alt_priority": 2})])
    ds = p.dataset()
    ex = order_components(ds, ds.items_by_pn["P"].id, 10, on=AS_OF, serial=None,
                          directives={("k", "X"): 5}, order_key="k")
    got = {ds.items[c.item_id].part_number: (c.qty, c.substitute_for is not None) for c in ex.components}
    assert got == {"A1": (15, False), "A2": (10, True)}


def test_no_effective_bom_warning():
    ds = Plant().item("P", "make", lead_time_days=1).dataset()
    ex = order_components(ds, ds.items_by_pn["P"].id, 1, on=AS_OF, serial=None)
    assert ex.components == () and ex.warnings[0]["code"] == "WO_NO_EFFECTIVE_BOM"


# ---------------------------------------------------------------- views (8.13)

def _shared():
    p = Plant().item("P1", "make", lead_time_days=1).item("P2", "make", lead_time_days=1)
    p.item("C", "buy", lead_time_days=5)
    p.bom("P1", [("C", 2)])
    p.bom("P2", [("C", 3)])
    ds = p.dataset()
    s = Snap(ds)
    s.stock("C", 10)
    s.dem("P1", 4, D("11-20"))
    s.dem("P2", 4, D("11-27"))
    return ds, s.run()


def test_timeline_and_buckets():
    ds, r = _shared()
    pc = plan(r, ds, "C")
    tl = pc.timeline
    assert tl[0].kind == "on_hand" and tl[0].qty == 10
    assert tl[-1].balance_planned >= 0
    assert min(e.balance_existing for e in tl) == 10 - 8 - 12
    assert item_timeline(pc, AS_OF) == tl
    bk = bucketize(tl, "week", AS_OF, D("11-30"))
    assert bk[0]["start"] == AS_OF and sum(b["gross"] for b in bk) == 20
    assert sum(b["planned"] for b in bk) == pc.stats.planned_qty
    assert bucketize(tl, "month", AS_OF, D("12-31"))[1]["start"] == D("12-01")
    assert pc.stats.on_hand == 10 and pc.stats.gross_qty == 20
    assert pc.stats.planned_count == 1 and pc.stats.planned_qty == 10        # stock covers P1's 8 + 2 of P2's 12


def test_pegging_up_and_down():
    ds, r = _shared()
    pc = plan(r, ds, "C")
    pr = next(s for s in pc.supplies if s.kind == "planned")
    up = pegging(r, pc.item_id, pr.node, "supply", "up")
    kinds = [(row["level"], row["kind"], row["label"]) for row in up["rows"]]
    assert kinds[0][1] == "supply" and any(lbl.startswith("DO-") for _l, _k, lbl in kinds)
    assert not up["truncated"]
    d = r.demand[0]
    p1 = plan(r, ds, "P1")
    down = pegging(r, p1.item_id, d.node, "requirement", "down")
    assert [row["kind"] for row in down["rows"]][:3] == ["requirement", "supply", "requirement"]
    assert any(row["item_id"] == pc.item_id for row in down["rows"])
    small = pegging(r, pc.item_id, pr.node, "supply", "up", max_rows=1)
    assert small["truncated"] and len(small["rows"]) == 1


def test_peg_summary_names_demand_lines():
    ds, r = _shared()
    for po in planned(r, ds, "C"):
        assert po.peg_summary and all(x.label.startswith("DO-") for x in po.peg_summary)
        assert abs(sum(x.qty for x in po.peg_summary) - sum(
            pg.qty for rq in plan(r, ds, "C").requirements for pg in rq.pegs if pg.supply_node == po.supply_node)) \
            < 1e-6


def test_compare_runs():
    ds, s, sid, _ = _po_scenario()
    a = s.run()
    b = s.run(supply_date_overrides=[{"schedule_id": sid, "date": "2027-03-01"}])
    cmp = compare(a, b)
    assert cmp["planned"]["a"]["buy"] <= cmp["planned"]["b"]["buy"]
    assert compare(a, a)["demand"] == [] and compare(a, a)["items"] == []


def test_item_plan_json_round_trip():
    ds, r = _shared()
    for p in r.items:
        js = to_jsonable(p)
        assert to_jsonable(item_plan_from_jsonable(js)) == js
    assert canonical_json(r) == canonical_json(r)


def test_routing_lead_time_scales_with_qty_and_speed():
    from superplanner.mfg.mrp import manufacturing_lead_days
    p = Plant().item("P", "make")
    p.routing("P", [{"seq": 10, "run_minutes": 48}])
    ds = p.dataset()
    pid = ds.items_by_pn["P"].id
    assert manufacturing_lead_days(ds, pid, 10, AS_OF) == 1
    assert manufacturing_lead_days(ds, pid, 11, AS_OF) == 2
    assert manufacturing_lead_days(ds, pid, 11, AS_OF, day_minutes=600) == 1
    assert manufacturing_lead_days(ds, pid, 11, AS_OF, override=9) == 9
    line = next(iter(ds.lines.values()))
    line.speed_factor = 2.0
    assert manufacturing_lead_days(ds, pid, 20, AS_OF) == 1


def test_workdays_setting_changes_dates():
    p = Plant().item("P", "make", lead_time_days=5).item("C", "buy", lead_time_days=1)
    p.bom("P", [("C", 1)])
    ds = p.dataset(mrp_workdays=["mon", "tue", "wed", "thu", "fri"])
    s = Snap(ds)
    s.stock("C", 10)
    s.dem("P", 1, D("11-20"))
    assert planned(s.run(), ds, "P")[0].start_date == D("11-13")      # Mon-Fri: 5 working days before Fri


def test_inspection_stock_available_after_receiving_days():
    ds = Plant().item("B", "buy", lead_time_days=30, receiving_days=3).dataset()
    s = Snap(ds)
    s.stock("B", 6, kind="inspection", loc="GOODS-IN", last_receipt=D("11-01"))
    s.stock("B", 9, kind="quarantine", loc="QUAR")
    s.dem("B", 6, D("11-10"))
    r = s.run()
    (sup,) = plan(r, ds, "B").supplies
    assert sup.kind == "inspection" and sup.avail_date == D("11-04")
    assert peg_view(r, ds, "B") == [[("inspection", 6, 0)]]
    assert not codes(r, "MRP_SHORTAGE")
