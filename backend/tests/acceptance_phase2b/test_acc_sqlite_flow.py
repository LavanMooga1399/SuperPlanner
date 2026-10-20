"""Scenario (a) of PLAN-PHASE2B 7: SQLite / inline / single_user.

A *real* legacy database is produced by the pre-2b code (git commit 4bd2efc, run in a subprocess) with real runs,
schedules and results; the current app then upgrades it on first start and the full solver + finance + what-if +
replan + approve flow continues on it. Every schedule is re-checked with the engine validator and the independent
checker of tests/integration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acc_helpers import API, BACKEND, FAST_FIN, FIN, load_int_helpers, wait_for
from superplanner import engine
from superplanner.api.config import Settings
from superplanner.api.main import create_app
from superplanner.engine import Placement, Problem

LEGACY_COMMIT = "4bd2efc"

OLD_SCRIPT = r"""
import json, sys, time
from fastapi.testclient import TestClient
from superplanner.api.config import Settings
from superplanner.api.main import create_app
API = "/api/v1"; FIN = API + "/finance"
out = {}
with TestClient(create_app(Settings(database_url=sys.argv[1]))) as c:
    r = c.post(API + "/templates/manufacturing/instantiate",
               json={"start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": 5}})
    pid = r.json()["id"]; out["problem_id"] = pid
    run = c.post(API + f"/problems/{pid}/solver-runs", json={"strategy": "auto", "time_limit_seconds": 2}).json()
    for _ in range(600):
        st = c.get(API + f"/solver-runs/{run['run_id']}").json()
        if st["status"] not in ("queued", "running"): break
        time.sleep(0.1)
    out["run_id"] = run["run_id"]; out["schedule_id"] = st["primary_schedule_id"]
    assert c.post(API + f"/schedules/{st['primary_schedule_id']}/approve", json={}).status_code == 200
    plan = c.post(FIN + "/templates/young_professional/instantiate", json={"start_month": "2026-11"}).json()
    out["plan_id"] = plan["id"]
    fr = c.post(FIN + f"/plans/{plan['id']}/runs", json=json.loads(sys.argv[2])).json()
    for _ in range(600):
        st = c.get(FIN + f"/runs/{fr['run_id']}").json()
        if st["status"] not in ("queued", "running"): break
        time.sleep(0.1)
    out["fin_run_id"] = fr["run_id"]; out["result_id"] = st["result_id"]; out["fin_status"] = st["status"]
