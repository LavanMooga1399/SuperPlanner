"""BD-like load-test seed (M8-DESIGN 14.2; `manage.py load-seed --profile bd|small`).

Profile `bd`: 40 flow lines (group `FLW`, 24/5) + 6 EtO chambers (group `STR`) + an aeration room, 3,000 SKUs
(1,800 finished make items in 20 families, 1,200 bought components), BOMs (3 components each), one routing
operation per finished item, 24 months of demand history, 6,000 open customer order lines (next 60 days), item
planning (rate replenishment, forecast on, packaging levels, EtO cycle), line rates per family, a changeover matrix.
`small` is the same shape at 1/20 (tests). Deterministic for a seed. The plant's manufacturing data is replaced
(same path as a sample load with `replace`).
"""

from __future__ import annotations

import math
import random
import time
from datetime import date, timedelta
from typing import Any

PROFILES = {"bd": {"lines": 40, "chambers": 6, "finished": 1800, "components": 1200, "families": 20,
                   "order_lines": 6000, "months": 24},
            "small": {"lines": 4, "chambers": 2, "finished": 90, "components": 60, "families": 4,
                      "order_lines": 300, "months": 24}}
DAYS = ["mon", "tue", "wed", "thu", "fri"]


def bundle(profile: str, anchor: date, rng: random.Random) -> dict[str, Any]:
    from .mfg.samples.common import Builder, line, op, shift

    p = PROFILES[profile]
    b = Builder()
    b.plant("Load test plant (BD-like)", utc_offset="-05:00", horizon=180, currency="USD")
    b.template("3X8-5", "Three shifts 24/5", [shift("A", DAYS, "06:00", "14:00"), shift("B", DAYS, "14:00", "22:00"),
                                             shift("C", DAYS, "22:00", "06:00")])
    b.template("24X7", "Continuous", [shift("Day", DAYS + ["sat", "sun"], "00:00", "00:00")])
    b.group("FLW", "Flow assembly", kind="line")
    b.group("STR", "EtO sterilisation", kind="oven")
    b.group("AER", "Aeration", kind="aeration")
    for k in range(p["lines"]):
        b.line(f"FL-{k + 1:02d}", "FLW", f"Flow line {k + 1}")
    for k in range(p["chambers"]):
        b.line(f"ST-{k + 1:02d}", "STR", f"Chamber {k + 1}")
    b.line("AER-01", "AER", "Aeration room")
    b.assign("3X8-5", "group", "FLW")
    b.assign("24X7", "group", "STR")
    b.assign("24X7", "group", "AER")
    comps = []
    for k in range(p["components"]):
        pn = f"BD-C{k + 1:05d}"
        b.item(pn, "buy", f"Component {k + 1}", lead_time_days=rng.choice((7, 14, 21, 28, 42)),
               min_order_qty=1000.0, standard_cost=round(rng.uniform(0.001, 0.05), 4))
        comps.append(pn)
    fins = []
    for k in range(p["finished"]):
        pn = f"BD-F{k + 1:05d}"
        fam = f"FAM{k % p['families'] + 1:02d}"
        b.item(pn, "make", f"Finished device {k + 1}", family=fam, lead_time_days=3, lot_controlled=True,
               standard_cost=round(rng.uniform(0.05, 0.6), 3))
        b.bom(pn, [line(10 * (j + 1), c, 1) for j, c in enumerate(rng.sample(comps, 3))])
        b.routing(pn, [op(10, "Assemble", "FLW", setup_minutes=0, run_minutes=0.001)])
        fins.append((pn, fam))
    bd = b.canonical()
    orders, lines = [], []
    per_order = 4
    n_orders = math.ceil(p["order_lines"] / per_order)
    for o in range(n_orders):
        no = f"SO-BD-{o + 1:06d}"
        orders.append({"number": no, "demand_type": "customer", "customer": f"Customer {o % 50 + 1}",
                       "program": None, "priority": 5, "status": "open"})
        for j in range(per_order):
            if len(lines) >= p["order_lines"]:
                break
            pn, _fam = rng.choice(fins)
            lines.append({"number": no, "line_no": 10 * (j + 1), "part_number": pn,
                          "qty": float(rng.choice((2000, 5000, 10000, 20000))),
                          "due_date": anchor + timedelta(days=rng.randint(1, 60))})
    stock = [{"part_number": c, "location_code": "STORES", "qty": float(rng.choice((0, 50000, 200000)))}
             for c in comps]
    bd["locations"] = [{"code": "STORES", "name": "Stores", "kind": "stores"},
                       {"code": "FG", "name": "Finished goods", "kind": "stores", "receipt_default": True}]
    bd["stock"] = [x for x in stock if x["qty"] > 0]
    bd["demand_orders"] = orders
    bd["demand_lines"] = lines
    return bd


