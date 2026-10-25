"""Import template spec (M1-DESIGN 8.2): header synonyms and cell parsers per column type (uses `bundle.SHEETS`).

Staged cells are JSON scalars (`str`, `int`, `float`, `bool`, `None`); Excel dates are staged as `YYYY-MM-DD`
(midnight) or `YYYY-MM-DD HH:MM:SS`. `parse_cell` turns one staged cell into the bundle value of its column or
raises `CellError(code, message)`.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from ..bundle import ATTR_PREFIX, SHEETS, SHEETS_BY_NAME, ColumnSpec, SheetSpec
from ..units import normalize_uom
from . import messages as msg

#: field -> header synonyms (normalised with `normalize_header`). Applies to every sheet that has the field.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "part_number": ("part_no", "part", "part_number", "pn", "p_n", "item", "item_code", "item_number", "material",
                    "material_number", "material_code", "article", "sku"),
    "parent_part_number": ("parent", "assembly", "parent_part", "parent_item", "assembly_part_number",
                           "parent_pn", "assy"),
    "child_part_number": ("component", "child", "component_part", "component_part_number", "child_part",
                          "component_pn", "child_pn", "component_item", "comp"),
    "qty_per": ("qty", "quantity", "qty_per", "quantity_per", "usage", "qty_per_assembly", "qty_per_assy",
                "quantity_per_assembly", "per"),
    "ref_designators": ("ref_des", "reference", "designators", "refdes", "reference_designators", "references",
                        "ref", "ref_designator", "designator"),
    "find_number": ("find_no", "item_no", "pos", "position", "find", "line_no", "find_num", "item_number_bom",
                    "position_number"),
    "description": ("desc", "description", "item_description", "part_description", "text"),
    "lead_time_days": ("lead_time", "lt", "lead_time_days", "leadtime", "lead_time_d", "lt_days"),
    "uom": ("uom", "unit", "unit_of_measure", "um", "units", "base_unit"),
    "make_buy": ("make_buy", "make_or_buy", "procurement", "procurement_type", "type", "source", "m_b"),
    "revision": ("rev", "revision", "version_rev", "eng_rev"),
    "scrap_pct": ("scrap", "scrap_pct", "scrap_percent", "scrap_", "component_scrap"),
    "family": ("family", "product_family", "item_family"),
    "safety_stock": ("safety_stock", "ss"),
    "min_order_qty": ("moq", "min_order_qty", "minimum_order_quantity", "min_qty"),
    "order_multiple": ("order_multiple", "multiple", "pack_size", "lot_multiple"),
    "code": ("code", "id"),
    "name": ("name", "title"),
    "group_code": ("group", "stage", "work_center", "workcenter", "group_code", "stage_code", "wc"),
    "seq": ("seq", "op", "operation", "op_no", "operation_no", "operation_number", "sequence", "step"),
    "setup_minutes": ("setup", "setup_time", "setup_min", "setup_minutes"),
    "run_minutes": ("run", "run_time", "run_min", "run_minutes", "cycle_time"),
    "quantity": ("quantity", "qty", "count"),
    "template_code": ("template", "template_code", "shift_template"),
    "shift_name": ("shift", "shift_name"),
}

#: source sheet name (normalised) -> target sheet, in addition to the exact target names.
SHEET_SYNONYMS: dict[str, str] = {
    "bom": "bom_lines", "bill_of_materials": "bom_lines", "bom_line": "bom_lines", "structure": "bom_lines",
    "item": "items", "parts": "items", "part": "items", "part_master": "items", "material_master": "items",
    "materials": "items", "item_master": "items", "routing": "routings", "operation": "operations",
    "ops": "operations", "work_centers": "groups", "stages": "groups", "workcenters": "groups",
    "tools": "tool_pools", "tooling": "tool_pools", "shift_template": "shift_templates", "templates": "shift_templates",
    "assignments": "shift_assignments", "exceptions": "calendar_exceptions", "calendar": "calendar_exceptions",
    "holidays": "calendar_exceptions", "people": "operators", "employees": "operators",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_header(text: Any) -> str:
    return _NON_ALNUM.sub("_", str(text if text is not None else "").strip().lower()).strip("_")


def is_attr_field(name: str) -> bool:
    return name.startswith(ATTR_PREFIX) and len(name) > len(ATTR_PREFIX)


def valid_field(sheet: SheetSpec, field: str) -> bool:
    return field in sheet.fields or (sheet.attr_columns and is_attr_field(field)
                                     and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-/]{0,31}",
                                                           field[len(ATTR_PREFIX):])))


def column_synonyms(field: str) -> list[str]:
    return sorted(set(SYNONYMS.get(field, ())) | {field})


def meta_spec() -> dict[str, Any]:
    """`GET /meta` `import_spec`."""
    return {"sheets": [{"name": s.name, "columns": [
        {"field": c.field, "type": c.type, "required_on_create": c.required_on_create, "key": c.key,
         "enum_values": list(c.enum_values) if c.enum_values is not None else None,
         "synonyms": column_synonyms(c.field)} for c in s.columns]} for s in SHEETS]}


# ---------------------------------------------------------------- cell parsing


class CellError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_INT = re.compile(r"^[+-]?\d+(\.0*)?$")
_FLOAT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$")
_TRUE = {"true", "yes", "y", "1", "t", "x"}
_FALSE = {"false", "no", "n", "0", "f"}
MAKE_BUY_ALIASES = {"m": "make", "make": "make", "manufactured": "make", "manufacture": "make", "made": "make",
                    "b": "buy", "buy": "buy", "purchased": "buy", "purchase": "buy", "bought": "buy",
                    "p": "phantom", "phantom": "phantom"}


def blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def as_text(v: Any) -> str:
    """Excel numeric cells in text fields without `.0` when integral (part numbers)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isfinite(v) and v.is_integer() and abs(v) < 1e16:
            return str(int(v))
        return repr(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def parse_int(v: Any) -> int:
    if isinstance(v, bool):
        raise CellError("IMP_BAD_NUMBER", msg.bad_integer(v))
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isfinite(v) and v.is_integer():
            return int(v)
        raise CellError("IMP_BAD_NUMBER", msg.bad_integer(v))
    t = str(v).strip()
    if _INT.match(t):
        return int(t.split(".")[0])
    if _FLOAT.match(t):
        raise CellError("IMP_BAD_NUMBER", msg.bad_integer(v))
    raise CellError("IMP_BAD_NUMBER", msg.bad_number(v))


def parse_float(v: Any) -> float:
    if isinstance(v, bool):
        raise CellError("IMP_BAD_NUMBER", msg.bad_number(v))
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        t = str(v).strip()
        if not _FLOAT.match(t):
            raise CellError("IMP_BAD_NUMBER", msg.bad_number(v))
        f = float(t)
    if not math.isfinite(f):
        raise CellError("IMP_BAD_NUMBER", msg.bad_number(v))
    return f


def parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    t = str(v).strip().lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    raise CellError("IMP_BAD_BOOLEAN", msg.bad_boolean(v))


def parse_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v).strip()
    m = _DATETIME.match(t)
    if m and int(m.group(2)) == 0 and int(m.group(3)) == 0 and not int(m.group(4) or 0):
        t = m.group(1)
    try:
        if _DATE.match(t):
            return date.fromisoformat(t)
    except ValueError:
        pass
    raise CellError("IMP_BAD_DATE", msg.bad_date(v))


