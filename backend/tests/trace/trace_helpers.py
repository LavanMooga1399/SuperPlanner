"""A small genealogy plant built through the API (M5-DESIGN 13 T-T1/T-T2): capacitor lot -> 2 PCB WOs (serials
P1..P3) -> 1 TPU WO (serials T1..T3, each consuming one PCB) -> 2 shipments to two customers."""

from __future__ import annotations

import itertools
from typing import Any

from apimfgm2_helpers import Api

_n = itertools.count(1)
PLANT_FIELDS = ("name", "utc_offset", "planning_horizon_days", "currency", "attributes", "mrp_workdays",
                "mrp_day_minutes", "mrp_defer_tolerance_days", "mrp_release_window_days", "over_receipt_pct",
                "time_zone", "aps_freeze_hours", "aps_horizon_days", "aps_overtime_policy", "replan_policy",
                "replan_debounce_minutes", "overrun_tolerance_pct", "adherence_tolerance_minutes",
                "wo_receipt_location_id", "backflush_location_id")


def ev(api: Api, op_id: str, event_type: str, **kw: Any) -> dict[str, Any]:
    body = {"client_event_id": f"trc-{next(_n):08d}", "wo_operation_id": op_id, "event_type": event_type, **kw}
    return api.req("POST", "/floor/events", 201, json=body).json()


def released(api: Api, item_id: str, qty: float) -> dict[str, Any]:
    wo = api.post("/work-orders", {"item_id": item_id, "qty": qty, "due_date": "2026-12-01",
                                   "start_date": "2026-11-02"})
    return api.post(f"/work-orders/{wo['id']}/release", {"override_reason": "test"}, status=200,
                    version=wo["row_version"])


def build(api: Api) -> dict[str, Any]:
    st = api.location("ST")
    fg = api.location("FG")
    q = api.location("QA", "quarantine")
    g = api.post("/groups", {"code": "G", "name": "Group"})
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    tpl = api.post("/shift-templates", {"code": "24X7", "name": "24x7", "shifts": [
        {"name": "A", "days": days, "start": "00:00", "end": "12:00"},
        {"name": "B", "days": days, "start": "12:00", "end": "24:00"}]})
    api.post("/shift-assignments", {"shift_template_id": tpl["id"], "target_type": "group", "group_id": g["id"],
                                    "effective_from": "2026-01-01"})
    api.post("/lines", {"group_id": g["id"], "code": "L1", "name": "Line 1"})
    cap = api.item("CAP", lot_controlled=True)
    pcb = api.item("PCB", "make", serialized=True)
    tpu = api.item("TPU", "make", serialized=True)
    for parent, child, qp in ((pcb, cap, 2), (tpu, pcb, 1)):
        b = api.post("/boms", {"item_id": parent["id"], "lines": [{"find_number": "1", "child_item_id": child["id"],
                                                                  "qty_per": qp, "operation_seq": 10}]})
        api.post(f"/boms/{b['id']}/release", {}, status=200, version=b["row_version"])
        rt = api.post("/routings", {"item_id": parent["id"], "operations": [
            {"seq": 10, "name": "Build", "group_id": g["id"], "setup_minutes": 1, "run_minutes": 1,
             "capture_serial": True, "crew_size": 0, "labor": "unattended"}]})
        api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
    p = api.get("/plant")
    api.put("/plant", {**{k: v for k, v in p.items() if k in PLANT_FIELDS}, "wo_receipt_location_id": fg["id"]},
            p["row_version"])
    api.receive(cap["id"], st["id"], 100, lot_code="L-2611", supplier_lot="SUPP-2611")
    lot = api.get("/lots", item_id=cap["id"])["items"][0]
    pcb_wos = []
    serial = 0
    for qty in (2, 1):
        w = released(api, pcb["id"], qty)
        comp = w["components"][0]
        api.post("/inventory/postings", {"type": "wo_issue", "lines": [
            {"wo_component_id": comp["id"], "location_id": st["id"], "qty": 2 * qty, "lot_code": "L-2611"}]})
        op = api.get(f"/work-orders/{w['id']}/operations")["items"][0]
        ev(api, op["id"], "start")
        ev(api, op["id"], "complete", qty_good=qty,
           serials={"produced": [f"P{serial + i + 1}" for i in range(qty)]})
        serial += qty
        pcb_wos.append(w)
    tw = released(api, tpu["id"], 3)
    op = api.get(f"/work-orders/{tw['id']}/operations")["items"][0]
    ev(api, op["id"], "start")
    for i in range(3):
        ev(api, op["id"], "complete" if i == 2 else "report", qty_good=1,
           serials={"produced": [f"T{i + 1}"], "consumed": [{"item_id": pcb["id"], "serial": f"P{i + 1}"}]})
    ships = []
    for k, cust in enumerate(("Rail zone A", "Rail zone B")):
        o = api.post("/demand-orders", {"number": f"DO-{k + 1}", "demand_type": "customer", "customer": cust,
                                        "lines": [{"line_no": 1, "item_id": tpu["id"], "qty": 1,
                                                   "due_date": "2026-12-01"}]})
        o = api.post(f"/demand-orders/{o['id']}/open", {}, status=200, version=o["row_version"]) \
            if o["status"] == "draft" else o
        api.post("/inventory/postings", {"type": "ship", "lines": [
            {"demand_line_id": o["lines"][0]["id"], "location_id": fg["id"], "qty": 1}]})
        ships.append(o)
    sers = {x["serial"]: x for x in api.get("/serials", limit=50)["items"]}
    return {"st": st, "fg": fg, "qa": q, "cap": cap, "pcb": pcb, "tpu": tpu, "lot": lot, "pcb_wos": pcb_wos,
            "tpu_wo": tw, "serials": sers, "orders": ships}


def flat(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = [node]
    for c in node["children"]:
        out += flat(c)
    return out
