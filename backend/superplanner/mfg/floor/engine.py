"""Pure shop-floor event rules (M4-DESIGN 4.2): the operation state machine, the replay of an operation's event log
into its state (also used by tests and the rebuild check), quantity checks over the WO's operation chain and the
backflush / receipt targets. No I/O: services load rows into `Ev` / `OpState` and apply the returned results.

Replay rules
- events are applied in `seq` order; a `correct` event replaces the quantities / time of the event it references
  (`corrects_event_id`; the latest correction wins) and is otherwise not a transition;
- `rework` pseudo-events (incoming units from a later operation, `Ev.event_type == "rework_in"`) add to
  `qty_rework_in` and re-open a completed operation (`paused`, 4.2);
- durations: setup = time in `setup`, run = time in `running` (pauses excluded); labour = interval minutes x the
  operators recorded on the event that opened the interval; negative intervals (backdated events) count 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

EPS = 1e-6

#: event -> statuses it may be applied from (4.2). `ready` is a computed view of `pending`.
FROM: dict[str, tuple[str, ...]] = {
    "setup_start": ("pending", "paused"),
    "start": ("pending", "setup", "paused"),
    "pause": ("setup", "running"),
    "resume": ("paused",),
    "report": ("setup", "running", "paused"),
    "complete": ("setup", "running", "paused"),
    "reopen": ("completed", "skipped"),          # reopening a skip reverts it (review M4)
    "skip": ("pending",),
    "correct": ("pending", "setup", "running", "paused", "completed", "skipped"),
}
SUPERVISOR_ONLY = frozenset({"reopen", "correct", "skip"})
QTY_EVENTS = frozenset({"report", "complete"})
ACTIVE = ("setup", "running")


class FloorRuleError(Exception):
    """A rule violation: `status` (HTTP), `code`, `message`, `details`."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


@dataclass(frozen=True)
class Ev:
    id: str
    seq: int
    event_type: str
    event_at: datetime
    line_id: str | None = None
    operators: int = 0
    qty_good: float | None = None
    qty_scrap: float | None = None
    qty_rework: float | None = None
    rework_to_seq: int | None = None
    corrects_event_id: str | None = None
    migrated: bool = False
    #: `correct` events: the fields they replace on their target (`event_at` only when the client gave a time)
    fields: tuple[str, ...] = ()


@dataclass
class OpState:
    status: str = "pending"
    before_pause: str | None = None
    qty_good: float = 0.0
    qty_scrap: float = 0.0
    qty_rework_out: float = 0.0
    qty_rework_in: float = 0.0
    line_id: str | None = None
    setup_minutes: float = 0.0
    run_minutes: float = 0.0
    labour_minutes: float = 0.0
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    last_seq: int | None = None
    since: datetime | None = None          # start of the open setup/running interval
    crew: int = 0                          # operators on the interval

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("status", "qty_good", "qty_scrap", "qty_rework_out", "qty_rework_in",
                                              "line_id", "setup_minutes", "run_minutes", "labour_minutes",
                                              "actual_start", "actual_end", "last_seq")}


def allowed_events(status: str, *, supervisor: bool = True) -> list[str]:
    st = "pending" if status == "ready" else status
    out = [e for e, f in FROM.items() if st in f and e != "correct"]
    if supervisor:
        out.append("correct")
    return [e for e in out if supervisor or e not in SUPERVISOR_ONLY]


def check_transition(status: str, event_type: str) -> None:
    st = "pending" if status == "ready" else status
    if event_type not in FROM or st not in FROM[event_type]:
        raise FloorRuleError(409, "FLR_INVALID_TRANSITION",
                             f"The operation is {status}; {event_type.replace('_', ' ')} is not allowed.",
                             {"status": status, "event": event_type, "allowed": allowed_events(status)})


def _minutes(a: datetime | None, b: datetime) -> float:
    if a is None:
        return 0.0
    return max(0.0, (b - a).total_seconds() / 60.0)


