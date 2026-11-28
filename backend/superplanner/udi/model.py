"""UDI device records, label templates, printers, print jobs / events and export contracts (M10-DESIGN 7; frozen
at S0). Label elements are in millimetres from the top-left corner of the label."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..esig.model import SignatureInput, SignatureManifest
from ..mfg.model import EntityId, MfgModel

Gtin = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{8}$|^[0-9]{12,14}$")]
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ClientEventId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,64}$")]
TemplateCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$")]
Level = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,8}$")]          # M8 packaging level (each, case ...)
Symbology = Literal["gs1_datamatrix", "gs1_128", "code128"]
AI = Literal["01", "11", "17", "10", "21"]

# ---------------------------------------------------------------- UDI device records (8, 14.1)


class PiFlags(MfgModel):
    lot: bool = True
    serial: bool = False
    expiry: bool = True
    mfg_date: bool = False


class UdiAttrs(MfgModel):
    """GUDID / Health Canada attributes (14.1). Element names: `udi/gudid_rules.py`."""
    brand: Annotated[str, StringConstraints(max_length=80)] = ""
    version_model: Annotated[str, StringConstraints(max_length=40)] = ""
    catalog_no: Annotated[str, StringConstraints(max_length=40)] = ""
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    gmdn_code: Annotated[str, StringConstraints(max_length=10)] = ""
    gmdn_term: Annotated[str, StringConstraints(max_length=200)] = ""
    fda_product_codes: Annotated[list[Annotated[str, StringConstraints(max_length=8)]], Field(max_length=10)] = \
        Field(default_factory=list)
    fda_class: Literal["", "I", "II", "III", "U"] = ""
    premarket_nos: Annotated[list[Annotated[str, StringConstraints(max_length=20)]], Field(max_length=10)] = \
        Field(default_factory=list)
    hc_licence_no: Annotated[str, StringConstraints(max_length=20)] = ""
    hc_class: Literal["", "I", "II", "III", "IV"] = ""
    sterile: bool = False
    ster_method: Annotated[str, StringConstraints(max_length=40)] = ""
    single_use: bool = False
    rx: bool = True
    kit: bool = False
    combination: bool = False
    mri_safety: Literal["", "mr_safe", "mr_conditional", "mr_unsafe", "not_evaluated", "no_info"] = ""
    latex: bool = False
    storage: Annotated[list[dict[str, Any]], Field(max_length=10)] = Field(default_factory=list)


class UdiDeviceInput(MfgModel):
    """U1 PUT (create when no record exists for the packaging row; If-Match on update). A draft only."""
    packaging_id: EntityId
    gtin: Gtin
    di_kind: Literal["base", "unit_of_use", "package"] = "base"
    qty_per_package: Annotated[int, Field(ge=1, le=10_000_000)] = 1
    contains_gtin: Gtin | None = None
    pi_flags: PiFlags = Field(default_factory=PiFlags)
    attrs: UdiAttrs = Field(default_factory=UdiAttrs)
    commercial_distribution_date: date | None = None


class UdiDeviceRecord(MfgModel):
    id: str
    packaging_id: str
    item_id: str
    item_part_number: str | None = None
    level: str
    gtin: str
    gtin_locked: bool
    di_kind: str
    qty_per_package: int
    contains_gtin: str | None = None
    pi_flags: PiFlags
    attrs: UdiAttrs
    status: Literal["draft", "approved", "obsolete"]
    commercial_distribution_date: date | None = None
    signatures: list[SignatureManifest] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class ApproveInput(MfgModel):
    signature: SignatureInput | None = None


class ParseResult(MfgModel):
    """U3 `GET /udi/parse?code=`: AI map, element string, HRI and warnings."""
    ok: bool
    symbology: str | None = None
    ais: dict[str, str] = Field(default_factory=dict)
    gtin_check_ok: bool | None = None
    expiry: date | None = None
    production_date: date | None = None
    data: str = ""
    hri: str = ""
    errors: list[str] = Field(default_factory=list)


class UdiExportInput(MfgModel):
    kind: Literal["gudid", "hc"]
    item_ids: Annotated[list[EntityId], Field(max_length=5000)] | None = None
    format: Literal["csv", "xlsx", "json"] = "csv"


class UdiExportRecord(MfgModel):
    id: str
    number: str
    kind: Literal["gudid", "hc"]
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed"]
    rule_version: str
    result: dict[str, Any] | None = None        # {rows, errors: [{gtin, element, message}], warnings: [...]}
    rendition: dict[str, Any] | None = None
    row_version: int
    created_at: datetime


# ---------------------------------------------------------------- label templates (7.2)

class BarcodeSpec(MfgModel):
    symbology: Symbology
    module_mm: Annotated[float, Field(gt=0, le=5)] = 0.5
    ais: Annotated[list[AI], Field(min_length=1, max_length=5)] = Field(default_factory=lambda: ["01", "17", "10"])
    hri: bool = True


class LabelElement(MfgModel):
    kind: Literal["text", "field", "barcode", "box", "line", "symbol"]
    x_mm: Annotated[float, Field(ge=0, le=500)]
    y_mm: Annotated[float, Field(ge=0, le=500)]
    w_mm: Annotated[float, Field(ge=0, le=500)] = 0
    h_mm: Annotated[float, Field(ge=0, le=500)] = 0
    rotation: Literal[0, 90, 180, 270] = 0
    font_pt: Annotated[float, Field(ge=4, le=72)] = 8
    bold: bool = False
    lang: Literal["en", "fr"] | None = None
    text: Annotated[str, StringConstraints(max_length=200)] | None = None
    field: Annotated[str, StringConstraints(pattern=r"^[a-z_]+\.[a-z_0-9]+$|^serial$")] | None = None
    barcode: BarcodeSpec | None = None
    #: `symbol`: customer-supplied SVG path data only (sanitised: commands and numbers)
    path: Annotated[str, StringConstraints(max_length=4000)] | None = None

    @model_validator(mode="after")
    def _kind(self) -> "LabelElement":
        need = {"text": "text", "field": "field", "barcode": "barcode", "symbol": "path"}.get(self.kind)
        if need and getattr(self, need) in (None, ""):
            raise ValueError(f"a {self.kind} element needs `{need}`")
        return self

    @field_validator("path")
    @classmethod
    def _path(cls, v: str | None) -> str | None:
        import re

        if v is not None and not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9eE.,\-\s]*", v):
            raise ValueError("symbol paths contain SVG path data only")
        return v


class LabelTemplateInput(MfgModel):
    code: TemplateCode
    name: Text200
    level: Level
    width_mm: Annotated[float, Field(gt=5, le=300)]
    height_mm: Annotated[float, Field(gt=5, le=300)]
    dpi: Literal[203, 300, 600] = 300
    languages: Annotated[list[Literal["en", "fr"]], Field(min_length=1, max_length=2)] = Field(
        default_factory=lambda: ["en"])
    elements: Annotated[list[LabelElement], Field(max_length=200)] = Field(default_factory=list)


class LabelTemplateRecord(LabelTemplateInput):
    id: str
    version: int
    status: Literal["draft", "in_change", "approved", "obsolete"]
    eco_id: str | None = None
    eco_number: str | None = None
    approved_at: datetime | None = None
    supersedes_id: str | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)     # validation findings (LBL_MODULE_TOO_SMALL ...)
    row_version: int
    created_at: datetime
    updated_at: datetime


class AssignmentRow(MfgModel):
    item_id: EntityId
    level: Level
    customer: Annotated[str, StringConstraints(max_length=100)] | None = None
    template_code: TemplateCode


class AssignmentsInput(MfgModel):
    """L5 PUT: replaces the assignments of the items named in `rows` (bulk)."""
    rows: Annotated[list[AssignmentRow], Field(max_length=2000)]


class PrinterInput(MfgModel):
    code: TemplateCode
    name: Text200
    kind: Literal["zpl_raw", "download"] = "zpl_raw"
    host: Annotated[str, StringConstraints(max_length=253)] = ""
    port: Annotated[int, Field(ge=1, le=65535)] = 9100
    dpi: Literal[203, 300, 600] = 300
    line_id: EntityId | None = None
    active: bool = True


class PrinterRecord(PrinterInput):
    id: str
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- print jobs (7.3, 7.4)

JobStatus = Literal["requested", "issued", "printed", "blocked", "reconciled", "void"]
EventKind = Literal["issued", "printed", "reprint", "used", "destroyed", "retained", "verify", "unblock"]


class PrintJobInput(MfgModel):
    item_id: EntityId
    level: Level
    lot_id: EntityId
    wo_id: EntityId | None = None
    customer: Annotated[str, StringConstraints(max_length=100)] | None = None
    qty: Annotated[int, Field(ge=1, le=1_000_000)]
    output: Literal["pdf", "zpl"] = "zpl"
    target: Literal["download", "printer"] = "download"
    printer_id: EntityId | None = None

    @model_validator(mode="after")
    def _printer(self) -> "PrintJobInput":
        if self.target == "printer" and self.printer_id is None:
            raise ValueError("a printer target names the printer")
        if self.target == "printer" and self.output != "zpl":
            raise ValueError("printers receive ZPL")
        return self


class JobTotals(MfgModel):
    issued: int = 0
    printed: int = 0
    reprinted: int = 0
    used: int = 0
    destroyed: int = 0
    retained: int = 0
    diff: int = 0


class PrintEventRecord(MfgModel):
    id: str
    job_id: str
    kind: EventKind
    qty: int
    serials: list[str] | None = None
    position: Literal["first", "last", "sample"] | None = None
    scan: str | None = None
    result: Literal["match", "mismatch"] | None = None
    mismatch: dict[str, Any] | None = None
    reason: str | None = None
    actor_id: str
    at: datetime
    client_event_id: str


class PrintJobRecord(MfgModel):
    id: str
    number: str
    item_id: str
    item_part_number: str | None = None
    level: str
    udi_id: str
    gtin: str
    lot_id: str
    lot_code: str | None = None
    wo_id: str | None = None
    template_id: str
    template_code: str
    template_version: int
    qty: int
    serials: list[str] | None = None
    data: dict[str, Any]
    data_sha256: str
    element_string: str
    hri: str
    output: Literal["pdf", "zpl"]
    target: Literal["download", "printer"]
    printer_id: str | None = None
    status: JobStatus
    totals: JobTotals
    recon_explanation: str | None = None
    reconciled_at: datetime | None = None
    verify: dict[str, Any] = Field(default_factory=dict)     # {first: bool, last: bool, mismatches: int}
    events: list[PrintEventRecord] = Field(default_factory=list)
    signatures: list[SignatureManifest] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class PrintEventInput(MfgModel):
    """L10: `printed` (confirm the count of a download), `reprint` (reason), `used`, `destroyed`, `retained`,
    `unblock` (supervisor, reason)."""
    kind: Literal["printed", "reprint", "used", "destroyed", "retained", "unblock"]
    qty: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    serials: Annotated[list[Annotated[str, StringConstraints(max_length=20)]], Field(max_length=100_000)] | None = None
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None
    client_event_id: ClientEventId


class VerifyInput(MfgModel):
    scan: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    position: Literal["first", "last", "sample"] = "sample"
    client_event_id: ClientEventId


class VerifyResult(MfgModel):
    result: Literal["match", "mismatch"]
    mismatch: dict[str, Any] = Field(default_factory=dict)    # {field: {expected, scanned}}
    parsed: ParseResult
    job: PrintJobRecord


class ReconcileInput(MfgModel):
    explanation: Annotated[str, StringConstraints(max_length=1000)] | None = None
    signature: SignatureInput | None = None


class VoidInput(MfgModel):
    reason: Reason


__all__ = ["ApproveInput", "AssignmentRow", "AssignmentsInput", "BarcodeSpec", "EventKind", "JobTotals",
           "LabelElement", "LabelTemplateInput", "LabelTemplateRecord", "ParseResult", "PiFlags", "PrintEventInput",
           "PrintEventRecord", "PrintJobInput", "PrintJobRecord", "PrinterInput", "PrinterRecord", "ReconcileInput",
           "UdiAttrs", "UdiDeviceInput", "UdiDeviceRecord", "UdiExportInput", "UdiExportRecord", "VerifyInput",
           "VerifyResult", "VoidInput"]
