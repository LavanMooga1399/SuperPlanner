"""8.12: every exception code, positive and negative; sort order; preflight."""

from __future__ import annotations

from datetime import date

import pytest

from mrp_helpers import AS_OF, D, Plant, Snap, codes, eid, planned
from superplanner.mfg.model_m2 import ItemSupplierRecord, SupplierRecord
from superplanner.mfg.mrp import MrpPreflightError
from superplanner.mfg.mrp.exceptions import CODES, sort_key


def _buy(pn="B", **kw):
    kw.setdefault("lead_time_days", 10)
    return Plant().item(pn, "buy", **kw).dataset()


def test_codes_table_is_complete_and_ordered():
    assert len(CODES) == 21
    assert CODES[0] == ("MRP_DEMAND_LATE", "critical") and CODES[-1][0] == "MRP_DEMAND_OUTSIDE_HORIZON"


def test_demand_past_due_vs_on_time():
    s = Snap(_buy())
    s.stock("B", 100)
    s.dem("B", 10, D("10-15"))
    s.dem("B", 10, D("11-20"))
    r = s.run()
    (pd,) = codes(r, "MRP_DEMAND_PAST_DUE")
    assert pd.days == 18 and pd.severity == "critical"
    assert [d.status for d in r.demand] == ["past_due", "on_time"]
    assert r.demand[0].projected_date == AS_OF and r.demand[0].late_days == 18
    assert not codes(r, "MRP_DEMAND_LATE")
    assert r.summary.demand_past_due == 1


def test_past_due_supply_assumed_today():
    s = Snap(_buy(receiving_days=1))
    s.schedule("B", 20, D("10-21"))
    s.schedule("B", 20, D("11-21"), number="PO-2")
    s.dem("B", 30, D("11-30"))
    r = s.run()
    (pd,) = codes(r, "MRP_PAST_DUE_SUPPLY")
    assert pd.subject.label == "PO-1/10/1" and pd.days == 12
    sup = r.items[0].supplies[0]
    assert sup.avail_date == D("11-03")          # max(dock, as_of) + receiving


def test_wo_late_and_not_late():
    p = Plant().item("W", "make", lead_time_days=2).item("C", "buy", lead_time_days=30)
    ds = p.dataset()
    s = Snap(ds)
    s.wo("W", 5, D("11-10"), D("11-12"), [("C", 5)])           # C only by planned PR -> late
    s.dem("W", 5, D("11-12"))
    r = s.run()
    (wl,) = codes(r, "MRP_WO_LATE")
    assert wl.subject.label == "WO-001" and "C" in wl.message
    s2 = Snap(ds)
    s2.stock("C", 5)
    s2.wo("W", 5, D("11-10"), D("11-12"), [("C", 5)])
    s2.dem("W", 5, D("11-12"))
    r2 = s2.run()
    assert not codes(r2, "MRP_WO_LATE") and r2.demand[0].status == "on_time"
    assert not codes(r2, "MRP_CANCEL")


def test_cancel_only_planned_status_wos():
    ds = Plant().item("W", "make", lead_time_days=2).dataset()
    for status, n in (("planned", 1), ("released", 0)):
        s = Snap(ds)
        s.wo("W", 5, D("11-10"), D("11-12"), [], status=status)
        assert len(codes(s.run(), "MRP_CANCEL")) == n


def test_expired_and_expiring_stock():
    ds = _buy("L", lot_controlled=True)
    s = Snap(ds)
    s.stock("L", 3, lot="OLD", expires=D("10-30"))
    s.stock("L", 5, lot="NEW", expires=D("11-20"))
    s.stock("L", 5, lot="FAR", expires=date(2027, 12, 1))
    s.dem("L", 5, D("11-10"))
    r = s.run()
    (ex,) = codes(r, "MRP_EXPIRED_STOCK")
    assert ex.subject.label == "OLD" and ex.qty == 3
    assert not codes(r, "MRP_EXPIRING_STOCK")              # NEW fully used, FAR beyond the horizon
    assert r.items[0].requirements[0].pegs[0].qty == 5


def test_reduce_negative_when_rounding_keeps_qty():
    s = Snap(_buy(min_order_qty=200))
    s.schedule("B", 200, D("11-10"))
    s.dem("B", 150, D("11-12"))
    r = s.run()
    assert not codes(r, "MRP_REDUCE")                    # rounded pegged qty (MOQ 200) == open qty


def test_defer_within_tolerance_is_silent():
    s = Snap(_buy())
    s.schedule("B", 100, D("11-10"))
    s.dem("B", 100, D("11-15"))
    assert not codes(s.run(), "MRP_DEFER")


def test_start_in_past_release_now_later():
    s = Snap(_buy(lead_time_days=10))
    s.dem("B", 1, D("11-05"))       # start 10-26 -> past
    s.dem("B", 1, D("11-16"))       # start 11-06 -> release now
    s.dem("B", 1, D("12-20"))       # later
    r = s.run()
    assert [p.release_status for p in r.planned_orders] == ["start_in_past", "release_now", "later"]
    assert len(codes(r, "MRP_START_IN_PAST")) == 1 and len(codes(r, "MRP_RELEASE_NOW")) == 1
    assert r.summary.start_in_past == 1 and r.summary.release_now == 1


