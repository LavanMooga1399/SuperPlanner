"""File drop (M5-DESIGN 4.5; T-I8): `INTEGRATION_ROOT/<plant code>/{inbox,processing,archive,error,outbox}`.

One scan per plant and poll (job kind `integration_filedrop`, scheduled by `integration.scheduler`):
- a file is complete when a `<name>.done` marker exists or its size and mtime were the same at the previous poll
  (the previous sizes are kept on the last run's `results.seen`);
- complete files move to `processing/` and are read as `superplanner.v1` JSON (`.json`: batches through the
  adapter -> the same inbound processing as REST, `int_inbox` rows with source `filedrop`) or with the M1 readers
  (`.csv/.xlsx/.zip`) and the plant's mapping profile whose `file_pattern` (fnmatch) matches the name (else the
  M1 suggestion); the import is planned and committed with zero row errors (as M1);
- stock sheets reconcile (4.8) unless stock SoR is `erp` (then they post `count` corrections through the import);
- the file goes to `archive/` with `<name>.result.json`, or to `error/` with the report and a notification.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

SUBDIRS = ("inbox", "processing", "archive", "error", "outbox")
SHEET_SOR = {"items": "items", "boms": "boms", "bom_lines": "boms", "routings": "routings", "operations": "routings",
             "suppliers": "suppliers", "item_suppliers": "item_suppliers", "purchase_docs": "purchase_orders",
             "purchase_lines": "purchase_orders", "purchase_schedules": "purchase_orders",
             "demand_orders": "demand_orders", "demand_lines": "demand_orders", "work_orders": "work_orders",
             "wo_components": "work_orders"}
MAX_FILE_BYTES = 50_000_000


def _settings(ctx: Any) -> Any:
    """The bound plant's settings as a detached plain namespace (or None)."""
    from types import SimpleNamespace

    from ..api.mfg.services import integration as svc
    from ..api.mfg.services.common import read_tx

    with read_tx(ctx) as s:
        st = svc.settings_row(s)
        if st is None:
            return None
        return SimpleNamespace(enabled=st.enabled, filedrop_enabled=st.filedrop_enabled, plant_code=st.plant_code,
                               adapter=st.adapter)


def plant_dir(root: str, code: str) -> Path:
    base = Path(root) / code
    for d in SUBDIRS:
        (base / d).mkdir(parents=True, exist_ok=True)
    return base


def _inbox_files(base: Path) -> list[Path]:
    out = []
    for p in sorted((base / "inbox").iterdir()):
        if not p.is_file() or p.name.startswith(".") or p.name.endswith((".done", ".part", ".tmp")):
            continue
        out.append(p)
    return out


def complete_files(base: Path, seen: dict[str, list[float]]) -> tuple[list[Path], dict[str, list[float]]]:
    """(files ready now, sizes to remember for the next poll)."""
    ready, now_seen = [], {}
    for p in _inbox_files(base):
        st = p.stat()
        sig = [float(st.st_size), float(st.st_mtime)]
        if (base / "inbox" / (p.name + ".done")).exists() or (seen.get(p.name) == sig and st.st_size > 0):
            ready.append(p)
        else:
            now_seen[p.name] = sig
    return ready, now_seen


def _profile(s: Any, name: str) -> dict[str, Any] | None:
    from ..api.mfg.db_models_m5 import IntMappingProfileRow

    for r in s.execute(select(IntMappingProfileRow).order_by(IntMappingProfileRow.name)).scalars():
        if fnmatch.fnmatch(name.lower(), (r.file_pattern or "").lower()):
            return {"name": r.name, "mapping": dict(r.mapping or {})}
    return None


def _mapping_for(staged: list[dict[str, Any]], prof: dict[str, Any] | None) -> dict[str, Any]:
    from ..mfg.io.mapping import suggest_mapping

    if prof is None:
        return {"sheets": {sh["name"]: suggest_mapping(sh) for sh in staged if suggest_mapping(sh)}}
    m = prof["mapping"]
    if "sheets" not in m:                         # shorthand: one sheet mapping for every sheet of the file
        return {"sheets": {sh["name"]: {"target": m.get("target"), "columns": m.get("columns") or {}}
                           for sh in staged}, "options": m.get("options") or {}}
    sheets = dict(m.get("sheets") or {})
    if len(sheets) == 1 and len(staged) == 1 and staged[0]["name"] not in sheets:
        sheets = {staged[0]["name"]: next(iter(sheets.values()))}
    return {**m, "sheets": sheets}


