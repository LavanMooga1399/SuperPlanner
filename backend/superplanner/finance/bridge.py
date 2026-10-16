"""Send to planner (FINANCE.md 16.1): the next 1-12 months of a finance result as a scheduling `Problem`.

The only finance module that imports the scheduling engine, and only `superplanner.engine.model`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from superplanner.engine.model import Calendar, Problem, Requirement, Resource, Task, Terminology

from . import timegrid as tg
from .advisor.messages import format_money
from .defaults import DISCLAIMER
from .model import FinancePlan, FinanceResult

PRIORITY = {"must": 9, "should": 6, "nice": 3}
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")
MAX_NAME = 200


def _tz(utc_offset: str) -> timezone:
    m = _OFFSET_RE.match(utc_offset or "+00:00")
    if not m or int(m.group(2)) > 14 or int(m.group(3)) > 59:
        raise ValueError(f"invalid utc_offset {utc_offset!r}; expected e.g. '+05:30'")
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def _name(text: str) -> str:
    return text if len(text) <= MAX_NAME else text[: MAX_NAME - 3] + "..."


def _at(month: str, day: int, hhmm: str, tz: timezone) -> datetime:
    y, m = tg.parse_month(month)
    h, mi = (int(x) for x in hhmm.split(":"))
    return datetime(y, m, day, h, mi, tzinfo=tz)


def to_planner_problem(plan: FinancePlan, result: FinanceResult, *, name: str, months: int = 12,
                       utc_offset: str = "+00:00", review_every_months: int = 3,
                       include_rebalances: bool = True) -> tuple[Problem, int]:
    if not 1 <= months <= 12:
        raise ValueError("months must be between 1 and 12")
    if not 1 <= review_every_months <= 12:
        raise ValueError("review_every_months must be between 1 and 12")
    tz = _tz(utc_offset)
    start = result.start_month
    h0 = _at(start, 1, "00:00", tz)
    h1 = _at(tg.add_months(start, months), 1, "00:00", tz)
    horizon_days = (h1 - h0).days
    cur = plan.profile.currency
    pi = plan.assumptions.inflation_pct / 100.0
    goal_index = {g.id: i for i, g in enumerate(plan.goals)}
    goals = {g.id: g for g in plan.goals}
    class_index = {a.id: j for j, a in enumerate(plan.assumptions.asset_classes)}
    class_name = {a.id: a.name for a in plan.assumptions.asset_classes}
    you = [Requirement(alternatives=["YOU"], units=1)]
    tasks: list[Task] = []
    skipped = 0

    def gkey(gid: str) -> str:
        return "ef" if gid == "emergency_fund" else f"g{goal_index.get(gid, 0)}"

    def group(gid: str) -> str:
        if gid == "emergency_fund":
            return "Emergency fund"
        return _name(goals[gid].name) if gid in goals else "Goals"

    def prio(gid: str) -> int:
        return 9 if gid == "emergency_fund" else PRIORITY.get(goals[gid].priority, 5) if gid in goals else 5

    def label(gid: str) -> str:
        return "the emergency fund" if gid == "emergency_fund" else f'"{goals[gid].name}"' if gid in goals else gid

    def activity(tid: str, nm: str, desc: str, gid: str, t: int, minutes: int, deadline_day: int,
                 meta: dict) -> None:
        nonlocal skipped
        if t < 0 or t >= months:
            skipped += 1
            return
        m = tg.add_months(start, t)
        tasks.append(Task(id=tid, name=_name(nm), description=(desc + "\n\n" + DISCLAIMER)[:10000],
                          group=group(gid) if gid else "Reviews", type="activity", duration_minutes=minutes,
                          priority=prio(gid) if gid else 5, earliest_start=_at(m, 1, "09:00", tz),
                          deadline=_at(m, deadline_day, "21:00", tz), deadline_hard=False, requirements=you,
                          metadata={"finance": meta}))

    def milestone(tid: str, nm: str, desc: str, gid: str, t: int, meta: dict) -> None:
        nonlocal skipped
        if t < 0 or t >= months:
            skipped += 1
            return
        m = tg.add_months(start, t)
        tasks.append(Task(id=tid, name=_name(nm), description=(desc + "\n\n" + DISCLAIMER)[:10000],
                          group=group(gid), type="milestone", duration_minutes=0, priority=prio(gid),
                          earliest_start=_at(m, 1, "09:00", tz), metadata={"finance": meta}))

    # contributions: one task per line start (start or change), one per stop
    by_key: dict[tuple[str, str], list] = {}
    for line in result.contributions:
        by_key.setdefault((line.goal_id, line.asset_class_id), []).append(line)
    for (gid, a), lines in by_key.items():
        lines.sort(key=lambda ln: ln.start_month)
        ck = f"a{class_index.get(a, 0)}"
        prev_end = None
        for ln in lines:
            t0 = tg.month_index(start, ln.start_month)
            t1 = tg.month_index(start, ln.end_month)
            month = ln.start_month
            amount = format_money(ln.monthly_amount_real, cur)
            nominal = format_money(ln.monthly_amount_real * (1 + pi) ** (t0 / 12.0), cur)
            verb = "Change to" if prev_end is not None and prev_end + 1 == t0 else "Start"
            meta = {"goal_id": gid, "asset_class_id": a, "month": month, "monthly_amount_real": ln.monthly_amount_real}
            activity(f"C-{gkey(gid)}-{ck}-{month.replace('-', '')}",
                     f"{verb} {amount}/month into {class_name.get(a, a)} for {label(gid)}",
                     f"Monthly contribution of {amount} in today's money (about {nominal} in expected future money) "
                     f"from {ln.start_month} to {ln.end_month}.", gid, t0, 30, 5, meta)
            prev_end = t1
        # stops: month after a line ends when no line continues there
        starts = {tg.month_index(start, ln.start_month) for ln in lines}
        for ln in lines:
            t1 = tg.month_index(start, ln.end_month)
            if t1 + 1 in starts:
                continue
            m = tg.add_months(start, t1 + 1)
            meta = {"goal_id": gid, "asset_class_id": a, "month": m, "monthly_amount_real": 0.0}
            activity(f"S-{gkey(gid)}-{ck}-{m.replace('-', '')}",
                     f"Stop the monthly contribution into {class_name.get(a, a)} for {label(gid)}",
                     f"The plan stops this contribution from {m}.", gid, t1 + 1, 15, 5, meta)

    if include_rebalances:
        for r in result.rebalances:
            t = tg.month_index(start, r.month)
            sells = ", ".join(f"{class_name.get(a, a)} {format_money(v, cur)}" for a, v in r.sells.items())
            buys = ", ".join(f"{class_name.get(a, a)} {format_money(v, cur)}" for a, v in r.buys.items())
            meta = {"goal_id": r.goal_id, "asset_class_id": None, "month": r.month, "monthly_amount_real": 0.0}
            activity(f"R-{gkey(r.goal_id)}-{r.month.replace('-', '')}", f"Rebalance the investments for "
                     f"{label(r.goal_id)}", f"Sell: {sells or 'nothing'}. Buy: {buys or 'nothing'}.",
                     r.goal_id, t, 60, 10, meta)

    t = review_every_months
    while t < months:
        m = tg.add_months(start, t)
        meta = {"goal_id": None, "asset_class_id": None, "month": m, "monthly_amount_real": 0.0}
        activity(f"REV-{m.replace('-', '')}", "Review your financial plan",
                 "Compare actual savings with the plan and re-run it if something changed.", "", t, 60, 7, meta)
        t += review_every_months

    for g in result.goals:
        t = tg.month_index(start, g.target_month)
        meta = {"goal_id": g.goal_id, "asset_class_id": None, "month": g.target_month, "monthly_amount_real": 0.0}
        milestone(f"G-{gkey(g.goal_id)}", f'Goal due: "{g.name}"',
                  f"Target {format_money(g.target_real, cur)} in today's money.", g.goal_id, t, meta)
    ef_m = result.summary.emergency_fund_complete_month
    if ef_m is not None and result.summary.emergency_fund_target > 0:
        t = tg.month_index(start, ef_m)
        if t > 0:
            meta = {"goal_id": "emergency_fund", "asset_class_id": None, "month": ef_m, "monthly_amount_real": 0.0}
            milestone("EF-DONE", "Emergency fund complete",
                      f"Emergency fund of {format_money(result.summary.emergency_fund_target, cur)} complete.",
                      "emergency_fund", t, meta)

    desc = (f"Money calendar from the finance plan \"{plan.name}\" for {months} month(s) from {start}.\n\n"
            + DISCLAIMER)
    problem = Problem(
        name=_name(name), description=desc[:10000], domain="personal_finance", horizon_start=h0,
        horizon_days=horizon_days, currency=cur,
        terminology=Terminology(task="Action", tasks="Actions", resource="Person", resources="People", group="Goal",
                                milestone="Milestone", schedule="Money calendar", deadline="Due date"),
        tasks=tasks,
        resources=[Resource(id="YOU", name="You", kind="person", capacity=1, calendar=Calendar(
            weekly={d: [("09:00", "21:00")] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}))],
        metadata={"source": "finance", "finance_plan_id": plan.id, "finance_result_id": None})
    return problem, skipped
