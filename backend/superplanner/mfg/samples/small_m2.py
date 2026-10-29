"""Sample `small`, M2 part (M2-DESIGN 13.2): 3 locations, 2 suppliers, stock for 8 of the 9 components, one
staggered PO for the MCU, two demand orders.

Intended MRP outcome (as_of = anchor): `DO-SM-001` on time from stock + the first MCU delivery; `DO-SM-002` late
(the MCUs left after `DO-SM-001` do not cover it and the second delivery lands after its WO start: `MRP_EXPEDITE` on
schedule 2); a planned PR for the bare PCB with `release_now`. Tuning recorded in M2-DESIGN 22.WP-A.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..bundle import MfgBundle

SUPPLIER_OF = {"SM-BPCB-100": "SUP-B", "SM-RES-10K": "SUP-A", "SM-RES-1K": "SUP-A", "SM-CAP-100N": "SUP-B",
               "SM-CAP-10U": "SUP-B", "SM-MCU-01": "SUP-A", "SM-CON-01": "SUP-B", "SM-COAT-01": "SUP-A",
               "SM-LBL-01": "SUP-B"}
PRICES = {"SM-BPCB-100": 180.0, "SM-RES-10K": 0.05, "SM-RES-1K": 0.05, "SM-CAP-100N": 0.08, "SM-CAP-10U": 0.6,
          "SM-MCU-01": 240.0, "SM-CON-01": 35.0, "SM-COAT-01": 1900.0, "SM-LBL-01": 2.0}
STOCK = {"SM-RES-10K": 5000, "SM-RES-1K": 5000, "SM-CAP-100N": 5000, "SM-CAP-10U": 4000, "SM-MCU-01": 30,
         "SM-CON-01": 100, "SM-COAT-01": 2.0, "SM-LBL-01": 200}


def master(b: MfgBundle) -> MfgBundle:
    b["locations"] = [
        {"code": "STORES", "name": "Main stores", "kind": "stores"},
        {"code": "GOODS-IN", "name": "Goods-in inspection", "kind": "inspection", "receipt_default": True},
        {"code": "QUAR", "name": "Quarantine", "kind": "quarantine"}]
    b["suppliers"] = [
        {"code": "SUP-A", "name": "Supplier A (fictional)", "currency": "INR"},
        {"code": "SUP-B", "name": "Supplier B (fictional)", "currency": "INR"}]
    rows: list[dict[str, Any]] = []
    for pn, sup in SUPPLIER_OF.items():
        row = {"part_number": pn, "supplier_code": sup, "unit_price": PRICES[pn], "currency": "INR",
               "preferred": True}
        if pn == "SM-MCU-01":
            row["lead_time_days"] = 84
        if pn == "SM-BPCB-100":
            row["lead_time_days"] = 14
        rows.append(row)
    rows.append({"part_number": "SM-MCU-01", "supplier_code": "SUP-B", "lead_time_days": 112, "unit_price": 255.0,
                 "currency": "INR", "preferred": False})
    b["item_suppliers"] = rows
    for it in b["items"]:
        if it["part_number"] in PRICES:
            it["standard_cost"] = PRICES[it["part_number"]]
    return b


def transactions(b: MfgBundle, anchor: date) -> dict[str, list[dict[str, Any]]]:
    def a(n: int) -> date:
        return anchor + timedelta(days=n)

    return {
        "stock": [{"part_number": pn, "location_code": "STORES", "qty": float(q)} for pn, q in STOCK.items()],
        "purchase_docs": [{"doc_type": "po", "number": "PO-SM-0001", "status": "open", "supplier_code": "SUP-A",
                           "currency": "INR", "order_date": a(-60)}],
        "purchase_lines": [{"doc_type": "po", "number": "PO-SM-0001", "line_no": 10, "part_number": "SM-MCU-01",
                            "unit_price": 240.0}],
        "purchase_schedules": [
            {"doc_type": "po", "number": "PO-SM-0001", "line_no": 10, "seq": 1, "requested_date": a(10), "qty": 40.0},
            {"doc_type": "po", "number": "PO-SM-0001", "line_no": 10, "seq": 2, "requested_date": a(50),
             "qty": 40.0}],
        "demand_orders": [
            {"number": "DO-SM-001", "demand_type": "customer", "customer": "Customer A (fictional)", "priority": 2,
             "status": "open"},
            {"number": "DO-SM-002", "demand_type": "spares", "customer": "Customer A (fictional)", "priority": 5,
             "status": "open"}],
        "demand_lines": [
            {"number": "DO-SM-001", "line_no": 10, "part_number": "SM-100", "qty": 50.0, "due_date": a(21)},
            {"number": "DO-SM-002", "line_no": 10, "part_number": "SM-100", "qty": 20.0, "due_date": a(45)}],
    }
