"""File drop (T-I8), the scheduled delivery job and the periodic file export (M5-DESIGN 4.5, 4.6)."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, make_app
from test_integration import DNS, KEY, Int, _enable, fake_getaddrinfo

INT_DUTIES = ("integration_filedrop", "integration_delivery", "maintenance_retention")


def _tick(app):
    from superplanner.api.db.ownership import system_scope
    from superplanner.api.mfg.db_models_m5 import MaintenanceRunRow
    from superplanner.integration import scheduler
    from sqlalchemy import select

    ctx = app.state.ctx
    out = scheduler.tick(ctx)
    for _ in range(200):
        with system_scope(), ctx.db.read() as s:
            busy = s.execute(select(MaintenanceRunRow.id).where(MaintenanceRunRow.status.in_(
                ("queued", "running")))).first()
        if busy is None:
            break
        time.sleep(0.05)
    return out


def _runs(app, kind):
    from superplanner.api.db.ownership import system_scope
    from superplanner.api.mfg.db_models_m5 import MaintenanceRunRow
    from sqlalchemy import select

    with system_scope(), app.state.ctx.db.read() as s:
        return [(r.status, r.results) for r in s.execute(select(MaintenanceRunRow).where(
            MaintenanceRunRow.kind == kind).order_by(MaintenanceRunRow.created_at)).scalars()]


def test_t_i8_file_drop_and_scheduled_duties(db_url, tmp_path, monkeypatch):
    DNS.clear()
    DNS["erp.example.com"] = ["93.184.216.34"]
    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    got = []

    def post(url, body, headers):
        got.append(json.loads(body))
        return 200, ""

    app = make_app(db_url, secrets_keys=[KEY], webhook_post=post, integration_root=str(tmp_path),
                   retention_enabled=False)
    with TestClient(app) as c:
        it, api = Int(c), Api(c)
        _enable(it, filedrop_enabled=True, export_enabled=True, export_interval_minutes=5,
                sor={"stock": "erp"})
        st = api.location("ST")
        it.req("POST", "/mapping-profiles", 201, json={"name": "erp items", "file_pattern": "items_*.csv",
                                                       "mapping": {"target": "items", "columns": {
                                                           "PartNo": "part_number", "Desc": "description",
                                                           "MB": "make_buy", "Ref": "external_ref"}}})
        _tick(app)                                        # creates the plant folders
        inbox = tmp_path / "HBL1" / "inbox"
        assert inbox.is_dir()
        f = inbox / "items_001.csv"
        f.write_text("PartNo,Desc,MB,Ref\nR-1,Resistor,buy,E-R1\n")       # partially written ...
        _tick(app)
        assert f.exists()                                  # ... not picked before its size is stable
        st_ = it.req("GET", "/filedrop/status", 200).json()
        assert st_["inbox"][0]["name"] == "items_001.csv"
        _tick(app)
        assert not f.exists() and (tmp_path / "HBL1" / "archive" / "items_001.csv").exists()
        res = json.loads((tmp_path / "HBL1" / "archive" / "items_001.csv.result.json").read_text())
        assert res["ok"] and res["profile"] == "erp items", res
        assert api.by_pn("R-1")["external_ref"] == "E-R1"
        # a bad file (unknown make_buy) goes to error/ with the report and a notification (.done marker: at once)
        (inbox / "items_002.csv").write_text("PartNo,Desc,MB,Ref\nR-2,X,maybe,E-R2\n")
        (inbox / "items_002.csv.done").write_text("")
        _tick(app)
        err = json.loads((tmp_path / "HBL1" / "error" / "items_002.csv.result.json").read_text())
        assert err["ok"] is False and err["error_count"] >= 1
        assert any(n["kind"] == "INTEGRATION_FILE_ERROR" for n in api.get("/notifications")["items"])
        recent = it.req("GET", "/filedrop/status", 200).json()["recent"]
        assert {(r["file"], r["ok"]) for r in recent} == {("items_001.csv", True), ("items_002.csv", False)}
        # a v1 JSON batch, and a 2-row stock file (stock SoR erp: count postings)
        (inbox / "po.json").write_text(json.dumps({"schema": "superplanner.v1", "entity": "item", "records": [
            {"ref": "E-R3", "part_number": "R-3"}]}))
        (inbox / "po.json.done").write_text("")
        (inbox / "stock_x.csv").write_text(f"part_number,location_code,qty\nR-1,{st['code']},7\nR-3,ST,2\n")
        (inbox / "stock_x.csv.done").write_text("")
        _tick(app)
        assert api.by_pn("R-3")
        assert {b["qty_on_hand"] for b in api.get("/inventory/balances", item_id=api.by_pn("R-1")["id"])["items"]} \
            == {7}
        # scheduled webhook delivery + file export of the events
        it.req("POST", "/endpoints", 201, json={"name": "erp", "url": "https://erp.example.com/hook",
                                                "secret": "s" * 20, "event_types": []})
        api.receive(api.by_pn("R-1")["id"], st["id"], 1)
        _tick(app)
        assert got and got[-1]["type"] == "inventory.posting"
        assert [k for k, _o in _tick(app) if k == "integration_delivery"] == []      # nothing left to deliver
        out = sorted(p.name for p in (tmp_path / "HBL1" / "outbox").iterdir())
        assert any(n.endswith(".jsonl") for n in out) and any("inventory_posting.csv" in n for n in out), out
        assert _runs(app, "integration_delivery")[-1][0] == "completed"


def test_dropped_bom_file_goes_through_an_erp_eco(db_url, tmp_path):
    from superplanner.api.db.ownership import owner_scope
    from superplanner.integration import filedrop

    app = make_app(db_url, integration_root=str(tmp_path), retention_enabled=False)
    with TestClient(app) as c:
        it, api = Int(c), Api(c)
        _enable(it, filedrop_enabled=True)
        it.batch("item", [{"ref": "P", "part_number": "PCB-1", "make_buy": "make"},
                          {"ref": "R", "part_number": "R-1"}], "i1")
        f = tmp_path / "bom_lines.csv"
        f.write_text("parent_part_number,find_number,child_part_number,qty_per\nPCB-1,1,R-1,2\n")
        with owner_scope("usr_local"):
            r = filedrop.process_file(app.state.ctx, f)
            assert r["ok"] and r["documents"]["bom"][0]["status"] == "created", r
            assert r["documents"]["bom"][0]["eco"]["number"] == "ECO-000001"
            again = filedrop.process_file(app.state.ctx, f)
        assert again["documents"]["bom"][0]["status"] == "unchanged"
        eco = api.get("/eco")["items"]
        assert [(e["source"], e["status"]) for e in eco] == [("erp", "implemented")]
