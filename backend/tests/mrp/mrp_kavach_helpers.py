"""Kavach-scale MRP scenario (M2-DESIGN 13.3, 15 MP1-MP3) built in the test: the M1 `kavach` master data plus the
13.3 additions (TPU BOM v2 ECO from serial 126 with KV-DOC-PACK-B, lot settings, suppliers / item-suppliers with
reel packs) and synthetic transactions (stock, staggered POs, PRs, demand orders, WOs) following 13.3. Used until
WP-A's `samples/kavach_m2.py` lands; deterministic (seeded)."""

from __future__ import annotations

import copy
import math
import random
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

from superplanner.mfg.bom import explode
from superplanner.mfg.bundle import bundle_to_dataset
from superplanner.mfg.dataset import BomIndex, MfgDataset
from superplanner.mfg.model import Ref
from superplanner.mfg.model_m2 import ItemSupplierRecord, LocationRecord, SupplierRecord
from superplanner.mfg.mrp import MrpSnapshot
from superplanner.mfg.mrp.explode import order_components
from superplanner.mfg.samples import kavach as kavach_mod

from mrp_helpers import AS_OF, Snap, eid

A = AS_OF
TS = datetime(2026, 1, 1, tzinfo=UTC)


def _a(n: int) -> date:
    return A + timedelta(days=n)


def _stamp(i: str) -> dict[str, Any]:
    return {"id": i, "row_version": 1, "created_at": TS, "updated_at": TS}


def _scaled(factor: int) -> dict:
    """M1 `kavach` master (generator module directly, independent of the sample registry's M2 layer), scaled like
    `samples.scale`: variant k >= 2 copies every make/phantom item with the prefix `KV<k>-`."""
    b = copy.deepcopy(kavach_mod.build())
    made = {r["part_number"] for r in b["items"] if r["make_buy"] != "buy"}
    base = {k: list(v) for k, v in b.items()}
    for k in range(2, factor + 1):
        new = f"KV{k}-"

        def ren(pn: str) -> str:
            return new + pn[3:] if pn in made and pn.startswith("KV-") else pn

        b["items"] += [dict(r, part_number=ren(r["part_number"])) for r in base["items"] if r["part_number"] in made]
        for sheet, flds in (("boms", ("parent_part_number",)), ("bom_lines", ("parent_part_number",
                                                                              "child_part_number")),
                            ("routings", ("part_number",)), ("operations", ("part_number",))):
            b[sheet] += [dict(r, **{f: ren(r[f]) for f in flds}) for r in base[sheet] if r[flds[0]] in made]
    return b


def kavach_bundle(factor: int = 1) -> dict:
    b = _scaled(factor)
    if not any(r["part_number"] == "KV-DOC-PACK-B" for r in b["items"]):
        b["items"].append({"part_number": "KV-DOC-PACK-B", "make_buy": "buy", "description": "Documentation pack B",
                           "lead_time_days": 14})
        for parent in sorted({r["parent_part_number"] for r in b["boms"] if r["parent_part_number"].endswith(
                "-TPU-1000")}):
            tpu = [ln for ln in b["bom_lines"] if ln["parent_part_number"] == parent]
            hdr = next(h for h in b["boms"] if h["parent_part_number"] == parent)
            b["boms"].append(dict(hdr, version=2, serial_from=126, serial_to=1_000_000_000, effective_to=None))
            for ln in tpu:
                nl = dict(ln, version=2)
                if nl["child_part_number"] == "KV-DOC-PACK":
                    nl["child_part_number"] = "KV-DOC-PACK-B"
                b["bom_lines"].append(nl)
    for it in b["items"]:
        pn = it["part_number"]
        if it["make_buy"] != "buy":
            continue
        if pn == "KV-COAT-UR" or pn.startswith(("KV-IC-FPGA", "KV-IC-PROC")) or pn == "KV-MOD-GSM":
            it["lot_controlled"] = True
        if pn.startswith(("KV-RES-", "KV-CAP-0", "KV-CAP-06", "KV-CAP-08")) and (it.get("min_order_qty") or 0) > 0:
            it["lot_rule"], it["lot_period_days"] = "period", 30
            it["min_order_qty"] = 0
            it["order_multiple"] = 0
        if pn.startswith("KV-IC-"):
            it["receiving_days"] = 2
    return b


