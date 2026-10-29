"""Sample `medium`, M2 part (M2-DESIGN 13.4): 3 locations, 3 suppliers, stock for ~80% of the buy items, 3 POs
(one staggered), 2 demand orders for MD-200 (20 and 30, two priorities), 1 released WO.

Intended MRP outcome: the second (lower-priority) demand line is late because the 210-day blank MCU only covers the
first one."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any

from ..bundle import MfgBundle
from .m2common import component_rows, dataset, per_unit, price, schedules

SEED = 2002
SUPPLIERS = (("SUP-A", "Supplier A (fictional)"), ("SUP-B", "Supplier B (fictional)"),
             ("SUP-C", "Supplier C (fictional)"))


def master(b: MfgBundle) -> MfgBundle:
    rng = random.Random(SEED)
    b["locations"] = [
        {"code": "STORES", "name": "Main stores", "kind": "stores"},
        {"code": "GOODS-IN", "name": "Goods-in inspection", "kind": "inspection", "receipt_default": True},
        {"code": "QUAR", "name": "Quarantine", "kind": "quarantine"}]
    b["suppliers"] = [{"code": c, "name": n, "currency": "INR"} for c, n in SUPPLIERS]
    rows = []
    buys = sorted((r for r in b["items"] if r["make_buy"] == "buy"), key=lambda r: r["part_number"])
    for k, it in enumerate(buys):
        p = price(rng, it["part_number"])
        it["standard_cost"] = p
        rows.append({"part_number": it["part_number"], "supplier_code": SUPPLIERS[k % 3][0], "unit_price": p,
                     "currency": "INR", "preferred": True})
    b["item_suppliers"] = rows
    return b


def transactions(b: MfgBundle, anchor: date) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(SEED + 1)

    def a(n: int) -> date:
        return anchor + timedelta(days=n)

    ds = dataset(b)
    need = per_unit(ds, "MD-200", anchor)
    wo_parts = set(per_unit(ds, "MD-PCB-PWR", anchor))
    stock = []
    for pn in sorted(need):
        it = ds.items_by_pn[pn]
        if it.make_buy != "buy":
            continue
        if pn == "MD-MCU-BLANK":
            q = 25.0
        elif (it.lead_time_days or 0) > 35 or pn in wo_parts or rng.random() < 0.8:
            q = need[pn] * 55 + (need.get(pn, 0) * 10 if pn in wo_parts else 0)
        else:
            continue
        q = float(math.ceil(q - 1e-9)) if it.uom == "EA" else round(q, 3)
        stock.append({"part_number": pn, "location_code": "STORES", "qty": q})
    pos = [("PO-MD-0001", "SUP-A", "MD-BPCB-MAIN", [(a(14), 20), (a(35), 20), (a(56), 20)]),
           ("PO-MD-0002", "SUP-B", "MD-CON-PWR-A", [(a(21), 60)]),
           ("PO-MD-0003", "SUP-C", "MD-COAT-01", [(a(7), 2)])]
    docs, lines, scheds = [], [], []
    for no, sup, pn, parts in pos:
        sup_code = next(r["supplier_code"] for r in b["item_suppliers"] if r["part_number"] == pn)
        docs.append({"doc_type": "po", "number": no, "status": "open", "supplier_code": sup_code, "currency": "INR",
                     "order_date": a(-30)})
        lines.append({"doc_type": "po", "number": no, "line_no": 10, "part_number": pn})
        scheds += schedules("po", no, 10, parts)
        del sup
    wo_start = a(-2)
    return {
        "stock": stock, "purchase_docs": docs, "purchase_lines": lines, "purchase_schedules": scheds,
        "demand_orders": [
            {"number": "DO-MD-001", "demand_type": "customer", "customer": "Customer M (fictional)", "priority": 1,
             "status": "open"},
            {"number": "DO-MD-002", "demand_type": "customer", "customer": "Customer N (fictional)", "priority": 3,
             "status": "open"}],
        "demand_lines": [
            {"number": "DO-MD-001", "line_no": 10, "part_number": "MD-200", "qty": 20.0, "due_date": a(77)},
            {"number": "DO-MD-002", "line_no": 10, "part_number": "MD-200", "qty": 30.0, "due_date": a(88)}],
        "work_orders": [{"number": "WO-MD-0001", "part_number": "MD-PCB-PWR", "qty": 10.0, "start_date": wo_start,
                         "due_date": a(5), "status": "released", "priority": 3}],
        "wo_components": component_rows(ds, "WO-MD-0001", "MD-PCB-PWR", 10, wo_start, None, 0.0),
    }
