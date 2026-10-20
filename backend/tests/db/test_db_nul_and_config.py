"""U+0000 rejection on both dialects (B 3.5.7; Q1-11), Settings resolution/validation (B 5.1), SQLite mode without
psycopg (Q1-12), auth maintenance helper."""

from __future__ import annotations

import json
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
        if k in ("SP_ENV", "DATABASE_URL", "JOB_BACKEND", "AUTH_MODE", "CORS_ORIGINS", "COOKIE_SECURE",
                 "PASSWORD_HASH_PROFILE", "LOG_FORMAT", "WORKER_EMBEDDED", "DB_AUTO_MIGRATE", "PUBLIC_BASE_URL",
                 "ALLOW_SINGLE_USER_IN_PRODUCTION"):
            monkeypatch.delenv(k, raising=False)


def test_development_defaults(monkeypatch):
    _clean_env(monkeypatch)
    s = Settings()
    assert s.sp_env == "development" and s.database_url.startswith("sqlite:///")
    assert s.database_url.endswith("superplanner.db")
    assert (s.job_backend, s.auth_mode, s.db_auto_migrate, s.cookie_secure) == ("inline", "single_user", True, False)
    assert s.cors_origins == list(DEFAULT_CORS_ORIGINS) and s.cors_allow_credentials is False
    assert s.worker_embedded == "auto" and s.embedded_workers == s.run_workers
    assert s.log_format == "text" and s.public_base_url == "http://127.0.0.1:5173"
    assert s.worker_kinds == ["solver_run", "finance_run"]


def test_postgres_defaults_and_url_normalisation(monkeypatch):
    _clean_env(monkeypatch)
    for raw in ("postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"):
        assert normalize_database_url(raw) == "postgresql+psycopg://u:p@h/db"
    s = Settings(database_url="postgres://u:p@h/db")
    assert s.database_url == "postgresql+psycopg://u:p@h/db" and s.is_postgres
    assert s.job_backend == "queue" and s.db_auto_migrate is False
    s = Settings(database_url=PG, job_backend="inline")
    assert any("only ONE API process" in w for w in s.warnings)


def test_production_defaults(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("SP_ENV", "production")
    s = Settings(database_url=PG, public_base_url="https://plan.example.com/")
    assert (s.auth_mode, s.cors_origins, s.cookie_secure, s.log_format) == ("accounts", [], True, "json")
    assert s.job_backend == "queue" and s.worker_embedded == 0 and s.embedded_workers == 0
    assert s.public_base_url == "https://plan.example.com" and s.cors_allow_credentials


@pytest.mark.parametrize("kwargs,env,match", [
    ({"job_backend": "queue"}, {}, "JOB_BACKEND=queue needs PostgreSQL"),
    ({"job_backend": "celery"}, {}, "JOB_BACKEND must be one of"),
    ({"auth_mode": "oauth"}, {}, "AUTH_MODE must be one of"),
    ({"database_url": "mysql://x"}, {}, "DATABASE_URL must be"),
    ({"auth_mode": "accounts", "cors_origins": ["*"]}, {}, "no '\\*'"),
    ({"log_format": "xml"}, {}, "LOG_FORMAT"),
    ({}, {"DB_POOL_SIZE": "many"}, "DB_POOL_SIZE must be an integer"),
    ({}, {"WORKER_EMBEDDED": "-1"}, "WORKER_EMBEDDED must be >= 0"),
    ({}, {"WORKER_KINDS": "solver_run,email"}, "WORKER_KINDS"),
    ({}, {"COOKIE_SECURE": "maybe"}, "COOKIE_SECURE must be true or false"),
    ({}, {"SP_ENV": "staging"}, "SP_ENV must be one of"),
])
def test_invalid_configuration(monkeypatch, kwargs, env, match):
    _clean_env(monkeypatch)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError, match=match):
        Settings(**kwargs)


@pytest.mark.parametrize("kwargs,match", [
    ({}, "DATABASE_URL is required"),
    ({"database_url": PG, "job_backend": "inline", "public_base_url": "https://x"}, "JOB_BACKEND=inline"),
    ({"database_url": PG, "password_hash_profile": "fast", "public_base_url": "https://x"}, "fast is for tests"),
    ({"database_url": PG, "auth_mode": "single_user"}, "single_user is refused"),
    ({"database_url": PG}, "PUBLIC_BASE_URL is required"),
])
def test_invalid_production_configuration(monkeypatch, kwargs, match):
    _clean_env(monkeypatch)
    monkeypatch.setenv("SP_ENV", "production")
    with pytest.raises(ConfigError, match=match):
        Settings(**kwargs)


def test_production_overrides(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("SP_ENV", "production")
    s = Settings(database_url=PG, auth_mode="single_user", allow_single_user_in_production=True)
    assert s.auth_mode == "single_user"
    s = Settings(database_url=PG, public_base_url="https://x", cookie_secure=False)
    assert any("COOKIE_SECURE=false" in w for w in s.warnings)


def test_uvicorn_import_exits_2_on_config_error(tmp_path):
    env = {**os.environ, "JOB_BACKEND": "queue", "DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"}
    p = subprocess.run([sys.executable, "-c", "import superplanner.api.main"], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 2, p.stderr
    assert "configuration error: JOB_BACKEND=queue needs PostgreSQL" in p.stderr


# ---------------------------------------------------------------- Q1-12 SQLite mode never imports psycopg

@pytest.mark.inline_jobs   # SQLite subprocess: must not inherit the Postgres run's JOB_BACKEND=queue
def test_sqlite_mode_works_without_psycopg(tmp_path):
    code = f"""
import sys
sys.modules["psycopg"] = None            # any import of psycopg now raises ImportError
sys.modules["psycopg2"] = None
from fastapi.testclient import TestClient
from superplanner.api.config import Settings
from superplanner.api.main import create_app
from superplanner import migrate
with TestClient(create_app(Settings(database_url={json.dumps(f"sqlite:///{tmp_path / 'w.db'}")}))) as c:
    assert c.get("/api/v1/health").status_code == 200
    r = c.post("/api/v1/templates/manufacturing/instantiate", json={{"parameters": {{"jobs": 2}}}})
    assert r.status_code == 201, r.text
    assert c.get("/api/v1/finance/plans").status_code == 200
assert migrate.schema_state({json.dumps(f"sqlite:///{tmp_path / 'w.db'}")}) == "current"
print("ok")
"""
    p = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stderr[-3000:]
    assert p.stdout.strip().endswith("ok")


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
