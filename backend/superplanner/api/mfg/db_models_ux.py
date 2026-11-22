"""UX upgrade tables (docs/UX-STANDARD.md "Backend support"); migration `0009_ux` (expand).

- `user_preferences` (platform, per person like `push_subscriptions`): one small JSON document per (user, key) -
  table column layouts, saved filter views, theme / density. Not plant data: not owner-scoped, not reset.
- `mfg_bulk_requests` (owned by the plant): the stored response of a bulk action sent with an `Idempotency-Key`
  (replayed for 24 h; plant data, so the data reset deletes it).
Registries: `UX_PLATFORM_MODELS`, `UX_OWNED_MODELS`, `UX_TABLES`, `UX_RESET_MODELS`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin


class UserPreferenceRow(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonType)
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MfgBulkRequestRow(OwnedMixin, Base):
    __tablename__ = "mfg_bulk_requests"
    __table_args__ = (UniqueConstraint("owner_id", "actor_id", "idempotency_key", name="uq_mfg_bulk_requests_key"),
                      Index("ix_mfg_bulk_requests_created", "created_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))           # e.g. "work-orders/release"
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8))            # running | done
    response: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


UX_PLATFORM_MODELS: tuple[type[Base], ...] = (UserPreferenceRow,)
UX_OWNED_MODELS: tuple[type[Base], ...] = (MfgBulkRequestRow,)
UX_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in UX_OWNED_MODELS + UX_PLATFORM_MODELS)
#: the mfg data reset deletes the plant's bulk replay records; personal preferences survive (like push/digests)
UX_RESET_MODELS: tuple[type[Base], ...] = UX_OWNED_MODELS
