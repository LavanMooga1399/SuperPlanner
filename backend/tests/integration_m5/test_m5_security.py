"""Focused security tests (M5-DESIGN 4.6 SSRF guard, 3.3 API token workspace isolation)."""

from __future__ import annotations

import http.server
import threading

import pytest
from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, V1, acc_app, sign_up
from superplanner.api.errors import ApiError
from superplanner.identity import crypto
from superplanner.integration import outbox
from test_integration import DNS, KEY, Int, _enable, fake_getaddrinfo

# ---------------------------------------------------------------- SSRF


@pytest.fixture
def dns(monkeypatch):
    DNS.clear()
    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    return DNS


@pytest.mark.parametrize("url", [
    "http://erp.example.com/hook",               # https only
    "ftp://erp.example.com/hook",
    "https://user:pw@erp.example.com/hook",      # no credentials in the URL
    "https:///nohost",
    "https://127.0.0.1/hook",
    "https://10.1.2.3/hook",
    "https://192.168.0.10/hook",
    "https://172.16.5.5/hook",
    "https://169.254.169.254/latest/meta-data",  # cloud metadata (link-local)
    "https://0.0.0.0/hook",
    "https://[::1]/hook",
    "https://[fc00::1]/hook",
    "https://[fe80::1]/hook",
    "https://[::ffff:127.0.0.1]/hook",           # IPv4-mapped loopback
    "https://224.0.0.1/hook",                    # multicast
    "https://internal.example.com/hook",         # name resolving to a private address
    "https://mixed.example.com/hook",            # any private address among several refuses
    "https://unknown.example.com/hook",          # unresolvable
])
def test_ssrf_guard_refuses(dns, url):
    dns["internal.example.com"] = ["10.0.0.7"]
    dns["mixed.example.com"] = ["93.184.216.34", "127.0.0.1"]
    with pytest.raises(ApiError) as e:
        outbox.check_url(url, allow_private=False)
    assert e.value.status == 422 and e.value.code == "INT_URL_NOT_ALLOWED"


def test_ssrf_guard_allows_public_and_lan_opt_in(dns):
    dns["erp.example.com"] = ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]
    dns["mw.lan"] = ["10.0.0.7"]
    outbox.check_url("https://erp.example.com:8443/hook", allow_private=False)
    outbox.check_url("https://mw.lan/hook", allow_private=True)           # INTEGRATION_ALLOW_PRIVATE_TARGETS
    with pytest.raises(ApiError):
        outbox.check_url("http://mw.lan/hook", allow_private=True)        # still https only


def test_ssrf_recheck_at_delivery_dns_rebinding(db_url, dns):
    """An endpoint saved while its host resolved publicly is re-checked before every post: when the name now
    resolves to a private address nothing is sent and the attempt fails; FIFO resumes once it is public again."""
    from apimfgm2_helpers import Api, make_app
    from superplanner.api.mfg.services import integration as svc

    sent = []

    def post(url, body, headers):
        sent.append(url)
        return 200, ""

    dns["erp.example.com"] = ["93.184.216.34"]
    app = make_app(db_url, secrets_keys=[KEY], webhook_post=post, integration_allow_private_targets=False)
    with TestClient(app) as c:
        it, api = Int(c), Api(c)
        _enable(it, sor={"items": "superplanner"})
        ep = it.req("POST", "/endpoints", 201, json={"name": "erp", "url": "https://erp.example.com/hook",
                                                     "secret": "s" * 32}).json()
        loc, item = api.location("ST"), api.item("X1")
        api.receive(item["id"], loc["id"], 1)                              # one inventory.posting event
        from datetime import UTC, datetime, timedelta

        from superplanner.api.db.ownership import owner_scope

        t0 = datetime.now(UTC)
        dns["erp.example.com"] = ["10.0.0.9"]                               # rebinding to the LAN
        with owner_scope("usr_local"):
            r = svc.deliver_now(app.state.ctx, ep["id"], post, now=t0)
        assert r == {"delivered": 0, "failed": 1, "dead": 0} and sent == []
        d = it.req("GET", f"/deliveries?endpoint_id={ep['id']}", 200).json()["items"]
        assert d and d[0]["last_error"].startswith("INT_URL_NOT_ALLOWED") and d[0]["status"] == "pending"
        dns["erp.example.com"] = ["93.184.216.34"]
        with owner_scope("usr_local"):
            r = svc.deliver_now(app.state.ctx, ep["id"], post, now=t0 + timedelta(seconds=31))
        assert r["delivered"] == 1 and sent == ["https://erp.example.com/hook"]

