"""SAP S/4HANA settings and sync (M8-DESIGN 9, 11 X1-X2; job `sap_sync`).

Settings live in `int_settings.sap` (secrets Fernet-encrypted with SECRETS_KEYS, never returned; `password_set`,
`client_secret_set` flags). A sync (duty run) pulls each requested entity with `$filter=LastChangeDateTime gt
<cursor>`, pages through `__next` / `@odata.nextLink`, maps every page to `superplanner.v1` batches (applied by the
M5 inbound path, so systems of record and value maps apply) plus the M8 extras (packaging levels, `sap` demand
history), and stores the cursor after each committed page. Outbound `planned_order_out` posts the open planned
orders of the latest live MRP run (make -> planned order, buy -> purchase requisition) with a CSRF token, once per
run. `stock` is a reconciliation snapshot (inbound stock sync of M5). `TRANSPORT` (tests) injects an httpx
transport instead of the network.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....mfg.model_m8 import SAP_IN_ENTITIES, SapSettings
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from . import m8_examples
from .common import audit, check_version, read_tx, write_tx

#: tests: a factory returning an `httpx.BaseTransport` (None = real network)
TRANSPORT: Callable[[], Any] | None = None
SECRET_FIELDS = ("password", "client_secret")


def _row(s: Session) -> Any:
    from ..db_models_m5 import IntSettingsRow

    return s.execute(select(IntSettingsRow)).scalars().first()


def _raw(row: Any) -> dict[str, Any]:
    return dict(row.sap or {}) if row is not None else {}


def _record(row: Any) -> dict[str, Any]:
    raw = _raw(row)
    st = SapSettings.model_validate({k: v for k, v in raw.items() if k in SapSettings.model_fields
                                     and k not in SECRET_FIELDS})
    return {**st.model_dump(mode="json"), "password": None, "client_secret": None,
            "password_set": bool(raw.get("password_enc")), "client_secret_set": bool(raw.get("client_secret_enc")),
            "cursors": dict(raw.get("cursors") or {}), "last_sync": dict(raw.get("last_sync") or {}),
            "row_version": row.row_version if row is not None else 0}


def get_settings(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _record(_row(s))


def put_settings(ctx: AppContext, a: Any, body: SapSettings, if_match: str | None) -> dict[str, Any]:
    from ....identity import crypto
    from ....integration.outbox import check_url
    from ..db_models_m5 import IntSettingsRow
    from .integration import SOR_DEFAULTS

    if body.base_url:
        check_url(body.base_url, ctx.settings.integration_allow_private_targets)
    if (body.password or body.client_secret) and not ctx.settings.secrets_keys:
        raise ApiError(409, "INT_SECRETS_REQUIRED", "Storing SAP credentials needs SECRETS_KEYS on the server.", {})
    with write_tx(ctx) as (s, _):
        row = _row(s)
        if row is None:
            now = utcnow()
            row = IntSettingsRow(id=new_id("ist_"), enabled=False, adapter="sap_s4", plant_code="",
                                 sor=dict(SOR_DEFAULTS), goods_receipts_owner="superplanner", filedrop_enabled=False,
                                 export_enabled=False, export_interval_minutes=15, export_cursor=0, sap=None,
                                 row_version=0, created_at=now, updated_at=now)
            s.add(row)
            s.flush()
        check_version(row, if_match)
        raw = _raw(row)
        before = _record(row)
        new = {**raw, **body.model_dump(mode="json", exclude=set(SECRET_FIELDS))}
        for f in SECRET_FIELDS:
            v = getattr(body, f)
            if v:
                new[f"{f}_enc"] = crypto.encrypt(ctx.settings.secrets_keys, v)
            elif v == "":
                new.pop(f"{f}_enc", None)
        row.sap = new
        if body.enabled:                            # SAP on = integration on with the sap_s4 adapter
            row.adapter, row.enabled = "sap_s4", True
        row.row_version += 1
        row.updated_at = utcnow()
        s.flush()
        rec = _record(row)
        audit(s, "sap_settings", row.id, "update", {"version": row.row_version},
              before={k: v for k, v in before.items() if k not in ("last_sync", "cursors")},
              after={k: v for k, v in rec.items() if k not in ("last_sync", "cursors")})
        return rec


def sync(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    from ....integration.jobs import active_run, new_run

    with write_tx(ctx, lock=False) as (s, _):
        row = _row(s)
        if row is None or not _raw(row).get("base_url"):
            raise ApiError(409, "SAP_NOT_CONFIGURED", "Configure the SAP connection first.", {})
        if active_run(s, "sap_sync", a.p.owner_id):
            raise ApiError(409, "SAP_SYNC_RUNNING", "A SAP sync is already running for this plant.", {})
        rid, job = new_run(s, ctx, "sap_sync", a.p.owner_id, {"entities": list(body.entities), "full": body.full})
        audit(s, "sap_sync", rid, "start", {"entities": list(body.entities), "full": body.full})
    ctx.jobs.dispatch(job)
    return {"run_id": rid, "status": "queued", "entities": list(body.entities)}


# ---------------------------------------------------------------- job body

def client_of(ctx: AppContext, raw: dict[str, Any]) -> Any:
    from ....identity import crypto
    from ....integration.sap.odata import Client

    def dec(f: str) -> str:
        v = raw.get(f"{f}_enc")
        return crypto.decrypt(ctx.settings.secrets_keys, v) if v else ""
    return Client(base_url=raw["base_url"], version=raw.get("odata_version", "v2"), username=raw.get("username", ""),
                  password=dec("password"), token_url=raw.get("token_url", ""), client_id=raw.get("client_id", ""),
                  client_secret=dec("client_secret"), auth=raw.get("auth", "basic"),
                  transport=TRANSPORT() if TRANSPORT else None,
                  allow_private=bool(ctx.settings.integration_allow_private_targets))


def _save(ctx: AppContext, entity: str, cursor: str | None, status: dict[str, Any] | None) -> None:
    with ctx.write_guard(), ctx.db.write() as s:
        row = _row(s)
        raw = _raw(row)
        if cursor is not None:
            raw["cursors"] = {**(raw.get("cursors") or {}), entity: cursor}
        if status is not None:
            raw["last_sync"] = {**(raw.get("last_sync") or {}), entity: status}
        row.sap = raw


def apply_extras(s: Session, extras: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Packaging levels (replace per item) and `sap` demand history (upsert per item-period)."""
    from ....mfg.model_m8 import PACK_LEVELS, PackagingInput
    from ..db_models import MfgItemRow
    from ..db_models_m8 import MfgDemandHistoryRow, MfgItemPackagingRow

    by_ref = {}
    refs = {x["item_ref"] for k in ("packaging", "history") for x in extras.get(k, [])}
    if refs:
        for r in s.execute(select(MfgItemRow).where((MfgItemRow.external_ref.in_(refs)) |
                                                    (MfgItemRow.part_number.in_(refs)))).scalars():
            by_ref[r.external_ref or r.part_number] = r
            by_ref.setdefault(r.part_number, r)
    out = {"packaging": 0, "history": 0}
    now = utcnow()
    from sqlalchemy import delete

    for p in extras.get("packaging", []):
        it = by_ref.get(p["item_ref"])
        if it is None:
            continue
        try:
            inp = PackagingInput.model_validate({"levels": [{k: v for k, v in lv.items() if v is not None}
                                                            for lv in p["levels"]]})
        except Exception:
            continue
        s.execute(delete(MfgItemPackagingRow).where(MfgItemPackagingRow.item_id == it.id))
        for lv in inp.levels:
            s.add(MfgItemPackagingRow(id=new_id("pkg_"), item_id=it.id, level=lv.level,
                                      seq=PACK_LEVELS.index(lv.level) + 1, code=lv.code, qty_base=lv.qty_base,
                                      gtin=lv.gtin, weight_kg=lv.weight_kg, row_version=1, created_at=now,
                                      updated_at=now))
        out["packaging"] += 1
    existing = {(r.item_id, r.period_start): r for r in s.execute(select(MfgDemandHistoryRow).where(
        MfgDemandHistoryRow.source == "sap", MfgDemandHistoryRow.bucket == "m")).scalars()}
    for h in extras.get("history", []):
        it = by_ref.get(h["item_ref"])
        if it is None:
            continue
        per = date.fromisoformat(h["period_start"])
        r = existing.get((it.id, per))
        if r is None:
            r = MfgDemandHistoryRow(id=new_id("dhi_"), item_id=it.id, period_start=per, bucket="m", qty=h["qty"],
                                    cleaned_qty=None, manual_qty=None, source="sap", updated_at=now)
            s.add(r)
            existing[(it.id, per)] = r
        else:
            r.qty, r.updated_at = h["qty"], now
        out["history"] += 1
    s.flush()
    return out


