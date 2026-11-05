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

    return run_tx(ctx, fn)


def check_local_item_write(s: Session, before: Any | None, after: Any) -> None:
    """409 `INT_ERP_OWNED` for a local change of an ERP-owned item field (4.4; inbound writes bypass this)."""
    if s.info.get("sp_inbound") or sor_of(s, "items") != "erp":
        return
    changed = [f for f in ITEM_ERP_FIELDS if before is None or getattr(before, f, None) != getattr(after, f, None)]
    if before is None:
        changed = ["part_number"]
    if changed:
        raise ApiError(409, "INT_ERP_OWNED", "These item fields are maintained in the ERP.", {"fields": changed})


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


def post_batch(ctx: AppContext, body: dict[str, Any], key: str | None) -> tuple[dict[str, Any], bool, int]:
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
            return batch_record(found), True, 200
    now = utcnow()

    def create(s: Session) -> str:
        row = IntInboxRow(id=new_id("inb_"), source="rest", idempotency_key=key, entity=batch.entity, mode=batch.mode,
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

    bid = run_tx(ctx, create)
    results = process(ctx, batch)
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


def process(ctx: AppContext, batch: C.V1Batch) -> list[dict[str, Any]]:
    ent = batch.entity
    with read_tx(ctx) as s:
        sor_key = {"item": "items", "supplier": "suppliers", "purchase_request": "purchase_requests",
                   "work_order": "work_orders", "po_receipt": "po_receipts", "bom": "boms", "routing": "routings",
                   "purchase_order": "purchase_orders", "demand_order": "demand_orders",
                   "item_supplier": "item_suppliers", "stock_snapshot": "stock"}[ent]
        sor = sor_of(s, sor_key)
        maps = _maps(s)
    out: list[dict[str, Any]] = []
    for raw in batch.records:
        ref = str(raw.get("ref", ""))[:64] if isinstance(raw, dict) else ""
        if ent in SP_OWNED_ENTITIES or (sor == "superplanner" and ent not in ("stock_snapshot",)):
            out.append(_rejected(ref, "INT_SOR_CONFLICT", f"{sor_key.replace('_', ' ')} are maintained in "
                                 "SuperPlanner for this plant."))
    if out:
        return out
    if ent == "item":
        return _items(ctx, batch, maps, sor)
    if ent == "po_receipt":
        return _po_receipts(ctx, batch, maps)
    return [_rejected(str(r.get("ref", ""))[:64], "INT_SCHEMA", f"{ent} records are not processed in this build.")
            for r in batch.records]


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
                                                         MfgItemRow.revision == r["revision"])).scalars().first()
                was = before.get((r["part_number"], r["revision"]))
                status = "created" if was is None else ("updated" if row is not None and row.id in changed
                                                        else "unchanged")
                results[i] = {"ref": ref, "status": status, "id": row.id if row else None, "errors": []}
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
    post = post or getattr(ctx.settings, "webhook_post", None) or outbox.http_post
    totals = {"delivered": 0, "failed": 0, "dead": 0}
    with read_tx(ctx) as s:
        q = select(IntEndpointRow.id).where(IntEndpointRow.active.is_(True))
        if endpoint_id:
            q = q.where(IntEndpointRow.id == endpoint_id)
        ids = list(s.execute(q).scalars())
        if endpoint_id and not ids:
            repo.get_row(s, IntEndpointRow, endpoint_id, what="Endpoint")      # 404 (foreign / unknown / inactive)
    for eid in ids:
        def fn(s: Session) -> dict[str, int]:
            ep = s.get(IntEndpointRow, eid, with_for_update={"skip_locked": True})
            if ep is None:
                return {}
            secret = crypto.decrypt(ctx.settings.secrets_keys, ep.secret_enc)
            return outbox.deliver_endpoint(s, ep, secret, _plant_ref(s), post, now,
                                           allow_private=ctx.settings.integration_allow_private_targets)
        for k, v in run_tx(ctx, fn).items():
            totals[k] = totals.get(k, 0) + v
    return totals


