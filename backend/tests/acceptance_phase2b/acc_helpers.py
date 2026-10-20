"""Q6 acceptance helpers: real API (uvicorn) and worker subprocesses, HTTP clients per user, and the job/run/event
invariants I1-I4 of PHASE2B 2.4 checked straight from the database with plain SQL (no product code involved)."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, pool, text

BACKEND = Path(__file__).resolve().parents[2]
API = "/api/v1"
FIN = f"{API}/finance"
PASSWORD = "correct horse battery staple"
TERMINAL_EVENTS = ("run_completed", "run_cancelled", "run_failed")
TERMINAL_STATUS = ("completed", "cancelled", "failed")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

FAST_FIN: dict[str, Any] = {"time_limit_seconds": 10, "simulation": {"n_paths": 200}, "compute_fixes": False,
                            "calibration_rounds": 0}
SLOW_FIN: dict[str, Any] = {"time_limit_seconds": 120, "simulation": {"n_paths": 10000}, "compute_fixes": True,
                            "calibration_rounds": 4}
FAST_SOLVER: dict[str, Any] = {"strategy": "heuristic", "time_limit_seconds": 1}
LONG_GA: dict[str, Any] = {"strategy": "ga", "time_limit_seconds": 30,
                           "ga": {"max_generations": 10000, "stagnation_generations": 1000}}

# Short lease timings so lease expiry / reaping happen within seconds.
FAST_JOB_ENV: dict[str, str] = {
    "JOB_LEASE_SECONDS": "3", "JOB_HEARTBEAT_SECONDS": "0.5", "JOB_CANCEL_POLL_SECONDS": "0.2",
    "JOB_REAPER_SECONDS": "0.5", "JOB_BACKOFF_BASE_SECONDS": "0.1", "JOB_BACKOFF_MAX_SECONDS": "0.5",
    "WORKER_POLL_SECONDS": "0.3", "WORKER_SHUTDOWN_GRACE_SECONDS": "5", "WORKER_METRICS_PORT": "0",
}


def load_int_helpers():
    """The engine-independent schedule checker of tests/integration (loaded under a unique module name)."""
    name = "acc_int_helpers"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, BACKEND / "tests" / "integration" / "int_helpers.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(pred: Callable[[], Any], timeout: float = 30.0, interval: float = 0.1, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while True:
        try:
            value = pred()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001 - retried until the deadline
            last_exc = exc
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what} (last error: {last_exc!r})")
        time.sleep(interval)


def _clean_env() -> dict[str, str]:
    drop = ("JOB_", "WORKER_", "DB_AUTO", "AUTH_", "SP_", "DATABASE_URL", "PORT", "COOKIE_", "PUBLIC_BASE_URL",
            "CORS_ORIGINS", "PASSWORD_HASH", "LOG_", "METRICS_", "SIGNUP_", "RUN_WORKERS")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


class Proc:
    def __init__(self, popen: subprocess.Popen, log: Path, name: str):
        self.p, self.log, self.name = popen, log, name

    @property
    def pid(self) -> int:
        return self.p.pid

    def alive(self) -> bool:
        return self.p.poll() is None

    def kill9(self) -> None:
        if self.alive():
            self.p.send_signal(signal.SIGKILL)
            self.p.wait(15)

    def stop(self, sig: int = signal.SIGTERM, timeout: float = 30.0) -> int | None:
        if self.alive():
            self.p.send_signal(sig)
            try:
                self.p.wait(timeout)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(10)
        return self.p.returncode

    def log_text(self) -> str:
        try:
            return self.log.read_text(errors="replace")
        except OSError:
            return ""


class ApiProc(Proc):
    def __init__(self, popen: subprocess.Popen, log: Path, port: int):
        super().__init__(popen, log, f"api:{port}")
        self.port = port
        self.url = f"http://127.0.0.1:{port}"


def start_api(db_url: str, log_dir: Path, *, port: int | None = None, auth: str = "accounts",
              embedded: str = "0", job_backend: str = "queue", **env: Any) -> ApiProc:
    port = port or free_port()
    e = _clean_env()
    e.update(FAST_JOB_ENV)
    e.update({"DATABASE_URL": db_url, "AUTH_MODE": auth, "JOB_BACKEND": job_backend, "WORKER_EMBEDDED": embedded,
              "COOKIE_SECURE": "false", "PASSWORD_HASH_PROFILE": "fast", "AUTH_SIGNIN_LIMIT_PER_IP": "1000",
              "AUTH_SIGNUP_LIMIT_PER_IP": "1000", "AUTH_SIGNIN_LIMIT_PER_EMAIL": "1000",
              "PUBLIC_BASE_URL": "http://127.0.0.1:5173", "RUN_WORKERS": "2", "PYTHONUNBUFFERED": "1"})
    e.update({k: str(v) for k, v in env.items()})
    log = log_dir / f"api-{port}-{uuid.uuid4().hex[:6]}.log"
    fh = open(log, "ab")
    uvicorn = BACKEND / ".venv" / "bin" / "uvicorn"
    p = subprocess.Popen([str(uvicorn), "superplanner.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=str(BACKEND), env=e, stdout=fh, stderr=subprocess.STDOUT)
    api = ApiProc(p, log, port)

    def up() -> bool:
        if not api.alive():
            raise AssertionError(f"API exited early ({p.returncode}):\n{api.log_text()[-3000:]}")
        return httpx.get(f"{api.url}{API}/health/ready", timeout=2).status_code == 200

    wait_for(up, 60, 0.2, what=f"API on {port}")
    return api


def start_worker(db_url: str, log_dir: Path, *args: str, name: str | None = None, **env: Any) -> Proc:
    e = _clean_env()
    e.update(FAST_JOB_ENV)
    e.update({"DATABASE_URL": db_url, "JOB_BACKEND": "queue", "PYTHONUNBUFFERED": "1", "LOG_LEVEL": "INFO"})
    if name:
        e["WORKER_ID"] = name
    e.update({k: str(v) for k, v in env.items()})
    log = log_dir / f"worker-{name or uuid.uuid4().hex[:6]}-{uuid.uuid4().hex[:4]}.log"
    fh = open(log, "ab")
    p = subprocess.Popen([sys.executable, "-m", "superplanner.worker", *args], cwd=str(BACKEND), env=e,
                         stdout=fh, stderr=subprocess.STDOUT)
    return Proc(p, log, name or f"worker:{p.pid}")


class User:
    """One browser: its own session cookie and CSRF token; can talk to any API instance on the same DB."""

    def __init__(self, email: str | None = None):
        self.email = email
        self.cookie: str | None = None
        self.csrf: str | None = None
        self.user_id: str | None = None

    def request(self, base: str, method: str, path: str, *, csrf: bool = True, origin: str | None = None,
                headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        h = dict(headers or {})
        if csrf and self.csrf and method.upper() in UNSAFE:
            h.setdefault("X-CSRF-Token", self.csrf)
        if origin:
            h["Origin"] = origin
        cookies = {"sp_session": self.cookie} if self.cookie else None
        kw.setdefault("timeout", 60)
        return httpx.request(method, f"{base}{path}", headers=h, cookies=cookies, **kw)

    def _take(self, r: httpx.Response) -> dict[str, Any]:
        info = r.json()
        self.cookie = r.cookies.get("sp_session")
        assert self.cookie, r.headers.get_list("set-cookie")
        self.csrf = info["csrf_token"]
        self.user_id = info["user"]["id"]
        return info

    def sign_up(self, base: str) -> dict[str, Any]:
        r = self.request(base, "POST", f"{API}/auth/sign-up", json={"email": self.email, "password": PASSWORD})
        assert r.status_code == 201, r.text
        return self._take(r)

    def sign_in(self, base: str) -> dict[str, Any]:
        r = self.request(base, "POST", f"{API}/auth/sign-in", json={"email": self.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return self._take(r)

    # ---- shortcuts
    def get(self, base: str, path: str, **kw: Any) -> httpx.Response:
        return self.request(base, "GET", path, **kw)

    def post(self, base: str, path: str, **kw: Any) -> httpx.Response:
        return self.request(base, "POST", path, **kw)

    def problem(self, base: str, jobs: int = 6) -> str:
        r = self.post(base, f"{API}/templates/manufacturing/instantiate",
                      json={"start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": jobs}})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def plan(self, base: str) -> str:
        r = self.post(base, f"{FIN}/templates/young_professional/instantiate", json={"start_month": "2026-11"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def solver_run(self, base: str, pid: str, req: dict[str, Any] | None = None, **headers: str) -> str:
        r = self.post(base, f"{API}/problems/{pid}/solver-runs", json=req or FAST_SOLVER, headers=headers or None)
        assert r.status_code == 202, r.text
        return r.json()["run_id"]

    def fin_run(self, base: str, plan: str, req: dict[str, Any] | None = None, **headers: str) -> str:
        r = self.post(base, f"{FIN}/plans/{plan}/runs", json=req or FAST_FIN, headers=headers or None)
        assert r.status_code == 202, r.text
        return r.json()["run_id"]

    def run_status(self, base: str, run_id: str, kind: str) -> dict[str, Any]:
        path = f"{API}/solver-runs/{run_id}" if kind == "solver" else f"{FIN}/runs/{run_id}"
        r = self.get(base, path)
        assert r.status_code == 200, r.text
        return r.json()

    def wait_run(self, base: str | Callable[[], str], run_id: str, kind: str, timeout: float = 90) -> dict[str, Any]:
        def done():
            b = base() if callable(base) else base
            st = self.run_status(b, run_id, kind)
            return st if st["status"] in TERMINAL_STATUS else None
        return wait_for(done, timeout, 0.2, what=f"{kind} run {run_id} terminal")


SINGLE = User()   # single_user mode: no cookie, no token


# ---------------------------------------------------------------- SSE

class SseReader(threading.Thread):
    """Reads one SSE stream in the background; collects (id, event, data) frames until the stream ends."""

    def __init__(self, user: User, base: str, path: str, last_event_id: int | None = None):
        super().__init__(daemon=True)
        self.user, self.base, self.path, self.last = user, base, path, last_event_id
        self.frames: list[dict[str, Any]] = []
        self.error: BaseException | None = None
        self.status: int | None = None
        self.ended = threading.Event()

    def run(self) -> None:
        headers = {"Last-Event-ID": str(self.last)} if self.last is not None else {}
        cookies = {"sp_session": self.user.cookie} if self.user.cookie else None
        try:
            with httpx.stream("GET", f"{self.base}{self.path}", headers=headers, cookies=cookies,
                              timeout=httpx.Timeout(120, connect=5)) as r:
                self.status = r.status_code
                cur: dict[str, Any] = {}
                for line in r.iter_lines():
                    if line == "":
                        if "data" in cur:
                            self.frames.append({"id": int(cur["id"]) if "id" in cur else None,
                                                "event": cur.get("event"), "data": json.loads(cur["data"])})
                        cur = {}
                    elif line.startswith(":"):
                        continue
                    else:
                        k, _, v = line.partition(":")
                        cur[k] = v[1:] if v.startswith(" ") else v
        except BaseException as exc:  # noqa: BLE001 - connection drop is an expected outcome in restart tests
            self.error = exc
        finally:
            self.ended.set()


# ---------------------------------------------------------------- DB invariants (plain SQL)

class Db:
    def __init__(self, url: str):
        self.engine = create_engine(url, poolclass=pool.NullPool)

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(text(sql), params)]

    def one(self, sql: str, **params: Any) -> dict[str, Any]:
        rs = self.rows(sql, **params)
        assert len(rs) == 1, (sql, params, rs)
        return rs[0]

    def job(self, run_id: str) -> dict[str, Any]:
        return self.one("SELECT * FROM jobs WHERE solver_run_id = :r OR finance_run_id = :r", r=run_id)

    def events(self, run_id: str, kind: str) -> list[dict[str, Any]]:
        t = "solver_run_events" if kind == "solver" else "finance_run_events"
        return self.rows(f"SELECT seq, type FROM {t} WHERE run_id = :r ORDER BY seq", r=run_id)

    def run(self, run_id: str, kind: str) -> dict[str, Any]:
        t = "solver_runs" if kind == "solver" else "finance_runs"
        return self.one(f"SELECT * FROM {t} WHERE id = :r", r=run_id)

    def dispose(self) -> None:
        self.engine.dispose()


JOB_FOR_RUN = {"completed": "succeeded", "cancelled": "cancelled", "failed": "failed"}


def check_invariants(db: Db, run_id: str, kind: str, *, expect: str | None = None,
                     max_attempts: int | None = None) -> dict[str, Any]:
    """I1-I4 for one run plus job/run status agreement. Returns a summary dict."""
    run = db.run(run_id, kind)
    job = db.job(run_id)
    ev = db.events(run_id, kind)
    types = [e["type"] for e in ev]
    assert run["status"] in TERMINAL_STATUS, (run_id, run["status"])
    if expect:
        assert run["status"] == expect, (run_id, run["status"], run.get("error"), types)
    # job terminal status written together with run terminal status
    assert job["status"] == JOB_FOR_RUN[run["status"]], (run_id, run["status"], job["status"])
    # I1: exactly one terminal event and it is the last; seq contiguous 1..n
    assert sum(t in TERMINAL_EVENTS for t in types) == 1, (run_id, types)
    assert types[-1] in TERMINAL_EVENTS and types[-1] == f"run_{run['status']}", (run_id, run["status"], types)
    assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1)), (run_id, [e["seq"] for e in ev])
    assert types[0] == "run_queued", types
    if kind == "solver":
        sch = db.rows("SELECT rank FROM schedules WHERE solver_run_id = :r ORDER BY rank", r=run_id)
        ranks = [s["rank"] for s in sch]
        if run["status"] not in ("completed", "cancelled"):
            assert ranks == [], (run_id, run["status"], ranks)   # I2
        assert ranks == list(range(len(ranks))), (run_id, ranks)  # I2 ranks 0..k unique
        if run["status"] == "completed" and run["feasibility"] in ("feasible",):
            assert ranks, run_id
    else:
        n = db.one("SELECT count(*) AS n FROM finance_results WHERE run_id = :r", r=run_id)["n"]
        assert n <= 1, (run_id, n)                                # I3
        if run["status"] == "completed":
            assert n == 1, run_id
        else:
            assert n == 0, (run_id, run["status"], n)
    if max_attempts is not None:
        assert job["attempts"] <= max_attempts, (run_id, job["attempts"])
    starts = types.count("run_started")
    requeues = types.count("run_requeued")
    return {"run": run, "job": job, "types": types, "starts": starts, "requeues": requeues}
