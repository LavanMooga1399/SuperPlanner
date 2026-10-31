"""Replan trigger rules and policy (M4-DESIGN 7). Pure: the service passes the loaded facts and stores what these
functions return (at most one open trigger per `dedupe_key`).

| Kind | Condition | Severity | dedupe_key |
| `line_down` | downtime opened on a line with published operations in [now, now + 24 h] | critical | `line_down:<id>` |
| `late_receipt` | a schedule pegged by the published run is overdue or its date is later than the planned start of
  the consuming operation | warning (critical if it delays a frozen op) | `late_receipt:<schedule id>` |
| `scrap_shortfall` | the WO can no longer reach its quantity | warning (critical if P1-P2) | `scrap:<wo id>` |
| `overrun` | projected end > planned end + max(tolerance x planned duration, 30 min) | warning | `overrun:<op>` |
| `rush_order` | demand line / WO with priority <= 2 due inside the published horizon | warning | `rush:<id>` |
| `not_started` | planned start + adherence tolerance passed, not started | info | `late_start:<op>` |
| `start_short` | operation started with a component shortage | info | `short:<op>` |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

OVERRUN_MIN_MINUTES = 30
LINE_DOWN_WINDOW = timedelta(hours=24)
RUSH_PRIORITY = 2


@dataclass(frozen=True)
class Trigger:
    kind: str
    severity: str
    ref_type: str
    ref_id: str
    dedupe_key: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def line_down(downtime_id: str, line_id: str, line_code: str, kind: str, ops: list[tuple[int, datetime, bool]],
              now: datetime) -> Trigger | None:
    """`ops`: published (op_no, start, frozen) on the line."""
    hit = [o for o in ops if now - timedelta(minutes=1) <= o[1] <= now + LINE_DOWN_WINDOW]
    if not hit:
        return None
    first = min(o[1] for o in hit)
    return Trigger("line_down", "critical", "downtime", downtime_id, f"line_down:{downtime_id}",
                   f"{line_code} is down ({kind}) with {len(hit)} published operation(s) in the next 24 h.",
                   {"line_id": line_id, "line_code": line_code, "ops_affected": len(hit),
                    "frozen_affected": sum(1 for o in hit if o[2]), "first_op_start": first.isoformat()})


def projected_end(now: datetime, remaining_qty: float, planned_qty: float, planned_run_minutes: float,
                  setup_left: float = 0.0) -> datetime:
    """APS-consistent projection (6.1): the remaining quantity at the planned rate from now."""
    rate = planned_run_minutes / planned_qty if planned_qty > 0 else 0.0
    return now + timedelta(minutes=max(0.0, remaining_qty) * rate + max(0.0, setup_left))


def overrun(wo_op_id: str, label: str, planned_start: datetime, planned_end: datetime, projected: datetime,
            tolerance_pct: float) -> Trigger | None:
    dur = (planned_end - planned_start).total_seconds() / 60.0
    tol = max(tolerance_pct / 100.0 * dur, OVERRUN_MIN_MINUTES)
    late = (projected - planned_end).total_seconds() / 60.0
    if late <= tol:
        return None
    return Trigger("overrun", "warning", "wo_operation", wo_op_id, f"overrun:{wo_op_id}",
                   f"{label} is projected to end {late:.0f} min after its planned end.",
                   {"planned_start": planned_start.isoformat(), "planned_end": planned_end.isoformat(),
                    "projected_end": projected.isoformat(), "tolerance_minutes": round(tol, 1),
                    "late_minutes": round(late, 1)})


def scrap_shortfall(wo_id: str, number: str, qty: float, reachable: float, priority: int) -> Trigger:
    return Trigger("scrap_shortfall", "critical" if priority <= RUSH_PRIORITY else "warning", "work_order", wo_id,
                   f"scrap:{wo_id}", f"{number} can no longer reach {qty:g} (at most {reachable:g} after scrap).",
                   {"qty": qty, "reachable": reachable, "priority": priority})


def start_short(wo_op_id: str, label: str, components: list[dict[str, Any]]) -> Trigger:
    return Trigger("start_short", "info", "wo_operation", wo_op_id, f"short:{wo_op_id}",
                   f"{label} started with {len(components)} short component(s).", {"components": components})


def not_started(wo_op_id: str, label: str, planned_start: datetime, now: datetime, tolerance_minutes: int
                ) -> Trigger | None:
    if now <= planned_start + timedelta(minutes=tolerance_minutes):
        return None
    late = (now - planned_start).total_seconds() / 60.0
    return Trigger("not_started", "info", "wo_operation", wo_op_id, f"late_start:{wo_op_id}",
                   f"{label} has not started {late:.0f} min after its planned start.",
                   {"planned_start": planned_start.isoformat(), "late_minutes": round(late, 1)})


def late_receipt(schedule_id: str, label: str, expected: date, today: date, consumer_start: datetime | None,
                 consumer_date: date | None, frozen: bool) -> Trigger | None:
    overdue = expected < today
    moved = consumer_date is not None and expected > consumer_date
    if not overdue and not moved:
        return None
    sev = "critical" if frozen else "warning"
    why = "is overdue" if overdue else "arrives after the planned start of its consuming operation"
    return Trigger("late_receipt", sev, "po_schedule", schedule_id, f"late_receipt:{schedule_id}",
                   f"{label} {why}.", {"expected": expected.isoformat(), "overdue": overdue,
                                        "consumer_start": consumer_start.isoformat() if consumer_start else None})


def rush_order(ref_type: str, ref_id: str, label: str, priority: int, due: date, horizon_end: date | None
               ) -> Trigger | None:
    if priority > RUSH_PRIORITY or horizon_end is None or due > horizon_end:
        return None
    return Trigger("rush_order", "warning", ref_type, ref_id, f"rush:{ref_id}",
                   f"{label} is priority {priority}, due {due.isoformat()} inside the published horizon.",
                   {"priority": priority, "due": due.isoformat()})


# ---------------------------------------------------------------- policy (7)

def wants_run(policy: str, severities: list[str]) -> bool:
    """`auto_whatif` / `auto_publish` start (or join) a debounced proposal for open warning / critical triggers."""
    return policy in ("auto_whatif", "auto_publish") and any(s in ("warning", "critical") for s in severities)


def auto_publish_check(validation_ok: bool, frozen_moved: int, wt_proposal: float, wt_published: float | None
                       ) -> tuple[bool, str]:
    """7: publish only when validator-clean, no frozen operation moved (except by downtime) and the weighted
    tardiness is not worse than the published plan's."""
    if not validation_ok:
        return False, "the proposal is not validator-clean"
    if frozen_moved:
        return False, f"{frozen_moved} frozen operation(s) would move"
    if wt_published is not None and wt_proposal > wt_published + 1e-6:
        return False, (f"weighted tardiness {wt_proposal:.0f} min is worse than the published plan's "
                       f"{wt_published:.0f} min")
    return True, ""


__all__ = ["Trigger", "auto_publish_check", "late_receipt", "line_down", "not_started", "overrun",
           "projected_end", "rush_order", "scrap_shortfall", "start_short", "wants_run"]
