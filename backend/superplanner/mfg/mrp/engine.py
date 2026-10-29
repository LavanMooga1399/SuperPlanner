"""`run_mrp(snapshot, params) -> MrpResult` (M2-DESIGN 8): orchestration of one deterministic run.

One pass = build existing supplies and gross requirements (8.3) -> process items by low-level code (8.4), within a
level by part number: reservations, ordering, allocation (8.8), lot sizing (8.6), explosion of planned make orders
(8.7) -> forward pass (8.10). With `alternates == "when_short"` the alternates pass (8.9) computes directives from
pass 1 and, if any, the whole computation runs again with them (`iterations = 2`).
"""

from __future__ import annotations

import gc
import math
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from ..dataset import MfgDataset
from ..limits import MRP_MAX_REQUIREMENTS
from ..model import EntityRef, HealthIssue, ItemRecord
from ..units import is_count
from .explode import StructureCache, apply_structure
from .leadtime import (PurchaseSource, calendar_of, item_suppliers_by_item, mlt_info, resolve_source, settings_of)
from .llc import bom_edges_in_window, low_level_codes
from .lotsize import LotParams, fixed_lots, lot_note, lot_params, round_order_qty
from .model import (EPS, LeadTimeInfo, MrpParams, MrpPreflightError, MrpResult, MrpSnapshot, MrpTooLarge,
                    SerialRange, SourceRef)
from .netting import Req, Sup, allocate, order_requirements, peg, peg_reservations

ONE = timedelta(days=1)
PO_SUPPLY_STATUSES = ("draft", "open", "partially_received")
PR_SUPPLY_STATUSES = ("draft", "submitted", "approved")
WO_SUPPLY_STATUSES = ("planned", "released", "in_progress")
SS_RANK = (2, 9, date.max, "", 0)


def fmt_qty(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x)):,}"
    return f"{x:,.3f}".rstrip("0").rstrip(".")


class _State:
    __slots__ = ("item", "llc", "reqs", "sups", "nxt", "processed", "protect", "planned")

    def __init__(self, item: ItemRecord, llc: int, protect: date):
        self.item = item
        self.llc = llc
        self.reqs: list[Req] = []
        self.sups: list[Sup] = []
        self.nxt = 0
        self.processed = False
        self.protect = protect
        self.planned: list[_Planned] = []


class _Planned:
    __slots__ = ("no", "kind", "item_id", "qty", "need", "start", "dock", "sup", "segment", "bom_id", "routing_id",
                 "order_key", "supplier_id", "directives", "lot_note", "mlt")

    def __init__(self, no: int, kind: str, item_id: str, qty: float, need: date, start: date, dock: date | None,
                 sup: Sup, segment: SerialRange | None, order_key: str, supplier_id: str | None, lot_note: str,
                 mlt: int):
        self.no = no
        self.kind = kind
        self.item_id = item_id
        self.qty = qty
        self.need = need
        self.start = start
        self.dock = dock
        self.sup = sup
        self.segment = segment
        self.bom_id: str | None = None
        self.routing_id: str | None = None
        self.order_key = order_key
        self.supplier_id = supplier_id
        self.directives: dict[str, float] = {}
        self.lot_note = lot_note
        self.mlt = mlt


# ---------------------------------------------------------------- shared context


