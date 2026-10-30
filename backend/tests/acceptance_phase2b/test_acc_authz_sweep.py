"""Authorization sweep (accounts mode): every route of the app (enumerated from `app.routes`, not from
OpenAPI, so hidden routes are included) is called as an anonymous visitor, as another signed-in user with the first
user's ids, and as a signed-in user without / with a wrong CSRF token or a foreign Origin."""

from __future__ import annotations

import copy
import re
import time
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from acc_helpers import API, FAST_FIN, FAST_SOLVER, FIN, PASSWORD, wait_for
from superplanner.api.config import Settings
from superplanner.api.main import create_app

PUBLIC = {("GET", "/api/v1/health"), ("GET", "/api/v1/health/live"), ("GET", "/api/v1/health/ready"),
          ("GET", "/api/v1/auth/session"), ("POST", "/api/v1/auth/sign-up"), ("POST", "/api/v1/auth/sign-in"),
          ("POST", "/api/v1/auth/sign-out"), ("POST", "/api/v1/auth/change-password"),
          ("GET", "/metrics")}   # /metrics: public unless METRICS_TOKEN (B 5.4); checked separately below
PARAM = re.compile(r"\{([a-z_]+)\}")


def _walk(routes):
    for r in routes:
        if isinstance(r, APIRoute) or (hasattr(r, "methods") and hasattr(r, "path") and hasattr(r, "endpoint")
                                       and type(r).__name__ == "_EffectiveRouteContext"):
            yield r
        elif hasattr(r, "effective_route_contexts"):          # FastAPI >= 0.140 lazily included routers
            yield from _walk(r.effective_route_contexts())


def all_routes(app) -> list[tuple[str, str]]:
    out = []
    for r in _walk(app.routes):
        if r.path.startswith(("/docs", "/redoc", "/openapi")):
            continue
        for m in sorted(set(r.methods) - {"HEAD", "OPTIONS"}):
            out.append((m, r.path))
    return sorted(set(out))


def acc_app(db_url: str, **kw: Any):
    return create_app(Settings(database_url=db_url, auth_mode="accounts", password_hash_profile="fast",
                               auth_signin_limit_per_ip=1000, auth_signup_limit_per_ip=1000,
                               auth_signin_limit_per_email=1000, **kw))


def signed_up(app, email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/sign-up", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def wait_status(c: TestClient, path: str, timeout: float = 90) -> dict[str, Any]:
    return wait_for(lambda: (lambda j: j if j["status"] in ("completed", "cancelled", "failed") else None)(
        c.get(path).json()), timeout, 0.1, what=path)


def make_world(c: TestClient) -> dict[str, Any]:
    """User-owned objects of every kind; returns ids and the documents needed for valid request bodies."""
    w: dict[str, Any] = {}
    r = c.post(f"{API}/templates/manufacturing/instantiate",
               json={"start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": 4}})
    assert r.status_code == 201, r.text
    w["problem_id"] = r.json()["id"]
    w["problem_doc"] = r.json()["problem"]
    run = c.post(f"{API}/problems/{w['problem_id']}/solver-runs", json=FAST_SOLVER)
    assert run.status_code == 202, run.text
    w["run_id"] = run.json()["run_id"]
    st = wait_status(c, f"{API}/solver-runs/{w['run_id']}")
    assert st["status"] == "completed", st
    w["schedule_id"] = st["primary_schedule_id"]
    r = c.post(f"{FIN}/templates/young_professional/instantiate", json={"start_month": "2026-11"})
    assert r.status_code == 201, r.text
    w["plan_id"] = r.json()["id"]
    w["plan_doc"] = r.json()["plan"]
    fr = c.post(f"{FIN}/plans/{w['plan_id']}/runs", json=FAST_FIN)
    assert fr.status_code == 202, fr.text
    w["fin_run_id"] = fr.json()["run_id"]
    st = wait_status(c, f"{FIN}/runs/{w['fin_run_id']}")
    assert st["status"] == "completed", st
    w["result_id"] = st["result_id"]
    wi = c.post(f"{FIN}/plans/{w['plan_id']}/what-if",
                json={"changes": {"label": "More", "extra_monthly_savings": 1000}, "run": FAST_FIN,
                      "base_result_id": w["result_id"]})
    assert wi.status_code == 202, wi.text
    st = wait_status(c, f"{FIN}/runs/{wi.json()['run_id']}")
    assert st["status"] == "completed", st
    w["whatif_run_id"] = wi.json()["run_id"]
    w["whatif_result_id"] = st["result_id"]
    make_mfg_world(c, w)
    return w


