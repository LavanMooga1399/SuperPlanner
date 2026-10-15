"""Concurrency, optimistic locking and crash recovery (criterion 4.5)."""

from __future__ import annotations

import copy
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

from int_helpers import API, assert_error

BACKEND = Path(__file__).resolve().parents[2]


def _parallel(fns):
    barrier = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def wrap(i, fn):
        barrier.wait()
        out[i] = fn()

    ts = [threading.Thread(target=wrap, args=(i, f)) for i, f in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    return out


def test_int_two_concurrent_run_creations(api, client):
    rec = api.instantiate(jobs=3)
    for _ in range(3):
        res = _parallel([lambda: api.post_run(rec["id"], time_limit_seconds=1)] * 2)
        codes = sorted(r.status_code for r in res)
        assert codes == [202, 409], [r.text for r in res]
        bad = next(r for r in res if r.status_code == 409)
        assert_error(bad, 409, "RUN_ALREADY_ACTIVE")
        ok = next(r for r in res if r.status_code == 202)
        api.wait(ok.json()["run_id"])
    runs = client.get(f"{API}/problems/{rec['id']}/solver-runs").json()["items"]
    assert len(runs) == 3


def test_int_two_concurrent_approvals(api, client):
    rec = api.instantiate(jobs=3)
    pid = rec["id"]
    a = api.solve(pid, strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    b = api.solve(pid, strategy="cpsat", time_limit_seconds=2)["primary_schedule_id"]
    res = _parallel([lambda: api.approve(a), lambda: api.approve(b)])
    assert all(r.status_code in (200, 409) for r in res), [r.text for r in res]
    approved = api.schedules(pid, "approved")
    assert len(approved) == 1
    statuses = sorted(api.schedule(x)["status"] for x in (a, b))
    assert statuses in (["approved", "superseded"], ["approved", "candidate"])


def test_int_optimistic_concurrency(api, client):
    rec = api.instantiate(jobs=2)
    pid = rec["id"]
    doc = copy.deepcopy(rec["problem"])
    # 428 without If-Match, 412 with a stale one
    assert_error(api.put(pid, doc, None), 428)
    err = assert_error(api.put(pid, doc, 5), 412, "VERSION_MISMATCH")
    assert err["details"]["current_version"] == 1
    # two writers with the same base version: exactly one wins
    d1, d2 = copy.deepcopy(doc), copy.deepcopy(doc)
    d1["name"], d2["name"] = "Writer one", "Writer two"
    res = _parallel([lambda: api.put(pid, d1, 1), lambda: api.put(pid, d2, 1)])
    codes = sorted(r.status_code for r in res)
    assert codes == [200, 412], [r.text for r in res]
    winner = next(r for r in res if r.status_code == 200).json()
    cur = api.get(pid)
    assert cur["version"] == 2 and cur["problem"]["name"] == winner["problem"]["name"]
    # all If-Match spellings
    for i, tag in enumerate(['"2"', "2", 'W/"2"']):
        v = 2 + i
        r = api.put(pid, doc, tag.replace("2", str(v)))
        assert r.status_code == 200, (tag, r.text)
        assert r.headers["etag"] == f'"{v + 1}"' and r.json()["version"] == v + 1
    # body id is overwritten
    doc["id"] = "someone-else"
    r = api.put(pid, doc, 5)
    assert r.status_code == 200 and r.json()["problem"]["id"] == pid


def test_int_snapshot_isolation(api, client):
    rec = api.instantiate(jobs=6)
    pid = rec["id"]
    created = api.start_run(pid, strategy="ga", time_limit_seconds=3)
    doc = copy.deepcopy(rec["problem"])
    for t in doc["tasks"]:
        t["duration_minutes"] += 30
    assert api.put(pid, doc, 1).status_code == 200
    run = api.wait(created["run_id"])
    sch = api.schedule(run["primary_schedule_id"])
    orig = {t["id"]: t["duration_minutes"] for t in rec["problem"]["tasks"]}
    for p in sch["placements"]:
        assert p["end"] - p["start"] == orig[p["task_id"]]
    assert sch["base_problem_version"] == 1


def test_int_delete_with_active_run(api, client):
    rec = api.instantiate(jobs=8)
    created = api.start_run(rec["id"], strategy="ga", time_limit_seconds=5)
    assert_error(client.delete(f"{API}/problems/{rec['id']}"), 409)
    client.post(f"{API}/solver-runs/{created['run_id']}/cancel")
    api.wait(created["run_id"])
    assert client.delete(f"{API}/problems/{rec['id']}").status_code == 204
    assert_error(client.get(f"{API}/solver-runs/{created['run_id']}"), 404)


# --------------------------------------------------------------------------- killed server

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(db: Path, port: int) -> subprocess.Popen:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "PORT": str(port)}
    proc = subprocess.Popen([str(BACKEND / "run_api.sh")], cwd=BACKEND, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}{API}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    proc.kill()
    raise AssertionError("server did not start")


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(10)


def test_int_killed_server_recovery(tmp_path):
    db = tmp_path / "crash.db"
    port = _free_port()
    base = f"http://127.0.0.1:{port}{API}"
    proc = _start_server(db, port)
    try:
        rec = httpx.post(f"{base}/templates/manufacturing/instantiate", json={"parameters": {"jobs": 10}}).json()
        run = httpx.post(f"{base}/problems/{rec['id']}/solver-runs",
                         json={"strategy": "ga", "time_limit_seconds": 30}).json()
        deadline = time.monotonic() + 10
        while httpx.get(f"{base}/solver-runs/{run['run_id']}").json()["status"] != "running":
            assert time.monotonic() < deadline
            time.sleep(0.1)
    finally:
        _kill(proc)
    proc = _start_server(db, port)
    try:
        r = httpx.get(f"{base}/solver-runs/{run['run_id']}").json()
        assert r["status"] == "failed", r
        assert r["error"] == "Server restarted before the run finished."
        ev = httpx.get(f"{base}/solver-runs/{run['run_id']}/events?stream=false").json()["items"]
        assert ev[-1]["type"] == "run_failed"
        # the problem accepts new runs again
        r2 = httpx.post(f"{base}/problems/{rec['id']}/solver-runs", json={"time_limit_seconds": 1})
        assert r2.status_code == 202, r2.text
    finally:
        _kill(proc)
