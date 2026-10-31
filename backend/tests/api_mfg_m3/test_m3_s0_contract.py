"""S0 (M3-DESIGN 14): migration 0004 -> 0005 -> 0004, the frozen contract examples validate against `aps.model`,
the 36 routes answer with the declared permissions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, acc_app, sign_up
from superplanner import migrate
from superplanner.api.mfg.db_models_m3 import M3_TABLES
from superplanner.mfg.aps import model as M

NOW = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def _fixture() -> dict:
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "superplanner" / "mfg" / "aps" / "fixtures" / "example_run.json"
    return json.loads(p.read_text())


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migration_0004_to_0005_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0004_mfg_m2")
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            c.execute(sa.text("INSERT INTO mfg_plant (id, owner_id, name, utc_offset, planning_horizon_days, currency, "
                              "attributes, data_version, row_version, created_at, updated_at, mrp_workdays, "
                              "mrp_day_minutes, mrp_defer_tolerance_days, mrp_release_window_days, over_receipt_pct)"
                              " VALUES ('plt_x', 'usr_local', 'P', '+05:30', 90, 'INR', '{}', 3, 1, :t, :t, "
                              "'[\"mon\"]', 480, 7, 7, 0)"), {"t": NOW})
    finally:
        eng.dispose()
    t4 = _tables(url)
    migrate.run_alembic_upgrade(url, "0005_mfg_m3")       # M4 (0006) on top: tests/api_mfg_m4
    assert _tables(url) - t4 == set(M3_TABLES) | {"mfg_wo_op_progress"} and migrate.schema_state(url) == "behind"
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            row = c.execute(sa.text("SELECT time_zone, aps_freeze_hours, aps_horizon_days, aps_overtime_policy "
                                    "FROM mfg_plant")).one()
            assert tuple(row) == (None, 48, 42, "suggest")
            defaults = c.execute(sa.text("SELECT count(*) FROM information_schema.columns WHERE table_name IN "
                                         "('mfg_plant', 'jobs') AND column_name LIKE 'aps%' AND column_default "
                                         "IS NOT NULL")).scalar()
            assert defaults == 0
            # exactly one job target (solver / finance / aps)
            with pytest.raises(sa.exc.IntegrityError):
                with c.begin_nested():
                    c.execute(sa.text("INSERT INTO jobs (id, kind, owner_id, status, priority, attempts, max_attempts,"
                                      " run_after, cancel_requested, created_at, updated_at) VALUES ('job_x', "
                                      "'aps_run', 'usr_local', 'queued', 0, 0, 1, :t, false, :t, :t)"), {"t": NOW})
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0004_mfg_m2")
    assert _tables(url) == t4
    migrate.run_alembic_upgrade(url)
    assert migrate.schema_state(url) == "current"


def test_contract_examples_validate_against_the_frozen_models():
    fx = _fixture()
    res = M.ApsResult.model_validate(fx["result"])
    assert res.summary.late_demand_count == 1 and res.validation.ok
    M.ApsParams.model_validate(fx["post_runs_body"])
    cp = M.ApsParams.model_validate(fx["post_runs_copy_of_body"])
    assert cp.copy_of and cp.overtime == "allow" and set(cp.model_fields_set) <= M.COPY_FIELDS
    acc = M.ApsParams.model_validate(fx["post_runs_accept_overtime_body"])
    assert acc.open_shifts and set(acc.model_fields_set) <= M.COPY_FIELDS
    assert fx["dispatch"]["shifts"] and "wo_row_version" in fx["dispatch"]["items"][0]
    for w in fx["result"]["overtime"]:
        assert "reason" in w and "orders" in w
    M.EditsRequest.model_validate(fx["edits_body"])
    M.Gantt.model_validate(fx["gantt"])
    M.Compare.model_validate(fx["compare"])
    assert set(fx["compare"]["tradeoff"]) == {"weighted_tardiness_saved", "late_minutes_saved", "late_demand_saved",
                                              "overtime_hours_added", "overtime_cost_added"}
    for d in fx["dispatch"]["items"]:
        M.DispatchRow.model_validate(d)
    for r in fx["load"]["items"]:
        M.LoadRow.model_validate(r)
    for o in fx["orders_page"]["items"]:
        M.OrderResult.model_validate(o)
    keys = {"id", "run_no", "kind", "status", "policy", "progress", "summary", "validation", "stale",
            "late_demand_remains", "copy_of_run_id", "parent_run_id", "is_published", "mrp_run", "row_version"}
    for k in ("run", "run_running", "run_copy_allow", "post_runs_response_202", "edits_response_201"):
        assert keys <= set(fx[k]), (k, keys - set(fx[k]))
    for row in fx["operations_page"]["items"]:
        M.ScheduledOp.model_validate({k: v for k, v in row.items() if k not in ("item", "line", "group", "link")})


def test_routes_and_permissions(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        owner = Api(oc)
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        me = owner.get("/me")
        assert {"schedule_run", "schedule_publish"} <= set(me["permissions"])
        vc = sign_up(app, "view@example.com")
        owner.post("/members", {"email": "view@example.com", "roles": ["viewer"]})
        pc = sign_up(app, "plan@example.com")
        owner.post("/members", {"email": "plan@example.com", "roles": ["planner"]})
        viewer, planner = Api(vc, oid), Api(pc, oid)
        assert set(planner.get("/me")["permissions"]) >= {"schedule_run", "schedule_publish"}
        e = viewer.err("POST", "/aps/runs", 403, "MFG_FORBIDDEN", json={})
        assert e["details"]["permission"] == "schedule_run"
        assert viewer.get("/setup-matrix")["items"] == []
        assert "time_zones" in owner.get("/meta")
