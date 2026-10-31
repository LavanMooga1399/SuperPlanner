"""U+0000 rejection (B 3.5.7; Q1-11), Settings resolution/validation (B 5.1; PostgreSQL only, secure defaults),
startup refusal with one-line errors, auth maintenance helper."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from db_helpers import make_app
from superplanner.api.auth.maintenance import prune_auth_tables
from superplanner.api.auth.models import AuthRateLimitRow, UserSessionRow
from superplanner.api.config import DEFAULT_CORS_ORIGINS, ConfigError, Settings, normalize_database_url
from superplanner.api.db import utcnow
from superplanner.api.limits import NulScanner

API = "/api/v1"
BACKEND = Path(__file__).resolve().parents[2]
PG = "postgresql+psycopg://u:p@127.0.0.1:5432/db"


# ---------------------------------------------------------------- Q1-11 NUL

def _raw(c: TestClient, path: str, text: str):
    return c.post(f"{API}{path}", content=text.encode(), headers={"Content-Type": "application/json"})


def test_nul_in_any_json_body_is_422_on_both_dialects(db_url):
    with TestClient(make_app(db_url)) as c:
        cases = [
            ("/templates/manufacturing/instantiate", '{"name": "bad\\u0000name", "parameters": {"jobs": 2}}'),
            ("/finance/templates/young_professional/instantiate", '{"name": "x\\u0000", "start_month": "2026-11"}'),
            ("/intake/schedule/describe", '{"text": "Task A \\u0000 2 days"}'),
            ("/problems/import", '{"format": "superplanner.problem", "x": {"\\u0000key": 1}}'),
        ]
        for path, body in cases:
            r = _raw(c, path, body)
            assert r.status_code == 422, (path, r.text)
            err = r.json()["error"]
            assert err["code"] == "VALIDATION_ERROR" and "NUL" in err["message"]
        # an escaped backslash followed by "u0000" is ordinary text and is stored as such
        r = _raw(c, "/templates/manufacturing/instantiate", '{"name": "C:\\\\u0000dir", "parameters": {"jobs": 2}}')
        assert r.status_code == 201, r.text
        assert r.json()["problem"]["name"] == "C:\\u0000dir"
        pid = r.json()["id"]
        assert c.get(f"{API}/problems/{pid}").json()["problem"]["name"] == "C:\\u0000dir"
        # nothing with a NUL got stored
        assert len(c.get(f"{API}/problems").json()["items"]) == 1
        assert c.get(f"{API}/finance/plans").json()["items"] == []


@pytest.mark.parametrize("text,expected", [
    ('"a\\u0000"', True), ('"\\\\u0000"', False), ('"\\\\\\u0000"', True), ('"u0000"', False),
    ('"\\u00001"', True), ('"\\u0001"', False), ("plain", False), ('"\x00"', True),
])
def test_nul_scanner_every_split(text, expected):
    data = text.encode()
    for cut in range(len(data) + 1):
        for step in (1, 2, 3, len(data) or 1):
            sc = NulScanner()
            hit = sc.feed(data[:cut]) if cut else False
            rest = data[cut:]
            for i in range(0, len(rest), step):
                hit = sc.feed(rest[i:i + step]) or hit
                if hit:
                    break
            assert hit is expected, (text, cut, step)


def test_nul_scanner_long_backslash_runs_across_chunks():
    sc = NulScanner()
    assert not sc.feed(b'"' + b"\\" * 1001)
    assert sc.feed(b"u0000")          # 1001 backslashes: the last one escapes the u
    sc = NulScanner()
    assert not sc.feed(b'"' + b"\\" * 1000)
    assert not sc.feed(b"u0000")      # 1000: all escaped pairs


# ---------------------------------------------------------------- config (B 5.1)

def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os.environ):
        if k in ("SP_ENV", "APP_ENV", "DATABASE_URL", "MIGRATION_DATABASE_URL", "JOB_BACKEND", "AUTH_MODE",
                 "CORS_ORIGINS", "COOKIE_SECURE", "PASSWORD_HASH_PROFILE", "LOG_FORMAT", "WORKER_EMBEDDED",
                 "DB_AUTO_MIGRATE", "AUTO_MIGRATE", "PUBLIC_BASE_URL", "METRICS_TOKEN", "METRICS_ENABLED"):
            monkeypatch.delenv(k, raising=False)


STRONG_PG = "postgresql+psycopg://sp_app:Zq7-long-random-pw-81@db.internal:5432/superplanner"
TOKEN = "m" + "x9Kq2LrT5vW8yB3nD6fH1jA4" * 2
PROD_OK = {"database_url": STRONG_PG, "public_base_url": "https://plan.example.com", "metrics_token": TOKEN}


def test_development_defaults(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    s = Settings(database_url=PG)
    assert s.sp_env == "development" and s.is_development and not s.is_production
    assert (s.job_backend, s.auth_mode, s.db_auto_migrate, s.cookie_secure) == ("queue", "accounts", False, False)
    assert s.cors_origins == list(DEFAULT_CORS_ORIGINS) and s.cors_allow_credentials is True
    assert s.worker_embedded == "auto" and s.embedded_workers == s.run_workers
    assert s.log_format == "text" and s.public_base_url == "http://127.0.0.1:5173"
    assert s.worker_kinds == ["solver_run", "finance_run", "aps_run"]   # M3-DESIGN 10: worker default kinds = all
    assert s.schema_url == PG
    s = Settings(database_url=PG, auth_mode="single_user")      # development only
    assert s.single_user


def test_app_env_defaults_to_production_and_sp_env_is_an_alias(monkeypatch):
    _clean_env(monkeypatch)
    s = Settings(**PROD_OK)
    assert s.sp_env == "production" and s.is_production
    monkeypatch.setenv("SP_ENV", "development")
    assert Settings(database_url=PG).is_development
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigError, match="disagree"):
        Settings(database_url=PG)


def test_postgres_url_normalisation_and_pool_settings(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    for raw in ("postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"):
        assert normalize_database_url(raw) == "postgresql+psycopg://u:p@h/db"
    s = Settings(database_url="postgres://u:p@h/db?sslmode=verify-full&sslrootcert=/etc/ca.pem")
    assert s.database_url == "postgresql+psycopg://u:p@h/db?sslmode=verify-full&sslrootcert=/etc/ca.pem"
    assert s.job_backend == "queue" and s.db_auto_migrate is False
    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_pre_ping, s.db_statement_timeout_ms,
            s.db_connect_timeout_seconds, s.db_lock_timeout_ms, s.db_pool_recycle_seconds) == \
        (10, 10, True, 30000, 10, 10000, 1800)
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("DB_POOL_PRE_PING", "false")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "5000")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://owner:p@h/db")
    s = Settings(database_url=PG)
    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_pre_ping, s.db_statement_timeout_ms,
            s.db_connect_timeout_seconds) == (3, 0, False, 5000, 3)
    assert s.schema_url == "postgresql+psycopg://owner:p@h/db"
    s = Settings(database_url=PG, job_backend="inline")
    assert any("only ONE API process" in w for w in s.warnings)


def test_database_engine_applies_connection_settings(db_url):
    from superplanner.api.db import Database

    db = Database(db_url, pool_size=2, max_overflow=1, statement_timeout_ms=1234, lock_timeout_ms=567,
                  connect_timeout_seconds=4, service="t")
    try:
        assert db.engine.pool.size() == 2 and db.engine.pool._max_overflow == 1
        assert db.engine.pool._pre_ping is True
        with db.engine.connect() as c:
            import sqlalchemy as sa

            assert c.execute(sa.text("SHOW statement_timeout")).scalar() == "1234ms"
            assert c.execute(sa.text("SHOW lock_timeout")).scalar() == "567ms"
            assert c.execute(sa.text("SELECT current_setting('application_name')")).scalar() == "superplanner-t"
    finally:
        db.dispose()


def test_production_defaults(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    s = Settings(**{**PROD_OK, "public_base_url": "https://plan.example.com/"})
    assert (s.auth_mode, s.cors_origins, s.cookie_secure, s.log_format) == ("accounts", [], True, "json")
    assert s.job_backend == "queue" and s.worker_embedded == 0 and s.embedded_workers == 0
    assert s.public_base_url == "https://plan.example.com" and s.cors_allow_credentials
    s = Settings(**PROD_OK, cors_origins=["https://app.example.com", "https://x.example.com:8443"])
    assert len(s.cors_origins) == 2
    s = Settings(**{**PROD_OK, "metrics_token": None}, metrics_enabled=False)
    assert s.metrics_token is None
    s = Settings(**{**PROD_OK, "database_url": "postgresql+psycopg://sp_app@db/superplanner?sslmode=verify-full"})
    assert "sslmode=verify-full" in s.database_url     # no password in the URL (pgpass / client cert): allowed


@pytest.mark.parametrize("kwargs,env,match", [
    ({"job_backend": "celery"}, {}, "JOB_BACKEND must be one of"),
    ({"auth_mode": "oauth"}, {}, "AUTH_MODE must be one of"),
    ({"database_url": "mysql://x"}, {}, "DATABASE_URL must be a PostgreSQL URL"),
    ({"database_url": "sqlite:///x.db"}, {}, "DATABASE_URL must be a PostgreSQL URL"),
    ({"database_url": "postgresql+asyncpg://u@h/d"}, {}, "DATABASE_URL must be a PostgreSQL URL"),
    ({"database_url": ""}, {}, "DATABASE_URL is required"),
    ({"migration_database_url": "sqlite:///m.db"}, {}, "MIGRATION_DATABASE_URL must be a PostgreSQL URL"),
    ({"auth_mode": "accounts", "cors_origins": ["*"]}, {}, "no '\\*'"),
    ({"log_format": "xml"}, {}, "LOG_FORMAT"),
    ({}, {"DB_POOL_SIZE": "many"}, "DB_POOL_SIZE must be an integer"),
    ({}, {"WORKER_EMBEDDED": "-1"}, "WORKER_EMBEDDED must be >= 0"),
    ({}, {"WORKER_KINDS": "solver_run,email"}, "WORKER_KINDS"),
    ({}, {"COOKIE_SECURE": "maybe"}, "COOKIE_SECURE must be true or false"),
    ({}, {"APP_ENV": "staging"}, "APP_ENV must be one of"),
])
def test_invalid_configuration(monkeypatch, kwargs, env, match):
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError, match=match):
        Settings(**{"database_url": PG, **kwargs})


@pytest.mark.parametrize("kwargs,match", [
    ({"database_url": None}, "DATABASE_URL is required"),
    ({"job_backend": "inline"}, "JOB_BACKEND=inline is only allowed with APP_ENV=development"),
    ({"password_hash_profile": "fast"}, "fast is for tests"),
    ({"auth_mode": "single_user"}, "single_user is only allowed with APP_ENV=development"),
    ({"public_base_url": None}, "PUBLIC_BASE_URL is required"),
    ({"public_base_url": "http://plan.example.com"}, "PUBLIC_BASE_URL must be https://"),
    ({"cookie_secure": False}, "COOKIE_SECURE=false is only allowed"),
    ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
    ({"cors_origins": ["null"]}, "too permissive"),
    ({"cors_origins": ["http://app.example.com"]}, "too permissive"),
    ({"cors_origins": ["https://*.example.com"]}, "too permissive"),
    ({"metrics_token": None}, "METRICS_TOKEN must be set"),
    ({"metrics_token": "short"}, "METRICS_TOKEN must be set"),
    ({"metrics_token": "change-me-please-change-me-now"}, "METRICS_TOKEN must be set"),
    ({"database_url": "postgresql://superplanner:change-me@db/superplanner"}, "weak or placeholder password"),
    ({"database_url": "postgresql://u:postgres@db/superplanner"}, "weak or placeholder password"),
    ({"migration_database_url": "postgresql://owner:short@db/superplanner"}, "MIGRATION_DATABASE_URL has a weak"),
])
def test_invalid_production_configuration(monkeypatch, kwargs, match):
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigError, match=match):
        Settings(**{**PROD_OK, **kwargs})


def test_module_app_exits_2_on_config_error():
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "APP_ENV", "SP_ENV")}
    code = "import superplanner.api.main as m; m.app"
    p = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 2, p.stderr
    assert p.stderr.strip().splitlines() == ["configuration error: DATABASE_URL is required (PostgreSQL only), "
                                             "e.g. DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME"]
    env["DATABASE_URL"] = "sqlite:///superplanner.db"
    p = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 2 and "must be a PostgreSQL URL" in p.stderr, p.stderr


def test_module_app_exits_3_with_one_line_when_schema_not_at_head(empty_pg_db):
    url = empty_pg_db()
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "development"}
    code = "import superplanner.api.main as m; m.app"
    p = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 3, p.stderr
    lines = p.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("schema error: Database schema is empty"), lines
    assert "Run: python -m superplanner.migrate upgrade" in lines[0]
    p = subprocess.run([sys.executable, "-c", code + "; print('ok')"], cwd=BACKEND,
                       env={**env, "AUTO_MIGRATE": "true"}, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0 and p.stdout.strip().endswith("ok"), p.stderr[-2000:]


def test_module_import_has_no_side_effects():
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL",)}
    p = subprocess.run([sys.executable, "-c", "from superplanner.api.main import create_app; print('ok')"],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0 and p.stdout.strip() == "ok", p.stderr


# ---------------------------------------------------------------- auth maintenance

def test_prune_auth_tables(db_url):
    with TestClient(make_app(db_url)) as c:
        db = c.app.state.ctx.db
        now = utcnow()
        with db.write() as s:
            for i, (exp, rev) in enumerate(((now - timedelta(days=1), None), (now + timedelta(days=1), None),
                                            (now + timedelta(days=1), now - timedelta(days=2)),
                                            (now + timedelta(days=1), now - timedelta(hours=1)))):
                s.add(UserSessionRow(id=f"ses_{i}", user_id="usr_local", token_hash=f"h{i}", csrf_token="c",
                                     created_at=now, last_seen_at=now, expires_at=exp, revoked_at=rev))
            s.add(AuthRateLimitRow(bucket="old", window_start=now - timedelta(hours=2), count=3))
            s.add(AuthRateLimitRow(bucket="new", window_start=now - timedelta(minutes=2), count=3))
        with db.write() as s:
            assert prune_auth_tables(s, now) == {"user_sessions": 2, "auth_rate_limits": 1}
        with db.read() as s:
            assert sorted(r.id for r in s.query(UserSessionRow)) == ["ses_1", "ses_3"]
            assert [r.bucket for r in s.query(AuthRateLimitRow)] == ["new"]
