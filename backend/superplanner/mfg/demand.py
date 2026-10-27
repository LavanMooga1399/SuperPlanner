"""Demand-order rules (M2-DESIGN 3.6, 6): status machine, editability, serial-range rules, effective priority.
Pure (no I/O); errors are `purchasing.RuleError`.

Status: `draft --open--> open --close--> closed`; `open` also re-opens `closed`; `cancel` from `draft`/`open`
without shipments; DELETE only `draft`/`cancelled` without shipments. When every line is shipped the order closes
automatically. Only `open` orders are planned; MRP plans lines with `open_qty > EPS`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .model_m2 import EPS
from .purchasing import RuleError, invalid_state, readonly

ACTIONS: dict[str, tuple[str, ...]] = {"open": ("draft", "closed"), "close": ("open",), "cancel": ("draft", "open")}
TARGET = {"open": "open", "close": "closed", "cancel": "cancelled"}
EDITABLE = ("draft", "open")
WHAT = "This demand order"


def check_action(status: str, action: str, *, has_shipments: bool = False) -> str:
    allowed = ACTIONS[action]
    if status not in allowed:
        raise invalid_state(WHAT, status, action, allowed)
    if action == "cancel" and has_shipments:
        raise RuleError(409, "MFG_INVALID_STATE", "This demand order has shipments and cannot be cancelled; close it "
                        "instead.", {"status": status, "action": action, "allowed_from": list(allowed)})
    return TARGET[action]


def check_editable(status: str) -> None:
    if status not in EDITABLE:
        raise readonly(WHAT, status)


def check_deletable(status: str, has_shipments: bool) -> None:
    if status not in ("draft", "cancelled") or has_shipments:
        raise invalid_state(WHAT, status, "delete", ["draft", "cancelled"])


def effective_priority(line_priority: int | None, header_priority: int) -> int:
    return line_priority if line_priority is not None else header_priority


def open_qty(qty: float, shipped: float) -> float:
    return max(0.0, qty - shipped)


def line_status(qty: float, shipped: float) -> str:
    return "shipped" if shipped >= qty - EPS else "open"


def derive_status(status: str, lines: Iterable[tuple[float, float]]) -> str:
    """Auto-close an `open` order when every line `(qty, shipped)` is shipped; a reversal re-opens it."""
    ls = list(lines)
    all_shipped = bool(ls) and all(s >= q - EPS for q, s in ls)
    if status == "open" and all_shipped:
        return "closed"
    return status


def reopen_after_reversal(status: str, lines: Iterable[tuple[float, float]]) -> str:
    ls = list(lines)
    if status == "closed" and any(s < q - EPS for q, s in ls):
        return "open"
    return status


@dataclass(frozen=True)
class SerialLine:
    index: int
    item_id: str
    serial_from: int | None
    serial_to: int | None


def serial_qty_error(serialized: bool, qty: float, sf: int | None, st: int | None) -> RuleError | None:
    """Item `serialized` else 422 `MFG_SERIAL_NOT_ALLOWED`; `to - from + 1 == qty` else 422
    `DEM_SERIAL_QTY_MISMATCH` (both or neither is a model rule)."""
    if sf is None:
        return None
    if not serialized:
        return RuleError(422, "MFG_SERIAL_NOT_ALLOWED", "This item is not serialized, so the line cannot have a serial "
                         "range.", {})
    if st is None or st - sf + 1 != round(qty) or abs(qty - round(qty)) > EPS:
        return RuleError(422, "DEM_SERIAL_QTY_MISMATCH", f"Serials {sf}-{st} are {0 if st is None else st - sf + 1} "
                         f"units but the quantity is {qty:g}.", {"serial_from": sf, "serial_to": st, "qty": qty})
    return None


def serial_overlaps(lines: Iterable[SerialLine]) -> list[tuple[int, int]]:
    """Pairs of line indexes of the same item whose serial ranges overlap (within one order -> 422
    `DEM_SERIAL_OVERLAP`; across orders the MRP warns)."""
    by_item: dict[str, list[SerialLine]] = {}
    for ln in lines:
        if ln.serial_from is not None and ln.serial_to is not None:
            by_item.setdefault(ln.item_id, []).append(ln)
    out: list[tuple[int, int]] = []
    for item_id in sorted(by_item):
        ls = sorted(by_item[item_id], key=lambda x: (x.serial_from, x.index))
        for i, a in enumerate(ls):
            for b in ls[i + 1:]:
                if b.serial_from > a.serial_to:
                    break
                out.append((min(a.index, b.index), max(a.index, b.index)))
    return sorted(out)


def check_line_edit(line_exists_with_shipments: bool, removed: bool, new_qty: float | None, shipped: float,
                    index: Any) -> None:
    if removed and line_exists_with_shipments:
        raise RuleError(422, "DEM_LINE_HAS_SHIPMENTS", "A line with shipments cannot be removed.", {"line": index})
    if new_qty is not None and new_qty < shipped - EPS:
        raise RuleError(422, "DEM_QTY_BELOW_SHIPPED", f"The quantity cannot go below the {shipped:g} already "
                        "shipped.", {"line": index, "shipped_qty": shipped})


__all__ = ["ACTIONS", "EDITABLE", "SerialLine", "check_action", "check_deletable", "check_editable",
           "check_line_edit", "derive_status", "effective_priority", "line_status", "open_qty",
           "reopen_after_reversal", "serial_overlaps", "serial_qty_error"]
