"""Import sessions (M1-DESIGN 8.1, 8.3, 9.3 #68-72), export and templates (#73, #74).

Upload -> staged sheets (`mfg_imports.sheets`) + suggested mapping; PUT mapping -> preview (plan against the current
data, outside any lock); commit -> plan in a read transaction, then ONE write transaction: plant lock, re-plan only
if `data_version` changed, zero row errors required, `writer.apply`, audit, session `committed` (staged rows
cleared). Import staging writes do not lock the plant or bump `data_version` (they are not master data).
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.bundle import MASTER_SHEETS, TXN_SHEETS, dataset_to_bundle
from ....mfg.dataset import MfgDataset
from ....mfg.io import export as xport
from ....mfg.io.mapping import MappingError, apply_mapping, suggest_mapping, validate_mapping
from ....mfg.io.plan import ImportOptions, ImportPlan, plan_import
from ....mfg.io.read import ImportFileInvalid, ImportTooLarge, read_upload, staged_size
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import repo, repo_m2, writer
from ..db_models import MfgImportRow
from .common import audit, check_version, read_tx, write_tx

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_TYPE = "application/zip"


# ---------------------------------------------------------------- records


def import_record(row: MfgImportRow) -> dict[str, Any]:
    sheets = []
    for sh in row.sheets or []:
        sheets.append({"name": sh["name"], "row_count": sh.get("row_count", 0), "headers": sh.get("headers") or [],
                       "sample_rows": sh.get("sample_rows") or [], "suggested": sh.get("suggested")})
    return {"id": row.id, "row_version": row.row_version, "status": row.status, "filename": row.filename,
            "format": row.format, "created_at": as_utc(row.created_at), "expires_at": as_utc(row.expires_at),
            "committed_at": as_utc(row.committed_at), "sheets": sheets, "mapping": row.mapping,
            "preview": row.preview, "result": row.result}


def _get(s: Session, import_id: str, lock: bool = False) -> MfgImportRow:
    row = repo.get_row(s, MfgImportRow, import_id, what="Import", lock=lock)
    if as_utc(row.expires_at) <= datetime.now(UTC):
        raise not_found("Import", import_id)
    return row


def _file_error(exc: Exception) -> ApiError:
    if isinstance(exc, ImportTooLarge):
        return ApiError(422, "MFG_IMPORT_TOO_LARGE", exc.message, {"limit": exc.limit, "value": exc.value})
    reason = getattr(exc, "reason", "The file could not be read.")
    return ApiError(422, "MFG_IMPORT_FILE_INVALID", reason, {"reason": reason})


# ---------------------------------------------------------------- upload


def upload(ctx: AppContext, data: bytes, filename: str, sheet: str | None) -> dict[str, Any]:
    try:
        raw = read_upload(data, sheet=sheet, filename=filename)
    except (ImportFileInvalid, ImportTooLarge) as exc:
        raise _file_error(exc) from None
    staged = []
    for i, sh in enumerate(raw.sheets):
        sh = dict(sh)
        sh["suggested"] = suggest_mapping(sh)
        sh["sample_rows"] = [cells for _n, cells in sh["rows"][:5]]
        sh["warnings"] = [w for w in raw.warnings if w.get("sheet") in (None, sh["name"])] if i == 0 else \
            [w for w in raw.warnings if w.get("sheet") == sh["name"]]
        staged.append(sh)
    size = staged_size(staged)
    if size > L.IMPORT_MAX_STAGED_BYTES:
        raise ApiError(422, "MFG_IMPORT_TOO_LARGE", "The file holds too much data to stage for an import.",
                       {"limit": "IMPORT_MAX_STAGED_BYTES", "value": size})
    now = utcnow()
    with write_tx(ctx, lock=False) as (s, _):
        s.execute(delete(MfgImportRow).where(MfgImportRow.expires_at <= now)
                  .execution_options(synchronize_session=False))
        row = MfgImportRow(id=new_id("imp_"), filename=filename[:200], format=raw.format, status="uploaded",
                           sheets=staged, mapping=None, preview=None, result=None,
                           expires_at=now + timedelta(hours=L.IMPORT_TTL_HOURS), committed_at=None, row_version=1,
                           created_at=now, updated_at=now)
        s.add(row)
        s.flush()
        open_ids = list(s.execute(select(MfgImportRow.id).where(MfgImportRow.status != "committed")
                                  .order_by(MfgImportRow.created_at.desc(), MfgImportRow.id.desc())).scalars())
        if row.id in open_ids:
            open_ids.remove(row.id)
        old = open_ids[L.IMPORT_MAX_OPEN_PER_OWNER - 1:]
        if old:
            s.execute(delete(MfgImportRow).where(MfgImportRow.id.in_(old)).execution_options(synchronize_session=False))
        audit(s, "import", row.id, "create", {"format": raw.format, "sheets": len(staged)})
        return import_record(row)


def get_import(ctx: AppContext, import_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return import_record(_get(s, import_id))


def delete_import(ctx: AppContext, import_id: str) -> None:
    with write_tx(ctx, lock=False) as (s, _):
        row = _get(s, import_id, lock=True)
        audit(s, "import", row.id, "delete", {"status": row.status, "version": row.row_version})
        s.delete(row)
        s.flush()


# ---------------------------------------------------------------- mapping / preview


def _options(mapping: dict[str, Any]) -> ImportOptions:
    o = mapping.get("options") or {}
    d = o.get("default_effective_from")
    from datetime import date

    return ImportOptions(replace_children=bool(o.get("replace_children", True)), release=bool(o.get("release", False)),
                         default_effective_from=date.fromisoformat(d) if isinstance(d, str) else d,
                         stock_mode=str(o.get("stock_mode") or "set"))


def _plan(staged: list[dict[str, Any]], mapping: dict[str, Any], ds: MfgDataset
          ) -> tuple[ImportPlan, list[dict[str, Any]], list[dict[str, Any]]]:
    bundle, sources, map_errors = apply_mapping(staged, mapping)
    plan = plan_import(bundle, ds, _options(mapping), sources=sources, id_factory=new_id)
    target_of = {src: (m or {}).get("target") for src, m in (mapping.get("sheets") or {}).items()}
    seen: set[tuple[str, int]] = set()
    for e in map_errors:
        t = target_of.get(e["sheet"])
        if t and (e["sheet"], e["row"]) not in seen:
            seen.add((e["sheet"], e["row"]))
            c = plan.counts.setdefault(t, {"create": 0, "update": 0, "unchanged": 0, "delete": 0, "error": 0})
            c["error"] += 1
    warnings: list[dict[str, Any]] = []
    for sh in staged:
        warnings.extend(sh.get("warnings") or [])
        if sh["name"] not in (mapping.get("sheets") or {}) or target_of.get(sh["name"]) is None:
            warnings.append({"code": "IMP_SHEET_IGNORED", "sheet": sh["name"],
                             "message": f"Sheet {sh['name']!r} is not imported."})
    return plan, map_errors, warnings


def _preview(plan: ImportPlan, map_errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    errors = map_errors + plan.row_errors
    return {"ok": not errors, "counts": plan.counts, "error_count": len(errors),
            "row_errors": errors[:L.MAX_ROW_ERRORS_RETURNED], "warnings": warnings + plan.warnings,
            "changes_sample": plan.changes_sample[:50]}


def _maps_txn(mapping: dict[str, Any]) -> bool:
    """Does the mapping target a transactional sheet (then the planner needs `ds.txn`)?"""
    return any((m or {}).get("target") in TXN_SHEETS for m in (mapping.get("sheets") or {}).values())


def put_mapping(ctx: AppContext, import_id: str, mapping: dict[str, Any], if_match: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        row = _get(s, import_id)
        version = check_version(row, if_match)
        if row.status == "committed":
            raise ApiError(409, "MFG_IMPORT_ALREADY_COMMITTED", "This import was committed already.",
                           {"result": row.result})
        staged = row.sheets or []
        try:
            validate_mapping(staged, mapping)
        except MappingError as exc:
            raise ApiError(422, "VALIDATION_ERROR", f"The mapping is not valid: {exc.errors[0]['msg']}",
                           {"errors": exc.errors}) from None
        ds = repo_m2.load_import_dataset(s, with_txn=_maps_txn(mapping))
    plan, map_errors, warnings = _plan(staged, mapping, ds)
    preview = _preview(plan, map_errors, warnings)
    with write_tx(ctx, lock=False) as (s, _):
        row = _get(s, import_id, lock=True)
        check_version(row, str(version))
        if row.status == "committed":
            raise ApiError(409, "MFG_IMPORT_ALREADY_COMMITTED", "This import was committed already.",
                           {"result": row.result})
        row.mapping = mapping
        row.preview = preview
        row.status = "mapped"
        row.row_version += 1
        row.updated_at = utcnow()
        audit(s, "import", row.id, "map", {"version": row.row_version,
                                            "targets": sorted({str((m or {}).get("target"))
                                                               for m in (mapping.get("sheets") or {}).values()
                                                               if (m or {}).get("target")})})
        s.flush()
        return import_record(row)


# ---------------------------------------------------------------- commit


def _plant_key(s: Session) -> tuple[str | None, int]:
    p = repo.plant_or_default(s)
    return p.id, p.data_version


SHEET_PERMISSION = {**{n: "master_edit" for n in MASTER_SHEETS}, "suppliers": "supplier_edit",
                    "item_suppliers": "supplier_edit", "stock": "inventory", "demand_orders": "demand_edit",
                    "demand_lines": "demand_edit", "work_orders": "wo_edit", "wo_components": "wo_edit"}


def _approved_pr(r: dict[str, Any]) -> bool:
    return str(r.get("doc_type") or "").strip() == "pr" and str(r.get("status") or "").strip() in ("approved",
                                                                                                    "ordered")


def _check_pr_self_approval(s: Session, bundle: dict[str, Any], perms: frozenset[str] | None) -> None:
    """m3 / 10.2: importing a PR as approved/ordered approves it; a member cannot approve a PR they requested
    (new PR: the importer is the requester; existing PR: its `submitted_by`). The workspace owner may."""
    from ....mfg import purchasing as PUR
    from ....mfg.purchasing import RuleError
    from ..db_models_m2 import MfgPurchaseDocRow
    from .m2util import actor_id, is_workspace_owner, rule_error

    if perms is None:
        return
    numbers = sorted({str(r.get("number") or "").strip() for r in bundle.get("purchase_docs") or []
                      if _approved_pr(r)})
    if not numbers:
        return
    actor, owner = actor_id(), is_workspace_owner()
    existing = {n: sb for n, sb in s.execute(select(MfgPurchaseDocRow.number, MfgPurchaseDocRow.submitted_by).where(
        MfgPurchaseDocRow.doc_type == "pr", MfgPurchaseDocRow.number.in_(numbers))).all()}
    for n in numbers:
        try:
            PUR.check_self_approval(existing[n] if n in existing else actor, actor, owner)
        except RuleError as e:
            err = rule_error(e)
            err.details = {**(err.details or {}), "number": n, "sheet": "purchase_docs"}
            raise err from None


def _check_sheet_permissions(bundle: dict[str, Any], perms: frozenset[str] | None) -> None:
    """M2-DESIGN 10.2: commit needs the permission of every sheet kind present (403 `MFG_FORBIDDEN`)."""
    if perms is None:
        return
    from ..access import roles_allowed

    for name, rows in bundle.items():
        if not rows:
            continue
        if name in ("purchase_docs", "purchase_lines", "purchase_schedules"):
            need = sorted({"pr_edit" if str(r.get("doc_type") or "").strip() == "pr" else "po_edit" for r in rows})
        else:
            need = [SHEET_PERMISSION.get(name, "master_edit")]
        if name == "purchase_docs" and any(_approved_pr(r) for r in rows):
            need.append("pr_approve")  # m3: an approved/ordered PR in the file is an approval
        for p in need:
            if p not in perms:
                raise ApiError(403, "MFG_FORBIDDEN", f"Your role in this workspace does not allow importing the "
                               f"{name!r} sheet.", {"permission": p, "roles_allowed": roles_allowed(p), "sheet": name})


def commit(ctx: AppContext, import_id: str, if_match: str | None, perms: frozenset[str] | None = None
           ) -> dict[str, Any]:
    t0 = time.monotonic()
    with read_tx(ctx) as s:
        row = _get(s, import_id)
        version = check_version(row, if_match)
        if row.status == "committed":
            raise ApiError(409, "MFG_IMPORT_ALREADY_COMMITTED", "This import was committed already.",
                           {"result": row.result})
        if row.status != "mapped" or row.mapping is None:
            raise ApiError(409, "MFG_IMPORT_NOT_MAPPED", "Map the columns and look at the preview before committing.")
        staged, mapping = row.sheets or [], row.mapping
        key = _plant_key(s)
        ds = repo_m2.load_import_dataset(s, with_txn=_maps_txn(mapping))
    plan, map_errors, warnings = _plan(staged, mapping, ds)
    bundle, _src, _errs = apply_mapping(staged, mapping)
    _check_sheet_permissions(bundle, perms)
    master = any(rows for n, rows in bundle.items() if n not in TXN_SHEETS)
    with write_tx(ctx, lock=master) as (s, plant):
        row = _get(s, import_id, lock=True)
        check_version(row, str(version))
        if row.status == "committed":
            raise ApiError(409, "MFG_IMPORT_ALREADY_COMMITTED", "This import was committed already.",
                           {"result": row.result})
        if plant is None:
            plant = repo.plant_row_unlocked(s)
        _check_pr_self_approval(s, bundle, perms)
        if not master or (plant.id, plant.data_version - 1) != key or any(bundle.get(n) for n in TXN_SHEETS):
            plan, map_errors, warnings = _plan(staged, mapping, repo_m2.load_import_dataset(s))
        errors = map_errors + plan.row_errors
        if errors:
            raise ApiError(409, "MFG_IMPORT_HAS_ERRORS",
                           f"The import has {len(errors)} row error(s); fix the file and upload it again.",
                           {"row_errors": errors[:L.MAX_ROW_ERRORS_RETURNED], "error_count": len(errors)})
        if plan.has_writes():
            writer.apply(s, plan, plant)
        elif master:
            plant.data_version -= 1             # nothing changed: data_version stays (re-import is a no-op)
        result = {"counts": plan.result_counts(), "duration_ms": int((time.monotonic() - t0) * 1000),
                  "data_version": plant.data_version}
        now = utcnow()
        row.status, row.committed_at, row.result = "committed", now, result
        row.sheets = [{**{k: v for k, v in sh.items() if k != "rows"}, "rows": []} for sh in staged]
        row.row_version += 1
        row.updated_at = now
        s.flush()
        audit(s, "import", row.id, "import_commit", {"counts": {k: v for k, v in plan.result_counts().items()
                                                                if any(v.values())}})
        return import_record(row)


# ---------------------------------------------------------------- export / templates


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name or "").strip("-")[:40]
    return s or "plant"


def export_file(ctx: AppContext, fmt: str, scope: str = "master") -> tuple[bytes, str, str]:
    """M2-DESIGN 11: `master` = M1 + the M2 master sheets; `transactions` = stock and documents; `all`."""
    with read_tx(ctx) as s:
        ds = repo_m2.load_import_dataset(s) if scope != "master" else repo.load_dataset(s)
    bundle = dataset_to_bundle(ds, scope=scope)
    from .common import plant_today

    stamp = plant_today(ds.plant).strftime("%Y%m%d")
    name = f"superplanner-mfg-{slug(ds.plant.name)}-{stamp}.{fmt}"
    if fmt == "xlsx":
        return xport.bundle_to_xlsx(bundle), name, XLSX_TYPE
    return xport.bundle_to_csv_zip(bundle), name, ZIP_TYPE


def template_file(fmt: str, scope: str = "master") -> tuple[bytes, str, str]:
    bundle = xport.template_bundle()
    keep = TXN_SHEETS if scope == "transactions" else MASTER_SHEETS if scope == "master" else tuple(bundle)
    bundle = {k: v for k, v in bundle.items() if k in keep}
    if fmt == "xlsx":
        return xport.bundle_to_xlsx(bundle), "superplanner-mfg-template.xlsx", XLSX_TYPE
    return xport.bundle_to_csv_zip(bundle), "superplanner-mfg-template.zip", ZIP_TYPE
