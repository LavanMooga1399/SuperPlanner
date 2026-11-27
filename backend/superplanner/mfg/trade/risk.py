"""Supplier risk (M9-DESIGN 7), pure. Score 0-100 per item-supplier: single source (the only active supplier of an
item with 12-month spend) 35; country risk 0-25; lead time > 60 d 15; on-time delivery < 90 % 15, < 95 % 8; tariff
exposure (duty >= 10 % or non-domestic COO in a milestone family) 10. Flags `single_source`, `sole_country`.
Dual-sourcing suggestions for score >= 50 within the top 80 % of spend: suppliers of the organisation already
supplying the same family or HTS heading (4 digits), ranked by landed-cost delta then their own score."""

from __future__ import annotations

from typing import Any


def score(row: dict[str, Any], *, n_suppliers: int, countries: set[str | None], country_risk: dict[str, int],
          domestic: str, milestone_families: set[str]) -> dict[str, Any]:
    single = n_suppliers == 1 and (row.get("spend_12m") or 0) > 0
    parts = {"single_source": 35 if single else 0,
             "country": int(country_risk.get(row.get("coo") or "", 0)),
             "lead_time": 15 if (row.get("lead_days") or 0) > 60 else 0,
             "otd": 0 if row.get("otd_pct") is None else (15 if row["otd_pct"] < 90 else (8 if row["otd_pct"] < 95
                                                                                          else 0)),
             "tariff": 10 if ((row.get("duty_pct") or 0) >= 10 or (row.get("coo") not in (None, domestic)
                                                                   and row.get("family") in milestone_families))
             else 0}
    flags = []
    if single:
        flags.append("single_source")
    if n_suppliers > 1 and len({c for c in countries if c}) == 1:
        flags.append("sole_country")
    return {"score": min(sum(parts.values()), 100), "parts": parts, "flags": flags}


def top_spend(rows: list[dict[str, Any]], pct: float = 0.8) -> set[int]:
    """Indexes of the rows inside the top `pct` of spend (cumulative, largest first)."""
    order = sorted(range(len(rows)), key=lambda i: -(rows[i].get("spend_12m") or 0))
    total = sum(r.get("spend_12m") or 0 for r in rows)
    out, acc = set(), 0.0
    for i in order:
        if total <= 0 or acc >= pct * total:
            break
        out.add(i)
        acc += rows[i].get("spend_12m") or 0
    return out


def suggestions(row: dict[str, Any], candidates: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    out = []
    for c in candidates:
        if c["supplier_code"] == row["supplier_code"]:
            continue
        basis = "family" if row.get("family") and c.get("family") == row.get("family") else (
            "heading" if row.get("hts") and c.get("hts") and c["hts"][:4] == row["hts"][:4] else None)
        if basis is None:
            continue
        delta = None if c.get("landed") is None or row.get("landed") is None else round(c["landed"] - row["landed"],
                                                                                         6)
        out.append({"supplier_code": c["supplier_code"], "supplier_name": c.get("supplier_name", c["supplier_code"]),
                    "node_owner_id": c["node_owner_id"], "coo": c.get("coo"), "landed_delta": delta,
                    "score": c.get("score"), "basis": basis})
    best: dict[str, dict[str, Any]] = {}
    for s in sorted(out, key=lambda s: (s["landed_delta"] is None, s["landed_delta"] or 0, s["score"] or 0)):
        best.setdefault(s["supplier_code"], s)
    return list(best.values())[:limit]
