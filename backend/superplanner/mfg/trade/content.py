"""Domestic content (M9-DESIGN 8.2, 8.3), pure.

Lot roll-up over a genealogy subgraph: the inputs of a made lot L are the trace edges into its WO - lot -> WO
(`exact`, qty) and item_stock -> WO (`possible`; item trade COO and std cost; marks the result `estimated`) -
attributed pro rata to L's share of the WO output. Per input: value = qty x unit_value (else std cost), weight =
qty x unit_weight_kg; domestic indicator = the input's own share if it is a made lot (recursion, memoised, depth <=
30), else 1 if its COO is the domestic country, else 0. `material_classes` keeps only inputs of those classes
(recursing into made lots under the same filter); `include_conversion` adds output std cost x qty - material value
at the plant country (value basis only). Share = sum dom x v / sum v (None when sum v = 0).

BOM share (projection): the same arithmetic over the multi-level M1 BOM, bought components weighted by their
supplier COO shares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_DEPTH = 30


@dataclass
class ItemT:
    id: str
    key: str
    description: str = ""
    uom: str = "EA"
    std_cost: float = 0.0
    weight: float | None = None
    coo: str | None = None
    material_class: str | None = None


@dataclass
class LotT:
    id: str
    code: str
    item_id: str
    coo: str | None = None
    unit_value: float | None = None
    wo_id: str | None = None            # producing WO (made lot)
    wo_share: float = 1.0               # this lot's share of the WO output
    out_qty: float = 0.0                # quantity received into this lot from the WO
    transfer_share: tuple[float | None, float | None] | None = None   # carried (value, weight) shares


@dataclass
class EdgeT:
    kind: str                           # lot | stock
    lot_id: str | None
    item_id: str
    qty: float


@dataclass
class Graph:
    items: dict[str, ItemT]
    lots: dict[str, LotT]
    wo_inputs: dict[str, list[EdgeT]] = field(default_factory=dict)


@dataclass
class Rule:
    domestic_country: str = "US"
    material_classes: frozenset[str] | None = None
    include_conversion: bool = False
    plant_country: str | None = None


@dataclass
class _Tot:
    nv: float = 0.0
    dv: float = 0.0
    nw: float = 0.0
    dw: float = 0.0
    est: bool = False


def _share(n: float, d: float) -> float | None:
    return round(n / d, 6) if d > 0 else None


def rollup(g: Graph, lot_id: str, rule: Rule, memo: dict[str, Any] | None = None) -> dict[str, Any]:
    """{share_value, share_weight, estimated, tree} of a lot (`memo` per rule, shared across calls)."""
    memo = {} if memo is None else memo
    filt = rule.material_classes
    stack: set[str] = memo.setdefault("~stack", set())          # review m5: lots being rolled up (shared)
    flags: set[str] = memo.setdefault("~flags", set())

    def per_unit(lid: str, depth: int) -> tuple[_Tot, list[dict[str, Any]]]:
        """Totals per unit of the lot's output (filtered leaves), and the child nodes for 1 unit."""
        if lid in memo:
            return memo[lid]
        lot = g.lots[lid]
        if lid in stack:                                 # back edge: a genealogy cycle - not followed, estimated
            flags.add("TRADE_GENEALOGY_CYCLE")
            return _Tot(est=True), []
        tot, kids = _Tot(), []
        if lot.wo_id is None or depth > MAX_DEPTH:
            memo[lid] = (tot, kids)
            return memo[lid]
        stack.add(lid)
        out = lot.out_qty / lot.wo_share if lot.wo_share > 0 else lot.out_qty
        out = out or 1.0
        mat_value = 0.0
        for e in g.wo_inputs.get(lot.wo_id, []):
            it = g.items.get(e.item_id) or ItemT(e.item_id, e.item_id)
            q = e.qty / out
            if q <= 0:
                continue
            sub = g.lots.get(e.lot_id) if e.lot_id else None
            made = sub is not None and sub.wo_id is not None
            v_unit = (sub.unit_value if sub is not None and sub.unit_value is not None else it.std_cost)
            v, w = q * (v_unit or 0.0), (q * it.weight if it.weight is not None else 0.0)
            mat_value += v
            est = e.kind == "stock"
            if made and filt is not None:
                st, skids = per_unit(sub.id, depth + 1)
                tot.nv += st.nv * q
                tot.dv += st.dv * q
                tot.nw += st.nw * q
                tot.dw += st.dw * q
                tot.est |= st.est
                if st.dv or st.dw:
                    kids.append(_node(sub, it, q, None, None, _share(st.nv, st.dv), st.est, _scale(skids, q),
                                      "made"))
                continue
            if filt is not None and (it.material_class or "") not in filt:
                continue
            if made:
                st, skids = per_unit(sub.id, depth + 1)
                full = rollup_shares(g, sub.id, rule, memo, depth + 1)
                dom_v, dom_w = full
                est |= st.est
                kid = _node(sub, it, q, v, w, dom_v, est, _scale(skids, q), "made")
            else:
                coo = (sub.coo if sub is not None else None) or it.coo
                if sub is not None and sub.transfer_share is not None:
                    dom_v, dom_w = sub.transfer_share
                    dom_v = dom_v if dom_v is not None else (1.0 if coo == rule.domestic_country else 0.0)
                    dom_w = dom_w if dom_w is not None else dom_v
                else:
                    dom_v = dom_w = 1.0 if coo == rule.domestic_country else 0.0
                kid = _node(sub, it, q, v, w, dom_v, est, [], "bought" if sub is not None else "possible", coo)
            tot.nv += (dom_v or 0.0) * v
            tot.dv += v
            tot.nw += (dom_w if dom_w is not None else 0.0) * w
            tot.dw += w
            tot.est |= est
            kids.append(kid)
        if rule.include_conversion and filt is None:
            it = g.items.get(lot.item_id)
            conv = max((it.std_cost if it else 0.0) - mat_value, 0.0)
            if conv > 0:
                d = 1.0 if rule.plant_country == rule.domestic_country else 0.0
                tot.nv += d * conv
                tot.dv += conv
                kids.append({"kind": "conversion", "lot_id": None, "lot_code": None, "item_key": "", "description":
                             "Conversion", "coo": rule.plant_country, "material_class": None, "qty": 1.0, "uom": "",
                             "value": round(conv, 6), "weight_kg": None, "domestic": d, "estimated": False,
                             "children": []})
        stack.discard(lid)
        memo[lid] = (tot, kids)
        return memo[lid]

    tot, kids = per_unit(lot_id, 0)
    lot = g.lots[lot_id]
    it = g.items.get(lot.item_id) or ItemT(lot.item_id, lot.item_id)
    q = lot.out_qty or 1.0
    sv, sw = _share(tot.nv, tot.dv), _share(tot.nw, tot.dw)
    if lot.wo_id is None:
        if lot.transfer_share is not None:
            sv, sw = lot.transfer_share
        else:
            sv = sw = 1.0 if (lot.coo or it.coo) == rule.domestic_country else 0.0
    tree = _node(lot, it, q, tot.dv * q if lot.wo_id else None, tot.dw * q if lot.wo_id else None, sv, tot.est,
                 _scale(kids, q), "made" if lot.wo_id else "bought", lot.coo)
    return {"share_value": sv, "share_weight": sw, "estimated": tot.est or bool(flags), "tree": tree,
            "flags": sorted(flags)}