def _suppliers(ds: MfgDataset, rng: random.Random) -> None:
    codes = ["SEMI-1", "SEMI-2", "PASS-1", "PASS-2", "CONN", "MECH", "RADIO", "PRINT"]
    sups = {eid("sup", c): SupplierRecord.model_construct(**_stamp(eid("sup", c)), code=c, name=f"Supplier {c}",
                                                          lead_time_days=None, currency="INR", active=True)
            for c in codes}
    isus: dict[str, Any] = {}

    def add(item: Any, code: str, *, preferred: bool, lead: int | None, moq: float = 0, mult: float = 0,
            pack: float = 1.0) -> None:
        rid = eid("isu", item.id, code)
        isus[rid] = ItemSupplierRecord.model_construct(
            **_stamp(rid), item_id=item.id, supplier_id=eid("sup", code), supplier_part_number="", lead_time_days=lead,
            min_order_qty=moq, order_multiple=mult, purchase_unit="REEL" if pack > 1 else None,
            units_per_purchase_unit=pack, unit_price=1.0, currency="INR", preferred=preferred, active=True, note="",
            item=None, supplier=Ref.model_construct(id=eid("sup", code), code=code, name=code))

    for it in sorted(ds.items.values(), key=lambda i: i.part_number):
        if it.make_buy != "buy":
            continue
        pn = it.part_number
        if pn.startswith(("KV-RES-", "KV-CAP-")) and it.lot_rule == "period":
            add(it, "PASS-1" if rng.random() < 0.5 else "PASS-2", preferred=True, lead=it.lead_time_days,
                moq=5000, mult=5000, pack=5000)
        elif pn.startswith("KV-IC-"):
            add(it, "SEMI-1", preferred=True, lead=it.lead_time_days)
            add(it, "SEMI-2", preferred=False, lead=(it.lead_time_days or 0) + 28)
        elif pn.startswith(("KV-CON-", "KV-WIR-", "KV-TRM-", "KV-HSG-")):
            add(it, "CONN", preferred=True, lead=it.lead_time_days)
        elif pn.startswith(("KV-MOD-", "KV-LCD-")):
            add(it, "RADIO", preferred=True, lead=it.lead_time_days)
        elif pn.startswith(("KV-DOC-", "KV-LBL-")):
            add(it, "PRINT", preferred=True, lead=it.lead_time_days)
        else:
            add(it, "MECH", preferred=True, lead=it.lead_time_days)
    ds.suppliers = sups
    ds.item_suppliers = isus
    ds.locations = {eid("loc", c): LocationRecord.model_construct(**_stamp(eid("loc", c)), code=c, name=c, kind=k,
                                                                  receipt_default=c == "GOODS-IN", active=True)
                    for c, k in (("STORES-MAIN", "stores"), ("GOODS-IN", "inspection"), ("LS-SMT", "line_side"),
                                 ("LS-HAR", "line_side"), ("FG", "stores"), ("QUAR", "quarantine"))}


@lru_cache(maxsize=4)
def _dataset(factor: int) -> MfgDataset:
    ds = bundle_to_dataset(kavach_bundle(factor))
    _suppliers(ds, random.Random(42))
    return ds


