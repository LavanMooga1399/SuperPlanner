"""Bundle spec and strict conversion (M1-DESIGN 8.1, 8.2)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from mfgpure_helpers import base_plant, ds_of
from superplanner.mfg import SHEETS, BundleError, bundle_to_dataset, canonical_json, dataset_to_bundle, fingerprint
from superplanner.mfg.bundle import SHEETS_BY_NAME, deterministic_id, parse_break, parse_days, parse_tool


def test_sheet_order_and_keys():
    assert [s.name for s in SHEETS] == ["plant", "items", "skills", "tool_pools", "groups", "lines",
                                        "shift_templates", "shifts", "shift_assignments", "calendar_exceptions",
                                        "operators", "boms", "bom_lines", "routings", "operations",
                                        # M2-DESIGN 11: M2 sheets after the M1 sheets
                                        "locations", "suppliers", "item_suppliers", "stock", "purchase_docs",
                                        "purchase_lines", "purchase_schedules", "demand_orders", "demand_lines",
                                        "work_orders", "wo_components",
                                        # M3-DESIGN 3.2: M3 master sheets last
                                        "operation_line_rates", "setup_matrix", "operator_absences"]
    assert SHEETS_BY_NAME["bom_lines"].key == ("parent_part_number", "revision", "version", "find_number",
                                               "child_part_number")
    assert SHEETS_BY_NAME["operations"].key == ("part_number", "revision", "code", "version", "seq")
    assert SHEETS_BY_NAME["items"].attr_columns and SHEETS_BY_NAME["plant"].max_rows == 1
    assert SHEETS_BY_NAME["items"].column("uom").enum_values[0] == "EA"


def test_canonical_json_is_compact_sorted_and_typed():
    out = canonical_json({"b": [{"d": date(2026, 1, 2), "x": 1.5}], "a": []})
    assert out == b'{"a":[],"b":[{"d":"2026-01-02","x":1.5}]}'
    with pytest.raises(ValueError):
        canonical_json({"a": [{"x": float("nan")}]})


def test_deterministic_ids():
    assert deterministic_id("itm_", "P") == deterministic_id("itm_", "P") != deterministic_id("itm_", "Q")
    assert len(deterministic_id("itm_", "P")) == 36


def test_parsers():
    assert parse_days(["mon-wed", "fri"]) == ["mon", "tue", "wed", "fri"]
    assert parse_days(["daily"]) == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    with pytest.raises(ValueError):
        parse_days(["sat-mon"])
    assert parse_break("Lunch=13:00-13:45") == {"name": "Lunch", "start": "13:00", "end": "13:45"}
    assert parse_break("9:00-9:15") == {"name": "", "start": "09:00", "end": "09:15"}
    assert parse_tool("JIG:2") == ("JIG", 2) and parse_tool("JIG") == ("JIG", 1)


def test_fingerprint_ignores_ids_and_order():
    ds = ds_of(base_plant())
    b = dataset_to_bundle(ds)
    b["items"].reverse()
    assert fingerprint(bundle_to_dataset(b)) == fingerprint(ds)


def test_strict_errors_are_collected():
    b = base_plant()
    b.b["items"].append({"part_number": "C", "make_buy": "buy"})                 # duplicate key
    b.b["items"].append({"part_number": "Z", "make_buy": "sometimes"})           # bad enum
    b.b["bom_lines"].append({"parent_part_number": "P", "find_number": "20", "child_part_number": "NOPE",
                             "qty_per": 1})
    b.b["lines"].append({"code": "L9", "group_code": "NOGROUP", "name": "x"})
    b.b["operators"].append({"code": "O9", "name": "x", "colour": "red"})
    b.b["bogus"] = []
    with pytest.raises(BundleError) as exc:
        bundle_to_dataset(b.b)
    text = "\n".join(exc.value.errors)
    for frag in ("unknown sheets: bogus", "items row 3: duplicate key", "items row 4", "unknown part number 'NOPE'",
                 "unknown group 'NOGROUP'", "unknown columns: colour"):
        assert frag in text, text


def test_header_defaults_and_inclusive_date_end():
    b = base_plant()
    b.b["boms"] = []                                     # header created from the lines with defaults (draft)
    b.exception("plant", None, "holiday", date(2026, 11, 9), date(2026, 11, 9), "H")
    ds = bundle_to_dataset(b.b)
    (bom,) = ds.boms.values()
    assert (bom.status, bom.revision, bom.version) == ("draft", "A", 1)
    (e,) = ds.calendar_exceptions.values()
    assert e.start.astimezone(UTC) == datetime(2026, 11, 8, 18, 30, tzinfo=UTC)
    assert (e.end - e.start).total_seconds() == 86400


def test_canonical_bundle_has_every_column():
    b = dataset_to_bundle(ds_of(base_plant()))
    for spec in SHEETS:
        for row in b[spec.name]:
            assert set(spec.fields) <= set(row), spec.name
    json.loads(canonical_json(b))
