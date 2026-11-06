"""M6 tables (M6-DESIGN 6) on the shared `Base`; migration `0008_m6` (expand).

Owned by the plant (`owner_id`): assistant conversations, turns and references (a conversation lives in the plant
it was asked in), daily inventory value snapshots. Platform tables (per person, like `users`): assistant token
usage (budgets span plants), push subscriptions, digest subscriptions.
Registries: `M6_OWNED_MODELS` (FK order), `M6_PLATFORM_MODELS`, `M6_TABLES`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, Double, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


def _s(n: int, nullable: bool = False) -> Any:
    return mapped_column(String(n), nullable=nullable)


# ---------------------------------------------------------------- assistant (1), owned by the plant

class AssistantConversationRow(OwnedMixin, Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (Index("ix_assistant_conversations_user", "owner_id", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = _s(200)
    allow_whatif: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _dt(False)
    updated_at: Mapped[datetime] = _dt(False)


class AssistantTurnRow(OwnedMixin, Base):
    __tablename__ = "assistant_turns"
    __table_args__ = (Index("ix_assistant_turns_conversation", "conversation_id", "created_at"),
                      # 1.2: one running turn per user (any plant)
                      Index("uq_assistant_turns_running", "user_id", unique=True,
                            postgresql_where=text("status IN ('queued', 'running')")),
                      Index("ix_assistant_turns_created", "created_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"))
    user_id: Mapped[str] = _s(64)
    user_text: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    allow_whatif: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = _s(16)                      # queued | running | completed | failed | cancelled
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JsonType)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JsonType)
    drafts: Mapped[list[dict[str, Any]]] = mapped_column(JsonType)
    #: tool results of this turn (trimmed JSON) for the history of the next model rounds; replaced by the reference
    #: list once the turn is older than the current one (1.2)
    tool_log: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonType, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    model: Mapped[str | None] = _s(64, True)
    fallback_code: Mapped[str | None] = _s(64, True)
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    tokens_cache_read: Mapped[int] = mapped_column(Integer)
    rounds: Mapped[int] = mapped_column(Integer)
    cancel_requested: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _dt(False)
    started_at: Mapped[datetime | None] = _dt()
    finished_at: Mapped[datetime | None] = _dt()
    heartbeat_at: Mapped[datetime | None] = _dt()


class AssistantRefRow(OwnedMixin, Base):
    """1.5: references issued by tools, numbered per conversation (R1, R2, ...)."""
    __tablename__ = "assistant_refs"
    __table_args__ = (UniqueConstraint("conversation_id", "ref_no", name="uq_assistant_refs_no"),
                      Index("ix_assistant_refs_record", "conversation_id", "ref_type", "record_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"))
    ref_no: Mapped[int] = mapped_column(Integer)
    ref_type: Mapped[str] = _s(32)
    record_id: Mapped[str] = _s(64)
    label: Mapped[str] = _s(200)
    link: Mapped[str] = _s(300)
    created_at: Mapped[datetime] = _dt(False)


class MfgInventorySnapshotRow(OwnedMixin, Base):
    """3.2: daily inventory value per item family and location kind (turns use month-end rows)."""
    __tablename__ = "mfg_inventory_snapshots"
    __table_args__ = (UniqueConstraint("owner_id", "day", "item_family", "location_kind",
                                       name="uq_mfg_inventory_snapshots_key"),
                      Index("ix_mfg_inventory_snapshots_day", "owner_id", "day"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    item_family: Mapped[str] = _s(32)                 # '' = no family
    location_kind: Mapped[str] = _s(16)
    qty_value: Mapped[float] = mapped_column(Double)  # on hand x standard cost (plant currency)
    items: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _dt(False)


# ---------------------------------------------------------------- platform tables (per person)

class AssistantUsageRow(Base):
    """1.6: daily token usage per user and plant (budgets: per user over all plants, per plant over all users)."""
    __tablename__ = "assistant_usage"
    __table_args__ = (UniqueConstraint("day", "user_id", "owner_id", name="uq_assistant_usage_key"),
                      Index("ix_assistant_usage_owner_day", "owner_id", "day"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tokens: Mapped[int] = mapped_column(BigInteger)
    calls: Mapped[int] = mapped_column(Integer)


class PushSubscriptionRow(Base):
    """2: Web Push subscriptions (keys encrypted with SECRETS_KEYS when configured)."""
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "endpoint_hash", name="uq_push_subscriptions_endpoint"),
                      Index("ix_push_subscriptions_user", "user_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = _s(1000)
    endpoint_hash: Mapped[str] = _s(64)
    p256dh_enc: Mapped[str] = mapped_column(Text)
    auth_enc: Mapped[str] = mapped_column(Text)
    topics: Mapped[list[str]] = mapped_column(JsonType)
    user_agent: Mapped[str] = _s(300)
    created_at: Mapped[datetime] = _dt(False)
    last_success_at: Mapped[datetime | None] = _dt()
    failures: Mapped[int] = mapped_column(Integer)


class DigestSubscriptionRow(Base):
    """3.3: e-mail digests of a plant or organisation dashboard."""
    __tablename__ = "digest_subscriptions"
    __table_args__ = (Index("ix_digest_subscriptions_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[str] = _s(8)                         # plant | org
    scope_id: Mapped[str] = _s(64)                     # plant owner id | org id
    frequency: Mapped[str] = _s(8)                     # daily | weekly
    local_time: Mapped[str] = _s(5)                    # HH:MM in `time_zone`
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0 = Monday (weekly)
    time_zone: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    last_sent_at: Mapped[datetime | None] = _dt()


M6_OWNED_MODELS: tuple[type[Base], ...] = (AssistantConversationRow, AssistantTurnRow, AssistantRefRow,
                                           MfgInventorySnapshotRow)
M6_PLATFORM_MODELS: tuple[type[Base], ...] = (AssistantUsageRow, PushSubscriptionRow, DigestSubscriptionRow)
M6_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M6_OWNED_MODELS + M6_PLATFORM_MODELS)
#: reset (M2 9.4) also deletes these (plant data); conversations go with the plant's data
M6_RESET_MODELS: tuple[type[Base], ...] = M6_OWNED_MODELS