def rollup_shares(g: Graph, lot_id: str, rule: Rule, memo: dict[str, Any], depth: int = 0
                  ) -> tuple[float | None, float | None]:
    key = f"~shares:{lot_id}"
    if lot_id in memo.get("~stack", set()) and key not in memo:
        memo.setdefault("~flags", set()).add("TRADE_GENEALOGY_CYCLE")
        return None, None
    if key not in memo:
        unf = Rule(rule.domestic_country, None, rule.include_conversion, rule.plant_country)
        sub_memo = memo.setdefault("~unfiltered", {}) if rule.material_classes is not None else memo
        r = rollup(g, lot_id, unf, sub_memo)
        memo[key] = (r["share_value"], r["share_weight"])
    return memo[key]


def _node(lot: LotT | None, it: ItemT, q: float, v: float | None, w: float | None, dom: float | None, est: bool,
          kids: list[dict[str, Any]], kind: str, coo: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "lot_id": lot.id if lot else None, "lot_code": lot.code if lot else None,
            "item_key": it.key, "description": it.description, "coo": coo if coo is not None else (
                lot.coo if lot else it.coo), "material_class": it.material_class, "qty": round(q, 6),
            "uom": it.uom, "value": None if v is None else round(v, 6), "weight_kg": None if w is None else round(w, 6),
            "domestic": dom, "estimated": est, "children": kids}


def _scale(kids: list[dict[str, Any]], f: float) -> list[dict[str, Any]]:
    out = []
    for k in kids:
        k2 = dict(k)
        for x in ("qty", "value", "weight_kg"):
            if k2.get(x) is not None:
                k2[x] = round(k2[x] * f, 6)
        k2["children"] = _scale(k.get("children", []), f)
        out.append(k2)
    return out


def bom_share(item_id: str, bom: dict[str, list[tuple[str, float]]], items: dict[str, ItemT],
              buy_coo: dict[str, list[tuple[str | None, float]]], rule: Rule, basis: str = "value",
              depth: int = 0) -> tuple[float, float]:
    """(domestic numerator, denominator) per unit of a made item over its BOM; bought components split by their
    supplier COO shares [(coo, share)] (else the item's COO)."""
    num = den = 0.0
    if depth > MAX_DEPTH:
        return 0.0, 0.0
    filt = rule.material_classes
    for comp, qper in bom.get(item_id, []):
        it = items.get(comp) or ItemT(comp, comp)
        if comp in bom:
            n, d = bom_share(comp, bom, items, buy_coo, rule, basis, depth + 1)
            if filt is not None:
                num += n * qper
                den += d * qper
                continue
            if d > 0:
                share = n / d
                size = qper * (it.std_cost if basis == "value" else (it.weight or 0.0))
                num += share * size
                den += size
            continue
        if filt is not None and (it.material_class or "") not in filt:
            continue
        size = qper * (it.std_cost if basis == "value" else (it.weight or 0.0))
        splits = buy_coo.get(comp) or [(it.coo, 1.0)]
        dom = sum(sh for c, sh in splits if c == rule.domestic_country) / (sum(sh for _c, sh in splits) or 1.0)
        num += dom * size
        den += size
    return num, den
