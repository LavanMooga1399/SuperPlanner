"""Identity security tests (M5-DESIGN 3.1-3.3; T-A1, T-A2, T-A3)."""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import PASSWORD, V1, Api, acc_app, sign_up
from fake_idp import CLIENT_ID, ISSUER, SECRET, FakeIdp
from superplanner.identity import crypto, oidc, totp
from superplanner.identity import tokens as tok

KEY = crypto.new_key()


# ---------------------------------------------------------------- T-A1 TOTP

def test_t_a1_rfc6238_vectors_and_replay():
    sec = base64.b32encode(b"12345678901234567890").decode()
    assert [totp.code_at(sec, t, 8) for t in (59, 1111111109, 1111111111, 1234567890, 2000000000, 20000000000)] == \
        ["94287082", "07081804", "14050471", "89005924", "69279037", "65353130"]
    code = totp.code_at(sec, 1_000_000)
    step = totp.verify(sec, code, 1_000_000, None)
    assert step == 1_000_000 // 30
    assert totp.verify(sec, code, 1_000_000, step) is None                    # same step twice: refused
    assert totp.verify(sec, totp.code_at(sec, 1_000_000 - 30), 1_000_000, None) is not None   # -1 step ok
    assert totp.verify(sec, totp.code_at(sec, 1_000_000 - 90), 1_000_000, None) is None       # -3 steps no
    assert totp.verify(sec, "12345", 1_000_000, None) is None and totp.verify(sec, "abcdef", 1, None) is None