def _close_interval(st: OpState, at: datetime) -> None:
    if st.since is not None and st.status in ACTIVE:
        m = _minutes(st.since, at)
        if st.status == "setup":
            st.setup_minutes += m
        else:
            st.run_minutes += m
        st.labour_minutes += m * st.crew
    st.since = None


def _open_interval(st: OpState, at: datetime, crew: int) -> None:
    st.since, st.crew = at, crew


def apply(st: OpState, e: Ev) -> OpState:
    """One event on a state (a copy is returned). Raises `FloorRuleError` for an invalid transition."""
    st = replace(st)
    t = e.event_type
    if t == "rework_in":
        st.qty_rework_in += e.qty_rework or 0.0
        if st.status == "completed":
            st.status, st.before_pause, st.actual_end = "paused", "running", None
        st.last_seq = max(st.last_seq or 0, e.seq)
        return st
    if e.migrated:                         # M3 done marker (migration 0006): completed as is
        st.status, st.qty_good = "completed", st.qty_good + (e.qty_good or 0.0)
        st.actual_end, st.last_seq = e.event_at, e.seq
        return st
    check_transition(st.status, t)
    if e.line_id is not None and t in ("setup_start", "start", "resume", "report", "complete"):
        st.line_id = e.line_id
    if t == "setup_start":
        _close_interval(st, e.event_at)
        st.status = "setup"
        _open_interval(st, e.event_at, e.operators)
        if st.actual_start is None:
            st.actual_start = e.event_at
    elif t == "start":
        _close_interval(st, e.event_at)
        st.status = "running"
        _open_interval(st, e.event_at, e.operators)
        if st.actual_start is None:
            st.actual_start = e.event_at
    elif t == "pause":
        _close_interval(st, e.event_at)
        st.before_pause, st.status = st.status, "paused"
    elif t == "resume":
        st.status = st.before_pause or "running"
        st.before_pause = None
        _open_interval(st, e.event_at, e.operators)
    elif t in QTY_EVENTS:
        st.qty_good += e.qty_good or 0.0
        st.qty_scrap += e.qty_scrap or 0.0
        st.qty_rework_out += e.qty_rework or 0.0
        if t == "complete":
            _close_interval(st, e.event_at)
            st.status, st.before_pause, st.actual_end = "completed", None, e.event_at
            if st.actual_start is None:
                st.actual_start = e.event_at
        elif e.operators and st.since is not None:
            # a report with a (new) crew: the interval continues with that crew
            _close_interval(st, e.event_at)
            _open_interval(st, e.event_at, e.operators)
    elif t == "reopen":
        st.status, st.before_pause, st.actual_end = "paused", "running", None
    elif t == "skip":
        st.status = "skipped"
    st.last_seq = e.seq
    return st


def corrected(events: Iterable[Ev]) -> list[Ev]:
    """Resolve `correct` events: each replaces the quantity / time fields it carries on its target (latest wins);
    the `correct` events themselves are dropped."""
    evs = sorted(events, key=lambda e: e.seq)
    by_id = {e.id: e for e in evs}
    root: dict[str, str] = {}

    def root_of(eid: str) -> str:
        seen = set()
        while eid in by_id and by_id[eid].event_type == "correct" and by_id[eid].corrects_event_id and eid not in seen:
            seen.add(eid)
            eid = by_id[eid].corrects_event_id or eid
        return eid

    patched: dict[str, Ev] = {}
    for e in evs:
        if e.event_type != "correct" or not e.corrects_event_id:
            continue
        tid = root_of(e.corrects_event_id)
        root[e.id] = tid
        base = patched.get(tid, by_id.get(tid))
        if base is None:
            continue
        upd = {f: getattr(e, f) for f in e.fields
               if f in ("qty_good", "qty_scrap", "qty_rework", "rework_to_seq", "line_id", "event_at")}
        patched[tid] = replace(base, **upd)
    return [patched.get(e.id, e) for e in evs if e.event_type != "correct"]


