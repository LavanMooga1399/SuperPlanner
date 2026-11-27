"""S&OP problem builder (M9-DESIGN 6.3, 6.4, 7): the baseline network at family x node x month, then the scenario's
typed change list applied on top. Node data is read per node inside its owner scope (`node_data`); everything after
that is pure (`build_problem`).

Baseline: consensus demand (the cycle's rows); nodes = plants and DCs; families of the demand; make where a plant
has made items of the family (hours / unit = demand-weighted mean of item hours / unit per cap group, M8 line rates
or routings); effective hours from the calendar (`base` windows); buy options from active item-suppliers of bought
items (landed cost, 8.4) and supplier sourcing rules; lanes with transit months = round(days / 30) for the families
the sourcing rules allow; initial stock and SS target = summed item stock / SS; conversion cost = std cost - material
roll-up (else std cost); money in the report currency (missing FX -> option dropped + `FX_MISSING`).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ..trade.fx import FxTable
from ..trade.landed import SupplierTerms, Tariff, landed
from . import curves
from .demand import add_months
from .model import SopBuy, SopLane, SopProblem

FIXED_KEYS = ("node", "dest_node", "source_node")


# ---------------------------------------------------------------- node data (DB, owner scope)

def node_data(s: Any, info: dict[str, Any], months: list[date]) -> dict[str, Any]:
    """Everything the S&OP builder needs from one node (bound owner scope)."""
    from sqlalchemy import func, select

    from ...api.mfg import repo
    from ...api.mfg.db_models import MfgLineRow
    from ...api.mfg.db_models_m2 import MfgInvBalanceRow, MfgItemSupplierRow, MfgLocationRow, MfgSupplierRow
    from ...api.mfg.db_models_m8 import MfgLineRateRow
    from ...api.mfg.db_models_m9 import MfgItemTradeRow
    from ..network.build import key_of
    from ..network.capacity import hours_per_unit

    ds = repo.load_dataset(s)
    items = {}
    for it in ds.items.values():
        if not getattr(it, "active", True):
            continue
        items[it.id] = {"id": it.id, "key": key_of(it), "family": it.family, "make_buy": it.make_buy,
                        "std_cost": float(it.standard_cost or 0.0), "ss": float(it.safety_stock or 0.0),
                        "part_number": it.part_number}
    stock = dict(s.execute(select(MfgInvBalanceRow.item_id, func.sum(MfgInvBalanceRow.qty_on_hand)).join(
        MfgLocationRow, MfgLocationRow.id == MfgInvBalanceRow.location_id).where(
        MfgLocationRow.kind.not_in(("quarantine", "scrap"))).group_by(MfgInvBalanceRow.item_id)).all())
    trade = {r.item_id: r for r in s.execute(select(MfgItemTradeRow)).scalars()}
    sup_codes = dict(s.execute(select(MfgSupplierRow.id, MfgSupplierRow.code)).all())
    isp = []
    for r in s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.active.is_(True))).scalars():
        tr = trade.get(r.item_id)
        isp.append({"item_id": r.item_id, "code": sup_codes.get(r.supplier_id, r.supplier_id),
                    "unit_price": r.unit_price, "currency": r.currency, "upu": r.units_per_purchase_unit or 1.0,
                    "coo": r.coo or (tr.coo if tr else None), "hts": r.hts_code or (tr.hts_code if tr else None),
                    "freight": r.freight_per_unit, "cap": r.cap_per_month, "preferred": r.preferred})
    material: dict[str, float] = {}
    for iid, boms in ds.boms_by_item.items():
        live = [b for b in boms if b.status == "released"] or boms
        if live and iid in items:
            material[iid] = sum(float(ln.qty_per) * items.get(ln.child_item_id, {}).get("std_cost", 0.0)
                                for ln in live[-1].lines)
    hours: dict[tuple[str, date], float] = defaultdict(float)
    hpu: dict[str, list[tuple[str, float]]] = {}
    if info["kind"] == "plant" and ds.lines:
        from ..calendar import line_windows
        from ..tz import plant_tz

        tz = plant_tz(ds.plant)
        if months:
            d0, d1 = months[0], add_months(months[-1], 1)
            for ln in ds.lines.values():
                g = ds.groups.get(ln.group_id)
                if g is None or not getattr(ln, "active", True):
                    continue
                par = max(int(getattr(ln, "parallel_capacity", 1) or 1), 1)
                for w in line_windows(ds, ln.id, d0, d1, kinds=("base",)):
                    m = w.start.astimezone(tz).date().replace(day=1)
                    hours[(g.code, m)] += (w.end - w.start).total_seconds() / 3600.0 * par
        rates = list(s.execute(select(MfgLineRateRow)).scalars())
        oee = dict(s.execute(select(MfgLineRow.id, MfgLineRow.oee)).all())
        for it in ds.items.values():
            if it.id in items and it.make_buy != "buy":
                h = hours_per_unit(ds, it, rates, oee)
                if h:
                    hpu[it.id] = h
    return {"info": info, "items": items, "stock": {k: float(v or 0.0) for k, v in stock.items()}, "isp": isp,
            "material": material, "hours": dict(hours), "hpu": hpu, "currency": ds.plant.currency or "USD",
            "country": info.get("country"), "workdays": tuple(sorted({"mon": 0, "tue": 1, "wed": 2, "thu": 3,
                                                                     "fri": 4, "sat": 5, "sun": 6}[d]
                                                                    for d in (ds.plant.mrp_workdays or [
                                                                        "mon", "tue", "wed", "thu", "fri"])))}


# ---------------------------------------------------------------- pure builder

def _node_ref(ref: str | None, nodes: dict[str, dict[str, Any]], virtual: dict[str, str]) -> str | None:
    if ref is None:
        return None
    if ref in nodes:
        return ref
    for oid, d in nodes.items():
        if d["info"]["code"] == ref:
            return oid
    return virtual.get(ref, ref if ref.startswith("new:") else None)


def build_problem(*, months: list[date], nodes: dict[str, dict[str, Any]], demand: dict[tuple[str, str, date], float],
                  orders: dict[tuple[str, str, date], float], lanes: list[dict[str, Any]], rules: list[dict[str, Any]],
                  settings: dict[str, Any], fx: FxTable, tariffs: list[Tariff], curves_by_code: dict[str, list[Any]],
                  milestones: list[dict[str, Any]], changes: list[dict[str, Any]], enforce: bool,
                  make_domestic: dict[tuple[str, str], float] | None = None) -> tuple[SopProblem, dict[str, Any]]:
    """-> (SopProblem, meta) where meta carries labels, capex, asp basis, rough-cut inputs and warnings."""
    rc = settings.get("report_currency", "USD")
    dom_country = settings.get("domestic_country", "US")
    m0 = months[0]
    warnings: list[dict[str, Any]] = []
    tariffs = list(tariffs)
    fx = FxTable([(f, t, m, x) for (f, t, m), x in fx.r.items()])
    # cost changes first (they feed landed costs)
    freight_pct: dict[str, float] = {}
    for ch in changes:
        if ch["kind"] != "cost_change":
            continue
        if ch.get("tariff"):
            keys = {(t["dest_country"], t["hts_prefix"], t.get("coo", "*"), t.get("layer", "mfn")) for t in ch["tariff"]}
            tariffs = [t for t in tariffs if (t.dest_country, t.hts_prefix, t.coo, t.layer) not in keys]
            tariffs += [Tariff(t["dest_country"], t["hts_prefix"], t.get("coo", "*"), t.get("layer", "mfn"),
                               float(t.get("rate_pct", 0)), t.get("per_unit"), t.get("per_unit_currency"),
                               _d(t["valid_from"]), _d(t.get("valid_to"))) for t in ch["tariff"]]
        if ch.get("fx"):
            f = ch["fx"]
            for m in months:
                if m >= _d(f["from_month"]):
                    fx.set(f["from"], f["to"], m, float(f["rate"]))
        if ch.get("freight"):
            freight_pct[ch["freight"]["lane"]] = float(ch["freight"]["pct"])

    def to_rc(amount: float | None, ccy: str) -> float | None:
        x, fl = fx.convert(amount, ccy, rc, m0)
        if x is None and amount is not None:
            warnings.append({"code": "FX_MISSING", "detail": {"from": ccy, "to": rc}})
        return x

    virtual: dict[str, str] = {}
    node_ids = sorted(nodes, key=lambda o: nodes[o]["info"]["code"])
    vnodes: dict[str, dict[str, Any]] = {}
    for ch in changes:
        if ch["kind"] == "add_node":
            vid = f"new:{ch['code']}"
            virtual[ch["code"]] = vid
            vnodes[vid] = {"code": ch["code"], "kind": ch.get("node_kind", "plant"), "country": ch["country"],
                           "currency": ch["currency"], "start": _d(ch["start"])}
    all_nodes = node_ids + sorted(vnodes)
    # demand changes
    dem = dict(demand)
    for ch in changes:
        if ch["kind"] != "demand_change":
            continue
        nd = _node_ref(ch.get("node"), nodes, virtual)
        a, b = _d(ch["from"]).replace(day=1), _d(ch.get("to")) or months[-1]
        for k in list(dem):
            if (nd is None or k[0] == nd) and (ch.get("family") in (None, k[1])) and a <= k[2] <= b:
                dem[k] = dem[k] * (1 + float(ch["pct"]) / 100.0)
    families = sorted({f for (_n, f, _t) in dem})
    # weights: orders before forecast
    weight = {k: 1.0 + (min(orders.get(k, 0.0), v) / v if v > 0 else 0.0) for k, v in dem.items()}
    # items by (node, family)
    fam_items: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for n in node_ids:
        for it in nodes[n]["items"].values():
            if it["family"] in families:
                fam_items[(n, it["family"])].append(it)
    std_cost, conv_cost, init_inv, ss_target = {}, {}, {}, {}
    make_allowed: set[tuple[str, str]] = set()
    hpu: dict[tuple[str, str, str], float] = {}
    hours: dict[tuple[str, str, date], float] = defaultdict(float)
    for n in node_ids:
        nd = nodes[n]
        ccy = nd["currency"]
        for g_m, h in nd["hours"].items():
            g, m = g_m
            if m in set(months):
                hours[(n, g, m)] += h
        for f in families:
            its = fam_items.get((n, f), [])
            if not its:
                continue
            sc = sum(i["std_cost"] for i in its) / len(its)
            std_cost[(n, f)] = to_rc(sc, ccy) or 0.0
            init_inv[(n, f)] = sum(nd["stock"].get(i["id"], 0.0) for i in its)
            ss_target[(n, f)] = sum(i["ss"] for i in its)
            made = [i for i in its if i["make_buy"] != "buy"]
            if made and nd["info"]["kind"] == "plant":
                make_allowed.add((n, f))
                cc = [max(i["std_cost"] - nd["material"].get(i["id"], 0.0), 0.0) or i["std_cost"] for i in made]
                conv_cost[(n, f)] = to_rc(sum(cc) / len(cc), ccy) or 0.0
                acc: dict[str, list[float]] = defaultdict(list)
                for i in made:
                    for g, h in nd["hpu"].get(i["id"], []):
                        acc[g].append(h)
                for g, hs in acc.items():
                    hpu[(n, g, f)] = sum(hs) / len(hs)
    # buy options
    buys: list[SopBuy] = []
    duty_info: dict[tuple[str, str, str], dict[str, Any]] = {}
    sup_rules = {(r["dest"], r["family"], r["supplier_code"]) for r in rules if r["source_kind"] == "supplier"}

    def add_buy(n: str, f: str, code: str, rows: list[dict[str, Any]]) -> None:
        nd = nodes[n]
        tot, cnt, cap, coos, flags = 0.0, 0, 0.0, set(), set()
        duty = 0.0
        for row in rows:
            lc = landed(SupplierTerms(row["unit_price"], row["currency"], row["upu"], row["coo"], row["hts"],
                                      row["freight"]), nd["country"], nd["currency"], m0, fx, tariffs,
                        duty_base=settings.get("duty_base"), other_cost_pct=float(settings.get("other_cost_pct", 0.5)))
            flags |= set(lc["flags"])
            if lc["total"] is None:
                continue
            tot += lc["total"]
            duty += sum(d["amount"] or 0 for d in lc["duty"])
            cnt += 1
            cap = cap + row["cap"] if (cap is not None and row["cap"] is not None) else None
            coos.add(row["coo"])
        if not cnt:
            warnings.append({"code": "SOP_BUY_NO_COST", "node": n, "family": f, "detail": {"supplier": code,
                                                                                         "flags": sorted(flags)}})
            return
        unit = to_rc(tot / cnt, nd["currency"])
        if unit is None:
            return
        dom = sum(1 for c in coos if c == dom_country) / len(coos) if coos else 0.0
        buys.append(SopBuy(n, f, code, unit, cap or None, domestic=dom))
        duty_info[(n, f, code)] = {"coo": sorted(c for c in coos if c)[0] if any(coos) else None,
                                   "duty_share": round((duty / cnt) / (tot / cnt), 4) if tot else None}

    for n in node_ids:
        nd = nodes[n]
        by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in nd["isp"]:
            it = nd["items"].get(row["item_id"])
            if it is None or it["family"] not in families:
                continue
            if it["make_buy"] == "buy" or (n, it["family"], row["code"]) in sup_rules:
                by[(it["family"], row["code"])].append(row)
        for (f, code), rows in sorted(by.items()):
            add_buy(n, f, code, rows)
    # lanes and the families each may carry
    lane_fams: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rules:
        if r["source_kind"] == "plant" and r["source"]:
            if r["family"]:
                lane_fams[(r["source"], r["dest"])].add(r["family"])
            elif r["key"]:
                for it in nodes.get(r["dest"], {}).get("items", {}).values():
                    if it["key"] == r["key"] and it["family"]:
                        lane_fams[(r["source"], r["dest"])].add(it["family"])
    sop_lanes: dict[str, SopLane] = {}
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for ln in lanes:
        if not ln["active"]:
            continue
        k = (ln["src"], ln["dst"])
        if k not in best or ln["transit_days"] < best[k]["transit_days"]:
            best[k] = ln
    for (a, b), ln in sorted(best.items()):
        fr = to_rc(ln["freight_per_unit"], ln["currency"]) or 0.0
        fr *= 1 + freight_pct.get(ln["id"], 0.0) / 100.0
        fams = lane_fams.get((a, b), set())
        if fams:
            sop_lanes[ln["id"]] = SopLane(ln["id"], a, b, round(ln["transit_days"] / 30), fr, frozenset(fams))
    ship_shares: dict[tuple[str, str], list[tuple[str, float, float]]] = {}
    capex: list[tuple[date, float]] = []
    fixed = 0.0
    added: dict[tuple[str, str, date], list[float]] = defaultdict(list)       # ramp factors for the rough-cut
    for ch in changes:
        k = ch["kind"]
        if k == "add_node":
            vid = virtual[ch["code"]]
            for i, lnd in enumerate(ch.get("lanes", [])):
                other = _node_ref(lnd.get("from") or lnd.get("to"), nodes, virtual)
                if other is None:
                    warnings.append({"code": "SOP_UNKNOWN_NODE", "detail": {"ref": lnd.get("from") or lnd.get("to")}})
                    continue
                a, b = (other, vid) if lnd.get("from") else (vid, other)
                lid = f"{vid}:{i}"
                fr = to_rc(float(lnd.get("freight_per_unit", 0.0)), rc) or 0.0
                sop_lanes[lid] = SopLane(lid, a, b, round(int(lnd["transit_days"]) / 30), fr, None)
        elif k == "add_line":
            n = _node_ref(ch["node"], nodes, virtual)
            if n is None:
                warnings.append({"code": "SOP_UNKNOWN_NODE", "detail": {"ref": ch["node"]}})
                continue
            start = _d(ch["start"])
            pts = ch.get("points") or curves_by_code.get(ch.get("curve") or "", None)
            if ch.get("curve") and not ch.get("points") and pts is None:
                warnings.append({"code": "SOP_UNKNOWN_CURVE", "detail": {"curve": ch["curve"]}})
            line_hpu = dict(ch.get("hpu_by_family") or {})
            for f, uph in (ch.get("uph_by_family") or {}).items():
                line_hpu.setdefault(f, 1.0 / (float(uph) * float(ch.get("oee") or 1.0)))
            g = ch["cap_group"]
            wd = nodes[n]["workdays"] if n in nodes else curves.WORKDAYS
            for m in months:
                fac = curves.month_factor(pts, start, m, wd)
                added[(n, g, m)].append(fac)
                h = curves.month_hours(float(ch["hours_per_week"]), m, wd) * fac
                if h <= 0:
                    continue
                # group-equivalent hours: line hours x (group hpu / line hpu), mean over the line's families
                ratios = [hpu[(n, g, f)] / lh for f, lh in line_hpu.items() if (n, g, f) in hpu and lh > 0]
                hours[(n, g, m)] += h * (sum(ratios) / len(ratios) if ratios else 1.0)
                if m >= start.replace(day=1) and ch.get("fixed_cost_per_month"):
                    fixed += float(ch["fixed_cost_per_month"])
            for f, lh in line_hpu.items():
                if f in families and (n, g, f) not in hpu:
                    hpu[(n, g, f)] = lh
                    make_allowed.add((n, f))
                    conv_cost.setdefault((n, f), std_cost.get((n, f), 0.0) or next(
                        (v for (nn, ff), v in std_cost.items() if ff == f), 0.0))
                    std_cost.setdefault((n, f), conv_cost[(n, f)])
            if ch.get("capex"):
                amt = to_rc(float(ch["capex"]), ch.get("capex_currency") or rc)
                if amt is not None:
                    capex.append((max(start.replace(day=1), m0), amt))
        elif k == "capacity_change":
            n = _node_ref(ch["node"], nodes, virtual)
            a, b = _d(ch["from"]).replace(day=1), _d(ch.get("to"))
            for (nn, g, m) in list(hours):
                if nn == n and g == ch["cap_group"] and m >= a and (b is None or m <= b):
                    hours[(nn, g, m)] *= max(0.0, 1 + float(ch["pct"]) / 100.0)
        elif k == "sourcing":
            dest = _node_ref(ch["dest_node"], nodes, virtual)
            f = ch["family"]
            rows = []
            for src in ch["sources"]:
                if src.get("source_node"):
                    sn = _node_ref(src["source_node"], nodes, virtual)
                    lane = next((ln for ln in sop_lanes.values() if ln.src == sn and ln.dst == dest), None)
                    if lane is None:
                        base = best.get((sn, dest))
                        if base is None:
                            warnings.append({"code": "NET_NO_LANE", "detail": {"from": sn, "to": dest}})
                            continue
                        fr = to_rc(base["freight_per_unit"], base["currency"]) or 0.0
                        lane = SopLane(base["id"], sn, dest, round(base["transit_days"] / 30), fr, frozenset())
                    sop_lanes[lane.id] = SopLane(lane.id, lane.src, lane.dst, lane.transit_months,
                                                 lane.freight_per_unit, (lane.families or frozenset()) | {f})
                    rows.append((lane.id, float(src.get("min_share", 0)), float(src.get("max_share", 1))))
                else:
                    code = src.get("supplier_code") or src.get("code")
                    _shares(buys, dest, f, code, src, warnings)
            if rows:
                ship_shares[(dest, f)] = rows
        elif k == "make_vs_buy":
            n = _node_ref(ch["node"], nodes, virtual)
            f = ch["family"]
            if ch["option"] == "buy":
                make_allowed.discard((n, f))
            if ch["option"] == "make":
                buys[:] = [b for b in buys if not (b.node == n and b.family == f)]
            if ch["option"] in ("buy", "both") and ch.get("supplier"):
                sp = ch["supplier"]
                add_buy_change(buys, duty_info, n, f, sp, nodes, settings, fx, tariffs, m0, rc, dom_country, warnings)
        elif k == "supplier_allocation":
            n = _node_ref(ch["node"], nodes, virtual)
            for row in ch["suppliers"]:
                _shares(buys, n, ch["family"], row.get("code") or row.get("supplier_code"), row, warnings)
    for vid in vnodes:
        all_nodes = all_nodes  # virtual nodes take part through their lanes and lines
    md = dict(make_domestic or {})
    for (n, f) in make_allowed:
        country = nodes[n]["country"] if n in nodes else vnodes.get(n, {}).get("country")
        md.setdefault((n, f), 1.0 if country == dom_country else 0.0)
    ms = []
    if enforce:
        for m in milestones:
            if m.get("family") in families:
                ms.append({"family": m["family"], "min_share": float(m["rule"]["min_pct"]) / 100.0})
    p = SopProblem(months=months, nodes=all_nodes, families=families, demand={k: v for k, v in dem.items() if v > 0},
                   priority_weight=weight, init_inv=init_inv, ss_target=ss_target, hours=dict(hours), hpu=hpu,
                   make_allowed=frozenset(make_allowed), conv_cost=conv_cost, std_cost=std_cost, buys=buys,
                   lanes=list(sop_lanes.values()), holding_rate=float(settings.get("holding_rate_pct", 20)) / 100.0,
                   fixed_cost=fixed, make_domestic=md, milestones=ms, ship_shares=ship_shares)
    labels = {n: nodes[n]["info"]["code"] for n in node_ids} | {v: d["code"] for v, d in vnodes.items()}
    meta = {"labels": labels, "capex": [(m.isoformat(), a) for m, a in capex], "warnings": _dedupe(warnings),
            "ramp": {f"{n}|{g}|{m.isoformat()}": sum(v) / len(v) for (n, g, m), v in added.items()},
            "duty": {f"{n}|{f}|{c}": v for (n, f, c), v in duty_info.items()}, "currency": rc}
    return p, meta


def add_buy_change(buys: list[SopBuy], duty_info: dict[Any, Any], n: str, f: str, sp: dict[str, Any],
                   nodes: dict[str, Any], settings: dict[str, Any], fx: FxTable, tariffs: list[Tariff], m0: date,
                   rc: str, dom_country: str, warnings: list[dict[str, Any]]) -> None:
    nd = nodes.get(n)
    country = nd["country"] if nd else None
    ccy = nd["currency"] if nd else rc
    lc = landed(SupplierTerms(float(sp["unit_price"]), sp["currency"], 1.0, sp.get("coo"), sp.get("hts_code"),
                              sp.get("freight_per_unit")), country, ccy, m0, fx, tariffs,
                duty_base=settings.get("duty_base"), other_cost_pct=float(settings.get("other_cost_pct", 0.5)))
    if lc["total"] is None:
        warnings.append({"code": "FX_MISSING", "node": n, "family": f, "detail": {"supplier": sp["code"]}})
        return
    unit, _fl = fx.convert(lc["total"], ccy, rc, m0)
    if unit is None:
        warnings.append({"code": "FX_MISSING", "node": n, "family": f, "detail": {"supplier": sp["code"]}})
        return
    buys[:] = [b for b in buys if not (b.node == n and b.family == f and b.code == sp["code"])]
    buys.append(SopBuy(n, f, sp["code"], unit, sp.get("cap_per_month"),
                       domestic=1.0 if sp.get("coo") == dom_country else 0.0))
    duty = sum(d["amount"] or 0 for d in lc["duty"])
    duty_info[(n, f, sp["code"])] = {"coo": sp.get("coo"), "duty_share": round(duty / lc["total"], 4)
                                     if lc["total"] else None}


def _shares(buys: list[SopBuy], n: str | None, f: str, code: str | None, row: dict[str, Any],
            warnings: list[dict[str, Any]]) -> None:
    for i, b in enumerate(buys):
        if b.node == n and b.family == f and b.code == code:
            cap = row.get("cap_per_month", b.cap_per_month)
            buys[i] = SopBuy(b.node, b.family, b.code, b.landed, cap if cap is not None else b.cap_per_month,
                             float(row.get("min_share", 0)), float(row.get("max_share", 1)), b.domestic)
            return
    warnings.append({"code": "SOP_UNKNOWN_SUPPLIER", "node": n, "family": f, "detail": {"supplier": code}})


def _dedupe(ws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for w in ws:
        k = repr(sorted(w.items(), key=lambda x: x[0]))
        if k not in seen:
            seen.add(k)
            out.append(w)
    return out[:200]


def _d(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def rough_cut(p: SopProblem, plan_make: dict[tuple[str, str, date], float], rules_primary: dict[tuple[str, str], str],
              ramp: dict[str, float]) -> list[dict[str, Any]]:
    """Per node x cap group x month: available, required (consensus routed to the making node: itself, else its
    primary plant source), planned (LP), utilisation (required / available), mean ramp factor of added lines."""
    required: dict[tuple[str, str, date], float] = defaultdict(float)
    for (n, f, t), q in p.demand.items():
        maker = n if (n, f) in p.make_allowed else rules_primary.get((n, f))
        if maker is None or (maker, f) not in p.make_allowed:
            continue
        for (nn, g, ff), h in p.hpu.items():
            if nn == maker and ff == f:
                required[(maker, g, t)] += q * h
    planned: dict[tuple[str, str, date], float] = defaultdict(float)
    for (n, f, t), q in plan_make.items():
        for (nn, g, ff), h in p.hpu.items():
            if nn == n and ff == f:
                planned[(n, g, t)] += q * h
    keys = {(n, g) for (n, g, _f) in p.hpu}
    out = []
    for n, g in sorted(keys):
        for t in p.months:
            av = p.hours.get((n, g, t), 0.0)
            req = required.get((n, g, t), 0.0)
            out.append({"node_owner_id": n, "cap_group": g, "month": t, "available": round(av, 2),
                        "required": round(req, 2), "planned": round(planned.get((n, g, t), 0.0), 2),
                        "util": round(req / av, 4) if av > 0 else None,
                        "factor": ramp.get(f"{n}|{g}|{t.isoformat()}")})
    return out
