"""`MfgBundle`: the one interchange format (M1-DESIGN 8.1, 8.2) for import, export, fingerprints and samples.

A bundle is `{sheet name: [row dict]}`; rows reference other entities by natural keys/codes, never ids. Row values
are Python scalars: `str`, `int`, `float`, `bool`, `None`, `datetime.date` (date columns), aware `datetime`
(datetime columns, plant offset) and `list[str]` (list columns; `[]` when empty). Items carry attributes as extra
`attr:<name>` columns.

Canonical bundles (`dataset_to_bundle`) contain every column of every sheet, rows sorted by natural key (shifts in
template order, BOM lines in 3.5 line order, operations by seq) and set-like list values sorted, so
`dataset_to_bundle(bundle_to_dataset(b)) == b` for every canonical `b`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import ValidationError

from .dataset import MfgDataset, line_sort_key, link
from .model import (WEEKDAYS, BomInput, BomLineRecord, BomRecord, CalendarExceptionInput,
                    CalendarExceptionRecord, GroupInput, GroupRecord, ItemInput, ItemRecord, LineInput, LineRecord,
                    OperationInput, OperationRecord, OperationToolRecord, OperatorInput, OperatorRecord, PlantInput,
                    PlantRecord, RoutingInput, RoutingRecord, ShiftAssignmentInput, ShiftAssignmentRecord,
                    ShiftTemplateInput, ShiftTemplateRecord, SkillInput, SkillRecord, ToolPoolInput, ToolPoolRecord)
from .units import UOM_CODES

MfgBundle = dict[str, list[dict[str, Any]]]
ColumnType = Literal["str", "int", "float", "bool", "date", "datetime", "list", "enum"]

#: Timestamps of records created from a bundle (pure datasets only; never written to the database).
BUNDLE_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
ATTR_PREFIX = "attr:"


@dataclass(frozen=True)
class ColumnSpec:
    field: str
    type: ColumnType
    required_on_create: bool = False
    key: bool = False
    enum_values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SheetSpec:
    name: str
    columns: tuple[ColumnSpec, ...]
    attr_columns: bool = False          # extra `attr:<name>` columns allowed (items)
    max_rows: int | None = None

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(c.field for c in self.columns if c.key)

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(c.field for c in self.columns)

    def column(self, name: str) -> ColumnSpec:
        for c in self.columns:
            if c.field == name:
                return c
        raise KeyError(name)


def _c(f: str, t: ColumnType = "str", req: bool = False, key: bool = False,
       enum: tuple[str, ...] | None = None) -> ColumnSpec:
    return ColumnSpec(f, "enum" if enum is not None else t, req, key, enum)


_STATUS = ("draft", "released", "obsolete")
_DOC_EFF = (_c("effective_from", "date"), _c("effective_to", "date"), _c("serial_from", "int"),
            _c("serial_to", "int"), _c("note"), _c("status", enum=_STATUS))

SHEETS: tuple[SheetSpec, ...] = (
    SheetSpec("plant", (_c("name"), _c("utc_offset"), _c("planning_horizon_days", "int"), _c("currency")),
              max_rows=1),
    SheetSpec("items", (
        _c("part_number", req=True, key=True), _c("revision"), _c("description"), _c("uom", enum=UOM_CODES),
        _c("make_buy", req=True, enum=("make", "buy", "phantom")), _c("family"), _c("setup_family"),
        _c("lead_time_days", "int"), _c("receiving_days", "int"),
        _c("lot_rule", enum=("lot_for_lot", "fixed", "period")),
        _c("fixed_lot_qty", "float"), _c("min_order_qty", "float"), _c("order_multiple", "float"),
        _c("safety_stock", "float"), _c("serialized", "bool"), _c("shelf_life_days", "int"),
        _c("handling_class"), _c("handling_note"), _c("active", "bool"), _c("external_ref"),
        _c("standard_cost", "float"), _c("lot_controlled", "bool"), _c("lot_period_days", "int")),
              attr_columns=True),
    SheetSpec("skills", (_c("code", req=True, key=True), _c("name", req=True), _c("description"))),
    SheetSpec("tool_pools", (_c("code", req=True, key=True), _c("name", req=True), _c("kind"),
                             _c("quantity", "int", req=True), _c("note"))),
    SheetSpec("groups", (_c("code", req=True, key=True), _c("name", req=True), _c("description"), _c("kind"),
                         _c("active", "bool"))),
    SheetSpec("lines", (_c("code", req=True, key=True), _c("group_code", req=True), _c("name", req=True),
                        _c("speed_factor", "float"), _c("parallel_capacity", "int"), _c("setup_family"),
                        _c("eligible_families", "list"), _c("eligible_part_numbers", "list"),
                        _c("cost_per_hour", "float"), _c("active", "bool"))),
    SheetSpec("shift_templates", (_c("code", req=True, key=True), _c("name", req=True), _c("description"))),
    SheetSpec("shifts", (_c("template_code", req=True, key=True), _c("shift_name", req=True, key=True),
                         _c("days", "list", req=True), _c("start", req=True), _c("end", req=True),
                         _c("breaks", "list"))),
    SheetSpec("shift_assignments", (
        _c("template_code", req=True, key=True), _c("target_type", req=True, key=True, enum=("group", "line")),
        _c("target_code", req=True, key=True), _c("kind", req=True, key=True, enum=("base", "optional")),
        _c("effective_from", "date", req=True, key=True), _c("effective_to", "date"), _c("shift_names", "list"),
        _c("cost_per_hour", "float"), _c("max_hours_per_week", "float"), _c("note"))),
    SheetSpec("calendar_exceptions", (
        _c("scope", req=True, key=True, enum=("plant", "group", "line")), _c("target_code", key=True),
        _c("kind", req=True, key=True, enum=("holiday", "shutdown", "maintenance")),
        _c("start", "datetime", req=True, key=True), _c("end", "datetime", req=True), _c("label"))),
    SheetSpec("operators", (_c("code", req=True, key=True), _c("name", req=True), _c("skills", "list"),
                            _c("shift_template_code"), _c("shift_names", "list"), _c("home_group_code"),
                            _c("active", "bool"))),
    SheetSpec("boms", (_c("parent_part_number", req=True, key=True), _c("revision", key=True),
                       _c("version", "int", key=True)) + _DOC_EFF),
    SheetSpec("bom_lines", (
        _c("parent_part_number", req=True, key=True), _c("revision", key=True), _c("version", "int", key=True),
        _c("find_number", key=True), _c("child_part_number", req=True, key=True), _c("qty_per", "float", req=True),
        _c("uom", enum=UOM_CODES), _c("scrap_pct", "float"), _c("ref_designators"), _c("alt_group"),
        _c("alt_priority", "int"), _c("operation_seq", "int"), _c("note"))),
    SheetSpec("routings", (_c("part_number", req=True, key=True), _c("revision", key=True),
                           _c("code", key=True), _c("version", "int", key=True), _c("priority", "int")) + _DOC_EFF),
    SheetSpec("operations", (
        _c("part_number", req=True, key=True), _c("revision", key=True), _c("code", key=True),
        _c("version", "int", key=True), _c("seq", "int", req=True, key=True), _c("name", req=True),
        _c("group_code", req=True), _c("setup_minutes", "float"), _c("run_minutes", "float"),
        _c("run_per", enum=("unit", "panel", "batch")), _c("units_per_panel", "int"), _c("units_per_batch", "int"),
        _c("queue_minutes", "float"), _c("move_minutes", "float"), _c("wait_minutes", "float"),
        _c("labor", enum=("attended", "unattended")), _c("crew_size", "int"), _c("skill_code"),
        _c("tools", "list"), _c("transfer_batch", "int"), _c("yield_pct", "float"), _c("inspection_gate", "bool"),
        _c("interruptible", "bool"))),
    # ------------------------------------------------------------ M2-DESIGN 11 (after the M1 sheets)
    SheetSpec("locations", (_c("code", req=True, key=True), _c("name", req=True),
                            _c("kind", req=True, enum=("stores", "line_side", "inspection", "quarantine")),
                            _c("receipt_default", "bool"), _c("active", "bool"), _c("external_ref"), _c("note"))),
    SheetSpec("suppliers", (_c("code", req=True, key=True), _c("name", req=True), _c("lead_time_days", "int"),
                            _c("currency"), _c("contact_name"), _c("email"), _c("phone"), _c("address"),
                            _c("active", "bool"), _c("external_ref"), _c("note"))),
    SheetSpec("item_suppliers", (
        _c("part_number", req=True, key=True), _c("supplier_code", req=True, key=True), _c("supplier_part_number"),
        _c("lead_time_days", "int"), _c("min_order_qty", "float"), _c("order_multiple", "float"),
        _c("purchase_unit"), _c("units_per_purchase_unit", "float"), _c("unit_price", "float"), _c("currency"),
        _c("preferred", "bool"), _c("active", "bool"), _c("note"))),
    SheetSpec("stock", (_c("part_number", req=True, key=True), _c("location_code", req=True, key=True),
                        _c("lot_code", key=True), _c("qty", "float", req=True), _c("expires_on", "date"),
                        _c("supplier_lot"))),
    SheetSpec("purchase_docs", (
        _c("doc_type", req=True, key=True, enum=("pr", "po")), _c("number", req=True, key=True),
        _c("status", enum=("draft", "submitted", "approved", "rejected", "ordered", "open", "partially_received",
                           "received", "closed", "cancelled")),
        _c("supplier_code"), _c("currency"), _c("order_date", "date"), _c("note"), _c("external_ref"))),
    SheetSpec("purchase_lines", (
        _c("doc_type", req=True, key=True, enum=("pr", "po")), _c("number", req=True, key=True),
        _c("line_no", "int", req=True, key=True), _c("part_number", req=True), _c("unit_price", "float"),
        _c("note"))),
    SheetSpec("purchase_schedules", (
        _c("doc_type", req=True, key=True, enum=("pr", "po")), _c("number", req=True, key=True),
        _c("line_no", "int", req=True, key=True), _c("seq", "int", req=True, key=True),
        _c("requested_date", "date", req=True), _c("confirmed_date", "date"), _c("qty", "float", req=True),
        _c("received_qty", "float"))),
    SheetSpec("demand_orders", (
        _c("number", req=True, key=True), _c("demand_type", req=True, enum=("customer", "internal", "spares",
                                                                              "project")),
        _c("customer"), _c("program"), _c("priority", "int"),
        _c("status", enum=("draft", "open", "closed", "cancelled")), _c("note"), _c("external_ref"))),
    SheetSpec("demand_lines", (
        _c("number", req=True, key=True), _c("line_no", "int", req=True, key=True), _c("part_number", req=True),
        _c("qty", "float", req=True), _c("due_date", "date", req=True), _c("serial_from", "int"),
        _c("serial_to", "int"), _c("priority", "int"), _c("shipped_qty", "float"), _c("note"))),
    SheetSpec("work_orders", (
        _c("number", req=True, key=True), _c("part_number", req=True), _c("qty", "float", req=True),
        _c("start_date", "date"), _c("due_date", "date", req=True),
        _c("status", enum=("planned", "released", "in_progress", "completed", "closed", "cancelled")),
        _c("priority", "int"), _c("serial_from", "int"), _c("serial_to", "int"), _c("qty_completed", "float"),
        _c("note"), _c("external_ref"))),
    SheetSpec("wo_components", (
        _c("wo_number", req=True, key=True), _c("part_number", req=True, key=True), _c("find_number", key=True),
        _c("required_qty", "float", req=True), _c("issued_qty", "float"), _c("operation_seq", "int"), _c("note"))),
)
SHEET_NAMES: tuple[str, ...] = tuple(s.name for s in SHEETS)
SHEETS_BY_NAME: dict[str, SheetSpec] = {s.name: s for s in SHEETS}
#: M2-DESIGN 11: sheet kind -> permission(s) checked on import commit
M2_MASTER_SHEETS: tuple[str, ...] = ("locations", "suppliers", "item_suppliers")
TXN_SHEETS: tuple[str, ...] = ("stock", "purchase_docs", "purchase_lines", "purchase_schedules", "demand_orders",
                               "demand_lines", "work_orders", "wo_components")
MASTER_SHEETS: tuple[str, ...] = tuple(n for n in SHEET_NAMES if n not in TXN_SHEETS)


class BundleError(ValueError):
    """A canonical bundle with invalid rows (`errors`: `"<sheet> row <n>: <message>"`, n 1-based data rows)."""

    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} invalid bundle row(s): " + "; ".join(errors[:5]))
        self.errors = errors


# ---------------------------------------------------------------- helpers


def deterministic_id(prefix: str, *key: Any) -> str:
    """prefix + first 32 hex of sha256 of the natural key (pure datasets only, review R5)."""
    raw = "\x1f".join("" if k is None else str(k) for k in key)
    return prefix + hashlib.sha256(f"{prefix}{raw}".encode()).hexdigest()[:32]


def _json_default(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    raise TypeError(f"not JSON serialisable: {type(v).__name__}")


def canonical_json(bundle: MfgBundle) -> bytes:
    return json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                      default=_json_default).encode("utf-8")


def format_break(name: str, start: str, end: str) -> str:
    return f"{name}={start}-{end}" if name else f"{start}-{end}"


_BREAK = re.compile(r"^(?:(?P<name>[^=]*)=)?\s*(?P<s>\d{1,2}:\d{2})\s*-\s*(?P<e>\d{1,2}:\d{2})$")


def parse_break(text: str) -> dict[str, str]:
    m = _BREAK.match(text.strip())
    if not m:
        raise ValueError(f"break {text!r} is not 'HH:MM-HH:MM' or 'name=HH:MM-HH:MM'")
    return {"name": (m.group("name") or "").strip(), "start": m.group("s").zfill(5), "end": m.group("e").zfill(5)}


def parse_days(values: list[str]) -> list[str]:
    """`mon`..`sun`, ranges `mon-sat`, `daily`; returned unique in week order."""
    days: set[str] = set()
    for v in values:
        t = str(v).strip().lower()
        if t in ("daily", "all"):
            days.update(WEEKDAYS)
        elif "-" in t:
            a, b = (x.strip()[:3] for x in t.split("-", 1))
            if a not in WEEKDAYS or b not in WEEKDAYS:
                raise ValueError(f"unknown day range {v!r}")
            i, j = WEEKDAYS.index(a), WEEKDAYS.index(b)
            if j < i:
                raise ValueError(f"day range {v!r} runs backwards")
            days.update(WEEKDAYS[i:j + 1])
        elif t[:3] in WEEKDAYS and t:
            days.add(t[:3])
        else:
            raise ValueError(f"unknown day {v!r}")
    return [d for d in WEEKDAYS if d in days]


def format_tool(code: str, qty: int) -> str:
    return f"{code}:{qty}"


def parse_tool(text: str) -> tuple[str, int]:
    t = str(text).strip()
    if ":" in t:
        code, q = t.rsplit(":", 1)
        return code.strip(), int(q)
    return t, 1


def _as_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _as_datetime(v: Any, tz: Any, *, end: bool = False) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo is not None else v.replace(tzinfo=tz)
    if isinstance(v, date):
        d = v + timedelta(days=1) if end else v      # a date-only end is inclusive (end of that day)
        return datetime(d.year, d.month, d.day, tzinfo=tz)
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return _as_datetime(date.fromisoformat(s), tz, end=end)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=tz)


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _list(v: Any) -> list[str]:
    if _blank(v):
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if not _blank(x)]
    return [x.strip() for x in re.split(r"[;,|]", str(v)) if x.strip()]


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


# ---------------------------------------------------------------- dataset -> bundle


def dataset_to_bundle(ds: MfgDataset, scope: Literal["all", "master", "transactions"] = "all") -> MfgBundle:
    """Canonical bundle of a dataset. `scope="master"`: the master sheets only (M1 + locations, suppliers,
    item-suppliers; the fingerprint); `"transactions"`: the transactional sheets only (from `ds.txn`); `"all"`
    (default): every sheet (transactional sheets empty when `ds.txn` is None)."""
    if scope == "transactions":
        return transactions_to_bundle(ds)
    items = ds.items
    pn = {i: it.part_number for i, it in items.items()}
    from .calendar import offset_tz

    tz = offset_tz(ds.plant.utc_offset)
    p = ds.plant
    out: MfgBundle = {name: [] for name in MASTER_SHEETS}
    out["plant"] = [{"name": p.name, "utc_offset": p.utc_offset, "planning_horizon_days": p.planning_horizon_days,
                     "currency": p.currency}]
    for it in sorted(items.values(), key=lambda x: x.part_number):
        row = {"part_number": it.part_number, "revision": it.revision, "description": it.description,
               "uom": it.uom, "make_buy": it.make_buy, "family": it.family, "setup_family": it.setup_family,
               "lead_time_days": it.lead_time_days, "receiving_days": it.receiving_days, "lot_rule": it.lot_rule,
               "fixed_lot_qty": _f(it.fixed_lot_qty), "min_order_qty": float(it.min_order_qty),
               "order_multiple": float(it.order_multiple), "safety_stock": float(it.safety_stock),
               "serialized": it.serialized, "shelf_life_days": it.shelf_life_days,
               "handling_class": it.handling_class, "handling_note": it.handling_note, "active": it.active,
               "external_ref": it.external_ref, "standard_cost": _f(it.standard_cost),
               "lot_controlled": it.lot_controlled, "lot_period_days": it.lot_period_days}
        for k in sorted(it.attributes):
            row[ATTR_PREFIX + k] = it.attributes[k]
        out["items"].append(row)
    for s in sorted(ds.skills.values(), key=lambda x: x.code):
        out["skills"].append({"code": s.code, "name": s.name, "description": s.description})
    tools = {t.id: t.code for t in ds.tool_pools.values()}
    for t in sorted(ds.tool_pools.values(), key=lambda x: x.code):
        out["tool_pools"].append({"code": t.code, "name": t.name, "kind": t.kind, "quantity": t.quantity,
                                  "note": t.note})
    gcode = {g.id: g.code for g in ds.groups.values()}
    for g in sorted(ds.groups.values(), key=lambda x: x.code):
        out["groups"].append({"code": g.code, "name": g.name, "description": g.description, "kind": g.kind,
                              "active": g.active})
    lcode = {ln.id: ln.code for ln in ds.lines.values()}
    for ln in sorted(ds.lines.values(), key=lambda x: x.code):
        out["lines"].append({"code": ln.code, "group_code": gcode.get(ln.group_id), "name": ln.name,
                             "speed_factor": float(ln.speed_factor), "parallel_capacity": ln.parallel_capacity,
                             "setup_family": ln.setup_family, "eligible_families": sorted(ln.eligible_families),
                             "eligible_part_numbers": sorted(pn[i] for i in ln.eligible_item_ids if i in pn),
                             "cost_per_hour": float(ln.cost_per_hour), "active": ln.active})
    tcode = {t.id: t.code for t in ds.shift_templates.values()}
    for t in sorted(ds.shift_templates.values(), key=lambda x: x.code):
        out["shift_templates"].append({"code": t.code, "name": t.name, "description": t.description})
        for sh in t.shifts:
            out["shifts"].append({"template_code": t.code, "shift_name": sh.name,
                                  "days": [d for d in WEEKDAYS if d in sh.days], "start": sh.start, "end": sh.end,
                                  "breaks": [format_break(b.name, b.start, b.end) for b in sh.breaks]})
    asg = []
    for a in ds.shift_assignments.values():
        target = gcode.get(a.group_id or "") if a.target_type == "group" else lcode.get(a.line_id or "")
        asg.append({"template_code": tcode.get(a.shift_template_id), "target_type": a.target_type,
                    "target_code": target, "kind": a.kind, "effective_from": a.effective_from,
                    "effective_to": a.effective_to, "shift_names": sorted(a.shift_names),
                    "cost_per_hour": _f(a.cost_per_hour), "max_hours_per_week": _f(a.max_hours_per_week),
                    "note": a.note})
    asg.sort(key=lambda r: (r["template_code"] or "", r["target_type"], r["target_code"] or "", r["kind"],
                            r["effective_from"]))
    out["shift_assignments"] = asg
    exc = []
    for e in ds.calendar_exceptions.values():
        target = None
        if e.scope == "group":
            target = gcode.get(e.group_id or "")
        elif e.scope == "line":
            target = lcode.get(e.line_id or "")
        exc.append({"scope": e.scope, "target_code": target, "kind": e.kind, "start": e.start.astimezone(tz),
                    "end": e.end.astimezone(tz), "label": e.label})
    exc.sort(key=lambda r: (r["scope"], r["target_code"] or "", r["kind"], r["start"], r["end"]))
    out["calendar_exceptions"] = exc
    scode = {s.id: s.code for s in ds.skills.values()}
    for o in sorted(ds.operators.values(), key=lambda x: x.code):
        out["operators"].append({"code": o.code, "name": o.name,
                                 "skills": sorted(scode[s] for s in o.skill_ids if s in scode),
                                 "shift_template_code": tcode.get(o.shift_template_id or ""),
                                 "shift_names": sorted(o.shift_names),
                                 "home_group_code": gcode.get(o.home_group_id or ""), "active": o.active})
    for b in sorted(ds.boms.values(), key=lambda x: (pn.get(x.item_id, ""), x.revision, x.version)):
        ppn = pn.get(b.item_id)
        out["boms"].append({"parent_part_number": ppn, "revision": b.revision, "version": b.version,
                            "effective_from": b.effective_from, "effective_to": b.effective_to,
                            "serial_from": b.serial_from, "serial_to": b.serial_to, "note": b.note,
                            "status": b.status})
        for ln in sorted(b.lines, key=line_sort_key):
            out["bom_lines"].append({"parent_part_number": ppn, "revision": b.revision, "version": b.version,
                                     "find_number": ln.find_number, "child_part_number": pn.get(ln.child_item_id),
                                     "qty_per": float(ln.qty_per), "uom": ln.uom, "scrap_pct": float(ln.scrap_pct),
                                     "ref_designators": ln.ref_designators, "alt_group": ln.alt_group,
                                     "alt_priority": ln.alt_priority, "operation_seq": ln.operation_seq,
                                     "note": ln.note})
    for r in sorted(ds.routings.values(), key=lambda x: (pn.get(x.item_id, ""), x.revision, x.code, x.version)):
        ipn = pn.get(r.item_id)
        out["routings"].append({"part_number": ipn, "revision": r.revision, "code": r.code, "version": r.version,
                                "priority": r.priority, "effective_from": r.effective_from,
                                "effective_to": r.effective_to, "serial_from": r.serial_from,
                                "serial_to": r.serial_to, "note": r.note, "status": r.status})
        for op in sorted(r.operations, key=lambda o: o.seq):
            out["operations"].append({
                "part_number": ipn, "revision": r.revision, "code": r.code, "version": r.version, "seq": op.seq,
                "name": op.name, "group_code": gcode.get(op.group_id), "setup_minutes": float(op.setup_minutes),
                "run_minutes": float(op.run_minutes), "run_per": op.run_per, "units_per_panel": op.units_per_panel,
                "units_per_batch": op.units_per_batch, "queue_minutes": float(op.queue_minutes),
                "move_minutes": float(op.move_minutes), "wait_minutes": float(op.wait_minutes), "labor": op.labor,
                "crew_size": op.crew_size, "skill_code": scode.get(op.skill_id or ""),
                "tools": sorted(format_tool(tools.get(t.tool_pool_id, "?"), t.qty) for t in op.tools),
                "transfer_batch": op.transfer_batch, "yield_pct": float(op.yield_pct),
                "inspection_gate": op.inspection_gate, "interruptible": op.interruptible})
    for loc in sorted(ds.locations.values(), key=lambda x: x.code):
        out["locations"].append({"code": loc.code, "name": loc.name, "kind": loc.kind,
                                 "receipt_default": loc.receipt_default, "active": loc.active,
                                 "external_ref": loc.external_ref, "note": loc.note})
    supcode = {x.id: x.code for x in ds.suppliers.values()}
    for sp in sorted(ds.suppliers.values(), key=lambda x: x.code):
        out["suppliers"].append({"code": sp.code, "name": sp.name, "lead_time_days": sp.lead_time_days,
                                 "currency": sp.currency, "contact_name": sp.contact_name, "email": sp.email,
                                 "phone": sp.phone, "address": sp.address, "active": sp.active,
                                 "external_ref": sp.external_ref, "note": sp.note})
    isu = []
    for r in ds.item_suppliers.values():
        isu.append({"part_number": pn.get(r.item_id), "supplier_code": supcode.get(r.supplier_id),
                    "supplier_part_number": r.supplier_part_number, "lead_time_days": r.lead_time_days,
                    "min_order_qty": float(r.min_order_qty), "order_multiple": float(r.order_multiple),
                    "purchase_unit": r.purchase_unit, "units_per_purchase_unit": float(r.units_per_purchase_unit),
                    "unit_price": _f(r.unit_price), "currency": r.currency, "preferred": r.preferred,
                    "active": r.active, "note": r.note})
    isu.sort(key=lambda r: (r["part_number"] or "", r["supplier_code"] or ""))
    out["item_suppliers"] = isu
    if scope == "all":
        out.update(transactions_to_bundle(ds))
        out = {name: out[name] for name in SHEET_NAMES}
    return out


def _natural_fn(fn: str | None) -> tuple[int, int, str]:
    from .dataset import natural

    return natural(fn) if fn else (2, 0, "")


def transactions_to_bundle(ds: MfgDataset) -> MfgBundle:
    """The transactional sheets (M2-DESIGN 11) of `ds.txn`: stock = balances with on hand > 0 (with their lot),
    documents with their current received/shipped/completed/issued quantities. Canonical row order."""
    from .model_m2 import EPS

    out: MfgBundle = {name: [] for name in TXN_SHEETS}
    t = ds.txn
    if t is None:
        return out
    pn = {i: it.part_number for i, it in ds.items.items()}
    loc = {x.id: x.code for x in ds.locations.values()}
    sup = {x.id: x.code for x in ds.suppliers.values()}
    stock = []
    for b in t.balances.values():
        if b.qty_on_hand <= EPS:
            continue
        lot = t.lots.get(b.lot_id or "")
        stock.append({"part_number": pn.get(b.item_id), "location_code": loc.get(b.location_id),
                      "lot_code": lot.lot_code if lot else None, "qty": float(b.qty_on_hand),
                      "expires_on": lot.expires_on if lot else None, "supplier_lot": lot.supplier_lot if lot else ""})
    stock.sort(key=lambda r: (r["part_number"] or "", r["location_code"] or "", r["lot_code"] or ""))
    out["stock"] = stock
    for d in sorted(t.purchase_docs.values(), key=lambda d: (d.doc_type, d.number)):
        out["purchase_docs"].append({"doc_type": d.doc_type, "number": d.number, "status": d.status,
                                     "supplier_code": sup.get(d.supplier_id or ""), "currency": d.currency,
                                     "order_date": d.order_date, "note": d.note, "external_ref": d.external_ref})
        for ln in sorted(d.lines, key=lambda x: x.line_no):
            out["purchase_lines"].append({"doc_type": d.doc_type, "number": d.number, "line_no": ln.line_no,
                                          "part_number": pn.get(ln.item_id), "unit_price": _f(ln.unit_price),
                                          "note": ln.note})
            for sc in sorted(ln.schedules, key=lambda x: x.seq):
                out["purchase_schedules"].append({
                    "doc_type": d.doc_type, "number": d.number, "line_no": ln.line_no, "seq": sc.seq,
                    "requested_date": sc.requested_date, "confirmed_date": sc.confirmed_date, "qty": float(sc.qty),
                    "received_qty": float(sc.received_qty)})
    for o in sorted(t.demand_orders.values(), key=lambda o: o.number):
        out["demand_orders"].append({"number": o.number, "demand_type": o.demand_type, "customer": o.customer,
                                     "program": o.program, "priority": o.priority, "status": o.status,
                                     "note": o.note, "external_ref": o.external_ref})
        for ln in sorted(o.lines, key=lambda x: x.line_no):
            out["demand_lines"].append({"number": o.number, "line_no": ln.line_no, "part_number": pn.get(ln.item_id),
                                        "qty": float(ln.qty), "due_date": ln.due_date, "serial_from": ln.serial_from,
                                        "serial_to": ln.serial_to, "priority": ln.priority,
                                        "shipped_qty": float(ln.shipped_qty), "note": ln.note})
    for w in sorted(t.work_orders.values(), key=lambda w: w.number):
        out["work_orders"].append({"number": w.number, "part_number": pn.get(w.item_id), "qty": float(w.qty),
                                   "start_date": w.start_date, "due_date": w.due_date, "status": w.status,
                                   "priority": w.priority, "serial_from": w.serial_from, "serial_to": w.serial_to,
                                   "qty_completed": float(w.qty_completed), "note": w.note,
                                   "external_ref": w.external_ref})
        comps = sorted(w.components, key=lambda c: (_natural_fn(c.find_number), pn.get(c.item_id) or "", c.id))
        for c in comps:
            out["wo_components"].append({"wo_number": w.number, "part_number": pn.get(c.item_id),
                                         "find_number": c.find_number, "required_qty": float(c.required_qty),
                                         "issued_qty": float(c.issued_qty), "operation_seq": c.operation_seq,
                                         "note": c.note})
    return out


# ---------------------------------------------------------------- bundle -> dataset (strict)


@dataclass
class _Ctx:
    errors: list[str] = field(default_factory=list)

    def err(self, sheet: str, n: int, msg: str) -> None:
        self.errors.append(f"{sheet} row {n}: {msg}")


def _pyd_msg(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in e['loc']) or 'row'}: {e['msg']}" for e in exc.errors()[:3])


def _clean(row: dict[str, Any], spec: SheetSpec) -> dict[str, Any]:
    """Known columns with blanks removed (so model defaults apply); list columns as lists."""
    out: dict[str, Any] = {}
    for c in spec.columns:
        v = row.get(c.field)
        if c.type == "list":
            out[c.field] = _list(v)
        elif not _blank(v):
            out[c.field] = v.strip() if isinstance(v, str) else v
    return out


def bundle_to_dataset(bundle: MfgBundle) -> MfgDataset:
    """Strict conversion (samples, tests): any invalid row raises `BundleError`. Ids are derived from natural keys
    (`deterministic_id`) and never reach the database (the import writer always uses `new_id`)."""
    from .calendar import offset_tz

    cx = _Ctx()
    unknown = [k for k in bundle if k not in SHEETS_BY_NAME]
    if unknown:
        cx.errors.append(f"unknown sheets: {', '.join(sorted(unknown))}")
    rows = {name: list(bundle.get(name) or []) for name in SHEET_NAMES}
    for name, spec in SHEETS_BY_NAME.items():
        for n, r in enumerate(rows[name], 1):
            extra = [k for k in r if k not in spec.fields and not (spec.attr_columns and k.startswith(ATTR_PREFIX))]
            if extra:
                cx.err(name, n, f"unknown columns: {', '.join(sorted(extra))}")
    stamp = {"row_version": 1, "created_at": BUNDLE_EPOCH, "updated_at": BUNDLE_EPOCH}

    # plant
    plant_rows = rows["plant"]
    if len(plant_rows) > 1:
        cx.err("plant", 2, "the plant sheet has at most one row")
    pdata = _clean(plant_rows[0], SHEETS_BY_NAME["plant"]) if plant_rows else {}
    try:
        pin = PlantInput.model_validate(pdata)
    except ValidationError as exc:
        cx.err("plant", 1, _pyd_msg(exc))
        pin = PlantInput()
    plant = PlantRecord.model_construct(**pin.__dict__, id=deterministic_id("plt_", "plant"), row_version=1,
                                        created_at=BUNDLE_EPOCH, updated_at=BUNDLE_EPOCH, data_version=0)
    tz = offset_tz(plant.utc_offset)
    ds = MfgDataset(plant=plant)

    def keyed(sheet: str, n: int, seen: dict[Any, int], key: Any) -> bool:
        if key in seen:
            cx.err(sheet, n, f"duplicate key {key!r} (also row {seen[key]})")
            return False
        seen[key] = n
        return True

    # items
    by_pn: dict[str, ItemRecord] = {}
    seen: dict[Any, int] = {}
    for n, r in enumerate(rows["items"], 1):
        d = _clean(r, SHEETS_BY_NAME["items"])
        d["attributes"] = {k[len(ATTR_PREFIX):]: v for k, v in r.items() if k.startswith(ATTR_PREFIX) and not _blank(v)}
        try:
            inp = ItemInput.model_validate(d)
        except ValidationError as exc:
            cx.err("items", n, _pyd_msg(exc))
            continue
        if not keyed("items", n, seen, inp.part_number):
            continue
        rec = ItemRecord.model_construct(**inp.__dict__, id=deterministic_id("itm_", inp.part_number), **stamp,
                                         has_bom=False, has_routing=False, used_in_count=0)
        ds.items[rec.id] = rec
        by_pn[rec.part_number] = rec

    def simple(sheet: str, in_cls: Any, rec_cls: Any, prefix: str, target: dict[str, Any],
               extra: dict[str, Any]) -> dict[str, Any]:
        codes: dict[str, Any] = {}
        seen_: dict[Any, int] = {}
        for n, r in enumerate(rows[sheet], 1):
            try:
                inp = in_cls.model_validate(_clean(r, SHEETS_BY_NAME[sheet]))
            except ValidationError as exc:
                cx.err(sheet, n, _pyd_msg(exc))
                continue
            if not keyed(sheet, n, seen_, inp.code):
                continue
            rec = rec_cls.model_construct(**inp.__dict__, id=deterministic_id(prefix, inp.code), **stamp, **extra)
            target[rec.id] = rec
            codes[rec.code] = rec
        return codes

    skills = simple("skills", SkillInput, SkillRecord, "skl_", ds.skills, {"operator_count": 0, "operation_count": 0})
    pools = simple("tool_pools", ToolPoolInput, ToolPoolRecord, "tlp_", ds.tool_pools, {"operation_count": 0})
    groups = simple("groups", GroupInput, GroupRecord, "wcg_", ds.groups, {"line_count": 0})

    def need(table: dict[str, Any], code: Any, sheet: str, n: int, what: str) -> Any | None:
        if _blank(code):
            return None
        x = table.get(str(code).strip())
        if x is None:
            cx.err(sheet, n, f"unknown {what} {code!r}")
        return x

    # lines
    lines: dict[str, LineRecord] = {}
    seen = {}
    for n, r in enumerate(rows["lines"], 1):
        d = _clean(r, SHEETS_BY_NAME["lines"])
        g = need(groups, d.pop("group_code", None), "lines", n, "group")
        pns = d.pop("eligible_part_numbers", [])
        ids = []
        for p in pns:
            it = need(by_pn, p, "lines", n, "part number")
            if it is not None:
                ids.append(it.id)
        if g is None:
            if "group_code" not in r or _blank(r.get("group_code")):
                cx.err("lines", n, "group_code is required")
            continue
        d.update(group_id=g.id, eligible_item_ids=ids)
        try:
            inp = LineInput.model_validate(d)
        except ValidationError as exc:
            cx.err("lines", n, _pyd_msg(exc))
            continue
        if not keyed("lines", n, seen, inp.code):
            continue
        rec = LineRecord.model_construct(**inp.__dict__, id=deterministic_id("lin_", inp.code), **stamp,
                                         eligible_items=[])
        ds.lines[rec.id] = rec
        lines[rec.code] = rec

    # shift templates + shifts
    shifts_of: dict[str, list[dict[str, Any]]] = {}
    seen = {}
    for n, r in enumerate(rows["shifts"], 1):
        d = _clean(r, SHEETS_BY_NAME["shifts"])
        tc = d.get("template_code")
        if not keyed("shifts", n, seen, (tc, d.get("shift_name"))):
            continue
        try:
            sd = {"name": d.get("shift_name"), "days": parse_days(d.get("days", [])), "start": d.get("start"),
                  "end": d.get("end"), "breaks": [parse_break(b) for b in d.get("breaks", [])]}
        except ValueError as exc:
            cx.err("shifts", n, str(exc))
            continue
        shifts_of.setdefault(str(tc), []).append(sd)
    templates: dict[str, ShiftTemplateRecord] = {}
    seen = {}
    for n, r in enumerate(rows["shift_templates"], 1):
        d = _clean(r, SHEETS_BY_NAME["shift_templates"])
        d["shifts"] = shifts_of.pop(str(d.get("code")), [])
        try:
            inp = ShiftTemplateInput.model_validate(d)
        except ValidationError as exc:
            cx.err("shift_templates", n, _pyd_msg(exc))
            continue
        if not keyed("shift_templates", n, seen, inp.code):
            continue
        from .calendar import validate_template

        for e in validate_template(inp):
            cx.err("shift_templates", n, e["msg"])
        rec = ShiftTemplateRecord.model_construct(**inp.__dict__, id=deterministic_id("sht_", inp.code), **stamp,
                                                  assignment_count=0, operator_count=0)
        ds.shift_templates[rec.id] = rec
        templates[rec.code] = rec
    for tc in shifts_of:
        cx.errors.append(f"shifts: unknown template {tc!r}")

    # assignments
    seen = {}
    for n, r in enumerate(rows["shift_assignments"], 1):
        d = _clean(r, SHEETS_BY_NAME["shift_assignments"])
        t = need(templates, d.pop("template_code", None), "shift_assignments", n, "shift template")
        tt = d.get("target_type")
        code = d.pop("target_code", None)
        tgt = need(groups if tt == "group" else lines, code, "shift_assignments", n, f"{tt}")
        if t is None or tgt is None:
            continue
        d["shift_template_id"] = t.id
        d["group_id" if tt == "group" else "line_id"] = tgt.id
        if "effective_from" in d:
            d["effective_from"] = _as_date(d["effective_from"])
        if "effective_to" in d:
            d["effective_to"] = _as_date(d["effective_to"])
        try:
            inp = ShiftAssignmentInput.model_validate(d)
        except ValidationError as exc:
            cx.err("shift_assignments", n, _pyd_msg(exc))
            continue
        bad = [s for s in inp.shift_names if s not in {sh.name for sh in t.shifts}]
        if bad:
            cx.err("shift_assignments", n, f"unknown shift names {bad}")
        key = (t.code, tt, tgt.code, inp.kind, inp.effective_from)
        if not keyed("shift_assignments", n, seen, key):
            continue
        rec = ShiftAssignmentRecord.model_construct(**inp.__dict__, id=deterministic_id("sha_", *key), **stamp)
        ds.shift_assignments[rec.id] = rec

    # calendar exceptions
    seen = {}
    for n, r in enumerate(rows["calendar_exceptions"], 1):
        d = _clean(r, SHEETS_BY_NAME["calendar_exceptions"])
        scope = d.get("scope")
        code = d.pop("target_code", None)
        if scope in ("group", "line"):
            tgt = need(groups if scope == "group" else lines, code, "calendar_exceptions", n, scope)
            if tgt is None:
                if _blank(code):
                    cx.err("calendar_exceptions", n, "target_code is required for this scope")
                continue
            d["group_id" if scope == "group" else "line_id"] = tgt.id
        elif not _blank(code):
            cx.err("calendar_exceptions", n, "a plant exception has no target_code")
            continue
        try:
            d["start"] = _as_datetime(d["start"], tz).astimezone(tz)
            d["end"] = _as_datetime(d["end"], tz, end=True).astimezone(tz)
            inp = CalendarExceptionInput.model_validate(d)
        except (KeyError, ValueError) as exc:
            cx.err("calendar_exceptions", n, _pyd_msg(exc) if isinstance(exc, ValidationError) else str(exc))
            continue
        key = (scope, code, inp.kind, inp.start.isoformat())
        if not keyed("calendar_exceptions", n, seen, key):
            continue
        rec = CalendarExceptionRecord.model_construct(**inp.__dict__, id=deterministic_id("cex_", *key), **stamp)
        ds.calendar_exceptions[rec.id] = rec

    # operators
    seen = {}
    for n, r in enumerate(rows["operators"], 1):
        d = _clean(r, SHEETS_BY_NAME["operators"])
        sk = [need(skills, s, "operators", n, "skill") for s in d.pop("skills", [])]
        t = need(templates, d.pop("shift_template_code", None), "operators", n, "shift template")
        hg = need(groups, d.pop("home_group_code", None), "operators", n, "group")
        d.update(skill_ids=[s.id for s in sk if s is not None], shift_template_id=t.id if t else None,
                 home_group_id=hg.id if hg else None)
        try:
            inp = OperatorInput.model_validate(d)
        except ValidationError as exc:
            cx.err("operators", n, _pyd_msg(exc))
            continue
        if t is not None:
            bad = [s for s in inp.shift_names if s not in {sh.name for sh in t.shifts}]
            if bad:
                cx.err("operators", n, f"unknown shift names {bad}")
        if not keyed("operators", n, seen, inp.code):
            continue
        rec = OperatorRecord.model_construct(**inp.__dict__, id=deterministic_id("emp_", inp.code), **stamp)
        ds.operators[rec.id] = rec

    _documents(rows, ds, by_pn, groups, skills, pools, cx, stamp)
    _m2_master(rows, ds, by_pn, cx, stamp)
    if not cx.errors:
        link(ds)
        _m2_transactions(rows, ds, by_pn, cx)
    if cx.errors:
        raise BundleError(cx.errors)
    return link(ds)


def _documents(rows: dict[str, list[dict[str, Any]]], ds: MfgDataset, by_pn: dict[str, ItemRecord],
               groups: dict[str, Any], skills: dict[str, Any], pools: dict[str, Any], cx: _Ctx,
               stamp: dict[str, Any]) -> None:
    def doc_key(sheet: str, n: int, d: dict[str, Any], pn_field: str, with_code: bool) -> tuple[Any, ...] | None:
        it = by_pn.get(str(d.get(pn_field, "")).strip())
        if it is None:
            cx.err(sheet, n, f"unknown part number {d.get(pn_field)!r}")
            return None
        rev = d.get("revision") or it.revision
        ver = int(d.get("version") or 1)
        if with_code:
            return (it.part_number, str(rev), str(d.get("code") or "STD"), ver)
        return (it.part_number, str(rev), ver)

    def header(sheet: str, n: int, d: dict[str, Any]) -> dict[str, Any]:
        h = {k: d[k] for k in ("effective_from", "effective_to", "serial_from", "serial_to", "note") if k in d}
        for k in ("effective_from", "effective_to"):
            if k in h:
                h[k] = _as_date(h[k])
        return h

    # BOMs
    heads: dict[tuple[Any, ...], tuple[int, dict[str, Any]]] = {}
    for n, r in enumerate(rows["boms"], 1):
        d = _clean(r, SHEETS_BY_NAME["boms"])
        k = doc_key("boms", n, d, "parent_part_number", False)
        if k is None:
            continue
        if k in heads:
            cx.err("boms", n, f"duplicate key {k!r} (also row {heads[k][0]})")
            continue
        heads[k] = (n, d)
    lines_of: dict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]] = {}
    for n, r in enumerate(rows["bom_lines"], 1):
        d = _clean(r, SHEETS_BY_NAME["bom_lines"])
        k = doc_key("bom_lines", n, d, "parent_part_number", False)
        if k is None:
            continue
        lines_of.setdefault(k, []).append((n, d))
        heads.setdefault(k, (0, {}))
    for k, (n, d) in heads.items():
        item = by_pn[k[0]]
        status = d.get("status", "draft")
        if status not in ("draft", "released", "obsolete"):
            cx.err("boms", n, f"unknown status {status!r}")
            continue
        blines: list[dict[str, Any]] = []
        auto = 0
        seen_l: dict[Any, int] = {}
        for ln_n, ld in lines_of.get(k, []):
            child = by_pn.get(str(ld.get("child_part_number", "")).strip())
            if child is None:
                cx.err("bom_lines", ln_n, f"unknown part number {ld.get('child_part_number')!r}")
                continue
            auto += 10
            fn = str(ld.get("find_number") or auto)
            lk = (fn, child.part_number)
            if lk in seen_l:
                cx.err("bom_lines", ln_n, f"duplicate line {lk!r} (also row {seen_l[lk]})")
                continue
            seen_l[lk] = ln_n
            row = {f: ld[f] for f in ("qty_per", "uom", "scrap_pct", "ref_designators", "alt_group", "alt_priority",
                                      "operation_seq", "note") if f in ld}
            row.setdefault("uom", child.uom)
            row.update(find_number=fn, child_item_id=child.id,
                       id=deterministic_id("bml_", *k, fn, child.part_number))
            blines.append(row)
        try:
            inp = BomInput.model_validate({"item_id": item.id, "revision": k[1], "version": k[2],
                                           **header("boms", n, d), "lines": blines})
        except ValidationError as exc:
            cx.err("boms", n or (lines_of.get(k) or [(0, None)])[0][0], _pyd_msg(exc))
            continue
        lines = [BomLineRecord.model_construct(**ln.__dict__) for ln in inp.lines]
        data = {**inp.__dict__, "lines": lines}
        rec = BomRecord.model_construct(**data, id=deterministic_id("bom_", *k), status=status,
                                        released_at=BUNDLE_EPOCH if status != "draft" else None,
                                        obsoleted_at=BUNDLE_EPOCH if status == "obsolete" else None, **stamp)
        ds.boms[rec.id] = rec

    # routings
    rheads: dict[tuple[Any, ...], tuple[int, dict[str, Any]]] = {}
    for n, r in enumerate(rows["routings"], 1):
        d = _clean(r, SHEETS_BY_NAME["routings"])
        k = doc_key("routings", n, d, "part_number", True)
        if k is None:
            continue
        if k in rheads:
            cx.err("routings", n, f"duplicate key {k!r} (also row {rheads[k][0]})")
            continue
        rheads[k] = (n, d)
    ops_of: dict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]] = {}
    for n, r in enumerate(rows["operations"], 1):
        d = _clean(r, SHEETS_BY_NAME["operations"])
        k = doc_key("operations", n, d, "part_number", True)
        if k is None:
            continue
        ops_of.setdefault(k, []).append((n, d))
        rheads.setdefault(k, (0, {}))
    for k, (n, d) in rheads.items():
        item = by_pn[k[0]]
        status = d.get("status", "draft")
        if status not in ("draft", "released", "obsolete"):
            cx.err("routings", n, f"unknown status {status!r}")
            continue
        ops: list[dict[str, Any]] = []
        seen_o: dict[Any, int] = {}
        for op_n, od in ops_of.get(k, []):
            g = groups.get(str(od.get("group_code", "")).strip())
            if g is None:
                cx.err("operations", op_n, f"unknown group {od.get('group_code')!r}")
                continue
            sk = None
            if not _blank(od.get("skill_code")):
                sk = skills.get(str(od["skill_code"]).strip())
                if sk is None:
                    cx.err("operations", op_n, f"unknown skill {od.get('skill_code')!r}")
                    continue
            tools = []
            for t in od.get("tools", []):
                code, q = parse_tool(t)
                tp = pools.get(code)
                if tp is None:
                    cx.err("operations", op_n, f"unknown tool pool {code!r}")
                    continue
                tools.append({"tool_pool_id": tp.id, "qty": q})
            seq = od.get("seq")
            if seq in seen_o:
                cx.err("operations", op_n, f"duplicate seq {seq} (also row {seen_o[seq]})")
                continue
            seen_o[seq] = op_n
            row = {f: od[f] for f in OperationInput.model_fields if f in od and f not in ("tools",)}
            row.update(group_id=g.id, skill_id=sk.id if sk else None, tools=tools,
                       id=deterministic_id("opr_", *k, seq))
            ops.append(row)
        hd = header("routings", n, d)
        if "priority" in d:
            hd["priority"] = d["priority"]
        try:
            inp = RoutingInput.model_validate({"item_id": item.id, "revision": k[1], "code": k[2], "version": k[3],
                                               **hd, "operations": ops})
        except ValidationError as exc:
            cx.err("routings", n or (ops_of.get(k) or [(0, None)])[0][0], _pyd_msg(exc))
            continue
        orecs = []
        for o in inp.operations:
            od = dict(o.__dict__)
            od["tools"] = [OperationToolRecord.model_construct(**t.__dict__) for t in o.tools]
            orecs.append(OperationRecord.model_construct(**od))
        rec = RoutingRecord.model_construct(**{**inp.__dict__, "operations": orecs}, id=deterministic_id("rtg_", *k),
                                            status=status, released_at=BUNDLE_EPOCH if status != "draft" else None,
                                            obsoleted_at=BUNDLE_EPOCH if status == "obsolete" else None, **stamp)
        ds.routings[rec.id] = rec


def bundle_counts(bundle: MfgBundle) -> dict[str, int]:
    return {name: len(bundle.get(name) or []) for name in SHEET_NAMES}


# ---------------------------------------------------------------- M2 sheets (strict)


def _m2_master(rows: dict[str, list[dict[str, Any]]], ds: MfgDataset, by_pn: dict[str, ItemRecord], cx: _Ctx,
               stamp: dict[str, Any]) -> None:
    from .model_m2 import (ItemSupplierInput, ItemSupplierRecord, LocationInput, LocationRecord, SupplierInput,
                           SupplierRecord)

    for sheet, in_cls, rec_cls, prefix, target, extra in (
            ("locations", LocationInput, LocationRecord, "loc_", ds.locations, {}),
            ("suppliers", SupplierInput, SupplierRecord, "sup_", ds.suppliers, {"item_count": 0})):
        seen: dict[Any, int] = {}
        for n, r in enumerate(rows[sheet], 1):
            try:
                inp = in_cls.model_validate(_clean(r, SHEETS_BY_NAME[sheet]))
            except ValidationError as exc:
                cx.err(sheet, n, _pyd_msg(exc))
                continue
            if inp.code in seen:
                cx.err(sheet, n, f"duplicate key {inp.code!r} (also row {seen[inp.code]})")
                continue
            seen[inp.code] = n
            rec = rec_cls.model_construct(**inp.__dict__, id=deterministic_id(prefix, inp.code), **stamp, **extra)
            target[rec.id] = rec
    defaults = [x.code for x in ds.locations.values() if x.receipt_default and x.active]
    if len(defaults) > 1:
        cx.errors.append(f"locations: more than one active receipt-default location ({', '.join(sorted(defaults))})")
    sup_by_code = {x.code: x for x in ds.suppliers.values()}
    seen2: dict[Any, int] = {}
    preferred: dict[str, int] = {}
    for n, r in enumerate(rows["item_suppliers"], 1):
        d = _clean(r, SHEETS_BY_NAME["item_suppliers"])
        it = by_pn.get(str(d.pop("part_number", "")).strip())
        sp = sup_by_code.get(str(d.pop("supplier_code", "")).strip())
        if it is None or sp is None:
            cx.err("item_suppliers", n, f"unknown {'part number' if it is None else 'supplier'} "
                   f"{r.get('part_number') if it is None else r.get('supplier_code')!r}")
            continue
        if it.make_buy != "buy":
            cx.err("item_suppliers", n, f"{it.part_number} is not a buy item")
            continue
        d.update(item_id=it.id, supplier_id=sp.id)
        try:
            inp = ItemSupplierInput.model_validate(d)
        except ValidationError as exc:
            cx.err("item_suppliers", n, _pyd_msg(exc))
            continue
        key = (it.part_number, sp.code)
        if key in seen2:
            cx.err("item_suppliers", n, f"duplicate key {key!r} (also row {seen2[key]})")
            continue
        seen2[key] = n
        if inp.preferred:
            preferred[it.id] = preferred.get(it.id, 0) + 1
            if preferred[it.id] > 1:
                cx.err("item_suppliers", n, f"{it.part_number} has more than one preferred supplier")
        from .units import is_count

        if is_count(it.uom) and float(inp.units_per_purchase_unit) != int(inp.units_per_purchase_unit):
            cx.err("item_suppliers", n, "units_per_purchase_unit must be a whole number for count items")
        rec = ItemSupplierRecord.model_construct(**inp.__dict__, id=deterministic_id("isu_", *key), **stamp,
                                                 item=None, supplier=None)
        ds.item_suppliers[rec.id] = rec


def _m2_transactions(rows: dict[str, list[dict[str, Any]]], ds: MfgDataset, by_pn: dict[str, ItemRecord],
                     cx: _Ctx) -> None:
    """Strict conversion of the transactional sheets into `ds.txn` (deterministic ids). Missing WO start dates
    and components are derived with `workorders` (7.2 / 8.5)."""
    from .dataset import (TxnBalance, TxnData, TxnDemandLine, TxnDemandOrder, TxnLot, TxnPurchaseDoc,
                          TxnPurchaseLine, TxnSchedule, TxnWoComponent, TxnWorkOrder)
    from .model_m2 import EPS
    from .units import is_count

    t = TxnData()
    ds.txn = t
    locs = {x.code: x for x in ds.locations.values()}
    sups = {x.code: x for x in ds.suppliers.values()}

    def item(sheet: str, n: int, v: Any) -> ItemRecord | None:
        it = by_pn.get(str(v or "").strip())
        if it is None:
            cx.err(sheet, n, f"unknown part number {v!r}")
        return it

    def num(sheet: str, n: int, v: Any, what: str, *, integer: bool = False, default: Any = None) -> Any:
        if _blank(v):
            return default
        try:
            x = float(v)
        except (TypeError, ValueError):
            cx.err(sheet, n, f"{what}: not a number ({v!r})")
            return default
        if integer:
            if x != int(x):
                cx.err(sheet, n, f"{what}: must be a whole number")
            return int(x)
        return x

    def whole(sheet: str, n: int, it: ItemRecord, q: float | None, what: str) -> None:
        if q is not None and is_count(it.uom) and abs(q - round(q)) > EPS:
            cx.err(sheet, n, f"{what}: {it.part_number} is counted in {it.uom}; use whole numbers")

    def day(sheet: str, n: int, v: Any, what: str, required: bool = False) -> date | None:
        try:
            d = _as_date(v)
        except ValueError:
            cx.err(sheet, n, f"{what}: not a date ({v!r})")
            return None
        if d is None and required:
            cx.err(sheet, n, f"{what} is required")
        return d

    # stock
    seen: dict[Any, int] = {}
    for n, r in enumerate(rows["stock"], 1):
        it = item("stock", n, r.get("part_number"))
        loc = locs.get(str(r.get("location_code") or "").strip())
        if loc is None:
            cx.err("stock", n, f"unknown location {r.get('location_code')!r}")
        if it is None or loc is None:
            continue
        lot_code = None if _blank(r.get("lot_code")) else str(r["lot_code"]).strip()
        key = (it.part_number, loc.code, lot_code or "")
        if key in seen:
            cx.err("stock", n, f"duplicate key {key!r} (also row {seen[key]})")
            continue
        seen[key] = n
        qty = num("stock", n, r.get("qty"), "qty")
        if qty is None or qty < 0:
            cx.err("stock", n, "qty must be 0 or more")
            continue
        whole("stock", n, it, qty, "qty")
        if it.lot_controlled and lot_code is None:
            cx.err("stock", n, f"{it.part_number} is lot-controlled: lot_code is required")
            continue
        if not it.lot_controlled and lot_code is not None:
            cx.err("stock", n, f"{it.part_number} is not lot-controlled: no lot_code allowed")
            continue
        lot_id = None
        if lot_code is not None:
            lot_id = deterministic_id("lot_", it.part_number, lot_code)
            exp = day("stock", n, r.get("expires_on"), "expires_on")
            lot = t.lots.get(lot_id)
            if lot is None:
                t.lots[lot_id] = TxnLot(lot_id, it.id, lot_code, exp, None, str(r.get("supplier_lot") or ""))
            elif lot.expires_on != exp:
                cx.err("stock", n, f"lot {lot_code} of {it.part_number} has two different expiry dates")
        bid = deterministic_id("bal_", *key)
        t.balances[bid] = TxnBalance(bid, it.id, loc.id, lot_id, lot_code or "", qty)

    # purchase documents
    heads: dict[tuple[str, str], TxnPurchaseDoc] = {}
    allowed = {"pr": ("draft", "submitted", "approved", "rejected", "ordered", "cancelled"),
               "po": ("draft", "open", "partially_received", "received", "closed", "cancelled")}
    for n, r in enumerate(rows["purchase_docs"], 1):
        dt, no = str(r.get("doc_type") or "").strip(), str(r.get("number") or "").strip()
        if dt not in allowed or not no:
            cx.err("purchase_docs", n, "doc_type (pr/po) and number are required")
            continue
        if (dt, no) in heads:
            cx.err("purchase_docs", n, f"duplicate key {(dt, no)!r}")
            continue
        status = str(r.get("status") or "draft")
        if status not in allowed[dt]:
            cx.err("purchase_docs", n, f"status {status!r} is not a {dt.upper()} status")
            continue
        sp = None
        if not _blank(r.get("supplier_code")):
            sp = sups.get(str(r["supplier_code"]).strip())
            if sp is None:
                cx.err("purchase_docs", n, f"unknown supplier {r.get('supplier_code')!r}")
                continue
        if dt == "po" and sp is None:
            cx.err("purchase_docs", n, "a purchase order needs a supplier (PUR_SUPPLIER_REQUIRED)")
            continue
        heads[(dt, no)] = TxnPurchaseDoc(
            deterministic_id("pdc_", dt, no), dt, no, status, sp.id if sp else None,
            str(r.get("currency") if not _blank(r.get("currency")) else (sp.currency if sp else "")),
            day("purchase_docs", n, r.get("order_date"), "order_date"), str(r.get("note") or ""), "import", None,
            None if _blank(r.get("external_ref")) else str(r["external_ref"]).strip())
    plines: dict[tuple[str, str, int], TxnPurchaseLine] = {}
    for n, r in enumerate(rows["purchase_lines"], 1):
        dt, no = str(r.get("doc_type") or "").strip(), str(r.get("number") or "").strip()
        d = heads.get((dt, no))
        if d is None:
            cx.err("purchase_lines", n, f"unknown document {dt} {no!r}")
            continue
        it = item("purchase_lines", n, r.get("part_number"))
        ln_no = num("purchase_lines", n, r.get("line_no"), "line_no", integer=True)
        if it is None or ln_no is None:
            continue
        if it.make_buy != "buy":
            cx.err("purchase_lines", n, f"{it.part_number} is not a buy item (MFG_ITEM_NOT_BUY)")
            continue
        if (dt, no, ln_no) in plines:
            cx.err("purchase_lines", n, f"duplicate line {ln_no}")
            continue
        status = {"cancelled": "cancelled", "ordered": "converted", "closed": "closed"}.get(d.status, "open")
        ln = TxnPurchaseLine(deterministic_id("pln_", dt, no, ln_no), ln_no, it.id,
                             num("purchase_lines", n, r.get("unit_price"), "unit_price"), status,
                             str(r.get("note") or ""))
        d.lines.append(ln)
        plines[(dt, no, ln_no)] = ln
    for n, r in enumerate(rows["purchase_schedules"], 1):
        dt, no = str(r.get("doc_type") or "").strip(), str(r.get("number") or "").strip()
        ln_no = num("purchase_schedules", n, r.get("line_no"), "line_no", integer=True)
        seq = num("purchase_schedules", n, r.get("seq"), "seq", integer=True)
        ln = plines.get((dt, no, ln_no))
        if ln is None or seq is None:
            cx.err("purchase_schedules", n, f"unknown line {dt} {no!r} / {ln_no}")
            continue
        if any(x.seq == seq for x in ln.schedules):
            cx.err("purchase_schedules", n, f"duplicate schedule {seq}")
            continue
        qty = num("purchase_schedules", n, r.get("qty"), "qty")
        rec = num("purchase_schedules", n, r.get("received_qty"), "received_qty", default=0.0)
        req = day("purchase_schedules", n, r.get("requested_date"), "requested_date", required=True)
        if qty is None or qty <= 0 or rec < 0 or req is None:
            cx.err("purchase_schedules", n, "qty must be > 0, received_qty >= 0 and requested_date set")
            continue
        it = ds.items[ln.item_id]
        whole("purchase_schedules", n, it, qty, "qty")
        whole("purchase_schedules", n, it, rec, "received_qty")
        d = heads[(dt, no)]
        ln.schedules.append(TxnSchedule(deterministic_id("psc_", dt, no, ln_no, seq), seq, req,
                                        day("purchase_schedules", n, r.get("confirmed_date"), "confirmed_date"),
                                        qty, rec, d.status in ("closed", "cancelled")))
    for d in heads.values():
        for ln in d.lines:
            if not ln.schedules:
                cx.errors.append(f"purchase_lines: {d.number} line {ln.line_no} has no schedules")
        t.purchase_docs[d.id] = d

    # demand orders
    orders: dict[str, TxnDemandOrder] = {}
    for n, r in enumerate(rows["demand_orders"], 1):
        no = str(r.get("number") or "").strip()
        if not no or no in orders:
            cx.err("demand_orders", n, f"number missing or duplicate ({no!r})")
            continue
        dtyp = str(r.get("demand_type") or "")
        status = str(r.get("status") or "draft")
        prio = num("demand_orders", n, r.get("priority"), "priority", integer=True, default=5)
        if dtyp not in ("customer", "internal", "spares", "project") or \
                status not in ("draft", "open", "closed", "cancelled") or not 1 <= prio <= 9:
            cx.err("demand_orders", n, "invalid demand_type, status or priority")
            continue
        orders[no] = TxnDemandOrder(deterministic_id("dmo_", no), no, dtyp, status, str(r.get("customer") or ""),
                                    None if _blank(r.get("program")) else str(r["program"]).strip(), prio,
                                    str(r.get("note") or ""),
                                    None if _blank(r.get("external_ref")) else str(r["external_ref"]).strip())
    for n, r in enumerate(rows["demand_lines"], 1):
        o = orders.get(str(r.get("number") or "").strip())
        if o is None:
            cx.err("demand_lines", n, f"unknown demand order {r.get('number')!r}")
            continue
        it = item("demand_lines", n, r.get("part_number"))
        ln_no = num("demand_lines", n, r.get("line_no"), "line_no", integer=True)
        if it is None or ln_no is None:
            continue
        if not it.active or it.make_buy == "phantom":
            cx.err("demand_lines", n, f"{it.part_number} cannot be planned (DEM_ITEM_NOT_PLANNABLE)")
            continue
        if any(x.line_no == ln_no for x in o.lines):
            cx.err("demand_lines", n, f"duplicate line {ln_no}")
            continue
        qty = num("demand_lines", n, r.get("qty"), "qty")
        due = day("demand_lines", n, r.get("due_date"), "due_date", required=True)
        shipped = num("demand_lines", n, r.get("shipped_qty"), "shipped_qty", default=0.0)
        sf = num("demand_lines", n, r.get("serial_from"), "serial_from", integer=True)
        st = num("demand_lines", n, r.get("serial_to"), "serial_to", integer=True)
        prio = num("demand_lines", n, r.get("priority"), "priority", integer=True)
        if qty is None or qty <= 0 or due is None or shipped < 0 or shipped > qty + EPS:
            cx.err("demand_lines", n, "qty must be > 0, due_date set and 0 <= shipped_qty <= qty")
            continue
        whole("demand_lines", n, it, qty, "qty")
        err = _serial_error(it, qty, sf, st)
        if err:
            cx.err("demand_lines", n, err)
            continue
        o.lines.append(TxnDemandLine(deterministic_id("dml_", o.number, ln_no), ln_no, it.id, qty, due, shipped, sf,
                                     st, prio, str(r.get("note") or "")))
    for o in orders.values():
        if not o.lines:
            cx.errors.append(f"demand_orders: {o.number} has no lines")
        t.demand_orders[o.id] = o

    # work orders
    from .workdays import WorkCalendar
    from . import workorders as W

    cal = WorkCalendar(ds.plant.mrp_workdays, W.plant_holidays(ds))
    wos: dict[str, TxnWorkOrder] = {}
    for n, r in enumerate(rows["work_orders"], 1):
        no = str(r.get("number") or "").strip()
        if not no or no in wos:
            cx.err("work_orders", n, f"number missing or duplicate ({no!r})")
            continue
        it = item("work_orders", n, r.get("part_number"))
        if it is None:
            continue
        if it.make_buy != "make":
            cx.err("work_orders", n, f"{it.part_number} is not a make item (MFG_ITEM_NOT_MAKE)")
            continue
        qty = num("work_orders", n, r.get("qty"), "qty")
        due = day("work_orders", n, r.get("due_date"), "due_date", required=True)
        status = str(r.get("status") or "planned")
        done = num("work_orders", n, r.get("qty_completed"), "qty_completed", default=0.0)
        prio = num("work_orders", n, r.get("priority"), "priority", integer=True, default=5)
        sf = num("work_orders", n, r.get("serial_from"), "serial_from", integer=True)
        st = num("work_orders", n, r.get("serial_to"), "serial_to", integer=True)
        if qty is None or qty <= 0 or due is None or status not in W.WO_STATUSES or done < 0 or not 1 <= prio <= 9:
            cx.err("work_orders", n, "invalid qty, due_date, status, priority or qty_completed")
            continue
        whole("work_orders", n, it, qty, "qty")
        err = _serial_error(it, qty, sf, st)
        if err:
            cx.err("work_orders", n, err)
            continue
        start = day("work_orders", n, r.get("start_date"), "start_date")
        if start is None:
            start = W.default_start_date(ds, it.id, qty, due, cal, on=due, serial=sf)
        if start > due:
            cx.err("work_orders", n, "start_date must not be after due_date")
            continue
        wid = deterministic_id("wko_", no)
        wos[no] = TxnWorkOrder(wid, no, it.id, qty, start, due, status, done, 0.0, prio, sf, st,
                               note=str(r.get("note") or ""),
                               external_ref=None if _blank(r.get("external_ref")) else str(r["external_ref"]).strip())
    comp_rows: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for n, r in enumerate(rows["wo_components"], 1):
        no = str(r.get("wo_number") or "").strip()
        if no not in wos:
            cx.err("wo_components", n, f"unknown work order {no!r}")
            continue
        comp_rows.setdefault(no, []).append((n, r))
    for no, w in wos.items():
        expl = W.generate_components(ds, w.item_id, w.qty, on=w.start_date, serial=w.serial_from)
        w.bom_id, w.routing_id = expl.bom_id, expl.routing_id
        if no not in comp_rows:
            for i, c in enumerate(expl.components, 1):
                w.components.append(TxnWoComponent(deterministic_id("woc_", no, i, c.item_id), c.item_id, c.qty, 0.0,
                                                   c.operation_seq, c.find_number, c.alt_group, c.bom_line_id))
        else:
            seen_c: dict[Any, int] = {}
            for i, (n, r) in enumerate(comp_rows[no], 1):
                it = item("wo_components", n, r.get("part_number"))
                if it is None:
                    continue
                if it.make_buy == "phantom":
                    cx.err("wo_components", n, f"{it.part_number} is a phantom; list its components instead")
                    continue
                fn = None if _blank(r.get("find_number")) else str(r["find_number"]).strip()
                k = (it.part_number, fn)
                if k in seen_c:
                    cx.err("wo_components", n, f"duplicate component {k!r} (also row {seen_c[k]})")
                    continue
                seen_c[k] = n
                req = num("wo_components", n, r.get("required_qty"), "required_qty")
                iss = num("wo_components", n, r.get("issued_qty"), "issued_qty", default=0.0)
                if req is None or req < 0 or iss < 0:
                    cx.err("wo_components", n, "required_qty and issued_qty must be 0 or more")
                    continue
                whole("wo_components", n, it, req, "required_qty")
                whole("wo_components", n, it, iss, "issued_qty")
                match = next((c for c in expl.components if c.item_id == it.id and c.find_number == fn), None)
                w.components.append(TxnWoComponent(
                    deterministic_id("woc_", no, it.part_number, fn or ""), it.id, req, iss,
                    num("wo_components", n, r.get("operation_seq"), "operation_seq", integer=True),
                    fn, match.alt_group if match else None, match.bom_line_id if match else None,
                    str(r.get("note") or "")))
        t.work_orders[w.id] = w


def _serial_error(it: ItemRecord, qty: float, sf: int | None, st: int | None) -> str | None:
    if (sf is None) != (st is None):
        return "serial_from and serial_to must both be set or both be empty"
    if sf is None:
        return None
    if not it.serialized:
        return f"{it.part_number} is not serialized, so it cannot have a serial range (MFG_SERIAL_NOT_ALLOWED)"
    if st < sf or st - sf + 1 != round(qty):
        return f"the serial range {sf}-{st} must hold exactly {qty:g} units (DEM_SERIAL_QTY_MISMATCH)"
    return None
