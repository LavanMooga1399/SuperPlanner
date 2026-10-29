"""Shared helpers of the M2 services (M2-DESIGN 4.5, 12.1).

- `run_tx(ctx, fn, lock=False)`: one write transaction (`write_tx`); a deadlock (40P01) or serialization failure
  (40001) retries the whole transaction once, then 409 `MFG_BUSY`; lock timeouts are 409 `MFG_BUSY` (M1).
  Transactional writes do not take the plant lock (`lock=False`); master writes do.
- `rule_error`: a pure-rule `RuleError` -> `ApiError`.
- ref builders (items, locations, lots, actors) with one statement per kind.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ....mfg.dataset import item_ref
from ....mfg.model import ItemRef, PlantRecord
from ....mfg.model_m2 import EPS, LocationRef, LotRef
from ....mfg.purchasing import RuleError
from ....mfg.units import is_count
from ...context import AppContext
from ...db.ownership import current_actor, current_owner
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow, MfgPlantRow
from ..db_models_m2 import MfgLocationRow, MfgLotRow
from .common import busy, plant_today, write_tx

T = TypeVar("T")


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None)


def run_tx(ctx: AppContext, fn: Callable[[Session], T], *, lock: bool = False) -> T:
    for attempt in (0, 1):
        try:
            with write_tx(ctx, lock=lock) as (s, _plant):
                return fn(s)
        except DBAPIError as exc:
            if _sqlstate(exc) in ("40P01", "40001"):
                if attempt == 0:
                    continue
                raise busy() from None
            raise
    raise busy()  # pragma: no cover


def rule_error(e: RuleError) -> ApiError:
    return ApiError(e.status, e.code, e.message, dict(e.details))


def actor_id() -> str:
    a = current_actor() or current_owner()
    return a if isinstance(a, str) else "usr_local"


def is_workspace_owner() -> bool:
    a = current_actor()
    return a is None or a == current_owner()


def plant(s: Session) -> PlantRecord:
    return repo.plant_or_default(s)


def today(s: Session) -> date:
    return plant_today(plant(s).utc_offset)


def plant_lock_free(s: Session) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow)).scalars().first()


def items(s: Session, ids: Iterable[str]) -> dict[str, MfgItemRow]:
    out: dict[str, MfgItemRow] = {}
    ids = sorted({i for i in ids if i})
    for k in range(0, len(ids), 2000):
        for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(ids[k:k + 2000]))).scalars():
            out[r.id] = r
    return out


def iref(row: MfgItemRow | None, item_id: str = "") -> ItemRef:
    if row is None:
        return ItemRef.model_construct(id=item_id, part_number="?", revision="", description="", uom="EA",
                                       make_buy="buy", active=False)
    return ItemRef.model_construct(id=row.id, part_number=row.part_number, revision=row.revision,
                                   description=row.description, uom=row.uom, make_buy=row.make_buy, active=row.active)


def item_refs(s: Session, ids: Iterable[str]) -> dict[str, ItemRef]:
    rows = items(s, ids)
    return {i: iref(r, i) for i, r in rows.items()}


def locations(s: Session, ids: Iterable[str] | None = None) -> dict[str, MfgLocationRow]:
    q = select(MfgLocationRow)
    if ids is not None:
        q = q.where(MfgLocationRow.id.in_(sorted(set(ids))))
    return {r.id: r for r in s.execute(q).scalars()}


def lref(row: MfgLocationRow | None, loc_id: str = "") -> LocationRef:
    if row is None:
        return LocationRef.model_construct(id=loc_id, code="?", name="", kind="stores")
    return LocationRef.model_construct(id=row.id, code=row.code, name=row.name, kind=row.kind)


def lots(s: Session, ids: Iterable[str]) -> dict[str, MfgLotRow]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {r.id: r for r in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(ids))).scalars()}


def lotref(row: MfgLotRow | None) -> LotRef | None:
    if row is None:
        return None
    return LotRef.model_construct(id=row.id, lot_code=row.lot_code, expires_on=row.expires_on, hold=row.hold)


def user_names(s: Session, ids: Iterable[str]) -> dict[str, str]:
    from ...auth.models import UserRow
    from ...db.ownership import system_scope

    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    with system_scope():
        rows = s.execute(select(UserRow.id, UserRow.display_name, UserRow.email).where(UserRow.id.in_(ids))).all()
    return {r[0]: (r[1] or r[2] or ("Local user" if r[0] == "usr_local" else r[0])) for r in rows}


def actor_ref(names: dict[str, str], uid: str | None) -> dict[str, Any]:
    return {"id": uid, "name": names.get(uid or "", uid or "")}


def check_whole(it: Any, qty: float, loc: list[Any]) -> None:
    if is_count(it.uom) and abs(qty - round(qty)) > EPS:
        raise ApiError(422, "INV_FRACTIONAL_QTY", f"{it.part_number} is counted in {it.uom}; use a whole number.",
                       {"loc": loc})


def r6(x: float | None) -> float | None:
    return None if x is None else round(float(x), 6)


def request_hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def page(items_: list[Any], total: int, limit: int, offset: int, **extra: Any) -> dict[str, Any]:
    return {"items": items_, "total": total, "limit": limit, "offset": offset, **extra}


def validation(loc: list[Any], msg: str) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", msg, {"errors": [{"loc": loc, "msg": msg, "type": "value_error"}]})


__all__ = ["actor_id", "actor_ref", "check_whole", "iref", "is_workspace_owner", "item_ref", "item_refs", "items",
           "locations", "lotref", "lots", "lref", "page", "plant", "r6", "request_hash", "rule_error", "run_tx",
           "today", "user_names", "validation"]
