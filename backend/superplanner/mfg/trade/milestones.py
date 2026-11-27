"""Tariff-milestone report arithmetic (M9-DESIGN 8.3), pure: month share = sum share_l x denom_l / sum denom_l;
status for months >= effective: `met` (>= min), `at_risk` (within 5 points below), `missed`."""

from __future__ import annotations

from datetime import date
from typing import Any


def status(share_pct: float | None, min_pct: float, month: date, effective: date) -> str | None:
    if share_pct is None or month < effective:
        return None
    if share_pct >= min_pct - 1e-9:
        return "met"
    if share_pct >= min_pct - 5 - 1e-9:
        return "at_risk"
    return "missed"


def month_cell(lots: list[dict[str, Any]], min_pct: float, month: date, effective: date) -> dict[str, Any]:
    """lots: [{share (0..1 or None), denom, qty, estimated}] of one group-month."""
    num = sum((x["share"] or 0.0) * x["denom"] for x in lots if x["share"] is not None)
    den = sum(x["denom"] for x in lots if x["share"] is not None)
    share = round(num / den * 100, 2) if den > 0 else None
    below = [x for x in lots if x["share"] is not None and x["share"] * 100 < min_pct - 1e-9]
    qty = sum(x["qty"] for x in lots)
    return {"month": month, "share_pct": share, "status": status(share, min_pct, month, effective),
            "projected": False, "lots": len(lots), "lots_below": len(below),
            "qty_below_pct": round(sum(x["qty"] for x in below) / qty * 100, 2) if qty else None,
            "estimated_pct": round(sum(x["qty"] for x in lots if x["estimated"]) / qty * 100, 2) if qty else None}


def projected_cell(share_pct: float | None, min_pct: float, month: date, effective: date) -> dict[str, Any]:
    return {"month": month, "share_pct": share_pct, "status": status(share_pct, min_pct, month, effective),
            "projected": True, "lots": 0, "lots_below": 0, "qty_below_pct": None, "estimated_pct": None}