def _pull(ctx: AppContext, client: Any, entity: str, raw: dict[str, Any], full: bool) -> dict[str, Any]:
    from ....integration.adapters.sap_s4 import SapS4
    from ....integration.sap import mapping as M
    from . import integration as INT

    prof = SapSettings.model_validate({k: v for k, v in raw.items() if k in SapSettings.model_fields
                                       and k not in SECRET_FIELDS})
    cursor = None if full else (raw.get("cursors") or {}).get(entity)
    path = M.ENTITIES[entity][0]
    params = M.delta_filter(entity, cursor, prof.odata_version)
    params["$top"] = str(prof.page_size) if prof.odata_version == "v4" else params.get("$top", str(prof.page_size))
    counts: dict[str, int] = {}
    errors: list[dict[str, Any]] = []
    pages = records = 0
    for recs in client.get_all(path, params):
        pages += 1
        records += len(recs)
        ad = SapS4(prof)
        for batch in ad.map_page(entity, recs):
            for r in INT.process(ctx, batch):
                counts[r["status"]] = counts.get(r["status"], 0) + 1
                if r["status"] == "rejected" and len(errors) < 20:
                    errors.append({"entity": batch.entity, "ref": r.get("ref"), "errors": r.get("errors")})
        if ad.extras:
            with ctx.write_guard(), ctx.db.write() as s:
                for k, v in apply_extras(s, ad.extras).items():
                    counts[k] = counts.get(k, 0) + v
        cursor = M.max_cursor(recs, entity, cursor)
        _save(ctx, entity, cursor, None)                # after each committed page
    return {"pages": pages, "records": records, "results": counts, "cursor": cursor, "errors": errors}


