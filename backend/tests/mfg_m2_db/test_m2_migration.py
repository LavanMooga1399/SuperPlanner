"""A1 (M2-DESIGN 9, 16.2): `0003_mfg -> 0004_mfg_m2` keeps data, `compare_metadata` is empty, the head is
`0004_mfg_m2`, and `downgrade 0003_mfg` removes exactly the 22 tables and the 9 added columns. Schema rules of 9.1:
names <= 63 characters, owner-led and FK-led indexes, no server defaults, CHECK backstops fire."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from superplanner import migrate
from superplanner.api.db import load_all_models
from superplanner.api.mfg.db_models_m2 import ALL_MFG_MODELS, M2_MODELS, M2_TABLES, MFG_ACCESS_MODELS

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
ITEM_COLS = {"external_ref", "standard_cost", "lot_controlled", "lot_period_days"}
PLANT_COLS = {"mrp_workdays", "mrp_day_minutes", "mrp_defer_tolerance_days", "mrp_release_window_days",
              "over_receipt_pct"}


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _columns(url: str, table: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return {c["name"] for c in sa.inspect(eng).get_columns(table)}
    finally:
        eng.dispose()


def _diffs(url: str) -> list:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return list(compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}),
                                         load_all_models()))
    finally:
        eng.dispose()


def test_head_and_table_lists():
    assert migrate.HEAD == "0006_mfg_m4"   # M3 and M4 on top (M3-DESIGN 10, M4-DESIGN 3.2)
    assert len(M2_TABLES) == 22 and len(M2_MODELS) == 21 and len(MFG_ACCESS_MODELS) == 1
    assert [m.__tablename__ for m in ALL_MFG_MODELS][-21:] == [
        "mfg_locations", "mfg_suppliers", "mfg_item_suppliers", "mfg_lots", "mfg_purchase_docs", "mfg_purchase_lines",
        "mfg_purchase_schedules", "mfg_demand_orders", "mfg_demand_lines", "mfg_work_orders", "mfg_wo_components",
        "mfg_inv_balances", "mfg_inv_reservations", "mfg_inv_postings", "mfg_inv_transactions", "mfg_number_series",
        "mfg_mrp_runs", "mfg_mrp_planned_orders", "mfg_mrp_exceptions", "mfg_mrp_item_results",
        "mfg_mrp_demand_results"]


def test_upgrade_from_0003_keeps_data_and_downgrade_removes_exactly_m2(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0003_mfg")
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            c.execute(sa.text("INSERT INTO mfg_plant (id, owner_id, name, utc_offset, planning_horizon_days, currency, "
                              "attributes, data_version, row_version, created_at, updated_at) VALUES ('plt_x', "
                              "'usr_local', 'P', '+05:30', 90, 'INR', '{}', 3, 1, :t, :t)"), {"t": NOW})
            c.execute(sa.text("INSERT INTO mfg_items (id, owner_id, part_number, revision, description, uom, make_buy, "
                              "receiving_days, lot_rule, min_order_qty, order_multiple, safety_stock, serialized, "
                              "handling_note, attributes, active, row_version, created_at, updated_at) VALUES "
                              "('itm_x', 'usr_local', 'A-1', 'A', '', 'EA', 'buy', 0, 'lot_for_lot', 0, 0, 0, false, '',"
                              " '{}', true, 1, :t, :t)"), {"t": NOW})
    finally:
        eng.dispose()
    t3 = _tables(url)
    migrate.run_alembic_upgrade(url, "0004_mfg_m2")             # M3 (0005) adds more on top: see tests/api_mfg_m3
    assert _tables(url) - t3 == set(M2_TABLES)
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            row = c.execute(sa.text("SELECT mrp_workdays, mrp_day_minutes, mrp_defer_tolerance_days, "
                                    "mrp_release_window_days, over_receipt_pct, data_version FROM mfg_plant")).one()
            assert list(row[0]) == ["mon", "tue", "wed", "thu", "fri", "sat"] and tuple(row[1:]) == (480, 7, 7, 0, 3)
            assert c.execute(sa.text("SELECT lot_controlled FROM mfg_items")).scalar() is False
            defaults = c.execute(sa.text("SELECT count(*) FROM information_schema.columns WHERE table_name IN "
                                         "('mfg_items', 'mfg_plant') AND column_default IS NOT NULL")).scalar()
            assert defaults == 0
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0003_mfg")
    assert _tables(url) == t3
    assert not (_columns(url, "mfg_items") & ITEM_COLS) and not (_columns(url, "mfg_plant") & PLANT_COLS)
    migrate.run_alembic_upgrade(url)
    assert _diffs(url) == [] and migrate.schema_state(url) == "current"


def _m2_tables():
    md = load_all_models()
    return [md.tables[t] for t in M2_TABLES]


def _leading(t: sa.Table) -> list[tuple[str, ...]]:
    out = [tuple(c.name for c in ix.columns) for ix in t.indexes]
    out += [tuple(c.name for c in uc.columns) for uc in t.constraints if isinstance(uc, sa.UniqueConstraint)]
    out.append(tuple(c.name for c in t.primary_key.columns))
    return out


def test_schema_rules_of_9_1():
    for t in _m2_tables():
        names = [ix.name for ix in t.indexes] + [c.name for c in t.constraints if c.name is not None]
        assert all(len(n) <= 63 for n in names), (t.name, [n for n in names if len(n) > 63])
        assert any(cols and cols[0] == "owner_id" for cols in _leading(t)), t.name
        leads = {cols[0] for cols in _leading(t) if cols}
        for fk in t.foreign_keys:
            assert fk.parent.name in leads, (t.name, fk.parent.name)
        assert all(c.server_default is None or c.identity is not None for c in t.columns), t.name
        assert all(fk.name and fk.name.startswith(f"fk_{t.name}_") for fk in t.foreign_key_constraints)
    md = load_all_models()
    for t in ("mfg_mrp_planned_orders", "mfg_mrp_exceptions", "mfg_mrp_item_results", "mfg_mrp_demand_results"):
        assert {fk.column.table.name for fk in md.tables[t].foreign_keys} == {"mfg_mrp_runs", "users"}


def test_check_constraints_fire(m2_db):
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg import db_models as m1
    from superplanner.api.mfg import db_models_m2 as m2

    with owner_scope("usr_a"), m2_db.write() as s:
        s.add(m1.MfgItemRow(id="itm_" + "1" * 32, part_number="X", revision="A", description="", uom="EA",
                            make_buy="buy", receiving_days=0, lot_rule="lot_for_lot", min_order_qty=0, order_multiple=0,
                            safety_stock=0, serialized=False, handling_note="", attributes={}, active=True,
                            lot_controlled=False))
        s.add(m2.MfgLocationRow(id="loc_" + "1" * 32, code="S", name="S", kind="stores", receipt_default=False,
                                active=True, note=""))
    for on, res in ((-1.0, 0.0), (1.0, -1.0), (1.0, 2.0)):
        with pytest.raises(IntegrityError):
            with owner_scope("usr_a"), m2_db.write() as s:
                s.add(m2.MfgInvBalanceRow(id="bal_" + "1" * 32, item_id="itm_" + "1" * 32, location_id="loc_" + "1" * 32,
                                          lot_id=None, lot_key="", qty_on_hand=on, qty_reserved=res,
                                          updated_at=NOW))
    with owner_scope("usr_a"), m2_db.write() as s:
        s.add(m2.MfgInvBalanceRow(id="bal_" + "1" * 32, item_id="itm_" + "1" * 32, location_id="loc_" + "1" * 32,
                                  lot_id=None, lot_key="", qty_on_hand=2.0, qty_reserved=2.0, updated_at=NOW))
