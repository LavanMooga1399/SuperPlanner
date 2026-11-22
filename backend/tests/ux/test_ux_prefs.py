"""Per-user preferences: CRUD with If-Match, key / size / count limits, personal (not workspace) scope, tokens
refused (403 TOKEN_SCOPE)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up
from superplanner.api.routes import preferences as PREFS

ME = f"{V1}/me/preferences"


def _put(c: TestClient, key: str, value, version: int | None = None, status: int = 200):
    h = {"If-Match": f'"{version}"'} if version is not None else {}
    r = c.put(f"{ME}/{key}", json={"value": value}, headers=h)
    assert r.status_code == status, r.text
    return r


def test_crud_if_match_and_limits(client: TestClient, monkeypatch):
    assert client.get(ME).json() == {"items": [], "total": 0, "limits": {"max_keys": 200, "max_bytes": 32768}}
    assert client.get(f"{ME}/table.mfg.work-orders").status_code == 404
    layout = {"columns": [{"id": "number", "width": 120}, {"id": "status", "hidden": True}], "density": "compact"}
    r = _put(client, "table.mfg.work-orders", layout, status=201)
    assert r.headers["ETag"] == '"1"' and r.json()["value"] == layout and r.json()["row_version"] == 1
    got = client.get(f"{ME}/table.mfg.work-orders")
    assert got.json()["value"] == layout and got.headers["ETag"] == '"1"'
    # existing key: If-Match required (428), stale (412), current (200)
    e = _put(client, "table.mfg.work-orders", {}, status=428).json()["error"]
    assert e["code"] == "PRECONDITION_REQUIRED" and e["details"]["current_version"] == 1
    assert _put(client, "table.mfg.work-orders", {}, 7, 412).json()["error"]["details"]["current_version"] == 1
    r = _put(client, "table.mfg.work-orders", {"columns": []}, 1)
    assert r.json()["row_version"] == 2 and r.headers["ETag"] == '"2"'
    # create with If-Match "0" is allowed; with another version the row is gone -> 412
    _put(client, "theme", "dark", 0, 201)
    _put(client, "views:mfg.demand", [1, 2], 3, 412)
    lst = client.get(ME).json()
    assert [(i["key"], i["row_version"]) for i in lst["items"]] == [("table.mfg.work-orders", 2), ("theme", 1)]
    assert "value" not in lst["items"][0] and lst["items"][1]["size_bytes"] == len('"dark"')
    assert [i["key"] for i in client.get(ME, params={"prefix": "table."}).json()["items"]] == ["table.mfg.work-orders"]
    # key pattern, size
    for bad in ("-x", ".x", "a b", "a" * 129, "ä"):
        r = client.put(f"{ME}/{bad}", json={"value": 1})
        assert r.status_code in (404, 422), (bad, r.status_code)
        if r.status_code == 422:
            assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = _put(client, "big", "x" * (32 * 1024), status=413)
    assert r.json()["error"]["code"] == "PREF_TOO_LARGE"
    assert client.put(f"{ME}/k", json={"value": 1, "extra": 2}).status_code == 422
    # delete: If-Match required and checked
    assert client.delete(f"{ME}/theme").status_code == 428
    assert client.delete(f"{ME}/theme", headers={"If-Match": '"9"'}).status_code == 412
    assert client.delete(f"{ME}/theme", headers={"If-Match": '"1"'}).status_code == 204
    assert client.delete(f"{ME}/theme", headers={"If-Match": '"1"'}).status_code == 404
    assert client.delete(f"{ME}/theme").status_code == 404                   # unknown key: 404 before 428
    # per-user key limit
    monkeypatch.setattr(PREFS, "MAX_KEYS_PER_USER", 2)
    _put(client, "k2", True, status=201)
    assert _put(client, "k3", True, status=409).json()["error"]["code"] == "PREF_TOO_MANY"
    _put(client, "k2", False, 1)                                    # updating an existing key is still allowed


def test_personal_scope_and_tokens_refused(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        a = sign_up(app, "a@example.com")
        b = sign_up(app, "b@example.com")
        aid = a.get(f"{V1}/auth/session").json()["user"]["id"]
        Api(a).post("/members", {"email": "b@example.com", "roles": ["viewer"]})
        _put(a, "theme", "dark", status=201)
        # b is a member of a's workspace, but preferences are personal: the workspace header changes nothing
        assert b.get(f"{ME}/theme", headers={"X-SP-Workspace": aid}).status_code == 404
        _put(b, "theme", "light", status=201)
        assert a.get(f"{ME}/theme").json()["value"] == "dark"
        assert b.get(ME).json()["total"] == 1
        # API tokens: 403 TOKEN_SCOPE on every preferences route
        raw = a.post(f"{V1}/tokens", json={"name": "erp", "scopes": ["view"]}).json()["token"]
        t = TestClient(app)
        t.headers["Authorization"] = f"Bearer {raw}"
        for method, path in (("GET", ME), ("GET", f"{ME}/theme"), ("PUT", f"{ME}/theme"), ("DELETE", f"{ME}/theme")):
            r = t.request(method, path, json={"value": 1} if method == "PUT" else None)
            assert r.status_code == 403 and r.json()["error"]["code"] == "TOKEN_SCOPE", (method, r.text)
        # no session: 401
        assert TestClient(app).get(ME).status_code == 401
