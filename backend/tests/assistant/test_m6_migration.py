"""S0: migration 0007 -> 0008 -> 0007 (expand), head, table set, ORM == schema (M6-DESIGN 6)."""

from __future__ import annotations

import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.mfg.db_models_m6 import M6_TABLES


def _tables(url):
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _diffs(url):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from superplanner.api.db import load_all_models

    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return list(compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}),
                                         load_all_models()))
    finally:
        eng.dispose()


def test_migration_0007_to_0008_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0007_m5")
    t7 = _tables(url)
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            c.execute(sa.text("INSERT INTO mfg_plant (id, owner_id, name, utc_offset, planning_horizon_days, currency, "
                              "attributes, data_version, mrp_workdays, mrp_day_minutes, mrp_defer_tolerance_days, "
                              "mrp_release_window_days, over_receipt_pct, aps_freeze_hours, aps_horizon_days, "
                              "aps_overtime_policy, replan_policy, replan_debounce_minutes, overrun_tolerance_pct, "
                              "adherence_tolerance_minutes, row_version, created_at, updated_at) VALUES ('plt_1', "
                              "'usr_local', 'P', '+00:00', 90, 'INR', '{}', 0, '[\"mon\"]', 480, 7, 7, 0, 48, 42, "
                              "'suggest', 'notify', 15, 20, 120, 1, now(), now())"))
    finally:
        eng.dispose()
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0008_m6" and migrate.schema_state(url) == "current"
    assert _tables(url) - t7 == set(M6_TABLES)
    assert _diffs(url) == []
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:   # existing plants: assistant on, what-if allowed (server defaults)
            assert c.execute(sa.text("SELECT assistant_enabled, assistant_allow_whatif, dashboard_thresholds FROM "
                                     "mfg_plant")).one() == (True, True, None)
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0007_m5")
    assert _tables(url) == t7
    migrate.run_alembic_upgrade(url)
    assert migrate.schema_state(url) == "current"
