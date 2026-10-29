"""Locations (M2-DESIGN 3.2, 12.3 #84-87): master data (plant lock, `data_version`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from ....mfg import limits as L
from ....mfg.model_m2 import LocationInput, LocationRecord
from ...context import AppContext
from ...db import new_id, utcnow
from .. import repo
from ..db_models_m2 import MfgInvBalanceRow, MfgInvTransactionRow, MfgLocationRow
from ..repo_m2 import location_record
from .common import (audit, check_limit, check_version, count, ensure_unique, ilike, in_use, read_tx, touch,
                     write_tx)

FIELDS = tuple(LocationInput.model_fields)


def list_locations(ctx: AppContext, q: str | None, kind: str | None, active: bool | None) -> dict[str, Any]:
    conds: list[Any] = []
    if q:
        conds.append(ilike(MfgLocationRow.code, q) | ilike(MfgLocationRow.name, q))
    if kind:
        conds.append(MfgLocationRow.kind == kind)
    if active is not None:
        conds.append(MfgLocationRow.active.is_(active))
    with read_tx(ctx) as s:
        rows = s.execute(select(MfgLocationRow).where(*conds).order_by(MfgLocationRow.code)).scalars()
        return {"items": [location_record(r) for r in rows]}


def _unique(s: Any, inp: LocationInput, exclude: str | None = None) -> None:
    ensure_unique(s, MfgLocationRow, "A location", {"code": inp.code}, exclude_id=exclude)
    if inp.external_ref is not None:
        ensure_unique(s, MfgLocationRow, "A location", {"external_ref": inp.external_ref}, exclude_id=exclude)


def _clear_default(s: Any, keep_id: str) -> None:
    now = utcnow()
    s.execute(update(MfgLocationRow).where(MfgLocationRow.receipt_default.is_(True), MfgLocationRow.id != keep_id)
              .values(receipt_default=False, row_version=MfgLocationRow.row_version + 1, updated_at=now)
              .execution_options(synchronize_session=False))


def create_location(ctx: AppContext, inp: LocationInput) -> LocationRecord:
    with write_tx(ctx) as (s, _plant):
        _unique(s, inp)
        check_limit(s, MfgLocationRow, L.MAX_LOCATIONS, "locations")
        now = utcnow()
        row = MfgLocationRow(id=new_id("loc_"), row_version=1, created_at=now, updated_at=now,
                             **{f: getattr(inp, f) for f in FIELDS})
        s.add(row)
        s.flush()
        if inp.receipt_default:
            _clear_default(s, row.id)
        audit(s, "location", row.id, "create", {"code": row.code, "version": 1})
        return location_record(row)


def update_location(ctx: AppContext, location_id: str, inp: LocationInput, if_match: str | None) -> LocationRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgLocationRow, location_id, what="Location", lock=True)
        check_version(row, if_match)
        _unique(s, inp, row.id)
        for f in FIELDS:
            setattr(row, f, getattr(inp, f))
        touch(row)
        s.flush()
        if inp.receipt_default:
            _clear_default(s, row.id)
        audit(s, "location", row.id, "update", {"version": row.row_version})
        return location_record(row)


def delete_location(ctx: AppContext, location_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgLocationRow, location_id, what="Location", lock=True)
        check_version(row, if_match)
        refs = {"balances": count(s, MfgInvBalanceRow, MfgInvBalanceRow.location_id == row.id),
                "transactions": count(s, MfgInvTransactionRow, MfgInvTransactionRow.location_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Location {row.code}", refs)
        s.delete(row)
        s.flush()
        audit(s, "location", row.id, "delete", {"code": row.code, "version": row.row_version})
