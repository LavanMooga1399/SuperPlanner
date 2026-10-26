"""WP-D adversarial: cross-user id guessing on every /api/v1/mfg route (accounts mode). User B uses user A's ids
on every route with a path id (valid bodies and queries, proven valid by A getting 412 for the same request with a
stale If-Match, or 200 for reads): B always gets 404 NOT_FOUND with a body identical to the one for an id that never
existed; list filters with A's ids return nothing; body references to A's ids are 422 MFG_UNKNOWN_REFERENCE; A's
data is byte-identical afterwards. Anonymous calls are 401 on every route."""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient

from accm1_helpers import MFG, Api, acc_app, sign_up

RECORD_ONLY = {"id", "row_version", "created_at", "updated_at", "has_bom", "has_routing", "used_in_count", "item",
               "status", "released_at", "obsoleted_at", "line_count", "assignment_count", "operator_count",
               "operation_count", "group", "eligible_items", "template", "target", "skills", "shift_template",
               "home_group", "lines", "assignments", "data_version"}


def _input(rec: dict[str, Any], keep: tuple[str, ...] = ()) -> dict[str, Any]:
    return {k: v for k, v in rec.items() if k not in RECORD_ONLY or k in keep}


def _world(a: Api) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    a.load("small")
    top = a.item("SM-100")
    bom = a.released_bom("SM-100")
    rt = a.released_routing("SM-100")
    grp = a.by_code("/groups", "SMT")
    line = a.by_code("/lines", "SMT-1")
    tmpl = a.by_code("/shift-templates", "REG")
    asg = a.get("/shift-assignments")["items"][0]
    exc = a.post("/calendar-exceptions", {"scope": "plant", "kind": "holiday", "start": "2026-12-24T00:00:00+05:30",
                                          "end": "2026-12-25T00:00:00+05:30", "label": "A only"})
    skill = a.by_code("/skills", "SMT-OP")
    op = a.get("/operators")["items"][0]
    tool = a.get("/tool-pools")["items"][0]
    imp = a.upload(b"part_number,make_buy,lead_time_days\nA-ONLY,buy,3\n", "a.csv", sheet="items")
    ids = {"item_id": top["id"], "bom_id": bom["id"], "routing_id": rt["id"], "group_id": grp["id"],
           "line_id": line["id"], "shift_template_id": tmpl["id"], "assignment_id": asg["id"],
           "exception_id": exc["id"], "skill_id": skill["id"], "operator_id": op["id"], "tool_pool_id": tool["id"],
           "import_id": imp["id"]}
    lines_in = [{k: ln[k] for k in ("id", "find_number", "child_item_id", "qty_per", "uom", "scrap_pct",
                                    "ref_designators", "alt_group", "alt_priority", "operation_seq", "note")}
                for ln in bom["lines"]]
    ops_in = []
    for o in rt["operations"]:
        d = {k: v for k, v in o.items() if k not in ("group", "skill", "tools")}
        d["tools"] = [{"tool_pool_id": t["tool_pool_id"], "qty": t["qty"]} for t in o["tools"]]
        ops_in.append(d)
    bodies = {
        "/items/{item_id}": _input(top),
        "/boms/{bom_id}": {**{k: bom[k] for k in ("item_id", "revision", "version", "effective_from", "effective_to",
                                                  "serial_from", "serial_to", "note")}, "lines": lines_in},
        "/routings/{routing_id}": {**{k: rt[k] for k in ("item_id", "revision", "code", "version", "priority",
                                                         "effective_from", "effective_to", "serial_from",
                                                         "serial_to", "note")}, "operations": ops_in},
        "/groups/{group_id}": _input(a.get(f"/groups/{grp['id']}")),
        "/lines/{line_id}": {**_input(line), "eligible_item_ids": [i["id"] for i in line["eligible_items"]]}
        if "eligible_item_ids" not in line else _input(line),
        "/shift-templates/{shift_template_id}": _input(tmpl),
        "/shift-assignments/{assignment_id}": _input(asg),
        "/calendar-exceptions/{exception_id}": _input(exc),
        "/skills/{skill_id}": _input(skill),
        "/operators/{operator_id}": _input(op),
        "/tool-pools/{tool_pool_id}": _input(tool),
        "/imports/{import_id}/mapping": {"sheets": {"items": imp["sheets"][0]["suggested"]}, "options": {}},
        "/boms/{bom_id}/release": {"effective_from": None, "supersede_previous": False},
        "/routings/{routing_id}/release": {"effective_from": None, "supersede_previous": False},
        "/boms/{bom_id}/copy": {"revision": None},
        "/routings/{routing_id}/copy": {"revision": None, "code": None},
    }
    return ids, bodies


QUERY = {"/lines/{line_id}/windows": {"from": "2026-11-02", "to": "2026-11-09"},
         "/routings/{routing_id}/time-preview": {"qty": 5}}


def _mfg_routes(app: Any) -> list[tuple[str, str]]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith(MFG + "/"):
            for m in sorted(ops):
                if m.upper() in ("GET", "POST", "PUT", "DELETE"):
                    out.append((m.upper(), path[len(MFG):]))
    return out


def _fill(template: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids[m.group(1)], template)


def _fake(ids: dict[str, str]) -> dict[str, str]:
    return {k: v[:4] + "0" * 32 for k, v in ids.items()}


