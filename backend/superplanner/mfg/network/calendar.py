"""Working-day arithmetic of a node (M9-DESIGN 5.3: transit in source working days) and Monday weeks."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weeks(as_of: date, n: int) -> list[date]:
    w0 = monday(as_of)
    return [w0 + timedelta(days=7 * k) for k in range(n)]


class NodeCalendar:
    def __init__(self, workdays: Iterable[int] = (0, 1, 2, 3, 4), holidays: Iterable[date] = ()):
        self.workdays = frozenset(workdays) or frozenset({0, 1, 2, 3, 4})
        self.holidays = frozenset(holidays)

    def working(self, d: date) -> bool:
        return d.weekday() in self.workdays and d not in self.holidays

    def back(self, d: date, n: int) -> date:
        """`n` working days before `d` (n = 0 -> d)."""
        out = d
        k = 0
        while k < n:
            out -= timedelta(days=1)
            if self.working(out):
                k += 1
        return out

    def forward(self, d: date, n: int) -> date:
        out = d
        k = 0
        while k < n:
            out += timedelta(days=1)
            if self.working(out):
                k += 1
        return out

    def next_working(self, d: date) -> date:
        out = d
        for _ in range(400):
            if self.working(out):
                return out
            out += timedelta(days=1)
        return d
