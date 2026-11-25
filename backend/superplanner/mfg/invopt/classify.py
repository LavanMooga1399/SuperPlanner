"""ABC / XYZ classification (M8-DESIGN 5, pure).

- ABC: items ranked by annual value (12-month forecast, else history, x standard cost; missing cost -> volume and
  flag `FC_NO_COST`) descending; cumulative share of the total (including the item) <= cutoffs[0] -> A,
  <= cutoffs[1] -> B, else C. The top item is always A (a dominant item never leaves class A empty).
- XYZ: CV = rmse1 / mean period demand (intermittent / lumpy: CV of non-zero sizes x sqrt(ADI)); < cutoffs[0] X,
  < cutoffs[1] Y, else Z.
"""

from __future__ import annotations

import math
from typing import Iterable


def abc(values: dict[str, float], cutoffs: Iterable[float] = (0.8, 0.95)) -> dict[str, str]:
    a_cut, b_cut = list(cutoffs)
    ranked = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(max(v, 0.0) for _k, v in ranked)
    out: dict[str, str] = {}
    cum = 0.0
    for n, (k, v) in enumerate(ranked):
        cum += max(v, 0.0)
        share = cum / total if total > 0 else 1.0
        if total <= 0:
            out[k] = "C"
        elif n == 0 or share <= a_cut + 1e-12:
            out[k] = "A"
        elif share <= b_cut + 1e-12:
            out[k] = "B"
        else:
            out[k] = "C"
    return out


def cv(rmse1: float, mean: float, demand_class: str | None = None, nonzero_cv: float | None = None,
       adi: float | None = None) -> float:
    if demand_class in ("intermittent", "lumpy") and nonzero_cv is not None and adi:
        return nonzero_cv * math.sqrt(adi)
    if mean <= 0:
        return math.inf
    return rmse1 / mean


def xyz(cv_value: float, cutoffs: Iterable[float] = (0.5, 1.0)) -> str:
    x_cut, y_cut = list(cutoffs)
    if cv_value < x_cut:
        return "X"
    if cv_value < y_cut:
        return "Y"
    return "Z"
