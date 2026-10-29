"""Sample `kavach`, M2 part (M2-DESIGN 13.3): locations, 8 fictional suppliers, item-supplier terms (passive reels
with MOQ/multiple 5,000 moved to the item-supplier row), lot settings, the serial ECO (`KV-TPU-1000` BOM v2 from
unit 126 with `KV-DOC-PACK-B`), opening stock, staggered POs, PRs, five demand orders and three work orders.

Stock cover per buy item is seeded ({30: 30%, 70: 70%} units of `KV-TPU-1000`; tuned from the 13.3 {0, 20, 50} so the
first demand lines, both open WOs and the spares can be built - see 22.WP-A); parts with a lead time over 42 days
always get 70, apart from the explicit exceptions of 13.3.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any

from ..bundle import MfgBundle
from .m2common import component_rows, dataset, per_unit, price, schedules

SEED = 3003
SUPPLIERS = (("SUP-SEMI-1", "Semiconductor distributor 1 (fictional)", "INR"),
             ("SUP-SEMI-2", "Semiconductor distributor 2 (fictional)", "INR"),
             ("SUP-PAS-1", "Passives supplier 1 (fictional)", "INR"),
             ("SUP-PAS-2", "Passives supplier 2 (fictional)", "INR"),
             ("SUP-CONN", "Connectors and wire supplier (fictional)", "INR"),
             ("SUP-MECH", "Mechanical parts supplier (fictional)", "INR"),
             ("SUP-DISP", "Displays and radio supplier (fictional)", "INR"),
             ("SUP-PRINT", "Print shop (fictional)", "INR"))
SEMI = ("IC", "BLK", "XTL", "TRN", "DIO")
PASSIVE = ("RES", "CAP", "IND", "FB")
CONN = ("CON", "WIR", "TRM", "SLV", "HSK", "RLY", "FUS", "GRM")
LOT_CONTROLLED = ("KV-COAT-UR", "KV-IC-FPGA-V1", "KV-IC-FPGA-V2", "KV-IC-FPGA-R1", "KV-IC-PROC-V1", "KV-IC-PROC-R1",
                  "KV-IC-PROC-D1", "KV-MOD-GSM")
NO_PERIOD = LOT_CONTROLLED + ("KV-LCD-104", "KV-DOC-PACK", "KV-DOC-PACK-B")


def _seg(pn: str) -> str:
    return pn.split("-")[1]


def _supplier(pn: str, k: int) -> str:
    seg = _seg(pn)
    if pn in ("KV-LCD-104", "KV-MOD-GSM"):
        return "SUP-DISP"
    if seg in ("LBL", "DOC"):
        return "SUP-PRINT"
    if seg in SEMI:
        return "SUP-SEMI-1" if k % 2 == 0 else "SUP-SEMI-2"
    if seg in PASSIVE:
        return "SUP-PAS-1" if k % 2 == 0 else "SUP-PAS-2"
    if seg in CONN:
        return "SUP-CONN"
    return "SUP-MECH"


def master(b: MfgBundle) -> MfgBundle:
    rng = random.Random(SEED)
    b["locations"] = [
        {"code": "STORES-MAIN", "name": "Main stores", "kind": "stores"},
        {"code": "GOODS-IN", "name": "Goods-in inspection", "kind": "inspection", "receipt_default": True},
        {"code": "LS-SMT", "name": "SMT line side", "kind": "line_side"},
        {"code": "LS-HAR", "name": "Harness line side", "kind": "line_side"},
        {"code": "FG", "name": "Finished goods", "kind": "stores"},
        {"code": "QUAR", "name": "Quarantine", "kind": "quarantine"}]
    b["suppliers"] = [{"code": c, "name": n, "currency": cur} for c, n, cur in SUPPLIERS]
    # the serial ECO: KV-DOC-PACK-B and KV-TPU-1000 BOM v2 (units 126..)
    b["items"].append({"part_number": "KV-DOC-PACK-B", "make_buy": "buy", "description": "Documentation pack, rev B",
                       "lead_time_days": 14, "attr:manufacturer": "Synthetic", "attr:mpn": "SYN-KV-DOCB"})
    top = next(r for r in b["boms"] if r["parent_part_number"] == "KV-TPU-1000")
    b["boms"].append(dict(top, version=2, serial_from=126, serial_to=1_000_000_000,
                          note="ECO: documentation pack rev B from unit 126"))
    v1_lines = [r for r in b["bom_lines"] if r["parent_part_number"] == "KV-TPU-1000" and r["version"] == top["version"]]
    for r in v1_lines:
        nr = dict(r, version=2)
        if nr["child_part_number"] == "KV-DOC-PACK":
            nr["child_part_number"] = "KV-DOC-PACK-B"
        b["bom_lines"].append(nr)
    rows: list[dict[str, Any]] = []
    buys = sorted((r for r in b["items"] if r["make_buy"] == "buy"), key=lambda r: r["part_number"])
    for k, it in enumerate(buys):
        pn = it["part_number"]
        p = price(rng, pn)
        it["standard_cost"] = p
        sup = _supplier(pn, k)
        row: dict[str, Any] = {"part_number": pn, "supplier_code": sup, "lead_time_days": it.get("lead_time_days"),
                               "unit_price": p, "currency": "INR", "preferred": True,
                               "supplier_part_number": f"{sup[4:]}-{k:05d}"}
        if _seg(pn) in ("RES", "CAP") and (it.get("min_order_qty") or 0) >= 5000:
            row.update(min_order_qty=float(it["min_order_qty"]), order_multiple=float(it["order_multiple"]),
                       purchase_unit="REEL", units_per_purchase_unit=5000.0)
            it["min_order_qty"] = 0.0
            it["order_multiple"] = 0.0
        rows.append(row)
        if _seg(pn) == "IC":
            other = "SUP-SEMI-2" if sup == "SUP-SEMI-1" else "SUP-SEMI-1"
            rows.append({"part_number": pn, "supplier_code": other, "lead_time_days": (it.get("lead_time_days") or 0)
                         + 28, "unit_price": round(p * 0.95, 2), "currency": "INR", "preferred": False})
            it["receiving_days"] = 2
        if pn in LOT_CONTROLLED:
            it["lot_controlled"] = True
        if pn not in NO_PERIOD:
            it["lot_rule"] = "period"
            it["lot_period_days"] = 30
            it.pop("fixed_lot_qty", None)
    b["item_suppliers"] = rows
    return b


def _ceil(q: float, it: Any) -> float:
    return float(math.ceil(q - 1e-9)) if it.uom == "EA" else round(q, 3)


def transactions(b: MfgBundle, anchor: date) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(SEED + 1)

    def a(n: int) -> date:
        return anchor + timedelta(days=n)

    ds = dataset(b)
    need = per_unit(ds, "KV-TPU-1000", anchor)
    packs = {r["part_number"]: r.get("units_per_purchase_unit") or 1.0 for r in b["item_suppliers"]
             if r.get("preferred")}
    explicit = {"KV-IC-FPGA-V1", "KV-MOD-GSM", "KV-LCD-104", "KV-COAT-UR", "KV-CAP-1210-22U-A",
                "KV-CAP-1210-22U-B"}
    stock: list[dict[str, Any]] = []
    passives_ls = 0
    quar_done = False
    for pn in sorted(need):
        it = ds.items_by_pn[pn]
        if it.make_buy != "buy" or pn in explicit:
            continue
        r = rng.random()
        cover = 30 if r < 0.30 else 70
        if (it.lead_time_days or 0) > 42:
            cover = 70
        q = _ceil(cover * need[pn], it)
        pack = packs.get(pn, 1.0)
        if pack > 1:
            q = float(math.ceil(q / pack - 1e-9) * pack)
        loc = "STORES-MAIN"
        if pack > 1 and passives_ls < 20:
            loc = "LS-SMT"
            passives_ls += 1
        row: dict[str, Any] = {"part_number": pn, "location_code": loc, "qty": q}
        if it.lot_controlled:
            row.update(lot_code=f"{pn[3:10]}-2609", expires_on=a(700))
        stock.append(row)
        if not quar_done and _seg(pn) == "CON":
            stock.append({"part_number": pn, "location_code": "QUAR", "qty": 50.0})
            quar_done = True
    stock += [
        {"part_number": "KV-IC-FPGA-V1", "location_code": "STORES-MAIN", "lot_code": "FV1-2609", "qty": 45.0,
         "expires_on": a(700)},
        {"part_number": "KV-MOD-GSM", "location_code": "STORES-MAIN", "lot_code": "GSM-2609", "qty": 12.0,
         "expires_on": a(900)},
        {"part_number": "KV-LCD-104", "location_code": "STORES-MAIN", "qty": 20.0},
        {"part_number": "KV-LCD-104", "location_code": "GOODS-IN", "qty": 6.0},
        {"part_number": "KV-COAT-UR", "location_code": "STORES-MAIN", "lot_code": "L-2610", "qty": 3.0,
         "expires_on": a(18)},
        {"part_number": "KV-COAT-UR", "location_code": "STORES-MAIN", "lot_code": "L-2702", "qty": 4.0,
         "expires_on": a(200)},
        {"part_number": "KV-CAP-1210-22U-B", "location_code": "STORES-MAIN", "qty": 500.0},
        {"part_number": "KV-HAR-L01", "location_code": "STORES-MAIN", "qty": 6.0},
        {"part_number": "KV-PCB-LED", "location_code": "STORES-MAIN", "qty": 15.0}]

    sup_of = {r["part_number"]: r["supplier_code"] for r in b["item_suppliers"] if r.get("preferred")}
    connectors = sorted(pn for pn in need if _seg(pn) == "CON")
    passives = sorted(pn for pn in need if _seg(pn) in ("RES", "CAP") and packs.get(pn, 1) > 1)
    mechs = sorted(pn for pn in need if sup_of.get(pn) == "SUP-MECH")
    docs: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    scheds: list[dict[str, Any]] = []

    def po(no: str, pn: str, parts: list[tuple[date, float]], *, confirmed: dict[int, date] | None = None,
           received: dict[int, float] | None = None, doc_type: str = "po", status: str = "open",
           extra_lines: list[tuple[str, list[tuple[date, float]]]] | None = None) -> None:
        docs.append({"doc_type": doc_type, "number": no, "status": status, "supplier_code": sup_of.get(pn),
                     "currency": "INR", "order_date": a(-90) if doc_type == "po" else None})
        for k, (p_, ps) in enumerate([(pn, parts)] + (extra_lines or [])):
            ln_no = 10 * (k + 1)
            lines.append({"doc_type": doc_type, "number": no, "line_no": ln_no, "part_number": p_})
            scheds.extend(schedules(doc_type, no, ln_no, ps, confirmed if k == 0 else None,
                                    received if k == 0 else None))

    po("PO-KV-0101", "KV-IC-FPGA-V1", [(a(20), 30), (a(48), 30), (a(110), 30)], confirmed={2: a(64)})
    po("PO-KV-0102", connectors[0], [(a(-12), 200)])
    po("PO-KV-0103", "KV-MOD-GSM", [(a(28), 10), (a(58), 10), (a(88), 10), (a(118), 10)])
    po("PO-KV-0104", "KV-LCD-104", [(a(23), 20), (a(48), 20), (a(78), 20)], confirmed={2: a(63)},
       received={1: 6})
    po("PO-KV-0105", "KV-DOC-PACK", [(a(30), 40)])
    for k in range(6):
        pn = passives[(k * 7) % len(passives)] if k < 4 else mechs[(k * 3) % len(mechs)]
        n_s = 1 + k % 3
        po(f"PO-KV-01{6 + k:02d}", pn, [(a(14 + 21 * s), 5000.0 if k < 4 else 40.0) for s in range(n_s)])
    po("PR-KV-0201", connectors[1], [(a(40), 50), (a(70), 50)], doc_type="pr", status="submitted",
       extra_lines=[(connectors[2], [(a(40), 30), (a(70), 30)])])
    wires = sorted(pn for pn in need if _seg(pn) == "WIR")
    po("PR-KV-0202", wires[0], [(a(35), 100.0)], doc_type="pr", status="draft")
    # documents of a PR carry no supplier unless the PR names one; keep the suggestion
    demand_orders = [
        {"number": "DO-KV-001", "demand_type": "customer", "customer": "Zonal Railway A (fictional)",
         "program": "KVP-26", "priority": 1, "status": "open"},
        {"number": "DO-KV-002", "demand_type": "customer", "customer": "Zonal Railway B (fictional)",
         "program": "KVP-27", "priority": 2, "status": "open"},
        {"number": "DO-KV-003", "demand_type": "spares", "customer": "Zonal Railway A (fictional)", "priority": 3,
         "status": "open"},
        {"number": "DO-KV-004", "demand_type": "project", "customer": "Prototype programme (fictional)",
         "program": "KVP-PROTO", "priority": 1, "status": "open"},
        {"number": "DO-KV-005", "demand_type": "customer", "customer": "Zonal Railway B (fictional)",
         "program": "KVP-27", "priority": 2, "status": "draft"}]
    tpu = "KV-TPU-1000"
    demand_lines = [
        {"number": "DO-KV-001", "line_no": 10, "part_number": tpu, "qty": 10.0, "due_date": a(43),
         "serial_from": 101, "serial_to": 110},
        {"number": "DO-KV-001", "line_no": 20, "part_number": tpu, "qty": 10.0, "due_date": a(74),
         "serial_from": 111, "serial_to": 120},
        {"number": "DO-KV-002", "line_no": 10, "part_number": tpu, "qty": 15.0, "due_date": a(90),
         "serial_from": 121, "serial_to": 135},
        {"number": "DO-KV-003", "line_no": 10, "part_number": "KV-PCB-CPU", "qty": 4.0, "due_date": a(29)},
        {"number": "DO-KV-003", "line_no": 20, "part_number": "KV-HAR-L03", "qty": 6.0, "due_date": a(23)},
        {"number": "DO-KV-003", "line_no": 30, "part_number": "KV-PSU-6000", "qty": 2.0, "due_date": a(69)},
        {"number": "DO-KV-004", "line_no": 10, "part_number": tpu, "qty": 2.0, "due_date": a(12),
         "serial_from": 99, "serial_to": 100},
        {"number": "DO-KV-005", "line_no": 10, "part_number": tpu, "qty": 5.0, "due_date": a(120)}]
    wos = [{"number": "WO-KV-0001", "part_number": "KV-PCB-CPU", "qty": 30.0, "start_date": a(-3), "due_date": a(7),
            "status": "released", "priority": 2},
           {"number": "WO-KV-0002", "part_number": "KV-HAR-L03", "qty": 12.0, "start_date": a(-5), "due_date": a(4),
            "status": "in_progress", "priority": 3, "qty_completed": 4.0},
           {"number": "WO-KV-0003", "part_number": "KV-VCU-2000", "qty": 10.0, "start_date": a(20),
            "due_date": a(30), "status": "planned", "priority": 2}]
    comps = (component_rows(ds, "WO-KV-0001", "KV-PCB-CPU", 30, a(-3), None, 0.5)
             + component_rows(ds, "WO-KV-0002", "KV-HAR-L03", 12, a(-5), None, 1.0)
             + component_rows(ds, "WO-KV-0003", "KV-VCU-2000", 10, a(20), None, 0.0))
    return {"stock": stock, "purchase_docs": docs, "purchase_lines": lines, "purchase_schedules": scheds,
            "demand_orders": demand_orders, "demand_lines": demand_lines, "work_orders": wos, "wo_components": comps}
