"""Helpers for the WP-D acceptance suite (module name unique across backend/tests: `accm1_helpers`)."""

from __future__ import annotations

import io
import re
from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

V1 = "/api/v1"
MFG = f"{V1}/mfg"
PASSWORD = "correct horse battery staple"
AS_OF = "2026-11-02"
RESET = {"confirm": "DELETE ALL MANUFACTURING DATA"}

# M1-DESIGN 11.3 (jump-to-fix links) resolved against the frontend route patterns of 11.1
# (frontend/src/mfg/routes.tsx). Each entry: entity type -> regex with named groups for the ids it carries.
ID = r"[a-z]{3}_[0-9a-f]{32}"
LINK_PATTERNS: dict[str, re.Pattern[str]] = {
    "item": re.compile(rf"^/mfg/items/(?P<item>{ID})(?:/(?:bom|routing)(?:\?(?:bom|routing)=(?P<doc>{ID}))?)?$"),
    "bom": re.compile(rf"^/mfg/items/(?P<item>{ID})/bom\?bom=(?P<bom>{ID})$"),
    "bom_line": re.compile(
        rf"^/mfg/items/(?P<item>{ID})/bom(?:/(?P<edit_bom>{ID})/edit\?line=(?P<eline>{ID})"
        rf"|\?bom=(?P<bom>{ID})&line=(?P<line>{ID}))$"),
    "routing": re.compile(rf"^/mfg/items/(?P<item>{ID})/routing\?routing=(?P<routing>{ID})$"),
    "operation": re.compile(rf"^/mfg/items/(?P<item>{ID})/routing\?routing=(?P<routing>{ID})&op=(?P<seq>\d+)$"),
    "group": re.compile(rf"^/mfg/plant/groups\?group=(?P<group>{ID})$"),
    "line": re.compile(rf"^/mfg/plant/groups\?line=(?P<line>{ID})$"),
    "shift_template": re.compile(rf"^/mfg/plant/shifts\?template=(?P<template>{ID})$"),
    "shift_assignment": re.compile(rf"^/mfg/plant/shifts\?assignment=(?P<assignment>{ID})$"),
    "calendar_exception": re.compile(rf"^/mfg/plant/calendar\?exception=(?P<exception>{ID})$"),
    "skill": re.compile(rf"^/mfg/resources/skills\?skill=(?P<skill>{ID})$"),
    "operator": re.compile(rf"^/mfg/resources/operators\?operator=(?P<operator>{ID})$"),
    "tool_pool": re.compile(rf"^/mfg/resources/tooling\?tool=(?P<tool>{ID})$"),
    "plant": re.compile(r"^/mfg/plant/settings$"),
}

# Every route pattern of frontend/src/mfg/routes.tsx (path part only; any link must match one of these).
FRONTEND_ROUTES = [re.compile(p) for p in (
    r"^/mfg$", r"^/mfg/items$", rf"^/mfg/items/{ID}$", rf"^/mfg/items/{ID}/bom$", rf"^/mfg/items/{ID}/bom/{ID}/edit$",
    rf"^/mfg/items/{ID}/where-used$", rf"^/mfg/items/{ID}/routing$", r"^/mfg/plant/groups$", r"^/mfg/plant/shifts$",
    r"^/mfg/plant/calendar$", r"^/mfg/plant/settings$", r"^/mfg/resources/skills$", r"^/mfg/resources/operators$",
    r"^/mfg/resources/tooling$", r"^/mfg/health$", r"^/mfg/import$", rf"^/mfg/import/{ID}$")]


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def acc_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, auth_mode="accounts", password_hash_profile="fast",
                               auth_signin_limit_per_ip=1000, auth_signup_limit_per_ip=1000,
                               auth_signin_limit_per_email=1000, **overrides))