class Ctx:
    """Inputs and caches shared by both passes."""

    def __init__(self, snap: MrpSnapshot, params: MrpParams):
        ds = snap.dataset
        self.snap = snap
        self.ds = ds
        self.params = params
        self.as_of: date = params.as_of or snap.as_of
        self.settings = settings_of(ds.plant)
        self.cal = calendar_of(self.settings, frozenset(snap.holidays))
        horizon = params.horizon_days or int(getattr(ds.plant, "planning_horizon_days", 90) or 90)
        self.horizon_days = horizon
        self.horizon_end = self.as_of + timedelta(days=horizon)
        self.lt_over: dict[str, int] = {o.item_id: o.lead_time_days for o in params.lead_time_overrides}
        self.sched_over: dict[str, date] = {o.schedule_id: o.date for o in params.supply_date_overrides
                                            if o.schedule_id}
        self.wo_over: dict[str, date] = {o.wo_id: o.date for o in params.supply_date_overrides if o.wo_id}
        self.protected = set(params.protect_programs)
        self.isup = item_suppliers_by_item(ds)
        self.locations = getattr(ds, "locations", None) or {}
        self.structures = StructureCache(ds)
        self._src: dict[str, PurchaseSource] = {}
        self._lot: dict[str, LotParams] = {}
        self._note: dict[str, str] = {}
        self._fast: dict[int, tuple] = {}
        self._fast_keep: list[Any] = []          # keeps the structures alive so their ids stay unique
        self.serial_make = {i: (it.make_buy == "make" and it.serialized) for i, it in ds.items.items()}
        self._mlt: dict[tuple, tuple[int, str]] = {}
        self._protect: dict[str, date] = {}
        self._cuts: dict[str, list[int]] = {}
        self.speed: dict[tuple[str, str], float] = {}
        # low-level codes
        # C10: window end = horizon end + largest purchase lead time (buy items, item-suppliers, suppliers,
        # overrides of buy items) + 1 day
        max_lead = 0
        for it in ds.items.values():
            if it.make_buy == "buy":
                max_lead = max(max_lead, it.lead_time_days or 0)
        for r in (getattr(ds, "item_suppliers", None) or {}).values():
            max_lead = max(max_lead, r.lead_time_days or 0)
        for s in (getattr(ds, "suppliers", None) or {}).values():
            max_lead = max(max_lead, s.lead_time_days or 0)
        for o in params.lead_time_overrides:
            it = ds.items.get(o.item_id)
            if it is not None and it.make_buy == "buy":
                max_lead = max(max_lead, o.lead_time_days)
        edges = bom_edges_in_window(ds, self.as_of, self.horizon_end + timedelta(days=max_lead + 1))
        wo_edges = [(w.id, w.item_id, c[1]) for w in sorted(snap.work_orders, key=lambda w: (w.number, w.id))
                    if w.status in WO_SUPPLY_STATUSES and w.item_id in ds.items
                    for c in w.components if c[1] in ds.items]
        self.llc, self.cycle_wos = low_level_codes(ds.items.keys(), edges, wo_edges)
        self.order = sorted(ds.items, key=lambda i: (self.llc.get(i, 0), ds.items[i].part_number, i))

    # -------------------------------------------------- per-item resolutions

    def source(self, item: ItemRecord) -> PurchaseSource:
        s = self._src.get(item.id)
        if s is None:
            s = self._src[item.id] = resolve_source(self.ds, item, self.isup.get(item.id, []),
                                                    self.lt_over.get(item.id))
        return s

    def lot(self, item: ItemRecord) -> LotParams:
        lp = self._lot.get(item.id)
        if lp is None:
            lp = self._lot[item.id] = lot_params(item, self.source(item) if item.make_buy == "buy" else None)
        return lp

    def fast_structure(self, us: Any) -> tuple[tuple[str, float, bool, Any], ...]:
        """Primary positions of a unit structure as `(child, factor, count_uom, alt group | None)` (cached)."""
        f = self._fast.get(id(us))
        if f is None:
            items = self.ds.items
            f = tuple((g.primary.item_id, g.primary.factor, is_count(items[g.primary.item_id].uom),
                       g if (g.alt_key is not None and g.alternates) else None) for g in us.groups)
            self._fast[id(us)] = f
            self._fast_keep.append(us)
        return f

    def lot_note(self, item: ItemRecord) -> str:
        n = self._note.get(item.id)
        if n is None:
            n = self._note[item.id] = lot_note(self.lot(item))
        return n

    def mlt(self, item_id: str, qty: float, on: date, serial: int | None, routing_id: str | None = None) -> int:
        return self.mlt_src(item_id, qty, on, serial, routing_id)[0]

    def mlt_src(self, item_id: str, qty: float, on: date, serial: int | None,
                routing_id: str | None = None) -> tuple[int, str]:
        k = (item_id, qty, on, serial, routing_id)
        v = self._mlt.get(k)
        if v is None:
            v = self._mlt[k] = mlt_info(self.ds, item_id, qty, on, serial, self.settings.day_minutes,
                                        override=self.lt_over.get(item_id), routing_id=routing_id,
                                        speed_cache=self.speed)
        return v

    def earliest_new(self, item: ItemRecord) -> date:
        """8.5 earliest new availability = `protect_until` (8.8)."""
        d = self._protect.get(item.id)
        if d is None:
            if item.make_buy == "buy":
                src = self.source(item)
                d = self.as_of + timedelta(days=src.lead_days + item.receiving_days)
            else:
                d = self.cal.workday_add(self.as_of, self.mlt(item.id, 1.0, self.as_of, None))
            self._protect[item.id] = d
        return d

    def lead_info(self, item: ItemRecord) -> LeadTimeInfo:
        if item.make_buy == "buy":
            src = self.source(item)
            return LeadTimeInfo(src.lead_source, src.lead_days, "calendar", item.receiving_days)
        days, source = self.mlt_src(item.id, 1.0, self.as_of, None)
        return LeadTimeInfo(source, days, "working", item.receiving_days)

    def serial_cuts(self, item_id: str) -> list[int]:
        cuts = self._cuts.get(item_id)
        if cuts is None:
            s: set[int] = set()
            for doc in list(self.ds.boms_by_item.get(item_id, ())) + list(self.ds.routings_by_item.get(item_id, ())):
                if doc.status == "released" and doc.serial_from is not None:
                    s.add(doc.serial_from)
                    s.add(doc.serial_to + 1)
            cuts = self._cuts[item_id] = sorted(s)
        return cuts

    def loc_code(self, location_id: str) -> str:
        loc = self.locations.get(location_id)
        return loc.code if loc is not None else location_id

    def lot_code(self, lot_id: str | None) -> str | None:
        if lot_id is None:
            return None
        lot = self.snap.lots.get(lot_id)
        return getattr(lot, "lot_code", None) or lot_id

    @property
    def kind(self) -> str:
        p = self.params
        if (p.as_of is not None and p.as_of != self.snap.as_of) or p.what_if_inputs():
            return "what_if"
        return "live"


