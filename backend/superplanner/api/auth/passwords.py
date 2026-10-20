"""Password hashing and policy (PHASE2B 4.3).

argon2id via `argon2-cffi`. Profile `default` = library defaults (t=3, m=64 MiB, p=4); profile `fast`
(t=1, m=8 MiB, p=1) is for tests only and refused with `SP_ENV=production` (config validation). Hashes made with
another profile are upgraded on the next successful sign-in (`needs_rehash`).

Policy (NIST style, no composition rules): 10..256 characters after NFKC normalisation, not equal to the email,
not in the bundled list of common passwords. Passwords are NFKC-normalised before hashing and verifying, so the
same password typed with a different Unicode composition still matches.

Concurrency (fix round): every argon2 operation (`hash_password`, `verify_password`, `verify_dummy`) holds one of a
process-wide number of hash slots (`AUTH_HASH_CONCURRENCY`, default `max(1, cpu_count // 2)`). The `default`
profile allocates 64 MiB per operation, so unbounded parallel sign-ins could exhaust memory and every request thread.
A caller waits at most `AUTH_HASH_WAIT_SECONDS` for a slot, then `HashBusy` is raised (the router answers 429
`RATE_LIMITED` with `Retry-After`). `create_app` configures the slots from its settings (last app wins, as the
limit is per process).
"""

from __future__ import annotations

import functools
import math
import os
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
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


DEFAULT_HASH_WAIT_SECONDS = 1.0


class HashBusy(Exception):
    """No hash slot became free within the wait time."""

    def __init__(self, retry_after: int = 1):
        super().__init__("all password hash slots are busy")
        self.retry_after = retry_after


def default_hash_concurrency() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


class _HashSlots:
    def __init__(self, size: int, wait_seconds: float):
        self.size = max(1, int(size))
        self.wait_seconds = max(0.0, float(wait_seconds))
        self._sem = threading.BoundedSemaphore(self.size)

    def acquire(self) -> bool:
        return self._sem.acquire(timeout=self.wait_seconds)

    def release(self) -> None:
        self._sem.release()


_slots = _HashSlots(default_hash_concurrency(), DEFAULT_HASH_WAIT_SECONDS)
_slots_lock = threading.Lock()


def configure_hash_slots(size: int | None, wait_seconds: float | None) -> None:
    """Replace the process-wide slots (None = default). Holders of the old slots release into the old semaphore."""
    global _slots
    with _slots_lock:
        _slots = _HashSlots(size or default_hash_concurrency(),
                            DEFAULT_HASH_WAIT_SECONDS if wait_seconds is None else wait_seconds)


def hash_slots() -> tuple[int, float]:
    return _slots.size, _slots.wait_seconds


@contextmanager
def _slot() -> Iterator[None]:
    slots = _slots
    if not slots.acquire():
        raise HashBusy(max(1, math.ceil(slots.wait_seconds)))
    try:
        yield
    finally:
        slots.release()


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
    """Raises `HashBusy` when no hash slot is free in time."""
    with _slot():
        return hasher(profile).hash(normalize(password))


def verify_password(password_hash: str, password: str, profile: str = "default") -> bool:
    """Constant-work verification; any malformed hash counts as a mismatch. Raises `HashBusy` (no slot in time)."""
    with _slot():
        return _verify(password_hash, password, profile)


def _verify(password_hash: str, password: str, profile: str) -> bool:
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
    """A constant hash of a random-looking secret, verified for unknown emails so timing matches (B 4.3).
    Computed once per profile (cached), outside the slots."""
    return hasher(profile).hash("sp-dummy-password-never-valid-7f3c")


def verify_dummy(password: str, profile: str = "default") -> bool:
    """Burn the same work as a real verification (through `verify_password`, so it holds a slot). Always False."""
    verify_password(dummy_hash(profile), password, profile)
    return False
