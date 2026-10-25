"""Release and document rules (M1-DESIGN 4.2, 3.5, 3.6; PLAN-M1 A2-4): every blocking condition has one blocked
and one passing case; supersede only shortens earlier-starting overlapping documents."""

from __future__ import annotations

from datetime import date

import pytest

from mfgpure_helpers import Builder, base_plant, ds_of, item, line, op
from superplanner.mfg import (ReleaseError, bom_release_issues, routing_release_issues, validate_bom_document,
                              validate_routing_document)
from superplanner.mfg.model import BomLineInput, OperationInput


def draft_bom(b: Builder, lines: list[dict], version: int = 2, **kw) -> Builder:
    b.bom("P", lines, version=version, status="draft", effective_from=kw.pop("effective_from", None), **kw)
    return b


def bom_id(ds, version: int) -> str:
    return next(x.id for x in ds.boms.values() if x.version == version)


def codes(issues) -> list[str]:
    return [i.code for i in issues]


def release(b: Builder, version: int = 2, eff=date(2027, 1, 1), sup: bool = True):
    ds = ds_of(b)
    return bom_release_issues(ds, bom_id(ds, version), eff, sup)


def test_passing_release_supersedes_the_earlier_bom():
    issues, superseded = release(draft_bom(base_plant(), [line(10, "C", 3)]))
    assert issues == []
    assert [(s["version"], s["effective_to"]) for s in superseded] == [(1, date(2027, 1, 1))]


def test_later_starting_bom_is_not_touched_and_blocks():
    b = base_plant()
    b.bom("P", [line(10, "C", 1)], version=3, effective_from=date(2027, 6, 1))
    draft_bom(b, [line(10, "C", 3)])
    issues, superseded = release(b)
    assert codes(issues) == ["MFG_BOM_EFFECTIVITY_OVERLAP"] and [s["version"] for s in superseded] == [1]


def test_overlap_without_supersede_blocks():
    issues, superseded = release(draft_bom(base_plant(), [line(10, "C", 3)]), sup=False)
    assert codes(issues) == ["MFG_BOM_EFFECTIVITY_OVERLAP"] and superseded == []


def test_no_overlap_when_windows_do_not_meet():
    b = base_plant()
    b.b["boms"][0]["effective_to"] = date(2026, 6, 1)
    issues, _ = release(draft_bom(b, [line(10, "C", 3)]), eff=date(2026, 6, 1), sup=False)
    assert issues == []


def test_empty_bom_blocks():
    assert codes(release(draft_bom(base_plant(), []))[0]) == ["MFG_BOM_EMPTY"]


def test_cycle_blocks():
    b = base_plant()
    b.item("Q", "make", "Q")
    b.bom("Q", [line(10, "P", 1)], status="draft", effective_from=None)
    draft_bom(b, [line(10, "C", 2), line(20, "Q", 1)])
    issues, _ = release(b)
    assert codes(issues) == ["MFG_BOM_CYCLE"] and "P -> Q -> P" in issues[0].message


def test_uom_mismatch_blocks():
    assert codes(release(draft_bom(base_plant(), [line(10, "C", 2, uom="M")]))[0]) == ["MFG_UOM_MISMATCH"]
    assert release(draft_bom(base_plant(), [line(10, "C", 2, uom="EA")]))[0] == []


def test_alternates_need_exactly_one_primary_and_distinct_priorities():
    b = base_plant()
    b.item("C2", "buy", "C2", lead_time_days=1)
    alt = [line(10, "C", 1, alt_group="10", alt_priority=2), line(10, "C2", 1, alt_group="10", alt_priority=3)]
    assert codes(release(draft_bom(b, alt))[0]) == ["MFG_ALT_NO_PRIMARY"]
    b = base_plant()
    b.item("C2", "buy", "C2", lead_time_days=1)
    dup = [line(10, "C", 1, alt_group="10", alt_priority=1), line(10, "C2", 1, alt_group="10", alt_priority=1)]
    assert codes(release(draft_bom(b, dup))[0]) == ["MFG_ALT_DUPLICATE_PRIORITY"]
    b = base_plant()
    b.item("C2", "buy", "C2", lead_time_days=1)
    good = [line(10, "C", 1, alt_group="10", alt_priority=1), line(10, "C2", 1, alt_group="10", alt_priority=2)]
    assert release(draft_bom(b, good))[0] == []


def test_inactive_component_blocks():
    b = base_plant()
    b.item("X", "buy", "Old", lead_time_days=1, active=False)
    assert codes(release(draft_bom(b, [line(10, "X", 1)]))[0]) == ["MFG_INACTIVE_COMPONENT"]


