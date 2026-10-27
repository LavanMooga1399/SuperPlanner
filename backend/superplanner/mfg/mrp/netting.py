"""Netting and allocation (M2-DESIGN 8.8): working node types, requirement ordering, allocation of existing supply.

Interpretation (22.WP-E): the phase tests use the *effective* need date `max(need_date, as_of)` - a requirement
that was due in the past can at best be covered today, so stock on hand serves it in phase 1 (otherwise past-due
needs could never use stock when `protect_until == as_of`). `late_days` stays `satisfied_date - need_date`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .model import EPS, SerialRange, SourceRef

KIND_ORDER = {"stock": 0, "inspection": 1, "po": 2, "pr": 3, "wo": 4, "planned": 5}
DATE_MAX = date.max


class Req:
    __slots__ = ("item_id", "node", "kind", "need", "qty", "rank", "rank_label", "source", "segment", "pegs",
                 "pegged", "sat", "late", "parent", "alt", "order_key", "share", "component_id", "wo_id")

    def __init__(self, item_id: str, node: int, kind: str, need: date, qty: float, rank: tuple, rank_label: str,
                 source: SourceRef, segment: SerialRange | None):
        self.item_id = item_id
        self.node = node
        self.kind = kind
        self.need = need
        self.qty = qty
        self.rank = rank
        self.rank_label = rank_label
        self.source = source
        self.segment = segment
        self.pegs: list[PegI] = []
        self.pegged = 0.0
        self.sat: date | None = None
        self.late = 0
        self.parent: Sup | None = None             # parent make supply (dependent requirements)
        self.alt: list[tuple[Any, float]] = []     # (alternate group, primary qty of this requirement)
        self.order_key: str | None = None
        self.share: list[tuple[tuple[str | None, str], float]] | None = None
        self.component_id: str | None = None
        self.wo_id: str | None = None

    @property
    def remaining(self) -> float:
        return self.qty - self.pegged


class Sup:
    __slots__ = ("item_id", "node", "kind", "qty", "avail", "proj", "exp", "ref", "pegged", "comps", "planned_no",
                 "reserved_for", "start", "due", "mlt", "lot_id", "pegs", "po", "wo", "sched", "bal", "comp_ready",
                 "share", "dock_override")

    def __init__(self, item_id: str, node: int, kind: str, qty: float, avail: date, ref: SourceRef,
                 exp: date | None = None):
        self.item_id = item_id
        self.node = node
        self.kind = kind
        self.qty = qty
        self.avail = avail
        self.proj: date | None = None
        self.exp = exp
        self.ref = ref
        self.pegged = 0.0
        self.comps: list[Req] = []
        self.planned_no: int | None = None
        self.reserved_for: str | None = None
        self.start: date | None = None
        self.due: date | None = None
        self.mlt = 0
        self.lot_id: str | None = None
        self.pegs: list[PegI] = []
        self.po: Any = None          # planned order (planned supplies)
        self.wo: Any = None          # WoSnap
        self.sched: Any = None       # ScheduleSnap
        self.bal: Any = None         # BalanceSnap
        self.comp_ready: date | None = None
        self.share: list[tuple[tuple[str | None, str], float]] | None = None
        self.dock_override: date | None = None

    @property
    def remaining(self) -> float:
        return self.qty - self.pegged

    def sort_key(self) -> tuple:
        return (self.avail, self.exp or DATE_MAX, KIND_ORDER[self.kind], self.node)


class PegI:
    __slots__ = ("sup", "req", "qty", "late")

    def __init__(self, sup: Sup, req: Req, qty: float):
        self.sup = sup
        self.req = req
        self.qty = qty
        self.late = 0


def peg(sup: Sup, req: Req, qty: float) -> PegI:
    p = PegI(sup, req, qty)
    sup.pegged += qty
    req.pegged += qty
    sup.pegs.append(p)
    req.pegs.append(p)
    return p


def order_requirements(reqs: list[Req], allocation: str, protect_until: date) -> list[Req]:
    """8.8 step 3."""
    if allocation == "priority":
        first = sorted((r for r in reqs if r.need < protect_until), key=lambda r: (r.rank, r.need, r.node))
        rest = sorted((r for r in reqs if r.need >= protect_until), key=lambda r: (r.need, r.rank, r.node))
        return first + rest
    return sorted(reqs, key=lambda r: (r.need, r.rank, r.node))


def peg_reservations(reserved: list[Sup], by_component: dict[str, Req]) -> list[tuple[Sup, Req | None, float]]:
    """8.8 step 2: each reservation supply first covers its WO-component requirement; returns
    `(supply, requirement | None, excess over the component's open qty)` for every reservation with an excess."""
    excess: list[tuple[Sup, Req | None, float]] = []
    for s in sorted(reserved, key=lambda s: s.node):
        r = by_component.get(s.reserved_for or "")
        need = r.remaining if r is not None else 0.0
        q = min(s.remaining, max(0.0, need))
        if q > EPS and r is not None:
            peg(s, r, q)
        open_qty = r.qty if r is not None else 0.0
        if s.qty > open_qty + EPS:
            excess.append((s, r, s.qty - open_qty))
    return excess


def allocate(ordered: list[Req], supplies: list[Sup], as_of: date, protect_until: date) -> list[tuple[Req, float]]:
    """8.8 step 4: phase 1 (available by the effective need date, not expired by then), phase 2 (existing supply
    arriving after the need but before `protect_until`, pegged late). Returns the residuals `(req, qty)`."""
    free = sorted((s for s in supplies if s.remaining > EPS), key=Sup.sort_key)
    residuals: list[tuple[Req, float]] = []
    for r in ordered:
        rem = r.remaining
        if rem <= EPS:
            continue
        n = r.need if r.need > as_of else as_of
        if free:
            for s in free:                                   # phase 1
                if s.avail > n:
                    break
                sr = s.qty - s.pegged
                if sr <= EPS or (s.exp is not None and s.exp <= n):
                    continue
                q = sr if sr < rem else rem
                peg(s, r, q)
                rem -= q
                if rem <= EPS:
                    break
            if rem > EPS:                                    # phase 2
                for s in free:
                    if s.avail <= n:
                        continue
                    if s.avail >= protect_until:
                        break
                    sr = s.qty - s.pegged
                    if sr <= EPS or (s.exp is not None and s.exp <= n):
                        continue
                    q = sr if sr < rem else rem
                    peg(s, r, q)
                    rem -= q
                    if rem <= EPS:
                        break
            if len(free) > 8 and free[0].qty - free[0].pegged <= EPS:
                free = [s for s in free if s.qty - s.pegged > EPS]
        if rem > EPS:
            residuals.append((r, rem))
    return residuals


__all__ = ["KIND_ORDER", "PegI", "Req", "Sup", "allocate", "order_requirements", "peg", "peg_reservations"]
