"""M7-DESIGN 12 performance (QP1-QP8 subset), PostgreSQL, measured through the API (TestClient, in-process).
Marked `slow`; prints the measurements (`-s`). Targets are asserted with headroom for slow CI hosts."""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from m7_helpers import World

pytestmark = pytest.mark.slow


def _p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)]


def test_m7_performance(db_url):
    w = World(db_url)
    out: dict[str, str] = {}
    try:
        api = w.owner.api
        loc = api.location("ST")
        it = api.item("P", lot_controlled=True)
        api.receive(it["id"], loc["id"], 10_000, lot_code="L-1")
        lot = api.get("/lots", item_id=it["id"])["items"][0]
        w.part11_on()
        appr = w.member("appr", ["qa_approver"])
        from m7_helpers import signature

        # QP1: signed hold release (argon2 "fast" test profile + hash + insert + chain), 20 runs
        times = []
        for k in range(20):
            h = api.post("/qa/holds", {"lot_id": lot["id"], "reason": f"h{k}"})
            sig = signature(appr, "hold", h["id"], "release", "released")
            t0 = time.perf_counter()
            appr.api.req("POST", f"/qa/holds/{h['id']}/release", 200, json={"signature": sig})
            times.append((time.perf_counter() - t0) * 1000)
        out["QP1 signed action p95 ms"] = f"{_p95(times):.0f} (median {statistics.median(times):.0f})"
        assert _p95(times) < 800

        # QP2: diff + reason overhead of a regulated update (in-process)
        from superplanner.api.audit_diff import diff

        rec = api.get(f"/items/{it['id']}")
        rec2 = {**rec, "description": "changed"}
        t0 = time.perf_counter()
        for _ in range(1000):
            diff(rec, rec2)
        out["QP2 diff per update ms"] = f"{(time.perf_counter() - t0):.3f}"
        assert (time.perf_counter() - t0) < 3.0

        # QP4: 2,000 results with evaluation in one batch
        sc = api.post("/qa/schemes", {"code": "N1000", "name": "N1000", "kind": "fixed", "fixed_n": 1000})
        appr.api.post(f"/qa/schemes/{sc['id']}/approve", {"signature": signature(
            appr, "sampling_scheme", sc["id"], "approve", "approved")}, 200)
        pl = api.post("/qa/plans", {"name": "p", "item_id": it["id"], "scope": "final", "scheme_id": sc["id"],
                                    "characteristics": [
                                        {"seq": 1, "code": "A", "name": "A", "kind": "variable", "severity": "major",
                                         "lsl": 0, "usl": 10},
                                        {"seq": 2, "code": "B", "name": "B", "kind": "attribute",
                                         "severity": "minor"}]})
        h = signature(appr, "inspection_plan", pl["id"], "approve", "approved")
        appr.api.post(f"/qa/plans/{pl['id']}/approve", {"signature": h}, 200)
        il = api.post("/qa/inspection-lots", {"plan_id": pl["id"], "lot_size": 5000},
                      headers={"X-SP-Change-Reason": "perf"})
        c1, c2 = [c["id"] for c in il["characteristics"]]
        rows = [{"characteristic_id": c1, "sample_no": k, "value": 5.0} for k in range(1, 1001)] + \
            [{"characteristic_id": c2, "sample_no": k, "passed": True} for k in range(1, 1001)]
        t0 = time.perf_counter()
        r = api.post(f"/qa/inspection-lots/{il['id']}/results", {"client_batch_id": "perf", "results": rows}, 200)
        ms = (time.perf_counter() - t0) * 1000
        out["QP4 results batch 2,000 ms"] = f"{ms:.0f}"
        assert r["verdict"]["verdict"] == "accept" and ms < 2000

        # QP6: 100,000 inspection lots, filtered page
        eng = sa.create_engine(db_url)
        with eng.begin() as c:
            c.execute(sa.text(
                "INSERT INTO qa_inspection_lots (id, owner_id, number, plan_id, plan_version, scope, item_id, "
                "lot_size, sampling, status, decision_note, hold, source, due_at, row_version, created_at, "
                "updated_at) SELECT 'ilt_' || md5(g::text), :o, 'IL-P' || g, :p, 1, 'final', :i, 10, '{}'::jsonb, "
                "CASE WHEN g % 10 = 0 THEN 'open' ELSE 'accepted' END, '', false, 'manual', now(), 1, now(), now() "
                "FROM generate_series(1, 100000) g"), {"o": w.oid, "p": pl["id"], "i": it["id"]})
            c.execute(sa.text("ANALYZE qa_inspection_lots"))
            c.execute(sa.text(
                "INSERT INTO audit_events (entity_type, entity_id, action, details, created_at, actor_id, owner_id, "
                "reason) SELECT 'mfg_item', :i, 'update', '{}'::jsonb, now(), :o, :o, 'perf' "
                "FROM generate_series(1, 2000)"), {"i": it["id"], "o": w.oid})
        eng.dispose()
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            pg = api.get("/qa/inspection-lots", status="open", scope="final", limit=50)
            times.append((time.perf_counter() - t0) * 1000)
        out["QP6 100k lots filtered page ms"] = f"{min(times):.0f} (total {pg['total']})"
        assert min(times) < 600

        # QP8: record audit trail with 2,000 events
        t0 = time.perf_counter()
        tr = api.get("/audit/record", entity_type="item", entity_id=it["id"], limit=2000)
        ms = (time.perf_counter() - t0) * 1000
        out["QP8 audit trail 2,000 events ms"] = f"{ms:.0f}"
        assert tr["total"] >= 2000 and ms < 1500

        # QP7: equipment block check at floor start (in-process)
        from superplanner.api.db.ownership import bind_owner
        from superplanner.api.mfg.services.qa_equipment import check_line

        bind_owner(w.oid)
        with w.app.state.ctx.db.read() as s:
            t0 = time.perf_counter()
            for _ in range(100):
                check_line(s, "lin_" + "0" * 32, datetime.now(UTC))
            out["QP7 line equipment check ms"] = f"{(time.perf_counter() - t0) * 10:.2f}"
    finally:
        print("\nM7 performance:", out)
        w.close()