def _with_supplier(ds, pn, lead=None, preferred=True, moq=0.0, mult=0.0, pack=1.0):
    from datetime import UTC, datetime
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    sid = eid("sup", "S1")
    ds.suppliers = {sid: SupplierRecord.model_construct(id=sid, row_version=1, created_at=ts, updated_at=ts,
                                                        code="S1", name="S1", lead_time_days=lead, active=True)}
    iid = ds.items_by_pn[pn].id
    rid = eid("isu", pn)
    ds.item_suppliers = {rid: ItemSupplierRecord.model_construct(
        id=rid, row_version=1, created_at=ts, updated_at=ts, item_id=iid, supplier_id=sid, lead_time_days=None,
        min_order_qty=moq, order_multiple=mult, units_per_purchase_unit=pack, preferred=preferred, active=True)}
    return sid


def test_no_supplier_and_source_resolution():
    ds = _buy(lead_time_days=10)
    s = Snap(ds)
    s.dem("B", 7, D("12-01"))
    assert codes(s.run(), "MRP_NO_SUPPLIER")
    sid = _with_supplier(ds, "B", lead=20, pack=5)
    r = Snap(ds, demand=list(s.demand)).run()
    assert not codes(r, "MRP_NO_SUPPLIER")
    (po,) = r.planned_orders
    assert po.supplier_id == sid and po.qty == 10                       # pack 5
    assert po.start_date == D("12-01") - __import__("datetime").timedelta(days=20)   # supplier lead time
    assert r.items[0].lead_time.source == "supplier"


def test_merge_into_pr():
    ds = _buy(lead_time_days=5)
    s = Snap(ds)
    s.schedule("B", 1, D("11-28"), doc_type="pr", number="PR-9", status="draft")
    s.dem("B", 1, D("11-28"))
    s.dem("B", 10, D("12-25"))
    r = s.run(include_pr_supply=False)
    m = codes(r, "MRP_MERGE_INTO_PR")
    assert len(m) == 1 and "PR-9" in m[0].message and m[0].related[0].label == "PR-9"


def test_demand_serial_overlap():
    ds = Plant().item("E", "make", serialized=True, lead_time_days=1).dataset()
    s = Snap(ds)
    s.dem("E", 5, D("11-20"), serials=(1, 5), number="DO-A")
    s.dem("E", 5, D("11-20"), serials=(5, 9), number="DO-B")
    s.dem("E", 5, D("11-20"), serials=(10, 14), number="DO-C")
    r = s.run()
    ov = codes(r, "MRP_DEMAND_SERIAL_OVERLAP")
    assert sorted(e.subject.label for e in ov) == ["DO-A/10", "DO-B/10"]


def test_reservation_excess():
    ds = Plant().item("W", "make").item("R", "buy", lead_time_days=3).dataset()
    s = Snap(ds)
    bal = s.stock("R", 50, reserved=40)
    w = s.wo("W", 1, D("11-05"), D("11-10"), [("R", 25)])
    s.reserve(w.components[0].component_id, bal, 40)
    r = s.run()
    (ex,) = codes(r, "MRP_RESERVATION_EXCESS")
    assert ex.qty == 15 and ex.subject.label == "WO-001"
    p = r.items[[i.part_number for i in r.items].index("R")]
    assert sum(x.pegged_qty for x in p.supplies) == 25


def test_wo_component_cycle():
    p = Plant().item("A", "make", lead_time_days=1).item("B", "make", lead_time_days=1)
    p.bom("A", [("B", 1)])
    ds = p.dataset()
    s = Snap(ds)
    s.wo("B", 1, D("11-10"), D("11-12"), [("A", 1)])          # B -> A closes A -> B
    s.stock("A", 5)
    r = s.run()
    (cy,) = codes(r, "MRP_WO_COMPONENT_CYCLE")
    assert cy.subject.label == "WO-001"


def test_outside_horizon():
    s = Snap(_buy())
    s.dem("B", 1, D("11-20"))
    s.dem("B", 1, date(2027, 6, 1))
    r = s.run(horizon_days=90)
    (oh,) = codes(r, "MRP_DEMAND_OUTSIDE_HORIZON")
    assert oh.qty == 1 and r.summary.demand_lines == 1 and r.summary.demand_outside_horizon == 1
    assert not codes(s.run(horizon_days=365), "MRP_DEMAND_OUTSIDE_HORIZON")


def test_sorted_by_severity_code_date():
    s = Snap(_buy())
    s.dem("B", 1, D("10-15"))
    s.dem("B", 1, D("11-30"))
    s.schedule("B", 5, D("10-01"))
    r = s.run()
    assert r.exceptions == sorted(r.exceptions, key=sort_key)
    assert r.exceptions[0].severity == "critical"


def test_preflight_blocks_inactive_and_phantom_and_unknown_overrides():
    p = Plant().item("X", "buy", active=False).item("PH", "phantom").item("K", "buy")
    p.bom("PH", [("K", 1)])
    ds = p.dataset()
    s = Snap(ds)
    s.dem("X", 1, D("11-20"))
    s.dem("PH", 1, D("11-20"))
    with pytest.raises(MrpPreflightError) as ei:
        s.run(supply_date_overrides=[{"schedule_id": eid("psc", "nope"), "date": "2026-12-01"}])
    got = sorted(i["code"] for i in ei.value.issues)
    assert got == ["MRP_DEMAND_ITEM_INACTIVE", "MRP_DEMAND_ITEM_PHANTOM", "MRP_OVERRIDE_UNKNOWN"]


def test_planned_orders_are_numbered_in_creation_order():
    p = Plant().item("P", "make", lead_time_days=1).item("C", "buy", lead_time_days=1)
    p.bom("P", [("C", 2)])
    ds = p.dataset()
    s = Snap(ds)
    s.dem("P", 1, D("11-20"))
    r = s.run()
    assert [(x.planned_no, x.part_number) for x in r.planned_orders] == [(1, "P"), (2, "C")]
    assert planned(r, ds, "C")[0].qty == 2