MFG = f"{API}/mfg"


def _input(cls: Any, rec: dict[str, Any]) -> dict[str, Any]:
    """The Input-model fields of a record (nested BOM lines / operations / tools reduced too)."""
    from superplanner.mfg import model as mm

    nested = {"lines": mm.BomLineInput, "operations": mm.OperationInput, "tools": mm.OperationToolInput}
    out: dict[str, Any] = {}
    for f in cls.model_fields:
        v = rec.get(f)
        if f in nested and isinstance(v, list):
            v = [_input(nested[f], x) for x in v]
        out[f] = v
    return out


def make_mfg_world(c: TestClient, w: dict[str, Any]) -> None:
    """Manufacturing objects (M1-DESIGN 14.2): sample `small`, one import session, one draft BOM/routing."""
    from superplanner.mfg import model as mm

    r = c.post(f"{MFG}/samples/small/load", json={"replace": False})
    assert r.status_code == 200, r.text
    item = c.get(f"{MFG}/items", params={"q": "SM-100", "make_buy": "make"}).json()["items"][0]
    bom = c.get(f"{MFG}/items/{item['id']}/boms").json()["items"][0]
    rtg = c.get(f"{MFG}/items/{item['id']}/routings").json()["items"][0]
    bom, rtg = c.get(f"{MFG}/boms/{bom['id']}").json(), c.get(f"{MFG}/routings/{rtg['id']}").json()
    grp = c.get(f"{MFG}/groups").json()["items"][0]
    line = c.get(f"{MFG}/lines").json()["items"][0]
    tpl = c.get(f"{MFG}/shift-templates").json()["items"][0]
    asg = c.get(f"{MFG}/shift-assignments").json()["items"][0]
    exc = c.get(f"{MFG}/calendar-exceptions").json()["items"][0]
    skill = c.get(f"{MFG}/skills").json()["items"][0]
    op = c.get(f"{MFG}/operators").json()["items"][0]
    pool = c.get(f"{MFG}/tool-pools").json()["items"][0]
    r = c.post(f"{MFG}/imports", params={"filename": "items.csv", "sheet": "items"},
               content=b"part_number,make_buy\nSW-1,buy\n", headers={"content-type": "application/octet-stream"})
    assert r.status_code == 201, r.text
    w["mfg_ids"] = {"item_id": item["id"], "bom_id": bom["id"], "routing_id": rtg["id"], "group_id": grp["id"],
                    "line_id": line["id"], "shift_template_id": tpl["id"], "assignment_id": asg["id"],
                    "exception_id": exc["id"], "skill_id": skill["id"], "operator_id": op["id"],
                    "tool_pool_id": pool["id"], "import_id": r.json()["id"]}
    w["mfg_bodies"] = {
        "/items/{item_id}": _input(mm.ItemInput, item), "/boms/{bom_id}": _input(mm.BomInput, bom),
        "/routings/{routing_id}": _input(mm.RoutingInput, rtg), "/groups/{group_id}": _input(mm.GroupInput, grp),
        "/lines/{line_id}": _input(mm.LineInput, line),
        "/shift-templates/{shift_template_id}": _input(mm.ShiftTemplateInput, tpl),
        "/shift-assignments/{assignment_id}": _input(mm.ShiftAssignmentInput, asg),
        "/calendar-exceptions/{exception_id}": _input(mm.CalendarExceptionInput, exc),
        "/skills/{skill_id}": _input(mm.SkillInput, skill), "/operators/{operator_id}": _input(mm.OperatorInput, op),
        "/tool-pools/{tool_pool_id}": _input(mm.ToolPoolInput, pool),
        "/imports/{import_id}/mapping": {"sheets": {"items": {"target": "items", "columns": {
            "part_number": "part_number", "make_buy": "make_buy"}}}, "options": {}},
        "/samples/{sample_id}/load": {"replace": False},
    }
    make_mfg_m2_world(c, w, item)


