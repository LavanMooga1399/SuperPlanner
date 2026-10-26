"""B1-5: a write waiting behind a held plant lock answers 409 `MFG_BUSY` with `Retry-After` (PostgreSQL only,
M1-DESIGN 6.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from apimfg_helpers import Mfg, err, make_app
from superplanner.api.db.ownership import system_scope
from superplanner.api.mfg.db_models import MfgPlantRow


@pytest.mark.postgres_only
def test_lock_timeout_is_mfg_busy(db_url):
    app = make_app(db_url)
    with TestClient(app) as c:
        m = Mfg(c)
        m.item("FIRST")                                     # plant row exists
        db = app.state.ctx.db
        db.engine.dispose()

        @event.listens_for(db.engine, "connect")
        def _short(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("SET lock_timeout = 200")
            cur.close()
            dbapi_conn.commit()

        holder = db.engine.connect()
        tx = holder.begin()
        try:
            with system_scope():
                holder.execute(select(MfgPlantRow.id).with_for_update())
            r = c.post("/api/v1/mfg/items", json={"part_number": "SECOND", "make_buy": "buy"})
            err(r, 409, "MFG_BUSY")
            assert r.headers["Retry-After"] == "5"
        finally:
            tx.rollback()
            holder.close()
        assert c.post("/api/v1/mfg/items", json={"part_number": "SECOND", "make_buy": "buy"}).status_code == 201
        with holder.engine.connect() as x:
            assert x.execute(text("SELECT 1")).scalar() == 1
