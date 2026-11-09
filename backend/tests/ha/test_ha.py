"""S3 (M6-DESIGN 4.2, 9 T-H1 / T-H2, HA2): replica routing with lag check and read-your-writes, replica failure
fallback, 503 DB_UNAVAILABLE on a demoted primary with idempotent retry, readiness refusing a standby."""

from __future__ import annotations

import time

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, make_app
from superplanner.api.db.session import RW_COOKIE, RW_HEADER


def _app(db_url: str, read_url: str | None = None):
    return make_app(db_url, database_read_url=read_url or db_url, replica_max_lag_seconds=5.0)


def test_replica_routing_lag_and_read_your_writes(db_url):
    """T-H1 / HA2: lag 10 s -> primary; fresh -> replica; an unsafe request just made -> primary for 15 s."""
    app = _app(db_url)
    with TestClient(app) as c:
        api = Api(c)
        rep = app.state.ctx.db.replica
        rep.lag_probe = lambda: 0.0
        rep.reset()
        assert api.get("/dashboard")["source"] == "replica"
        rep.lag_probe = lambda: 10.0
        rep.reset()
        assert api.get("/dashboard")["source"] == "primary"
        r = c.get(f"{V1}/health/ready")
        assert r.status_code == 200 and r.json()["replica"] == {"status": "lagging", "lag_seconds": 10.0}
        rep.lag_probe = lambda: 0.0
        rep.reset()
        # an unsafe request sets the marker cookie and header ...
        r = c.post(f"{V1}/mfg/items", json={"part_number": "RYW-1", "make_buy": "buy", "lead_time_days": 5})
        assert r.status_code == 201
        assert RW_COOKIE in r.cookies and float(r.headers[RW_HEADER]) > time.time()
        # ... and while it is present replica-routed reads use the primary
        assert api.get("/dashboard")["source"] == "primary"
        c.cookies.clear()
        assert api.get("/dashboard")["source"] == "replica"
        # token clients send the header back
        r = c.get(f"{V1}/mfg/dashboard", headers={RW_HEADER: str(time.time() + 10)})
        assert r.json()["source"] == "primary"
        r = c.get(f"{V1}/mfg/dashboard", headers={RW_HEADER: str(time.time() - 1)})
        assert r.json()["source"] == "replica"
        # never for anything outside replica_reads (writes, If-Match reads)
        item = api.get("/items", q="RYW-1")["items"][0]
        api.put(f"/items/{item['id']}", {"part_number": "RYW-1", "make_buy": "buy", "lead_time_days": 6},
                item["row_version"])


def test_replica_down_falls_back_to_primary(db_url):
    from sqlalchemy.engine import make_url

    bad = make_url(db_url).set(port=1).render_as_string(hide_password=False)
    app = _app(db_url, bad)
    with TestClient(app) as c:
        t0 = time.monotonic()
        r = c.get(f"{V1}/mfg/dashboard")
        assert r.status_code == 200 and r.json()["source"] == "primary"
        assert time.monotonic() - t0 < 10
        assert c.get(f"{V1}/health/ready").json()["replica"]["status"] == "error"


def test_no_replica_no_marker(db_url):
    with TestClient(make_app(db_url)) as c:
        r = c.post(f"{V1}/mfg/items", json={"part_number": "X-1", "make_buy": "buy", "lead_time_days": 5})
        assert r.status_code == 201 and RW_HEADER not in r.headers and RW_COOKIE not in r.cookies
        assert "replica" not in c.get(f"{V1}/health/ready").json()


def _set_read_only(pg_admin, db_url: str, on: bool) -> None:
    name = sa.engine.make_url(db_url).database
    pg_admin.execute(f'ALTER DATABASE "{name}" SET default_transaction_read_only = {"on" if on else "off"}')


def test_demoted_primary_is_503_and_retry_is_idempotent(db_url, pg_admin):
    """T-H2: a write while the primary answers 25006 -> 503 DB_UNAVAILABLE + Retry-After (never 500); the
    client's retry with the same Idempotency-Key creates exactly one posting."""
    with TestClient(make_app(db_url)) as c:
        api = Api(c)
        it = api.item("HA-1")
        loc = api.location("ST1")
        body = {"type": "receipt_misc", "lines": [{"item_id": it["id"], "location_id": loc["id"], "qty": 5}]}
        _set_read_only(pg_admin, db_url, True)
        try:
            c.app.state.ctx.db.invalidate()
            r = c.post(f"{V1}/mfg/inventory/postings", json=body, headers={"Idempotency-Key": "ha-post-1"})
            assert r.status_code == 503, r.text
            assert r.json()["error"]["code"] == "DB_UNAVAILABLE" and r.headers["Retry-After"] == "5"
            ready = c.get(f"{V1}/health/ready")
            assert ready.status_code in (200, 503)            # read-only DB but not in recovery: no crash
        finally:
            _set_read_only(pg_admin, db_url, False)
        c.app.state.ctx.db.invalidate()
        r1 = c.post(f"{V1}/mfg/inventory/postings", json=body, headers={"Idempotency-Key": "ha-post-1"})
        r2 = c.post(f"{V1}/mfg/inventory/postings", json=body, headers={"Idempotency-Key": "ha-post-1"})
        assert r1.status_code == 201 and r2.status_code in (200, 201) and r2.json()["id"] == r1.json()["id"]
        assert api.get("/inventory/postings")["total"] == 1
        bal = api.get("/inventory/balances", item_id=it["id"])["items"]
        assert sum(b["qty_on_hand"] for b in bal) == 5             # zero lost, no duplicate posting


def test_readiness_refuses_a_standby_write_target(db_url, monkeypatch):
    app = make_app(db_url)
    with TestClient(app) as c:
        assert c.get(f"{V1}/health/ready").status_code == 200
        monkeypatch.setattr(type(app.state.ctx.db), "in_recovery", lambda self: True)
        r = c.get(f"{V1}/health/ready")
        assert r.status_code == 503 and r.json()["database"] == "read_only" and r.json()["status"] == "not_ready"


def test_classify():
    from superplanner.api.ha import classify

    class Orig(Exception):
        def __init__(self, st):
            self.sqlstate = st

    def err(st, cls=sa.exc.DBAPIError):
        return cls("stmt", {}, Orig(st))

    assert classify(err("25006")) == "read_only"
    assert classify(err("57P01")) == "admin_shutdown"
    assert classify(err("08006")) == "connection"
    assert classify(err(None, sa.exc.OperationalError)) == "connection"
    assert classify(err("55P03", sa.exc.OperationalError)) is None       # lock timeout stays MFG_BUSY
    assert classify(err("23505", sa.exc.IntegrityError)) is None
    assert classify(ValueError()) is None