def process_file(ctx: Any, path: Path) -> dict[str, Any]:
    """Process one file of the bound plant -> result dict (`ok`, counts, row_errors ...). Raises nothing."""
    from ..api.errors import ApiError

    t0 = time.monotonic()
    data = path.read_bytes()
    out: dict[str, Any] = {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "started_at": datetime.now(UTC).isoformat()}
    try:
        if len(data) > MAX_FILE_BYTES:
            raise ApiError(422, "MFG_IMPORT_TOO_LARGE", "The file is larger than 50 MB.", {})
        if path.suffix.lower() == ".json":
            out.update(_json_file(ctx, data, path.name, out["sha256"]))
        else:
            out.update(_tabular_file(ctx, data, path.name))
    except ApiError as e:
        out.update({"ok": False, "error": {"code": e.code, "message": e.message, "details": e.details}})
    except Exception as e:                     # unreadable file etc.: reported, never crashes the scan
        out.update({"ok": False, "error": {"code": "INT_FILE_FAILED", "message": str(e)[:500]}})
    out["duration_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def _json_file(ctx: Any, data: bytes, name: str, sha: str) -> dict[str, Any]:
    from ..api.mfg.services import integration as svc
    from ..api.mfg.services.common import read_tx
    from .adapters import registry

    st = _settings(ctx)
    ad = registry.get(st.adapter if st else "generic_v1")
    batches = ad.inbound(data, name)
    results, counts = [], {}
    for i, b in enumerate(batches):
        body = b.model_dump(mode="json", by_alias=True)
        rec, _replayed, _st = svc.post_batch(ctx, body, f"file:{sha[:40]}:{i}", source="filedrop")
        results.append({"batch_id": rec["id"], "entity": b.entity, "counts": rec["counts"]})
        for k, v in (rec["counts"] or {}).items():
            counts[k] = counts.get(k, 0) + v
    return {"ok": counts.get("rejected", 0) == 0, "kind": "v1", "batches": results, "counts": counts}


def _tabular_file(ctx: Any, data: bytes, name: str) -> dict[str, Any]:
    from types import SimpleNamespace

    from ..api.errors import ApiError
    from ..api.mfg import repo, repo_m2, writer
    from ..api.mfg.services import integration as svc
    from ..api.mfg.services.common import audit, read_tx, write_tx
    from ..api.mfg.services.imports import _file_error, _plan
    from ..mfg.bundle import TXN_SHEETS
    from ..mfg.io.mapping import apply_mapping
    from ..mfg.io.read import ImportFileInvalid, ImportTooLarge, read_upload

    try:
        raw = read_upload(data, filename=name)
    except (ImportFileInvalid, ImportTooLarge) as exc:
        raise _file_error(exc) from None
    staged = [dict(sh) for sh in raw.sheets]
    with read_tx(ctx) as s:
        prof = _profile(s, name)
        mapping = _mapping_for(staged, prof)
        targets = {(m or {}).get("target") for m in mapping.get("sheets", {}).values()} - {None}
        if not targets:
            raise ApiError(422, "INT_NO_MAPPING", "No mapping profile matches this file and its columns are not "
                           "recognised.", {"file": name})
        sor = {t: svc.sor_of(s, SHEET_SOR[t]) for t in targets if t in SHEET_SOR}
        stock_sor = svc.sor_of(s, "stock")
    bad = sorted(t for t, v in sor.items() if v == "superplanner")
    if bad:
        raise ApiError(422, "INT_SOR_CONFLICT", f"{', '.join(bad)} are maintained in SuperPlanner for this plant.",
                       {"sheets": bad})
    out: dict[str, Any] = {"kind": "tabular", "profile": prof["name"] if prof else None,
                           "targets": sorted(targets)}
    if "stock" in targets and stock_sor != "erp":             # 4.8: ERP stock lists reconcile, never overwrite
        bundle, _src, map_errors = apply_mapping(staged, mapping)
        if map_errors:
            return {**out, "ok": False, "row_errors": map_errors[:200], "error_count": len(map_errors)}
        recs = [{"ref": f"{name}:{i + 1}", "item_ref": str(r.get("part_number")), "location_code":
                 str(r.get("location_code")), "lot_code": r.get("lot_code") or None, "qty": float(r.get("qty") or 0),
                 "as_at": datetime.now(UTC).isoformat()} for i, r in enumerate(bundle.get("stock") or [])]
        rec = svc.reconcile(ctx, SimpleNamespace(entities=["stock"], records={"stock": recs}, snapshot="inline",
                                                 file_name=name))
        return {**out, "ok": True, "reconciliation_id": rec["id"], "summary": rec["summary"]}
    with write_tx(ctx) as (s, plant):              # one plan, under the plant lock (no second planning pass)
        s.info["sp_inbound"] = True
        if plant is None:
            plant = repo.plant_row_unlocked(s)
        plan, map_errors, warnings = _plan(staged, mapping, repo_m2.load_import_dataset(
            s, with_txn=bool(targets & set(TXN_SHEETS))))
        errors = map_errors + plan.row_errors
        if errors:
            return {**out, "ok": False, "counts": plan.counts, "row_errors": errors[:200],
                    "error_count": len(errors)}
        if plan.has_writes():
            writer.apply(s, plan, plant)
        audit(s, "integration_file", None, "import", {"file": name, "counts": {
            k: v for k, v in plan.result_counts().items() if any(v.values())}})
    return {**out, "ok": True, "counts": plan.result_counts(), "warnings": warnings[:50]}


def _move(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}.{int(time.time() * 1000)}{src.suffix}"
    shutil.move(str(src), str(dest))
    return dest


def scan(ctx: Any, seen: dict[str, list[float]]) -> dict[str, Any]:
    """One poll of the bound plant -> {processed: [...], seen: {...}, polled_at}."""
    from ..api.mfg.services import integration as svc
    from ..api.mfg.services.common import read_tx, write_tx
    from ..api.mfg.services.replan import notify

    st = _settings(ctx)
    root = ctx.settings.integration_root
    if st is None or not st.enabled or not st.filedrop_enabled or not root or not st.plant_code:
        return {"processed": [], "seen": {}, "skipped": "file drop is off", "polled_at": _now()}
    base = plant_dir(root, st.plant_code)
    ready, now_seen = complete_files(base, seen)
    processed = []
    for p in ready:
        marker = base / "inbox" / (p.name + ".done")
        work = _move(p, base / "processing")
        if marker.exists():
            marker.unlink()
        res = process_file(ctx, work)
        target = base / ("archive" if res.get("ok") else "error")
        final = _move(work, target)
        (target / (final.name + ".result.json")).write_text(json.dumps(res, indent=1, default=str))
        processed.append({"file": final.name, "ok": bool(res.get("ok")), "dir": target.name,
                          "counts": res.get("counts"), "error": res.get("error")})
        if not res.get("ok"):
            with write_tx(ctx, lock=False) as (s, _p):
                notify(s, "INTEGRATION_FILE_ERROR", "warning", f"File {final.name} was not imported",
                       (res.get("error") or {}).get("message") or f"{res.get('error_count', 0)} row error(s); see "
                       f"error/{final.name}.result.json.", "/mfg/integration/filedrop")
    return {"processed": processed, "seen": now_seen, "polled_at": _now()}


def status(ctx: Any, last: dict[str, Any] | None) -> dict[str, Any]:
    from ..api.mfg.services import integration as svc
    from ..api.mfg.services.common import read_tx

    st = _settings(ctx)
    root = ctx.settings.integration_root
    out: dict[str, Any] = {"enabled": bool(st and st.filedrop_enabled), "root": root, "inbox": [], "recent": [],
                           "last_poll_at": (last or {}).get("polled_at")}
    if not root or st is None or not st.plant_code:
        return out
    base = Path(root) / st.plant_code
    if not base.exists():
        return out
    seen = (last or {}).get("seen") or {}
    if (base / "inbox").exists():
        for p in _inbox_files(base):
            stt = p.stat()
            out["inbox"].append({"name": p.name, "size": stt.st_size, "modified_at": datetime.fromtimestamp(
                stt.st_mtime, UTC).isoformat(), "waiting": "size stable on the next poll" if p.name in seen
                else "first seen"})
    recent = []
    for d in ("archive", "error"):
        if (base / d).exists():
            for p in (base / d).glob("*.result.json"):
                recent.append((p.stat().st_mtime, d, p))
    for _m, d, p in sorted(recent, reverse=True)[:20]:
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        out["recent"].append({"file": p.name[:-len(".result.json")], "dir": d, "ok": r.get("ok"),
                              "counts": r.get("counts"), "error": r.get("error"),
                              "error_count": r.get("error_count", 0), "at": r.get("started_at")})
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat()


def run_job(ctx: Any, run_id: str, lease: Any) -> None:
    from .jobs import run_duty

    def fn(row: Any) -> dict[str, Any]:
        from ..api.mfg.db_models_m5 import MaintenanceRunRow
        from ..api.db.ownership import system_scope

        with system_scope(), ctx.db.read() as s:
            prev = s.execute(select(MaintenanceRunRow).where(
                MaintenanceRunRow.kind == "integration_filedrop", MaintenanceRunRow.owner_scope_id ==
                row["owner"], MaintenanceRunRow.status == "completed").order_by(
                MaintenanceRunRow.created_at.desc()).limit(1)).scalars().first()
            seen = dict(((prev.results or {}).get("seen") or {})) if prev else {}
        return scan(ctx, seen)

    run_duty(ctx, run_id, lease, fn)


_ = os
