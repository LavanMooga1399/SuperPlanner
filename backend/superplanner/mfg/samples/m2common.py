"""Helpers of the M2 sample parts (M2-DESIGN 13): per-unit requirements of an end item, deterministic prices and
WO component rows with issued quantities."""

from __future__ import annotations

import math
import random
from datetime import date
from typing import Any

from ..bundle import MfgBundle, bundle_to_dataset
from ..dataset import BomIndex, MfgDataset


def dataset(b: MfgBundle) -> MfgDataset:
    return bundle_to_dataset(b)


def per_unit(ds: MfgDataset, top_pn: str, on: date) -> dict[str, float]:
    """part number -> total quantity per unit of `top_pn` (summarized explosion with scrap and yield)."""
    from ..bom import explode

    e = explode(BomIndex.from_dataset(ds, on), ds.items_by_pn[top_pn].id, mode="summarized")
    return {r.part_number: r.total_qty for r in e.rows}


def price(rng: random.Random, pn: str) -> float:
    seg = pn.split("-")[1] if "-" in pn else ""
    lo, hi = {"RES": (0.02, 0.2), "CAP": (0.03, 0.8), "IND": (0.5, 4), "FB": (0.2, 1), "DIO": (0.5, 5),
              "TRN": (0.8, 6), "IC": (40, 900), "CON": (15, 300), "XTL": (8, 40), "WIR": (6, 30),
              "BPCB": (150, 2500), "LCD": (9000, 15000), "MOD": (14000, 22000), "COAT": (1500, 2500)}.get(seg, (5, 400))
    return round(lo + (hi - lo) * rng.random(), 2)


def component_rows(ds: MfgDataset, wo_number: str, pn: str, qty: float, start: date, serial: int | None,
                   issued_share: float) -> list[dict[str, Any]]:
    """The generated components of a WO (7.2) as `wo_components` rows, `issued_share` of each issued (rounded down
    for count items)."""
    from ..units import is_count
    from ..workorders import generate_components

    expl = generate_components(ds, ds.items_by_pn[pn].id, qty, on=start, serial=serial)
    rows = []
    seen: set[tuple[str, str | None]] = set()
    for c in expl.components:
        it = ds.items[c.item_id]
        key = (it.part_number, c.find_number)
        if key in seen:
            continue
        seen.add(key)
        iss = c.qty * issued_share
        iss = float(math.floor(iss + 1e-9)) if is_count(it.uom) else round(iss, 6)
        rows.append({"wo_number": wo_number, "part_number": it.part_number, "find_number": c.find_number,
                     "required_qty": float(c.qty), "issued_qty": iss, "operation_seq": c.operation_seq})
    return rows


def schedules(doc_type: str, number: str, line_no: int, parts: list[tuple[date, float]],
              confirmed: dict[int, date] | None = None, received: dict[int, float] | None = None
              ) -> list[dict[str, Any]]:
    out = []
    for seq, (d, q) in enumerate(parts, 1):
        row = {"doc_type": doc_type, "number": number, "line_no": line_no, "seq": seq, "requested_date": d,
               "qty": float(q)}
        if confirmed and seq in confirmed:
            row["confirmed_date"] = confirmed[seq]
        if received and seq in received:
            row["received_qty"] = float(received[seq])
        out.append(row)
    return out