def seed(db: Any, owner: str, *, profile: str = "bd", rng_seed: int = 8, anchor: date | None = None
         ) -> dict[str, Any]:
    from .api.db.models import new_id, utcnow
    from .api.db.ownership import owner_scope
    from .api.mfg import repo, writer
    from sqlalchemy import select

    from .api.mfg.db_models import MfgItemRow, MfgLineRow
    from .api.mfg.db_models_m8 import (MfgChangeoverRow, MfgDemandHistoryRow, MfgItemPackagingRow,
                                       MfgItemPlanningRow, MfgLineRateRow)
    from .api.mfg.services.samples import delete_all
    from .mfg.dataset import MfgDataset
    from .mfg.io.plan import ImportOptions, plan_import
    from .mfg.model import PlantRecord

    t0 = time.monotonic()
    rng = random.Random(rng_seed)
    p = PROFILES[profile]
    anchor = anchor or date.today() - timedelta(days=date.today().weekday())
    bd = bundle(profile, anchor, rng)
    plan = plan_import(bd, MfgDataset(plant=PlantRecord()), ImportOptions(release=True, today=anchor),
                       id_factory=new_id)
    if not plan.ok:
        raise ValueError(f"seed import has errors: {plan.row_errors[:5]}")
    with owner_scope(owner), db.write() as s:
        plant = repo.lock_plant(s)
        dv = plant.data_version
        delete_all(s)
        plant = repo.lock_plant(s)
        plant.data_version = dv + 1
        s.flush()
        writer.apply(s, plan, plant, stock_date=anchor - timedelta(days=1))
        now = utcnow()
        lines = {ln.code: ln for ln in s.execute(select(MfgLineRow)).scalars()}
        fams = [f"FAM{k + 1:02d}" for k in range(p["families"])]
        for code, ln in lines.items():
            if code.startswith("FL-"):
                ln.planning, ln.oee, ln.clearance_minutes, ln.setup_family = "flow", 0.85, 30, "BDF"
                ln.clean_every_hours, ln.clean_minutes = 72.0, 120
                k = int(code[3:]) - 1
                for f in {fams[k % len(fams)], fams[(k + 1) % len(fams)]}:
                    s.add(MfgLineRateRow(id=new_id("lrt_"), line_id=ln.id, item_id=None, item_family=f,
                                         units_per_hour=float(rng.choice((6000, 8000, 10000))), oee=None,
                                         row_version=1, created_at=now, updated_at=now))
            elif code.startswith("ST-"):
                ln.planning, ln.chamber_pallets, ln.cycle_hours = "sterilisation", 24, 14.0
            elif code == "AER-01":
                ln.chamber_pallets = 96
        s.add(MfgChangeoverRow(id=new_id("chg_"), line_setup_family="BDF", from_key="*", to_key="*", minutes=60,
                               cost=200.0, kind="changeover", row_version=1, created_at=now, updated_at=now))
        items = list(s.execute(select(MfgItemRow).where(MfgItemRow.make_buy == "make"))
                     .scalars())
        planning, packs, hist = [], [], []
        first = date(anchor.year, anchor.month, 1)
        months = []
        for k in range(p["months"], 0, -1):
            y, m = divmod(first.month - 1 - k, 12)
            months.append(date(first.year + y, m + 1, 1))
        for it in items:
            planning.append({"id": new_id("ipn_"), "owner_id": owner, "item_id": it.id, "replenishment": "rate",
                             "forecast": True, "like_item_id": None, "like_factor": 1.0, "service_level": None,
                             "order_pack_level": "case", "campaign_key": it.family, "campaign_min_hours": 4.0,
                             "campaign_max_hours": 48.0, "target_cover_days": 7, "ster_cycle_code": "ETO-STD",
                             "aeration_hours": 24.0, "release_mode": "parametric", "release_days": 1.0,
                             "post_days": 2, "abc": None, "xyz": None, "row_version": 1, "created_at": now,
                             "updated_at": now})
            for seq, (lvl, q) in enumerate((("each", 1.0), ("case", 1000.0), ("pallet", 50000.0)), start=1):
                packs.append({"id": new_id("pkg_"), "owner_id": owner, "item_id": it.id, "level": lvl, "seq": seq,
                              "code": lvl.upper()[:4], "qty_base": q, "gtin": None, "weight_kg": None,
                              "row_version": 1, "created_at": now, "updated_at": now})
            base = rng.uniform(5_000, 120_000)
            amp = rng.uniform(0.0, 0.3)
            for j, per in enumerate(months):
                v = base * (1 + 0.01 * j) * (1 + amp * math.cos(2 * math.pi * (per.month - 1) / 12)) * \
                    rng.uniform(0.9, 1.1)
                hist.append({"id": new_id("dhi_"), "owner_id": owner, "item_id": it.id, "period_start": per,
                             "bucket": "m", "qty": round(v), "cleaned_qty": None, "manual_qty": None,
                             "source": "import", "updated_at": now})
        for model, rows in ((MfgItemPlanningRow, planning), (MfgItemPackagingRow, packs),
                            (MfgDemandHistoryRow, hist)):
            for i in range(0, len(rows), 5000):
                s.execute(model.__table__.insert(), rows[i:i + 5000])
    return {"profile": profile, "items": p["finished"] + p["components"], "lines": p["lines"],
            "chambers": p["chambers"], "order_lines": p["order_lines"], "history_rows": len(hist),
            "seconds": round(time.monotonic() - t0, 1)}
