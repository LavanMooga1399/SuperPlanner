"""Q5-2: /health/live and /health/ready (PHASE2B 5.2); /api/v1/health unchanged (Q5-1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ops_helpers import API, AUTH, PASSWORD, app_for
from superplanner import migrate


def test_live_needs_no_database(db_url, monkeypatch):
    app = app_for(db_url)
    ctx = app.state.ctx

    def boom(*a, **k):
        raise AssertionError("live must not touch the database")

    monkeypatch.setattr(ctx, "start", boom)
    monkeypatch.setattr(ctx.db, "ping", boom)
    c = TestClient(app)   # no `with`: no lifespan start
    r = c.get(f"{API}/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_body(db_url, db_kind):
    app = app_for(db_url)
    with TestClient(app) as c:
        r = c.get(f"{API}/health/ready")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"status": "ready", "database": "ok", "schema": "ok", "schema_revision": migrate.HEAD,
                        "job_backend": app.state.settings.job_backend, "workers_alive": body["workers_alive"],
                        "queue": {"queued": 0, "running": 0}}
        if db_kind == "sqlite":
            assert body["job_backend"] == "inline" and body["workers_alive"] == app.state.settings.run_workers
        else:
            assert body["job_backend"] == "queue" and body["workers_alive"] >= 1   # embedded test workers
        # the existing endpoint is unchanged
        h = c.get(f"{API}/health").json()
        assert set(h) == {"status", "version", "ortools_version", "database"} and h["status"] == "ok"


def test_ready_counts_queued_jobs(db_url, db_kind):
    """Queue counts come from the jobs table (no workers: the job stays queued)."""
    if db_kind != "postgres":
        pytest.skip("needs the queue backend (PostgreSQL) to keep a job queued")
    from ops_helpers import problem

    app = app_for(db_url, worker_embedded=0)
    with TestClient(app) as c:
        pid = problem(c)
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 1})
        assert r.status_code == 202
        from superplanner.obs import http_metrics

        http_metrics._cache.clear()
        body = c.get(f"{API}/health/ready").json()
        assert body["status"] == "ready" and body["queue"] == {"queued": 1, "running": 0}
        assert body["workers_alive"] == 0   # missing workers do not make the API unready


def test_ready_503_when_database_down(db_url, monkeypatch):
    app = app_for(db_url)
    with TestClient(app) as c:
        monkeypatch.setattr(app.state.ctx.db, "ping", lambda: False)
        r = c.get(f"{API}/health/ready")
        assert r.status_code == 503
        assert r.json()["status"] == "not_ready" and r.json()["database"] == "error"


@pytest.mark.inline_jobs   # SQLite URL also in the Postgres run
def test_ready_503_when_database_unreachable(tmp_path):
    """A database that cannot be opened at all (lazy start fails): 503, not 500."""
    url = f"sqlite:///{tmp_path / 'missing-dir' / 'x.db'}"
    c = TestClient(app_for(url))
    r = c.get(f"{API}/health/ready")
    assert r.status_code == 503 and r.json()["database"] == "error" and r.json()["status"] == "not_ready"
    assert c.get(f"{API}/health/live").status_code == 200


def test_ready_503_when_schema_behind_head(db_url, db_kind):
    if db_kind == "sqlite":
        migrate.run_alembic_upgrade(db_url, migrate.BASE_REVISION)
    else:
        migrate.run_alembic_downgrade(db_url, migrate.BASE_REVISION)
    assert migrate.current_revision(db_url) == migrate.BASE_REVISION
    c = TestClient(app_for(db_url, db_auto_migrate=False))
    r = c.get(f"{API}/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "not_ready" and body["schema"] == "outdated" and body["database"] == "ok"
    assert body["schema_revision"] == migrate.BASE_REVISION


def test_health_endpoints_public_in_accounts_mode(db_url):
    """No cookie, accounts mode: both are public and do not trip the fail-closed ownership rule (R9)."""
    app = app_for(db_url, auth_mode="accounts")
    with TestClient(app) as c:
        assert c.get(f"{API}/problems").status_code == 401
        assert c.get(f"{API}/health/live").status_code == 200
        r = c.get(f"{API}/health/ready")
        assert r.status_code == 200 and r.json()["status"] == "ready", r.text
        # signed in as well
        r = c.post(f"{AUTH}/sign-up", json={"email": "ops@example.com", "password": PASSWORD})
        assert r.status_code == 201
        assert c.get(f"{API}/health/ready").status_code == 200


def test_ready_lazy_start_inside_request(db_url):
    """First request is /health/ready on a TestClient without `with` (lazy start in a request, R9)."""
    c = TestClient(app_for(db_url, auth_mode="accounts"))
    r = c.get(f"{API}/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready", r.text
