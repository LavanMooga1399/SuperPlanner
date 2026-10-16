"""Shared return math (FINANCE.md sections 3, 4.8, 5.3, 5.4, 8.2).

Used by the optimizer, the simulator, the pipeline and the independent validator, so every stage values
a bucket with exactly the same formulas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import TYPE_CHECKING, Callable

from . import defaults as D

if TYPE_CHECKING:  # pragma: no cover
    from .model import AssetClass, Assumptions, FinancePlan, Goal

_ND = NormalDist()


def pi_general(plan: "FinancePlan") -> float:
    return plan.assumptions.inflation_pct / 100.0


def price_index(pi: float, t: int | float) -> float:
    """`P_t = (1 + pi)^(t/12)`."""
    return (1.0 + pi) ** (t / 12.0)


def real_annual(ac: "AssetClass", pi: float) -> float:
    """`R_a = (1 + mu - er - td) / (1 + pi) - 1`."""
    mu = ac.expected_return_pct / 100.0
    er = ac.expense_ratio_pct / 100.0
    td = ac.tax_drag_pct / 100.0
    return (1.0 + mu - er - td) / (1.0 + pi) - 1.0


def monthly_from_annual(R: float) -> float:
    return (1.0 + max(R, -0.99)) ** (1.0 / 12.0)


def gamma(ac: "AssetClass", pi: float) -> float:
    """Expected real monthly growth factor `1 + r_a`."""
    return monthly_from_annual(real_annual(ac, pi))


def min_probability(goal: "Goal") -> float:
    if goal.min_success_probability is not None:
        return goal.min_success_probability
    return D.DEFAULT_MIN_PROBABILITY[goal.priority]


def initial_z(goal: "Goal") -> float:
    return _ND.inv_cdf(min_probability(goal))


def real_volatility(ac: "AssetClass", inflation_vol: float) -> float:
    """Annual std dev of the class's *real* return: own volatility and inflation shocks (independent)."""
    return math.sqrt((ac.volatility_pct / 100.0) ** 2 + inflation_vol ** 2)


def planning_return(ac: "AssetClass", pi: float, z: float, D_g: int, inflation_vol: float) -> float:
    """Cautious annual real return for goal date `D_g` (8.2), interpreted as the z-quantile of the annualized
    lognormal real return over `Y = max(1, D/12)` years:
    `Rplan = max(-0.5, (1 + R) exp(-s^2/2 - z s / sqrt(Y)) - 1)`, `s = sqrt(ln(1 + (sigma_real/(1+R))^2))`.
    With zero volatility this is exactly `R` (see F.24.3)."""
    Y = max(1.0, D_g / 12.0)
    R = real_annual(ac, pi)
    sig = real_volatility(ac, inflation_vol)
    if sig <= 0:
        return max(-0.5, R)
    s = math.sqrt(math.log(1.0 + (sig / max(1e-6, 1.0 + R)) ** 2))
    return max(-0.5, (1.0 + R) * math.exp(-s * s / 2.0 - z * s / math.sqrt(Y)) - 1.0)


def planning_rho(ac: "AssetClass", pi: float, z: float, D_g: int, inflation_vol: float) -> float:
    return (1.0 + planning_return(ac, pi, z, D_g, inflation_vol)) ** (1.0 / 12.0)


def inflation_vol(plan: "FinancePlan") -> float:
    return plan.assumptions.inflation_volatility_pct / 100.0


def annuity_due(rho: float, n: int) -> float:
    """`Phi(n) = rho (rho^n - 1)/(rho - 1)`: value at block end of 1/month paid at the start of n months."""
    if n <= 0:
        return 0.0
    if abs(rho - 1.0) < 1e-12:
        return float(n)
    return rho * (rho ** n - 1.0) / (rho - 1.0)


def goal_inflation(plan: "FinancePlan", goal: "Goal") -> float:
    return (goal.inflation_pct / 100.0) if goal.inflation_pct is not None else pi_general(plan)


def real_target(plan: "FinancePlan", goal: "Goal", D_g: int) -> float:
    """`TR_g = target * ((1 + pi_g)/(1 + pi))^(D_g/12)`."""
    pi = pi_general(plan)
    pig = goal_inflation(plan, goal)
    return goal.target_amount * ((1.0 + pig) / (1.0 + pi)) ** (D_g / 12.0)


def tolerance_of(plan: "FinancePlan", goal: "Goal") -> int:
    return goal.risk_tolerance or plan.profile.risk_tolerance


def base_cap(assumptions: "Assumptions", tol: int) -> float:
    return assumptions.risky_cap_by_tolerance_pct[tol - 1] / 100.0


def glide(assumptions: "Assumptions", months_to_goal: int) -> float:
    best = None
    for step in assumptions.glide_path:
        if step.min_months_to_goal <= months_to_goal and (best is None or step.min_months_to_goal > best[0]):
            best = (step.min_months_to_goal, step.multiplier)
    return best[1] if best else 0.0


def is_risky(ac: "AssetClass") -> bool:
    return ac.category in D.RISKY_CATEGORIES


def is_equity(ac: "AssetClass") -> bool:
    return ac.category in D.EQUITY_CATEGORIES


def allowed_classes(plan: "FinancePlan", goal: "Goal") -> list[str]:
    """Allowed classes of a goal in assumption order (unknown ids ignored; preflight reports them)."""
    ids = [a.id for a in plan.assumptions.asset_classes]
    if goal.allowed_asset_class_ids is None:
        return ids
    allowed = set(goal.allowed_asset_class_ids)
    return [i for i in ids if i in allowed]


