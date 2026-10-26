"""15.3 #7: restart - all data survives an app restart; migrations - an existing 0002 database with problems,
schedules and finance data upgrades to 0003_mfg without data loss (SQLite: automatically on start, with a
`.bak-0002-*` backup; PostgreSQL: `python -m superplanner.migrate upgrade`, then `check` exits 0), and
`downgrade 0002_phase2b` removes only the 18 `mfg_*` tables (all other rows unchanged)."""

from __future__ import annotations

import time
from typing import Any

import sqlalchemy as sa
from fastapi.testclient import TestClient

from accm1_helpers import AS_OF, V1, Api, make_app
from superplanner import migrate

FIN = f"{V1}/finance"


def _wait(c: TestClient, path: str, timeout: float = 90) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while True:
        st = c.get(path).json()
        if st["status"] not in ("queued", "running"):
            return st
        assert time.monotonic() < end, st
        time.sleep(0.1)


def _seed_2b_data(c: TestClient) -> dict[str, str]:
    r = c.post(f"{V1}/templates/manufacturing/instantiate",
               json={"start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": 5}})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    run = c.post(f"{V1}/problems/{pid}/solver-runs", json={"strategy": "auto", "time_limit_seconds": 2}).json()
    st = _wait(c, f"{V1}/solver-runs/{run['run_id']}")
    assert st["status"] == "completed", st
    plan = c.post(f"{FIN}/templates/young_professional/instantiate", json={"start_month": "2026-11"})
    assert plan.status_code == 201, plan.text
    return {"problem": pid, "schedule": st["primary_schedule_id"], "plan": plan.json()["id"]}


def _snapshot_2b(c: TestClient, ids: dict[str, str]) -> dict[str, Any]:
    out = {}
    for key, path in (("problem", f"{V1}/problems/{ids['problem']}"), ("schedule", f"{V1}/schedules/{ids['schedule']}"),
                      ("plan", f"{FIN}/plans/{ids['plan']}"), ("problems", f"{V1}/problems"),
                      ("plans", f"{FIN}/plans")):
        r = c.get(path)
        assert r.status_code == 200, (path, r.text)
        out[key] = r.json()
    return out


def _table_counts(url: str) -> dict[str, int]:
    eng = sa.create_engine(url)
    try:
        names = sa.inspect(eng).get_table_names()
        with eng.connect() as conn:
            return {t: int(conn.execute(sa.text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()) for t in names}
    finally:
        eng.dispose()


def _mfg_snapshot(api: Api) -> tuple[bytes, str, dict[str, Any]]:
    exp = api.call("GET", "/export", 200, params={"format": "zip"}).content
    return exp, api.health()["fingerprint"], api.get("/summary")["counts"]


def test_mfg_and_existing_data_survive_restart(db_url: str):
    with TestClient(make_app(db_url)) as c:
        api = Api(c)
        ids = _seed_2b_data(c)
        api.load("kavach")
        top = api.item("KV-TPU-1000")
        snap = _mfg_snapshot(api)
        before_2b = _snapshot_2b(c, ids)
        explosion = api.get(f"/items/{top['id']}/explosion", on=AS_OF)
    for _ in range(2):                                         # two restarts
        with TestClient(make_app(db_url)) as c:
            api = Api(c)
            assert _mfg_snapshot(api) == snap
            assert api.get(f"/items/{top['id']}/explosion", on=AS_OF) == explosion
            assert _snapshot_2b(c, ids) == before_2b
    assert migrate.schema_state(db_url) == "current"


def test_0002_database_upgrades_without_loss_and_downgrade_removes_only_mfg(db_url: str, db_kind: str):
    from superplanner.api.mfg.db_models import MFG_TABLES

    # 1. a database with problems, a schedule, finance data AND mfg data, at head
    with TestClient(make_app(db_url)) as c:
        ids = _seed_2b_data(c)
        Api(c).load("small")
        before_2b = _snapshot_2b(c, ids)
    at_head = _table_counts(db_url)
    assert set(MFG_TABLES) <= set(at_head) and at_head["mfg_items"] == 10

    # 2. downgrade to 0002 removes exactly the mfg tables and keeps every other row
    migrate.run_alembic_downgrade(db_url, "0002_phase2b")
    at_0002 = _table_counts(db_url)
    assert set(at_head) - set(at_0002) == set(MFG_TABLES)
    assert len(MFG_TABLES) == 18
    assert at_0002 == {t: n for t, n in at_head.items() if t not in MFG_TABLES}
    assert migrate.current_revision(db_url) == "0002_phase2b"
    assert migrate.schema_state(db_url) == "behind"

    # 3. upgrade: SQLite on first start (with a backup); PostgreSQL through the CLI, then `check`
    if db_kind == "sqlite":
        path = migrate.sqlite_path(db_url)
        assert not list(path.parent.glob(f"{path.name}.bak-0002-*"))
    else:
        assert migrate.main(["upgrade", "--url", db_url]) == 0
        assert migrate.main(["check", "--url", db_url]) == 0
    with TestClient(make_app(db_url)) as c:
        api = Api(c)
        assert _snapshot_2b(c, ids) == before_2b
        assert api.get("/summary")["counts"]["items"] == 0          # mfg starts empty after the downgrade
        api.load("small")
        assert api.health()["ok"]
    assert migrate.current_revision(db_url) == migrate.HEAD == "0003_mfg"
    after = _table_counts(db_url)
    for t, n in at_0002.items():
        if t == "audit_events":
            assert after[t] >= n                                    # the sample load audits
        elif t == "job_workers":
            continue                                                # queue worker registry (PostgreSQL run)
        else:
            assert after[t] == n, t
    if db_kind == "sqlite":
        backups = list(path.parent.glob(f"{path.name}.bak-0002-*"))
        assert len(backups) == 1
        assert _table_counts(f"sqlite:///{backups[0]}") == at_0002
