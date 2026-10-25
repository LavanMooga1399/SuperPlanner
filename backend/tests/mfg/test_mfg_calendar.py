"""Shift windows (M1-DESIGN 4.6): T-C1..T-C8, template validation, week expansion, capacity, operator windows."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from mfgpure_helpers import MON_SAT, Builder, by_code, ds_of, shift
from superplanner.mfg import expand_template_week, group_capacity, line_windows, operator_windows, validate_template
from superplanner.mfg.bundle import parse_break
from superplanner.mfg.calendar import week_minutes_per_day
from superplanner.mfg.model import ShiftTemplateInput

TZ = timezone(timedelta(hours=5, minutes=30))
MON = date(2026, 11, 2)
TUE, WED, SUN = MON + timedelta(days=1), MON + timedelta(days=2), MON + timedelta(days=6)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


def plant(**line_kw) -> Builder:
    b = Builder()
    b.plant("P", utc_offset="+05:30")
    b.group("G", "Stage")
    b.line("L1", "G", "Line", **line_kw)
    return b


def wins(b: Builder, d0: date = MON, d1: date | None = None, line_code: str = "L1"):
    ds = ds_of(b)
    return ds, line_windows(ds, by_code(ds, line_code).id, d0, d1 or d0 + timedelta(days=7))


def simple(ws):
    return [(w.start, w.end, w.kind) for w in ws]


def minutes(ws, kind=None):
    return sum((w.end - w.start).total_seconds() / 60 for w in ws if kind is None or w.kind == kind)


REG = [shift("Day", MON_SAT, "09:00", "18:00", "Lunch=13:00-13:45")]
EVE = [shift("Evening", MON_SAT, "18:00", "22:00")]
THREE = [shift("A", MON_SAT, "06:00", "14:00"), shift("B", MON_SAT, "14:00", "22:00"),
         shift("C", MON_SAT, "22:00", "06:00")]


def test_tc1_regular_shift_with_lunch():
    b = plant()
    b.template("REG", "Regular", REG)
    b.assign("REG", "group", "G")
    _, ws = wins(b)
    assert simple(ws)[:2] == [(at(MON, 9), at(MON, 13), "base"), (at(MON, 13, 45), at(MON, 18), "base")]
    assert len(ws) == 12 and minutes(ws) == 6 * 495
    assert not any(w.start.date() == SUN for w in ws)
    assert {w.shift_label for w in ws} == {"REG/Day"} and ws[0].start.utcoffset() == timedelta(hours=5, minutes=30)


def test_tc2_optional_touches_base_but_is_not_merged():
    b = plant()
    b.template("REG", "Regular", REG)
    b.template("EVE", "Evening", EVE)
    b.assign("REG", "group", "G")
    b.assign("EVE", "group", "G", kind="optional", cost_per_hour=300.0)
    _, ws = wins(b, MON, TUE)
    assert simple(ws) == [(at(MON, 9), at(MON, 13), "base"), (at(MON, 13, 45), at(MON, 18), "base"),
                          (at(MON, 18), at(MON, 22), "optional")]
    assert ws[2].cost_per_hour == 300.0 and ws[2].shift_label == "EVE/Evening" and ws[0].cost_per_hour is None


def test_tc3_three_shifts_are_one_window_mon_to_sun():
    b = plant()
    b.template("3S", "Three", THREE)
    b.assign("3S", "group", "G")
    _, ws = wins(b)
    assert simple(ws) == [(at(MON, 6), at(SUN, 6), "base")]
    assert ws[0].shift_label == "3S/A+B+C"


def test_tc4_per_kind_source_line_optional_keeps_group_base():
    b = plant()
    b.line("L2", "G", "Other line")
    b.template("REG", "Regular", REG)
    b.template("EVE", "Evening", EVE)
    b.assign("REG", "group", "G")
    b.assign("EVE", "line", "L1", kind="optional", cost_per_hour=100.0)
    _, ws = wins(b, MON, TUE)
    assert [w.kind for w in ws] == ["base", "base", "optional"]
    _, ws2 = wins(b, MON, TUE, "L2")
    assert [w.kind for w in ws2] == ["base", "base"]
    b.assign("EVE", "line", "L1", effective_from=date(2026, 1, 1) + timedelta(days=1))   # line base overrides
    _, ws3 = wins(b, MON, TUE)
    assert simple(ws3) == [(at(MON, 18), at(MON, 22), "base")]


def test_tc5_holiday_removes_the_day_and_the_night_tail():
    b = plant()
    b.template("3S", "Three", THREE)
    b.assign("3S", "group", "G")
    b.exception("plant", None, "holiday", TUE, TUE, "Holiday")         # date-only end is inclusive
    _, ws = wins(b)
    assert simple(ws) == [(at(MON, 6), at(TUE, 0), "base"), (at(WED, 0), at(SUN, 6), "base")]


def test_tc6_optional_overlapping_base_is_cut():
    b = plant()
    b.template("B", "Base", [shift("Day", MON_SAT, "09:00", "18:00")])
    b.template("O", "Opt", [shift("Late", MON_SAT, "16:00", "20:00")])
    b.assign("B", "group", "G")
    b.assign("O", "group", "G", kind="optional", cost_per_hour=10.0)
    _, ws = wins(b, MON, TUE)
    assert simple(ws) == [(at(MON, 9), at(MON, 18), "base"), (at(MON, 18), at(MON, 20), "optional")]


def test_tc7_overlapping_optionals_go_to_the_cheaper():
    b = plant()
    b.template("O1", "Opt 1", [shift("E", MON_SAT, "18:00", "22:00")])
    b.template("O2", "Opt 2", [shift("N", MON_SAT, "20:00", "23:00")])
    b.template("B", "Base", [shift("Day", MON_SAT, "09:00", "18:00")])
    b.assign("B", "group", "G")
    b.assign("O1", "group", "G", kind="optional", cost_per_hour=400.0)
    b.assign("O2", "group", "G", kind="optional", cost_per_hour=300.0)
    _, ws = wins(b, MON, TUE)
    opt = [(w.start, w.end, w.cost_per_hour, w.shift_label) for w in ws if w.kind == "optional"]
    assert opt == [(at(MON, 18), at(MON, 20), 400.0, "O1/E"), (at(MON, 20), at(MON, 23), 300.0, "O2/N")]


def test_tc8_range_from_tuesday_includes_monday_night_tail():
    b = plant()
    b.template("N", "Night", [shift("C", MON_SAT, "22:00", "06:00")])
    b.assign("N", "group", "G")
    _, ws = wins(b, TUE, WED)
    assert simple(ws) == [(at(TUE, 0), at(TUE, 6), "base"), (at(TUE, 22), at(WED, 0), "base")]


def test_exceptions_by_scope_and_inactive_targets():
    b = plant()
    b.line("L2", "G", "Other")
    b.template("B", "Base", [shift("Day", MON_SAT, "09:00", "18:00")])
    b.assign("B", "group", "G")
    b.exception("line", "L2", "maintenance", at(MON, 10), at(MON, 11), "PM")
    b.exception("group", "G", "shutdown", at(MON, 17), at(MON, 18), "Stop")
    _, ws = wins(b, MON, TUE)
    assert simple(ws) == [(at(MON, 9), at(MON, 17), "base")]
    _, ws = wins(b, MON, TUE, "L2")
    assert simple(ws) == [(at(MON, 9), at(MON, 10), "base"), (at(MON, 11), at(MON, 17), "base")]
    b.b["groups"][0]["active"] = False          # group assignments of an inactive group have no effect
    _, ws = wins(b, MON, TUE)
    assert ws == []


def test_effective_dates_of_assignments():
    b = plant()
    b.template("B", "Base", [shift("Day", MON_SAT, "09:00", "18:00")])
    b.assign("B", "group", "G", effective_from=TUE)
    b.b["shift_assignments"][-1]["effective_to"] = WED
    _, ws = wins(b)
    assert simple(ws) == [(at(TUE, 9), at(TUE, 18), "base")]


def test_24h_template_is_continuous():
    b = plant()
    b.template("H", "24x7", [shift("Day", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "00:00", "00:00")])
    b.assign("H", "group", "G")
    _, ws = wins(b)
    assert simple(ws) == [(at(MON, 0), at(MON + timedelta(days=7), 0), "base")]


# ---------------------------------------------------------------- templates

def tpl(*shifts) -> ShiftTemplateInput:
    shifts = [{**sh, "breaks": [parse_break(x) for x in sh["breaks"]]} for sh in shifts]
    return ShiftTemplateInput.model_validate({"code": "T", "name": "T", "shifts": shifts})


def test_validate_template_ok_cases():
    assert validate_template(tpl(*THREE)) == []
    assert validate_template(tpl(shift("D", ["mon", "tue"], "06:00", "06:00"))) == []           # 24 h, touching
    assert validate_template(tpl(shift("C", MON_SAT, "22:00", "06:00", "Meal=02:00-02:30"))) == []


def test_validate_template_sunday_night_wraps_onto_monday():
    errs = validate_template(tpl(shift("N", ["sun"], "22:00", "06:00"), shift("M", ["mon"], "05:00", "13:00")))
    assert [e["type"] for e in errs] == ["shift_overlap"] and errs[0]["loc"] == ["body", "shifts", 1]


def test_validate_template_overlaps_and_breaks():
    assert [e["type"] for e in validate_template(tpl(shift("A", ["mon"], "06:00", "14:00"),
                                                     shift("B", ["mon"], "13:00", "22:00")))] == ["shift_overlap"]
    errs = validate_template(tpl(shift("A", ["mon"], "06:00", "14:00", "x=15:00-15:30")))
    assert [(e["type"], e["loc"]) for e in errs] == [("break_outside_shift", ["body", "shifts", 0, "breaks", 0])]
    errs = validate_template(tpl(shift("A", ["mon"], "06:00", "14:00", "x=10:00-10:00")))
    assert [e["type"] for e in errs] == ["break_empty"]
    errs = validate_template(tpl(shift("A", ["mon"], "06:00", "14:00", "x=10:00-11:00", "y=10:30-11:30")))
    assert [e["type"] for e in errs] == ["break_overlap"]
    errs = validate_template(tpl(shift("D", ["mon", "tue"], "06:00", "07:00"), shift("E", ["mon"], "06:00", "06:00")))
    assert errs and errs[0]["type"] == "shift_overlap"


def test_expand_template_week_example_9_4():
    t = tpl(shift("A", MON_SAT, "06:00", "14:00", "Meal=10:00-10:30"),
            shift("B", MON_SAT, "14:00", "22:00", "Meal=18:00-18:30"),
            shift("C", MON_SAT, "22:00", "06:00", "Meal=02:00-02:30"))
    ww = expand_template_week(t)
    assert [(w.shift, w.day, w.start_minute, w.end_minute) for w in ww[:2]] == \
        [("A", "mon", 360, 600), ("A", "mon", 630, 840)]
    sat_c = [(w.start_minute, w.end_minute) for w in ww if w.shift == "C" and w.day == "sat"]
    assert sat_c == [(8520, 8760), (8790, 9000)]
    per_day = week_minutes_per_day(t)
    assert per_day["mon"] == 1350 and per_day["sun"] == 0 and sum(per_day.values()) == 8100


def test_group_capacity_uses_parallel_capacity():
    b = plant(parallel_capacity=4)
    b.line("L2", "G", "Second")
    b.line("L3", "G", "Inactive", active=False)
    b.template("B", "Base", [shift("Day", ["mon"], "09:00", "17:00")])
    b.template("O", "Opt", [shift("Eve", ["mon"], "17:00", "19:00")])
    b.assign("B", "group", "G")
    b.assign("O", "line", "L2", kind="optional", cost_per_hour=1.0)
    ds = ds_of(b)
    cap = group_capacity(ds, by_code(ds, "G").id, MON, TUE)
    assert cap["base_minutes"] == 480 * 4 + 480 and cap["optional_minutes"] == 120
    assert set(cap["lines"]) == {by_code(ds, "L1").id, by_code(ds, "L2").id}


def test_operator_windows_are_spans_with_previous_night_tail():
    b = plant()
    b.template("3S", "Three", [shift("A", MON_SAT, "06:00", "14:00", "Meal=10:00-10:30"),
                               shift("C", MON_SAT, "22:00", "06:00", "Meal=02:00-02:30")])
    b.skill("S", "S")
    b.operator("O1", "Night", ["S"], "3S", ["C"])
    b.operator("O2", "Both", ["S"], "3S")
    b.exception("plant", None, "holiday", TUE, TUE, "Holiday")   # never applied to operators
    ds = ds_of(b)
    ws = operator_windows(ds, by_code(ds, "O1").id, TUE, WED)
    assert simple(ws) == [(at(TUE, 0), at(TUE, 6), "base"), (at(TUE, 22), at(WED, 0), "base")]
    ws = operator_windows(ds, by_code(ds, "O2").id, TUE, WED)
    assert simple(ws) == [(at(TUE, 0), at(TUE, 14), "base"), (at(TUE, 22), at(WED, 0), "base")]
    assert ws[0].shift_label == "3S/C+A" and ws[0].assignment_id is None
