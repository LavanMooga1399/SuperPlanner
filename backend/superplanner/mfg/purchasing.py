"""Purchasing rules (M2-DESIGN 3.3, 5): PR/PO status machines, derived PO/line status, schedule dates (dock,
available, overdue), supply eligibility for MRP and the item-supplier source resolution. Pure (no I/O).

Action errors are returned as `RuleError` (the services raise them as API errors):
- wrong state -> 409 `MFG_INVALID_STATE` `details: {status, action, allowed_from}`;
- edit of a document in a final status -> 409 `MFG_DOC_READONLY`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .model_m2 import EPS

# ---------------------------------------------------------------- errors


@dataclass
class RuleError(Exception):
    status: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.status} {self.code}: {self.message}"


def invalid_state(what: str, status: str, action: str, allowed_from: Iterable[str]) -> RuleError:
    allowed = list(allowed_from)
    return RuleError(409, "MFG_INVALID_STATE",
                     f"{what} is {status.replace('_', ' ')}; '{action}' is only possible when it is "
                     f"{' or '.join(a.replace('_', ' ') for a in allowed)}.",
                     {"status": status, "action": action, "allowed_from": allowed})


def readonly(what: str, status: str) -> RuleError:
    return RuleError(409, "MFG_DOC_READONLY", f"{what} is {status.replace('_', ' ')} and can no longer be changed.",
                     {"status": status})


# ---------------------------------------------------------------- status machines (5.1)

PR_ACTIONS: dict[str, tuple[tuple[str, ...], str | None]] = {
    # action: (allowed from, target (None = computed))
    "submit": (("draft",), "submitted"),
    "approve": (("submitted",), "approved"),
    "reject": (("submitted",), "rejected"),
    "revise": (("submitted", "rejected"), "draft"),
    "cancel": (("draft", "submitted", "approved", "rejected"), "cancelled"),
    "convert": (("approved",), None),
}
PR_EDITABLE = ("draft", "rejected")
PR_READONLY = ("submitted", "approved", "ordered", "cancelled")

PO_ACTIONS: dict[str, tuple[tuple[str, ...], str | None]] = {
    "issue": (("draft",), "open"),
    "close": (("open", "partially_received", "received"), "closed"),
    "cancel": (("draft", "open"), "cancelled"),
}
PO_EDITABLE = ("draft", "open", "partially_received")
PO_READONLY = ("received", "closed", "cancelled")
#: 5.5: document statuses whose open lines/schedules count as supply
PR_SUPPLY_STATUSES = ("draft", "submitted", "approved")
PO_SUPPLY_STATUSES = ("draft", "open", "partially_received")


def doc_label(doc_type: str) -> str:
    return "This purchase request" if doc_type == "pr" else "This purchase order"


def check_action(doc_type: str, status: str, action: str) -> str | None:
    """Raise `RuleError` if `action` is not allowed in `status`; returns the target status (None = computed)."""
    table = PR_ACTIONS if doc_type == "pr" else PO_ACTIONS
    allowed, target = table[action]
    if status not in allowed:
        raise invalid_state(doc_label(doc_type), status, action, allowed)
    return target


def check_editable(doc_type: str, status: str) -> None:
    editable = PR_EDITABLE if doc_type == "pr" else PO_EDITABLE
    if status not in editable:
        raise readonly(doc_label(doc_type), status)


def check_deletable(doc_type: str, status: str, source: str, has_receipts: bool) -> None:
    """PR: `draft` not from MRP, or any `cancelled`; PO: `draft` without receipts (5.1)."""
    if doc_type == "pr":
        if status == "cancelled" or (status == "draft" and source != "mrp"):
            return
        allowed = ["cancelled"] if source == "mrp" else ["draft", "cancelled"]
        raise invalid_state(doc_label("pr"), status, "delete", allowed)
    if status != "draft" or has_receipts:
        raise invalid_state(doc_label("po"), status, "delete", ["draft"])


def check_po_cancel(status: str, has_receipts: bool) -> None:
    check_action("po", status, "cancel")
    if has_receipts:
        raise RuleError(409, "MFG_INVALID_STATE", "This purchase order has receipts and cannot be cancelled; close "
                        "it instead.", {"status": status, "action": "cancel", "allowed_from": ["draft", "open"]})


def check_self_approval(submitted_by: str | None, actor: str, is_owner: bool) -> None:
    """A member cannot approve a PR they submitted (409 `PUR_SELF_APPROVAL`); the workspace owner may."""
    if not is_owner and submitted_by is not None and submitted_by == actor:
        raise RuleError(409, "PUR_SELF_APPROVAL", "You submitted this purchase request, so someone else has to "
                        "approve it.", {"submitted_by": submitted_by})


# ---------------------------------------------------------------- derived status (5.1)


@dataclass
class SchedState:
    qty: float
    received_qty: float
    closed: bool

    @property
    def open_qty(self) -> float:
        return 0.0 if self.closed else max(0.0, self.qty - self.received_qty)


def schedule_open_qty(qty: float, received_qty: float, closed: bool) -> float:
    return 0.0 if closed else max(0.0, qty - received_qty)


def derive_po_status(status: str, schedules: Iterable[SchedState]) -> str:
    """Status after a posting or PUT: `open`/`partially_received`/`received` follow the receipts (a reversal moves
    `received` back); `draft`, `closed`, `cancelled` are kept."""
    if status not in ("open", "partially_received", "received"):
        return status
    scs = list(schedules)
    any_received = any(s.received_qty > EPS for s in scs)
    all_done = bool(scs) and all(s.closed or s.received_qty >= s.qty - EPS for s in scs)
    if all_done and any_received:
        return "received"
    if any_received:
        return "partially_received"
    return "open"


def derive_pr_status(status: str, line_statuses: Iterable[str]) -> str:
    """`approved` PR becomes `ordered` when no line is `open` any more (5.4)."""
    if status == "approved" and not any(s == "open" for s in line_statuses):
        return "ordered"
    return status


# ---------------------------------------------------------------- dates (5.2)


def dock_date(requested: date, confirmed: date | None) -> date:
    return confirmed or requested


def available_date(dock: date, receiving_days: int) -> date:
    return dock + timedelta(days=int(receiving_days or 0))


def overdue(open_qty: float, closed: bool, dock: date, today: date) -> tuple[bool, int]:
    late = open_qty > EPS and not closed and dock < today
    return late, (today - dock).days if late else 0


def schedule_view(qty: float, received_qty: float, closed: bool, requested: date, confirmed: date | None,
                  receiving_days: int, today: date) -> dict[str, Any]:
    """The computed fields of a schedule record (3.5)."""
    oq = schedule_open_qty(qty, received_qty, closed)
    d = dock_date(requested, confirmed)
    od, days = overdue(oq, closed, d, today)
    return {"open_qty": round(oq, 6), "dock_date": d, "available_date": available_date(d, receiving_days),
            "overdue": od, "overdue_days": days}


def is_supply(doc_type: str, doc_status: str, line_status: str, open_qty: float, closed: bool) -> bool:
    """5.5: what counts as supply in MRP."""
    if doc_type == "pr":
        return doc_status in PR_SUPPLY_STATUSES and line_status == "open" and open_qty > EPS
    return doc_status in PO_SUPPLY_STATUSES and line_status == "open" and open_qty > EPS and not closed


# ---------------------------------------------------------------- receipts (4.1, 5.3)


def receipt_limit(open_qty: float, over_receipt_pct: float) -> float:
    return open_qty * (1.0 + over_receipt_pct / 100.0) + EPS


def allocate_receipt(schedules: list[tuple[str, date, float]], qty: float) -> list[tuple[str, float]]:
    """UI helper (5.3): spread a receipt of `qty` over a line's open schedules `(id, dock_date, open_qty)` in
    dock-date order; any excess goes to the last schedule (the over-receipt rule then decides)."""
    out: list[tuple[str, float]] = []
    rest = qty
    ordered = sorted(schedules, key=lambda s: (s[1], s[0]))
    for i, (sid, _d, oq) in enumerate(ordered):
        if rest <= EPS:
            break
        take = rest if i == len(ordered) - 1 else min(rest, oq)
        if take > EPS:
            out.append((sid, round(take, 6)))
            rest -= take
    return out


# ---------------------------------------------------------------- item-supplier source (3.3)


@dataclass(frozen=True)
class Source:
    item_supplier_id: str | None
    supplier_id: str | None
    lead_time_days: int | None
    lead_time_source: str              # override | item_supplier | supplier | item
    min_order_qty: float
    order_multiple: float
    pack: float
    unit_price: float | None
    currency: str


def resolve_source(item: Any, rows: Iterable[Any], suppliers: dict[str, Any]) -> Source:
    """The preferred active row whose supplier is active; else the active row (active supplier) with the smallest
    effective lead time, then supplier code. Effective values: lead time row -> supplier -> item; MOQ/multiple row
    if > 0 else item; pack = the row's `units_per_purchase_unit` (1 without a row)."""
    cands = [r for r in rows if r.active and getattr(suppliers.get(r.supplier_id), "active", False)]

    def lt(r: Any) -> tuple[int | None, str]:
        if r.lead_time_days is not None:
            return r.lead_time_days, "item_supplier"
        sp = suppliers.get(r.supplier_id)
        if sp is not None and sp.lead_time_days is not None:
            return sp.lead_time_days, "supplier"
        return item.lead_time_days, "item"

    pref = [r for r in cands if r.preferred]
    chosen = None
    if pref:
        chosen = sorted(pref, key=lambda r: (suppliers[r.supplier_id].code, r.id))[0]
    elif cands:
        chosen = sorted(cands, key=lambda r: (lt(r)[0] if lt(r)[0] is not None else 10**9,
                                              suppliers[r.supplier_id].code, r.id))[0]
    if chosen is None:
        return Source(None, None, item.lead_time_days, "item", float(item.min_order_qty), float(item.order_multiple),
                      1.0, None, "")
    days, src = lt(chosen)
    return Source(chosen.id, chosen.supplier_id, days, src,
                  float(chosen.min_order_qty) if chosen.min_order_qty > 0 else float(item.min_order_qty),
                  float(chosen.order_multiple) if chosen.order_multiple > 0 else float(item.order_multiple),
                  float(chosen.units_per_purchase_unit), chosen.unit_price, chosen.currency)


