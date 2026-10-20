"""Scenarios (b)-(d) of PLAN-PHASE2B 7 with real processes (PostgreSQL, JOB_BACKEND=queue, AUTH_MODE=accounts):
uvicorn API subprocesses and `python -m superplanner.worker` subprocesses on one database. Every finished run is
checked from the database against invariants I1-I4 (PHASE2B 2.4) and job/run status agreement."""

from __future__ import annotations

import random
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from acc_helpers import (API, FAST_FIN, FAST_SOLVER, FIN, SLOW_FIN, SseReader, User, check_invariants,
                         load_int_helpers, start_api, start_worker, wait_for)

pytestmark = pytest.mark.postgres_only

GA = {"strategy": "ga", "time_limit_seconds": 8, "ga": {"max_generations": 10000, "stagnation_generations": 1000}}


def job_running(db, run_id: str, owner: str | None = None) -> bool:
    j = db.job(run_id)
    return j["status"] == "running" and (owner is None or j["lease_owner"] == owner)


def run_started(db, run_id: str, kind: str) -> bool:
    return db.run(run_id, kind)["status"] == "running"


def events_path(run_id: str, kind: str) -> str:
    return f"{API}/solver-runs/{run_id}/events" if kind == "solver" else f"{FIN}/runs/{run_id}/events"


def assert_frames_contiguous(frames: list[dict], total: int) -> None:
    ids = [f["id"] for f in frames]
    assert ids == list(range(1, total + 1)), ids
    assert frames[-1]["event"] in ("run_completed", "run_cancelled", "run_failed"), frames[-1]


# ---------------------------------------------------------------- (b) two users, two worker processes

