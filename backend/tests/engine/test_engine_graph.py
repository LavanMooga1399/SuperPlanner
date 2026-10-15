"""A.9.2 graph analysis: Tarjan cycles, Kahn order, CPM for all four dependency types."""

import pytest

from engine_helpers import at, compiled, dep, lock, problem, task
from superplanner.engine.graph import CycleError, cpm, find_cycles, topological_order


def test_find_cycles_reports_cycle_in_order():
    cycles = find_cycles(5, [(0, 1), (1, 2), (2, 0), (3, 4)])
    assert cycles == [[0, 1, 2]]
    assert find_cycles(3, [(0, 1), (1, 2)]) == []
    two = find_cycles(6, [(0, 1), (1, 0), (2, 3), (3, 4), (4, 2), (5, 5 - 1)])
    assert sorted(len(c) for c in two) == [2, 3]


def test_topological_order_ties_by_index():
    assert topological_order(4, [(2, 0), (3, 1)]) == [2, 0, 3, 1]
    with pytest.raises(CycleError):
        topological_order(2, [(0, 1), (1, 0)])


def test_cpm_textbook_network():
    # A(3) -> B(2) -> D(4); A -> C(5) -> D
    p = problem([task("A", 3), task("B", 2), task("C", 5), task("D", 4)], [],
                [dep("A", "B"), dep("A", "C"), dep("B", "D"), dep("C", "D")])
    r = cpm(compiled(p))
    t = r.tasks
    assert r.lower_bound_makespan_minutes == 12
    assert (t["A"].es, t["A"].ef, t["C"].es, t["D"].es) == (0, 3, 3, 8)
    assert (t["B"].ls, t["B"].slack, t["B"].critical) == (6, 3, False)
    assert all(t[x].critical for x in "ACD")
    assert r.critical_path == ["A", "C", "D"]


@pytest.mark.parametrize("dtype,lag,expected_es_b", [
    ("FS", 0, 60), ("FS", 30, 90), ("FS", -30, 30),
    ("SS", 20, 20), ("SS", -20, 0),
    ("FF", 0, 30), ("FF", 15, 45),       # E_b >= E_a + L  ->  S_b >= 60 + L - 30
    ("SF", 50, 20), ("SF", 10, 0),        # E_b >= S_a + L  ->  S_b >= 0 + L - 30
])
def test_cpm_dependency_types_and_lags(dtype, lag, expected_es_b):
    p = problem([task("A", 60), task("B", 30)], [], [dep("A", "B", dtype, lag)])
    r = cpm(compiled(p))
    assert r.tasks["B"].es == expected_es_b


def test_cpm_backward_pass_ff_ss():
    p = problem([task("A", 60), task("B", 30), task("C", 100)], [], [dep("A", "B", "FF", 0)])
    r = cpm(compiled(p))
    # PE = 100 (C); B has LF 100; A's LF bounded by LF_B - 0 = 100
    assert r.lower_bound_makespan_minutes == 100
    assert r.tasks["A"].lf == 100 and r.tasks["A"].slack == 40


def test_cpm_release_and_lock():
    p = problem([task("A", 60, earliest_start=at(100)), task("B", 30, locked=lock(500))], [], [dep("A", "B")])
    r = cpm(compiled(p))
    assert r.tasks["A"].es == 100 and r.tasks["B"].es == 500
