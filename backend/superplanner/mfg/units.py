"""Units of measure (M1-DESIGN 3.2): a fixed table; user-defined units are deferred."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Uom:
    code: str
    dimension: str
    factor: float          # to the base unit of the dimension
    aliases: tuple[str, ...]


UOMS: tuple[Uom, ...] = (
    Uom("EA", "count", 1.0, ("EA", "EACH", "PC", "PCS", "PCE", "NO", "NOS", "NUM", "UNIT", "UNITS")),
    Uom("M", "length", 1.0, ("M", "MTR", "MTRS", "METER", "METRE", "METERS", "METRES")),
    Uom("CM", "length", 0.01, ("CM",)),
    Uom("MM", "length", 0.001, ("MM",)),
    Uom("KG", "mass", 1.0, ("KG", "KGS")),
    Uom("G", "mass", 0.001, ("G", "GM", "GMS", "GRAM")),
    Uom("L", "volume", 1.0, ("L", "LT", "LTR", "LITRE", "LITER")),
    Uom("ML", "volume", 0.001, ("ML",)),
    Uom("M2", "area", 1.0, ("M2", "SQM", "SQ.M")),
)
UOM_CODES: tuple[str, ...] = tuple(u.code for u in UOMS)
_BY_CODE = {u.code: u for u in UOMS}
_ALIASES = {a: u.code for u in UOMS for a in u.aliases}


class UnitMismatch(ValueError):
    """A conversion between units of different dimensions (e.g. M -> EA)."""


def _get(code: str) -> Uom:
    try:
        return _BY_CODE[code]
    except KeyError:
        raise ValueError(f"unknown unit of measure {code!r}") from None


def dimension(code: str) -> str:
    return _get(code).dimension


def is_count(code: str) -> bool:
    return _get(code).dimension == "count"


def normalize_uom(text: str) -> str | None:
    """Import alias -> code (case-insensitive, trimmed, one trailing '.' ignored); None if unknown."""
    if text is None:
        return None
    t = str(text).strip().upper()
    if t.endswith(".") and t not in _ALIASES:
        t = t[:-1].strip()
    return _ALIASES.get(t)


def same_dimension(a: str, b: str) -> bool:
    return a in _BY_CODE and b in _BY_CODE and _BY_CODE[a].dimension == _BY_CODE[b].dimension


def convert(qty: float, from_uom: str, to_uom: str) -> float:
    if from_uom == to_uom:
        return qty
    a, b = _get(from_uom), _get(to_uom)
    if a.dimension != b.dimension:
        raise UnitMismatch(f"cannot convert {from_uom} ({a.dimension}) to {to_uom} ({b.dimension})")
    return qty * a.factor / b.factor
