"""Identity contract (M5-DESIGN 3.1-3.3; frozen at S0)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


Code6 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]
RecoveryCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=32)]


class AuthConfig(BaseModel):
    mode: Literal["accounts", "single_user"]
    sso_enabled: bool
    sso_label: str = ""
    sso_required_domains: list[str] = Field(default_factory=list)
    password_login: bool = True


class TotpSetupOut(BaseModel):
    secret: str                          # base32, shown once
    otpauth_uri: str


class TotpCodeIn(_In):
    code: Code6


class TotpLoginIn(_In):
    pending_token: Annotated[str, StringConstraints(min_length=20, max_length=100)]
    code: Code6 | None = None
    recovery_code: RecoveryCode | None = None


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]            # shown once


class TotpStatus(BaseModel):
    enabled: bool
    enabled_at: datetime | None = None
    recovery_codes_left: int = 0
    required_by_org: bool = False


TokenScope = Annotated[str, StringConstraints(pattern=r"^[a-z_.]{2,40}$")]


class TokenIn(_In):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    kind: Literal["personal", "plant"] = "personal"
    scopes: Annotated[list[TokenScope], Field(min_length=1, max_length=40)]
    workspace_owner_id: Annotated[str, StringConstraints(max_length=64)] | None = None   # None: own workspace
    expires_days: Annotated[int, Field(ge=1, le=366)] = 90


class TokenRecord(BaseModel):
    id: str
    kind: Literal["personal", "plant"]
    name: str
    prefix: str
    scopes: list[str]
    workspace_owner_id: str
    expires_at: datetime
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class TokenCreated(TokenRecord):
    token: str                           # spt_..., shown once