# ---------------------------------------------------------------- one pass


class Pass:
    def __init__(self, ctx: Ctx, directives: Mapping[tuple[str, str], float] | None = None):
        self.c = ctx
        self.directives: dict[tuple[str, str], float] = dict(directives or {})
        self.dir_by_order: dict[str, dict[str, float]] = {}
        for (ok, k), v in sorted(self.directives.items()):
            self.dir_by_order.setdefault(ok, {})[k] = v
        self.states: dict[str, _State] = {}
        self.planned: list[_Planned] = []
        self.n_reqs = 0
        self.expired: list[Any] = []
        self.past_due: list[Sup] = []
        self.res_excess: list[tuple[Sup, Req | None, float]] = []
        self.demand_reqs: list[tuple[Req, Any, int | None]] = []
        self.outside = 0
        self.ss_reqs: list[Req] = []
        self.wo_sups: dict[str, Sup] = {}
        self._keys: dict[tuple[str, str, date], int] = {}

    # -------------------------------------------------- node factories

    def st(self, item_id: str) -> _State:
        s = self.states.get(item_id)
        if s is None:
            item = self.c.ds.items[item_id]
            s = self.states[item_id] = _State(item, self.c.llc.get(item_id, 0), self.c.earliest_new(item))
        return s

    def new_req(self, item_id: str, kind: str, need: date, qty: float, rank: tuple, rank_label: str,
                source: SourceRef, segment: SerialRange | None) -> Req:
        st = self.st(item_id)
        if st.processed:
            raise RuntimeError(f"low-level code violation: requirement for processed item {st.item.part_number}")
        self.n_reqs += 1
        if self.n_reqs > MRP_MAX_REQUIREMENTS:
            raise MrpTooLarge(MRP_MAX_REQUIREMENTS)
        st.nxt += 1
        r = Req(item_id, st.nxt, kind, need, qty, rank, rank_label, source, segment)
        st.reqs.append(r)
        return r

    def new_sup(self, item_id: str, kind: str, qty: float, avail: date, ref: SourceRef,
                exp: date | None = None) -> Sup:
        st = self.st(item_id)
        st.nxt += 1
        s = Sup(item_id, st.nxt, kind, qty, avail, ref, exp)
        st.sups.append(s)
        return s

    # -------------------------------------------------- inputs (8.3)

    def build(self) -> None:
        c = self.c
        ds, snap, as_of, items = c.ds, c.snap, c.as_of, c.ds.items
        res_by_bal: dict[str, list[Any]] = {}
        for r in sorted(snap.reservations, key=lambda r: (r.balance_id, r.wo_component_id)):
            res_by_bal.setdefault(r.balance_id, []).append(r)
        for b in sorted(snap.balances, key=lambda b: (b.item_id, b.location_id, b.lot_id or "", b.id)):
            item = items.get(b.item_id)
            # C9: held lots and stock in inactive locations are not nettable (as kitting)
            if item is None or b.qty_on_hand <= EPS or b.hold or not getattr(b, "location_active", True):
                continue
            if b.kind in ("stores", "line_side"):
                avail, kind = as_of, "stock"
            elif b.kind == "inspection":
                base = (b.last_receipt_on + timedelta(days=item.receiving_days)) if b.last_receipt_on else as_of
                avail, kind = max(as_of, base), "inspection"
            else:
                continue
            if b.expires_on is not None and b.expires_on <= as_of:
                self.expired.append(b)
                continue
            lot = c.lot_code(b.lot_id)
            label = f"Stock {c.loc_code(b.location_id)}" + (f" lot {lot}" if lot else "")
            left = b.qty_on_hand
            for r in res_by_bal.get(b.id, ()):
                q = min(r.qty, left)
                if q <= EPS:
                    continue
                s = self.new_sup(b.item_id, kind, q, avail, SourceRef("balance", b.id, f"{label} (reserved)"),
                                 b.expires_on)
                s.reserved_for, s.lot_id, s.bal = r.wo_component_id, b.lot_id, b
                left -= q
            if left > EPS:
                s = self.new_sup(b.item_id, kind, left, avail, SourceRef("balance", b.id, label), b.expires_on)
                s.lot_id, s.bal = b.lot_id, b
        for sc in sorted(snap.schedules, key=lambda s: (s.item_id, s.number, s.line_no, s.seq, s.schedule_id)):
            item = items.get(sc.item_id)
            if item is None or sc.open_qty <= EPS:
                continue
            if sc.doc_type == "po":
                if sc.doc_status not in PO_SUPPLY_STATUSES:
                    continue
            elif sc.doc_type == "pr":
                if sc.doc_status not in PR_SUPPLY_STATUSES or not c.params.include_pr_supply:
                    continue
            else:
                continue
            dock = c.sched_over.get(sc.schedule_id) or sc.confirmed_date or sc.requested_date
            avail = max(dock, as_of) + timedelta(days=item.receiving_days)
            label = f"{sc.number}/{sc.line_no}/{sc.seq}"
            s = self.new_sup(sc.item_id, sc.doc_type, sc.open_qty, avail,
                             SourceRef(f"{sc.doc_type}_schedule", sc.schedule_id, label, number=sc.number))
            s.sched, s.dock_override = sc, dock
            if dock < as_of:
                self.past_due.append(s)
        for w in sorted(snap.work_orders, key=lambda w: (w.number, w.id)):
            if w.status not in WO_SUPPLY_STATUSES or w.item_id not in items:
                continue
            due = c.wo_over.get(w.id) or w.due_date
            parent: Sup | None = None
            if w.open_qty > EPS:
                parent = self.new_sup(w.item_id, "wo", w.open_qty, max(due, as_of),
                                      SourceRef("work_order", w.id, w.number, number=w.number))
                parent.wo, parent.start, parent.due = w, w.start_date, due
                self.wo_sups[w.id] = parent
            seg = SerialRange(w.serial_from, w.serial_to) if w.serial_from is not None else None
            agg_rank = (1, w.priority, w.due_date, w.number, 0)
            for comp in w.components:
                cid, child, oq, _op = comp[0], comp[1], comp[2], comp[3]
                if child not in items or oq <= EPS:
                    continue
                ci = items[child]
                r = self.new_req(child, "wo_component", w.start_date, float(oq), agg_rank, f"P{w.priority} {w.number}",
                                 SourceRef("work_order", w.id, w.number, item_id=w.item_id,
                                           node=parent.node if parent else None, number=w.number, component_id=cid),
                                 seg if (ci.make_buy == "make" and ci.serialized) else None)
                r.parent, r.component_id, r.wo_id = parent, cid, w.id
                if parent is not None:
                    parent.comps.append(r)
        p = c.params
        flt = p.demand_filter
        excl = set(p.exclude_demand_line_ids)
        for d in sorted(snap.demand, key=lambda d: (d.number, d.line_no, d.line_id)):
            if d.item_id not in items or d.open_qty <= EPS or d.line_id in excl:
                continue
            if flt is not None:
                if flt.order_ids is not None and d.order_id not in flt.order_ids:
                    continue
                if flt.programs is not None and d.program not in flt.programs:
                    continue
                if flt.types is not None and d.demand_type not in flt.types:
                    continue
            if d.due_date > c.horizon_end:
                self.outside += 1
                continue
            prot = 0 if (d.program is not None and d.program in c.protected) else 1
            seg = SerialRange(d.serial_from, d.serial_to) if d.serial_from is not None else None
            label = f"{d.number}/{d.line_no}"
            r = self.new_req(d.item_id, "demand", d.due_date, float(d.open_qty),
                             (prot, d.effective_priority, d.due_date, d.number, d.line_no),
                             f"P{d.effective_priority} {label}", SourceRef("demand_line", d.line_id, label), seg)
            self.demand_reqs.append((r, d, None))
        for i, x in enumerate(p.extra_demand):
            if x.item_id not in items:
                continue
            seg = SerialRange(x.serial_from, x.serial_to) if x.serial_from is not None else None
            num = f"EXTRA-{i + 1:03d}"
            label = x.label or f"Extra demand {i + 1}"
            r = self.new_req(x.item_id, "extra_demand", x.due_date, float(x.qty),
                             (1, x.priority, x.due_date, num, 0), f"P{x.priority} {label}",
                             SourceRef("extra", f"extra:{i}", label), seg)
            self.demand_reqs.append((r, x, i))
        if p.safety_stock:
            for iid in c.order:
                it = items[iid]
                if it.safety_stock > EPS and it.active and it.make_buy != "phantom":
                    r = self.new_req(iid, "safety_stock", as_of, float(it.safety_stock), SS_RANK, "Safety stock",
                                     SourceRef("safety_stock", iid, f"Safety stock {it.part_number}"), None)
                    self.ss_reqs.append(r)

    # -------------------------------------------------- item processing

    @staticmethod
    def _best(sup: Sup | None, default: tuple, default_label: str) -> tuple[tuple, str]:
        if sup is None or not sup.pegs:
            return default, default_label
        best = min(sup.pegs, key=lambda pg: (pg.req.rank, pg.req.node))
        return best.req.rank, best.req.rank_label

    def process(self, st: _State) -> None:
        c = self.c
        st.processed = True
        for r in st.reqs:
            if r.kind == "wo_component" and r.parent is not None:
                r.rank, r.rank_label = self._best(r.parent, r.rank, r.rank_label)
        reserved = [s for s in st.sups if s.reserved_for is not None]
        if reserved:
            by_comp = {r.component_id: r for r in st.reqs if r.kind == "wo_component"}
            self.res_excess.extend(peg_reservations(reserved, by_comp))
        if st.reqs:
            ordered = order_requirements(st.reqs, c.params.allocation, st.protect)
            residuals = allocate(ordered, st.sups, c.as_of, st.protect)
            if residuals:
                self.size_lots(st, residuals)
        if st.planned and st.item.make_buy != "buy":
            for po in st.planned:
                self.explode(st, po)

    def _split(self, item_id: str, seg: SerialRange, q: float, count: bool) -> list[tuple[SerialRange, float]]:
        cuts = [x for x in self.c.serial_cuts(item_id) if seg.serial_from < x <= seg.serial_to]
        if not cuts:
            return [(seg, q)]
        bounds = [seg.serial_from] + cuts + [seg.serial_to + 1]
        total = seg.serial_to - seg.serial_from + 1
        out: list[tuple[SerialRange, float]] = []
        prev = 0.0
        for a, b in zip(bounds, bounds[1:]):
            cum_len = b - seg.serial_from
            cum = q * cum_len / total
            if count:
                cum = float(math.floor(cum + 0.5 + 1e-9))
            if b == bounds[-1]:
                cum = q
            pq = cum - prev
            prev = cum
            if pq > EPS:
                out.append((SerialRange(a, b - 1), pq))
        return out

    def size_lots(self, st: _State, residuals: list[tuple[Req, float]]) -> None:
        c = self.c
        item = st.item
        lp = c.lot(item)
        serial_make = item.make_buy == "make" and item.serialized
        groups: dict[tuple[int, int] | None, list[tuple[date, tuple, int, Req, float]]] = {}
        for r, q in residuals:
            d = st.protect if r.kind == "safety_stock" else r.need
            if serial_make and r.segment is not None:
                for seg, pq in self._split(item.id, r.segment, q, lp.count):
                    groups.setdefault((seg.serial_from, seg.serial_to), []).append((d, r.rank, r.node, r, pq))
            else:
                groups.setdefault(None, []).append((d, r.rank, r.node, r, q))
        keys = sorted(groups, key=lambda k: (0, 0, 0) if k is None else (1, k[0], k[1]))
        for key in keys:
            lst = sorted(groups[key], key=lambda x: (x[0], x[1], x[2]))
            seg = SerialRange(key[0], key[1]) if key is not None else None
            orders: list[_Planned] = []
            n = len(lst)
            i = 0
            while i < n:
                d, _rk, _nd, r, q = lst[i]
                q = self._use_surplus(orders, r, q, d)
                if q <= EPS:
                    i += 1
                    continue
                group = [(r, q)]
                j = i + 1
                if lp.rule == "fixed":
                    raw_target = fixed_lots(q, lp)
                else:
                    end = d + timedelta(days=lp.period_days if lp.rule == "period" else 1)
                    while j < n and lst[j][0] < end:
                        rj, qj = lst[j][3], lst[j][4]
                        qj = self._use_surplus(orders, rj, qj, lst[j][0])
                        if qj > EPS:
                            group.append((rj, qj))
                        j += 1
                    raw_target = sum(x[1] for x in group)
                qty = round_order_qty(raw_target, lp)
                qty = max(qty, sum(x[1] for x in group))
                po = self.new_planned(st, d, qty, seg, lp)
                orders.append(po)
                for rr, qq in group:
                    peg(po.sup, rr, qq)
                i = j

    @staticmethod
    def _use_surplus(orders: list[_Planned], r: Req, q: float, d: date) -> float:
        """Surplus of earlier orders of the same segment, in creation order. Exhausted leading orders are dropped
        from `orders` (surplus never grows), which keeps the scan linear."""
        while orders and orders[0].sup.qty - orders[0].sup.pegged <= EPS:
            orders.pop(0)
        for po in orders:
            if q <= EPS:
                break
            s = po.sup
            left = s.qty - s.pegged
            if left > EPS and po.need <= d:
                t = left if left < q else q
                peg(s, r, t)
                q -= t
        return q

    def new_planned(self, st: _State, d: date, qty: float, seg: SerialRange | None, lp: LotParams) -> _Planned:
        c = self.c
        item = st.item
        no = len(self.planned) + 1
        if item.make_buy == "buy":
            src = c.source(item)
            dock = d - timedelta(days=item.receiving_days)
            start = dock - timedelta(days=src.lead_days)
            kind, mlt, supplier = "buy", 0, src.supplier_id
        else:
            mlt = c.mlt(item.id, qty, max(d, c.as_of), seg.serial_from if seg else None)
            start = c.cal.workday_sub(d, mlt)
            kind, dock, supplier = "make", None, None
        segkey = seg.key() if seg else "-"
        k = (item.id, segkey, d)
        idx = self._keys.get(k, 0)
        self._keys[k] = idx + 1
        order_key = f"{item.id}:{segkey}:{d.isoformat()}:{idx}"
        label = f"Planned {'WO' if kind == 'make' else 'PR'} P-{no}"
        sup = self.new_sup(item.id, "planned", qty, d, SourceRef("planned_order", str(no), label, number=f"P-{no}"))
        sup.planned_no, sup.start, sup.mlt = no, start, mlt
        sup.due = d if kind == "make" else None
        po = _Planned(no, kind, item.id, qty, d, start, dock, sup, seg, order_key, supplier, c.lot_note(item), mlt)
        dmap = self.dir_by_order.get(order_key)
        if dmap:
            po.directives = dict(dmap)
        sup.po = po
        self.planned.append(po)
        st.planned.append(po)
        return po

    def explode(self, st: _State, po: _Planned) -> None:
        c = self.c
        on = max(po.start, c.as_of)
        us = c.structures.get(po.item_id, on, po.segment.serial_from if po.segment else None)
        po.bom_id, po.routing_id = us.bom_id, us.routing_id
        if not us.groups:
            return
        agg: dict[str, list[Any]] = {}
        qty = po.qty
        if po.directives:
            comps = apply_structure(c.ds, us, qty, directives=self.directives, order_key=po.order_key)
            groups = {g.alt_key: g for g in us.groups if g.alt_key is not None and g.alternates}
            for cn in comps:
                a = agg.get(cn.item_id)
                if a is None:
                    a = agg[cn.item_id] = [0.0, []]
                a[0] += cn.qty
                if cn.substitute_for is None and cn.alt_key in groups:
                    a[1].append((groups[cn.alt_key], cn.qty))
        else:                                    # fast path, same arithmetic as apply_structure without directives
            for child, factor, count, group in c.fast_structure(us):
                x = qty * factor
                if x <= 1e-9:
                    continue
                q = float(math.ceil(x - 1e-9)) if count else round(x, 6)
                if q <= 0:
                    continue
                a = agg.get(child)
                if a is None:
                    a = agg[child] = [0.0, []]
                a[0] += q
                if group is not None:
                    a[1].append((group, q))
        rank, rank_label = self._best(po.sup, SS_RANK, "Safety stock")
        src = SourceRef("planned_order", str(po.no), po.sup.ref.label, item_id=po.item_id, node=po.sup.node,
                        number=f"P-{po.no}")
        serial_child = c.serial_make
        start, seg, sup, okey = po.start, po.segment, po.sup, po.order_key
        comps_out = sup.comps
        for child, (q, alt) in agg.items():
            r = self.new_req(child, "planned_component", start, q, rank, rank_label, src,
                             seg if serial_child[child] else None)
            r.parent, r.order_key, r.alt = sup, okey, alt
            comps_out.append(r)

    # -------------------------------------------------- forward pass (8.10)

    def forward(self) -> None:
        c = self.c
        as_of, cal = c.as_of, c.cal
        for iid in reversed(c.order):
            st = self.states.get(iid)
            if st is None:
                continue
            item = st.item
            for s in st.sups:
                k = s.kind
                if k in ("stock", "inspection", "po", "pr"):
                    s.proj = s.avail
                elif k == "planned" and s.po.kind == "buy":
                    if s.start >= as_of:
                        s.proj = s.po.need
                    else:
                        src = c.source(item)
                        s.proj = as_of + timedelta(days=src.lead_days + item.receiving_days)
                else:                                    # make: existing WO or planned make
                    if k == "wo":
                        w = s.wo
                        mlt = s.mlt = c.mlt(iid, w.open_qty, max(w.start_date, as_of), w.serial_from,
                                            w.routing_id)
                    else:
                        mlt = s.mlt
                    comp = None
                    for r in s.comps:
                        if r.sat is not None and (comp is None or r.sat > comp):
                            comp = r.sat
                    s.comp_ready = comp
                    ready = max(s.start, as_of)
                    if comp is not None and comp > ready:
                        ready = comp
                    if ready == s.start:
                        s.proj = s.due
                    else:
                        s.proj = max(s.due, cal.workday_add(ready, mlt))
            for r in st.reqs:
                sat = None
                for pg in r.pegs:
                    pj = pg.sup.proj
                    if pj is not None and (sat is None or pj > sat):
                        sat = pj
                r.sat = sat
                if r.kind == "safety_stock":
                    r.late = 0
                    for pg in r.pegs:
                        pg.late = 0
                    continue
                r.late = max(0, (sat - r.need).days) if sat is not None else 0
                for pg in r.pegs:
                    pj = pg.sup.proj
                    pg.late = max(0, (pj - r.need).days) if pj is not None else 0

    def run(self) -> "Pass":
        self.build()
        for iid in self.c.order:
            st = self.states.get(iid)
            if st is not None:
                self.process(st)
        self.forward()
        return self


