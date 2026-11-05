"""RFC 6238 TOTP (SHA-1, 30 s, 6 digits, +-1 step), stdlib HMAC (M5-DESIGN 3.2). Pure."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    pad = "=" * (-len(secret_b32) % 8)
    return base64.b32decode(secret_b32.upper() + pad)


def hotp(key: bytes, counter: int, digits: int = DIGITS, digest: str = "sha1") -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, digest)).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def code_at(secret_b32: str, unix: float, digits: int = DIGITS) -> str:
    return hotp(_key(secret_b32), int(unix // STEP), digits)


def verify(secret_b32: str, code: str, unix: float, last_step: int | None) -> int | None:
    """The matching time step (to store as `last_step`), or None. Steps <= `last_step` are refused (replay)."""
    if not code.isdigit() or len(code) != DIGITS:
        return None
    key = _key(secret_b32)
    now = int(unix // STEP)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(hotp(key, step), code):
            return step
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str = "SuperPlanner") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def recovery_codes(n: int = 10) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(2)) for _ in range(n)]
