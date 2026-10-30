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
    for w in res.overtime:
        if w.status in ("opened", "forced"):
            opened_by_line.setdefault(w.line_id, []).append((_m(as_of, w.start), _m(as_of, w.end)))
    used_lines = sorted({o.line_id for o in sched if o.line_id})
    windows: dict[str, list[tuple[int, int]]] = {}
    for lid in used_lines:
        if lid not in ds.lines:
            continue
        det = line_detail(ds, lid, d0, d1)
        base = [(loc(p.start), loc(p.end)) for p in det.pieces if p.kind == "base"]
        opt = [(loc(p.start), loc(p.end)) for p in det.pieces if p.kind == "optional" and any(
            loc(p.start) < b and a < loc(p.end) for a, b in opened_by_line.get(lid, []))]
        win = _union(base + opt)
        cl = _union(closes.get(lid, []))
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
        fixed = o.frozen
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
        if k > 0 and not fixed:
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
        avail = _union((loc(a), loc(b)) for a, b in operator_intervals(ds, e, d0, d1))
        lst.sort()
        frozen_ops = {o.op_no for o in sched if o.frozen}
        for i, (a, b, n) in enumerate(lst):
            if n not in frozen_ops and not _inside(avail, a, b):
                bad("APS_V_CREW_SHIFT", n, f"Op {n}: operator {ds.operators[e].code} is off shift or absent.",
                    operator_id=e)
            if i > 0 and a < lst[i - 1][1] and lst[i - 1][2] != n:
                bad("APS_V_CREW_DOUBLE", n, f"Op {n}: operator {ds.operators[e].code} is also on op "
                    f"{lst[i - 1][2]}.", operator_id=e)
    # ---- line capacity
    for lid, lst in by_line.items():
        line = ds.lines.get(lid)
        if line is None:
            continue
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
        for t in o.tools:
            use.setdefault(t.tool_pool_id, []).append((_m(as_of, o.start), _m(as_of, o.end), t.qty, o.op_no))
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
        for oid, lst in by_order.items():
            sch = [x for x in lst if x.status == "scheduled" and not x.frozen]
            if not sch:
                continue
            first = min(x.seq for x in lst)
            for c in comps.get(oid, []):
                seq = c.operation_seq if any(x.seq == c.operation_seq for x in lst) else first
                tgt = [x for x in sch if x.seq == seq]
                if not tgt:
                    continue
                st = min(_m(as_of, x.start) for x in tgt)
                for sp in snap.mrp.pegs.get((keys[oid][0], keys[oid][1], c.item_id), ()):
                    need = None
                    if sp.kind in ("po_schedule", "pr_schedule", "po", "pr") and sp.available_date:
                        need = max(0, mid(sp.available_date))
                    elif sp.kind in ("work_order", "wo"):
                        need = child_end.get(f"wo:{sp.ref_id}")
                    elif sp.kind == "planned":
                        need = child_end.get(f"planned:{sp.planned_no if sp.planned_no is not None else sp.ref_id}")
                    if need is not None and st < need:
                        bad("APS_V_MATERIAL", tgt[0].op_no, f"Op {tgt[0].op_no} starts before its component "
                            f"{ds.items[c.item_id].part_number if c.item_id in ds.items else c.item_id} is available.",
                            item_id=c.item_id)
                        break
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
