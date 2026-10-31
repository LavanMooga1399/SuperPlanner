"""Independent validator (M3-DESIGN 7.4): re-derives every fact from the snapshot's master data (calendar windows
via `mfg.calendar`, durations with its own formula) and checks the result; it shares no code with construction or
LNS. Codes (`APS_V_*`): ELIGIBLE, CAPACITY, WINDOW, CONTINUOUS, DURATION, PRECEDENCE, MATERIAL, CREW_COUNT,
CREW_SKILL, CREW_SHIFT, CREW_DOUBLE, TOOL, OVERTIME_LIMIT, LOCKED."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..calendar import DAY, add_days, from_local_minute, line_detail, operator_intervals
from ..routing import line_eligible, lot_inputs
from ..units import is_count
from .model import ApsResult, ApsSnapshot, Validation, Violation

EPS = 1e-6


def _m(as_of: datetime, dt: datetime) -> int:
    return round((dt.astimezone(UTC) - as_of).total_seconds() / 60.0)


def _ceil(x: float) -> int:
    return max(0, math.ceil(x - EPS))


def _union(iv: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(iv):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _inside(iv: list[tuple[int, int]], a: int, b: int) -> bool:
    for s, e in iv:
        if s <= a and b <= e:
            return True
        if s > a:
            return False
    return False


def _loads(op: Any, q: float) -> float:
    if op.run_per == "panel":
        return float(math.ceil(q / op.units_per_panel - EPS))
    if op.run_per == "batch":
        return float(math.ceil(q / op.units_per_batch - EPS))
    return float(q)


def validate(snap: ApsSnapshot, res: ApsResult) -> Validation:
    ds = snap.dataset
    tz = snap.tz
    as_of = res.as_of.astimezone(UTC)
    viol: list[Violation] = []

    def bad(code: str, op_no: int | None, msg: str, **refs: Any) -> None:
        viol.append(Violation(code=code, op_no=op_no, message=msg[:500], refs=refs))

    def loc(lm: int) -> int:
        return _m(as_of, from_local_minute(lm, tz))

    sched = [o for o in res.operations if o.status == "scheduled"]
    if not sched:
        return Validation(ok=True, violations=[], counts={})
    d0 = add_days(as_of.astimezone(tz).date(), -1)
    d1 = add_days(max(o.end for o in sched).astimezone(tz).date(), 2)

    # ---- master facts
    routing_of: dict[str, Any] = {}
    qty_of: dict[str, float] = {}
    for w in snap.work_orders:
        routing_of[w.id] = ds.routings.get(w.routing_id) if w.routing_id else None
        qty_of[w.id] = w.qty
    planned_by_id = {p.id: p for p in (snap.mrp.planned if snap.mrp else ())}
    for p in planned_by_id.values():
        routing_of[p.id] = ds.routings.get(p.routing_id) if p.routing_id else None
        qty_of[p.id] = p.qty
    matrix: dict[str, dict[tuple[str, str], float]] = {}
    for r in getattr(ds, "setup_matrix", {}).values():
        matrix.setdefault(r.line_setup_family, {})[(r.from_family, r.to_family)] = float(r.setup_minutes)
    rates = {(r.operation_id, r.line_id): r for r in getattr(ds, "operation_line_rates", {}).values()}

    def fam(item_id: str) -> str:
        it = ds.items.get(item_id)
        return (it.setup_family or it.family or "") if it is not None else ""

    def setup_formula(op: Any, line: Any, prev_fam: str | None, f: str) -> int:
        t = matrix.get(line.setup_family or "", {}) if line.setup_family else {}
        keys = ((("*", f), ("*", "*")) if prev_fam is None else
                ((prev_fam, f), (prev_fam, "*"), ("*", f), ("*", "*")))
        for k in keys:
            if k in t:
                return _ceil(t[k])
        r = rates.get((op.id, line.id))
        if r is not None and r.setup_minutes is not None:
            return _ceil(r.setup_minutes)
        return _ceil(op.setup_minutes)

    def run_formula(op: Any, line: Any, q: float) -> int:
        r = rates.get((op.id, line.id))
        n = _loads(op, q)
        if r is not None and r.run_minutes is not None:
            return _ceil(r.run_minutes * n)
        return _ceil(op.run_minutes * n / (line.speed_factor or 1.0))

    # ---- re-derived freeze (6.6): from the published plan, the plant freeze hours and as_of (M4)
    freeze = int(getattr(ds.plant, "aps_freeze_hours", 48) or 0) * 60
    edited = {(k[1], k[2]) for k in snap.moves} | {(k[1], k[2]) for _l, ks in snap.resequence for k in ks}
    frozen_pub: dict[tuple[str, int, int], Any] = {}
    # M4-DESIGN 6.1: the floor state supersedes published placements of active operations; frozen placements on a
    # closed line are re-planned (re-derived here from the snapshot, independent of the builder)
    # (re-derived here, independent of `aps.actuals` used by the builder - review M8)
    actuals = getattr(snap, "actuals", {}) or {}
    sup_keys = {k for k, a in actuals.items() if a.status in ("setup", "running", "paused") and a.line_id}
    closed_spans = _closed_spans(snap, res.params)
    moved_keys = {(p.order_id, p.seq, p.split_index) for p in (snap.published.ops if snap.published else ())
                  if p.line_id in closed_spans and p.start is not None and p.end is not None and
                  any(a < p.end and p.start < b for a, b in closed_spans[p.line_id])}
    if snap.published is not None:
        for p in snap.published.ops:
            if p.start is None or p.end is None or p.line_id is None:
                continue
            if (p.order_id, p.seq) in sup_keys or (p.order_id, p.seq, p.split_index) in moved_keys:
                continue
            ps_, pe_ = _m(as_of, p.start), _m(as_of, p.end)
            if pe_ <= 0:
                continue
            inprog = ps_ < 0 < pe_
            if not inprog and ps_ >= freeze:
                continue
            if not inprog and snap.override_freeze and (p.order_id, p.seq) in edited:
                continue
            frozen_pub[(p.order_id, p.seq, p.split_index)] = p

    # ---- allowed optional capacity (M4): opened only by the allow policy, forced only by open_shifts /
    # capacity_overrides(open_optional)
    forced_spans: dict[str, list[tuple[int, int]]] = {}
    for sh in res.params.open_shifts:
        forced_spans.setdefault(sh.line_id, []).append((_m(as_of, sh.start), _m(as_of, sh.end)))
    for ov in res.params.capacity_overrides:
        if ov.mode != "open_optional":
            continue
        for ln in ds.lines.values():
            if (ov.target_type == "line" and ln.id == ov.target_id) or (ov.target_type == "group" and
                                                                        ln.group_id == ov.target_id):
                forced_spans.setdefault(ln.id, []).append((_m(as_of, ov.start), _m(as_of, ov.end)))
    policy = res.summary.policy
    allowed_ot = []
    for w in res.overtime:
        if w.status == "suggested":
            continue
        a, b = _m(as_of, w.start), _m(as_of, w.end)
        ok = (w.status == "opened" and policy == "allow") or (
            w.status == "forced" and any(x < b and a < y for x, y in forced_spans.get(w.line_id, [])))
        if not ok:
            bad("APS_V_OVERTIME_POLICY", None, f"Optional time on line {w.line_id} is {w.status} although the run "
                f"(policy {policy}) does not allow it.", line_id=w.line_id)
            continue
        allowed_ot.append(w)

    # ---- open windows per line (base + opened/forced optional instances - closures)
    closes: dict[str, list[tuple[int, int]]] = {}
    for ov in res.params.capacity_overrides:
        if ov.mode != "close":
            continue
        for ln in ds.lines.values():
            if (ov.target_type == "line" and ln.id == ov.target_id) or (ov.target_type == "group" and
                                                                        ln.group_id == ov.target_id):
                closes.setdefault(ln.id, []).append((_m(as_of, ov.start), _m(as_of, ov.end)))
    opened_by_line: dict[str, list[tuple[int, int]]] = {}
    for w in allowed_ot:
        opened_by_line.setdefault(w.line_id, []).append((_m(as_of, w.start), _m(as_of, w.end)))
    for lid, spans in closed_spans.items():                          # M4 6.1 / 8: downtime, breakdowns
        for a, b in spans:
            closes.setdefault(lid, []).append((_m(as_of, a), _m(as_of, b)))
    for x in ds.calendar_exceptions.values():      # m6: exceptions as UTC instants (DST fall-back)
        for ln in ds.lines.values():
            if x.scope == "plant" or (x.scope == "group" and x.group_id == ln.group_id) or \
                    (x.scope == "line" and x.line_id == ln.id):
                closes.setdefault(ln.id, []).append((_m(as_of, x.start), _m(as_of, x.end)))
    used_lines = sorted({o.line_id for o in sched if o.line_id})
    windows: dict[str, list[tuple[int, int]]] = {}
    for lid in used_lines:
        if lid not in ds.lines:
            continue
        det = line_detail(ds, lid, d0, d1, with_exceptions=False)
        base = [(loc(p.start), loc(p.end)) for p in det.pieces if p.kind == "base"]
        opt = [(loc(p.start), loc(p.end)) for p in det.pieces if p.kind == "optional" and any(
            loc(p.start) < b and a < loc(p.end) for a, b in opened_by_line.get(lid, []))]
        win = _union(base + opt)
        cl = _union(closes.get(lid, []))
        win = _union(win)
        if cl:
            out = []
            for s, e in win:
                cur = s
                for a, b in cl:
                    if b <= cur or a >= e:
                        continue
                    if a > cur:
                        out.append((cur, a))
                    cur = max(cur, b)
                if cur < e:
                    out.append((cur, e))
            win = out
        windows[lid] = win

    # ---- per operation checks
    tool_need: dict[int, list[tuple[str, int]]] = {}
    fixed_ops = {o.op_no for o in sched if (o.order.id, o.seq, o.split.index) in frozen_pub}
    by_line: dict[str, list[Any]] = {}
    for o in sched:
        by_line.setdefault(o.line_id or "", []).append(o)
    for lst in by_line.values():
        lst.sort(key=lambda x: (_m(as_of, x.start), x.op_no))
    for o in sched:
        line = ds.lines.get(o.line_id or "")
        rt = routing_of.get(o.order.id)
        rop = next((x for x in rt.operations if x.seq == o.seq), None) if rt is not None else None
        item = ds.items.get(o.order.item_id)
        if line is None or rop is None or item is None:
            bad("APS_V_ELIGIBLE", o.op_no, f"Op {o.op_no}: unknown line / operation.")
            continue
        if line.group_id != rop.group_id or not line.active or not line_eligible(line, item):
            bad("APS_V_ELIGIBLE", o.op_no, f"Op {o.op_no} is on {line.code}, which is not eligible.",
                line_id=line.id)
        s, e = _m(as_of, o.start), _m(as_of, o.end)
        pcs = [(_m(as_of, p.start), _m(as_of, p.end)) for p in o.pieces] or [(s, e)]
        pub = frozen_pub.get((o.order.id, o.seq, o.split.index))
        fixed = pub is not None
        act = actuals.get((o.order.id, o.seq)) if o.order.type == "wo" else None
        if act is not None and (o.order.id, o.seq) in sup_keys:
            if o.line_id != act.line_id:
                bad("APS_V_ACTUAL", o.op_no, f"Op {o.op_no} is {act.status} on the floor but planned on another "
                    "line.", line_id=o.line_id)
            elif _m(as_of, o.start) < 0:
                bad("APS_V_ACTUAL", o.op_no, f"Op {o.op_no} is planned before the planning start.")
            elif getattr(ds.lines.get(o.line_id or ""), "parallel_capacity", 1) == 1:
                # first on its (single-slot) line: nothing re-planned starts before it (fixed work may)
                st = _m(as_of, o.start)
                for x in by_line.get(o.line_id or "", []):
                    if x is o or x.frozen or x.locked or (x.order.id, x.seq) in sup_keys:
                        continue
                    if _m(as_of, x.start) < st:
                        bad("APS_V_ACTUAL", o.op_no, f"Op {o.op_no} is {act.status} on the floor but op "
                            f"{x.op_no} is planned before it on its line.", line_id=o.line_id)
                        break
        elif o.frozen and not fixed:
            bad("APS_V_FROZEN", o.op_no, f"Op {o.op_no} is marked frozen but is not frozen in the published plan.")
        if fixed and (o.line_id != pub.line_id or abs(_m(as_of, o.start) - _m(as_of, pub.start)) > 0):
            bad("APS_V_FROZEN", o.op_no, f"Op {o.op_no} is frozen in the published plan but was moved.")
        need_tools = sorted((t.tool_pool_id, int(t.qty)) for t in rop.tools)
        if sorted((t.tool_pool_id, t.qty) for t in o.tools) != need_tools:
            bad("APS_V_TOOL", o.op_no, f"Op {o.op_no}: tools differ from the routing operation.")
        tool_need[o.op_no] = need_tools
        win = windows.get(line.id, [])
        if not fixed:
            for a, b in pcs:
                if b > a and not _inside(win, a, b):
                    bad("APS_V_WINDOW", o.op_no, f"Op {o.op_no} on {line.code} runs outside an open window "
                        f"({o.start.astimezone(tz):%a %d %b %H:%M}).", line_id=line.id)
                    break
            if not rop.interruptible and len([p for p in pcs if p[1] > p[0]]) > 1:
                bad("APS_V_CONTINUOUS", o.op_no, f"Op {o.op_no} is not interruptible but has several pieces.")
            work = sum(b - a for a, b in pcs)
            if work != o.setup_minutes + o.run_minutes or pcs[0][0] != s or pcs[-1][1] != e:
                bad("APS_V_DURATION", o.op_no, f"Op {o.op_no}: pieces carry {work} min, expected "
                    f"{o.setup_minutes + o.run_minutes}.")
            if o.run_minutes != run_formula(rop, line, o.qty):
                bad("APS_V_DURATION", o.op_no, f"Op {o.op_no}: run {o.run_minutes} min, formula "
                    f"{run_formula(rop, line, o.qty)} min.")
            f = fam(o.order.item_id)
            prevs = [x for x in by_line[line.id] if x is not o and _m(as_of, x.end) <= s]
            cand = {setup_formula(rop, line, None, f)}
            if prevs:
                if line.parallel_capacity == 1:
                    pv = max(prevs, key=lambda x: (_m(as_of, x.end), x.op_no))
                    cand = {0} if (pv.order.id == o.order.id and pv.seq == o.seq) else \
                        {setup_formula(rop, line, fam(pv.order.item_id), f)}
                else:
                    cand |= {setup_formula(rop, line, fam(x.order.item_id), f) for x in prevs}
                    if any(x.order.id == o.order.id and x.seq == o.seq for x in prevs):
                        cand.add(0)
            if o.setup_minutes not in cand:
                bad("APS_V_DURATION", o.op_no, f"Op {o.op_no}: setup {o.setup_minutes} min does not match the "
                    f"changeover on {line.code} ({sorted(cand)}).")
        # crew
        k = int(rop.crew_size)
        if k > 0 and not fixed:  # crew
            if rop.labor == "attended":
                att = pcs
            else:
                att, left = [], o.setup_minutes
                for a, b in pcs:
                    if left <= 0:
                        break
                    take = min(left, b - a)
                    att.append((a, a + take))
                    left -= take
            slots = [(c.operator_id, _m(as_of, c.start), _m(as_of, c.end)) for c in o.crew]
            pts = sorted({p for a, b in att for p in (a, b)} | {p for _e, a, b in slots for p in (a, b)})
            for x, y in zip(pts, pts[1:]):
                if y <= x or not any(a <= x and y <= b for a, b in att):
                    continue
                who = {e for e, a, b in slots if a <= x and y <= b}
                if len(who) < k:
                    bad("APS_V_CREW_COUNT", o.op_no, f"Op {o.op_no}: {len(who)} of {k} operators at "
                        f"{as_of + timedelta(minutes=x):%d %b %H:%M}.")
                    break
            for e, a, b in slots:
                emp = ds.operators.get(e)
                if emp is None or not emp.active or (rop.skill_id and rop.skill_id not in emp.skill_ids):
                    bad("APS_V_CREW_SKILL", o.op_no, f"Op {o.op_no}: operator {emp.code if emp else e} is not "
                        "qualified.", operator_id=e)
    # ---- operator shifts / absences / double booking
    slots_by_emp: dict[str, list[tuple[int, int, int]]] = {}
    for o in sched:
        for c in o.crew:
            slots_by_emp.setdefault(c.operator_id, []).append((_m(as_of, c.start), _m(as_of, c.end), o.op_no))
    for e, lst in sorted(slots_by_emp.items()):
        if e not in ds.operators:
            continue
        avail = _union((loc(a), loc(b)) for a, b in operator_intervals(ds, e, d0, d1, with_absences=False))
        absent = _union((_m(as_of, x.start), _m(as_of, x.end)) for x in getattr(ds, "operator_absences", {}).values()
                        if x.operator_id == e)
        lst.sort()
        far_end, far_op = -(1 << 60), None
        for a, b, n in lst:
            if n not in fixed_ops and (not _inside(avail, a, b) or any(x < b and a < y for x, y in absent)):
                bad("APS_V_CREW_SHIFT", n, f"Op {n}: operator {ds.operators[e].code} is off shift or absent.",
                    operator_id=e)
            if a < far_end and far_op != n:
                bad("APS_V_CREW_DOUBLE", n, f"Op {n}: operator {ds.operators[e].code} is also on op "
                    f"{far_op}.", operator_id=e)
            if b > far_end:
                far_end, far_op = b, n
    # ---- line capacity (M4 6.3: compatible batch operations sharing one load on a batch_merge line count once)
    for lid, lst in by_line.items():
        line = ds.lines.get(lid)
        if line is None:
            continue
        lst = _collapse_loads(line, lst, routing_of, ds)
        ev = sorted([(_m(as_of, o.start), 1, o.op_no) for o in lst] + [(_m(as_of, o.end), -1, o.op_no) for o in lst],
                    key=lambda x: (x[0], x[1]))
        n = 0
        for t, d, no in ev:
            n += d
            if n > line.parallel_capacity:
                bad("APS_V_CAPACITY", no, f"{line.code}: more than {line.parallel_capacity} operation(s) at once.",
                    line_id=lid)
                break
    # ---- tools
    use: dict[str, list[tuple[int, int, int, int]]] = {}
    for o in sched:
        for pool, q in tool_need.get(o.op_no, [(t.tool_pool_id, t.qty) for t in o.tools]):
            use.setdefault(pool, []).append((_m(as_of, o.start), _m(as_of, o.end), q, o.op_no))
    for pool, lst in use.items():
        cap = ds.tool_pools[pool].quantity if pool in ds.tool_pools else 0
        ev = sorted([(a, q, n) for a, b, q, n in lst] + [(b, -q, n) for a, b, q, n in lst], key=lambda x: (x[0], x[1]))
        tot = 0
        for t, q, n in ev:
            tot += q
            if tot > cap:
                bad("APS_V_TOOL", n, f"Tool pool {ds.tool_pools[pool].code if pool in ds.tool_pools else pool}: "
                    f"{tot} > {cap} in use.", tool_pool_id=pool)
                break
    # ---- precedence within orders, material (pegs)
    by_order: dict[str, list[Any]] = {}
    for o in res.operations:
        by_order.setdefault(o.order.id, []).append(o)
    end_of: dict[str, int] = {}
    for oid, lst in by_order.items():
        if all(x.status == "scheduled" for x in lst):
            end_of[oid] = max(_m(as_of, x.end) for x in lst)
    for oid, lst in by_order.items():
        rt = routing_of.get(oid)
        if rt is None:
            continue
        seqs = sorted({x.seq for x in lst})
        ops = {op.seq: op for op in rt.operations}
        for s1, s2 in zip(seqs, seqs[1:]):
            a = [x for x in lst if x.seq == s1 and x.status == "scheduled"]
            b = [x for x in lst if x.seq == s2 and x.status == "scheduled"]
            if not a or not b or any(x.frozen for x in b):
                continue
            pa, pb = ops[s1], ops[s2]
            g = _ceil(pa.move_minutes + pa.wait_minutes + pb.queue_minutes)
            a_s, a_e = min(_m(as_of, x.start) for x in a), max(_m(as_of, x.end) for x in a)
            b_s, b_e = min(_m(as_of, x.start) for x in b), max(_m(as_of, x.end) for x in b)
            overlap = pa.transfer_batch and not pa.inspection_gate and pa.transfer_batch < sum(x.qty for x in a)
            if (not overlap and b_s < a_e + g) or (overlap and (b_s < a_s or b_e < a_e + g)):
                bad("APS_V_PRECEDENCE", b[0].op_no, f"Op {b[0].op_no} (seq {s2}) starts before seq {s1} allows.")
    if res.params.material != "ignore" and snap.mrp is not None:
        mid = lambda d: _m(as_of, datetime(d.year, d.month, d.day, tzinfo=tz))  # noqa: E731
        comps: dict[str, list[Any]] = {w.id: list(w.components) for w in snap.work_orders}
        keys = {w.id: ("wo", w.id) for w in snap.work_orders}
        for p in planned_by_id.values():
            comps[p.id] = list(p.components)
            keys[p.id] = ("planned", str(p.planned_no))
        child_end: dict[str, int] = {}
        for w in snap.work_orders:
            if w.id in end_of:
                child_end[f"wo:{w.id}"] = end_of[w.id]
        for p in planned_by_id.values():
            if p.id in end_of:
                child_end[f"planned:{p.planned_no}"] = end_of[p.id]
        planned_by_no = {str(p.planned_no): p.id for p in planned_by_id.values()}
        PARTIAL = -1
        for oid, lst in by_order.items():
            sch = [x for x in lst if x.status == "scheduled" and (x.order.id, x.seq, x.split.index) not in frozen_pub
                   and (x.order.id, x.seq) not in sup_keys]
            if not sch or oid not in keys:
                continue
            first = min(x.seq for x in lst)
            for c in comps.get(oid, []):
                if c.qty <= 1e-9:
                    continue
                seq = c.operation_seq if any(x.seq == c.operation_seq for x in lst) else first
                tgt = [x for x in sch if x.seq == seq]
                if not tgt:
                    continue
                st = min(_m(as_of, x.start) for x in tgt)
                pn = ds.items[c.item_id].part_number if c.item_id in ds.items else c.item_id
                sups = snap.mrp.pegs.get((keys[oid][0], keys[oid][1], c.item_id), ())
                needs: list[int | None] = []
                for sp in sups:
                    if sp.kind in ("po_schedule", "pr_schedule", "po", "pr") and sp.available_date:
                        needs.append(max(0, mid(sp.available_date)))
                    elif sp.kind in ("work_order", "wo"):
                        needs.append(child_end.get(f"wo:{sp.ref_id}", PARTIAL) if sp.ref_id in by_order else None)
                    elif sp.kind == "planned":
                        no = str(sp.planned_no if sp.planned_no is not None else sp.ref_id)
                        pid = planned_by_no.get(no)
                        if pid is not None and pid in by_order:
                            needs.append(child_end.get(f"planned:{no}", PARTIAL))
                        elif sp.available_date:
                            needs.append(max(0, mid(sp.available_date)))
                covered = sum(x.qty for x in sups)
                if covered + 1e-6 < c.qty:            # live fallback (6.4), replayed
                    need_q = c.qty - covered
                    free = snap.stock_now.get(c.item_id, 0.0)
                    if free + 1e-6 < need_q:
                        rest, got, when = need_q - max(0.0, free), 0.0, None
                        for sup in sorted((x for x in snap.open_supply if x.item_id == c.item_id),
                                          key=lambda x: (x.available_date, x.ref_id)):
                            got += sup.qty
                            if got + 1e-6 >= rest:
                                when = max(0, mid(sup.available_date))
                                break
                        if when is None:
                            bad("APS_V_MATERIAL", tgt[0].op_no, f"Op {tgt[0].op_no} is scheduled but {pn} has no "
                                "supply.", item_id=c.item_id)
                            continue
                        needs.append(when)
                if PARTIAL in needs:
                    bad("APS_V_MATERIAL", tgt[0].op_no, f"Op {tgt[0].op_no} uses {pn} from a child order that is "
                        "not completely scheduled.", item_id=c.item_id)
                    continue
                need = max((x for x in needs if x is not None), default=None)
                if need is not None and st < need:
                    bad("APS_V_MATERIAL", tgt[0].op_no, f"Op {tgt[0].op_no} starts before its component {pn} is "
                        "available.", item_id=c.item_id)
    # ---- every operation present with its quantity (M4)
    from ..aps.pure import wo_routing_id

    hz_date = res.horizon_end.astimezone(tz).date()
    expected: list[tuple[str, Any, float, frozenset[int], Any]] = []
    for w in snap.work_orders:
        rid = wo_routing_id(ds, w.item_id, w.start_date, w.serial_from, w.routing_id)
        if rid in ds.routings and w.qty > 1e-9 and w.item_id in ds.items:
            expected.append((w.id, ds.routings[rid], w.qty, w.done_seqs, ds.items[w.item_id]))
    if res.params.include_planned:
        for p in planned_by_id.values():
            if p.routing_id in ds.routings and p.start_date <= hz_date and p.item_id in ds.items:
                expected.append((p.id, ds.routings[p.routing_id], p.qty, frozenset(), ds.items[p.item_id]))
    for oid, rt, q, done, it in expected:
        ops = sorted(rt.operations, key=lambda x: x.seq)
        qs = lot_inputs(ops, q, is_count(it.uom))
        for op, need in zip(ops, qs):
            if op.seq in done:
                continue
            a = actuals.get((oid, op.seq))
            if a is not None and a.status != "pending":           # M4 6.1: the floor's remaining quantity
                if a.remaining <= 1e-9:
                    continue
                need = float(a.remaining)
            rows = [x for x in by_order.get(oid, []) if x.seq == op.seq]
            if not rows:
                bad("APS_V_MISSING", None, f"Operation {op.seq} of order {oid} is missing from the result.",
                    order_id=oid, seq=op.seq)
                continue
            if all(x.status == "scheduled" for x in rows) and abs(sum(x.qty for x in rows) - need) > \
                    1e-6 * max(1.0, need):
                bad("APS_V_QTY", rows[0].op_no, f"Operation {op.seq} of order {oid} carries "
                    f"{sum(x.qty for x in rows):g} instead of {need:g}.", order_id=oid, seq=op.seq)
    # ---- requested moves placed as requested (6.7)
    for (otype, oid, seq, si), mv in snap.moves.items():
        if mv[1] is None:
            continue
        hit = [o for o in sched if o.order.id == oid and o.seq == seq and o.split.index == si]
        if not hit or (mv[0] and hit[0].line_id != mv[0]) or _m(as_of, hit[0].start) != _m(as_of, mv[1]):
            bad("APS_V_EDIT", hit[0].op_no if hit else None, f"Operation {seq} of {oid} is not where the edit "
                "placed it.", order_id=oid, seq=seq)
    # ---- overtime weekly limits
    per: dict[tuple[str, tuple[int, int]], int] = {}
    for w in res.overtime:
        if w.status != "opened" or not w.assignment_id:
            continue
        d = w.start.astimezone(tz).date()
        k = (w.assignment_id, d.isocalendar()[:2])
        per[k] = per.get(k, 0) + w.minutes
    for (aid, wk), mins in sorted(per.items()):
        a = ds.shift_assignments.get(aid)
        if a is not None and a.max_hours_per_week is not None and mins > a.max_hours_per_week * 60 + EPS:
            bad("APS_V_OVERTIME_LIMIT", None, f"Optional shift {aid} opens {mins / 60:.1f} h in week {wk[1]} "
                f"(max {a.max_hours_per_week} h).", assignment_id=aid)
    # ---- locks
    for (otype, oid, seq, si), p in snap.locked.items():
        hit = [o for o in sched if o.order.id == oid and o.seq == seq and o.split.index == si]
        if p.start is not None and (not hit or hit[0].line_id != p.line_id or
                                    abs(_m(as_of, hit[0].start) - _m(as_of, p.start)) > 0):
            bad("APS_V_LOCKED", hit[0].op_no if hit else None, f"Locked operation {oid}/{seq} moved.")
    counts: dict[str, int] = {}
    for v in viol:
        counts[v.code] = counts.get(v.code, 0) + 1
    return Validation(ok=not viol, violations=viol[:500], counts=counts)


__all__ = ["validate"]
_unused = (DAY, date, is_count, lot_inputs)


def _collapse_loads(line: Any, lst: list[Any], routing_of: dict[str, Any], ds: Any) -> list[Any]:
    """Operations on one load: same line / start / end, `run_per = batch`, same group, item setup family, units per
    batch and run minutes, total units <= units per batch. Each such load counts as one occupant."""
    if not getattr(line, "batch_merge", False):
        return lst
    groups: dict[tuple[Any, Any], list[Any]] = {}
    for o in lst:
        groups.setdefault((o.start, o.end), []).append(o)
    out = []
    for xs in groups.values():
        if len(xs) < 2:
            out += xs
            continue
        keys = set()
        upb = None
        for o in xs:
            rt = routing_of.get(o.order.id)
            rop = next((r for r in rt.operations if r.seq == o.seq), None) if rt is not None else None
            it = ds.items.get(o.order.item_id)
            if rop is None or rop.run_per != "batch" or not rop.units_per_batch:
                keys.add(None)
                break
            keys.add((rop.group_id, getattr(it, "setup_family", None) or getattr(it, "family", None),
                      rop.units_per_batch, float(rop.run_minutes)))
            upb = rop.units_per_batch
        if len(keys) == 1 and None not in keys and sum(o.qty for o in xs) <= (upb or 0) + 1e-6:
            out.append(xs[0])
        else:
            out += xs
    return out


def _closed_spans(snap: Any, params: Any) -> dict[str, list[tuple[Any, Any]]]:
    """Downtime (end, else expected end, else as_of + 4 h) and what-if breakdowns per line (M4 6.1 / 8)."""
    from datetime import timedelta

    out: dict[str, list[tuple[Any, Any]]] = {}
    for d in getattr(snap, "downtime", ()) or ():
        end = d.end or (max(d.expected_end, snap.as_of) if d.expected_end else max(snap.as_of, d.start)
                        + timedelta(hours=4))
        if end > snap.as_of and end > d.start:
            out.setdefault(d.line_id, []).append((d.start, end))
    for b in getattr(params, "line_breakdowns", ()) or ():
        out.setdefault(b.line_id, []).append((b.start, b.start + timedelta(hours=float(b.hours))))
    return out

