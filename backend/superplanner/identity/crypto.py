"""Secret encryption (M5-DESIGN 3.2, I4): Fernet with `SECRETS_KEYS` (first key encrypts, all decrypt - rotation)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..api.errors import ApiError


class SecretsUnavailable(ApiError):
    def __init__(self) -> None:
        super().__init__(503, "SECRETS_KEY_MISSING", "This feature needs SECRETS_KEY to be configured.", {})


def check_keys(keys: list[str]) -> None:
    from ..api.config import ConfigError

    for k in keys:
        try:
            Fernet(k.encode())
        except Exception:
            raise ConfigError("SECRETS_KEYS entries must be Fernet keys (url-safe base64 of 32 bytes).") from None


def _fernet(keys: list[str]) -> MultiFernet:
    if not keys:
        raise SecretsUnavailable()
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(keys: list[str], value: str) -> str:
    return _fernet(keys).encrypt(value.encode()).decode()


def decrypt(keys: list[str], token: str) -> str:
    try:
        return _fernet(keys).decrypt(token.encode()).decode()
    except InvalidToken:
        raise ApiError(500, "SECRETS_KEY_MISMATCH", "A stored secret cannot be decrypted with the configured "
                       "SECRETS_KEYS.", {}) from None


def new_key() -> str:
    return Fernet.generate_key().decode()
