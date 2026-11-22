"""Per-user UI preferences (docs/UX-STANDARD.md "Backend support"): `GET /me/preferences`,
`GET|PUT|DELETE /me/preferences/{key}`.

One small JSON document per (signed-in user, key): table column layouts, saved filter views, theme / density.
Personal: keyed by the session user, never by the workspace (`X-SP-Workspace` is ignored), so a person's layout
follows them across browsers and plants. API tokens are refused (403 TOKEN_SCOPE). Optimistic concurrency with
`row_version` (ETag / If-Match). No audit events: UI state is not business data, is written on every column drag,
and is visible only to its owner (see ARCHITECTURE implementation notes).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select

from ..context import AppContext, get_ctx
from ..errors import ApiError
from ..mfg.db_models_ux import UserPreferenceRow
from ..schemas import iso_utc
from ..services.problem_service import parse_if_match

router = APIRouter(prefix="/me", tags=["me"])

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_DOC_BYTES = 32 * 1024
MAX_KEYS_PER_USER = 200
KEY_HELP = "1-128 characters of A-Z a-z 0-9 . _ : - starting with a letter or digit"


class PreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any


def _user(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is None:  # pragma: no cover - require_user runs first
        raise ApiError(401, "AUTH_REQUIRED", "Please sign in to continue.")
    if getattr(principal, "scopes", None) is not None:
        raise ApiError(403, "TOKEN_SCOPE", "API tokens cannot use personal preferences.", {})
    return principal.user_id


def _key(key: str) -> str:
    if not KEY_RE.match(key):
        raise ApiError(422, "VALIDATION_ERROR", f"Preference keys are {KEY_HELP}.",
                       {"errors": [{"loc": ["path", "key"], "msg": f"key must be {KEY_HELP}", "type": "value_error"}]})
    return key


def _record(r: UserPreferenceRow, with_value: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"key": r.key, "row_version": r.row_version, "size_bytes": r.size_bytes,
                           "updated_at": iso_utc(r.updated_at)}
    if with_value:
        out["value"] = r.value
    return out


def _etag(r: UserPreferenceRow, body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"ETag": f'"{r.row_version}"'})


def _not_found(key: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"Preference {key!r} was not found.", {"key": key})


@router.get("/preferences")
def list_preferences(request: Request, prefix: str | None = Query(default=None, max_length=128),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    uid = _user(request)
    P = UserPreferenceRow
    with ctx.db.read() as s:
        q = select(P).where(P.user_id == uid)
        if prefix:
            q = q.where(func.starts_with(P.key, prefix))
        rows = list(s.execute(q.order_by(P.key)).scalars())
        return JSONResponse({"items": [_record(r, with_value=False) for r in rows], "total": len(rows),
                             "limits": {"max_keys": MAX_KEYS_PER_USER, "max_bytes": MAX_DOC_BYTES}})


@router.get("/preferences/{key}")
def get_preference(key: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    uid, key = _user(request), _key(key)
    with ctx.db.read() as s:
        r = s.get(UserPreferenceRow, (uid, key))
        if r is None:
            raise _not_found(key)
        return _etag(r, _record(r))


@router.put("/preferences/{key}")
def put_preference(key: str, body: PreferenceInput, request: Request,
                   if_match: str | None = Header(default=None, alias="If-Match"),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    """Create (no If-Match, or If-Match "0") -> 201; replace (If-Match = current row_version) -> 200."""
    uid, key = _user(request), _key(key)
    raw = json.dumps(body.value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_DOC_BYTES:
        raise ApiError(413, "PREF_TOO_LARGE", f"A preference may hold at most {MAX_DOC_BYTES // 1024} KB "
                       f"({len(raw)} bytes sent).", {"max_bytes": MAX_DOC_BYTES, "size_bytes": len(raw)})
    expected = None if if_match is None or not if_match.strip() else parse_if_match(if_match)
    now = datetime.now(UTC)
    from ..auth.models import UserRow

    with ctx.write_guard(), ctx.db.write() as s:
        s.execute(select(UserRow.id).where(UserRow.id == uid).with_for_update())   # serialise this user's writes
        r = s.get(UserPreferenceRow, (uid, key), with_for_update=True)
        if r is None:
            if expected not in (None, 0):
                raise ApiError(412, "VERSION_MISMATCH", "This preference no longer exists. Reload and try again.",
                               {"current_version": 0})
            n = int(s.execute(select(func.count()).select_from(UserPreferenceRow)
                              .where(UserPreferenceRow.user_id == uid)).scalar() or 0)
            if n >= MAX_KEYS_PER_USER:
                raise ApiError(409, "PREF_TOO_MANY", f"At most {MAX_KEYS_PER_USER} preferences per person; delete "
                               "unused ones first.", {"max_keys": MAX_KEYS_PER_USER})
            r = UserPreferenceRow(user_id=uid, key=key, value=body.value, size_bytes=len(raw), row_version=1,
                                  created_at=now, updated_at=now)
            s.add(r)
            s.flush()
            return _etag(r, _record(r), 201)
        if expected is None:
            raise ApiError(428, "PRECONDITION_REQUIRED",
                           f'This preference exists; send its version in If-Match, e.g. If-Match: "{r.row_version}".',
                           {"current_version": r.row_version})
        if expected != r.row_version:
            raise ApiError(412, "VERSION_MISMATCH", f"This preference was changed elsewhere (now version "
                           f"{r.row_version}, you edited {expected}). Reload and try again.",
                           {"current_version": r.row_version})
        r.value, r.size_bytes, r.row_version, r.updated_at = body.value, len(raw), r.row_version + 1, now
        s.flush()
        return _etag(r, _record(r))


@router.delete("/preferences/{key}", status_code=204)
def delete_preference(key: str, request: Request, if_match: str | None = Header(default=None, alias="If-Match"),
                      ctx: AppContext = Depends(get_ctx)) -> Response:
    uid, key = _user(request), _key(key)
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(UserPreferenceRow, (uid, key), with_for_update=True)
        if r is None:
            raise _not_found(key)
        expected = parse_if_match(if_match)       # after the lookup, like the mfg check_version
        if expected != r.row_version:
            raise ApiError(412, "VERSION_MISMATCH", f"This preference was changed elsewhere (now version "
                           f"{r.row_version}). Reload and try again.", {"current_version": r.row_version})
        s.execute(delete(UserPreferenceRow).where(UserPreferenceRow.user_id == uid, UserPreferenceRow.key == key))
    return Response(status_code=204)