def _push_planned(ctx: AppContext, client: Any, raw: dict[str, Any]) -> dict[str, Any]:
    from ....integration.sap import mapping as M
    from ..db_models_m2 import MfgMrpPlannedOrderRow
    from .mrp import latest_live

    prof = SapSettings.model_validate({k: v for k, v in raw.items() if k in SapSettings.model_fields
                                       and k not in SECRET_FIELDS})
    with ctx.db.read() as s:
        run = latest_live(s)
        if run is None:
            return {"posted": 0, "reason": "no live MRP run"}
        if (raw.get("cursors") or {}).get("planned_order_out") == run.id:
            return {"posted": 0, "reason": "already sent", "run_id": run.id}
        pos = [{"kind": p.kind, "part_number": p.part_number, "qty": p.qty, "need_date": p.need_date.isoformat(),
                "start_date": p.start_date.isoformat(), "ref": f"MRP{run.run_no}-P{p.planned_no}"}
               for p in s.execute(select(MfgMrpPlannedOrderRow).where(MfgMrpPlannedOrderRow.run_id == run.id,
                                                                      MfgMrpPlannedOrderRow.status == "open")
                                  .order_by(MfgMrpPlannedOrderRow.planned_no)).scalars()]
        run_id = run.id
    posted = []
    for po in pos:
        path, body = M.planned_order_out(po, prof)
        res = client.post(path, body)
        posted.append({"ref": po["ref"], "path": path.split("/")[0], "sap_id": _sap_id(res)})
    _save(ctx, "planned_order_out", run_id, None)
    return {"posted": len(posted), "run_id": run_id, "documents": posted[:200]}


def _sap_id(res: dict[str, Any]) -> str | None:
    d = res.get("d", res) if isinstance(res, dict) else {}
    return d.get("PlannedOrder") or d.get("PurchaseRequisition") if isinstance(d, dict) else None


def sync_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    with ctx.db.read() as s:
        raw = _raw(_row(s))
    if not raw.get("base_url"):
        raise RuntimeError("SAP is not configured")
    client = client_of(ctx, raw)
    out: dict[str, Any] = {}
    failed = None
    try:
        for entity in info["params"].get("entities", []):
            t0 = utcnow()
            try:
                with ctx.db.read() as s:
                    raw = _raw(_row(s))
                if entity in SAP_IN_ENTITIES:
                    res = _pull(ctx, client, "sales_order" if entity == "sales_order" else entity, raw,
                                bool(info["params"].get("full")))
                elif entity in ("planned_order_out", "pr_out"):
                    res = _push_planned(ctx, client, raw)
                else:
                    res = {"skipped": True, "reason": "not supported by this adapter version"}
                out[entity] = res
                _save(ctx, entity, None, {"at": t0.isoformat(), "status": "completed",
                                          "records": res.get("records", res.get("posted", 0)), "error": None})
            except Exception as exc:
                err = f"{exc.__class__.__name__}: {exc}"[:500]
                out[entity] = {"error": err}
                _save(ctx, entity, None, {"at": t0.isoformat(), "status": "failed", "records": 0, "error": err})
                failed = failed or err
    finally:
        client.close()
    if failed:
        raise RuntimeError(failed)
    return out


__getattr__ = m8_examples.module_getattr(__name__)