def goal_cap(plan: "FinancePlan", goal: "Goal", D_g: int, s_k: int) -> float:
    """Risky cap of goal g in the block starting at `s_k`: `base_g * glide(D_g - s_k)` (5.4)."""
    return base_cap(plan.assumptions, tolerance_of(plan, goal)) * glide(plan.assumptions, D_g - s_k)


def buyable(ac: "AssetClass", s_k: int, D_g: int) -> bool:
    """A rebalance may buy the class at block start `s_k` (8.3: lock-in classes only if they mature by D_g)."""
    return ac.lock_in_months == 0 or s_k + ac.lock_in_months <= D_g


def contributable(ac: "AssetClass", s_k: int, n_k: int, D_g: int) -> bool:
    """A level contribution over the block may go into the class (8.3 lock rule)."""
    return ac.lock_in_months == 0 or s_k + n_k - 1 + ac.lock_in_months <= D_g


def can_dilute(plan: "FinancePlan", goal: "Goal", D_g: int, s_k: int, capped: Callable[["AssetClass"], bool]) -> bool:
    """True when the goal can move money into an allowed, buyable class outside the capped set at `s_k`.

    Implementation note (F.24.3): a cap (glide cap, global equity or class cap) binds a goal's bucket only when
    this holds; otherwise the goal's capped positions count as allowance, like locked positions [R8]. Without it
    the LP could meet the cap only by destroying value (buy and sell the same class), or not at all."""
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    return any(not capped(classes[a]) and buyable(classes[a], s_k, D_g) for a in allowed_classes(plan, goal))


@dataclass(frozen=True)
class ActiveCaps:
    """Which caps bind a goal's bucket in the block starting at `s_k` (see `active_caps`)."""
    risk: bool
    equity: bool
    classes: frozenset[str]


def _caps_jointly_feasible(buy: list["AssetClass"], risk: float | None, equity: float | None,
                           cls: dict[str, float]) -> bool:
    """True when some mix of the buyable classes `buy` meets every given cap at once.

    The cap sets are laminar (single classes, equity within risky), so the largest mass that fits is: every
    non-risky class up to its own class cap, plus the risky classes up to the risky cap, where the equity classes
    are limited by the equity cap first. The caps can all hold iff that mass reaches 100 %."""
    def lim(ac: "AssetClass") -> float:
        return min(1.0, cls.get(ac.id, 1.0))
    non_r = sum(lim(ac) for ac in buy if not is_risky(ac))
    r_not_e = sum(lim(ac) for ac in buy if is_risky(ac) and not is_equity(ac))
    e = sum(lim(ac) for ac in buy if is_equity(ac))
    e_fit = min(equity, e) if equity is not None else e
    r_fit = r_not_e + e_fit
    if risk is not None:
        r_fit = min(risk, r_fit)
    return non_r + r_fit >= 1.0 - 1e-12


def active_caps(plan: "FinancePlan", goal: "Goal", D_g: int, s_k: int) -> ActiveCaps:
    """Caps that bind goal g's bucket at block start `s_k` (F.24.3 rule 4: caps bind only where they can be met).

    Implementation note: caps are taken greedily in priority order - the goal's risky cap, then the global
    equity cap, then the class caps in plan order - and a cap binds only when it can hold together with the caps
    already binding, given the classes the goal can buy at `s_k`. Testing each cap alone (`can_dilute`) is not
    enough: with only {fixed_deposit, equity} allowed, an equity cap of 0 % and a fixed_deposit cap of 40 % can
    each be met but not both, and requiring both would force the LP to empty the bucket. A cap that does not bind
    a goal makes that goal's capped positions count as allowance, as for locked positions [R8]."""
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    buy = [classes[a] for a in allowed_classes(plan, goal) if buyable(classes[a], s_k, D_g)]
    risk: float | None = None
    cap_g = goal_cap(plan, goal, D_g, s_k)
    if cap_g < 1.0 and _caps_jointly_feasible(buy, cap_g, None, {}):
        risk = cap_g
    equity: float | None = None
    maxeq = plan.constraints.max_equity_pct
    if maxeq is not None and _caps_jointly_feasible(buy, risk, maxeq / 100.0, {}):
        equity = maxeq / 100.0
    cls: dict[str, float] = {}
    for a, pct in plan.constraints.max_class_pct.items():
        if a not in classes:
            continue
        trial = dict(cls)
        trial[a] = pct / 100.0
        if _caps_jointly_feasible(buy, risk, equity, trial):
            cls = trial
    return ActiveCaps(risk=risk is not None, equity=equity is not None, classes=frozenset(cls))


def mix_cap_applies(plan: "FinancePlan", goal: "Goal", D_g: int, s_k: int, n_k: int) -> bool:
    """The contribution-mix cap (8.4 rule 8) binds only when a non-risky class can receive contributions."""
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    return any(not is_risky(classes[a]) and contributable(classes[a], s_k, n_k, D_g)
               for a in allowed_classes(plan, goal))


def floor2(v: float) -> float:
    """Floor to 2 decimals (8.8). The 1e-6 guard keeps 12.34 from flooring to 12.33 through float noise."""
    return math.floor(v * 100.0 + 1e-6) / 100.0
