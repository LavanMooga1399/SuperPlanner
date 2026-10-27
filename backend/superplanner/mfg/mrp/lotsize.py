"""Lot sizing and rounding (M2-DESIGN 8.6, the binding rounding decision).

Grouping: `lot_for_lot` = one order per distinct need date; `period` = one order for all residuals with need date
in `[d, d + lot_period_days)`; `fixed` = per residual the smallest `k x fixed_lot_qty` covering the uncovered
quantity. Then: MOQ -> multiple -> purchase pack (buy items, pack > 1) -> integer for count UoM (else 6 decimals).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..units import is_count
from .model import LotInfo


@dataclass(frozen=True, slots=True)
class LotParams:
    rule: str
    period_days: int
    fixed_qty: float | None
    moq: float
    multiple: float
    pack: float
    count: bool

    def info(self) -> LotInfo:
        return LotInfo(rule=self.rule, moq=self.moq, multiple=self.multiple, pack=self.pack,
                       period_days=self.period_days if self.rule == "period" else None, fixed_qty=self.fixed_qty)


def lot_params(item: Any, source: Any | None) -> LotParams:
    rule = getattr(item, "lot_rule", "lot_for_lot") or "lot_for_lot"
    period = int(getattr(item, "lot_period_days", None) or 1) if rule == "period" else 1
    if source is not None:
        moq, mult, pack = source.moq, source.multiple, source.pack
    else:
        moq, mult, pack = float(item.min_order_qty), float(item.order_multiple), 1.0
    if item.make_buy != "buy":
        pack = 1.0
    return LotParams(rule=rule, period_days=max(1, period), fixed_qty=getattr(item, "fixed_lot_qty", None),
                     moq=float(moq), multiple=float(mult), pack=float(pack), count=is_count(item.uom))


def fixed_lots(uncovered: float, lp: LotParams) -> float:
    f = lp.fixed_qty or 0.0
    if f <= 0:
        return uncovered
    return math.ceil(uncovered / f - 1e-9) * f


def round_order_qty(q: float, lp: LotParams) -> float:
    """Steps 2-5 of 8.6."""
    q = max(q, lp.moq)
    if lp.multiple > 0:
        q = math.ceil(q / lp.multiple - 1e-9) * lp.multiple
    if lp.pack > 1:
        q = math.ceil(q / lp.pack - 1e-9) * lp.pack
    if lp.count:
        return float(math.ceil(q - 1e-9))
    return round(q, 6)


def _num(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.6f}".rstrip("0").rstrip(".")


def lot_note(lp: LotParams) -> str:
    parts = [{"lot_for_lot": "lot-for-lot", "period": f"period {lp.period_days} days",
              "fixed": f"fixed {_num(lp.fixed_qty or 0)}"}.get(lp.rule, lp.rule)]
    if lp.moq > 0:
        parts.append(f"MOQ {_num(lp.moq)}")
    if lp.multiple > 0:
        parts.append(f"multiple {_num(lp.multiple)}")
    if lp.pack > 1:
        parts.append(f"pack {_num(lp.pack)}")
    return "; ".join(parts)[:200]


__all__ = ["LotParams", "fixed_lots", "lot_note", "lot_params", "round_order_qty"]
