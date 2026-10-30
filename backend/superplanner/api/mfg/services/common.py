"""Shared helpers of the mfg services (M1-DESIGN 9.1, 9.2, 6.1).

- `write_tx(ctx)`: `ctx.write_guard()` + one transaction + `repo.lock_plant` first (the per-owner mutex, bumps
  `data_version`); a Postgres lock timeout (SQLSTATE 55P03) becomes 409 `MFG_BUSY` with `Retry-After: 5`.
- `check_version`: If-Match after the owned lookup (428 / 412 with `current_version`).
- `jsonable`: fast JSON conversion of records built with `model_construct` (UTC stamps as `Z`, plant-time values
  with their offset, dates `YYYY-MM-DD`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ....mfg.calendar import offset_tz
from ...context import AppContext
from ...errors import ApiError
from ...schemas import iso_utc
from ...services.problem_service import audit as _audit
from ...services.problem_service import parse_if_match
from .. import repo
from ..db_models import MfgPlantRow

API = "/api/v1/mfg"
BUSY_MESSAGE = "Another change to your manufacturing data is still being saved. Try again in a moment."


def jsonable(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return {k: jsonable(x) for k, x in v.__dict__.items()}
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, datetime):
        off = v.utcoffset()
        if off is None or off.total_seconds() == 0:
            return iso_utc(v)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def respond(record: Any, status: int = 200, location: str | None = None, etag: bool = True) -> JSONResponse:
    body = jsonable(record)
    headers: dict[str, str] = {}
    if etag and isinstance(body, dict) and "row_version" in body:
        headers["ETag"] = f'"{body["row_version"]}"'
    if location:
        headers["Location"] = f"{API}{location}"
    return JSONResponse(body, status_code=status, headers=headers)


def is_lock_timeout(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) == "55P03" or type(orig).__name__ == "LockNotAvailable"


def busy() -> ApiError:
    return ApiError(409, "MFG_BUSY", BUSY_MESSAGE, {}, headers={"Retry-After": "5"})


@contextmanager
def write_tx(ctx: AppContext, *, lock: bool = True) -> Iterator[tuple[Session, MfgPlantRow | None]]:
    """One mfg write transaction. `lock=True` (master data): lock the plant row first (creating it if absent)."""
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            plant = repo.lock_plant(s) if lock else None
            yield s, plant
    except DBAPIError as exc:
        if is_lock_timeout(exc):
            raise busy() from None
        raise


@contextmanager
def read_tx(ctx: AppContext) -> Iterator[Session]:
    try:
        with ctx.db.read() as s:
            yield s
    except DBAPIError as exc:
        if is_lock_timeout(exc):
            raise busy() from None
        raise


def check_version(row: Any, if_match: str | None, *, current: int | None = None) -> int:
    expected = parse_if_match(if_match)
    cur = row.row_version if current is None else current
    if expected != cur:
        raise ApiError(412, "VERSION_MISMATCH",
                       f"This was changed elsewhere (now version {cur}, you edited {expected}). Reload and try again.",
                       {"current_version": cur})
    return expected


def touch(row: Any, now: datetime | None = None) -> None:
    row.row_version = (row.row_version or 0) + 1
    row.updated_at = now or datetime.now(UTC)


def audit(s: Session, entity: str, entity_id: str | None, action: str, details: dict[str, Any] | None = None
          ) -> None:
    _audit(s, f"mfg_{entity}", entity_id or "-", action, details or {})


def duplicate(what: str, key: dict[str, Any], existing_id: str) -> ApiError:
    desc = ", ".join(f"{k.replace('_', ' ')} {v!r}" for k, v in key.items())
    return ApiError(409, "MFG_DUPLICATE_KEY", f"{what} with {desc} already exists.",
                    {"key": jsonable(key), "existing_id": existing_id})


def ensure_unique(s: Session, model: Any, what: str, key: dict[str, Any], exclude_id: str | None = None) -> None:
    q = select(model.id).where(*[getattr(model, k) == v for k, v in key.items()])
    if exclude_id is not None:
        q = q.where(model.id != exclude_id)
    found = s.execute(q.limit(1)).scalar()
    if found is not None:
        raise duplicate(what, key, found)


def check_limit(s: Session, model: Any, limit: int, what: str, adding: int = 1) -> None:
    n = int(s.execute(select(func.count()).select_from(model)).scalar() or 0)
    if n + adding > limit:
        raise ApiError(422, "MFG_LIMIT", f"You can have at most {limit} {what}.", {"limit": limit, "count": n})


def unknown_ref(loc: list[Any], ident: str, what: str = "Referenced record") -> ApiError:
    return ApiError(422, "MFG_UNKNOWN_REFERENCE", f"{what} {ident!r} was not found.", {"loc": loc, "id": ident})


def in_use(what: str, refs: dict[str, int]) -> ApiError:
    refs = {k: v for k, v in refs.items() if v}
    text = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in refs.items())
    return ApiError(409, "MFG_IN_USE", f"{what} is still in use ({text}).", {"references": refs})


def count(s: Session, model: Any, *where: Any) -> int:
    return int(s.execute(select(func.count()).select_from(model).where(*where)).scalar() or 0)


def plant_today(plant: Any) -> date:
    """Local date in plant time (M3 5): a plant row/record (IANA zone or fixed offset) or an offset string."""
    if isinstance(plant, str):
        return datetime.now(offset_tz(plant)).date()
    from ....mfg.tz import plant_today as _today

    return _today(plant)


def like_pattern(q: str) -> str:
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def ilike(col: Any, q: str) -> Any:
    return func.lower(col).like(func.lower(like_pattern(q)), escape="\\")
