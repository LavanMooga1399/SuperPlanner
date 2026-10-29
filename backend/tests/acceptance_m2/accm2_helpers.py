"""Helpers for the WP-D M2 acceptance suite (module name unique across backend/tests: `accm2_helpers`).

`Api` wraps /api/v1/mfg with status assertions and `need(...)`, which skips the test (naming the endpoint of
M2-DESIGN 12.3) while the route is not registered yet. `push_plant` sets an oracle plant up through the public
API (items, routings, BOMs, shifts, locations, suppliers, stock postings, POs/PRs, demand, WOs) so the same plant
can be planned by the product and by the oracle.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

V1 = "/api/v1"
MFG = f"{V1}/mfg"
PASSWORD = "correct horse battery staple"
RESET = {"confirm": "DELETE ALL MANUFACTURING DATA"}
AS_OF = "2026-11-02"
ID = r"[a-z]{3}_[0-9a-f]{32}"


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def acc_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, auth_mode="accounts", password_hash_profile="fast",
                               auth_signin_limit_per_ip=1000, auth_signup_limit_per_ip=1000,
                               auth_signin_limit_per_email=1000, **overrides))


def im(v: int) -> dict[str, str]:
    return {"If-Match": f'"{v}"'}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def registered_routes(app: Any) -> set[tuple[str, str]]:
    out = set()
    for r in app.routes:
        for m in getattr(r, "methods", None) or ():
            out.add((m, _norm(getattr(r, "path", ""))))
    return out


def need_routes(app: Any, *endpoints: str) -> None:
    """Skip unless every 'METHOD /path' (12.3, relative to /api/v1/mfg) is registered."""
    have = registered_routes(app)
    missing = [e for e in endpoints if (e.split()[0], _norm(MFG + e.split()[1])) not in have]
    if missing:
        pytest.skip(f"M2 endpoint(s) not implemented yet (M2-DESIGN 12.3): {', '.join(missing)}")


def need_module(name: str, attr: str | None = None) -> Any:
    import importlib

    try:
        mod = importlib.import_module(name)
    except ImportError as exc:
        pytest.skip(f"module {name} not available yet ({exc})")
    if attr is not None and not hasattr(mod, attr):
        pytest.skip(f"{name}.{attr} not implemented yet")
    return mod


class Api:
    """Thin wrapper over /api/v1/mfg with status assertions."""

    def __init__(self, c: TestClient, app: Any, workspace: str | None = None):
        self.c = c
        self.app = app
        self.workspace = workspace

    def need(self, *endpoints: str) -> "Api":
        need_routes(self.app, *endpoints)
        return self

    def in_workspace(self, owner_id: str | None) -> "Api":
        return Api(self.c, self.app, owner_id)

    def _headers(self, extra: dict[str, str] | None) -> dict[str, str]:
        h = dict(extra or {})
        if self.workspace:
            h["X-SP-Workspace"] = self.workspace
        return h

    def raw(self, method: str, path: str, headers: dict[str, str] | None = None, **kw: Any):
        return self.c.request(method, MFG + path, headers=self._headers(headers), **kw)

    def call(self, method: str, path: str, status: int | tuple[int, ...], **kw: Any) -> Any:
        r = self.raw(method, path, **kw)
        ok = status if isinstance(status, tuple) else (status,)
        assert r.status_code in ok, (method, path, r.status_code, r.text[:3000])
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r

    def get(self, path: str, status: int = 200, **params: Any) -> Any:
        return self.call("GET", path, status, params=params or None)

    def post(self, path: str, body: Any = None, status: int | tuple[int, ...] = 201, version: int | None = None,
             headers: dict[str, str] | None = None) -> Any:
        h = dict(headers or {})
        if version is not None:
            h.update(im(version))
        return self.call("POST", path, status, json={} if body is None else body, headers=h)

    def put(self, path: str, body: Any, version: int, status: int = 200) -> Any:
        return self.call("PUT", path, status, json=body, headers=im(version))

    def delete(self, path: str, version: int | None = None, status: int = 204) -> Any:
        return self.call("DELETE", path, status, headers=im(version) if version is not None else {})

    def error(self, method: str, path: str, status: int, code: str, **kw: Any) -> dict[str, Any]:
        body = self.call(method, path, status, **kw)
        assert body["error"]["code"] == code, body
        return body["error"]

    def all_pages(self, path: str, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.get(path, limit=200, offset=offset, **params)
            out += page["items"]
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                return out

    # ------------------------------------------------------------------ conveniences
    def load(self, sample: str, *, anchor: str | None = AS_OF, include_transactions: bool = True,
             replace: bool = False) -> dict[str, Any]:
        return self.post(f"/samples/{sample}/load", {"replace": replace, "anchor": anchor,
                                                     "include_transactions": include_transactions}, status=200)

    def item(self, pn: str) -> dict[str, Any]:
        items = self.get("/items", q=pn, limit=200)["items"]
        hit = [i for i in items if i["part_number"] == pn]
        assert len(hit) == 1, (pn, [i["part_number"] for i in items])
        return hit[0]

    def by_code(self, coll: str, code: str) -> dict[str, Any]:
        hit = [x for x in self.get(coll)["items"] if x["code"] == code]
        assert len(hit) == 1, (coll, code)
        return hit[0]

    def doc(self, coll: str, number: str) -> dict[str, Any]:
        hit = [x for x in self.all_pages(coll, q=number) if x["number"] == number]
        assert len(hit) == 1, (coll, number, hit)
        return self.get(f"{coll}/{hit[0]['id']}")

    def post_stock(self, item_id: str, location_id: str, qty: float, *, lot: str | None = None,
                   expires: str | None = None, key: str | None = None, status: int = 201) -> Any:
        line = {"item_id": item_id, "location_id": location_id, "qty": qty, "lot_code": lot}
        if expires:
            line["expires_on"] = expires
        h = {"Idempotency-Key": key} if key else None
        return self.post("/inventory/postings", {"type": "receipt_misc", "lines": [line]}, status=status, headers=h)

    def run_mrp(self, status: int = 201, **params: Any) -> dict[str, Any]:
        return self.post("/mrp/runs", params, status=status)

    def balance(self, item_id: str, location_id: str, lot_id: str | None = None) -> float:
        rows = self.get("/inventory/balances", item_id=item_id, location_id=location_id, only_nonzero="false",
                        limit=200)["items"]
        rows = [r for r in rows if lot_id is None or (r["lot"] or {}).get("id") == lot_id]
        return sum(r["qty_on_hand"] for r in rows)


class Accounts:
    """Users of one accounts-mode app; `user(email)` signs up (once) and returns an `Api` with the CSRF header."""

    def __init__(self, app: Any):
        self.app = app
        self.clients: dict[str, TestClient] = {}
        self.ids: dict[str, str] = {}

    def user(self, email: str) -> Api:
        if email not in self.clients:
            c = TestClient(self.app)
            r = c.post(f"{V1}/auth/sign-up", json={"email": email, "password": PASSWORD})
            assert r.status_code == 201, r.text
            c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
            self.clients[email] = c
            self.ids[email] = c.get(f"{V1}/auth/session").json()["user"]["id"]
        return Api(self.clients[email], self.app)

    def uid(self, email: str) -> str:
        self.user(email)
        return self.ids[email]

    def close(self) -> None:
        for c in self.clients.values():
            c.close()


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------- oracle plant -> API


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def plant_today(api: Api) -> date:
    """Plant-local today as the server sees it (utc_offset +00:00 in these tests)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


