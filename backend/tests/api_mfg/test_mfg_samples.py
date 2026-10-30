"""B3-5: sample load (both modes, idempotent), reset (M1-DESIGN 9.3 #75-77, 10)."""

from __future__ import annotations

import pytest

from apimfg_helpers import Mfg, err, etag, row_counts
from superplanner.mfg import samples


def test_sample_list(mfg: Mfg):
    items = mfg.get("/samples")["items"]
    assert [s["id"] for s in items] == ["small", "medium", "kavach"]
    assert items[0]["counts"]["items"] == 10 and set(items[0]) == {"id", "name", "description", "counts"}


@pytest.mark.parametrize("sid", ["small", "medium", "kavach"])
def test_load_twice_is_unchanged_and_health_ok(mfg: Mfg, sid: str):
    out = mfg.load(sid)
    assert out["sample_id"] == sid and out["health"]["ok"] is True
    exp = samples.counts(sid)
    assert out["result"]["counts"]["items"]["create"] == exp["items"]
    assert out["result"]["counts"]["bom_lines"]["create"] == exp["bom_lines"]
    assert mfg.get("/health", params={"as_of": "2026-11-02", "horizon_days": 90})["ok"] is True
    again = mfg.load(sid)
    assert all(c["create"] == c["update"] == c["delete"] == 0 for c in again["result"]["counts"].values())
    assert again["result"]["data_version"] == out["result"]["data_version"]
    statuses = {b["status"] for i in mfg.get("/items", params={"make_buy": "make", "limit": 5})["items"]
                for b in mfg.get(f"/items/{i['id']}/boms")["items"]}
    assert statuses == {"released"}


def test_replace_resets_first_and_clash_is_409(client, mfg: Mfg):
    mfg.load("small")
    mine = mfg.item("MY-PART")
    item = mfg.by_pn("SM-100")
    bom = mfg.get(f"/items/{item['id']}/boms")["items"][0]
    copy = mfg.post(f"/boms/{bom['id']}/copy", {}, headers=etag(bom["row_version"]))
    body = mfg.get(f"/boms/{copy['id']}")
    mfg.post(f"/boms/{copy['id']}/release", {"effective_from": "2026-06-01", "supersede_previous": True},
             status=200, headers=etag(body["row_version"]))
    e = err(mfg.req("POST", "/samples/small/load", json={"replace": False}), 409, "MFG_IMPORT_HAS_ERRORS")
    assert e["details"]["error_count"] >= 1
    out = mfg.load("small", replace=True)
    assert out["health"]["ok"] is True
    assert "MY-PART" not in [i["part_number"] for i in mfg.get("/items", params={"limit": 200})["items"]]
    assert row_counts(client.app)["mfg_boms"] == 1
    assert mine


def test_reset(client, mfg: Mfg):
    mfg.load("small")
    err(mfg.req("POST", "/reset", json={"confirm": "yes"}), 422, "MFG_RESET_CONFIRM")
    err(mfg.req("POST", "/reset", json={}), 422, "MFG_RESET_CONFIRM")
    out = mfg.post("/reset", {"confirm": "DELETE ALL MANUFACTURING DATA"}, status=200)
    assert out["deleted"]["items"] == 10 and out["deleted"]["plant"] == 1 and len(out["deleted"]) == 18 + 21  # M2: + the 21 M2 data tables
    assert all(v == 0 for v in row_counts(client.app).values())
    err(mfg.req("POST", "/samples/nope/load", json={}), 404, "NOT_FOUND")
