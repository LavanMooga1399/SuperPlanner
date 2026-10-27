"""Gate 2 #2/#3 groundwork: the independent oracle reproduces every hand-calculated vector of M2-DESIGN 8.15.

Pure (no database, no engine). If one of these fails, the oracle (not the product) is wrong - fix the oracle first;
the comparison tests (`test_acc_m2_02_oracle_vs_engine.py`) are only as good as this file.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from oracle import run_oracle
from oracle import vectors as V
from oracle.build import d
from oracle.query import demand_proj, demand_req, exc, peg_kinds, pegs, planned, reqs

ORACLE_DIR = Path(__file__).resolve().parent / "oracle"


def test_oracle_is_independent_of_the_product():
    """17.2/16.1: the oracle must not import `superplanner` (in particular never `superplanner.mfg.mrp`)."""
    for path in sorted(ORACLE_DIR.glob("*.py")):
        if path.name == "adapters.py":       # the adapters translate product types; they never import mfg.mrp
            src = path.read_text()
            assert "superplanner.mfg.mrp" not in src.replace('"superplanner.mfg.mrp"', "").replace(
                "'superplanner.mfg.mrp'", ""), path
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith("superplanner") for a in node.names), (path, ast.unparse(node))
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("superplanner"), (path, ast.unparse(node))


def test_tm1_pegs_and_planned_pr():
    v = V.tm1()
    res = run_oracle(v.plant)
    r1, r2 = demand_req(res, v.r1.line_id), demand_req(res, v.r2.line_id)
    assert pegs(res, r1) == [(("balance", v.stock.id), 100), (("schedule", v.po.schedule_id), 20)]
    p = planned(res, v.c.id)
    assert len(p) == 1
    p = p[0]
    assert (p.kind, p.qty, p.need_date, p.dock_date, p.start_date, p.release_status) == \
        ("buy", 50, d("11-20"), d("11-18"), d("11-08"), "release_now")
    assert pegs(res, r2) == [(("schedule", v.po.schedule_id), 30), (("planned", p.planned_no), 50)]
    assert not exc(res, "MRP_EXPEDITE")
    assert demand_proj(res, v.r1.line_id).status == "on_time"
    assert demand_proj(res, v.r2.line_id).projected_date == d("11-20")


def test_tm2_moq_and_multiple():
    v = V.tm2()
    res = run_oracle(v.plant)
    (p,) = planned(res, v.c.id)
    assert p.qty == 5000
    s = res.supplies[v.c.id][p.supply_node - 1]
    assert round(s.qty - s.pegged, 6) == 4950


def test_tm3_phase2_late_peg_and_messages():
    v = V.tm3()
    res = run_oracle(v.plant)
    r = demand_req(res, v.r.line_id)
    assert pegs(res, r) == [(("schedule", v.po.schedule_id), 150)]
    assert r.late_days == 11 and r.satisfied_date == d("12-01")
    assert not planned(res, v.d.id)
    (e,) = exc(res, "MRP_EXPEDITE")
    assert e.subject == ("po_schedule", v.po.schedule_id) and e.suggested == {"date": d("11-20")}
    (e,) = exc(res, "MRP_REDUCE")
    assert e.suggested == {"qty": 150}
    (e,) = exc(res, "MRP_SHORTAGE")
    assert e.item_id == v.d.id


def test_tm4_component_rounding_per_order():
    v = V.tm4()
    res = run_oracle(v.plant)
    (p,) = planned(res, v.p.id)
    assert (p.kind, p.qty) == ("make", 100)
    (c,) = reqs(res, v.c.id, "planned_component")
    assert c.qty == 430          # 429.2026 -> 430 (M1 T-Q1)


def test_tm5_routing_lead_time_and_holiday():
    res = run_oracle(V.tm5().plant)
    (p,) = res.planned
    assert (p.need_date, p.start_date) == (d("11-20"), d("11-16"))          # MLT 4 days
    res = run_oracle(V.tm5(holiday=True).plant)
    (p,) = res.planned
    assert p.start_date == d("11-14")                                       # Sat (Tue 17 holiday)


def test_tm6_both_allocation_policies():
    v = V.tm6("priority")
    res = run_oracle(v.plant)
    r1, r2 = demand_req(res, v.d1.line_id), demand_req(res, v.d2.line_id)
    assert peg_kinds(res, r1) == [("stock", 8)]
    assert peg_kinds(res, r2) == [("stock", 2), ("planned", 6)]
    (p,) = res.planned
    assert p.release_status == "start_in_past"
    assert demand_proj(res, v.d2.line_id).projected_date == d("01-31")
    assert r2.late_days == 72
    v = V.tm6("due_date")
    res = run_oracle(v.plant)
    r1, r2 = demand_req(res, v.d1.line_id), demand_req(res, v.d2.line_id)
    assert peg_kinds(res, r2) == [("stock", 8)]
    assert peg_kinds(res, r1) == [("stock", 2), ("planned", 6)]
    assert r1.late_days == 62


def test_tm7_alternates_when_short():
    v = V.tm7()
    res = run_oracle(v.plant)
    assert res.iterations == 2
    (a2,) = reqs(res, v.a2.id, "planned_component")
    assert a2.qty == 300 and peg_kinds(res, a2) == [("stock", 300)]
    assert not reqs(res, v.a1.id)
    assert demand_proj(res, v.dm.line_id).status == "on_time"
    assert exc(res, "MRP_ALTERNATE_USED")
    # alternate qty_per 2: directive 250, A2 500, A1 residual 50 late
    v = V.tm7(2)
    res = run_oracle(v.plant)
    assert list(res.directives.values()) == [250]
    (a2,) = reqs(res, v.a2.id, "planned_component")
    assert a2.qty == 500
    (a1,) = reqs(res, v.a1.id, "planned_component")
    assert a1.qty == 50 and a1.late_days > 0
    # never: no second pass
    v = V.tm7(alternates="never")
    res = run_oracle(v.plant)
    assert res.iterations == 1 and not reqs(res, v.a2.id) and reqs(res, v.a1.id)[0].qty == 300


def test_tm8_serial_segments_and_eco_split():
    v = V.tm8()
    res = run_oracle(v.plant)
    ps = sorted(planned(res, v.e.id), key=lambda p: p.segment)
    assert [(p.segment, p.qty) for p in ps] == [((101, 105), 5), ((106, 110), 5)]
    (k1,) = reqs(res, v.k1.id)
    (k2,) = reqs(res, v.k2.id)
    assert (k1.qty, k2.qty) == (5, 5)


def test_tm9_lot_expiry():
    v = V.tm9()
    res = run_oracle(v.plant)
    r = demand_req(res, v.r.line_id)
    assert peg_kinds(res, r) == [("planned", 50)]
    (e,) = exc(res, "MRP_EXPIRING_STOCK")
    assert e.qty == 100 and e.subject == ("lot", v.lot.lot_id)
    v = V.tm9("11-10")
    res = run_oracle(v.plant)
    assert pegs(res, demand_req(res, v.r.line_id)) == [(("balance", v.lot.id), 50)]


def test_tm10_safety_stock():
    v = V.tm10()
    res = run_oracle(v.plant)
    (p,) = res.planned
    assert (p.qty, p.need_date) == (5, d("11-07"))
    (ss,) = reqs(res, v.x.id, "safety_stock")
    assert ss.late_days == 0
    assert exc(res, "MRP_BELOW_SAFETY_STOCK")
    assert not exc(res, "MRP_SHORTAGE")


def test_tm11_reservations_are_prepegged():
    v = V.tm11()
    res = run_oracle(v.plant)
    by_wo = {r.source[1]: r for r in reqs(res, v.c.id, "wo_component")}
    assert peg_kinds(res, by_wo[v.w1.id]) == [("stock", 40)]
    assert peg_kinds(res, by_wo[v.w2.id]) == [("stock", 10), ("planned", 20)]


def test_tm12_defer_and_cancel():
    v = V.tm12()
    res = run_oracle(v.plant)
    (e,) = exc(res, "MRP_DEFER")
    assert e.subject == ("po_schedule", v.pa.schedule_id) and e.suggested == {"date": d("12-20")}
    (e,) = exc(res, "MRP_CANCEL")
    assert e.subject == ("po_schedule", v.pb.schedule_id)


def test_tm13_forward_pass_and_limiting_path():
    v = V.tm13()
    res = run_oracle(v.plant)
    (p,) = planned(res, v.p.id)
    assert p.start_date == d("11-28")
    (c,) = reqs(res, v.c.id)
    assert c.late_days == 5
    dp = demand_proj(res, v.dm.line_id)
    assert (dp.projected_date, dp.late_days, dp.status) == (d("12-09"), 5, "late")
    assert [(s["item"], s["reason"]) for s in dp.limiting] == [(v.p.id, "component"), (v.c.id, "supply_date")]
    assert dp.limiting[1]["supply"] == ("schedule", v.po.schedule_id)


def test_oracle_is_deterministic_and_fully_pegged_on_all_vectors():
    for name, fn in V.ALL.items():
        a, b = run_oracle(fn().plant), run_oracle(fn().plant)
        assert [(p.item_id, p.qty, p.need_date, p.start_date) for p in a.planned] == \
            [(p.item_id, p.qty, p.need_date, p.start_date) for p in b.planned], name
        for rs in a.requirements.values():
            for r in rs:
                assert abs(r.pegged - r.qty) < 1e-6, (name, r)
        for ss in a.supplies.values():
            for s in ss:
                assert s.pegged <= s.qty + 1e-6, (name, s)
        assert a.as_of == date(2026, 11, 2)
