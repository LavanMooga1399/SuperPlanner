"""OIDC authorization code + PKCE (M5-DESIGN 3.1). Protocol pieces only (no DB): discovery and JWKS (cached 1 h),
PKCE S256, state / nonce generation, code exchange, id_token validation with PyJWT (RS256 / ES256 only; `iss`,
`aud`, `exp`, `iat`, `nonce` required and checked; unknown `kid` -> one JWKS refresh, then refused).

HTTP goes through `fetch` (stdlib urllib, TLS verified with the default context, 10 s timeout); tests pass a fake
IdP as `Settings.oidc_http`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

import jwt
from jwt import PyJWK

ALGORITHMS = ("RS256", "ES256")
CACHE_SECONDS = 3600
TIMEOUT = 10.0
LEEWAY = 60

Fetch = Callable[[str, str, dict[str, str] | None], tuple[int, Any]]


class OidcError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def http_fetch(method: str, url: str, form: dict[str, str] | None) -> tuple[int, Any]:
    if not url.startswith("https://"):
        raise OidcError("AUTH_SSO_CONFIG", "OIDC endpoints must be https.")
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json",
                                          **({"Content-Type": "application/x-www-form-urlencoded"} if data else {})})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:   # noqa: S310 (https only)
            return r.status, json.loads(r.read(1_000_000) or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read(100_000) or b"null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise OidcError("AUTH_SSO_UNAVAILABLE", f"The sign-in provider cannot be reached ({e.__class__.__name__}).") \
            from None


class _Cache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        with self.lock:
            hit = self.items.get(key)
            return hit[1] if hit and time.monotonic() - hit[0] < CACHE_SECONDS else None

    def put(self, key: str, value: Any) -> None:
        with self.lock:
            self.items[key] = (time.monotonic(), value)

    def drop(self, key: str) -> None:
        with self.lock:
            self.items.pop(key, None)


CACHE = _Cache()


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(48))
    return verifier, b64url(hashlib.sha256(verifier.encode()).digest())


def new_state() -> str:
    return b64url(secrets.token_bytes(32))


def discovery(issuer: str, fetch: Fetch) -> dict[str, Any]:
    key = f"disc:{issuer}"
    hit = CACHE.get(key)
    if hit is not None:
        return hit
    st, doc = fetch("GET", issuer.rstrip("/") + "/.well-known/openid-configuration", None)
    if st != 200 or not isinstance(doc, dict) or doc.get("issuer", "").rstrip("/") != issuer.rstrip("/"):
        raise OidcError("AUTH_SSO_CONFIG", "The provider's discovery document is invalid.")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not str(doc.get(k, "")).startswith("https://"):
            raise OidcError("AUTH_SSO_CONFIG", f"The provider's {k} must be https.")
    CACHE.put(key, doc)
    return doc


def _jwks(uri: str, fetch: Fetch, refresh: bool = False) -> dict[str, Any]:
    key = f"jwks:{uri}"
    if refresh:
        CACHE.drop(key)
    hit = CACHE.get(key)
    if hit is not None:
        return hit
    st, doc = fetch("GET", uri, None)
    if st != 200 or not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        raise OidcError("AUTH_SSO_CONFIG", "The provider's key set is invalid.")
    CACHE.put(key, doc)
    return doc


def authorize_url(doc: dict[str, Any], client_id: str, redirect_uri: str, scopes: str, state: str, nonce: str,
                  challenge: str) -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": scopes,
         "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    return doc["authorization_endpoint"] + ("&" if "?" in doc["authorization_endpoint"] else "?") + \
        urllib.parse.urlencode(q)


def exchange(doc: dict[str, Any], fetch: Fetch, *, code: str, verifier: str, redirect_uri: str, client_id: str,
             client_secret: str) -> dict[str, Any]:
    st, body = fetch("POST", doc["token_endpoint"], {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id,
        "client_secret": client_secret, "code_verifier": verifier})
    if st != 200 or not isinstance(body, dict) or not isinstance(body.get("id_token"), str):
        raise OidcError("AUTH_SSO_FAILED", "The provider refused the sign-in code.")
    return body


def validate_id_token(token: str, doc: dict[str, Any], fetch: Fetch, *, issuer: str, client_id: str, nonce: str
                      ) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise OidcError("AUTH_SSO_FAILED", "The identity token is malformed.") from None
    alg, kid = header.get("alg"), header.get("kid")
    if alg not in ALGORITHMS:
        raise OidcError("AUTH_SSO_FAILED", "The identity token uses an algorithm that is not accepted.")
    jwk = None
    for refresh in (False, True):
        keys = _jwks(doc["jwks_uri"], fetch, refresh=refresh)["keys"]
        jwk = next((k for k in keys if k.get("kid") == kid), None)
        if jwk is not None:
            break
    if jwk is None:
        raise OidcError("AUTH_SSO_FAILED", "The identity token is signed with an unknown key.")
    try:
        key = PyJWK(jwk, algorithm=alg).key
        claims = jwt.decode(token, key=key, algorithms=[alg], audience=client_id, issuer=issuer, leeway=LEEWAY,
                            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]})
    except jwt.ExpiredSignatureError:
        raise OidcError("AUTH_SSO_FAILED", "The identity token has expired.") from None
    except jwt.PyJWTError as e:
        raise OidcError("AUTH_SSO_FAILED", f"The identity token is not valid ({e.__class__.__name__}).") from None
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("AUTH_SSO_FAILED", "The identity token does not belong to this sign-in (nonce).")
    azp = claims.get("azp")
    if isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1 and azp != client_id:
        raise OidcError("AUTH_SSO_FAILED", "The identity token was issued to another client.")
    return claims


__all__ = ["ALGORITHMS", "CACHE", "OidcError", "authorize_url", "discovery", "exchange", "http_fetch", "new_state",
           "pkce_pair", "validate_id_token"]