def make_mfg_m2_world(c: TestClient, w: dict[str, Any], make_item: dict[str, Any]) -> None:
    """M2 objects (M2-DESIGN 19.2): `small` was loaded with transactions; plus a member, a lot, a PR, a WO and one
    MRP run, so every new path parameter has a real id."""
    ids = w["mfg_ids"]
    other = f"member-{uuid.uuid4().hex[:8]}@example.com"
    signed_up(c.app, other)
    r = c.post(f"{MFG}/members", json={"email": other, "roles": ["viewer"]})
    assert r.status_code == 201, r.text
    ids["member_id"] = r.json()["id"]
    loc = next(x for x in c.get(f"{MFG}/locations").json()["items"] if x["code"] == "STORES")
    sup = c.get(f"{MFG}/suppliers").json()["items"][0]
    isup = c.get(f"{MFG}/item-suppliers", params={"supplier_id": sup["id"]}).json()["items"][0]
    r = c.post(f"{MFG}/items", json={"part_number": "SW-LOT", "make_buy": "buy", "lead_time_days": 5,
                                     "lot_controlled": True})
    assert r.status_code == 201, r.text
    r = c.post(f"{MFG}/inventory/postings", json={"type": "receipt_misc", "lines": [
        {"item_id": r.json()["id"], "location_id": loc["id"], "qty": 2, "lot_code": "L1"}]})
    assert r.status_code == 201, r.text
    posting = r.json()
    lot_id = posting["lines"][0]["lot"]["id"]
    buy = isup["item"]["id"]
    r = c.post(f"{MFG}/purchase-requests", json={"lines": [{"item_id": buy, "schedules": [
        {"requested_date": "2026-12-01", "qty": 1}]}]})
    assert r.status_code == 201, r.text
    pr = r.json()
    r = c.post(f"{MFG}/work-orders", json={"item_id": make_item["id"], "qty": 1, "due_date": "2026-12-15"})
    assert r.status_code == 201, r.text
    wo = r.json()
    order = c.get(f"{MFG}/demand-orders").json()["items"][0]
    r = c.post(f"{MFG}/mrp/runs", json={"label": "sweep"})
    assert r.status_code == 201, r.text
    run = r.json()
    planned = c.get(f"{MFG}/mrp/runs/{run['id']}/planned-orders").json()["items"]
    assert planned
    ids.update({"location_id": loc["id"], "supplier_id": sup["id"], "item_supplier_id": isup["id"],
                "lot_id": lot_id, "posting_id": posting["id"], "doc_id": pr["id"], "order_id": order["id"],
                "wo_id": wo["id"], "mrp_run_id": run["id"]})
    doc = {"lines": [{"item_id": buy, "schedules": [{"requested_date": "2026-12-01", "qty": 1}]}]}
    w["mfg_bodies"].update({
        "/locations/{location_id}": {"code": loc["code"], "name": loc["name"], "kind": loc["kind"]},
        "/suppliers/{supplier_id}": {"code": sup["code"], "name": sup["name"]},
        "/item-suppliers/{item_supplier_id}": {"item_id": buy, "supplier_id": isup["supplier"]["id"]},
        "/lots/{lot_id}": {"hold": False}, "/members/{member_id}": {"roles": ["viewer"]},
        "/mrp/runs/{run_id}": {"label": "x"}, "/purchase-orders/{doc_id}": doc, "/purchase-requests/{doc_id}": doc,
        "/demand-orders/{order_id}": {"demand_type": "customer", "lines": [
            {"item_id": make_item["id"], "qty": 1, "due_date": "2026-12-01"}]},
        "/work-orders/{wo_id}": {"item_id": make_item["id"], "qty": 1, "due_date": "2026-12-15"},
        "/mrp/runs/{run_id}/planned-orders/convert": {"orders": [{"id": planned[0]["id"]}]},
        "/purchase-requests/{doc_id}/reject": {"reason": "no"},
    })


