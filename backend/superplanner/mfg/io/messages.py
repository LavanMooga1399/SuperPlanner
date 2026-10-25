"""Import row-error codes and plain-language messages (M1-DESIGN 8.2, WP-B; split from `mfg/messages.py`)."""

from __future__ import annotations

ROW_ERROR_CODES: tuple[str, ...] = (
    "IMP_REQUIRED", "IMP_BAD_NUMBER", "IMP_BAD_BOOLEAN", "IMP_BAD_DATE", "IMP_BAD_ENUM", "IMP_BAD_UOM",
    "IMP_BAD_VALUE", "IMP_UNKNOWN_REFERENCE", "IMP_DUPLICATE_KEY", "IMP_RELEASED_READONLY", "IMP_BOM_CYCLE",
    "IMP_FORMULA_NO_VALUE", "IMP_TOO_LONG", "IMP_CONTROL_CHAR", "IMP_RELEASE_BLOCKED",
)

WARNING_CODES: tuple[str, ...] = ("IMP_ENCODING_FALLBACK", "IMP_SHEET_IGNORED", "IMP_COLUMN_IGNORED",
                                  "IMP_EMPTY_SHEET")

FIELD_LABELS: dict[str, str] = {
    "part_number": "Part number", "parent_part_number": "Parent part number",
    "child_part_number": "Component part number", "qty_per": "Quantity per", "find_number": "Find number",
    "make_buy": "Make/buy", "uom": "Unit", "code": "Code", "name": "Name", "group_code": "Stage code",
    "template_code": "Shift template code", "shift_name": "Shift name", "target_type": "Target type",
    "target_code": "Target code", "kind": "Kind", "effective_from": "Effective from", "scope": "Scope",
    "start": "Start", "end": "End", "days": "Days", "seq": "Operation number", "quantity": "Quantity",
}


def label(field: str) -> str:
    return FIELD_LABELS.get(field, field.replace("_", " ").capitalize())


def required(field: str) -> str:
    return f"{label(field)} is required."


def bad_number(value: object) -> str:
    return (f"{value!r} is not a number (use a '.' as the decimal point and no thousands separators).")


def bad_integer(value: object) -> str:
    return f"{value!r} is not a whole number."


def bad_boolean(value: object) -> str:
    return f"{value!r} is not yes/no (use true/false, yes/no, y/n or 1/0)."


def bad_date(value: object) -> str:
    return f"{value!r} is not a date (use YYYY-MM-DD)."


def bad_datetime(value: object) -> str:
    return f"{value!r} is not a date/time (use YYYY-MM-DD, YYYY-MM-DD HH:MM or an ISO time with offset)."


def bad_enum(value: object, allowed: tuple[str, ...] | list[str]) -> str:
    return f"{value!r} is not allowed here (allowed: {', '.join(allowed)})."


def bad_uom(value: object) -> str:
    return f"{value!r} is not a known unit (for example EA, PCS, M, MM, KG, L, ML)."


def unknown_reference(what: str, value: object) -> str:
    return f"{what} {value!r} is not in your data or in this file."


def duplicate_key(key: object, other_row: int | None) -> str:
    where = f" (also row {other_row})" if other_row else ""
    return f"The key {key} appears twice in this file{where}."


def released_readonly(what: str, label_: str) -> str:
    return (f"{what} {label_} is released or obsolete and cannot be changed by an import; copy it to a new "
            "version first.")


def cycle(path: str) -> str:
    return f"This line would make an item contain itself: {path}."


def formula_no_value() -> str:
    return "The cell has a formula without a calculated value; open the file in Excel, save it and upload again."


def control_char() -> str:
    return "The cell contained control characters; they were removed."


def too_long(field: str, max_len: int | None = None) -> str:
    return f"{label(field)} is too long" + (f" (at most {max_len} characters)." if max_len else ".")


def release_blocked(what: str, label_: str, problems: list[str]) -> str:
    return f"{what} {label_} cannot be released: " + " ".join(problems)
