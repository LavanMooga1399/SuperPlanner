"""S&OP demand review (M9-DESIGN 6.2): family x node x month rows, overrides, item disaggregation (pure).

- Rows: `stat_qty` = sum of item forecast finals; `order_qty` = open customer orders; `base_qty` = sum over items of
  max(order, stat) per item-month (consumption).
- Overrides in `seq`: node pct scales; node abs sets; all-nodes pct scales every node; all-nodes abs splits the
  value by base share (equal split when every base is 0). Result = consensus.
- Disaggregation (publish): an item's quantity = family consensus x its final share; stat 0 -> 12-month history
  share; neither -> `SOP_DISAGG_NONE`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable

Key = tuple[str, str, date]      # (node, family, month)


def months_between(a: date, b: date) -> list[date]:
    out, m = [], a.replace(day=1)
    while m <= b:
        out.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


def add_months(m: date, k: int) -> date:
    y, mo = m.year, m.month - 1 + k
    return date(y + mo // 12, mo % 12 + 1, 1)


def aggregate(item_rows: Iterable[dict[str, Any]]) -> dict[Key, dict[str, Any]]:
    """item_rows: {node, family, item_key, month, stat, order} -> rows with per-item basis in `items`."""
    out: dict[Key, dict[str, Any]] = {}
    for r in item_rows:
        k = (r["node"], r["family"], r["month"])
        row = out.setdefault(k, {"stat_qty": 0.0, "order_qty": 0.0, "base_qty": 0.0, "items": {}})
        stat, order = float(r.get("stat") or 0.0), float(r.get("order") or 0.0)
        it = row["items"].setdefault(r["item_key"], {"stat": 0.0, "order": 0.0, "base": 0.0})
        it["stat"] += stat
        it["order"] += order
    for row in out.values():
        for it in row["items"].values():
            it["base"] = max(it["stat"], it["order"])
            row["stat_qty"] += it["stat"]
            row["order_qty"] += it["order"]
            row["base_qty"] += it["base"]
    return out


def apply_overrides(base: dict[Key, float], overrides: Iterable[Any]) -> dict[Key, float]:
    """Consensus from base quantities and overrides (objects/dicts with node_owner_id, family, month_from, month_to,
    mode, value, seq), applied in `seq`."""
    cons = dict(base)

    def g(o: Any, k: str) -> Any:
        return o[k] if isinstance(o, dict) else getattr(o, k)

    for o in sorted(overrides, key=lambda o: g(o, "seq")):
        fam, node, mode, val = g(o, "family"), g(o, "node_owner_id"), g(o, "mode"), float(g(o, "value"))
        for m in months_between(g(o, "month_from"), g(o, "month_to")):
            keys = sorted(k for k in cons if k[1] == fam and k[2] == m and (node is None or k[0] == node))
            if node is not None and not keys:
                keys = [(node, fam, m)]
                cons[keys[0]] = 0.0
            if mode == "pct":
                for k in keys:
                    cons[k] = cons[k] * (1 + val / 100.0)
            elif node is not None:
                cons[keys[0]] = val
            else:
                tot = sum(base.get(k, 0.0) for k in keys)
                for k in keys:
                    share = base.get(k, 0.0) / tot if tot > 0 else 1.0 / len(keys)
                    cons[k] = val * share
    return {k: round(v, 6) for k, v in cons.items()}


def disaggregate(consensus: float, finals: dict[str, float], history: dict[str, float] | None = None
                 ) -> tuple[dict[str, float], str | None]:
    """Item quantities for one family-month: pro rata to item finals; stat 0 -> history share; else none."""
    tot = sum(v for v in finals.values() if v > 0)
    if tot > 0:
        return {k: round(consensus * v / tot, 6) for k, v in finals.items() if v > 0}, None
    h = {k: v for k, v in (history or {}).items() if v > 0}
    ht = sum(h.values())
    if ht > 0:
        return {k: round(consensus * v / ht, 6) for k, v in h.items()}, None
    return {}, "SOP_DISAGG_NONE"


def content_hash_table(rows: Iterable[dict[str, Any]]) -> str:
    import hashlib
    import json

    canon = sorted((r["node_owner_id"], r["family"], str(r["month"]), round(float(r["consensus_qty"]), 3))
                   for r in rows)
    return hashlib.sha256(json.dumps(canon).encode()).hexdigest()


def by_family_month(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, date], float]:
    out: dict[tuple[str, date], float] = defaultdict(float)
    for r in rows:
        out[(r["family"], r["month"])] += r["consensus_qty"]
    return out
