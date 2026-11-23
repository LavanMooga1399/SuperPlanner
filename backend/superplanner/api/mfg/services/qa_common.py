"""Shared M7 service helpers (M7-DESIGN 9): the request's acting context (`Act`), QA settings, record decorations
(signatures, links, attachments), attachments and links."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request

from ..access import MfgPrincipal, mfg_principal
from . import m7_examples


@dataclass(frozen=True)
class Act:
    """Who acts, from where (signatures record the session reference and client address, 4.2)."""
    p: MfgPrincipal
    session_id: str | None
    client_ip: str | None

    @property
    def user_id(self) -> str:
        return self.p.user_id

    @property
    def session_ref(self) -> str | None:
        return hashlib.sha256(self.session_id.encode()).hexdigest() if self.session_id else None


async def act(request: Request, p: MfgPrincipal = Depends(mfg_principal)) -> Act:
    principal = getattr(request.state, "principal", None)
    return Act(p, getattr(principal, "session_id", None), request.client.host if request.client else None)


__getattr__ = m7_examples.module_getattr(__name__)
