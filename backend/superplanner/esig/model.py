"""M7 electronic signature contract (M7-DESIGN 4; frozen at S0): signing input, manifestations, policies, preview,
enrolment, verification, record audit trail, Part 11 mode, packages and exports, time."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..mfg.model import MfgModel

Meaning = Literal["authored", "reviewed", "approved", "released", "rejected", "verified", "performed", "closed"]
MEANINGS: tuple[str, ...] = ("authored", "reviewed", "approved", "released", "rejected", "verified", "performed",
                             "closed")
MEANING_LABELS: dict[str, dict[str, str]] = {
    "en": {"authored": "Authored", "reviewed": "Reviewed", "approved": "Approved", "released": "Released",
           "rejected": "Rejected", "verified": "Verified", "performed": "Performed", "closed": "Closed"},
    "fr-CA": {"authored": "Rédigé", "reviewed": "Révisé", "approved": "Approuvé", "released": "Libéré",
              "rejected": "Rejeté", "verified": "Vérifié", "performed": "Effectué", "closed": "Fermé"},
}
AuthLevel = Literal["password", "password_totp"]
AuthMethod = Literal["password", "password_totp", "sso", "sso_mfa"]
SignatureStatus = Literal["valid", "superseded"]
RecordType = Literal["inspection_plan", "sampling_scheme", "inspection_lot", "hold", "ncr", "capa", "complaint",
                     "field_action", "calibration", "equipment", "eco", "esig_policy", "plant", "ster_load",
                     "sop_cycle"]
RECORD_TYPES: tuple[str, ...] = ("inspection_plan", "sampling_scheme", "inspection_lot", "hold", "ncr", "capa",
                                 "complaint", "field_action", "calibration", "equipment", "eco", "esig_policy",
                                 "plant", "ster_load", "sop_cycle")
ActionName = Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,32}$")]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Comment = Annotated[str, StringConstraints(max_length=500)]
ACK_VERSION = "2026-11"
ACK_TEXT: dict[str, str] = {
    "en": "I agree that my electronic signature is the legally binding equivalent of my handwritten signature.",
    "fr-CA": "J'accepte que ma signature électronique soit l'équivalent juridiquement contraignant de ma signature "
             "manuscrite.",
}


class SignatureInput(MfgModel):
    """4.2: sent with a signable action (`signature`). Both credential components every time (11.200)."""
    meaning: Meaning
    content_hash: Hash
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None = None
    totp_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")] | None = None
    stepup_token: Annotated[str, StringConstraints(min_length=16, max_length=200)] | None = None
    comment: Comment = ""

    @model_validator(mode="after")
    def _credential(self) -> "SignatureInput":
        if self.password is None and self.stepup_token is None:
            raise ValueError("give the password (or an SSO step-up token)")
        return self


class SignatureManifest(MfgModel):
    """11.50 manifestation carried by every signable record (`signatures[]`)."""
    id: str
    meaning: Meaning
    meaning_label: str
    signer_legal_name: str
    signer_username: str
    signed_at: datetime
    signed_at_local: str                      # "2026-11-23 14:05:12 EST (UTC-05:00)"
    auth_method: AuthMethod
    action: str
    step: int
    status: SignatureStatus
    record_version: int
    comment: str = ""
    content_matches_current: bool


class PolicyStep(MfgModel):
    meaning: Meaning
    roles: Annotated[list[Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,32}$")]],
                     Field(min_length=1, max_length=10)]


class PolicyRecord(MfgModel):
    id: str
    record_type: str
    action: str
    steps: list[PolicyStep]
    auth: AuthLevel
    distinct_signers: bool
    exclude_author: bool
    version: int
    fixed: bool                               # fixed actions keep at least one step
    row_version: int
    updated_at: datetime
    signatures: list[SignatureManifest] = Field(default_factory=list)


class PolicyUpdate(MfgModel):
    steps: Annotated[list[PolicyStep], Field(min_length=0, max_length=5)]
    auth: AuthLevel
    distinct_signers: bool = True
    exclude_author: bool = False
    signature: SignatureInput | None = None


class NextStep(MfgModel):
    step: int                                 # 1-based
    meanings: list[Meaning]
    roles: list[str]
    auth: AuthLevel
    can_sign: bool                            # the caller holds a step role and is not excluded
    blocked_reason: str | None = None         # ESIG_ROLE | ESIG_SAME_SIGNER | ESIG_AUTHOR | ESIG_NOT_ENROLLED


class SummaryLine(MfgModel):
    label: str
    value: str


class PreviewResult(MfgModel):
    """E3: what will be signed (content, hash), the policy and the next step for this user."""
    record_type: str
    record_id: str
    action: str
    record_version: int
    content_hash: str
    content: dict[str, Any]
    summary: list[SummaryLine]
    required: bool                            # Part 11 mode on and a policy with steps
    part11_mode: bool
    policy: PolicyRecord | None = None
    next_step: NextStep | None = None
    signatures: list[SignatureManifest] = Field(default_factory=list)
    signer: dict[str, Any]                    # {legal_name, username, methods[], enrolled, locked_until}
    legal_statement: str


class PendingSignatures(MfgModel):
    """202 of an intermediate step (4.2 (8)): state unchanged."""
    status: Literal["pending_signatures"] = "pending_signatures"
    record_type: str
    record_id: str
    signatures: list[SignatureManifest]
    next_step: NextStep | None = None


class EnrollInput(MfgModel):
    legal_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None = None
    stepup_token: Annotated[str, StringConstraints(min_length=16, max_length=200)] | None = None
    acknowledgement: Literal[True]
    #: ESIG_LOCAL_CREDENTIALS=true and an SSO user: the signing password set now (TOTP from /auth/totp)
    signing_password: Annotated[str, StringConstraints(min_length=12, max_length=1024)] | None = None
    #: local-credentials enrolment of an SSO user: the TOTP code confirms the person (review m13)
    totp_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")] | None = None

    @model_validator(mode="after")
    def _credential(self) -> "EnrollInput":
        if self.password is None and self.stepup_token is None and self.signing_password is None:
            raise ValueError("give the password (or an SSO step-up token, or a signing password with a TOTP code)")
        return self


class EsigStatus(MfgModel):
    user_id: str
    username: str
    enrolled: bool
    legal_name: str | None = None
    enrolled_at: datetime | None = None
    ack_version: str | None = None
    revoked_at: datetime | None = None
    locked_until: datetime | None = None
    methods: list[AuthMethod]                 # what this person can sign with now
    totp_enabled: bool
    sso_user: bool
    local_credentials: bool                   # ESIG_LOCAL_CREDENTIALS fallback in use for this person
    can_sign: bool                            # person, enrolled, not revoked, not locked
    acknowledgement: dict[str, str]           # {version, en, fr-CA}


class VerifyResult(MfgModel):
    signature_id: str
    mac_ok: bool
    chain_ok: bool
    content_hash_ok: bool
    content_matches_current: bool
    record_version_signed: int
    record_version_current: int | None = None
    current_hash: str | None = None


class AuditChange(MfgModel):
    path: str
    old: Any = None
    new: Any = None
    old_sha256: str | None = None
    new_sha256: str | None = None


class AuditRecordEvent(MfgModel):
    id: int
    at: datetime
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    entity_type: str
    entity_id: str
    record_version: int | None = None
    reason: str | None = None
    changes: list[AuditChange] = Field(default_factory=list)
    signature: SignatureManifest | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AuditRecordPage(MfgModel):
    entity_type: str
    entity_id: str
    items: list[AuditRecordEvent]
    total: int
    limit: int
    offset: int


class Part11ModeRecord(MfgModel):
    enabled: bool
    enabled_at: datetime | None = None
    enabled_by: str | None = None
    enabled_by_name: str | None = None
    signatures: list[SignatureManifest] = Field(default_factory=list)
    esig_enabled: bool
    secrets_configured: bool
    clock_skew_ms: float | None = None
    max_clock_skew_ms: float


class Part11ModeInput(MfgModel):
    enabled: Literal[True]
    signature: SignatureInput | None = None


class Part11Package(MfgModel):
    record_type: str
    record_id: str
    record: dict[str, Any]
    signatures: list[SignatureManifest]
    audit: list[AuditRecordEvent]
    attachments: list[dict[str, Any]]         # [{id, filename, size, sha256}]
    links: list[dict[str, Any]]
    generated_at: datetime
    generated_by: str
    package_sha256: str


class Part11ExportInput(MfgModel):
    from_: date = Field(alias="from")
    to: date
    record_types: Annotated[list[RecordType], Field(min_length=0, max_length=20)] = Field(default_factory=list)

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def _range(self) -> "Part11ExportInput":
        if self.to < self.from_:
            raise ValueError("'to' must not be before 'from'")
        return self


class Part11ExportRecord(MfgModel):
    id: str
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed"]
    manifest: dict[str, Any] | None = None
    sha256: str | None = None
    error: str | None = None
    requested_by: str
    created_at: datetime
    finished_at: datetime | None = None
    download_url: str | None = None


class TimeInfo(MfgModel):
    app_utc: datetime
    db_utc: datetime
    skew_ms: float
    max_skew_ms: float
    ok: bool