def test_t_a1_totp_login_flow_enforced_and_single_use(db_url):
    app = acc_app(db_url, secrets_keys=[KEY])
    with TestClient(app):
        c = sign_up(app, "ana@example.com")
        setup = c.post(f"{V1}/auth/totp/setup").json()
        secret = setup["secret"]
        assert setup["otpauth_uri"].startswith("otpauth://totp/") and "secret=" in setup["otpauth_uri"]
        bad = c.post(f"{V1}/auth/totp/enable", json={"code": "000000"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "AUTH_TOTP_INVALID"
        en = c.post(f"{V1}/auth/totp/enable", json={"code": totp.code_at(secret, time.time())})
        assert en.status_code == 200, en.text
        rec = en.json()["recovery_codes"]
        assert len(rec) == 10
        eng = sa.create_engine(db_url)
        with eng.connect() as conn:
            row = conn.execute(sa.text("SELECT secret_enc, recovery_hashes FROM user_totp")).one()
        eng.dispose()
        assert secret not in row[0] and all(r not in str(row[1]) for r in rec)   # encrypted / hashed (I4)
        anon = TestClient(app)
        r = anon.post(f"{V1}/auth/sign-in", json={"email": "ana@example.com", "password": PASSWORD})
        assert r.status_code == 403 and r.json()["error"]["code"] == "AUTH_2FA_REQUIRED"
        pending = r.json()["error"]["details"]["pending_token"]
        assert "sp_session" not in anon.cookies and not anon.cookies
        # the code used to enable is a used step: a fresh code of the next step logs in
        step_now = int(time.time() // 30)
        code = totp.code_at(secret, (step_now + 1) * 30)
        ok = anon.post(f"{V1}/auth/login/totp", json={"pending_token": pending, "code": code})
        assert ok.status_code == 200, ok.text
        assert ok.json()["authenticated"]
        # a pending token works once; the same code is not accepted again for a new login
        r2 = TestClient(app).post(f"{V1}/auth/sign-in", json={"email": "ana@example.com", "password": PASSWORD})
        p2 = r2.json()["error"]["details"]["pending_token"]
        again = TestClient(app).post(f"{V1}/auth/login/totp", json={"pending_token": p2, "code": code})
        assert again.status_code == 422
        rc = TestClient(app).post(f"{V1}/auth/login/totp", json={"pending_token": p2, "recovery_code": rec[0]})
        assert rc.status_code == 200
        r3 = TestClient(app).post(f"{V1}/auth/sign-in", json={"email": "ana@example.com", "password": PASSWORD})
        p3 = r3.json()["error"]["details"]["pending_token"]
        reuse = TestClient(app).post(f"{V1}/auth/login/totp", json={"pending_token": p3, "recovery_code": rec[0]})
        assert reuse.status_code == 422                                           # recovery codes: single use
        assert TestClient(app).post(f"{V1}/auth/login/totp", json={"pending_token": "x" * 40, "code": code}) \
            .status_code == 401


# ---------------------------------------------------------------- T-A2 OIDC

def _oidc_app(db_url, idp, **kw):
    oidc.CACHE.items.clear()
    return acc_app(db_url, oidc_issuer=ISSUER, oidc_client_id=CLIENT_ID, oidc_client_secret=SECRET,
                   oidc_allowed_domains=["corp.example"], oidc_required_domains=["corp.example"], oidc_http=idp,
                   public_base_url="http://testserver", **kw)


def _login(client, idp, **kw):
    r = client.get(f"{V1}/auth/oidc/login", params={"next": "/mfg"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    code, state = idp.authorize(r.headers["location"], **kw)
    return client.get(f"{V1}/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)


def test_t_a2_oidc_valid_login_jit_and_sso_required(db_url):
    idp = FakeIdp()
    app = _oidc_app(db_url, idp)
    with TestClient(app) as c:
        cfg = c.get(f"{V1}/auth/config").json()
        assert cfg["sso_enabled"] and cfg["sso_required_domains"] == ["corp.example"]
        r = _login(c, idp)
        assert r.status_code == 302 and r.headers["location"] == "/mfg", r.text
        me = c.get(f"{V1}/auth/session").json()
        assert me["authenticated"] and me["user"]["email"] == "ana@corp.example"
        exp = datetime.fromisoformat(me["expires_at"].replace("Z", "+00:00"))
        assert exp - datetime.now(UTC) <= timedelta(hours=12, minutes=1)        # SSO_SESSION_HOURS
        again = _login(TestClient(app), idp)                                     # linked by (iss, sub)
        assert again.status_code == 302
        pw = TestClient(app).post(f"{V1}/auth/sign-in", json={"email": "ana@corp.example", "password": "x" * 12})
        assert pw.status_code == 403 and pw.json()["error"]["code"] == "AUTH_SSO_REQUIRED"
        other = _login(TestClient(app), idp, email="eve@other.example", sub="sub-9")
        assert other.status_code == 403 and other.json()["error"]["code"] == "AUTH_SSO_NOT_ALLOWED"
        unverified = _login(TestClient(app), idp, email="bob@corp.example", sub="sub-8", verified=False)
        assert unverified.status_code == 403


@pytest.mark.parametrize("case", ["wrong_aud", "expired", "bad_nonce", "unknown_kid", "wrong_iss", "hs256",
                                  "no_nonce"])
def test_t_a2_oidc_bad_tokens_are_refused(db_url, case):
    idp = FakeIdp()
    if case == "wrong_aud":
        idp.claims_override = {"aud": "someone-else"}
    elif case == "expired":
        idp.claims_override = {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}
    elif case == "bad_nonce":
        idp.claims_override = {"nonce": "forged"}
    elif case == "unknown_kid":
        idp.header_override = {"kid": "k-unknown"}
    elif case == "wrong_iss":
        idp.claims_override = {"iss": "https://evil.example"}
    elif case == "hs256":
        idp.sign_with = "hs256"
    elif case == "no_nonce":
        idp.claims_override = {"nonce": None}
    app = _oidc_app(db_url, idp)
    with TestClient(app) as c:
        r = _login(c, idp)
        assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_SSO_FAILED", (case, r.text)
        assert not c.get(f"{V1}/auth/session").json()["authenticated"]


def test_t_a2_oidc_es256_state_single_use_and_pkce(db_url):
    idp = FakeIdp()
    idp.sign_with = "ec"
    app = _oidc_app(db_url, idp)
    with TestClient(app) as c:
        r = c.get(f"{V1}/auth/oidc/login", params={"next": "https://evil.example/x"}, follow_redirects=False)
        code, state = idp.authorize(r.headers["location"])
        ok = c.get(f"{V1}/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
        assert ok.status_code == 302 and ok.headers["location"] == "/"          # open redirect refused
        replay = c.get(f"{V1}/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
        assert replay.status_code == 400 and replay.json()["error"]["code"] == "AUTH_SSO_STATE"
        forged = c.get(f"{V1}/auth/oidc/callback", params={"code": "x", "state": "forged"}, follow_redirects=False)
        assert forged.status_code == 400
    eng = sa.create_engine(db_url)
    with eng.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM oidc_states")).scalar() == 0
    eng.dispose()


# ---------------------------------------------------------------- T-A3 API tokens

def test_t_a3_tokens_scopes_revocation_expiry_and_hashing(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        c = sign_up(app, "tok@example.com")
        api = Api(c)
        r = c.post(f"{V1}/tokens", json={"name": "erp", "scopes": ["view"]})
        assert r.status_code == 201, r.text
        t = r.json()
        raw = t["token"]
        assert tok.looks_like(raw) and t["prefix"] == raw[:12] and "token" not in c.get(f"{V1}/tokens").json()[
            "items"][0]
        eng = sa.create_engine(db_url)
        with eng.connect() as conn:
            stored = conn.execute(sa.text("SELECT token_hash FROM api_tokens")).scalar()
        assert stored == tok.token_hash(raw) and raw not in stored
        b = TestClient(app)
        b.headers["Authorization"] = f"Bearer {raw}"
        assert b.get(f"{V1}/mfg/items").status_code == 200                       # no cookie, no CSRF
        e = b.post(f"{V1}/mfg/items", json={"part_number": "X1", "make_buy": "buy"})
        assert e.status_code == 403 and e.json()["error"]["code"] == "TOKEN_SCOPE"
        assert b.get(f"{V1}/tokens").status_code == 403                          # tokens cannot mint tokens
        for path in ("/problems", "/templates", "/finance/plans"):         # outside the token surface (15.WP-S M1)
            x = b.get(f"{V1}{path}")
            assert x.status_code == 403 and x.json()["error"]["code"] == "TOKEN_SCOPE", path
        w = b.get(f"{V1}/mfg/items", headers={"X-SP-Workspace": "usr_other"})
        assert w.status_code == 404
        bad = TestClient(app)
        bad.headers["Authorization"] = "Bearer spt_" + "A" * 43
        assert bad.get(f"{V1}/mfg/items").json()["error"]["code"] == "AUTH_TOKEN_INVALID"
        r2 = c.post(f"{V1}/tokens", json={"name": "w", "scopes": ["view", "master_edit"]}).json()
        b2 = TestClient(app)
        b2.headers["Authorization"] = f"Bearer {r2['token']}"
        assert b2.post(f"{V1}/mfg/items", json={"part_number": "X1", "make_buy": "buy", "lead_time_days": 3}) \
            .status_code == 201
        assert c.delete(f"{V1}/tokens/{t['id']}").status_code == 204
        assert b.get(f"{V1}/mfg/items").json()["error"]["code"] == "AUTH_TOKEN_INVALID"
        with eng.begin() as conn:
            conn.execute(sa.text("UPDATE api_tokens SET expires_at = now() - interval '1 minute' WHERE id = :i"),
                         {"i": r2["id"]})
        eng.dispose()
        x = b2.get(f"{V1}/mfg/items")
        assert x.status_code == 401 and x.json()["error"]["code"] == "AUTH_TOKEN_EXPIRED"
        assert c.post(f"{V1}/tokens", json={"name": "z", "scopes": ["root"]}).status_code == 422
        assert api.get("/items")["total"] == 1


def test_secrets_key_rotation_and_config_checks():
    from superplanner.api.config import ConfigError, Settings

    k1, k2 = crypto.new_key(), crypto.new_key()
    enc = crypto.encrypt([k1], "s3cret")
    assert crypto.decrypt([k2, k1], enc) == "s3cret"                            # old key still decrypts
    with pytest.raises(Exception):
        crypto.decrypt([k2], enc)
    with pytest.raises(ConfigError):
        Settings(database_url="postgresql://x/y", secrets_keys=["not-a-key"])
    with pytest.raises(ConfigError):
        Settings(database_url="postgresql://x/y", oidc_issuer="https://i", oidc_client_id="c")
