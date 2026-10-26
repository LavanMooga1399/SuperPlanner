"""B4: performance targets P2-P11 and statement counts (M1-DESIGN 12; PLAN-M1 B2-4, B4). Both dialects; the
PostgreSQL time limits are x 1.5 (except P7). Statement counts wrap the HTTP call in single_user mode, where
`require_user` issues no SQL, so they are the service's statements (BEGIN/COMMIT excluded)."""

from __future__ import annotations

import io
import math
import time
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apimfg_helpers import Mfg, count_statements, etag, make_app
from superplanner.api.mfg.services import imports as imports_service
from superplanner.mfg import samples
from superplanner.mfg.io import export

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def kavach_app(db_url_factory_module):
    app = make_app(db_url_factory_module("apimfg_perf"))
    with TestClient(app) as c:
        m = Mfg(c)
        t = time.monotonic()
        out = m.load("kavach")
        app.state.p9 = time.monotonic() - t
        assert out["health"]["ok"]
        yield app


def _limit(db_kind: str, seconds: float) -> float:
    return seconds * (1.5 if db_kind == "postgres" else 1.0)


def _timed(c: TestClient, method: str, url: str, **kw: Any) -> tuple[Any, float, int]:
    with count_statements(c.app) as seen:
        t = time.monotonic()
        r = c.request(method, "/api/v1/mfg" + url, **kw)
        dt = time.monotonic() - t
    assert r.status_code < 300, r.text[:500]
    print(f"[perf] {method} {url.split('?')[0]}: {dt:.3f} s, {len(seen)} statements")
    return r, dt, len(seen)


def test_p9_sample_load(kavach_app, db_kind):
    print(f"[perf] P9 kavach sample load: {kavach_app.state.p9:.3f} s")
    assert kavach_app.state.p9 < _limit(db_kind, 10.0), kavach_app.state.p9


def test_p2_p3_explosion_and_where_used(kavach_app, db_kind):
    c = TestClient(kavach_app)
    m = Mfg(c)
    top = m.by_pn("KV-TPU-1000")
    r, dt, n = _timed(c, "GET", f"/items/{top['id']}/explosion", params={"on": "2026-11-02"})
    L = r.json()["totals"]["max_level"]
    assert dt < _limit(db_kind, 1.0), dt
    assert n <= 3 * (L + 1) + 3, n
    r, dt, n = _timed(c, "GET", f"/items/{top['id']}/explosion")            # default `on`: +1 plant read
    assert n <= 3 * (L + 1) + 3, n
    cap = m.by_pn("KV-CAP-0402-100N")
    r, dt, n = _timed(c, "GET", f"/items/{cap['id']}/where-used", params={"mode": "indented"})
    lv = max(x["level"] for x in r.json()["rows"])
    assert len(r.json()["rows"]) >= 10
    assert dt < _limit(db_kind, 0.3), dt
    assert n <= 3 * lv + 2, (n, lv)


def test_p5_p10_p11_health_export_windows(kavach_app, db_kind):
    c = TestClient(kavach_app)
    _r, dt, n = _timed(c, "GET", "/health", params={"as_of": "2026-11-02"})
    assert dt < _limit(db_kind, 2.0) and n <= 20, (dt, n)
    _r, dt, n = _timed(c, "GET", "/export", params={"format": "xlsx"})
    assert dt < _limit(db_kind, 5.0) and n <= 20, (dt, n)
    line = next(x for x in Mfg(c).get("/lines")["items"] if x["code"] == "SMT-2")
    _r, dt, n = _timed(c, "GET", f"/lines/{line['id']}/windows", params={"from": "2026-11-01", "to": "2027-01-02"})
    assert dt < _limit(db_kind, 0.1) and n <= 6, (dt, n)


def test_p4_items_page_with_search(db_url_factory, db_kind):
    app = make_app(db_url_factory("apimfg_p4"))
    with TestClient(app) as c:
        rows = "\n".join(f"P-{i:05d},buy,{i % 90},Part number {i}" for i in range(10_000))
        data = ("part_number,make_buy,lead_time_days,description\n" + rows + "\n").encode()
        m = Mfg(c)
        rec = m.req("POST", "/imports", 201, params={"filename": "i.csv", "sheet": "items"}, content=data,
                    headers={"content-type": "application/octet-stream"}).json()
        mp = {"sheets": {"items": rec["sheets"][0]["suggested"]}, "options": {}}
        p = m.put(f"/imports/{rec['id']}/mapping", mp, 1)
        m.post(f"/imports/{rec['id']}/commit", {}, status=200, headers=etag(p["row_version"]))
        r, dt, n = _timed(c, "GET", "/items", params={"q": "number 12", "limit": 50})
        assert r.json()["total"] == 111 and len(r.json()["items"]) == 50
        assert dt < _limit(db_kind, 0.15) and n <= 5, (dt, n)


