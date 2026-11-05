"""ECO impact rules (M5-DESIGN 5), pure."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

EPS = 1e-9
STATUSES = ("draft", "submitted", "approved", "rejected", "implemented", "cancelled")
ACTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "submit": (("draft",), "submitted"), "approve": (("submitted",), "approved"),
    "reject": (("submitted",), "rejected"), "cancel": (("draft", "submitted", "approved"), "cancelled"),
    "implement": (("approved",), "implemented")}


def bom_delta(old: Iterable[tuple[str, float]], new: Iterable[tuple[str, float]], names: dict[str, str]
              ) -> dict[str, list[Any]]:
    """Component (child item id, qty per summed over lines) delta: added / removed / changed (old -> new)."""
    a: dict[str, float] = {}
    b: dict[str, float] = {}
    for k, q in old:
        a[k] = a.get(k, 0.0) + q
    for k, q in new:
        b[k] = b.get(k, 0.0) + q
    added = sorted(names.get(k, k) for k in b if k not in a)
    removed = sorted(names.get(k, k) for k in a if k not in b)
    changed = sorted(({"item": names.get(k, k), "item_id": k, "from": round(a[k], 6), "to": round(b[k], 6)}
                      for k in a if k in b and abs(a[k] - b[k]) > EPS), key=lambda x: x["item"])
    return {"added": added, "removed": removed, "changed": changed,
            "added_ids": sorted(k for k in b if k not in a), "removed_ids": sorted(k for k in a if k not in b)}


def use_up_date(timeline: Iterable[Any], as_of: date) -> date | None:
    """First date the projected (existing-supply) balance of a phased-out component reaches zero; `as_of` when
    nothing is on hand, None when it never runs out in the horizon."""
    ev = sorted(timeline, key=lambda e: (e.date, 0 if e.kind == "on_hand" else 1))
    if not ev:
        return as_of
    start = next((e.balance_existing for e in ev if e.kind == "on_hand"), None)
    if start is not None and start <= EPS:
        return as_of
    for e in ev:
        if e.kind != "on_hand" and e.balance_existing <= EPS:
            return e.date
    return None


def self_approval(submitted_by: str | None, actor: str, privileged: bool) -> bool:
    """True when the approval must be refused (approver == submitter, unless owner / plant_admin)."""
    return not privileged and submitted_by is not None and submitted_by == actor


__all__ = ["ACTIONS", "STATUSES", "bom_delta", "self_approval", "use_up_date"]
