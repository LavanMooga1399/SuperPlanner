"""Snapshot -> scheduling model (M3-DESIGN 6.2-6.6): orders and operations, resources (lines with base / optional
windows, operators, tools), release times (material, precedence) and fixed placements (freeze, in progress, locks).

Time axis: integer minutes from `as_of` (UTC arithmetic). Local wall-clock rules are resolved by `mfg.calendar` in
the plant time (`tz.plant_tz`) and every boundary is converted to an instant (fold 0) before it becomes a minute,
so a shift across a DST change has its real elapsed length (5)."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..calendar import DAY, absence_intervals, add_days, from_local_minute, hhmm, line_detail, operator_intervals
from ..calendar import subtract as isub
from ..calendar import union as iunion
from ..routing import eligible_lines, lot_inputs, to_engine_minutes
from ..units import is_count
from .durations import SetupMatrix, family, rates_index
from .model import ApsComponent, ApsParams, ApsSnapshot, PegSupply

#: windows are built this many days past the horizon end, so operations starting before it can finish (6.2)
TAIL_DAYS = 21
Interval = tuple[int, int]


# ---------------------------------------------------------------- clock

class Clock:
    def __init__(self, as_of: datetime, tz: Any):
        self.as_of = as_of.astimezone(UTC)
        self.tz = tz
        self._lm: dict[int, int] = {}

    def to_min(self, dt: datetime, *, ceil: bool = True) -> int:
        s = (dt.astimezone(UTC) - self.as_of).total_seconds() / 60.0
        return math.ceil(s - 1e-9) if ceil else math.floor(s + 1e-9)

    def to_dt(self, m: int) -> datetime:
        return self.as_of + timedelta(minutes=m)

    def local(self, lm: int) -> int:
        """Local wall-clock minute (calendar convention) -> schedule minute."""
        v = self._lm.get(lm)
        if v is None:
            v = self._lm[lm] = self.to_min(from_local_minute(lm, self.tz))
        return v

    def midnight(self, d: date) -> int:
        return self.to_min(datetime(d.year, d.month, d.day, tzinfo=self.tz))

    def local_date(self, m: int) -> date:
        return self.to_dt(m).astimezone(self.tz).date()


# ---------------------------------------------------------------- resources

@dataclass
class OptInstance:
    key: str                    # "<line>:<assignment>:<shift>:<local day ordinal>"
    line_id: str
    assignment_id: str
    shift: str
    intervals: list[Interval]
    minutes: int
    cost_per_hour: float
    week: tuple[int, int]
    max_week_minutes: float | None
    label: str


@dataclass
class LineRes:
    id: str
    code: str
    group_id: str
    capacity: int
    speed_factor: float
    setup_family: str | None
    cost_per_hour: float
    base: list[Interval]
    optional: list[OptInstance]
    closed: list[Interval]
    base_labels: list[tuple[int, int, str]] = field(default_factory=list)


@dataclass
class OperatorRes:
    id: str
    code: str
    skills: frozenset[str]
    avail: list[Interval]
    starts: list[int] = field(default_factory=list)


# ---------------------------------------------------------------- orders and operations

@dataclass
class Order:
    type: str                   # wo | planned
    id: str                     # WO id / mpo_ id
    key: str                    # "wo:<id>" | "planned:<planned_no>"
    number: str
    planned_no: int | None
    item_id: str
    part_number: str
    qty: float
    due: int | None             # schedule minute of local 00:00 of the due date
    due_date: date | None
    rank: tuple[Any, ...]
    rank_label: str
    priority: int
    weight: float
    count_uom: bool
    ops: list["Op"] = field(default_factory=list)
    mrp_key: tuple[str, str] = ("", "")
    demand_refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Material:
    at: int | None              # earliest minute (None: missing)
    refs: list[dict[str, Any]]
    providers: list[tuple[str, int]]        # (provider order key, move minutes) - cross-order precedence
    missing: list[str]          # part numbers without supply


@dataclass
class Op:
    no: int                     # 1-based, stable order (order rank, order number, seq)
    order: Order
    seq: int
    idx: int                    # position in the order's remaining operations
    rec: Any                    # OperationRecord
    group_id: str
    qty: float
    lines: list[str]
    family: str
    gap_before: int             # elapsed minutes between the predecessor and this op (move+wait of pred + queue)
    move_after: int
    material: Material | None = None
    min_duration: int = 0       # fastest line, no setup credit
    latest_start: int = 0
    attended: bool = True
    crew_size: int = 0
    skill_id: str | None = None
    tools: tuple[tuple[str, int], ...] = ()
    interruptible: bool = True
    transfer_batch: int | None = None
    gate: bool = False

    @property
    def key(self) -> tuple[str, int]:
        return (self.order.key, self.seq)


@dataclass
class Fixed:
    """A placement that is not re-planned: frozen (published, before as_of + freeze), in progress, locked (edits)."""
    op_key: tuple[str, int]
    split_index: int
    split_count: int
    qty: float
    line_id: str
    start: int
    end: int
    pieces: list[Interval]
    setup: int
    run: int
    crew: list[tuple[str, int, int]]
    kind: str                   # frozen | in_progress | locked | edit


@dataclass
class Model:
    clock: Clock
    params: ApsParams
    policy: str
    horizon: int                # minutes to the horizon end
    window_end: int
    ds: Any
    lines: dict[str, LineRes]
    operators: dict[str, OperatorRes]
    tools: dict[str, int]
    orders: dict[str, Order]
    ops: list[Op]
    matrix: SetupMatrix
    rates: dict[tuple[str, str], Any]
    fixed: dict[tuple[tuple[str, int], int], Fixed]
    exceptions: list[dict[str, Any]]
    items: dict[str, Any]
    forced_open: set[str] = field(default_factory=set)       # optional instance keys forced by overrides
    hints: dict[tuple[str, int], tuple[str, tuple[str, int] | None]] = field(default_factory=dict)
    demand: list[Any] = field(default_factory=list)


def _week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _shift_starts(ds: Any) -> dict[tuple[str, str], int]:
    out = {}
    for t in ds.shift_templates.values():
        for sh in t.shifts:
            out[(t.code, sh.name)] = hhmm(sh.start)
    return out


def exception_minutes(ds: Any, ln: Any, clock: Clock) -> list[Interval]:
    """Calendar exceptions of a line (plant / its group / the line) as schedule minutes from their UTC instants."""
    return [(clock.to_min(x.start, ceil=False), clock.to_min(x.end)) for x in ds.calendar_exceptions.values()
            if x.scope == "plant" or (x.scope == "group" and x.group_id == ln.group_id) or
            (x.scope == "line" and x.line_id == ln.id)]


def build_line(ds: Any, ln: Any, clock: Clock, d0: date, d1: date, closes: list[Interval], opens: list[Interval],
               lo: int, hi: int) -> tuple[LineRes, set[str]]:
    det = line_detail(ds, ln.id, d0, d1, with_exceptions=False)
    closes = list(closes) + exception_minutes(ds, ln, clock)      # UTC instants (m6: correct in DST fall-back)
    starts = _shift_starts(ds)
    asg = ds.shift_assignments
    base: list[Interval] = []
    labels: list[tuple[int, int, str]] = []
    inst: dict[str, OptInstance] = {}
    for p in det.pieces:
        s, e = clock.local(p.start), clock.local(p.end)
        s, e = max(s, lo), min(e, hi)
        if s >= e:
            continue
        if p.kind == "base":
            base.append((s, e))
            labels.append((s, e, f"{p.template}/{p.shift}"))
            continue
        day = (p.start - starts.get((p.template, p.shift), 0)) // DAY
        key = f"{ln.id}:{p.assignment_id}:{p.shift}:{day}"
        a = asg.get(p.assignment_id)
        x = inst.get(key)
        if x is None:
            dd = date.fromordinal(max(1, day))
            cph = (a.cost_per_hour if a is not None and a.cost_per_hour is not None else ln.cost_per_hour) or 0.0
            mw = a.max_hours_per_week * 60.0 if a is not None and a.max_hours_per_week is not None else None
            x = inst[key] = OptInstance(key, ln.id, p.assignment_id or "", p.shift, [], 0, float(cph), _week(dd), mw,
                                        f"{p.template}/{p.shift} {dd.isoformat()}")
        x.intervals.append((s, e))
    closed = iunion(closes)
    base = isub(iunion(base), closed)
    forced: set[str] = set()
    out_inst = []
    for k in sorted(inst):
        x = inst[k]
        x.intervals = isub(iunion(x.intervals), closed)
        x.minutes = sum(e - s for s, e in x.intervals)
        if x.minutes <= 0:
            continue
        if any(s < oe and os_ < e for s, e in x.intervals for os_, oe in opens):
            forced.add(x.key)
        out_inst.append(x)
    out_inst.sort(key=lambda x: (x.intervals[0][0], x.key))
    lr = LineRes(ln.id, ln.code, ln.group_id, int(ln.parallel_capacity), float(ln.speed_factor or 1.0),
                 ln.setup_family, float(ln.cost_per_hour or 0.0), base, out_inst, closed, labels)
    return lr, forced


def _order_rank(snap: ApsSnapshot, key: tuple[str, str], fallback: tuple[Any, ...]) -> tuple[tuple[Any, ...], str]:
    mrp = snap.mrp
    if mrp is not None and key in mrp.ranks:
        r = tuple(mrp.ranks[key])
        return r, mrp.rank_labels.get(key, "")
    return fallback, ""


def _priority_of(rank: tuple[Any, ...], default: int) -> int:
    if len(rank) > 1 and isinstance(rank[1], int) and 1 <= rank[1] <= 9:
        return rank[1]
    return default


def build(snap: ApsSnapshot, params: ApsParams, policy: str, horizon_days: int) -> Model:
    ds = snap.dataset
    clock = Clock(snap.as_of, snap.tz)
    horizon = horizon_days * DAY
    d0 = add_days(clock.local_date(0), -1)
    d1 = add_days(clock.local_date(horizon), TAIL_DAYS + 1)
    window_end = clock.midnight(d1)
    lo, hi = 0, window_end
    matrix = SetupMatrix(getattr(ds, "setup_matrix", {}).values())
    rates = rates_index(ds)
    exc: list[dict[str, Any]] = []

    # ---- capacity overrides (6.8)
    closes: dict[str, list[Interval]] = {}
    opens: dict[str, list[Interval]] = {}
    for ov in params.capacity_overrides:
        tgt = [ln.id for ln in ds.lines.values() if (ov.target_type == "line" and ln.id == ov.target_id) or
               (ov.target_type == "group" and ln.group_id == ov.target_id)]
        iv = (clock.to_min(ov.start, ceil=False), clock.to_min(ov.end))
        for lid in tgt:
            (closes if ov.mode == "close" else opens).setdefault(lid, []).append(iv)
    for sh in params.open_shifts:       # accepted suggestions (16 Q1): planner-opened optional time
        opens.setdefault(sh.line_id, []).append((clock.to_min(sh.start, ceil=False), clock.to_min(sh.end)))

    # ---- orders
    items = ds.items
    orders: dict[str, Order] = {}
    work = []
    for w in snap.work_orders:
        it = items.get(w.item_id)
        if it is None or w.routing_id is None or w.routing_id not in ds.routings or w.qty <= 1e-9:
            continue
        due = clock.midnight(w.due_date)
        rank, label = _order_rank(snap, ("wo", w.id), (1, w.priority, w.due_date.isoformat(), w.number, 0))
        p = _priority_of(rank, w.priority)
        o = Order("wo", w.id, f"wo:{w.id}", w.number, None, w.item_id, it.part_number, float(w.qty), due, w.due_date,
                  rank, label or f"P{w.priority} {w.number}", p, float(2 ** (9 - p)), is_count(it.uom),
                  mrp_key=("wo", w.id))
        orders[o.key] = o
        work.append((o, ds.routings[w.routing_id], w.components, w.done_seqs))
    if snap.mrp is not None and params.include_planned:
        hz_date = clock.local_date(horizon)
        for pm in snap.mrp.planned:
            it = items.get(pm.item_id)
            if it is None or pm.routing_id is None or pm.routing_id not in ds.routings or pm.start_date > hz_date:
                continue
            due = clock.midnight(pm.need_date)
            key = ("planned", str(pm.planned_no))
            rank, label = _order_rank(snap, key, (1, 5, pm.need_date.isoformat(), f"P-{pm.planned_no}", 0))
            p = _priority_of(rank, 5)
            o = Order("planned", pm.id, f"planned:{pm.planned_no}", f"P-{pm.planned_no}", pm.planned_no, pm.item_id,
                      it.part_number, float(pm.qty), due, pm.need_date, rank, label, p, float(2 ** (9 - p)),
                      is_count(it.uom), mrp_key=key)
            orders[o.key] = o
            work.append((o, ds.routings[pm.routing_id], pm.components, frozenset()))

    # ---- operations
    ops: list[Op] = []
    for o, rt, comps, done in work:
        all_ops = sorted(rt.operations, key=lambda x: x.seq)
        qs = lot_inputs(all_ops, o.qty, o.count_uom)
        it = items[o.item_id]
        remaining = [(r, q) for r, q in zip(all_ops, qs) if r.seq not in done]
        prev = None
        for idx, (r, q) in enumerate(remaining):
            lines = [ln.id for ln in eligible_lines(ds, r.group_id, it)]
            gap = 0
            if prev is not None:
                gap = to_engine_minutes(prev.move_minutes + prev.wait_minutes + r.queue_minutes)
            op = Op(0, o, r.seq, idx, r, r.group_id, float(q), lines, family(it), gap,
                    to_engine_minutes(r.move_minutes), crew_size=int(r.crew_size), skill_id=r.skill_id,
                    tools=tuple((t.tool_pool_id, int(t.qty)) for t in r.tools), interruptible=bool(r.interruptible),
                    transfer_batch=r.transfer_batch, gate=bool(r.inspection_gate),
                    attended=r.labor == "attended")
            o.ops.append(op)
            ops.append(op)
            prev = r
        o_first = o.ops[0] if o.ops else None
        # components -> operations (6.4: operation_seq None / unknown -> first operation)
        seqs = {x.seq for x in o.ops}
        o.__dict__["components"] = [(c, c.operation_seq if c.operation_seq in seqs else
                                     (o_first.seq if o_first else None)) for c in comps]

    # ---- lines
    used_groups = {op.group_id for op in ops}
    lines: dict[str, LineRes] = {}
    forced: set[str] = set()
    for ln in sorted(ds.lines.values(), key=lambda x: x.code):
        if not ln.active or (ln.group_id not in used_groups and not any(ln.id in op.lines for op in ops)):
            continue
        lr, f = build_line(ds, ln, clock, d0, d1, closes.get(ln.id, []), opens.get(ln.id, []), lo, hi)
        lines[ln.id] = lr
        forced |= f
    for op in ops:
        op.lines = [lid for lid in op.lines if lid in lines]

    # ---- operators (shift spans minus absences, 6.3)
    operators: dict[str, OperatorRes] = {}
    for e in sorted(ds.operators.values(), key=lambda x: x.code):
        if not e.active:
            continue
        av = [(clock.local(s), clock.local(t)) for s, t in operator_intervals(ds, e.id, d0, d1, with_absences=False)]
        av = isub(iunion(av), iunion((clock.to_min(a.start, ceil=False), clock.to_min(a.end))
                                     for a in getattr(ds, "operator_absences", {}).values() if a.operator_id == e.id))
        av = [(max(s, lo), min(t, hi)) for s, t in av if min(t, hi) > max(s, lo)]
        operators[e.id] = OperatorRes(e.id, e.code, frozenset(e.skill_ids), iunion(av))
        operators[e.id].starts = [s for s, _ in operators[e.id].avail]
    tools = {t.id: int(t.quantity) for t in ds.tool_pools.values()}

    # ---- material (6.4)
    for o, _rt, _comps, _done in work:
        _material(snap, params, clock, o, orders, items, exc)

    # ---- durations for priorities: fastest line, setup included; backward pass from the due (7.1)
    for o in orders.values():
        nxt_ls: int | None = None
        for op in reversed(o.ops):
            best = None
            for lid in op.lines:
                ln = lines[lid]
                from .durations import run_minutes as _run, setup_minutes as _setup

                r = rates.get((op.rec.id, lid))
                d = _setup(op.rec, ln, r, matrix, None, op.family) + _run(op.rec, ln, r, op.qty)
                best = d if best is None else min(best, d)
            op.min_duration = best or 0
            # working time stretched to elapsed: about 3 x for one-shift lines; keep the plain sum (lower bound)
            succ_gap = o.ops[op.idx + 1].gap_before if op.idx + 1 < len(o.ops) else 0
            base_due = o.due if o.due is not None else horizon
            lf = base_due if nxt_ls is None else nxt_ls - succ_gap
            op.latest_start = lf - op.min_duration
            nxt_ls = op.latest_start

    # stable op numbers: order rank, order number, seq
    ops.sort(key=lambda x: (x.order.rank, x.order.number, x.seq))
    for i, op in enumerate(ops, 1):
        op.no = i

    m = Model(clock, params, policy, horizon, window_end, ds, lines, operators, tools, orders, ops, matrix, rates, {},
              exc, items, forced)
    _fixed_from_published(snap, m)
    m.moves = {k: (v[0], clock.to_min(v[1], ceil=False) if v[1] is not None else None, *v[2:])  # type: ignore
               for k, v in snap.moves.items()}
    if snap.mrp is not None:
        m.demand = list(snap.mrp.demand)
    return m


def _supply_at(clock: Clock, s: PegSupply, orders: dict[str, Order]) -> tuple[int | None, tuple[str, int] | None]:
    """(minute, provider order key) of one pegged supply."""
    if s.kind in ("stock", "on_hand", "inspection", "balance"):
        return 0, None
    if s.kind in ("work_order", "wo"):
        key = f"wo:{s.ref_id}"
        if key in orders:
            return None, (key, 0)
        return (max(0, clock.midnight(s.available_date)) if s.available_date else 0), None
    if s.kind == "planned":
        key = f"planned:{s.planned_no if s.planned_no is not None else s.ref_id}"
        if key in orders:
            return None, (key, 0)
        return (max(0, clock.midnight(s.available_date)) if s.available_date else None), None
    if s.available_date is None:
        return None, None
    return max(0, clock.midnight(s.available_date)), None


def _material(snap: ApsSnapshot, params: ApsParams, clock: Clock, o: Order, orders: dict[str, Order],
              items: dict[str, Any], exc: list[dict[str, Any]]) -> None:
    comps: list[tuple[ApsComponent, int | None]] = o.__dict__.get("components", [])
    by_seq: dict[int, Material] = {op.seq: Material(0, [], [], []) for op in o.ops}
    if params.material == "ignore":
        for op in o.ops:
            op.material = by_seq[op.seq]
        return
    mrp = snap.mrp
    for c, seq in comps:
        if seq is None or c.qty <= 1e-9:
            continue
        mat = by_seq[seq]
        pn = items[c.item_id].part_number if c.item_id in items else c.item_id
        sup = mrp.pegs.get((o.mrp_key[0], o.mrp_key[1], c.item_id)) if mrp is not None else None
        if sup:
            covered = sum(x.qty for x in sup)
            for x in sup:
                at, prov = _supply_at(clock, x, orders)
                if prov is not None:
                    child = orders[prov[0]]
                    mv = child.ops[-1].move_after if child.ops else 0
                    mat.providers.append((prov[0], mv))
                    mat.refs.append({"type": "work_order" if child.type == "wo" else "planned", "id": child.id,
                                     "label": f"{pn} from {child.number}"})
                    continue
                if at is None:
                    mat.missing.append(pn)
                    continue
                mat.at = max(mat.at or 0, at)
                mat.refs.append({"type": x.kind if x.kind != "on_hand" else "stock", "id": x.ref_id,
                                 "label": f"{pn}: {x.label}", "at_min": at})
            if covered + 1e-6 >= c.qty:
                continue
            need = c.qty - covered
        else:
            need = c.qty
        # live fallback (unpegged / partially pegged): free stock, else earliest open schedule covering it
        free = snap.stock_now.get(c.item_id, 0.0)
        if free + 1e-6 >= need:
            mat.refs.append({"type": "stock", "id": None, "label": f"{pn}: free stock", "at_min": 0})
            continue
        rest = need - max(0.0, free)
        cand = sorted((s for s in snap.open_supply if s.item_id == c.item_id), key=lambda s: (s.available_date,
                                                                                               s.ref_id))
        got, at2, ref = 0.0, None, None
        for s in cand:
            got += s.qty
            if got + 1e-6 >= rest:
                at2, ref = max(0, clock.midnight(s.available_date)), s
                break
        if at2 is None:
            mat.missing.append(pn)
        else:
            mat.at = max(mat.at or 0, at2)
            mat.refs.append({"type": ref.kind, "id": ref.ref_id, "label": f"{pn}: {ref.label}", "at_min": at2})
    for op in o.ops:
        mt = by_seq[op.seq]
        if mt.missing:
            mt.at = None
        op.material = mt


def _fixed_from_published(snap: ApsSnapshot, m: Model) -> None:
    """Freeze (6.6) and locks (6.7)."""
    clock = m.clock
    by_key = {op.key: op for op in m.ops}
    freeze = int(getattr(m.ds.plant, "aps_freeze_hours", 48) or 0) * 60
    pub = snap.published
    # operations an edit targets (6.7): with `override_freeze` only these leave the freeze; in-progress never does
    edited = {(k[1], k[2]) for k in snap.moves} | {(k[1], k[2]) for _l, ks in snap.resequence for k in ks}
    if pub is not None:
        for p in sorted(pub.ops, key=lambda x: x.op_no):
            if p.start is None or p.end is None or p.line_id is None:
                continue
            okey = f"{'wo' if p.order_type == 'wo' else 'planned'}:{p.order_id}"
            op = by_key.get((okey, p.seq))
            if op is None:
                op = next((o for o in m.ops if o.order.id == p.order_id and o.seq == p.seq), None)
            s, e = clock.to_min(p.start, ceil=False), clock.to_min(p.end)
            if op is None:
                if e > 0:
                    m.exceptions.append({"code": "APS_FROZEN_DROPPED", "op_no": p.op_no, "order_id": p.order_id,
                                         "seq": p.seq, "reason": "order gone or operation done"})
                continue
            if e <= 0:
                m.exceptions.append({"code": "APS_PAST_OP_NOT_DONE", "op": op, "end": e})
                continue
            in_progress = s < 0 < e
            if not in_progress and s >= freeze:
                continue
            if not in_progress and snap.override_freeze and (p.order_id, p.seq) in edited:
                continue
            if abs(p.qty - (op.qty / max(1, p.split_count))) > 1e-6 and p.split_count == 1:
                m.exceptions.append({"code": "APS_FROZEN_DROPPED", "op_no": p.op_no, "order_id": p.order_id,
                                     "seq": p.seq, "reason": "quantity changed"})
                continue
            if p.line_id not in m.lines:
                continue
            pieces = [(clock.to_min(a, ceil=False), clock.to_min(b)) for a, b in (p.pieces or ((p.start, p.end),))]
            m.fixed[(op.key, p.split_index)] = Fixed(
                op.key, p.split_index, p.split_count, p.qty, p.line_id, s, e, pieces, int(p.setup_minutes),
                int(p.run_minutes), [(c[0], clock.to_min(c[1], ceil=False), clock.to_min(c[2])) for c in p.crew],
                "in_progress" if in_progress else "frozen")
    for (otype, oid, seq, si), p in sorted(snap.locked.items()):
        okey = f"{'wo' if otype == 'wo' else 'planned'}:{oid}"
        op = by_key.get((okey, seq)) or next((o for o in m.ops if o.order.id == oid and o.seq == seq), None)
        if op is None or p.line_id is None or p.start is None or p.end is None or p.line_id not in m.lines:
            continue
        pieces = [(clock.to_min(a, ceil=False), clock.to_min(b)) for a, b in (p.pieces or ((p.start, p.end),))]
        m.fixed[(op.key, si)] = Fixed(op.key, si, p.split_count, p.qty, p.line_id, clock.to_min(p.start, ceil=False),
                                      clock.to_min(p.end), pieces, int(p.setup_minutes), int(p.run_minutes),
                                      [(c[0], clock.to_min(c[1], ceil=False), clock.to_min(c[2])) for c in p.crew],
                                      "locked")


def open_windows(line: LineRes, opened: set[str]) -> list[Interval]:
    """Base plus the given optional instances, merged (touching windows merge, 6.5)."""
    extra = [iv for x in line.optional if x.key in opened for iv in x.intervals]
    return iunion(line.base + extra)


def window_at(windows: list[Interval], t: int) -> int:
    """Index of the window containing t or the next one (len if none)."""
    i = bisect_right(windows, (t, 1 << 60)) - 1
    if i >= 0 and windows[i][0] <= t < windows[i][1]:
        return i
    return i + 1


__all__ = ["Clock", "Fixed", "LineRes", "Material", "Model", "Op", "OperatorRes", "OptInstance", "Order",
           "TAIL_DAYS", "build", "open_windows", "window_at"]
_unused = (absence_intervals,)
