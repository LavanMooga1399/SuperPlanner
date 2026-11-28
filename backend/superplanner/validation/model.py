"""M10 validation and enterprise contracts (M10-DESIGN 8, 9; frozen at S0): validation packages and their manifest,
IQ checks, evidence uploads, the residency report and the organisation audit page."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from ..esig.model import SignatureInput, SignatureManifest
from ..mfg.model import MfgModel

PackageKind = Literal["full", "iq", "oq", "pq", "periodic", "evidence"]


class ManifestFile(MfgModel):
    path: str
    sha256: str
    size: int
    kind: str = ""                          # plan | csa | register | trace | iq | oq | pq | baseline | ...


class PackageManifest(MfgModel):
    """`manifest.json` inside the zip; `manifest.json.sha256` holds the sha256 of its canonical bytes."""
    package: str                            # VP-000001
    kind: PackageKind
    plant: str
    app_version: str
    git_sha: str
    migration_head: str
    generated_at: datetime
    baseline_sha256: str | None = None
    prev_baseline_sha256: str | None = None
    baseline_diff: list[dict[str, Any]] = Field(default_factory=list)
    files: list[ManifestFile]
    statement: str


class PackageInput(MfgModel):
    kind: Literal["full", "iq", "oq", "pq", "periodic"] = "full"
    #: OQ JUnit XML (optional, from `docker compose run --rm oq`); otherwise the trace matrix lists coverage only
    junit_xml: Annotated[str, StringConstraints(max_length=20_000_000)] | None = None
    label: Annotated[str, StringConstraints(max_length=200)] = ""


class PackageRecord(MfgModel):
    id: str
    number: str
    kind: PackageKind
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed", "approved"]
    baseline_id: str | None = None
    prev_baseline_id: str | None = None
    manifest: dict[str, Any] | None = None
    sha256: str | None = None
    size: int | None = None
    error: str | None = None
    signatures: list[SignatureManifest] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class EvidenceInput(MfgModel):
    """Q5 (JSON body or multipart `file`): an HA drill / load report / rehearsal record stored as evidence."""
    kind: Literal["ha_drill", "load_report", "ha_rehearsal", "other"]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    provisional: bool = False
    content: dict[str, Any]


class IqCheck(MfgModel):
    code: str
    label: str
    status: Literal["pass", "fail", "warn", "skip"]
    detail: str = ""
    observed: Any = None
    expected: Any = None


class IqResult(MfgModel):
    plant: str
    at: datetime
    ok: bool
    checks: list[IqCheck]


class ApproveInput(MfgModel):
    signature: SignatureInput | None = None


class ResidencyItem(MfgModel):
    kind: Literal["deployment", "org", "archive", "backup", "smtp", "logs", "ai", "endpoint", "assistant"]
    name: str
    region: str | None = None
    ok: bool
    detail: str = ""
    exception_signature_id: str | None = None


class ResidencyReport(MfgModel):
    org_id: str
    data_region: str
    deployment_region: str
    ok: bool
    mismatches: list[ResidencyItem]
    items: list[ResidencyItem]


class OrgAuditRow(MfgModel):
    id: int
    plant: str | None = None
    owner_id: str | None = None
    entity_type: str
    entity_id: str
    action: str
    actor_id: str | None = None
    created_at: datetime
    reason: str | None = None
    signature_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ApproveInput", "EvidenceInput", "IqCheck", "IqResult", "ManifestFile", "OrgAuditRow", "PackageInput",
           "PackageManifest", "PackageRecord", "ResidencyItem", "ResidencyReport"]
