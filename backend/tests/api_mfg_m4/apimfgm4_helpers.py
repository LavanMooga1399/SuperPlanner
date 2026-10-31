"""M4 API test helpers: a tiny two-operation plant built through the API (fast) on top of the M2/M3 helpers."""

from __future__ import annotations

import itertools
from typing import Any

from apimfgm2_helpers import MFG, A, Api, acc_app, im, make_app, sign_up  # noqa: F401

_n = itertools.count(1)


def cid() -> str:
    return f"test-{next(_n):08d}"


def plant(api: Api, *, ops: int = 2, wo_qty: float = 10, serialized: bool = False, capture_seq: int | None = None,
          backflush: bool = False, bf_stock: float = 1000, comp_qty_per: float = 4, lot_fg: bool = False,
          yield_pct: float = 100, receipt: bool = True, batch: int | None = None, merge: bool = False,
          wait: int = 0) -> dict[str, Any]:
    """Item FG (make) with `ops` operations (seq 10, 20, ...) on group G (line L1, L2) and component C (buy, qty 4
    per FG, at op 10; backflushed from LS when `backflush`). One released WO of `wo_qty`. Returns ids."""
    fg_loc = api.location("FG")
    ls = api.location("LS", "line_side")
    g = api.post("/groups", {"code": "G", "name": "Group"})
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    tpl = api.post("/shift-templates", {"code": "24X7", "name": "Round the clock", "shifts": [
        {"name": "A", "days": days, "start": "00:00", "end": "12:00"},
        {"name": "B", "days": days, "start": "12:00", "end": "24:00"}]})
    api.post("/shift-assignments", {"shift_template_id": tpl["id"], "target_type": "group", "group_id": g["id"],
                                    "effective_from": "2026-01-01"})
    l1 = api.post("/lines", {"group_id": g["id"], "code": "L1", "name": "Line 1", "location_id": ls["id"],
                             "batch_merge": merge, "batch_wait_minutes": wait})
    l2 = api.post("/lines", {"group_id": g["id"], "code": "L2", "name": "Line 2", "active": batch is None})
    comp = api.item("C", issue_method="backflush" if backflush else "manual")
    fg = api.item("FG", "make", serialized=serialized, lot_controlled=lot_fg)
    b = api.post("/boms", {"item_id": fg["id"],
                           "lines": [{"find_number": "1", "child_item_id": comp["id"], "qty_per": comp_qty_per,
                                     "operation_seq": 10}]})
    api.post(f"/boms/{b['id']}/release", {}, status=200, version=b["row_version"])
    rt = api.post("/routings", {"item_id": fg["id"], "operations": [
        {"seq": 10 * (k + 1), "name": f"Op {10 * (k + 1)}", "group_id": g["id"], "setup_minutes": 10,
         "run_minutes": 2, "yield_pct": yield_pct, "capture_serial": capture_seq == 10 * (k + 1), "crew_size": 0,
         **({"run_per": "batch", "units_per_batch": batch} if batch else {}),
         "labor": "unattended"}
        for k in range(ops)]})
    api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
    p = api.get("/plant")
    body = {k: v for k, v in p.items() if k in PLANT_FIELDS}
    if receipt:
        body["wo_receipt_location_id"] = fg_loc["id"]
    body["backflush_location_id"] = ls["id"]
    api.put("/plant", body, p["row_version"])
    if bf_stock:
        api.receive(comp["id"], ls["id"], bf_stock)
    wo = api.post("/work-orders", {"item_id": fg["id"], "qty": wo_qty, "due_date": "2026-12-01",
                                   "start_date": "2026-11-02"})
    wo = api.post(f"/work-orders/{wo['id']}/release", {"override_reason": "test"}, status=200,
                  version=wo["row_version"])
    opsr = api.get(f"/work-orders/{wo['id']}/operations")["items"]
    return {"fg": fg, "comp": comp, "g": g, "l1": l1, "l2": l2, "fg_loc": fg_loc, "ls": ls, "wo": wo, "ops": opsr}


PLANT_FIELDS = ("name", "utc_offset", "planning_horizon_days", "currency", "attributes", "mrp_workdays",
                "mrp_day_minutes", "mrp_defer_tolerance_days", "mrp_release_window_days", "over_receipt_pct",
                "time_zone", "aps_freeze_hours", "aps_horizon_days", "aps_overtime_policy", "replan_policy",
                "replan_debounce_minutes", "overrun_tolerance_pct", "adherence_tolerance_minutes",
                "wo_receipt_location_id", "backflush_location_id")


def ev(api: Api, op_id: str, event_type: str, status: int = 201, **kw: Any) -> dict[str, Any]:
    body = {"client_event_id": kw.pop("client_event_id", None) or cid(), "wo_operation_id": op_id,
            "event_type": event_type, **kw}
    r = api.req("POST", "/floor/events", status, json=body)
    return r.json()
