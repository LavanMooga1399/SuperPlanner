"""List sort keys (demand orders, lots, inventory transactions) and migration 0008_m6 -> 0009_ux -> 0008_m6."""

from __future__ import annotations

import sqlalchemy as sa

from apimfgm2_helpers import Api
from superplanner import migrate
from superplanner.api.mfg.db_models_ux import UX_TABLES


def test_demand_sort_keys(api: Api):
    a = api.item("A")
    b = api.item("B")
    o1 = api.post("/demand-orders", {"demand_type": "customer", "customer": "Zeta", "priority": 3,
                                     "lines": [{"item_id": a["id"], "qty": 1, "due_date": "2026-12-20"}]})
    o2 = api.post("/demand-orders", {"demand_type": "customer", "customer": "Alpha", "priority": 1,
                                     "lines": [{"item_id": b["id"], "qty": 1, "due_date": "2026-12-05"}]})
    o3 = api.post("/demand-orders", {"demand_type": "customer", "customer": "Mid", "priority": 2,
                                     "lines": [{"item_id": a["id"], "qty": 1, "due_date": "2026-12-10"}]})

    def ids(sort: str | None = None) -> list[str]:
        return [x["id"] for x in api.get("/demand-orders", **({"sort": sort} if sort else {}))["items"]]

    assert ids() == ids("number") == [o1["id"], o2["id"], o3["id"]]
    assert ids("-number") == [o3["id"], o2["id"], o1["id"]]
    assert ids("customer") == [o2["id"], o3["id"], o1["id"]]
    assert ids("priority") == [o2["id"], o3["id"], o1["id"]]
    assert ids("due_date") == [o2["id"], o3["id"], o1["id"]]
    assert ids("-due_date") == [o1["id"], o3["id"], o2["id"]]
    assert ids("-created_at")[0] == o3["id"] and len(ids("status")) == 3
    api.err("GET", "/demand-orders", 422, "VALIDATION_ERROR", params={"sort": "bogus"})


def test_lot_and_transaction_sort_keys(api: Api):
    a = api.item("A-LOT", lot_controlled=True)
    b = api.item("B-LOT", lot_controlled=True)
    st = api.location("ST")
    api.receive(b["id"], st["id"], 5, lot_code="L2", expires_on="2027-01-01")
    api.receive(a["id"], st["id"], 7, lot_code="L3", expires_on="2026-12-01")
    api.receive(a["id"], st["id"], 2, lot_code="L1")

    def lots(sort: str | None = None) -> list[str]:
        return [x["lot_code"] for x in api.get("/lots", **({"sort": sort} if sort else {}))["items"]]

    assert lots() == lots("expires_on") == ["L3", "L2", "L1"]
    assert lots("-expires_on") == ["L2", "L3", "L1"]
    assert lots("lot_code") == ["L1", "L2", "L3"] and lots("-lot_code") == ["L3", "L2", "L1"]
    assert lots("part_number")[2] == "L2" and lots("-created_at") == ["L1", "L3", "L2"]

    def txns(sort: str | None = None) -> list[float]:
        return [x["qty"] for x in api.get("/inventory/transactions", **({"sort": sort} if sort else {}))["items"]]

    assert txns() == txns("-seq") == [2, 7, 5] and txns("seq") == [5, 7, 2]
    assert txns("-qty") == [7, 5, 2] and txns("qty") == [2, 5, 7]
    assert txns("part_number") == [2, 7, 5]
    assert len(txns("-txn_date")) == len(txns("txn_date")) == len(txns("txn_type")) == 3
    api.err("GET", "/inventory/transactions", 422, "VALIDATION_ERROR", params={"sort": "bogus"})
    api.err("GET", "/lots", 422, "VALIDATION_ERROR", params={"sort": "bogus"})


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migration_0008_to_0009_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0008_m6")
    t8 = _tables(url)
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0009_ux" and migrate.schema_state(url) == "current"
    assert _tables(url) - t8 == set(UX_TABLES) == {"user_preferences", "mfg_bulk_requests"}
    migrate.run_alembic_downgrade(url, "0008_m6")
    assert _tables(url) == t8
