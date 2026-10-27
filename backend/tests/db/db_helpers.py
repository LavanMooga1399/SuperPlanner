"""Helpers for tests/db: databases at revision 0001_initial filled with data (frozen 0001 table definitions)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.config import Settings
from superplanner.api.main import create_app

ALL_11 = ("problems", "problem_versions", "solver_runs", "solver_run_events", "schedules", "audit_events",
          "finance_plans", "finance_plan_versions", "finance_runs", "finance_run_events", "finance_results")
SCHEDULING_6 = ALL_11[:6]
OWNED = ("problems", "solver_runs", "schedules", "finance_plans", "finance_runs", "finance_results")
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def _ts(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def legacy_rows(tables: tuple[str, ...] = ALL_11, *, extra: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Rows for every legacy table. `extra=True` adds a second approved schedule and a second active run."""
    doc = {"name": "Legacy", "domain": "generic", "tasks": []}
    rows: dict[str, list[dict[str, Any]]] = {
        "problems": [dict(id="p_1", name="Legacy", domain="generic", template_id=None, version=1, document=doc,
                          created_at=_ts(0), updated_at=_ts(0))],
        "problem_versions": [dict(id="pv_1", problem_id="p_1", base_version=1, kind="snapshot", content_hash="h1",
                                  document=doc, created_at=_ts(1))],
        "solver_runs": [dict(id="run_1", problem_id="p_1", problem_version_id="pv_1", status="completed",
                             request={"strategy": "auto"}, seed=0, engine_version="1.0", selection=None,
                             phases=None, feasibility="feasible", termination_reason="done",
                             optimality_proven=False, objectives=None, metrics=None, diagnostics=[], error=None,
                             cancel_requested=False, source_schedule_id=None, created_at=_ts(2),
                             started_at=_ts(2), finished_at=_ts(3))],
        "solver_run_events": [dict(run_id="run_1", seq=i, type=t, payload={"seq": i, "type": t}, created_at=_ts(2))
                              for i, t in ((1, "run_queued"), (2, "run_started"), (3, "run_completed"))],
        "schedules": [dict(id=f"sch_{i}", problem_id="p_1", problem_version_id="pv_1", solver_run_id="run_1",
                           source_schedule_id=None, status="approved" if i == 1 else "candidate", rank=i - 1,
                           label="Recommended", solver="cpsat", feasibility="feasible", objectives=None,
                           metrics=None, violations=[], placements=[], explanation=None, created_at=_ts(3),
                           approved_at=_ts(4) if i == 1 else None, superseded_at=None,
                           approved_problem_version=1 if i == 1 else None) for i in (1, 2)],
        "audit_events": [dict(entity_type="problem", entity_id="p_1", action="problem.created", details={},
                              created_at=_ts(0))],
        "finance_plans": [dict(id="fp_1", name="Money", template_id=None, version=1, document={"name": "Money"},
                               created_at=_ts(0), updated_at=_ts(0))],
        "finance_plan_versions": [dict(id="fpv_1", plan_id="fp_1", base_version=1, kind="snapshot",
                                       content_hash="f1", document={"name": "Money"}, created_at=_ts(1))],
        "finance_runs": [dict(id="frun_1", plan_id="fp_1", plan_version_id="fpv_1", kind="baseline", label=None,
                              status="completed", request={}, what_if=None, seed=0, engine_version="fin-0.2.0",
                              feasibility="feasible", error=None, cancel_requested=False, created_at=_ts(2),
                              started_at=_ts(2), finished_at=_ts(3))],
        "finance_run_events": [dict(run_id="frun_1", seq=1, type="run_queued", payload={"seq": 1},
                                    created_at=_ts(2))],
        "finance_results": [dict(id="fres_1", plan_id="fp_1", plan_version_id="fpv_1", run_id="frun_1",
                                 kind="baseline", label=None, feasibility="feasible", summary={"goals_total": 1},
                                 result={"ok": True}, created_at=_ts(3))],
    }
    if extra:
        rows["schedules"].append(dict(rows["schedules"][0], id="sch_old", approved_at=_ts(-60), rank=5))
        rows["solver_runs"].append(dict(rows["solver_runs"][0], id="run_old", status="queued", created_at=_ts(-30),
                                        started_at=None, finished_at=None, feasibility=None))
        rows["solver_runs"].append(dict(rows["solver_runs"][0], id="run_new", status="running", created_at=_ts(30),
                                        started_at=_ts(30), finished_at=None, feasibility=None))
        rows["solver_run_events"].append(dict(run_id="run_old", seq=1, type="run_queued", payload={"seq": 1},
                                              created_at=_ts(-30)))
    return {t: v for t, v in rows.items() if t in tables}


def initial_module() -> Any:
    """The frozen 0001 revision module (its `build_metadata()` defines the 0001 tables)."""
    path = migrate.MIGRATIONS_DIR / "versions" / "0001_initial.py"
    spec = importlib.util.spec_from_file_location("superplanner_migration_0001_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_0001_db(url: str, tables: tuple[str, ...] = ALL_11, *, extra: bool = False) -> dict[str, int]:
    """An (empty) database migrated to 0001_initial, filled with rows in `tables`. Returns row counts."""
    migrate.run_alembic_upgrade(url, migrate.BASE_REVISION)
    md = initial_module().build_metadata()
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            for t, items in legacy_rows(tables, extra=extra).items():
                c.execute(md.tables[t].insert(), items)
    finally:
        eng.dispose()
    return counts(url, tables)


def counts(url: str, tables: tuple[str, ...] = ALL_11) -> dict[str, int]:
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return {t: int(c.execute(sa.text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()) for t in tables}
    finally:
        eng.dispose()


def schema_diffs(url: str) -> list[Any]:
    """Alembic autogenerate diff between the live database and the model metadata (empty = identical)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from superplanner.api.db import load_all_models

    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            mc = MigrationContext.configure(c, opts={"compare_type": True})
            return list(compare_metadata(mc, load_all_models()))
    finally:
        eng.dispose()
