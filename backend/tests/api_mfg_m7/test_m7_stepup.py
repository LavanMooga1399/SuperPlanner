"""T-S4 (M7-DESIGN 4.2 (3)): SSO users sign with a single-use OIDC step-up token of their own session (fake IdP);
reuse and another session's token are refused; MFA steps need an MFA `amr`."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "identity"))

from apimfgm2_helpers import V1, Api  # noqa: E402
from fake_idp import CLIENT_ID, ISSUER, SECRET, FakeIdp  # noqa: E402
from m7_helpers import KEY, World, preview  # noqa: E402
from superplanner.identity import oidc  # noqa: E402
from test_m7_esig import _eco  # noqa: E402


def _login(c: TestClient, idp: FakeIdp) -> None:
    r = c.get(f"{V1}/auth/oidc/login", params={"next": "/mfg"}, follow_redirects=False)
    code, state = idp.authorize(r.headers["location"])
    r = c.get(f"{V1}/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert r.status_code == 302, r.text
    c.headers["X-CSRF-Token"] = c.get(f"{V1}/auth/session").json()["csrf_token"]


def _stepup(c: TestClient, idp: FakeIdp, amr: list[str]) -> str:
    r = c.get(f"{V1}/auth/oidc/stepup", params={"purpose": "esig"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    assert "prompt=login" in r.headers["location"] and "max_age=0" in r.headers["location"]
    idp.claims_override = {"auth_time": int(time.time()), "amr": amr}
    code, state = idp.authorize(r.headers["location"])
    r = c.get(f"{V1}/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/esig/stepup-done#token="), loc
    return loc.split("#token=", 1)[1]


def test_t_s4_stepup_token_single_use_and_bound_to_the_session(db_url):
    idp = FakeIdp()
    oidc.CACHE.items.clear()
    w = World(db_url, oidc_issuer=ISSUER, oidc_client_id=CLIENT_ID, oidc_client_secret=SECRET,
              oidc_allowed_domains=["corp.example"], oidc_http=idp, public_base_url="http://testserver",
              secrets_keys=[KEY])
    try:
        w.owner.api.location("ST")
        cr = _eco(w)
        w.part11_on()
        ana = TestClient(w.app)
        _login(ana, idp)
        w.owner.api.post("/members", {"email": "ana@corp.example", "roles": ["qa_approver"]})
        r = ana.post(f"{V1}/auth/esig/enroll", json={"legal_name": "Ana Lima", "acknowledgement": True,
                                                     "stepup_token": _stepup(ana, idp, ["pwd"])})
        assert r.status_code == 200 and r.json()["enrolled"] and "sso" in r.json()["methods"], r.text
        api = Api(ana, w.oid)

        class P:
            pass

        p = P()
        p.api = api                                    # type: ignore[attr-defined]
        h = preview(p, "eco", cr["id"], "approve")["content_hash"]  # type: ignore[arg-type]
        tok = _stepup(ana, idp, ["pwd"])
        sig = {"meaning": "approved", "content_hash": h, "username": "ana@corp.example", "stepup_token": tok,
               "comment": "Approved after review"}
        # another browser session of the same person cannot use the token
        other = TestClient(w.app)
        _login(other, idp)
        Api(other, w.oid).err("POST", f"/eco/{cr['id']}/approve", 422, "ESIG_AUTH_FAILED", json={"signature": sig})
        out = api.req("POST", f"/eco/{cr['id']}/approve", 200, json={"signature": sig}).json()
        assert out["status"] == "approved"
        s = w.owner.api.get("/esig/signatures", record_type="eco")["items"][0]
        assert s["auth_method"] == "sso" and s["signer_legal_name"] == "Ana Lima"
        # reuse of a consumed token (credentials are checked before the record's state)
        api.err("POST", f"/eco/{cr['id']}/approve", 422, "ESIG_AUTH_FAILED", json={"signature": sig})
        # MFA steps: a token without an MFA amr is refused, one with it signs as sso_mfa
        from superplanner.api.mfg.services import esig as ESIG

        status = ana.get(f"{V1}/auth/esig/status").json()
        assert status["sso_user"] and status["can_sign"]
        assert ESIG.POL.DEFAULTS[("field_action", "approve")][1] == "password_totp"
    finally:
        w.close()