def test_serial_range_needs_serialized_item():
    b = draft_bom(base_plant(), [line(10, "C", 1)])
    b.b["boms"][-1].update(serial_from=1, serial_to=10)
    assert codes(release(b, sup=False)[0]) == ["MFG_SERIAL_NOT_ALLOWED"]
    b.b["items"][0]["serialized"] = True
    assert release(b, sup=False)[0] == []          # generic v1 + serial-specific v2 never overlap


def test_release_request_errors():
    b = draft_bom(base_plant(), [line(10, "C", 1)])
    ds = ds_of(b)
    with pytest.raises(ReleaseError):
        bom_release_issues(ds, bom_id(ds, 2), None, True)
    b.b["boms"][-1]["effective_to"] = date(2027, 1, 1)
    ds = ds_of(b)
    with pytest.raises(ReleaseError):
        bom_release_issues(ds, bom_id(ds, 2), date(2027, 1, 1), True)


def _routing(b: Builder, ops: list, priority: int = 1, version: int = 2, **kw) -> tuple:
    b.routing("P", ops, priority=priority, version=version, status="draft", effective_from=None)
    b.b["routings"][-1].update(kw)
    ds = ds_of(b)
    rid = next(r.id for r in ds.routings.values() if r.version == version)
    return ds, rid


def test_routing_release_rules():
    work = [op(10, "Work", "G", run_minutes=1)]
    ds, rid = _routing(base_plant(), [])
    assert codes(routing_release_issues(ds, rid, date(2027, 1, 1), True)[0]) == ["MFG_ROUTING_NO_OPERATIONS"]
    ds, rid = _routing(base_plant(), work)
    issues, sup = routing_release_issues(ds, rid, date(2027, 1, 1), True)
    assert issues == [] and [s["version"] for s in sup] == [1]
    assert codes(routing_release_issues(ds, rid, date(2027, 1, 1), False)[0]) == ["MFG_ROUTING_EFFECTIVITY_OVERLAP"]
    ds, rid = _routing(base_plant(), work, priority=2)
    assert routing_release_issues(ds, rid, None, False) == ([], [])          # other priority never overlaps
    b = base_plant()
    ds, rid = _routing(b, work, serial_from=1, serial_to=5)
    assert codes(routing_release_issues(ds, rid, None, False)[0]) == ["MFG_SERIAL_NOT_ALLOWED"]


def test_validate_bom_document():
    ds = ds_of(base_plant())
    p, c = item(ds, "P").id, item(ds, "C").id
    ok = [BomLineInput(find_number="10", child_item_id=c, qty_per=1)]
    assert validate_bom_document(ds, p, ok) == []
    lines = [BomLineInput(find_number="10", child_item_id=c, qty_per=1),
             BomLineInput(find_number="10", child_item_id=c, qty_per=2),
             BomLineInput(find_number="20", child_item_id=p, qty_per=1),
             BomLineInput(find_number="30", child_item_id="itm_" + "9" * 32, qty_per=1),
             BomLineInput(find_number="40", child_item_id=c, qty_per=1, alt_group="A"),
             BomLineInput(find_number="41", child_item_id=c, qty_per=1, alt_group="A", alt_priority=2)]
    errs = validate_bom_document(ds, p, lines)
    assert [(e["loc"], e["type"]) for e in errs] == [
        (["body", "lines", 1, "find_number"], "duplicate_line"), (["body", "lines", 2, "child_item_id"],
                                                                  "mfg_bom_cycle"),
        (["body", "lines", 3, "child_item_id"], "mfg_unknown_reference"),
        (["body", "lines", 5, "child_item_id"], "duplicate_alternate")]


def test_validate_routing_document():
    ds = ds_of(base_plant())
    g = next(iter(ds.groups))
    ops = [OperationInput(seq=10, name="a", group_id=g), OperationInput(seq=10, name="b", group_id=g),
           OperationInput(seq=20, name="c", group_id="wcg_" + "9" * 32, skill_id="skl_" + "9" * 32,
                          tools=[{"tool_pool_id": "tlp_" + "9" * 32}])]
    errs = validate_routing_document(ds, item(ds, "P").id, ops)
    assert [(e["loc"][-1], e["type"]) for e in errs] == [("seq", "duplicate_seq"), ("group_id", "mfg_unknown_reference"),
                                                         ("skill_id", "mfg_unknown_reference"),
                                                         ("tool_pool_id", "mfg_unknown_reference")]
    assert validate_routing_document(ds, item(ds, "P").id, ops[:1]) == []
