"""Tables `users`, `user_sessions`, `auth_rate_limits` on the shared `Base` (PHASE2B 4.2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, utcnow


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email", "email", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)          # usr_<hex>; usr_local fixed
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)   # trimmed + lower-cased
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSessionRow(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (Index("uq_user_sessions_token", "token_hash", unique=True),
                      Index("ix_user_sessions_user", "user_id"),
                      Index("ix_user_sessions_expires", "expires_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)          # ses_<hex>
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64))                     # sha256 hex of the cookie token
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))   # absolute expiry
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)


class AuthRateLimitRow(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (Index("ix_auth_rate_limits_window", "window_start"),)

    bucket: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer)
