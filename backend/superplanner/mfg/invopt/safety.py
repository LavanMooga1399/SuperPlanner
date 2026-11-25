"""Safety stock by service level (M8-DESIGN 5, 0.5; pure).

SS = z(SL) x sqrt(LT x sigma_d^2 + d^2 x sigma_LT^2); z = inverse standard normal (Acklam's rational
approximation, |error| < 1.2e-9, no scipy). The proposal is rounded up to the order pack (`pack_qty`) and capped at
`max_cover_days` x d (`SS_CAPPED`: the largest pack multiple within the cap).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
      -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
      -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
      4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
_LOW = 0.02425


def z_of(p: float) -> float:
    """Inverse standard normal CDF (Acklam)."""
    if not 0.0 < p < 1.0:
        raise ValueError("service level must be between 0 and 1")
    if p < _LOW:
        q = math.sqrt(-2 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
    if p > 1 - _LOW:
        return -z_of(1 - p)
    q = p - 0.5
    r = q * q
    return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
        (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)


def safety_stock(z: float, d: float, sigma_d: float, lt: float, sigma_lt: float) -> float:
    return z * math.sqrt(max(lt, 0.0) * sigma_d ** 2 + d ** 2 * sigma_lt ** 2)


def round_up(qty: float, pack: float | None) -> float:
    if not pack or pack <= 0:
        return math.ceil(qty - 1e-9) if qty > 0 else 0.0
    return math.ceil(qty / pack - 1e-9) * pack


@dataclass
class Proposal:
    raw: float
    proposed: float
    flags: list[str] = field(default_factory=list)


def propose(z: float, d: float, sigma_d: float, lt: float, sigma_lt: float, pack: float | None,
            max_cover_days: float) -> Proposal:
    raw = safety_stock(z, d, sigma_d, lt, sigma_lt)
    out = round_up(raw, pack)
    flags: list[str] = []
    cap = max_cover_days * d
    if max_cover_days > 0 and d > 0 and out > cap + 1e-9:
        step = pack if pack and pack > 0 else 1.0          # largest pack multiple within the cap
        out = math.floor(cap / step + 1e-9) * step
        flags.append("SS_CAPPED")
    return Proposal(raw, float(out), flags)


def lt_sigma(delays: list[float]) -> float:
    """Std of receipt delays (actual - confirmed days) of the last 20 receipts when >= 5, else 0."""
    xs = delays[-20:]
    if len(xs) < 5:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
