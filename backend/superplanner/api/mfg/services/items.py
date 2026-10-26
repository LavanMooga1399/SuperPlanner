"""Items (M1-DESIGN 3.4, 9.3 #5-9): paginated list with search/filters (<= 5 statements), CRUD, delete-in-use."""

from __future__ import annotations

from typing import Any

from sqlalchemy import distinct, exists, func, select
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.model import ItemInput, ItemRecord
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgBomLineRow, MfgBomRow, MfgItemRow, MfgRoutingRow
from .common import (audit, check_limit, check_version, count, ensure_unique, ilike, in_use, read_tx, touch,
                     write_tx)

ITEM_FIELDS = tuple(ItemInput.model_fields)


def flags(s: Session, ids: list[str]) -> tuple[set[str], set[str], dict[str, int]]:
    """has_bom, has_routing and used_in_count for the given item ids (3 statements)."""
    if not ids:
        return set(), set(), {}
    has_bom = set(s.execute(select(MfgBomRow.item_id).where(MfgBomRow.item_id.in_(ids),
                                                            MfgBomRow.status != "obsolete").distinct()).scalars())
    has_rtg = set(s.execute(select(MfgRoutingRow.item_id).where(MfgRoutingRow.item_id.in_(ids),
                                                                MfgRoutingRow.status != "obsolete").distinct())
                  .scalars())
    used = dict(s.execute(select(MfgBomLineRow.child_item_id, func.count(distinct(MfgBomRow.item_id)))
                          .join(MfgBomRow, MfgBomRow.id == MfgBomLineRow.bom_id)
                          .where(MfgBomLineRow.child_item_id.in_(ids), MfgBomRow.status != "obsolete")
                          .group_by(MfgBomLineRow.child_item_id)).all())
    return has_bom, has_rtg, {k: int(v) for k, v in used.items()}


def record(s: Session, row: MfgItemRow) -> ItemRecord:
    hb, hr, used = flags(s, [row.id])
    return repo.to_record(row, has_bom=row.id in hb, has_routing=row.id in hr, used_in_count=used.get(row.id, 0))


def list_items(ctx: AppContext, *, q: str | None, make_buy: str | None, family: str | None, active: bool | None,
               has_bom: bool | None, has_routing: bool | None, sort: str, limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if q:
        conds.append(ilike(MfgItemRow.part_number, q) | ilike(MfgItemRow.description, q))
    if make_buy:
        conds.append(MfgItemRow.make_buy == make_buy)
    if family:
        conds.append(MfgItemRow.family == family)
    if active is not None:
        conds.append(MfgItemRow.active.is_(active))
    if has_bom is not None:
        e = exists().where(MfgBomRow.item_id == MfgItemRow.id, MfgBomRow.status != "obsolete")
        conds.append(e if has_bom else ~e)
    if has_routing is not None:
        e = exists().where(MfgRoutingRow.item_id == MfgItemRow.id, MfgRoutingRow.status != "obsolete")
        conds.append(e if has_routing else ~e)
    order = {"part_number": (MfgItemRow.part_number, MfgItemRow.id),
             "-updated_at": (MfgItemRow.updated_at.desc(), MfgItemRow.id.desc()),
             "description": (MfgItemRow.description, MfgItemRow.part_number, MfgItemRow.id)}[sort]
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgItemRow).where(*conds).order_by(*order).limit(limit).offset(offset))
                    .scalars())
        total = int(s.execute(select(func.count()).select_from(MfgItemRow).where(*conds)).scalar() or 0)
        hb, hr, used = flags(s, [r.id for r in rows])
        items = [repo.to_record(r, has_bom=r.id in hb, has_routing=r.id in hr, used_in_count=used.get(r.id, 0))
                 for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _apply(row: MfgItemRow, inp: ItemInput) -> None:
    for f in ITEM_FIELDS:
        v = getattr(inp, f)
        setattr(row, f, dict(v) if f == "attributes" else v)


def create_item(ctx: AppContext, inp: ItemInput) -> ItemRecord:
    with write_tx(ctx) as (s, _plant):
        ensure_unique(s, MfgItemRow, "An item", {"part_number": inp.part_number})
        check_limit(s, MfgItemRow, L.MAX_ITEMS, "items")
        now = utcnow()
        row = MfgItemRow(id=new_id("itm_"), row_version=1, created_at=now, updated_at=now)
        _apply(row, inp)
        s.add(row)
        s.flush()
        audit(s, "item", row.id, "create", {"version": 1})
        return repo.to_record(row)


def get_item(ctx: AppContext, item_id: str) -> ItemRecord:
    with read_tx(ctx) as s:
        return record(s, repo.get_row(s, MfgItemRow, item_id, what="Item"))


def update_item(ctx: AppContext, item_id: str, inp: ItemInput, if_match: str | None) -> ItemRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgItemRow, item_id, what="Item", lock=True)
        check_version(row, if_match)
        ensure_unique(s, MfgItemRow, "An item", {"part_number": inp.part_number}, exclude_id=row.id)
        if row.serialized and not inp.serialized:
            _check_no_serial_documents(s, row)
        _apply(row, inp)
        touch(row)
        s.flush()
        audit(s, "item", row.id, "update", {"version": row.row_version})
        return record(s, row)


def _check_no_serial_documents(s: Session, row: MfgItemRow) -> None:
    """409 `MFG_IN_USE` when the item would stop being serialized while draft/released BOMs or routings of it keep
    a serial range (review F5); `details.used_by` lists them."""
    used: list[dict[str, Any]] = []
    for b in s.execute(select(MfgBomRow).where(MfgBomRow.item_id == row.id, MfgBomRow.status != "obsolete",
                                               MfgBomRow.serial_from.is_not(None))
                       .order_by(MfgBomRow.revision, MfgBomRow.version)).scalars():
        used.append({"type": "bom", "id": b.id, "label": f"BOM {b.revision} v{b.version} ({b.status})"})
    for r in s.execute(select(MfgRoutingRow).where(MfgRoutingRow.item_id == row.id,
                                                   MfgRoutingRow.status != "obsolete",
                                                   MfgRoutingRow.serial_from.is_not(None))
                       .order_by(MfgRoutingRow.code, MfgRoutingRow.version)).scalars():
        used.append({"type": "routing", "id": r.id, "label": f"routing {r.code} v{r.version} ({r.status})"})
    if used:
        refs = {"boms": sum(u["type"] == "bom" for u in used), "routings": sum(u["type"] == "routing" for u in used)}
        raise ApiError(409, "MFG_IN_USE", f"Item {row.part_number} cannot stop being serialized: "
                       f"{', '.join(u['label'] for u in used[:5])}{' ...' if len(used) > 5 else ''} "
                       "still use a serial range. Remove the serial ranges first (or make those documents obsolete).",
                       {"references": {k: v for k, v in refs.items() if v}, "used_by": used})


def delete_item(ctx: AppContext, item_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgItemRow, item_id, what="Item", lock=True)
        check_version(row, if_match)
        refs = {"bom_lines": count(s, MfgBomLineRow, MfgBomLineRow.child_item_id == row.id),
                "boms": count(s, MfgBomRow, MfgBomRow.item_id == row.id),
                "routings": count(s, MfgRoutingRow, MfgRoutingRow.item_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Item {row.part_number}", refs)
        s.delete(row)
        s.flush()
        audit(s, "item", row.id, "delete", {"version": row.row_version})
