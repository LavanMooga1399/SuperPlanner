"""Sample datasets (M1-DESIGN 10, M2-DESIGN 13): `SAMPLES` registry, `build(sample_id, *, anchor, include_transactions)
-> MfgBundle` (deterministic, canonical) and `scale(sample_id, factor)` (tests/benchmarks: extra product variants
sharing the buy-item library; master data only).

M2: every sample module `<id>_m2` adds master rows (`master(bundle)`: locations, suppliers, item-suppliers, item lot
fields, ...) and transactional rows dated as offsets from `anchor` (`transactions(bundle, anchor)`: stock, purchase
documents, demand, work orders). `mrp_state(sample_id, anchor)` is the pure equivalent of a loaded sample (opening
stock posted on `anchor - 1`, released/in-progress WOs reserved like the sample load does)."""

from __future__ import annotations

import copy
import importlib
from dataclasses import dataclass
from functools import lru_cache

from datetime import date
from typing import TYPE_CHECKING

from ..bundle import MfgBundle, bundle_counts
from .common import canonical

if TYPE_CHECKING:  # pragma: no cover
    from ..dataset import MfgDataset


@dataclass(frozen=True)
class SampleInfo:
    id: str
    name: str
    description: str
    module: str
    prefix: str


SAMPLES: dict[str, SampleInfo] = {}


def _register(module: str, prefix: str) -> None:
    mod = importlib.import_module(f".{module}", __name__)
    SAMPLES[mod.ID] = SampleInfo(mod.ID, mod.NAME, mod.DESCRIPTION, module, prefix)


_register("small", "SM-")
_register("medium", "MD-")
_register("kavach", "KV-")


DEFAULT_ANCHOR = date(2026, 11, 2)       # a Monday; golden values are pinned for it


@lru_cache(maxsize=8)
def _master(sample_id: str) -> MfgBundle:
    info = SAMPLES[sample_id]
    b = importlib.import_module(f".{info.module}", __name__).build()
    m2 = importlib.import_module(f".{info.module}_m2", __name__)
    b = m2.master(b)
    m3 = _m3(sample_id)
    return canonical(m3.master(b) if m3 is not None else b)


def _m3(sample_id: str):  # type: ignore[no-untyped-def]
    """The optional M3 module `<id>_m3` (M3-DESIGN 13)."""
    try:
        return importlib.import_module(f".{SAMPLES[sample_id].module}_m3", __name__)
    except ModuleNotFoundError:
        return None


def sample_progress(sample_id: str) -> dict[str, list[int]]:
    """WO number -> operation seqs marked done when the sample is loaded (M3 3.3)."""
    m3 = _m3(sample_id)
    return dict(getattr(m3, "PROGRESS", {})) if m3 is not None else {}


@lru_cache(maxsize=16)
def _built(sample_id: str, anchor: date = DEFAULT_ANCHOR, include_transactions: bool = True) -> MfgBundle:
    b = copy.deepcopy(_master(sample_id))
    if include_transactions:
        m2 = importlib.import_module(f".{SAMPLES[sample_id].module}_m2", __name__)
        b.update(m2.transactions(copy.deepcopy(b), anchor))
        m3 = _m3(sample_id)
        if m3 is not None and hasattr(m3, "dated"):
            b.update(m3.dated(b, anchor))
        b = canonical(b)
    return b


def build(sample_id: str, *, anchor: date = DEFAULT_ANCHOR, include_transactions: bool = True) -> MfgBundle:
    """The canonical bundle of a sample (a fresh deep copy; KeyError for unknown ids). Transactional dates are
    offsets from `anchor` (a Monday)."""
    if sample_id not in SAMPLES:
        raise KeyError(sample_id)
    return copy.deepcopy(_built(sample_id, anchor, include_transactions))


def mrp_state(sample_id: str, anchor: date = DEFAULT_ANCHOR) -> "MfgDataset":
    """The dataset (master + `txn`) a sample load with this `anchor` produces, as a pure value: balances received
    on `anchor - 1`, released / in-progress WOs reserved FEFO in WO-number order at `anchor`."""
    from ..bundle import bundle_to_dataset

    ds = bundle_to_dataset(build(sample_id, anchor=anchor))
    apply_opening_state(ds, anchor)
    return ds


