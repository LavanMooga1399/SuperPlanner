"""Q3-10 admin CLI `python -m superplanner.manage` (PHASE2B 4.9)."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from auth_helpers import API, AUTH, PASSWORD, error, acc_app, sign_in, sign_up

from superplanner import manage
from superplanner.api.config import Settings
from superplanner.api.main import create_app

BACKEND = Path(__file__).resolve().parents[2]


def run(url: str, *argv: str, stdin: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = manage.main(["--url", url, *argv], out=out, err=err, stdin=io.StringIO(stdin))
    return code, out.getvalue(), err.getvalue()


def test_create_user_and_sign_in(db_url):
    code, out, err = run(db_url, "create-user", "--email", "Admin@Example.com", "--name", "Admin",
                         "--password-stdin", stdin=PASSWORD + "\n")
    assert code == 0, err
    uid = out.strip()
    assert uid.startswith("usr_")
    code, out, _ = run(db_url, "list-users")
    assert code == 0 and "admin@example.com" in out and "usr_local" in out
    assert run(db_url, "create-user", "--email", "admin@example.com", "--password-stdin",
               stdin=PASSWORD + "\n")[0] == 1                                        # taken
    code, _, err = run(db_url, "create-user", "--email", "w@example.com", "--password-stdin", stdin="short\n")
    assert code == 1 and "too_short" in err
    assert run(db_url, "create-user", "--email", "not-an-email", "--password-stdin", stdin=PASSWORD)[0] == 1
    with TestClient(acc_app(db_url)) as c:
        info = sign_in(c, "admin@example.com")
        assert info["user"]["id"] == uid and info["user"]["display_name"] == "Admin"


def test_set_password_disable_enable_revoke_sessions(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        assert c.get(f"{API}/problems").status_code == 200
        code, out, err = run(db_url, "set-password", "--email", "ana@example.com", "--password-stdin",
                             stdin="another long secret\n")
        assert code == 0 and "1 session(s) revoked" in out, err
        error(c.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
        error(c.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": PASSWORD}), 401,
              "INVALID_CREDENTIALS")
        sign_in(c, "ana@example.com", "another long secret")

        assert run(db_url, "disable-user", "--email", "ana@example.com")[0] == 0
        error(c.get(f"{API}/problems"), 401, "AUTH_REQUIRED")
        error(c.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": "another long secret"}),
              401, "INVALID_CREDENTIALS")
        assert run(db_url, "enable-user", "--email", "ana@example.com")[0] == 0
        sign_in(c, "ana@example.com", "another long secret")
        assert c.get(f"{API}/problems").status_code == 200
    assert run(db_url, "disable-user", "--email", "ghost@example.com")[0] == 1


def test_reassign_owner_moves_legacy_data(db_url):
    # legacy data made in single_user mode (owned by usr_local)
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        pid = c.post(f"{API}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 2}}).json()["id"]
        rid = c.post(f"{API}/problems/{pid}/solver-runs",
                     json={"strategy": "heuristic", "time_limit_seconds": 1}).json()["run_id"]
        c.app.state.ctx.jobs.wait_idle(rid)
        fpid = c.post(f"{API}/finance/templates/young_professional/instantiate",
                      json={"start_month": "2026-11"}).json()["id"]
    assert run(db_url, "create-user", "--email", "owner@example.com", "--password-stdin", stdin=PASSWORD)[0] == 0
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_in(c, "owner@example.com")
        assert c.get(f"{API}/problems").json()["items"] == []
        error(c.get(f"{API}/problems/{pid}"), 404, "NOT_FOUND")

        code, out, _ = run(db_url, "reassign-owner", "--from", "usr_local", "--to-email", "owner@example.com",
                           "--dry-run")
        assert code == 0 and "would move" in out and "problems: 1" in out and "solver_runs: 1" in out
        assert "finance_plans: 1" in out
        error(c.get(f"{API}/problems/{pid}"), 404, "NOT_FOUND")   # dry run changed nothing

        code, out, _ = run(db_url, "reassign-owner", "--to-email", "owner@example.com")
        assert code == 0 and "moved" in out and "problems: 1" in out and "jobs: 1" in out
        assert [p["id"] for p in c.get(f"{API}/problems").json()["items"]] == [pid]
        assert c.get(f"{API}/solver-runs/{rid}").json()["status"] == "completed"
        assert len(c.get(f"{API}/problems/{pid}/schedules").json()["items"]) >= 1
        assert [p["id"] for p in c.get(f"{API}/finance/plans").json()["items"]] == [fpid]
        code, out, _ = run(db_url, "reassign-owner", "--to-email", "owner@example.com", "--dry-run")
        assert "problems: 0" in out
    assert run(db_url, "reassign-owner", "--from", "usr_nobody", "--to-email", "owner@example.com")[0] == 1


def test_prune(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
        c.post(f"{AUTH}/sign-out")
    code, out, _ = run(db_url, "prune")
    assert code == 0 and "user_sessions:" in out and "auth_rate_limits:" in out


def test_cli_entry_point_and_config_error(tmp_path):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("JOB_", "WORKER_", "AUTH_", "SP_"))}
    env = {**base, "DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}", "PASSWORD_HASH_PROFILE": "fast"}
    p = subprocess.run([sys.executable, "-m", "superplanner.manage", "create-user", "--email", "c@example.com",
                        "--password-stdin"], input=PASSWORD + "\n", capture_output=True, text=True, cwd=BACKEND,
                       env=env, timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().startswith("usr_") and PASSWORD not in p.stdout + p.stderr
    p = subprocess.run([sys.executable, "-m", "superplanner.manage", "list-users"], capture_output=True, text=True,
                       cwd=BACKEND, env={**env, "AUTH_MODE": "bogus"}, timeout=120)
    assert p.returncode == 2 and "AUTH_MODE" in p.stderr