def mfg_body_for(method: str, path: str, w: dict[str, Any]) -> dict[str, Any]:
    rel = path[len(MFG):]
    if rel == "/lines/{line_id}/windows":
        return {"params": {"from": "2026-11-02", "to": "2026-11-04"}}
    if rel == "/mrp/runs/{run_id}/compare":
        return {"params": {"with": w["mfg_ids"]["mrp_run_id"]}}
    if rel == "/mrp/runs/{run_id}/pegging":
        return {"params": {"item_id": w["mfg_ids"]["item_id"], "node": 0}}
    if method == "POST" and PARAM.search(rel) and rel not in w["mfg_bodies"] and not rel.startswith(
            ("/imports/", "/samples/", "/boms/", "/routings/")):
        return {"json": {}, "headers": {"If-Match": "1"}}            # M2 document actions
    if method == "PUT" and rel in w["mfg_bodies"]:
        return {"json": copy.deepcopy(w["mfg_bodies"][rel]), "headers": {"If-Match": "1"}}
    if method == "POST" and rel.endswith(("/release", "/obsolete", "/copy", "/commit")):
        return {"json": {}, "headers": {"If-Match": "1"}}
    if method == "POST" and rel in w["mfg_bodies"]:
        return {"json": copy.deepcopy(w["mfg_bodies"][rel]), "headers": {"If-Match": "1"}}
    if method == "POST" and rel == "/reset":
        return {"json": {"confirm": "DELETE ALL MANUFACTURING DATA"}}
    if method == "DELETE" and not rel.startswith("/imports/"):
        return {"headers": {"If-Match": "1"}}
    return {}


def snapshot(c: TestClient, w: dict[str, Any]) -> dict[str, Any]:
    """Everything a foreign request could have changed, seen by the owner."""
    return {
        "problems": sorted((p["id"], p["version"]) for p in c.get(f"{API}/problems").json()["items"]),
        "problem": c.get(f"{API}/problems/{w['problem_id']}").json()["version"],
        "runs": sorted((r["id"], r["status"]) for r in
                       c.get(f"{API}/problems/{w['problem_id']}/solver-runs").json()["items"]),
        "schedules": sorted((s["id"], s["status"]) for s in
                            c.get(f"{API}/problems/{w['problem_id']}/schedules").json()["items"]),
        "plans": sorted((p["id"], p["version"]) for p in c.get(f"{FIN}/plans").json()["items"]),
        "fin_runs": sorted((r["id"], r["status"]) for r in
                           c.get(f"{FIN}/plans/{w['plan_id']}/runs").json()["items"]),
        "results": sorted(r["id"] for r in c.get(f"{FIN}/plans/{w['plan_id']}/results").json()["items"]),
        "mfg_summary": c.get(f"{API}/mfg/summary").json(),
    }


