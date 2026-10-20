"""Request/response bodies of the auth endpoints (PHASE2B 4.5). All request bodies are `extra="forbid"`."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL = 254
MAX_PASSWORD_INPUT = 4096   # longer bodies are a validation error; 257..4096 -> WEAK_PASSWORD too_long


def normalize_email(value: str) -> str:
    return value.strip().lower()


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EmailIn(_In):
    email: str = Field(max_length=1000)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = normalize_email(v)
        if len(v) > MAX_EMAIL or not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v


class SignUpIn(_EmailIn):
    password: str = Field(max_length=MAX_PASSWORD_INPUT)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("The name must not be empty.")
        return v


class SignInIn(_EmailIn):
    password: str = Field(max_length=MAX_PASSWORD_INPUT)


class ChangePasswordIn(_In):
    current_password: str = Field(max_length=MAX_PASSWORD_INPUT)
    new_password: str = Field(max_length=MAX_PASSWORD_INPUT)


class UserOut(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    is_local: bool
    created_at: datetime | None


class SessionInfo(BaseModel):
    auth_mode: str
    authenticated: bool
    user: UserOut | None
    csrf_token: str | None
    expires_at: datetime | None
    signup_enabled: bool
