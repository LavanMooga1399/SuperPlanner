#!/usr/bin/env python
"""Load sanity script for the durable job queue (PHASE2B 6). Run with the backend venv on a disposable database:

    DATABASE_URL=postgresql+psycopg://... .venv/bin/python scripts/load_queue.py \\
        --runs 50 --solver-share 0.5 --workers 3 [--concurrency 1] [--api-url URL] [--chaos-kill-after 5] \\
        [--json out.json] [--database-url URL] [--log-dir DIR]

Without `--api-url` it migrates the database (`migrate upgrade`), starts its own API (uvicorn subprocess,
`JOB_BACKEND=queue`, `WORKER_EMBEDDED=0`, `AUTH_MODE=single_user`, free port) and `--workers` worker subprocesses
(`python -m superplanner.worker --concurrency C --id load-w<i>`). With `--api-url` the API is external (it must run
in single_user mode on the same database); workers are still started here unless `--workers 0`.

Setup: ceil(runs*share) scheduling plans (template `manufacturing`, jobs=6) and the rest finance plans (template
`young_professional`, else the first finance template); one run per plan. Solver runs use
`{"strategy":"auto","time_limit_seconds":2}`, finance runs the defaults. All runs are enqueued concurrently
(16 HTTP threads), each with an `Idempotency-Key`; 10% of the POSTs are sent a second time, concurrently, with the
same key (the replay must return the same run id).

`--chaos-kill-after N`: after N jobs succeeded, SIGKILLs one worker that holds a running job, to exercise lease
expiry and requeue. Unless set in the environment, chaos mode shortens the workers' lease timings
(JOB_LEASE_SECONDS=6, JOB_HEARTBEAT_SECONDS=2, JOB_REAPER_SECONDS=2) so the requeue happens within seconds.

Verification from the database (system scope); any violation -> exit 1: every run `completed`; exactly one job
per run, `succeeded`; replays returned the same run id; exactly one terminal event per run and it is the last;
event `seq` contiguous from 1; solver runs: schedule ranks unique and contiguous from 0; finance runs: exactly one
result; `attempts == 1` for every job unless chaos (then requeued jobs have `attempts == 2` and a `run_requeued`
event, and at least one job was requeued); every job's final `lease_owner` is a known worker.

Report (stdout, optional JSON): runs, workers, concurrency, wall seconds, throughput (runs/min), queue wait
p50/p95, job duration p50/p95 per kind, jobs per worker, requeues, duplicates (must be 0), lost (must be 0).
`run(argv) -> Report` is the programmatic entry (tests/jobs/test_load_small.py). Exit codes: 0 ok, 1 violations or
timeout, 2 configuration error.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

API = "/api/v1"
SOLVER_REQUEST = {"strategy": "auto", "time_limit_seconds": 2}
HTTP_THREADS = 16
CHAOS_ENV = {"JOB_LEASE_SECONDS": "6", "JOB_HEARTBEAT_SECONDS": "2", "JOB_REAPER_SECONDS": "2",
             "JOB_CANCEL_POLL_SECONDS": "0.5"}


class LoadError(RuntimeError):
    """Configuration / environment problem (exit 2)."""


@dataclass
class Report:
    runs: int = 0
    solver_runs: int = 0
    finance_runs: int = 0
    workers: int = 0
    concurrency: int = 1
    chaos: bool = False
    killed_worker: str | None = None
    wall_seconds: float = 0.0
    throughput_runs_per_min: float = 0.0
    queue_wait_p50_s: float = 0.0
    queue_wait_p95_s: float = 0.0
    job_duration_s: dict[str, dict[str, float]] = field(default_factory=dict)
    jobs_per_worker: dict[str, int] = field(default_factory=dict)
    replays_sent: int = 0
    replays_ok: int = 0
    requeues: int = 0
    duplicates: int = 0
    lost: int = 0
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d

    def text(self) -> str:
        lines = [
            f"runs              {self.runs} (solver {self.solver_runs}, finance {self.finance_runs})",
            f"workers           {self.workers} x concurrency {self.concurrency}"
            + (f"  (chaos: killed {self.killed_worker})" if self.chaos else ""),
            f"wall seconds      {self.wall_seconds:.1f}",
            f"throughput        {self.throughput_runs_per_min:.1f} runs/min",
            f"queue wait        p50 {self.queue_wait_p50_s:.2f}s  p95 {self.queue_wait_p95_s:.2f}s",
        ]
        for kind, d in sorted(self.job_duration_s.items()):
            lines.append(f"duration {kind:<12}p50 {d['p50']:.2f}s  p95 {d['p95']:.2f}s  (n={int(d['n'])})")
        lines.append("jobs per worker   " + ", ".join(f"{k}={v}" for k, v in sorted(self.jobs_per_worker.items())))
        lines += [f"replays           {self.replays_ok}/{self.replays_sent} returned the same run id",
                  f"requeues          {self.requeues}",
                  f"duplicates        {self.duplicates}",
                  f"lost              {self.lost}",
                  "result            " + ("OK" if self.ok else f"FAILED ({len(self.violations)} violations)")]
        lines += [f"  - {v}" for v in self.violations[:50]]
        return "\n".join(lines)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# ---------------------------------------------------------------- processes

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Procs:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.items: list[tuple[str, subprocess.Popen, Any]] = []

    def start(self, name: str, cmd: list[str], env: dict[str, str]) -> subprocess.Popen:
        fh = open(self.log_dir / f"{name}.log", "wb")
        p = subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=fh, stderr=subprocess.STDOUT)
        self.items.append((name, p, fh))
        return p

    def stop_all(self, timeout: float = 30.0) -> None:
        for _, p, _ in self.items:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + timeout
        for _, p, fh in self.items:
            try:
                p.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=10)
            fh.close()


def child_env(db_url: str, chaos: bool) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"DATABASE_URL": db_url, "JOB_BACKEND": "queue", "WORKER_EMBEDDED": "0", "AUTH_MODE": "single_user",
                "SP_ENV": "development", "PYTHONUNBUFFERED": "1", "METRICS_ENABLED": "true"})
    if chaos:
        for k, v in CHAOS_ENV.items():
            env.setdefault(k, v)
    return env


def wait_http(base: str, proc: subprocess.Popen | None, timeout: float = 60.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise LoadError(f"the API exited with code {proc.returncode} during startup")
        try:
            if httpx.get(f"{base}{API}/health", timeout=2).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise LoadError(f"the API at {base} did not become healthy within {timeout:.0f}s")


# ---------------------------------------------------------------- HTTP part

def _check(r: Any, status: int, what: str) -> dict[str, Any]:
    if r.status_code != status:
        raise RuntimeError(f"{what}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def create_plans(client: Any, n_solver: int, n_fin: int) -> tuple[list[str], list[str]]:
    templates = _check(client.get(f"{API}/finance/templates"), 200, "finance templates")["items"]
    ids = [t.get("id") for t in templates]
    fin_tpl = "young_professional" if "young_professional" in ids else ids[0]

    def mk_problem(i: int) -> str:
        r = client.post(f"{API}/templates/manufacturing/instantiate",
                        json={"start_date": "2026-11-02", "utc_offset": "+00:00", "parameters": {"jobs": 6}})
        return _check(r, 201, "instantiate manufacturing")["id"]

    def mk_fin(i: int) -> str:
        r = client.post(f"{API}/finance/templates/{fin_tpl}/instantiate", json={"start_month": "2026-11"})
        return _check(r, 201, f"instantiate {fin_tpl}")["id"]

    with cf.ThreadPoolExecutor(HTTP_THREADS) as ex:
        problems = list(ex.map(mk_problem, range(n_solver)))
        plans = list(ex.map(mk_fin, range(n_fin)))
    return problems, plans


@dataclass
class Post:
    kind: str           # solver_run | finance_run
    target: str         # problem id / plan id
    key: str
    replay: bool = False


def enqueue(client: Any, posts: list[Post]) -> dict[str, list[tuple[str, bool]]]:
    """key -> [(run_id, replayed_header)] for every POST (two entries for replayed keys)."""
    out: dict[str, list[tuple[str, bool]]] = {}
    lock = threading.Lock()

    def one(p: Post) -> None:
        if p.kind == "solver_run":
            url, body = f"{API}/problems/{p.target}/solver-runs", SOLVER_REQUEST
        else:
            url, body = f"{API}/finance/plans/{p.target}/runs", {}
        r = client.post(url, json=body, headers={"Idempotency-Key": p.key})
        data = _check(r, 202, f"enqueue {p.kind}")
        with lock:
            out.setdefault(p.key, []).append((data["run_id"], r.headers.get("idempotent-replayed") == "true"))

    with cf.ThreadPoolExecutor(HTTP_THREADS) as ex:
        for f in [ex.submit(one, p) for p in posts]:
            f.result()
    return out


# ---------------------------------------------------------------- DB part (system scope)

class Db:
    def __init__(self, url: str):
        from superplanner.api.db import Database, load_all_models

        load_all_models()
        self.db = Database(url, pool_size=2, max_overflow=2, service="manage")

    def read(self) -> Any:
        return self.db.read()

    def close(self) -> None:
        self.db.dispose()

    def counts(self, run_ids: list[str]) -> tuple[int, int]:
        """(succeeded jobs, terminal jobs) among our runs."""
        from sqlalchemy import func, or_, select

        from superplanner.api.db import JobRow
        from superplanner.api.db.ownership import system_scope

        with system_scope(), self.read() as s:
            rows = s.execute(select(JobRow.status, func.count()).where(
                or_(JobRow.solver_run_id.in_(run_ids), JobRow.finance_run_id.in_(run_ids)))
                .group_by(JobRow.status)).all()
        by = {st: int(n) for st, n in rows}
        return by.get("succeeded", 0), sum(by.get(st, 0) for st in ("succeeded", "failed", "cancelled"))

    def running_owners(self) -> dict[str, int]:
        from sqlalchemy import func, select

        from superplanner.api.db import JobRow
        from superplanner.api.db.ownership import system_scope

        with system_scope(), self.read() as s:
            rows = s.execute(select(JobRow.lease_owner, func.count()).where(JobRow.status == "running")
                             .group_by(JobRow.lease_owner)).all()
        return {o: int(n) for o, n in rows if o}

    def active_runs(self, solver_ids: list[str], fin_ids: list[str]) -> int:
        from sqlalchemy import func, select

        from superplanner.api.db import SolverRunRow
        from superplanner.api.db.ownership import system_scope
        from superplanner.api.finance.db_models import FinanceRunRow

        active = ("queued", "running")
        with system_scope(), self.read() as s:
            a = s.scalar(select(func.count()).select_from(SolverRunRow).where(
                SolverRunRow.id.in_(solver_ids), SolverRunRow.status.in_(active))) or 0 if solver_ids else 0
            b = s.scalar(select(func.count()).select_from(FinanceRunRow).where(
                FinanceRunRow.id.in_(fin_ids), FinanceRunRow.status.in_(active))) or 0 if fin_ids else 0
        return int(a) + int(b)


def _aware(dt: Any) -> Any:
    from datetime import UTC

    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def verify(db: Db, report: Report, solver_ids: list[str], fin_ids: list[str], workers: set[str],
           chaos: bool) -> tuple[list[float], dict[str, list[float]], Any, Any]:
    """Appends violations to the report; returns (queue waits, durations by kind, first created, last finished)."""
    from sqlalchemy import or_, select

    from superplanner.api.db import JobRow, ScheduleRow, SolverRunEventRow, SolverRunRow
    from superplanner.api.db.ownership import system_scope
    from superplanner.api.finance.db_models import FinanceResultRow, FinanceRunEventRow, FinanceRunRow

    terminal = ("run_completed", "run_failed", "run_cancelled")
    v = report.violations
    waits: list[float] = []
    durations: dict[str, list[float]] = {"solver_run": [], "finance_run": []}
    first_created = last_finished = None
    all_ids = solver_ids + fin_ids
    with system_scope(), db.read() as s:
        jobs: dict[str, list[Any]] = {}
        for j in s.scalars(select(JobRow).where(or_(JobRow.solver_run_id.in_(all_ids),
                                                    JobRow.finance_run_id.in_(all_ids)))).all():
            jobs.setdefault(j.solver_run_id or j.finance_run_id, []).append(j)
        runs: dict[str, Any] = {r.id: r for r in s.scalars(select(SolverRunRow).where(
            SolverRunRow.id.in_(solver_ids))).all()} if solver_ids else {}
        if fin_ids:
            runs.update({r.id: r for r in s.scalars(select(FinanceRunRow).where(
                FinanceRunRow.id.in_(fin_ids))).all()})
        events: dict[str, list[tuple[int, str]]] = {}
        if solver_ids:
            for rid, seq, typ in s.execute(select(SolverRunEventRow.run_id, SolverRunEventRow.seq,
                                                  SolverRunEventRow.type)
                                           .where(SolverRunEventRow.run_id.in_(solver_ids))).all():
                events.setdefault(rid, []).append((int(seq), typ))
        if fin_ids:
            for rid, seq, typ in s.execute(select(FinanceRunEventRow.run_id, FinanceRunEventRow.seq,
                                                  FinanceRunEventRow.type)
                                           .where(FinanceRunEventRow.run_id.in_(fin_ids))).all():
                events.setdefault(rid, []).append((int(seq), typ))
        ranks: dict[str, list[int]] = {}
        if solver_ids:
            for rid, rank in s.execute(select(ScheduleRow.solver_run_id, ScheduleRow.rank)
                                       .where(ScheduleRow.solver_run_id.in_(solver_ids))).all():
                ranks.setdefault(rid, []).append(int(rank))
        results: dict[str, int] = {}
        if fin_ids:
            for (rid,) in s.execute(select(FinanceResultRow.run_id).where(FinanceResultRow.run_id.in_(fin_ids))):
                results[rid] = results.get(rid, 0) + 1

        lost: set[str] = set()
        dup: set[str] = set()
        for rid in all_ids:
            kind = "solver_run" if rid in solver_ids else "finance_run"
            run = runs.get(rid)
            if run is None:
                v.append(f"{rid}: run row missing")
                lost.add(rid)
                continue
            if run.status != "completed":
                v.append(f"{rid}: status {run.status} (error={run.error!r})")
                lost.add(rid)
            js = jobs.get(rid, [])
            if len(js) != 1:
                v.append(f"{rid}: {len(js)} job rows")
                (dup if len(js) > 1 else lost).add(rid)
            evs = sorted(events.get(rid, []))
            seqs = [e[0] for e in evs]
            if seqs != list(range(1, len(seqs) + 1)):
                v.append(f"{rid}: event seq not contiguous from 1: {seqs[:10]}...")
            n_term = sum(1 for _, t in evs if t in terminal)
            if n_term != 1:
                v.append(f"{rid}: {n_term} terminal events")
                (dup if n_term > 1 else lost).add(rid)
            elif evs[-1][1] not in terminal:
                v.append(f"{rid}: terminal event is not the last ({evs[-1][1]} after it)")
            requeued_events = sum(1 for _, t in evs if t == "run_requeued")
            if kind == "solver_run":
                rk = sorted(ranks.get(rid, []))
                if not rk or rk != list(range(len(rk))):
                    v.append(f"{rid}: schedule ranks {rk} not unique/contiguous from 0")
                    if len(rk) != len(set(rk)):
                        dup.add(rid)
            else:
                n = results.get(rid, 0)
                if n != 1:
                    v.append(f"{rid}: {n} finance results")
                    (dup if n > 1 else lost).add(rid)
            if len(js) == 1:
                j = js[0]
                if j.status != "succeeded":
                    v.append(f"{rid}: job {j.id} status {j.status} (last_error={j.last_error!r})")
                if j.lease_owner not in workers:
                    v.append(f"{rid}: job {j.id} lease_owner {j.lease_owner!r} is not a known worker")
                else:
                    report.jobs_per_worker[j.lease_owner] = report.jobs_per_worker.get(j.lease_owner, 0) + 1
                if j.attempts > 1:
                    report.requeues += j.attempts - 1
                if not chaos and j.attempts != 1:
                    v.append(f"{rid}: job attempts {j.attempts} (expected 1 without chaos)")
                if chaos and j.attempts > 1 and (j.attempts != 2 or requeued_events < 1):
                    v.append(f"{rid}: requeued job has attempts {j.attempts} and {requeued_events} run_requeued events")
                if chaos and j.attempts == 1 and requeued_events:
                    v.append(f"{rid}: run_requeued event but attempts == 1")
                created, started, finished = _aware(j.created_at), _aware(j.started_at), _aware(j.finished_at)
                if created is not None and started is not None:
                    waits.append(max(0.0, (started - created).total_seconds()))
                if started is not None and finished is not None:
                    durations[kind].append(max(0.0, (finished - started).total_seconds()))
                if created is not None and (first_created is None or created < first_created):
                    first_created = created
                if finished is not None and (last_finished is None or finished > last_finished):
                    last_finished = finished
    report.lost = len(lost)
    report.duplicates = len(dup)
    if chaos and report.requeues < 1:
        v.append("chaos: no job was requeued after the worker kill")
    return waits, durations, first_created, last_finished


# ---------------------------------------------------------------- main flow

def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="load_queue.py", description="Load sanity check of the job queue (B 6).")
    p.add_argument("--runs", type=int, default=50)
    p.add_argument("--solver-share", type=float, default=0.5)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--api-url", default=None, help="external API (single_user, same database)")
    p.add_argument("--chaos-kill-after", type=int, default=None, metavar="N")
    p.add_argument("--json", default=None, metavar="FILE")
    p.add_argument("--database-url", default=None, help="default: DATABASE_URL")
    p.add_argument("--log-dir", default=None, help="subprocess logs (default: a new temp dir)")
    p.add_argument("--timeout", type=float, default=None, help="default: max(300, runs*10/workers)")
    a = p.parse_args(argv)
    if a.runs < 1 or not (0.0 <= a.solver_share <= 1.0) or a.workers < 0 or a.concurrency < 1:
        p.error("--runs >= 1, 0 <= --solver-share <= 1, --workers >= 0, --concurrency >= 1")
    return a


def run(argv: list[str] | None = None) -> Report:
    a = parse(argv)
    from superplanner.api.config import is_postgres_url, normalize_database_url

    url = normalize_database_url(a.database_url or os.environ.get("DATABASE_URL") or "")
    if not is_postgres_url(url):
        raise LoadError("set DATABASE_URL (or --database-url) to a disposable postgresql+psycopg:// database")
    if a.workers == 0 and a.api_url is None:
        raise LoadError("--workers 0 needs --api-url (an API with embedded workers)")
    chaos = a.chaos_kill_after is not None
    if chaos and a.workers < 2:
        raise LoadError("--chaos-kill-after needs --workers >= 2 (one survives to finish the jobs)")

    n_solver = math.ceil(a.runs * a.solver_share)
    n_fin = a.runs - n_solver
    report = Report(runs=a.runs, solver_runs=n_solver, finance_runs=n_fin, workers=a.workers,
                    concurrency=a.concurrency, chaos=chaos)
    log_dir = Path(a.log_dir) if a.log_dir else Path(tempfile.mkdtemp(prefix="sp-load-"))
    log_dir.mkdir(parents=True, exist_ok=True)
    env = child_env(url, chaos)
    procs = Procs(log_dir)
    db: Db | None = None
    import httpx

    try:
        from superplanner import migrate

        migrate.upgrade(url)
        if a.api_url:
            base = a.api_url.rstrip("/")
            wait_http(base, None, 30)
        else:
            port = free_port()
            base = f"http://127.0.0.1:{port}"
            api = procs.start("api", [sys.executable, "-m", "uvicorn", "superplanner.api.main:app", "--host",
                                      "127.0.0.1", "--port", str(port), "--no-access-log"], env)
            wait_http(base, api)
        worker_ids = [f"load-w{i}-{uuid.uuid4().hex[:4]}" for i in range(a.workers)]
        workers = {wid: procs.start(wid, [sys.executable, "-m", "superplanner.worker", "--concurrency",
                                          str(a.concurrency), "--id", wid, "--metrics-port", "0"], env)
                   for wid in worker_ids}
        known = set(worker_ids)
        db = Db(url)

        with httpx.Client(base_url=base, timeout=60.0,
                          limits=httpx.Limits(max_connections=HTTP_THREADS * 2)) as client:
            problems, plans = create_plans(client, n_solver, n_fin)
            posts = [Post("solver_run", t, f"load-{uuid.uuid4().hex}") for t in problems]
            posts += [Post("finance_run", t, f"load-{uuid.uuid4().hex}") for t in plans]
            n_replay = max(1, round(len(posts) * 0.10)) if len(posts) >= 2 else 0
            step = max(1, len(posts) // max(1, n_replay))
            replays = [Post(p.kind, p.target, p.key, True) for p in posts[::step][:n_replay]]
            t_enqueue = time.monotonic()
            by_key = enqueue(client, posts + replays)
        report.replays_sent = len(replays)
        kind_of = {p.key: p.kind for p in posts}
        solver_ids, fin_ids = [], []
        for key, got in by_key.items():
            ids = {rid for rid, _ in got}
            if len(ids) != 1:
                report.violations.append(f"key {key}: POSTs returned different run ids {sorted(ids)}")
            if len(got) == 2:
                if len(ids) == 1 and sum(1 for _, rep in got if rep) == 1:
                    report.replays_ok += 1
                elif len(ids) == 1:
                    report.violations.append(f"key {key}: replay without exactly one Idempotent-Replayed header")
            (solver_ids if kind_of[key] == "solver_run" else fin_ids).append(got[0][0])

        timeout = a.timeout or max(300.0, a.runs * 10.0 / max(1, a.workers))
        deadline = time.monotonic() + timeout
        killed = False
        all_ids = solver_ids + fin_ids
        while True:
            for wid, p in workers.items():
                if p.poll() is not None and not (killed and wid == report.killed_worker):
                    report.violations.append(f"worker {wid} exited unexpectedly (code {p.returncode})")
                    raise _Abort()
            succeeded, _ = db.counts(all_ids)
            if chaos and not killed and succeeded >= a.chaos_kill_after:
                owners = db.running_owners()
                victim = next((w for w in worker_ids if owners.get(w)), None)
                if victim is not None:
                    workers[victim].send_signal(signal.SIGKILL)
                    workers[victim].wait(timeout=10)
                    report.killed_worker = victim
                    killed = True
            if db.active_runs(solver_ids, fin_ids) == 0:
                break
            if time.monotonic() > deadline:
                report.violations.append(f"timeout: runs still active after {timeout:.0f}s")
                break
            time.sleep(0.25)
        if chaos and not killed:
            report.violations.append("chaos: no worker held a running job after the threshold; nothing was killed")
        t_done = time.monotonic()
        if a.api_url:   # an external API may run embedded workers (registered in job_workers)
            known |= _external_workers(url)

        waits, durations, first, last = verify(db, report, solver_ids, fin_ids, known, chaos)
        if first is not None and last is not None:
            report.wall_seconds = max(0.0, (last - first).total_seconds())
        else:
            report.wall_seconds = t_done - t_enqueue
        report.throughput_runs_per_min = (a.runs / report.wall_seconds * 60.0) if report.wall_seconds else 0.0
        report.queue_wait_p50_s = round(percentile(waits, 0.5), 3)
        report.queue_wait_p95_s = round(percentile(waits, 0.95), 3)
        report.job_duration_s = {k: {"p50": round(percentile(d, 0.5), 3), "p95": round(percentile(d, 0.95), 3),
                                     "n": float(len(d))} for k, d in durations.items() if d}
        report.wall_seconds = round(report.wall_seconds, 2)
        report.throughput_runs_per_min = round(report.throughput_runs_per_min, 1)
    except _Abort:
        pass
    finally:
        if db is not None:
            db.close()
        procs.stop_all()
    report_logs = str(log_dir)
    if a.json:
        Path(a.json).write_text(json.dumps({**report.to_dict(), "log_dir": report_logs}, indent=2))
    return report


class _Abort(Exception):
    pass


def _external_workers(url: str) -> set[str]:
    from sqlalchemy import select

    from superplanner.api.db import Database, JobWorkerRow
    from superplanner.api.db.ownership import system_scope

    db = Database(url, pool_size=1, max_overflow=0, service="manage")
    try:
        with system_scope(), db.read() as s:
            return set(s.scalars(select(JobWorkerRow.id)).all())
    finally:
        db.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        report = run(argv)
    except LoadError as exc:
        print(f"load_queue: {exc}", file=sys.stderr)
        return 2
    print(report.text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