def replay(events: Iterable[Ev], rework_in: Iterable[Ev] = ()) -> OpState:
    """The state of one operation from its events (any order; applied by `seq`) and the incoming rework of later
    operations (`rework_in` pseudo-events carrying `qty_rework` and the source event's `seq`)."""
    evs = corrected(events) + list(rework_in)
    evs.sort(key=lambda e: (e.seq, 0 if e.event_type != "rework_in" else 1))
    st = OpState()
    for e in evs:
        st = apply(st, e)
    return st


# ---------------------------------------------------------------- quantities over the operation chain (4.2)

@dataclass
class ChainOp:
    seq: int
    status: str
    qty_planned: float
    qty_good: float = 0.0
    qty_scrap: float = 0.0
    qty_rework_out: float = 0.0
    qty_rework_in: float = 0.0
    transfer_batch: int | None = None


@dataclass
class ChainView:
    seq: int
    qty_input: float          # predecessor good (first op: its qty_planned) + rework in
    qty_available: float      # input - good - scrap - rework out
    predecessor_done: bool
    ready: bool


def chain(ops: list[ChainOp]) -> dict[int, ChainView]:
    """Per operation (ascending seq): input, available input, predecessor state. Skipped operations pass their
    input through."""
    out: dict[int, ChainView] = {}
    prev_out: float | None = None
    prev_done = True
    prev_tb_ok = True
    for o in sorted(ops, key=lambda x: x.seq):
        base = o.qty_planned if prev_out is None else prev_out
        qin = base + o.qty_rework_in
        avail = qin - o.qty_good - o.qty_scrap - o.qty_rework_out
        ready = o.status == "pending" and (prev_done or prev_tb_ok)
        out[o.seq] = ChainView(o.seq, round(qin, 6), round(max(0.0, avail), 6), prev_done, ready)
        if o.status == "skipped":
            prev_out = qin
        else:
            prev_out = o.qty_good
            prev_done = o.status in ("completed",)
            prev_tb_ok = bool(o.transfer_batch) and o.qty_good + EPS >= float(o.transfer_batch or 0)
    return out


def check_quantities(view: ChainView, good: float, scrap: float, rework: float, *, forced: bool) -> None:
    used = good + scrap + rework
    if used > view.qty_available + EPS and not forced:
        raise FloorRuleError(422, "FLR_QTY_EXCEEDS_INPUT",
                             f"Good {_fmt(good)} + scrap {_fmt(scrap)}"
                             + (f" + rework {_fmt(rework)}" if rework else "")
                             + f" exceeds the available input {_fmt(view.qty_available)}.",
                             {"available": view.qty_available, "good": good, "scrap": scrap, "rework": rework})


def _fmt(x: float) -> str:
    return f"{x:g}"


def backflush_target(units: float, required_qty: float, wo_qty: float, count_uom: bool) -> float:
    """Cumulative backflush of a component after `units` (good + scrap) of its operation: units x per-unit
    requirement, rounded as M2 7.2 (count UoM up to whole units)."""
    import math

    if wo_qty <= EPS:
        return 0.0
    q = units * required_qty / wo_qty
    return float(math.ceil(q - EPS)) if count_uom else round(q, 6)


def shortfall(wo_qty: float, chain_ops: list[ChainOp]) -> bool:
    """4.3 WO shortfall: every unit not scrapped can still become good output (rework loses nothing), so the WO can
    no longer reach its quantity when the first operation's input minus all scrap is below it."""
    if not chain_ops:
        return False
    first = min(chain_ops, key=lambda o: o.seq)
    return first.qty_planned - sum(o.qty_scrap for o in chain_ops) < wo_qty - EPS


__all__ = ["ACTIVE", "ChainOp", "ChainView", "Ev", "FROM", "FloorRuleError", "OpState", "SUPERVISOR_ONLY",
           "allowed_events", "apply", "backflush_target", "chain", "check_quantities", "check_transition",
           "corrected", "replay", "shortfall"]

