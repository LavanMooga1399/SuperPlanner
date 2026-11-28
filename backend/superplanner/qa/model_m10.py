"""M10 quality contracts (M10-DESIGN 4.4, 6; frozen at S0): deviations, customer quality agreements, certificates
of analysis and batch documentation packs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..esig.model import SignatureInput, SignatureManifest
from ..mfg.model import EntityId, MfgModel

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text2000 = Annotated[str, StringConstraints(max_length=2000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Customer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Ref = Annotated[str, StringConstraints(max_length=64)]

# ---------------------------------------------------------------- deviations (4.4)


class DeviationScope(MfgModel):
    item_ids: Annotated[list[EntityId], Field(max_length=200)] = Field(default_factory=list)
    lot_ids: Annotated[list[EntityId], Field(max_length=500)] = Field(default_factory=list)
    wo_ids: Annotated[list[EntityId], Field(max_length=500)] = Field(default_factory=list)
    valid_from: date | None = None
    valid_to: date | None = None
    max_qty: Annotated[float, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _window(self) -> "DeviationScope":
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        return self


class DeviationRisk(MfgModel):
    severity: Annotated[int, Field(ge=1, le=5)] = 1
    occurrence: Annotated[int, Field(ge=1, le=5)] = 1
    rationale: Text2000 = ""


class DeviationInput(MfgModel):
    kind: Literal["planned", "unplanned"]
    title: Text200
    description: Annotated[str, StringConstraints(max_length=20_000)] = ""
    scope: DeviationScope = Field(default_factory=DeviationScope)
    risk: DeviationRisk = Field(default_factory=DeviationRisk)
    ncr_id: EntityId | None = None
    capa_id: EntityId | None = None
    external_ref: Ref | None = None
    #: created from a DHR exception (unplanned): the exception is dispositioned `deviation` by the creation
    from_exception_id: EntityId | None = None


class DeviationRecord(MfgModel):
    id: str
    number: str
    kind: Literal["planned", "unplanned"]
    title: str
    description: str
    scope: DeviationScope
    risk: DeviationRisk
    risk_score: int
    status: Literal["draft", "approved", "closed", "cancelled"]
    ncr_id: str | None = None
    capa_id: str | None = None
    author_id: str
    approved_at: datetime | None = None
    closed_at: datetime | None = None
    outcome: str | None = None
    external_ref: str | None = None
    sor: Literal["superplanner", "external"] = "superplanner"
    used_qty: float = 0.0                     # received qty of lots in scope (4.4)
    signatures: list[SignatureManifest] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    people: dict[str, str] = Field(default_factory=dict)
    row_version: int
    created_at: datetime
    updated_at: datetime


class DeviationApproveInput(MfgModel):
    signature: SignatureInput | None = None


class DeviationCloseInput(MfgModel):
    outcome: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    cancel: bool = False


# ---------------------------------------------------------------- customer agreements, CoA (6)

class Spec(MfgModel):
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    unit: Annotated[str, StringConstraints(max_length=16)] = ""


class CoaCharacteristic(MfgModel):
    item_id: EntityId | None = None
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    label: Text200
    label_fr: Annotated[str, StringConstraints(max_length=200)] = ""
    report: Literal["value", "summary", "pass"] = "value"
    spec: Spec | None = None                 # customer override; None = the inspection plan's spec


class CoaSpecInput(MfgModel):
    characteristics: Annotated[list[CoaCharacteristic], Field(max_length=100)] = Field(default_factory=list)
    statement: Text2000 = ""
    statement_fr: Text2000 = ""
    language: Literal["en", "fr", "en_fr"] = "en"


PackDoc = Literal["coa", "coc", "dhr_summary", "dhr_full", "ster_cert", "genealogy", "label_specimen"]


class PackSpec(MfgModel):
    documents: Annotated[list[PackDoc], Field(max_length=7)] = Field(default_factory=lambda: ["coa", "coc"])
    per: Literal["lot", "shipment"] = "lot"


class AgreementInput(MfgModel):
    customer: Customer
    title: Text200
    external_ref: Ref = ""
    item_ids: Annotated[list[EntityId], Field(max_length=500)] = Field(default_factory=list)
    coa: CoaSpecInput = Field(default_factory=CoaSpecInput)
    pack: PackSpec = Field(default_factory=PackSpec)
    effective_from: date | None = None


class AgreementRecord(AgreementInput):
    id: str
    number: str
    version: int
    status: Literal["draft", "approved", "obsolete"]
    supersedes_id: str | None = None
    signatures: list[SignatureManifest] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class CoaInput(MfgModel):
    lot_id: EntityId
    agreement_id: EntityId
    demand_line_id: EntityId | None = None


class CoaLine(MfgModel):
    code: str
    label: str
    label_fr: str = ""
    report: Literal["value", "summary", "pass"]
    spec: Spec | None = None
    spec_source: Literal["customer", "plan", "none"]
    n: int
    defects: int
    mean: float | None = None
    min: float | None = None
    max: float | None = None
    conforms: bool
    result_text: str


class CoaRecord(MfgModel):
    id: str
    number: str
    agreement_id: str
    agreement_number: str | None = None
    agreement_version: int
    lot_id: str
    lot_code: str | None = None
    item_id: str | None = None
    dhr_id: str
    dhr_number: str | None = None
    customer: str
    demand_line_id: str | None = None
    content: dict[str, Any]                  # {lines: [CoaLine], statement, language, lot, item, dhr, expiry}
    content_sha256: str
    status: Literal["draft", "approved", "void"]
    void_reason: str | None = None
    rendition: dict[str, Any] | None = None
    signatures: list[SignatureManifest] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class SignInput(MfgModel):
    signature: SignatureInput | None = None


class VoidInput(MfgModel):
    reason: Reason


class BatchPackInput(MfgModel):
    agreement_id: EntityId
    lot_ids: Annotated[list[EntityId], Field(min_length=1, max_length=50)]
    demand_line_id: EntityId | None = None


class PackDocument(MfgModel):
    kind: str
    lot_id: str | None = None
    ref_id: str | None = None
    filename: str
    sha256: str
    size: int


class BatchPackRecord(MfgModel):
    id: str
    number: str
    agreement_id: str
    lot_ids: list[str]
    customer: str
    demand_line_id: str | None = None
    status: Literal["building", "ready", "failed"]
    documents: list[PackDocument] = Field(default_factory=list)
    rendition: dict[str, Any] | None = None
    manifest_sha256: str | None = None
    error: str | None = None
    row_version: int
    created_at: datetime
    updated_at: datetime


__all__ = ["AgreementInput", "AgreementRecord", "BatchPackInput", "BatchPackRecord", "CoaCharacteristic",
           "CoaInput", "CoaLine", "CoaRecord", "CoaSpecInput", "DeviationApproveInput", "DeviationCloseInput",
           "DeviationInput", "DeviationRecord", "DeviationRisk", "DeviationScope", "PackDocument", "PackSpec",
           "SignInput", "Spec", "VoidInput"]
