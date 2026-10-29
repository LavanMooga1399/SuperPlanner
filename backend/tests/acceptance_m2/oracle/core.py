"""Independent MRP oracle: a deliberately naive re-implementation of M2-DESIGN section 8 (WP-D, 17.2).

Rules implemented straight from the text (section numbers in comments):
- 8.3 requirements and supplies, 8.4 low-level codes, 8.5 calendars and lead times, 8.6 lot sizing and rounding,
  8.7 explosion (scrap, cumulative yield, UoM, phantoms, alternates directives, serial segments and ECO split),
  8.8 netting/allocation (ranks, reservations first, two phases, residuals), 8.9 alternates second pass,
  8.10 forward pass and limiting path, 8.11 planned orders, 8.12 exceptions (the codes the acceptance tests use).
- M1 4.1 (effective documents), 4.4 (cumulative yields, lot inputs), 4.5 (loads), 3.2 (unit factors).

No code is shared with `superplanner` (by design: the oracle must catch the engine's mistakes, not repeat them).
Where section 8 leaves a choice open the oracle takes the reading documented in `INTERPRETATIONS` below; every
entry is reported to LEAD as a spec ambiguity (22.WP-D).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .model import (EPS, WEEKDAYS, OBom, OBomLine, ODemandProj, OException, OItem, OPeg, OPlant, OPlanned, OReq,
                    OResult, ORouting, OSup)

INTERPRETATIONS = {
    "I1": "8.4 'max lead time' in the LLC window = max item/item-supplier/supplier lead time days (calendar).",
    "I2": "8.8 rank of the components of an existing WO that no demand pegs = (1, wo.priority, wo.due_date, "
          "wo.number, 0) (the engine's reading; 8.8 only defines the pegged case). Unpegged planned orders "
          "cannot occur; they would get the safety-stock rank.",
    "I3": "8.6 residuals with segment None form their own group (never mixed with non-null segments).",
    "I4": "8.8 phase-2 applies the same expiry filter as phase 1 (expires_on > need_date).",
    "I5": "8.10 demand status: past_due (due < as_of) wins over late.",
    "I6": "8.7 per-line rounding of count-UoM children, then summed per (order, child).",
    "I7": "8.9 several alternates: the directive is split per alternate in priority order as taken in 8.9.",
    "I8": "8.10 forward pass lead time of an existing WO: on = max(start_date, as_of), serial = serial_from, primary "
          "effective routing (not WoSnap.routing_id).",
    "I9": "3.3 source resolution 'else' branch also requires an active supplier.",
    "I10": "8.3 WO component requirements carry the WO serial range as segment when the WO item is serialized.",
    "I11": "8.10 safety-stock requirements always have late_days 0 (never reported late).",
    "I13": "8.8/8.9 a requirement dated before as_of is allocated as if needed at as_of (phase 1 avail <= "
           "max(need, as_of); phase 2 above that; alternates' free supply likewise). Read literally, phase 1/2 "
           "never give as_of stock to a past-dated need when protect_until == as_of (lead time 0), and 8.9 never "
           "finds free alternate stock for an order starting in the past. late_days still count from need_date.",
    "I14": "8.7/8.9 directives are in continuous primary-need units: the late qty is capped at the primary line's "
           "unrounded need, alternate need = to_alt(moved) rounded per child, primary keeps ceil(need - moved).",
    "I12": "8.6 ECO split of a count-UoM residual: cumulative proportional quantities rounded half up.",
}

KIND_ORDER = {"stock": 0, "inspection": 1, "po": 2, "pr": 3, "wo": 4, "planned": 5}
SS_RANK = (2, 9, date.max, "", 0)
NETTABLE = ("stores", "line_side", "inspection")

# M1 3.2 unit table: code -> (dimension, factor to base)
UNITS = {"EA": ("count", 1.0), "M": ("length", 1.0), "CM": ("length", 0.01), "MM": ("length", 0.001),
         "KG": ("mass", 1.0), "G": ("mass", 0.001), "L": ("volume", 1.0), "ML": ("volume", 0.001),
         "M2": ("area", 1.0)}


class OracleError(AssertionError):
    pass


def is_count(uom: str) -> bool:
    return UNITS[uom][0] == "count"


def convert(qty: float, frm: str, to: str) -> float:
    if frm == to:
        return qty
    df, ff = UNITS[frm]
    dt, ft = UNITS[to]
    if df != dt:
        raise OracleError(f"unit mismatch {frm} -> {to}")
    return qty * ff / ft


def ceil_eps(x: float) -> float:
    return float(math.ceil(x - 1e-9))


# ---------------------------------------------------------------- calendar (8.5)


class Cal:
    def __init__(self, workdays: tuple[str, ...], holidays: frozenset[date]):
        self.wd = {WEEKDAYS.index(w) for w in workdays}
        self.holidays = holidays

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.wd and d not in self.holidays

    def add(self, d: date, n: int) -> date:
        if n == 0:
            while not self.is_workday(d):
                d += timedelta(days=1)
            return d
        k = 0
        while k < n:
            d += timedelta(days=1)
            if self.is_workday(d):
                k += 1
        return d

    def sub(self, d: date, n: int) -> date:
        if n == 0:
            while not self.is_workday(d):
                d -= timedelta(days=1)
            return d
        k = 0
        while k < n:
            d -= timedelta(days=1)
            if self.is_workday(d):
                k += 1
        return d


# ---------------------------------------------------------------- effectivity (M1 4.1)


def _effective(doc: Any, on: date, serial: int | None) -> bool:
    if doc.status != "released":
        return False
    if doc.effective_from is not None and doc.effective_from > on:
        return False
    if doc.effective_to is not None and not on < doc.effective_to:
        return False
    if doc.serial_from is None:
        return True
    return serial is not None and doc.serial_from <= serial <= doc.serial_to


def _pick(docs: list[Any], on: date, serial: int | None) -> Any | None:
    cands = [d for d in docs if _effective(d, on, serial)]
    specific = [d for d in cands if d.serial_from is not None]
    pool = specific or cands
    if not pool:
        return None
    return max(pool, key=lambda d: (d.effective_from or date.min, d.version, d.revision, d.id))


# ---------------------------------------------------------------- explosion record


@dataclass
class _AltGroup:
    alt_group: str
    primary: OBomLine
    alternates: list[OBomLine]
    primary_need: float          # child UoM, rounded (count) - before directives


@dataclass
class _Order:
    planned: OPlanned
    supply: OSup
    alt_groups: list[_AltGroup] = field(default_factory=list)


@dataclass
class _Entry:
    req: OReq
    qty: float
    need: date
    segment: tuple[int, int] | None


# ---------------------------------------------------------------- the oracle


class Oracle:
    def __init__(self, plant: OPlant):
        self.p = plant
        self.par = plant.params
        self.as_of = plant.params.as_of
        hd = plant.params.horizon_days if plant.params.horizon_days is not None else plant.planning_horizon_days
        self.horizon_end = self.as_of + timedelta(days=hd)
        self.cal = Cal(plant.workdays, plant.holidays)
        self.items = plant.items
        self.boms_by_item: dict[str, list[OBom]] = defaultdict(list)
        for b in plant.boms:
            self.boms_by_item[b.item_id].append(b)
        self.routings_by_item: dict[str, list[ORouting]] = defaultdict(list)
        for r in plant.routings:
            self.routings_by_item[r.item_id].append(r)
        self.balances = {b.id: b for b in plant.balances}
        self.schedules = {s.schedule_id: s for s in plant.schedules}
        self.wos = {w.id: w for w in plant.work_orders}
        self._check_preflight()

    # ------------------------------------------------------------ preflight (8.12)
    def _check_preflight(self) -> None:
        for d in self.p.demand:
            it = self.items.get(d.item_id)
            if it is None or not it.active or it.make_buy == "phantom":
                raise OracleError(f"preflight: demand line {d.line_id} on an inactive/phantom/unknown item")
        for x in self.par.extra_demand:
            if x.item_id not in self.items:
                raise OracleError("preflight: MRP_OVERRIDE_UNKNOWN extra demand")

    # ------------------------------------------------------------ documents
    def effective_bom(self, item_id: str, on: date, serial: int | None) -> OBom | None:
        return _pick(self.boms_by_item.get(item_id, []), on, serial)

    def primary_routing(self, item_id: str, on: date, serial: int | None) -> ORouting | None:
        by_prio: dict[int, list[ORouting]] = defaultdict(list)
        for r in self.routings_by_item.get(item_id, []):
            by_prio[r.priority].append(r)
        for prio in sorted(by_prio):
            hit = _pick(by_prio[prio], on, serial)
            if hit is not None:
                return hit
        return None

    # ------------------------------------------------------------ sources and lead times (3.3, 8.5)
    def _row_lt(self, row: Any) -> int | None:
        if row.lead_time_days is not None:
            return row.lead_time_days
        sup = self.p.suppliers.get(row.supplier_id)
        if sup is not None and sup.lead_time_days is not None:
            return sup.lead_time_days
        return self.items[row.item_id].lead_time_days

    def source(self, item_id: str) -> Any | None:
        rows = [r for r in self.p.item_suppliers if r.item_id == item_id and r.active
                and self.p.suppliers.get(r.supplier_id) is not None and self.p.suppliers[r.supplier_id].active]
        pref = [r for r in rows if r.preferred]
        if pref:
            return sorted(pref, key=lambda r: self.p.suppliers[r.supplier_id].code)[0]
        if not rows:
            return None
        return min(rows, key=lambda r: (self._row_lt(r) if self._row_lt(r) is not None else 10 ** 9,
                                        self.p.suppliers[r.supplier_id].code))

    def purchase_lt(self, item_id: str) -> int:
        if item_id in self.par.lead_time_overrides:
            return int(self.par.lead_time_overrides[item_id])
        row = self.source(item_id)
        if row is not None:
            lt = self._row_lt(row)
        else:
            lt = self.items[item_id].lead_time_days
        return int(lt or 0)

    def lot_params(self, item_id: str) -> tuple[float, float, float]:
        it = self.items[item_id]
        row = self.source(item_id) if it.make_buy == "buy" else None
        moq = row.min_order_qty if row is not None and row.min_order_qty > 0 else it.min_order_qty
        mult = row.order_multiple if row is not None and row.order_multiple > 0 else it.order_multiple
        pack = row.units_per_purchase_unit if row is not None else 1.0
        return moq, mult, pack

    def round_chain(self, item_id: str, q: float) -> float:
        """8.6 steps 2-5."""
        it = self.items[item_id]
        moq, mult, pack = self.lot_params(item_id)
        q = max(q, moq)
        if mult > 0:
            q = math.ceil(q / mult - 1e-9) * mult
        if it.make_buy == "buy" and pack > 1:
            q = math.ceil(q / pack - 1e-9) * pack
        return ceil_eps(q) if is_count(it.uom) else round(q, 6)

    def _yields(self, routing: ORouting | None) -> tuple[list[Any], list[float]]:
        ops = sorted(routing.ops, key=lambda o: o.seq) if routing is not None else []
        ys = [o.yield_pct / 100.0 for o in ops]
        cum = [1.0] * (len(ops) + 1)
        for k in range(len(ops) - 1, -1, -1):
            cum[k] = cum[k + 1] * ys[k]
        return ops, cum

    def mld(self, item_id: str, qty: float, on: date, serial: int | None) -> int:
        """8.5 manufacturing_lead_days."""
        if item_id in self.par.lead_time_overrides:
            return int(self.par.lead_time_overrides[item_id])
        it = self.items[item_id]
        if it.lead_time_days is not None:
            return int(it.lead_time_days)
        r = self.primary_routing(item_id, on, serial)
        if r is None:
            return 0
        ops, cum = self._yields(r)
        n = len(ops)
        inputs = [0.0] * n
        if is_count(it.uom):
            nxt = qty
            for k in range(n - 1, -1, -1):
                inputs[k] = ceil_eps(nxt / (ops[k].yield_pct / 100.0))
                nxt = inputs[k]
        else:
            for k in range(n):
                inputs[k] = qty / cum[k]
        minutes = 0.0
        for k, op in enumerate(ops):
            if op.run_per == "panel":
                loads = ceil_eps(inputs[k] / op.units_per_panel)
            elif op.run_per == "batch":
                loads = ceil_eps(inputs[k] / op.units_per_batch)
            else:
                loads = inputs[k]
            minutes += (op.queue_minutes + op.setup_minutes + op.run_minutes * loads / self._best_speed(it, op)
                        + op.move_minutes + op.wait_minutes)
        if minutes <= 0:
            return 0
        return int(math.ceil(minutes / self.p.day_minutes - 1e-9))

    def _best_speed(self, it: OItem, op: Any) -> float:
        best = None
        for ln in self.p.lines:
            if ln.group_id != op.group_id or not ln.active:
                continue
            elig = (not ln.eligible_families and not ln.eligible_item_ids) or \
                (it.family is not None and it.family in ln.eligible_families) or it.id in ln.eligible_item_ids
            if elig and (best is None or ln.speed_factor > best):
                best = ln.speed_factor
        return best if best is not None else 1.0

    def protect_until(self, item_id: str) -> date:
        """8.8 step 3 = earliest new availability (8.5)."""
        it = self.items[item_id]
        if it.make_buy == "buy":
            return self.as_of + timedelta(days=self.purchase_lt(item_id) + it.receiving_days)
        return self.cal.add(self.as_of, self.mld(item_id, 1, self.as_of, None))

    # ------------------------------------------------------------ explosion (8.7)
    def explode(self, item_id: str, qty: float, on: date, serial: int | None,
                directives: dict[tuple[str, str, str], float], order_key: str
                ) -> tuple[OBom | None, ORouting | None, list[tuple[str, float]], list[_AltGroup]]:
        bom = self.effective_bom(item_id, on, serial)
        routing = self.primary_routing(item_id, on, serial)
        if bom is None:
            return None, routing, [], []
        ops, cum = self._yields(routing)
        seq_index = {o.seq: k for k, o in enumerate(ops)}
        out: list[tuple[str, float]] = []
        groups: list[_AltGroup] = []
        alts_by_group: dict[str, list[OBomLine]] = defaultdict(list)
        for ln in bom.lines:
            if ln.alt_group is not None and ln.alt_priority != 1:
                alts_by_group[ln.alt_group].append(ln)
        for ln in sorted(bom.lines, key=_line_order):
            if ln.alt_group is not None and ln.alt_priority != 1:
                continue
            k = seq_index.get(ln.operation_seq, 0) if ln.operation_seq is not None else 0
            y = cum[k] if ops else 1.0
            base = qty / y * ln.qty_per * (1 + ln.scrap_pct / 100.0)
            child = self.items[ln.child_id]
            need_child = convert(base, ln.uom, child.uom)
            if child.make_buy == "phantom":
                self._explode_phantom(ln.child_id, need_child, on, serial, out, depth=1)
                continue
            rounded = ceil_eps(need_child) if is_count(child.uom) else need_child
            if ln.alt_group is not None and alts_by_group.get(ln.alt_group):
                alts = sorted(alts_by_group[ln.alt_group], key=lambda a: a.alt_priority)
                groups.append(_AltGroup(ln.alt_group, ln, alts, need_child))    # I14: continuous need
                moved_total = 0.0
                for a in alts:
                    moved = directives.get((order_key, ln.alt_group, a.id), 0.0)
                    if moved <= EPS:
                        continue
                    moved_total += moved
                    a_child = self.items[a.child_id]
                    a_need = self.to_alt(moved, ln, a)
                    out.append((a.child_id, ceil_eps(a_need) if is_count(a_child.uom) else a_need))
                rest = max(0.0, need_child - moved_total)
                rounded = ceil_eps(rest) if is_count(child.uom) else rest
            out.append((ln.child_id, rounded))
        return bom, routing, out, groups

    def _explode_phantom(self, phantom_id: str, qty: float, on: date, serial: int | None,
                         out: list[tuple[str, float]], depth: int) -> None:
        if depth > 50:
            raise OracleError("phantom nesting too deep")
        bom = self.effective_bom(phantom_id, on, serial)
        if bom is None:
            return
        for ln in sorted(bom.lines, key=_line_order):
            if ln.alt_group is not None and ln.alt_priority != 1:
                continue
            base = qty * ln.qty_per * (1 + ln.scrap_pct / 100.0)
            child = self.items[ln.child_id]
            need_child = convert(base, ln.uom, child.uom)
            if child.make_buy == "phantom":
                self._explode_phantom(ln.child_id, need_child, on, serial, out, depth + 1)
            else:
                out.append((ln.child_id, ceil_eps(need_child) if is_count(child.uom) else need_child))

    def to_alt(self, prim_qty: float, prim: OBomLine, alt: OBomLine) -> float:
        """8.7: alternate need = moved x alt.qty_per / primary.qty_per x (1 + alt.scrap)/(1 + primary.scrap)."""
        pq = convert(prim_qty, self.items[prim.child_id].uom, prim.uom)
        aq = pq * alt.qty_per / prim.qty_per * (1 + alt.scrap_pct / 100.0) / (1 + prim.scrap_pct / 100.0)
        return convert(aq, alt.uom, self.items[alt.child_id].uom)

    def from_alt(self, alt_qty: float, prim: OBomLine, alt: OBomLine) -> float:
        aq = convert(alt_qty, self.items[alt.child_id].uom, alt.uom)
        pq = aq * prim.qty_per / alt.qty_per * (1 + prim.scrap_pct / 100.0) / (1 + alt.scrap_pct / 100.0)
        return convert(pq, prim.uom, self.items[prim.child_id].uom)

    # ------------------------------------------------------------ low-level codes (8.4)
    def llc(self) -> dict[str, int]:
        max_lt = max([i.lead_time_days or 0 for i in self.items.values()]
                     + [r.lead_time_days or 0 for r in self.p.item_suppliers]
                     + [s.lead_time_days or 0 for s in self.p.suppliers.values()] + [0])
        lo, hi = self.as_of, self.horizon_end + timedelta(days=max_lt)
        children: dict[str, set[str]] = defaultdict(set)
        for b in self.p.boms:
            if b.status != "released":
                continue
            if b.effective_from is not None and b.effective_from > hi:
                continue
            if b.effective_to is not None and b.effective_to <= lo:
                continue
            for ln in b.lines:
                children[b.item_id].add(ln.child_id)
        for w in self.p.work_orders:
            for c in w.components:
                children[w.item_id].add(c.item_id)
        level: dict[str, int] = {i: 0 for i in self.items}
        # longest path by naive relaxation (graph is acyclic; |V| rounds suffice)
        for _ in range(len(self.items) + 1):
            changed = False
            for parent in sorted(children):
                for ch in sorted(children[parent]):
                    if level.get(ch, 0) < level.get(parent, 0) + 1:
                        level[ch] = level.get(parent, 0) + 1
                        changed = True
            if not changed:
                break
        else:
            raise OracleError("cycle in the LLC graph")
        return level

    # ------------------------------------------------------------ run
    def run(self) -> OResult:
        res1 = _Pass(self, {}).run()
        if self.par.alternates == "when_short":
            directives = self._alt_directives(res1)
            if directives:
                res2 = _Pass(self, directives).run()
                res2.result.iterations = 2
                res2.result.directives = {(k[0], k[1]): v for k, v in _sum_dirs(directives).items()}
                for (okey, grp), qty in sorted(res2.result.directives.items()):
                    po = next((o.planned for o in res2.orders.values() if o.planned.order_key == okey), None)
                    res2.result.exceptions.append(OException(
                        "MRP_ALTERNATE_USED", "info", po.item_id if po else None,
                        ("planned_order", po.planned_no if po else okey), qty=qty))
                res2.result.exceptions.sort(key=_exc_sort)
                return res2.result
        return res1.result

    def _alt_directives(self, pass1: "_Pass") -> dict[tuple[str, str, str], float]:
        """8.9: late primary planned_component requirements of alternate groups, in rank order."""
        cands = []
        for order in pass1.orders.values():
            for g in order.alt_groups:
                child = g.primary.child_id
                req = next((r for r in pass1.reqs[child] if r.kind == "planned_component"
                            and r.source == ("planned_component", order.planned.planned_no)), None)
                if req is None or req.satisfied_date is None:
                    continue
                eff = max(req.need_date, self.as_of)        # I13: nothing can come before as_of
                if req.satisfied_date <= eff:
                    continue
                sups = {s.node: s for s in pass1.sups[child]}
                late = sum(pg.qty for pg in req.pegs if sups[pg.supply_node].projected_date > eff)
                late = min(late, g.primary_need)
                if late > EPS:
                    cands.append(((req.rank, req.need_date, self.items[child].part_number, req.node), order, g, req,
                                  late))
        cands.sort(key=lambda c: c[0])
        taken: dict[str, float] = defaultdict(float)
        directives: dict[tuple[str, str, str], float] = defaultdict(float)
        for _, order, g, req, late in cands:
            for a in g.alternates:
                if late <= EPS:
                    break
                need = max(req.need_date, self.as_of)        # I13
                free = sum(s.remaining for s in pass1.sups[a.child_id]
                           if s.kind != "planned" and s.remaining > EPS and s.avail_date <= need
                           and (s.expires_on is None or s.expires_on > need)) - taken[a.child_id]
                if free <= EPS:
                    continue
                take = min(self.to_alt(late, g.primary, a), free)
                prim_eq = self.from_alt(take, g.primary, a)
                taken[a.child_id] += take
                directives[(order.planned.order_key, g.alt_group, a.id)] += prim_eq
                late -= prim_eq
        return dict(directives)


def _sum_dirs(d: dict[tuple[str, str, str], float]) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = defaultdict(float)
    for (k, g, _a), v in d.items():
        out[(k, g)] += v
    return dict(out)


def _natural(fn: str) -> tuple[int, int, str]:
    return (0, int(fn), "") if fn.isdigit() else (1, 0, fn)


def _line_order(ln: OBomLine) -> tuple[Any, ...]:
    return (_natural(ln.find_number), ln.alt_group or "", ln.alt_priority, ln.child_id, ln.id)


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
CODE_ORDER = {c: i for i, c in enumerate((
    "MRP_DEMAND_LATE", "MRP_DEMAND_PAST_DUE", "MRP_SHORTAGE", "MRP_START_IN_PAST", "MRP_EXPEDITE",
    "MRP_PAST_DUE_SUPPLY", "MRP_WO_LATE", "MRP_EXPIRED_STOCK", "MRP_EXPIRING_STOCK", "MRP_CANCEL", "MRP_REDUCE",
    "MRP_DEFER", "MRP_RELEASE_NOW", "MRP_BELOW_SAFETY_STOCK", "MRP_ALTERNATE_USED", "MRP_NO_SUPPLIER",
    "MRP_MERGE_INTO_PR", "MRP_DEMAND_SERIAL_OVERLAP", "MRP_RESERVATION_EXCESS", "MRP_WO_COMPONENT_CYCLE",
    "MRP_DEMAND_OUTSIDE_HORIZON"))}


def _exc_sort(e: OException) -> tuple[Any, ...]:
    return (SEVERITY_ORDER[e.severity], CODE_ORDER[e.code], e.date or date.min, str(e.item_id), str(e.subject))


class _Pass:
    """One planning pass (8.8 for every item in LLC order, then 8.10)."""

    def __init__(self, o: Oracle, directives: dict[tuple[str, str, str], float]):
        self.o = o
        self.dirs = directives
        self.reqs: dict[str, list[OReq]] = defaultdict(list)
        self.sups: dict[str, list[OSup]] = defaultdict(list)
        self.orders: dict[int, _Order] = {}
        self.planned: list[OPlanned] = []
        self.exceptions: list[OException] = []
        self.key_counts: dict[tuple[str, Any, date], int] = defaultdict(int)
        self.demand_req: dict[tuple[Any, ...], OReq] = {}
        self.wo_supply: dict[str, OSup] = {}

    # ------------------------------------------------------------ helpers
    def add_req(self, item_id: str, **kw: Any) -> OReq:
        r = OReq(item_id=item_id, node=len(self.reqs[item_id]) + 1, **kw)
        self.reqs[item_id].append(r)
        return r

    def add_sup(self, item_id: str, **kw: Any) -> OSup:
        s = OSup(item_id=item_id, node=len(self.sups[item_id]) + 1, **kw)
        self.sups[item_id].append(s)
        return s

    def peg(self, r: OReq, s: OSup, qty: float) -> None:
        if qty <= EPS:
            return
        pg = OPeg(s.item_id, s.node, r.item_id, r.node, qty)
        r.pegs.append(pg)
        s.pegs.append(pg)
        s.pegged += qty

    def rank_of(self, r: OReq) -> tuple[Any, ...]:
        o = self.o
        if r.kind == "demand":
            d = r.source[2]
            prot = 0 if d.program is not None and d.program in o.par.protect_programs else 1
            return (prot, d.priority, d.due_date, d.number, d.line_no)
        if r.kind == "extra_demand":
            x = r.source[2]
            return (1, x.priority, x.due_date, x.label, r.source[1])
        if r.kind == "safety_stock":
            return SS_RANK
        parent = self._parent_supply(r)
        ranks = [self.reqs[pg.requirement_item_id][pg.requirement_node - 1].rank for pg in parent.pegs]
        if ranks:
            return min(ranks)
        if r.kind == "wo_component":       # I2: an unpegged WO ranks by its own priority / due date / number
            w = o.wos[r.source[1]]
            return (1, w.priority, w.due_date, w.number, 0)
        return SS_RANK

    def _parent_supply(self, r: OReq) -> OSup:
        if r.kind == "wo_component":
            return self.wo_supply[r.source[1]]
        return self.orders[r.source[1]].supply

    # ------------------------------------------------------------ inputs (8.3)
    def _inputs(self) -> None:
        o = self.o
        par = o.par
        flt = par.demand_filter or {}
        self.outside_horizon = 0
        for d in sorted(o.p.demand, key=lambda d: (d.number, d.line_no)):
            if d.open_qty <= EPS:
                continue
            if flt.get("order_ids") is not None and d.order_id not in flt["order_ids"]:
                continue
            if flt.get("programs") is not None and d.program not in flt["programs"]:
                continue
            if flt.get("types") is not None and d.demand_type not in flt["types"]:
                continue
            if d.line_id in par.exclude_demand_line_ids:
                continue
            if d.due_date > o.horizon_end:
                self.outside_horizon += 1
                continue
            seg = (d.serial_from, d.serial_to) if d.serial_from is not None else None
            r = self.add_req(d.item_id, kind="demand", need_date=d.due_date, qty=d.open_qty,
                             source=("demand", d.line_id, d), segment=seg)
            self.demand_req[("demand", d.line_id)] = r
        for idx, x in enumerate(par.extra_demand):
            if x.due_date > o.horizon_end:
                continue
            seg = (x.serial_from, x.serial_to) if x.serial_from is not None else None
            r = self.add_req(x.item_id, kind="extra_demand", need_date=x.due_date, qty=x.qty,
                             source=("extra", idx, x), segment=seg)
            self.demand_req[("extra", idx)] = r
        if par.safety_stock:
            for it in sorted(o.items.values(), key=lambda i: i.part_number):
                if it.safety_stock > EPS and it.active and it.make_buy != "phantom":
                    self.add_req(it.id, kind="safety_stock", need_date=o.as_of, qty=it.safety_stock,
                                 source=("ss", it.id))
        # existing supply: stock (one supply per nettable balance; reserved split off)
        rsv_by_bal: dict[str, list[Any]] = defaultdict(list)
        for rv in o.p.reservations:
            rsv_by_bal[rv.balance_id].append(rv)
        for b in sorted(o.p.balances, key=lambda b: (b.item_id, b.location_id, b.lot_code or "")):
            if b.location_kind not in NETTABLE or b.qty_on_hand <= EPS or b.hold:
                continue
            if b.expires_on is not None and b.expires_on <= o.as_of:
                self.exceptions.append(OException("MRP_EXPIRED_STOCK", "warning", b.item_id, ("lot", b.lot_id),
                                                  date=b.expires_on, qty=b.qty_on_hand))
                continue
            it = o.items[b.item_id]
            kind = "inspection" if b.location_kind == "inspection" else "stock"
            avail = o.as_of
            if kind == "inspection":
                avail = max(o.as_of, (b.last_receipt_on or o.as_of) + timedelta(days=it.receiving_days))
            reserved = 0.0
            for rv in sorted(rsv_by_bal.get(b.id, []), key=lambda r: r.wo_component_id):
                q = min(rv.qty, b.qty_on_hand - reserved)
                if q <= EPS:
                    continue
                reserved += q
                self.add_sup(b.item_id, kind=kind, qty=q, avail_date=avail, expires_on=b.expires_on,
                             ref=("reservation", b.id, rv.wo_component_id), bound_component_id=rv.wo_component_id)
            free = b.qty_on_hand - reserved
            if free > EPS:
                self.add_sup(b.item_id, kind=kind, qty=free, avail_date=avail, expires_on=b.expires_on,
                             ref=("balance", b.id))
        # PO / PR schedules (5.5)
        for s in sorted(o.p.schedules, key=lambda s: (s.doc_type != "po", s.number, s.line_no, s.seq)):
            if s.open_qty <= EPS:
                continue
            if s.doc_type == "pr" and (not par.include_pr_supply or s.doc_status not in
                                       ("draft", "submitted", "approved")):
                continue
            if s.doc_type == "po" and s.doc_status not in ("draft", "open", "partially_received"):
                continue
            dock = par.supply_date_overrides.get(s.schedule_id) or s.confirmed_date or s.requested_date
            it = o.items[s.item_id]
            avail = max(dock, o.as_of) + timedelta(days=it.receiving_days)
            self.add_sup(s.item_id, kind=s.doc_type, qty=s.open_qty, avail_date=avail, ref=("schedule", s.schedule_id))
            if (s.confirmed_date or s.requested_date) < o.as_of:
                self.exceptions.append(OException("MRP_PAST_DUE_SUPPLY", "warning", s.item_id,
                                                  (f"{s.doc_type}_schedule", s.schedule_id),
                                                  date=s.confirmed_date or s.requested_date, qty=s.open_qty))
        # existing WOs and their component requirements
        for w in sorted(o.p.work_orders, key=lambda w: w.number):
            if w.status not in ("planned", "released", "in_progress"):
                continue
            due = par.supply_date_overrides.get(w.id) or w.due_date
            sup = None
            if w.open_qty > EPS:
                sup = self.add_sup(w.item_id, kind="wo", qty=w.open_qty, avail_date=max(due, o.as_of),
                                   ref=("wo", w.id), start_date=w.start_date, due_date=due)
            else:
                sup = OSup(item_id=w.item_id, node=0, kind="wo", qty=0, avail_date=max(due, o.as_of),
                           ref=("wo", w.id), start_date=w.start_date, due_date=due)
            self.wo_supply[w.id] = sup
            seg = (w.serial_from, w.serial_to) if (w.serial_from is not None and o.items[w.item_id].serialized) \
                else None
            for c in w.components:
                if c.open_qty <= EPS:
                    continue
                r = self.add_req(c.item_id, kind="wo_component", need_date=w.start_date, qty=c.open_qty,
                                 source=("wo_component", w.id, c.id), segment=seg)
                sup.component_nodes.append((c.item_id, r.node))

    # ------------------------------------------------------------ netting of one item (8.8)
    def _net(self, item_id: str) -> None:
        o = self.o
        it = o.items[item_id]
        R = self.reqs.get(item_id, [])
        if it.make_buy == "phantom":
            if R:
                raise OracleError(f"requirement on phantom {it.part_number}")
            return
        for r in R:
            r.rank = self.rank_of(r)
        S = self.sups.get(item_id, [])
        # step 2: reserved supply first
        comp_req = {r.source[2]: r for r in R if r.kind == "wo_component"}
        for s in S:
            if s.bound_component_id is None:
                continue
            r = comp_req.get(s.bound_component_id)
            if r is not None:
                self.peg(r, s, min(s.remaining, r.qty - r.pegged))
            if s.remaining > EPS:
                w = next((x for x in o.p.work_orders if any(c.id == s.bound_component_id for c in x.components)),
                         None)
                self.exceptions.append(OException("MRP_RESERVATION_EXCESS", "info", item_id,
                                                  ("work_order", w.id if w else None), qty=s.remaining))
            s.bound_component_id = None
        pu = o.protect_until(item_id)

        def order_key(r: OReq) -> tuple[Any, ...]:
            if o.par.allocation == "priority":
                if r.need_date < pu:
                    return (0, r.rank, r.need_date, r.node)
                return (1, r.need_date, r.rank, r.node)
            return (r.need_date, r.rank, r.node)

        def sup_key(s: OSup) -> tuple[Any, ...]:
            return (s.avail_date, s.expires_on or date.max, KIND_ORDER[s.kind], s.node)

        residuals: list[tuple[OReq, float]] = []
        for r in sorted(R, key=order_key):
            rem = r.qty - r.pegged
            need = max(r.need_date, o.as_of)          # I13: past-dated needs are served from as_of on
            if rem > EPS:
                ph1 = sorted((s for s in S if s.remaining > EPS and s.avail_date <= need
                              and (s.expires_on is None or s.expires_on > need)), key=sup_key)
                for s in ph1:
                    if rem <= EPS:
                        break
                    q = min(rem, s.remaining)
                    self.peg(r, s, q)
                    rem -= q
            if rem > EPS:
                ph2 = sorted((s for s in S if s.remaining > EPS and need < s.avail_date < pu
                              and (s.expires_on is None or s.expires_on > need)), key=sup_key)
                for s in ph2:
                    if rem <= EPS:
                        break
                    q = min(rem, s.remaining)
                    self.peg(r, s, q)
                    rem -= q
            if rem > EPS:
                residuals.append((r, rem))
        if residuals:
            self._lot_size(item_id, residuals, pu)

    # ------------------------------------------------------------ lot sizing (8.6)
    def _split_segment(self, item_id: str, seg: tuple[int, int], qty: float) -> list[tuple[tuple[int, int], float]]:
        o = self.o
        points: set[int] = set()
        for d in list(o.boms_by_item.get(item_id, [])) + list(o.routings_by_item.get(item_id, [])):
            if d.status == "released" and d.serial_from is not None:
                points.add(d.serial_from)
                points.add(d.serial_to + 1)
        a, z = seg
        cuts = sorted(p for p in points if a < p <= z)
        bounds = [a] + cuts + [z + 1]
        pieces = [(bounds[i], bounds[i + 1] - 1) for i in range(len(bounds) - 1)]
        if len(pieces) == 1:
            return [(seg, qty)]
        total = z - a + 1
        out = []
        prev = 0.0
        acc = 0
        count = is_count(o.items[item_id].uom)
        for lo, hi in pieces:
            acc += hi - lo + 1
            cum = qty * acc / total
            if count:
                cum = math.floor(cum + 0.5)
            out.append(((lo, hi), cum - prev))
            prev = cum
        return [(s, q) for s, q in out if q > EPS]

    def _lot_size(self, item_id: str, residuals: list[tuple[OReq, float]], pu: date) -> None:
        o = self.o
        it = o.items[item_id]
        serial_make = it.make_buy == "make" and it.serialized
        entries: list[_Entry] = []
        for r, q in residuals:
            need = r.need_date if r.kind != "safety_stock" else max(o.as_of, pu)
            seg = r.segment if serial_make else None
            if seg is not None:
                for sp, qp in self._split_segment(item_id, seg, q):
                    entries.append(_Entry(r, qp, need, sp))
            else:
                entries.append(_Entry(r, q, need, None))
        entries.sort(key=lambda e: (e.need, e.req.rank, e.req.node, e.segment or (0, 0)))
        groups: dict[Any, list[_Entry]] = {}
        for e in entries:
            groups.setdefault(e.segment, []).append(e)
        for seg, ents in groups.items():
            surplus: list[OSup] = []

            def consume(e: _Entry) -> float:
                rem = e.qty
                for s in surplus:
                    if rem <= EPS:
                        break
                    if s.remaining > EPS and s.avail_date <= e.need:
                        q = min(rem, s.remaining)
                        self.peg(e.req, s, q)
                        rem -= q
                return rem

            rule = it.lot_rule
            i = 0
            while i < len(ents):
                e = ents[i]
                if rule == "lot_for_lot":
                    same = [x for x in ents[i:] if x.need == e.need]
                    rems = [(x, consume(x)) for x in same]
                    i += len(same)
                    total = sum(q for _, q in rems if q > EPS)
                    if total > EPS:
                        s = self._new_order(item_id, total, e.need, seg)
                        for x, q in rems:
                            if q > EPS:
                                self.peg(x.req, s, q)
                        surplus.append(s)
                elif rule == "fixed":
                    i += 1
                    rem = consume(e)
                    if rem > EPS:
                        f = it.fixed_lot_qty
                        s = self._new_order(item_id, math.ceil(rem / f - 1e-9) * f, e.need, seg)
                        self.peg(e.req, s, rem)
                        surplus.append(s)
                elif rule == "period":
                    rem = consume(e)
                    i += 1
                    if rem > EPS:
                        end = e.need + timedelta(days=it.lot_period_days)
                        window = [(e, rem)]
                        while i < len(ents) and ents[i].need < end:
                            x = ents[i]
                            window.append((x, consume(x)))
                            i += 1
                        total = sum(q for _, q in window if q > EPS)
                        s = self._new_order(item_id, total, e.need, seg)
                        for x, q in window:
                            if q > EPS:
                                self.peg(x.req, s, q)
                        surplus.append(s)
                else:
                    raise OracleError(f"unknown lot rule {rule}")

    def _new_order(self, item_id: str, q_raw: float, need: date, seg: tuple[int, int] | None) -> OSup:
        o = self.o
        it = o.items[item_id]
        q = o.round_chain(item_id, q_raw)
        no = len(self.planned) + 1
        kk = (item_id, seg, need)
        okey = f"{item_id}:{'' if seg is None else f'{seg[0]}-{seg[1]}'}:{need.isoformat()}:{self.key_counts[kk]}"
        self.key_counts[kk] += 1
        if it.make_buy == "make":
            n = o.mld(item_id, q, max(need, o.as_of), seg[0] if seg else None)
            start = o.cal.sub(need, n)
            dock = None
            supplier = None
            kind = "make"
        else:
            dock = need - timedelta(days=it.receiving_days)
            start = dock - timedelta(days=o.purchase_lt(item_id))
            row = o.source(item_id)
            supplier = row.supplier_id if row is not None else None
            kind = "buy"
        if start < o.as_of:
            rs = "start_in_past"
        elif start <= o.as_of + timedelta(days=o.p.release_window_days):
            rs = "release_now"
        else:
            rs = "later"
        po = OPlanned(planned_no=no, kind=kind, item_id=item_id, qty=q, need_date=need, start_date=start,
                      dock_date=dock, segment=seg, order_key=okey, supplier_id=supplier, release_status=rs,
                      projected_start=max(start, o.as_of))
        sup = self.add_sup(item_id, kind="planned", qty=q, avail_date=need, ref=("planned", no), planned_no=no,
                           start_date=start, due_date=need)
        po.supply_node = sup.node
        self.planned.append(po)
        self.orders[no] = _Order(po, sup)
        return sup

    def _explode_orders(self, item_id: str) -> None:
        o = self.o
        for order in [x for x in self.orders.values() if x.planned.item_id == item_id and x.planned.kind == "make"]:
            po = order.planned
            if order.supply.component_nodes or getattr(order, "_exploded", False):
                continue
            order._exploded = True  # type: ignore[attr-defined]
            on = max(po.start_date, o.as_of)
            serial = po.segment[0] if po.segment else None
            bom, routing, needs, groups = o.explode(item_id, po.qty, on, serial, self.dirs, po.order_key)
            po.bom_id = bom.id if bom else None
            po.routing_id = routing.id if routing else None
            order.alt_groups = groups
            agg: dict[str, float] = {}
            for child, q in needs:
                agg[child] = agg.get(child, 0.0) + q
            for child, q in agg.items():
                if q <= EPS:
                    continue
                r = self.add_req(child, kind="planned_component", need_date=po.start_date, qty=q,
                                 source=("planned_component", po.planned_no), segment=po.segment)
                order.supply.component_nodes.append((child, r.node))

    # ------------------------------------------------------------ forward pass (8.10)
    def _forward(self, order: list[str]) -> None:
        o = self.o
        for item_id in reversed(order):
            it = o.items[item_id]
            for s in self.sups.get(item_id, []):
                if s.kind in ("stock", "inspection", "po", "pr"):
                    s.projected_date = s.avail_date
                elif s.kind == "planned" and self.orders[s.planned_no].planned.kind == "buy":
                    po = self.orders[s.planned_no].planned
                    s.projected_date = po.need_date if po.start_date >= o.as_of else \
                        o.as_of + timedelta(days=o.purchase_lt(item_id) + it.receiving_days)
                else:
                    self._project_make(s)
            for r in self.reqs.get(item_id, []):
                sups = self.sups[item_id]
                dates = [sups[pg.supply_node - 1].projected_date for pg in r.pegs]
                r.satisfied_date = max(dates) if dates else None
                if r.kind == "safety_stock" or r.satisfied_date is None:
                    r.late_days = 0
                else:
                    r.late_days = max(0, (r.satisfied_date - r.need_date).days)
        for w in self.wo_supply.values():
            if w.node == 0:
                self._project_make(w)

    def _project_make(self, s: OSup) -> None:
        o = self.o
        comp_dates = [self.reqs[c][n - 1].satisfied_date for c, n in s.component_nodes]
        comp_dates = [d for d in comp_dates if d is not None]
        s.comp_ready = max(comp_dates) if comp_dates else None
        ready = max([s.start_date, o.as_of] + ([s.comp_ready] if s.comp_ready else []))
        s.ready = ready
        if ready == s.start_date:
            s.projected_date = s.due_date
            return
        if s.kind == "planned":
            po = self.orders[s.planned_no].planned
            n = o.mld(s.item_id, s.qty, max(po.need_date, o.as_of), po.segment[0] if po.segment else None)
        else:
            w = o.wos[s.ref[1]]
            n = o.mld(s.item_id, w.open_qty, max(w.start_date, o.as_of), w.serial_from)
        s.projected_date = max(s.due_date, o.cal.add(ready, n))

    # ------------------------------------------------------------ main
    def run(self) -> "_Pass":
        o = self.o
        self._inputs()
        level = o.llc()
        order = sorted(o.items, key=lambda i: (level[i], o.items[i].part_number))
        for item_id in order:
            self._net(item_id)
            self._explode_orders(item_id)
        for item_id in order:      # P7: every requirement fully pegged
            for r in self.reqs.get(item_id, []):
                if abs(r.pegged - r.qty) > 1e-5:
                    raise OracleError(f"requirement not fully pegged: {o.items[item_id].part_number} {r}")
        self._forward(order)
        for po in self.planned:
            s = self.orders[po.planned_no].supply
            po.projected_due = s.projected_date
            po.late_days = max(0, (s.projected_date - po.need_date).days)
        demand = self._demand()
        self._exceptions(demand)
        self.exceptions.sort(key=_exc_sort)
        kind = "live"
        self.result = OResult(as_of=o.as_of, horizon_end=o.horizon_end, kind=kind, requirements=dict(self.reqs),
                              supplies=dict(self.sups), planned=self.planned, demand=demand,
                              exceptions=self.exceptions, iterations=1, llc=level)
        return self

    def _demand(self) -> list[ODemandProj]:
        o = self.o
        out = []
        for key, r in self.demand_req.items():
            late = r.late_days
            if r.need_date < o.as_of:
                status = "past_due"
            elif late > 0:
                status = "late"
            else:
                status = "on_time"
            out.append(ODemandProj(key=key, item_id=r.item_id, qty=r.qty, due_date=r.need_date,
                                   projected_date=r.satisfied_date, late_days=late, status=status,
                                   limiting=self.limiting(r) if late > 0 else []))
        return out

    def limiting(self, r: OReq) -> list[dict[str, Any]]:
        o = self.o
        steps: list[dict[str, Any]] = []
        cur = r
        while len(steps) < 10:
            sups = self.sups[cur.item_id]
            if not cur.pegs:
                break
            s = max((sups[pg.supply_node - 1] for pg in cur.pegs), key=lambda x: (x.projected_date, -x.node))
            is_make = s.kind == "wo" or (s.kind == "planned" and self.orders[s.planned_no].planned.kind == "make")
            if is_make:
                decided = s.comp_ready is not None and s.ready == s.comp_ready and \
                    s.comp_ready > max(s.start_date, o.as_of)
                if decided:
                    steps.append({"item": s.item_id, "supply": s.ref, "date": s.projected_date, "reason": "component"})
                    comps = [self.reqs[c][n - 1] for c, n in s.component_nodes]
                    cur = max(comps, key=lambda x: (x.satisfied_date, -x.node))
                    continue
                steps.append({"item": s.item_id, "supply": s.ref, "date": s.projected_date,
                              "reason": "start_in_past" if s.start_date < o.as_of else "lead_time"})
                break
            steps.append({"item": s.item_id, "supply": s.ref, "date": s.projected_date, "reason": "supply_date"})
            break
        return steps

    # ------------------------------------------------------------ exceptions (8.12, subset)
    def _exceptions(self, demand: list[ODemandProj]) -> None:
        o = self.o
        E = self.exceptions
        for d in demand:
            subj = ("demand_line", d.key[1]) if d.key[0] == "demand" else ("extra", d.key[1])
            if d.late_days > 0:
                E.append(OException("MRP_DEMAND_LATE", "critical", d.item_id, subj, date=d.projected_date,
                                    qty=d.qty, days=d.late_days))
            if d.due_date < o.as_of:
                E.append(OException("MRP_DEMAND_PAST_DUE", "critical", d.item_id, subj, date=d.due_date, qty=d.qty))
        for item_id, R in self.reqs.items():
            late = [r for r in R if r.late_days > 0 and r.kind != "safety_stock"]
            if late:
                first = min(late, key=lambda r: r.need_date)
                E.append(OException("MRP_SHORTAGE", "warning", item_id, ("item", item_id), date=first.need_date,
                                    qty=sum(r.qty for r in late)))
            for r in R:
                if r.kind == "safety_stock":
                    sups = self.sups[item_id]
                    existing = sum(pg.qty for pg in r.pegs if sups[pg.supply_node - 1].kind != "planned")
                    if existing < r.qty - EPS:
                        E.append(OException("MRP_BELOW_SAFETY_STOCK", "info", item_id, ("item", item_id),
                                            qty=r.qty - existing))
        no_supplier: set[str] = set()
        for po in self.planned:
            if po.release_status == "start_in_past":
                E.append(OException("MRP_START_IN_PAST", "warning", po.item_id, ("planned_order", po.planned_no),
                                    date=po.start_date, days=(o.as_of - po.start_date).days))
            elif po.release_status == "release_now":
                E.append(OException("MRP_RELEASE_NOW", "info", po.item_id, ("planned_order", po.planned_no),
                                    date=po.start_date))
            if po.kind == "buy" and po.supplier_id is None:
                no_supplier.add(po.item_id)
        for item_id in sorted(no_supplier):
            E.append(OException("MRP_NO_SUPPLIER", "info", item_id, ("item", item_id)))
        lot_unpegged: dict[str, list[Any]] = {}
        for item_id, S in self.sups.items():
            it = o.items[item_id]
            for s in S:
                needs = [self.reqs[pg.requirement_item_id][pg.requirement_node - 1].need_date for pg in s.pegs]
                earliest = min(needs) if needs else None
                if s.kind in ("stock", "inspection") and s.expires_on is not None and \
                        s.expires_on <= o.horizon_end and s.remaining > EPS:
                    bal = o.balances[s.ref[1]]
                    acc = lot_unpegged.setdefault(bal.lot_id or bal.id, [item_id, 0.0, s.expires_on])
                    acc[1] += s.remaining
                if s.kind in ("po", "pr"):
                    sch = o.schedules[s.ref[1]]
                    subj = (f"{s.kind}_schedule", sch.schedule_id)
                    if s.pegged <= EPS:
                        E.append(OException("MRP_CANCEL", "warning", item_id, subj, qty=s.qty))
                    else:
                        if s.projected_date > earliest:
                            E.append(OException("MRP_EXPEDITE", "warning", item_id, subj,
                                                date=s.projected_date,
                                                suggested={"date": earliest - timedelta(days=it.receiving_days)}))
                        if s.pegged < s.qty - EPS:
                            rq = o.round_chain(item_id, s.pegged)
                            if rq < s.qty - EPS:
                                E.append(OException("MRP_REDUCE", "info", item_id, subj, qty=s.qty,
                                                    suggested={"qty": rq}))
                        if earliest > s.avail_date + timedelta(days=o.p.defer_tolerance_days):
                            E.append(OException("MRP_DEFER", "info", item_id, subj, date=s.avail_date,
                                                suggested={"date": earliest - timedelta(days=it.receiving_days)}))
                if s.kind == "wo":
                    w = o.wos[s.ref[1]]
                    subj = ("work_order", w.id)
                    if s.pegged <= EPS:
                        if w.status == "planned":
                            E.append(OException("MRP_CANCEL", "warning", item_id, subj, qty=s.qty))
                    else:
                        if s.projected_date > earliest:
                            E.append(OException("MRP_EXPEDITE", "warning", item_id, subj, date=s.projected_date,
                                                suggested={"date": earliest}))
                        if earliest > s.avail_date + timedelta(days=o.p.defer_tolerance_days):
                            E.append(OException("MRP_DEFER", "info", item_id, subj, date=s.avail_date,
                                                suggested={"date": earliest}))
        for w in self.wo_supply.values():
            if w.projected_date is not None and w.due_date is not None and w.projected_date > w.due_date:
                E.append(OException("MRP_WO_LATE", "warning", w.item_id, ("work_order", w.ref[1]),
                                    date=w.projected_date, days=(w.projected_date - w.due_date).days))
        for lot, (item_id, qty, exp) in sorted(lot_unpegged.items()):
            E.append(OException("MRP_EXPIRING_STOCK", "warning", item_id, ("lot", lot), date=exp, qty=qty))
        if self.outside_horizon:
            E.append(OException("MRP_DEMAND_OUTSIDE_HORIZON", "info", None, ("plant", None),
                                qty=float(self.outside_horizon)))


def run_oracle(plant: OPlant) -> OResult:
    return Oracle(plant).run()
