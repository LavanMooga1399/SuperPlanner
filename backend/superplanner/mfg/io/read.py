"""Uploaded file -> staged raw sheets (M1-DESIGN 8.1, 8.3, review R4).

Format by magic bytes (never by name): `PK\\x03\\x04` -> zip (an xlsx if it holds `[Content_Types].xml` and
`xl/workbook.xml`, else a zip of `<sheet>.csv` files); OLE `D0 CF 11 E0` (`.xls`) is refused; anything else is CSV
text. Zip members are checked from `infolist()` before anything is decompressed (count, declared total size,
per-member ratio, path safety) and never extracted to disk. xlsx is read with openpyxl `read_only=True,
data_only=True, keep_links=False` (defusedxml active); rows come from openpyxl's worksheet parser, which yields only
the rows present in the XML, so a cell in row 1,000,000 is found without iterating a million filler rows.

Every staged cell is a JSON-safe scalar. Strings lose C0 control characters other than tab/CR/LF (cell issue
`IMP_CONTROL_CHAR`); non-finite numbers become `None` (`IMP_BAD_NUMBER`); formulas without a cached value become
`None` (`IMP_FORMULA_NO_VALUE`); Excel dates become `YYYY-MM-DD` (midnight) or `YYYY-MM-DD HH:MM:SS`. Cell issues are
turned into row errors at mapping time, for mapped columns only.

Staged sheet: `{"name", "headers", "rows": [[row_number, [cells]]], "row_count", "issues": [[row, col, code]]}`.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from .. import limits as L

log = logging.getLogger(__name__)

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CSV_ESCAPE_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "'")


class ImportFileInvalid(ValueError):
    """422 `MFG_IMPORT_FILE_INVALID` (`reason` is generic and safe to show)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ImportTooLarge(ValueError):
    """422 `MFG_IMPORT_TOO_LARGE` with `details.limit` / `details.value`."""

    def __init__(self, limit: str, value: int | None = None, message: str | None = None):
        super().__init__(message or f"The file exceeds the import limit {limit}.")
        self.limit = limit
        self.value = value
        self.message = message or f"The file exceeds the import limit {limit}."


@dataclass
class RawFile:
    format: str                      # xlsx | csv | zip
    sheets: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------- cell normalisation


class _Sheet:
    """Builds one staged sheet: header = first non-empty row; empty rows skipped; limits enforced."""

    def __init__(self, name: str, total: list[int]):
        self.name = name
        self.headers: list[str] | None = None
        self.rows: list[list[Any]] = []
        self.issues: list[list[Any]] = []
        self.total = total

    def add(self, rownum: int, cells: list[Any], issues: list[tuple[int, str]]) -> None:
        if all(c is None or (isinstance(c, str) and c.strip() == "") for c in cells) and not issues:
            return
        if self.headers is None:
            self.headers = _headers(cells)
            return
        width = len(self.headers)
        row = list(cells[:width]) + [None] * max(0, width - len(cells))
        if all(c is None or (isinstance(c, str) and c.strip() == "") for c in row) and \
                not any(col < width for col, _ in issues):
            return
        if len(self.rows) >= L.IMPORT_MAX_ROWS_PER_SHEET:
            raise ImportTooLarge("IMPORT_MAX_ROWS_PER_SHEET", L.IMPORT_MAX_ROWS_PER_SHEET,
                                 f"Sheet {self.name!r} has more than {L.IMPORT_MAX_ROWS_PER_SHEET} data rows.")
        self.total[0] += 1
        if self.total[0] > L.IMPORT_MAX_ROWS_TOTAL:
            raise ImportTooLarge("IMPORT_MAX_ROWS_TOTAL", L.IMPORT_MAX_ROWS_TOTAL,
                                 f"The file has more than {L.IMPORT_MAX_ROWS_TOTAL} data rows.")
        self.rows.append([rownum, row])
        for col, code in issues:
            if col < width:
                self.issues.append([rownum, col, code])

    def staged(self) -> dict[str, Any]:
        return {"name": self.name, "headers": self.headers or [], "rows": self.rows, "row_count": len(self.rows),
                "issues": self.issues}


def _headers(cells: list[Any]) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    last = max((i for i, c in enumerate(cells) if not (c is None or (isinstance(c, str) and not c.strip()))),
               default=-1)
    for i, c in enumerate(cells[:last + 1]):
        h = "" if c is None else (c.strip() if isinstance(c, str) else _stage_text(c))
        if not h:
            h = f"Column {i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        out.append(h)
    return out


