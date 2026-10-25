"""Domain models (M1-DESIGN 3): one valid and one invalid case per field constraint / model rule; A1-6 round trips."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from superplanner.mfg import bundle_to_dataset, samples
from superplanner.mfg.model import (INPUT_OF, BomInput, BomLineInput, CalendarExceptionInput, GroupInput,
                                    ItemInput, LineInput, OperationInput, OperatorInput, PlantInput, RoutingInput,
                                    ShiftAssignmentInput, ShiftDef, ShiftTemplateInput, SkillInput, ToolPoolInput,
                                    input_data, to_input)

ID = "itm_" + "a" * 32
ID2 = "itm_" + "b" * 32
GID = "wcg_" + "c" * 32


def ok(cls, **kw):
    return cls.model_validate(kw)


def bad(cls, **kw):
    with pytest.raises(ValidationError):
        cls.model_validate(kw)


# ---------------------------------------------------------------- common types

@pytest.mark.parametrize("pn", ["KV-PCB-CPU", "123", "Ä-Teil 7", "x" * 64])
def test_part_number_valid(pn):
    assert ok(ItemInput, part_number=pn, make_buy="buy").part_number == pn


@pytest.mark.parametrize("pn", ["", "   ", "x" * 65, "A\x00B", "A\nB", "A\x7fB"])
def test_part_number_invalid(pn):
    bad(ItemInput, part_number=pn, make_buy="buy")


def test_part_number_trimmed():
    assert ok(ItemInput, part_number="  P-1 ", make_buy="buy").part_number == "P-1"


@pytest.mark.parametrize("code,valid", [("SMT-1", True), ("a/b.c_d", True), ("3SHIFT", True), ("x" * 32, True),
                                        ("x" * 33, False), ("-A", False), ("A B", False), ("", False)])
def test_code(code, valid):
    (ok if valid else bad)(SkillInput, code=code, name="n")


@pytest.mark.parametrize("rev,valid", [("A", True), ("B.2-x_1", True), ("x" * 17, False), ("A B", False)])
def test_revision(rev, valid):
    (ok if valid else bad)(ItemInput, part_number="P", make_buy="buy", revision=rev)


def test_name_rules():
    ok(SkillInput, code="S", name="x" * 200)
    bad(SkillInput, code="S", name="x" * 201)
    bad(SkillInput, code="S", name="  ")
    bad(SkillInput, code="S", name="a\tb")


def test_text500_allows_tab_and_line_breaks_only():
    assert ok(SkillInput, code="S", name="n", description="a\tb\r\nc").description == "a\tb\r\nc"
    bad(SkillInput, code="S", name="n", description="a\x01b")
    bad(SkillInput, code="S", name="n", description="x" * 501)


def test_extra_fields_forbidden():
    bad(SkillInput, code="S", name="n", colour="red")


def test_entity_id_format():
    ok(BomLineInput, find_number="10", child_item_id=ID, qty_per=1)
    bad(BomLineInput, find_number="10", child_item_id="itm_123", qty_per=1)
    bad(BomLineInput, find_number="10", child_item_id="ITM_" + "a" * 32, qty_per=1)


@pytest.mark.parametrize("q,valid", [(0.001, True), (1_000_000, True), (0, False), (-1, False), (1_000_001, False)])
def test_qty(q, valid):
    (ok if valid else bad)(BomLineInput, find_number="10", child_item_id=ID, qty_per=q)


@pytest.mark.parametrize("p,valid", [(0, True), (99.9, True), (100, False), (-0.1, False)])
def test_scrap_pct(p, valid):
    (ok if valid else bad)(BomLineInput, find_number="10", child_item_id=ID, qty_per=1, scrap_pct=p)


@pytest.mark.parametrize("y,valid", [(0.1, True), (100, True), (0, False), (100.1, False)])
def test_yield_pct(y, valid):
    (ok if valid else bad)(OperationInput, seq=10, name="x", group_id=GID, yield_pct=y)


@pytest.mark.parametrize("m,valid", [(0, True), (100_000, True), (-1, False), (100_001, False)])
def test_minutes(m, valid):
    (ok if valid else bad)(OperationInput, seq=10, name="x", group_id=GID, setup_minutes=m)


def test_attributes():
    assert ok(ItemInput, part_number="P", make_buy="buy", attributes={"mpn": "SYN-1", "n": 3, "f": 1.5,
                                                                      "b": True}).attributes["n"] == 3
    bad(ItemInput, part_number="P", make_buy="buy", attributes={f"k{i}": 1 for i in range(51)})
    bad(ItemInput, part_number="P", make_buy="buy", attributes={"bad key": 1})
    bad(ItemInput, part_number="P", make_buy="buy", attributes={"k": "x" * 501})
    bad(ItemInput, part_number="P", make_buy="buy", attributes={"k": [1]})


@pytest.mark.parametrize("off,valid", [("+05:30", True), ("-14:00", True), ("+00:00", True), ("+15:00", False),
                                       ("05:30", False), ("+5:30", False)])
def test_utc_offset(off, valid):
    (ok if valid else bad)(PlantInput, utc_offset=off)


def test_plant_defaults_and_horizon():
    p = PlantInput()
    assert (p.name, p.utc_offset, p.planning_horizon_days, p.currency) == ("Plant", "+00:00", 90, "")
    bad(PlantInput, planning_horizon_days=6)
    bad(PlantInput, planning_horizon_days=731)
    bad(PlantInput, currency="x" * 9)


# ---------------------------------------------------------------- item

def test_item_defaults():
    i = ok(ItemInput, part_number="P", make_buy="make")
    assert (i.revision, i.uom, i.lot_rule, i.active, i.serialized) == ("A", "EA", "lot_for_lot", True, False)


def test_item_uom_must_be_known():
    ok(ItemInput, part_number="P", make_buy="buy", uom="ML")
    bad(ItemInput, part_number="P", make_buy="buy", uom="PCS")


def test_item_fixed_lot_iff_fixed_rule():
    ok(ItemInput, part_number="P", make_buy="buy", lot_rule="fixed", fixed_lot_qty=10)
    bad(ItemInput, part_number="P", make_buy="buy", lot_rule="fixed")
    bad(ItemInput, part_number="P", make_buy="buy", fixed_lot_qty=10)


def test_item_ranges():
    bad(ItemInput, part_number="P", make_buy="buy", lead_time_days=731)
    bad(ItemInput, part_number="P", make_buy="buy", receiving_days=61)
    bad(ItemInput, part_number="P", make_buy="buy", shelf_life_days=0)
    bad(ItemInput, part_number="P", make_buy="buy", min_order_qty=-1)
    bad(ItemInput, part_number="P", make_buy="other")


# ---------------------------------------------------------------- BOM

def test_bom_effectivity_and_serials():
    ok(BomInput, item_id=ID, effective_from=date(2026, 1, 1), effective_to=date(2026, 2, 1))
    bad(BomInput, item_id=ID, effective_from=date(2026, 2, 1), effective_to=date(2026, 2, 1))
    ok(BomInput, item_id=ID, serial_from=1, serial_to=1)
    bad(BomInput, item_id=ID, serial_from=1)
    bad(BomInput, item_id=ID, serial_from=5, serial_to=4)
    bad(BomInput, item_id=ID, version=0)


def test_bom_line_limits():
    line = {"find_number": "10", "child_item_id": ID, "qty_per": 1}
    ok(BomInput, item_id=ID, lines=[line] * 2000)
    bad(BomInput, item_id=ID, lines=[line] * 2001)
    bad(BomLineInput, **line, alt_priority=0)
    bad(BomLineInput, **line, operation_seq=10_000)
    bad(BomLineInput, **line, uom="XX")
    bad(BomLineInput, **line, ref_designators="R" * 4001)
    bad(BomLineInput, find_number="1 0", child_item_id=ID, qty_per=1)


# ---------------------------------------------------------------- routing

def test_operation_panel_and_batch_rules():
    ok(OperationInput, seq=10, name="x", group_id=GID, run_per="panel", units_per_panel=4)
    bad(OperationInput, seq=10, name="x", group_id=GID, run_per="panel")
    bad(OperationInput, seq=10, name="x", group_id=GID, units_per_panel=4)
    ok(OperationInput, seq=10, name="x", group_id=GID, run_per="batch", units_per_batch=8)
    bad(OperationInput, seq=10, name="x", group_id=GID, run_per="batch")


def test_operation_crew_zero_only_unattended():
    ok(OperationInput, seq=10, name="x", group_id=GID, labor="unattended", crew_size=0)
    bad(OperationInput, seq=10, name="x", group_id=GID, crew_size=0)


def test_operation_tools_unique():
    t = {"tool_pool_id": "tlp_" + "d" * 32, "qty": 1}
    ok(OperationInput, seq=10, name="x", group_id=GID, tools=[t])
    bad(OperationInput, seq=10, name="x", group_id=GID, tools=[t, t])
    bad(OperationInput, seq=10, name="x", group_id=GID, tools=[{**t, "qty": 101}])


def test_routing_rules():
    r = ok(RoutingInput, item_id=ID)
    assert (r.code, r.priority) == ("STD", 1)
    bad(RoutingInput, item_id=ID, priority=10)
    op = {"seq": 10, "name": "x", "group_id": GID}
    ok(RoutingInput, item_id=ID, operations=[op] * 200)
    bad(RoutingInput, item_id=ID, operations=[op] * 201)


# ---------------------------------------------------------------- groups, lines

def test_line_rules():
    ok(LineInput, group_id=GID, code="L", name="n", speed_factor=0.05, parallel_capacity=100)
    bad(LineInput, group_id=GID, code="L", name="n", speed_factor=0.04)
    bad(LineInput, group_id=GID, code="L", name="n", speed_factor=20.1)
    bad(LineInput, group_id=GID, code="L", name="n", parallel_capacity=0)
    bad(LineInput, group_id=GID, code="L", name="n", eligible_families=["A", "A"])
    bad(LineInput, group_id=GID, code="L", name="n", eligible_item_ids=[ID, ID])
    ok(GroupInput, code="G", name="n", kind="oven")


# ---------------------------------------------------------------- shifts

def test_shift_def_rules():
    ok(ShiftDef, name="A", days=["mon"], start="22:00", end="06:00")
    bad(ShiftDef, name="A", days=["mon"], start="24:00", end="06:00")
    bad(ShiftDef, name="A", days=["mon", "mon"], start="06:00", end="14:00")
    bad(ShiftDef, name="A", days=[], start="06:00", end="14:00")
    bad(ShiftDef, name="A", days=["xyz"], start="06:00", end="14:00")
    bad(ShiftDef, name="A", days=["mon"], start="25:00", end="06:00")
    ok(ShiftDef, name="A", days=["mon"], start="00:00", end="24:00")


def test_template_rules():
    sh = {"name": "A", "days": ["mon"], "start": "06:00", "end": "14:00"}
    ok(ShiftTemplateInput, code="T", name="n", shifts=[sh])
    bad(ShiftTemplateInput, code="T", name="n", shifts=[])
    bad(ShiftTemplateInput, code="T", name="n", shifts=[sh, sh])
    bad(ShiftTemplateInput, code="T", name="n", shifts=[{**sh, "name": f"S{i}"} for i in range(11)])


def test_assignment_rules():
    base = {"shift_template_id": "sht_" + "e" * 32, "effective_from": date(2026, 1, 1)}
    ok(ShiftAssignmentInput, **base, target_type="group", group_id=GID)
    bad(ShiftAssignmentInput, **base, target_type="group")
    bad(ShiftAssignmentInput, **base, target_type="line", group_id=GID)
    ok(ShiftAssignmentInput, **base, target_type="group", group_id=GID, kind="optional", cost_per_hour=10,
       max_hours_per_week=12)
    bad(ShiftAssignmentInput, **base, target_type="group", group_id=GID, cost_per_hour=10)
    bad(ShiftAssignmentInput, **base, target_type="group", group_id=GID, kind="optional", max_hours_per_week=169)
    bad(ShiftAssignmentInput, **base, target_type="group", group_id=GID, effective_to=date(2026, 1, 1))


def test_exception_rules():
    t0 = datetime(2026, 11, 9, tzinfo=UTC)
    ok(CalendarExceptionInput, scope="plant", kind="holiday", start=t0, end=t0 + timedelta(days=1))
    bad(CalendarExceptionInput, scope="plant", kind="holiday", start=t0, end=t0)
    bad(CalendarExceptionInput, scope="plant", kind="holiday", start=t0, end=t0 + timedelta(days=367))
    bad(CalendarExceptionInput, scope="group", kind="holiday", start=t0, end=t0 + timedelta(days=1))
    bad(CalendarExceptionInput, scope="plant", group_id=GID, kind="holiday", start=t0, end=t0 + timedelta(days=1))
    bad(CalendarExceptionInput, scope="plant", kind="holiday", start=datetime(2026, 11, 9),
        end=datetime(2026, 11, 10))
    bad(CalendarExceptionInput, scope="plant", kind="vacation", start=t0, end=t0 + timedelta(days=1))


def test_operator_and_tool_rules():
    sid = "skl_" + "f" * 32
    ok(OperatorInput, code="O", name="n", skill_ids=[sid])
    bad(OperatorInput, code="O", name="n", skill_ids=[sid, sid])
    bad(OperatorInput, code="O", name="n", shift_names=["A"])
    ok(ToolPoolInput, code="T", name="n", quantity=0)
    bad(ToolPoolInput, code="T", name="n", quantity=10_001)
    bad(ToolPoolInput, code="T", name="n")


# ---------------------------------------------------------------- A1-6

@pytest.mark.parametrize("sample", ["small", "medium"])
def test_every_record_round_trips(sample):
    ds = bundle_to_dataset(samples.build(sample))
    tables = [ds.items, ds.boms, ds.routings, ds.groups, ds.lines, ds.shift_templates, ds.shift_assignments,
              ds.calendar_exceptions, ds.skills, ds.operators, ds.tool_pools]
    seen = set()
    for table in tables:
        for rec in table.values():
            seen.add(type(rec))
            again = type(rec).model_validate(rec.model_dump())
            assert again.model_dump() == rec.model_dump()
            inp = to_input(rec)
            assert type(inp).model_validate(inp.model_dump()) == inp
            assert inp.model_dump() == INPUT_OF[type(rec)].model_validate(input_data(rec)).model_dump()
    assert len(seen) == len(tables)
    plant_in = to_input(ds.plant)
    assert isinstance(plant_in, PlantInput) and plant_in.name == ds.plant.name