# ---------------------------------------------------------------- alternates (8.9)


def alternate_directives(p: Pass) -> tuple[dict[tuple[str, str], float], list[dict[str, Any]]]:
    c = p.c
    as_of = c.as_of
    items = c.ds.items
    cands: list[Req] = []
    for iid in c.order:
        st = p.states.get(iid)
        if st is None:
            continue
        for r in st.reqs:
            if r.kind == "planned_component" and r.alt and r.sat is not None and r.sat > max(r.need, as_of):
                cands.append(r)
    cands.sort(key=lambda r: (r.rank, r.need, items[r.item_id].part_number, r.node))
    taken: dict[str, float] = {}
    out: dict[tuple[str, str], float] = {}
    records: list[dict[str, Any]] = []

    def free_of(alt_item: str, n: date) -> float:
        st = p.states.get(alt_item)
        if st is None:
            return 0.0
        tot = 0.0
        for s in st.sups:
            if s.kind == "planned" or s.avail > n or (s.exp is not None and s.exp <= n):
                continue
            tot += max(0.0, s.qty - s.pegged)
        return tot - taken.get(alt_item, 0.0)

    for r in cands:
        n = max(r.need, as_of)
        late_left = sum(pg.qty for pg in r.pegs if pg.sup.proj is not None and pg.sup.proj > n)
        for g, pq in r.alt:
            lq = min(late_left, pq)
            if lq <= EPS:
                continue
            pf = g.primary.factor
            for i, (prio, a) in enumerate(g.alternates):
                if lq <= EPS or pf <= 0:
                    break
                ratio = a.factor / pf
                free = free_of(a.item_id, n)
                if free <= EPS or ratio <= 0:
                    continue
                take = min(lq * ratio, free)
                moved = take / ratio
                key = g.alt_key if i == 0 else f"{g.alt_key}:{prio}"
                out[(r.order_key, key)] = out.get((r.order_key, key), 0.0) + moved
                taken[a.item_id] = taken.get(a.item_id, 0.0) + take
                lq -= moved
                late_left -= moved
                records.append({"order_key": r.order_key, "primary_item_id": r.item_id, "alt_item_id": a.item_id,
                                "alt_qty": take, "primary_qty": moved, "alt_group": g.primary.line.alt_group,
                                "parent_item_id": r.parent.item_id if r.parent else None})
    return out, records