def deliver_all_job(ctx: Any, run_id: str, lease: Any) -> None:  # pragma: no cover - scheduling (S2)
    raise NotImplementedError


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
        s.flush()
        audit(s, "integration_delivery", d.id, "retry", {"event_seq": int(d.event_seq)})
        return delivery_record(d, None)

    return run_tx(ctx, fn)


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
    with read_tx(ctx) as s:
        st = settings_row(s)
    return {"enabled": bool(st and st.filedrop_enabled), "root": ctx.settings.integration_root, "inbox": [],
            "recent": [], "last_poll_at": None}


def reconcile(ctx: AppContext, inp: Any) -> dict[str, Any]:
    """4.8, inline snapshots of stock (item x location x lot, tolerance 1e-6): `different` / `missing_in_sp` /
    `missing_in_erp`; never posts (counts are reviewed by a store keeper unless stock SoR is `erp`)."""
    from ..db_models import MfgItemRow
    from ..db_models_m2 import MfgInvBalanceRow, MfgLocationRow, MfgLotRow

    summary: dict[str, Any] = {}
    results: dict[str, Any] = {}
    with read_tx(ctx) as s:
        maps = _maps(s)
        if "stock" in inp.entities:
            items = {i.id: i for i in s.execute(select(MfgItemRow)).scalars()}
            refs = {(i.external_ref or i.part_number): i.id for i in items.values()}
            locs = {x.id: x.code for x in s.execute(select(MfgLocationRow)).scalars()}
            lots = {x.id: x.lot_code for x in s.execute(select(MfgLotRow)).scalars()}
            sp: dict[tuple[str, str, str], float] = {}
            for b in s.execute(select(MfgInvBalanceRow)).scalars():
                k = (b.item_id, locs.get(b.location_id, ""), lots.get(b.lot_id, "") if b.lot_id else "")
                sp[k] = sp.get(k, 0.0) + float(b.qty_on_hand)
            erp: dict[tuple[str, str, str], float] = {}
            unknown = []
            for raw in inp.records.get("stock", []):
                rec = C.StockSnapshotV1.model_validate(raw)
                iid = refs.get(rec.item_ref)
                if iid is None:
                    unknown.append(rec.item_ref)
                    continue
                loc = maps.get(("location", rec.location_code.upper()), rec.location_code)
                k = (iid, loc, rec.lot_code or "")
                erp[k] = erp.get(k, 0.0) + rec.qty
            diff, miss_sp, miss_erp = [], [], []
            for k in sorted(set(sp) | set(erp)):
                a, b = sp.get(k), erp.get(k)
                row = {"item": items[k[0]].part_number if k[0] in items else k[0], "location": k[1], "lot": k[2],
                       "sp_qty": a, "erp_qty": b}
                if a is None:
                    miss_sp.append(row)
                    continue
                if b is None:
                    if abs(a or 0) > 1e-6:
                        miss_erp.append(row)
                    continue
                if abs(a - b) > 1e-6:
                    diff.append({**row, "delta": round(b - a, 6)})
            results["stock"] = {"different": diff, "missing_in_sp": miss_sp + [{"item_ref": u} for u in unknown],
                                "missing_in_erp": miss_erp}
            summary["stock"] = {"different": len(diff), "missing_in_sp": len(miss_sp) + len(unknown),
                                "missing_in_erp": len(miss_erp), "sor_conflicts": 0}
    now = utcnow()

    def fn(s: Session) -> dict[str, Any]:
        r = IntReconciliationRow(id=new_id("irc_"), entities=list(inp.entities), status="completed", summary=summary,
                                 results=results, snapshot=None, actor_id=actor_id(), created_at=now, finished_at=now)
        s.add(r)
        s.flush()
        audit(s, "integration_reconciliation", r.id, "run", {"summary": summary})
        return reconciliation_record(r)

    return run_tx(ctx, fn)


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
