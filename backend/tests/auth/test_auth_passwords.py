"""Q3-3 password storage and policy, Q3-9 timing equalisation (PHASE2B 4.3)."""

from __future__ import annotations

import pytest
from argon2 import extract_parameters
from fastapi.testclient import TestClient
from sqlalchemy import select

from auth_helpers import AUTH, PASSWORD, acc_app, error, sign_up

from superplanner.api.auth import passwords
from superplanner.api.auth.models import UserRow
from superplanner.api.config import ConfigError, Settings


def _hash_of(app, email: str) -> str:
    with app.state.ctx.db.read() as s:
        return s.scalar(select(UserRow.password_hash).where(UserRow.email == email))


def test_profiles_parameters():
    d = extract_parameters(passwords.hash_password("some long password", "default"))
    assert (d.time_cost, d.memory_cost, d.parallelism) == (3, 65536, 4)
    f = extract_parameters(passwords.hash_password("some long password", "fast"))
    assert (f.time_cost, f.memory_cost, f.parallelism) == (1, 8192, 1)


def test_fast_profile_refused_in_production():
    with pytest.raises(ConfigError, match="PASSWORD_HASH_PROFILE=fast"):
        Settings(sp_env="production", database_url="postgresql://u@h/db", public_base_url="https://x.example",
                 password_hash_profile="fast", auth_mode="accounts")


def test_stored_hash_is_argon2id_and_never_plain(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
    h = _hash_of(app, "ana@example.com")
    assert h.startswith("$argon2id$") and PASSWORD not in h
    assert passwords.verify_password(h, PASSWORD) and not passwords.verify_password(h, PASSWORD + "x")


def test_rehash_on_sign_in_when_profile_changes(db_url):
    app = acc_app(db_url, password_hash_profile="fast")
    with TestClient(app) as c:
        sign_up(c, "ana@example.com")
    fast_hash = _hash_of(app, "ana@example.com")
    assert extract_parameters(fast_hash).time_cost == 1
    app2 = acc_app(db_url, password_hash_profile="default")
    with TestClient(app2) as c:
        assert c.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": PASSWORD}).status_code == 200
    new_hash = _hash_of(app2, "ana@example.com")
    assert new_hash != fast_hash and extract_parameters(new_hash).time_cost == 3


def test_policy_reasons():
    assert passwords.policy_reasons("correct horse battery", "a@b.co") == []
    assert passwords.policy_reasons("x" * 9, None) == ["too_short"]
    assert passwords.policy_reasons("xq" * 5, None) == []
    assert passwords.policy_reasons("xq" * 128, None) == []
    assert passwords.policy_reasons("x" * 257, None) == ["too_long"]
    assert passwords.policy_reasons("QWERTYUIOP", None) == ["common"]
    assert passwords.policy_reasons("1234567890", None) == ["common"]
    assert passwords.policy_reasons("A@B.CO.example", "a@b.co.example") == ["same_as_email"]
    # NFKC: full-width digits normalise to the common "1234567890"
    assert passwords.policy_reasons("１２３４５６７８９０", None) == ["common"]
    assert len(passwords.common_passwords()) == 1000


def test_nfkc_normalised_before_hashing():
    h = passwords.hash_password("ｃｏｒｒｅｃｔ horse battery")
    assert passwords.verify_password(h, "correct horse battery")


def test_unknown_email_verifies_the_dummy_hash(db_url, monkeypatch):
    """Q3-9: both failure paths do one argon2 verification (compared by calls, not wall time)."""
    calls: list[str] = []
    real = passwords.verify_password

    def spy(h, pw, profile="default"):
        calls.append("dummy" if h == passwords.dummy_hash(profile) else "user")
        return real(h, pw, profile)

    monkeypatch.setattr(passwords, "verify_password", spy)
    with TestClient(acc_app(db_url)) as c:
        sign_up(c, "ana@example.com")
        c.post(f"{AUTH}/sign-out")
        calls.clear()
        error(c.post(f"{AUTH}/sign-in", json={"email": "ghost@example.com", "password": PASSWORD}), 401,
              "INVALID_CREDENTIALS")
        assert calls == ["dummy"]
        calls.clear()
        error(c.post(f"{AUTH}/sign-in", json={"email": "ana@example.com", "password": "not the password"}), 401,
              "INVALID_CREDENTIALS")
        assert calls == ["user"]
    # the dummy hash uses the configured profile, so the work matches a real hash of that profile
    assert extract_parameters(passwords.dummy_hash("fast")).time_cost == 1
    assert extract_parameters(passwords.dummy_hash("default")).time_cost == 3
