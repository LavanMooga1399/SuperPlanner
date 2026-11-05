"""M5 performance, remaining targets (M5-DESIGN 11): IP1, IP2 (repeat), IP4, IP5, AP2, TP1, TP2, BF1, EP1.
`-m slow`; numbers are printed and recorded in 15.WP-S."""

from __future__ import annotations

import json
import resource
import statistics
import threading
import time
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, V1, Api, make_app
from superplanner.api.db.ownership import owner_scope, system_scope
from superplanner.identity import crypto
from test_integration import DNS, Int, _enable, fake_getaddrinfo

pytestmark = pytest.mark.slow
OUT: list[str] = []


def _rec(msg: str) -> None:
    OUT.append(msg)
    print("M5 PERF", msg, flush=True)


def _wait_batch(it: Int, bid: str, timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = it.req("GET", f"/batches/{bid}", 200).json()
        if b["status"] in ("completed", "failed"):
            return b
        time.sleep(0.2)
    raise AssertionError("batch timeout")


def _batch(it: Int, entity: str, recs: list, key: str) -> tuple[dict, float]:
    t = time.perf_counter()
    r = it.req("POST", "/batches", None, json={"schema": "superplanner.v1", "entity": entity, "records": recs},
               headers={"Idempotency-Key": key})
    assert r.status_code in (200, 202), r.text[:500]
    b = r.json()
    if r.status_code == 202:
        b = _wait_batch(it, b["id"])
    return b, time.perf_counter() - t


def test_ip1_ip5_ip2_ip4(db_url, tmp_path, monkeypatch):
    DNS.clear()
    DNS["erp.example.com"] = ["93.184.216.34"]
    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    lat: list[float] = []

    def post(url, body, headers):
        ev = json.loads(body)
        lat.append(time.time() - datetime.fromisoformat(ev["occurred_at"].replace("Z", "+00:00")).timestamp())
        return 200, ""

    app = make_app(db_url, secrets_keys=[crypto.new_key()], webhook_post=post, integration_root=str(tmp_path),
                   retention_enabled=False)
    with TestClient(app) as c:
        it, api = Int(c), Api(c)
        _enable(it, filedrop_enabled=True, sor={"stock": "erp"})
        # IP1: 10,000 items, 50 % unchanged
        first = [{"ref": f"E{i:05d}", "part_number": f"IP1-{i:05d}", "description": "x"} for i in range(5000)]
        _b, t_first = _batch(it, "item", first, "ip1a")
        recs = first + [{"ref": f"E{i:05d}", "part_number": f"IP1-{i:05d}", "description": "x"}
                        for i in range(5000, 10000)]
        b, t = _batch(it, "item", recs, "ip1b")
        assert b["counts"] == {"unchanged": 5000, "created": 5000}, b["counts"]
        _rec(f"IP1 10,000 items (50% unchanged) {t:.1f} s (first 5,000 new: {t_first:.1f} s)")
        # IP5: 20,000-row stock file (2,000 items x 10 locations), stock SoR erp -> count postings
        locs = [api.location(f"L{k}") for k in range(10)]
        lines = ["part_number,location_code,qty"] + [f"IP1-{i:05d},L{k},{(i % 7) + 1}" for i in range(2000)
                                                     for k in range(10)]
        from superplanner.integration import scheduler

        ctx = app.state.ctx
        scheduler.tick(ctx)
        time.sleep(0.5)
        inbox = tmp_path / "HBL1" / "inbox"
        (inbox / "stock_full.csv").write_text("\n".join(lines) + "\n")
        polls = 0
        t0 = time.perf_counter()
        t_commit = None
        while polls < 4:
            polls += 1
            scheduler.tick(ctx)
            for _ in range(2400):
                with system_scope(), ctx.db.read() as s:
                    busy = s.execute(sa.text("SELECT 1 FROM maintenance_runs WHERE status IN ('queued', "
                                             "'running') LIMIT 1")).first()
                if busy is None:
                    break
                time.sleep(0.05)
            if (tmp_path / "HBL1" / "archive" / "stock_full.csv").exists():
                t_commit = json.loads((tmp_path / "HBL1" / "archive" / "stock_full.csv.result.json")
                                      .read_text())["duration_ms"] / 1000
                break
        assert t_commit is not None, list((tmp_path / "HBL1").rglob("*"))
        _rec(f"IP5 20,000-row stock file picked up at poll {polls} (<= 2), committed in {t_commit:.1f} s "
             f"(wall incl. polls {time.perf_counter() - t0:.1f} s)")
        del locs
        # IP2 repeated: outbox overhead per posting (integration on vs off), same posting
        st = api.location("ST")
        it.batch("item", [{"ref": "IP2X", "part_number": "IP2-X"}], "ip2x")
        x = api.by_pn("IP2-X")
        p = lambda: api.receive(x["id"], st["id"], 1)  # noqa: E731

        def med(n: int) -> float:
            xs = []
            for _ in range(n):
                t = time.perf_counter()
                p()
                xs.append((time.perf_counter() - t) * 1000)
            return statistics.median(xs)

        on1 = med(60)
        cur = it.req("GET", "/settings", 200).json()
        it.req("PUT", "/settings", 200, json={**{k: cur[k] for k in ("plant_code", "goods_receipts_owner",
                                                                    "filedrop_enabled", "export_enabled",
                                                                    "export_interval_minutes")},
                                              "enabled": False, "sor": {}}, headers={"If-Match": f'"{cur["row_version"]}"'})
        off = med(60)
        cur = it.req("GET", "/settings", 200).json()
        it.req("PUT", "/settings", 200, json={**{k: cur[k] for k in ("plant_code", "goods_receipts_owner",
                                                                    "filedrop_enabled", "export_enabled",
                                                                    "export_interval_minutes")},
                                              "enabled": True, "sor": {"stock": "erp"}},
               headers={"If-Match": f'"{cur["row_version"]}"'})
        on2 = med(60)
        # emit cost alone (in the business session)
        from superplanner.api.mfg.services.inventory import posting_record
        from superplanner.api.mfg.db_models_m2 import MfgInvPostingRow
        from superplanner.integration import outbox

        with owner_scope("usr_local"), ctx.db.write() as s:
            row = s.execute(sa.select(MfgInvPostingRow).limit(1)).scalars().first()
            ts = []
            for _ in range(50):
                t = time.perf_counter()
                outbox.emit(s, "inventory.posting", posting_record(s, row), row.number)
                s.flush()
                ts.append((time.perf_counter() - t) * 1000)
            s.rollback()
        _rec(f"IP2 posting median off {off:.2f} ms, on {on1:.2f}/{on2:.2f} ms -> overhead "
             f"{statistics.mean([on1, on2]) - off:+.2f} ms; emit()+record alone {statistics.median(ts):.2f} ms")
        # IP4: 100 events/s for 10 s to a healthy endpoint, scheduler every 2 s (INTEGRATION_DELIVERY_POLL_SECONDS)
        it.req("POST", "/endpoints", 201, json={"name": "erp", "url": "https://erp.example.com/hook",
                                                "secret": "s" * 20, "event_types": []})
        stop = threading.Event()

        def deliverer():
            while not stop.is_set():
                scheduler.tick(ctx, duties={"integration_delivery"})
                stop.wait(2.0)

        th = threading.Thread(target=deliverer, daemon=True)
        th.start()
        eng = sa.create_engine(db_url)
        t0 = time.time()
        for sec in range(10):
            with eng.begin() as conn:
                conn.execute(sa.text("INSERT INTO int_outbox (id, owner_id, type, entity_ref, data, actor_id, "
                                     "occurred_at) SELECT 'evt_' || md5(random()::text || g::text), 'usr_local', "
                                     "'inventory.posting', 'X', '{\"lines\": []}'::jsonb, 'usr_local', now() "
                                     "FROM generate_series(1, 100) g"))
            time.sleep(max(0.0, t0 + sec + 1 - time.time()))
        deadline = time.time() + 30
        while len(lat) < 1000 and time.time() < deadline:
            time.sleep(0.2)
        stop.set()
        th.join(5)
        eng.dispose()
        lat_sorted = sorted(lat)
        p95 = lat_sorted[int(0.95 * len(lat_sorted)) - 1] if lat_sorted else None
        _rec(f"IP4 {len(lat)} of 1,000 events delivered at 100/s; p95 event->delivery {p95:.2f} s, max "
             f"{lat_sorted[-1]:.2f} s")
        assert len(lat) >= 1000


def _synthetic_genealogy(db_url: str) -> dict:
    """TP1: a unit serial whose structure holds ~1,400 nodes; TP2: one supplier lot in 20 WOs x 100 units."""
    eng = sa.create_engine(db_url)
    o = "usr_local"
    now = datetime.now(UTC)
    edges = []
    n = [0]

    def nid(p: str) -> str:
        n[0] += 1
        return f"{p}{n[0]:032x}"

    def edge(fk, fid, tk, tid, prec="exact", qty=1.0):
        edges.append({"id": nid("tre_"), "owner_id": o, "from_kind": fk, "from_id": fid, "to_kind": tk, "to_id": tid,
                      "qty": qty, "precision": prec, "event_at": now, "source_key": nid("syn:")})

    with eng.begin() as conn:
        item = conn.execute(sa.text("SELECT id FROM mfg_items WHERE owner_id = :o LIMIT 1"), {"o": o}).scalar()
        root = nid("ser_")
        conn.execute(sa.text("INSERT INTO mfg_unit_serials (id, owner_id, item_id, serial, status, captured_at, "
                             "row_version, created_at, updated_at) VALUES (:i, :o, :it, 'TPU-PERF-1', 'shipped', "
                             "now(), 1, now(), now())"), {"i": root, "o": o, "it": item})
        wo0 = nid("wko_")
        edge("wo", wo0, "serial", root)
        for _a in range(6):
            sub = nid("ser_")
            wo = nid("wko_")
            edge("serial", sub, "wo", wo0)
            edge("serial", sub, "serial", root)
            edge("wo", wo, "serial", sub)
            for _l in range(60):
                edge("lot", nid("lot_"), "wo", wo, qty=10)
            for _b in range(4):
                ss = nid("ser_")
                w2 = nid("wko_")
                edge("serial", ss, "wo", wo)
                edge("wo", w2, "serial", ss)
                for _l in range(40):
                    edge("lot", nid("lot_"), "wo", w2, qty=5)
        # TP2
        lot = nid("lot_")
        conn.execute(sa.text("INSERT INTO mfg_lots (id, owner_id, item_id, lot_code, supplier_lot, hold, note, "
                             "row_version, created_at, updated_at) VALUES (:i, :o, :it, 'SUP-PERF', 'SUPP-PERF', "
                             "false, '', 1, now(), now())"), {"i": lot, "o": o, "it": item})
        for _w in range(20):
            wo = nid("wko_")
            edge("lot", lot, "wo", wo, qty=50)
            for _u in range(100):
                edge("wo", wo, "serial", nid("ser_"))
        conn.execute(sa.text("INSERT INTO mfg_trace_edges (id, owner_id, from_kind, from_id, to_kind, to_id, qty, "
                             "precision, event_at, source_key) VALUES (:id, :owner_id, :from_kind, :from_id, "
                             ":to_kind, :to_id, :qty, :precision, :event_at, :source_key)"), edges)
    eng.dispose()
    return {"root": root, "lot": lot, "item": item, "edges": len(edges)}


def test_tp1_tp2_ap2(db_url, capsys):
    app = make_app(db_url)
    with TestClient(app) as c:
        api = Api(c)
        api.item("TP-ITEM")
        g = _synthetic_genealogy(db_url)
        ts = []
        for _ in range(3):
            t = time.perf_counter()
            tr = api.get("/trace", kind="serial", id=g["root"], direction="backward")
            ts.append(time.perf_counter() - t)
        _rec(f"TP1 backward trace {tr['nodes']} nodes: {min(ts) * 1000:.0f} ms (median {statistics.median(ts) * 1000:.0f})")
        t = time.perf_counter()
        fw = api.get("/trace", kind="lot", id=g["lot"], direction="forward")
        t_fw = time.perf_counter() - t
        t = time.perf_counter()
        rec = api.post("/recalls", {"name": "perf", "sources": [{"item_id": g["item"], "supplier_lot": "SUPP-PERF"}]})
        t_rc = time.perf_counter() - t
        assert rec["report"]["counts"]["units"] == 2000
        _rec(f"TP2 forward trace {fw['nodes']} nodes {t_fw * 1000:.0f} ms; recall report 2,000 units "
             f"{t_rc * 1000:.0f} ms")
        # AP2: 1,000,000 audit rows streamed
        eng = sa.create_engine(db_url)
        with eng.begin() as conn:
            conn.execute(sa.text("INSERT INTO audit_events (entity_type, entity_id, action, details, actor_id, "
                                 "owner_id, created_at) SELECT 'perf', g::text, 'x', '{\"n\": 1}'::jsonb, "
                                 "'usr_local', 'usr_local', now() FROM generate_series(1, 1000000) g"))
        eng.dispose()
        rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        t = time.perf_counter()
        nbytes = lines = 0
        with c.stream("GET", f"{V1}/audit/export", params={"format": "jsonl"}) as r:
            for chunk in r.iter_bytes():
                nbytes += len(chunk)
                lines += chunk.count(b"\n")
        t_ap2 = time.perf_counter() - t
        rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        assert lines >= 1_000_000
        _rec(f"AP2 audit export {lines:,} rows / {nbytes / 1e6:.0f} MB streamed in {t_ap2:.1f} s; max RSS growth "
             f"{(rss1 - rss0) / 1024:.0f} MB")
    with capsys.disabled():
        print("\n".join(OUT))


def test_bf1_ep1_kavach(db_url, capsys):
    app = make_app(db_url)
    with TestClient(app) as c:
        api = Api(c)
        api.load("kavach")
        ctx = app.state.ctx
        from superplanner.api.mfg.db_models_m5 import MfgTraceEdgeRow
        from superplanner.api.mfg.services.trace import backfill

        with system_scope(), ctx.db.write() as s:
            n_live = s.execute(sa.select(sa.func.count()).select_from(MfgTraceEdgeRow)).scalar()
            s.execute(sa.delete(MfgTraceEdgeRow))
            t = time.perf_counter()
            r = backfill(s)
            t_bf = time.perf_counter() - t
        assert r["edges_added"] == n_live
        _rec(f"BF1 trace backfill of the Kavach M4 sample: {r['postings']} postings, {r['serials']} serials, "
             f"{r['edges_added']} edges in {t_bf:.2f} s")
        cpu = api.by_pn("KV-PCB-CPU")
        boms = api.get(f"/items/{cpu['id']}/boms")["items"]
        cur = next(b for b in boms if b["status"] == "released")
        bom = api.get(f"/boms/{cur['id']}")
        draft = api.post(f"/boms/{bom['id']}/copy", {}, version=bom["row_version"])
        lines = [{k: ln[k] for k in ("find_number", "qty_per", "uom", "scrap_pct", "ref_designators",
                                     "operation_seq") if k in ln} | {"child_item_id": ln["child"]["id"]}
                 for ln in draft["lines"]]
        lines[0]["qty_per"] = lines[0]["qty_per"] + 1
        lines = lines[1:] + [lines[0]]
        removed = lines.pop(0)
        del removed
        draft = api.put(f"/boms/{draft['id']}", {"item_id": cpu["id"], "lines": lines}, draft["row_version"])
        cr = api.post("/eco", {"title": "perf", "effectivity": {"mode": "use_up"}})
        api.post(f"/eco/{cr['id']}/items", {"doc_type": "bom", "doc_id": draft["id"]})
        api.post("/mrp/runs", {})
        t = time.perf_counter()
        imp = api.get(f"/eco/{cr['id']}/impact")
        t_ep = time.perf_counter() - t
        _rec(f"EP1 ECO impact on KV-PCB-CPU (incl. MRP what-if): {t_ep:.2f} s (server {imp['computed_ms']} ms); "
             f"delta {imp['explosion_delta'][0]['removed'][:2]}..., mrp_delta {len(imp['mrp_delta'])}, "
             f"use_up {imp['use_up_date']}")
    with capsys.disabled():
        print("\n".join(OUT))


_ = MFG


def test_ip1_kavach_master(db_url, capsys):
    """IP1 (second target): the full Kavach master as v1 batches (items, BOMs, routings) into an empty plant."""
    from superplanner.api.mfg import repo, repo_m2, writer
    from superplanner.api.mfg.services.common import write_tx
    from superplanner.mfg.bundle import dataset_to_bundle
    from superplanner.mfg.io.plan import ImportOptions, plan_import

    app = make_app(db_url, secrets_keys=[crypto.new_key()])
    with TestClient(app) as c:
        it, api = Int(c), Api(c)
        api.load("kavach")
        ctx = app.state.ctx
        with owner_scope("usr_local"), ctx.db.read() as s:
            ds = repo.load_dataset(s)
            b = dataset_to_bundle(ds, "master")
        items = [{"ref": r["part_number"], "part_number": r["part_number"], "revision": r.get("revision") or "A",
                  "description": r.get("description") or "", "uom": r.get("uom") or "EA", "make_buy": r["make_buy"]}
                 for r in b["items"]]
        lines: dict[tuple, list] = {}
        for ln in b["bom_lines"]:
            lines.setdefault((ln["parent_part_number"], ln["revision"], ln["version"]), []).append(
                {"child_ref": ln["child_part_number"], "find_number": str(ln["find_number"]), "qty_per": ln["qty_per"],
                 **({"operation_seq": ln["operation_seq"]} if ln.get("operation_seq") else {})})
        boms = [{"ref": f"B-{h['parent_part_number']}", "parent_ref": h["parent_part_number"],
                 "lines": lines.get((h["parent_part_number"], h["revision"], h["version"]), [])}
                for h in b["boms"] if h.get("status") == "released"]
        ops: dict[tuple, list] = {}
        for o in b["operations"]:
            ops.setdefault((o["part_number"], o["revision"], o["code"], o["version"]), []).append(
                {"seq": o["seq"], "name": o["name"], "group_code": o["group_code"],
                 "setup_minutes": o.get("setup_minutes") or 0, "run_minutes": o.get("run_minutes") or 0,
                 "run_per": o.get("run_per") or "unit", "labor": o.get("labor") or "attended",
                 "crew_size": o.get("crew_size") if o.get("crew_size") is not None else 1,
                 **({"units_per_batch": o["units_per_batch"]} if o.get("units_per_batch") else {}),
                 **({"units_per_panel": o["units_per_panel"]} if o.get("units_per_panel") else {})})
        rtgs = [{"ref": f"R-{h['part_number']}-{h['code']}", "item_ref": h["part_number"], "code": h["code"],
                 **({"priority": h["priority"]} if h.get("priority") else {}),
                 "operations": ops.get((h["part_number"], h["revision"], h["code"], h["version"]), [])}
                for h in b["routings"] if h.get("status") == "released"]
        api.post("/reset", {"confirm": "DELETE ALL MANUFACTURING DATA"}, status=200)
        keep = ("skills", "tool_pools", "groups", "lines", "shift_templates", "shifts", "shift_assignments")
        with owner_scope("usr_local"), write_tx(ctx) as (s, plant):
            plan = plan_import({k: b[k] for k in keep}, repo_m2.load_import_dataset(s, with_txn=False),
                               ImportOptions())
            assert plan.ok, plan.row_errors[:3]
            writer.apply(s, plan, plant or repo.plant_row_unlocked(s))
        _enable(it)
        t0 = time.perf_counter()
        bi, ti = _batch(it, "item", items, "km-items")
        bb, tb = _batch(it, "bom", boms, "km-boms")
        br, tr = _batch(it, "routing", rtgs, "km-routings")
        total = time.perf_counter() - t0
        rej = [r for x in (bi, bb, br) for r in (x["results"] or []) if r["status"] == "rejected"]
        assert not rej, json.dumps(rej[:2])[:3000]
        _rec(f"IP1 Kavach master via v1: {len(items)} items {ti:.1f} s, {len(boms)} BOMs {tb:.1f} s, {len(rtgs)} "
             f"routings {tr:.1f} s; total {total:.1f} s (each BOM/routing release through an ERP ECO)")
    with capsys.disabled():
        print("\n".join(OUT))
