"""Working-day calendar for MRP lead-time offsets (M2-DESIGN 8.5; frozen at milestone A1).

`WorkCalendar(workdays=plant.mrp_workdays, holidays=snapshot.holidays)`:

- `is_workday(d)`: the weekday is a working day and `d` is not a (whole-day) plant holiday/shutdown.
- `workday_add(d, n)`: `n = 0` -> `d` if working else the next working day; `n > 0` -> the n-th working day
  after `d`.
- `workday_sub(d, n)`: `n = 0` -> `d` if working else the previous working day; `n > 0` -> the n-th working day
  before `d`. An order with lead time n started on `workday_sub(due, n)` works on n working days and is available
  at the start of `due`.

Pure and deterministic (no clock reads). Dates outside `date.min..date.max` raise `OverflowError` like `date`
arithmetic does; a calendar without any working day in a long stretch raises `ValueError` instead of looping.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from .model import WEEKDAYS

_ONE = timedelta(days=1)
#: no working day within this many consecutive calendar days -> ValueError (a misconfigured calendar)
MAX_GAP_DAYS = 3660


class WorkCalendar:
    __slots__ = ("workdays", "holidays", "_wd")

    def __init__(self, workdays: Iterable[str] = WEEKDAYS[:6], holidays: Iterable[date] = ()):
        self.workdays: tuple[str, ...] = tuple(d for d in WEEKDAYS if d in set(workdays))
        if not self.workdays:
            raise ValueError("a work calendar needs at least one working weekday")
        self.holidays: frozenset[date] = frozenset(holidays)
        self._wd = frozenset(WEEKDAYS.index(d) for d in self.workdays)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"WorkCalendar({list(self.workdays)}, {len(self.holidays)} holidays)"

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self._wd and d not in self.holidays

    def _step(self, d: date, delta: timedelta) -> date:
        for _ in range(MAX_GAP_DAYS):
            d = d + delta
            if self.is_workday(d):
                return d
        raise ValueError(f"no working day within {MAX_GAP_DAYS} days of {d.isoformat()}")

    def workday_add(self, d: date, n: int) -> date:
        if n < 0:
            return self.workday_sub(d, -n)
        if n == 0:
            return d if self.is_workday(d) else self._step(d, _ONE)
        for _ in range(n):
            d = self._step(d, _ONE)
        return d

    def workday_sub(self, d: date, n: int) -> date:
        if n < 0:
            return self.workday_add(d, -n)
        if n == 0:
            return d if self.is_workday(d) else self._step(d, -_ONE)
        for _ in range(n):
            d = self._step(d, -_ONE)
        return d

    def workdays_between(self, a: date, b: date) -> int:
        """Working days in `[a, b)` (0 when `b <= a`)."""
        n = 0
        d = a
        while d < b:
            if self.is_workday(d):
                n += 1
            d += _ONE
        return n


__all__ = ["MAX_GAP_DAYS", "WorkCalendar"]
