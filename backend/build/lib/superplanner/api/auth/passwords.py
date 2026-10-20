"""Password hashing and policy (PHASE2B 4.3).

argon2id via `argon2-cffi`. Profile `default` = library defaults (t=3, m=64 MiB, p=4); profile `fast`
(t=1, m=8 MiB, p=1) is for tests only and refused with `SP_ENV=production` (config validation). Hashes made with
another profile are upgraded on the next successful sign-in (`needs_rehash`).

Policy (NIST style, no composition rules): 10..256 characters after NFKC normalisation, not equal to the email,
not in the bundled list of common passwords. Passwords are NFKC-normalised before hashing and verifying, so the
same password typed with a different Unicode composition still matches.
"""

from __future__ import annotations

import functools
import unicodedata
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
MAX_LENGTH = 256
_COMMON_FILE = Path(__file__).with_name("common_passwords.txt")

PROFILES: dict[str, dict[str, int]] = {
    "default": {"time_cost": 3, "memory_cost": 65536, "parallelism": 4},
    "fast": {"time_cost": 1, "memory_cost": 8192, "parallelism": 1},
}


@functools.cache
def hasher(profile: str = "default") -> PasswordHasher:
    return PasswordHasher(**PROFILES[profile])


@functools.cache
def common_passwords() -> frozenset[str]:
    lines = _COMMON_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#"))


def normalize(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def policy_reasons(password: str, email: str | None) -> list[str]:
    """Empty list = acceptable. Reasons: too_short, too_long, common, same_as_email."""
    pw = normalize(password)
    reasons: list[str] = []
    if len(pw) < MIN_LENGTH:
        reasons.append("too_short")
    if len(pw) > MAX_LENGTH:
        reasons.append("too_long")
    if pw.lower() in common_passwords():
        reasons.append("common")
    if email and pw.strip().lower() == email.strip().lower():
        reasons.append("same_as_email")
    return reasons


def hash_password(password: str, profile: str = "default") -> str:
    return hasher(profile).hash(normalize(password))


def verify_password(password_hash: str, password: str, profile: str = "default") -> bool:
    """Constant-work verification; any malformed hash counts as a mismatch."""
    try:
        return hasher(profile).verify(password_hash, normalize(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str, profile: str = "default") -> bool:
    try:
        return hasher(profile).check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@functools.cache
def dummy_hash(profile: str = "default") -> str:
    """A constant hash of a random-looking secret, verified for unknown emails so timing matches (B 4.3)."""
    return hasher(profile).hash("sp-dummy-password-never-valid-7f3c")


def verify_dummy(password: str, profile: str = "default") -> bool:
    """Burn the same work as a real verification. Always returns False."""
    verify_password(dummy_hash(profile), password, profile)
    return False
