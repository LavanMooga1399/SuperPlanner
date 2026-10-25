"""BOM computations (M1-DESIGN 4.1, 4.3, 4.4, 5; review R8; PLAN-M1 A2-1..A2-3)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from mfgpure_helpers import AS_OF, Builder, ds_of, item, line, op
from superplanner.mfg import (BomIndex, ExplosionTooLarge, ParentIndex, bom_edges, effective_bom, explode,
                              find_cycles, refdes_count, where_used, would_create_cycle)
from superplanner.mfg.limits import MAX_EXPLOSION_ROWS


def _plant(b: Builder) -> Builder:
    b.plant("P")
    b.group("G", "Stage")
    b.line("L1", "G", "Line")
    return b


# ---------------------------------------------------------------- effectivity (4.1)

def _versions() -> Builder:
    b = _plant(Builder())
    b.item("P", "make", "Parent", serialized=True)
    for pn in ("C1", "C2", "C3", "C4"):
        b.item(pn, "buy", pn, lead_time_days=1)
    b.bom("P", [line(10, "C1", 1)], version=1, effective_from=date(2026, 1, 1))
    b.b["boms"][-1]["effective_to"] = date(2026, 6, 1)
    b.bom("P", [line(10, "C2", 1)], version=2, effective_from=date(2026, 6, 1))
    b.bom("P", [line(10, "C3", 1)], version=3, effective_from=date(2026, 3, 1))
    b.b["boms"][-1].update(serial_from=100, serial_to=199)
    b.bom("P", [line(10, "C4", 1)], version=4, status="draft", effective_from=None)
    return b


@pytest.mark.parametrize("on,serial,expected", [
    (date(2025, 12, 31), None, None),                     # before the first window
    (date(2026, 1, 1), None, 1),                          # from is inclusive
    (date(2026, 5, 31), None, 1),
    (date(2026, 6, 1), None, 2),                          # to is exclusive, the successor starts
    (date(2026, 7, 1), 150, 3),                           # serial-specific overrides generic
    (date(2026, 7, 1), 99, 2),                            # outside the serial range -> generic
    (date(2026, 2, 1), 150, 1),                           # specific not yet effective on that date
])
def test_effective_bom_selection(on, serial, expected):
    ds = ds_of(_versions())
    b = effective_bom(ds, item(ds, "P").id, on, serial)
    assert (b.version if b else None) == expected


def test_draft_never_effective_and_overlap_tie_break():
    b = _versions()
    b.bom("P", [line(10, "C1", 2)], version=5, effective_from=date(2026, 6, 1))      # overlaps v2, later version
    ds = ds_of(b)
    assert effective_bom(ds, item(ds, "P").id, date(2026, 7, 1)).version == 5
    b.b["boms"][-1]["effective_from"] = date(2026, 5, 1)     # same version rule, later effective_from wins
    ds = ds_of(b)
    assert effective_bom(ds, item(ds, "P").id, date(2026, 7, 1)).version == 2


# ---------------------------------------------------------------- quantities (4.4), T-Q1

def _tq1(seq: int | None = 10) -> Builder:
    b = _plant(Builder())
    b.item("P", "make", "PCB")
    b.item("C", "buy", "Capacitor", lead_time_days=1)
    b.bom("P", [line(10, "C", 4, scrap_pct=2, operation_seq=seq)])
    b.routing("P", [op(10, "SMT", "G", run_minutes=1), op(20, "ICT", "G", run_minutes=1, yield_pct=97),
                    op(30, "FCT", "G", run_minutes=1, yield_pct=98)])
    return b


def _explode(ds, pn, **kw):
    return explode(BomIndex.from_dataset(ds, AS_OF), item(ds, pn).id, **kw)


def test_tq1_rolled_up_quantity():
    e = _explode(ds_of(_tq1()), "P", qty=100)
    assert e.rows[1].extended_qty == 429.202609
    assert e.rows[0].extended_qty == 100.0 and e.rows[0].routing_id is not None


def test_scrap_and_yield_switches():
    ds = ds_of(_tq1())
    assert _explode(ds, "P", qty=100, include_yield=False).rows[1].extended_qty == 408.0
    assert _explode(ds, "P", qty=100, include_scrap=False).rows[1].extended_qty == round(400 / 0.9506, 6)
    assert _explode(ds, "P", qty=100, include_scrap=False, include_yield=False).rows[1].extended_qty == 400.0


def test_operation_seq_consumption():
    assert _explode(ds_of(_tq1(30)), "P", qty=100).rows[1].extended_qty == round(100 / 0.98 * 4 * 1.02, 6)
    assert _explode(ds_of(_tq1(20)), "P", qty=100).rows[1].extended_qty == round(100 / 0.9506 * 4 * 1.02, 6)
    assert _explode(ds_of(_tq1(None)), "P", qty=100).rows[1].extended_qty == 429.202609
    assert _explode(ds_of(_tq1(99)), "P", qty=100).rows[1].extended_qty == 429.202609   # unknown seq -> first op


def test_uom_conversion_wire_mm_to_m():
    b = _plant(Builder())
    b.item("H", "make", "Harness")
    b.item("W", "buy", "Wire", uom="M", lead_time_days=1)
    b.bom("H", [line(10, "W", 1500, uom="MM")])
    e = _explode(ds_of(b), "H", qty=2)
    assert (e.rows[1].extended_qty, e.rows[1].uom, e.rows[1].line_uom, e.rows[1].qty_per) == (3.0, "M", "MM", 1500.0)


# ---------------------------------------------------------------- structure

def _tree() -> Builder:
    b = _plant(Builder())
    b.item("T", "make", "Top")
    b.item("S", "make", "Sub")
    b.item("K", "phantom", "Kit")
    for pn in ("A", "B", "X", "Y", "Z"):
        b.item(pn, "buy", pn, lead_time_days=1)
    b.bom("T", [line(10, "S", 2), line(20, "A", 1), line(30, "K", 1),
                line(40, "X", 1, alt_group="40", alt_priority=1), line(40, "Y", 1, alt_group="40", alt_priority=2)])
    b.bom("S", [line(10, "A", 3), line(2, "B", 1)])
    b.bom("K", [line(10, "Z", 4)])
    return b


def test_indented_order_levels_subtree_end_and_flags():
    e = _explode(ds_of(_tree()), "T")
    got = [(r.row, r.level, r.part_number, r.parent_row, r.subtree_end) for r in e.rows]
    assert got == [(0, 0, "T", None, 8), (1, 1, "S", 0, 4), (2, 2, "B", 1, 3), (3, 2, "A", 1, 4),
                   (4, 1, "A", 0, 5), (5, 1, "K", 0, 7), (6, 2, "Z", 5, 7), (7, 1, "X", 0, 8)]
    rows = {r.row: r for r in e.rows}
    assert rows[0].subtree_end == len(e.rows) == 8
    assert e.rows[7].part_number == "X" and e.rows[7].subtree_end == 8
    assert [a.part_number for a in e.rows[7].alternates] == ["Y"]
    assert not any(r.part_number == "Y" for r in e.rows)                           # alternates attached, not rows
    assert rows[3].extended_qty == 6.0 and rows[4].extended_qty == 1.0
    assert rows[3].is_shared and rows[4].is_shared and not rows[2].is_shared        # A under T and S
    assert rows[5].is_phantom and rows[5].has_children and not rows[4].has_children
    assert rows[1].bom_id is not None and rows[4].bom_id is None
    assert rows[2].find_number == "2"                                               # natural find-number order
    assert e.totals.model_dump() == {"rows": 8, "distinct_items": 7, "max_level": 2, "make_items": 2,
                                     "buy_items": 4, "phantom_items": 1}
    assert e.warnings == []


def test_summarized_omits_phantoms_and_rolls_up():
    e = _explode(ds_of(_tree()), "T", qty=2, mode="summarized")
    rows = {r.part_number: r for r in e.rows}
    assert set(rows) == {"S", "A", "X", "B", "Z"}
    assert rows["A"].total_qty == 2 + 12 and rows["A"].occurrences == 2
    assert (rows["A"].min_level, rows["A"].max_level) == (1, 2)
    assert rows["Z"].total_qty == 8 and rows["Z"].min_level == 2
    assert [r.part_number for r in e.rows] == ["A", "S", "X", "B", "Z"]          # (min_level, part_number)


def test_max_depth_and_missing_bom_warning():
    b = _tree()
    b.b["boms"] = [r for r in b.b["boms"] if r["parent_part_number"] != "S"]
    b.b["bom_lines"] = [r for r in b.b["bom_lines"] if r["parent_part_number"] != "S"]
    ds = ds_of(b)
    e = _explode(ds, "T")
    assert [(w.code, w.item_id) for w in e.warnings] == [("MFG_NO_EFFECTIVE_BOM", item(ds, "S").id)]
    e = _explode(ds_of(_tree()), "T", max_depth=1)
    assert max(r.level for r in e.rows) == 1 and e.warnings == []


def test_cycle_is_cut_with_warning():
    b = _plant(Builder())
    b.item("A", "make", "A")
    b.item("B", "make", "B")
    b.bom("A", [line(10, "B", 1)])
    b.bom("B", [line(10, "A", 1)])
    e = _explode(ds_of(b), "A")
    assert [r.part_number for r in e.rows] == ["A", "B", "A"]
    assert [w.code for w in e.warnings] == ["MFG_BOM_CYCLE"]


def test_too_deep_warning():
    b = _plant(Builder())
    for i in range(23):
        b.item(f"N{i}", "make" if i < 22 else "buy", f"N{i}", lead_time_days=1 if i == 22 else None)
    for i in range(22):
        b.bom(f"N{i}", [line(10, f"N{i + 1}", 1)])
    e = _explode(ds_of(b), "N0")
    assert max(r.level for r in e.rows) == 20
    assert [w.code for w in e.warnings] == ["MFG_BOM_TOO_DEEP"]
    s = _explode(ds_of(b), "N0", mode="summarized")
    assert [w.code for w in s.warnings] == ["MFG_BOM_TOO_DEEP"] and s.totals.max_level == 20


# ---------------------------------------------------------------- R8 diamond (A2-3)

def _diamond() -> Builder:
    b = _plant(Builder())
    b.item("R", "make", "Root")
    for k in range(1, 20):
        b.item(f"A{k}", "make", f"A{k}")
        b.item(f"B{k}", "make", f"B{k}")
    b.item("LEAF", "buy", "Leaf", lead_time_days=1)
    b.bom("R", [line(10, "A1", 1), line(20, "B1", 1)])
    for k in range(1, 19):
        for x in ("A", "B"):
            b.bom(f"{x}{k}", [line(10, f"A{k + 1}", 1), line(20, f"B{k + 1}", 1)])
    for x in ("A", "B"):
        b.bom(f"{x}19", [line(10, "LEAF", 1), line(20, "LEAF", 1)])
    return b


def test_diamond_indented_raises_fast_and_summarized_counts_paths():
    ds = ds_of(_diamond())
    idx = BomIndex.from_dataset(ds, AS_OF)
    root = item(ds, "R").id
    t = time.perf_counter()
    with pytest.raises(ExplosionTooLarge) as exc:
        explode(idx, root)
    assert time.perf_counter() - t < 1.0 and exc.value.limit == MAX_EXPLOSION_ROWS
    t = time.perf_counter()
    e = explode(idx, root, mode="summarized")
    assert time.perf_counter() - t < 1.0
    leaf = next(r for r in e.rows if r.part_number == "LEAF")
    assert leaf.occurrences == 2 ** 20 and leaf.total_qty == float(2 ** 20)
    assert (leaf.min_level, leaf.max_level) == (20, 20)


# ---------------------------------------------------------------- where-used

def test_where_used_single_and_indented():
    b = _tree()
    b.bom("S", [line(10, "A", 5)], version=2, status="draft", effective_from=None)
    ds = ds_of(b)
    a = item(ds, "A").id
    eff = ParentIndex.from_dataset(ds, AS_OF, "effective")
    single = where_used(eff, a)
    assert [(r.part_number, r.level, r.parent_row, r.is_top) for r in single.rows] == \
        [("S", 1, None, False), ("T", 1, None, True)]
    ind = where_used(eff, a, mode="indented")
    assert [(r.part_number, r.level, r.parent_row) for r in ind.rows] == [("S", 1, None), ("T", 2, 0), ("T", 1, None)]
    assert ind.totals.model_dump() == {"rows": 3, "top_items": 1}
    allv = where_used(ParentIndex.from_dataset(ds, None, "all"), a)
    assert [(r.part_number, r.bom_version, r.bom_status) for r in allv.rows] == \
        [("S", 1, "released"), ("S", 2, "draft"), ("T", 1, "released")]


# ---------------------------------------------------------------- cycles (A2-2)

def test_find_cycles_self_two_long_and_multiple():
    assert find_cycles([("a", "a")]) == [["a", "a"]]
    assert find_cycles([("a", "b"), ("b", "a")]) == [["a", "b", "a"]]
    long_ = [(f"n{i}", f"n{i + 1}") for i in range(9)] + [("n9", "n0")]
    assert find_cycles(long_) == [["n0"] + [f"n{i}" for i in range(1, 10)] + ["n0"]]
    multi = [("x", "y"), ("y", "x"), ("b", "c"), ("c", "d"), ("d", "b"), ("d", "e"), ("e", "f")]
    assert find_cycles(multi) == [["b", "c", "d", "b"], ["x", "y", "x"]]
    assert find_cycles([("a", "b"), ("b", "c")]) == []


def test_find_cycles_rotation_by_key():
    pn = {"i1": "Z", "i2": "A", "i3": "M"}
    assert find_cycles([("i1", "i2"), ("i2", "i3"), ("i3", "i1")], key=pn.get) == [["i2", "i3", "i1", "i2"]]


def test_find_cycles_5000_chain_without_recursion_error():
    edges = [(f"n{i}", f"n{i + 1}") for i in range(5000)]
    assert find_cycles(edges) == []
    cyc = find_cycles(edges + [("n5000", "n0")])
    assert len(cyc) == 1 and len(cyc[0]) == 5002


def test_would_create_cycle():
    edges = [("a", "b"), ("b", "c")]
    assert would_create_cycle(edges, [("c", "a")]) == ["c", "a", "b", "c"]
    assert would_create_cycle(edges, [("x", "x")]) == ["x", "x"]
    assert would_create_cycle(edges, [("a", "c")]) is None


def test_bom_edges_skip_obsolete():
    b = _tree()
    b.bom("S", [line(10, "Y", 1)], version=2, status="obsolete")
    ds = ds_of(b)
    pairs = {(ds.items[p].part_number, ds.items[c].part_number) for p, c in bom_edges(ds)}
    assert ("S", "Y") not in pairs and ("T", "S") in pairs and ("T", "Y") in pairs


# ---------------------------------------------------------------- reference designators

@pytest.mark.parametrize("text,expected", [
    ("R1-R5", (5, [])), ("R1-5", (5, [])), ("C1, C2 C3", (3, [])), ("R1, R2, R5-R9", (7, [])), ("", (0, [])),
    ("U1;U2", (2, [])), ("R5-R1", (0, ["R5-R1"])), ("R1-C5", (0, ["R1-C5"])), ("R1, 12, R-", (1, ["12", "R-"])),
    ("J1A", (1, [])),
])
def test_refdes_count(text, expected):
    assert refdes_count(text) == expected


def test_refdes_huge_range_is_one_invalid_token_and_fast():
    t = time.perf_counter()
    assert refdes_count("R1-R999999999") == (0, ["R1-R999999999"])
    assert time.perf_counter() - t < 0.01
    assert refdes_count("R1-R10000") == (10000, [])
    assert refdes_count("R1-R10001") == (0, ["R1-R10001"])
