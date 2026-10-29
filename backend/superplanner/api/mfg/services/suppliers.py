"""Suppliers and item-suppliers (M2-DESIGN 3.3, 12.3 #88-96): master data (plant lock, `data_version`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update

from ....mfg import limits as L
from ....mfg.dataset import ref
from ....mfg.model_m2 import ItemSupplierInput, ItemSupplierRecord, SupplierInput, SupplierRecord
from ....mfg.units import is_count
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow
from ..db_models_m2 import MfgItemSupplierRow, MfgPurchaseDocRow, MfgSupplierRow
from ..repo_m2 import item_supplier_record, supplier_record
from .common import (audit, check_limit, check_version, count, ensure_unique, ilike, in_use, read_tx, touch,
                     unknown_ref, write_tx)
from .m2util import iref, item_refs, validation

SUP_FIELDS = tuple(SupplierInput.model_fields)
ISU_FIELDS = tuple(f for f in ItemSupplierInput.model_fields)


def _counts(s: Any, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    return {k: int(v) for k, v in s.execute(select(MfgItemSupplierRow.supplier_id, func.count())
                                             .where(MfgItemSupplierRow.supplier_id.in_(ids))
                                             .group_by(MfgItemSupplierRow.supplier_id)).all()}


def list_suppliers(ctx: AppContext, q: str | None, active: bool | None) -> dict[str, Any]:
    conds: list[Any] = []
    if q:
        conds.append(ilike(MfgSupplierRow.code, q) | ilike(MfgSupplierRow.name, q))
    if active is not None:
        conds.append(MfgSupplierRow.active.is_(active))
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgSupplierRow).where(*conds).order_by(MfgSupplierRow.code)).scalars())
        n = _counts(s, [r.id for r in rows])
        return {"items": [supplier_record(r, n.get(r.id, 0)) for r in rows]}


def _isu_records(s: Any, rows: list[MfgItemSupplierRow]) -> list[ItemSupplierRecord]:
    refs = item_refs(s, [r.item_id for r in rows])
    sups = {x.id: x for x in s.execute(select(MfgSupplierRow).where(
        MfgSupplierRow.id.in_(sorted({r.supplier_id for r in rows})))).scalars()} if rows else {}
    return [item_supplier_record(r, refs.get(r.item_id) or iref(None, r.item_id),
                                 ref(sups[r.supplier_id]) if r.supplier_id in sups else None) for r in rows]


def get_supplier(ctx: AppContext, supplier_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        row = repo.get_row(s, MfgSupplierRow, supplier_id, what="Supplier")
        isus = list(s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.supplier_id == row.id)
                              .order_by(MfgItemSupplierRow.id)).scalars())
        recs = _isu_records(s, isus)
        recs.sort(key=lambda r: (r.item.part_number, r.id))
        out = supplier_record(row, len(isus)).__dict__.copy()
        out["items"] = recs
        return out


def _sup_unique(s: Any, inp: SupplierInput, exclude: str | None = None) -> None:
    ensure_unique(s, MfgSupplierRow, "A supplier", {"code": inp.code}, exclude_id=exclude)
    if inp.external_ref is not None:
        ensure_unique(s, MfgSupplierRow, "A supplier", {"external_ref": inp.external_ref}, exclude_id=exclude)


def create_supplier(ctx: AppContext, inp: SupplierInput) -> SupplierRecord:
    with write_tx(ctx) as (s, _plant):
        _sup_unique(s, inp)
        check_limit(s, MfgSupplierRow, L.MAX_SUPPLIERS, "suppliers")
        now = utcnow()
        row = MfgSupplierRow(id=new_id("sup_"), row_version=1, created_at=now, updated_at=now,
                             **{f: getattr(inp, f) for f in SUP_FIELDS})
        s.add(row)
        s.flush()
        audit(s, "supplier", row.id, "create", {"code": row.code, "version": 1})
        return supplier_record(row)


def update_supplier(ctx: AppContext, supplier_id: str, inp: SupplierInput, if_match: str | None) -> SupplierRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgSupplierRow, supplier_id, what="Supplier", lock=True)
        check_version(row, if_match)
        _sup_unique(s, inp, row.id)
        for f in SUP_FIELDS:
            setattr(row, f, getattr(inp, f))
        touch(row)
        s.flush()
        audit(s, "supplier", row.id, "update", {"version": row.row_version})
        return supplier_record(row, _counts(s, [row.id]).get(row.id, 0))


def delete_supplier(ctx: AppContext, supplier_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgSupplierRow, supplier_id, what="Supplier", lock=True)
        check_version(row, if_match)
        refs = {"purchase_documents": count(s, MfgPurchaseDocRow, MfgPurchaseDocRow.supplier_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Supplier {row.code}", refs)
        s.delete(row)
        s.flush()
        audit(s, "supplier", row.id, "delete", {"code": row.code, "version": row.row_version})


# ---------------------------------------------------------------- item-suppliers


def list_item_suppliers(ctx: AppContext, item_id: str | None, supplier_id: str | None) -> dict[str, Any]:
    if not item_id and not supplier_id:
        raise validation(["query", "item_id"], "Give item_id or supplier_id.")
    conds: list[Any] = []
    if item_id:
        conds.append(MfgItemSupplierRow.item_id == item_id)
    if supplier_id:
        conds.append(MfgItemSupplierRow.supplier_id == supplier_id)
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgItemSupplierRow).where(*conds)).scalars())
        recs = _isu_records(s, rows)
        recs.sort(key=lambda r: (not r.preferred, r.supplier.code if r.supplier else "", r.item.part_number, r.id))
        return {"items": recs}


def _check_isu(s: Any, inp: ItemSupplierInput) -> tuple[MfgItemRow, MfgSupplierRow]:
    item = s.execute(select(MfgItemRow).where(MfgItemRow.id == inp.item_id)).scalars().first()
    if item is None:
        raise unknown_ref(["body", "item_id"], inp.item_id, "Item")
    sup = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id == inp.supplier_id)).scalars().first()
    if sup is None:
        raise unknown_ref(["body", "supplier_id"], inp.supplier_id, "Supplier")
    if item.make_buy != "buy":
        raise ApiError(422, "MFG_ITEM_NOT_BUY", f"{item.part_number} is not a buy item; only buy items have "
                       "suppliers.", {"loc": ["body", "item_id"]})
    if is_count(item.uom) and abs(inp.units_per_purchase_unit - round(inp.units_per_purchase_unit)) > 1e-9:
        raise ApiError(422, "INV_FRACTIONAL_QTY", f"{item.part_number} is counted in {item.uom}; a pack must hold a "
                       "whole number of units.", {"loc": ["body", "units_per_purchase_unit"]})
    return item, sup


def _clear_preferred(s: Any, item_id: str, keep: str) -> None:
    s.execute(update(MfgItemSupplierRow).where(MfgItemSupplierRow.item_id == item_id,
                                               MfgItemSupplierRow.preferred.is_(True), MfgItemSupplierRow.id != keep)
              .values(preferred=False, row_version=MfgItemSupplierRow.row_version + 1, updated_at=utcnow())
              .execution_options(synchronize_session=False))


def create_item_supplier(ctx: AppContext, inp: ItemSupplierInput) -> ItemSupplierRecord:
    with write_tx(ctx) as (s, _plant):
        item, sup = _check_isu(s, inp)
        ensure_unique(s, MfgItemSupplierRow, "This supplier link",
                      {"item_id": inp.item_id, "supplier_id": inp.supplier_id})
        check_limit(s, MfgItemSupplierRow, L.MAX_ITEM_SUPPLIERS, "item-supplier links")
        now = utcnow()
        row = MfgItemSupplierRow(id=new_id("isu_"), row_version=1, created_at=now, updated_at=now,
                                 **{f: getattr(inp, f) for f in ISU_FIELDS})
        s.add(row)
        s.flush()
        if inp.preferred:
            _clear_preferred(s, item.id, row.id)
        audit(s, "item_supplier", row.id, "create", {"item_id": item.id, "supplier_id": sup.id, "version": 1})
        return item_supplier_record(row, iref(item), ref(sup))


def update_item_supplier(ctx: AppContext, isu_id: str, inp: ItemSupplierInput, if_match: str | None
                         ) -> ItemSupplierRecord:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgItemSupplierRow, isu_id, what="Item supplier", lock=True)
        check_version(row, if_match)
        if inp.item_id != row.item_id or inp.supplier_id != row.supplier_id:
            raise validation(["body", "item_id" if inp.item_id != row.item_id else "supplier_id"],
                             "item_id and supplier_id cannot change.")
        item, sup = _check_isu(s, inp)
        for f in ISU_FIELDS:
            setattr(row, f, getattr(inp, f))
        touch(row)
        s.flush()
        if inp.preferred:
            _clear_preferred(s, item.id, row.id)
        audit(s, "item_supplier", row.id, "update", {"version": row.row_version})
        return item_supplier_record(row, iref(item), ref(sup))


def delete_item_supplier(ctx: AppContext, isu_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _plant):
        row = repo.get_row(s, MfgItemSupplierRow, isu_id, what="Item supplier", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "item_supplier", row.id, "delete", {"version": row.row_version})