def push_plant(api: Api, plant: Any) -> dict[str, Any]:
    """Create the oracle plant through the API. Returns maps from oracle ids to API records:
    {"items": {oracle_item_id: record}, "locations": {...}, "schedules": {oracle_schedule_id: api_schedule_id},
     "demand_lines": {oracle_line_id: api_line_id}, "wos": {oracle_wo_id: record}, "pos": {number: record}}.
    Stock is received today (txn_date default); lot expiries and holds are applied as given."""
    api.need("POST /locations", "POST /suppliers", "POST /item-suppliers", "POST /inventory/postings",
             "POST /purchase-orders", "POST /purchase-requests", "POST /demand-orders", "POST /work-orders")
    out: dict[str, Any] = {"items": {}, "locations": {}, "schedules": {}, "demand_lines": {}, "wos": {}, "pos": {}}
    p = api.get("/plant")
    body = {k: p[k] for k in ("name", "utc_offset", "planning_horizon_days", "currency", "attributes")}
    body.update(mrp_workdays=list(plant.workdays), mrp_day_minutes=plant.day_minutes,
                mrp_defer_tolerance_days=plant.defer_tolerance_days,
                mrp_release_window_days=plant.release_window_days, over_receipt_pct=0,
                planning_horizon_days=plant.planning_horizon_days)
    api.put("/plant", body, p["row_version"])
    groups = {}
    for gid in sorted({ln.group_id for ln in plant.lines} | {op.group_id for r in plant.routings for op in r.ops}):
        g = api.post("/groups", {"code": f"G{len(groups) + 1}", "name": f"Stage {len(groups) + 1}"})
        groups[gid] = g
        tpl = api.post("/shift-templates", {"code": f"T{len(groups)}", "name": "Day", "shifts": [
            {"name": "Day", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "start": "08:00",
             "end": "16:00"}]})
        api.post("/shift-assignments", {"shift_template_id": tpl["id"], "target_type": "group", "group_id": g["id"],
                                        "effective_from": "2026-01-01"})
    for i, ln in enumerate(plant.lines):
        api.post("/lines", {"group_id": groups[ln.group_id]["id"], "code": f"L{i + 1}", "name": f"Line {i + 1}",
                            "speed_factor": ln.speed_factor, "eligible_families": ln.eligible_families,
                            "active": ln.active})
    lot_items = {b.item_id for b in plant.balances if b.lot_code}
    for it in sorted(plant.items.values(), key=lambda x: x.part_number):
        out["items"][it.id] = api.post("/items", {
            "part_number": it.part_number, "make_buy": it.make_buy, "uom": it.uom,
            "lead_time_days": it.lead_time_days, "receiving_days": it.receiving_days, "lot_rule": it.lot_rule,
            "fixed_lot_qty": it.fixed_lot_qty, "lot_period_days": it.lot_period_days,
            "min_order_qty": it.min_order_qty, "order_multiple": it.order_multiple,
            "safety_stock": it.safety_stock, "serialized": it.serialized, "active": it.active,
            "family": it.family, "lot_controlled": it.id in lot_items})
    iid = {k: v["id"] for k, v in out["items"].items()}
    for r in plant.routings:
        rec = api.post("/routings", {"item_id": iid[r.item_id], "code": r.code, "priority": r.priority,
                                     "serial_from": r.serial_from, "serial_to": r.serial_to, "operations": [
                                         {"seq": o.seq, "name": f"Op {o.seq}", "group_id": groups[o.group_id]["id"],
                                          "setup_minutes": o.setup_minutes, "run_minutes": o.run_minutes,
                                          "queue_minutes": o.queue_minutes, "move_minutes": o.move_minutes,
                                          "wait_minutes": o.wait_minutes, "yield_pct": o.yield_pct}
                                         for o in r.ops]})
        api.post(f"/routings/{rec['id']}/release", {"effective_from": None}, status=200, version=rec["row_version"])
    for b in sorted(plant.boms, key=lambda x: x.version):
        rec = api.post("/boms", {"item_id": iid[b.item_id], "version": b.version, "serial_from": b.serial_from,
                                 "serial_to": b.serial_to, "lines": [
                                     {"find_number": ln.find_number, "child_item_id": iid[ln.child_id],
                                      "qty_per": ln.qty_per, "uom": ln.uom, "scrap_pct": ln.scrap_pct,
                                      "alt_group": ln.alt_group, "alt_priority": ln.alt_priority,
                                      "operation_seq": ln.operation_seq} for ln in b.lines]})
        api.post(f"/boms/{rec['id']}/release", {"effective_from": None}, status=200, version=rec["row_version"])
    for h in sorted(plant.holidays):
        api.post("/calendar-exceptions", {"scope": "plant", "kind": "holiday", "label": "Holiday",
                                          "start": f"{h.isoformat()}T00:00:00+00:00",
                                          "end": f"{(h + timedelta(days=1)).isoformat()}T00:00:00+00:00"})
    kinds = {(b.location_id, b.location_kind) for b in plant.balances} | {("_default", "stores")}
    for n, (lid, kind) in enumerate(sorted(kinds)):
        out["locations"][lid] = api.post("/locations", {"code": f"LOC{n}", "name": f"Location {n}", "kind": kind,
                                                        "receipt_default": lid == "_default"})
    sups = {}
    for s in plant.suppliers.values():
        sups[s.id] = api.post("/suppliers", {"code": s.code, "name": s.code, "lead_time_days": s.lead_time_days,
                                             "active": s.active})
    default_sup = api.post("/suppliers", {"code": "ACC-DEFAULT", "name": "Default (fictional)"})
    for r in plant.item_suppliers:
        api.post("/item-suppliers", {"item_id": iid[r.item_id], "supplier_id": sups[r.supplier_id]["id"],
                                     "lead_time_days": r.lead_time_days, "min_order_qty": r.min_order_qty,
                                     "order_multiple": r.order_multiple,
                                     "units_per_purchase_unit": r.units_per_purchase_unit,
                                     "preferred": r.preferred, "active": r.active})
    bal_ids: dict[str, dict[str, Any]] = {}
    for b in plant.balances:
        line = {"item_id": iid[b.item_id], "location_id": out["locations"][b.location_id]["id"],
                "qty": b.qty_on_hand, "lot_code": b.lot_code}
        if b.expires_on:
            line["expires_on"] = b.expires_on.isoformat()
        rec = api.post("/inventory/postings", {"type": "receipt_misc", "lines": [line]})
        bal_ids[b.id] = rec["lines"][0]
        if b.hold and rec["lines"][0]["lot"]:
            lot = rec["lines"][0]["lot"]
            full = [x for x in api.all_pages("/lots", item_id=iid[b.item_id]) if x["id"] == lot["id"]][0]
            api.put(f"/lots/{lot['id']}", {"expires_on": full["expires_on"], "supplier_lot": full["supplier_lot"],
                                           "hold": True, "note": ""}, full["row_version"])
    by_doc: dict[tuple[str, str], list[Any]] = {}
    for s in plant.schedules:
        by_doc.setdefault((s.doc_type, s.number), []).append(s)
    for (dt, number), scheds in sorted(by_doc.items()):
        coll = "/purchase-orders" if dt == "po" else "/purchase-requests"
        rec = api.post(coll, {"number": number, "supplier_id": (sups.get(scheds[0].supplier_id) or default_sup)["id"],
                              "lines": [{"line_no": scheds[0].line_no, "item_id": iid[scheds[0].item_id],
                                         "schedules": [{"seq": s.seq, "requested_date": s.requested_date.isoformat(),
                                                        "confirmed_date": _iso(s.confirmed_date), "qty": s.open_qty}
                                                       for s in scheds]}]})
        status = scheds[0].doc_status
        if dt == "po" and status in ("open", "partially_received"):
            rec = api.post(f"{coll}/{rec['id']}/issue", {}, status=200, version=rec["row_version"])
        if dt == "pr" and status in ("submitted", "approved"):
            rec = api.post(f"{coll}/{rec['id']}/submit", {}, status=200, version=rec["row_version"])
            if status == "approved":
                rec = api.post(f"{coll}/{rec['id']}/approve", {"note": ""}, status=200, version=rec["row_version"])
        out["pos"][number] = rec
        for s, api_s in zip(sorted(scheds, key=lambda x: x.seq), rec["lines"][0]["schedules"]):
            out["schedules"][s.schedule_id] = api_s["id"]
    by_order: dict[str, list[Any]] = {}
    for dm in plant.demand:
        by_order.setdefault(dm.number, []).append(dm)
    for number, lines in sorted(by_order.items()):
        rec = api.post("/demand-orders", {"number": number, "demand_type": lines[0].demand_type,
                                          "program": lines[0].program, "priority": lines[0].priority, "lines": [
                                              {"line_no": x.line_no, "item_id": iid[x.item_id], "qty": x.open_qty,
                                               "due_date": x.due_date.isoformat(), "serial_from": x.serial_from,
                                               "serial_to": x.serial_to, "priority": x.priority} for x in lines]})
        rec = api.post(f"/demand-orders/{rec['id']}/open", {}, status=200, version=rec["row_version"])
        for x, api_l in zip(sorted(lines, key=lambda y: y.line_no), rec["lines"]):
            out["demand_lines"][x.line_id] = api_l["id"]
    rsv_by_comp = {r.wo_component_id: r for r in plant.reservations}
    for w in plant.work_orders:
        rec = api.post("/work-orders", {"number": w.number, "item_id": iid[w.item_id], "qty": w.open_qty,
                                        "start_date": w.start_date.isoformat(), "due_date": w.due_date.isoformat(),
                                        "priority": w.priority, "serial_from": w.serial_from,
                                        "serial_to": w.serial_to,
                                        "components": [{"item_id": iid[c.item_id], "required_qty": c.open_qty}
                                                       for c in w.components]})
        if w.status in ("released", "in_progress"):
            reserve = any(c.id in rsv_by_comp for c in w.components)
            rec = api.post(f"/work-orders/{rec['id']}/release", {"reserve": reserve}, status=200,
                           version=rec["row_version"])
        out["wos"][w.id] = rec
    return out


