"""`schedule(snapshot, params)` -> `ApsResult` (M3-DESIGN 6-9): build -> construct (policy; `suggest` adds an
internal `allow` pass) -> LNS -> independent validation -> explanations, KPIs, load.

Determinism (S3): no wall-clock or hash-order dependent decision; CP-SAT runs with one worker, a fixed seed and a
deterministic time limit. A wall-clock safety cap that cuts LNS short is recorded (`summary.budget_cut`)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from ..calendar import DAY
from .build import Model, Op, build
from .construct import Placed, Schedule, construct
from .model import (ApsException, ApsParams, ApsResult, ApsSnapshot, ApsSummary, Bottleneck, CrewSlot, DemandRef,
                    DemandResult, LateStep, LoadRow, OrderRef, OrderResult, OvertimeWindow, RefItem, ReleaseInfo,
                    ScheduledOp, Span, SplitInfo, StartReason, ToolUse, Validation)

Progress = Callable[[str, float, list[float] | None], None]

REASON_TEXT = {
    "as_of": "Starts at the planning start (as of).",
    "material": "Waits for material",
    "predecessor": "Waits for the previous operation",
    "line_busy": "The line is busy",
    "no_window": "Waits for an open shift window",
    "crew": "Waits for qualified operators",
    "tool": "Waits for tooling",
    "setup": "Setup changeover",
    "frozen": "Frozen (published plan within the freeze window).",
    "in_progress": "In progress at the planning start.",
    "locked": "Locked by a manual edit.",
    "edit": "Placed by a manual edit.",
    "elapsed": "Queue / move / wait time",
}
SEVERITY = {"APS_ORDER_LATE": "critical", "APS_MATERIAL_MISSING": "critical", "APS_BEYOND_HORIZON": "info",
            "APS_OVERTIME_SUGGESTED": "info", "APS_OVERTIME_LIMIT": "warning", "APS_NO_CREW": "warning",
            "APS_PAST_OP_NOT_DONE": "warning", "APS_FROZEN_DROPPED": "warning", "APS_SPLIT": "info",
            "APS_BUDGET_CUT": "info"}


def _policy(snap: ApsSnapshot, params: ApsParams) -> str:
    return params.overtime or getattr(snap.dataset.plant, "aps_overtime_policy", "suggest") or "suggest"


def horizon_days(snap: ApsSnapshot, params: ApsParams) -> int:
    return int(params.horizon_days or getattr(snap.dataset.plant, "aps_horizon_days", 42) or 42)


def run_kind(params: ApsParams, mrp_kind: str | None) -> str:
    if params.as_of is not None or params.material == "ignore" or params.capacity_overrides or mrp_kind == "what_if":
        return "what_if"
    return "live"


# ---------------------------------------------------------------- evaluation

def order_ends(m: Model, sc: Schedule) -> dict[str, tuple[int | None, int | None, bool]]:
    """order key -> (first start, last end, complete)."""
    out = {}
    for k, o in m.orders.items():
        starts, ends, complete = [], [], True
        for op in o.ops:
            ps = sc.placed.get(op.key)
            if ps is None:
                complete = False
                continue
            starts += [p.start for p in ps]
            ends += [p.end for p in ps]
        last = o.ops[-1].key if o.ops else None
        end = max(p.end for p in sc.placed[last]) if last in sc.placed and complete else None
        out[k] = (min(starts) if starts else None, end, complete)
    return out


def score(m: Model, sc: Schedule, hard: int = 0) -> list[float]:
    ends = order_ends(m, sc)
    wt = 0.0
    wip = 0.0
    mk = 0
    for k, o in m.orders.items():
        s, e, complete = ends[k]
        if o.due is not None:
            if e is not None:
                wt += o.weight * max(0, e - o.due)
            elif any(sc.unscheduled.get(op.key) and sc.unscheduled[op.key].reason != "beyond_horizon"
                     for op in o.ops):
                wt += o.weight * max(0, m.window_end - o.due)
        if s is not None and e is not None:
            wip += e - s
    setup = 0
    for ps in sc.placed.values():
        for p in ps:
            mk = max(mk, p.end)
            setup += p.setup
    ot = overtime_cost(m, sc)
    return [float(hard), float(wt), round(ot, 4), float(wip), float(mk), float(setup)]


def overtime_cost(m: Model, sc: Schedule) -> float:
    inst = {x.key: x for ln in m.lines.values() for x in ln.optional}
    return sum(inst[k].minutes * inst[k].cost_per_hour / 60.0 for k in sc.opened if k in inst)


# ---------------------------------------------------------------- top level

def schedule(snap: ApsSnapshot, params: ApsParams, progress: Progress | None = None,
             cancelled: Callable[[], bool] | None = None, *, wall_cap: float | None = None) -> ApsResult:
    t0 = time.monotonic()
    timings: dict[str, int] = {}
    policy = _policy(snap, params)
    hd = horizon_days(snap, params)
    m = build(snap, params, policy, hd)
    m.snapshot = snap                   # type: ignore[attr-defined]  (LNS validates candidates)
    if progress:
        progress("construct", 5.0, None)
    hints = edit_hints(m, snap)
    base_policy = "off" if policy == "suggest" else policy
    sc = construct(m, base_policy, hints)
    timings["construct"] = int((time.monotonic() - t0) * 1000)
    suggested: list[OvertimeWindow] = []
    if policy == "suggest":
        suggested = suggest(m, sc, hints)
    best = score(m, sc)
    if progress:
        progress("improve", 30.0, best)
    iterations = accepted = 0
    used = 0.0
    cut = False
    t1 = time.monotonic()
    if params.improve_seconds > 0 and not snap.edits and not (cancelled and cancelled()):
        from .lns import improve

        sc, best, iterations, accepted, used, cut = improve(m, sc, base_policy, hints, params.improve_seconds,
                                                           progress, cancelled, wall_cap=wall_cap)
    timings["improve"] = int((time.monotonic() - t1) * 1000)
    t2 = time.monotonic()
    res = assemble(snap, params, m, sc, policy, suggested, iterations, accepted, used, cut)
    from .validator import validate

    res.validation = validate(snap, res)
    res.summary.validation_ok = res.validation.ok
    res.summary.violations = len(res.validation.violations)
    res.score[0] = float(len(res.validation.violations))
    timings["validate"] = int((time.monotonic() - t2) * 1000)
    res.summary.timings_ms.update(timings)
    return res


def edit_hints(m: Model, snap: ApsSnapshot) -> dict[tuple[str, int], tuple[str, tuple[str, int] | None]]:
    """`resequence` and line-only `move` edits -> forced line + predecessor-on-line hints (6.7); timed moves and
    locks are fixed placements."""
    hints: dict[tuple[str, int], tuple[str, tuple[str, int] | None]] = {}
    by_id = {(op.order.type, op.order.id, op.seq): op for op in m.ops}
    for line_id, keys in snap.resequence:
        if line_id not in m.lines:
            continue
        prev = None
        for k in keys:
            op = by_id.get(tuple(k))
            if op is None:
                continue
            hints[op.key] = (line_id, prev)
            prev = op.key
    for (otype, oid, seq, _si), (line_id, start) in snap.moves.items():
        op = by_id.get((otype, oid, seq))
        if op is not None and line_id and start is None and line_id in m.lines:
            hints[op.key] = (line_id, None)
    return hints


def suggest(m: Model, base: Schedule, hints: Any) -> list[OvertimeWindow]:
    """`suggest` (6.8): an internal `allow` pass; its opened instances become suggestions, the saved weighted
    tardiness is apportioned to them by the operation minutes they carry."""
    alt = construct(m, "allow", hints)
    s0, s1 = score(m, base), score(m, alt)
    saved = max(0.0, s0[1] - s1[1])
    inst = {x.key: x for ln in m.lines.values() for x in ln.optional}
    use: dict[str, int] = {}
    for ps in alt.placed.values():
        for p in ps:
            for k in p.opened or ():
                pass
            ln = m.lines[p.line_id]
            for x in ln.optional:
                if alt.opened.get(x.key) == "opened":
                    u = sum(max(0, min(b, pe) - max(a, ps_)) for a, b in x.intervals for ps_, pe in p.pieces)
                    if u:
                        use[x.key] = use.get(x.key, 0) + u
    total = sum(use.values()) or 1
    out = []
    clock = m.clock
    for k in sorted(use, key=lambda k: (inst[k].intervals[0][0], k)):
        x = inst[k]
        cost = x.minutes * x.cost_per_hour / 60.0
        out.append(OvertimeWindow(line_id=x.line_id, assignment_id=x.assignment_id or None,
                                  start=clock.to_dt(x.intervals[0][0]), end=clock.to_dt(x.intervals[-1][1]),
                                  minutes=x.minutes, cost=round(cost, 2), status="suggested",
                                  tardiness_saved_minutes=round(saved * use[k] / total, 2)))
    out.sort(key=lambda w: (-(w.tardiness_saved_minutes or 0) / max(w.cost, 1e-9), w.start, w.line_id))
    return out


# ---------------------------------------------------------------- result assembly

def _ref(d: dict[str, Any], clock: Any) -> RefItem:
    at = d.get("at_min")
    return RefItem(type=str(d.get("type") or ""), id=d.get("id"), label=str(d.get("label") or "")[:300],
                   at=clock.to_dt(at) if at is not None else None)


def _fmt(clock: Any, m: int) -> str:
    dt = clock.to_dt(m).astimezone(clock.tz)
    return dt.strftime("%a %d %b %H:%M")


def reason_text(m: Model, p: Placed) -> str:
    base = REASON_TEXT.get(p.reason, p.reason)
    clock = m.clock
    if p.reason == "material":
        lab = "; ".join(r["label"] for r in p.reason_refs[:2])
        return f"{base}: {lab} (available {_fmt(clock, p.start)})." if lab else f"{base}."
    if p.reason == "predecessor":
        lab = p.reason_refs[0]["label"] if p.reason_refs else "previous operation"
        return f"{base} {lab}" + (f" + {p.op.gap_before} min queue/move/wait." if p.op.gap_before else ".")
    if p.reason == "line_busy":
        lab = p.reason_refs[0]["label"] if p.reason_refs else "another operation"
        return f"{base}: {m.lines[p.line_id].code} runs {lab} until {_fmt(clock, p.start)}."
    if p.reason == "no_window":
        return f"{base}: {m.lines[p.line_id].code} opens {_fmt(clock, p.start)}."
    if p.reason == "crew":
        return f"{base} ({p.op.crew_size} needed); starts {_fmt(clock, p.start)}."
    if p.reason == "tool":
        return f"{base}; starts {_fmt(clock, p.start)}."
    return base


def assemble(snap: ApsSnapshot, params: ApsParams, m: Model, sc: Schedule, policy: str,
             suggested: list[OvertimeWindow], iterations: int, accepted: int, used: float, cut: bool) -> ApsResult:
    clock = m.clock
    items = m.items
    ends = order_ends(m, sc)
    order_refs: dict[str, OrderRef] = {}
    for k, o in m.orders.items():
        order_refs[k] = OrderRef(type=o.type, id=o.id, number=o.number, planned_no=o.planned_no, item_id=o.item_id)
    sops: list[ScheduledOp] = []
    rows: list[tuple[tuple[Any, ...], Op, Placed | None]] = []
    for op in m.ops:
        ps = sc.placed.get(op.key)
        if ps:
            for p in sorted(ps, key=lambda x: (x.part, x.start)):
                rows.append(((op.no, p.part), op, p))
        else:
            rows.append(((op.no, 0), op, None))
    rows.sort(key=lambda r: r[0])
    op_no_of: dict[tuple[tuple[str, int], int], int] = {}
    for n, (_k, op, p) in enumerate(rows, 1):
        op_no_of[(op.key, p.part if p else 0)] = n
    for n, (_k, op, p) in enumerate(rows, 1):
        o = op.order
        due = clock.to_dt(o.due) if o.due is not None else None
        rel = sc.release.get(op.key, {})
        release = ReleaseInfo(material_at=clock.to_dt(rel["material_at"]) if rel.get("material_at") is not None
                              else None,
                              predecessor_at=clock.to_dt(rel["predecessor_at"]) if rel.get("predecessor_at") is not None
                              else None,
                              refs=[_ref(r, clock) for r in rel.get("refs", [])][:20])
        if p is None:
            u = sc.unscheduled.get(op.key)
            code = u.reason if u else "no_window"
            sops.append(ScheduledOp(op_no=n, order=order_refs[o.key], seq=op.seq, name=op.rec.name,
                                    group_id=op.group_id, qty=op.qty, status="unscheduled", release=release,
                                    reason=StartReason(code=code, refs=[_ref(r, clock) for r in (u.refs if u else [])],
                                                       text=u.text if u else ""),
                                    due=due, family=op.family))
            continue
        lf = op.latest_start + op.min_duration
        late = max(0, p.end - lf) if op.idx == len(o.ops) - 1 else 0
        if op.idx == len(o.ops) - 1 and o.due is not None:
            late = max(0, p.end - o.due)
        reason_code = p.fixed if p.fixed in ("frozen", "locked", "edit", "in_progress") else (p.reason or "as_of")
        txt = REASON_TEXT.get(reason_code, "") if p.fixed else reason_text(m, p)
        refs = [_ref(r, clock) for r in p.reason_refs]
        for r in refs:
            if r.type == "operation" and r.id is not None:
                pk = next((x for x in m.ops if str(x.no) == r.id), None)
                if pk is not None and (pk.key, 0) in op_no_of:
                    r.id = str(op_no_of[(pk.key, 0)])
        sops.append(ScheduledOp(
            op_no=n, order=order_refs[o.key], seq=op.seq, name=op.rec.name, group_id=op.group_id, qty=p.qty,
            split=SplitInfo(index=p.part, count=p.parts), line_id=p.line_id, start=clock.to_dt(p.start),
            end=clock.to_dt(p.end), setup_minutes=p.setup, run_minutes=p.run,
            pieces=[Span(start=clock.to_dt(a), end=clock.to_dt(b)) for a, b in p.pieces],
            crew=[CrewSlot(operator_id=e, start=clock.to_dt(a), end=clock.to_dt(b)) for e, a, b in p.crew],
            tools=[ToolUse(tool_pool_id=t, qty=q) for t, q in p.tools], release=release,
            locked=p.fixed in ("locked", "edit"), frozen=p.fixed in ("frozen", "in_progress"), status="scheduled",
            reason=StartReason(code=reason_code, refs=refs, text=txt), due=due, late_minutes=int(late),
            family=op.family, setup_from_family=p.prev_family))
    # ---- orders + late chains
    from .explain import late_chain

    orders: list[OrderResult] = []
    demand_of: dict[str, list[DemandRef]] = {}
    for d in m.demand:
        for s in d.supplies:
            if s.kind in ("work_order", "wo"):
                demand_of.setdefault(f"wo:{s.ref_id}", []).append(
                    DemandRef(demand_line_id=d.demand_line_id, order_number=d.order_number, line_no=d.line_no))
            elif s.kind == "planned":
                demand_of.setdefault(f"planned:{s.planned_no if s.planned_no is not None else s.ref_id}", []).append(
                    DemandRef(demand_line_id=d.demand_line_id, order_number=d.order_number, line_no=d.line_no))
    late_wos = 0
    by_no = {op.no: op for op in m.ops}
    for k, o in sorted(m.orders.items(), key=lambda kv: (kv[1].rank, kv[1].number)):
        s, e, complete = ends[k]
        late = max(0, e - o.due) if (e is not None and o.due is not None) else 0
        uns = sum(1 for op in o.ops if op.key in sc.unscheduled)
        chain, text = late_chain(m, sc, o, by_no) if late > 0 else ([], "")
        orders.append(OrderResult(
            order=order_refs[k], part_number=o.part_number, qty=o.qty,
            due=clock.to_dt(o.due) if o.due is not None else None, start=clock.to_dt(s) if s is not None else None,
            end=clock.to_dt(e) if e is not None else None, late_minutes=int(late), weight=o.weight,
            priority=o.priority, rank_label=o.rank_label[:100], demand_refs=demand_of.get(k, []),
            late_chain=chain, late_text=text[:1000], unscheduled_ops=uns))
        if late > 0 and o.type == "wo":
            late_wos += 1
    # ---- demand view (8)
    demand: list[DemandResult] = []
    for d in m.demand:
        due = clock.midnight(d.due_date)
        end: int | None = 0
        refs: list[OrderRef] = []
        unknown = False
        for s in d.supplies:
            if s.kind in ("work_order", "wo", "planned"):
                key = f"wo:{s.ref_id}" if s.kind != "planned" else \
                    f"planned:{s.planned_no if s.planned_no is not None else s.ref_id}"
                if key in ends:
                    refs.append(order_refs[key])
                    oe = ends[key][1]
                    if oe is None:
                        unknown = True
                    else:
                        end = max(end or 0, oe)
                elif s.available_date is not None:
                    end = max(end or 0, clock.midnight(s.available_date))
            elif s.kind not in ("stock", "on_hand", "inspection", "balance") and s.available_date is not None:
                end = max(end or 0, clock.midnight(s.available_date))
        if not d.supplies:
            unknown = True
        sched = None if unknown else end
        late = max(0, sched - due) if sched is not None else max(0, m.window_end - due)
        pn = items[d.item_id].part_number if d.item_id in items else d.item_id
        demand.append(DemandResult(
            demand_line_id=d.demand_line_id, order_id=d.order_id, order_number=d.order_number, line_no=d.line_no,
            item_id=d.item_id, part_number=pn, qty=d.qty, due=clock.to_dt(due),
            scheduled_end=clock.to_dt(sched) if sched is not None else None, late_minutes=int(late),
            priority=d.priority, program=d.program, orders=refs,
            late_text="" if late == 0 else ("Not completely scheduled within the horizon." if sched is None else
                                            f"Scheduled completion {_fmt(clock, sched)}, due {d.due_date.isoformat()}.")))
    # ---- overtime
    inst = {x.key: x for ln in m.lines.values() for x in ln.optional}
    overtime: list[OvertimeWindow] = []
    for k in sorted(sc.opened, key=lambda k: (inst[k].intervals[0][0], k) if k in inst else (0, k)):
        if k not in inst:
            continue
        x = inst[k]
        overtime.append(OvertimeWindow(line_id=x.line_id, assignment_id=x.assignment_id or None,
                                       start=clock.to_dt(x.intervals[0][0]), end=clock.to_dt(x.intervals[-1][1]),
                                       minutes=x.minutes, cost=round(x.minutes * x.cost_per_hour / 60.0, 2),
                                       status="forced" if sc.opened[k] == "forced" else "opened"))
    overtime += suggested
    # ---- load (9.2)
    load, util = load_rows(m, sc)
    # ---- exceptions
    exc = exceptions(m, sc, sops, orders, overtime, cut)
    # ---- bottlenecks (8)
    bottl = bottlenecks(m, util, orders, suggested)
    # ---- summary
    sc_score = score(m, sc)
    dl_late = sum(1 for d in demand if d.late_minutes > 0)
    flows = [(e - s) / DAY for s, e, _c in ends.values() if s is not None and e is not None]
    unsched: dict[str, int] = {}
    for u in sc.unscheduled.values():
        unsched[u.reason] = unsched.get(u.reason, 0) + 1
    setups = [p for ps in sc.placed.values() for p in ps if p.setup > 0]
    summ = ApsSummary(
        policy=policy, operations=len(sops), scheduled_operations=sum(1 for x in sops if x.status == "scheduled"),
        unscheduled=dict(sorted(unsched.items())), orders=len(orders),
        late_orders=sum(1 for o in orders if o.late_minutes > 0), late_wos=late_wos, demand_lines=len(demand),
        demand_lines_on_time=len(demand) - dl_late, demand_lines_late=dl_late, late_demand_count=dl_late,
        weighted_tardiness=sc_score[1], max_lateness_minutes=max((o.late_minutes for o in orders), default=0),
        overtime_minutes=sum(w.minutes for w in overtime if w.status != "suggested"),
        overtime_cost=round(sum(w.cost for w in overtime if w.status != "suggested"), 2),
        suggested_overtime_minutes=sum(w.minutes for w in suggested),
        suggested_overtime_cost=round(sum(w.cost for w in suggested), 2),
        suggested_tardiness_saved=round(sum(w.tardiness_saved_minutes or 0 for w in suggested), 2),
        utilisation={g: round(v, 4) for g, v in sorted(util.items())},
        bottlenecks=[b.group_id for b in bottl], setup_minutes=int(sc_score[5]), changeovers=len(setups),
        avg_flow_days=round(sum(flows) / len(flows), 3) if flows else 0.0, makespan_minutes=int(sc_score[4]),
        splits=sum(1 for ps in sc.placed.values() if len(ps) > 1), iterations=iterations, accepted_moves=accepted,
        budget_used=round(used, 3), budget_cut=cut)
    mrp_kind = snap.mrp.kind if snap.mrp is not None else None
    return ApsResult(params=params, kind=run_kind(params, mrp_kind), as_of=clock.as_of,
                     horizon_end=clock.to_dt(m.horizon), summary=summ, score=sc_score, validation=Validation(ok=True),
                     operations=sops, overtime=overtime, orders=orders, demand=demand, exceptions=exc, load=load,
                     bottlenecks=bottl, iterations=iterations, budget_used=round(used, 3))


def load_rows(m: Model, sc: Schedule) -> tuple[list[LoadRow], dict[str, float]]:
    clock = m.clock
    day0 = clock.local_date(0)
    last = clock.local_date(m.horizon - 1)
    days: list[date] = []
    d = day0
    while d <= last:
        days.append(d)
        d += timedelta(days=1)
    bounds = [(dd, clock.midnight(dd), clock.midnight(dd + timedelta(days=1))) for dd in days]

    def per_day(ivs: list[tuple[int, int]], mult: float = 1.0) -> dict[date, float]:
        out: dict[date, float] = {}
        for a, b in ivs:
            for dd, lo, hi in bounds:
                x = min(b, hi) - max(a, lo, 0)
                if x > 0:
                    out[dd] = out.get(dd, 0.0) + x * mult
        return out

    rows: list[LoadRow] = []
    util: dict[str, float] = {}
    req_by_line: dict[str, dict[date, float]] = {}
    for o in m.orders.values():
        d_req = o.due_date or day0
        for op in o.ops:
            if not op.lines:
                continue
            lid = op.lines[0]
            dd = max(day0, min(last, d_req - timedelta(days=1)))
            req_by_line.setdefault(lid, {})[dd] = req_by_line.get(lid, {}).get(dd, 0.0) + op.min_duration
    for gid in sorted({ln.group_id for ln in m.lines.values()}):
        gl = sorted((ln for ln in m.lines.values() if ln.group_id == gid), key=lambda x: x.code)
        gsum: dict[date, list[float]] = {}
        tot_s = tot_b = 0.0
        for ln in gl:
            sched = per_day([pc for ps in sc.placed.values() for p in ps if p.line_id == ln.id for pc in p.pieces])
            base = per_day(ln.base, ln.capacity)
            opt = per_day([iv for x in ln.optional for iv in x.intervals], ln.capacity)
            opened = per_day([iv for x in ln.optional if x.key in sc.opened for iv in x.intervals], ln.capacity)
            req = req_by_line.get(ln.id, {})
            for dd in days:
                vals = [sched.get(dd, 0.0), req.get(dd, 0.0), base.get(dd, 0.0), opt.get(dd, 0.0),
                        opened.get(dd, 0.0)]
                if any(vals):
                    rows.append(LoadRow(group_id=gid, line_id=ln.id, day=dd, scheduled_minutes=vals[0],
                                        required_minutes=vals[1], base_minutes=vals[2], optional_minutes=vals[3],
                                        opened_minutes=vals[4]))
                g = gsum.setdefault(dd, [0.0] * 5)
                for i, v in enumerate(vals):
                    g[i] += v
                tot_s += vals[0]
                tot_b += vals[2]
        for dd in days:
            g = gsum.get(dd)
            if g and any(g):
                rows.append(LoadRow(group_id=gid, line_id=None, day=dd, scheduled_minutes=g[0], required_minutes=g[1],
                                    base_minutes=g[2], optional_minutes=g[3], opened_minutes=g[4]))
        util[gid] = (tot_s / tot_b) if tot_b > 0 else (1.0 if tot_s > 0 else 0.0)
    rows.sort(key=lambda r: (r.group_id, r.line_id or "", r.day))
    return rows, util


def exceptions(m: Model, sc: Schedule, sops: list[ScheduledOp], orders: list[OrderResult],
               overtime: list[OvertimeWindow], cut: bool) -> list[ApsException]:
    out: list[ApsException] = []

    def add(code: str, subject: RefItem, message: str, *, op_no: int | None = None, order: OrderRef | None = None,
            refs: list[RefItem] | None = None) -> None:
        out.append(ApsException(code=code, severity=SEVERITY[code], subject=subject, op_no=op_no, order=order,
                                message=message[:1000], refs=refs or []))

    for o in orders:
        if o.late_minutes > 0:
            add("APS_ORDER_LATE", RefItem(type=o.order.type, id=o.order.id, label=o.order.number),
                f"{o.order.number} ({o.part_number} x{o.qty:g}) is {_dur(o.late_minutes)} late. {o.late_text}",
                order=o.order)
    beyond: dict[str, int] = {}
    for x in sops:
        if x.status != "unscheduled":
            continue
        if x.reason.code == "material_missing":
            add("APS_MATERIAL_MISSING", RefItem(type=x.order.type, id=x.order.id, label=x.order.number),
                f"{x.order.number} op {x.seq} {x.name}: {x.reason.text}", op_no=x.op_no, order=x.order,
                refs=x.reason.refs)
        elif x.reason.code == "beyond_horizon":
            beyond[x.order.number] = beyond.get(x.order.number, 0) + 1
        elif x.reason.code == "crew":
            add("APS_NO_CREW", RefItem(type=x.order.type, id=x.order.id, label=x.order.number),
                f"{x.order.number} op {x.seq} {x.name}: no qualified operators.", op_no=x.op_no, order=x.order)
    if beyond:
        n = sum(beyond.values())
        add("APS_BEYOND_HORIZON", RefItem(type="plant", id=None, label="Horizon"),
            f"{n} operation(s) of {len(beyond)} order(s) start after the horizon end (rolling horizon).")
    lines = m.lines
    for w in overtime:
        if w.status == "suggested":
            add("APS_OVERTIME_SUGGESTED", RefItem(type="line", id=w.line_id, label=lines[w.line_id].code),
                f"Opening {lines[w.line_id].code} {w.start.astimezone(m.clock.tz):%a %d %b %H:%M} ({_dur(w.minutes)},"
                f" cost {w.cost:,.0f}) saves {w.tardiness_saved_minutes or 0:,.0f} weighted late minutes.")
    seen_limit: set[str] = set()
    for e in sc.events:
        if e["code"] == "APS_OVERTIME_LIMIT" and e["line_id"] not in seen_limit:
            seen_limit.add(e["line_id"])
            add("APS_OVERTIME_LIMIT", RefItem(type="line", id=e["line_id"], label=lines[e["line_id"]].code),
                f"Overtime on {lines[e['line_id']].code} hit the weekly limit (max hours per week).")
        elif e["code"] == "APS_SPLIT":
            op = e["op"]
            add("APS_SPLIT", RefItem(type=op.order.type, id=op.order.id, label=op.order.number),
                f"{op.order.number} op {op.seq} {op.rec.name} was split into {e['parts']} parts across lines.")
    for e in m.exceptions:
        if e["code"] == "APS_PAST_OP_NOT_DONE":
            op = e["op"]
            add("APS_PAST_OP_NOT_DONE", RefItem(type=op.order.type, id=op.order.id, label=op.order.number),
                f"{op.order.number} op {op.seq} {op.rec.name} ended in the published plan before the planning start "
                "but is not marked done; it was rescheduled.")
        elif e["code"] == "APS_FROZEN_DROPPED":
            add("APS_FROZEN_DROPPED", RefItem(type="operation", id=str(e["op_no"]), label=f"op {e['op_no']}"),
                f"A frozen operation of the published plan was dropped ({e['reason']}).")
    if cut:
        add("APS_BUDGET_CUT", RefItem(type="plant", id=None, label="Improvement"),
            "The improvement phase was cut short by the wall-clock safety cap.")
    out.sort(key=lambda x: ({"critical": 0, "warning": 1, "info": 2}[x.severity], x.code, x.subject.label))
    return out


def bottlenecks(m: Model, util: dict[str, float], orders: list[OrderResult], suggested: list[OvertimeWindow]
                ) -> list[Bottleneck]:
    chains: dict[str, int] = {}
    for o in orders:
        for st in o.late_chain:
            if st.kind == "capacity":
                for r in st.refs:
                    if r.type == "group" and r.id:
                        chains[r.id] = chains.get(r.id, 0) + 1
    saved: dict[str, float] = {}
    for w in suggested:
        g = m.lines[w.line_id].group_id
        saved[g] = saved.get(g, 0.0) + (w.tardiness_saved_minutes or 0)
    ranked = sorted(util, key=lambda g: (-chains.get(g, 0), -util[g], g))
    out = []
    for i, g in enumerate(ranked[:3], 1):
        sv = saved.get(g)
        sug = None
        if sv:
            ws = [w for w in suggested if m.lines[w.line_id].group_id == g]
            codes = sorted({m.lines[w.line_id].code for w in ws})
            sug = f"Opening optional shifts on {', '.join(codes)} saves {sv:,.0f} weighted late minutes."
        out.append(Bottleneck(group_id=g, rank=i, utilisation=round(util[g], 4), late_chains=chains.get(g, 0),
                              suggestion=sug, saved_minutes=round(sv, 2) if sv else None))
    return out


def _dur(minutes: int) -> str:
    if minutes >= 1440:
        return f"{minutes / 1440:.1f} days"
    if minutes >= 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes} min"


__all__ = ["assemble", "horizon_days", "order_ends", "run_kind", "schedule", "score"]