def body_for(method: str, path: str, w: dict[str, Any]) -> dict[str, Any]:
    """A request that would succeed for the owner (so a non-404 answer for a stranger means a leak)."""
    kw: dict[str, Any] = {}
    if path.startswith(f"{API}/mfg/"):
        return mfg_body_for(method, path, w)
    if path.endswith("/problems/{problem_id}") and method == "PUT":
        kw = {"json": copy.deepcopy(w["problem_doc"]), "headers": {"If-Match": "1"}}
    elif path.endswith("/finance/plans/{plan_id}") and method == "PUT":
        kw = {"json": copy.deepcopy(w["plan_doc"]), "headers": {"If-Match": "1"}}
    elif path.endswith("/solver-runs") and method == "POST":
        kw = {"json": FAST_SOLVER}
    elif path.endswith("/finance/plans/{plan_id}/runs"):
        kw = {"json": FAST_FIN}
    elif path.endswith("/what-if"):
        kw = {"json": {"changes": {"extra_monthly_savings": 1000}, "run": FAST_FIN}}
    elif path.endswith("/replan"):
        kw = {"json": {"cutoff": "2026-10-20T08:00:00+05:30", "run": FAST_SOLVER}}
    elif path.endswith("/approve") or path.endswith("/send-to-planner"):
        kw = {"json": {}}
    return kw


def id_map(w: dict[str, Any], which: str = "baseline") -> dict[str, str]:
    return {"problem_id": w["problem_id"], "schedule_id": w["schedule_id"], "plan_id": w["plan_id"],
            "run_id": w["run_id"], "fin_run_id": w["fin_run_id"] if which == "baseline" else w["whatif_run_id"],
            "result_id": w["result_id"] if which == "baseline" else w["whatif_result_id"], **w["mfg_ids"]}


def fill(path: str, ids: dict[str, str]) -> str:
    def key(n: str) -> str:
        if n == "run_id" and "/finance/" in path:
            return "fin_run_id"
        return "mrp_run_id" if (n == "run_id" and "/mfg/" in path) else n
    return PARAM.sub(lambda m: ids[key(m.group(1))], path)


def normalize(body: bytes, ids: list[str]) -> bytes:
    for i in ids:
        body = body.replace(i.encode(), b"<ID>")
    return body


def test_anonymous_gets_401_on_every_non_public_route(db_url):
    app = acc_app(db_url)
    with TestClient(app) as anon:
        routes = all_routes(app)
        assert len(routes) >= 60, routes
        checked = 0
        for method, path in routes:
            if (method, path) in PUBLIC:
                continue
            url = PARAM.sub(lambda m: f"x{uuid.uuid4().hex[:12]}", path)
            if "compare" in path:
                url += "?a=x1&b=x2"
            r = anon.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
            assert r.status_code == 401, (method, path, r.status_code, r.text)
            assert r.json()["error"]["code"] == "AUTH_REQUIRED", (method, path, r.text)
            checked += 1
        assert checked >= 55
        # public routes really are public and leak nothing owned
        assert anon.get(f"{API}/auth/session").json()["authenticated"] is False
        assert anon.post(f"{API}/auth/sign-out").status_code == 204
        assert anon.post(f"{API}/auth/change-password",
                         json={"current_password": "x" * 12, "new_password": "y" * 12}).status_code == 401


