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
        _c("lead_time_days", "int"), _c("receiving_days", "int"), _c("lot_rule", enum=("lot_for_lot", "fixed")),
        _c("fixed_lot_qty", "float"), _c("min_order_qty", "float"), _c("order_multiple", "float"),
        _c("safety_stock", "float"), _c("serialized", "bool"), _c("shelf_life_days", "int"),
        _c("handling_class"), _c("handling_note"), _c("active", "bool")), attr_columns=True),
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
)
SHEET_NAMES: tuple[str, ...] = tuple(s.name for s in SHEETS)
SHEETS_BY_NAME: dict[str, SheetSpec] = {s.name: s for s in SHEETS}


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


def dataset_to_bundle(ds: MfgDataset) -> MfgBundle:
    items = ds.items
    pn = {i: it.part_number for i, it in items.items()}
    from .calendar import offset_tz

    tz = offset_tz(ds.plant.utc_offset)
    p = ds.plant
    out: MfgBundle = {name: [] for name in SHEET_NAMES}
    out["plant"] = [{"name": p.name, "utc_offset": p.utc_offset, "planning_horizon_days": p.planning_horizon_days,
                     "currency": p.currency}]
    for it in sorted(items.values(), key=lambda x: x.part_number):
        row = {"part_number": it.part_number, "revision": it.revision, "description": it.description,
               "uom": it.uom, "make_buy": it.make_buy, "family": it.family, "setup_family": it.setup_family,
               "lead_time_days": it.lead_time_days, "receiving_days": it.receiving_days, "lot_rule": it.lot_rule,
               "fixed_lot_qty": _f(it.fixed_lot_qty), "min_order_qty": float(it.min_order_qty),
               "order_multiple": float(it.order_multiple), "safety_stock": float(it.safety_stock),
               "serialized": it.serialized, "shelf_life_days": it.shelf_life_days,
               "handling_class": it.handling_class, "handling_note": it.handling_note, "active": it.active}
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
