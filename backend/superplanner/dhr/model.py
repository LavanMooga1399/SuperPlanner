"""eDHR contracts (M10-DESIGN 4; frozen at S0): sections, exceptions, records, review queue, inputs.

The record content (`DhrContent`) is the canonical JSON of twelve sections; each section has its own sha256
(`section_hashes`) and the content hash is the sha256 of the canonical JSON of all sections (M7 4.2 rules,
`esig.content.canonical`). Bulk lists (serial numbers, raw floor events) are not part of the stored content; the
`serials` section holds the count, ranges and the sha256 of the full list (JSON export / paged API carry the list).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..esig.model import SignatureInput, SignatureManifest
from ..mfg.model import EntityId, MfgModel

SECTIONS: tuple[str, ...] = ("header", "materials", "operations", "equipment", "inspections", "nonconformance",
                             "sterilisation", "labels", "serials", "genealogy", "holds", "review")
Section = Literal["header", "materials", "operations", "equipment", "inspections", "nonconformance",
                  "sterilisation", "labels", "serials", "genealogy", "holds", "review"]
Severity = Literal["major", "minor", "info"]
DhrStatus = Literal["open", "assembled", "in_review", "released", "rejected"]
SubjectKind = Literal["lot", "wo"]
Disposition = Literal["accepted", "ncr", "deviation"]
EXCEPTION_CODES: tuple[str, ...] = (
    "DHR_NCR", "DHR_DEVIATION", "DHR_CORRECTION", "DHR_OVERRIDE", "DHR_TIME_WINDOW", "DHR_YIELD", "DHR_QTY_BALANCE",
    "DHR_LATE_ENTRY", "DHR_CAL", "DHR_MATERIAL_HOLD", "DHR_GENEALOGY_POSSIBLE", "DHR_STER", "DHR_LABEL_RECON",
    "DHR_POST_RELEASE")
Comment = Annotated[str, StringConstraints(max_length=1000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class DhrContent(MfgModel):
    """The twelve sections (4.1). Rows are plain JSON objects; their keys are listed per section in
    `api/mfg/fixtures/example_m10.json` (`dhr_record.content`)."""
    header: dict[str, Any]
    materials: dict[str, Any]          # {lines: [...], possible_edges: int}
    operations: dict[str, Any]         # {operations: [{seq, name, events: [...], ...}]}
    equipment: dict[str, Any]          # {equipment: [...]}
    inspections: dict[str, Any]        # {lots: [...]}
    nonconformance: dict[str, Any]     # {ncrs: [...], deviations: [...]}
    sterilisation: dict[str, Any]      # {required: bool, loads: [...]}
    labels: dict[str, Any]             # {jobs: [...]}
    serials: dict[str, Any]            # {count, ranges: [[from, to]], list_sha256}
    genealogy: dict[str, Any]          # {backward: [...], forward: [...]}
    holds: dict[str, Any]              # {holds: [...]}
    review: dict[str, Any]             # {exceptions: [...], signatures: [...]} (dispositions, not hashed live state)


class DhrException(MfgModel):
    id: str
    record_id: str
    code: str
    severity: Severity
    section: Section
    ref_type: str
    ref_id: str | None = None
    ref_number: str | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    disposition: Disposition | None = None
    disposition_ref: str | None = None
    disposition_ref_number: str | None = None
    comment: str | None = None
    carried: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    allowed: list[Disposition] = Field(default_factory=list)     # empty for `info`
    needs_disposition: bool                                       # major / minor without a disposition
    row_version: int


class Blocking(MfgModel):
    """One reason a record is not releasable (409 `DHR_NOT_RELEASABLE`, `details.blocking[]`)."""
    code: Literal["EXCEPTION_OPEN", "NCR_OPEN", "DEVIATION_NOT_APPROVED", "FINAL_INSPECTION", "STERILITY_HOLD",
                  "LABEL_NOT_RECONCILED", "DHR_STALE"]
    message: str
    ref_type: str | None = None
    ref_id: str | None = None
    ref_number: str | None = None


class Releasable(MfgModel):
    ok: bool
    blocking: list[Blocking] = Field(default_factory=list)


class DhrCounts(MfgModel):
    major: int = 0
    minor: int = 0
    info: int = 0
    open: int = 0                         # major / minor without a disposition


class ItemRef(MfgModel):
    id: str
    part_number: str | None = None
    revision: str | None = None
    name: str | None = None


class DhrVersion(MfgModel):
    id: str
    version: int
    status: DhrStatus
    content_sha256: str
    section_hashes: dict[str, str]
    assembled_at: datetime
    changed_after_release: bool
    reassemble_reason: str | None = None


class RenditionRef(MfgModel):
    id: str
    kind: Literal["pdf", "json", "zip", "zpl", "csv", "xlsx"]
    filename: str
    sha256: str
    size: int
    renderer_version: str
    created_at: datetime
    warnings: list[str] = Field(default_factory=list)


class DhrSummary(MfgModel):
    """List row (D1) and review queue row."""
    id: str
    number: str
    version: int
    subject_kind: SubjectKind
    lot_id: str | None = None
    lot_code: str | None = None
    wo_ids: list[str]
    wo_numbers: list[str]
    item: ItemRef
    status: DhrStatus
    changed_after_release: bool
    superseded_by_id: str | None = None
    assembled_at: datetime
    age_days: float
    counts: DhrCounts
    released_at: datetime | None = None
    decision: Literal["released", "rejected"] | None = None
    row_version: int


class DhrRecord(DhrSummary):
    """D2 (stored version) and D3 (live, `id` = "live", `status` = "open", not stored)."""
    item_revision: dict[str, Any]
    content: DhrContent
    content_sha256: str
    section_hashes: dict[str, str]
    exceptions: list[DhrException]
    signatures: list[SignatureManifest] = Field(default_factory=list)
    versions: list[DhrVersion] = Field(default_factory=list)
    supersedes_id: str | None = None
    hold_id: str | None = None
    hold_open: bool = False
    dhr_required: bool
    releasable: Releasable
    renditions: list[RenditionRef] = Field(default_factory=list)
    renderer_version: str | None = None
    reassemble_reason: str | None = None


class SectionPage(MfgModel):
    """D5: one section, its bulk list paged (serials, operation events)."""
    record_id: str
    section: Section
    sha256: str
    data: dict[str, Any]
    items: list[Any] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    limit: int = 500


class ReviewQueueRow(MfgModel):
    """D10: records waiting for review, oldest first."""
    id: str
    number: str
    version: int
    status: DhrStatus
    item: ItemRef
    lot_code: str | None = None
    line_codes: list[str] = Field(default_factory=list)
    open_major: int
    open_minor: int
    oldest_exception_age_days: float
    age_days: float
    changed_after_release: bool
    reviewer_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- inputs

class DhrAssembleInput(MfgModel):
    """D4: assemble (or re-assemble) the record of a lot or a WO."""
    lot_id: EntityId | None = None
    wo_id: EntityId | None = None
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None

    @model_validator(mode="after")
    def _one(self) -> "DhrAssembleInput":
        if (self.lot_id is None) == (self.wo_id is None):
            raise ValueError("give exactly one of lot_id or wo_id")
        return self


class DispositionInput(MfgModel):
    """D6: disposition of one exception (If-Match = the exception's row_version; reason in Part 11 mode)."""
    disposition: Disposition
    disposition_ref: EntityId | None = None      # the NCR / deviation id for `ncr` / `deviation`
    comment: Comment = ""

    @model_validator(mode="after")
    def _ref(self) -> "DispositionInput":
        if self.disposition in ("ncr", "deviation") and self.disposition_ref is None:
            raise ValueError("an ncr / deviation disposition references the record (disposition_ref)")
        return self


class DhrReleaseInput(MfgModel):
    """D8: release or reject (signed `dhr.release`; the last step's meaning decides: released / rejected)."""
    decision: Literal["released", "rejected"]
    ncr_id: EntityId | None = None               # required for `rejected`
    note: Annotated[str, StringConstraints(max_length=500)] = ""
    signature: SignatureInput | None = None

    @model_validator(mode="after")
    def _ncr(self) -> "DhrReleaseInput":
        if self.decision == "rejected" and self.ncr_id is None:
            raise ValueError("a rejected record names the NCR (ncr_id)")
        return self


class StartReviewInput(MfgModel):
    note: Annotated[str, StringConstraints(max_length=500)] = ""


__all__ = ["Blocking", "DhrAssembleInput", "DhrContent", "DhrCounts", "DhrException", "DhrRecord",
           "DhrReleaseInput", "DhrSummary", "DhrVersion", "DispositionInput", "EXCEPTION_CODES", "ItemRef",
           "Releasable", "RenditionRef", "ReviewQueueRow", "SECTIONS", "SectionPage", "StartReviewInput"]
