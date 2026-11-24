"""Inspection results -> verdict (M7-DESIGN 5.2), pure.

Per characteristic: defective units d over its entered (not superseded) samples; `d >= re` -> reject; all n entered
and `d <= ac` -> accept; else pending. Lot verdict: reject if any characteristic rejects, accept when all accept,
else pending. A variable result is defective iff outside [lsl, usl]; an attribute result iff not passed.
"""

from __future__ import annotations

from typing import Any


def defective(kind: str, value: float | None, passed: bool | None, lsl: float | None, usl: float | None) -> bool:
    if kind == "variable":
        if value is None:
            return True
        return (lsl is not None and value < lsl) or (usl is not None and value > usl)
    return not bool(passed)


def characteristic_verdict(n: int, ac: int, re: int, samples: dict[int, bool]) -> tuple[str, int, int]:
    """samples: sample_no -> defective. -> (verdict, entered, defective)."""
    entered = len(samples)
    d = sum(1 for x in samples.values() if x)
    if d >= re:
        return "reject", entered, d
    if entered >= n and d <= ac:
        return "accept", entered, d
    return "pending", entered, d


def lot_verdict(chars: list[dict[str, Any]]) -> str:
    vs = [c["verdict"] for c in chars]
    if any(v == "reject" for v in vs):
        return "reject"
    if vs and all(v == "accept" for v in vs):
        return "accept"
    return "pending"


__all__ = ["characteristic_verdict", "defective", "lot_verdict"]
