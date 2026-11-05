"""M5 performance (M5-DESIGN 11: AP1 bearer overhead, IP2 outbox overhead, IP3 pull of 1,000 events). `-m slow`."""

from __future__ import annotations

import statistics
import time

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, V1, Api, acc_app, sign_up
from superplanner.identity import crypto

pytestmark = pytest.mark.slow


def _t(fn, n):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return statistics.median(xs)


def test_m5_perf(db_url, capsys):
    app = acc_app(db_url, secrets_keys=[crypto.new_key()])
    with TestClient(app):
        c = sign_up(app, "perf@example.com")
        tok = c.post(f"{V1}/tokens", json={"name": "p", "scopes": ["view", "inventory", "master_edit",
                                                                    "integration.read"]}).json()["token"]
        b = TestClient(app)
        b.headers["Authorization"] = f"Bearer {tok}"
        cookie = _t(lambda: c.get(f"{MFG}/plant"), 200)
        bearer = _t(lambda: b.get(f"{MFG}/plant"), 200)
        api = Api(c)
        loc = api.location("ST")
        it = api.item("X1")
        post = lambda: api.receive(it["id"], loc["id"], 1)  # noqa: E731
        off = _t(post, 60)
        c.put(f"{V1}/integration/settings", json={"enabled": True, "plant_code": "P", "sor": {"items": "superplanner"}},
              headers={"If-Match": '"0"'})
        on = _t(post, 60)
        oid = c.get(f"{V1}/auth/session").json()["user"]["id"]
        eng = sa.create_engine(db_url)
        with eng.begin() as conn:
            conn.execute(sa.text("INSERT INTO int_outbox (id, owner_id, type, entity_ref, data, actor_id, occurred_at) "
                                 "SELECT 'evt_' || md5(g::text), :o, 'inventory.posting', 'X', "
                                 "'{\"lines\": [{\"qty\": 1}]}'::jsonb, :o, now() FROM generate_series(1, 1000) g"),
                         {"o": oid})
        eng.dispose()
        pull = _t(lambda: b.get(f"{V1}/integration/events", params={"limit": 1000}), 10)
        assert len(b.get(f"{V1}/integration/events", params={"limit": 1000}).json()["items"]) == 1000
    with capsys.disabled():
        print(f"\nM5 perf: AP1 bearer-cookie {bearer - cookie:+.2f} ms (cookie {cookie:.2f}, bearer {bearer:.2f}); "
              f"IP2 outbox {on - off:+.2f} ms per posting (off {off:.2f}, on {on:.2f}); IP3 pull 1000 {pull:.1f} ms")
