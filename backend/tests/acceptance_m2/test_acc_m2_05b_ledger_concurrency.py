"""Gate 2 #5 / MP8 on PostgreSQL: 20 threads x 50 postings (receipts, issues, two-line postings in both key orders)
on 5 shared balances, spread over two real API processes. No lost update, no negative stock, no 500, no
deadlock surfacing as an error other than 409 `MFG_BUSY`, exact final balances; concurrent requests with one
`Idempotency-Key` create exactly one posting.
"""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from accm2_helpers import Servers, need_routes

pytestmark = pytest.mark.slow
N_THREADS, PER_THREAD, START = 20, 50, 100


@pytest.fixture
def servers(app, db_url, tmp_path):
    need_routes(app, "POST /locations", "POST /inventory/postings", "GET /inventory/balances",
                "GET /inventory/transactions")
    srv = Servers(db_url, tmp_path, n=2)
    try:
        yield srv.bases
    finally:
        logs = srv.close()
        assert "Traceback" not in logs, logs[-5000:]


def _req(base: str, method: str, path: str, **kw):
    return httpx.request(method, base + path, timeout=60, **kw)


def _setup(base: str) -> tuple[list[str], str]:
    loc = _req(base, "POST", "/locations", json={"code": "STORES", "name": "Stores", "kind": "stores"}).json()["id"]
    items = []
    for i in range(5):
        r = _req(base, "POST", "/items", json={"part_number": f"CC-{i}", "make_buy": "buy", "lead_time_days": 1})
        assert r.status_code == 201, r.text
        items.append(r.json()["id"])
    r = _req(base, "POST", "/inventory/postings", json={"type": "receipt_misc", "lines": [
        {"item_id": i, "location_id": loc, "qty": START} for i in items]})
    assert r.status_code == 201, r.text
    return items, loc


def _balances(base: str, items: list[str], loc: str) -> dict[str, dict]:
    out = {}
    for i in items:
        rows = _req(base, "GET", "/inventory/balances", params={"item_id": i, "location_id": loc}).json()["items"]
        assert len(rows) == 1, rows
        out[i] = rows[0]
    return out


def test_concurrent_postings_on_shared_balances(servers):
    base0 = servers[0]
    items, loc = _setup(base0)
    rng = random.Random(1234)
    jobs = []
    for t in range(N_THREADS):
        for k in range(PER_THREAD):
            a, b = rng.sample(items, 2)
            q1, q2 = rng.randint(1, 6), rng.randint(1, 6)
            kind = rng.choice(["in", "out", "out", "pair"])
            if kind == "in":
                body = {"type": "receipt_misc", "lines": [{"item_id": a, "location_id": loc, "qty": q1}]}
                deltas = {a: q1}
            elif kind == "out":
                body = {"type": "issue_misc", "reason_code": "SCRAP",
                        "lines": [{"item_id": a, "location_id": loc, "qty": q1}]}
                deltas = {a: -q1}
            else:   # two balances in a random order: lock order must be sorted by key server-side (4.5)
                body = {"type": "adjust", "reason_code": "MOVE", "lines": [
                    {"item_id": a, "location_id": loc, "qty": -q1}, {"item_id": b, "location_id": loc, "qty": q2}]}
                deltas = {a: -q1, b: q2}
            jobs.append((servers[(t + k) % 2], body, deltas))

    def go(job):
        base, body, deltas = job
        r = _req(base, "POST", "/inventory/postings", json=body)
        return r.status_code, (r.json().get("error", {}).get("code") if r.status_code != 201 else None), deltas

    t0 = time.perf_counter()
    with ThreadPoolExecutor(N_THREADS) as ex:
        results = list(ex.map(go, jobs))
    elapsed = time.perf_counter() - t0
    statuses = Counter((s, c) for s, c, _ in results)
    assert all(s in (201, 409) for s, _c, _d in results), statuses
    assert {c for s, c, _ in results if s == 409} <= {"INV_INSUFFICIENT_STOCK", "MFG_BUSY"}, statuses
    assert statuses[(201, None)] >= len(jobs) * 0.5, statuses
    expected = defaultdict(float, {i: START for i in items})
    for s, _c, deltas in results:
        if s == 201:
            for i, q in deltas.items():
                expected[i] += q
    final = _balances(base0, items, loc)
    for i in items:
        assert final[i]["qty_on_hand"] == expected[i], (i, final[i]["qty_on_hand"], expected[i])
        assert final[i]["qty_on_hand"] >= 0
    # every successful posting is in the ledger exactly once, sums match
    txns, offset = [], 0
    while True:
        page = _req(base0, "GET", "/inventory/transactions", params={"limit": 200, "offset": offset}).json()
        txns += page["items"]
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            break
    sums = defaultdict(float)
    for t in txns:
        sums[t["item"]["id"]] += t["qty"]
    assert dict(sums) == {i: expected[i] for i in items}
    assert len({t["seq"] for t in txns}) == len(txns)
    assert elapsed < 10, f"MP8: {len(jobs)} postings took {elapsed:.1f} s"


def test_concurrent_requests_with_one_idempotency_key(servers):
    base0 = servers[0]
    items, loc = _setup(base0)
    body = {"type": "receipt_misc", "lines": [{"item_id": items[0], "location_id": loc, "qty": 11}]}

    def go(i):
        r = _req(servers[i % 2], "POST", "/inventory/postings", json=body, headers={"Idempotency-Key": "race-1"})
        return r.status_code, r.headers.get("Idempotent-Replay"), (r.json().get("id") if r.status_code < 300 else
                                                                   r.json()["error"]["code"])

    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(go, range(10)))
    created = [x for x in res if x[0] == 201]
    replays = [x for x in res if x[0] == 200]
    assert len(created) == 1, res
    assert all(x[1] == "true" and x[2] == created[0][2] for x in replays), res
    assert all(x[0] in (200, 201) or x[2] == "MFG_BUSY" for x in res), res
    assert _balances(base0, items, loc)[items[0]]["qty_on_hand"] == START + 11
