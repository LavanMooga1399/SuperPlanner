"""Q5-7 deployment files, Q5-8 production config validation, `manage prune` jobs part (PHASE2B 5.1, 5.5, 2.9)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from ops_helpers import BACKEND, REPO
from superplanner.api.config import ConfigError, Settings

PG = "postgresql+psycopg://u:p@db.internal:5432/sp"


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# ---------------------------------------------------------------- Q5-8 production config

def test_production_defaults(monkeypatch):
    for k in ("AUTH_MODE", "CORS_ORIGINS", "COOKIE_SECURE", "LOG_FORMAT", "JOB_BACKEND", "WORKER_EMBEDDED"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(sp_env="production", database_url=PG, public_base_url="https://p.example.com",
                 password_hash_profile="default")
    assert s.auth_mode == "accounts" and s.cors_origins == [] and s.cookie_secure is True
    assert s.log_format == "json" and s.job_backend == "queue" and s.embedded_workers == 0
    assert s.forwarded_allow_ips == "127.0.0.1"


def test_production_cors_star_with_credentials_refused():
    with pytest.raises(ConfigError, match="CORS_ORIGINS"):
        Settings(sp_env="production", database_url=PG, public_base_url="https://p.example.com",
                 password_hash_profile="default", cors_origins=["*"])


def test_production_cors_star_exits_2():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("JOB_", "WORKER_", "AUTH_", "SP_", "PASSWORD_", "CORS_"))}
    env.update({"SP_ENV": "production", "DATABASE_URL": PG, "PUBLIC_BASE_URL": "https://p.example.com",
                "CORS_ORIGINS": "*"})
    p = subprocess.run([sys.executable, "-c", "import superplanner.api.main"], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 2, (p.stdout, p.stderr)
    assert "configuration error" in p.stderr and "CORS_ORIGINS" in p.stderr


# ---------------------------------------------------------------- Q5-7 files

def _env_example() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (REPO / ".env.example").read_text().splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=(.*)$", line)
        if m:
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def test_env_example_lists_every_setting():
    """Every environment variable read by api/config.py appears in .env.example (set or commented)."""
    src = (BACKEND / "superplanner" / "api" / "config.py").read_text()
    names = set(re.findall(r'_(?:env|int|float|str|bool|opt_bool|lower|env_flag|env_float)\("([A-Z0-9_]+)"', src))
    names |= set(re.findall(r'os\.environ\.get\("([A-Z0-9_]+)"', src))
    names |= {"WORKER_EMBEDDED", "WORKER_KINDS"}
    assert len(names) >= 50
    listed = _env_example()
    missing = sorted(n for n in names if n not in listed)
    assert not missing, missing
    for n in ("POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_DB", "HTTP_PORT", "WORKER_REPLICAS",
              "SP_INTERNAL_SUBNET", "ANTHROPIC_API_KEY"):
        assert n in listed, n


def test_env_example_has_no_real_secret_and_env_is_ignored():
    env = _env_example()
    assert env["POSTGRES_PASSWORD"] == "change-me"
    assert env["METRICS_TOKEN"] == "" and env.get("ANTHROPIC_API_KEY", "") == ""
    assert env["FORWARDED_ALLOW_IPS"] != "*" and env["CORS_ORIGINS"] == ""
    assert env["PASSWORD_HASH_PROFILE"] == "default"
    text = (REPO / ".env.example").read_text()
    assert "sk-ant" not in text
    if shutil.which("git"):
        p = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=REPO)
        assert p.returncode == 0, ".env must be git-ignored"


def test_nginx_overwrites_forwarded_for_and_hides_metrics():
    conf = _strip_comments((REPO / "frontend" / "nginx.conf").read_text())
    assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;", conf)
    assert "$proxy_add_x_forwarded_for" not in conf
    assert re.search(r"location\s*=\s*/metrics\s*\{\s*return 404;", conf)
    assert re.search(r"location /api/ \{[^}]*proxy_buffering off;", conf, re.S)
    assert "proxy_read_timeout 3600s" in conf and "try_files $uri /index.html" in conf
    assert "resolver 127.0.0.11" in conf and "proxy_pass $api_upstream" in conf
    assert "listen 8080" in conf and "frame-ancestors 'none'" in conf
    script = (REPO / "frontend" / "docker" / "40-sp-real-ip.sh").read_text()
    assert "set_real_ip_from" in script and "TRUSTED_PROXY_CIDRS" in script


def test_real_ip_script(tmp_path):
    if not shutil.which("sh"):
        pytest.skip("no POSIX shell")
    script = (REPO / "frontend" / "docker" / "40-sp-real-ip.sh").read_text()
    out = tmp_path / "real.conf"
    patched = tmp_path / "s.sh"
    patched.write_text(script.replace("/etc/nginx/sp-real-ip.conf", str(out)))
    env = {"PATH": os.environ.get("PATH", ""), "TRUSTED_PROXY_CIDRS": "10.0.0.0/8, 192.168.1.5,bad;rm -rf"}
    subprocess.run(["sh", str(patched)], env=env, check=True)
    text = out.read_text()
    assert "set_real_ip_from 10.0.0.0/8;" in text and "set_real_ip_from 192.168.1.5;" in text
    assert "rm" not in text and "real_ip_header X-Forwarded-For;" in text
    subprocess.run(["sh", str(patched)], env={"PATH": os.environ.get("PATH", "")}, check=True)
    assert not out.exists()


def test_dockerfiles_run_as_non_root():
    back = (BACKEND / "Dockerfile").read_text()
    assert "FROM python:3.13-slim AS base" in back and "USER 10001" in back
    assert "AS api" in back and "AS worker" in back and "--no-access-log" in back
    assert '--forwarded-allow-ips=\\"$FORWARDED_ALLOW_IPS\\"' in back and "health/ready" in back
    front = (REPO / "frontend" / "Dockerfile").read_text()
    assert "nginx-unprivileged" in front and "USER 101" in front and "npm ci" in front
    ignore = (BACKEND / ".dockerignore").read_text().split()
    assert {".venv", "tests", "*.db", ".pgdata", "__pycache__"} <= set(ignore)
    assert {"node_modules", "dist"} <= set((REPO / "frontend" / ".dockerignore").read_text().split())


def _compose() -> dict:
    text = (REPO / "docker-compose.yml").read_text()
    # resolve ${VAR:-default} / ${VAR:?msg} for a static check
    text = re.sub(r"\$\{([A-Z_]+):-([^}]*)\}", r"\2", text)
    text = re.sub(r"\$\{([A-Z_]+):\?[^}]*\}", "x", text)
    return yaml.safe_load(text)


def test_compose_structure():
    c = _compose()
    s = c["services"]
    assert set(s) == {"postgres", "migrate", "api", "worker", "frontend"}
    assert s["postgres"]["image"] == "postgres:16-alpine" and "ports" not in s["postgres"]
    assert "--locale=C.UTF-8" in s["postgres"]["environment"]["POSTGRES_INITDB_ARGS"]
    assert s["migrate"]["restart"] == "no" and s["migrate"]["command"][-1] == "upgrade"
    assert s["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert s["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert s["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"
    fwd = s["api"]["environment"]["FORWARDED_ALLOW_IPS"]
    assert fwd != "*" and fwd == c["networks"]["backend"]["ipam"]["config"][0]["subnet"]
    assert s["api"]["environment"]["SP_ENV"] == "production" and s["api"]["environment"]["JOB_BACKEND"] == "queue"
    assert s["worker"]["stop_grace_period"] == "45s" and "ports" not in s["api"] and "ports" not in s["worker"]
    assert s["frontend"]["ports"] == ["8080:8080"]
    assert "health/ready" in " ".join(s["api"]["healthcheck"]["test"])
    assert "9101/metrics" in " ".join(s["worker"]["healthcheck"]["test"])


def test_docker_compose_config_validates():
    if not shutil.which("docker"):
        pytest.skip("docker CLI not installed (compose file checked structurally above)")
    p = subprocess.run(["docker", "compose", "--env-file", ".env.example", "config", "-q"], cwd=REPO,
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0 and "is not a docker command" in p.stderr:
        pytest.skip("docker compose plugin not installed")
    assert p.returncode == 0, p.stderr


def test_line_endings_and_run_scripts():
    attrs = (REPO / ".gitattributes").read_text()
    assert re.search(r"^\*\.sh\s+text\s+eol=lf", attrs, re.M)
    sh = (BACKEND / "run_api.sh").read_text()
    assert re.search(r'if \[ "\$\{LOG_FORMAT:-\}" = "json" \]; then\s+args\+=\(--no-access-log\)', sh)
    ps1 = (BACKEND / "run_api.ps1").read_text()
    assert ".venv\\Scripts\\python.exe" in ps1 and '$env:LOG_FORMAT -eq "json"' in ps1
    assert "--no-access-log" in ps1


def test_run_api_sh_starts_zero_setup(tmp_path):
    """run_api.sh with no configuration: SQLite + single_user API answers /health (G7 smoke, Linux)."""
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("bash script")
    import socket
    import time
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("JOB_", "WORKER_", "AUTH_", "SP_", "DATABASE_", "CORS_", "LOG_"))}
    env.update({"PORT": str(port), "DATABASE_URL": f"sqlite:///{tmp_path / 'zero.db'}"})
    p = subprocess.Popen(["bash", str(BACKEND / "run_api.sh")], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health/ready", timeout=2).read()
                break
            except Exception:
                assert p.poll() is None and time.monotonic() < deadline
                time.sleep(0.3)
        assert b'"job_backend":"inline"' in body
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/problems", timeout=5).status == 200
    finally:
        p.terminate()
        p.wait(timeout=30)
    assert (tmp_path / "zero.db").exists()


# ---------------------------------------------------------------- manage prune (jobs part)

def test_manage_prune_deletes_old_terminal_jobs(db_url):
    from fastapi.testclient import TestClient
    from sqlalchemy import select, update

    from ops_helpers import API, app_for, problem
    from superplanner import manage
    from superplanner.api.db import JobRow, JobWorkerRow
    from superplanner.api.db.ownership import system_scope

    app = app_for(db_url)
    with TestClient(app) as c:
        pid = problem(c)
        run_id = c.post(f"{API}/problems/{pid}/solver-runs",
                        json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        import time

        deadline = time.monotonic() + 30
        while c.get(f"{API}/solver-runs/{run_id}").json()["status"] in ("queued", "running"):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        pid2 = problem(c)
        run2 = c.post(f"{API}/problems/{pid2}/solver-runs",
                      json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        while c.get(f"{API}/solver-runs/{run2}").json()["status"] in ("queued", "running"):
            assert time.monotonic() < deadline
            time.sleep(0.1)
    db = app.state.ctx.db.__class__(db_url)
    old = datetime.now(UTC) - timedelta(days=45)
    with system_scope(), db.write() as s:
        s.execute(update(JobRow).where(JobRow.solver_run_id == run_id).values(finished_at=old))
        s.add(JobWorkerRow(id="stale-worker", hostname="h", pid=1, kinds=["solver_run"], concurrency=1, busy=0,
                           started_at=old, heartbeat_at=old))
    import io

    out = io.StringIO()
    assert manage.main(["--url", db_url, "prune"], out=out) == 0
    text = out.getvalue()
    assert "jobs: 1 deleted" in text and "job_workers: 1 deleted" in text and "user_sessions:" in text
    with system_scope(), db.read() as s:
        left = s.scalars(select(JobRow.solver_run_id)).all()
    assert left == [run2]
    db.dispose()
