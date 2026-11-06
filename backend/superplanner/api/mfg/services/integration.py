"""Integration console and inbound batches (M5-DESIGN 4; I1, I2, I4).

Inbound REST batches go through the M1 import plan / writer (I1: same validation, plant lock, audit), in chunks of
2,000 records per transaction; each record is first checked against the contract, the value maps and the system of
record (4.4) and rejected on its own (`INT_SCHEMA`, `INT_UNMAPPED_VALUE`, `INT_SOR_CONFLICT`). The batch result is
stored on `int_inbox` with the payload hash: a replay of the `Idempotency-Key` returns it, a different body under the
same key is 409 `INT_IDEMPOTENCY_CONFLICT`.

Entities processed in this build: `item`, `supplier` (bundle sheets), `po_receipt` (M2 posting, only when the
plant's `goods_receipts_owner` is `erp`), `stock_snapshot` (reconciliation input only) and every SuperPlanner-owned
entity (rejected per record). Other v1 entities are accepted by the contract and rejected `INT_SCHEMA` with
"not processed in this build" (15.WP-S).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....identity import crypto
from ....integration import contract as C
from ....integration import outbox
from ....integration.model import SHARED_ALLOWED, SOR_DEFAULTS
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import repo
from ..db_models_m5 import (IntDeliveryRow, IntEndpointRow, IntInboxRow, IntMappingProfileRow, IntOutboxRow,
                            IntReconciliationRow, IntSettingsRow, IntValueMapRow)
from .common import audit, check_version, read_tx, touch, write_tx
from .m2util import actor_id, page, run_tx

ITEM_ERP_FIELDS = ("part_number", "revision", "description", "uom", "make_buy", "active", "external_ref",
                   "standard_cost")
SP_OWNED_ENTITIES = {"purchase_request": "purchase_requests", "work_order": "work_orders"}


# ---------------------------------------------------------------- settings / SoR (4.4)

def settings_row(s: Session) -> IntSettingsRow | None:
    return s.execute(select(IntSettingsRow)).scalars().first()


def sor_of(s: Session, entity: str) -> str:
    st = settings_row(s)
    if st is None or not st.enabled:            # integration off: SuperPlanner owns everything
        return "superplanner"
    return (st.sor or {}).get(entity, SOR_DEFAULTS.get(entity, "superplanner"))


def settings_record(r: IntSettingsRow | None, plant_name: str = "") -> dict[str, Any]:
    if r is None:
        return {"enabled": False, "adapter": "generic_v1", "plant_code": "", "sor": dict(SOR_DEFAULTS),
                "goods_receipts_owner": "superplanner", "filedrop_enabled": False, "export_enabled": False,
                "export_interval_minutes": 15, "row_version": 0, "adapters": ["generic_v1"]}
    return {"enabled": r.enabled, "adapter": r.adapter, "plant_code": r.plant_code,
            "sor": {**SOR_DEFAULTS, **{k: v for k, v in (r.sor or {}).items() if not k.startswith("_")}},
            "goods_receipts_owner": r.goods_receipts_owner, "filedrop_enabled": r.filedrop_enabled,
            "export_enabled": r.export_enabled, "export_interval_minutes": r.export_interval_minutes,
            "row_version": r.row_version, "adapters": ["generic_v1"]}


def get_settings(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return settings_record(settings_row(s))


def put_settings(ctx: AppContext, inp: Any, if_match: str | None) -> dict[str, Any]:
    for ent, v in inp.sor.items():
        if v == "shared" and ent not in SHARED_ALLOWED:
            raise ApiError(422, "VALIDATION_ERROR", f"SoR 'shared' is allowed for {', '.join(SHARED_ALLOWED)} only.",
                           {"errors": [{"loc": ["body", "sor", ent], "msg": "shared not allowed",
                                        "type": "value_error"}]})

    def fn(s: Session) -> dict[str, Any]:
        r = s.execute(select(IntSettingsRow).with_for_update()).scalars().first()
        if inp.plant_code:                   # names the file-drop folders: unique across plants (15.WP-S)
            from ...db.ownership import current_owner, system_scope

            me = current_owner()
            with system_scope():
                other = s.execute(select(IntSettingsRow.owner_id).where(
                    func.lower(IntSettingsRow.plant_code) == inp.plant_code.lower(),
                    IntSettingsRow.owner_id != me)).first()
            if other is not None:
                raise ApiError(409, "INT_PLANT_CODE_TAKEN", f"Plant code {inp.plant_code!r} is used by another "
                               "plant.", {"loc": ["body", "plant_code"]})
        now = utcnow()
        sor = {**SOR_DEFAULTS, **inp.sor}
        sor["po_receipts"] = inp.goods_receipts_owner           # 14 Q2: one switch, kept in step
        if r is None:
            check_version(type("V", (), {"row_version": 0})(), if_match)
            r = IntSettingsRow(id=new_id("ist_"), enabled=inp.enabled, adapter=inp.adapter, plant_code=inp.plant_code,
                               sor=sor, goods_receipts_owner=inp.goods_receipts_owner,
                               filedrop_enabled=inp.filedrop_enabled, export_enabled=inp.export_enabled,
                               export_interval_minutes=inp.export_interval_minutes, export_cursor=0, row_version=1,
                               created_at=now, updated_at=now)
            s.add(r)
        else:
            check_version(r, if_match)
            purged = (r.sor or {}).get("_purged_through")
            r.enabled, r.adapter, r.plant_code = inp.enabled, inp.adapter, inp.plant_code
            r.sor = {**sor, **({"_purged_through": purged} if purged else {})}
            r.goods_receipts_owner = inp.goods_receipts_owner
            r.filedrop_enabled, r.export_enabled = inp.filedrop_enabled, inp.export_enabled
            r.export_interval_minutes = inp.export_interval_minutes
            touch(r, now)
        s.flush()
        audit(s, "integration_settings", r.id, "update", {"sor": r.sor, "enabled": r.enabled,
                                                          "goods_receipts_owner": r.goods_receipts_owner})
        return settings_record(r)

    try:
        return run_tx(ctx, fn)
    except IntegrityError as exc:            # a concurrent save of the same code
        if "uq_int_settings_plant_code" in str(exc.orig):
            raise ApiError(409, "INT_PLANT_CODE_TAKEN", f"Plant code {inp.plant_code!r} is used by another plant.",
                           {"loc": ["body", "plant_code"]}) from None
        raise


def check_local_item_write(s: Session, before: Any | None, after: Any) -> None:
    """409 `INT_ERP_OWNED` for a local change of an ERP-owned item field (4.4; inbound writes bypass this)."""
    if s.info.get("sp_inbound") or sor_of(s, "items") != "erp":
        return
    changed = [f for f in ITEM_ERP_FIELDS if before is None or getattr(before, f, None) != getattr(after, f, None)]
    if before is None:
        changed = ["part_number"]
    if changed:
        raise ApiError(409, "INT_ERP_OWNED", "These item fields are maintained in the ERP.", {"fields": changed})


def check_local_write(s: Session, entity: str, fields: list[str] | None = None) -> None:
    """4.4: 409 `INT_ERP_OWNED` for a local write of an ERP-owned entity (`fields`: the ERP-owned fields touched;
    None = the whole document). Inbound writes, integration off and `shared` SoR pass."""
    if s.info.get("sp_inbound") or sor_of(s, entity) != "erp":
        return
    raise ApiError(409, "INT_ERP_OWNED", f"{entity.replace('_', ' ').capitalize()} are maintained in the ERP for "
                   "this plant.", {"fields": fields or ["document"], "entity": entity})


def track_shared(s: Session, entity: str, record_id: str, ref: str | None, version_before: int | None,
                 version_after: int, changed: bool) -> None:
    """4.4 `shared` SoR: remember the row version an inbound write leaves; when the inbound write changes a record
    that was also changed locally since the previous sync, log a conflict (last writer - the ERP - still wins)."""
    from ..db_models_m5 import IntSyncStateRow

    st = s.execute(select(IntSyncStateRow).where(IntSyncStateRow.entity == entity,
                                                 IntSyncStateRow.record_id == record_id).with_for_update()
                   ).scalars().first()
    now = utcnow()
    if st is None:
        s.add(IntSyncStateRow(id=new_id("iss_"), entity=entity, record_id=record_id, ref=ref,
                              synced_version=int(version_after), synced_at=now, conflict=None, conflict_at=None))
        s.flush()
        return
    if changed and version_before is not None and int(version_before) != int(st.synced_version):
        st.conflict = {"entity": entity, "record_id": record_id, "ref": ref, "synced_version": st.synced_version,
                       "local_version": int(version_before), "erp_version": int(version_after),
                       "message": "Changed in SuperPlanner and in the ERP since the last sync; the ERP value "
                                  "was applied (last writer wins)."}
        st.conflict_at = now
    st.synced_version, st.synced_at, st.ref = int(version_after), now, ref or st.ref
    s.flush()


def shared_conflicts(s: Session, entities: tuple[str, ...]) -> list[dict[str, Any]]:
    from ..db_models_m5 import IntSyncStateRow

    return [{**(r.conflict or {}), "detected_at": as_utc(r.conflict_at).isoformat()} for r in s.execute(
        select(IntSyncStateRow).where(IntSyncStateRow.entity.in_(entities), IntSyncStateRow.conflict_at.is_not(None))
        .order_by(IntSyncStateRow.conflict_at.desc()).limit(1000)).scalars()]


IMPORT_SHEET_SOR = {"boms": "boms", "bom_lines": "boms", "routings": "routings", "operations": "routings",
                    "suppliers": "suppliers", "item_suppliers": "item_suppliers", "purchase_docs": "purchase_orders",
                    "purchase_lines": "purchase_orders", "purchase_schedules": "purchase_orders",
                    "demand_orders": "demand_orders", "demand_lines": "demand_orders", "work_orders": "work_orders",
                    "wo_components": "work_orders"}


def check_import_plan(s: Session, bundle: dict[str, Any], plan: Any) -> None:
    """15.WP-S (security review M4): the M1 import wizard obeys the system of record and ECO locks like the UI.
    - sheets of ERP-owned entities -> 409 `INT_ERP_OWNED` (POs only for PO rows; items see below);
    - items while ERP-owned: no new items and no change of an ERP-owned field (planning fields import fine);
    - BOM / routing rows of a document held by an open change request -> 409 `ECO_DOC_LOCKED`."""
    from ..db_models import MfgBomLineRow, MfgBomRow, MfgOperationRow, MfgRoutingRow
    from ..db_models_m5 import MfgChangeRequestRow

    for sheet, ent in IMPORT_SHEET_SOR.items():
        rows = bundle.get(sheet) or []
        if sheet.startswith("purchase_"):
            rows = [r for r in rows if str(r.get("doc_type") or "").strip() == "po"]
        if rows:
            check_local_write(s, ent, [sheet])
    if sor_of(s, "items") == "erp":
        bad: set[str] = set()
        for c in plan.changes:
            if c.table != "items":
                continue
            if c.action == "create":
                bad.add("part_number")
            elif c.action == "update":
                bad |= {f for f in c.values if f in ITEM_ERP_FIELDS}
        if bad:
            raise ApiError(409, "INT_ERP_OWNED", "These item fields are maintained in the ERP.",
                           {"fields": sorted(bad), "entity": "items", "sheet": "items"})
    docs: dict[str, set[str]] = {"boms": set(), "routings": set()}
    lines: dict[str, set[str]] = {"bom_lines": set(), "operations": set()}
    for c in plan.changes:
        if c.table in docs and c.action != "create":
            docs[c.table].add(c.id)
        elif c.table in lines:
            parent = c.values.get("bom_id" if c.table == "bom_lines" else "routing_id")
            if parent:
                docs["boms" if c.table == "bom_lines" else "routings"].add(parent)
            elif isinstance(c.id, str):
                lines[c.table].add(c.id)
    if lines["bom_lines"]:
        docs["boms"] |= set(s.execute(select(MfgBomLineRow.bom_id).where(
            MfgBomLineRow.id.in_(sorted(lines["bom_lines"])))).scalars())
    if lines["operations"]:
        docs["routings"] |= set(s.execute(select(MfgOperationRow.routing_id).where(
            MfgOperationRow.id.in_(sorted(lines["operations"])))).scalars())
    for table, model in (("boms", MfgBomRow), ("routings", MfgRoutingRow)):
        if not docs[table]:
            continue
        for d, cr in s.execute(select(model, MfgChangeRequestRow).join(
                MfgChangeRequestRow, MfgChangeRequestRow.id == model.locked_by_cr_id).where(
                model.id.in_(sorted(docs[table])), MfgChangeRequestRow.status.in_(("submitted", "approved")))).all():
            raise ApiError(409, "ECO_DOC_LOCKED", f"A document in the file is part of {cr.number} ({cr.status}).",
                           {"cr_id": cr.id, "number": cr.number, "doc_id": d.id, "sheet": table})


def check_local_po_receipt(s: Session) -> None:
    """14 Q2: with goods receipts owned by the ERP, PO receipts come in through integration only."""
    st = settings_row(s)
    if s.info.get("sp_inbound") or st is None or not st.enabled or st.goods_receipts_owner != "erp":
        return
    raise ApiError(409, "INT_ERP_OWNED", "Goods receipts against purchase orders are booked in the ERP for this "
                   "plant.", {"fields": ["po_receipt"]})


# ---------------------------------------------------------------- value maps

def _maps(s: Session) -> dict[tuple[str, str], str]:
    return {(r.domain, r.external_value.upper()): r.internal_value for r in s.execute(select(IntValueMapRow)).scalars()}


def get_value_maps(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        rows = list(s.execute(select(IntValueMapRow).order_by(IntValueMapRow.domain, IntValueMapRow.external_value))
                    .scalars())
        return {"rows": [{"domain": r.domain, "external_value": r.external_value, "internal_value": r.internal_value}
                         for r in rows]}


def put_value_maps(ctx: AppContext, inp: Any) -> dict[str, Any]:
    keys = [(r.domain, r.external_value.upper()) for r in inp.rows]
    if len(set(keys)) != len(keys):
        raise ApiError(422, "VALIDATION_ERROR", "Each (domain, external value) may appear once.", {})

    def fn(s: Session) -> dict[str, Any]:
        s.execute(delete(IntValueMapRow).execution_options(synchronize_session=False))
        s.add_all([IntValueMapRow(id=new_id("ivm_"), domain=r.domain, external_value=r.external_value,
                                  internal_value=r.internal_value) for r in inp.rows])
        s.flush()
        audit(s, "integration_value_maps", None, "replace", {"rows": len(inp.rows)})
        return {"rows": [r.model_dump() for r in inp.rows]}

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- inbound batches (4.3)

def _hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def batch_record(r: IntInboxRow, with_results: bool = True) -> dict[str, Any]:
    return {"id": r.id, "entity": r.entity, "mode": r.mode, "status": r.status, "counts": r.counts or {},
            "results": r.results if with_results else None, "received_at": as_utc(r.received_at),
            "finished_at": as_utc(r.finished_at)}


def post_batch(ctx: AppContext, body: dict[str, Any], key: str | None, source: str = "rest"
               ) -> tuple[dict[str, Any], bool, int]:
    """-> (batch, replayed, http status)."""
    if not key:
        raise ApiError(422, "VALIDATION_ERROR", "The Idempotency-Key header is required.",
                       {"errors": [{"loc": ["header", "Idempotency-Key"], "msg": "required", "type": "missing"}]})
    try:
        batch = C.V1Batch.model_validate(body)
    except ValidationError as e:
        raise ApiError(422, "INT_SCHEMA", "The batch does not follow superplanner.v1.",
                       {"errors": [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()[:50]]}) from None
    h = _hash(body)
    with read_tx(ctx) as s:
        st = settings_row(s)
        if st is None or not st.enabled:
            raise ApiError(409, "INT_DISABLED", "Integration is not enabled for this plant.", {})
        found = s.execute(select(IntInboxRow).where(IntInboxRow.idempotency_key == key)).scalars().first()
        if found is not None:
            if found.payload_hash != h:
                raise ApiError(409, "INT_IDEMPOTENCY_CONFLICT", "This Idempotency-Key was used for another batch.",
                               {"batch_id": found.id})
            stale = found.status == "running" and _aware_dt(found.received_at) < utcnow() - STALE_BATCH
            if found.status != "failed" and not stale:
                return batch_record(found), True, 200
            retry_id = found.id                    # 15.WP-S minor 4: a failed / abandoned batch runs again
        else:
            retry_id = None
    now = utcnow()

    def create(s: Session) -> str:
        if retry_id is not None:
            r = s.get(IntInboxRow, retry_id, with_for_update=True)
            if r.status not in ("failed", "running"):
                raise ApiError(409, "INT_IDEMPOTENCY_CONFLICT", "This Idempotency-Key is being processed.", {})
            r.status, r.results, r.counts, r.received_at, r.finished_at = "running", None, {}, now, None
            s.flush()
            return r.id
        row = IntInboxRow(id=new_id("inb_"), source=source, idempotency_key=key, entity=batch.entity, mode=batch.mode,
                          status="running", counts={}, results=None, payload=body, payload_hash=h,
                          actor_id=actor_id(), received_at=now, finished_at=None)
        try:
            with s.begin_nested():
                s.add(row)
                s.flush()
        except IntegrityError:
            raise ApiError(409, "INT_IDEMPOTENCY_CONFLICT", "This Idempotency-Key is being processed.", {}) \
                from None
        return row.id

    if len(batch.records) > C.SYNC_LIMIT:                    # 4.3: 202 + job kind integration_import
        def queue(s: Session) -> tuple[dict[str, Any], Any]:
            from ...db.ownership import current_owner

            row = IntInboxRow(id=new_id("inb_"), source=source, idempotency_key=key, entity=batch.entity,
                              mode=batch.mode, status="queued", counts={}, results=None, payload=body,
                              payload_hash=h, actor_id=actor_id(), received_at=now, finished_at=None)
            try:
                with s.begin_nested():
                    s.add(row)
                    s.flush()
            except IntegrityError:
                raise ApiError(409, "INT_IDEMPOTENCY_CONFLICT", "This Idempotency-Key is being processed.", {}) \
                    from None
            job = ctx.jobs.enqueue(s, "integration_import", row.id, str(current_owner()))
            return batch_record(row), job

        rec, job = run_tx(ctx, queue)
        ctx.jobs.dispatch(job)
        return rec, False, 202
    bid = run_tx(ctx, create)
    try:
        results = process(ctx, batch)
    except BaseException as exc:                     # recorded, so the key can be retried
        def fail(s: Session) -> None:
            row = s.get(IntInboxRow, bid, with_for_update=True)
            if row is not None:
                row.status, row.finished_at = "failed", utcnow()
                row.results = [{"ref": "", "status": "rejected", "id": None, "errors": [
                    {"code": getattr(exc, "code", "INT_FAILED"), "message": str(exc)[:300]}]}]
        run_tx(ctx, fail)
        raise
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    def finish(s: Session) -> dict[str, Any]:
        row = s.get(IntInboxRow, bid)
        row.status, row.results, row.counts, row.finished_at = "completed", results, counts, utcnow()
        s.flush()
        audit(s, "integration_batch", bid, "process", {"entity": batch.entity, "counts": counts})
        return batch_record(row)

    return run_tx(ctx, finish), False, 200


STALE_BATCH = __import__("datetime").timedelta(minutes=15)


def _aware_dt(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def get_batch(ctx: AppContext, batch_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return batch_record(repo.get_row(s, IntInboxRow, batch_id, what="Batch"))


def list_batches(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(IntInboxRow)).scalar() or 0)
        rows = list(s.execute(select(IntInboxRow).order_by(IntInboxRow.received_at.desc(), IntInboxRow.id)
                              .limit(limit).offset(offset)).scalars())
        return page([batch_record(r, False) for r in rows], total, limit, offset)


def _rejected(ref: str, code: str, msg: str, **details: Any) -> dict[str, Any]:
    return {"ref": ref, "status": "rejected", "id": None, "errors": [{"code": code, "message": msg, **details}]}


SOR_KEY = {"item": "items", "supplier": "suppliers", "purchase_request": "purchase_requests",
           "work_order": "work_orders", "po_receipt": "po_receipts", "bom": "boms", "routing": "routings",
           "purchase_order": "purchase_orders", "demand_order": "demand_orders", "item_supplier": "item_suppliers",
           "stock_snapshot": "stock"}


def process(ctx: AppContext, batch: C.V1Batch) -> list[dict[str, Any]]:
    from ....integration import inbound

    ent = batch.entity
    with read_tx(ctx) as s:
        sor_key = SOR_KEY[ent]
        sor = sor_of(s, sor_key)
        maps = _maps(s)
    if ent == "purchase_request" or (sor == "superplanner" and ent not in ("stock_snapshot", "po_receipt")):
        return [_rejected(str(r.get("ref", ""))[:64] if isinstance(r, dict) else "", "INT_SOR_CONFLICT",
                          f"{sor_key.replace('_', ' ')} are maintained in SuperPlanner for this plant.")
                for r in batch.records]
    if batch.mode == "delete" and ent not in ("bom", "routing"):
        return [_rejected(str(r.get("ref", ""))[:64], "INT_SCHEMA", "Delete is not supported over the API; "
                          "deactivate or close the record instead.") for r in batch.records]
    if ent == "item":
        return _items(ctx, batch, maps, sor)
    if ent == "po_receipt":
        return _po_receipts(ctx, batch, maps)
    if ent in ("bom", "routing"):
        return inbound.documents(ctx, batch, maps)
    if ent == "stock_snapshot":
        return inbound.stock(ctx, batch, maps, sor)
    return inbound.via_bundle(ctx, batch, maps)


def _items(ctx: AppContext, batch: C.V1Batch, maps: dict[tuple[str, str], str], sor: str) -> list[dict[str, Any]]:
    from ....mfg.io.plan import ImportOptions, plan_import
    from ....mfg.units import UOM_CODES
    from .. import repo_m2, writer

    results: dict[int, dict[str, Any]] = {}
    rows: list[tuple[int, dict[str, Any], str]] = []
    for i, raw in enumerate(batch.records):
        ref = str(raw.get("ref", ""))[:64]
        try:
            rec = C.ItemV1.model_validate(raw)
        except ValidationError as e:
            results[i] = _rejected(ref, "INT_SCHEMA", "The record does not follow superplanner.v1.",
                                   fields=[".".join(map(str, x["loc"])) for x in e.errors()[:10]])
            continue
        uom = maps.get(("uom", rec.uom.upper()), rec.uom)
        if uom not in UOM_CODES:
            results[i] = _rejected(ref, "INT_UNMAPPED_VALUE", f"Unit {rec.uom!r} has no value map.", domain="uom",
                                   value=rec.uom)
            continue
        row = {"part_number": rec.part_number, "revision": rec.revision, "description": rec.description,
               "uom": uom, "make_buy": rec.make_buy, "active": rec.active, "external_ref": rec.ref,
               "standard_cost": rec.standard_cost}
        if sor != "erp" and rec.lead_time_days is not None:
            row["lead_time_days"] = rec.lead_time_days
        rows.append((i, row, ref))
    for k in range(0, len(rows), C.CHUNK):
        chunk = rows[k:k + C.CHUNK]
        with write_tx(ctx) as (s, plant):
            s.info["sp_inbound"] = True
            ds = repo_m2.load_import_dataset(s, with_txn=False)
            by_ref = {it.external_ref: it for it in ds.items.values() if it.external_ref}
            by_pn = {(it.part_number, it.revision): it for it in ds.items.values()}
            for i, row, ref in chunk:            # an ERP ref re-keys to the stored part number if it changed
                ex = by_ref.get(ref)
                if ex is not None and ex.part_number != row["part_number"]:
                    results[i] = _rejected(ref, "INT_SCHEMA", "Changing the part number of an existing item is not "
                                           "supported; create a new item.")
            live = [(i, row, ref) for i, row, ref in chunk if i not in results]
            before = {(r["part_number"], r["revision"]): by_pn.get((r["part_number"], r["revision"]))
                      for _i, r, _ref in live}
            for _attempt in range(3):
                plan = plan_import({"items": [r for _i, r, _ref in live]}, ds, ImportOptions(release=True),
                                   id_factory=new_id)
                if plan.ok:
                    break
                bad_rows = {int(e.get("row", 0)) for e in plan.row_errors if e.get("sheet") == "items"}
                keep = []
                for n, (i, r, ref) in enumerate(live, start=2):          # row 1 is the header row
                    if n in bad_rows:
                        errs = [e for e in plan.row_errors if int(e.get("row", 0)) == n][:5]
                        results[i] = _rejected(ref, "INT_SCHEMA", errs[0].get("message", "Invalid record.")
                                               if errs else "Invalid record.", details=errs)
                    else:
                        keep.append((i, r, ref))
                if len(keep) == len(live):
                    for i, _r, ref in live:
                        results[i] = _rejected(ref, "INT_SCHEMA", "The batch chunk could not be planned.",
                                               details=plan.row_errors[:5])
                    keep = []
                live = keep
                if not live:
                    break
            if live and plan.ok and plan.has_writes():
                writer.apply(s, plan, plant)
            changed = {c.id for c in plan.changes if c.table == "items"} if live else set()
            from ..db_models import MfgItemRow

            for i, r, ref in live:
                row = s.execute(select(MfgItemRow).where(MfgItemRow.part_number == r["part_number"],
                                                         MfgItemRow.revision == r["revision"])
                                .execution_options(populate_existing=True)).scalars().first()
                was = before.get((r["part_number"], r["revision"]))
                status = "created" if was is None else ("updated" if row is not None and row.id in changed
                                                        else "unchanged")
                results[i] = {"ref": ref, "status": status, "id": row.id if row else None, "errors": []}
                if sor == "shared" and row is not None:
                    track_shared(s, "items", row.id, ref, was.row_version if was is not None else None,
                                 row.row_version, status == "updated")
            if live:
                audit(s, "integration_batch", None, "items_chunk", {"records": len(live)})
    return [results[i] for i in range(len(batch.records))]


def _po_receipts(ctx: AppContext, batch: C.V1Batch, maps: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    """14 Q2 `goods_receipts_owner = erp`: each record posts one M2 `po_receipt` (idempotent per `ref`)."""
    from ....mfg.model_m2 import PoReceiptLine, PoReceiptPosting
    from ..db_models_m2 import (MfgInvPostingRow, MfgLocationRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                                MfgPurchaseScheduleRow)
    from .inventory import post_in_session

    with read_tx(ctx) as s:
        st = settings_row(s)
        owner = st.goods_receipts_owner if st is not None else "superplanner"
    out = []
    for raw in batch.records:
        ref = str(raw.get("ref", ""))[:64]
        if owner != "erp":
            out.append(_rejected(ref, "INT_SOR_CONFLICT", "Goods receipts are booked in SuperPlanner for this plant."))
            continue
        try:
            rec = C.PoReceiptV1.model_validate(raw)
        except ValidationError as e:
            out.append(_rejected(ref, "INT_SCHEMA", "The record does not follow superplanner.v1.",
                                 fields=[".".join(map(str, x["loc"])) for x in e.errors()[:10]]))
            continue
        key = f"erp-receipt:{rec.ref}"
        loc_code = maps.get(("location", rec.location_code.upper()), rec.location_code)

        def fn(s: Session) -> dict[str, Any]:
            s.info["sp_inbound"] = True
            done = s.execute(select(MfgInvPostingRow.id).where(MfgInvPostingRow.idempotency_key == key)).scalar()
            if done is not None:
                return {"ref": rec.ref, "status": "unchanged", "id": done, "errors": []}
            doc = s.execute(select(MfgPurchaseDocRow).where(MfgPurchaseDocRow.doc_type == "po", (
                (MfgPurchaseDocRow.external_ref == rec.po_ref) | (MfgPurchaseDocRow.number == rec.po_ref)))
            ).scalars().first()
            sc = None
            if doc is not None:
                sc = s.execute(select(MfgPurchaseScheduleRow).join(
                    MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).where(
                    MfgPurchaseLineRow.doc_id == doc.id, MfgPurchaseLineRow.line_no == rec.line_no,
                    MfgPurchaseScheduleRow.seq == rec.schedule_seq)).scalars().first()
            loc = s.execute(select(MfgLocationRow).where(MfgLocationRow.code == loc_code)).scalars().first()
            if sc is None or loc is None:
                return _rejected(rec.ref, "INT_UNMAPPED_VALUE", "Unknown PO schedule or location.",
                                 po=rec.po_ref, location=rec.location_code)
            try:
                with s.begin_nested():
                    row, _w = post_in_session(s, PoReceiptPosting.model_construct(
                        type="po_receipt", txn_date=None, note=f"ERP receipt {rec.ref}", reason_code=None,
                        lines=[PoReceiptLine.model_construct(schedule_id=sc.id, location_id=loc.id, qty=rec.qty,
                                                             lot_code=rec.lot_code, expires_on=None,
                                                             supplier_lot="", unit_cost=None)]),
                        system=True, txn_date=rec.received_on, idem=key, body_hash=key)
            except ApiError as e:
                return _rejected(rec.ref, e.code, e.message)
            return {"ref": rec.ref, "status": "created", "id": row.id, "errors": []}

        out.append(run_tx(ctx, fn))
    return out


# ---------------------------------------------------------------- endpoints, deliveries, events (4.6)

def _plant_ref(s: Session) -> dict[str, Any]:
    st = settings_row(s)
    p = repo.plant_or_default(s)
    return {"code": st.plant_code if st else "", "owner_id": getattr(p, "owner_id", None) or _owner()}


def _owner() -> str:
    from ...db.ownership import current_owner

    return str(current_owner() or "")


def endpoint_record(s: Session, r: IntEndpointRow) -> dict[str, Any]:
    cnt = dict(s.execute(select(IntDeliveryRow.status, func.count()).where(IntDeliveryRow.endpoint_id == r.id)
                         .group_by(IntDeliveryRow.status)).all())
    return {"id": r.id, "name": r.name, "url": r.url, "event_types": list(r.event_types or []), "active": r.active,
            "cursor": int(r.cursor), "secret_set": bool(r.secret_enc), "pending": int(cnt.get("pending", 0)),
            "dead": int(cnt.get("dead", 0)), "row_version": r.row_version, "created_at": as_utc(r.created_at)}


def list_endpoints(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return {"items": [endpoint_record(s, r) for r in s.execute(select(IntEndpointRow).order_by(
            IntEndpointRow.created_at)).scalars()]}


def _check_types(types: list[str]) -> None:
    bad = [t for t in types if t not in C.EVENT_TYPES]
    if bad:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown event type {bad[0]!r}.", {})


def create_endpoint(ctx: AppContext, inp: Any) -> dict[str, Any]:
    _check_types(inp.event_types)
    outbox.check_url(inp.url, ctx.settings.integration_allow_private_targets)
    if not inp.secret:
        raise ApiError(422, "VALIDATION_ERROR", "A signing secret is required.",
                       {"errors": [{"loc": ["body", "secret"], "msg": "required", "type": "missing"}]})
    enc = crypto.encrypt(ctx.settings.secrets_keys, inp.secret)

    def fn(s: Session) -> dict[str, Any]:
        seq = s.execute(select(func.max(IntOutboxRow.seq))).scalar() or 0     # new endpoints start at "now"
        now = utcnow()
        r = IntEndpointRow(id=new_id("iep_"), name=inp.name, url=inp.url, event_types=list(inp.event_types),
                           secret_enc=enc, active=inp.active, cursor=int(seq), row_version=1, created_at=now,
                           updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "integration_endpoint", r.id, "create", {"url": r.url})
        return endpoint_record(s, r)

    return run_tx(ctx, fn)


def update_endpoint(ctx: AppContext, endpoint_id: str, inp: Any, if_match: str | None) -> dict[str, Any]:
    _check_types(inp.event_types)
    outbox.check_url(inp.url, ctx.settings.integration_allow_private_targets)
    enc = crypto.encrypt(ctx.settings.secrets_keys, inp.secret) if inp.secret else None

    def fn(s: Session) -> dict[str, Any]:
        r = repo.get_row(s, IntEndpointRow, endpoint_id, what="Endpoint", lock=True)
        check_version(r, if_match)
        r.name, r.url, r.event_types, r.active = inp.name, inp.url, list(inp.event_types), inp.active
        if enc:
            r.secret_enc = enc
        touch(r)
        s.flush()
        audit(s, "integration_endpoint", r.id, "update", {"url": r.url, "secret_rotated": bool(enc)})
        return endpoint_record(s, r)

    return run_tx(ctx, fn)


def delete_endpoint(ctx: AppContext, endpoint_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        r = repo.get_row(s, IntEndpointRow, endpoint_id, what="Endpoint", lock=True)
        check_version(r, if_match)
        s.delete(r)
        audit(s, "integration_endpoint", r.id, "delete", {})

    run_tx(ctx, fn)


def deliver_now(ctx: AppContext, endpoint_id: str | None = None, post: outbox.Poster | None = None,
                now: datetime | None = None) -> dict[str, int]:
    """Deliver due events (per endpoint FIFO under the endpoint row lock). Used by the delivery job and tests."""
    allow = bool(ctx.settings.integration_allow_private_targets)
    def default_post(u: str, b: bytes, h: dict[str, str]) -> tuple[int, str]:
        try:
            proxy = outbox.proxy_config(getattr(ctx.settings, "webhook_proxy", None),
                                        getattr(ctx.settings, "webhook_proxy_connect", "ip"))
        except ValueError as e:                    # a failed attempt, visible in last_error
            return 0, f"WEBHOOK_PROXY: {e}"[:200]
        return outbox.pinned_post(u, b, h, allow_private=allow, proxy=proxy)

    post = post or getattr(ctx.settings, "webhook_post", None) or default_post
    totals = {"delivered": 0, "failed": 0, "dead": 0}
    with read_tx(ctx) as s:
        q = select(IntEndpointRow.id).where(IntEndpointRow.active.is_(True))
        if endpoint_id:
            q = q.where(IntEndpointRow.id == endpoint_id)
        ids = list(s.execute(q).scalars())
        if endpoint_id and not ids:
            repo.get_row(s, IntEndpointRow, endpoint_id, what="Endpoint")      # 404 (foreign / unknown / inactive)
    allow_chk = ctx.settings.integration_allow_private_targets
    for eid in ids:
        r = _deliver_endpoint(ctx, eid, post, now, allow_chk)
        for k, v in r.items():
            totals[k] = totals.get(k, 0) + v
    return totals


def _deliver_endpoint(ctx: AppContext, eid: str, post: Any, now: datetime | None, allow: bool,
                      max_events: int = 500) -> dict[str, int]:
    """One endpoint, FIFO: a session advisory lock (on its own connection) keeps one deliverer per endpoint while
    every step runs in its own short transaction and the HTTP call runs outside any transaction (minor 3)."""
    from sqlalchemy import text

    out = {"delivered": 0, "failed": 0, "dead": 0}
    with ctx.db.engine.connect() as lc:
        got = lc.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": "sp-deliver:" + eid}).scalar()
        lc.commit()
        if not got:
            return out
        try:
            with read_tx(ctx) as s:
                ep = s.get(IntEndpointRow, eid)
                if ep is None or not ep.active:
                    return out
                url, secret = ep.url, crypto.decrypt(ctx.settings.secrets_keys, ep.secret_enc)
                plant = _plant_ref(s)
            for _ in range(max_events):
                t = now or datetime.now(UTC)

                def prep(s: Session) -> dict[str, Any] | None:
                    ep2 = s.get(IntEndpointRow, eid)
                    return outbox.next_step(s, ep2, plant, t) if ep2 is not None else None

                step = run_tx(ctx, prep)
                if step is None:
                    break
                if step.get("stop") == "dead":
                    out["dead"] += 1
                    break
                code, err = outbox.send(step, url, secret, post, allow)

                def rec(s: Session) -> str:
                    ep2 = s.get(IntEndpointRow, eid, with_for_update=True)
                    return outbox.record_step(s, ep2, step, code, err, now or datetime.now(UTC)) \
                        if ep2 is not None else "failed"

                res = run_tx(ctx, rec)
                out[res] = out.get(res, 0) + 1
                if res != "delivered" and step["kind"] == "fifo":
                    break                                  # FIFO: a failure blocks the later events
        finally:
            lc.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": "sp-deliver:" + eid})
            lc.commit()
    return out


def deliver_all_job(ctx: Any, run_id: str, lease: Any) -> None:
    """`integration_delivery` (scheduled, 4.6): deliver due webhook events of every endpoint of the plant (FIFO,
    per-endpoint row lock with SKIP LOCKED), then the periodic file export when it is due."""
    from ....integration.jobs import run_duty

    def fn(info: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for _ in range(20):                         # up to 20 x 500 events per run
            r = deliver_now(ctx)
            for k, v in r.items():
                out[k] = out.get(k, 0) + v
            if r.get("delivered", 0) < 1 or r.get("failed") or r.get("dead"):
                break
        out["export"] = export_events(ctx)
        return out

    run_duty(ctx, run_id, lease, fn)


def export_events(ctx: Any, now: datetime | None = None, force: bool = False) -> dict[str, Any] | None:
    """4.6 file export: new events since `export_cursor` as one CSV per type plus a JSONL file in
    `INTEGRATION_ROOT/<code>/outbox/` (written to a temp name, then renamed: consumers never see partial files)."""
    import csv
    import io
    import os
    from pathlib import Path

    from ....integration.scheduler import export_is_due

    now = now or datetime.now(UTC)
    root = ctx.settings.integration_root

    def fn(s: Session) -> dict[str, Any] | None:
        st = s.execute(select(IntSettingsRow).with_for_update()).scalars().first()
        if st is None or not root or not st.plant_code:
            return None
        top = int(s.execute(select(func.max(IntOutboxRow.seq))).scalar() or 0)
        if not force and not export_is_due(st, top, now, ctx.settings):
            return None
        rows = list(s.execute(select(IntOutboxRow).where(IntOutboxRow.seq > st.export_cursor)
                              .order_by(IntOutboxRow.seq).limit(100_000)).scalars())
        if not rows:
            return None
        out_dir = Path(root) / st.plant_code / "outbox"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        plant = {"code": st.plant_code, "owner_id": st.owner_id}
        files = []
        by_type: dict[str, list[Any]] = {}
        jl = io.StringIO()
        for r in rows:
            ev = outbox._json(outbox.event_view(r, plant))
            jl.write(json.dumps(ev, sort_keys=True, separators=(",", ":")) + "\n")
            by_type.setdefault(r.type, []).append(ev)
        name = f"events-{stamp}-{rows[0].seq}-{rows[-1].seq}"
        payloads = {f"{name}.jsonl": jl.getvalue()}
        for typ, evs in by_type.items():
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "type", "occurred_at", "actor", "entity_ref", "data"])
            for e in evs:
                w.writerow([e["id"], e["type"], e["occurred_at"], e["actor"], "", json.dumps(e["data"],
                                                                                        sort_keys=True)])
            payloads[f"{name}-{typ.replace('.', '_')}.csv"] = buf.getvalue()
        for fname, body in payloads.items():
            tmp = out_dir / f".{fname}.tmp"
            tmp.write_text(body)
            os.replace(tmp, out_dir / fname)
            files.append(fname)
        st.export_cursor = int(rows[-1].seq)
        st.sor = {**(st.sor or {}), "_exported_at": now.isoformat()}
        s.flush()
        audit(s, "integration_export", st.id, "export", {"events": len(rows), "files": len(files)})
        return {"events": len(rows), "files": files, "cursor": int(rows[-1].seq)}

    return run_tx(ctx, fn)


def delivery_record(r: IntDeliveryRow, type_: str | None) -> dict[str, Any]:
    return {"id": r.id, "endpoint_id": r.endpoint_id, "event_seq": int(r.event_seq), "event_type": type_,
            "status": r.status, "attempts": r.attempts, "next_attempt_at": as_utc(r.next_attempt_at),
            "last_error": r.last_error, "last_status_code": r.last_status_code,
            "delivered_at": as_utc(r.delivered_at), "created_at": as_utc(r.created_at)}


def list_deliveries(ctx: AppContext, status: str | None, endpoint_id: str | None, limit: int, offset: int
                    ) -> dict[str, Any]:
    conds = []
    if status:
        conds.append(IntDeliveryRow.status == status)
    if endpoint_id:
        conds.append(IntDeliveryRow.endpoint_id == endpoint_id)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(IntDeliveryRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(IntDeliveryRow, IntOutboxRow.type).outerjoin(
            IntOutboxRow, IntOutboxRow.seq == IntDeliveryRow.event_seq).where(*conds)
            .order_by(IntDeliveryRow.event_seq.desc()).limit(limit).offset(offset)).all())
        return page([delivery_record(r, t) for r, t in rows], total, limit, offset)


def retry_delivery(ctx: AppContext, delivery_id: str) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        d = repo.get_row(s, IntDeliveryRow, delivery_id, what="Delivery", lock=True)
        if d.status == "delivered":
            raise ApiError(409, "MFG_INVALID_STATE", "This event was delivered.", {"status": d.status})
        d.status, d.next_attempt_at, d.created_at = "pending", utcnow(), utcnow()   # a fresh 24 h window
        if d.status == "pending":
            ep = s.get(IntEndpointRow, d.endpoint_id, with_for_update=True)
            if ep is not None and ep.cursor >= d.event_seq:         # un-park: send it on the next run
                d.status = "retry"
        s.flush()
        audit(s, "integration_delivery", d.id, "retry", {"event_seq": int(d.event_seq)})
        return delivery_record(d, None)

    return run_tx(ctx, fn)


def park_delivery(ctx: AppContext, delivery_id: str) -> dict[str, Any]:
    """Park a pending / dead delivery: its endpoint's FIFO moves past it (the cursor skips the event); the event
    stays retryable (`retry` / `unpark` sends it on the next run, out of order)."""
    def fn(s: Session) -> dict[str, Any]:
        d = repo.get_row(s, IntDeliveryRow, delivery_id, what="Delivery", lock=True)
        if d.status == "delivered":
            raise ApiError(409, "MFG_INVALID_STATE", "This event was delivered.", {"status": d.status})
        ep = s.get(IntEndpointRow, d.endpoint_id, with_for_update=True)
        d.status, d.next_attempt_at = "parked", None
        if ep is not None and ep.cursor < d.event_seq:
            ep.cursor = int(d.event_seq)
        s.flush()
        audit(s, "integration_delivery", d.id, "park", {"event_seq": int(d.event_seq)})
        return delivery_record(d, None)

    return run_tx(ctx, fn)


def ownership(ctx: AppContext) -> dict[str, Any]:
    """4.4 for every role: SoR per entity, the ERP-owned fields of each, who books goods receipts."""
    from ....integration.model import SOR_DEFAULTS

    owned = {"items": list(ITEM_ERP_FIELDS), "boms": ["document"], "routings": ["document"],
             "suppliers": ["document"], "item_suppliers": ["all except preferred"],
             "purchase_orders": ["header", "lines", "schedules"], "demand_orders": ["all except priority"],
             "work_orders": ["document"], "po_receipts": ["posting"]}
    with read_tx(ctx) as s:
        st = settings_row(s)
        on = bool(st and st.enabled)
        sor = {k: (sor_of(s, k) if on else "superplanner") for k in SOR_DEFAULTS}
    return {"enabled": on, "sor": sor, "goods_receipts_owner": st.goods_receipts_owner if st else "superplanner",
            "erp_fields": {k: v for k, v in owned.items() if sor.get(k) == "erp"}}


def pull_events(ctx: AppContext, after: int, limit: int, types: list[str] | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return outbox.events(s, after, limit, types, _plant_ref(s))


# ---------------------------------------------------------------- mapping profiles, file drop, reconciliation

def list_profiles(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return {"items": [{"id": r.id, "name": r.name, "file_pattern": r.file_pattern, "mapping": r.mapping,
                           "row_version": r.row_version} for r in s.execute(select(IntMappingProfileRow)).scalars()]}


def create_profile(ctx: AppContext, inp: Any) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        now = utcnow()
        r = IntMappingProfileRow(id=new_id("imp_"), name=inp.name, file_pattern=inp.file_pattern,
                                 mapping=inp.mapping, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "integration_profile", r.id, "create", {"name": r.name})
        return {"id": r.id, "name": r.name, "file_pattern": r.file_pattern, "mapping": r.mapping, "row_version": 1}

    return run_tx(ctx, fn)


def filedrop_status(ctx: AppContext) -> dict[str, Any]:
    from ....integration import filedrop
    from ..db_models_m5 import MaintenanceRunRow
    from ...db.ownership import current_owner, system_scope

    owner = current_owner()
    with system_scope(), ctx.db.read() as s:
        last = s.execute(select(MaintenanceRunRow).where(
            MaintenanceRunRow.kind == "integration_filedrop", MaintenanceRunRow.owner_scope_id == owner,
            MaintenanceRunRow.status == "completed").order_by(MaintenanceRunRow.created_at.desc()).limit(1)
        ).scalars().first()
        res = dict(last.results or {}) if last else None
    return filedrop.status(ctx, res)


def _snapshot_records(ctx: AppContext, s: Session, inp: Any) -> dict[str, list[dict[str, Any]]]:
    """4.8 snapshot sources: inline records, a JSON file in the plant's inbox (`{entity: [records]}`), or the
    adapter's `snapshot` (generic_v1 has none -> 422)."""
    if inp.snapshot == "inline":
        return dict(inp.records or {})
    if inp.snapshot == "file":
        import pathlib

        st = settings_row(s)
        root = ctx.settings.integration_root
        name = pathlib.PurePath(inp.file_name or "").name
        if not root or st is None or not name:
            raise ApiError(422, "VALIDATION_ERROR", "A file snapshot needs INTEGRATION_ROOT, a plant code and "
                           "file_name.", {})
        f = pathlib.Path(root) / st.plant_code / "inbox" / name
        if f.is_symlink() or not f.is_file():
            raise ApiError(422, "VALIDATION_ERROR", f"{name} is not in the plant's inbox.", {})
        if f.stat().st_size > 50_000_000:          # checked before reading (15.WP-S minor 5)
            raise ApiError(422, "MFG_IMPORT_TOO_LARGE", "The snapshot file is larger than 50 MB.", {})
        data = json.loads(f.read_bytes())
        return {k: list(v) for k, v in (data.get("records", data) or {}).items() if isinstance(v, list)}
    from ....integration.adapters import registry

    ad = registry.get((settings_row(s).adapter if settings_row(s) else "generic_v1"))
    out = {}
    for e in inp.entities:
        snap = ad.snapshot(e)
        if snap is None:
            raise ApiError(422, "VALIDATION_ERROR", f"The {ad.name} adapter cannot pull a {e} snapshot.", {})
        out[e] = [x.model_dump(mode="json") if hasattr(x, "model_dump") else x for x in snap]
    return out