def kavach_snap(*, factor: int = 1, extra_lines: int = 0, seed: int = 2611) -> Snap:
    ds = _dataset(factor)
    rng = random.Random(seed)
    s = Snap(ds)
    by = ds.items_by_pn
    tpu = by["KV-TPU-1000"].id
    per = explode(BomIndex.from_dataset(ds, A), tpu, mode="summarized")
    qty_per = {r.item_id: r.total_qty for r in per.rows}
    explicit = {"KV-IC-FPGA-V1", "KV-MOD-GSM", "KV-LCD-104", "KV-COAT-UR"}
    reels: list[str] = []
    for it in sorted(ds.items.values(), key=lambda i: i.part_number):
        if it.make_buy != "buy" or it.part_number in explicit or it.id not in qty_per:
            continue
        x = rng.random()
        c = 0 if x < 0.05 else (20 if x < 0.30 else 50)
        if c == 0:
            continue
        q = math.ceil(c * qty_per[it.id] - 1e-9)
        if it.lot_rule == "period":
            q = math.ceil(q / 5000) * 5000
            reels.append(it.part_number)
        loc = "LS-SMT" if it.lot_rule == "period" and len(reels) <= 20 else "STORES-MAIN"
        s.stock(it.part_number, float(q), loc=loc)
    s.stock("KV-IC-FPGA-V1", 45, lot="FV1-2609", expires=_a(700))
    s.stock("KV-MOD-GSM", 8, lot="GSM-2608", expires=_a(700))
    s.stock("KV-LCD-104", 20)
    s.stock("KV-LCD-104", 6, kind="inspection", loc="GOODS-IN", last_receipt=_a(-1))
    s.stock("KV-COAT-UR", 1.5, lot="L-2610", expires=_a(18))
    s.stock("KV-COAT-UR", 4, lot="L-2702", expires=_a(200))
    con = next(pn for pn in sorted(by) if pn.startswith("KV-CON-DSUB"))
    s.stock(con, 50, kind="quarantine", loc="QUAR")
    s.stock("KV-HAR-L01", 6)
    s.stock("KV-PCB-LED", 15)
    # purchase orders (staggered)
    s.schedule("KV-IC-FPGA-V1", 30, _a(20), number="PO-KV-0101")
    s.schedule("KV-IC-FPGA-V1", 30, _a(48), confirmed=_a(64), number="PO-KV-0101")
    s.schedule("KV-IC-FPGA-V1", 30, _a(110), number="PO-KV-0101")
    for k in (28, 58, 88, 118):
        s.schedule("KV-MOD-GSM", 10, _a(k), number="PO-KV-0103")
    s.schedule("KV-LCD-104", 14, _a(23), number="PO-KV-0104")
    s.schedule("KV-LCD-104", 20, _a(48), confirmed=_a(63), number="PO-KV-0104")
    s.schedule("KV-LCD-104", 20, _a(78), number="PO-KV-0104")
    s.schedule(con, 200, _a(-12), number="PO-KV-0102")
    s.schedule("KV-DOC-PACK", 40, _a(30), number="PO-KV-0105")
    buys = [pn for pn in sorted(by) if by[pn].make_buy == "buy" and pn.startswith(("KV-SCR-", "KV-PNL-", "KV-GSK"))]
    for i, pn in enumerate(buys[:6]):
        for k in range(1 + i % 3):
            s.schedule(pn, 50.0 * (k + 1), _a(15 + 20 * k), number=f"PO-KV-02{i:02d}")
    cons = [pn for pn in sorted(by) if pn.startswith("KV-CON-M12")][:2]
    for j, pn in enumerate(cons):
        for k in range(2):
            s.schedule(pn, 20, _a(30 + 30 * k), doc_type="pr", number="PR-KV-0201", line_no=10 * (j + 1),
                       status="submitted")
    wire = next(pn for pn in sorted(by) if pn.startswith("KV-WIR-"))
    s.schedule(wire, 500, _a(25), doc_type="pr", number="PR-KV-0202", status="draft")
    # demand
    s.dem("KV-TPU-1000", 10, _a(43), priority=1, number="DO-KV-001", line_no=10, serials=(101, 110),
          program="KVP-26")
    s.dem("KV-TPU-1000", 10, _a(74), priority=1, number="DO-KV-001", line_no=20, serials=(111, 120),
          program="KVP-26")
    s.dem("KV-TPU-1000", 15, _a(90), priority=2, number="DO-KV-002", line_no=10, serials=(121, 135),
          program="KVP-27")
    s.dem("KV-PCB-CPU", 4, _a(29), priority=3, number="DO-KV-003", line_no=10, demand_type="spares")
    s.dem("KV-HAR-L03", 6, _a(23), priority=3, number="DO-KV-003", line_no=20, demand_type="spares")
    s.dem("KV-PSU-6000", 2, _a(69), priority=3, number="DO-KV-003", line_no=30, demand_type="spares")
    s.dem("KV-TPU-1000", 2, _a(18), priority=1, number="DO-KV-004", line_no=10, serials=(99, 100),
          program="KVP-PROTO", demand_type="project")
    # work orders
    bal_by_item: dict[str, list[Any]] = {}
    for bsn in s.balances:
        if bsn.kind in ("stores", "line_side"):
            bal_by_item.setdefault(bsn.item_id, []).append(bsn)
    for number, pn, q, start, due, status, done in (("WO-KV-0001", "KV-PCB-CPU", 30, -3, 7, "released", 0.5),
                                                     ("WO-KV-0002", "KV-HAR-L03", 8, -5, 4, "in_progress", 0.33),
                                                     ("WO-KV-0003", "KV-VCU-2000", 10, 20, 30, "planned", 0.0)):
        ex = order_components(ds, by[pn].id, q, on=A, serial=None)
        comps = [(ds.items[c.item_id].part_number, round(c.qty * (1 - done))) for c in ex.components
                 if round(c.qty * (1 - done)) > 0]
        w = s.wo(pn, q, _a(start), _a(due), comps, status=status, number=number)
        if number == "WO-KV-0001":
            for comp in w.components:
                for bsn in bal_by_item.get(comp.item_id, ())[:1]:
                    rq = min(comp.open_qty, bsn.qty_on_hand)
                    if rq > 0:
                        s.reserve(comp.component_id, bsn.id, rq)
    for i in range(extra_lines):
        sf = 1000 + 20 * i
        n = 2 + rng.randrange(9)
        tgt = "KV-TPU-1000" if factor == 1 or i % 2 == 0 else "KV2-TPU-1000"
        s.dem(tgt, n, _a(20 + rng.randrange(180)), priority=1 + rng.randrange(9), number=f"DO-SYN-{i:03d}",
              serials=(sf, sf + n - 1))
    return s


def kavach_snapshot(**kw: Any) -> MrpSnapshot:
    return kavach_snap(**kw).snapshot()
