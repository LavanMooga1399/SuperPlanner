"""Network snapshot (M9-DESIGN 5.2): one read per node (the M2 MRP snapshot + M8 inputs, so demand, consumption,
holds and sterility supplies follow the plant's MRP), turned into the pure `NetProblem`.

Items match across nodes by key = `external_ref`, else part number; a key with different UoMs at two nodes is
excluded (`NET_UOM_MISMATCH`). Demand: open customer order lines, the unconsumed forecast of the node's version
(pinned in the params, else active), open transfer lines out (`transfer_open`). Supply: free stock, inspection /
sterility releases, open POs, WOs, published rate supplies, open transfer lines in (`transfer_in`). Capacity and
hours per unit from `capacity.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .calendar import weeks as horizon_weeks
from .capacity import available_hours, hours_per_unit
from .model import NetBomLine, NetCap, NetDemand, NetItem, NetLane, NetLoad, NetNode, NetProblem, NetRule, NetSupply

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
NON_NETTABLE = {"quarantine", "scrap", "rejected", "mrb"}


@dataclass
class NodePart:
    node: NetNode
    items: list[NetItem] = field(default_factory=list)
    demand: list[NetDemand] = field(default_factory=list)
    supply: list[NetSupply] = field(default_factory=list)
    bom: list[NetBomLine] = field(default_factory=list)
    capacity: list[NetCap] = field(default_factory=list)
    load: list[NetLoad] = field(default_factory=list)
    item_ids: dict[str, str] = field(default_factory=dict)        # key -> item id
    names: dict[str, tuple[str, str | None, str]] = field(default_factory=dict)   # key -> (description, family, uom)
    as_of: date | None = None


def key_of(item: Any) -> str:
    return (item.external_ref or item.part_number or "").strip()


def build_node(s: Any, info: dict[str, Any], as_of: date, horizon_weeks_n: int,
               forecast_version_id: str | None) -> NodePart:
    """Read one node inside its owner scope (`s` = a REPEATABLE READ snapshot transaction)."""
    from ...api.mfg import repo_m2
    from ...api.mfg.db_models import MfgLineRow
    from ...api.mfg.db_models_m8 import MfgLineRateRow
    from ...api.mfg.services import m8mrp
    from ..mrp.model import MrpParams

    snap = repo_m2.load_mrp_snapshot(s, as_of)
    params = MrpParams.model_validate({"forecast_version_id": forecast_version_id} if forecast_version_id else {})
    snap = m8mrp.add_inputs(s, snap, params)
    ds = snap.dataset
    plant = ds.plant
    workdays = tuple(sorted(WEEKDAYS[d] for d in (plant.mrp_workdays or ["mon", "tue", "wed", "thu", "fri"])
                            if d in WEEKDAYS))
    node = NetNode(info["owner_id"], info["code"], info["kind"], info.get("country"), plant.currency or "USD",
                   plant.time_zone or "UTC", workdays, frozenset(snap.holidays))
    part = NodePart(node, as_of=as_of)
    wks = horizon_weeks(as_of, horizon_weeks_n)
    keys: dict[str, str] = {}
    for it in ds.items.values():
        if not getattr(it, "active", True):
            continue
        k = key_of(it)
        if not k or k in part.item_ids:
            continue
        keys[it.id] = k
        part.item_ids[k] = it.id
        part.names[k] = (it.description, it.family, it.uom)
        part.items.append(NetItem(node.id, k, it.id, it.family, it.uom, float(it.standard_cost or 0.0),
                                  float(it.safety_stock or 0.0), int(it.lead_time_days or 0),
                                  "buy" if it.make_buy == "buy" else "make", float(it.order_multiple or 0.0),
                                  float(it.min_order_qty or 0.0)))
    replanned = _replanned_tos(s)          # open unshipped network TOs are re-planned (keep / cancel at publish)
    # demand
    for d in snap.demand:
        k = keys.get(d.item_id)
        if k is None or d.open_qty <= 0 or (d.demand_type == "transfer" and d.order_id in replanned):
            continue
        kind = "transfer_open" if d.demand_type == "transfer" else "order"
        part.demand.append(NetDemand(node.id, k, d.due_date, float(d.open_qty), kind,
                                     f"{d.number}/{d.line_no}", int(d.effective_priority or 5)))
    for f in snap.forecasts:
        k = keys.get(f.item_id)
        if k is not None and f.qty > 0:
            part.demand.append(NetDemand(node.id, k, f.date, float(f.qty), "forecast",
                                         f"FC:{f.period_start.isoformat()}", 7))
    # supply
    for b in snap.balances:
        k = keys.get(b.item_id)
        if k is None or not b.location_active or b.kind in NON_NETTABLE:
            continue
        free = float(b.qty_on_hand) - float(b.qty_reserved or 0)
        if free <= 0:
            continue
        if b.hold and not b.inspection_hold:
            continue
        if b.expires_on is not None and b.expires_on < as_of:
            continue
        wk = as_of + timedelta(days=7) if b.inspection_hold else as_of
        part.supply.append(NetSupply(node.id, k, wk, free, "stock", b.id))
    for r in snap.release_supplies:
        k = keys.get(r.item_id)
        if k is not None:
            part.supply.append(NetSupply(node.id, k, r.avail_date, float(r.qty), "stock", r.ref_id))
    for sc in snap.schedules:
        k = keys.get(sc.item_id)
        if k is None or sc.open_qty <= 0 or sc.doc_type not in ("po",):
            continue
        if sc.doc_id in replanned:
            continue
        kind = "transfer_in" if sc.doc_id.startswith("tro_") else "po"
        part.supply.append(NetSupply(node.id, k, sc.confirmed_date or sc.requested_date, float(sc.open_qty), kind,
                                     f"{sc.number}/{sc.line_no}"))
    for w in snap.work_orders:
        k = keys.get(w.item_id)
        if k is not None and w.open_qty > 0:
            part.supply.append(NetSupply(node.id, k, w.due_date, float(w.open_qty), "wo", w.number))
    for r in snap.rate_supplies:
        k = keys.get(r.item_id)
        if k is not None:
            part.supply.append(NetSupply(node.id, k, r.avail_date, float(r.qty), "rate", r.ref_id))
    # BOM (current released BOM per made item; networked components are chosen by the engine)
    for it_id, boms in ds.boms_by_item.items():
        pk = keys.get(it_id)
        if pk is None:
            continue
        live = [b for b in boms if b.status == "released"] or boms
        b = live[-1]
        seen: set[str] = set()
        for ln in b.lines:
            ck = keys.get(ln.child_item_id)
            if ck is None or ck in seen or (ln.alt_group and ln.alt_priority != 1):
                continue
            seen.add(ck)
            part.bom.append(NetBomLine(node.id, pk, ck, float(ln.qty_per) * (1 + float(ln.scrap_pct or 0) / 100)))
    # capacity
    if info["kind"] == "plant" and ds.lines:
        for (g, wk), h in sorted(available_hours(ds, wks).items()):
            part.capacity.append(NetCap(node.id, g, wk, round(h, 4)))
        from sqlalchemy import select

        rates = list(s.execute(select(MfgLineRateRow)).scalars())
        oee = dict(s.execute(select(MfgLineRow.id, MfgLineRow.oee)).all())
        for it in ds.items.values():
            k = keys.get(it.id)
            if k is None or it.make_buy == "buy":
                continue
            for g, h in hours_per_unit(ds, it, rates, oee):
                part.load.append(NetLoad(node.id, g, k, h))
    return part


def _replanned_tos(s: Any) -> set[str]:
    """Ids (both directions) of the network's open transfer orders without any shipment."""
    from sqlalchemy import select

    from ...api.db.ownership import current_owner, system_scope
    from ...api.mfg.db_models_m5 import MfgTransferLineRow, MfgTransferOrderRow

    owner = str(current_owner())
    with system_scope():
        rows = list(s.execute(select(MfgTransferOrderRow.id, MfgTransferOrderRow.mirror_of).where(
            MfgTransferOrderRow.source == "network", MfgTransferOrderRow.status.in_(("draft", "open")),
            (MfgTransferOrderRow.source_owner_id == owner) | (MfgTransferOrderRow.dest_owner_id == owner))).all())
        if not rows:
            return set()
        src_ids = {i for i, m in rows if m is None} | {m for _i, m in rows if m is not None}
        shipped = set(s.execute(select(MfgTransferLineRow.order_id).where(
            MfgTransferLineRow.order_id.in_(src_ids), MfgTransferLineRow.shipped_qty > 0)).scalars())
    return {i for i, m in rows if (m or i) not in shipped}


