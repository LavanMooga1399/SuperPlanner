"""S&OP financial view and KPIs (M9-DESIGN 6.5), all in the report currency.

Per node x family x month: revenue = delivered x asp; COGS = make x std_cost + buy x landed + freight (shipments x
lane freight); gross margin, GM %; inventory value = inv x std_cost; days of cover = inventory / (consensus / 30);
capex by the start month of the change. KPIs per horizon / calendar year / next 3 months: service % (delivered /
consensus), unmet units, revenue, COGS, margin, inventory value, cover, capex; utilisation max / avg per cap group;
domestic share per milestone family."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from .model import SopProblem, SopResult


def _r(x: float | None, n: int = 2) -> float | None:
    return None if x is None else round(x, n)


def cells(p: SopProblem, r: SopResult, asp: dict[tuple[str, str], float | None], capex: list[tuple[date, float]]
          ) -> list[dict[str, Any]]:
    lanes = {ln.id: ln for ln in p.lanes}
    landed = {(b.node, b.family, b.code): (b.landed or 0.0) for b in p.buys}
    buy_cost: dict[tuple[str, str, date], float] = defaultdict(float)
    for (n, f, c, t), q in r.buy.items():
        buy_cost[(n, f, t)] += q * landed.get((n, f, c), 0.0)
    freight: dict[tuple[str, str, date], float] = defaultdict(float)
    for (lid, f, t), q in r.ship.items():
        freight[(lanes[lid].src, f, t)] += q * lanes[lid].freight_per_unit
    out = []
    for n in p.nodes:
        for f in p.families:
            sc = p.std_cost.get((n, f), 0.0)
            a = asp.get((n, f))
            for t in p.months:
                d = p.demand.get((n, f, t), 0.0)
                delivered = d - r.unmet.get((n, f, t), 0.0)
                make = r.make.get((n, f, t), 0.0)
                inv = r.inv.get((n, f, t), 0.0)
                if not (d or make or inv or buy_cost.get((n, f, t)) or freight.get((n, f, t))):
                    continue
                rev = delivered * a if a is not None else None
                cogs = make * sc + buy_cost.get((n, f, t), 0.0) + freight.get((n, f, t), 0.0)
                out.append({"node": n, "family": f, "month": t, "consensus": d, "delivered": delivered,
                            "revenue": rev, "cogs": cogs, "freight": freight.get((n, f, t), 0.0),
                            "inventory_value": inv * sc, "inv_units": inv})
    for t, amt in capex:
        out.append({"node": "*", "family": "*", "month": t, "consensus": 0.0, "delivered": 0.0, "revenue": 0.0,
                    "cogs": 0.0, "freight": 0.0, "inventory_value": 0.0, "inv_units": 0.0, "capex": amt})
    return out


def fold(rows: list[dict[str, Any]], key: str, month: date | None, last_month: date | None) -> dict[str, Any]:
    rev = sum(x["revenue"] or 0.0 for x in rows)
    has_rev = any(x["revenue"] is not None for x in rows)
    cogs = sum(x["cogs"] for x in rows)
    inv_rows = [x for x in rows if last_month is None or x["month"] == last_month]
    inv = sum(x["inventory_value"] for x in inv_rows)
    units = sum(x["inv_units"] for x in inv_rows)
    cons_m = sum(x["consensus"] for x in inv_rows)
    gm = rev - cogs if has_rev else None
    return {"key": key, "month": month, "revenue": _r(rev) if has_rev else None, "cogs": _r(cogs),
            "freight": _r(sum(x["freight"] for x in rows)), "gross_margin": _r(gm),
            "gm_pct": _r(gm / rev * 100, 2) if gm is not None and rev else None, "inventory_value": _r(inv),
            "days_of_cover": _r(units / (cons_m / 30.0), 1) if cons_m > 0 else None,
            "capex": _r(sum(x.get("capex", 0.0) for x in rows)) or 0.0}


def view(p: SopProblem, rows: list[dict[str, Any]], group_by: str) -> dict[str, Any]:
    months = list(p.months)
    keyf = {"total": lambda x: "total", "node": lambda x: x["node"], "family": lambda x: x["family"]}[group_by]
    groups: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for x in rows:
        k = keyf(x)
        if k == "*" and group_by != "total":
            k = "capex"
        groups[(k, x["month"])].append(x)
    out = [fold(v, k, m, m) for (k, m), v in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1]))]
    return {"rows": out, "totals": totals(rows, months)}


def periods(months: list[date]) -> dict[str, list[date]]:
    return {"horizon": months, "year": [m for m in months if m.year == months[0].year], "next3": months[:3]}


def totals(rows: list[dict[str, Any]], months: list[date]) -> dict[str, Any]:
    out = {}
    for name, ms in periods(months).items():
        sel = [x for x in rows if x["month"] in set(ms)]
        out[name] = fold(sel, "total", None, ms[-1] if ms else None)
    return out


def kpis(p: SopProblem, r: SopResult, rows: list[dict[str, Any]], currency: str,
         milestones: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    months = list(p.months)
    tot = totals(rows, months)
    out: dict[str, Any] = {"currency": currency}
    for name, ms in periods(months).items():
        mset = set(ms)
        cons = sum(v for (n, f, t), v in p.demand.items() if t in mset)
        unmet = sum(v for (n, f, t), v in r.unmet.items() if t in mset)
        t = tot[name]
        out[name] = {"delivered_units": round(cons - unmet, 3), "consensus_units": round(cons, 3),
                     "unmet_units": round(unmet, 3), "service_pct": round((cons - unmet) / cons * 100, 2) if cons
                     else None, "revenue": t["revenue"], "cogs": t["cogs"], "gross_margin": t["gross_margin"],
                     "gm_pct": t["gm_pct"], "inventory_value": t["inventory_value"],
                     "days_of_cover": t["days_of_cover"], "capex": t["capex"]}
    util = []
    groups: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for (n, g, f), h in p.hpu.items():
        groups[(n, g)].append((f, h))
    for (n, g), fh in sorted(groups.items()):
        pct = []
        for t in months:
            av = p.hours.get((n, g, t), 0.0)
            used = sum(r.make.get((n, f, t), 0.0) * h for f, h in fh)
            if av > 0:
                pct.append(used / av * 100)
        if pct:
            util.append({"node": n, "cap_group": g, "max_pct": round(max(pct), 1),
                         "avg_pct": round(sum(pct) / len(pct), 1)})
    out["utilisation"] = util
    dom = []
    for m in milestones or []:
        f = m.get("family")
        num = den = 0.0
        first_missed = None
        by_month: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for (n, ff, t), q in r.make.items():
            if ff == f:
                by_month[t][0] += q * p.make_domestic.get((n, f), 0.0)
                by_month[t][1] += q
        for b in p.buys:
            if b.family != f:
                continue
            for t in months:
                q = r.buy.get((b.node, f, b.code, t), 0.0)
                by_month[t][0] += q * b.domestic
                by_month[t][1] += q
        for t in sorted(by_month):
            a, d = by_month[t]
            num += a
            den += d
            if d > 0 and t >= m.get("effective", months[0]) and a / d * 100 < float(m["min_pct"]) - 1e-6 \
                    and first_missed is None:
                first_missed = t
        dom.append({"milestone_id": m["id"], "code": m["code"], "family": f, "min_pct": m["min_pct"],
                    "share_pct": round(num / den * 100, 2) if den else None, "first_missed_month": first_missed})
    out["domestic"] = dom
    return out


def delta(base: dict[str, Any] | None, other: dict[str, Any] | None) -> dict[str, Any] | None:
    if base is None or other is None:
        return None
    out = {}
    for per in ("horizon", "year", "next3"):
        a, b = base.get(per) or {}, other.get(per) or {}
        out[per] = {k: (round(b[k] - a[k], 4) if isinstance(a.get(k), (int, float)) and isinstance(
            b.get(k), (int, float)) else None) for k in b}
    return out
