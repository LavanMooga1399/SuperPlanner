"""M6 push contract (M6-DESIGN 2; frozen at S0)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from ..mfg.model import MfgModel

Topic = Literal["critical_alerts", "approvals", "digest_ready"]
TOPICS: tuple[str, ...] = ("critical_alerts", "approvals", "digest_ready")
B64U = Annotated[str, StringConstraints(strip_whitespace=True, min_length=16, max_length=200,
                                        pattern=r"^[A-Za-z0-9_-]+={0,2}$")]


class PushKeys(MfgModel):
    p256dh: B64U
    auth: B64U


class PushSubscriptionInput(MfgModel):
    endpoint: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]
    keys: PushKeys
    topics: Annotated[list[Topic], Field(min_length=1, max_length=3)] = Field(
        default_factory=lambda: ["critical_alerts", "approvals"])

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.lower().startswith("https://"):
            raise ValueError("endpoint must be an https:// URL")
        return v


class PushSubscriptionRecord(MfgModel):
    id: str
    endpoint_host: str
    topics: list[Topic]
    user_agent: str = ""
    created_at: datetime
    active: bool = True


class VapidPublicKey(MfgModel):
    enabled: bool
    public_key: str | None = None
    topics: list[Topic] = Field(default_factory=lambda: list(TOPICS))   # type: ignore[arg-type]


class PushPayload(MfgModel):
    """What the service worker receives (2: title, short body, link path only)."""
    title: Annotated[str, StringConstraints(max_length=120)]
    body: Annotated[str, StringConstraints(max_length=240)] = ""
    link: Annotated[str, StringConstraints(max_length=300, pattern=r"^/")] = "/m"
    topic: Topic
    tag: str | None = None
