"""A.4 time model and calendar expansion."""

from datetime import datetime, timedelta, timezone

from superplanner.engine.model import BlockedInterval, Calendar
from superplanner.engine.timeutil import expand_windows, fmt_duration, fmt_minute, from_minute, to_minute

IST = timezone(timedelta(hours=5, minutes=30))


def test_to_from_minute_and_flooring():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=IST)
    assert to_minute(hs + timedelta(minutes=90, seconds=59), hs) == 90
    assert to_minute(hs - timedelta(seconds=30), hs) == -1
    assert from_minute(90, hs).isoformat() == "2026-10-19T01:30:00+05:30"
    # a UTC datetime is converted through absolute time
    assert to_minute(datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc), hs) == 360


def test_offset_windows_land_on_right_minutes():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=IST)  # Monday
    cal = Calendar(weekly={"mon": [("06:00", "14:00")], "tue": [("06:00", "08:00")]})
    assert expand_windows(cal, hs, 3 * 1440) == [(360, 840), (1440 + 360, 1440 + 480)]


def test_horizon_start_mid_day():
    hs = datetime(2026, 10, 19, 10, 0, tzinfo=IST)  # Monday 10:00
    cal = Calendar(weekly={"mon": [("06:00", "14:00")], "tue": [("06:00", "14:00")]})
    # Monday window clipped to [0, 240); Tuesday 06:00 is minute 1200
    assert expand_windows(cal, hs, 2 * 1440) == [(0, 240), (1200, 1680)]


def test_night_shift_merges_across_midnight():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    cal = Calendar(weekly={"mon": [("22:00", "24:00")], "tue": [("00:00", "06:00")]})
    assert expand_windows(cal, hs, 3 * 1440) == [(22 * 60, 1440 + 360)]


def test_touching_windows_merge():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    cal = Calendar(weekly={"mon": [("06:00", "14:00"), ("14:00", "22:00")]})
    assert expand_windows(cal, hs, 1440) == [(360, 1320)]


def test_blocked_subtraction():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=IST)
    cal = Calendar(weekly={"mon": [("06:00", "22:00")]},
                   blocked=[BlockedInterval(start=hs + timedelta(hours=10), end=hs + timedelta(hours=12))])
    assert expand_windows(cal, hs, 1440) == [(360, 600), (720, 1320)]


def test_weekly_none_with_blocked():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    cal = Calendar(weekly=None, blocked=[BlockedInterval(start=hs + timedelta(hours=1), end=hs + timedelta(hours=2)),
                                         BlockedInterval(start=hs - timedelta(hours=5), end=hs + timedelta(minutes=10))])
    assert expand_windows(cal, hs, 1440) == [(10, 60), (120, 1440)]
    assert expand_windows(None, hs, 1440) == [(0, 1440)]


def test_missing_weekday_and_empty_list_are_closed():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    cal = Calendar(weekly={"mon": [], "wed": [("08:00", "09:00")]})
    assert expand_windows(cal, hs, 7 * 1440) == [(2 * 1440 + 480, 2 * 1440 + 540)]


def test_formatting():
    hs = datetime(2026, 10, 19, 0, 0, tzinfo=IST)
    assert fmt_minute(1440 + 600, hs) == "Tue 20 Oct 10:00"
    assert fmt_duration(135) == "2h 15m"
    assert fmt_duration(45) == "45m"
    assert fmt_duration(1440 + 120) == "1d 2h"
