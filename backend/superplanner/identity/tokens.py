"""API tokens (M5-DESIGN 3.3, I4): `spt_<43 url-safe chars>`, stored as sha256, shown once. Pure helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "spt_"
MAX_DAYS = 366


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)          # 43 chars


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like(token: str) -> bool:
    return token.startswith(PREFIX) and 40 <= len(token) <= 60 and all(
        c.isalnum() or c in "-_" for c in token[len(PREFIX):])


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def display_prefix(token: str) -> str:
    return token[:len(PREFIX) + 8]
