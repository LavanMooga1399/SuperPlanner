"""Shift windows (M1-DESIGN 4.6). Internally every instant is an integer "local minute" = `date.toordinal() * 1440
+ minute of day` (wall clock) in the plant time `tz.plant_tz` (M3 5: the IANA zone if set, else the fixed offset);
results are converted to aware datetimes (fold 0) at the end. Durations of windows are elapsed UTC minutes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from typing import Any

from .dataset import MfgDataset
from .model import ShiftAssignmentRecord, ShiftDef, ShiftTemplateInput, WeekWindow, Window, WEEKDAYS

DAY = 1440
WEEK = 7 * DAY
Interval = tuple[int, int]


def hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def add_days(d: date, n: int) -> date:
    """`d + n days`, saturating at `date.min` / `date.max` instead of raising OverflowError (inputs are bounded to
    `limits.MIN_DATE..MAX_DATE`; this keeps the internal arithmetic total for any stored value)."""
    o = d.toordinal() + n
    return date.fromordinal(min(max(o, 1), date.max.toordinal()))


from .tz import offset_tz, plant_tz  # noqa: E402  (offset_tz re-exported for M1/M2 callers)


def to_local_minute(dt: datetime, tz: tzinfo, *, ceil: bool = False) -> int:
    loc = dt.astimezone(tz)
    base = loc.date().toordinal() * DAY + loc.hour * 60 + loc.minute
    if ceil and (loc.second or loc.microsecond):
        base += 1
    return base


def from_local_minute(m: int, tz: tzinfo) -> datetime:
    d = date.fromordinal(m // DAY)
    mm = m % DAY
    return datetime(d.year, d.month, d.day, mm // 60, mm % 60, tzinfo=tz)


# ---------------------------------------------------------------- interval helpers (sorted, non-overlapping lists)


def union(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(intervals):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def subtract(a: list[Interval], b: list[Interval]) -> list[Interval]:
    """a - b; both sorted and merged."""
    out: list[Interval] = []
    j = 0
    for s, e in a:
        cur = s
        while j < len(b) and b[j][1] <= cur:
            j += 1
        k = j
        while k < len(b) and b[k][0] < e:
            bs, be = b[k]
            if bs > cur:
                out.append((cur, bs))
            cur = max(cur, be)
            if cur >= e:
                break
            k += 1
        if cur < e:
            out.append((cur, e))
    return out


def minutes(intervals: list[Interval]) -> int:
    return sum(e - s for s, e in intervals)


# ---------------------------------------------------------------- shift geometry


def shift_span(sh: ShiftDef) -> Interval:
    """[start, end) in minutes relative to the start day's midnight (end may be > 1440)."""
    s = hhmm(sh.start)
    e = hhmm(sh.end)
    if e == s:
        e = s + DAY
    elif e < s:
        e += DAY
    return s, e


def break_span(sh: ShiftDef, start: str, end: str) -> Interval:
    s0, _ = shift_span(sh)
    bs, be = hhmm(start), hhmm(end)
    b0 = bs if bs >= s0 else bs + DAY
    return b0, b0 + ((be - bs) % DAY)


def shift_pieces(sh: ShiftDef, *, with_breaks: bool = True) -> list[Interval]:
    span = shift_span(sh)
    if not with_breaks or not sh.breaks:
        return [span]
    return subtract([span], union([break_span(sh, b.start, b.end) for b in sh.breaks]))