def _stage_text(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def clean_string(s: str) -> tuple[str, bool]:
    if _CTRL.search(s):
        return _CTRL.sub("", s), True
    return s, False


def stage_cell(v: Any) -> tuple[Any, str | None]:
    """A Python cell value -> (JSON-safe scalar, issue code or None)."""
    if v is None:
        return None, None
    if isinstance(v, bool):
        return v, None
    if isinstance(v, int):
        return v, None
    if isinstance(v, float):
        if not math.isfinite(v):
            return None, "IMP_BAD_NUMBER"
        return v, None
    if isinstance(v, str):
        if len(v) > L.IMPORT_MAX_CELL_CHARS:
            raise ImportTooLarge("IMPORT_MAX_CELL_CHARS", L.IMPORT_MAX_CELL_CHARS,
                                 f"A cell has more than {L.IMPORT_MAX_CELL_CHARS} characters.")
        s, bad = clean_string(v)
        return s, ("IMP_CONTROL_CHAR" if bad else None)
    if isinstance(v, datetime):
        if v.tzinfo is None and v.time() == time(0, 0):
            return v.date().isoformat(), None
        return v.replace(microsecond=0).isoformat(sep=" ") if v.tzinfo is None else v.isoformat(), None
    if isinstance(v, date):
        return v.isoformat(), None
    if isinstance(v, time):
        return v.strftime("%H:%M"), None
    if isinstance(v, timedelta):
        return v.total_seconds() / 86400.0, None
    s, bad = clean_string(str(v))
    return s, ("IMP_CONTROL_CHAR" if bad else None)


# ---------------------------------------------------------------- entry point


def detect_format(data: bytes) -> str:
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return "xls"
    return "csv"


def read_upload(data: bytes, *, sheet: str | None = None, filename: str = "") -> RawFile:
    """Parse an upload. Raises `ImportFileInvalid` / `ImportTooLarge`; any other exception raised while reading
    is turned into `ImportFileInvalid` (logged at INFO), never a 500."""
    try:
        return _read(data, sheet=sheet, filename=filename)
    except (ImportFileInvalid, ImportTooLarge):
        raise
    except Exception as exc:  # openpyxl ValueError (NaN), BadZipFile, KeyError, XML errors, defusedxml ...
        log.info("import file unreadable: %s: %s", type(exc).__name__, str(exc)[:200])
        raise ImportFileInvalid("The file could not be read. Save it as .xlsx or .csv and try again.") from None


def _read(data: bytes, *, sheet: str | None, filename: str) -> RawFile:
    if not data:
        raise ImportFileInvalid("The file is empty.")
    kind = detect_format(data)
    if kind == "xls":
        raise ImportFileInvalid("Old Excel files (.xls) are not supported. Save the file as .xlsx and try again.")
    if kind == "csv":
        name = (sheet or _stem(filename) or "data").strip() or "data"
        text, warnings = _decode(data)
        total = [0]
        return RawFile("csv", [_read_csv_text(text, name, total)], warnings)
    zf = _open_zip(data)
    names = set(zf.namelist())
    if "[Content_Types].xml" in names and "xl/workbook.xml" in names:
        return RawFile("xlsx", _read_xlsx(data))
    return _read_csv_zip(zf)


def _stem(filename: str) -> str:
    base = re.split(r"[\\/]", filename or "")[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportFileInvalid("The file is not a valid .xlsx or .zip file.") from None
    infos = zf.infolist()
    if len(infos) > L.IMPORT_MAX_ZIP_MEMBERS:
        raise ImportTooLarge("IMPORT_MAX_ZIP_MEMBERS", len(infos),
                             f"The archive has more than {L.IMPORT_MAX_ZIP_MEMBERS} files.")
    total = 0
    for info in infos:
        n = info.filename
        if n.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", n) or ".." in re.split(r"[\\/]", n):
            raise ImportFileInvalid("The archive contains unsafe file paths.")
        total += info.file_size
        if info.file_size / max(info.compress_size, 1) > L.IMPORT_MAX_COMPRESSION_RATIO:
            raise ImportTooLarge("IMPORT_MAX_COMPRESSION_RATIO", int(info.file_size / max(info.compress_size, 1)),
                                 "The archive is compressed suspiciously strongly and was refused.")
    if total > L.IMPORT_MAX_UNCOMPRESSED_BYTES:
        raise ImportTooLarge("IMPORT_MAX_UNCOMPRESSED_BYTES", total,
                             f"The archive unpacks to more than {L.IMPORT_MAX_UNCOMPRESSED_BYTES} bytes.")
    return zf


def _decode(data: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), [
            {"code": "IMP_ENCODING_FALLBACK", "sheet": None,
             "message": "The file is not UTF-8; it was read as Windows-1252 (check special characters)."}]


def _read_csv_zip(zf: zipfile.ZipFile) -> RawFile:
    sheets: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    total = [0]
    for info in sorted(zf.infolist(), key=lambda i: i.filename):
        if info.is_dir():
            continue
        base = re.split(r"[\\/]", info.filename)[-1]
        if not base.lower().endswith(".csv"):
            if not base.lower().startswith("readme") and not base.startswith("."):
                warnings.append({"code": "IMP_SHEET_IGNORED", "sheet": base,
                                 "message": f"{base} is not a .csv file and was ignored."})
            continue
        text, w = _decode(zf.read(info))
        for x in w:
            x["sheet"] = base[:-4]
        warnings.extend(w)
        sheets.append(_read_csv_text(text, base[:-4], total))
    if not sheets:
        raise ImportFileInvalid("The archive contains no .csv files.")
    return RawFile("zip", sheets, warnings)


def _sniff(text: str) -> str:
    first = ""
    for ln in text.splitlines():
        if ln.strip():
            first = ln
            break
    counts = {d: first.count(d) for d in (",", ";", "\t")}
    best = max(counts, key=lambda d: (counts[d], d == ","))
    return best if counts[best] > 0 else ","


def unescape_csv(v: str) -> str:
    """CSV formula escape (8.3): strip one leading `'` when the next character is a trigger."""
    if len(v) >= 2 and v[0] == "'" and v[1] in CSV_ESCAPE_TRIGGERS:
        return v[1:]
    return v


def _read_csv_text(text: str, name: str, total: list[int]) -> dict[str, Any]:
    sh = _Sheet(name, total)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_sniff(text))
    for n, row in enumerate(reader, 1):
        if n > L.IMPORT_MAX_SCANNED_ROWS:
            if any(c.strip() for c in row):
                raise ImportTooLarge("IMPORT_MAX_SCANNED_ROWS", L.IMPORT_MAX_SCANNED_ROWS,
                                     f"Sheet {name!r} has more than {L.IMPORT_MAX_SCANNED_ROWS} rows.")
            continue
        if len(row) > L.IMPORT_MAX_COLUMNS and any(c.strip() for c in row[L.IMPORT_MAX_COLUMNS:]):
            raise ImportTooLarge("IMPORT_MAX_COLUMNS", L.IMPORT_MAX_COLUMNS,
                                 f"Sheet {name!r} has more than {L.IMPORT_MAX_COLUMNS} columns.")
        cells: list[Any] = []
        issues: list[tuple[int, str]] = []
        for i, c in enumerate(row[:L.IMPORT_MAX_COLUMNS]):
            v, code = stage_cell(unescape_csv(c.strip()) if c.strip() else "")
            cells.append(v if v != "" else None)
            if code:
                issues.append((i, code))
        sh.add(n, cells, issues)
    return sh.staged()


# ---------------------------------------------------------------- xlsx


def _parser_class() -> Any:
    from openpyxl.worksheet._reader import FORMULA_TAG, WorkSheetParser

    class _Parser(WorkSheetParser):
        def parse_cell(self, element: Any) -> dict[str, Any]:
            c = super().parse_cell(element)
            if c["value"] is None and element.find(FORMULA_TAG) is not None:
                c["formula_no_value"] = True
            return c

    return _Parser


def _read_xlsx(data: bytes) -> list[dict[str, Any]]:
    import openpyxl

    if not getattr(openpyxl, "DEFUSEDXML", False):  # pragma: no cover - guarded by a test as well
        raise ImportFileInvalid("xlsx import is disabled: the XML safety package is missing.")
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    parser_cls = _parser_class()
    total = [0]
    out: list[dict[str, Any]] = []
    try:
        for ws in wb.worksheets:
            if not hasattr(ws, "_get_source"):
                continue                      # chart sheets
            sh = _Sheet(ws.title, total)
            with ws._get_source() as src:
                parser = parser_cls(src, ws._shared_strings, data_only=True, epoch=wb.epoch,
                                    date_formats=wb._date_formats, timedelta_formats=wb._timedelta_formats)
                for idx, row in parser.parse():
                    present = [c for c in row if c.get("value") is not None or c.get("formula_no_value")]
                    if not present:
                        continue
                    if idx > L.IMPORT_MAX_SCANNED_ROWS:
                        raise ImportTooLarge("IMPORT_MAX_SCANNED_ROWS", idx,
                                             f"Sheet {ws.title!r} has data after row {L.IMPORT_MAX_SCANNED_ROWS}.")
                    width = max(c["column"] for c in present)
                    if width > L.IMPORT_MAX_COLUMNS:
                        raise ImportTooLarge("IMPORT_MAX_COLUMNS", width,
                                             f"Sheet {ws.title!r} has data beyond column {L.IMPORT_MAX_COLUMNS}.")
                    cells: list[Any] = [None] * width
                    issues: list[tuple[int, str]] = []
                    for c in present:
                        col = c["column"] - 1
                        if c.get("formula_no_value"):
                            issues.append((col, "IMP_FORMULA_NO_VALUE"))
                            continue
                        v, code = stage_cell(c["value"])
                        cells[col] = v
                        if code:
                            issues.append((col, code))
                    sh.add(idx, cells, issues)
            out.append(sh.staged())
    finally:
        wb.close()
    return out


def staged_size(sheets: list[dict[str, Any]]) -> int:
    return len(json.dumps(sheets, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