def test_metrics_token_protects_metrics(db_url):
    app = acc_app(db_url, metrics_token="s3cret-token")
    with TestClient(app) as anon:
        assert anon.get("/metrics").status_code == 401
        assert anon.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert anon.get("/metrics", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


@pytest.mark.parametrize("which", ["baseline", "what_if"])
def test_other_user_gets_404_for_every_owned_id_and_changes_nothing(db_url, which):
    app = acc_app(db_url)
    with TestClient(app):
        a = signed_up(app, f"ana-{which}@example.com")
        b = signed_up(app, f"ben-{which}@example.com")
        wa = make_world(a)
        wb = make_world(b)
        before = snapshot(a, wa)
        ids_a = id_map(wa, which)
        a_ids = [v for v in ids_a.values()]
        routes = [rt for rt in all_routes(app) if PARAM.search(rt[1]) and rt not in PUBLIC]
        assert len(routes) >= 25
        leaks = []
        for method, path in routes:
            if "/templates/" in path or "/mfg/samples/" in path:
                continue                                    # template and sample ids are not owned
            kw = body_for(method, path, wa)
            r_foreign = b.request(method, fill(path, ids_a), **copy.deepcopy(kw))
            unknown = {k: f"x{uuid.uuid4().hex[:12]}" for k in ids_a}
            r_unknown = b.request(method, fill(path, unknown), **copy.deepcopy(kw))
            if r_foreign.status_code != 404:
                leaks.append((method, path, r_foreign.status_code, r_foreign.text[:200]))
                continue
            assert r_unknown.status_code == 404, (method, path, r_unknown.text)
            assert r_foreign.json()["error"]["code"] == "NOT_FOUND"
            assert normalize(r_foreign.content, a_ids) == normalize(r_unknown.content, list(unknown.values())), \
                (method, path, r_foreign.content, r_unknown.content)
        assert leaks == []
        # query-parameter references: compare with one foreign id, what-if on own plan with foreign base result
        r = b.get(f"{API}/schedules/compare", params={"a": wb["schedule_id"], "b": wa["schedule_id"]})
        assert r.status_code == 404, r.text
        r = b.get(f"{FIN}/results/compare", params={"a": wb["result_id"], "b": ids_a["result_id"]})
        assert r.status_code == 404, r.text
        r = b.post(f"{FIN}/plans/{wb['plan_id']}/what-if",
                   json={"changes": {"extra_monthly_savings": 5}, "run": FAST_FIN,
                         "base_result_id": ids_a["result_id"]})
        assert r.status_code == 404, r.text
        # B's lists show only B's objects
        assert {p["id"] for p in b.get(f"{API}/problems").json()["items"]} & {wa["problem_id"]} == set()
        assert {p["id"] for p in b.get(f"{FIN}/plans").json()["items"]} & {wa["plan_id"]} == set()
        # SSE of A's runs (stream and non-stream)
        for path in (f"{API}/solver-runs/{wa['run_id']}/events", f"{FIN}/runs/{wa['fin_run_id']}/events"):
            assert b.get(path, params={"stream": "false"}).status_code == 404
        time.sleep(0.5)
        assert snapshot(a, wa) == before


def test_csrf_and_origin_enforced_on_every_unsafe_route(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        a = signed_up(app, "csrf-a@example.com")
        wa = make_world(a)
        before = snapshot(a, wa)
        token = a.headers.pop("X-CSRF-Token")
        ids = id_map(wa)
        unsafe = [rt for rt in all_routes(app) if rt[0] in ("POST", "PUT", "PATCH", "DELETE")
                  and not rt[1].startswith(f"{API}/auth/")]
        assert len(unsafe) >= 25
        bad = []
        for method, path in unsafe:
            url = fill(path, {**ids, "template_id": "manufacturing", "sample_id": "small"})
            if "/finance/templates/" in path:
                url = url.replace("manufacturing", "young_professional")
            kw = body_for(method, path, wa)
            for label, headers in (("no token", {}), ("wrong token", {"X-CSRF-Token": "nope"}),
                                   ("foreign origin", {"X-CSRF-Token": token, "Origin": "https://evil.example"})):
                k = copy.deepcopy(kw)
                k["headers"] = {**k.get("headers", {}), **headers}
                r = a.request(method, url, **k)
                if r.status_code != 403 or r.json()["error"]["code"] != "CSRF_FAILED":
                    bad.append((label, method, path, r.status_code, r.text[:160]))
        assert bad == []
        # sign-out and change-password with a valid session also require the token
        assert a.post(f"{API}/auth/sign-out").status_code == 403
        assert a.post(f"{API}/auth/change-password",
                      json={"current_password": PASSWORD, "new_password": "another long passphrase"}
                      ).status_code == 403
        a.headers["X-CSRF-Token"] = token
        assert snapshot(a, wa) == before
        assert a.get(f"{API}/auth/session").json()["authenticated"] is True