# ---------------------------------------------------------------- preflight (8.12)


def preflight(snapshot: MrpSnapshot, params: MrpParams) -> list[dict[str, Any]]:
    """Blocking issues (422 `MRP_PREFLIGHT_FAILED`), health-issue shape. Gate 1 is the caller's (B) job."""
    ds = snapshot.dataset
    as_of = params.as_of or snapshot.as_of
    horizon = params.horizon_days or int(getattr(ds.plant, "planning_horizon_days", 90) or 90)
    end = as_of + timedelta(days=horizon)
    issues: list[dict[str, Any]] = []

    def add(code: str, message: str, fix: str, etype: str, eid: str | None, label: str, fld: str | None = None):
        issues.append(HealthIssue.model_construct(
            code=code, severity="error", message=message, fix=fix,
            entity=EntityRef.model_construct(type=etype, id=eid, label=label), related=[], link=None,
            field=fld).model_dump(mode="json"))

    excl = set(params.exclude_demand_line_ids)
    for d in sorted(snapshot.demand, key=lambda d: (d.number, d.line_no, d.line_id)):
        if d.line_id in excl or d.due_date > end:
            continue
        it = ds.items.get(d.item_id)
        label = f"{d.number}/{d.line_no}"
        if it is None:
            add("MRP_OVERRIDE_UNKNOWN", f"{label} references an unknown item.", "Fix the demand line.",
                "demand_line", d.line_id, label, "item_id")
        elif not it.active:
            add("MRP_DEMAND_ITEM_INACTIVE", f"{label}: item {it.part_number} is inactive.",
                "Activate the item or close the demand line.", "demand_line", d.line_id, label, "item_id")
        elif it.make_buy == "phantom":
            add("MRP_DEMAND_ITEM_PHANTOM", f"{label}: item {it.part_number} is a phantom and cannot be planned.",
                "Order the parent item instead.", "demand_line", d.line_id, label, "item_id")
    for i, x in enumerate(params.extra_demand):
        it = ds.items.get(x.item_id)
        label = x.label or f"Extra demand {i + 1}"
        if it is None:
            add("MRP_OVERRIDE_UNKNOWN", f"{label} references an unknown item.", "Choose an existing item.",
                "extra_demand", str(i), label, "item_id")
        elif not it.active:
            add("MRP_DEMAND_ITEM_INACTIVE", f"{label}: item {it.part_number} is inactive.", "Choose an active item.",
                "extra_demand", str(i), label, "item_id")
        elif it.make_buy == "phantom":
            add("MRP_DEMAND_ITEM_PHANTOM", f"{label}: item {it.part_number} is a phantom.", "Choose a make or buy item.",
                "extra_demand", str(i), label, "item_id")
    sched_ids = {s.schedule_id for s in snapshot.schedules}
    wo_ids = {w.id for w in snapshot.work_orders}
    for o in params.supply_date_overrides:
        if o.schedule_id is not None and o.schedule_id not in sched_ids:
            add("MRP_OVERRIDE_UNKNOWN", "A supply date override references an unknown or closed schedule.",
                "Remove the override.", "purchase_schedule", o.schedule_id, o.schedule_id, "schedule_id")
        if o.wo_id is not None and o.wo_id not in wo_ids:
            add("MRP_OVERRIDE_UNKNOWN", "A supply date override references an unknown or closed work order.",
                "Remove the override.", "work_order", o.wo_id, o.wo_id, "wo_id")
    for o in params.lead_time_overrides:
        if o.item_id not in ds.items:
            add("MRP_OVERRIDE_UNKNOWN", "A lead-time override references an unknown item.", "Remove the override.",
                "item", o.item_id, o.item_id, "item_id")
    return issues


# ---------------------------------------------------------------- entry point


def run_mrp(snapshot: MrpSnapshot, params: MrpParams | None = None) -> MrpResult:
    """Pure and deterministic: same snapshot + params -> byte-identical canonical JSON of the result."""
    from .forward import build_result

    # the run allocates a large, acyclic-in-practice object graph: pausing the cyclic GC saves ~20 %
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        params = params or MrpParams()
        issues = preflight(snapshot, params)
        if issues:
            raise MrpPreflightError(issues)
        ctx = Ctx(snapshot, params)
        p1 = Pass(ctx).run()
        final, iterations, records = p1, 1, []
        if params.alternates == "when_short":
            directives, records = alternate_directives(p1)
            if directives:
                final = Pass(ctx, directives).run()
                iterations = 2
        return build_result(ctx, final, iterations, records)
    finally:
        if gc_was_enabled:
            gc.enable()


def make_snapshot(ds: MfgDataset, as_of: date, **kw: Any) -> MrpSnapshot:
    """Convenience constructor (tests, tools)."""
    return MrpSnapshot(as_of=as_of, dataset=ds, **kw)


__all__ = ["Ctx", "Pass", "alternate_directives", "make_snapshot", "preflight", "run_mrp"]