def validate_template(t: ShiftTemplateInput) -> list[dict[str, Any]]:
    """Pydantic-style error dicts (`loc`, `msg`, `type`); empty = valid (3.8 template rules)."""
    errors: list[dict[str, Any]] = []
    instances: list[tuple[int, int, int]] = []
    for i, sh in enumerate(t.shifts):
        s, e = shift_span(sh)
        bspans: list[Interval] = []
        for j, b in enumerate(sh.breaks):
            b0, b1 = break_span(sh, b.start, b.end)
            loc = ["body", "shifts", i, "breaks", j]
            if b1 <= b0:
                errors.append({"loc": loc, "msg": "A break must last longer than 0 minutes.", "type": "break_empty"})
            elif not (s <= b0 and b1 <= e):
                errors.append({"loc": loc, "msg": f"The break {b.start}-{b.end} is outside the shift "
                                                  f"{sh.start}-{sh.end}.", "type": "break_outside_shift"})
            else:
                for (c0, c1) in bspans:
                    if b0 < c1 and c0 < b1:
                        errors.append({"loc": loc, "msg": "Breaks of a shift must not overlap.",
                                       "type": "break_overlap"})
                        break
                bspans.append((b0, b1))
        for d in sh.days:
            base = WEEKDAYS.index(d) * DAY
            instances.append((base + s, base + e, i))
    # overlap on the reference week, with wrap-around
    pieces: list[tuple[int, int, int]] = []
    for s, e, i in instances:
        if e > WEEK:
            pieces.append((s, WEEK, i))
            pieces.append((0, e - WEEK, i))
        else:
            pieces.append((s, e, i))
    pieces.sort()
    reported: set[tuple[int, int]] = set()
    for a in range(len(pieces)):
        s1, e1, i1 = pieces[a]
        for b in range(a + 1, len(pieces)):
            s2, e2, i2 = pieces[b]
            if s2 >= e1:
                break
            pair = (min(i1, i2), max(i1, i2))
            if pair in reported:
                continue
            reported.add(pair)
            n1, n2 = t.shifts[pair[0]].name, t.shifts[pair[1]].name
            msg = (f"Shift {n1} overlaps itself on consecutive days." if pair[0] == pair[1]
                   else f"Shifts {n1} and {n2} overlap.")
            errors.append({"loc": ["body", "shifts", pair[1]], "msg": msg, "type": "shift_overlap"})
    return errors


def expand_template_week(t: ShiftTemplateInput) -> list[WeekWindow]:
    out: list[WeekWindow] = []
    for sh in t.shifts:
        for d in sh.days:
            base = WEEKDAYS.index(d) * DAY
            for s, e in shift_pieces(sh):
                out.append(WeekWindow.model_construct(shift=sh.name, day=d, start_minute=base + s,
                                                      end_minute=base + e))
    out.sort(key=lambda w: (w.start_minute, w.shift))
    return out


def week_minutes_per_day(t: ShiftTemplateInput) -> dict[str, int]:
    out = {d: 0 for d in WEEKDAYS}
    for w in expand_template_week(t):
        out[w.day] += w.end_minute - w.start_minute
    return out


# ---------------------------------------------------------------- line windows


@dataclass
class Piece:
    start: int
    end: int
    kind: str
    assignment_id: str | None
    shift: str
    template: str
    cost: float | None


def _assignment_active(a: ShiftAssignmentRecord, d: date) -> bool:
    return a.effective_from <= d and (a.effective_to is None or d < a.effective_to)


def _instances(ds: MfgDataset, template_id: str, shift_names: list[str], d: date, *, with_breaks: bool = True
               ) -> list[tuple[int, int, str, str]]:
    t = ds.shift_templates.get(template_id)
    if t is None:
        return []
    wd = WEEKDAYS[d.weekday()]
    base = d.toordinal() * DAY
    out = []
    for sh in t.shifts:
        if shift_names and sh.name not in shift_names:
            continue
        if wd not in sh.days:
            continue
        for s, e in shift_pieces(sh, with_breaks=with_breaks):
            out.append((base + s, base + e, sh.name, t.code))
    return out


def _cost_key(a: ShiftAssignmentRecord) -> tuple[Any, ...]:
    return (a.cost_per_hour or 0.0, a.effective_from, a.id)


@dataclass
class LineDetail:
    """Internals of `line_windows` (used by the health check): attributed pieces before clipping/merging, and per
    optional assignment its raw minutes and the minutes left after removing base time."""
    pieces: list[Piece]
    optional_raw: dict[str, int]
    optional_after_base: dict[str, int]