def assemble(parts: list[NodePart], rules: list[NetRule], lanes: list[NetLane], *, as_of: date, horizon: int,
             constrained: bool, prebuild: int, firm_days: int, currency: str) -> NetProblem:
    uoms: dict[str, set[str]] = {}
    for pt in parts:
        for it in pt.items:
            uoms.setdefault(it.key, set()).add(it.uom)
    bad = {k for k, u in uoms.items() if len(u) > 1}
    warnings = [{"code": "NET_UOM_MISMATCH", "key": k, "detail": {"uoms": sorted(uoms[k])}} for k in sorted(bad)]

    def keep(x: Any) -> bool:
        return getattr(x, "key", None) not in bad

    items, demand, supply, bom, cap, load = [], [], [], [], [], []
    for pt in parts:
        items += [x for x in pt.items if keep(x)]
        demand += [x for x in pt.demand if keep(x)]
        supply += [x for x in pt.supply if keep(x)]
        bom += [x for x in pt.bom if x.parent_key not in bad and x.component_key not in bad]
        cap += pt.capacity
        load += [x for x in pt.load if keep(x)]
    return NetProblem(as_of=as_of, horizon_weeks=horizon, constrained=constrained, prebuild_weeks=prebuild,
                      firm_days=firm_days, nodes=[pt.node for pt in parts], items=items, demand=demand,
                      supply=supply, rules=rules, lanes=lanes, bom=bom, capacity=cap, load=load, currency=currency,
                      warnings=warnings)