def test_two_users_concurrent_runs_two_workers_exactly_once(db_url, db, tmp_path, procs):
    api = start_api(db_url, tmp_path)
    procs.append(api)
    w1 = start_worker(db_url, tmp_path, "--concurrency", "2", name="w-one")
    w2 = start_worker(db_url, tmp_path, "--concurrency", "2", name="w-two")
    procs += [w1, w2]
    ana, ben = User("ana@example.com"), User("ben@example.com")
    ana.sign_up(api.url)
    ben.sign_up(api.url)
    owned: dict[str, dict[str, list[str]]] = {}
    for u in (ana, ben):
        pids = [u.problem(api.url) for _ in range(5)]        # one active run per problem / plan (existing rule)
        plans = [u.plan(api.url) for _ in range(5)]          # one active baseline run per plan (existing rule)
        owned[u.email] = {"problem": pids, "plan": plans, "solver": [], "finance": []}

    def submit(u: User, kind: str, i: int) -> None:
        o = owned[u.email]
        if kind == "solver":
            o["solver"].append(u.solver_run(api.url, o["problem"][i], {**FAST_SOLVER, "seed": i}))
        else:
            o["finance"].append(u.fin_run(api.url, o["plan"][i], {**FAST_FIN, "seed": i}))

    tasks = [(u, k, i) for u in (ana, ben) for k in ("solver", "finance") for i in range(5)]
    random.Random(7).shuffle(tasks)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda t: submit(*t), tasks))
    total = 0
    owners_seen = set()
    ih = load_int_helpers()
    for u in (ana, ben):
        other = ben if u is ana else ana
        o = owned[u.email]
        for kind in ("solver", "finance"):
            for rid in o[kind]:
                st = u.wait_run(api.url, rid, kind, timeout=180)
                assert st["status"] == "completed", st
                inv = check_invariants(db, rid, kind, expect="completed")
                assert inv["job"]["attempts"] == 1 and inv["starts"] == 1 and inv["requeues"] == 0, inv["types"]
                owners_seen.add(inv["job"]["lease_owner"])
                assert inv["run"]["owner_id"] == u.user_id
                # the other user cannot see it
                path = f"{API}/solver-runs/{rid}" if kind == "solver" else f"{FIN}/runs/{rid}"
                assert other.get(api.url, path).status_code == 404
                total += 1
        # lists show exactly the own runs
        runs = [r["id"] for pid in o["problem"] for r in
                u.get(api.url, f"{API}/problems/{pid}/solver-runs").json()["items"]]
        assert sorted(runs) == sorted(o["solver"])
        fruns = [r["id"] for plan in o["plan"] for r in
                 u.get(api.url, f"{FIN}/plans/{plan}/runs").json()["items"]]
        assert sorted(fruns) == sorted(o["finance"])
        assert sorted(p["id"] for p in u.get(api.url, f"{API}/problems").json()["items"]) == sorted(o["problem"])
        assert sorted(p["id"] for p in u.get(api.url, f"{FIN}/plans").json()["items"]) == sorted(o["plan"])
        # every stored schedule is valid for its problem
        for pid in o["problem"]:
            doc = u.get(api.url, f"{API}/problems/{pid}").json()["problem"]
            for s in u.get(api.url, f"{API}/problems/{pid}/schedules").json()["items"]:
                sch = u.get(api.url, f"{API}/schedules/{s['id']}").json()
                assert sch["feasibility"] == "feasible", sch["feasibility"]
                pls = [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")} for p in sch["placements"]]
                assert ih.independent_check(doc, pls, sch["horizon_start"]) == []
        # owner stamping on worker-written rows
        for t, col in (("schedules", "solver_run_id"), ("finance_results", "run_id")):
            ids = o["solver"] if t == "schedules" else o["finance"]
            rows = db.rows(f"SELECT DISTINCT owner_id FROM {t} WHERE {col} = ANY(:ids)", ids=ids)
            assert [r["owner_id"] for r in rows] == [u.user_id], (t, rows)
    assert total == 20
    assert owners_seen <= {"w-one", "w-two"} and owners_seen, owners_seen
    assert db.one("SELECT count(*) AS n FROM jobs")["n"] == 20


# ---------------------------------------------------------------- (c) worker kill -9 mid-run

@pytest.mark.parametrize("kind", ["solver", "finance"])
def test_kill_9_worker_mid_run_sse_continues_and_run_completes_once(db_url, db, tmp_path, procs, kind):
    api = start_api(db_url, tmp_path)
    procs.append(api)
    w1 = start_worker(db_url, tmp_path, "--concurrency", "1", name="victim")
    procs.append(w1)
    u = User("kill@example.com")
    u.sign_up(api.url)
    rid = (u.solver_run(api.url, u.problem(api.url, jobs=8), GA) if kind == "solver"
           else u.fin_run(api.url, u.plan(api.url), SLOW_FIN))
    sse = SseReader(u, api.url, events_path(rid, kind))
    sse.start()
    wait_for(lambda: run_started(db, rid, kind) and job_running(db, rid, "victim"), 60, what="victim running")
    time.sleep(1.0)
    w1.kill9()
    w2 = start_worker(db_url, tmp_path, "--concurrency", "1", name="rescuer")
    procs.append(w2)
    st = u.wait_run(api.url, rid, kind, timeout=240)
    assert st["status"] == "completed", st
    sse.join(30)
    assert sse.ended.is_set() and sse.error is None, sse.error
    inv = check_invariants(db, rid, kind, expect="completed")
    assert inv["job"]["attempts"] == 2 and inv["job"]["lease_owner"] == "rescuer", inv["job"]
    assert inv["requeues"] == 1 and inv["starts"] == 2, inv["types"]
    assert_frames_contiguous(sse.frames, len(inv["types"]))
    assert [f["event"] for f in sse.frames] == inv["types"]


# ---------------------------------------------------------------- (c) API restart during SSE

@pytest.mark.parametrize("how", ["sigkill", "sigterm"])
def test_api_restart_during_sse_with_separate_worker(db_url, db, tmp_path, procs, how):
    api1 = start_api(db_url, tmp_path)
    procs.append(api1)
    w = start_worker(db_url, tmp_path, "--concurrency", "2", name="steady")
    procs.append(w)
    u = User("restart@example.com")
    u.sign_up(api1.url)
    runs = [(u.solver_run(api1.url, u.problem(api1.url, jobs=8), GA), "solver"),
            (u.fin_run(api1.url, u.plan(api1.url), SLOW_FIN), "finance")]
    readers = [SseReader(u, api1.url, events_path(r, k)) for r, k in runs]
    for s in readers:
        s.start()
    for r, k in runs:
        wait_for(lambda: run_started(db, r, k), 60, what="running")
    wait_for(lambda: all(len(s.frames) >= 2 for s in readers), 30, what="first SSE frames")
    if how == "sigkill":
        api1.kill9()
    else:
        api1.stop(signal.SIGTERM, timeout=30)
    for s in readers:
        s.join(30)
        assert s.ended.is_set()
    api2 = start_api(db_url, tmp_path)
    procs.append(api2)
    for (r, k), s in zip(runs, readers):
        last = s.frames[-1]["id"]
        if s.frames[-1]["event"] in ("run_completed", "run_cancelled", "run_failed"):
            frames = s.frames
        else:
            s2 = SseReader(u, api2.url, events_path(r, k), last_event_id=last)   # same cookie, new instance
            s2.start()
            s2.join(240)
            assert s2.ended.is_set() and s2.error is None and s2.status == 200, (s2.status, s2.error)
            frames = s.frames + s2.frames
        inv = check_invariants(db, r, k, expect="completed")
        assert_frames_contiguous(frames, len(inv["types"]))
        assert inv["job"]["attempts"] == 1 and inv["requeues"] == 0, inv["types"]   # worker was never disturbed


def test_api_with_embedded_workers_killed_mid_run_next_instance_reclaims(db_url, db, tmp_path, procs):
    api1 = start_api(db_url, tmp_path, embedded="1")
    procs.append(api1)
    u = User("embedded@example.com")
    u.sign_up(api1.url)
    rid = u.fin_run(api1.url, u.plan(api1.url), SLOW_FIN)
    wait_for(lambda: run_started(db, rid, "finance"), 60, what="running in API 1")
    owner1 = db.job(rid)["lease_owner"]
    api1.kill9()
    api2 = start_api(db_url, tmp_path, embedded="1")
    procs.append(api2)
    sse = SseReader(u, api2.url, events_path(rid, "finance"), last_event_id=0)
    sse.start()
    st = u.wait_run(api2.url, rid, "finance", timeout=240)
    assert st["status"] == "completed", st
    sse.join(30)
    inv = check_invariants(db, rid, "finance", expect="completed")
    assert inv["job"]["attempts"] == 2 and inv["job"]["lease_owner"] != owner1, inv["job"]
    assert inv["requeues"] == 1, inv["types"]
    assert_frames_contiguous(sse.frames, len(inv["types"]))


def test_api_with_embedded_workers_sigterm_requeues_without_using_an_attempt(db_url, db, tmp_path, procs):
    api1 = start_api(db_url, tmp_path, embedded="1", WORKER_SHUTDOWN_GRACE_SECONDS="0.5")
    procs.append(api1)
    u = User("graceful@example.com")
    u.sign_up(api1.url)
    rid = u.fin_run(api1.url, u.plan(api1.url), SLOW_FIN)
    wait_for(lambda: run_started(db, rid, "finance"), 60, what="running in API 1")
    api1.stop(signal.SIGTERM, timeout=60)
    j = db.job(rid)
    assert j["status"] == "queued", j
    assert db.run(rid, "finance")["status"] == "queued"
    w = start_worker(db_url, tmp_path, "--concurrency", "1", name="after")
    procs.append(w)
    api2 = start_api(db_url, tmp_path)
    procs.append(api2)
    st = u.wait_run(api2.url, rid, "finance", timeout=240)
    assert st["status"] == "completed", st
    inv = check_invariants(db, rid, "finance", expect="completed")
    assert inv["requeues"] == 1 and inv["job"]["lease_owner"] == "after", (inv["types"], inv["job"])
    # graceful shutdown does not count as a failed attempt (B 2.9): attempts counts claims, max not reduced
    assert inv["job"]["attempts"] <= 2


# ---------------------------------------------------------------- two workers racing for one job

def test_two_workers_race_for_single_jobs_each_claimed_once(db_url, db, tmp_path, procs):
    api = start_api(db_url, tmp_path)
    procs.append(api)
    u = User("race@example.com")
    u.sign_up(api.url)
    pid, plan = u.problem(api.url, jobs=4), u.plan(api.url)
    # round 0: job queued before either worker exists, then both start at the same moment
    first = u.solver_run(api.url, pid, FAST_SOLVER)
    ws = [start_worker(db_url, tmp_path, "--concurrency", "1", name=n) for n in ("racer-a", "racer-b")]
    procs += ws
    rids = [first]
    u.wait_run(api.url, first, "solver", timeout=60)
    # rounds 1..12: one job at a time while both workers are idle and woken together by NOTIFY
    for i in range(12):
        rid = (u.solver_run(api.url, pid, {**FAST_SOLVER, "seed": i}) if i % 2 == 0
               else u.fin_run(api.url, plan, FAST_FIN))
        rids.append(rid)
        u.wait_run(api.url, rid, "solver" if i % 2 == 0 else "finance", timeout=60)
    winners = []
    for n, rid in enumerate(rids):
        kind = "solver" if n == 0 or (n - 1) % 2 == 0 else "finance"
        inv = check_invariants(db, rid, kind, expect="completed")
        assert inv["job"]["attempts"] == 1 and inv["starts"] == 1 and inv["requeues"] == 0, (rid, inv["types"])
        winners.append(inv["job"]["lease_owner"])
    assert set(winners) <= {"racer-a", "racer-b"}
    for w in ws:
        assert w.alive(), w.log_text()[-2000:]


# ---------------------------------------------------------------- (d) cancel: queued / running / finishing

def test_cancel_while_queued_is_never_claimed(db_url, db, tmp_path, procs):
    api = start_api(db_url, tmp_path)               # no worker yet
    procs.append(api)
    u = User("cq@example.com")
    u.sign_up(api.url)
    srid = u.solver_run(api.url, u.problem(api.url), FAST_SOLVER)
    frid = u.fin_run(api.url, u.plan(api.url), FAST_FIN)
    for rid, path in ((srid, f"{API}/solver-runs/{srid}/cancel"), (frid, f"{FIN}/runs/{frid}/cancel")):
        r = u.post(api.url, path)
        assert r.status_code == 202, r.text
    w = start_worker(db_url, tmp_path, "--concurrency", "2", name="late")
    procs.append(w)
    time.sleep(3)
    for rid, kind in ((srid, "solver"), (frid, "finance")):
        inv = check_invariants(db, rid, kind, expect="cancelled")
        assert inv["job"]["attempts"] == 0 and inv["job"]["lease_owner"] is None, inv["job"]
        assert inv["types"] == ["run_queued", "run_cancelled"], inv["types"]
    # a second cancel of a terminal run does not change anything
    r = u.post(api.url, f"{API}/solver-runs/{srid}/cancel")
    assert r.status_code in (202, 409), r.text
    assert check_invariants(db, srid, "solver", expect="cancelled")["types"] == ["run_queued", "run_cancelled"]


@pytest.mark.parametrize("kind", ["solver", "finance"])
def test_cancel_while_running_from_another_api_instance(db_url, db, tmp_path, procs, kind):
    api1, api2 = start_api(db_url, tmp_path), start_api(db_url, tmp_path)
    procs += [api1, api2]
    w = start_worker(db_url, tmp_path, "--concurrency", "1", name="busy")
    procs.append(w)
    u = User("cr@example.com")
    u.sign_up(api1.url)
    rid = (u.solver_run(api1.url, u.problem(api1.url, jobs=8), {**GA, "time_limit_seconds": 30}) if kind == "solver"
           else u.fin_run(api1.url, u.plan(api1.url), SLOW_FIN))
    sse = SseReader(u, api1.url, events_path(rid, kind))
    sse.start()
    wait_for(lambda: run_started(db, rid, kind), 60, what="running")
    time.sleep(1.0)
    path = f"{API}/solver-runs/{rid}/cancel" if kind == "solver" else f"{FIN}/runs/{rid}/cancel"
    t0 = time.monotonic()
    r = u.post(api2.url, path)
    assert r.status_code == 202, r.text
    st = u.wait_run(api2.url, rid, kind, timeout=30)
    elapsed = time.monotonic() - t0
    assert st["status"] == "cancelled", st
    assert elapsed < 5, elapsed                     # B 2.7: cancel observed within JOB_CANCEL_POLL + slack
    sse.join(30)
    inv = check_invariants(db, rid, kind, expect="cancelled")
    assert inv["job"]["attempts"] == 1, inv["job"]
    assert [f["event"] for f in sse.frames] == inv["types"]


def test_cancel_racing_completion_never_breaks_invariants(db_url, db, tmp_path, procs):
    api = start_api(db_url, tmp_path)
    procs.append(api)
    w = start_worker(db_url, tmp_path, "--concurrency", "2", name="fin")
    procs.append(w)
    u = User("cf@example.com")
    u.sign_up(api.url)
    pid, plan = u.problem(api.url, jobs=4), u.plan(api.url)
    rng = random.Random(11)
    outcomes: dict[str, int] = {}
    cancel_codes: dict[int, int] = {}

    def start(kind: str, i: int) -> str:
        return (u.solver_run(api.url, pid, {**FAST_SOLVER, "seed": i}) if kind == "solver"
                else u.fin_run(api.url, plan, {**FAST_FIN, "seed": i}))

    # measure how long a run takes from "running" (as seen by polling) to terminal, per kind
    duration: dict[str, float] = {}
    for kind in ("solver", "finance"):
        rid = start(kind, 99)
        wait_for(lambda: db.run(rid, kind)["status"] != "queued", 30, 0.01, what="claimed")
        t0 = time.monotonic()
        u.wait_run(api.url, rid, kind, timeout=60)
        duration[kind] = time.monotonic() - t0
    for i in range(24):
        kind = "solver" if i % 2 == 0 else "finance"
        rid = start(kind, i)
        wait_for(lambda: db.run(rid, kind)["status"] != "queued", 30, 0.01, what="claimed")
        # aim at the end of the run: the cancel lands just before, during or just after the final write
        time.sleep(rng.uniform(0.5, 1.1) * duration[kind])
        path = f"{API}/solver-runs/{rid}/cancel" if kind == "solver" else f"{FIN}/runs/{rid}/cancel"
        code = u.post(api.url, path).status_code
        cancel_codes[code] = cancel_codes.get(code, 0) + 1
        assert code in (202, 409), code
        st = u.wait_run(api.url, rid, kind, timeout=60)
        assert st["status"] in ("completed", "cancelled"), st
        inv = check_invariants(db, rid, kind)
        outcomes[f"{kind}:{inv['run']['status']}"] = outcomes.get(f"{kind}:{inv['run']['status']}", 0) + 1
        # I4: a terminal job never changes again
        j1 = db.job(rid)
        time.sleep(0.3)
        j2 = db.job(rid)
        assert (j1["status"], j1["updated_at"], j1["attempts"]) == (j2["status"], j2["updated_at"], j2["attempts"])
    print("cancel race outcomes", outcomes, "cancel codes", cancel_codes, "durations", duration)
    assert sum(outcomes.values()) == 24
    # the race was really exercised: some cancels won, some arrived after completion
    assert cancel_codes.get(202, 0) >= 1 and any(k.endswith(":cancelled") for k in outcomes), (outcomes, cancel_codes)
