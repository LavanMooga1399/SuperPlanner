"""Sampling schemes (M7-DESIGN 5.1): table validation, resolution and switching rules (pure).

`resolve(scheme, lot_size, level, aql, state)` -> `{n, ac, re, full}`: `fixed` -> n, ac 0, re 1; `percent` ->
ceil(lot_size x p / 100); `full` -> lot_size; `table` -> the lot-size range's code letter at `level`, then the plan of
`state` (normal / tightened) for that letter and AQL. `n >= lot_size` -> 100 % (`n = lot_size`, ac/re kept).
"""

from __future__ import annotations

import math
from typing import Any


class SchemeError(ValueError):
    def __init__(self, loc: list[Any], msg: str):
        super().__init__(msg)
        self.loc = loc


def validate_table(t: dict[str, Any]) -> None:
    """Ranges contiguous from 1 (last may be open), every level lettered, `n >= 1`, `0 <= ac < re <= n + 1`."""
    ranges = t["lot_size_ranges"]
    expect = 1
    for i, r in enumerate(ranges):
        if r["min"] != expect:
            raise SchemeError(["table", "lot_size_ranges", i, "min"], f"range {i + 1} must start at {expect}")
        if r.get("max") is None:
            if i != len(ranges) - 1:
                raise SchemeError(["table", "lot_size_ranges", i, "max"], "only the last range may be open")
            expect = None  # type: ignore[assignment]
            continue
        if r["max"] < r["min"]:
            raise SchemeError(["table", "lot_size_ranges", i, "max"], "max is below min")
        expect = r["max"] + 1
        for lv in t["levels"]:
            if lv not in r["letters"]:
                raise SchemeError(["table", "lot_size_ranges", i, "letters", lv], f"no code letter for level {lv}")
    if expect is not None:
        raise SchemeError(["table", "lot_size_ranges", len(ranges) - 1, "max"], "the last range must be open")
    for state, letters in t["plans"].items():
        for letter, by_aql in letters.items():
            for aql, p in by_aql.items():
                loc = ["table", "plans", state, letter, aql]
                if p["n"] < 1 or not (0 <= p["ac"] < p["re"] <= p["n"] + 1):
                    raise SchemeError(loc, "needs n >= 1 and 0 <= ac < re <= n + 1")
    if "normal" not in t["plans"]:
        raise SchemeError(["table", "plans", "normal"], "the normal plans are required")


def letter_for(t: dict[str, Any], lot_size: float, level: str) -> str:
    size = max(1, int(math.ceil(lot_size)))
    for r in t["lot_size_ranges"]:
        if r["min"] <= size and (r.get("max") is None or size <= r["max"]):
            letter = r["letters"].get(level)
            if letter is None:
                raise SchemeError(["level"], f"the scheme has no level {level}")
            return letter
    raise SchemeError(["lot_size"], "no lot-size range covers this lot")  # pragma: no cover - validated table


def resolve(kind: str, *, lot_size: float, fixed_n: int | None = None, percent: float | None = None,
            table: dict[str, Any] | None = None, level: str = "II", aql: str = "0.65", state: str = "normal"
            ) -> dict[str, Any]:
    size = max(1, int(math.ceil(lot_size)))
    if kind == "fixed":
        n, ac, re = int(fixed_n or 1), 0, 1
    elif kind == "percent":
        n, ac, re = max(1, int(math.ceil(size * float(percent or 100) / 100.0))), 0, 1
    elif kind == "full":
        n, ac, re = size, 0, 1
    else:
        assert table is not None
        letter = letter_for(table, size, level)
        plans = table["plans"].get(state) or table["plans"]["normal"]
        p = (plans.get(letter) or {}).get(aql)
        if p is None:
            raise SchemeError(["aql"], f"the scheme has no plan for letter {letter} at AQL {aql} ({state})")
        n, ac, re = int(p["n"]), int(p["ac"]), int(p["re"])
    full = n >= size
    return {"n": min(n, size), "ac": ac, "re": re, "full": full}


def next_state(state: str, history: list[str], rules: dict[str, Any] | None) -> str:
    """Switching (5.1): normal -> tightened when `rejected` of the last `of_last` decisions were rejections;
    tightened -> normal after `consecutive_accepted` acceptances. `history` = decisions, newest last ('A'/'R')."""
    r = rules or {"to_tightened": {"rejected": 2, "of_last": 5}, "to_normal": {"consecutive_accepted": 5}}
    if state == "normal":
        tt = r.get("to_tightened", {})
        window = history[-int(tt.get("of_last", 5)):]
        return "tightened" if window.count("R") >= int(tt.get("rejected", 2)) else "normal"
    k = int(r.get("to_normal", {}).get("consecutive_accepted", 5))
    tail = history[-k:]
    return "normal" if len(tail) >= k and all(x == "A" for x in tail) else "tightened"


__all__ = ["SchemeError", "letter_for", "next_state", "resolve", "validate_table"]