def _big_bundle() -> dict[str, list[dict[str, Any]]]:
    """1,000 items (40 make) + 4,000 BOM lines = 5,000 rows."""
    items = [{"part_number": f"MK-{i:03d}", "make_buy": "make"} for i in range(40)]
    items += [{"part_number": f"BY-{i:04d}", "make_buy": "buy", "lead_time_days": 10} for i in range(960)]
    lines = [{"parent_part_number": f"MK-{p:03d}", "find_number": str(10 * (k + 1)),
              "child_part_number": f"BY-{(p * 37 + k) % 960:04d}", "qty_per": 1 + k % 3}
             for p in range(40) for k in range(100)]
    return {"items": items, "bom_lines": lines}


def _zip(bundle: dict[str, list[dict[str, Any]]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rows in bundle.items():
            cols = list(dict.fromkeys(k for r in rows for k in r))
            text = ",".join(cols) + "\n" + "\n".join(",".join(str(r.get(k, "")) for k in cols) for r in rows)
            z.writestr(f"{name}.csv", text + "\n")
    return buf.getvalue()


def test_p6_p7_p8_import_5000_rows(db_url_factory, db_kind, monkeypatch):
    held: list[float] = []
    real = imports_service.write_tx

    from contextlib import contextmanager

    @contextmanager
    def timed_tx(ctx, **kw):
        t = time.monotonic()
        with real(ctx, **kw) as v:
            yield v
        held.append(time.monotonic() - t)

    monkeypatch.setattr(imports_service, "write_tx", timed_tx)
    app = make_app(db_url_factory("apimfg_p7"))
    data = _zip(_big_bundle())
    with TestClient(app) as c:
        m = Mfg(c)
        rec = m.req("POST", "/imports", 201, params={"filename": "big.zip"}, content=data,
                    headers={"content-type": "application/octet-stream"}).json()
        mp = {"sheets": {s["name"]: s["suggested"] for s in rec["sheets"]}, "options": {}}
        r, dt, n = _timed(c, "PUT", f"/imports/{rec['id']}/mapping", json=mp, headers=etag(1))
        assert r.json()["preview"]["ok"] and r.json()["preview"]["counts"]["bom_lines"]["create"] == 4000
        assert dt < _limit(db_kind, 4.0) and n <= 25, (dt, n)
        held.clear()
        t = time.monotonic()
        r = m.req("POST", f"/imports/{rec['id']}/commit", 200, json={}, headers=etag(2))
        total = time.monotonic() - t
        assert r.json()["result"]["counts"]["items"]["create"] == 1000
        print(f"[perf] P7 commit 5,000 rows: {total:.3f} s, write tx {max(held):.3f} s")
        assert total < 10.0 and max(held) < 6.0, (total, held)
        rec = m.req("POST", "/imports", 201, params={"filename": "big.zip"}, content=data,
                    headers={"content-type": "application/octet-stream"}).json()
        p = m.put(f"/imports/{rec['id']}/mapping", mp, 1)
        t = time.monotonic()
        with count_statements(app) as seen:
            r = m.req("POST", f"/imports/{rec['id']}/commit", 200, json={}, headers=etag(p["row_version"]))
        dt = time.monotonic() - t
        print(f"[perf] P8 re-import 5,000 rows: {dt:.3f} s")
        assert dt < _limit(db_kind, 5.0), dt
        writes = [s for s in seen if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        assert all("mfg_imports" in s or "audit_events" in s or "mfg_plant" in s for s in writes), writes
        assert r.json()["result"]["counts"]["bom_lines"]["unchanged"] == 4000


def test_p2_kavach_x2(db_url_factory, db_kind):
    app = make_app(db_url_factory("apimfg_x2"))
    bundle = samples.scale("kavach", 2)
    assert len(bundle["bom_lines"]) >= 4000
    with TestClient(app) as c:
        m = Mfg(c)
        data = export.bundle_to_csv_zip(bundle)
        rec = m.req("POST", "/imports", 201, params={"filename": "x2.zip"}, content=data,
                    headers={"content-type": "application/octet-stream"}).json()
        mp = {"sheets": {s["name"]: s["suggested"] for s in rec["sheets"]}, "options": {}}
        p = m.put(f"/imports/{rec['id']}/mapping", mp, 1)
        assert p["preview"]["ok"], p["preview"]["row_errors"][:3]
        m.post(f"/imports/{rec['id']}/commit", {}, status=200, headers=etag(p["row_version"]))
        for pn in ("KV-TPU-1000", "KV2-TPU-1000"):
            top = m.by_pn(pn)
            r, dt, n = _timed(c, "GET", f"/items/{top['id']}/explosion", params={"on": "2026-11-02"})
            L = r.json()["totals"]["max_level"]
            assert dt < _limit(db_kind, 1.5), dt
            assert n <= 3 * (L + 1) + 3 + math.ceil(r.json()["totals"]["distinct_items"] / 2000), n
