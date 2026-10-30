"""Repository loaders (M1-DESIGN 6.4; PLAN-M1 A4-1..A4-3) on the Kavach sample written as ORM rows: equality with
the pure indexes, statement counts, `lazy="raise"`, owner isolation."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError

from mfgdb_helpers import count_statements, open_db, write_dataset
from superplanner.api.db.ownership import owner_scope
from superplanner.api.errors import ApiError
from superplanner.api.mfg import repo
from superplanner.api.mfg.db_models import MfgBomRow, MfgItemRow, MfgOperationRow
from superplanner.mfg import (BomIndex, ParentIndex, bundle_to_dataset, explode, fingerprint, run_health_check,
                              samples, where_used)

DATES = [date(2026, 2, 1), date(2026, 11, 2), date(2027, 6, 30)]
CAP = "KV-CAP-0402-100N"


@pytest.fixture(scope="module")
def kavach(db_url_factory_module):
    db = open_db(db_url_factory_module("mfgrepo"))
    pure = bundle_to_dataset(samples.build("kavach"))
    with owner_scope("usr_a"), db.write() as s:
        ids = write_dataset(s, pure)
    try:
        yield db, pure, ids
    finally:
        db.dispose()


def test_load_dataset_equals_the_pure_dataset(kavach):
    db, pure, _ = kavach
    with owner_scope("usr_a"), db.read() as s:
        with count_statements(db) as c:
            ds = repo.load_dataset(s)
        assert c.count <= 25   # M3-DESIGN 14.1: +3 master tables
    assert fingerprint(ds) == fingerprint(pure)
    assert run_health_check(ds, date(2026, 11, 2), 90).by_code == run_health_check(pure, date(2026, 11, 2), 90).by_code
    some = next(iter(ds.calendar_exceptions.values()))
    assert some.start.utcoffset().total_seconds() == 5.5 * 3600            # plant offset
    assert all(i.created_at.tzinfo is not None for i in ds.items.values())


@pytest.mark.parametrize("on", DATES)
def test_bom_index_down_equals_from_dataset_and_is_bounded(kavach, on):
    db, pure, ids = kavach
    root = ids[pure.items_by_pn["KV-TPU-1000"].id]
    with owner_scope("usr_a"), db.read() as s:
        ds = repo.load_dataset(s)
        with count_statements(db) as c:
            idx = repo.load_bom_index_down(s, root, on, None)
    a = explode(idx, root).model_dump()
    b = explode(BomIndex.from_dataset(ds, on), root).model_dump()
    assert a == b and a["totals"]["rows"] > 2000
    levels = a["totals"]["max_level"]
    assert levels == 4 and c.count <= 3 * (levels + 1) + 3, c.count
    assert explode(idx, root, mode="summarized").model_dump() == \
        explode(BomIndex.from_dataset(ds, on), root, mode="summarized").model_dump()


def test_bom_index_before_effectivity_has_no_children(kavach):
    db, pure, ids = kavach
    root = ids[pure.items_by_pn["KV-TPU-1000"].id]
    with owner_scope("usr_a"), db.read() as s:
        e = explode(repo.load_bom_index_down(s, root, date(2025, 12, 31), None), root)
    assert e.totals.rows == 1 and [w.code for w in e.warnings] == ["MFG_NO_EFFECTIVE_BOM"]


@pytest.mark.parametrize("include,on", [("effective", date(2026, 11, 2)), ("effective", None), ("all", None)])
def test_parent_index_equals_from_dataset_and_is_bounded(kavach, include, on):
    db, pure, ids = kavach
    cap = ids[pure.items_by_pn[CAP].id]
    with owner_scope("usr_a"), db.read() as s:
        ds = repo.load_dataset(s)
        with count_statements(db) as c:
            pidx = repo.load_parent_index(s, cap, on, include)
    a = where_used(pidx, cap, mode="indented").model_dump()
    b = where_used(ParentIndex.from_dataset(ds, on, include), cap, mode="indented").model_dump()
    assert a == b
    levels = max(r["level"] for r in a["rows"])
    assert levels == 3 and c.count <= 3 * levels + 2, c.count
    assert where_used(pidx, cap).model_dump() == where_used(ParentIndex.from_dataset(ds, on, include), cap).model_dump()
    assert len({r["item_id"] for r in a["rows"] if r["level"] == 1}) >= 10


def test_bom_edge_list_is_one_statement(kavach):
    db, pure, _ = kavach
    with owner_scope("usr_a"), db.read() as s:
        ds = repo.load_dataset(s)
        with count_statements(db) as c:
            edges = repo.bom_edge_list(s)
    from superplanner.mfg import bom_edges

    assert c.count == 1 and sorted(edges) == sorted(bom_edges(ds))


def test_relationships_raise_on_lazy_load(kavach):
    db, _, _ = kavach
    with owner_scope("usr_a"), db.read() as s:
        bom = s.execute(select(MfgBomRow).limit(1)).scalars().one()
        with pytest.raises(InvalidRequestError):
            _ = bom.lines
        op = s.execute(select(MfgOperationRow).limit(1)).scalars().one()
        with pytest.raises(InvalidRequestError):
            _ = op.tools


def test_to_record_round_trip(kavach):
    db, pure, ids = kavach
    with owner_scope("usr_a"), db.read() as s:
        row = repo.get_row(s, MfgItemRow, ids[pure.items_by_pn[CAP].id], what="Item")
        rec = repo.to_record(row, used_in_count=3)
    assert rec.part_number == CAP and rec.used_in_count == 3 and rec.created_at.tzinfo is not None
    assert type(rec).model_validate(rec.model_dump()) == rec


def test_owner_isolation_at_repository_level(kavach):
    db, pure, ids = kavach
    root = ids[pure.items_by_pn["KV-TPU-1000"].id]
    cap = ids[pure.items_by_pn[CAP].id]
    with owner_scope("usr_b"), db.read() as s:
        ds = repo.load_dataset(s)
        assert ds.plant.id is None and not any([ds.items, ds.boms, ds.routings, ds.groups, ds.lines, ds.operators,
                                                ds.skills, ds.tool_pools, ds.shift_templates, ds.shift_assignments,
                                                ds.calendar_exceptions])
        assert repo.bom_edge_list(s) == []
        assert repo.plant_or_default(s).id is None
        for fn in (lambda: repo.load_bom_index_down(s, root, date(2026, 11, 2), None),
                   lambda: repo.load_parent_index(s, cap, None, "all"),
                   lambda: repo.get_row(s, MfgItemRow, cap, what="Item")):
            with pytest.raises(ApiError) as exc:
                fn()
            assert exc.value.status == 404
