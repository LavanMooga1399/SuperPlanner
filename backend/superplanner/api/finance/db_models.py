"""Finance tables on the shared `Base` (FINANCE.md 17, PHASE2B 3.3). Same column conventions as A.13; FKs cascade.

Owned roots: finance_plans, finance_runs, finance_results (`OwnedMixin`). No one-active-run index (review R5): the
plan row lock taken by every run-creating path enforces the rule."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, BigIntId, JsonType, utcnow
from ..db.ownership import OwnedMixin


class FinancePlanRow(OwnedMixin, Base):
    __tablename__ = "finance_plans"
    __table_args__ = (Index("ix_finance_plans_owner_updated", "owner_id", "updated_at", "id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    document: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinancePlanVersionRow(Base):
    __tablename__ = "finance_plan_versions"
    __table_args__ = (Index("ix_finance_plan_versions_hash", "plan_id", "content_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("finance_plans.id", ondelete="CASCADE"))
    base_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))          # snapshot | what_if
    content_hash: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinanceRunRow(OwnedMixin, Base):
    __tablename__ = "finance_runs"
    __table_args__ = (Index("ix_finance_runs_plan_created", "plan_id", "created_at"),
                      Index("ix_finance_runs_status", "status"),
                      Index("ix_finance_runs_plan_version", "plan_version_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("finance_plans.id", ondelete="CASCADE"))
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("finance_plan_versions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))          # baseline | what_if
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    request: Mapped[dict[str, Any]] = mapped_column(JsonType)
    what_if: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    engine_version: Mapped[str] = mapped_column(String(32))
    feasibility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinanceRunEventRow(Base):
    __tablename__ = "finance_run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_finance_run_event_seq"),)

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("finance_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinanceResultRow(OwnedMixin, Base):
    __tablename__ = "finance_results"
    __table_args__ = (Index("ix_finance_results_plan_created", "plan_id", "created_at"),
                      Index("ix_finance_results_plan_version", "plan_version_id"),
                      Index("uq_finance_results_run", "run_id", unique=True))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("finance_plans.id", ondelete="CASCADE"))
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("finance_plan_versions.id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("finance_runs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feasibility: Mapped[str] = mapped_column(String(16))
    summary: Mapped[dict[str, Any]] = mapped_column(JsonType)
    result: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
