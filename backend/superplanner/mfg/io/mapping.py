"""Mapping suggestion and application (M1-DESIGN 8.1, 8.2).

`suggest_mapping(staged_sheet)` -> `{"target", "columns"}` or None. `apply_mapping(staged, mapping)` turns staged
cells into an `MfgBundle` (typed values, only mapped columns present in each row) plus, per bundle row, its source
(`Source`), and the row errors found while parsing cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..bundle import ATTR_PREFIX, SHEETS, SHEETS_BY_NAME, MfgBundle, SheetSpec
from . import messages as msg
from .spec import (SHEET_SYNONYMS, SYNONYMS, CellError, is_attr_field, normalize_header, parse_cell, valid_field)


@dataclass
class Source:
    sheet: str                                  # source sheet name
    row: int                                    # 1-based row number as Excel shows it
    columns: dict[str, str] = field(default_factory=dict)   # field -> source column header

    def column(self, f: str) -> str:
        return self.columns.get(f, f)


class MappingError(ValueError):
    """422 `VALIDATION_ERROR` for an invalid mapping request (`errors` in the A 14 shape)."""

    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("; ".join(e["msg"] for e in errors[:3]))
        self.errors = errors


def _column_for(header: str, sheet: SheetSpec, used: set[str]) -> str | None:
    raw = str(header).strip()
    if sheet.attr_columns and raw.lower().startswith(ATTR_PREFIX):
        f = ATTR_PREFIX + raw[len(ATTR_PREFIX):].strip()
        return f if valid_field(sheet, f) and f not in used else None
    h = normalize_header(raw)
    if h in sheet.fields and h not in used:
        return h
    for f in sheet.fields:
        if f in used:
            continue
        syn = SYNONYMS.get(f, ())
        if f == "description" and "name" in sheet.fields:
            syn = tuple(s for s in syn if s != "name")
        if h in syn:
            return f
    if h == "name" and "name" not in sheet.fields and "description" in sheet.fields and "description" not in used:
        return "description"
    return None


def suggest_columns(headers: list[str], sheet: SheetSpec) -> dict[str, str | None]:
    used: set[str] = set()
    out: dict[str, str | None] = {}
    for h in headers:
        f = _column_for(h, sheet, used)
        out[h] = f
        if f is not None:
            used.add(f)
    return out


def suggest_mapping(staged: dict[str, Any]) -> dict[str, Any] | None:
    headers = list(staged.get("headers") or [])
    name = normalize_header(staged.get("name", ""))
    target: str | None = None
    if name in SHEETS_BY_NAME:
        target = name
    elif name in SHEET_SYNONYMS:
        target = SHEET_SYNONYMS[name]
    if target is None:
        best: tuple[int, int, str] | None = None
        for s in SHEETS:
            cols = suggest_columns(headers, s)
            mapped = {f for f in cols.values() if f}
            keys = len(mapped & set(s.key))
            if keys >= 2:
                cand = (keys, len(mapped), s.name)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        if best is not None:
            target = best[2]
    if target is None:
        return None
    return {"target": target, "columns": suggest_columns(headers, SHEETS_BY_NAME[target])}


def validate_mapping(staged: list[dict[str, Any]], mapping: dict[str, Any]) -> None:
    by_name = {s["name"]: s for s in staged}
    errors: list[dict[str, Any]] = []
    for src, m in (mapping.get("sheets") or {}).items():
        loc = ["body", "sheets", src]
        if src not in by_name:
            errors.append({"loc": loc, "msg": f"The file has no sheet {src!r}.", "type": "unknown_sheet"})
            continue
        target = m.get("target")
        if target is None:
            continue
        if target not in SHEETS_BY_NAME:
            errors.append({"loc": loc + ["target"], "msg": f"{target!r} is not an import sheet.",
                           "type": "unknown_target"})
            continue
        spec = SHEETS_BY_NAME[target]
        headers = set(by_name[src]["headers"])
        seen: dict[str, str] = {}
        for col, f in (m.get("columns") or {}).items():
            cloc = loc + ["columns", col]
            if col not in headers:
                errors.append({"loc": cloc, "msg": f"Sheet {src!r} has no column {col!r}.", "type": "unknown_column"})
                continue
            if f is None:
                continue
            if not valid_field(spec, f):
                errors.append({"loc": cloc, "msg": f"{f!r} is not a field of {target}.", "type": "unknown_field"})
                continue
            if f in seen:
                errors.append({"loc": cloc, "msg": f"Columns {seen[f]!r} and {col!r} are both mapped to {f!r}.",
                               "type": "duplicate_field"})
                continue
            seen[f] = col
    if errors:
        raise MappingError(errors)


def apply_mapping(staged: list[dict[str, Any]], mapping: dict[str, Any]
                  ) -> tuple[MfgBundle, dict[str, list[Source]], list[dict[str, Any]]]:
    """(bundle, sources per bundle sheet aligned with its rows, row errors). Rows with a cell error are kept
    without the bad field (the error blocks the commit anyway); sheets mapped to null are ignored."""
    by_name = {s["name"]: s for s in staged}
    bundle: MfgBundle = {}
    sources: dict[str, list[Source]] = {}
    errors: list[dict[str, Any]] = []
    for src, m in (mapping.get("sheets") or {}).items():
        target = m.get("target")
        if target is None or src not in by_name:
            continue
        spec = SHEETS_BY_NAME[target]
        sh = by_name[src]
        headers: list[str] = sh["headers"]
        cols = [(i, h, f) for i, h in enumerate(headers) for f in [(m.get("columns") or {}).get(h)] if f]
        issues: dict[tuple[int, int], str] = {(r, c): code for r, c, code in sh.get("issues") or []}
        rows = bundle.setdefault(target, [])
        srcs = sources.setdefault(target, [])
        for rownum, cells in sh["rows"]:
            row: dict[str, Any] = {}
            colmap: dict[str, str] = {}
            for i, h, f in cols:
                colmap[f] = h
                code = issues.get((rownum, i))
                if code is not None:
                    errors.append({"sheet": src, "row": rownum, "column": h, "code": code,
                                   "message": _issue_message(code)})
                    if code != "IMP_CONTROL_CHAR":
                        continue
                v = cells[i] if i < len(cells) else None
                col = spec.column(f) if f in spec.fields else None
                try:
                    row[f] = parse_cell(v, col, f)
                except CellError as exc:
                    errors.append({"sheet": src, "row": rownum, "column": h, "code": exc.code,
                                   "message": exc.message})
            rows.append(row)
            srcs.append(Source(src, rownum, colmap))
    return bundle, sources, errors


def _issue_message(code: str) -> str:
    if code == "IMP_CONTROL_CHAR":
        return msg.control_char()
    if code == "IMP_FORMULA_NO_VALUE":
        return msg.formula_no_value()
    if code == "IMP_BAD_NUMBER":
        return "The cell holds a number that is too large or not a number."
    return code


def bundle_sources(bundle: MfgBundle) -> dict[str, list[Source]]:
    """Sources for a bundle that did not come from a file (samples): sheet = bundle sheet, row = index + 2."""
    return {name: [Source(name, i + 2) for i in range(len(rows))] for name, rows in bundle.items()}