def line_detail(ds: MfgDataset, line_id: str, d0: date, d1: date, kinds: tuple[str, ...] = ("base", "optional")
                ) -> LineDetail:
    line = ds.lines[line_id]
    group = ds.groups.get(line.group_id)
    tz = plant_tz(ds.plant)
    lo, hi = d0.toordinal() * DAY, d1.toordinal() * DAY
    line_asg = [a for a in ds.shift_assignments.values() if a.target_type == "line" and a.line_id == line_id
                and line.active]
    group_asg = [a for a in ds.shift_assignments.values() if a.target_type == "group" and a.group_id == line.group_id
                 and (group is None or group.active)]
    raw: dict[str, list[tuple[int, int, str, str, ShiftAssignmentRecord]]] = {"base": [], "optional": []}
    d = add_days(d0, -1)
    while d < d1:
        for kind in ("base", "optional"):
            src = [a for a in line_asg if a.kind == kind and _assignment_active(a, d)]
            if not src:
                src = [a for a in group_asg if a.kind == kind and _assignment_active(a, d)]
            for a in src:
                for s, e, name, tcode in _instances(ds, a.shift_template_id, a.shift_names, d):
                    raw[kind].append((s, e, name, tcode, a))
        if d == date.max:
            break
        d = add_days(d, 1)
    # exceptions (plant, the line's group, the line)
    exc: list[Interval] = []
    for x in ds.calendar_exceptions.values():
        if x.scope == "plant" or (x.scope == "group" and x.group_id == line.group_id) or \
                (x.scope == "line" and x.line_id == line_id):
            s, e = to_local_minute(x.start, tz), to_local_minute(x.end, tz, ceil=True)
            if e > lo - DAY and s < hi:
                exc.append((s, e))
    exc = union(exc)
    pieces: list[Piece] = []
    taken: list[Interval] = []
    opt_raw: dict[str, int] = {}
    opt_after: dict[str, int] = {}
    base_union: list[Interval] = []
    for kind in ("base", "optional"):
        by_asg: dict[str, list[tuple[int, int, str, str]]] = {}
        asg: dict[str, ShiftAssignmentRecord] = {}
        for s, e, name, tcode, a in raw[kind]:
            by_asg.setdefault(a.id, []).append((s, e, name, tcode))
            asg[a.id] = a
        order = sorted(asg.values(), key=_cost_key)
        if kind == "optional":
            taken = list(base_union)
        else:
            taken = []
        for a in order:
            mine = by_asg[a.id]
            if kind == "optional":
                in_h = [(max(s, lo), min(e, hi)) for s, e, _n, _t in mine if s < hi and e > lo]
                u = union(in_h)
                opt_raw[a.id] = opt_raw.get(a.id, 0) + minutes(u)
                opt_after[a.id] = opt_after.get(a.id, 0) + minutes(subtract(u, base_union))
            claimed: list[Interval] = []
            for s, e, name, tcode in sorted(mine):
                for ps, pe in subtract([(s, e)], taken):
                    for qs, qe in subtract([(ps, pe)], exc):
                        pieces.append(Piece(qs, qe, kind, a.id, name, tcode,
                                            a.cost_per_hour if kind == "optional" else None))
                claimed.append((s, e))
            taken = union(taken + claimed)
        if kind == "base":
            base_union = taken
    pieces = [p for p in pieces if p.kind in kinds]
    return LineDetail(pieces, opt_raw, opt_after)


def _clip_merge(pieces: list[Piece], lo: int, hi: int) -> list[tuple[int, int, str, str | None, list[str], str,
                                                                        float | None]]:
    clipped = []
    for p in pieces:
        s, e = max(p.start, lo), min(p.end, hi)
        if s < e:
            clipped.append((s, e, p))
    clipped.sort(key=lambda x: (x[0], x[1]))
    merged: list[list[Any]] = []
    for s, e, p in clipped:
        if merged:
            m = merged[-1]
            if m[2] == p.kind and m[3] == p.assignment_id and s <= m[1]:
                m[1] = max(m[1], e)
                if p.shift not in m[4]:
                    m[4].append(p.shift)
                continue
        merged.append([s, e, p.kind, p.assignment_id, [p.shift], p.template, p.cost])
    return [tuple(m) for m in merged]  # type: ignore[misc]


def _windows(merged: list[Any], tz: tzinfo) -> list[Window]:
    return [Window.model_construct(start=from_local_minute(s, tz), end=from_local_minute(e, tz), kind=kind,
                                   assignment_id=aid, shift_label=f"{tcode}/{'+'.join(names)}", cost_per_hour=cost)
            for s, e, kind, aid, names, tcode, cost in merged]


def line_windows(ds: MfgDataset, line_id: str, d0: date, d1: date, *,
                 kinds: tuple[str, ...] | list[str] = ("base", "optional")) -> list[Window]:
    tz = plant_tz(ds.plant)
    det = line_detail(ds, line_id, d0, d1, tuple(kinds))
    merged = _clip_merge(det.pieces, d0.toordinal() * DAY, d1.toordinal() * DAY)
    return _windows(merged, tz)


