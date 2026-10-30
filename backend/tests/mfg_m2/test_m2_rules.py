"""WP-A pure rules (M2-DESIGN 3, 4, 5, 6, 7, 8.5): model validators, work calendar, posting planner, FEFO,
status machines, serial rules, reservations and kitting."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from superplanner.mfg import demand as DEM
from superplanner.mfg import inventory as INV
from superplanner.mfg import purchasing as PUR
from superplanner.mfg import workorders as WOR
from superplanner.mfg.model import ItemInput, PlantInput
from superplanner.mfg.model_m2 import (DemandOrderInput, ItemSupplierInput, LocationInput, MemberInput, PostingInput,
                                       PurchaseDocInput, WorkOrderInput)
from superplanner.mfg.purchasing import RuleError
from superplanner.mfg.workdays import WorkCalendar

D = date(2026, 11, 2)                     # Monday
ID = "itm_" + "a" * 32
ID2 = "itm_" + "b" * 32
LOC = "loc_" + "1" * 32
LOC2 = "loc_" + "2" * 32
QUAR = "loc_" + "3" * 32
POST = TypeAdapter(PostingInput)


# ---------------------------------------------------------------- models (3)


def test_item_and_plant_m2_fields():
    it = ItemInput(part_number="X", make_buy="buy", lot_rule="period", lot_period_days=30, external_ref="ERP-1",
                   standard_cost=2.5, lot_controlled=True)
    assert it.lot_period_days == 30 and it.lot_controlled
    with pytest.raises(ValidationError):
        ItemInput(part_number="X", make_buy="buy", lot_rule="period")
    with pytest.raises(ValidationError):
        ItemInput(part_number="X", make_buy="buy", lot_period_days=5)
    p = PlantInput()
    assert p.mrp_workdays == ["mon", "tue", "wed", "thu", "fri", "sat"] and p.mrp_day_minutes == 480
    assert (p.mrp_defer_tolerance_days, p.mrp_release_window_days, p.over_receipt_pct) == (7, 7, 0)
    with pytest.raises(ValidationError):
        PlantInput(mrp_workdays=["mon", "mon"])
    with pytest.raises(ValidationError):
        PlantInput(mrp_day_minutes=30)


def test_m2_input_rules():
    LocationInput(code="S", name="S", kind="stores")
    with pytest.raises(ValidationError):
        LocationInput(code="S", name="S", kind="yard")
    ItemSupplierInput(item_id=ID, supplier_id="sup_" + "1" * 32, units_per_purchase_unit=5000)
    with pytest.raises(ValidationError):
        ItemSupplierInput(item_id=ID, supplier_id="sup_" + "1" * 32, units_per_purchase_unit=0)
    MemberInput(email="a@b.c", roles=["viewer", "planner"])
    with pytest.raises(ValidationError):
        MemberInput(email="a@b.c", roles=["viewer", "viewer"])
    with pytest.raises(ValidationError):
        MemberInput(email="a@b.c", roles=["admin"])
    sched = {"requested_date": D, "qty": 1}
    PurchaseDocInput(lines=[{"item_id": ID, "schedules": [sched]}])
    with pytest.raises(ValidationError):
        PurchaseDocInput(lines=[])
    with pytest.raises(ValidationError):
        PurchaseDocInput(lines=[{"item_id": ID, "line_no": 10, "schedules": [sched]},
                                {"item_id": ID, "line_no": 10, "schedules": [sched]}])
    with pytest.raises(ValidationError):
        DemandOrderInput(demand_type="customer", lines=[{"item_id": ID, "qty": 2, "due_date": D, "serial_from": 5}])
    with pytest.raises(ValidationError):
        WorkOrderInput(item_id=ID, qty=1, due_date=D, start_date=D + timedelta(days=1))
    with pytest.raises(ValidationError):
        POST.validate_python({"type": "adjust", "lines": [{"item_id": ID, "location_id": LOC, "qty": 0}]})
    with pytest.raises(ValidationError):
        POST.validate_python({"type": "wo_receipt", "lines": [{"wo_id": "wko_" + "1" * 32, "location_id": LOC,
                                                                "qty": 0, "scrap_qty": 0}]})
    with pytest.raises(ValidationError):
        POST.validate_python({"type": "teleport", "lines": [{"item_id": ID}]})


# ---------------------------------------------------------------- work calendar (8.5, T-M5)


def test_workdays_t_m5():
    c = WorkCalendar()
    fri = date(2026, 11, 20)
    assert c.workday_sub(fri, 4) == date(2026, 11, 16)
    assert WorkCalendar(holidays=[date(2026, 11, 17)]).workday_sub(fri, 4) == date(2026, 11, 14)
    sun = date(2026, 11, 22)
    assert not c.is_workday(sun)
    assert c.workday_add(sun, 0) == date(2026, 11, 23) and c.workday_sub(sun, 0) == date(2026, 11, 21)
    assert c.workday_add(fri, 2) == date(2026, 11, 23) and c.workday_add(fri, 0) == fri
    assert c.workdays_between(date(2026, 11, 16), fri) == 4
    with pytest.raises(ValueError):
        WorkCalendar(workdays=[])


# ---------------------------------------------------------------- posting planner (4)


def _ctx(**kw) -> INV.PostingContext:
    items = {ID: INV.ItemInfo(ID, "P-1", "EA", standard_cost=2.0),
             ID2: INV.ItemInfo(ID2, "L-1", "L", lot_controlled=True, shelf_life_days=100)}
    locs = {LOC: INV.LocInfo(LOC, "STORES", "stores", receipt_default=True),
            LOC2: INV.LocInfo(LOC2, "LS", "line_side"), QUAR: INV.LocInfo(QUAR, "Q", "quarantine")}
    return INV.PostingContext(today=D, items=items, locations=locs, **kw)


def _post(body: dict, ctx: INV.PostingContext) -> INV.PostingPlan:
    return INV.plan_posting(POST.validate_python(body), ctx)


def _err(body: dict, ctx: INV.PostingContext) -> RuleError:
    with pytest.raises(RuleError) as e:
        _post(body, ctx)
    return e.value


def test_receipt_issue_and_insufficient_stock():
    ctx = _ctx()
    p = _post({"type": "receipt_misc", "lines": [{"item_id": ID, "location_id": LOC, "qty": 5}]}, ctx)
    assert [(t.txn_type, t.qty, t.set_last_receipt, t.unit_cost) for t in p.transactions] == \
        [("receipt_misc", 5.0, D, 2.0)]
    ctx = _ctx(balances={(ID, LOC, ""): INV.BalInfo(ID, LOC, "", 10, 4)})
    e = _err({"type": "issue_misc", "reason_code": "SCRAP", "lines": [{"item_id": ID, "location_id": LOC,
                                                                        "qty": 7}]}, ctx)
    assert (e.status, e.code, e.details["available"], e.details["requested"]) == (409, "INV_INSUFFICIENT_STOCK", 6,
                                                                                  7)
    assert _err({"type": "issue_misc", "lines": [{"item_id": ID, "location_id": LOC, "qty": 1}]},
                ctx).code == "INV_REASON_REQUIRED"
    assert _err({"type": "receipt_misc", "lines": [{"item_id": ID, "location_id": LOC, "qty": 1.5}]},
                ctx).code == "INV_FRACTIONAL_QTY"
    assert _err({"type": "receipt_misc", "txn_date": "2026-09-01", "lines": [{"item_id": ID, "location_id": LOC,
                                                                              "qty": 1}]}, ctx).code == \
        "INV_BACKDATE_LIMIT"
    assert _err({"type": "receipt_misc", "txn_date": "2026-11-03", "lines": [{"item_id": ID, "location_id": LOC,
                                                                              "qty": 1}]}, ctx).code == \
        "INV_BACKDATE_LIMIT"
    ctx.locations[LOC2].active = False
    assert _err({"type": "receipt_misc", "lines": [{"item_id": ID, "location_id": LOC2, "qty": 1}]},
                ctx).code == "INV_LOCATION_INACTIVE"


def test_lot_rules_new_lot_expiry_and_fefo():
    ctx = _ctx()
    assert _err({"type": "receipt_misc", "lines": [{"item_id": ID2, "location_id": LOC, "qty": 1}]},
                ctx).code == "INV_LOT_REQUIRED"
    assert _err({"type": "receipt_misc", "lines": [{"item_id": ID, "location_id": LOC, "qty": 1, "lot_code": "X"}]},
                ctx).code == "INV_LOT_NOT_ALLOWED"
    p = _post({"type": "receipt_misc", "lines": [{"item_id": ID2, "location_id": LOC, "qty": 1.5, "lot_code": "N"}]},
              ctx)
    assert p.new_lots[0].expires_on == D + timedelta(days=100) and p.new_lots[0].received_on == D
    lots = {(ID2, "A"): INV.LotInfo(ID2, "A", "lot_a", D + timedelta(days=30)),
            (ID2, "B"): INV.LotInfo(ID2, "B", "lot_b", D + timedelta(days=10)),
            (ID2, "C"): INV.LotInfo(ID2, "C", "lot_c", None),
            (ID2, "X"): INV.LotInfo(ID2, "X", "lot_x", D),            # expired today
            (ID2, "H"): INV.LotInfo(ID2, "H", "lot_h", None, hold=True)}
    bals = {(ID2, LOC, k): INV.BalInfo(ID2, LOC, k, 2) for k in "ABCXH"}
    ctx = _ctx(lots=lots, balances=bals)
    p = _post({"type": "issue_misc", "reason_code": "S", "lines": [{"item_id": ID2, "location_id": LOC, "qty": 5}]},
              ctx)
    assert [(t.lot_code, t.qty) for t in p.transactions] == [("B", -2), ("A", -2), ("C", -1)]
    assert _err({"type": "issue_misc", "reason_code": "S", "lines": [{"item_id": ID2, "location_id": LOC,
                                                                       "qty": 1, "lot_code": "X"}]}, ctx).code == \
        "INV_LOT_EXPIRED"
    assert _err({"type": "issue_misc", "reason_code": "S", "lines": [{"item_id": ID2, "location_id": LOC,
                                                                       "qty": 1, "lot_code": "H"}]}, ctx).code == \
        "INV_LOT_ON_HOLD"
    p = _post({"type": "transfer", "lines": [{"item_id": ID2, "from_location_id": LOC, "to_location_id": QUAR,
                                               "qty": 2, "lot_code": "X"}]}, ctx)
    assert [t.qty for t in p.transactions] == [-2, 2]
    assert INV.pick_fefo([((ID2, LOC, k), 2, lots[(ID2, k)].expires_on, lots[(ID2, k)].hold) for k in "ABCXH"], 3,
                         D) == [((ID2, LOC, "B"), 2), ((ID2, LOC, "A"), 1)]


def test_transfer_count_and_reservations():
    bals = {(ID, LOC, ""): INV.BalInfo(ID, LOC, "", 10, 6, last_receipt_on=D - timedelta(days=3))}
    res = [INV.ResInfo("r1", "c1", (ID, LOC, ""), 4, 1), INV.ResInfo("r2", "c2", (ID, LOC, ""), 2, 2)]
    ctx = _ctx(balances=bals, reservations=res)
    assert _err({"type": "transfer", "lines": [{"item_id": ID, "from_location_id": LOC, "to_location_id": LOC,
                                                 "qty": 1}]}, ctx).code == "INV_SAME_LOCATION"
    p = _post({"type": "transfer", "lines": [{"item_id": ID, "from_location_id": LOC, "to_location_id": LOC2,
                                               "qty": 4}]}, ctx)
    assert p.transactions[1].set_last_receipt == D - timedelta(days=3)
    assert _err({"type": "transfer", "lines": [{"item_id": ID, "from_location_id": LOC, "to_location_id": LOC2,
                                                 "qty": 5}]}, ctx).code == "INV_INSUFFICIENT_STOCK"
    p = _post({"type": "count", "lines": [{"item_id": ID, "location_id": LOC, "counted_qty": 3}]}, ctx)
    assert [t.qty for t in p.transactions] == [-7] and p.transactions[0].txn_type == "adjust"
    assert p.reservation_qty == {"r1": 1.0} and p.warnings[0]["code"] == "INV_RESERVATION_REDUCED"
    p = _post({"type": "count", "lines": [{"item_id": ID, "location_id": LOC, "counted_qty": 10}]}, ctx)
    assert p.transactions == []


def _po_ctx(status: str = "open", received: float = 0.0, pct: float = 0.0) -> INV.PostingContext:
    sc = INV.SchedInfo("psc_1", 1, 10, received, False, "pln_1", 10, ID, 3.5, "pdc_1", "PO-1", "po", status)
    return _ctx(schedules={"psc_1": sc}, over_receipt_pct=pct)


def test_po_receipt_rules():
    body = {"type": "po_receipt", "lines": [{"schedule_id": "psc_" + "0" * 32, "qty": 4}]}
    body["lines"][0]["schedule_id"] = "psc_1".ljust(36, "0")
    ctx = _po_ctx()
    ctx.schedules = {body["lines"][0]["schedule_id"]: ctx.schedules["psc_1"]}
    sid = body["lines"][0]["schedule_id"]
    ctx.schedules[sid].id = sid
    p = _post(body, ctx)
    assert p.transactions[0].location_id == LOC and p.transactions[0].unit_cost == 3.5
    assert p.schedule_received == {sid: 4.0}
    body["lines"][0]["qty"] = 11
    e = _err(body, ctx)
    assert (e.status, e.code, e.details["open_qty"]) == (409, "PUR_OVER_RECEIPT", 10)
    ctx.over_receipt_pct = 10
    assert _post(body, ctx).schedule_received[sid] == 11
    ctx.schedules[sid].doc_status = "draft"
    assert _err(body, ctx).code == "MFG_INVALID_STATE"
    ctx.schedules[sid].doc_status = "open"
    ctx.locations[LOC].receipt_default = False
    assert _err(body, ctx).code == "INV_LOCATION_REQUIRED"


def test_wo_issue_return_receipt_and_ship():
    wo = "wko_" + "1" * 32
    comp = "woc_" + "1" * 32
    dl = "dml_" + "1" * 32
    bals = {(ID, LOC, ""): INV.BalInfo(ID, LOC, "", 10, 5)}
    ctx = _ctx(balances=bals, reservations=[INV.ResInfo("r1", comp, (ID, LOC, ""), 5)],
               components={comp: INV.CompInfo(comp, wo, ID, 8, 0)},
               work_orders={wo: INV.WoInfo(wo, "WO-1", "released", ID2, 2, 0)},
               demand_lines={dl: INV.DemLineInfo(dl, "dmo_1", "DO-1", "open", 10, ID, 3, 0)})
    p = _post({"type": "wo_issue", "lines": [{"wo_component_id": comp, "location_id": LOC, "qty": 8}]}, ctx)
    assert p.reservation_qty == {"r1": 0.0} and p.component_issued == {comp: 8} and wo in p.wo_touched
    assert _err({"type": "wo_issue", "lines": [{"wo_component_id": comp, "location_id": LOC, "qty": 9}]},
                ctx).code == "WO_OVER_ISSUE"
    assert _err({"type": "wo_return", "lines": [{"wo_component_id": comp, "location_id": LOC, "qty": 1}]},
                ctx).code == "WO_RETURN_ABOVE_ISSUED"
    p = _post({"type": "wo_receipt", "lines": [{"wo_id": wo, "location_id": LOC, "qty": 2, "lot_code": "F1",
                                                 "scrap_qty": 1}]}, ctx)
    assert p.wo_completed == {wo: 2} and p.wo_scrapped == {wo: 1} and p.reservation_qty == {"r1": 0.0}
    ctx.work_orders[wo].status = "planned"
    assert _err({"type": "wo_issue", "lines": [{"wo_component_id": comp, "location_id": LOC, "qty": 1}]},
                ctx).code == "MFG_INVALID_STATE"
    assert _err({"type": "ship", "lines": [{"demand_line_id": dl, "location_id": LOC, "qty": 4}]},
                ctx).code == "DEM_OVER_SHIPMENT"
    assert _post({"type": "ship", "lines": [{"demand_line_id": dl, "location_id": LOC, "qty": 3}]},
                 ctx).demand_shipped == {dl: 3}
    assert INV.validate_posting(POST.validate_python({"type": "ship", "lines": [
        {"demand_line_id": dl, "location_id": LOC, "qty": 9}]}), ctx)[0]["code"] == "DEM_OVER_SHIPMENT"


def test_reversal_needs_stock():
    bals = {(ID, LOC, ""): INV.BalInfo(ID, LOC, "", 3, 0)}
    ctx = _ctx(balances=bals)
    orig = [INV.OrigTxn(1, "receipt_misc", ID, LOC, None, 5)]
    with pytest.raises(RuleError) as e:
        INV.plan_reversal("receipt_misc", orig, ctx, D)
    assert e.value.code == "INV_INSUFFICIENT_STOCK"
    p = INV.plan_reversal("issue_misc", [INV.OrigTxn(1, "issue_misc", ID, LOC, None, -2)], ctx, D)
    assert [t.qty for t in p.transactions] == [2]


# ---------------------------------------------------------------- purchasing (5)


def test_pr_and_po_status_machines():
    assert PUR.check_action("pr", "draft", "submit") == "submitted"
    assert PUR.check_action("pr", "submitted", "approve") == "approved"
    assert PUR.check_action("pr", "rejected", "revise") == "draft"
    with pytest.raises(RuleError) as e:
        PUR.check_action("pr", "draft", "approve")
    assert e.value.code == "MFG_INVALID_STATE" and e.value.details["allowed_from"] == ["submitted"]
    with pytest.raises(RuleError):
        PUR.check_self_approval("usr_m", "usr_m", is_owner=False)
    PUR.check_self_approval("usr_m", "usr_m", is_owner=True)
    assert PUR.check_action("po", "draft", "issue") == "open"
    with pytest.raises(RuleError):
        PUR.check_po_cancel("open", has_receipts=True)
    with pytest.raises(RuleError) as e:
        PUR.check_editable("po", "received")
    assert e.value.code == "MFG_DOC_READONLY"
    PUR.check_deletable("pr", "draft", "manual", False)
    with pytest.raises(RuleError):
        PUR.check_deletable("pr", "draft", "mrp", False)
    S = PUR.SchedState
    assert PUR.derive_po_status("open", [S(10, 0, False), S(10, 0, False)]) == "open"
    assert PUR.derive_po_status("open", [S(10, 4, False), S(10, 0, False)]) == "partially_received"
    assert PUR.derive_po_status("partially_received", [S(10, 10, False), S(10, 2, True)]) == "received"
    assert PUR.derive_po_status("received", [S(10, 6, False)]) == "partially_received"
    assert PUR.derive_pr_status("approved", ["converted", "cancelled"]) == "ordered"


def test_schedule_dates_and_source_resolution():
    v = PUR.schedule_view(30, 10, False, date(2026, 10, 20), None, 2, D)
    assert v == {"open_qty": 20, "dock_date": date(2026, 10, 20), "available_date": date(2026, 10, 22),
                 "overdue": True, "overdue_days": 13}
    assert PUR.schedule_view(30, 0, False, D, date(2027, 1, 5), 2, D)["available_date"] == date(2027, 1, 7)

    class O:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    item = O(lead_time_days=30, min_order_qty=10, order_multiple=0)
    sups = {"s1": O(id="s1", code="A", active=True, lead_time_days=20), "s2": O(id="s2", code="B", active=True,
                                                                             lead_time_days=None),
            "s3": O(id="s3", code="C", active=False, lead_time_days=1)}
    rows = [O(id="r1", supplier_id="s1", active=True, preferred=False, lead_time_days=None, min_order_qty=0,
              order_multiple=0, units_per_purchase_unit=1, unit_price=1.0, currency=""),
            O(id="r2", supplier_id="s2", active=True, preferred=False, lead_time_days=15, min_order_qty=50,
              order_multiple=5, units_per_purchase_unit=10, unit_price=2.0, currency=""),
            O(id="r3", supplier_id="s3", active=True, preferred=True, lead_time_days=1, min_order_qty=0,
              order_multiple=0, units_per_purchase_unit=1, unit_price=0.5, currency="")]
    src = PUR.resolve_source(item, rows, sups)          # preferred row's supplier is inactive -> smallest lead
    assert (src.item_supplier_id, src.lead_time_days, src.min_order_qty, src.order_multiple, src.pack) == \
        ("r2", 15, 50, 5, 10)
    rows[0].preferred = True
    assert PUR.resolve_source(item, rows, sups).lead_time_source == "supplier"
    assert PUR.resolve_source(item, [], sups).lead_time_days == 30
    assert PUR.allocate_receipt([("a", date(2026, 11, 10), 5), ("b", date(2026, 11, 3), 3)], 10) == \
        [("b", 3), ("a", 7)]
    assert PUR.doc_value([(10, 2.0, 4), (5, None, 5)]) == (None, None)


# ---------------------------------------------------------------- demand (6)


def test_demand_machine_and_serials():
    assert DEM.check_action("draft", "open") == "open"
    assert DEM.check_action("closed", "open") == "open"
    with pytest.raises(RuleError):
        DEM.check_action("open", "cancel", has_shipments=True)
    with pytest.raises(RuleError):
        DEM.check_editable("closed")
    assert DEM.derive_status("open", [(5, 5), (2, 2)]) == "closed"
    assert DEM.reopen_after_reversal("closed", [(5, 3)]) == "open"
    assert DEM.serial_qty_error(True, 10, 101, 110) is None
    assert DEM.serial_qty_error(True, 9, 101, 110).code == "DEM_SERIAL_QTY_MISMATCH"
    assert DEM.serial_qty_error(False, 10, 101, 110).code == "MFG_SERIAL_NOT_ALLOWED"
    lines = [DEM.SerialLine(0, ID, 101, 110), DEM.SerialLine(1, ID, 111, 120), DEM.SerialLine(2, ID, 110, 112),
             DEM.SerialLine(3, ID2, 101, 110)]
    assert DEM.serial_overlaps(lines) == [(0, 2), (1, 2)]
    with pytest.raises(RuleError):
        DEM.check_line_edit(False, False, 1, 2, 0)


# ---------------------------------------------------------------- work orders (7)


def test_wo_machine_and_put_rules():
    assert WOR.check_action("planned", "release") == "released"
    with pytest.raises(RuleError):
        WOR.check_action("completed", "release")
    with pytest.raises(RuleError) as e:
        WOR.check_put("released", qty=1, qty_completed=2, item_changed=False)
    assert e.value.code == "WO_QTY_BELOW_COMPLETED"
    with pytest.raises(RuleError) as e:
        WOR.check_put("in_progress", qty=5, qty_completed=2, item_changed=False, components=[(0, 1, 2)])
    assert e.value.code == "WO_COMPONENT_BELOW_ISSUED"
    with pytest.raises(RuleError):
        WOR.check_put("closed", qty=5, qty_completed=0, item_changed=False)
    with pytest.raises(RuleError) as e:
        WOR.check_deletable("planned", True)
    assert e.value.code == "WO_HAS_TRANSACTIONS"
    assert WOR.derive_status("released", 5, 0, touched=True) == "in_progress"
    assert WOR.derive_status("in_progress", 5, 5, touched=True) == "completed"
    assert WOR.derive_status("completed", 5, 3, touched=True) == "in_progress"


def _bal(i: str, item: str, kind: str, qty: float, reserved: float = 0, exp: date | None = None, hold: bool = False,
         code: str = "S") -> WOR.StockBal:
    return WOR.StockBal(i, item, "loc_" + i, code, kind, None, None, exp, hold, qty, reserved)


def test_reservation_planning_fefo_and_kitting():
    bals = [_bal("b1", ID, "stores", 5, code="ST"), _bal("b2", ID, "line_side", 3, code="LS"),
            _bal("b3", ID, "quarantine", 50), _bal("b4", ID, "stores", 9, exp=D), _bal("b5", ID, "stores", 9, hold=True),
            _bal("b6", ID, "stores", 4, exp=D + timedelta(days=5), code="ZZ")]
    plan, summary = WOR.plan_reservations([WOR.ResComp("c1", ID, 10, 1)], bals, D)
    assert plan == [("c1", "b6", 4), ("c1", "b2", 3), ("c1", "b1", 2)] and summary[0]["shortage"] == 0
    plan, summary = WOR.plan_reservations([WOR.ResComp("c1", ID, 20, 0)], bals, D)
    assert summary == [{"component_id": "c1", "qty": 12, "shortage": 8}]
    wo = WOR.KitWo("w1", "WO-1", "released", 5, D, [WOR.KitComponent("c1", ID, 20, 2, 3)])
    k = WOR.kitting(wo, bals, D, {ID: {"type": "po_schedule"}})
    assert k["rows"][0]["free"] == 12 and k["rows"][0]["shortage"] == 3 and not k["totals"]["kit_complete"]
    w2 = WOR.KitWo("w2", "WO-2", "planned", 1, D + timedelta(days=3), [WOR.KitComponent("c2", ID, 10, 0, 0)])
    sim = WOR.simulate_kitting([wo, w2], bals, None, "priority", D)
    assert [r["number"] for r in sim["rows"]] == ["WO-2", "WO-1"]
    assert sim["rows"][0]["kit_complete"] and sim["rows"][1]["short_components"] == 1
    assert sim["items_short"][0]["total_shortage"] == 13 and sim["items_short"][0]["wo_count"] == 1
    sim = WOR.simulate_kitting([wo, w2], bals, None, "start_date", D)
    assert [r["number"] for r in sim["rows"]] == ["WO-1", "WO-2"]
