"""15.3 #5: ten explosion quantities and ten operation times of the Kavach sample, recomputed in this test from the
raw documents (BOM lines, routing operations, line speeds) with the hand formulas of M1-DESIGN 4.4 / 4.5 - no
library code - match the API within 1e-9 (the API rounds displayed values to 6 decimals, 4.4).

    required(line) = (Q_parent / Y_k) x qty_per x (1 + scrap/100) x uom_factor(line uom -> child uom)
    Y_k = product of yield_pct/100 of the parent's primary routing operations with seq >= seq_k
          (k = the line's operation_seq, missing/None -> first operation; no routing -> 1)
    lot inputs (count uom): in_n = ceil(Q / y_n - 1e-9), in_k = ceil(in_{k+1} / y_k - 1e-9)
    loads = qty | ceil(qty / units_per_panel - 1e-9) | ceil(qty / units_per_batch - 1e-9)
    total = setup + run x loads / speed_factor
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from accm1_helpers import Api

ON = "2026-11-02"
FACTOR = {"EA": ("count", 1.0), "M": ("length", 1.0), "CM": ("length", 0.01), "MM": ("length", 0.001),
          "KG": ("mass", 1.0), "G": ("mass", 0.001), "L": ("volume", 1.0), "ML": ("volume", 0.001),
          "M2": ("area", 1.0)}


def _close(hand: float, api_value: float) -> bool:
    return min(abs(hand - api_value), abs(round(hand, 6) - api_value)) <= 1e-9


class Hand:
    def __init__(self, api: Api):
        self.api = api
        self._boms: dict[str, Any] = {}
        self._routing: dict[str, Any] = {}

    def bom(self, bom_id: str) -> dict[str, Any]:
        if bom_id not in self._boms:
            self._boms[bom_id] = self.api.get(f"/boms/{bom_id}")
        return self._boms[bom_id]

    def primary_ops(self, item_id: str) -> list[dict[str, Any]]:
        if item_id not in self._routing:
            on = date.fromisoformat(ON)
            eff = []
            for r in self.api.get(f"/items/{item_id}/routings")["items"]:
                if r["status"] != "released" or r["priority"] != 1 or r["serial_from"] is not None:
                    continue
                f = date.fromisoformat(r["effective_from"]) if r["effective_from"] else date.min
                t = date.fromisoformat(r["effective_to"]) if r["effective_to"] else date.max
                if f <= on < t:
                    eff.append(r)
            assert len(eff) <= 1
            ops = self.api.get(f"/routings/{eff[0]['id']}")["operations"] if eff else []
            self._routing[item_id] = sorted(ops, key=lambda o: o["seq"])
        return self._routing[item_id]

    def cum_yield(self, item_id: str, op_seq: int | None) -> float:
        ops = self.primary_ops(item_id)
        if not ops:
            return 1.0
        idx = next((i for i, o in enumerate(ops) if o["seq"] == op_seq), 0)
        y = 1.0
        for o in ops[idx:]:
            y *= o["yield_pct"] / 100.0
        return y


def test_ten_explosion_quantities_match_hand_formulas(api: Api):
    api.load("kavach")
    top = api.item("KV-TPU-1000")
    qty = 3.0
    rows = api.get(f"/items/{top['id']}/explosion", on=ON, qty=qty)["rows"]
    by_row = {r["row"]: r for r in rows}

    def pick(pred, label):
        hit = [r for r in rows if pred(r)]
        assert hit, label
        return hit[len(hit) // 2]

    chosen = [
        pick(lambda r: r["level"] == 1 and r["part_number"] == "KV-DMI-4000", "DMI x2"),
        pick(lambda r: r["level"] == 4, "level-4 blank IC"),
        pick(lambda r: r["line_uom"] == "ML", "coating ML -> L"),
        pick(lambda r: r["line_uom"] == "MM", "wire MM -> M"),
        pick(lambda r: (r["scrap_pct"] or 0) > 0 and r["level"] == 3, "scrap at level 3"),
        pick(lambda r: by_row[r["parent_row"]]["is_phantom"] if r["parent_row"] is not None else False,
             "child of a phantom"),
        pick(lambda r: r["is_phantom"], "phantom row"),
        pick(lambda r: r["part_number"] == "KV-CAP-0402-100N" and r["level"] == 3, "shared capacitor"),
        pick(lambda r: r["operation_seq"] is not None and r["level"] == 3 and r["line_uom"] == "EA",
             "consumed at a later operation"),
        rows[-1],
    ]
    assert len({r["row"] for r in chosen}) == 10
    hand = Hand(api)
    for r in chosen:
        path = [r]
        while path[-1]["parent_row"] is not None:
            path.append(by_row[path[-1]["parent_row"]])
        path.reverse()
        q = qty
        for parent, child in zip(path, path[1:]):
            line = next(ln for ln in hand.bom(parent["bom_id"])["lines"] if ln["id"] == child["line_id"])
            assert line["child"]["part_number"] == child["part_number"]
            dim_l, f_l = FACTOR[line["uom"]]
            dim_c, f_c = FACTOR[line["child"]["uom"]]
            assert dim_l == dim_c
            y = hand.cum_yield(parent["item_id"], line["operation_seq"])
            q = (q / y) * line["qty_per"] * (1 + line["scrap_pct"] / 100.0) * (f_l / f_c)
        assert _close(q, r["extended_qty"]), (r["part_number"], r["row"], q, r["extended_qty"])


def _lot_inputs(ops: list[dict[str, Any]], q: float) -> list[int]:
    ins = [0] * len(ops)
    nxt = q
    for i in range(len(ops) - 1, -1, -1):
        ins[i] = math.ceil(nxt / (ops[i]["yield_pct"] / 100.0) - 1e-9)
        nxt = ins[i]
    return ins


def _loads(op: dict[str, Any], q: float) -> float:
    if op["run_per"] == "panel":
        return math.ceil(q / op["units_per_panel"] - 1e-9)
    if op["run_per"] == "batch":
        return math.ceil(q / op["units_per_batch"] - 1e-9)
    return q


def test_ten_operation_times_match_hand_formulas(api: Api):
    api.load("kavach")
    lines = {ln["id"]: ln for ln in api.get("/lines")["items"]}
    cases = [  # (part number, routing priority, op seq, line code or None = first line, qty)
        ("KV-TPU-1000", 1, 10, "FA-2", 7),
        ("KV-TPU-1000", 1, 20, "BI-1", 7),         # burn-in per batch
        ("KV-PCB-CPU", 1, 10, "SMT-1", 250),        # SMT top per panel
        ("KV-PCB-COM", 1, 10, "SMT-3", 250),        # slow line, speed 0.7
        ("KV-PCB-CPU", 1, 70, None, 33),            # wash per batch
        ("KV-PCB-VIO", 1, 90, None, 120),           # cure per batch, unattended
        ("KV-PCB-VIO", 1, 110, None, 120),          # FCT gate with yield
        ("KV-PCB-FLT", 2, None, None, 40),          # alternate routing (wave solder)
        ("KV-HAR-L01", 1, 30, None, 5),             # harness assembly
        ("KV-PCB-DCC", 1, 50, None, 1),             # THT per unit, qty 1
    ]
    checked = 0
    for pn, prio, seq, line_code, q in cases:
        it = api.item(pn)
        rts = [r for r in api.get(f"/items/{it['id']}/routings")["items"]
               if r["status"] == "released" and r["priority"] == prio]
        assert len(rts) == 1, (pn, prio)
        rt = api.get(f"/routings/{rts[0]['id']}")
        ops = sorted(rt["operations"], key=lambda o: o["seq"])
        tp = api.get(f"/routings/{rt['id']}/time-preview", qty=q)
        ins = _lot_inputs(ops, q) if it["uom"] == "EA" else None
        idx = next(i for i, o in enumerate(ops) if o["seq"] == seq) if seq is not None else len(ops) // 2
        op = ops[idx]
        tpo = next(o for o in tp["operations"] if o["seq"] == op["seq"])
        assert tpo["input_qty"] == ins[idx], (pn, op["seq"], tpo["input_qty"], ins[idx])
        loads = _loads(op, ins[idx])
        assert _close(loads, tpo["loads"]), (pn, op["seq"])
        tpl = (next(x for x in tpo["lines"] if x["code"] == line_code) if line_code else tpo["lines"][0])
        speed = lines[tpl["line_id"]]["speed_factor"]
        assert lines[tpl["line_id"]]["group_id"] == op["group_id"]
        run = op["run_minutes"] * loads / speed
        total = op["setup_minutes"] + run
        assert _close(op["setup_minutes"], tpl["setup_minutes"]), (pn, op["seq"])
        assert _close(run, tpl["run_minutes"]), (pn, op["seq"], run, tpl["run_minutes"])
        assert _close(total, tpl["total_minutes"]), (pn, op["seq"], total, tpl["total_minutes"])
        if line_code == "SMT-3":
            assert speed == 0.7
        checked += 1
    assert checked == 10
