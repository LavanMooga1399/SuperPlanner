"""The hand-calculated test vectors of M2-DESIGN 8.15 as oracle plants (as_of Mon 2026-11-02, Mon-Sat, 480 min).

Each builder returns a `PB` (so tests can reach the named objects) - the same plant drives the oracle self-test,
the engine-vs-oracle comparison and the API set-up of Gate 2 #3.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from .build import PB, d


def tm1(**item_kw: Any) -> SimpleNamespace:
    b = PB(tag="tm1")
    c = b.buy("C", lt=10, receiving_days=2, **item_kw)
    stock = b.stock(c, 100)
    po = b.po(c, [(d("11-10"), 50)])
    r1 = b.demand(c, 120, d("11-15"), number="DO-TM1-1")
    r2 = b.demand(c, 80, d("11-20"), number="DO-TM1-2")
    return SimpleNamespace(b=b, plant=b.build(), c=c, stock=stock, po=po[0], r1=r1, r2=r2)


def tm2() -> SimpleNamespace:
    return tm1(min_order_qty=5000, order_multiple=5000)


def tm3() -> SimpleNamespace:
    b = PB(tag="tm3")
    x = b.buy("D", lt=60)
    po = b.po(x, [(d("12-01"), 200)])
    r = b.demand(x, 150, d("11-20"), number="DO-TM3-1")
    return SimpleNamespace(b=b, plant=b.build(), d=x, po=po[0], r=r)


def tm4() -> SimpleNamespace:
    """M1 T-Q1: ops 10 (100%), 20 (97%), 30 (98%); C qty_per 4, scrap 2 %, consumed at op 10; P fixed LT 0."""
    b = PB(tag="tm4")
    p = b.make("P", lt=0)
    c = b.buy("C", lt=0)
    b.routing(p, [{"seq": 10, "yield_pct": 100}, {"seq": 20, "yield_pct": 97}, {"seq": 30, "yield_pct": 98}])
    b.bom(p, [(c, 4, {"scrap": 2, "op": 10})])
    dm = b.demand(p, 100, d("11-30"), number="DO-TM4-1")
    return SimpleNamespace(b=b, plant=b.build(), p=p, c=c, dm=dm)


def tm5(holiday: bool = False) -> SimpleNamespace:
    b = PB(tag="tm5")
    p = b.make("P")
    b.routing(p, [{"seq": 10, "setup_minutes": 60, "run_minutes": 3},
                  {"seq": 20, "run_minutes": 1.2, "wait_minutes": 1440}])
    if holiday:
        b.holiday(d("11-17"))
    dm = b.demand(p, 100, d("11-20"), number="DO-TM5-1")
    return SimpleNamespace(b=b, plant=b.build(), p=p, dm=dm)


def tm6(allocation: str = "priority") -> SimpleNamespace:
    b = PB(tag="tm6", allocation=allocation)
    x = b.buy("X", lt=90)
    stock = b.stock(x, 10)
    d1 = b.demand(x, 8, d("11-30"), priority=1, number="DO-TM6-1")
    d2 = b.demand(x, 8, d("11-20"), priority=5, number="DO-TM6-2")
    return SimpleNamespace(b=b, plant=b.build(), x=x, stock=stock, d1=d1, d2=d2)


def tm7(alt_qty_per: float = 1, alternates: str = "when_short") -> SimpleNamespace:
    b = PB(tag="tm7", alternates=alternates)
    p = b.make("P", lt=2)
    a1 = b.buy("A1", lt=120)
    a2 = b.buy("A2", lt=120)
    b.simple_routing(p)
    b.bom(p, [(a1, 1, {"alt_group": "G1", "alt_priority": 1}),
              (a2, alt_qty_per, {"alt_group": "G1", "alt_priority": 2})])
    s2 = b.stock(a2, 500)
    dm = b.demand(p, 300, d("11-20"), number="DO-TM7-1")
    return SimpleNamespace(b=b, plant=b.build(), p=p, a1=a1, a2=a2, s2=s2, dm=dm)


def tm8() -> SimpleNamespace:
    b = PB(tag="tm8")
    e = b.make("E", lt=1, serialized=True)
    k1 = b.buy("K1", lt=0)
    k2 = b.buy("K2", lt=0)
    b.simple_routing(e)
    v1 = b.bom(e, [(k1, 1)], version=1)
    v2 = b.bom(e, [(k2, 1)], version=2, serial=(106, 1_000_000_000))
    dm = b.demand(e, 10, d("12-15"), serial=(101, 110), number="DO-TM8-1")
    return SimpleNamespace(b=b, plant=b.build(), e=e, k1=k1, k2=k2, v1=v1, v2=v2, dm=dm)


def tm9(need: str = "11-20") -> SimpleNamespace:
    b = PB(tag="tm9")
    g = b.buy("G", lt=5)
    lot = b.stock(g, 100, lot="L1", expires=d("11-15"))
    r = b.demand(g, 50, d(need), number="DO-TM9-1")
    return SimpleNamespace(b=b, plant=b.build(), g=g, lot=lot, r=r)


def tm10() -> SimpleNamespace:
    b = PB(tag="tm10")
    x = b.buy("S", lt=5, safety_stock=20)
    st = b.stock(x, 15)
    return SimpleNamespace(b=b, plant=b.build(), x=x, stock=st)


def tm11() -> SimpleNamespace:
    b = PB(tag="tm11")
    c = b.buy("C", lt=30)
    p1 = b.make("P1", lt=1)
    p2 = b.make("P2", lt=1)
    b.simple_routing(p1)
    b.simple_routing(p2)
    st = b.stock(c, 50)
    w1 = b.wo(p1, 40, d("11-05"), d("11-06"), components=[(c, 40)], number="WO-TM11-1")
    w2 = b.wo(p2, 30, d("11-04"), d("11-05"), components=[(c, 30)], number="WO-TM11-2")
    b.reserve(w1.components[0], st, 40)
    return SimpleNamespace(b=b, plant=b.build(), c=c, stock=st, w1=w1, w2=w2)


def tm12() -> SimpleNamespace:
    b = PB(tag="tm12")
    j = b.buy("J", lt=10)
    pa = b.po(j, [(d("11-10"), 100)], number="PO-TM12-A")
    pb = b.po(j, [(d("11-12"), 50)], number="PO-TM12-B")
    r = b.demand(j, 100, d("12-20"), number="DO-TM12-1")
    return SimpleNamespace(b=b, plant=b.build(), j=j, pa=pa[0], pb=pb[0], r=r)


def tm13() -> SimpleNamespace:
    b = PB(tag="tm13")
    p = b.make("P", lt=5)
    c = b.buy("C", lt=60)
    b.simple_routing(p)
    b.bom(p, [(c, 1)])
    po = b.po(c, [(d("12-03"), 10)])
    dm = b.demand(p, 10, d("12-04"), number="DO-TM13-1")
    return SimpleNamespace(b=b, plant=b.build(), p=p, c=c, po=po[0], dm=dm)


ALL = {"T-M1": tm1, "T-M2": tm2, "T-M3": tm3, "T-M4": tm4, "T-M5": tm5,
       "T-M5h": lambda: tm5(holiday=True), "T-M6p": tm6, "T-M6d": lambda: tm6("due_date"), "T-M7": tm7,
       "T-M7b": lambda: tm7(2), "T-M7n": lambda: tm7(alternates="never"), "T-M8": tm8, "T-M9": tm9,
       "T-M9b": lambda: tm9("11-10"), "T-M10": tm10, "T-M11": tm11, "T-M12": tm12, "T-M13": tm13}
