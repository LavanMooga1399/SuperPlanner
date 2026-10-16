"""Contribution calendar CSV (FINANCE.md 16.2)."""

from __future__ import annotations

import csv
import io

from . import timegrid as tg
from .defaults import DISCLAIMER
from .model import FinancePlan, FinanceResult

HEADER = ["month", "action", "goal_id", "goal_name", "priority", "asset_class_id", "asset_class_name",
          "amount_today_money", "amount_expected_nominal"]
ACTION_ORDER = {"contribute": 0, "emergency_fund": 1, "rebalance_sell": 2, "rebalance_buy": 3, "goal_withdrawal": 4}
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_text(value: object) -> str:
    """Neutralise spreadsheet formula injection (same rule as the scheduling CSV) [R18]."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def contributions_csv(plan: FinancePlan, result: FinanceResult) -> str:
    start = result.start_month
    T = result.horizon_months
    pi = plan.assumptions.inflation_pct / 100.0
    goals = {g.id: g for g in plan.goals}
    gorder = {g.id: i for i, g in enumerate(plan.goals)}
    corder = {a.id: i for i, a in enumerate(plan.assumptions.asset_classes)}
    cname = {a.id: a.name for a in plan.assumptions.asset_classes}
    rows: list[tuple] = []

    def add(t: int, action: str, gid: str, cls: str | None, amount: float) -> None:
        if amount < 1.0:
            return
        g = goals.get(gid)
        name = g.name if g else ("Emergency fund" if gid == "emergency_fund" else gid)
        prio = g.priority if g else ""
        nominal = amount * (1.0 + pi) ** (t / 12.0)
        key = (t, ACTION_ORDER[action], gorder.get(gid, -1 if gid == "emergency_fund" else 999),
               corder.get(cls, 999) if cls else -1)
        rows.append((key, [tg.add_months(start, t), action, csv_text(gid), csv_text(name), prio, csv_text(cls or ""),
                           csv_text(cname.get(cls, "") if cls else ""), f"{amount:.2f}", f"{nominal:.2f}"]))

    for line in result.contributions:
        t0 = tg.month_index(start, line.start_month)
        t1 = tg.month_index(start, line.end_month)
        action = "emergency_fund" if line.goal_id == "emergency_fund" else "contribute"
        for t in range(t0, t1 + 1):
            add(t, action, line.goal_id, line.asset_class_id, line.monthly_amount_real)
    for r in result.rebalances:
        t = tg.month_index(start, r.month)
        for a, v in r.sells.items():
            add(t, "rebalance_sell", r.goal_id, a, v)
        for a, v in r.buys.items():
            add(t, "rebalance_buy", r.goal_id, a, v)
    for g in result.goals:
        t = tg.month_index(start, g.target_month)
        if 0 <= t < T:
            add(t, "goal_withdrawal", g.goal_id, None, min(g.projected_central_real, g.target_real))
    rows.sort(key=lambda r: r[0])
    buf = io.StringIO()
    buf.write("# " + DISCLAIMER + "\r\n")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADER)
    for _, row in rows:
        w.writerow(row)
    return buf.getvalue()
