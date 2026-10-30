"""Operation durations on a line incl. line rates and sequence-dependent setups (M3-DESIGN 4).

```
setup_o,L(prev) = matrix(L.setup_family, family(prev item), family(item))   if L.setup_family has a matching row
                = rate.setup_minutes ?? o.setup_minutes                     otherwise
                = 0 when prev is the same order's same operation (continuation of a split on the same line)
run_o,L(q)      = rate.run_minutes x loads(o, q)                           if a line rate overrides run_minutes
                = o.run_minutes x loads(o, q) / L.speed_factor             otherwise
```
`family(item) = item.setup_family or item.family or ""`. Durations are whole minutes, rounded up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..routing import loads, to_engine_minutes

ANY = "*"


def family(item: Any) -> str:
    return (getattr(item, "setup_family", None) or getattr(item, "family", None) or "") if item is not None else ""


class SetupMatrix:
    """Rows by line setup family; `lookup` -> minutes or None (no matching row)."""

    def __init__(self, rows: Any):
        self.by_line: dict[str, dict[tuple[str, str], float]] = {}
        for r in rows:
            self.by_line.setdefault(r.line_setup_family, {})[(r.from_family, r.to_family)] = float(r.setup_minutes)

    def lookup(self, line_family: str | None, prev_family: str | None, fam: str) -> float | None:
        if not line_family:
            return None
        t = self.by_line.get(line_family)
        if not t:
            return None
        if prev_family is None:          # nothing before on the slot (horizon start)
            for k in ((ANY, fam), (ANY, ANY)):
                if k in t:
                    return t[k]
            return None
        for k in ((prev_family, fam), (prev_family, ANY), (ANY, fam), (ANY, ANY)):
            if k in t:
                return t[k]
        return None


@dataclass(frozen=True)
class Rate:
    setup_minutes: float | None
    run_minutes: float | None


def rates_index(ds: Any) -> dict[tuple[str, str], Rate]:
    """(operation_id, line_id) -> Rate."""
    return {(r.operation_id, r.line_id): Rate(r.setup_minutes, r.run_minutes)
            for r in getattr(ds, "operation_line_rates", {}).values()}


def setup_minutes(op: Any, line: Any, rate: Rate | None, matrix: SetupMatrix, prev_family: str | None, fam: str,
                  *, continuation: bool = False) -> int:
    if continuation:
        return 0
    m = matrix.lookup(getattr(line, "setup_family", None), prev_family, fam)
    if m is not None:
        return to_engine_minutes(m)
    if rate is not None and rate.setup_minutes is not None:
        return to_engine_minutes(rate.setup_minutes)
    return to_engine_minutes(op.setup_minutes)


def run_minutes(op: Any, line: Any, rate: Rate | None, qty: float) -> int:
    n = loads(op, qty)
    if rate is not None and rate.run_minutes is not None:
        return to_engine_minutes(rate.run_minutes * n)
    return to_engine_minutes(op.run_minutes * n / (line.speed_factor or 1.0))


__all__ = ["ANY", "Rate", "SetupMatrix", "family", "rates_index", "run_minutes", "setup_minutes"]
