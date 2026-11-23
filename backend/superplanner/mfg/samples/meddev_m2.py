"""Sample `meddev`, M2 part: locations, eight fictional suppliers (one in USD), item-supplier terms, opening stock in
supplier lots with expiry dates (one polypropylene lot expires in nine days), staggered purchase orders, a submitted
purchase request, demand orders from fictional Canadian provincial purchasing groups, hospitals and US distributors,
and three open work orders (one in progress for the floor).

Intended MRP outcome (as_of = anchor, pinned in `tests/mfg/test_meddev_sample.py`): the rush IV-set line and the
second prefillable-syringe line are late (make lead time / bought-in glass barrels), the expiring resin lot raises
`MRP_EXPIRING_STOCK`, and the glass-barrel PO needs expediting. The schedule (APS) has late demand on the IV-set
assembly line and suggests Saturday / night overtime; the Allow run opens it and cuts the lateness.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from ..bundle import MfgBundle
from .m2common import component_rows, dataset, per_unit, schedules

SUPPLIERS = (("SUP-RESIN", "Polymer resins supplier (fictional)", "CAD"),
             ("SUP-TUBE", "Precision tubing supplier (fictional)", "CAD"),
             ("SUP-ELAST", "Elastomer components supplier (fictional)", "CAD"),
             ("SUP-GLASS", "Pharmaceutical glass supplier (fictional)", "USD"),
             ("SUP-CHEM", "Chemicals and additives supplier (fictional)", "CAD"),
             ("SUP-PACK", "Sterile packaging supplier (fictional)", "CAD"),
             ("SUP-LABEL", "Label printer (fictional)", "CAD"),
             ("SUP-COMP", "Fluid-path components supplier (fictional)", "CAD"))

SOURCE = {"MDV-RES-PP": "SUP-RESIN", "MDV-RES-PET": "SUP-RESIN", "MDV-RES-PVC": "SUP-RESIN",
          "MDV-STL-TUBE": "SUP-TUBE", "MDV-FEP-20": "SUP-TUBE", "MDV-FEP-22": "SUP-TUBE",
          "MDV-STP-03": "SUP-ELAST", "MDV-STP-10": "SUP-ELAST", "MDV-CLS-13": "SUP-ELAST",
          "MDV-NSH-1ML": "SUP-ELAST", "MDV-GLS-1ML": "SUP-GLASS", "MDV-SIL-OIL": "SUP-CHEM",
          "MDV-ADH-UV": "SUP-CHEM", "MDV-SOLV": "SUP-CHEM", "MDV-NACL": "SUP-CHEM", "MDV-EDTA": "SUP-CHEM",
          "MDV-SST-GEL": "SUP-CHEM", "MDV-TIP-CAP": "SUP-COMP", "MDV-CLAMP": "SUP-COMP", "MDV-LUER-M": "SUP-COMP",
          "MDV-LBL-UDI": "SUP-LABEL", "MDV-IFU-IVS": "SUP-LABEL", "MDV-TYV-LID": "SUP-PACK",
          "MDV-POUCH-S": "SUP-PACK", "MDV-POUCH-L": "SUP-PACK", "MDV-NEST-1ML": "SUP-PACK", "MDV-CTN-100": "SUP-PACK"}
PRICES = {"MDV-RES-PP": 2.85, "MDV-RES-PET": 3.10, "MDV-RES-PVC": 3.40, "MDV-STL-TUBE": 0.42, "MDV-FEP-20": 1.95,
          "MDV-FEP-22": 1.85, "MDV-STP-03": 0.012, "MDV-STP-10": 0.018, "MDV-CLS-13": 0.035, "MDV-NSH-1ML": 0.06,
          "MDV-GLS-1ML": 0.38, "MDV-SIL-OIL": 95.0, "MDV-ADH-UV": 420.0, "MDV-SOLV": 38.0, "MDV-NACL": 1.2,
          "MDV-EDTA": 260.0, "MDV-SST-GEL": 48.0, "MDV-TIP-CAP": 0.008, "MDV-CLAMP": 0.045, "MDV-LUER-M": 0.06,
          "MDV-LBL-UDI": 0.004, "MDV-IFU-IVS": 0.03, "MDV-TYV-LID": 3.2, "MDV-POUCH-S": 0.015,
          "MDV-POUCH-L": 0.04, "MDV-NEST-1ML": 1.9, "MDV-CTN-100": 0.55}
#: standard costs of made items (CAD per unit / metre)
MADE_COST = {"MDV-SYR-03": 0.07, "MDV-SYR-10": 0.11, "MDV-NDL-23": 0.06, "MDV-NDL-25": 0.06, "MDV-IVC-20": 0.62,
             "MDV-IVC-22": 0.60, "MDV-FLS-10": 0.34, "MDV-BCT-EDTA4": 0.09, "MDV-BCT-SST5": 0.12,
             "MDV-PFS-1ML": 0.74, "MDV-IVS-20": 1.15}

#: opening stock with explicit lots / quantities: (part, location, lot code or None, qty, expires in days or None);
#: every other bought-in material is stocked in one lot covering the demand (`transactions`)
STOCK: list[tuple[str, str, str | None, float, int | None]] = [
    ("MDV-RES-PP", "STORES", "PP-2609-A", 900.0, 9),            # expires in nine days (MRP_EXPIRING_STOCK)
    ("MDV-RES-PP", "STORES", "PP-2610-B", 1800.0, 410),
    ("MDV-GLS-1ML", "STORES", "GB1-2608", 30000.0, None),      # covers the first PFS line only
    ("MDV-NSH-1ML", "STORES", "NS1-2609", 70000.0, 940),
    ("MDV-RES-PP", "QUAR", "PP-2607-X", 250.0, 200),            # failed incoming inspection, held
    # finished goods on hand
    ("MDV-SYR-03", "FG", "F2610-SYR03", 120000.0, 1750),
    ("MDV-NDL-23", "FG", "F2610-NDL23", 90000.0, 1750),
    ("MDV-IVS-20", "FG", "F2610-IVS20", 6000.0, 1750),
    ("MDV-BCT-EDTA4", "FG", "F2610-EDTA4", 50000.0, 1750),
]
EXPLICIT = {r[0] for r in STOCK}
#: lot-code stems of the generated supplier lots
LOT_STEM = {"MDV-RES-PET": "PET", "MDV-RES-PVC": "PVC", "MDV-STL-TUBE": "SS304", "MDV-FEP-20": "FEP20",
            "MDV-FEP-22": "FEP22", "MDV-STP-03": "ST03", "MDV-STP-10": "ST10", "MDV-CLS-13": "CL13",
            "MDV-SIL-OIL": "SIL", "MDV-ADH-UV": "UV", "MDV-SOLV": "CYH", "MDV-NACL": "NACL", "MDV-EDTA": "EDTA",
            "MDV-SST-GEL": "GEL", "MDV-LBL-UDI": "UDI", "MDV-TYV-LID": "TYV"}
#: made components: stock covers the demand due within this many days
MADE_COVER_DAYS = 21

PROVINCE_E = "Provincial health purchasing group East (fictional)"
PROVINCE_W = "Provincial health purchasing group West (fictional)"
HOSP_N = "Northern regional hospital network (fictional)"
HOSP_U = "University hospital centre (fictional)"
DIST_A = "US distributor Alpha (fictional)"
DIST_B = "US distributor Beta (fictional)"
BIOPH = "Biologics fill-finish customer (fictional)"

#: demand orders: (number, type, customer, program, priority, status, [(line, part, qty, due offset)])
DEMAND: list[tuple[str, str, str, str | None, int, str, list[tuple[int, str, float, int]]]] = [
    ("DO-MDV-1001", "customer", PROVINCE_E, "Tender 2026-27", 2, "open",
     [(10, "MDV-SYR-03", 250000, 10), (20, "MDV-SYR-10", 150000, 10), (30, "MDV-NDL-23", 300000, 17),
      (40, "MDV-SYR-03", 250000, 38)]),
    ("DO-MDV-1002", "customer", PROVINCE_W, "Tender 2026-27", 2, "open",
     [(10, "MDV-IVS-20", 40000, 14), (20, "MDV-IVC-22", 60000, 18), (30, "MDV-IVS-20", 40000, 35)]),
    ("DO-MDV-1003", "customer", HOSP_N, None, 1, "open",
     [(10, "MDV-IVS-20", 30000, 4), (20, "MDV-FLS-10", 80000, 11)]),
    ("DO-MDV-1004", "customer", HOSP_U, None, 2, "open",
     [(10, "MDV-BCT-EDTA4", 200000, 12), (20, "MDV-BCT-SST5", 150000, 16), (30, "MDV-IVC-20", 30000, 20)]),
    ("DO-MDV-1005", "customer", DIST_A, "US-ACUTE", 3, "open",
     [(10, "MDV-NDL-25", 400000, 21), (20, "MDV-SYR-10", 200000, 24), (30, "MDV-IVS-20", 50000, 28)]),
    ("DO-MDV-1006", "customer", BIOPH, "PFS supply", 1, "open",
     [(10, "MDV-PFS-1ML", 25000, 15), (20, "MDV-PFS-1ML", 40000, 30)]),
    ("DO-MDV-1007", "customer", DIST_B, "US-LAB", 3, "open",
     [(10, "MDV-BCT-EDTA4", 300000, 33), (20, "MDV-BCT-SST5", 200000, 40), (30, "MDV-FLS-10", 120000, 36)]),
    ("DO-MDV-1008", "internal", "Safety stock replenishment (internal)", None, 5, "draft",
     [(10, "MDV-IVS-20", 30000, 56)]),
]

#: purchase orders: (number, part, [(dock offset, qty)], confirmed {seq: offset}, received {seq: qty})
POS: list[tuple[str, str, list[tuple[int, float]], dict[int, int], dict[int, float]]] = [
    ("PO-MDV-2001", "MDV-RES-PP", [(5, 2000.0), (19, 2000.0), (33, 2000.0)], {}, {}),
    ("PO-MDV-2002", "MDV-GLS-1ML", [(12, 30000.0), (40, 40000.0)], {1: 26}, {}),
    ("PO-MDV-2003", "MDV-RES-PET", [(8, 1500.0), (29, 1500.0)], {}, {}),
    ("PO-MDV-2004", "MDV-FEP-20", [(-4, 1000.0)], {}, {}),                 # past due
    ("PO-MDV-2005", "MDV-STP-10", [(15, 300000.0), (36, 300000.0)], {}, {}),
    ("PO-MDV-2006", "MDV-CLAMP", [(9, 60000.0), (30, 60000.0)], {}, {}),
    ("PO-MDV-2007", "MDV-POUCH-L", [(7, 60000.0), (28, 60000.0)], {}, {}),
    ("PO-MDV-2008", "MDV-RES-PVC", [(6, 1000.0), (27, 1000.0)], {}, {}),
]


def master(b: MfgBundle) -> MfgBundle:
    b["locations"] = [
        {"code": "STORES", "name": "Controlled stores", "kind": "stores"},
        {"code": "RECEIVING", "name": "Receiving inspection", "kind": "inspection", "receipt_default": True},
        {"code": "FG", "name": "Finished goods, released", "kind": "stores"},
        {"code": "QUAR", "name": "Quarantine (MRB)", "kind": "quarantine"}]
    b["suppliers"] = [{"code": c, "name": n, "currency": cur} for c, n, cur in SUPPLIERS]
    cur = {c: x for c, _n, x in SUPPLIERS}
    rows: list[dict[str, Any]] = []
    for k, (pn, sup) in enumerate(sorted(SOURCE.items())):
        price = PRICES[pn] if cur[sup] == "CAD" else round(PRICES[pn] / 1.38, 3)
        rows.append({"part_number": pn, "supplier_code": sup, "unit_price": price, "currency": cur[sup],
                     "preferred": True, "supplier_part_number": f"{sup[4:]}-{k + 1:04d}"})
    rows.append({"part_number": "MDV-RES-PP", "supplier_code": "SUP-CHEM", "lead_time_days": 35, "unit_price": 3.05,
                 "currency": "CAD", "preferred": False, "supplier_part_number": "CHEM-PP-ALT"})
    b["item_suppliers"] = rows
    for it in b["items"]:
        pn = it["part_number"]
        if pn in PRICES:
            it["standard_cost"] = PRICES[pn]
        elif pn in MADE_COST:
            it["standard_cost"] = MADE_COST[pn]
    return b


def transactions(b: MfgBundle, anchor: date) -> dict[str, list[dict[str, Any]]]:
    def a(n: int) -> date:
        return anchor + timedelta(days=n)

    ds = dataset(b)
    stock = []
    for pn, loc, lot, qty, exp in STOCK:
        row: dict[str, Any] = {"part_number": pn, "location_code": loc, "qty": qty}
        if lot:
            row["lot_code"] = lot
        if exp is not None:
            row["expires_on"] = a(exp)
        stock.append(row)
    stock += _generated_stock(ds, anchor)
    sup_of = {r["part_number"]: r["supplier_code"] for r in b["item_suppliers"] if r.get("preferred")}
    cur = {c: x for c, _n, x in SUPPLIERS}
    docs, lines, scheds = [], [], []
    for no, pn, parts, conf, rec in POS:
        sup = sup_of[pn]
        docs.append({"doc_type": "po", "number": no, "status": "open", "supplier_code": sup, "currency": cur[sup],
                     "order_date": a(-45)})
        lines.append({"doc_type": "po", "number": no, "line_no": 10, "part_number": pn})
        scheds += schedules("po", no, 10, [(a(d), q) for d, q in parts], {k: a(v) for k, v in conf.items()} or None,
                            rec or None)
    docs.append({"doc_type": "pr", "number": "PR-MDV-3001", "status": "submitted", "supplier_code": "SUP-ELAST",
                 "currency": "CAD", "order_date": None})
    lines.append({"doc_type": "pr", "number": "PR-MDV-3001", "line_no": 10, "part_number": "MDV-NSH-1ML"})
    scheds += schedules("pr", "PR-MDV-3001", 10, [(a(30), 40000.0)])
    orders, dlines = [], []
    for no, kind, cust, prog, prio, status, ls in DEMAND:
        orders.append({"number": no, "demand_type": kind, "customer": cust, "program": prog, "priority": prio,
                       "status": status})
        for ln, pn, q, due in ls:
            dlines.append({"number": no, "line_no": ln, "part_number": pn, "qty": float(q), "due_date": a(due)})
    wos = [{"number": "WO-MDV-0001", "part_number": "MDV-SYR-10", "qty": 60000.0, "start_date": a(-2),
            "due_date": a(5), "status": "in_progress", "priority": 2},
           {"number": "WO-MDV-0002", "part_number": "MDV-BRL-03", "qty": 150000.0, "start_date": a(0),
            "due_date": a(3), "status": "released", "priority": 2},
           {"number": "WO-MDV-0003", "part_number": "MDV-IVS-20", "qty": 18000.0, "start_date": a(0),
            "due_date": a(4), "status": "released", "priority": 1}]
    comps = (component_rows(ds, "WO-MDV-0001", "MDV-SYR-10", 60000, a(-2), None, 0.0)
             + component_rows(ds, "WO-MDV-0002", "MDV-BRL-03", 150000, a(0), None, 0.0)
             + component_rows(ds, "WO-MDV-0003", "MDV-IVS-20", 18000, a(0), None, 0.0))
    return {"stock": stock, "purchase_docs": docs, "purchase_lines": lines, "purchase_schedules": scheds,
            "demand_orders": orders, "demand_lines": dlines, "work_orders": wos, "wo_components": comps}


def _generated_stock(ds: Any, anchor: date) -> list[dict[str, Any]]:
    """One supplier lot per remaining bought-in material covering the open demand (plus 15 %, or exactly the demand
    less the open PO quantity where a PO tops it up), and made components covering the demand due in the next
    `MADE_COVER_DAYS` days (lot `M<yymm>-<part>`)."""
    po_qty: dict[str, float] = {}
    for _no, pn, parts, _c, _r in POS:
        po_qty[pn] = po_qty.get(pn, 0.0) + sum(q for _d, q in parts)
    need: dict[str, float] = {}
    near: dict[str, float] = {}
    explosions: dict[str, dict[str, float]] = {}
    for _no, _k, _c, _p, _pr, status, ls in DEMAND:
        if status != "open":
            continue
        for _ln, top, q, due in ls:
            pu = explosions.setdefault(top, per_unit(ds, top, anchor))
            for pn, per in pu.items():
                if pn == top:
                    continue
                need[pn] = need.get(pn, 0.0) + q * per
                if due <= MADE_COVER_DAYS:
                    near[pn] = near.get(pn, 0.0) + q * per
    out: list[dict[str, Any]] = []
    stem = f"{anchor:%y%m}"
    for pn in sorted(need):
        it = ds.items_by_pn[pn]
        if pn in EXPLICIT:
            continue
        if it.make_buy == "buy":
            qty = need[pn] * (0.75 if pn in po_qty else 1.15)
        else:
            qty = near.get(pn, 0.0)
        qty = float(math.ceil(qty))
        if qty <= 0:
            continue
        row: dict[str, Any] = {"part_number": pn, "location_code": "STORES", "qty": qty}
        if it.lot_controlled:
            code = LOT_STEM.get(pn, pn.removeprefix("MDV-"))
            row["lot_code"] = f"{code}-{stem}" if it.make_buy == "buy" else f"M{stem}-{code}"
            if it.shelf_life_days:
                row["expires_on"] = anchor + timedelta(days=min(it.shelf_life_days - 60, 700))
        out.append(row)
    return out
