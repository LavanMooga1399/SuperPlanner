"""Claim / lease / reaper / fencing / requeue / shutdown semantics of the PostgreSQL queue (PHASE2B 2.4-2.9;
plan Q2-2..Q2-6, Q2-8 and the transient-error retry). In-process: embedded `WorkerLoop`s and manual claims."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from jobs_helpers import (FAST_LEASE, BlockingRunPlan, assert_one_terminal_last, fin_events, fin_plan, fin_results,
                          fin_run, fin_status, job_of, make_app, wait_fin, wait_for)
from superplanner import finance as finance_module
from superplanner.api.db.ownership import system_scope
from superplanner.api.finance import run_service as finance_run_service
from superplanner.jobs import pg
from superplanner.jobs.types import WORKER_LOST_ERROR, LeaseLost
from superplanner.jobs.worker import WorkerLoop


KINDS = ["solver_run", "finance_run"]


def _app(db_url, **overrides):
    settings = dict(FAST_LEASE, worker_embedded=0)
    settings.update(overrides)
    return make_app(db_url, **settings)


def _claim(ctx, worker_id="test-worker"):
    token = pg.new_token()
    with system_scope(), ctx.db.write() as s:
        c = pg.claim(s, KINDS, worker_id, token, ctx.settings.job_lease_seconds)
    return None if c is None else pg.lease_from_claim(c, token)


def _expire(ctx, lease):
    """Wait until the lease is past its expiry by the DB clock."""
    wait_for(lambda: _expired(ctx, lease.job_id), timeout=10, what="lease expiry")


def _expired(ctx, job_id):
    from sqlalchemy import text

    with system_scope(), ctx.db.read() as s:
        return bool(s.scalar(text("SELECT lease_expires_at < now() FROM jobs WHERE id = :id"), {"id": job_id}))


def _loop(ctx, **kw):
    loop = WorkerLoop(ctx, concurrency=kw.pop("concurrency", 1), kinds=KINDS, embedded=True, **kw)
    loop.start()
    return loop


# ---------------------------------------------------------------- Q2-2

def test_concurrent_claimers_claim_every_job_exactly_once(db_url):
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        run_ids = [fin_run(c, fin_plan(c)) for _ in range(30)]
        claims: list[tuple[str, str]] = []
        lock = threading.Lock()
        barrier = threading.Barrier(3)

        def claimer(n):
            barrier.wait()
            while True:
                lease = _claim(ctx, f"w{n}")
                if lease is None:
                    return
                with lock:
                    claims.append((lease.run_id, f"w{n}"))

        threads = [threading.Thread(target=claimer, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert sorted(r for r, _ in claims) == sorted(run_ids)
        assert len({r for r, _ in claims}) == 30
        for rid in run_ids:
            j = job_of(ctx, rid)
            assert j.status == "running" and j.attempts == 1 and j.lease_token is not None
        assert len({w for _, w in claims}) >= 2   # really concurrent (SKIP LOCKED, not serialised)


# ---------------------------------------------------------------- Q2-3

def test_expired_lease_is_requeued_by_the_reaper_and_completes_once(db_url):
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        lease = _claim(ctx)               # a worker claims ... and dies (no heartbeat)
        assert lease is not None and lease.run_id == rid and lease.attempt == 1
        assert pg.reap_expired(ctx) == {}  # not expired yet
        _expire(ctx, lease)
        assert pg.reap_expired(ctx) == {"queued": 1}
        j = job_of(ctx, rid)
        assert j.status == "queued" and j.lease_token is None and j.last_error == "lease_expired"
        requeued = [e for e in fin_events(ctx, rid) if e["type"] == "run_requeued"]
        assert len(requeued) == 1
        assert requeued[0]["attempt"] == 2 and requeued[0]["max_attempts"] == 3
        assert requeued[0]["reason"] == "lease_expired" and requeued[0]["retry_at"].endswith("Z")
        loop = _loop(ctx)
        try:
            run = wait_fin(c, rid)
        finally:
            loop.stop(1)
        assert run["status"] == "completed"
        j = job_of(ctx, rid)
        assert j.status == "succeeded" and j.attempts == 2 and j.lease_owner == loop.worker_id
        assert fin_results(ctx, rid) == 1
        assert_one_terminal_last(fin_events(ctx, rid))


# ---------------------------------------------------------------- Q2-4

def test_max_attempts_of_expiries_fail_the_run_with_worker_lost(db_url):
    with TestClient(_app(db_url, job_max_attempts=2)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        first = _claim(ctx)
        _expire(ctx, first)
        assert pg.reap_expired(ctx) == {"queued": 1}
        second = wait_for(lambda: _claim(ctx), timeout=5, what="the backoff to pass")
        assert second.attempt == 2
        _expire(ctx, second)
        assert pg.reap_expired(ctx) == {"failed": 1}
        run = fin_status(c, rid)
        assert run["status"] == "failed" and run["error"] == WORKER_LOST_ERROR.format(n=2)
        assert run["error"] == "The run was interrupted 2 times and was stopped."
        events = fin_events(ctx, rid)
        assert [e["type"] for e in events].count("run_failed") == 1
        assert_one_terminal_last(events)
        j = job_of(ctx, rid)
        assert j.status == "failed" and j.attempts == 2 and j.finished_at is not None and j.lease_token is None
        assert pg.reap_expired(ctx) == {}  # I4: terminal jobs never change again
        assert _claim(ctx) is None


# ---------------------------------------------------------------- Q2-5

def test_stale_lease_cannot_write_after_takeover(db_url):
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        stale = _claim(ctx)
        _expire(ctx, stale)
        pg.reap_expired(ctx)
        fresh = wait_for(lambda: _claim(ctx, "w2"), timeout=5, what="the backoff to pass")
        assert fresh.attempt == 2 and fresh.token != stale.token
        n_before = len(fin_events(ctx, rid))
        with system_scope():
            with pytest.raises(LeaseLost):
                with ctx.db.write() as s:
                    stale.fence(s)
            with pytest.raises(LeaseLost):
                with ctx.db.write() as s:
                    stale.finish(s, "succeeded")
            with pytest.raises(LeaseLost):
                with ctx.db.write() as s:
                    finance_run_service.add_event(s, rid, "progress", {"stage": "x"}, 0.0, lease=stale)
            with pytest.raises(LeaseLost):   # the whole handler: its start transaction is fenced
                finance_run_service.run_job(ctx, rid, stale)
        assert len(fin_events(ctx, rid)) == n_before   # nothing from the stale holder
        assert job_of(ctx, rid).lease_token == fresh.token
        with system_scope():
            finance_run_service.run_job(ctx, rid, fresh)
        assert fin_status(c, rid)["status"] == "completed"
        j = job_of(ctx, rid)
        assert j.status == "succeeded" and j.attempts == 2 and j.lease_owner == "w2"
        with system_scope(), pytest.raises(LeaseLost):   # a stale finish after the terminal write
            with ctx.db.write() as s:
                stale.finish(s, "cancelled")
        assert fin_results(ctx, rid) == 1
        assert_one_terminal_last(fin_events(ctx, rid))


# ---------------------------------------------------------------- Q2-6

def test_lost_heartbeat_is_not_a_cancel(db_url, monkeypatch):
    blocker = BlockingRunPlan(block=1)
    monkeypatch.setattr(finance_module, "run_plan", blocker)
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        loop = WorkerLoop(ctx, concurrency=1, kinds=KINDS, embedded=True)
        real_renew, real_check = loop._renew_one, loop._check

        def renew(lease):
            if lease.attempt == 1:
                raise OperationalError("UPDATE jobs", {}, Exception("connection lost"))
            return real_renew(lease)

        def check(leases):
            if any(lease.attempt == 1 for lease in leases):
                raise OperationalError("SELECT jobs", {}, Exception("connection lost"))
            return real_check(leases)

        monkeypatch.setattr(loop, "_renew_one", renew)
        monkeypatch.setattr(loop, "_check", check)
        loop.start()
        try:
            assert blocker.entered.wait(20)
            assert blocker.released.wait(20)   # the lease was treated as lost -> engine told to stop
            run = wait_fin(c, rid, timeout=60)
        finally:
            loop.stop(1)
        assert run["status"] == "completed"
        types = [e["type"] for e in fin_events(ctx, rid)]
        assert "run_cancelled" not in types
        requeued = [e for e in fin_events(ctx, rid) if e["type"] == "run_requeued"]
        assert [e["reason"] for e in requeued] == ["lease_expired"] and requeued[0]["attempt"] == 2
        j = job_of(ctx, rid)
        assert j.status == "succeeded" and j.attempts == 2 and not j.cancel_requested
        assert fin_results(ctx, rid) == 1
        assert_one_terminal_last(fin_events(ctx, rid))


# ---------------------------------------------------------------- Q2-8

def test_graceful_shutdown_requeues_without_consuming_an_attempt(db_url, monkeypatch):
    blocker = BlockingRunPlan(block=1)
    monkeypatch.setattr(finance_module, "run_plan", blocker)
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        first = _loop(ctx)
        assert blocker.entered.wait(20)
        wait_for(lambda: fin_status(c, rid)["status"] == "running", what="run running")
        first.stop(0.3)
        assert blocker.released.wait(5)
        j = job_of(ctx, rid)
        assert j.status == "queued" and j.attempts == 0 and j.lease_token is None
        assert j.last_error == "worker_shutdown"
        run = fin_status(c, rid)
        assert run["status"] == "queued" and run["cancel_requested"] is False
        events = fin_events(ctx, rid)
        assert events[-1]["type"] == "run_requeued"
        assert events[-1]["reason"] == "worker_shutdown" and events[-1]["attempt"] == 1
        assert "run_cancelled" not in [e["type"] for e in events]
        second = _loop(ctx)
        try:
            run = wait_fin(c, rid)
        finally:
            second.stop(1)
        assert run["status"] == "completed"
        j = job_of(ctx, rid)
        assert j.status == "succeeded" and j.attempts == 1 and j.lease_owner == second.worker_id
        assert fin_results(ctx, rid) == 1
        assert_one_terminal_last(fin_events(ctx, rid))


# ---------------------------------------------------------------- transient DB error -> retry

def test_transient_db_error_requeues_and_retries(db_url, monkeypatch):
    calls = []

    def flaky(run_id):
        calls.append(run_id)
        if len(calls) == 1:
            raise OperationalError("INSERT INTO finance_results", {}, Exception("server closed the connection"))

    monkeypatch.setattr(finance_run_service, "_before_final_write", flaky)
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        loop = _loop(ctx)
        try:
            run = wait_fin(c, rid)
        finally:
            loop.stop(1)
        assert run["status"] == "completed" and len(calls) == 2
        requeued = [e for e in fin_events(ctx, rid) if e["type"] == "run_requeued"]
        assert [e["reason"] for e in requeued] == ["transient_error"]
        j = job_of(ctx, rid)
        assert j.status == "succeeded" and j.attempts == 2
        assert fin_results(ctx, rid) == 1
        assert_one_terminal_last(fin_events(ctx, rid))


def test_engine_error_is_not_retried(db_url, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(finance_module, "run_plan", boom)
    with TestClient(_app(db_url)) as c:
        ctx = c.app.state.ctx
        rid = fin_run(c, fin_plan(c))
        loop = _loop(ctx)
        try:
            run = wait_fin(c, rid)
            time.sleep(0.3)
        finally:
            loop.stop(1)
        assert run["status"] == "failed" and run["error"] == "engine exploded"
        j = job_of(ctx, rid)
        assert j.status == "failed" and j.attempts == 1 and j.last_error == "engine exploded"
        assert_one_terminal_last(fin_events(ctx, rid))
