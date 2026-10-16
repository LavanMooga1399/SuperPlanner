"""Month arithmetic, occurrence rule, horizon and blocks (F.3, F.7.1)."""

from fin_helpers import goal, plan
from superplanner.finance import timegrid as tg


def test_month_index_and_add():
    assert tg.month_index("2026-11", "2026-11") == 0
    assert tg.month_index("2026-11", "2027-01") == 2
    assert tg.month_index("2026-11", "2026-10") == -1
    assert tg.add_months("2026-11", 2) == "2027-01"
    assert tg.add_months("2026-11", -11) == "2025-12"
    assert tg.month_list("2026-12", 3) == ["2026-12", "2027-01", "2027-02"]


def test_occurrence_rule_each_frequency():
    assert tg.occurrence_months(0, 11, "monthly") == list(range(12))
    assert tg.occurrence_months(1, 11, "quarterly") == [1, 4, 7, 10]
    assert tg.occurrence_months(0, 13, "half_yearly") == [0, 6, 12]
    assert tg.occurrence_months(2, 30, "yearly") == [2, 14, 26]
    assert tg.occurrence_months(5, 30, "once") == [5]
    assert tg.occurrence_months(5, 4, "monthly") == []
    assert tg.occurs(4, 1, 11, "quarterly") and not tg.occurs(5, 1, 11, "quarterly")


def test_item_bounds_clamp_and_end_before_start():
    assert tg.item_bounds("2026-11", "2025-03", None, 24) == (0, 23)       # starts before plan start [R2]
    assert tg.item_bounds("2026-11", None, "2027-02", 24) == (0, 3)
    t0, t1 = tg.item_bounds("2026-11", None, "2026-01", 24)                 # ended before the plan start
    assert t1 < t0


def test_horizon_includes_goal_payment_month():
    p = plan(goals=[goal(month="2030-11")])
    assert tg.horizon(p) == 48 + 1                                          # [R1]
    assert tg.horizon(plan()) == 12
    p2 = plan(goals=[goal(month="2027-03")], one_offs=[dict(id="o", name="O", month="2028-01", amount=1)])
    assert tg.horizon(p2) == 15
    p3 = plan(goals=[goal(month="2027-03")], horizon_end_month="2030-10")
    assert tg.horizon(p3) == 48
    p4 = plan(goals=[goal(month="2027-03", enabled=False)])
    assert tg.horizon(p4) == 12


def test_blocks_truncated_at_goal_date():
    assert tg.blocks(30, 12) == [(0, 0, 12), (1, 12, 12), (2, 24, 6)]
    assert tg.blocks(12, 12) == [(0, 0, 12)]
    assert tg.blocks(13, 6) == [(0, 0, 6), (1, 6, 6), (2, 12, 1)]
    assert tg.blocks(0, 12) == []
