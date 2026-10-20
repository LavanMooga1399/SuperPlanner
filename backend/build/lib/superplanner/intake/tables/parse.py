"""Delimiter/header detection and CSV parsing (PHASE2 2.13)."""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import date

from ..models import (MAX_TABLE_CHARS, MAX_TABLE_COLUMNS, MAX_TABLE_ROWS, Domain, IntakeError, TableColumn,
                      TableParseResult)
from ..text.dates import find_dates
from ..text.durations import find_durations
from ..text.numbers import find_money
from .mapping import header_field, suggest

CANDIDATES = ("\t", ",", ";", "|")
csv.field_size_limit(MAX_TABLE_CHARS + 1)


def _rows(text: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar='"', skipinitialspace=False)
    out = []
    for row in reader:
        cells = [c.strip() for c in row]
        if any(cells):
            out.append(cells)
    return out


def detect_delimiter(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    sample = "\n".join(lines)
    best, best_share = "\t", -1.0
    for d in CANDIDATES:
        try:
            counts = [len(r) for r in _rows(sample, d)]
        except csv.Error:
            continue
        if not counts:
            continue
        modal, freq = Counter(counts).most_common(1)[0]
        if modal <= 1:
            continue
        share = freq / len(counts)
        if share > best_share:
            best, best_share = d, share
    return best


def looks_like_value(cell: str, today: date) -> bool:
    c = cell.strip()
    if not c:
        return False
    if c.replace(",", "").replace(".", "", 1).isdigit():
        return True
    return bool(find_durations(c) or find_dates(c, today) or find_money(c, min_bare=0.0))


def parse_rows(text: str, delimiter: str, *, max_chars: int = MAX_TABLE_CHARS) -> list[list[str]]:
    if len(text) > max_chars:
        raise IntakeError("TABLE_TOO_LARGE", f"The table is longer than {max_chars} characters.",
                          {"max_chars": max_chars})
    if not text.strip():
        raise IntakeError("TABLE_EMPTY", "The table is empty.")
    try:
        rows = _rows(text, delimiter)
    except csv.Error:
        raise IntakeError("TABLE_EMPTY", "The table could not be read.") from None
    if not rows:
        raise IntakeError("TABLE_EMPTY", "The table is empty.")
    if max(len(r) for r in rows) > MAX_TABLE_COLUMNS:
        raise IntakeError("TABLE_TOO_LARGE", f"The table has more than {MAX_TABLE_COLUMNS} columns.",
                          {"max_columns": MAX_TABLE_COLUMNS})
    if len(rows) > MAX_TABLE_ROWS + 1:
        raise IntakeError("TABLE_TOO_LARGE", f"The table has more than {MAX_TABLE_ROWS} rows.",
                          {"max_rows": MAX_TABLE_ROWS})
    return rows


def detect_header(first: list[str], domain: Domain, today: date) -> bool:
    if any(looks_like_value(c, today) for c in first):
        return False
    return any(header_field(c, domain)[0] is not None for c in first)


def parse_table(text: str, domain: Domain, *, delimiter: str = "auto", has_header: bool | None = None,
                today: date | None = None, max_chars: int = MAX_TABLE_CHARS) -> TableParseResult:
    today = today or date.today()
    if len(text) > max_chars:
        raise IntakeError("TABLE_TOO_LARGE", f"The table is longer than {max_chars} characters.",
                          {"max_chars": max_chars})
    d = detect_delimiter(text) if delimiter == "auto" else delimiter
    rows = parse_rows(text, d, max_chars=max_chars)
    header = detect_header(rows[0], domain, today) if has_header is None else has_header
    data = rows[1:] if header else rows
    if len(data) > MAX_TABLE_ROWS:
        raise IntakeError("TABLE_TOO_LARGE", f"The table has more than {MAX_TABLE_ROWS} rows.",
                          {"max_rows": MAX_TABLE_ROWS})
    ncol = max(len(r) for r in rows)
    warnings: list[str] = []
    for i, r in enumerate(data):
        if len(r) != ncol and len(warnings) < 20:
            warnings.append(f"Row {i + 1} has {len(r)} cells; the table has {ncol} columns.")
    padded = [r + [""] * (ncol - len(r)) for r in data]
    headers = [(rows[0][j] if j < len(rows[0]) else "") if header else None for j in range(ncol)]
    for j in range(ncol):
        if data and not any(r[j] for r in padded):
            warnings.append(f"Column {j + 1} is empty.")
    suggestions = suggest(headers, padded, domain, today)
    columns = [TableColumn(index=j, header=headers[j], samples=[r[j] for r in padded[:5]],
                           suggested_field=suggestions[j][0], confidence=suggestions[j][1]) for j in range(ncol)]
    return TableParseResult(delimiter=d, has_header=header, row_count=len(data), columns=columns,
                            preview=padded[:10], warnings=warnings)
