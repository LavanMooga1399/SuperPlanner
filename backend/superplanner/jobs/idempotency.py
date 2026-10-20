"""`Idempotency-Key` on the four run-creating endpoints (PHASE2B 2.8).

Order inside the creation transaction (review R8): lock the plan/problem row, then `lookup()`, then the one-active
check. Same key + same request hash (owner-scoped, younger than IDEMPOTENCY_TTL_HOURS) -> `Replay` with the original
creation body (current status); other hash -> 422 IDEMPOTENCY_KEY_MISMATCH; older than the TTL -> the old job's key
is cleared in the same transaction and the request proceeds. A concurrent insert of the same key (different plans)
violates `uq_jobs_idempotency`; the service then calls `replay_after_conflict()` in a new transaction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .types import IDEMPOTENCY_KEY_RE

HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replayed"
MISMATCH_MESSAGE = "This Idempotency-Key was used for a different request."
ROUTE_KINDS = ("solver_run", "replan", "finance_run", "what_if")


@dataclass(frozen=True)
class Idempotency:
    key: str
    request_hash: str


class Replay(Exception):
    """Control flow: the request is a replay; the route answers 202 with `body` and `Idempotent-Replayed: true`."""

    def __init__(self, body: dict[str, Any]):
        super().__init__("idempotent replay")
        self.body = body


CreatedFromJob = Callable[[Session, Any], dict[str, Any]]


def request_hash(route_kind: str, path_params: dict[str, Any], body: Any) -> str:
    canonical = json.dumps({"path": path_params, "body": body}, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(f"{route_kind}\n{canonical}".encode()).hexdigest()


def from_header(raw: str | None, route_kind: str, path_params: dict[str, Any], body: Any) -> Idempotency | None:
    """None without the header; 422 VALIDATION_ERROR (`loc ["header","idempotency-key"]`) for a bad format."""
    if raw is None:
        return None
    from ..api.errors import ApiError

    if not IDEMPOTENCY_KEY_RE.match(raw):
        raise ApiError(422, "VALIDATION_ERROR", "The request is not valid.",
                       {"errors": [{"loc": ["header", "idempotency-key"],
                                    "msg": "must be 1-128 characters of A-Z a-z 0-9 . _ : -",
                                    "type": "string_pattern_mismatch"}]})
    return Idempotency(raw, request_hash(route_kind, path_params, body))


def _owner() -> str:
    from ..api.db.ownership import LOCAL_USER_ID, current_owner

    owner = current_owner()
    return owner if isinstance(owner, str) else LOCAL_USER_ID


def _mismatch() -> Exception:
    from ..api.errors import ApiError

    return ApiError(422, "IDEMPOTENCY_KEY_MISMATCH", MISMATCH_MESSAGE, {})


def lookup(s: Session, idem: Idempotency | None, ttl_hours: int, created: CreatedFromJob) -> None:
    """Inside the creation transaction, after the plan/problem lock. Raises Replay / 422 mismatch, or returns."""
    if idem is None:
        return
    from ..api.db import JobRow, utcnow

    job = s.scalars(select(JobRow).where(JobRow.owner_id == _owner(), JobRow.idempotency_key == idem.key)
                    .with_for_update()).first()
    if job is None:
        return
    created_at = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
    if created_at < utcnow() - timedelta(hours=ttl_hours):
        job.idempotency_key = None   # expired: free the key for this request (unique index)
        s.flush()
        return
    if job.request_hash != idem.request_hash:
        raise _mismatch()
    raise Replay(created(s, job))


def is_key_conflict(exc: IntegrityError) -> bool:
    from ..api.db.locks import is_unique_violation

    return is_unique_violation(exc, "uq_jobs_idempotency", "jobs.owner_id, jobs.idempotency_key")


def replay_after_conflict(ctx: Any, idem: Idempotency, created: CreatedFromJob) -> None:
    """After a `uq_jobs_idempotency` violation: re-run the lookup in a new transaction (always raises)."""
    with ctx.db.read() as s:
        lookup(s, idem, 10 ** 6, created)   # the winner was created just now: never treat it as expired
    raise _mismatch()   # pragma: no cover - the winning row vanished (plan deleted at once)


def accepted(create: Callable[[], dict[str, Any]]) -> Any:
    """Route helper: 202 with the creation body, or the replayed body + `Idempotent-Replayed: true`."""
    from fastapi.responses import JSONResponse

    try:
        return JSONResponse(create(), status_code=202)
    except Replay as replay:
        return JSONResponse(replay.body, status_code=202, headers={REPLAY_HEADER: "true"})