def test_http_post_does_not_follow_redirects():
    hits: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/hook":
                self.send_response(307)
                self.send_header("Location", "/internal-admin")
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        code, err = outbox.http_post(f"http://127.0.0.1:{srv.server_port}/hook", b"{}", {})
    finally:
        srv.shutdown()
    assert code == 307 and hits == ["/hook"]       # failure, retried later; the redirect target is never hit


# ---------------------------------------------------------------- API token workspace isolation


def test_token_is_pinned_to_its_workspace(db_url):
    app = acc_app(db_url, secrets_keys=[crypto.new_key()])
    with TestClient(app):
        a = sign_up(app, "a@example.com")
        aid = a.get(f"{V1}/auth/session").json()["user"]["id"]
        b = sign_up(app, "b@example.com")
        bid = b.get(f"{V1}/auth/session").json()["user"]["id"]
        u = sign_up(app, "u@example.com")
        uid = u.get(f"{V1}/auth/session").json()["user"]["id"]
        assert a.post(f"{MFG}/items", json={"part_number": "A-ONLY", "make_buy": "buy"}).status_code == 201
        assert b.post(f"{MFG}/items", json={"part_number": "B-ONLY", "make_buy": "buy"}).status_code == 201
        assert u.post(f"{MFG}/items", json={"part_number": "U-OWN", "make_buy": "buy"}).status_code == 201
        m = a.post(f"{MFG}/members", json={"email": "u@example.com", "roles": ["viewer"]})
        assert m.status_code == 201, m.text
        b.post(f"{MFG}/members", json={"email": "u@example.com", "roles": ["planner"]})

        def bearer(raw: str) -> TestClient:
            c = TestClient(app)
            c.headers["Authorization"] = f"Bearer {raw}"
            return c

        def parts(c: TestClient, **h) -> list[str]:
            r = c.get(f"{MFG}/items", headers=h)
            assert r.status_code == 200, r.text
            return [x["part_number"] for x in r.json()["items"]]

        # a token for A's workspace sees A's data only, whatever header is sent
        ta = u.post(f"{V1}/tokens", json={"name": "a", "scopes": ["view", "master_edit"],
                                          "workspace_owner_id": aid}).json()
        ca = bearer(ta["token"])
        assert parts(ca) == ["A-ONLY"] and parts(ca, **{"X-SP-Workspace": aid}) == ["A-ONLY"]
        for other in (bid, uid, "usr_doesnotexist"):
            r = ca.get(f"{MFG}/items", headers={"X-SP-Workspace": other})
            assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", r.text
        # scopes are capped by the holder's role in that workspace (viewer cannot edit despite master_edit scope)
        r = ca.post(f"{MFG}/items", json={"part_number": "X", "make_buy": "buy"})
        assert r.status_code == 403
        # a token for U's own workspace cannot be pointed at A or B, although U is a member of both
        tu = bearer(u.post(f"{V1}/tokens", json={"name": "own", "scopes": ["view"]}).json()["token"])
        assert parts(tu) == ["U-OWN"]
        for other in (aid, bid):
            assert tu.get(f"{MFG}/items", headers={"X-SP-Workspace": other}).status_code == 404
        # no token for a workspace the creator is not a member of
        c = sign_up(app, "c@example.com")
        cid = c.get(f"{V1}/auth/session").json()["user"]["id"]
        r = u.post(f"{V1}/tokens", json={"name": "c", "scopes": ["view"], "workspace_owner_id": cid})
        assert r.status_code == 404
        # removing the membership cuts the token off immediately
        mem = next(x for x in a.get(f"{MFG}/members").json()["items"] if x["user"]["email"] == "u@example.com")
        assert a.delete(f"{MFG}/members/{mem['id']}",
                        headers={"If-Match": f'"{mem["row_version"]}"'}).status_code == 204
        r = ca.get(f"{MFG}/items")
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
        # the token list is per user: A cannot see or revoke U's tokens
        assert all(t["id"] != ta["id"] for t in a.get(f"{V1}/tokens").json()["items"])
        assert a.delete(f"{V1}/tokens/{ta['id']}").status_code == 404
