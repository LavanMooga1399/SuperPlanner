"""BOM documents (M1-DESIGN 3.5, 4.2; 9.3 #12, #14-20) and the explosion / where-used views (#10, #11).

Documents are edited as a whole (header + all lines in one PUT, If-Match on the header). Kept line ids keep their
ids, omitted lines are deleted, new lines get fresh ids. Cycles are rejected on every write (drafts too). Status
changes only through release / obsolete / copy.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.bom import ExplosionTooLarge, explode, where_used, would_create_cycle
from ....mfg.dataset import MfgDataset, item_ref
from ....mfg.model import BomInput, BomLineInput, BomRecord, PlantRecord
from ....mfg.release import ReleaseError, bom_release_issues, validate_bom_document
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgBomLineRow, MfgBomRow, MfgItemRow
from .common import (audit, check_limit, check_version, ensure_unique, jsonable, plant_today, read_tx, touch,
                     unknown_ref, write_tx)

LINE_FIELDS = ("find_number", "child_item_id", "qty_per", "uom", "scrap_pct", "ref_designators", "alt_group",
               "alt_priority", "operation_seq", "note")
HEADER_FIELDS = ("effective_from", "effective_to", "serial_from", "serial_to", "note")


# ---------------------------------------------------------------- shared document helpers


def document_errors(errors: list[dict[str, Any]], s: Session) -> None:
    """Map `validate_*_document` error dicts to the API codes (3.5 / 17.WP-A)."""
    if not errors:
        return
    for e in errors:
        if e.get("type") == "mfg_unknown_reference":
            loc = list(e["loc"])
            raise ApiError(422, "MFG_UNKNOWN_REFERENCE", e["msg"], {"loc": loc, "id": _id_at(e)})
    for e in errors:
        if e.get("type") == "mfg_bom_cycle":
            raise ApiError(422, "MFG_BOM_CYCLE", "An item cannot contain itself.",
                           {"cycle": e.get("cycle") or [], "loc": list(e["loc"])})
    raise ApiError(422, "VALIDATION_ERROR", errors[0]["msg"],
                   {"errors": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in errors]})


def _id_at(e: dict[str, Any]) -> str:
    m = str(e.get("msg", ""))
    if "'" in m:
        return m.split("'")[1]
    return ""


def readonly(status: str, what: str) -> ApiError:
    return ApiError(409, "MFG_RELEASED_READONLY",
                    f"This {what} is {status} and cannot be changed. Copy it to a new version to make changes.",
                    {"status": status})


def invalid_state(status: str, action: str, what: str) -> ApiError:
    return ApiError(409, "MFG_INVALID_STATE", f"A {status} {what} cannot be {action}.", {"status": status})


def release_blocked(issues: list[Any], what: str) -> ApiError:
    n = len(issues)
    return ApiError(422, "MFG_RELEASE_BLOCKED",
                    f"This {what} cannot be released yet ({n} problem{'s' if n != 1 else ''}).",
                    {"issues": jsonable(issues)})


def release_error(exc: ReleaseError) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", str(exc),
                    {"errors": [{"loc": ["body", "effective_from"], "msg": str(exc), "type": "value_error"}]})


def check_ids_kept(given: list[str | None], existing: set[str], what: str) -> None:
    errors = [{"loc": ["body", what, i, "id"], "msg": f"{x!r} is not a {what[:-1].replace('_', ' ')} of this "
               "document.", "type": "unknown_child_id"} for i, x in enumerate(given) if x is not None
              and x not in existing]
    seen: set[str] = set()
    for i, x in enumerate(given):
        if x is not None and x in seen:
            errors.append({"loc": ["body", what, i, "id"], "msg": f"{x!r} is listed twice.", "type": "duplicate_id"})
        if x is not None:
            seen.add(x)
    if errors:
        raise ApiError(422, "VALIDATION_ERROR", errors[0]["msg"], {"errors": errors})


def item_for_document(s: Session, item_id: str, *, routing: bool) -> MfgItemRow:
    item = s.execute(select(MfgItemRow).where(MfgItemRow.id == item_id)).scalars().first()
    if item is None:
        raise unknown_ref(["body", "item_id"], item_id, "Item")
    if (routing and item.make_buy != "make") or (not routing and item.make_buy == "buy"):
        what = "a routing" if routing else "a BOM"
        raise ApiError(422, "MFG_ITEM_NOT_MAKE",
                       f"{item.part_number} is a {item.make_buy} item and cannot have {what}.",
                       {"loc": ["body", "item_id"], "id": item_id, "make_buy": item.make_buy})
    return item


def check_serial(item: MfgItemRow, serial_from: int | None) -> None:
    if serial_from is not None and not item.serialized:
        raise ApiError(422, "MFG_SERIAL_NOT_ALLOWED",
                       f"{item.part_number} is not serialized, so the document cannot have a serial range.",
                       {"loc": ["body", "serial_from"]})


# ---------------------------------------------------------------- records


def bom_record(s: Session, row: MfgBomRow) -> BomRecord:
    lines = list(s.execute(select(MfgBomLineRow).where(MfgBomLineRow.bom_id == row.id)).scalars())
    ids = {row.item_id} | {ln.child_item_id for ln in lines}
    items = {r.id: repo.to_record(r) for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(sorted(ids))))
             .scalars()}
    from ....mfg.dataset import line_sort_key

    recs = [repo.to_record(ln, child=item_ref(items[ln.child_item_id])) for ln in lines if ln.child_item_id in items]
    recs.sort(key=line_sort_key)
    return repo.to_record(row, lines=recs, item=item_ref(items[row.item_id]))


def get_bom(ctx: AppContext, bom_id: str) -> BomRecord:
    with read_tx(ctx) as s:
        return bom_record(s, repo.get_row(s, MfgBomRow, bom_id, what="BOM"))


def list_item_boms(ctx: AppContext, item_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        item = repo.get_row(s, MfgItemRow, item_id, what="Item")
        ref = item_ref(repo.to_record(item))
        rows = list(s.execute(select(MfgBomRow).where(MfgBomRow.item_id == item.id)
                              .order_by(MfgBomRow.revision, MfgBomRow.version)).scalars())
        counts = dict(s.execute(select(MfgBomLineRow.bom_id, func.count()).where(
            MfgBomLineRow.bom_id.in_([r.id for r in rows])).group_by(MfgBomLineRow.bom_id)).all()) if rows else {}
        out = []
        for r in rows:
            d = jsonable(repo.to_record(r, item=ref))
            d.pop("lines", None)
            d["line_count"] = int(counts.get(r.id, 0))
            out.append(d)
        return {"items": out}


# ---------------------------------------------------------------- writes


def _validate_lines(s: Session, item: MfgItemRow, lines: list[BomLineInput]) -> dict[str, MfgItemRow]:
    child_ids = sorted({ln.child_item_id for ln in lines})
    children = {r.id: r for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(child_ids))).scalars()} \
        if child_ids else {}
    ds = MfgDataset(plant=PlantRecord())
    for r in children.values():
        ds.items[r.id] = repo.to_record(r)
    errors = validate_bom_document(ds, item.id, lines)
    for e in errors:
        if e.get("type") == "mfg_bom_cycle":
            e["cycle"] = [item.part_number, item.part_number]
    document_errors(errors, s)
    if lines:
        path = would_create_cycle(repo.bom_edge_list(s), [(item.id, ln.child_item_id) for ln in lines])
        if path is not None:
            pns = dict(s.execute(select(MfgItemRow.id, MfgItemRow.part_number)
                                 .where(MfgItemRow.id.in_(sorted(set(path))))).all())
            cycle = [pns.get(i, i) for i in path]
            raise ApiError(422, "MFG_BOM_CYCLE",
                           f"This change would make an item contain itself: {' -> '.join(cycle)}.", {"cycle": cycle})
    return children


def _line_values(ln: BomLineInput, children: dict[str, MfgItemRow]) -> dict[str, Any]:
    v = {f: getattr(ln, f) for f in LINE_FIELDS}
    if v["uom"] is None:
        v["uom"] = children[ln.child_item_id].uom
    return v


def write_children(s: Session, model: Any, parent_field: str, parent_id: str, prefix: str,
                   inputs: list[tuple[str | None, dict[str, Any]]], key_fields: tuple[str, ...],
                   placeholder: Any) -> list[Any]:
    """Replace the children of a document: kept ids are updated in place, the rest deleted, new rows added.
    Unique keys of kept rows that change are moved to placeholders first, so swaps never collide."""
    existing = {r.id: r for r in s.execute(select(model).where(getattr(model, parent_field) == parent_id)).scalars()}
    keep = {cid for cid, _ in inputs if cid is not None}
    gone = [cid for cid in existing if cid not in keep]
    if gone:
        s.execute(delete(model).where(model.id.in_(gone)).execution_options(synchronize_session=False))
        for cid in gone:
            s.expunge(existing.pop(cid))
    now = utcnow()
    moved = [(cid, vals) for cid, vals in inputs if cid is not None and
             tuple(getattr(existing[cid], k) for k in key_fields) != tuple(vals[k] for k in key_fields)]
    if moved:
        for i, (cid, _vals) in enumerate(moved):
            setattr(existing[cid], key_fields[0], placeholder(i))
        s.flush()
    out = []
    for cid, vals in inputs:
        if cid is None:
            row = model(id=new_id(prefix), row_version=1, created_at=now, updated_at=now,
                        **{parent_field: parent_id}, **vals)
            s.add(row)
        else:
            row = existing[cid]
            changed = any(getattr(row, k) != v for k, v in vals.items())
            for k, v in vals.items():
                setattr(row, k, v)
            if changed:
                touch(row, now)
        out.append(row)
    s.flush()
    return out


def _next_version(s: Session, item_id: str, revision: str) -> int:
    v = s.execute(select(func.max(MfgBomRow.version)).where(MfgBomRow.item_id == item_id,
                                                            MfgBomRow.revision == revision)).scalar()
    return int(v or 0) + 1


def _limits(s: Session, new_lines: int, new_doc: bool) -> None:
    if new_doc:
        check_limit(s, MfgBomRow, L.MAX_BOMS, "BOMs")
    if new_lines:
        check_limit(s, MfgBomLineRow, L.MAX_BOM_LINES_TOTAL, "BOM lines", adding=new_lines)


def create_bom(ctx: AppContext, inp: BomInput) -> BomRecord:
    with write_tx(ctx) as (s, _):
        item = item_for_document(s, inp.item_id, routing=False)
        check_serial(item, inp.serial_from)
        check_ids_kept([ln.id for ln in inp.lines], set(), "lines")
        revision = inp.revision or item.revision
        version = inp.version or _next_version(s, item.id, revision)
        ensure_unique(s, MfgBomRow, "A BOM", {"item_id": item.id, "revision": revision, "version": version})
        children = _validate_lines(s, item, inp.lines)
        _limits(s, len(inp.lines), True)
        now = utcnow()
        row = MfgBomRow(id=new_id("bom_"), item_id=item.id, revision=revision, version=version, status="draft",
                        row_version=1, created_at=now, updated_at=now,
                        **{f: getattr(inp, f) for f in HEADER_FIELDS})
        s.add(row)
        s.flush()
        write_children(s, MfgBomLineRow, "bom_id", row.id, "bml_",
                       [(None, _line_values(ln, children)) for ln in inp.lines], ("find_number", "child_item_id"),
                       lambda i: f"~{i}")
        audit(s, "bom", row.id, "create", {"version": 1, "lines": len(inp.lines)})
        return bom_record(s, row)


def update_bom(ctx: AppContext, bom_id: str, inp: BomInput, if_match: str | None) -> BomRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgBomRow, bom_id, what="BOM", lock=True)
        check_version(row, if_match)
        if row.status != "draft":
            raise readonly(row.status, "BOM")
        if inp.item_id != row.item_id:
            raise ApiError(422, "VALIDATION_ERROR", "The item of a BOM cannot be changed.",
                           {"errors": [{"loc": ["body", "item_id"], "msg": "must equal the stored item_id",
                                        "type": "immutable"}]})
        item = item_for_document(s, row.item_id, routing=False)
        check_serial(item, inp.serial_from)
        existing = set(s.execute(select(MfgBomLineRow.id).where(MfgBomLineRow.bom_id == row.id)).scalars())
        check_ids_kept([ln.id for ln in inp.lines], existing, "lines")
        revision = inp.revision or row.revision
        version = inp.version or row.version
        ensure_unique(s, MfgBomRow, "A BOM", {"item_id": item.id, "revision": revision, "version": version},
                      exclude_id=row.id)
        children = _validate_lines(s, item, inp.lines)
        _limits(s, sum(1 for ln in inp.lines if ln.id is None), False)
        row.revision, row.version = revision, version
        for f in HEADER_FIELDS:
            setattr(row, f, getattr(inp, f))
        write_children(s, MfgBomLineRow, "bom_id", row.id, "bml_",
                       [(ln.id, _line_values(ln, children)) for ln in inp.lines], ("find_number", "child_item_id"),
                       lambda i: f"~{i}")
        touch(row)
        s.flush()
        audit(s, "bom", row.id, "update", {"version": row.row_version, "lines": len(inp.lines)})
        return bom_record(s, row)


def delete_bom(ctx: AppContext, bom_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgBomRow, bom_id, what="BOM", lock=True)
        check_version(row, if_match)
        if row.status == "released":
            raise readonly(row.status, "BOM")
        s.execute(delete(MfgBomLineRow).where(MfgBomLineRow.bom_id == row.id)
                  .execution_options(synchronize_session=False))
        s.execute(delete(MfgBomRow).where(MfgBomRow.id == row.id).execution_options(synchronize_session=False))
        s.expunge(row)
        audit(s, "bom", bom_id, "delete", {"version": row.row_version})


def release_bom(ctx: AppContext, bom_id: str, effective_from: date | None, supersede: bool, if_match: str | None
                ) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgBomRow, bom_id, what="BOM", lock=True)
        check_version(row, if_match)
        if row.status != "draft":
            raise invalid_state(row.status, "released", "BOM")
        ds = repo.load_dataset(s)
        try:
            issues, superseded = bom_release_issues(ds, row.id, effective_from, supersede)
        except ReleaseError as exc:
            raise release_error(exc) from None
        if issues:
            raise release_blocked(issues, "BOM")
        now = utcnow()
        if effective_from is not None:
            row.effective_from = effective_from
        row.status, row.released_at = "released", now
        touch(row, now)
        for sup in superseded:
            other = repo.get_row(s, MfgBomRow, sup["id"], what="BOM", lock=True)
            other.effective_to = sup["effective_to"]
            touch(other, now)
        s.flush()
        audit(s, "bom", row.id, "release", {"version": row.row_version,
                                            "superseded": [x["id"] for x in superseded]})
        return {"bom": bom_record(s, row), "superseded": superseded}


def obsolete_bom(ctx: AppContext, bom_id: str, if_match: str | None) -> BomRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgBomRow, bom_id, what="BOM", lock=True)
        check_version(row, if_match)
        if row.status != "released":
            raise invalid_state(row.status, "made obsolete", "BOM")
        now = utcnow()
        row.status, row.obsoleted_at = "obsolete", now
        touch(row, now)
        s.flush()
        audit(s, "bom", row.id, "obsolete", {"version": row.row_version})
        return bom_record(s, row)


def copy_bom(ctx: AppContext, bom_id: str, revision: str | None, if_match: str | None) -> BomRecord:
    with write_tx(ctx) as (s, _):
        src = repo.get_row(s, MfgBomRow, bom_id, what="BOM", lock=True)
        check_version(src, if_match)
        item_for_document(s, src.item_id, routing=False)
        rev = revision or src.revision
        lines = list(s.execute(select(MfgBomLineRow).where(MfgBomLineRow.bom_id == src.id)).scalars())
        _limits(s, len(lines), True)
        now = utcnow()
        row = MfgBomRow(id=new_id("bom_"), item_id=src.item_id, revision=rev, version=_next_version(s, src.item_id, rev),
                        status="draft", effective_from=None, effective_to=None, serial_from=src.serial_from,
                        serial_to=src.serial_to, note=src.note, row_version=1, created_at=now, updated_at=now)
        s.add(row)
        s.flush()
        s.add_all([MfgBomLineRow(id=new_id("bml_"), bom_id=row.id, row_version=1, created_at=now, updated_at=now,
                                 **{f: getattr(ln, f) for f in LINE_FIELDS}) for ln in lines])
        s.flush()
        audit(s, "bom", row.id, "copy", {"from": src.id, "version": row.version})
        return bom_record(s, row)


# ---------------------------------------------------------------- views


def explosion(ctx: AppContext, item_id: str, *, on: date | None, serial: int | None, qty: float, mode: str,
              include_scrap: bool, include_yield: bool, max_depth: int | None) -> Any:
    with read_tx(ctx) as s:
        if on is None:
            on = plant_today(repo.plant_or_default(s).utc_offset)
        index = repo.load_bom_index_down(s, item_id, on, serial)
    try:
        return explode(index, item_id, qty=qty, mode=mode, include_scrap=include_scrap,  # type: ignore[arg-type]
                       include_yield=include_yield, max_depth=max_depth)
    except ExplosionTooLarge:
        raise ApiError(422, "MFG_EXPLOSION_TOO_LARGE",
                       f"The indented structure has more than {L.MAX_EXPLOSION_ROWS} rows. Use mode=summarized or "
                       "a max_depth.", {"limit": L.MAX_EXPLOSION_ROWS, "suggest": "mode=summarized"}) from None


def where_used_view(ctx: AppContext, item_id: str, *, on: date | None, include: str, mode: str) -> Any:
    with read_tx(ctx) as s:
        index = repo.load_parent_index(s, item_id, on, include)
    try:
        return where_used(index, item_id, mode=mode)  # type: ignore[arg-type]
    except ExplosionTooLarge:
        raise ApiError(422, "MFG_EXPLOSION_TOO_LARGE",
                       f"The indented where-used list has more than {L.MAX_EXPLOSION_ROWS} rows. Use mode=single.",
                       {"limit": L.MAX_EXPLOSION_ROWS, "suggest": "mode=single"}) from None