def common_preferred_supplier(sources: Iterable[Source]) -> str | None:
    """5.4: the supplier preferred by every selected line's item, else None."""
    ids = {s.supplier_id for s in sources}
    if len(ids) == 1:
        (only,) = ids
        return only
    return None


def doc_value(lines: Iterable[tuple[float, float | None, float]]) -> tuple[float | None, float | None]:
    """`(qty, unit_price, open_qty)` per line -> (value, open_value); None if any price is missing."""
    v = ov = 0.0
    for qty, price, oq in lines:
        if price is None:
            return None, None
        v += qty * price
        ov += oq * price
    return round(v, 6), round(ov, 6)


__all__ = ["PO_ACTIONS", "PO_EDITABLE", "PO_READONLY", "PO_SUPPLY_STATUSES", "PR_ACTIONS", "PR_EDITABLE",
           "PR_READONLY", "PR_SUPPLY_STATUSES", "RuleError", "SchedState", "Source", "allocate_receipt",
           "available_date", "check_action", "check_deletable", "check_editable", "check_po_cancel",
           "check_self_approval", "common_preferred_supplier", "derive_po_status", "derive_pr_status", "doc_value",
           "dock_date", "invalid_state", "is_supply", "overdue", "readonly", "receipt_limit", "resolve_source",
           "schedule_open_qty", "schedule_view"]