# ---------------------------------------------------------------------- MRP API reads (12.3 #148-#163)


def seg(x: Any) -> tuple[int, int] | None:
    from oracle.adapters import _seg

    return _seg(x)


def mrp_planned(api: Api, run_id: str, **flt: Any) -> list[dict[str, Any]]:
    return api.all_pages(f"/mrp/runs/{run_id}/planned-orders", **flt)


def mrp_demand(api: Api, run_id: str, **flt: Any) -> list[dict[str, Any]]:
    return api.all_pages(f"/mrp/runs/{run_id}/demand", **flt)


def mrp_exceptions(api: Api, run_id: str, **flt: Any) -> list[dict[str, Any]]:
    return api.all_pages(f"/mrp/runs/{run_id}/exceptions", **flt)


def mrp_item(api: Api, run_id: str, item_id: str) -> dict[str, Any]:
    return api.get(f"/mrp/runs/{run_id}/items/{item_id}", bucket="day")


def demand_row(rows: list[dict[str, Any]], line_id: str) -> dict[str, Any]:
    hit = [r for r in rows if r["demand_line_id"] == line_id]
    assert len(hit) == 1, (line_id, rows)
    return hit[0]


def req_pegs(plan: dict[str, Any], req: dict[str, Any]) -> list[tuple[str, float]]:
    """[(supply kind, qty)] of one requirement of an MrpItemPlan (12.4)."""
    kinds = {s["node"]: s["kind"] for s in plan["supplies"]}
    return [(kinds[p["supply_node"]], round(p["qty"], 6)) for p in req["pegs"]]


