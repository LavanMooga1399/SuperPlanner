"""Rate engine (M8-DESIGN 7; pure): construction, CP-SAT improvement, validator mutations, shortages."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from superplanner.mfg.rate import engine
from superplanner.mfg.rate.construct import matrix_lookup
from superplanner.mfg.rate.model import ChangeoverRule, RateDemand, RateItem, RateLine, RateProblem, Window
from superplanner.mfg.rate.validator import validate

T0 = datetime(2026, 11, 30, 0, 0, tzinfo=UTC)        # Monday


def windows(days: int = 30, start_h: int = 6, end_h: int = 22, weekdays: int = 5) -> tuple[Window, ...]:
    out = []
    for k in range(days):
        d = T0 + timedelta(days=k)
        if d.weekday() < weekdays:
            out.append(Window(d + timedelta(hours=start_h), d + timedelta(hours=end_h)))
    return tuple(out)


def line(rates: dict[str, float], **kw) -> RateLine:
    return RateLine(id="lin_a", code="ASM-01", setup_family="ASM", windows=kw.pop("wins", windows()), rates=rates,
                    **kw)


def item(i: str, key: str, case: float | None = 100, **kw) -> RateItem:
    return RateItem(id=i, part_number=i.upper(), key=key, case_qty=case, **kw)


def problem(ln, items, demands, rules=(), days=30, **kw) -> RateProblem:
    return RateProblem(as_of=T0, horizon_end=T0 + timedelta(days=days), lines=(ln,) if isinstance(ln, RateLine) else
                       tuple(ln), items={i.id: i for i in items}, demands=tuple(demands), changeovers=tuple(rules),
                       time_budget_s=kw.pop("budget", 5.0), workers=1, **kw)


RULES = (ChangeoverRule("ASM", "SYR", "SYR", 30, 50, "changeover"),
         ChangeoverRule("ASM", "*", "*", 90, 300, "changeover"),
         ChangeoverRule("ASM", "SYR", "NDL", 240, 900, "cleaning"),
         ChangeoverRule("ASM", "NDL", "SYR", 240, 900, "cleaning"))


def test_matrix_most_specific():
    assert matrix_lookup(RULES, "ASM", "SYR", "SYR") == {"changeover": (30, 50)}
    assert matrix_lookup(RULES, "ASM", "SYR", "NDL") == {"changeover": (90, 300), "cleaning": (240, 900)}
    assert matrix_lookup(RULES, "OTHER", "SYR", "NDL") == {}


def _dem(i, days, qty, prio=5):
    return [RateDemand(i, (T0 + timedelta(days=d)).date(), qty, prio, "forecast") for d in days]


@pytest.mark.req("M8-RATE-01")
def test_sequence_minimises_changeover_and_blocks_match_matrix():
    # two syringe sizes (same key family SYR) and one needle: SYR-SYR is cheap, crossing SYR<->NDL is expensive
    ln = line({"s3": 1000.0, "s5": 1000.0, "n21": 1000.0}, clearance_minutes=15)
    its = [item("s3", "SYR", target_cover_days=20), item("n21", "NDL", target_cover_days=20),
           item("s5", "SYR", target_cover_days=20)]
    # run-out order alone would alternate s3, n21, s5
    dem = _dem("s3", [2], 8000) + _dem("n21", [3], 8000) + _dem("s5", [4], 8000)
    res = engine.solve(problem(ln, its, dem, RULES, budget=5))
    assert res.validator["ok"], res.validator
    prods = [b for b in res.blocks if b.kind == "production"]
    order = []
    for b in prods:
        if not order or order[-1] != b.item_id:
            order.append(b.item_id)
    # the two syringes are adjacent (one expensive crossing instead of two)
    assert order in (["s3", "s5", "n21"], ["s5", "s3", "n21"], ["n21", "s3", "s5"], ["n21", "s5", "s3"])
    assert res.objective["changeover_cost"] == pytest.approx(50 + 300 + 900)
    # setup blocks between n21 and a syringe: changeover 90 + cleaning 240 + clearance 15 minutes
    kinds = {}
    for b in res.blocks:
        if b.kind in ("changeover", "cleaning", "clearance"):
            kinds[b.kind] = kinds.get(b.kind, 0) + (b.end - b.start).total_seconds() / 60
    assert kinds == {"changeover": 30 + 90, "cleaning": 240, "clearance": 30}


@pytest.mark.req("M8-RATE-02")
def test_demand_above_capacity_gives_capacity_shortage_with_load():
    ln = line({"s3": 500.0}, wins=windows(7))
    its = [item("s3", "SYR")]
    res = engine.solve(problem(ln, its, _dem("s3", [5], 100_000), days=7))
    assert res.validator["ok"], res.validator
    assert res.shortages and res.shortages[0].cause == "RATE_CAPACITY"
    ex = [e for e in res.explanations if e["code"] == "RATE_CAPACITY"]
    assert ex and ex[0]["detail"]["load_pct"] >= 95
    assert res.objective["shortage_unit_days"] > 0


@pytest.mark.req("M8-RATE-03")
def test_min_campaign_hours_with_small_demand_reports_excess():
    ln = line({"s3": 1000.0})
    its = [item("s3", "SYR", campaign_min_hours=8, target_cover_days=0)]
    res = engine.solve(problem(ln, its, _dem("s3", [3], 1500)))
    assert res.validator["ok"], res.validator
    prods = [b for b in res.blocks if b.kind == "production"]
    hours = sum((b.end - b.start).total_seconds() / 3600 for b in prods)
    assert hours == pytest.approx(8.0) and sum(b.qty for b in prods) == pytest.approx(8000)
    assert res.objective["excess_cover_unit_days"] > 0 and not res.shortages


@pytest.mark.req("M8-RATE-04")
def test_periodic_cleaning_inserted_and_validator_ok():
    wins = tuple(Window(T0 + timedelta(days=k), T0 + timedelta(days=k + 1)) for k in range(14))   # 24/7
    ln = line({"s3": 1000.0}, wins=wins, clean_every_hours=72, clean_minutes=120)
    its = [item("s3", "SYR", target_cover_days=30)]
    res = engine.solve(problem(ln, its, _dem("s3", [1, 4, 7, 10, 13], 30_000), days=14))
    assert res.validator["ok"], res.validator
    cleans = [b for b in res.blocks if b.kind == "cleaning"]
    assert cleans and sum((b.end - b.start).total_seconds() / 60 for b in cleans) >= 120
    # never more than 72 production hours without a cleaning
    run = 0.0
    for b in sorted(res.blocks, key=lambda b: b.start):
        if b.kind == "cleaning":
            run = 0.0
        elif b.kind == "production":
            run += (b.end - b.start).total_seconds() / 3600
            assert run <= 72 + 1e-6


@pytest.mark.req("M8-RATE-05")
def test_validator_detects_mutations():
    ln = line({"s3": 1000.0, "n21": 1000.0}, clearance_minutes=15)
    its = [item("s3", "SYR"), item("n21", "NDL")]
    p = problem(ln, its, _dem("s3", [2], 5000) + _dem("n21", [3], 5000), RULES)
    res = engine.solve(p, improve=False)
    assert res.validator["ok"], res.validator
    blocks = res.blocks

    def codes(bl):
        return {v["code"] for v in validate(p, bl)["violations"]}
    prods = [b for b in blocks if b.kind == "production"]
    # overlap: second production starts inside the first
    mut = [replace(b) for b in blocks]
    k = next(i for i, b in enumerate(mut) if b is not None and b.kind == "production" and b.item_id == "n21")
    first = next(b for b in mut if b.kind == "production")
    mut[k] = replace(mut[k], start=first.start + timedelta(minutes=10))
    assert "RATE_V_OVERLAP" in codes(mut)
    # missing changeover: drop all setup blocks
    assert "RATE_V_CHANGEOVER" in codes([b for b in blocks if b.kind == "production"])
    # qty > rate x hours by more than a case
    mut = [replace(b) for b in blocks]
    j = blocks.index(prods[0])
    mut[j] = replace(mut[j], qty=mut[j].qty + 500)
    assert "RATE_V_QTY" in codes(mut)
    # outside a window, ineligible item, campaign max
    mut = [replace(b) for b in blocks]
    mut[j] = replace(mut[j], start=mut[j].start - timedelta(hours=10), qty=mut[j].qty + 10_000)
    assert "RATE_V_WINDOW" in codes(mut)
    mut = [replace(b) for b in blocks]
    mut[j] = replace(mut[j], item_id="zzz")
    assert "RATE_V_ELIGIBILITY" in codes(mut)
    p2 = replace(p, items={**p.items, "s3": replace(p.items["s3"], campaign_max_hours=1.0)})
    assert "RATE_V_CAMPAIGN_MAX" in {v["code"] for v in validate(p2, blocks)["violations"]}
    # firm block removed
    p3 = replace(p, firm_blocks=(replace(prods[0], firm=True),))
    assert "RATE_V_FIRM" in {v["code"] for v in validate(p3, blocks[1:])["violations"]}


def test_no_line_and_split_and_firm_kept():
    l1 = line({"s3": 1000.0}, wins=windows(7))
    l2 = RateLine(id="lin_b", code="ASM-02", setup_family="ASM", windows=windows(7), rates={"s3": 1000.0})
    its = [item("s3", "SYR"), item("x9", "X")]
    dem = _dem("s3", [1, 2, 3, 4], 30_000) + _dem("x9", [2], 100)
    res = engine.solve(problem((l1, l2), its, dem, days=7))
    assert res.validator["ok"], res.validator
    assert {b.line_id for b in res.blocks if b.kind == "production"} == {"lin_a", "lin_b"}
    assert any(e["code"] == "RATE_SPLIT" for e in res.explanations)
    assert any(s.cause == "RATE_NO_LINE" and s.item_id == "x9" for s in res.shortages)
    firm = [replace(b, firm=True) for b in res.blocks if b.line_id == "lin_a"][:2]
    res2 = engine.solve(problem((l1, l2), its, dem, days=7, firm_blocks=tuple(firm)))
    assert res2.validator["ok"], res2.validator
    for f in firm:
        assert any(b.start == f.start and b.end == f.end and b.item_id == f.item_id for b in res2.blocks)


def test_determinism():
    ln = line({"s3": 1000.0, "s5": 800.0, "n21": 1200.0})
    its = [item("s3", "SYR"), item("s5", "SYR"), item("n21", "NDL")]
    dem = _dem("s3", [2, 9, 16], 9000) + _dem("n21", [3, 10], 7000) + _dem("s5", [4, 11, 18], 6000)
    a = engine.solve(problem(ln, its, dem, RULES, budget=0), improve=False)
    b = engine.solve(problem(ln, its, dem, RULES, budget=0), improve=False)
    assert [(x.kind, x.item_id, x.start, x.qty) for x in a.blocks] == [(x.kind, x.item_id, x.start, x.qty)
                                                                       for x in b.blocks]
    assert date(2026, 11, 30) <= min(x.prod_date for x in a.blocks)


def test_publish_started_wo_never_duplicated():
    from superplanner.mfg.rate.publish import Group, PrevWo, decide

    d = date(2026, 12, 1)
    g = [Group(("lin_a", "s3", d), "lin_a", "s3", d, d, 5000.0, ["b1"]),
         Group(("lin_b", "s3", d), "lin_b", "s3", d, d, 3000.0, ["b2"])]
    started = PrevWo("w1", "s3", d, 4800.0, True, "lin_a")        # started, quantity differs
    unstarted = PrevWo("w2", "s3", d, 2999.0, False, "lin_b")     # quantity differs -> cancelled, recreated
    dec = decide(g, [unstarted, started])
    assert [x.key for x in dec.create] == [("lin_b", "s3", d)]
    assert [w.id for w, _g in dec.keep] == ["w1"] and [w.id for w in dec.cancel] == ["w2"]
    assert dec.skipped == [{"wo_id": "w1", "item_id": "s3", "due": d, "planned_qty": 5000.0, "wo_qty": 4800.0}]


def test_cleaning_interval_counts_firm_production():
    """Demo review: firm blocks with 70 h of production since the last cleaning; the construction must clean
    within the next 2 h of production (validator: run hours <= 72)."""
    from superplanner.mfg.rate.model import RateBlock

    wins = tuple(Window(T0 + timedelta(days=k), T0 + timedelta(days=k + 1)) for k in range(14))
    ln = line({"s3": 1000.0}, wins=wins, clean_every_hours=72, clean_minutes=120)
    firm = []
    t = T0
    for h in (24, 24, 22):                         # 70 h, split at midnight like real blocks
        firm.append(RateBlock("lin_a", "production", "s3", 1, t, t + timedelta(hours=h), qty=1000.0 * h,
                              prod_date=t.date(), firm=True))
        t += timedelta(hours=24)
    p = problem(ln, [item("s3", "SYR", target_cover_days=10)], _dem("s3", [4, 7, 10], 40_000), days=14,
                firm_blocks=tuple(firm))
    res = engine.solve(p)
    assert res.validator["ok"], res.validator
    first_clean = min(b.start for b in res.blocks if b.kind == "cleaning")
    prod_before = sum((b.end - b.start).total_seconds() / 3600 for b in res.blocks
                      if b.kind == "production" and b.start < first_clean)
    assert prod_before <= 72 + 1e-6