def line_intervals(ds: MfgDataset, line_id: str, d0: date, d1: date,
                   kinds: tuple[str, ...] = ("base", "optional")) -> list[tuple[int, int, str, str]]:
    """(start, end, kind, shift_label) in local minutes, clipped and merged (health check helper)."""
    det = line_detail(ds, line_id, d0, d1, kinds)
    merged = _clip_merge(det.pieces, d0.toordinal() * DAY, d1.toordinal() * DAY)
    return [(s, e, kind, f"{tcode}/{'+'.join(names)}") for s, e, kind, _aid, names, tcode, _c in merged]


def absence_intervals(ds: MfgDataset, operator_id: str, tz: tzinfo | None = None) -> list[Interval]:
    """M3-DESIGN 3.2: the operator's absences as merged local-minute intervals."""
    tz = tz or plant_tz(ds.plant)
    out = [(to_local_minute(a.start, tz), to_local_minute(a.end, tz, ceil=True))
           for a in getattr(ds, "operator_absences", {}).values() if a.operator_id == operator_id]
    return union(out)


def operator_intervals(ds: MfgDataset, operator_id: str, d0: date, d1: date) -> list[Interval]:
    """Shift spans of the operator (breaks not removed) minus absences (M3 3.2), local minutes."""
    op = ds.operators[operator_id]
    if op.shift_template_id is None:
        return []
    lo, hi = d0.toordinal() * DAY, d1.toordinal() * DAY
    out: list[Interval] = []
    d = add_days(d0, -1)
    while d < d1:
        for s, e, _n, _t in _instances(ds, op.shift_template_id, op.shift_names, d, with_breaks=False):
            s, e = max(s, lo), min(e, hi)
            if s < e:
                out.append((s, e))
        if d == date.max:
            break
        d = add_days(d, 1)
    return subtract(union(out), absence_intervals(ds, operator_id))


def operator_windows(ds: MfgDataset, operator_id: str, d0: date, d1: date) -> list[Window]:
    """Shift spans of the operator's template / shift names (breaks NOT removed), clipped to [d0, d1); no
    exceptions; absences removed (M3 3.2). Touching spans are merged (label `<template>/<names>`); `kind` is
    "base", `assignment_id` None."""
    op = ds.operators[operator_id]
    if op.shift_template_id is None or op.shift_template_id not in ds.shift_templates:
        return []
    tz = plant_tz(ds.plant)
    pieces: list[Piece] = []
    d = add_days(d0, -1)
    while d < d1:
        for s, e, name, tcode in _instances(ds, op.shift_template_id, op.shift_names, d, with_breaks=False):
            pieces.append(Piece(s, e, "base", None, name, tcode, None))
        if d == date.max:
            break
        d = add_days(d, 1)
    absent = absence_intervals(ds, operator_id, tz)
    if absent:
        cut: list[Piece] = []
        for p in pieces:
            for a, b in subtract([(p.start, p.end)], absent):
                cut.append(Piece(a, b, p.kind, p.assignment_id, p.shift, p.template, p.cost))
        pieces = cut
    return _windows(_clip_merge(pieces, d0.toordinal() * DAY, d1.toordinal() * DAY), tz)


def window_minutes(windows: list[Window]) -> dict[str, float]:
    out = {"base_minutes": 0.0, "optional_minutes": 0.0}
    for w in windows:   # elapsed (UTC) minutes: a shift across a DST change has its real length (M3 5)
        out[f"{w.kind}_minutes"] += (w.end.astimezone(UTC) - w.start.astimezone(UTC)).total_seconds() / 60.0
    return out


def group_capacity(ds: MfgDataset, group_id: str, d0: date, d1: date) -> dict[str, Any]:
    lines: dict[str, dict[str, float]] = {}
    base = opt = 0.0
    for ln in ds.lines_by_group.get(group_id, ()):
        if not ln.active:
            continue
        m = window_minutes(line_windows(ds, ln.id, d0, d1))
        b, o = m["base_minutes"] * ln.parallel_capacity, m["optional_minutes"] * ln.parallel_capacity
        lines[ln.id] = {"base_minutes": b, "optional_minutes": o}
        base += b
        opt += o
    return {"base_minutes": base, "optional_minutes": opt, "lines": lines}


def longest_window(intervals: list[tuple[int, int, str, str]]) -> int:
    """Longest continuous stretch, base and optional merged when touching regardless of kind/assignment."""
    best = 0
    for s, e in union([(s, e) for s, e, _k, _l in intervals]):
        best = max(best, e - s)
    return best


__all__ = ["expand_template_week", "group_capacity", "line_windows", "operator_windows", "validate_template",
           "week_minutes_per_day", "window_minutes"]
