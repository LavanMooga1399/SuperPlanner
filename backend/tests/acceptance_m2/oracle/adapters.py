"""Translation between product types and oracle plants/results (contract of M2-DESIGN 8.2, 3, 9).

- `oplant_to_snapshot(plant)` builds the engine's `MrpSnapshot` + `MrpParams` from an oracle plant (used for the
  hand vectors and the randomized plants).
- `snapshot_to_oplant(snapshot, params)` reads a product snapshot (e.g. `repo_m2.load_mrp_snapshot` of a loaded
  sample) into an oracle plant.
- `engine_canon(result, snapshot)` / `oracle_canon(res)` turn both results into the same canonical shape for
  Gate 2 #2 (planned orders, peg quantities per (requirement, supply) pair, demand projected dates).

Product modules are imported lazily by name. A missing module/class raises `Unavailable` (the tests turn it into
a skip naming what is missing); a class whose fields contradict the contract raises `ContractMismatch` (a failure:
the contract or the implementation must change). The engine module itself is only *called*, never read.
"""

from __future__ import annotations

import dataclasses
import importlib
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any

from .model import (EPS, OBalance, OBom, OBomLine, ODemand, OExtraDemand, OItem, OItemSupplier, OLine, OOp,
                    OParams, OPlant, OReservation, OResult, ORouting, OSchedule, OSupplier, OWoComponent,
                    OWorkOrder)

ENGINE_MODULE = "superplanner.mfg.mrp"
_MODEL_MODULES = ("superplanner.mfg.mrp.model", "superplanner.mfg.mrp", "superplanner.mfg.model_m2",
                  "superplanner.mfg.model", "superplanner.mfg.dataset")
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


class Unavailable(Exception):
    """A product module/class of the M2 contract is not implemented yet."""


class ContractMismatch(AssertionError):
    pass


