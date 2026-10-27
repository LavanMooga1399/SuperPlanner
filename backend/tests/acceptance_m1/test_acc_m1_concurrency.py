"""WP-D adversarial: concurrent edits against two real API processes (uvicorn subprocesses) on one database
(PostgreSQL). Optimistic locking must give exactly one winner, natural keys and cycle checks must
hold across processes (plant lock, M 6.1), and nothing may answer 500."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

from accm1_helpers import RESET

BACKEND = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.slow


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servers(db_url: str, tmp_path: Path) -> Iterator[list[str]]:
    procs, bases = [], []
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SP_", "DATABASE_URL", "AUTH_", "JOB_"))}
    env.update(DATABASE_URL=db_url, AUTH_MODE="single_user", JOB_BACKEND="inline", RUN_WORKERS="1",
               PYTHONPATH=str(BACKEND))
    for i in range(2):
        port = _port()
        log = open(tmp_path / f"api{i}.log", "wb")
        procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "superplanner.api.main:app", "--host",
                                       "127.0.0.1", "--port", str(port)], cwd=BACKEND, env=env, stdout=log,
                                      stderr=subprocess.STDOUT))
        bases.append(f"http://127.0.0.1:{port}/api/v1/mfg")
        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert procs[-1].poll() is None, (tmp_path / f"api{i}.log").read_text()[-3000:]
            assert time.monotonic() < deadline, "API did not start"
            time.sleep(0.2)
    try:
        yield bases
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
        logs = "".join((tmp_path / f"api{i}.log").read_text(errors="replace") for i in range(2))
        assert "Traceback" not in logs, logs[-5000:]


def _req(base: str, method: str, path: str, **kw: Any) -> httpx.Response:
    return httpx.request(method, base + path, timeout=120, **kw)


def _race(calls: list[tuple[str, str, str, dict[str, Any]]]) -> list[httpx.Response]:
    with ThreadPoolExecutor(len(calls)) as ex:
        return list(ex.map(lambda c: _req(c[0], c[1], c[2], **c[3]), calls))


def _item_body(rec: dict[str, Any], **change: Any) -> dict[str, Any]:
    drop = {"id", "row_version", "created_at", "updated_at", "has_bom", "has_routing", "used_in_count"}
    return {**{k: v for k, v in rec.items() if k not in drop}, **change}


def test_concurrent_edits_across_two_processes(servers: list[str]):
    a, b = servers
    assert _req(a, "POST", "/samples/small/load", json={"replace": False}).status_code == 200

    # 1. same item, same If-Match, 8 writers over both processes -> exactly one 200, the rest 412
    it = next(i for i in _req(a, "GET", "/items", params={"q": "SM-LBL-01"}).json()["items"])
    calls = [(servers[k % 2], "PUT", f"/items/{it['id']}",
              {"json": _item_body(it, description=f"writer {k}"), "headers": {"If-Match": f'"{it["row_version"]}"'}})
             for k in range(8)]
    codes = Counter(r.status_code for r in _race(calls))
    assert codes == {200: 1, 412: 7}, codes
    now = _req(b, "GET", f"/items/{it['id']}").json()
    assert now["row_version"] == it["row_version"] + 1 and now["description"].startswith("writer ")

    # 2. same natural key created concurrently -> one 201, the rest 409 MFG_DUPLICATE_KEY
    calls = [(servers[k % 2], "POST", "/items", {"json": {"part_number": "RACE-1", "make_buy": "buy",
                                                           "lead_time_days": 3, "description": str(k)}})
             for k in range(8)]
    rs = _race(calls)
    assert Counter(r.status_code for r in rs) == {201: 1, 409: 7}, [r.text[:200] for r in rs]
    assert all(r.json()["error"]["code"] == "MFG_DUPLICATE_KEY" for r in rs if r.status_code == 409)
    assert _req(a, "GET", "/items", params={"q": "RACE-1"}).json()["total"] == 1

    # 3. two drafts that would close a cycle only together, saved at the same time -> at most one succeeds
    for _ in range(3):
        x = _req(a, "POST", "/items", json={"part_number": f"CY-X-{_}", "make_buy": "make"}).json()
        y = _req(b, "POST", "/items", json={"part_number": f"CY-Y-{_}", "make_buy": "make"}).json()
        bx = _req(a, "POST", "/boms", json={"item_id": x["id"], "lines": []}).json()
        by = _req(b, "POST", "/boms", json={"item_id": y["id"], "lines": []}).json()
        calls = [(a, "PUT", f"/boms/{bx['id']}", {"json": {"item_id": x["id"], "revision": bx["revision"],
                                                          "version": bx["version"], "lines": [
                                                              {"find_number": "10", "child_item_id": y["id"],
                                                               "qty_per": 1}]},
                                                 "headers": {"If-Match": f'"{bx["row_version"]}"'}}),
                 (b, "PUT", f"/boms/{by['id']}", {"json": {"item_id": y["id"], "revision": by["revision"],
                                                          "version": by["version"], "lines": [
                                                              {"find_number": "10", "child_item_id": x["id"],
                                                               "qty_per": 1}]},
                                                 "headers": {"If-Match": f'"{by["row_version"]}"'}})]
        rs = _race(calls)
        got = sorted(r.status_code for r in rs)
        assert got == [200, 422], [r.text[:300] for r in rs]
        assert next(r for r in rs if r.status_code == 422).json()["error"]["code"] == "MFG_BOM_CYCLE"
    h = _req(a, "GET", "/health", params={"as_of": "2026-11-02"}).json()
    assert "MFG_BOM_CYCLE" not in h["by_code"], h["by_code"]

    # 4. sample loads, an import commit and reset racing: every call answers 2xx/409, data stays consistent
    data = b"part_number,make_buy,lead_time_days\nIMP-1,buy,4\nIMP-2,buy,5\n"
    rec = _req(a, "POST", "/imports", params={"filename": "i.csv", "sheet": "items"}, content=data,
               headers={"content-type": "application/octet-stream"}).json()
    rec = _req(a, "PUT", f"/imports/{rec['id']}/mapping",
               json={"sheets": {"items": rec["sheets"][0]["suggested"]}, "options": {}},
               headers={"If-Match": '"1"'}).json()
    calls = [(a, "POST", "/samples/medium/load", {"json": {"replace": False}}),
             (b, "POST", "/samples/medium/load", {"json": {"replace": False}}),
             (b, "POST", f"/imports/{rec['id']}/commit", {"json": {}, "headers": {"If-Match": '"2"'}}),
             (a, "POST", f"/imports/{rec['id']}/commit", {"json": {}, "headers": {"If-Match": '"2"'}})]
    rs = _race(calls)
    assert all(r.status_code in (200, 409, 412) for r in rs), [(r.status_code, r.text[:300]) for r in rs]
    assert [r.status_code for r in rs[:2]].count(200) >= 1
    commits = [r for r in rs[2:]]
    assert sorted(r.status_code for r in commits)[0] == 200, [r.text[:300] for r in commits]
    s = _req(b, "GET", "/summary").json()["counts"]
    assert s["items"] == 10 + 1 + 6 + 2 + 171, s           # small + RACE-1 + 6 cycle items + 2 imported + medium
    # a second medium load is all unchanged
    again = _req(a, "POST", "/samples/medium/load", json={"replace": False}).json()["result"]["counts"]
    assert all(v.get("create", 0) == v.get("update", 0) == 0 for v in again.values()), again
    assert _req(b, "POST", "/reset", json=RESET).status_code == 200
    assert _req(a, "GET", "/summary").json()["counts"]["items"] == 0