def reconcile(ctx: AppContext, inp: Any) -> dict[str, Any]:
    """4.8: compare an ERP snapshot with SuperPlanner per record: `different` / `missing_in_sp` / `missing_in_erp`
    (stock by item x location x lot, tolerance 1e-6) and `sor_conflicts` (records of a SuperPlanner-owned entity, or
    of a `shared` entity changed on both sides). Never posts (`post_stock_counts` is the reviewed follow-up)."""
    summary: dict[str, Any] = {}
    results: dict[str, Any] = {}
    with read_tx(ctx) as s:
        maps = _maps(s)
        records = _snapshot_records(ctx, s, inp)
        for ent in inp.entities:
            fn = {"stock": _rec_stock, "items": _rec_items, "purchase_orders": _rec_pos}[ent]
            res = fn(s, records.get(ent, []) or records.get({"items": "item", "purchase_orders": "purchase_order",
                                                              "stock": "stock_snapshot"}[ent], []), maps)
            sor = sor_of(s, ent)
            res["sor_conflicts"] = ([{"entity": ent, "message": f"{ent} are maintained in SuperPlanner; the ERP "
                                      "snapshot is informational."}] if sor == "superplanner" and ent != "stock"
                                    else [])
            if ent == "items":                      # 4.4: conflicts of shared items / suppliers since the last sync
                res["sor_conflicts"] += shared_conflicts(s, ("items", "suppliers"))
            results[ent] = res
            summary[ent] = {k: len(v) for k, v in res.items()}
    now = utcnow()

    def fn(s: Session) -> dict[str, Any]:
        r = IntReconciliationRow(id=new_id("irc_"), entities=list(inp.entities), status="completed", summary=summary,
                                 results=results, snapshot=None, actor_id=actor_id(), created_at=now, finished_at=now)
        s.add(r)
        s.flush()
        audit(s, "integration_reconciliation", r.id, "run", {"summary": summary})
        return reconciliation_record(r)

    return run_tx(ctx, fn)