def test_cross_user_id_guessing_on_every_mfg_route(db_url: str):
    app = acc_app(db_url)
    with TestClient(app):
        ca, cb = sign_up(app, "idor-a@example.com"), sign_up(app, "idor-b@example.com")
        a, b = Api(ca), Api(cb)
        b.load("small")                                    # B has the same natural keys, different ids
        ids, bodies = _world(a)
        export_before = a.call("GET", "/export", 200, params={"format": "zip"}).content
        imp_before = a.get(f"/imports/{ids['import_id']}")
        routes = _mfg_routes(app)
        assert len(routes) == 77, len(routes)
        with_ids = [(m, p) for m, p in routes if "{" in p and "{sample_id}" not in p]
        assert len(with_ids) == 45, len(with_ids)
        for method, tpl in with_ids:
            kw: dict[str, Any] = {}
            if method in ("PUT", "POST"):
                kw["json"] = bodies.get(tpl, {})
            if method in ("PUT", "POST", "DELETE") and not tpl.startswith("/imports/{import_id}") or \
                    tpl.endswith(("/commit", "/mapping")):
                kw["headers"] = {"If-Match": '"999"'}
            if tpl in QUERY:
                kw["params"] = QUERY[tpl]
            # the request is valid for its owner (412 for stale If-Match, 2xx for reads)
            if method == "GET":
                ra = a.raw(method, _fill(tpl, ids), **kw)
                assert ra.status_code == 200, (method, tpl, ra.text[:300])
            elif "headers" in kw:
                ra = a.raw(method, _fill(tpl, ids), **kw)
                assert ra.status_code == 412, (method, tpl, ra.status_code, ra.text[:300])
            rb = b.raw(method, _fill(tpl, ids), **kw)
            rf = b.raw(method, _fill(tpl, _fake(ids)), **kw)
            assert rb.status_code == 404, (method, tpl, rb.status_code, rb.text[:300])
            assert rb.json()["error"]["code"] == "NOT_FOUND"
            fake_body = rf.text
            for k, v in ids.items():
                fake_body = fake_body.replace(_fake(ids)[k], v)
            assert rb.text == fake_body, (method, tpl, rb.text, rf.text)
            assert dict(rb.headers).get("etag") is None
        # list filters with A's ids show nothing of A
        for path, params in (("/lines", {"group_id": ids["group_id"]}),
                             ("/shift-assignments", {"group_id": ids["group_id"]}),
                             ("/shift-assignments", {"line_id": ids["line_id"]}),
                             ("/shift-assignments", {"shift_template_id": ids["shift_template_id"]}),
                             ("/calendar-exceptions", {"line_id": ids["line_id"]}),
                             ("/calendar-exceptions", {"group_id": ids["group_id"]}),
                             ("/operators", {"skill_id": ids["skill_id"]}),
                             ("/calendar-exceptions", {})):
            r = b.raw("GET", path, params=params)
            assert r.status_code in (200, 404, 422), (path, params, r.status_code)
            if r.status_code == 200:
                found = [x for x in r.json()["items"] if x["id"] in set(ids.values()) or
                         x.get("label") == "A only"]
                assert found == [], (path, params)
        # body references to A's ids -> 422 MFG_UNKNOWN_REFERENCE (never a cross-owner link)
        bt = b.by_code("/shift-templates", "REG")
        bg = b.by_code("/groups", "SMT")
        b_item = b.item("SM-100")
        for path, body in (
            ("/boms", {"item_id": ids["item_id"], "lines": []}),
            ("/boms", {"item_id": b_item["id"], "lines": [{"find_number": "1", "child_item_id": ids["item_id"],
                                                          "qty_per": 1}]}),
            ("/routings", {"item_id": b_item["id"], "code": "X", "operations": [
                {"seq": 10, "name": "x", "group_id": ids["group_id"]}]}),
            ("/lines", {"group_id": ids["group_id"], "code": "B-L", "name": "B line"}),
            ("/lines", {"group_id": bg["id"], "code": "B-L2", "name": "B line", "eligible_item_ids": [ids["item_id"]]}),
            ("/operators", {"code": "B-OP", "name": "B", "skill_ids": [ids["skill_id"]]}),
            ("/operators", {"code": "B-OP2", "name": "B", "shift_template_id": ids["shift_template_id"]}),
            ("/operators", {"code": "B-OP3", "name": "B", "home_group_id": ids["group_id"]}),
            ("/shift-assignments", {"shift_template_id": ids["shift_template_id"], "target_type": "group",
                                    "group_id": bg["id"], "effective_from": "2026-01-01"}),
            ("/shift-assignments", {"shift_template_id": bt["id"], "target_type": "line",
                                    "line_id": ids["line_id"], "effective_from": "2026-01-01"}),
            ("/calendar-exceptions", {"scope": "group", "group_id": ids["group_id"], "kind": "holiday",
                                      "start": "2026-12-01T00:00:00Z", "end": "2026-12-02T00:00:00Z"}),
        ):
            r = b.raw("POST", path, json=body)
            assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_UNKNOWN_REFERENCE", \
                (path, r.status_code, r.text[:300])
        # B's where-used / explosion never reaches A's documents
        for it in b.get("/items", limit=200)["items"]:
            wu = b.get(f"/items/{it['id']}/where-used", include="all")
            assert all(r["bom_id"] not in (ids["bom_id"],) for r in wu["rows"])
        # A is unchanged
        assert a.call("GET", "/export", 200, params={"format": "zip"}).content == export_before
        assert a.get(f"/imports/{ids['import_id']}") == imp_before
        # B's reset leaves A alone
        b.post("/reset", {"confirm": "DELETE ALL MANUFACTURING DATA"}, status=200)
        assert a.call("GET", "/export", 200, params={"format": "zip"}).content == export_before

        # anonymous: 401 on all 77 routes
        anon = TestClient(app)
        for method, tpl in routes:
            path = _fill(tpl, {**ids, "sample_id": "small"})
            r = anon.request(method, MFG + path, json={} if method in ("POST", "PUT") else None)
            assert r.status_code == 401, (method, tpl, r.status_code)
        ca.close()
        cb.close()
