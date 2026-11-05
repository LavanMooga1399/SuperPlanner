"""An in-process OIDC provider with real RS256 / ES256 JWKS signing (M5-DESIGN 12 S1)."""

from __future__ import annotations

import base64
import hashlib
import time
import urllib.parse
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

ISSUER = "https://idp.example.test"
CLIENT_ID = "sp-client"
SECRET = "sp-secret"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


class FakeIdp:
    def __init__(self) -> None:
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.codes: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.claims_override: dict[str, Any] = {}
        self.header_override: dict[str, Any] = {}
        self.sign_with: str = "rsa"

    def jwks(self) -> dict[str, Any]:
        pub = self.rsa.public_key().public_numbers()
        n = pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")
        e = pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")
        ecn = self.ec.public_key().public_numbers()
        return {"keys": [{"kty": "RSA", "kid": "k-rsa", "alg": "RS256", "use": "sig", "n": _b64(n), "e": _b64(e)},
                         {"kty": "EC", "kid": "k-ec", "alg": "ES256", "use": "sig", "crv": "P-256",
                          "x": _b64(ecn.x.to_bytes(32, "big")), "y": _b64(ecn.y.to_bytes(32, "big"))}]}

    def discovery(self) -> dict[str, Any]:
        return {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/jwks"}

    def authorize(self, url: str, *, email: str = "ana@corp.example", sub: str = "sub-1",
                  verified: bool = True) -> tuple[str, str]:
        """What the browser does at the IdP: returns (code, state) for the callback."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        assert q["code_challenge_method"] == "S256" and q["client_id"] == CLIENT_ID and q["response_type"] == "code"
        code = f"code-{len(self.codes) + 1}"
        self.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"], "email": email, "sub": sub,
                            "verified": verified, "redirect_uri": q["redirect_uri"]}
        return code, q["state"]

    def id_token(self, c: dict[str, Any]) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": c["sub"], "email": c["email"],
                  "email_verified": c["verified"], "nonce": c["nonce"], "iat": now, "exp": now + 300, "name": "Ana"}
        claims.update(self.claims_override)
        if self.sign_with == "ec":
            return jwt.encode(claims, self.ec, algorithm="ES256", headers={"kid": "k-ec", **self.header_override})
        if self.sign_with == "hs256":
            return jwt.encode(claims, SECRET, algorithm="HS256", headers={"kid": "k-rsa"})
        return jwt.encode(claims, self.rsa, algorithm="RS256", headers={"kid": "k-rsa", **self.header_override})

    def __call__(self, method: str, url: str, form: dict[str, str] | None) -> tuple[int, Any]:
        self.calls.append((method, url))
        if url == ISSUER + "/.well-known/openid-configuration":
            return 200, self.discovery()
        if url == ISSUER + "/jwks":
            return 200, self.jwks()
        if url == ISSUER + "/token" and method == "POST" and form:
            c = self.codes.pop(form.get("code", ""), None)
            if c is None or form.get("client_secret") != SECRET or form.get("redirect_uri") != c["redirect_uri"]:
                return 400, {"error": "invalid_grant"}
            if _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != c["challenge"]:
                return 400, {"error": "invalid_grant", "error_description": "PKCE"}
            return 200, {"id_token": self.id_token(c), "access_token": "at", "token_type": "Bearer"}
        return 404, None
