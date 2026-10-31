"""S0 (M4-DESIGN 13): migration 0005 -> 0006 -> 0005 incl. M3 progress rows, the frozen contract examples validate
against `mfg.model_m4`, the 26 new routes are registered with the declared permissions, the new roles exist."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, acc_app, sign_up
from superplanner import migrate
from superplanner.api.mfg.db_models_m4 import M4_TABLES
from superplanner.mfg import model_m4 as M
from superplanner.mfg.aps import model as APS

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
FIX = Path(__file__).resolve().parents[2] / "superplanner" / "mfg" / "floor" / "fixtures" / "example_floor.json"


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _ins(c: sa.Connection, table: str, **vals: object) -> None:
    """INSERT with every other NOT NULL column filled by a neutral value of its type (literal schema, no ORM)."""
    cols = c.execute(sa.text("SELECT column_name, data_type, is_nullable, column_default "
                             "FROM information_schema.columns "
                             "WHERE table_name = :t"), {"t": table}).all()
    neutral = {"integer": 0, "bigint": 0, "smallint": 0, "double precision": 0.0, "boolean": False, "jsonb": "{}",
               "json": "{}", "date": "2026-11-02", "timestamp with time zone": NOW}
    row = dict(vals)
    if "owner_id" in {x[0] for x in cols}:
        row.setdefault("owner_id", "usr_local")
    for name, typ, nullable, default in cols:
        if name not in row and nullable == "NO" and default is None:
            row[name] = neutral.get(typ, "")
    names = ", ".join(row)
    c.execute(sa.text(f"INSERT INTO {table} ({names}) VALUES ({', '.join(':' + k for k in row)})"),
              {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()})


def _seed_m3(c: sa.Connection) -> None:
    """A plant, an item with a released routing (ops 10 / 20), a released WO and one M3 done marker (seq 10)."""
    _ins(c, "mfg_plant", id="plt_x", name="P", utc_offset="+05:30", currency="INR", mrp_workdays=["mon"],
         aps_overtime_policy="suggest")
    _ins(c, "mfg_items", id="itm_1", part_number="FG", revision="A", uom="EA", make_buy="make", lot_rule="lot_for_lot",
         active=True)
    _ins(c, "mfg_groups", id="wcg_1", code="G", name="G", active=True)
    _ins(c, "mfg_routings", id="rtg_1", item_id="itm_1", revision="A", code="STD", version=1, priority=1,
         status="released")
    for seq, name in ((10, "Kit"), (20, "Test")):
        _ins(c, "mfg_operations", id=f"opr_{seq}", routing_id="rtg_1", seq=seq, name=name, group_id="wcg_1",
             run_minutes=1, run_per="unit", labor="attended", crew_size=1, yield_pct=100, interruptible=True)
    _ins(c, "mfg_work_orders", id="wko_1", number="WO-000001", item_id="itm_1", qty=7, start_date="2026-11-02",
         due_date="2026-11-09", status="released", priority=5, source="manual", released_at=NOW, row_version=1)
    _ins(c, "mfg_wo_op_progress", id="wop_00000000000000000000000000000001", wo_id="wko_1", seq=10, done=True,
         done_at=NOW, done_by="usr_local", row_version=1)
    _ins(c, "mfg_wo_op_progress", id="wop_00000000000000000000000000000002", wo_id="wko_1", seq=20, done=False,
         row_version=1)


def test_migration_0005_to_0006_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0005_mfg_m3")
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            _seed_m3(c)
    finally:
        eng.dispose()
    t5 = _tables(url)
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0006_mfg_m4" and migrate.schema_state(url) == "current"
    assert _tables(url) - t5 == set(M4_TABLES) and t5 - _tables(url) == {"mfg_wo_op_progress"}
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            ops = c.execute(sa.text("SELECT id, wo_id, seq, name, group_id, status, qty_planned, qty_good, source, "
                                    "last_event_seq FROM mfg_wo_operations")).all()
            assert len(ops) == 1
            o = ops[0]
            assert (o.wo_id, o.seq, o.name, o.group_id, o.status, o.qty_planned, o.qty_good, o.source) == \
                ("wko_1", 10, "Kit", "wcg_1", "completed", 7.0, 7.0, "migrated")
            ev = c.execute(sa.text("SELECT event_type, qty_good, details, actor_id, seq FROM mfg_floor_events")).one()
            assert ev.event_type == "complete" and ev.qty_good == 7.0 and ev.details == {"migrated": True}
            assert o.last_event_seq == ev.seq and ev.actor_id == "usr_local"
            plant = c.execute(sa.text("SELECT replan_policy, replan_debounce_minutes, overrun_tolerance_pct, "
                                      "adherence_tolerance_minutes, wo_receipt_location_id FROM mfg_plant")).one()
            assert tuple(plant) == ("notify", 15, 20.0, 120, None)
            item = c.execute(sa.text("SELECT issue_method FROM mfg_items")).scalar()
            assert item == "manual"
            defaults = c.execute(sa.text(
                "SELECT count(*) FROM information_schema.columns WHERE column_default IS NOT NULL AND column_name IN "
                "('issue_method', 'capture_serial', 'batch_merge', 'batch_wait_minutes', 'replan_policy', "
                "'replan_debounce_minutes', 'overrun_tolerance_pct', 'adherence_tolerance_minutes')")).scalar()
            assert defaults == 0
            with pytest.raises(sa.exc.IntegrityError):    # exactly one of four job targets
                with c.begin_nested():
                    c.execute(sa.text("INSERT INTO jobs (id, kind, owner_id, status, priority, attempts, max_attempts,"
                                      " run_after, cancel_requested, created_at, updated_at) VALUES ('job_x', "
                                      "'aps_simulation', 'usr_local', 'queued', 0, 0, 1, :t, false, :t, :t)"),
                              {"t": NOW})
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0005_mfg_m3")
    assert _tables(url) == t5
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            rows = c.execute(sa.text("SELECT wo_id, seq, done FROM mfg_wo_op_progress")).all()
            assert [tuple(r) for r in rows] == [("wko_1", 10, True)]
    finally:
        eng.dispose()
    migrate.run_alembic_upgrade(url)
    assert migrate.schema_state(url) == "current"


def test_contract_examples_validate_against_the_frozen_models():
    fx = json.loads(FIX.read_text())
    for k in ("scan_wo", "scan_operation", "scan_operator"):
        M.ScanResult.model_validate(fx[k])
    M.QueueResponse.model_validate(fx["queue"])
    M.FloorOperationDetail.model_validate(fx["operation_detail"])
    M.FloorEventInput.model_validate(fx["event_body"])
    M.FloorEventInput.model_validate(fx["serial_event_body"])
    for k in ("event_result_201", "event_result_last_op_201"):
        M.FloorEventResult.model_validate(fx[k])
    for e in fx["events_page"]["items"]:
        M.FloorEventRecord.model_validate(e)
    for o in fx["wo_operations"]["items"]:
        M.WoOperationRecord.model_validate(o)
    M.DowntimeInput.model_validate(fx["downtime_body"])
    M.DowntimeUpdate.model_validate(fx["downtime_close_body"])
    M.DowntimeRecord.model_validate(fx["downtime_201"])
    M.BatchLoadInput.model_validate(fx["batch_load_body"])
    M.BatchLoadRecord.model_validate(fx["batch_load_201"])
    M.UnitSerialDetail.model_validate(fx["serial_detail"])
    for t in fx["triggers_page"]["items"]:
        M.ReplanTriggerRecord.model_validate(t)
    M.ReplanRunInput.model_validate(fx["replan_run_body"])
    M.NotificationRecord.model_validate(fx["notification_acked"])
    M.KpiResponse.model_validate(fx["kpis"])
    for r in fx["adherence"]["items"]:
        M.AdherenceRow.model_validate(r)
    M.SimulationInput.model_validate(fx["simulation_body"])
    M.SimulationRecord.model_validate(fx["simulation"])
    APS.ApsParams.model_validate(fx["aps_params_m4"])
    assert set(fx["summary_floor"]) == {"running_ops", "lines_down", "open_triggers", "pending_backflush"}
    assert set(fx["kpis"]["metrics"]) >= {"otd", "wo_on_time", "utilisation", "availability", "performance", "fpy",
                                          "oee", "wip", "setup", "adherence", "scrap_rate"}


M4_ROUTES = [
    ("GET", "/floor/scan", "floor_view"), ("GET", "/floor/queue", "floor_view"),
    ("GET", "/floor/operations/{wo_op_id}", "floor_view"), ("POST", "/floor/events", "floor_report"),
    ("GET", "/floor/events", "floor_view"), ("POST", "/floor/backflush/retry", "inventory"),
    ("POST", "/work-orders/{wo_id}/operations/refresh", "wo_edit"),
    ("GET", "/downtime", "view"), ("POST", "/downtime", "downtime_report"),
    ("PUT", "/downtime/{downtime_id}", "downtime_report"),
    ("GET", "/batch-loads", "floor_view"), ("POST", "/batch-loads", "floor_report"),
    ("GET", "/batch-loads/{load_id}", "floor_view"),
    ("GET", "/serials", "view"), ("GET", "/serials/{serial_id}", "view"),
    ("GET", "/replan/triggers", "view"), ("POST", "/replan/triggers/{trigger_id}/ignore", "replan_manage"),
    ("POST", "/replan/triggers/{trigger_id}/handle", "replan_manage"), ("POST", "/replan/run", "schedule_run"),
    ("GET", "/notifications", "view"), ("POST", "/notifications/{notification_id}/ack", "view"),
    ("GET", "/kpis", "view"), ("GET", "/kpis/adherence", "view"),
    ("POST", "/aps/simulations", "schedule_run"), ("GET", "/aps/simulations/{simulation_id}", "view"),
    ("GET", "/aps/simulations", "view"),
]


def test_the_26_routes_declare_their_permission():
    from superplanner.api.mfg import router_m4

    got = []
    for r in router_m4.router.routes:
        perms = [d.dependency.mfg_permission for d in r.dependencies if hasattr(d.dependency, "mfg_permission")]
        assert len(perms) == 1, r.path
        for m in r.methods:
            got.append((m, r.path.removeprefix("/mfg"), perms[0]))
    assert sorted(got) == sorted(M4_ROUTES)


def test_roles_and_permissions():
    from superplanner.api.mfg.access import ROLE_PERMISSIONS, roles_allowed

    assert roles_allowed("floor_view") == ["owner", "planner", "purchaser", "store_keeper", "approver", "viewer",
                                           "operator", "supervisor"]
    assert set(roles_allowed("floor_report")) == {"owner", "planner", "operator", "supervisor"}
    assert set(roles_allowed("floor_supervise")) == {"owner", "supervisor"}
    assert set(roles_allowed("downtime_report")) == {"owner", "planner", "operator", "supervisor"}
    assert set(roles_allowed("replan_manage")) == {"owner", "planner"}
    assert "wo_edit" not in ROLE_PERMISSIONS["operator"] and "inventory" not in ROLE_PERMISSIONS["supervisor"]


def test_operator_member_uses_floor_routes_only(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        owner = Api(oc)
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        tc = sign_up(app, "tablet@example.com")
        owner.post("/members", {"email": "tablet@example.com", "roles": ["operator"]})
        op = Api(tc, oid)
        perms = set(op.get("/me")["permissions"])
        assert {"floor_view", "floor_report", "downtime_report", "view"} <= perms
        assert "floor_supervise" not in perms and "wo_edit" not in perms
        e = op.err("POST", "/replan/run", 403, "MFG_FORBIDDEN", json={})
        assert e["details"]["permission"] == "schedule_run"
        op.err("POST", "/items", 403, "MFG_FORBIDDEN", json={"part_number": "X", "make_buy": "buy"})
        assert op.get("/floor/events")["items"] == []
        op.err("GET", "/floor/scan", 404, "FLR_SCAN_UNKNOWN", params={"code": "NOPE-1"})