print("OUT" + json.dumps(out))
"""


def _legacy_tree(dest: Path) -> Path:
    repo = BACKEND.parent
    try:
        blob = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", LEGACY_COMMIT, "backend/superplanner"],
                              check=True, capture_output=True, timeout=60).stdout
    except (OSError, subprocess.CalledProcessError) as exc:   # pragma: no cover - not a git checkout
        pytest.skip(f"legacy commit {LEGACY_COMMIT} not available: {exc}")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(dest, filter="data")
    return dest / "backend"


def recheck(doc: dict, sch: dict) -> None:
    ih = load_int_helpers()
    pls = [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")} for p in sch["placements"]]
    rep = engine.validate_schedule(Problem.model_validate(doc), [Placement(**p) for p in pls])
    assert rep.feasibility == "feasible", rep.violations
    assert ih.independent_check(doc, pls, sch["horizon_start"]) == []
    assert sch["hard_violation_count"] == 0
    assert len(pls) == len(doc["tasks"])


def wait_run(c: TestClient, path: str, timeout: float = 120) -> dict:
    return wait_for(lambda: (lambda j: j if j["status"] not in ("queued", "running") else None)(c.get(path).json()),
                    timeout, 0.1, what=path)


@pytest.mark.sqlite_only
def test_legacy_file_from_pre_2b_code_upgrades_and_full_flow_continues(tmp_path):
    old = _legacy_tree(tmp_path / "old")
    db_file = tmp_path / "superplanner.db"
    url = f"sqlite:///{db_file}"
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(old), "HOME": str(tmp_path)}
    proc = subprocess.run([sys.executable, "-c", OLD_SCRIPT, url, json.dumps(FAST_FIN)], cwd=str(old), env=env,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    legacy = json.loads(proc.stdout.split("OUT", 1)[1])
    assert legacy["fin_status"] == "completed", legacy

    import sqlite3
    con = sqlite3.connect(db_file)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alembic_version" not in tables and "jobs" not in tables      # really a pre-2b file
    before = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    con.close()

    with TestClient(create_app(Settings(database_url=url))) as c:      # zero-setup defaults: single_user, inline
        sess = c.get(f"{API}/auth/session").json()
        assert sess["auth_mode"] == "single_user" and sess["authenticated"] is True
        assert sess["user"]["id"] == "usr_local"
        backups = list(tmp_path.glob("superplanner.db.bak-0001-*"))
        assert len(backups) == 1, list(tmp_path.iterdir())
        # legacy data is intact and readable
        probs = c.get(f"{API}/problems").json()["items"]
        assert [p["id"] for p in probs] == [legacy["problem_id"]]
        doc = c.get(f"{API}/problems/{legacy['problem_id']}").json()["problem"]
        old_sch = c.get(f"{API}/schedules/{legacy['schedule_id']}").json()
        assert old_sch["status"] == "approved"
        recheck(doc, old_sch)
        old_res = c.get(f"{FIN}/results/{legacy['result_id']}")
        assert old_res.status_code == 200, old_res.text
        # new solver run on the legacy problem
        pid = legacy["problem_id"]
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "auto", "time_limit_seconds": 2})
        assert r.status_code == 202, r.text
        st = wait_run(c, f"{API}/solver-runs/{r.json()['run_id']}")
        assert st["status"] == "completed", st
        for s in c.get(f"{API}/problems/{pid}/schedules").json()["items"]:
            full = c.get(f"{API}/schedules/{s['id']}").json()
            if full["feasibility"] == "feasible":
                recheck(doc, full)
        # replan from the approved legacy schedule, approve the replanned primary
        rp = c.post(f"{API}/schedules/{legacy['schedule_id']}/replan",
                    json={"cutoff": old_sch["placements"][0]["start_at"],
                          "run": {"strategy": "heuristic", "time_limit_seconds": 1}})
        assert rp.status_code == 202, rp.text
        st = wait_run(c, f"{API}/solver-runs/{rp.json()['run_id']}")
        assert st["status"] == "completed", st
        new_sched = st["primary_schedule_id"]
        doc2 = c.get(f"{API}/problems/{pid}").json()["problem"]
        recheck(doc2, c.get(f"{API}/schedules/{new_sched}").json())
        ap = c.post(f"{API}/schedules/{new_sched}/approve", json={})
        assert ap.status_code == 200, ap.text
        assert c.get(f"{API}/schedules/{legacy['schedule_id']}").json()["status"] == "superseded"
        # finance: what-if on the legacy baseline result, compare, CSV, send to planner
        wi = c.post(f"{FIN}/plans/{legacy['plan_id']}/what-if",
                    json={"changes": {"label": "Save more", "extra_monthly_savings": 2000}, "run": FAST_FIN,
                          "base_result_id": legacy["result_id"]})
        assert wi.status_code == 202, wi.text
        wst = wait_run(c, f"{FIN}/runs/{wi.json()['run_id']}")
        assert wst["status"] == "completed", wst
        comp = c.get(f"{FIN}/results/compare", params={"a": legacy["result_id"], "b": wst["result_id"]})
        assert comp.status_code == 200, comp.text
        assert c.get(f"{FIN}/results/{legacy['result_id']}/contributions.csv").status_code == 200
        sent = c.post(f"{FIN}/results/{wst['result_id']}/send-to-planner", json={"months": 6})
        assert sent.status_code == 201, sent.text
        assert c.post(f"{API}/problems/{sent.json()['problem_id']}/validate").json()["ok"] is True

    con = sqlite3.connect(db_file)
    after = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in before}
    owners = {t: {r[0] for r in con.execute(f'SELECT DISTINCT owner_id FROM "{t}"')}
              for t in ("problems", "solver_runs", "schedules", "finance_plans", "finance_runs", "finance_results")}
    jobs = con.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall()
    con.close()
    assert all(after[t] >= before[t] for t in before), (before, after)
    assert all(o == {"usr_local"} for o in owners.values()), owners
    # inline mode writes one job row per run started after the upgrade (3 runs: solver, replan, what-if)
    assert dict(jobs) == {"succeeded": 3}, jobs
    # the backup is a consistent copy of the legacy file
    bcon = sqlite3.connect(backups[0])
    assert bcon.execute("SELECT COUNT(*) FROM problems").fetchone()[0] == before["problems"]
    assert bcon.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    bcon.close()
    shutil.rmtree(old.parent, ignore_errors=True)


@pytest.mark.sqlite_only
def test_inline_api_killed_during_sse_restart_fails_the_run_once(tmp_path):
    """Zero-setup mode: an API killed mid-run (inline thread pool) marks the run failed on the next start
    (RESTART_ERROR), with exactly one terminal event; the reconnected SSE stream ends with it."""
    from acc_helpers import SINGLE, Db, SseReader, check_invariants, start_api

    url = f"sqlite:///{tmp_path / 'inline.db'}"
    api1 = start_api(url, tmp_path, auth="single_user", job_backend="inline", embedded="0")
    try:
        rid = SINGLE.fin_run(api1.url, SINGLE.plan(api1.url),
                             {"time_limit_seconds": 120, "simulation": {"n_paths": 10000}, "compute_fixes": True,
                              "calibration_rounds": 4})
        sse = SseReader(SINGLE, api1.url, f"{FIN}/runs/{rid}/events")
        sse.start()
        wait_for(lambda: SINGLE.run_status(api1.url, rid, "finance")["status"] == "running", 60, what="running")
        wait_for(lambda: len(sse.frames) >= 2, 30, what="frames")
        api1.kill9()
        sse.join(30)
    finally:
        api1.stop()
    api2 = start_api(url, tmp_path, auth="single_user", job_backend="inline", embedded="0")
    try:
        st = SINGLE.run_status(api2.url, rid, "finance")
        assert st["status"] == "failed", st
        assert st["error"]["message"] == "Server restarted before the run finished." if isinstance(st["error"], dict) \
            else "restarted" in str(st["error"]), st
        s2 = SseReader(SINGLE, api2.url, f"{FIN}/runs/{rid}/events", last_event_id=sse.frames[-1]["id"])
        s2.start()
        s2.join(30)
        frames = sse.frames + s2.frames
        assert [f["id"] for f in frames] == list(range(1, len(frames) + 1))
        assert frames[-1]["event"] == "run_failed"
        db = Db(url)
        inv = check_invariants(db, rid, "finance", expect="failed")
        assert inv["job"]["status"] == "failed"
        db.dispose()
    finally:
        api2.stop()