def _rec_stock(s: Session, raw_records: list[dict[str, Any]], maps: dict[tuple[str, str], str]) -> dict[str, Any]:
    from ..db_models import MfgItemRow
    from ..db_models_m2 import MfgInvBalanceRow, MfgLocationRow, MfgLotRow

    items = {i.id: i for i in s.execute(select(MfgItemRow)).scalars()}
    refs: dict[str, str] = {}
    for i in items.values():
        refs.setdefault(i.part_number, i.id)
        if i.external_ref:
            refs[i.external_ref] = i.id
    locs = {x.id: x.code for x in s.execute(select(MfgLocationRow)).scalars()}
    loc_ids = {v: k for k, v in locs.items()}
    lots = {x.id: x.lot_code for x in s.execute(select(MfgLotRow)).scalars()}
    sp: dict[tuple[str, str, str], float] = {}
    for b in s.execute(select(MfgInvBalanceRow)).scalars():
        k = (b.item_id, locs.get(b.location_id, ""), lots.get(b.lot_id, "") if b.lot_id else "")
        sp[k] = sp.get(k, 0.0) + float(b.qty_on_hand)
    erp: dict[tuple[str, str, str], float] = {}
    unknown = []
    for raw in raw_records:
        rec = C.StockSnapshotV1.model_validate(raw)
        iid = refs.get(rec.item_ref)
        if iid is None:
            unknown.append({"item_ref": rec.item_ref, "location": rec.location_code, "lot": rec.lot_code or "",
                            "erp_qty": rec.qty, "sp_qty": None})
            continue
        loc = maps.get(("location", rec.location_code.upper()), rec.location_code)
        k = (iid, loc, rec.lot_code or "")
        erp[k] = erp.get(k, 0.0) + rec.qty
    diff, miss_sp, miss_erp = [], [], []
    for k in sorted(set(sp) | set(erp)):
        a, b = sp.get(k), erp.get(k)
        it = items.get(k[0])
        row = {"item": it.part_number if it else k[0], "item_id": k[0],
               "item_ref": (it.external_ref or it.part_number) if it else k[0], "location": k[1],
               "location_id": loc_ids.get(k[1]), "lot": k[2], "sp_qty": a, "erp_qty": b}
        if a is None:
            miss_sp.append(row)
            continue
        if b is None:
            if abs(a or 0) > 1e-6:
                miss_erp.append(row)
            continue
        if abs(a - b) > 1e-6:
            diff.append({**row, "delta": round(b - a, 6)})
    return {"different": diff, "missing_in_sp": miss_sp + unknown, "missing_in_erp": miss_erp}