def parse_datetime(v: Any) -> date | datetime:
    """Date-only -> `date` (local midnight / inclusive end, resolved by the planner); `YYYY-MM-DD HH:MM` -> naive
    local datetime; ISO with offset -> aware datetime."""
    if isinstance(v, (date, datetime)):
        return v
    t = str(v).strip()
    try:
        if _DATE.match(t):
            return date.fromisoformat(t)
        m = _DATETIME.match(t)
        if m:
            return datetime.fromisoformat(f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}:{m.group(4) or '00'}")
        return datetime.fromisoformat(t)
    except ValueError:
        raise CellError("IMP_BAD_DATE", msg.bad_datetime(v)) from None


def parse_list(v: Any) -> list[str]:
    if blank(v):
        return []
    if isinstance(v, (list, tuple)):
        return [as_text(x) for x in v if not blank(x)]
    return [x.strip() for x in re.split(r"[;,|]", as_text(v)) if x.strip()]


def parse_enum(v: Any, col: ColumnSpec) -> str:
    allowed = col.enum_values or ()
    t = as_text(v)
    if col.field == "uom":
        code = normalize_uom(t)
        if code is None:
            raise CellError("IMP_BAD_UOM", msg.bad_uom(v))
        return code
    low = t.lower()
    if col.field == "make_buy" and low in MAKE_BUY_ALIASES:
        return MAKE_BUY_ALIASES[low]
    for a in allowed:
        if a.lower() == low:
            return a
    raise CellError("IMP_BAD_ENUM", msg.bad_enum(v, allowed))


def parse_attr(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip()
    return v


def parse_cell(v: Any, col: ColumnSpec | None, field: str) -> Any:
    """One staged cell -> the bundle value (blank -> None, or [] for lists)."""
    if col is None:                                  # attr:<name>
        return None if blank(v) else parse_attr(v)
    if col.type == "list":
        return parse_list(v)
    if blank(v):
        return None
    t = col.type
    if t == "str":
        return as_text(v)
    if t == "int":
        return parse_int(v)
    if t == "float":
        return parse_float(v)
    if t == "bool":
        return parse_bool(v)
    if t == "date":
        return parse_date(v)
    if t == "datetime":
        return parse_datetime(v)
    if t == "enum":
        return parse_enum(v, col)
    return v  # pragma: no cover


def sheet_spec(name: str) -> SheetSpec:
    return SHEETS_BY_NAME[name]
