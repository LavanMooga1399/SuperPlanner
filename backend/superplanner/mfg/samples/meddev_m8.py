"""M8 additions to the fictional `meddev` sample (M8-DESIGN 14.1), loaded as sample `meddev_m8` (= `meddev` + this
layer) so `meddev` and its M1-M7 expectations stay unchanged. Pure data and a seeded history generator.

- Rate-planned (flow) assembly lines `FLA-01`, `FLA-02` (group `FLOW`, setup family `FLA`, rates per family, OEE
  0.80 / 0.88, clearance 45 min, cleaning every 72 h for 120 min) and packaging line `FLP-01`; EtO chambers
  `EOS-01`, `EOS-02` (24 pallets, 14 h) planned by the sterilisation planner and aeration room `AER-01` (96 pallet
  positions). New lines: the sample's discrete lines (ASSY, STER, ...) stay with APS.
- Changeover matrix by `campaign_key`: same size 30 min, size change 90 min, syringe <-> needle 240 min cleaning +
  45 min clearance.
- Packaging levels on the finished syringes / needles / catheters / flush (each, inner 100, case, pallet).
- 30 months of monthly history (seeded): trend, flu-season peak for syringes and needles, two intermittent SKUs,
  one new item with a like item (`MDV-SYR-10` like `MDV-SYR-03` x 0.5), two outliers.
- Forecast overrides (3), kanban loops (tip caps, roller clamps; one empty card).
"""

from __future__ import annotations

import math
import random
from datetime import date
from typing import Any

ID = "meddev_m8"
NAME = "Medical devices + volume planning (M8)"
DESCRIPTION = ("Fictional medical device plant with M8 make-to-stock planning: 30 months of demand history, "
               "forecasts, safety-stock proposals, rate-planned flow lines, EtO chambers and kanban loops. "
               "Not real data.")

RATE_ITEMS = {"MDV-SYR-03": "SYR-3", "MDV-SYR-10": "SYR-10", "MDV-NDL-23": "NDL-23", "MDV-NDL-25": "NDL-25"}
FORECAST_ITEMS = ("MDV-SYR-03", "MDV-SYR-10", "MDV-NDL-23", "MDV-NDL-25", "MDV-IVC-20", "MDV-IVC-22", "MDV-FLS-10")
STERILE = ("MDV-SYR-03", "MDV-SYR-10", "MDV-NDL-23", "MDV-NDL-25", "MDV-IVC-20", "MDV-IVC-22")
CASE = {"MDV-SYR-03": 2000, "MDV-SYR-10": 1000, "MDV-NDL-23": 2000, "MDV-NDL-25": 2000, "MDV-IVC-20": 1000,
        "MDV-IVC-22": 1000, "MDV-FLS-10": 1000}
PALLET_CASES = {"MDV-SYR-03": 48, "MDV-SYR-10": 40, "MDV-NDL-23": 60, "MDV-NDL-25": 60, "MDV-IVC-20": 50,
                "MDV-IVC-22": 50, "MDV-FLS-10": 40}
#: (code, name, planning, oee, clearance, clean_every_hours, clean_minutes, chamber_pallets, cycle_hours)
LINES = [("FLA-01", "Flow assembly 1", "FLOW", "flow", 0.80, 45, 72.0, 120, None, None),
         ("FLA-02", "Flow assembly 2", "FLOW", "flow", 0.88, 45, 72.0, 120, None, None),
         ("FLP-01", "Flow packaging 1", "FLOWPK", "flow", 0.85, 15, None, None, None, None),
         ("EOS-01", "EtO chamber (planned) 1", "EOS", "sterilisation", 0.85, 0, None, None, 24, 14.0),
         ("EOS-02", "EtO chamber (planned) 2", "EOS", "sterilisation", 0.85, 0, None, None, 24, 14.0),
         ("AER-01", "Aeration room 1", "AER", "discrete", 0.85, 0, None, None, 96, None)]
GROUPS = [("FLOW", "Flow assembly (rate planned)", "line", "FLA"), ("FLOWPK", "Flow packaging", "line", "FLP"),
          ("EOS", "EtO sterilisation (load planned)", "oven", None), ("AER", "EtO aeration", "aeration", None)]
#: line code -> [(family, units per hour)]
RATES = {"FLA-01": [("SYRINGE", 9000.0), ("NEEDLE", 11000.0)], "FLA-02": [("SYRINGE", 8000.0), ("NEEDLE", 10000.0)],
         "FLP-01": [("SYRINGE", 15000.0), ("NEEDLE", 15000.0)]}