def _rec_items(s: Session, raw_records: list[dict[str, Any]], maps: dict[tuple[str, str], str]) -> dict[str, Any]:
    from ..db_models import MfgItemRow

    items = list(s.execute(select(MfgItemRow)).scalars())
    by = {}
    for i in items:
        by.setdefault(i.part_number, i)
        if i.external_ref:
            by[f"ref:{i.external_ref}"] = i
    seen, diff, miss_sp = set(), [], []
    for raw in raw_records:
        rec = C.ItemV1.model_validate(raw)
        it = by.get(f"ref:{rec.ref}") or by.get(rec.part_number)
        if it is None:
            miss_sp.append({"ref": rec.ref, "part_number": rec.part_number})
            continue
        seen.add(it.id)
        uom = maps.get(("uom", rec.uom.upper()), rec.uom)
        fields = {f: (getattr(it, f), v) for f, v in (("part_number", rec.part_number), ("revision", rec.revision),
                                                       ("description", rec.description), ("uom", uom),
                                                       ("make_buy", rec.make_buy), ("active", rec.active),
                                                       ("standard_cost", rec.standard_cost))
                  if v is not None and getattr(it, f) != v}
        if fields:
            diff.append({"ref": rec.ref, "part_number": it.part_number, "item_id": it.id,
                         "fields": {k: {"sp": a, "erp": b} for k, (a, b) in fields.items()}})
    miss_erp = [{"ref": i.external_ref, "part_number": i.part_number, "item_id": i.id} for i in items
                if i.external_ref and i.id not in seen] if raw_records else []
    return {"different": diff, "missing_in_sp": miss_sp, "missing_in_erp": miss_erp}


