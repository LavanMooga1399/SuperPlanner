"""Data-health check (M1-DESIGN 7; PLAN-M1 A3-1): each of the 43 codes (40 of 7.2 + 3 of the M1 fix round) has a
fixture that raises it and a minimal change that clears it; ordering, truncation, counts; links match the frontend
routes of 11.1; T-S1..T-S6 (R1)."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest

from mfgpure_helpers import AS_OF, MON_SAT, Builder, base_plant, ds_of, line, op, shift
from superplanner.mfg import run_health_check
from superplanner.mfg.limits import MAX_HEALTH_ISSUES
from superplanner.mfg.messages import CODE_INFO, HEALTH_CODES

# frontend routes of M 11.1 (path) + the query parameters 11.3 uses
ROUTES = [r"/mfg/items/[a-z]{3}_[0-9a-f]{32}", r"/mfg/items/[a-z]{3}_[0-9a-f]{32}/bom",
          r"/mfg/items/[a-z]{3}_[0-9a-f]{32}/bom/[a-z]{3}_[0-9a-f]{32}/edit",
          r"/mfg/items/[a-z]{3}_[0-9a-f]{32}/where-used", r"/mfg/items/[a-z]{3}_[0-9a-f]{32}/routing",
          r"/mfg/plant/groups", r"/mfg/plant/shifts", r"/mfg/plant/calendar", r"/mfg/plant/settings",
          r"/mfg/resources/skills", r"/mfg/resources/operators", r"/mfg/resources/tooling", r"/mfg/health"]
QUERY = {"bom", "line", "on", "serial", "qty", "routing", "op", "group", "template", "assignment", "exception",
         "skill", "operator", "tool"}


def assert_link(link: str | None) -> None:
    assert link is not None
    path, _, query = link.partition("?")
    assert any(re.fullmatch(p, path) for p in ROUTES), link
    for part in filter(None, query.split("&")):
        k, _, v = part.partition("=")
        assert k in QUERY and v, link


def rows(b: Builder, sheet: str, **match: Any) -> list[dict[str, Any]]:
    out = [r for r in b.b[sheet] if all(r.get(k) == v for k, v in match.items())]
    assert out, (sheet, match)
    return out


def one(b: Builder, sheet: str, **match: Any) -> dict[str, Any]:
    return rows(b, sheet, **match)[0]


def report(b: Builder):
    r = run_health_check(ds_of(b), AS_OF, 90)
    for i in r.issues:
        assert_link(i.link)
    return r


def test_base_scenario_is_clean():
    r = report(base_plant())
    assert r.ok and r.issues == [] and r.by_code == {}


# ---------------------------------------------------------------- one break + one fix per code

def _chain(b: Builder, n: int) -> None:
    prev = "P"
    one(b, "bom_lines", parent_part_number="P")["child_part_number"] = "M1"
    for i in range(1, n + 1):
        b.item(f"M{i}", "make", f"M{i}")
        b.bom(f"M{i}", [line(10, f"M{i + 1}" if i < n else "C", 1)])
        prev = f"M{i}"
    del prev


def _too_deep(b):
    _chain(b, 21)


def _not_deep(b):
    b.b["items"] = [r for r in b.b["items"] if r["part_number"] not in ("M20", "M21")]
    b.b["boms"] = [r for r in b.b["boms"] if r["parent_part_number"] not in ("M20", "M21")]
    b.b["bom_lines"] = [r for r in b.b["bom_lines"] if r["parent_part_number"] not in ("M20", "M21")]
    one(b, "bom_lines", parent_part_number="M19")["child_part_number"] = "C"


def _cycle(b):
    b.item("Q", "make", "Q")
    b.bom("Q", [line(10, "P", 1)], status="draft", effective_from=None)
    b.b["bom_lines"].append({**one(b, "bom_lines", parent_part_number="P"), "find_number": "20",
                             "child_part_number": "Q"})


def _uncycle(b):
    b.b["bom_lines"] = [r for r in b.b["bom_lines"] if r["child_part_number"] != "Q"]


def _set(sheet: str, field: str, value: Any, **match: Any) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        for r in rows(b, sheet, **match):
            r[field] = value
    return f


def _both(*fns: Callable[[Builder], None]) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        for fn in fns:
            fn(b)
    return f


def _add_routing(code: str, priority: int, ops: list, **kw: Any) -> Callable[[Builder], None]:
    return lambda b: b.routing("P", ops, code=code, priority=priority, **kw)


def _no_assignment(b):
    b.b["shift_assignments"] = []


def _readd_assignment(b):
    b.assign("REG", "group", "G")


def _alt_lines(p1: int, p2: int) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        b.item("C2", "buy", "Alt", lead_time_days=1)
        one(b, "bom_lines", parent_part_number="P").update(alt_group="10", alt_priority=p1)
        b.b["bom_lines"].append({**one(b, "bom_lines", parent_part_number="P"), "child_part_number": "C2",
                                 "alt_priority": p2})
    return f


def _alt_prios(p1: int, p2: int) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        one(b, "bom_lines", child_part_number="C")["alt_priority"] = p1
        one(b, "bom_lines", child_part_number="C2")["alt_priority"] = p2
    return f


def _phantom(b):
    b.item("K", "phantom", "Kit")
    b.b["bom_lines"].append({**one(b, "bom_lines", parent_part_number="P"), "find_number": "20",
                             "child_part_number": "K", "qty_per": 1})


def _tool(qty: int) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        if not any(r["code"] == "T" for r in b.b["tool_pools"]):
            b.tool("T", "Tool", qty)
            one(b, "operations", part_number="P")["tools"] = ["T:1"]
        one(b, "tool_pools", code="T")["quantity"] = qty
    return f


def _inactive_line_assignment(b):
    b.line("L2", "G", "Line 2", active=False)
    b.assign("REG", "line", "L2")


def _eve(cost: float | None, start: str = "18:00", end: str = "22:00") -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        b.template("EVE", "Evening", [shift("Evening", MON_SAT, start, end)])
        b.assign("EVE", "group", "G", kind="optional", cost_per_hour=cost)
        b.template("EXT", "Extended", [shift("Extended", MON_SAT, "09:00", "22:00")])
        one(b, "operators", code="O1")["shift_template_code"] = "EXT"
    return f


def _line_shutdown(b):
    b.line("L2", "G", "Line 2")
    b.exception("line", "L2", "maintenance", AS_OF - timedelta(days=1), AS_OF + timedelta(days=100), "Rebuild")


def _no_bom(b):
    b.b["boms"], b.b["bom_lines"] = [], []
    b.item("X", "buy", "kept used", lead_time_days=1)


def _gap(sheet_head: str, pn_field: str) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        head = one(b, sheet_head, **{pn_field: "P"})
        head["effective_to"] = date(2026, 12, 1)
        if sheet_head == "boms":
            b.bom("P", [line(10, "C", 2)], version=2, effective_from=date(2026, 12, 15))
        else:
            b.routing("P", [op(10, "Work", "G", run_minutes=1, skill_code="S")], version=2,
                      effective_from=date(2026, 12, 15))
    return f


def _buy_doc(kind: str) -> Callable[[Builder], None]:
    def f(b: Builder) -> None:
        if kind == "bom":
            b.item("Z", "buy", "Z", lead_time_days=1)
            b.bom("C", [line(10, "Z", 1)], status="draft", effective_from=None)
            b.b["bom_lines"].append({**one(b, "bom_lines", parent_part_number="P"), "find_number": "30",
                                     "child_part_number": "Z"})
        else:
            b.routing("C", [op(10, "x", "G", run_minutes=1)], status="draft", effective_from=None)
    return f


def _orphan(b):
    b.item("X", "buy", "Unused", lead_time_days=1)


def _use_x(b):
    b.b["bom_lines"].append({**one(b, "bom_lines", parent_part_number="P"), "find_number": "20",
                             "child_part_number": "X"})


def _dup(b):
    b.b["bom_lines"].append({**one(b, "bom_lines", parent_part_number="P"), "find_number": "20"})


def _undup(b):
    b.b["bom_lines"] = [r for r in b.b["bom_lines"] if r["find_number"] != "20"]


def _draft_only(b):
    b.item("D", "make", "Draft item")
    b.bom("D", [line(10, "C", 1)], status="draft", effective_from=None)


CASES: list[tuple[str, Callable[[Builder], None], Callable[[Builder], None]]] = [
    ("MFG_BOM_CYCLE", _cycle, _uncycle),
    ("MFG_BOM_TOO_DEEP", _too_deep, _not_deep),
    ("MFG_MAKE_NO_ROUTING", _set("routings", "status", "draft", part_number="P"),
     _set("routings", "status", "released", part_number="P")),
    ("MFG_ROUTING_NO_OPERATIONS", _add_routing("ALT", 2, []),
     lambda b: b.b["operations"].append({**one(b, "operations", part_number="P"), "code": "ALT"})),
    ("MFG_GROUP_NO_LINE", _set("lines", "active", False, code="L1"), _set("lines", "active", True, code="L1")),
    ("MFG_NO_ELIGIBLE_LINE", _set("lines", "eligible_families", ["OTHER"], code="L1"),
     _set("lines", "eligible_families", ["OTHER", "FAM"], code="L1")),
    ("MFG_GROUP_NO_SHIFT", _no_assignment, _readd_assignment),
    ("MFG_GROUP_OPTIONAL_ONLY", _both(_set("shift_assignments", "kind", "optional"),
                                      _set("shift_assignments", "cost_per_hour", 10.0)),
     _both(_set("shift_assignments", "kind", "base"), _set("shift_assignments", "cost_per_hour", None))),
    ("MFG_UNINTERRUPTIBLE_TOO_LONG", _both(_set("operations", "interruptible", False),
                                           _set("operations", "run_minutes", 300)),
     _set("operations", "run_minutes", 200)),
    ("MFG_UNINTERRUPTIBLE_LOT_TOO_LONG", _both(_set("operations", "interruptible", False),
                                               _set("operations", "run_minutes", 100),
                                               _set("items", "min_order_qty", 5, part_number="P")),
     _set("items", "min_order_qty", 2, part_number="P")),
    ("MFG_BUY_NO_LEAD_TIME", _set("items", "lead_time_days", None, part_number="C"),
     _set("items", "lead_time_days", 0, part_number="C")),
    ("MFG_UOM_MISMATCH", _set("bom_lines", "uom", "M"), _set("bom_lines", "uom", "EA")),
    ("MFG_FRACTIONAL_SERIALIZED", _both(_set("items", "serialized", True, part_number="C"),
                                        _set("bom_lines", "qty_per", 2.5)), _set("bom_lines", "qty_per", 3)),
    ("MFG_BOM_EFFECTIVITY_OVERLAP", lambda b: b.bom("P", [line(10, "C", 2)], version=2,
                                                    effective_from=date(2026, 6, 1)),
     _set("boms", "effective_to", date(2026, 6, 1), version=1)),
    ("MFG_ROUTING_EFFECTIVITY_OVERLAP", _add_routing("STD", 1, [op(10, "Work", "G", run_minutes=1, skill_code="S")],
                                                     version=2),
     _set("routings", "priority", 2, version=2)),
    ("MFG_ALT_NO_PRIMARY", _alt_lines(2, 3), _alt_prios(1, 3)),
    ("MFG_ALT_DUPLICATE_PRIORITY", _alt_lines(1, 1), _alt_prios(1, 2)),
    ("MFG_INACTIVE_COMPONENT", _set("items", "active", False, part_number="C"),
     _set("items", "active", True, part_number="C")),
    ("MFG_PHANTOM_NO_BOM", _phantom, lambda b: b.bom("K", [line(10, "C", 1)])),
    ("MFG_SKILL_NO_OPERATOR", _set("operators", "active", False), _set("operators", "active", True)),
    ("MFG_TOOL_SHORT", _tool(0), _tool(1)),
    ("MFG_SERIAL_NOT_ALLOWED", _both(_set("boms", "serial_from", 1, parent_part_number="P"),
                                     _set("boms", "serial_to", 99, parent_part_number="P")),
     _set("items", "serialized", True, part_number="P")),
    ("MFG_ASSIGNMENT_INACTIVE_TARGET", _inactive_line_assignment, _set("lines", "active", True, code="L2")),
    ("MFG_OPERATION_SEQ_REF", _set("bom_lines", "operation_seq", 99), _set("bom_lines", "operation_seq", 10)),
    ("MFG_SKILL_NOT_ON_SHIFT", _both(_eve(300.0), _set("operators", "shift_template_code", "REG")),
     _set("operators", "shift_template_code", "EXT")),
    ("MFG_LINE_NO_SHIFT", _line_shutdown, lambda b: b.b.__setitem__("calendar_exceptions", [])),
    ("MFG_OPTIONAL_NO_COST", _eve(None), _set("shift_assignments", "cost_per_hour", 50.0, kind="optional")),
    ("MFG_OPTIONAL_OVERLAPS_BASE", _eve(50.0, "10:00", "12:00"),
     _both(_set("shifts", "start", "18:00", template_code="EVE"), _set("shifts", "end", "20:00",
                                                                        template_code="EVE"))),
    ("MFG_MAKE_NO_BOM", _no_bom, lambda b: b.bom("P", [line(10, "C", 2), line(20, "X", 1)])),
    ("MFG_BOM_EFFECTIVITY_GAP", _gap("boms", "parent_part_number"),
     _set("boms", "effective_from", date(2026, 12, 1), version=2)),
    ("MFG_ROUTING_EFFECTIVITY_GAP", _gap("routings", "part_number"),
     _set("routings", "effective_from", date(2026, 12, 1), version=2)),
    ("MFG_BUY_WITH_BOM", _buy_doc("bom"), _set("boms", "status", "obsolete", parent_part_number="C")),
    ("MFG_BUY_WITH_ROUTING", _buy_doc("routing"), _set("routings", "status", "obsolete", part_number="C")),
    ("MFG_ALT_SINGLE", _set("bom_lines", "alt_group", "10"), _set("bom_lines", "alt_group", None)),
    ("MFG_REFDES_COUNT", _set("bom_lines", "ref_designators", "R1-R3"),
     _set("bom_lines", "ref_designators", "R1-R2")),
    ("MFG_ZERO_TIME_OPERATION", _both(_set("operations", "setup_minutes", 0), _set("operations", "run_minutes", 0)),
     _set("operations", "run_minutes", 1)),
    ("MFG_LOW_YIELD", _set("operations", "yield_pct", 40), _set("operations", "yield_pct", 60)),
    ("MFG_ORPHAN_ITEM", _orphan, _use_x),
    ("MFG_DUPLICATE_COMPONENT", _dup, _undup),
    ("MFG_LONG_LEAD_TIME", _set("items", "lead_time_days", 200, part_number="C"),
     _set("items", "lead_time_days", 180, part_number="C")),
    ("MFG_DRAFT_ONLY", _draft_only, _set("boms", "status", "released", parent_part_number="D")),
]


# codes a valid bundle cannot express (bundle_to_dataset refuses unknown shift names): tested on the dataset below
DATASET_ONLY = ("MFG_ASSIGNMENT_UNKNOWN_SHIFT", "MFG_OPERATOR_UNKNOWN_SHIFT")


def test_cases_cover_all_43_codes():
    assert [c for c, _, _ in CASES] == [c for c in HEALTH_CODES if c not in DATASET_ONLY] and len(HEALTH_CODES) == 43


@pytest.mark.parametrize("code", DATASET_ONLY)
def test_unknown_shift_names_raised_and_cleared(code):
    """Review F2: an assignment / operator naming a shift its template no longer has (the template was edited
    around the service check, e.g. by older data) is an error; the time silently never exists otherwise."""
    ds = ds_of(base_plant())
    a = next(iter(ds.shift_assignments.values()))
    o = next(iter(ds.operators.values()))
    target = a if code == "MFG_ASSIGNMENT_UNKNOWN_SHIFT" else o
    target.shift_names = ["Day", "Night"]
    r = run_health_check(ds, AS_OF, 90)
    hits = [i for i in r.issues if i.code == code]
    assert len(hits) == 1 and not r.ok and "Night" in hits[0].message and "Day," not in hits[0].message
    info = CODE_INFO[code]
    assert hits[0].severity == "error" and hits[0].entity.type == info.entity == ("shift_assignment" if target is a
                                                                                   else "operator")
    assert hits[0].field == "shift_names" and [x.type for x in hits[0].related] == ["shift_template"]
    assert_link(hits[0].link)
    target.shift_names = ["Day"]
    assert code not in run_health_check(ds, AS_OF, 90).by_code


@pytest.mark.parametrize("code,brk,fix", CASES, ids=[c for c, _, _ in CASES])
def test_code_raised_and_cleared(code, brk, fix):
    b = base_plant()
    brk(b)
    r = report(b)
    hits = [i for i in r.issues if i.code == code]
    assert hits, (code, r.by_code)
    info = CODE_INFO[code]
    assert all(i.severity == info.severity and i.entity.type == info.entity and i.message and i.fix for i in hits)
    assert r.ok == (r.counts.error == 0)
    if info.severity == "error":
        assert not r.ok
    fix(b)
    r2 = report(b)
    assert code not in r2.by_code, [i.message for i in r2.issues if i.code == code]


# ---------------------------------------------------------------- specifics

def test_make_no_routing_message_and_link_point_to_the_draft():
    b = base_plant()
    _set("routings", "status", "draft", part_number="P")(b)
    r = report(b)
    i = next(i for i in r.issues if i.code == "MFG_MAKE_NO_ROUTING")
    assert "it has a draft routing STD v1" in i.message and "2 Nov 2026" in i.message
    assert i.link.endswith(f"/routing?routing={i.related[0].id}") and i.related[0].label == "STD v1 (draft)"


def test_cycle_message_lists_the_path():
    b = base_plant()
    _cycle(b)
    i = next(i for i in report(b).issues if i.code == "MFG_BOM_CYCLE")
    assert "P -> Q -> P" in i.message and i.entity.label == "P"


def test_bom_line_links_depend_on_status():
    b = base_plant()
    _set("bom_lines", "ref_designators", "R1-R3")(b)
    i = next(i for i in report(b).issues if i.code == "MFG_REFDES_COUNT")
    assert re.fullmatch(r"/mfg/items/itm_\w+/bom\?bom=bom_\w+&line=bml_\w+", i.link)
    _set("boms", "status", "draft")(b)
    b.bom("P", [line(10, "C", 2)], version=2)          # keep a released BOM so P is still fine
    ds = ds_of(b)
    r = run_health_check(ds, AS_OF, 90)
    draft_issue = next(i for i in r.issues if i.code == "MFG_REFDES_COUNT")
    assert re.fullmatch(r"/mfg/items/itm_\w+/bom/bom_\w+/edit\?line=bml_\w+", draft_issue.link)


def test_routing_expiring_inside_the_horizon_is_caught():
    b = base_plant()
    one(b, "routings", part_number="P")["effective_to"] = AS_OF + timedelta(days=21)
    i = next(i for i in report(b).issues if i.code == "MFG_MAKE_NO_ROUTING")
    assert "23 Nov 2026" in i.message


def test_ordering_truncation_and_complete_counts():
    b = base_plant()
    for k in range(1100):
        b.item(f"X{k:04d}", "buy", "no lead time")       # error + orphan warning each
    r = report(b)
    assert r.truncated and len(r.issues) == MAX_HEALTH_ISSUES
    assert r.counts.error == 1100 and r.counts.warning == 1100 and r.by_code == {"MFG_BUY_NO_LEAD_TIME": 1100,
                                                                                 "MFG_ORPHAN_ITEM": 1100}
    assert all(i.code == "MFG_BUY_NO_LEAD_TIME" for i in r.issues)
    labels = [i.entity.label for i in r.issues]
    assert labels == sorted(labels)
    b2 = base_plant()
    _orphan(b2)
    _set("items", "lead_time_days", 200, part_number="C")(b2)
    _set("bom_lines", "uom", "M")(b2)
    r2 = report(b2)
    assert [i.severity for i in r2.issues] == ["error", "warning", "info"] and not r2.truncated
    assert list(r2.by_code) == ["MFG_UOM_MISMATCH", "MFG_ORPHAN_ITEM", "MFG_LONG_LEAD_TIME"]


def test_report_fields():
    ds = ds_of(base_plant())
    r = run_health_check(ds, AS_OF, 30)
    assert (r.as_of, r.horizon_days, r.data_version) == (AS_OF, 30, 0) and len(r.fingerprint) == 64


def test_inactive_items_are_skipped_as_subjects():
    b = base_plant()
    b.item("X", "buy", "Inactive, no lead time", active=False)
    assert report(b).by_code == {}


# ---------------------------------------------------------------- skill coverage vectors T-S1..T-S6 (review R1)

def _coverage(op_templates: list[tuple[str, list[dict]]], line_setup: Callable[[Builder], None]) -> Any:
    b = base_plant()
    b.b["operators"] = []
    for i, (code, shifts) in enumerate(op_templates, 1):
        if not any(r["code"] == code for r in b.b["shift_templates"]):
            b.template(code, code, shifts)
        b.operator(f"OP{i}", f"Operator {i}", ["S"], code)
    line_setup(b)
    return report(b)


REG_OP = ("REGOP", [shift("Day", MON_SAT, "09:00", "18:00", "Lunch=12:00-12:45")])   # lunch differs from line's
EXT_OP = ("EXTOP", [shift("Ext", MON_SAT, "09:00", "22:00")])


def _with_eve(b: Builder, effective_from: date | None = None) -> None:
    b.template("EVE", "Evening", [shift("Evening", MON_SAT, "18:00", "22:00")])
    kw = {"effective_from": effective_from} if effective_from else {}
    b.assign("EVE", "group", "G", kind="optional", cost_per_hour=300.0, **kw)


def _skill_issues(r) -> list[Any]:
    return [i for i in r.issues if i.code == "MFG_SKILL_NOT_ON_SHIFT"]


def test_ts1_reg_operators_cover_reg_line_despite_different_lunch():
    assert _skill_issues(_coverage([REG_OP], lambda b: None)) == []


def test_ts2_optional_evening_without_crew():
    issues = _skill_issues(_coverage([REG_OP], _with_eve))
    assert len(issues) == 1
    assert issues[0].message == ("No operator with skill S is on shift for line L1 during EVE/Evening (optional) "
                                 "Mon-Sat 18:00-22:00.")
    assert issues[0].entity.type == "skill" and [x.type for x in issues[0].related] == ["line", "group"]
    assert issues[0].link.startswith("/mfg/resources/skills?skill=")


def test_ts3_extended_hours_crew_covers_overtime():
    assert _skill_issues(_coverage([REG_OP, EXT_OP], _with_eve)) == []


def test_ts4_partial_overlap_is_not_coverage():
    def three(b: Builder) -> None:
        b.template("3S", "Three", [shift("A", MON_SAT, "06:00", "14:00"), shift("B", MON_SAT, "14:00", "22:00"),
                                   shift("C", MON_SAT, "22:00", "06:00")])
        one(b, "shift_assignments", template_code="REG")["template_code"] = "3S"
    issues = _skill_issues(_coverage([REG_OP], three))
    assert len(issues) == 1
    assert issues[0].message == (
        "No operator with skill S is on shift for line L1 during 3S/A+B+C (base) Mon 06:00-09:00; "
        "3S/A+B+C (base) Mon-Fri 18:00-09:00; 3S/A+B+C (base) Sat 18:00-06:00 and 1 more.")


def test_ts5_handover_gap_below_tolerance_is_ignored():
    early = ("EARLY", [shift("E", MON_SAT, "09:00", "13:30")])
    late = ("LATE", [shift("L", MON_SAT, "13:40", "18:00")])

    def no_lunch(b: Builder) -> None:
        one(b, "shifts", template_code="REG")["breaks"] = []
    assert _skill_issues(_coverage([early, late], no_lunch)) == []
    long_gap = ("LATE2", [shift("L", MON_SAT, "13:50", "18:00")])
    assert len(_skill_issues(_coverage([early, long_gap], no_lunch))) == 1


def test_ts6_assignment_starting_inside_the_horizon_is_found():
    issues = _skill_issues(_coverage([REG_OP], lambda b: _with_eve(b, AS_OF + timedelta(days=30))))
    assert len(issues) == 1 and "EVE/Evening (optional) Mon-Sat 18:00-22:00" in issues[0].message
    assert _skill_issues(_coverage([REG_OP], lambda b: _with_eve(b, AS_OF + timedelta(days=95)))) == []


def test_unattended_crew_zero_needs_no_operator_on_shift():
    def unattended(b: Builder) -> None:
        _with_eve(b)
        one(b, "operations").update(labor="unattended", crew_size=0)
    assert _skill_issues(_coverage([REG_OP], unattended)) == []