MATRIX = ([{"line_setup_family": "FLA", "from_key": k, "to_key": k, "minutes": 30, "cost": 50.0,
            "kind": "changeover"} for k in RATE_ITEMS.values()] +
          [{"line_setup_family": "FLA", "from_key": "*", "to_key": "*", "minutes": 90, "cost": 300.0,
            "kind": "changeover"}] +
          [{"line_setup_family": "FLA", "from_key": a, "to_key": b, "minutes": 240, "cost": 900.0, "kind": "cleaning"}
           for a in ("SYR-3", "SYR-10") for b in ("NDL-23", "NDL-25")] +
          [{"line_setup_family": "FLA", "from_key": b, "to_key": a, "minutes": 240, "cost": 900.0, "kind": "cleaning"}
           for a in ("SYR-3", "SYR-10") for b in ("NDL-23", "NDL-25")] +
          [{"line_setup_family": "FLA", "from_key": a, "to_key": b, "minutes": 45, "cost": 0.0, "kind": "clearance"}
           for a, b in (("SYR-3", "NDL-23"), ("SYR-3", "NDL-25"), ("SYR-10", "NDL-23"), ("SYR-10", "NDL-25"),
                        ("NDL-23", "SYR-3"), ("NDL-25", "SYR-3"), ("NDL-23", "SYR-10"), ("NDL-25", "SYR-10"))])
#: monthly base volume, trend per month, season amplitude, intermittent probability
PROFILE = {"MDV-SYR-03": (1_200_000, 6_000, 0.30, 0.0), "MDV-NDL-23": (900_000, 4_000, 0.28, 0.0),
           "MDV-NDL-25": (700_000, 2_500, 0.25, 0.0), "MDV-IVC-20": (200_000, 1_000, 0.05, 0.0),
           "MDV-IVC-22": (60_000, 0, 0.0, 0.55), "MDV-FLS-10": (40_000, 0, 0.0, 0.6)}
LIKE = {"MDV-SYR-10": ("MDV-SYR-03", 0.5, 6)}             # new item: 6 months own history
OUTLIERS = {("MDV-NDL-23", 9): 6.0, ("MDV-IVC-20", 20): 8.0}   # (item, month index) -> factor
MONTHS = 30
OVERRIDES = [{"item_family": "SYRINGE", "mode": "pct", "value": 8.0, "periods": (0, 2),
              "reason": "Flu season: distributor pre-buy"},
             {"item": "MDV-NDL-25", "mode": "abs", "value": 750_000.0, "periods": (1, 1),
              "reason": "Hospital group tender (confirmed volume)"},
             {"item": "MDV-IVC-22", "mode": "pct", "value": -20.0, "periods": (0, 5),
              "reason": "Customer conversion to 20G"}]
KANBAN = [{"item": "MDV-TIP-CAP", "location": "LS-FLA", "cards": 4, "container_qty": 25_000, "lead": 7, "empty": 1},
          {"item": "MDV-CLAMP", "location": "LS-FLA", "cards": 3, "container_qty": 10_000, "lead": 7, "empty": 0}]
STER = {"cycle": "ETO-STD", "aeration_hours": 48.0, "release_mode": "bi", "release_days": 7.0}


def _add_months(d: date, k: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    return date(d.year + y, m + 1, 1)


def history(anchor: date) -> list[tuple[str, date, float]]:
    """(part number, period start, qty) for the 30 closed months before the anchor's month (seeded)."""
    rng = random.Random(20261125)
    last = _add_months(anchor.replace(day=1), -1)
    first = _add_months(last, -(MONTHS - 1))
    out: list[tuple[str, date, float]] = []
    for pn in sorted(PROFILE):
        base, trend, amp, p_zero = PROFILE[pn]
        for k in range(MONTHS):
            per = _add_months(first, k)
            season = 1 + amp * math.cos(2 * math.pi * (per.month - 12) / 12)
            v = (base + trend * k) * season * (1 + rng.gauss(0, 0.04))
            if p_zero and rng.random() < p_zero:
                v = 0.0
            elif p_zero:
                v = base * rng.uniform(0.6, 1.8)
            v *= OUTLIERS.get((pn, k), 1.0)
            out.append((pn, per, round(max(v, 0.0))))
    for pn, (like, factor, own) in LIKE.items():
        src = {p: q for i, p, q in out if i == like}
        for k in range(MONTHS - own, MONTHS):
            per = _add_months(first, k)
            out.append((pn, per, round(src[per] * factor * (1 + rng.gauss(0, 0.05)))))
    return out


def packaging(pn: str) -> list[dict[str, Any]]:
    case = CASE[pn]
    return [{"level": "each", "code": "EA", "qty_base": 1.0}, {"level": "inner", "code": "BX100", "qty_base": 100.0},
            {"level": "case", "code": f"CS{case}", "qty_base": float(case)},
            {"level": "pallet", "code": f"PL{PALLET_CASES[pn]}", "qty_base": float(case * PALLET_CASES[pn])}]
