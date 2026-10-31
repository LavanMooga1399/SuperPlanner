"""Barcode grammar (M4-DESIGN 5): a scanned string -> the lookups that resolve it, in order. Pure; the service
(`services/floor.scan`) runs the lookups and returns the first hit (404 `FLR_SCAN_UNKNOWN` when none).

| Scan | Meaning |
| `WO-000143` or any WO number | work order |
| `WO-000143/30` | operation seq 30 of that WO |
| `L:<part>:<lot>` | lot |
| `S:<part>:<serial>` | unit serial |
| `LOC:<code>`, `LIN:<code>` | location, line |
| `OP:<code>` | operator badge (M1 operator code) |
| `BL:<id-suffix>` | batch load |

Prefixes are case-insensitive. A bare string is tried as a WO number, then as a lot code, a serial, a line, a
location and an operator code (raw document numbers are accepted, 5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Lookup:
    type: str            # work_order | operation | lot | serial | location | line | operator | batch_load
    key: tuple[str, ...]


def normalise(code: str) -> str:
    """Scanners may add CR/LF/tab or surrounding blanks; internal whitespace collapses to one blank."""
    return _WS.sub(" ", code.strip())


def parse(code: str) -> list[Lookup]:
    c = normalise(code)
    if not c:
        return []
    up = c.upper()
    for prefix, kind in (("LOC:", "location"), ("LIN:", "line"), ("OP:", "operator"), ("BL:", "batch_load")):
        if up.startswith(prefix):
            rest = c[len(prefix):].strip()
            return [Lookup(kind, (rest,))] if rest else []
    for prefix, kind in (("L:", "lot"), ("S:", "serial")):
        if up.startswith(prefix):
            part, sep, value = c[len(prefix):].partition(":")
            if not sep or not part.strip() or not value.strip():
                return []
            return [Lookup(kind, (part.strip(), value.strip()))]
    out: list[Lookup] = []
    if "/" in c:
        number, _, seq = c.rpartition("/")
        if number.strip() and seq.strip().isdigit() and len(seq.strip()) <= 9:
            out.append(Lookup("operation", (number.strip(), str(int(seq.strip())))))
    out.append(Lookup("work_order", (c,)))
    out += [Lookup("lot_code", (c,)), Lookup("serial_code", (c,)), Lookup("line", (c,)), Lookup("location", (c,)),
            Lookup("operator", (c,))]
    return out


__all__ = ["Lookup", "normalise", "parse"]
