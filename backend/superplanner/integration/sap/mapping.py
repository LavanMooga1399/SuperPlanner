"""SAP S/4HANA OData <-> `superplanner.v1` mapping (M8-DESIGN 9; pure).

Profile (`SapSettings`): plant (WERKS) filter, storage location -> location code map, ISO unit map (PCE -> EA, ...),
material number zero-strip, MRP controller filter, order types. Both OData v2 (`to_Item`, `/Date(ms)/`) and v4
(`_Item`, ISO dates) payload shapes are accepted.

`ENTITIES[name]` = (entity set path, delta field, mapper). A mapper turns one page of OData records into
`(v1 entity, v1 records)` batches plus M8 extras (`packaging`, `history`) that the sync applies directly.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any, Callable

PACK_UNITS = {"CS": "case", "CAR": "case", "KAR": "case", "BOX": "inner", "BX": "inner", "PAK": "inner",
              "IN": "inner", "PAL": "pallet", "PL": "pallet", "PLT": "pallet"}


def strip(material: str | None, on: bool = True) -> str:
    m = (material or "").strip()
    if on and m.isdigit():
        m = m.lstrip("0") or "0"
    return m


def unit(code: str | None, profile: Any) -> str:
    c = (code or "EA").strip().upper()
    return profile.unit_map.get(c, c)


_MS = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")


def to_date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    s = str(v)
    m = _MS.match(s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, UTC).date()
    return date.fromisoformat(s[:10])


def to_dt(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    s = str(v)
    m = _MS.match(s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, UTC)
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def children(rec: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    for n in names:
        v = rec.get(n)
        if v is None:
            continue
        if isinstance(v, dict):
            return list(v.get("results", []))
        if isinstance(v, list):
            return v
    return []


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- inbound mappers

Out = dict[str, list[dict[str, Any]]]


def products(recs: list[dict[str, Any]], p: Any) -> Out:
    items, packs = [], []
    for r in recs:
        mat = strip(r.get("Product"), p.strip_zeros)
        plants = [x for x in children(r, "to_Plant", "_ProductPlant") if not p.plant or x.get("Plant") == p.plant]
        if p.plant and not plants:
            continue
        pl = plants[0] if plants else {}
        if p.mrp_controllers and pl.get("MRPResponsible") not in p.mrp_controllers:
            continue
        desc = next((d.get("ProductDescription") for d in children(r, "to_Description", "_ProductDescription")
                     if d.get("Language") in ("EN", "E", "en")), "") or ""
        item: dict[str, Any] = {"ref": mat, "part_number": mat, "description": desc[:500],
                                "uom": unit(r.get("BaseUnit"), p),
                                "make_buy": "make" if pl.get("ProcurementType") == "E" else "buy",
                                "active": not r.get("IsMarkedForDeletion", False)}
        lt = pl.get("PlannedDeliveryDurationInDays")
        if lt not in (None, ""):
            item["lead_time_days"] = int(_num(lt))
        val = children(r, "to_Valuation", "_ProductValuation")
        if val and _num(val[0].get("StandardPrice")) > 0:
            item["standard_cost"] = round(_num(val[0]["StandardPrice"]) / max(_num(val[0].get("PriceUnitQty")) or 1, 1),
                                          6)
        items.append(item)
        levels = [{"level": "each", "code": unit(r.get("BaseUnit"), p), "qty_base": 1.0}]
        for u in children(r, "to_ProductUnitsOfMeasure", "_ProductUnitsOfMeasure"):
            alt = (u.get("AlternativeUnit") or "").upper()
            if alt == (r.get("BaseUnit") or "").upper():
                continue
            lvl = PACK_UNITS.get(alt)
            den = _num(u.get("QuantityDenominator")) or 1.0
            q = _num(u.get("QuantityNumerator")) / den
            if lvl and q > 1:
                levels.append({"level": lvl, "code": alt, "qty_base": q,
                               "gtin": (u.get("GlobalTradeItemNumber") or None)})
        order = ("each", "inner", "case", "pallet")
        levels = sorted({lv["level"]: lv for lv in levels}.values(), key=lambda x: order.index(x["level"]))
        if len(levels) > 1:
            packs.append({"item_ref": mat, "levels": levels})
    return {"item": items, "packaging": packs}


def suppliers(recs: list[dict[str, Any]], p: Any) -> Out:
    return {"supplier": [{"ref": r["Supplier"], "code": r["Supplier"][:32],
                          "name": (r.get("SupplierName") or r["Supplier"])[:200],
                          "active": not r.get("PostingIsBlocked", False)} for r in recs]}


def info_records(recs: list[dict[str, Any]], p: Any) -> Out:
    out = []
    for r in recs:
        org = [x for x in children(r, "to_PurgInfoRecdOrgPlantData", "_PurgInfoRecdOrgPlantData")
               if not p.plant or x.get("Plant") in (p.plant, "", None)]
        o = org[0] if org else {}
        rec: dict[str, Any] = {"ref": r["PurchasingInfoRecord"], "item_ref": strip(r.get("Material"), p.strip_zeros),
                               "supplier_ref": r["Supplier"],
                               "supplier_part_number": (r.get("SupplierMaterialNumber") or "")[:64]}
        if o.get("MaterialPlannedDeliveryDurn") not in (None, ""):
            rec["lead_time_days"] = int(_num(o["MaterialPlannedDeliveryDurn"]))
        if _num(o.get("MinimumPurchaseOrderQuantity")) > 0:
            rec["moq"] = _num(o["MinimumPurchaseOrderQuantity"])
        if _num(o.get("NetPriceAmount")) > 0:
            rec["price"] = _num(o["NetPriceAmount"])
        out.append(rec)
    return {"item_supplier": out}


def stock(recs: list[dict[str, Any]], p: Any) -> Out:
    agg: dict[tuple[str, str, str | None], float] = defaultdict(float)
    for r in recs:
        if p.plant and r.get("Plant") != p.plant:
            continue
        if str(r.get("InventoryStockType", "01")) not in ("01", "1"):
            continue
        loc = p.location_map.get(r.get("StorageLocation") or "", r.get("StorageLocation") or "")
        if not loc:
            continue
        agg[(strip(r.get("Material"), p.strip_zeros), loc, (r.get("Batch") or None))] += \
            _num(r.get("MatlWrhsStkQtyInMatlBaseUnit"))
    now = datetime.now(UTC).replace(microsecond=0)
    return {"stock_snapshot": [{"ref": f"{m}|{loc}|{b or ''}", "item_ref": m, "location_code": loc, "lot_code": b,
                                "qty": round(q, 6), "as_at": now.isoformat()} for (m, loc, b), q in sorted(agg.items())]}


def purchase_orders(recs: list[dict[str, Any]], p: Any) -> Out:
    out = []
    for r in recs:
        lines = []
        for it in children(r, "to_PurchaseOrderItem", "_PurchaseOrderItem"):
            if p.plant and it.get("Plant") not in (p.plant, None, ""):
                continue
            scheds = [{"seq": int(_num(sl.get("ScheduleLine")) or k + 1),
                       "requested_date": to_date(sl.get("ScheduleLineDeliveryDate")).isoformat(),
                       "qty": _num(sl.get("ScheduleLineOrderQuantity"))}
                      for k, sl in enumerate(children(it, "to_ScheduleLine", "_PurchaseOrderScheduleLine"))
                      if _num(sl.get("ScheduleLineOrderQuantity")) > 0]
            if not scheds and _num(it.get("OrderQuantity")) > 0:
                scheds = [{"seq": 1, "requested_date": to_date(r.get("PurchaseOrderDate")).isoformat(),
                           "qty": _num(it["OrderQuantity"])}]
            if scheds:
                ln: dict[str, Any] = {"line_no": int(_num(it.get("PurchaseOrderItem"))),
                                      "item_ref": strip(it.get("Material"), p.strip_zeros), "schedules": scheds}
                if _num(it.get("NetPriceAmount")) > 0:
                    ln["unit_price"] = _num(it["NetPriceAmount"])
                lines.append(ln)
        if lines:
            out.append({"ref": r["PurchaseOrder"], "number": r["PurchaseOrder"][:32], "supplier_ref": r["Supplier"],
                        "status": "cancelled" if r.get("PurchasingProcessingStatus") == "08" else "open",
                        "order_date": (to_date(r.get("PurchaseOrderDate")) or date.today()).isoformat(),
                        "currency": r.get("DocumentCurrency", ""), "lines": lines})
    return {"purchase_order": out}


def sales_orders(recs: list[dict[str, Any]], p: Any) -> Out:
    out = []
    for r in recs:
        lines = []
        for it in children(r, "to_Item", "_Item"):
            if p.plant and it.get("ProductionPlant", p.plant) not in (p.plant, None, ""):
                continue
            mat = strip(it.get("Material") or it.get("Product"), p.strip_zeros)
            sls = children(it, "to_ScheduleLine", "_ScheduleLine")
            if sls:
                for k, sl in enumerate(sls):
                    q = _num(sl.get("ScheduleLineOrderQuantity") or sl.get("ConfdOrderQtyByMatlAvailCheck"))
                    d = to_date(sl.get("ConfirmedDeliveryDate") or sl.get("RequestedDeliveryDate"))
                    if q > 0 and d:
                        lines.append({"line_no": int(_num(it.get("SalesOrderItem"))) * 10 + k + 1, "item_ref": mat,
                                      "qty": q, "due_date": d.isoformat()})
            else:
                q = _num(it.get("RequestedQuantity"))
                d = to_date(it.get("RequestedDeliveryDate") or r.get("RequestedDeliveryDate"))
                if q > 0 and d:
                    lines.append({"line_no": int(_num(it.get("SalesOrderItem"))) * 10 + 1, "item_ref": mat,
                                  "qty": q, "due_date": d.isoformat()})
        if lines:
            out.append({"ref": r["SalesOrder"], "number": r["SalesOrder"][:32], "demand_type": "customer",
                        "customer": (r.get("SoldToParty") or "")[:200], "lines": lines})
    return {"demand_order": out}


def billing(recs: list[dict[str, Any]], p: Any) -> Out:
    """Billing document items -> monthly demand history (`sap` rows), quantity per material and month."""
    agg: dict[tuple[str, str], float] = defaultdict(float)
    for r in recs:
        if p.plant and r.get("Plant") not in (p.plant, None, ""):
            continue
        d = to_date(r.get("BillingDocumentDate"))
        if d is None:
            continue
        sign = -1.0 if r.get("BillingDocumentIsCancelled") or r.get("SDDocumentCategory") in ("N", "O") else 1.0
        agg[(strip(r.get("Material") or r.get("Product"), p.strip_zeros), d.replace(day=1).isoformat())] += \
            sign * _num(r.get("BillingQuantity"))
    return {"history": [{"item_ref": m, "period_start": per, "qty": round(q, 6)} for (m, per), q in sorted(agg.items())
                        if q > 0]}


def boms(recs: list[dict[str, Any]], p: Any) -> Out:
    out = []
    for r in recs:
        if p.plant and r.get("Plant") not in (p.plant, None, ""):
            continue
        lines = [{"child_ref": strip(i.get("BillOfMaterialComponent"), p.strip_zeros),
                  "find_number": str(i.get("BillOfMaterialItemNumber") or k + 1)[:16],
                  "qty_per": _num(i.get("BillOfMaterialItemQuantity")) / max(_num(r.get("BOMHeaderQuantityInBaseUnit"))
                                                                             or 1.0, 1e-9)}
                 for k, i in enumerate(children(r, "to_BillOfMaterialItem", "_BillOfMaterialItem"))
                 if _num(i.get("BillOfMaterialItemQuantity")) > 0]
        if lines:
            mat = strip(r.get("Material"), p.strip_zeros)
            out.append({"ref": f"{mat}|{r.get('BillOfMaterial')}|{r.get('BillOfMaterialVariant', '1')}",
                        "parent_ref": mat, "lines": lines})
    return {"bom": out}


def routings(recs: list[dict[str, Any]], p: Any) -> Out:
    out = []
    for r in recs:
        ops = [{"seq": int(_num(o.get("Operation") or o.get("OperationSequence") or (k + 1) * 10)),
                "name": (o.get("OperationText") or f"Op {k + 1}")[:100], "group_code": (o.get("WorkCenter") or "WC")[:32],
                "setup_minutes": _num(o.get("StandardWorkQuantity1")),
                "run_minutes": _num(o.get("StandardWorkQuantity2"))}
               for k, o in enumerate(children(r, "to_Operation", "_Operation"))]
        if ops:
            mat = strip(r.get("Material"), p.strip_zeros)
            out.append({"ref": f"{mat}|{r.get('ProductionRoutingGroup')}|{r.get('ProductionRouting', '1')}",
                        "item_ref": mat, "operations": ops})
    return {"routing": out}


#: entity -> (entity set path, delta field, mapper)
ENTITIES: dict[str, tuple[str, str, Callable[[list[dict[str, Any]], Any], Out]]] = {
    "product": ("API_PRODUCT_SRV/A_Product", "LastChangeDateTime", products),
    "supplier": ("API_BUSINESS_PARTNER/A_Supplier", "LastChangeDateTime", suppliers),
    "info_record": ("API_INFORECORD_PROCESS_SRV/A_PurchasingInfoRecord", "LastChangeDateTime", info_records),
    "stock": ("API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod", "", stock),
    "purchase_order": ("API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder", "LastChangeDateTime", purchase_orders),
    "sales_order": ("API_SALES_ORDER_SRV/A_SalesOrder", "LastChangeDateTime", sales_orders),
    "billing": ("API_BILLING_DOCUMENT_SRV/A_BillingDocumentItem", "LastChangeDateTime", billing),
    "bom": ("API_BILL_OF_MATERIAL_SRV;v=0002/MaterialBOM", "LastChangeDateTime", boms),
    "routing": ("API_PRODUCTION_ROUTING/ProductionRoutingHeader", "LastChangeDateTime", routings),
}
EXPAND = {"product": "to_Description,to_Plant,to_ProductUnitsOfMeasure,to_Valuation",
          "purchase_order": "to_PurchaseOrderItem/to_ScheduleLine", "sales_order": "to_Item/to_ScheduleLine",
          "info_record": "to_PurgInfoRecdOrgPlantData", "bom": "to_BillOfMaterialItem", "routing": "to_Operation"}


def delta_filter(entity: str, cursor: str | None, version: str) -> dict[str, str]:
    path, field_, _m = ENTITIES[entity]
    q: dict[str, str] = {}
    if entity in EXPAND:
        q["$expand"] = EXPAND[entity]
    if field_:
        q["$orderby"] = f"{field_} asc"                  # review 4: stable order for the cursor
    if cursor and field_:
        lit = f"datetimeoffset'{cursor}'" if version == "v2" else cursor
        q["$filter"] = f"{field_} ge {lit}"               # ge + idempotent upserts: no change lost at a tie
    return q


def max_cursor(recs: list[dict[str, Any]], entity: str, cur: str | None) -> str | None:
    field_ = ENTITIES[entity][1]
    best = to_dt(cur) if cur else None
    for r in recs:
        v = to_dt(r.get(field_)) if field_ else None
        if v is not None and (best is None or v > best):
            best = v
    return best.isoformat().replace("+00:00", "Z") if best else cur


# ---------------------------------------------------------------- outbound

def planned_order_out(po: dict[str, Any], p: Any) -> tuple[str, dict[str, Any]]:
    """An MRP planned order -> (path, OData body): make -> planned order, buy -> purchase requisition."""
    if po["kind"] == "make":
        return "API_PLANNED_ORDERS/A_PlannedOrder", {
            "Material": po["part_number"], "MRPPlant": p.plant, "ProductionPlant": p.plant,
            "PlannedOrderType": p.order_types.get("planned_order", "LA"),
            "TotalQuantity": str(po["qty"]), "PlndOrderPlannedStartDate": f"{po['start_date']}T00:00:00",
            "PlndOrderPlannedEndDate": f"{po['need_date']}T00:00:00", "ExternalReference": po["ref"][:20]}
    return "API_PURCHASEREQ_PROCESS_SRV/A_PurchaseRequisitionHeader", {
        "PurchaseRequisitionType": p.order_types.get("purchase_req", "NB"),
        "to_PurchaseReqnItem": {"results": [{"Material": po["part_number"], "Plant": p.plant,
                                             "RequestedQuantity": str(po["qty"]),
                                             "DeliveryDate": f"{po['need_date']}T00:00:00",
                                             "PurchaseRequisitionItemText": po["ref"][:40]}]}}
