"""M6 security review fixes (design 11, review items M1-M4, m1-m6): one regression test each."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up


def test_m1_tokens_cannot_use_the_assistant(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        c = sign_up(app, "tok@m6.example")
        r = c.post(f"{V1}/tokens", json={"name": "x", "scopes": ["view", "assistant_use"]})
        assert r.status_code == 422                                     # not a mintable scope
        raw = c.post(f"{V1}/tokens", json={"name": "x", "scopes": ["view"]}).json()["token"]
        b = TestClient(app)
        b.headers["Authorization"] = f"Bearer {raw}"
        for method, path in (("GET", "/mfg/assistant/status"), ("GET", "/mfg/assistant/quick?kind=limits"),
                             ("GET", "/mfg/assistant/conversations"), ("POST", "/mfg/assistant/conversations")):
            r = b.request(method, V1 + path, json={} if method == "POST" else None)
            assert r.status_code == 403 and r.json()["error"]["code"] == "TOKEN_SCOPE", (path, r.text)
        assert Api(c).get("/assistant/status")["code"] == "AI_DISABLED"   # sessions unaffected


def test_m1_tool_permissions_honour_scopes():
    from superplanner.assistant.tools import ToolContext, current_permissions

    t = ToolContext(ctx=None, user_id="u", owner_id="o", permissions=frozenset(), conversation_id="c",
                    allow_whatif=False, refs=None, scopes=frozenset({"view"}),       # type: ignore[arg-type]
                    reload_permissions=lambda _t: frozenset({"view", "mrp_run", "trace_view"}))
    assert current_permissions(t) == frozenset({"view"})
