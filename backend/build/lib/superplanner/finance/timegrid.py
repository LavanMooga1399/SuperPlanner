"""Month arithmetic, occurrence rule, horizon and blocks (FINANCE.md section 3 and 7.1)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .model import FinancePlan, Goal

PERIOD = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12, "once": 0}
MONTHLY_FACTOR = {"monthly": 1.0, "quarterly": 1 / 3, "half_yearly": 1 / 6, "yearly": 1 / 12, "once": 0.0}


def parse_month(m: str) -> tuple[int, int]:
    y, mo = m.split("-")
    return int(y), int(mo)


def month_index(start_month: str, m: str) -> int:
    """Number of months from `start_month` to `m` (negative if `m` is earlier)."""
    y0, m0 = parse_month(start_month)
    y1, m1 = parse_month(m)
    return (y1 - y0) * 12 + (m1 - m0)


def add_months(start_month: str, n: int) -> str:
    y, m = parse_month(start_month)
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_list(start_month: str, T: int) -> list[str]:
    return [add_months(start_month, t) for t in range(T)]


def item_bounds(start_month: str, item_start: str | None, item_end: str | None, T: int) -> tuple[int, int]:
    """Clamped `[t0, t1]` of a recurring item (4.3: an item starting before the plan start starts at 0).

    Returns `t1 < t0` when the item never occurs inside the horizon."""
    t0 = 0 if item_start is None else max(0, month_index(start_month, item_start))
    t1 = T - 1 if item_end is None else min(T - 1, month_index(start_month, item_end))
    return t0, t1


def occurs(t: int, t0: int, t1: int, frequency: str) -> bool:
    if t < t0 or t > t1:
        return False
    p = PERIOD[frequency]
    if p == 0:
        return t == t0
    return (t - t0) % p == 0


def occurrence_months(t0: int, t1: int, frequency: str) -> list[int]:
    if t1 < t0:
        return []
    p = PERIOD[frequency]
    if p == 0:
        return [t0]
    return list(range(t0, t1 + 1, p))


def goal_date(plan: "FinancePlan", goal: "Goal") -> int:
    return month_index(plan.start_month or "2000-01", goal.target_month)


def computed_horizon(plan: "FinancePlan") -> int:
    """`max(12, max D_g + 1, last one-off + 1)` over enabled goals (section 3, [R1])."""
    start = plan.start_month or "2000-01"
    T = 12
    for g in plan.goals:
        if g.enabled:
            T = max(T, month_index(start, g.target_month) + 1)
    for o in plan.one_offs:
        T = max(T, month_index(start, o.month) + 1)
    return T


def horizon(plan: "FinancePlan") -> int:
    """Plan horizon T. An explicit `horizon_end_month` is used only when it covers the computed value
    (otherwise preflight reports `HORIZON_BEFORE_GOAL` and the computed value is used)."""
    T = computed_horizon(plan)
    if plan.horizon_end_month and plan.start_month:
        explicit = month_index(plan.start_month, plan.horizon_end_month) + 1
        if explicit >= T:
            T = explicit
    return T


def blocks(D: int, L: int) -> list[tuple[int, int, int]]:
    """Blocks `(k, s_k, n_k)` of a goal with date `D` and block length `L`, truncated at `D`."""
    K = math.ceil(D / L) if D > 0 else 0
    return [(k, k * L, min(L, D - k * L)) for k in range(K)]


def plan_year(t: int) -> int:
    return t // 12
