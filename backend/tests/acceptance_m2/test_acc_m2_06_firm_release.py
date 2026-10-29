"""Gate 2 #6: firm/release loop. Release every `release_now` planned order of the latest live run -> re-run -> no
planned order duplicates converted supply (lot-for-lot plant without MOQ: each affected item's planned quantity
drops by exactly the converted quantity); converting the same planned order again -> 409
`MRP_ALREADY_CONVERTED`; converting from an older or a what-if run -> 409 `MRP_RUN_NOT_LATEST`; conversion is
all-or-nothing, idempotent with an `Idempotency-Key`, and exactly-once under two concurrent requests (two real
API processes on PostgreSQL).
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx
import pytest

from accm2_helpers import MRP_ENDPOINTS, Servers, mrp_planned, push_plant
from oracle.build import PB

CONVERT = "POST /mrp/runs/{run_id}/planned-orders/convert"


def loop_plant(today: date):
    b = PB(as_of=today, tag="fr")
    p = b.make("FR-P", lt=2)
    c1 = b.buy("FR-C1", lt=3)
    c2 = b.buy("FR-C2", lt=30)
    b.simple_routing(p)
    b.bom(p, [(c1, 2), (c2, 1)])
    b.stock(c1, 4)
    b.demand(p, 5, today + timedelta(days=6), number="DO-FR-1", priority=1)
    b.demand(p, 3, today + timedelta(days=40), number="DO-FR-2")
    b.demand(c1, 7, today + timedelta(days=5), number="DO-FR-3")
    return b.build()


def planned_qty(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for r in rows:
        out[r["item"]["part_number"]] += r["qty"]
    return dict(out)


def convert(api, run_id: str, ids: list[str], status: int = 201, mode: str = "release", key: str | None = None):
    body = {"mode": mode, "orders": [{"id": i} for i in ids], "pr_grouping": "per_supplier", "add_to_pr_id": None,
            "reserve": False}
    return api.post(f"/mrp/runs/{run_id}/planned-orders/convert", body, status=status,
                    headers={"Idempotency-Key": key} if key else None)


@pytest.fixture
def world(api):
    api.need(*MRP_ENDPOINTS, CONVERT, "GET /work-orders", "GET /purchase-requests")
    today = date.today()
    push_plant(api, loop_plant(today))
    run1 = api.run_mrp(label="live 1")
    assert run1["kind"] == "live" and run1["status"] == "completed", run1
    return api, run1


def test_release_now_orders_convert_once_and_are_supply_on_rerun(world):
    api, run1 = world
    rows1 = mrp_planned(api, run1["id"])
    now = [r for r in rows1 if r["release_status"] == "release_now"]
    assert {r["kind"] for r in now} == {"make", "buy"}, rows1      # plant designed to have both
    # all-or-nothing: one unknown id -> nothing converted
    bad = convert(api, run1["id"], [now[0]["id"], "mpo_" + "0" * 32], status=(404, 422))
    assert bad["error"]["code"] in ("NOT_FOUND", "MFG_UNKNOWN_REFERENCE")
    assert all(r["status"] != "converted" for r in mrp_planned(api, run1["id"]))
    res = convert(api, run1["id"], [r["id"] for r in now], key="conv-acc-1")
    assert {c["planned_order_id"] for c in res["converted"]} == {r["id"] for r in now}
    assert {c["type"] for c in res["converted"]} == {"wo", "pr"}
    # idempotent replay with the same key and body
    again = api.raw("POST", f"/mrp/runs/{run1['id']}/planned-orders/convert",
                    json={"mode": "release", "orders": [{"id": r["id"]} for r in now], "pr_grouping": "per_supplier",
                          "add_to_pr_id": None, "reserve": False}, headers={"Idempotency-Key": "conv-acc-1"})
    assert again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true", again.text
    # same order again (no key) -> 409 with the ids
    err = convert(api, run1["id"], [now[0]["id"]], status=409)
    assert err["error"]["code"] == "MRP_ALREADY_CONVERTED" and now[0]["id"] in err["error"]["details"]["ids"]
    # created documents: released WOs, submitted PRs, source = mrp
    wos = [w for w in api.all_pages("/work-orders") if w["source"] == "mrp"]
    prs = [p for p in api.all_pages("/purchase-requests") if p["source"] == "mrp"]
    assert wos and all(w["status"] == "released" and w["source_run_no"] == run1["run_no"] for w in wos)
    assert prs and all(p["status"] == "submitted" for p in prs)
    rows1 = mrp_planned(api, run1["id"])
    assert all(r["status"] == "converted" and r["converted"]["id"] for r in rows1 if r["id"] in
               {x["id"] for x in now})
    # re-run: converted supply is not planned twice
    run2 = api.run_mrp(label="live 2")
    q1, q2 = planned_qty(rows1), planned_qty(mrp_planned(api, run2["id"]))
    conv: dict[str, float] = defaultdict(float)
    for r in now:
        conv[r["item"]["part_number"]] += r["qty"]
    for pn, q in conv.items():
        assert round(q2.get(pn, 0), 6) == round(q1[pn] - q, 6), (pn, q1, q2, conv)
    # older run / what-if run -> not latest
    rest = [r["id"] for r in rows1 if r["status"] != "converted"]
    if rest:
        assert convert(api, run1["id"], rest[:1], status=409)["error"]["code"] == "MRP_RUN_NOT_LATEST"
    wi = api.run_mrp(label="what-if", include_pr_supply=False)
    assert wi["kind"] == "what_if"
    wrows = mrp_planned(api, wi["id"])
    assert wrows
    assert convert(api, wi["id"], [wrows[0]["id"]], status=409)["error"]["code"] == "MRP_RUN_NOT_LATEST"
    latest = api.get("/mrp/runs/latest")
    assert latest["id"] == run2["id"]
    # firm mode on the latest run: WO planned, PR draft
    rows2 = [r for r in mrp_planned(api, run2["id"]) if r["status"] != "converted"]
    if rows2:
        res = convert(api, run2["id"], [r["id"] for r in rows2], mode="firm")
        for c in res["converted"]:
            doc = api.get(f"/work-orders/{c['id']}") if c["type"] == "wo" else \
                api.get(f"/purchase-requests/{c['id']}")
            assert doc["status"] == ("planned" if c["type"] == "wo" else "draft"), doc


def test_convert_is_exactly_once_under_concurrency(world, db_url, tmp_path):
    api, run1 = world
    rows = mrp_planned(api, run1["id"])
    target = rows[0]["id"]
    srv = Servers(db_url, tmp_path, n=2)
    try:
        body = {"mode": "firm", "orders": [{"id": target}], "pr_grouping": "per_supplier", "add_to_pr_id": None,
                "reserve": False}

        def go(i: int):
            r = httpx.post(f"{srv.bases[i % 2]}/mrp/runs/{run1['id']}/planned-orders/convert", json=body, timeout=60)
            return r.status_code, r.json()

        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(go, range(6)))
    finally:
        logs = srv.close()
    assert "Traceback" not in logs, logs[-4000:]
    ok = [r for r in res if r[0] == 201]
    assert len(ok) == 1, res
    assert all(r[1]["error"]["code"] in ("MRP_ALREADY_CONVERTED", "MFG_BUSY") for r in res if r[0] != 201), res
    docs = [w for w in api.all_pages("/work-orders") if w["source"] == "mrp"] + \
        [p for p in api.all_pages("/purchase-requests") if p["source"] == "mrp"]
    assert len(docs) == 1, docs