def demand_req_of(plan: dict[str, Any], line_id: str) -> dict[str, Any]:
    hit = [r for r in plan["requirements"] if r["source"]["type"] == "demand_line" and r["source"]["id"] == line_id]
    assert len(hit) == 1, (line_id, plan["requirements"])
    return hit[0]


MRP_ENDPOINTS = ("POST /mrp/runs", "GET /mrp/runs/{run_id}", "GET /mrp/runs/{run_id}/planned-orders",
                 "GET /mrp/runs/{run_id}/demand", "GET /mrp/runs/{run_id}/exceptions",
                 "GET /mrp/runs/{run_id}/items/{item_id}")


def run_plant(api: Api, plant: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """push_plant + one MRP run at the plant's as_of with its params. Returns (maps, run)."""
    from oracle.adapters import mrp_params_body

    api.need(*MRP_ENDPOINTS)
    maps = push_plant(api, plant)
    run = api.run_mrp(**mrp_params_body(plant.params))
    assert run["status"] == "completed", run
    return maps, run


def assert_run_matches_oracle(api: Api, run: dict[str, Any], plant: Any, maps: dict[str, Any]) -> None:
    """Planned orders (item, kind, qty, need, start, segment) and demand projected dates equal the oracle's."""
    from collections import Counter

    from oracle import run_oracle

    res = run_oracle(plant)
    pn = {i: it.part_number for i, it in plant.items.items()}
    want = Counter((pn[p.item_id], p.kind, round(p.qty, 6), p.need_date.isoformat(), p.start_date.isoformat(),
                    p.segment) for p in res.planned)
    got = Counter((p["item"]["part_number"], p["kind"], round(p["qty"], 6), p["need_date"], p["start_date"],
                   seg(p["segment"])) for p in mrp_planned(api, run["id"]))
    assert got == want, (got - want, want - got)
    rows = mrp_demand(api, run["id"])
    for dp in res.demand:
        if dp.key[0] != "demand":
            continue
        row = demand_row(rows, maps["demand_lines"][dp.key[1]])
        assert row["projected_date"] == dp.projected_date.isoformat(), (row, dp)
        assert row["late_days"] == dp.late_days, (row, dp)


# ---------------------------------------------------------------------- real API processes (concurrency)


class Servers:
    """`n` uvicorn processes of the real app on one database (single_user). `bases[i]` = .../api/v1/mfg."""

    def __init__(self, db_url: str, log_dir: Any, n: int = 2):
        import os
        import socket
        import subprocess
        import sys
        from pathlib import Path

        backend = Path(__file__).resolve().parents[2]
        self.procs: list[Any] = []
        self.bases: list[str] = []
        self.logs = [Path(log_dir) / f"api{i}.log" for i in range(n)]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SP_", "DATABASE_URL", "AUTH_", "JOB_"))}
        env.update(DATABASE_URL=db_url, AUTH_MODE="single_user", JOB_BACKEND="inline", RUN_WORKERS="1",
                   PYTHONPATH=str(backend))
        for i in range(n):
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            log = open(self.logs[i], "wb")
            self.procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "superplanner.api.main:app", "--host", "127.0.0.1", "--port",
                 str(port)], cwd=backend, env=env, stdout=log, stderr=subprocess.STDOUT))
            self.bases.append(f"http://127.0.0.1:{port}{MFG}")
            self._wait(port, i)

    def _wait(self, port: int, i: int) -> None:
        import time

        import httpx

        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{port}{V1}/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            assert self.procs[-1].poll() is None, self.logs[i].read_text()[-3000:]
            assert time.monotonic() < deadline, "API did not start"
            time.sleep(0.2)

    def close(self) -> str:
        import subprocess

        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
        return "".join(x.read_text(errors="replace") for x in self.logs)


# ---------------------------------------------------------------------- workspaces and members (10)


MEMBER_ENDPOINTS = ("GET /me", "GET /workspaces", "GET /members", "POST /members", "PUT /members/{member_id}",
                    "DELETE /members/{member_id}")


def add_member(acc: Accounts, owner_email: str, email: str, roles: list[str]) -> Api:
    """Sign `email` up, make it a member of `owner_email`'s plant with `roles`; returns the member's Api bound to
    the owner's workspace (X-SP-Workspace)."""
    owner = acc.user(owner_email)
    acc.user(email)
    owner.post("/members", {"email": email, "roles": roles})
    return acc.user(email).in_workspace(acc.uid(owner_email))


def audit_events(app: Any, entity_type: str | None = None) -> list[Any]:
    from sqlalchemy import select

    from superplanner.api.db.models import AuditEventRow as t
    from superplanner.api.db.ownership import system_scope

    q = select(t.entity_type, t.action, t.entity_id, t.actor_id, t.details).order_by(t.id)
    if entity_type:
        q = q.where(t.entity_type == entity_type)
    with system_scope(), app.state.ctx.db.read() as s:
        return list(s.execute(q).all())
