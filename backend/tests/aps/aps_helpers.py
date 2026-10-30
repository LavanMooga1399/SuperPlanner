"""Scenario builders for the pure APS vectors: a Builder dataset + work orders -> `ApsSnapshot`."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from superplanner.mfg.aps.engine import schedule
from superplanner.mfg.aps.model import (ApsComponent, ApsParams, ApsSnapshot, DemandPeg, MrpPegView, PegSupply,
                                        WoSnap)
from superplanner.mfg.bundle import bundle_to_dataset
from superplanner.mfg.samples.common import REG, Builder, op, shift
from superplanner.mfg.tz import plant_tz

IST = ZoneInfo("Asia/Kolkata")
MON = date(2026, 11, 2)                      # Monday
AS_OF = datetime(2026, 11, 2, 9, 0, tzinfo=IST)


def plant(b: Builder | None = None, tz: str = "Asia/Kolkata") -> Builder:
    b = b or Builder()
    b.plant("APS test plant", utc_offset="+05:30")
    b.b["plant"][0]["time_zone"] = tz
    return b


def ds_of(b: Builder) -> Any:
    return bundle_to_dataset(b.b)


def wo(ds: Any, number: str, pn: str, qty: float, due: date, *, priority: int = 5, status: str = "released",
       comps: tuple[ApsComponent, ...] = (), done: frozenset[int] = frozenset()) -> WoSnap:
    it = ds.items_by_pn[pn]
    rt = next(r for r in ds.routings.values() if r.item_id == it.id)
    return WoSnap(id=f"wko_{abs(hash(number)) % (16 ** 32):032x}", number=number, status=status, item_id=it.id,
                  qty=qty, due_date=due, start_date=MON, priority=priority, routing_id=rt.id, serial_from=None,
                  components=comps, done_seqs=done)


def snap(ds: Any, wos: list[WoSnap], *, as_of: datetime = AS_OF, mrp: MrpPegView | None = None,
         stock: dict[str, float] | None = None, published: Any = None, **kw: Any) -> ApsSnapshot:
    return ApsSnapshot(as_of=as_of.astimezone(UTC), tz=plant_tz(ds.plant), dataset=ds, work_orders=wos, mrp=mrp,
                       stock_now=stock or {}, open_supply=[], published=published, **kw)


def run(s: ApsSnapshot, **params: Any) -> Any:
    params.setdefault("improve_seconds", 0)
    params.setdefault("overtime", "off")
    params.setdefault("horizon_days", 14)
    return schedule(s, ApsParams(**params))


def ops_of(res: Any, number: str) -> list[Any]:
    return sorted((o for o in res.operations if o.order.number == number), key=lambda o: (o.seq, o.split.index))


def local(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%a %H:%M")


__all__ = ["AS_OF", "IST", "MON", "ApsComponent", "Builder", "DemandPeg", "MrpPegView", "PegSupply", "REG", "ds_of",
           "local", "op", "ops_of", "plant", "run", "shift", "snap", "wo"]
