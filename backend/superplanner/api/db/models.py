"""SQLAlchemy 2 ORM tables (ARCHITECTURE 13)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    pass


class ProblemRow(Base):
    __tablename__ = "problems"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    document: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProblemVersionRow(Base):
    __tablename__ = "problem_versions"
    __table_args__ = (Index("ix_problem_versions_hash", "problem_id", "content_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    base_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SolverRunRow(Base):
    __tablename__ = "solver_runs"
    __table_args__ = (Index("ix_solver_runs_problem_created", "problem_id", "created_at"),
                      Index("ix_solver_runs_status", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    problem_version_id: Mapped[str] = mapped_column(ForeignKey("problem_versions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    request: Mapped[dict[str, Any]] = mapped_column(JsonType)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    engine_version: Mapped[str] = mapped_column(String(32))
    selection: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    phases: Mapped[list[Any] | None] = mapped_column(JsonType, nullable=True)
    feasibility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    optimality_proven: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    objectives: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    diagnostics: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    source_schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SolverRunEventRow(Base):
    __tablename__ = "solver_run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("solver_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduleRow(Base):
    __tablename__ = "schedules"
    __table_args__ = (Index("ix_schedules_problem_status", "problem_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    problem_version_id: Mapped[str] = mapped_column(ForeignKey("problem_versions.id", ondelete="CASCADE"))
    solver_run_id: Mapped[str | None] = mapped_column(ForeignKey("solver_runs.id", ondelete="CASCADE"),
                                                      nullable=True)
    source_schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    rank: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(64))
    solver: Mapped[str] = mapped_column(String(64))
    feasibility: Mapped[str] = mapped_column(String(16))
    objectives: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    violations: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    placements: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_problem_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
