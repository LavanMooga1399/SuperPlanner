"""S0 placeholder: dashboards answer from the M6 fixture (replaced in S2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIX = Path(__file__).resolve().parents[3] / "assistant" / "fixtures" / "example_m6.json"


def _fx() -> dict[str, Any]:
    return json.loads(FIX.read_text(encoding="utf-8"))


def plant_dashboard(ctx: Any, period: str) -> dict[str, Any]:
    return dict(_fx()["dashboard"], period=period)


def org_dashboard(ctx: Any, user_id: str, org_id: str, period: str) -> dict[str, Any]:
    return dict(_fx()["org_dashboard"], period=period)


def export(ctx: Any, period: str, fmt: str) -> tuple[bytes, str, str]:
    return b"tile,value\n", "dashboard.csv", "text/csv"


def put_thresholds(ctx: Any, body: Any) -> dict[str, Any]:
    return {"thresholds": body.model_dump(mode="json")["thresholds"]}


def supplier_lateness(ctx: Any, supplier_id: str) -> dict[str, Any]:
    return {}


def top_alerts(ctx: Any) -> list[dict[str, Any]]:
    return []
