"""T-M14 determinism and T-M15 invariants (8.15), on the Kavach-scale scenario and 500 seeded random plants:

- every requirement's peg sum == its qty (fully pegged, P7); every supply's pegged <= qty; planned qty >= residuals
- conservation in pegging: per item, sum of pegs == sum of requirement qty == sum of supply pegged qty
- planned-component requirements point at an existing parent make supply that lists them (pegging walks)
- no negative projected stock (`balance_planned`) except on items with a reported shortage (`MRP_SHORTAGE`),
  and never deeper than the item's short quantity
- determinism: same inputs -> byte-identical canonical JSON (also across `PYTHONHASHSEED`s, in subprocesses)
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from mrp_helpers import AS_OF, Plant, Snap
from mrp_kavach_helpers import kavach_snapshot
from superplanner.mfg.mrp import MrpParams, canonical_json, run_mrp

EPS = 1e-6
HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]


def random_snap(seed: int) -> tuple[Snap, dict]:
    rng = random.Random(seed)
    p = Plant(horizon=120)
    n_buy, n_make = rng.randint(3, 8), rng.randint(2, 6)
    buys = [f"B{i}" for i in range(n_buy)]
    makes = [f"M{i}" for i in range(n_make)]
    for b in buys:
        kw: dict = {"lead_time_days": rng.choice([0, 3, 10, 30, 90]), "receiving_days": rng.choice([0, 0, 2])}
        rule = rng.choice(["lot_for_lot", "lot_for_lot", "fixed", "period"])
        if rule == "fixed":
            kw.update(lot_rule="fixed", fixed_lot_qty=rng.choice([5, 12, 50]))
        elif rule == "period":
            kw.update(lot_rule="period", lot_period_days=rng.choice([3, 7, 30]))
        if rng.random() < 0.3:
            kw.update(min_order_qty=rng.choice([10, 100]), order_multiple=rng.choice([0, 5, 25]))
        if rng.random() < 0.2:
            kw["safety_stock"] = rng.choice([2, 10])
        if rng.random() < 0.2:
            kw["lot_controlled"] = True
        p.item(b, "buy", **kw)
    for i, m in enumerate(makes):
        kw = {"serialized": rng.random() < 0.3}
        if rng.random() < 0.5:
            kw["lead_time_days"] = rng.choice([0, 1, 3, 8])
        p.item(m, "make", **kw)
    # BOMs: make i uses buys and makes with a higher index (acyclic), sometimes an alternate group
    for i, m in enumerate(makes):
        kids = rng.sample(buys, k=min(len(buys), rng.randint(1, 3)))
        lines = [(k, rng.choice([1, 2, 0.5, 3])) for k in kids]
        if i + 1 < len(makes) and rng.random() < 0.6:
            lines.append((rng.choice(makes[i + 1:]), rng.choice([1, 2])))
        spare = [x for x in buys if x not in kids]
        if spare and rng.random() < 0.35:
            a, b = lines[0][0], spare[0]
            lines[0] = (a, 1, {"alt_group": "G", "alt_priority": 1})
            lines.append((b, rng.choice([1, 2]), {"alt_group": "G", "alt_priority": 2}))
        p.bom(m, lines)
        if "lead_time_days" not in p.b.b["items"][-n_make + i] and rng.random() < 0.8:
            p.routing(m, [{"seq": 10, "setup_minutes": rng.choice([0, 60]), "run_minutes": rng.choice([5, 30, 120])},
                          {"seq": 20, "run_minutes": 10, "yield_pct": rng.choice([100, 95])}])
    ds = p.dataset()
    s = Snap(ds)
    for b in buys:
        if rng.random() < 0.6:
            lot = ds.items_by_pn[b].lot_controlled
            s.stock(b, float(rng.randint(1, 60)), lot="L" + b if lot else None,
                    expires=AS_OF + timedelta(days=rng.randint(-5, 60)) if lot else None)
        for k in range(rng.randint(0, 2)):
            s.schedule(b, float(rng.randint(5, 50)), AS_OF + timedelta(days=rng.randint(-10, 80)),
                       number=f"PO-{b}-{k}", doc_type=rng.choice(["po", "po", "pr"]))
    serial = 1
    for k in range(rng.randint(1, 6)):
        it = rng.choice(makes + buys[:1])
        q = rng.randint(1, 12)
        ser = None
        if ds.items_by_pn[it].serialized:
            ser = (serial, serial + q - 1)
            serial += q
        s.dem(it, float(q), AS_OF + timedelta(days=rng.randint(-3, 100)), priority=rng.randint(1, 9),
              number=f"DO-{k:02d}", serials=ser)
    if rng.random() < 0.5 and makes:
        m = rng.choice(makes)
        kid = rng.choice(buys)
        w = s.wo(m, float(rng.randint(1, 5)), AS_OF + timedelta(days=rng.randint(-3, 10)),
                 AS_OF + timedelta(days=rng.randint(11, 30)), [(kid, float(rng.randint(1, 10)))],
                 status=rng.choice(["planned", "released"]))
        if s.balances and rng.random() < 0.5:
            bal = next((b for b in s.balances if b.item_id == ds.items_by_pn[kid].id), None)
            if bal is not None:
                s.reserve(w.components[0].component_id, bal.id, min(bal.qty_on_hand, w.components[0].open_qty))
    params = {"allocation": rng.choice(["priority", "due_date"]), "alternates": rng.choice(["never", "when_short"])}
    return s, params


def check_invariants(r) -> None:
    short_items = {e.item_id for e in r.exceptions if e.code == "MRP_SHORTAGE"}
    plans = {p.item_id: p for p in r.items}
    for p in r.items:
        sups = {s.node: s for s in p.supplies}
        reqs = {q.node: q for q in p.requirements}
        assert len(sups) == len(p.supplies) and not (set(sups) & set(reqs)), "node numbers unique per item"
        pegged = {n: 0.0 for n in sups}
        for q in p.requirements:
            tot = sum(pg.qty for pg in q.pegs)
            assert abs(tot - q.qty) < 1e-5, (p.part_number, q.node, tot, q.qty)
            for pg in q.pegs:
                assert pg.qty > 0 and pg.supply_node in sups and pg.supply_item_id == p.item_id
                pegged[pg.supply_node] += pg.qty
            if q.kind in ("planned_component", "wo_component") and q.source.node is not None:
                parent = plans[q.source.item_id]
                ps = next(s for s in parent.supplies if s.node == q.source.node)
                assert (p.item_id, q.node) in ps.component_nodes
        for n, s in sups.items():
            assert abs(pegged[n] - s.pegged_qty) < 1e-5
            assert s.pegged_qty <= s.qty + 1e-5, (p.part_number, s.node)
        # projected stock
        if p.part_number and p.item_id not in short_items:
            assert all(e.balance_planned >= -1e-5 for e in p.timeline), (p.part_number, p.timeline)
        else:
            assert p.stats.min_balance >= -p.stats.short_qty - 1e-5
    for po in r.planned_orders:
        pl = plans[po.item_id]
        s = next(x for x in pl.supplies if x.node == po.supply_node)
        assert s.kind == "planned" and s.planned_no == po.planned_no and po.qty + 1e-9 >= s.pegged_qty
        assert po.start_date <= po.need_date
    assert [p.planned_no for p in r.planned_orders] == list(range(1, len(r.planned_orders) + 1))


@pytest.mark.parametrize("chunk", range(10))
def test_invariants_on_random_plants(chunk):
    for seed in range(chunk * 50, chunk * 50 + 50):
        s, params = random_snap(seed)
        r = s.run(**params)
        check_invariants(r)
        assert canonical_json(r) == canonical_json(s.run(**params)), seed


@pytest.fixture(scope="module")
def kavach_result():
    snap = kavach_snapshot()
    return snap, run_mrp(snap, MrpParams())


def test_invariants_on_kavach(kavach_result):
    _snap, r = kavach_result
    check_invariants(r)
    assert r.summary.demand_lines == 7 and r.summary.planned_make > 50 and r.summary.planned_buy > 300


def test_kavach_intended_shape(kavach_result):
    """13.3 shapes that do not depend on the (A-owned, not yet pinned) sample stock: ECO split of DO-KV-002/10,
    DOC-PACK-B only for serials >= 126, past-due PO, expiring coating lot, reduce/cancel on PO-KV-0105."""
    snap, r = kavach_result
    ds = snap.dataset
    tpu = ds.items_by_pn["KV-TPU-1000"].id
    segs = sorted((p.segment.serial_from, p.segment.serial_to) for p in r.planned_orders
                  if p.item_id == tpu and p.segment)
    assert (121, 125) in segs and (126, 135) in segs
    pb = r.item(ds.items_by_pn["KV-DOC-PACK-B"].id)
    # only the 126-135 TPU order needs it: ceil(10 / 0.96 final-test yield) = 11 (M1 4.4)
    assert pb is not None and [q.qty for q in pb.requirements] == [11]
    parent = next(p for p in r.planned_orders if p.supply_node == pb.requirements[0].source.node
                  and p.item_id == tpu)
    assert (parent.segment.serial_from, parent.segment.serial_to) == (126, 135)
    by = {(e.code, e.subject.label) for e in r.exceptions}
    assert any(c == "MRP_PAST_DUE_SUPPLY" and lbl.startswith("PO-KV-0102") for c, lbl in by)
    coat = r.item(ds.items_by_pn["KV-COAT-UR"].id)
    lot = next(s for s in coat.supplies if s.ref.label.endswith("L-2610"))
    assert (("MRP_EXPIRING_STOCK", "L-2610") in by) == (lot.pegged_qty < lot.qty - 1e-6)
    assert all(s.expires_on is None or pg_need < s.expires_on
               for q in coat.requirements for pg in q.pegs
               for s in coat.supplies if s.node == pg.supply_node
               for pg_need in [max(q.need_date, snap.as_of)])
    assert any(c in ("MRP_REDUCE", "MRP_CANCEL") and lbl.startswith("PO-KV-0105") for c, lbl in by)
    late = {d.label: d for d in r.demand if d.status == "late"}
    assert "DO-KV-004/10" in late and late["DO-KV-004/10"].limiting[0].part_number == "KV-TPU-1000"


def test_kavach_deterministic_across_hash_seeds(kavach_result, tmp_path):
    """T-M14: two runs in-process + two subprocesses with different PYTHONHASHSEEDs -> identical bytes."""
    snap, r = kavach_result
    mine = canonical_json(r)
    assert canonical_json(run_mrp(kavach_snapshot(), MrpParams())) == mine
    code = ("import sys, hashlib; sys.path[:0] = [%r, %r]\n"
            "from mrp_kavach_helpers import kavach_snapshot\n"
            "from superplanner.mfg.mrp import MrpParams, canonical_json, run_mrp\n"
            "print(hashlib.sha256(canonical_json(run_mrp(kavach_snapshot(), MrpParams()))).hexdigest())"
            % (str(BACKEND), str(HERE)))
    import hashlib
    want = hashlib.sha256(mine).hexdigest()
    for seed in ("1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300,
                             cwd=str(BACKEND))
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == want, seed


def test_engine_layering():
    """`superplanner.mfg.mrp` imports neither the API / DB layers nor the scheduling engine."""
    code = ("import sys, json; import superplanner.mfg.mrp; "
            "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'sqlalchemy') "
            "or m.startswith(('superplanner.api', 'superplanner.engine')))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(BACKEND), timeout=120,
                         env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