def _rec_pos(s: Session, raw_records: list[dict[str, Any]], maps: dict[tuple[str, str], str]) -> dict[str, Any]:
    from ..db_models_m2 import MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow

    docs = {d.number: d for d in s.execute(select(MfgPurchaseDocRow).where(MfgPurchaseDocRow.doc_type == "po"))
            .scalars()}
    seen, diff, miss_sp = set(), [], []
    for raw in raw_records:
        rec = C.PurchaseOrderV1.model_validate(raw)
        d = docs.get(rec.number)
        if d is None:
            miss_sp.append({"ref": rec.ref, "number": rec.number})
            continue
        seen.add(d.number)
        sched = {(ln.line_no, sc.seq): sc for ln, sc in s.execute(select(MfgPurchaseLineRow, MfgPurchaseScheduleRow)
                                                                  .join(MfgPurchaseScheduleRow,
                                                                        MfgPurchaseScheduleRow.line_id ==
                                                                        MfgPurchaseLineRow.id)
                                                                  .where(MfgPurchaseLineRow.doc_id == d.id)).all()}
        out = []
        for ln in rec.lines:
            for sc in ln.schedules:
                x = sched.pop((ln.line_no, sc.seq), None)
                if x is None:
                    out.append({"line_no": ln.line_no, "seq": sc.seq, "issue": "missing_in_sp"})
                    continue
                f = {}
                if abs(x.qty - sc.qty) > 1e-6:
                    f["qty"] = {"sp": x.qty, "erp": sc.qty}
                if sc.received_qty is not None and abs(x.received_qty - sc.received_qty) > 1e-6:
                    f["received_qty"] = {"sp": x.received_qty, "erp": sc.received_qty}
                if x.requested_date != sc.requested_date:
                    f["requested_date"] = {"sp": x.requested_date.isoformat(), "erp": sc.requested_date.isoformat()}
                if f:
                    out.append({"line_no": ln.line_no, "seq": sc.seq, "fields": f})
        out += [{"line_no": k[0], "seq": k[1], "issue": "missing_in_erp"} for k in sorted(sched)]
        if out or (rec.status != d.status and not (rec.status == "open" and d.status in
                                                   ("partially_received", "received"))):
            diff.append({"number": rec.number, "status": {"sp": d.status, "erp": rec.status}, "schedules": out})
    miss_erp = [{"number": n} for n, d in sorted(docs.items()) if n not in seen and d.external_ref] \
        if raw_records else []
    return {"different": diff, "missing_in_sp": miss_sp, "missing_in_erp": miss_erp}


