"""S0: migration 0006 -> 0007 -> 0006 (additive), head and table set (M5-DESIGN 10)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.mfg.db_models_m5 import M5_TABLES


def _tables(url):
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migration_0006_to_0007_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0006_mfg_m4")
    t6 = _tables(url)
    migrate.run_alembic_upgrade(url, "0007_m5")
    assert migrate.schema_state(url) == "behind"
    assert _tables(url) - t6 == set(M5_TABLES)
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            assert c.execute(sa.text("SELECT kind FROM users WHERE id = 'usr_local'")).scalar() == "person"
            cols = {r[0] for r in c.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE "
                                                    "table_name = 'jobs'"))}
            assert {"int_inbox_id", "int_reconciliation_id", "maintenance_run_id", "org_publish_id"} <= cols
            with pytest.raises(sa.exc.IntegrityError):
                with c.begin_nested():
                    c.execute(sa.text("INSERT INTO jobs (id, kind, owner_id, status, priority, attempts, "
                                      "max_attempts, run_after, cancel_requested, created_at, updated_at) VALUES "
                                      "('job_x', 'org_publish', 'usr_local', 'queued', 0, 0, 1, now(), false, now(), "
                                      "now())"))
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0006_mfg_m4")
    assert _tables(url) == t6
    migrate.run_alembic_upgrade(url)
    assert migrate.schema_state(url) == "current"
