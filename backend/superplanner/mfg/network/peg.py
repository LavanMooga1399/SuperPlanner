"""Network pegging (M9-DESIGN 5.3 step 4) over the stored plan: every planned transfer / production carries the
pegs of the demand it serves (the ultimate demand refs propagate through transfers and BOM explosion), so a walk
down from a demand follows the objects pegged to its ref: receipts at the demand's vertex, then for a transfer the
objects at its source vertex, for a production the objects of other keys at the same node (its components). Up from
a supply lists the demands it is pegged to."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

Obj = dict[str, Any]   # {id, type: transfer|production, node, src?, key, week, qty, pegs, kind?, to_id?}


def _peg_qty(o: Obj, ref: str) -> float:
    return round(sum(p["qty"] for p in o["pegs"] if p["ref"] == ref), 6)


def down(ref: str, node: str, key: str, week: date | None, qty: float, objs: list[Obj], shortages: list[Obj],
         link: Callable[[str, Obj], str | None]) -> dict[str, Any]:
    pegged = [o for o in objs if any(p["ref"] == ref for p in o["pegs"])]
    used: set[str] = set()

    def vertex(n: str, k: str, depth: int) -> list[dict[str, Any]]:
        out = []
        if depth > 30:
            return out
        for o in pegged:
            if o["id"] in used:
                continue
            at = (o["dst"] if o["type"] == "transfer" else o["node"], o["key"])
            if at != (n, k):
                continue
            used.add(o["id"])
            out.append(node_of(o, depth))
        for s in shortages:
            if (s["node"], s["key"]) == (n, k) and any(p.get("ref") == ref for p in s["detail"].get("pegs", [])):
                sid = f"s:{s['id']}"
                if sid in used:
                    continue
                used.add(sid)
                out.append({"id": sid, "kind": "shortage", "node_owner_id": n, "item_key": k, "week": s["week"],
                            "qty": s["qty"], "ref": None, "cause": s["cause"], "link": None, "children": []})
        return out

    def node_of(o: Obj, depth: int) -> dict[str, Any]:
        if o["type"] == "transfer":
            kids = vertex(o["src"], o["key"], depth + 1)
            return {"id": f"t:{o['id']}", "kind": "transfer", "node_owner_id": o["src"], "item_key": o["key"],
                    "week": o["week"], "qty": _peg_qty(o, ref), "ref": o.get("to_number"), "cause": None,
                    "link": link(o["dst"], o), "children": kids}
        kids: list[dict[str, Any]] = []
        if o.get("kind") == "make":
            comps = sorted({p["key"] for p in pegged if p["type"] == "production" and p["node"] == o["node"]
                            and p["key"] != o["key"]} | {p["key"] for p in pegged if p["type"] == "transfer"
                                                         and p["dst"] == o["node"] and p["key"] != o["key"]})
            for ck in comps:
                kids += vertex(o["node"], ck, depth + 1)
        return {"id": f"p:{o['id']}", "kind": "production" if o.get("kind") == "make" else "purchase",
                "node_owner_id": o["node"], "item_key": o["key"], "week": o["week"], "qty": _peg_qty(o, ref),
                "ref": o.get("supplier_code"), "cause": None, "link": link(o["node"], o), "children": kids}

    return {"id": f"d:{ref}", "kind": "demand", "node_owner_id": node, "item_key": key, "week": week, "qty": qty,
            "ref": ref, "cause": None, "link": None, "children": vertex(node, key, 0)}


def up(o: Obj, link: Callable[[str, Obj], str | None]) -> dict[str, Any]:
    kids = [{"id": f"d:{p['ref']}", "kind": "demand", "node_owner_id": p["node"], "item_key": o["key"], "week": None,
             "qty": p["qty"], "ref": p["ref"], "cause": None, "link": None, "children": []}
            for p in sorted(o["pegs"], key=lambda p: (p["kind"], p["ref"]))]
    kind = "transfer" if o["type"] == "transfer" else ("production" if o.get("kind") == "make" else "purchase")
    node = o["src"] if o["type"] == "transfer" else o["node"]
    return {"id": f"{o['type'][0]}:{o['id']}", "kind": kind, "node_owner_id": node, "item_key": o["key"],
            "week": o["week"], "qty": o["qty"], "ref": o.get("to_number"), "cause": None,
            "link": link(node, o), "children": kids}
