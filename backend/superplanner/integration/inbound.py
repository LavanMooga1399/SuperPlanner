"""Inbound `superplanner.v1` records -> the M1 import plan / M2 postings (M5-DESIGN 4.3, 4.4; I1).

Every entity of 4.2 is mapped to the M1 bundle sheets it corresponds to and goes through `plan_import` +
`writer.apply` (same validation, plant lock and audit as the import wizard), in chunks of `CHUNK` records per
transaction. Each bundle row carries a `Source` naming its record, so plan row errors reject exactly that record;
the chunk is re-planned without it (at most 3 passes).

System of record (4.4) on the inbound side:
- an entity owned by SuperPlanner -> every record `rejected` `INT_SOR_CONFLICT`;
- SuperPlanner-owned fields of ERP-owned entities are never written by inbound records (item planning fields,
  item-supplier `preferred`, demand priorities); on create they take the record value or the default;
- BOMs / routings: a structure that differs from the current released document becomes a new draft version
  released through an auto-approved ECO (`source erp`, 5) in the record's own transaction;
- stock snapshots: a reconciliation run (4.8), or `count` postings reason `ERP_SYNC` when stock SoR is `erp`.

Record status: `created` (natural key new), `updated` (the plan changed the document or one of its children),
`unchanged`, `rejected`.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import contract as C

EPS = 1e-9
DEMAND_TYPES = {"customer": "customer", "forecast": "internal", "program": "project", "safety": "internal"}


class Reject(Exception):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def rejected(ref: str, code: str, msg: str, **details: Any) -> dict[str, Any]:
    return {"ref": ref, "status": "rejected", "id": None, "errors": [{"code": code, "message": msg, **details}]}


def _schema(ref: str, e: ValidationError) -> dict[str, Any]:
    return rejected(ref, "INT_SCHEMA", "The record does not follow superplanner.v1.",
                    fields=[".".join(map(str, x["loc"])) for x in e.errors()[:10]])


# ---------------------------------------------------------------- reference resolution

class Refs:
    """External keys -> natural keys of the plant (items by external_ref else part number, suppliers by
    external_ref else code), value maps applied."""

    def __init__(self, s: Session, maps: dict[tuple[str, str], str]):
        from ..api.mfg.db_models import MfgItemRow
        from ..api.mfg.db_models_m2 import MfgSupplierRow

        self.maps = maps
        self.items: dict[str, Any] = {}
        for it in s.execute(select(MfgItemRow)).scalars():
            self.items.setdefault(it.part_number, it)
            if it.external_ref:
                self.items[f"ref:{it.external_ref}"] = it
        self.sups: dict[str, Any] = {}
        for x in s.execute(select(MfgSupplierRow)).scalars():
            self.sups.setdefault(x.code, x)
            if x.external_ref:
                self.sups[f"ref:{x.external_ref}"] = x

    def item(self, ref: str, what: str = "item_ref") -> Any:
        it = self.items.get(f"ref:{ref}") or self.items.get(ref)
        if it is None:
            raise Reject("INT_UNMAPPED_VALUE", f"Item {ref!r} is not known in this plant.", field=what, value=ref)
        return it

    def supplier(self, ref: str) -> Any:
        x = self.sups.get(f"ref:{ref}") or self.sups.get(ref)
        if x is None:
            raise Reject("INT_UNMAPPED_VALUE", f"Supplier {ref!r} is not known in this plant.", field="supplier_ref",
                         value=ref)
        return x

    def uom(self, v: str | None) -> str | None:
        from ..mfg.units import UOM_CODES

        if v is None:
            return None
        u = self.maps.get(("uom", v.upper()), v)
        if u not in UOM_CODES:
            raise Reject("INT_UNMAPPED_VALUE", f"Unit {v!r} has no value map.", domain="uom", value=v)
        return u

    def location(self, v: str) -> str:
        return self.maps.get(("location", v.upper()), v)

    def status(self, v: str) -> str:
        return self.maps.get(("status", v.upper()), v)


# ---------------------------------------------------------------- record -> bundle rows (+ natural key)

Rows = dict[str, list[dict[str, Any]]]


def _supplier(rec: C.SupplierV1, R: Refs, s: Session) -> tuple[Rows, tuple]:
    row = {"code": rec.code, "name": rec.name, "active": rec.active, "external_ref": rec.ref}
    if rec.lead_time_days is not None:
        row["lead_time_days"] = rec.lead_time_days
    return {"suppliers": [row]}, ("supplier", rec.code)


def _item_supplier(rec: C.ItemSupplierV1, R: Refs, s: Session) -> tuple[Rows, tuple]:
    from ..api.mfg.db_models_m2 import MfgItemSupplierRow

    it, sup = R.item(rec.item_ref), R.supplier(rec.supplier_ref)
    row: dict[str, Any] = {"part_number": it.part_number, "supplier_code": sup.code,
                           "supplier_part_number": rec.supplier_part_number}
    for f, v in (("lead_time_days", rec.lead_time_days), ("min_order_qty", rec.moq),
                 ("order_multiple", rec.order_multiple), ("unit_price", rec.price)):
        if v is not None:
            row[f] = v
    exists = s.execute(select(MfgItemSupplierRow.id).where(MfgItemSupplierRow.item_id == it.id,
                                                           MfgItemSupplierRow.supplier_id == sup.id)).first()
    if exists is None and rec.preferred is not None:        # SuperPlanner-owned: only the initial value
        row["preferred"] = rec.preferred
    return {"item_suppliers": [row]}, ("item_supplier", it.id, sup.id)


def _purchase_order(rec: C.PurchaseOrderV1, R: Refs, s: Session) -> tuple[Rows, tuple]:
    sup = R.supplier(rec.supplier_ref)
    hdr = {"doc_type": "po", "number": rec.number, "status": R.status(rec.status), "supplier_code": sup.code,
           "external_ref": rec.ref}
    if rec.currency:
        hdr["currency"] = rec.currency
    if rec.order_date:
        hdr["order_date"] = rec.order_date
    lines, scheds = [], []
    for ln in rec.lines:
        it = R.item(ln.item_ref)
        lr = {"doc_type": "po", "number": rec.number, "line_no": ln.line_no, "part_number": it.part_number}
        if ln.unit_price is not None:
            lr["unit_price"] = ln.unit_price
        lines.append(lr)
        for sc in ln.schedules:
            sr = {"doc_type": "po", "number": rec.number, "line_no": ln.line_no, "seq": sc.seq,
                  "requested_date": sc.requested_date, "qty": sc.qty}
            if sc.confirmed_date:
                sr["confirmed_date"] = sc.confirmed_date
            scheds.append(sr)
    return {"purchase_docs": [hdr], "purchase_lines": lines, "purchase_schedules": scheds}, ("po", rec.number)


def _demand_order(rec: C.DemandOrderV1, R: Refs, s: Session) -> tuple[Rows, tuple]:
    from ..api.mfg.db_models_m2 import MfgDemandOrderRow

    exists = s.execute(select(MfgDemandOrderRow.id).where(MfgDemandOrderRow.number == rec.number)).first()
    hdr = {"number": rec.number, "demand_type": DEMAND_TYPES[rec.demand_type], "customer": rec.customer,
           "program": rec.program, "status": "open", "external_ref": rec.ref}
    lines = []
    for ln in rec.lines:
        it = R.item(ln.item_ref)
        r = {"number": rec.number, "line_no": ln.line_no, "part_number": it.part_number, "qty": ln.qty,
             "due_date": ln.due_date}
        if exists is None and ln.priority is not None:      # priority is SuperPlanner-owned (4.4)
            r["priority"] = ln.priority
        lines.append(r)
    return {"demand_orders": [hdr], "demand_lines": lines}, ("demand", rec.number)


def _work_order(rec: C.WorkOrderV1, R: Refs, s: Session) -> tuple[Rows, tuple]:
    it = R.item(rec.item_ref)
    row = {"number": rec.number, "part_number": it.part_number, "qty": rec.qty, "due_date": rec.due_date,
           "priority": rec.priority, "external_ref": rec.ref}
    if rec.start_date:
        row["start_date"] = rec.start_date
    return {"work_orders": [row]}, ("wo", rec.number)


MAPPERS: dict[str, tuple[type, Callable[..., tuple[Rows, tuple]]]] = {
    "supplier": (C.SupplierV1, _supplier), "item_supplier": (C.ItemSupplierV1, _item_supplier),
    "purchase_order": (C.PurchaseOrderV1, _purchase_order), "demand_order": (C.DemandOrderV1, _demand_order),
    "work_order": (C.WorkOrderV1, _work_order)}


def _doc_ids(s: Session, key: tuple) -> tuple[str | None, set[str]]:
    """(document id, ids of its child rows) of a natural key after apply."""
    from ..api.mfg.db_models_m2 import (MfgDemandLineRow, MfgDemandOrderRow, MfgItemSupplierRow, MfgPurchaseDocRow,
                                        MfgPurchaseLineRow, MfgPurchaseScheduleRow, MfgSupplierRow,
                                        MfgWoComponentRow, MfgWorkOrderRow)

    k = key[0]
    if k == "supplier":
        return s.execute(select(MfgSupplierRow.id).where(MfgSupplierRow.code == key[1])).scalar(), set()
    if k == "item_supplier":
        return s.execute(select(MfgItemSupplierRow.id).where(MfgItemSupplierRow.item_id == key[1],
                                                             MfgItemSupplierRow.supplier_id == key[2])).scalar(), set()
    if k == "po":
        d = s.execute(select(MfgPurchaseDocRow.id).where(MfgPurchaseDocRow.doc_type == "po",
                                                         MfgPurchaseDocRow.number == key[1])).scalar()
        if d is None:
            return None, set()
        lines = set(s.execute(select(MfgPurchaseLineRow.id).where(MfgPurchaseLineRow.doc_id == d)).scalars())
        sc = set(s.execute(select(MfgPurchaseScheduleRow.id).where(MfgPurchaseScheduleRow.line_id.in_(lines)))
                 .scalars()) if lines else set()
        return d, lines | sc
    if k == "demand":
        d = s.execute(select(MfgDemandOrderRow.id).where(MfgDemandOrderRow.number == key[1])).scalar()
        return d, set(s.execute(select(MfgDemandLineRow.id).where(MfgDemandLineRow.order_id == d)).scalars()) \
            if d else set()
    if k == "wo":
        d = s.execute(select(MfgWorkOrderRow.id).where(MfgWorkOrderRow.number == key[1])).scalar()
        return d, set(s.execute(select(MfgWoComponentRow.id).where(MfgWoComponentRow.wo_id == d)).scalars()) \
            if d else set()
    return None, set()


def via_bundle(ctx: Any, batch: C.V1Batch, maps: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    from ..api.db import new_id
    from ..api.mfg import repo_m2, writer
    from ..api.mfg.services.common import audit, write_tx
    from ..mfg.io.mapping import Source
    from ..mfg.io.plan import ImportOptions, plan_import

    model, mapper = MAPPERS[batch.entity]
    n = len(batch.records)
    results: dict[int, dict[str, Any]] = {}
    parsed: list[tuple[int, Any]] = []
    for i, raw in enumerate(batch.records):
        ref = str(raw.get("ref", ""))[:64] if isinstance(raw, dict) else ""
        try:
            parsed.append((i, model.model_validate(raw)))
        except ValidationError as e:
            results[i] = _schema(ref, e)
    opts = ImportOptions(replace_children=batch.mode == "replace_children", release=False)
    for k in range(0, len(parsed), C.CHUNK):
        chunk = parsed[k:k + C.CHUNK]
        with write_tx(ctx) as (s, plant):
            s.info["sp_inbound"] = True
            R = Refs(s, maps)
            rows_of: dict[int, tuple[Rows, tuple]] = {}
            for i, rec in chunk:
                try:
                    rows_of[i] = mapper(rec, R, s)
                except Reject as e:
                    results[i] = rejected(rec.ref, e.code, e.message, **e.details)
            before = {i: _doc_ids(s, key)[0] for i, (_r, key) in rows_of.items()}
            live = [i for i, _r in chunk if i in rows_of]
            plan = None
            for _attempt in range(3):
                if not live:
                    break
                bundle: Rows = {}
                sources: dict[str, list[Source]] = {}
                for i in live:
                    for sheet, rws in rows_of[i][0].items():
                        for r in rws:
                            bundle.setdefault(sheet, []).append(r)
                            sources.setdefault(sheet, []).append(Source(f"r{i}", i + 2))
                ds = repo_m2.load_import_dataset(s, with_txn=True)
                plan = plan_import(bundle, ds, opts, sources=sources, id_factory=new_id)
                if plan.ok:
                    break
                bad: dict[int, list[dict[str, Any]]] = {}
                for e in plan.row_errors:
                    sh = str(e.get("sheet") or "")
                    if sh.startswith("r") and sh[1:].isdigit():
                        bad.setdefault(int(sh[1:]), []).append(e)
                if not bad:                       # an error without a record: reject the whole chunk
                    for i in live:
                        results[i] = rejected(chunk_ref(batch, i), "INT_SCHEMA", "The chunk could not be planned.",
                                              details=plan.row_errors[:5])
                    live = []
                    break
                for i, errs in bad.items():
                    results[i] = rejected(chunk_ref(batch, i), "INT_SCHEMA", errs[0].get("message", "Invalid."),
                                          details=[{kk: v for kk, v in x.items() if kk != "sheet"} for x in errs[:5]])
                live = [i for i in live if i not in bad]
            if live and plan is not None and plan.ok:
                if plan.has_writes():
                    writer.apply(s, plan, plant)
                changed = {c.id for c in plan.changes if isinstance(c.id, str)}
                changed |= {v for c in plan.changes if c.action == "create" for v in c.values.values()
                            if isinstance(v, str)}
                for i in live:
                    rec_ref = chunk_ref(batch, i)
                    did, kids = _doc_ids(s, rows_of[i][1])
                    st = "created" if before[i] is None else (
                        "updated" if did in changed or kids & changed else "unchanged")
                    results[i] = {"ref": rec_ref, "status": st, "id": did, "errors": []}
                audit(s, "integration_batch", None, f"{batch.entity}_chunk", {"records": len(live)})
    return [results[i] for i in range(n)]


def chunk_ref(batch: C.V1Batch, i: int) -> str:
    raw = batch.records[i]
    return str(raw.get("ref", ""))[:64] if isinstance(raw, dict) else ""


# ---------------------------------------------------------------- BOMs / routings through ECO (4.4, 5)

def _lines_sig(lines: list[Any]) -> list[tuple]:
    return sorted((str(ln[0]), ln[1], round(float(ln[2]), 6), ln[3] or "", round(float(ln[4] or 0), 6),
                   ln[5] or "", ln[6]) for ln in lines)


def documents(ctx: Any, batch: C.V1Batch, maps: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    """One transaction per document (a release failure rejects only that record)."""
    from ..api.errors import ApiError
    from ..api.mfg.services.m2util import run_tx

    is_bom = batch.entity == "bom"
    model = C.BomV1 if is_bom else C.RoutingV1
    out = []
    for raw in batch.records:
        ref = str(raw.get("ref", ""))[:64] if isinstance(raw, dict) else ""
        try:
            rec = model.model_validate(raw)
        except ValidationError as e:
            out.append(_schema(ref, e))
            continue
        if batch.mode == "delete":
            out.append(rejected(ref, "INT_SCHEMA", "Delete is not supported for documents; send status obsolete."))
            continue
        try:
            out.append(run_tx(ctx, lambda s, rec=rec: _document(ctx, s, rec, is_bom, maps), lock=True))
        except Reject as e:
            out.append(rejected(ref, e.code, e.message, **e.details))
        except ApiError as e:
            out.append(rejected(ref, e.code, e.message, **({"issues": e.details.get("issues")}
                                                           if (e.details or {}).get("issues") else {})))
    return out


def _document(ctx: Any, s: Session, rec: Any, is_bom: bool, maps: dict[tuple[str, str], str]) -> dict[str, Any]:
    from ..api.db import new_id
    from ..api.mfg import repo, repo_m2, writer
    from ..api.mfg.db_models import MfgBomLineRow, MfgBomRow, MfgGroupRow, MfgOperationRow, MfgRoutingRow
    from ..api.mfg.services import eco
    from ..api.mfg.services.m2util import today
    from ..mfg.io.plan import ImportOptions, plan_import

    s.info["sp_inbound"] = True
    plant = repo.plant_row_unlocked(s)
    R = Refs(s, maps)
    parent = R.item(rec.parent_ref if is_bom else rec.item_ref, "parent_ref" if is_bom else "item_ref")
    rev = rec.revision or parent.revision
    Doc = MfgBomRow if is_bom else MfgRoutingRow
    conds = [Doc.item_id == parent.id, Doc.revision == rev]
    if not is_bom:
        conds.append(Doc.code == rec.code)
    docs = list(s.execute(select(Doc).where(*conds).order_by(Doc.version)).scalars())
    if is_bom:
        new_sig = _lines_sig([(ln.find_number, R.item(ln.child_ref, "child_ref").id, ln.qty_per,
                               R.uom(ln.uom) or R.item(ln.child_ref).uom, ln.scrap_pct, ln.ref_designators,
                               ln.operation_seq) for ln in rec.lines])
    else:
        groups = {g.code: g.id for g in s.execute(select(MfgGroupRow)).scalars()}
        for op in rec.operations:
            if op.group_code not in groups:
                raise Reject("INT_UNMAPPED_VALUE", f"Group {op.group_code!r} is not known in this plant.",
                             field="group_code", value=op.group_code)
        new_sig = sorted((o.seq, o.name, groups[o.group_code], round(o.setup_minutes, 6), round(o.run_minutes, 6),
                          o.run_per, o.units_per_batch, o.units_per_panel, o.labor, o.crew_size)
                         for o in rec.operations)

    def sig(d: Any) -> list[tuple]:
        if is_bom:
            return _lines_sig([(x.find_number, x.child_item_id, x.qty_per, x.uom, x.scrap_pct, x.ref_designators,
                                x.operation_seq) for x in s.execute(select(MfgBomLineRow).where(
                                    MfgBomLineRow.bom_id == d.id)).scalars()])
        return sorted((o.seq, o.name, o.group_id, round(o.setup_minutes, 6), round(o.run_minutes, 6), o.run_per,
                       o.units_per_batch, o.units_per_panel, o.labor, o.crew_size) for o in s.execute(select(MfgOperationRow).where(
                           MfgOperationRow.routing_id == d.id)).scalars())

    target = next((d for d in docs if rec.version is not None and d.version == rec.version), None)
    current = next((d for d in reversed(docs) if d.status == "released"), None)
    if rec.status == "obsolete":
        d = target or current
        if d is None or d.status == "obsolete":
            return {"ref": rec.ref, "status": "unchanged", "id": d.id if d else None, "errors": []}
        if d.status != "released":
            raise Reject("INT_SCHEMA", "Only a released document can be made obsolete.")
        d.status, d.obsoleted_at = "obsolete", _now()
        d.row_version += 1
        s.flush()
        return {"ref": rec.ref, "status": "updated", "id": d.id, "errors": []}
    if target is not None and target.status != "draft":
        if sig(target) == new_sig:
            return {"ref": rec.ref, "status": "unchanged", "id": target.id, "errors": []}
        raise Reject("INT_SCHEMA", f"Version {target.version} is {target.status} and cannot change; send a new "
                     "version (or none to let SuperPlanner number it).")
    if target is None and rec.status == "released" and current is not None and sig(current) == new_sig:
        return {"ref": rec.ref, "status": "unchanged", "id": current.id, "errors": []}
    version = rec.version or (max((d.version for d in docs), default=0) + 1)
    key = {"revision": rev, "version": version}
    if is_bom:
        hdr = {"parent_part_number": parent.part_number, **key, "status": "draft"}
        for f in ("effective_to",):
            if getattr(rec, f):
                hdr[f] = getattr(rec, f)
        kids = [{"parent_part_number": parent.part_number, **key, "find_number": ln.find_number,
                 "child_part_number": R.item(ln.child_ref, "child_ref").part_number, "qty_per": ln.qty_per,
                 "scrap_pct": ln.scrap_pct, "ref_designators": ln.ref_designators,
                 **({"uom": R.uom(ln.uom)} if ln.uom else {}),
                 **({"operation_seq": ln.operation_seq} if ln.operation_seq else {})} for ln in rec.lines]
        bundle = {"boms": [hdr], "bom_lines": kids}
    else:
        hdr = {"part_number": parent.part_number, **key, "code": rec.code, "status": "draft",
               **({"priority": rec.priority} if rec.priority else {})}
        kids = [{"part_number": parent.part_number, **key, "code": rec.code, "seq": o.seq, "name": o.name,
                 "group_code": o.group_code, "setup_minutes": o.setup_minutes, "run_minutes": o.run_minutes,
                 "run_per": o.run_per, "labor": o.labor, "crew_size": o.crew_size,
                 **({"units_per_batch": o.units_per_batch} if o.units_per_batch else {}),
                 **({"units_per_panel": o.units_per_panel} if o.units_per_panel else {})} for o in rec.operations]
        bundle = {"routings": [hdr], "operations": kids}
    plan = plan_import(bundle, repo_m2.load_import_dataset(s, with_txn=False), ImportOptions(replace_children=True),
                       id_factory=new_id)
    if not plan.ok:
        e = plan.row_errors[0]
        raise Reject("INT_SCHEMA", e.get("message", "Invalid document."), details=plan.row_errors[:5])
    if plan.has_writes():
        writer.apply(s, plan, plant)
    s.flush()
    conds2 = [Doc.item_id == parent.id, Doc.revision == rev, Doc.version == version]
    if not is_bom:
        conds2.append(Doc.code == rec.code)
    d = s.execute(select(Doc).where(*conds2)).scalars().one()
    created = target is None
    if rec.status != "released":
        return {"ref": rec.ref, "status": "created" if created else ("updated" if plan.has_writes() else
                                                                      "unchanged"), "id": d.id, "errors": []}
    eff = rec.effective_from if is_bom else None
    eff = eff or (today(s) if current is not None else None)
    cr = eco.implement_erp(s, f"ERP {'BOM' if is_bom else 'routing'} {parent.part_number} rev {rev} v{version}",
                           [("bom" if is_bom else "routing", d, current.id if current else None)], eff)
    return {"ref": rec.ref, "status": "created" if created else "updated", "id": d.id, "errors": [],
            "eco": {"id": cr.id, "number": cr.number}}


def _now() -> Any:
    from ..api.db import utcnow

    return utcnow()


# ---------------------------------------------------------------- stock snapshots (4.8)

def stock(ctx: Any, batch: C.V1Batch, maps: dict[tuple[str, str], str], sor: str) -> list[dict[str, Any]]:
    """Stock SoR `superplanner`: one reconciliation run over the snapshot (never posts). `erp`: one `count`
    posting (reason `ERP_SYNC`) per differing item x location x lot."""
    from types import SimpleNamespace

    from ..api.mfg.services import integration as svc

    recs, out = [], []
    for raw in batch.records:
        ref = str(raw.get("ref", ""))[:64] if isinstance(raw, dict) else ""
        try:
            recs.append(C.StockSnapshotV1.model_validate(raw))
            out.append({"ref": ref, "status": "unchanged", "id": None, "errors": []})
        except ValidationError as e:
            out.append(_schema(ref, e))
    good = [r.model_dump(mode="json") for r in recs]
    run = svc.reconcile(ctx, SimpleNamespace(entities=["stock"], records={"stock": good}, snapshot="inline",
                                             file_name=None))
    if sor == "erp":
        posted = svc.post_stock_counts(ctx, run["id"], reason="ERP_SYNC", system=True)
        changed = {(x["item_ref"], x["location"], x["lot"] or "") for x in posted.get("lines", [])}
        for o, r in zip([x for x in out if x["status"] != "rejected"], recs):
            o["id"] = run["id"]
            if (r.item_ref, R_loc(maps, r.location_code), r.lot_code or "") in changed:
                o["status"] = "updated"
    else:
        for o in out:
            if o["status"] != "rejected":
                o["id"] = run["id"]
    return out


def R_loc(maps: dict[tuple[str, str], str], code: str) -> str:   # noqa: N802
    return maps.get(("location", code.upper()), code)


# ---------------------------------------------------------------- job (> SYNC_LIMIT records)

def run_job(ctx: Any, inbox_id: str, lease: Any) -> None:
    """`integration_import`: process a queued batch (owner scope of the inbox row), store the results."""
    from ..api.db.ownership import owner_scope
    from ..api.mfg.db_models_m5 import IntInboxRow
    from ..api.mfg.services import integration as svc
    from ..jobs.types import LeaseLost

    with ctx.write_guard(), ctx.db.write() as s:
        row = s.get(IntInboxRow, inbox_id, with_for_update=True)
        if row is None:
            raise LeaseLost(f"batch {inbox_id} is gone")
        lease.fence(s)
        if row.status not in ("queued", "running"):
            lease.finish(s, "succeeded")
            return
        row.status = "running"
        owner, body = row.owner_id, dict(row.payload or {})
    with owner_scope(owner):
        batch = C.V1Batch.model_validate(body)
        try:
            results = svc.process(ctx, batch)
            status, err = "completed", None
        except Exception as exc:      # recorded on the batch; the job fails
            results, status, err = [], "failed", str(exc)[:500]
        counts: dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        with ctx.write_guard(), ctx.db.write() as s:
            row = s.get(IntInboxRow, inbox_id, with_for_update=True)
            if row is None:
                raise LeaseLost(f"batch {inbox_id} is gone")
            row.status, row.results, row.counts, row.finished_at = status, results, counts, _now()
            lease.finish(s, "succeeded" if status == "completed" else "failed", err)


_ = date
