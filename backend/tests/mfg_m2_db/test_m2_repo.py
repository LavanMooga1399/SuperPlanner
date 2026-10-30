"""A2/A3 (M2-DESIGN 9.5, 17.2): `load_mrp_snapshot` equals the pure snapshot of the same bundle and is bounded;
`inputs_token`; lockers and the savepoint create pattern under concurrent threads; number series."""

from __future__ import annotations

import dataclasses
import threading
from datetime import date

import pytest
from sqlalchemy import func, select

from mfgdb_helpers import count_statements
from mfgm2_helpers import write_all
from superplanner.api.db.ownership import owner_scope
from superplanner.api.mfg import repo_m2
from superplanner.api.mfg.db_models_m2 import MfgInvBalanceRow, MfgLotRow, MfgNumberSeriesRow
from superplanner.mfg import fingerprint, samples
from superplanner.mfg.dataset import mrp_inputs

A = date(2026, 11, 2)


def _norm(parts: dict, ids: dict[str, str] | None) -> dict:
    def m(v):
        if isinstance(v, str) and ids is not None and v in ids:
            return ids[v]
        if isinstance(v, tuple):
            return tuple(m(x) for x in v)
        return v

    out = {}
    for k in ("balances", "reservations", "schedules", "demand", "work_orders"):
        rows = []
        for r in parts[k]:
            d = {f.name: m(getattr(r, f.name)) for f in dataclasses.fields(r)}
            if "components" in d:
                d["components"] = tuple(sorted(tuple(m(x) for x in c) for c in d["components"]))
            rows.append(tuple(sorted(d.items())))
        out[k] = sorted(rows, key=repr)
    out["lots"] = sorted(((m(i), x.lot_code, x.expires_on, x.on_hand) for i, x in parts["lots"].items()), key=repr)
    out["holidays"] = parts["holidays"]
    return out


@pytest.fixture(scope="module")
def kavach_db(db_url_factory_module):
    from mfgdb_helpers import open_db

    db = open_db(db_url_factory_module("mfgm2db"))
    pure = samples.mrp_state("kavach", A)
    with owner_scope("usr_a"), db.write() as s:
        ids = write_all(s, pure)
    try:
        yield db, pure, ids
    finally:
        db.dispose()


def test_load_mrp_snapshot_equals_the_pure_snapshot(kavach_db):
    db, pure, ids = kavach_db
    with owner_scope("usr_a"), repo_m2.snapshot_tx(db) as s:
        with count_statements(db) as c:
            snap = repo_m2.load_mrp_snapshot(s, A)
        assert c.count <= 32, c.count
    assert fingerprint(snap.dataset) == fingerprint(pure)
    assert _norm({f.name: getattr(snap, f.name) for f in dataclasses.fields(snap)}, None) == \
        _norm(mrp_inputs(pure, A), ids)
    assert len(snap.balances) > 1000 and len(snap.demand) == 7 and len(snap.work_orders) == 3
    assert snap.reservations and all(b.location_active for b in snap.balances)


def test_mrp_result_from_db_equals_pure(kavach_db):
    from superplanner.mfg.mrp import MrpParams, MrpSnapshot, run_mrp

    db, pure, _ids = kavach_db
    with owner_scope("usr_a"), repo_m2.snapshot_tx(db) as s:
        snap = repo_m2.load_mrp_snapshot(s, A)
    a = run_mrp(snap, MrpParams())
    b = run_mrp(MrpSnapshot(as_of=A, dataset=pure, **mrp_inputs(pure, A)), MrpParams())
    assert a.summary == b.summary
    assert [(d.order_number, d.line_no, d.projected_date) for d in a.demand] == \
        [(d.order_number, d.line_no, d.projected_date) for d in b.demand]


def test_inputs_token_is_one_statement(kavach_db):
    db, _pure, _ids = kavach_db
    with owner_scope("usr_a"), db.read() as s:
        with count_statements(db) as c:
            tok = repo_m2.inputs_token(s)
        assert c.count == 1
    assert set(tok) == {"seq", "purchase_docs", "demand_orders", "work_orders", "data_version", "lots_updated",
                        "lots_n", "purchase_docs_n", "purchase_lines_n", "purchase_schedules_n", "demand_orders_n",
                        "demand_lines_n", "work_orders_n", "wo_components_n", "reservations_n"}
    assert tok["lots_n"] > 0 and tok["work_orders_n"] == 3


def test_concurrent_lot_balance_and_series_creation_is_race_free(kavach_db):
    db, pure, ids = kavach_db
    item = ids[pure.items_by_pn["KV-COAT-UR"].id]
    loc = ids[pure.locations_by_code["FG"].id]
    errors: list[BaseException] = []
    numbers: list[str] = []
    barrier = threading.Barrier(6)

    def work() -> None:
        try:
            with owner_scope("usr_a"), db.write() as s:
                barrier.wait()
                lots = repo_m2.lock_or_create_lots(s, {(item, "RACE-1"): {"received_on": A}})
                lot_id = lots[(item, "RACE-1")].id
                repo_m2.lock_or_create_balances(s, [(item, loc, "RACE-1")], {(item, "RACE-1"): lot_id})
                numbers.append(repo_m2.next_number(s, "WO", lambda n: False))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    ts = [threading.Thread(target=work) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    assert len(set(numbers)) == 6 and all(n.startswith("WO-") for n in numbers)
    with owner_scope("usr_a"), db.read() as s:
        assert s.execute(select(func.count()).select_from(MfgLotRow).where(MfgLotRow.lot_code == "RACE-1")).scalar() == 1
        assert s.execute(select(func.count()).select_from(MfgInvBalanceRow).where(
            MfgInvBalanceRow.lot_key == "RACE-1")).scalar() == 1
        assert s.execute(select(func.count()).select_from(MfgNumberSeriesRow)).scalar() == 1


def test_next_number_skips_taken_numbers(kavach_db):
    db, _p, _i = kavach_db
    with owner_scope("usr_b"), db.write() as s:
        taken = {"PR-000001", "PR-000002"}
        assert repo_m2.next_number(s, "PR", taken.__contains__) == "PR-000003"
        assert repo_m2.next_number(s, "PR", taken.__contains__) == "PR-000004"


def test_lockers_sort_ids(kavach_db):
    db, pure, ids = kavach_db
    from superplanner.api.mfg.db_models_m2 import MfgPurchaseDocRow

    doc_ids = sorted(ids[d] for d in pure.txn.purchase_docs)
    with owner_scope("usr_a"), db.write() as s:
        rows = repo_m2.lock_docs(s, MfgPurchaseDocRow, list(reversed(doc_ids)))
        assert [r.id for r in rows] == doc_ids