def post_stock_counts(ctx: AppContext, rec_id: str, *, reason: str = "ERP_SYNC", system: bool = False
                      ) -> dict[str, Any]:
    """Turn a stock reconciliation's differences into one `count` posting (items set to the ERP quantity). Used
    automatically only when stock SoR is `erp` (4.8)."""
    from ....mfg.model_m2 import CountLine, CountPosting
    from .inventory import post_in_session, posting_record

    def fn(s: Session) -> dict[str, Any]:
        r = repo.get_row(s, IntReconciliationRow, rec_id, what="Reconciliation", lock=True)
        res = (r.results or {}).get("stock") or {}
        rows = [x for x in res.get("different", []) + res.get("missing_in_sp", []) + res.get("missing_in_erp", [])
                if x.get("item_id") and x.get("location_id")]
        if not rows:
            return {"posting": None, "lines": []}
        lines = [CountLine.model_construct(item_id=x["item_id"], location_id=x["location_id"],
                                           counted_qty=float(x.get("erp_qty") or 0.0), lot_code=x["lot"] or None,
                                           expires_on=None) for x in rows]
        s.info["sp_inbound"] = True
        row, w = post_in_session(s, CountPosting.model_construct(type="count", txn_date=None,
                                                                 note=f"ERP stock sync {r.id}", reason_code=reason,
                                                                 lines=lines), system=system)
        r.snapshot = {**(r.snapshot or {}), "posting_id": row.id}
        s.flush()
        audit(s, "integration_reconciliation", r.id, "post_counts", {"posting": row.number, "lines": len(rows),
                                                                     "reason": reason})
        return {"posting": posting_record(s, row, w), "lines": rows}

    return run_tx(ctx, fn, lock=True)


