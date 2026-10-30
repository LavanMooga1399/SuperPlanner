"""Seeded random plants for Gate 2 #2 (multi-level, shared components, staggered POs/PRs, lots with expiry,
reservations, all lot rules, MOQ/multiple/pack, both allocation policies, alternates never/when_short, serial
segments with an ECO split).

The generator stays inside the unambiguous part of section 8 (see `core.INTERPRETATIONS`): one alternate per
group, alternates never inside phantoms, a child at most once per BOM, serialized demand quantities equal to their
serial-range length, no lot-controlled stock in inspection, preferred suppliers active, no WO component cycles.
Every plant also satisfies the Gate 1 essentials (buy items have a lead time, in-use make items a routing).
"""

from __future__ import annotations

import random
from datetime import timedelta

from .build import AS_OF, PB
from .model import OItem, OPlant


def random_plant(seed: int) -> OPlant:
    rng = random.Random(seed)
    b = PB(tag=f"r{seed}", allocation=rng.choice(["priority", "due_date"]),
           alternates=rng.choice(["never", "when_short", "when_short"]),
           horizon_days=rng.choice([60, 90, 120, 180]), safety_stock=rng.random() < 0.8)
    pl = b.plant
    if rng.random() < 0.3:
        pl.workdays = ("mon", "tue", "wed", "thu", "fri")
    for _ in range(rng.randint(0, 2)):
        b.holiday(AS_OF + timedelta(days=rng.randint(1, 60)))
    pl.release_window_days = rng.choice([0, 7, 14])
    pl.defer_tolerance_days = rng.choice([0, 7])
    sups = [b.supplier(f"S{i}", lt=rng.choice([None, 5, 20])) for i in range(rng.randint(1, 3))]
    if rng.random() < 0.3:
        sups.append(b.supplier("SX", lt=7, active=False))
    b.location("LS", "line_side")
    b.location("INSP", "inspection")
    b.location("Q", "quarantine")
    b.location("LSX", "line_side")          # inactive location (C9: never nettable)

    # ---------------------------------------------------------- buy items
    buys: list[OItem] = []
    for i in range(rng.randint(4, 10)):
        uom = rng.choice(["EA"] * 6 + ["KG", "M"])
        rule = rng.choice(["lot_for_lot"] * 3 + ["fixed", "period"])
        kw = dict(uom=uom, receiving_days=rng.choice([0, 0, 1, 3]), lot_rule=rule,
                  safety_stock=rng.choice([0] * 6 + [5, 20]))
        if rule == "fixed":
            kw["fixed_lot_qty"] = float(rng.choice([10, 25, 100]))
        if rule == "period":
            kw["lot_period_days"] = rng.choice([7, 14, 30])
        if rng.random() < 0.3:
            kw["min_order_qty"] = float(rng.choice([20, 50, 500]))
        if rng.random() < 0.25:
            kw["order_multiple"] = float(rng.choice([5, 10, 50]))
        it = b.buy(f"B{i:02d}", lt=rng.choice([0, 3, 10, 30, 60, 90]), **kw)
        buys.append(it)
        if rng.random() < 0.7:
            active = [s for s in sups if s.active]
            s1 = rng.choice(active)
            pack = float(rng.choice([1, 1, 1, 10, 100])) if uom == "EA" else rng.choice([1.0, 2.5])
            b.item_supplier(it, s1, lead_time_days=rng.choice([None, None, 15, 45]),
                            min_order_qty=rng.choice([0.0, 0.0, 30.0]), order_multiple=rng.choice([0.0, 0.0, 4.0]),
                            units_per_purchase_unit=pack, preferred=rng.random() < 0.6)
            others = [s for s in sups if s is not s1]
            if others and rng.random() < 0.4:
                b.item_supplier(it, rng.choice(others), lead_time_days=rng.choice([5, 60]))

    # ---------------------------------------------------------- make items by level (0 = top)
    levels = rng.randint(2, 4)
    makes: list[list[OItem]] = []
    for lv in range(levels):
        row = []
        for j in range(rng.randint(1, 2) if lv == 0 else rng.randint(1, 3)):
            ser = lv == 0 and rng.random() < 0.5
            rule = rng.choice(["lot_for_lot"] * 4 + ["fixed", "period"]) if not ser else "lot_for_lot"
            kw = dict(serialized=ser, lot_rule=rule, safety_stock=rng.choice([0] * 8 + [3]))
            if rule == "fixed":
                kw["fixed_lot_qty"] = float(rng.choice([5, 20]))
            if rule == "period":
                kw["lot_period_days"] = rng.choice([7, 30])
            if not ser and rng.random() < 0.2:
                kw["min_order_qty"] = 10.0
            lt = rng.choice([None, None, 0, 2, 5])
            row.append(b.make(f"M{lv}{j}", lt=lt, family=rng.choice([None, "FAM"]), **kw))
        makes.append(row)
    phantom = b.phantom("PH0") if levels >= 3 and rng.random() < 0.5 else None

    def ops() -> list[dict]:
        out = []
        for k in range(rng.randint(1, 3)):
            out.append({"seq": 10 * (k + 1), "setup_minutes": rng.choice([0, 30, 120]),
                        "run_minutes": rng.choice([0, 1, 4, 15]), "wait_minutes": rng.choice([0, 0, 600]),
                        "yield_pct": rng.choice([100, 100, 98, 95]),
                        "run_per": "unit"})
        return out

    if rng.random() < 0.5:
        b.plant.lines.append(type(b.plant.lines[0])(id=f"lin_{'f' * 32}", group_id=b.group_id, speed_factor=1.5,
                                                    eligible_families=["FAM"]))
    for lv, row in enumerate(makes):
        lower_makes = [m for r in makes[lv + 1:] for m in r]
        for m in row:
            b.routing(m, ops())
            pool = lower_makes + buys
            if phantom is not None and lv == 0:
                pool = pool + [phantom]
            n = min(len(pool), rng.randint(1, 4))
            children = rng.sample(pool, n)
            if lv == levels - 1 or not any(c.make_buy == "make" for c in children):
                pass
            lines = []
            used = {c.id for c in children}
            for c in children:
                q = float(rng.choice([1, 1, 2, 3])) if c.uom == "EA" else rng.choice([0.25, 1.5])
                opt = {"scrap": rng.choice([0, 0, 2, 5]), "op": rng.choice([None, 10, 20])}
                lines.append((c, q, opt))
            if rng.random() < 0.35:
                prim = [ln for ln in lines if ln[0].make_buy == "buy" and ln[0].uom == "EA"]
                alts = [x for x in buys if x.id not in used and x.uom == "EA"]
                if prim and alts:
                    p0 = prim[0]
                    p0[2].update({"alt_group": "A1", "alt_priority": 1})
                    a = rng.choice(alts)
                    lines.append((a, p0[1] * rng.choice([1, 2]), {"alt_group": "A1", "alt_priority": 2,
                                                                  "op": p0[2]["op"]}))
                    used.add(a.id)
                    b.stock(a, float(rng.choice([0, 50, 300])))
            b.bom(m, lines)
            if m.serialized and rng.random() < 0.7:
                extra = rng.choice([x for x in buys if x.id not in used] or buys)
                v2 = [(c, q, {k: v for k, v in o.items() if k not in ("alt_group", "alt_priority")})
                      for c, q, o in lines if o.get("alt_priority", 1) == 1]
                v2 = [ln for ln in v2 if ln[0].id != extra.id] + [(extra, 1.0)]
                b.bom(m, v2, version=2, serial=(rng.choice([104, 110, 125]), 1_000_000_000))
    if phantom is not None:
        bottom = [x for x in buys]
        b.bom(phantom, [(c, float(rng.choice([1, 2]))) for c in rng.sample(bottom, min(2, len(bottom)))])

    allm = [m for r in makes for m in r]
    # ---------------------------------------------------------- stock, lots, POs, PRs
    for it in buys + allm[1:]:
        if rng.random() < 0.55:
            q = float(rng.choice([1, 5, 20, 80, 400]))
            if it.make_buy == "buy" and rng.random() < 0.25:
                b.stock(it, q, lot=f"L{it.part_number}", expires=AS_OF + timedelta(days=rng.choice([-3, 10, 40, 400])),
                        hold=rng.random() < 0.1)
            else:
                b.stock(it, q, loc=rng.choice(["STORES", "STORES", "LS", "Q"]))
        if rng.random() < 0.1:
            b.stock(it, float(rng.choice([7, 70])), loc="LSX").location_active = False
        if it.make_buy == "buy" and rng.random() < 0.15:
            b.stock(it, float(rng.choice([3, 30])), loc="INSP", last_receipt=AS_OF - timedelta(days=rng.choice([0, 1])))
    for it in buys:
        if rng.random() < 0.5:
            scheds = []
            for _ in range(rng.randint(1, 3)):
                req = AS_OF + timedelta(days=rng.randint(-10, 100))
                conf = req + timedelta(days=rng.choice([0, 7, 30])) if rng.random() < 0.3 else None
                scheds.append((req, float(rng.choice([10, 40, 150])), conf))
            b.po(it, scheds, status=rng.choice(["open", "open", "draft", "partially_received"]))
        if rng.random() < 0.2:
            b.pr(it, [(AS_OF + timedelta(days=rng.randint(5, 60)), float(rng.choice([10, 50])))],
                 status=rng.choice(["draft", "submitted", "approved"]))
    # ---------------------------------------------------------- existing WOs (sub-levels), reservations
    subs = [m for r in makes[1:] for m in r]
    for k, m in enumerate(subs[:rng.randint(0, 2)]):
        start = AS_OF + timedelta(days=rng.randint(-4, 20))
        bom = next(x for x in pl.boms if x.item_id == m.id and x.version == 1)
        comps = [(pl.items[ln.child_id], ln.qty_per * 10) for ln in bom.lines
                 if ln.alt_priority == 1 and pl.items[ln.child_id].make_buy != "phantom"]
        w = b.wo(m, 10, start, start + timedelta(days=rng.randint(0, 8)), components=comps,
                 status=rng.choice(["planned", "released", "in_progress"]))
        w.routing_id = next(x.id for x in pl.routings if x.item_id == m.id)        # C12
        if w.status != "planned":
            for c in w.components:
                bal = next((x for x in pl.balances if x.item_id == c.item_id and x.location_kind == "stores"
                            and x.lot_id is None and x.qty_on_hand - x.qty_reserved > 1), None)
                if bal is not None and rng.random() < 0.6:
                    b.reserve(c, bal, float(min(c.open_qty + rng.choice([0, 5]), int(bal.qty_on_hand - bal.qty_reserved))))
    # ---------------------------------------------------------- demand
    serial_next = 101
    progs = ["PA", "PB", None]
    for k in range(rng.randint(2, 6)):
        it = rng.choice(makes[0] + (subs if subs and rng.random() < 0.3 else []))
        due = AS_OF + timedelta(days=rng.randint(-5, 130))
        qty = rng.randint(1, 12)
        serial = None
        if it.serialized and rng.random() < 0.85:
            serial = (serial_next, serial_next + qty - 1)
            serial_next += qty
        b.demand(it, float(qty), due, priority=rng.randint(1, 9), serial=serial, program=rng.choice(progs),
                 number=f"DO-{k:03d}")
    if rng.random() < 0.3:
        pl.params.protect_programs = ["PB"]
    return b.build()
