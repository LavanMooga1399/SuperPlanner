"""SQLAlchemy 2 ORM tables (ARCHITECTURE 13)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData,
                        SmallInteger, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .ownership import OwnedMixin

JsonType = JSON().with_variant(JSONB(), "postgresql")
# int8 on PostgreSQL; SQLite keeps INTEGER PRIMARY KEY (rowid alias, autoincrement) (PHASE2B 3.3).
BigIntId = BigInteger().with_variant(Integer, "sqlite")


def _partial(predicate: str) -> dict[str, object]:
    """Partial-index predicate for both dialects (SQLite supports partial indexes)."""
    return {"postgresql_where": text(predicate), "sqlite_where": text(predicate)}


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    # Named FKs so migrations can address them (`fk_problems_owner_id_users`); other names are unchanged.
    metadata = MetaData(naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"})


class ProblemRow(OwnedMixin, Base):
    __tablename__ = "problems"
    __table_args__ = (Index("ix_problems_owner_updated", "owner_id", "updated_at", "id"),)

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


class SolverRunRow(OwnedMixin, Base):
    __tablename__ = "solver_runs"
    __table_args__ = (Index("ix_solver_runs_problem_created", "problem_id", "created_at"),
                      Index("ix_solver_runs_status", "status"),
                      Index("ix_solver_runs_problem_version", "problem_version_id"),
                      Index("uq_solver_runs_one_active", "problem_id", unique=True,
                            **_partial("status IN ('queued', 'running')")))

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

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("solver_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduleRow(OwnedMixin, Base):
    __tablename__ = "schedules"
    __table_args__ = (Index("ix_schedules_problem_status", "problem_id", "status"),
                      Index("ix_schedules_run_rank", "solver_run_id", "rank"),
                      Index("ix_schedules_problem_version", "problem_version_id"),
                      Index("uq_schedules_one_approved", "problem_id", unique=True, **_partial("status = 'approved'")))

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
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)   # user id; no FK (survives deletion)


# ---------------------------------------------------------------- jobs (PHASE2B 2.3)

class JobRow(OwnedMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("(solver_run_id IS NULL) <> (finance_run_id IS NULL)", name="ck_jobs_one_target"),
        Index("ix_jobs_running_lease", "lease_expires_at", **_partial("status = 'running'")),
        Index("uq_jobs_solver_run", "solver_run_id", unique=True, **_partial("solver_run_id IS NOT NULL")),
        Index("uq_jobs_finance_run", "finance_run_id", unique=True, **_partial("finance_run_id IS NOT NULL")),
        Index("uq_jobs_idempotency", "owner_id", "idempotency_key", unique=True,
              **_partial("idempotency_key IS NOT NULL")),
        Index("ix_jobs_status_finished", "status", "finished_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    solver_run_id: Mapped[str | None] = mapped_column(ForeignKey("solver_runs.id", ondelete="CASCADE"),
                                                      nullable=True)
    finance_run_id: Mapped[str | None] = mapped_column(ForeignKey("finance_runs.id", ondelete="CASCADE"),
                                                       nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    priority: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Claim order ORDER BY priority DESC, run_after, created_at, id (B 2.5); declared here to reference the columns.
Index("ix_jobs_claim", JobRow.priority.desc(), JobRow.run_after, JobRow.created_at, JobRow.id,
      **_partial("status = 'queued'"))


class JobWorkerRow(Base):
    __tablename__ = "job_workers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255))
    pid: Mapped[int] = mapped_column(Integer)
    kinds: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    concurrency: Mapped[int] = mapped_column(Integer)
    busy: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Register the tables of the other packages on the same metadata (users for every owner_id FK, finance_runs for
# jobs.finance_run_id), so that create_all, flush ordering and Alembic always see the complete schema.
from ..auth import models as _auth_models  # noqa: E402,F401
from ..finance import db_models as _finance_db_models  # noqa: E402,F401