def sign_up(app: Any, email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{V1}/auth/sign-up", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def im(v: int) -> dict[str, str]:
    return {"If-Match": f'"{v}"'}


class Api:
    """Thin wrapper over /api/v1/mfg with status assertions."""

    def __init__(self, c: TestClient):
        self.c = c

    def raw(self, method: str, path: str, **kw: Any):
        return self.c.request(method, MFG + path, **kw)

    def call(self, method: str, path: str, status: int, **kw: Any) -> Any:
        r = self.raw(method, path, **kw)
        assert r.status_code == status, (method, path, r.status_code, r.text[:3000])
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r

    def get(self, path: str, status: int = 200, **params: Any) -> Any:
        return self.call("GET", path, status, params=params or None)

    def post(self, path: str, body: Any = None, status: int = 201, version: int | None = None) -> Any:
        return self.call("POST", path, status, json={} if body is None else body,
                         headers=im(version) if version is not None else {})

    def put(self, path: str, body: Any, version: int, status: int = 200) -> Any:
        return self.call("PUT", path, status, json=body, headers=im(version))

    def delete(self, path: str, version: int | None = None, status: int = 204) -> Any:
        return self.call("DELETE", path, status, headers=im(version) if version is not None else {})

    # ------------------------------------------------------------------ conveniences
    def load(self, sample: str, replace: bool = False) -> dict[str, Any]:
        return self.post(f"/samples/{sample}/load", {"replace": replace}, status=200)

    def health(self, as_of: str = AS_OF, horizon: int = 90) -> dict[str, Any]:
        return self.get("/health", as_of=as_of, horizon_days=horizon)

    def item(self, pn: str) -> dict[str, Any]:
        items = self.get("/items", q=pn, limit=200)["items"]
        hit = [i for i in items if i["part_number"] == pn]
        assert len(hit) == 1, (pn, [i["part_number"] for i in items])
        return hit[0]

    def by_code(self, coll: str, code: str) -> dict[str, Any]:
        hit = [x for x in self.get(coll)["items"] if x["code"] == code]
        assert len(hit) == 1, (coll, code)
        return hit[0]

    def released_bom(self, pn: str) -> dict[str, Any]:
        it = self.item(pn)
        rel = [b for b in self.get(f"/items/{it['id']}/boms")["items"] if b["status"] == "released"]
        assert len(rel) == 1, rel
        return self.get(f"/boms/{rel[0]['id']}")

    def released_routing(self, pn: str, priority: int = 1) -> dict[str, Any]:
        it = self.item(pn)
        rel = [r for r in self.get(f"/items/{it['id']}/routings")["items"]
               if r["status"] == "released" and r["priority"] == priority]
        assert len(rel) == 1, rel
        return self.get(f"/routings/{rel[0]['id']}")

    def upload(self, data: bytes, filename: str, sheet: str | None = None, status: int = 201) -> Any:
        params = {"filename": filename}
        if sheet:
            params["sheet"] = sheet
        return self.call("POST", "/imports", status, params=params, content=data,
                         headers={"content-type": "application/octet-stream"})

    def wizard(self, data: bytes, filename: str, *, options: dict[str, Any] | None = None,
               sheet: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Upload -> mapping from the suggestions without edits -> preview; returns (record, preview)."""
        rec = self.upload(data, filename, sheet)
        mapping = {"sheets": {s["name"]: s["suggested"] or {"target": None, "columns": {}} for s in rec["sheets"]},
                   "options": options or {"replace_children": True, "release": False,
                                          "default_effective_from": None}}
        rec = self.put(f"/imports/{rec['id']}/mapping", mapping, rec["row_version"])
        return rec, rec["preview"]

    def commit(self, rec: dict[str, Any], status: int = 200) -> Any:
        return self.post(f"/imports/{rec['id']}/commit", {}, status=status, version=rec["row_version"])


BOM_INPUT_FIELDS = ("item_id", "revision", "version", "effective_from", "effective_to", "serial_from", "serial_to",
                    "note")
LINE_INPUT_FIELDS = ("id", "find_number", "child_item_id", "qty_per", "uom", "scrap_pct", "ref_designators",
                     "alt_group", "alt_priority", "operation_seq", "note")
ROUTING_INPUT_FIELDS = ("item_id", "revision", "code", "version", "priority", "effective_from", "effective_to",
                        "serial_from", "serial_to", "note")
OP_INPUT_FIELDS = ("id", "seq", "name", "description", "group_id", "setup_minutes", "run_minutes", "run_per",
                   "units_per_panel", "units_per_batch", "queue_minutes", "move_minutes", "wait_minutes", "labor",
                   "crew_size", "skill_id", "transfer_batch", "yield_pct", "inspection_gate", "interruptible")


def bom_input(rec: dict[str, Any]) -> dict[str, Any]:
    out = {k: rec[k] for k in BOM_INPUT_FIELDS}
    out["lines"] = [{k: ln[k] for k in LINE_INPUT_FIELDS} for ln in rec["lines"]]
    return out


def routing_input(rec: dict[str, Any]) -> dict[str, Any]:
    out = {k: rec[k] for k in ROUTING_INPUT_FIELDS}
    out["operations"] = [{**{k: op[k] for k in OP_INPUT_FIELDS},
                          "tools": [{"tool_pool_id": t["tool_pool_id"], "qty": t["qty"]} for t in op["tools"]]}
                         for op in rec["operations"]]
    return out


def item_input(rec: dict[str, Any]) -> dict[str, Any]:
    drop = {"id", "row_version", "created_at", "updated_at", "has_bom", "has_routing", "used_in_count"}
    return {k: v for k, v in rec.items() if k not in drop}


def xlsx_sheets(data: bytes) -> dict[str, list[tuple[Any, ...]]]:
    """Parse an xlsx export into {sheet: [row tuples]} with openpyxl (independent of the product reader)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    finally:
        wb.close()


def check_link(api: Api, issue: dict[str, Any]) -> None:
    """The issue link matches the 11.3 pattern of its entity type, a frontend route pattern of 11.1, and every id it
    names exists for this user (GET answers 200)."""
    link = issue["link"]
    etype = issue["entity"]["type"]
    assert link, issue
    pat = LINK_PATTERNS[etype]
    m = pat.match(link)
    assert m, (etype, link)
    path = link.split("?", 1)[0]
    assert any(r.match(path) for r in FRONTEND_ROUTES), link
    g = {k: v for k, v in m.groupdict().items() if v}
    if "item" in g:
        api.get(f"/items/{g['item']}")
    for key in ("bom", "edit_bom"):
        if key in g:
            b = api.get(f"/boms/{g[key]}")
            assert b["item_id"] == g["item"], link
            if key == "edit_bom":
                assert b["status"] == "draft", link
                assert any(ln["id"] == g["eline"] for ln in b["lines"]), link
            if "line" in g:
                assert b["status"] != "draft", link
                assert any(ln["id"] == g["line"] for ln in b["lines"]), link
    if "doc" in g:
        r = api.raw("GET", f"/boms/{g['doc']}") if "/bom?" in link else api.raw("GET", f"/routings/{g['doc']}")
        assert r.status_code == 200, link
    if "routing" in g:
        r = api.get(f"/routings/{g['routing']}")
        assert r["item_id"] == g["item"], link
        if "seq" in g:
            assert any(op["seq"] == int(g["seq"]) for op in r["operations"]), link
    if "group" in g:
        api.get(f"/groups/{g['group']}")
    if etype == "line":
        api.get(f"/lines/{g['line']}")
    if "template" in g:
        api.get(f"/shift-templates/{g['template']}")
    if "assignment" in g:
        assert any(a["id"] == g["assignment"] for a in api.get("/shift-assignments")["items"]), link
    if "exception" in g:
        assert any(x["id"] == g["exception"] for x in api.get("/calendar-exceptions")["items"]), link
    if "skill" in g:
        assert any(x["id"] == g["skill"] for x in api.get("/skills")["items"]), link
    if "operator" in g:
        api.get(f"/operators/{g['operator']}")
    if "tool" in g:
        assert any(x["id"] == g["tool"] for x in api.get("/tool-pools")["items"]), link