def export_reconciliation(ctx: AppContext, rec_id: str, fmt: str) -> tuple[bytes, str, str]:
    """xlsx (one sheet per entity x kind) or CSV (entity, kind, data as JSON) of a reconciliation (4.8)."""
    import csv
    import io

    rec = get_reconciliation(ctx, rec_id)
    rows = [(ent, kind, x) for ent, res in (rec["results"] or {}).items() for kind, items in res.items()
            for x in items]
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["entity", "kind", "item", "location", "lot", "sp_qty", "erp_qty", "delta", "details"])
        for ent, kind, x in rows:
            w.writerow([ent, kind, x.get("item") or x.get("part_number") or x.get("number") or x.get("item_ref"),
                        x.get("location"), x.get("lot"), x.get("sp_qty"), x.get("erp_qty"), x.get("delta"),
                        json.dumps(x, sort_keys=True, default=str)])
        return buf.getvalue().encode(), "text/csv", f"reconciliation-{rec_id}.csv"
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("summary")
    ws.append(["entity", "kind", "count"])
    for ent, sm in (rec["summary"] or {}).items():
        for k, v in sm.items():
            ws.append([ent, k, v])
    for ent, res in (rec["results"] or {}).items():
        for kind, items in res.items():
            sh = wb.create_sheet(f"{ent}_{kind}"[:31])
            cols = sorted({k for x in items for k in x}) or ["(none)"]
            sh.append(cols)
            for x in items:
                sh.append([json.dumps(x[c], default=str) if isinstance(x.get(c), (dict, list)) else x.get(c)
                           for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", \
        f"reconciliation-{rec_id}.xlsx"


def reconciliation_record(r: IntReconciliationRow) -> dict[str, Any]:
    return {"id": r.id, "entities": r.entities, "status": r.status, "summary": r.summary, "results": r.results,
            "created_at": as_utc(r.created_at), "finished_at": as_utc(r.finished_at)}


def get_reconciliation(ctx: AppContext, rid: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return reconciliation_record(repo.get_row(s, IntReconciliationRow, rid, what="Reconciliation"))


def list_reconciliations(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(IntReconciliationRow)).scalar() or 0)
        rows = list(s.execute(select(IntReconciliationRow).order_by(IntReconciliationRow.created_at.desc())
                              .limit(limit).offset(offset)).scalars())
        return page([{**reconciliation_record(r), "results": None} for r in rows], total, limit, offset)


_ = (UTC, not_found)
