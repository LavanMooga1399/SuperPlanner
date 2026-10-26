"""Regression (review F1): `repo.load_bom_index_down` must expand an item that is first reached as an alternate and
later as a primary. The DB loader's explosion (indented and summarized) must equal the one over
`BomIndex.from_dataset` - for the reviewer's shape and for randomly generated structures."""

from __future__ import annotations

import random
from datetime import date

import pytest

from mfgdb_helpers import open_db, write_dataset
from superplanner.api.db.ownership import owner_scope
from superplanner.api.mfg import repo
from superplanner.mfg import BomIndex, bundle_to_dataset, explode
from superplanner.mfg.samples.common import Builder, line

ON = date(2026, 11, 2)


def _compare(db_url: str, b: Builder, roots: list[str], on: date = ON, serials: tuple[int | None, ...] = (None,)) \
        -> None:
    pure = bundle_to_dataset(b.b)
    db = open_db(db_url)
    try:
        with owner_scope("usr_a"), db.write() as s:
            ids = write_dataset(s, pure)
        with owner_scope("usr_a"), db.read() as s:
            ds = repo.load_dataset(s)
            for pn in roots:
                root = ids[pure.items_by_pn[pn].id]
                for serial in serials:
                    idx = repo.load_bom_index_down(s, root, on, serial)
                    ref = BomIndex.from_dataset(ds, on, serial)
                    for mode in ("indented", "summarized"):
                        a = explode(idx, root, mode=mode).model_dump()
                        e = explode(ref, root, mode=mode).model_dump()
                        assert a == e, (pn, serial, mode)
    finally:
        db.dispose()


def _alt_then_primary() -> Builder:
    """Probe p1_alt: A = {G: Y (prio 1), X (prio 2); P}; P = {X}; X = {L}. X is first loaded at level 1 as an
    alternate, then reached at level 2 as P's primary."""
    b = Builder()
    b.plant("P")
    for pn, mb in (("A", "make"), ("X", "make"), ("P", "make"), ("L", "buy"), ("Y", "buy")):
        b.item(pn, mb, pn, **({"lead_time_days": 1} if mb == "buy" else {}))
    b.bom("X", [line(10, "L", 2)])
    b.bom("P", [line(10, "X", 1)])
    b.bom("A", [line(10, "Y", 1, alt_group="G", alt_priority=1), line(11, "X", 1, alt_group="G", alt_priority=2),
                line(20, "P", 1)])
    return b


def test_alternate_then_primary_is_expanded(db_url_factory):
    b = _alt_then_primary()
    _compare(db_url_factory("bfsalt"), b, ["A"])
    pure = bundle_to_dataset(b.b)
    db = open_db(db_url_factory("bfsalt2"))
    try:
        with owner_scope("usr_a"), db.write() as s:
            ids = write_dataset(s, pure)
        root = ids[pure.items_by_pn["A"].id]
        with owner_scope("usr_a"), db.read() as s:
            e = explode(repo.load_bom_index_down(s, root, ON, None), root)
        assert [(r.level, r.part_number, r.extended_qty) for r in e.rows] == \
            [(0, "A", 1.0), (1, "Y", 1.0), (1, "P", 1.0), (2, "X", 1.0), (3, "L", 2.0)]
        assert e.warnings == []
    finally:
        db.dispose()


def _random_structure(rng: random.Random) -> tuple[Builder, list[str]]:
    b = Builder()
    b.plant("P")
    n = rng.randint(6, 16)
    kinds = ["make"] * 3 + ["phantom"] + ["buy"] * 2
    pns = [f"I{i:02d}" for i in range(n)]
    mb = {pn: rng.choice(kinds) for pn in pns}
    mb[pns[0]] = "make"
    for pn in pns:
        b.item(pn, mb[pn], pn, **({"lead_time_days": 1} if mb[pn] == "buy" else {}))
    for i, pn in enumerate(pns):
        if mb[pn] == "buy" or i == n - 1 or rng.random() < 0.1:
            continue
        later = pns[i + 1:]                              # children only later in the order: acyclic
        versions = rng.choice([1, 1, 1, 2])
        for v in range(1, versions + 1):
            children = rng.sample(later, k=min(len(later), rng.randint(1, 4)))
            lines, find = [], 10
            while children:
                if len(children) >= 2 and rng.random() < 0.4:
                    k = min(len(children), rng.randint(2, 3))
                    grp, children = children[:k], children[k:]
                    prios = rng.sample(range(1, 5), k=k)
                    if 1 not in prios and rng.random() < 0.8:     # else: no primary (explode takes the lowest)
                        prios[0] = 1
                    name = f"G{find}"
                    for c, p in zip(grp, prios):
                        lines.append(line(find, c, rng.choice([1, 2, 0.5]), alt_group=name, alt_priority=p))
                        find += 1
                else:
                    lines.append(line(find, children.pop(), rng.choice([1, 2, 3])))
                    find += 1
            status = rng.choice(["released", "released", "released", "draft"])
            eff = rng.choice([None, date(2026, 1, 1), date(2027, 1, 1)]) if versions > 1 else None
            b.bom(pn, lines, version=v, status=status, effective_from=eff)
    return b, pns[:3]


@pytest.mark.parametrize("seed", range(40))
def test_random_structures_match_from_dataset(db_url_factory, seed):
    rng = random.Random(seed)
    b, roots = _random_structure(rng)
    _compare(db_url_factory(f"bfsrnd{seed}"), b, roots)