def apply_opening_state(ds: "MfgDataset", anchor: date) -> None:
    """Mutates `ds.txn`: `last_receipt_on = anchor - 1` on every balance with stock, then the sample reservations
    (`sample_reservations`)."""
    from datetime import timedelta

    t = ds.txn
    if t is None:
        return
    for b in t.balances.values():
        if b.qty_on_hand > 0:
            b.last_receipt_on = anchor - timedelta(days=1)
    for comp_id, bal_id, qty in sample_reservations(ds, anchor):
        from ..bundle import deterministic_id
        from ..dataset import TxnReservation

        rid = deterministic_id("rsv_", comp_id, bal_id)
        t.reservations[rid] = TxnReservation(rid, comp_id, bal_id, qty)
        t.balances[bal_id].qty_reserved = round(t.balances[bal_id].qty_reserved + qty, 6)


def sample_reservations(ds: "MfgDataset", today: date) -> list[tuple[str, str, float]]:
    """Reservations of a sample load: every `released` / `in_progress` WO, in WO-number order, reserves its open
    components FEFO from the free usable stock (7.3)."""
    from ..workorders import ResComp, StockBal, plan_reservations

    t = ds.txn
    lots = t.lots
    bals = {b.id: StockBal(b.id, b.item_id, b.location_id, ds.locations[b.location_id].code,
                           ds.locations[b.location_id].kind, b.lot_id, lots[b.lot_id].lot_code if b.lot_id else None,
                           lots[b.lot_id].expires_on if b.lot_id else None, lots[b.lot_id].hold if b.lot_id else False,
                           b.qty_on_hand, b.qty_reserved, ds.locations[b.location_id].active)
            for b in t.balances.values()}
    out: list[tuple[str, str, float]] = []
    for w in sorted(t.work_orders.values(), key=lambda w: w.number):
        if w.status not in ("released", "in_progress"):
            continue
        comps = [ResComp(c.id, c.item_id, max(0.0, c.required_qty - c.issued_qty), 0.0) for c in w.components]
        res, _summary = plan_reservations(comps, list(bals.values()), today)
        for comp_id, bal_id, qty in res:
            bals[bal_id].qty_reserved += qty
            out.append((comp_id, bal_id, qty))
    return out


def counts(sample_id: str) -> dict[str, int]:
    return bundle_counts(_built(sample_id))


def sample_list() -> list[dict[str, object]]:
    """`GET /samples` items: `{id, name, description, counts}`."""
    return [{"id": s.id, "name": s.name, "description": s.description, "counts": counts(s.id)}
            for s in SAMPLES.values()]


def scale(sample_id: str, factor: int) -> MfgBundle:
    """`factor` product variants: variant k >= 2 copies every make/phantom item, its BOMs and routings with the
    part-number prefix `<P><k>-` (e.g. `KV2-`); buy items, plant and resources stay shared."""
    base = build(sample_id, include_transactions=False)
    if factor <= 1:
        return base
    prefix = SAMPLES[sample_id].prefix
    made = {r["part_number"] for r in base["items"] if r["make_buy"] != "buy"}
    for k in range(2, factor + 1):
        new = f"{prefix[:-1]}{k}-"

        def ren(pn: str) -> str:
            return new + pn[len(prefix):] if pn in made and pn.startswith(prefix) else pn

        base["items"] += [dict(r, part_number=ren(r["part_number"])) for r in _rows(base, "items")
                          if r["part_number"] in made]
        for sheet, fields in (("boms", ("parent_part_number",)), ("bom_lines", ("parent_part_number",
                                                                                "child_part_number")),
                              ("routings", ("part_number",)), ("operations", ("part_number",))):
            base[sheet] += [dict(r, **{f: ren(r[f]) for f in fields}) for r in _rows(base, sheet)
                            if r[fields[0]] in made and r[fields[0]].startswith(prefix)]
    return canonical(base)


def _rows(bundle: MfgBundle, sheet: str) -> list[dict]:
    return list(bundle[sheet])
