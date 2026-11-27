"""Monthly FX (M9-DESIGN 8.4): identity; direct row; inverse; via USD; else the latest earlier month within 3 months
(`FX_STALE`); else `None` (`FX_MISSING`) - never a silent 1."""

from __future__ import annotations

from datetime import date
from typing import Iterable

Rate = tuple[float | None, list[str]]


def _month(d: date) -> date:
    return d.replace(day=1)


def _back(m: date, k: int) -> date:
    y, mo = m.year, m.month - k
    while mo <= 0:
        mo += 12
        y -= 1
    return date(y, mo, 1)


class FxTable:
    def __init__(self, rows: Iterable[tuple[str, str, date, float]] = ()):
        self.r: dict[tuple[str, str, date], float] = {}
        for f, t, m, x in rows:
            if x > 0:
                self.r[(f.upper(), t.upper(), _month(m))] = float(x)

    def set(self, f: str, t: str, m: date, x: float) -> None:
        self.r[(f.upper(), t.upper(), _month(m))] = float(x)

    def _exact(self, f: str, t: str, m: date) -> float | None:
        if f == t:
            return 1.0
        x = self.r.get((f, t, m))
        if x is not None:
            return x
        inv = self.r.get((t, f, m))
        if inv:
            return 1.0 / inv
        if "USD" not in (f, t):
            a, b = self._exact(f, "USD", m), self._exact("USD", t, m)
            if a is not None and b is not None:
                return a * b
        return None

    def rate(self, f: str, t: str, month: date) -> Rate:
        f, t, m = f.upper(), t.upper(), _month(month)
        x = self._exact(f, t, m)
        if x is not None:
            return x, []
        for k in (1, 2, 3):
            x = self._exact(f, t, _back(m, k))
            if x is not None:
                return x, ["FX_STALE"]
        return None, ["FX_MISSING"]

    def convert(self, amount: float | None, f: str, t: str, month: date) -> tuple[float | None, list[str]]:
        if amount is None:
            return None, []
        x, flags = self.rate(f, t, month)
        return (None if x is None else amount * x), flags
