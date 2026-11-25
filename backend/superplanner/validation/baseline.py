"""Configuration baseline (M8-DESIGN 10): a canonical JSON snapshot of the configuration that defines the
validated state of one plant - app version, git sha, migration head, plant settings (planning, QA, Part 11, MRP /
APS / floor parameters, dashboard thresholds), e-signature policies, the role -> permission matrix, integration
settings with secrets redacted, job schedules. `digest` = sha256 of the canonical JSON; `diff` lists changed
paths (`a.b.c`, kind added / removed / changed)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .register import REPO

SECRET_KEYS = ("password", "secret", "token", "_enc", "client_secret", "api_key")
PLANT_FIELDS = ("name", "utc_offset", "time_zone", "planning_horizon_days", "currency", "mrp_workdays",
                "mrp_day_minutes", "mrp_defer_tolerance_days", "mrp_release_window_days", "over_receipt_pct",
                "aps_freeze_hours", "aps_horizon_days", "aps_overtime_policy", "replan_policy",
                "replan_debounce_minutes", "overrun_tolerance_pct", "adherence_tolerance_minutes",
                "assistant_enabled", "assistant_allow_whatif", "dashboard_thresholds", "part11_mode", "qa_settings",
                "planning_settings")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<redacted>" if any(s in k.lower() for s in SECRET_KEYS) and v not in (None, "") else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=5,
                              check=True).stdout.strip() or None
    except Exception:
        return None


def collect(s: Session) -> dict[str, Any]:
    """The baseline content of the bound plant (caller in owner scope)."""
    from .. import migrate
    from ..api.mfg.access import ROLE_PERMISSIONS
    from ..api.mfg.db_models import MfgPlantRow
    from ..api.mfg.db_models_m5 import IntEndpointRow, IntSettingsRow
    from ..api.mfg.db_models_m7 import EsigPolicyRow

    try:
        from importlib.metadata import version

        app_version = version("superplanner")
    except Exception:
        app_version = None
    p = s.execute(select(MfgPlantRow)).scalars().first()
    plant = {f: getattr(p, f, None) for f in PLANT_FIELDS} if p is not None else {}
    pols = {f"{r.record_type}.{r.action}": {"steps": r.steps, "auth": r.auth, "distinct_signers": r.distinct_signers,
                                            "exclude_author": r.exclude_author, "version": r.version}
            for r in s.execute(select(EsigPolicyRow).order_by(EsigPolicyRow.record_type, EsigPolicyRow.action))
            .scalars()}
    ist = s.execute(select(IntSettingsRow)).scalars().first()
    integ = {"enabled": ist.enabled, "adapter": ist.adapter, "plant_code": ist.plant_code, "sor": ist.sor,
             "goods_receipts_owner": ist.goods_receipts_owner, "filedrop_enabled": ist.filedrop_enabled,
             "export_enabled": ist.export_enabled, "export_interval_minutes": ist.export_interval_minutes,
             "sap": {k: v for k, v in (ist.sap or {}).items() if k not in ("cursors", "last_sync")}} \
        if ist is not None else None
    endpoints = [{"name": e.name, "url": e.url, "event_types": e.event_types, "active": e.active}
                 for e in s.execute(select(IntEndpointRow).order_by(IntEndpointRow.name)).scalars()]
    ps = (plant.get("planning_settings") or {})
    schedules = {"nightly_plan": {"enabled": ps.get("nightly_enabled", False), "at": ps.get("nightly_at", "02:00")},
                 "sap_sync": ((ist.sap or {}).get("schedule") if ist is not None else None) or {},
                 "integration_export_minutes": ist.export_interval_minutes if ist is not None else None}
    return redact({"app": {"version": app_version, "git_sha": git_sha(), "migration_head": migrate.HEAD},
                   "plant": plant, "esig_policies": pols,
                   "roles": {r: sorted(v) for r, v in sorted(ROLE_PERMISSIONS.items())},
                   "integration": integ, "endpoints": endpoints, "job_schedules": schedules})


def diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append({"path": p, "kind": "added", "a": None, "b": b[k]})
            elif k not in b:
                out.append({"path": p, "kind": "removed", "a": a[k], "b": None})
            else:
                out += diff(a[k], b[k], p)
        return out
    if canonical(a) != canonical(b):
        out.append({"path": path, "kind": "changed", "a": a, "b": b})
    return out
