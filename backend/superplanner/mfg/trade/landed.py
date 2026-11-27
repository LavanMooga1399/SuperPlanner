"""Landed cost (M9-DESIGN 8.4): one pure function used by item-supplier lists, make-vs-buy and the S&OP LP.

Per base unit in the destination plant's currency: price = unit_price / units_per_purchase_unit x fx; freight =
`freight_per_unit` (plant currency per base unit; missing -> 0 + `FREIGHT_MISSING`); customs value = price (FOB) or
price + freight (CIF per `duty_base[dest]`, else `duty_base["*"]`); duty per layer = the longest `hts_prefix` match,
COO exact before `*`, valid in the month: rate_pct x customs value + per_unit x fx; COO == destination country ->
no duty; no HTS -> 0 + `HTS_MISSING`; other = `other_cost_pct` x customs value; total = sum. Missing FX -> the
amounts that need it and `total` are `None` + `FX_MISSING` (never a silent 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from .fx import FxTable


@dataclass(frozen=True)
class Tariff:
    dest_country: str
    hts_prefix: str
    coo: str                    # 2 letters or "*"
    layer: str
    rate_pct: float
    per_unit: float | None
    per_unit_currency: str | None
    valid_from: date
    valid_to: date | None


@dataclass(frozen=True)
class SupplierTerms:
    unit_price: float | None
    currency: str
    units_per_purchase_unit: float = 1.0
    coo: str | None = None
    hts_code: str | None = None
    freight_per_unit: float | None = None


def duty_layers(tariffs: Iterable[Tariff], dest: str, hts: str, coo: str | None, month: date) -> list[Tariff]:
    """Per layer: the longest matching prefix, COO exact before `*`, valid in the month."""
    end = _month_end(month)
    best: dict[str, tuple[tuple[int, int], Tariff]] = {}
    for t in tariffs:
        if t.dest_country != dest or not hts.startswith(t.hts_prefix):
            continue
        if t.coo not in ("*", coo):
            continue
        if t.valid_from > end or (t.valid_to is not None and t.valid_to < month.replace(day=1)):
            continue
        rank = (len(t.hts_prefix), 1 if t.coo == coo else 0)
        cur = best.get(t.layer)
        if cur is None or rank > cur[0] or (rank == cur[0] and t.valid_from > cur[1].valid_from):
            best[t.layer] = (rank, t)
    return [best[k][1] for k in sorted(best)]


def _month_end(m: date) -> date:
    from calendar import monthrange

    return m.replace(day=monthrange(m.year, m.month)[1])


def r6(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def landed(terms: SupplierTerms, dest_country: str | None, dest_currency: str, month: date, fx: FxTable,
           tariffs: Iterable[Tariff], *, duty_base: dict[str, str] | None = None, other_cost_pct: float = 0.5,
           item_hts: str | None = None, item_coo: str | None = None) -> dict[str, Any]:
    flags: list[str] = []
    rate, fl = fx.rate(terms.currency, dest_currency, month)
    flags += fl
    upu = terms.units_per_purchase_unit or 1.0
    price = None if (rate is None or terms.unit_price is None) else terms.unit_price / upu * rate
    if terms.unit_price is None:
        flags.append("PRICE_MISSING")
    if terms.freight_per_unit is None:
        freight = 0.0
        flags.append("FREIGHT_MISSING")
    else:
        freight = float(terms.freight_per_unit)
    base = (duty_base or {"*": "fob"})
    mode = base.get(dest_country or "", base.get("*", "fob"))
    customs = None if price is None else (price + freight if mode == "cif" else price)
    coo = terms.coo or item_coo
    hts = terms.hts_code or item_hts
    duty: list[dict[str, Any]] = []
    duty_missing = False
    if coo is None:
        flags.append("TRADE_COO_MISSING")
    if not hts:
        flags.append("HTS_MISSING")
    elif dest_country and coo != dest_country:
        for t in duty_layers(tariffs, dest_country, hts, coo, month):
            amount = None if customs is None else customs * t.rate_pct / 100.0
            if t.per_unit:
                pr, f2 = fx.rate(t.per_unit_currency or dest_currency, dest_currency, month)
                flags += f2
                if pr is None or amount is None:
                    amount, duty_missing = None, True
                else:
                    amount += t.per_unit * pr
            duty.append({"layer": t.layer, "rate_pct": t.rate_pct, "per_unit": t.per_unit, "amount": r6(amount)})
    other = None if customs is None else customs * other_cost_pct / 100.0
    if not dest_country:                       # review M4: duty cannot be decided without the plant country
        flags.append("COUNTRY_MISSING")
        duty_missing = True
    total = None
    if price is not None and not duty_missing and all(d["amount"] is not None for d in duty):
        total = price + freight + sum(d["amount"] for d in duty) + (other or 0.0)
    return {"unit_price": r6(price), "freight": r6(freight), "customs_value": r6(customs), "duty": duty,
            "other": r6(other), "total": r6(total), "currency": dest_currency, "fx_rate": r6(rate),
            "flags": sorted(set(flags))}