def _mod(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise Unavailable(f"module {name} not importable ({exc})") from exc


def find_cls(name: str) -> Any:
    for m in _MODEL_MODULES:
        try:
            mod = importlib.import_module(m)
        except ImportError:
            continue
        if hasattr(mod, name):
            return getattr(mod, name)
    raise Unavailable(f"class {name} (M2-DESIGN 8.2/3) not found in {', '.join(_MODEL_MODULES)}")


def engine() -> Any:
    mod = _mod(ENGINE_MODULE)
    if not hasattr(mod, "run_mrp"):
        raise Unavailable(f"{ENGINE_MODULE}.run_mrp (8.2) not implemented yet")
    return mod


def g(obj: Any, *names: str, default: Any = None) -> Any:
    """First present attribute/key of `names`."""
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return default


def _fields(cls: Any) -> tuple[set[str], set[str]]:
    """(all field names, required field names)."""
    if dataclasses.is_dataclass(cls):
        fs = dataclasses.fields(cls)
        req = {f.name for f in fs if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
        return {f.name for f in fs}, req
    if hasattr(cls, "model_fields"):
        return set(cls.model_fields), {n for n, f in cls.model_fields.items() if f.is_required()}
    if isinstance(cls, type) and issubclass(cls, tuple) and hasattr(cls, "_fields"):     # NamedTuple
        defaults = getattr(cls, "_field_defaults", {})
        return set(cls._fields), {n for n in cls._fields if n not in defaults}
    raise ContractMismatch(f"{cls} is neither a dataclass nor a pydantic model")


def build(cls: Any, *, validate: bool = False, **kw: Any) -> Any:
    names, required = _fields(cls)
    missing = sorted(required - set(kw))
    if missing:
        raise ContractMismatch(f"{cls.__name__} requires fields {missing} that M2-DESIGN does not define "
                               f"(known: {sorted(kw)})")
    data = {k: v for k, v in kw.items() if k in names}
    if dataclasses.is_dataclass(cls) or (isinstance(cls, type) and issubclass(cls, tuple)):
        return cls(**data)
    return cls.model_validate(data) if validate else cls.model_construct(**data)


def _require_fields(cls: Any, *names: str) -> None:
    have, _ = _fields(cls)
    lacking = [n for n in names if n not in have]
    if lacking:
        raise Unavailable(f"{cls.__name__} lacks M2 fields {lacking} (M2-DESIGN 3.1, WP-A)")


# ---------------------------------------------------------------- oracle plant -> product snapshot


def _iref(it: OItem) -> Any:
    ItemRef = find_cls("ItemRef")
    return ItemRef.model_construct(id=it.id, part_number=it.part_number, revision="A", description="",
                                   uom=it.uom, make_buy=it.make_buy, active=it.active)


def _stamp(i: str) -> dict[str, Any]:
    return {"id": i, "row_version": 1, "created_at": NOW, "updated_at": NOW}


def oplant_to_snapshot(p: OPlant) -> tuple[Any, Any]:
    ItemRecord = find_cls("ItemRecord")
    _require_fields(ItemRecord, "lot_period_days", "lot_controlled", "standard_cost", "external_ref")
    PlantRecord = find_cls("PlantRecord")
    _require_fields(PlantRecord, "mrp_workdays", "mrp_day_minutes", "mrp_defer_tolerance_days",
                    "mrp_release_window_days")
    BomRecord, BomLineRecord = find_cls("BomRecord"), find_cls("BomLineRecord")
    RoutingRecord, OperationRecord = find_cls("RoutingRecord"), find_cls("OperationRecord")
    GroupRecord, LineRecord, Ref = find_cls("GroupRecord"), find_cls("LineRecord"), find_cls("Ref")
    LocationRecord, SupplierRecord = find_cls("LocationRecord"), find_cls("SupplierRecord")
    ItemSupplierRecord, LotRecord = find_cls("ItemSupplierRecord"), find_cls("LotRecord")
    MfgDataset = find_cls("MfgDataset")
    _require_fields(MfgDataset, "locations", "suppliers", "item_suppliers")
    MrpSnapshot, MrpParams = find_cls("MrpSnapshot"), find_cls("MrpParams")
    BalanceSnap, ReservationSnap = find_cls("BalanceSnap"), find_cls("ReservationSnap")
    ScheduleSnap, DemandSnap, WoSnap = find_cls("ScheduleSnap"), find_cls("DemandSnap"), find_cls("WoSnap")
    from superplanner.mfg.dataset import link

    lot_items = {b.item_id for b in p.balances if b.lot_id}
    items = {}
    for it in p.items.values():
        items[it.id] = ItemRecord.model_construct(
            **_stamp(it.id), part_number=it.part_number, revision="A", description="", uom=it.uom,
            make_buy=it.make_buy, family=it.family, setup_family=None, lead_time_days=it.lead_time_days,
            receiving_days=it.receiving_days, lot_rule=it.lot_rule, fixed_lot_qty=it.fixed_lot_qty,
            lot_period_days=it.lot_period_days, min_order_qty=it.min_order_qty, order_multiple=it.order_multiple,
            safety_stock=it.safety_stock, serialized=it.serialized, shelf_life_days=None, handling_class=None,
            handling_note="", attributes={}, active=it.active, external_ref=None, standard_cost=None,
            lot_controlled=it.id in lot_items, has_bom=False, has_routing=False, used_in_count=0)
    group_ids = sorted({op.group_id for r in p.routings for op in r.ops} | {ln.group_id for ln in p.lines})
    groups = {gid: GroupRecord.model_construct(**_stamp(gid), code=f"G{i}", name=f"Group {i}", description="",
                                               kind=None, active=True, line_count=0)
              for i, gid in enumerate(group_ids)}

    def gref(gid: str) -> Any:
        return Ref.model_construct(id=gid, code=groups[gid].code, name=groups[gid].name)

    lines = {ln.id: LineRecord.model_construct(
        **_stamp(ln.id), group_id=ln.group_id, code=f"L{i}", name=f"Line {i}", speed_factor=ln.speed_factor,
        parallel_capacity=1, setup_family=None, eligible_families=list(ln.eligible_families),
        eligible_item_ids=list(ln.eligible_item_ids), cost_per_hour=0, active=ln.active, group=gref(ln.group_id),
        eligible_items=[]) for i, ln in enumerate(p.lines)}
    boms = {}
    for b in p.boms:
        blines = [BomLineRecord.model_construct(
            id=ln.id, find_number=ln.find_number, child_item_id=ln.child_id, qty_per=ln.qty_per, uom=ln.uom,
            scrap_pct=ln.scrap_pct, ref_designators="", alt_group=ln.alt_group, alt_priority=ln.alt_priority,
            operation_seq=ln.operation_seq, note="", child=_iref(p.items[ln.child_id])) for ln in b.lines]
        boms[b.id] = BomRecord.model_construct(
            **_stamp(b.id), item_id=b.item_id, revision=b.revision, version=b.version,
            effective_from=b.effective_from, effective_to=b.effective_to, serial_from=b.serial_from,
            serial_to=b.serial_to, note="", lines=blines, status=b.status, released_at=NOW, obsoleted_at=None,
            item=_iref(p.items[b.item_id]))
    routings = {}
    for r in p.routings:
        ops = [OperationRecord.model_construct(
            id=f"opr_{r.id[4:28]}{op.seq:08x}", seq=op.seq, name=f"Op {op.seq}", description="",
            group_id=op.group_id, setup_minutes=op.setup_minutes, run_minutes=op.run_minutes, run_per=op.run_per,
            units_per_panel=op.units_per_panel, units_per_batch=op.units_per_batch, queue_minutes=op.queue_minutes,
            move_minutes=op.move_minutes, wait_minutes=op.wait_minutes, labor="attended", crew_size=1,
            skill_id=None, tools=[], transfer_batch=None, yield_pct=op.yield_pct, inspection_gate=False,
            interruptible=True, group=gref(op.group_id), skill=None) for op in r.ops]
        routings[r.id] = RoutingRecord.model_construct(
            **_stamp(r.id), item_id=r.item_id, revision=r.revision, code=r.code, version=r.version,
            priority=r.priority, effective_from=r.effective_from, effective_to=r.effective_to,
            serial_from=r.serial_from, serial_to=r.serial_to, note="", operations=ops, status=r.status,
            released_at=NOW, obsoleted_at=None, item=_iref(p.items[r.item_id]))
    loc_ids = sorted({(b.location_id, b.location_kind) for b in p.balances})
    locations = {lid: LocationRecord.model_construct(**_stamp(lid), code=f"LOC{i}", name=f"Location {i}",
                                                     kind=kind, receipt_default=False, active=True,
                                                     external_ref=None, note="")
                 for i, (lid, kind) in enumerate(loc_ids)}
    suppliers = {s.id: SupplierRecord.model_construct(**_stamp(s.id), code=s.code, name=s.code,
                                                      lead_time_days=s.lead_time_days, currency="", contact_name="",
                                                      email="", phone="", address="", active=s.active,
                                                      external_ref=None, note="", item_count=0)
                 for s in p.suppliers.values()}
    isus = {r.id: ItemSupplierRecord.model_construct(
        **_stamp(r.id), item_id=r.item_id, supplier_id=r.supplier_id, supplier_part_number="",
        lead_time_days=r.lead_time_days, min_order_qty=r.min_order_qty, order_multiple=r.order_multiple,
        purchase_unit=None, units_per_purchase_unit=r.units_per_purchase_unit, unit_price=None, currency="",
        preferred=r.preferred, active=r.active, note="", item=_iref(p.items[r.item_id]),
        supplier=Ref.model_construct(id=r.supplier_id, code=p.suppliers[r.supplier_id].code,
                                     name=p.suppliers[r.supplier_id].code)) for r in p.item_suppliers}
    plant = PlantRecord.model_construct(
        id="plt_" + "0" * 32, row_version=1, created_at=NOW, updated_at=NOW, data_version=1, name="Plant",
        utc_offset="+00:00", planning_horizon_days=p.planning_horizon_days, currency="", attributes={},
        mrp_workdays=list(p.workdays), mrp_day_minutes=p.day_minutes,
        mrp_defer_tolerance_days=p.defer_tolerance_days, mrp_release_window_days=p.release_window_days,
        over_receipt_pct=0)
    ds = MfgDataset(plant=plant, items=items, boms=boms, routings=routings, groups=groups, lines=lines,
                    locations=locations, suppliers=suppliers, item_suppliers=isus)
    link(ds)
    lots = {}
    for b in p.balances:
        if b.lot_id and b.lot_id not in lots:
            lots[b.lot_id] = LotRecord.model_construct(
                **_stamp(b.lot_id), item=_iref(p.items[b.item_id]), item_id=b.item_id, lot_code=b.lot_code,
                expires_on=b.expires_on, received_on=None, supplier_lot="", hold=b.hold, note="", on_hand=0.0)
    balances = [build(BalanceSnap, id=b.id, balance_id=b.id, item_id=b.item_id, location_id=b.location_id,
                      kind=b.location_kind, location_kind=b.location_kind, lot_id=b.lot_id, lot_code=b.lot_code,
                      expires_on=b.expires_on, hold=b.hold, qty_on_hand=b.qty_on_hand, qty_reserved=b.qty_reserved,
                      last_receipt_on=b.last_receipt_on) for b in p.balances if b.qty_on_hand > EPS]
    reservations = [build(ReservationSnap, wo_component_id=r.wo_component_id, balance_id=r.balance_id, qty=r.qty)
                    for r in p.reservations]
    schedules = [build(ScheduleSnap, doc_type=s.doc_type, doc_id=s.doc_id, number=s.number,
                       doc_status=s.doc_status, line_id=s.line_id, line_no=s.line_no, schedule_id=s.schedule_id,
                       seq=s.seq, item_id=s.item_id, supplier_id=s.supplier_id, open_qty=s.open_qty,
                       requested_date=s.requested_date, confirmed_date=s.confirmed_date) for s in p.schedules]
    demand = [build(DemandSnap, order_id=x.order_id, number=x.number, demand_type=x.demand_type,
                    customer=x.customer, program=x.program, line_id=x.line_id, line_no=x.line_no, item_id=x.item_id,
                    open_qty=x.open_qty, due_date=x.due_date, effective_priority=x.priority,
                    serial_from=x.serial_from, serial_to=x.serial_to) for x in p.demand]
    comp_cls = None
    for name in ("WoComponentSnap", "ComponentSnap"):
        try:
            comp_cls = find_cls(name)
            break
        except Unavailable:
            pass

    def comp(c: OWoComponent) -> Any:
        if comp_cls is None:
            return (c.id, c.item_id, c.open_qty, c.operation_seq)
        return build(comp_cls, component_id=c.id, id=c.id, item_id=c.item_id, open_qty=c.open_qty,
                     operation_seq=c.operation_seq)

    wos = [build(WoSnap, id=w.id, number=w.number, status=w.status, item_id=w.item_id, open_qty=w.open_qty,
                 start_date=w.start_date, due_date=w.due_date, priority=w.priority, serial_from=w.serial_from,
                 serial_to=w.serial_to, routing_id=w.routing_id, components=tuple(comp(c) for c in w.components))
           for w in p.work_orders]
    snap = build(MrpSnapshot, as_of=p.params.as_of, dataset=ds, lots=lots, balances=balances,
                 reservations=reservations, schedules=schedules, demand=demand, work_orders=wos,
                 holidays=frozenset(p.holidays))
    params = oparams_to_mrp_params(p.params, MrpParams)
    return snap, params


def oparams_to_mrp_params(op: OParams, MrpParams: Any) -> Any:
    body: dict[str, Any] = {"allocation": op.allocation, "alternates": op.alternates,
                            "safety_stock": op.safety_stock, "include_pr_supply": op.include_pr_supply,
                            "protect_programs": list(op.protect_programs)}
    if op.horizon_days is not None:
        body["horizon_days"] = op.horizon_days
    if op.demand_filter:
        body["demand_filter"] = op.demand_filter
    if op.exclude_demand_line_ids:
        body["exclude_demand_line_ids"] = list(op.exclude_demand_line_ids)
    if op.extra_demand:
        body["extra_demand"] = [{"item_id": x.item_id, "qty": x.qty, "due_date": x.due_date,
                                 "priority": x.priority, "serial_from": x.serial_from, "serial_to": x.serial_to,
                                 "label": x.label} for x in op.extra_demand]
    if op.supply_date_overrides:
        body["supply_date_overrides"] = [
            ({"wo_id": k} if k.startswith("wko_") else {"schedule_id": k}) | {"date": v}
            for k, v in sorted(op.supply_date_overrides.items())]
    if op.lead_time_overrides:
        body["lead_time_overrides"] = [{"item_id": k, "lead_time_days": v}
                                       for k, v in sorted(op.lead_time_overrides.items())]
    return MrpParams.model_validate(body)


def mrp_params_body(op: OParams) -> dict[str, Any]:
    """The same params as a JSON body for POST /mrp/runs (as_of explicit -> a what_if run)."""
    body: dict[str, Any] = {"as_of": op.as_of.isoformat(), "allocation": op.allocation,
                            "alternates": op.alternates, "safety_stock": op.safety_stock,
                            "include_pr_supply": op.include_pr_supply}
    if op.horizon_days is not None:
        body["horizon_days"] = op.horizon_days
    return body


# ---------------------------------------------------------------- product snapshot -> oracle plant


def snapshot_to_oplant(snap: Any, params: Any) -> OPlant:
    ds = g(snap, "dataset")
    plant = ds.plant
    items = {i.id: OItem(id=i.id, part_number=i.part_number, make_buy=i.make_buy, uom=i.uom,
                         lead_time_days=i.lead_time_days, receiving_days=i.receiving_days, lot_rule=i.lot_rule,
                         fixed_lot_qty=i.fixed_lot_qty, lot_period_days=g(i, "lot_period_days"),
                         min_order_qty=i.min_order_qty, order_multiple=i.order_multiple,
                         safety_stock=i.safety_stock, serialized=i.serialized, active=i.active, family=i.family)
             for i in ds.items.values()}
    boms = [OBom(id=b.id, item_id=b.item_id, status=b.status, version=b.version, revision=b.revision,
                 effective_from=b.effective_from, effective_to=b.effective_to, serial_from=b.serial_from,
                 serial_to=b.serial_to,
                 lines=[OBomLine(id=ln.id, find_number=ln.find_number, child_id=ln.child_item_id, qty_per=ln.qty_per,
                                 uom=ln.uom, scrap_pct=ln.scrap_pct, alt_group=ln.alt_group,
                                 alt_priority=ln.alt_priority, operation_seq=ln.operation_seq) for ln in b.lines])
            for b in ds.boms.values()]
    routings = [ORouting(id=r.id, item_id=r.item_id, status=r.status, priority=r.priority, version=r.version,
                         revision=r.revision, code=r.code, effective_from=r.effective_from,
                         effective_to=r.effective_to, serial_from=r.serial_from, serial_to=r.serial_to,
                         ops=[OOp(seq=o.seq, group_id=o.group_id, setup_minutes=o.setup_minutes,
                                  run_minutes=o.run_minutes, run_per=o.run_per, units_per_panel=o.units_per_panel,
                                  units_per_batch=o.units_per_batch, queue_minutes=o.queue_minutes,
                                  move_minutes=o.move_minutes, wait_minutes=o.wait_minutes, yield_pct=o.yield_pct)
                              for o in r.operations]) for r in ds.routings.values()]
    lines = [OLine(id=ln.id, group_id=ln.group_id, speed_factor=ln.speed_factor, active=ln.active,
                   eligible_families=list(ln.eligible_families), eligible_item_ids=list(ln.eligible_item_ids))
             for ln in ds.lines.values()]
    suppliers = {s.id: OSupplier(id=s.id, code=s.code, lead_time_days=s.lead_time_days, active=s.active)
                 for s in g(ds, "suppliers", default={}).values()}
    isus = [OItemSupplier(id=r.id, item_id=r.item_id, supplier_id=r.supplier_id, lead_time_days=r.lead_time_days,
                          min_order_qty=r.min_order_qty, order_multiple=r.order_multiple,
                          units_per_purchase_unit=r.units_per_purchase_unit, preferred=r.preferred, active=r.active)
            for r in g(ds, "item_suppliers", default={}).values()]
    locs = g(ds, "locations", default={})
    lots = g(snap, "lots", default={}) or {}
    balances = []
    for b in g(snap, "balances", default=[]):
        lot_id = g(b, "lot_id")
        lot = lots.get(lot_id) if lot_id else None
        loc_id = g(b, "location_id")
        kind = g(b, "kind", "location_kind") or (locs[loc_id].kind if loc_id in locs else None)
        balances.append(OBalance(
            id=g(b, "id", "balance_id"), item_id=g(b, "item_id"), location_id=loc_id, location_kind=kind,
            qty_on_hand=g(b, "qty_on_hand"), qty_reserved=g(b, "qty_reserved", default=0.0), lot_id=lot_id,
            lot_code=g(lot, "lot_code") if lot is not None else g(b, "lot_code"),
            expires_on=g(b, "expires_on", default=g(lot, "expires_on") if lot is not None else None),
            hold=bool(g(b, "hold", default=g(lot, "hold", default=False) if lot is not None else False)),
            last_receipt_on=g(b, "last_receipt_on")))
    reservations = [OReservation(wo_component_id=g(r, "wo_component_id"), balance_id=g(r, "balance_id"),
                                 qty=g(r, "qty")) for r in g(snap, "reservations", default=[])]
    schedules = [OSchedule(doc_type=g(s, "doc_type"), doc_id=g(s, "doc_id"), number=g(s, "number"),
                           doc_status=g(s, "doc_status"), line_id=g(s, "line_id"), line_no=g(s, "line_no"),
                           schedule_id=g(s, "schedule_id"), seq=g(s, "seq"), item_id=g(s, "item_id"),
                           supplier_id=g(s, "supplier_id"), open_qty=g(s, "open_qty"),
                           requested_date=g(s, "requested_date"), confirmed_date=g(s, "confirmed_date"))
                 for s in g(snap, "schedules", default=[])]
    demand = [ODemand(order_id=g(x, "order_id"), number=g(x, "number"), demand_type=g(x, "demand_type"),
                      customer=g(x, "customer", default=""), program=g(x, "program"), line_id=g(x, "line_id"),
                      line_no=g(x, "line_no"), item_id=g(x, "item_id"), open_qty=g(x, "open_qty"),
                      due_date=g(x, "due_date"), priority=g(x, "effective_priority", "priority"),
                      serial_from=g(x, "serial_from"), serial_to=g(x, "serial_to"))
              for x in g(snap, "demand", default=[])]

    def comp(c: Any) -> OWoComponent:
        if isinstance(c, tuple):
            return OWoComponent(id=c[0], item_id=c[1], open_qty=c[2], operation_seq=c[3] if len(c) > 3 else None)
        return OWoComponent(id=g(c, "component_id", "id"), item_id=g(c, "item_id"), open_qty=g(c, "open_qty"),
                            operation_seq=g(c, "operation_seq"))

    wos = [OWorkOrder(id=g(w, "id"), number=g(w, "number"), status=g(w, "status"), item_id=g(w, "item_id"),
                      open_qty=g(w, "open_qty"), start_date=g(w, "start_date"), due_date=g(w, "due_date"),
                      priority=g(w, "priority", default=5), serial_from=g(w, "serial_from"),
                      serial_to=g(w, "serial_to"), routing_id=g(w, "routing_id"),
                      components=[comp(c) for c in g(w, "components", default=[])])
           for w in g(snap, "work_orders", default=[])]
    op = OParams(as_of=g(snap, "as_of"), horizon_days=g(params, "horizon_days"),
                 allocation=g(params, "allocation", default="priority"),
                 alternates=g(params, "alternates", default="when_short"),
                 safety_stock=g(params, "safety_stock", default=True),
                 include_pr_supply=g(params, "include_pr_supply", default=True),
                 protect_programs=list(g(params, "protect_programs", default=[]) or []),
                 demand_filter=_dump(g(params, "demand_filter")),
                 exclude_demand_line_ids=list(g(params, "exclude_demand_line_ids", default=[]) or []),
                 extra_demand=[OExtraDemand(item_id=g(x, "item_id"), qty=g(x, "qty"), due_date=g(x, "due_date"),
                                            priority=g(x, "priority", default=5), serial_from=g(x, "serial_from"),
                                            serial_to=g(x, "serial_to"), label=g(x, "label", default=""))
                               for x in g(params, "extra_demand", default=[]) or []],
                 supply_date_overrides={(g(x, "schedule_id") or g(x, "wo_id")): g(x, "date")
                                        for x in g(params, "supply_date_overrides", default=[]) or []},
                 lead_time_overrides={g(x, "item_id"): g(x, "lead_time_days")
                                      for x in g(params, "lead_time_overrides", default=[]) or []})
    return OPlant(params=op, items=items, boms=boms, routings=routings, lines=lines, suppliers=suppliers,
                  item_suppliers=isus, balances=balances, reservations=reservations, schedules=schedules,
                  demand=demand, work_orders=wos, holidays=frozenset(g(snap, "holidays", default=()) or ()),
                  workdays=tuple(g(plant, "mrp_workdays", default=("mon", "tue", "wed", "thu", "fri", "sat"))),
                  day_minutes=float(g(plant, "mrp_day_minutes", default=480.0)),
                  planning_horizon_days=plant.planning_horizon_days,
                  release_window_days=int(g(plant, "mrp_release_window_days", default=7)),
                  defer_tolerance_days=int(g(plant, "mrp_defer_tolerance_days", default=7)))


def _dump(x: Any) -> dict[str, Any] | None:
    if x is None:
        return None
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return dict(x)


# ---------------------------------------------------------------- canonical results


def _seg(x: Any) -> tuple[int, int] | None:
    if x is None:
        return None
    if isinstance(x, (tuple, list)):
        return (int(x[0]), int(x[1]))
    lo = g(x, "serial_from", "from_", "lo", "start", "first")
    hi = g(x, "serial_to", "to", "hi", "end", "last")
    if lo is None and isinstance(x, dict):
        lo, hi = x.get("from"), x.get("to")
    return (int(lo), int(hi))


def _rank(x: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in x) if x is not None else ()


@dataclasses.dataclass
class Canon:
    planned: Counter                     # (part_number, kind, qty, need, start, segment) -> count
    demand: dict[Any, Any]               # demand key -> projected_date
    pegs: dict[tuple[Any, Any], float]   # (req key, supply key) -> qty
    pegs_tie: dict[tuple[Any, Any], float]
    req_totals: dict[Any, float]
    iterations: int


def _planned_ids(rows: list[tuple[int, Any]]) -> dict[int, tuple[Any, ...]]:
    """planned_no -> canonical id (item, kind, segment, need, start, qty, ordinal)."""
    base = sorted(rows, key=lambda r: (repr(r[1]), r[0]))
    seen: Counter = Counter()
    out = {}
    for no, key in base:
        out[no] = key + (seen[key],)
        seen[key] += 1
    return out


def oracle_canon(res: OResult, plant: OPlant) -> Canon:
    pn = {i: it.part_number for i, it in plant.items.items()}
    pids = _planned_ids([(p.planned_no, (pn[p.item_id], p.kind, p.segment, p.need_date, p.start_date,
                                         round(p.qty, 6))) for p in res.planned])
    planned = Counter((pn[p.item_id], p.kind, round(p.qty, 6), p.need_date, p.start_date, p.segment)
                      for p in res.planned)

    def req_key(r: Any) -> tuple[Any, ...]:
        if r.kind == "demand":
            return ("demand", r.source[1])
        if r.kind == "extra_demand":
            x = r.source[2]
            return ("extra", pn[x.item_id], x.due_date, round(x.qty, 6))
        if r.kind == "safety_stock":
            return ("ss", pn[r.item_id])
        if r.kind == "wo_component":
            return ("woc", pn[r.item_id], r.source[1])
        return ("pc", pn[r.item_id], pids[r.source[1]])

    def sup_key(s: Any) -> tuple[Any, ...]:
        if s.kind in ("stock", "inspection"):
            return ("bal", s.ref[1])
        if s.kind in ("po", "pr"):
            return ("sch", s.ref[1])
        if s.kind == "wo":
            return ("wo", s.ref[1])
        return ("pl", pids[s.planned_no])

    def sup_class(s: Any) -> tuple[Any, ...]:
        if s.kind == "planned":
            po = next(p for p in res.planned if p.planned_no == s.planned_no)
            return (pn[s.item_id], "planned", s.avail_date, po.segment)
        return (pn[s.item_id], s.kind, s.avail_date, s.expires_on)

    pegs: dict = defaultdict(float)
    tie: dict = defaultdict(float)
    totals: dict = defaultdict(float)
    for item_id, rs in res.requirements.items():
        for r in rs:
            totals[req_key(r)] += r.qty
            for pg in r.pegs:
                s = res.supplies[pg.supply_item_id][pg.supply_node - 1]
                pegs[(req_key(r), sup_key(s))] += pg.qty
                tie[((pn[item_id], _rank(r.rank), r.need_date), sup_class(s))] += pg.qty
    demand = {}
    for dp in res.demand:
        if dp.key[0] == "demand":
            demand[("demand", dp.key[1])] = dp.projected_date
        else:
            x = plant.params.extra_demand[dp.key[1]]
            demand[("extra", pn[x.item_id], x.due_date, round(x.qty, 6))] = dp.projected_date
    return Canon(planned, demand, _r(pegs), _r(tie), _r(totals), res.iterations)


def _r(d: dict) -> dict:
    return {k: round(v, 6) for k, v in d.items() if round(v, 6) != 0}


def engine_canon(result: Any, plant: OPlant) -> Canon:
    """Same shape from the engine's MrpResult (field names per 8.2; SourceRef per 12.4 requirement source)."""
    pn = {i: it.part_number for i, it in plant.items.items()}
    balances = {b.id: b for b in plant.balances}
    lot_bal = {(b.item_id, b.lot_id): b.id for b in plant.balances if b.lot_id}
    schedules = {s.schedule_id for s in plant.schedules}
    pos = list(g(result, "planned_orders", default=[]))
    by_no = {g(p, "planned_no"): p for p in pos}
    pids = _planned_ids([(g(p, "planned_no"), (pn[g(p, "item_id")], g(p, "kind"), _seg(g(p, "segment")),
                                               g(p, "need_date"), g(p, "start_date"), round(g(p, "qty"), 6)))
                         for p in pos])
    planned = Counter((pn[g(p, "item_id")], g(p, "kind"), round(g(p, "qty"), 6), g(p, "need_date"),
                       g(p, "start_date"), _seg(g(p, "segment"))) for p in pos)
    plans = {g(ip, "item_id"): ip for ip in g(result, "items", default=[])}
    sup_index = {(iid, g(s, "node")): s for iid, ip in plans.items() for s in g(ip, "supplies", default=[])}

    def sup_key(item_id: str, s: Any) -> tuple[Any, ...]:
        kind = g(s, "kind")
        ref = g(s, "ref")
        rid = g(ref, "id", "balance_id", "schedule_id", "wo_id")
        if kind in ("stock", "inspection"):
            if rid in balances:
                return ("bal", rid)
            if (item_id, rid) in lot_bal:
                return ("bal", lot_bal[(item_id, rid)])
            raise ContractMismatch(f"stock supply ref {ref!r} names no balance of the snapshot")
        if kind in ("po", "pr"):
            sid = g(ref, "schedule_id") or rid
            if sid not in schedules:
                raise ContractMismatch(f"{kind} supply ref {ref!r} names no schedule of the snapshot")
            return ("sch", sid)
        if kind == "wo":
            return ("wo", g(ref, "wo_id") or rid)
        if kind == "planned":
            return ("pl", pids[g(s, "planned_no")])
        raise ContractMismatch(f"unknown supply kind {kind}")

    def sup_class(item_id: str, s: Any) -> tuple[Any, ...]:
        kind = g(s, "kind")
        if kind == "planned":
            return (pn[item_id], "planned", g(s, "avail_date"), _seg(g(by_no[g(s, "planned_no")], "segment")))
        return (pn[item_id], kind, g(s, "avail_date"), g(s, "expires_on"))

    def parent_supply(src: Any) -> tuple[str, Any]:
        iid = g(src, "item_id", "parent_item_id")
        node = g(src, "node", "supply_node")
        if iid is None or node is None or (iid, node) not in sup_index:
            raise ContractMismatch(f"dependent requirement source {src!r} does not address a parent supply "
                                   "(item_id, node) (8.2)")
        return iid, sup_index[(iid, node)]

    def req_key(item_id: str, r: Any) -> tuple[Any, ...]:
        kind = g(r, "kind")
        src = g(r, "source")
        if kind == "demand":
            return ("demand", g(src, "id", "demand_line_id"))
        if kind == "extra_demand":
            return ("extra", pn[item_id], g(r, "need_date"), round(g(r, "qty"), 6))
        if kind == "safety_stock":
            return ("ss", pn[item_id])
        piid, ps = parent_supply(src)
        if kind == "wo_component":
            return ("woc", pn[item_id], sup_key(piid, ps)[1])
        return ("pc", pn[item_id], pids[g(ps, "planned_no")])

    pegs: dict = defaultdict(float)
    tie: dict = defaultdict(float)
    totals: dict = defaultdict(float)
    for item_id, ip in plans.items():
        for r in g(ip, "requirements", default=[]):
            rk = req_key(item_id, r)
            totals[rk] += g(r, "qty")
            for pg in g(r, "pegs", default=[]):
                siid = g(pg, "supply_item_id") or item_id
                s = sup_index[(siid, g(pg, "supply_node"))]
                pegs[(rk, sup_key(siid, s))] += g(pg, "qty")
                tie[((pn[item_id], _rank(g(r, "rank")), g(r, "need_date")), sup_class(siid, s))] += g(pg, "qty")
    demand = {}
    for dp in g(result, "demand", default=[]):
        lid = g(dp, "demand_line_id")
        if lid:
            demand[("demand", lid)] = g(dp, "projected_date")
        else:
            demand[("extra", pn[g(dp, "item_id")], g(dp, "due_date"), round(g(dp, "qty"), 6))] = \
                g(dp, "projected_date")
    return Canon(planned, demand, _r(pegs), _r(tie), _r(totals), int(g(result, "iterations", default=1)))


def diff_canon(a: Canon, b: Canon, *, limit: int = 25) -> dict[str, list[str]]:
    """a = engine, b = oracle. Returns {'planned', 'demand', 'pegs', 'pegs_tie', 'totals', 'iterations'} diffs."""
    out: dict[str, list[str]] = {k: [] for k in ("planned", "demand", "pegs", "pegs_tie", "totals", "iterations")}
    for k in sorted(set(a.planned) | set(b.planned), key=repr):
        if a.planned[k] != b.planned[k]:
            out["planned"].append(f"{k}: engine {a.planned[k]} oracle {b.planned[k]}")
    for k in sorted(set(a.demand) | set(b.demand), key=repr):
        if a.demand.get(k) != b.demand.get(k):
            out["demand"].append(f"{k}: engine {a.demand.get(k)} oracle {b.demand.get(k)}")
    for name in ("pegs", "pegs_tie"):
        x, y = getattr(a, name), getattr(b, name)
        for k in sorted(set(x) | set(y), key=repr):
            if abs(x.get(k, 0) - y.get(k, 0)) > 1e-5:
                out[name].append(f"{k}: engine {x.get(k, 0)} oracle {y.get(k, 0)}")
    for k in sorted(set(a.req_totals) | set(b.req_totals), key=repr):
        if abs(a.req_totals.get(k, 0) - b.req_totals.get(k, 0)) > 1e-5:
            out["totals"].append(f"{k}: engine {a.req_totals.get(k, 0)} oracle {b.req_totals.get(k, 0)}")
    if a.iterations != b.iterations:
        out["iterations"].append(f"engine {a.iterations} oracle {b.iterations}")
    return {k: v[:limit] for k, v in out.items() if v}
