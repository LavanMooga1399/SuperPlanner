"""VAPID (RFC 8292): ES256 JWT signed with `WEBPUSH_VAPID_PRIVATE_KEY` (PEM, P-256), public key for the browser."""

from __future__ import annotations

import base64
import time
from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

JWT_TTL_SECONDS = 12 * 3600


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _normalise(pem: str) -> str:
    return pem.replace("\\n", "\n").strip() + "\n"


def check_private_key(pem: str) -> str:
    """The normalised PEM, or ConfigError (P-256 private key required)."""
    from ..api.config import ConfigError

    norm = _normalise(pem)
    try:
        key = serialization.load_pem_private_key(norm.encode("ascii"), password=None)
    except Exception:
        raise ConfigError("WEBPUSH_VAPID_PRIVATE_KEY must be a PEM EC private key (P-256).") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise ConfigError("WEBPUSH_VAPID_PRIVATE_KEY must be a P-256 (prime256v1) EC private key.")
    return norm


@lru_cache(maxsize=4)
def _key(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    return key


def public_key(pem: str) -> str:
    """Application server key for `PushManager.subscribe` (base64url, uncompressed point)."""
    pub = _key(pem).public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint)
    return b64u(pub)


def audience(endpoint: str) -> str:
    u = urlsplit(endpoint)
    return f"{u.scheme}://{u.netloc}"


def authorization(pem: str, subject: str, endpoint: str, now: float | None = None) -> str:
    import jwt

    claims = {"aud": audience(endpoint), "exp": int((now or time.time()) + JWT_TTL_SECONDS), "sub": subject}
    token = jwt.encode(claims, _key(pem), algorithm="ES256", headers={"typ": "JWT"})
    return f"vapid t={token}, k={public_key(pem)}"


def generate_private_key_pem() -> str:
    """For `manage.py`/operators: a new VAPID key (PEM)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode("ascii")
