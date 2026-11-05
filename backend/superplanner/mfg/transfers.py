"""Inter-plant transfer order rules (M5-DESIGN 3.5), pure.

Statuses: draft -> open -> shipped (partly or fully) -> received -> closed; cancelled from draft/open (nothing
shipped). The source order (`direction out`) and its destination mirror (`in`, same number) share the status.
"""

from __future__ import annotations

from typing import Any

EPS = 1e-9
ACTIONS: dict[str, tuple[str, ...]] = {"open": ("draft",), "close": ("received", "shipped"),
                                       "cancel": ("draft", "open")}
TARGET = {"open": "open", "close": "closed", "cancel": "cancelled"}


def can(action: str, status: str, shipped: float = 0.0) -> bool:
    if action == "cancel" and shipped > EPS:
        return False
    return status in ACTIONS[action]


def derive_status(status: str, lines: list[tuple[float, float, float]]) -> str:
    """`lines` = [(qty, shipped, received)] -> status after a movement (open / shipped / received)."""
    if status in ("closed", "cancelled", "draft"):
        return status
    if lines and all(r >= q - EPS for q, _s, r in lines):
        return "received"
    if any(s > EPS for _q, s, _r in lines):
        return "shipped"
    return "open"


def match_item(src: Any, dest_items: list[Any]) -> Any | None:
    """Destination item by `external_ref`, else part number (+ revision, else any revision)."""
    if src.external_ref:
        for it in dest_items:
            if it.external_ref == src.external_ref:
                return it
    same = [it for it in dest_items if it.part_number == src.part_number]
    for it in same:
        if it.revision == src.revision:
            return it
    return same[0] if same else None


def take_in_transit(in_transit: list[dict[str, Any]], lot_code: str | None, qty: float) -> list[dict[str, Any]] | None:
    """Remove `qty` of `lot_code` from the in-transit list; None if not enough is in transit."""
    rest = qty
    out = []
    for x in in_transit:
        x = dict(x)
        if (x.get("lot_code") or None) == (lot_code or None) and rest > EPS:
            t = min(rest, float(x["qty"]))
            x["qty"] = round(float(x["qty"]) - t, 6)
            rest -= t
        if x["qty"] > EPS:
            out.append(x)
    return None if rest > 1e-6 else out


__all__ = ["ACTIONS", "TARGET", "can", "derive_status", "match_item", "take_in_transit"]
