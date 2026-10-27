"""Initial schema: the 11 tables of the pre-Phase-2b application.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-19

Frozen migration: literal table definitions only, never import the ORM models. `build_metadata()` is the
revision-local table definition this step creates (Alembic-managed; nothing creates tables outside the chain).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEDULING_TABLES = ("problems", "problem_versions", "solver_runs", "solver_run_events", "schedules", "audit_events")
FINANCE_TABLES = ("finance_plans", "finance_plan_versions", "finance_runs", "finance_run_events", "finance_results")
TABLES = SCHEDULING_TABLES + FINANCE_TABLES


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def build_metadata() -> sa.MetaData:
    md = sa.MetaData()
    sa.Table(
        "problems", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", _json(), nullable=False),
        _ts("created_at"), _ts("updated_at"),
    )
    sa.Table(
        "problem_versions", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("problem_id", sa.String(64), sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("document", _json(), nullable=False),
        _ts("created_at"),
        sa.Index("ix_problem_versions_hash", "problem_id", "content_hash"),
    )
    sa.Table(
        "solver_runs", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("problem_id", sa.String(64), sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("problem_version_id", sa.String(64), sa.ForeignKey("problem_versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request", _json(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("selection", _json(), nullable=True),
        sa.Column("phases", _json(), nullable=True),
        sa.Column("feasibility", sa.String(16), nullable=True),
        sa.Column("termination_reason", sa.String(32), nullable=True),
        sa.Column("optimality_proven", sa.Boolean(), nullable=True),
        sa.Column("objectives", _json(), nullable=True),
        sa.Column("metrics", _json(), nullable=True),
        sa.Column("diagnostics", _json(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("source_schedule_id", sa.String(64), nullable=True),
        _ts("created_at"), _ts("started_at", True), _ts("finished_at", True),
        sa.Index("ix_solver_runs_problem_created", "problem_id", "created_at"),
        sa.Index("ix_solver_runs_status", "status"),
    )
    sa.Table(
        "solver_run_events", md,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("solver_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
    )
    sa.Table(
        "schedules", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("problem_id", sa.String(64), sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("problem_version_id", sa.String(64), sa.ForeignKey("problem_versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("solver_run_id", sa.String(64), sa.ForeignKey("solver_runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source_schedule_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("solver", sa.String(64), nullable=False),
        sa.Column("feasibility", sa.String(16), nullable=False),
        sa.Column("objectives", _json(), nullable=True),
        sa.Column("metrics", _json(), nullable=True),
        sa.Column("violations", _json(), nullable=False),
        sa.Column("placements", _json(), nullable=False),
        sa.Column("explanation", _json(), nullable=True),
        _ts("created_at"), _ts("approved_at", True), _ts("superseded_at", True),
        sa.Column("approved_problem_version", sa.Integer(), nullable=True),
        sa.Index("ix_schedules_problem_status", "problem_id", "status"),
    )
    sa.Table(
        "audit_events", md,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details", _json(), nullable=False),
        _ts("created_at"),
    )
    sa.Table(
        "finance_plans", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", _json(), nullable=False),
        _ts("created_at"), _ts("updated_at"),
    )
    sa.Table(
        "finance_plan_versions", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("finance_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("document", _json(), nullable=False),
        _ts("created_at"),
        sa.Index("ix_finance_plan_versions_hash", "plan_id", "content_hash"),
    )
    sa.Table(
        "finance_runs", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("finance_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_version_id", sa.String(64), sa.ForeignKey("finance_plan_versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request", _json(), nullable=False),
        sa.Column("what_if", _json(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("feasibility", sa.String(16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        _ts("created_at"), _ts("started_at", True), _ts("finished_at", True),
        sa.Index("ix_finance_runs_plan_created", "plan_id", "created_at"),
        sa.Index("ix_finance_runs_status", "status"),
    )
    sa.Table(
        "finance_run_events", md,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("finance_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("run_id", "seq", name="uq_finance_run_event_seq"),
    )
    sa.Table(
        "finance_results", md,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("finance_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_version_id", sa.String(64), sa.ForeignKey("finance_plan_versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("finance_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("feasibility", sa.String(16), nullable=False),
        sa.Column("summary", _json(), nullable=False),
        sa.Column("result", _json(), nullable=False),
        _ts("created_at"),
        sa.Index("ix_finance_results_plan_created", "plan_id", "created_at"),
    )
    return md


def upgrade() -> None:
    build_metadata().create_all(op.get_bind())


def downgrade() -> None:
    build_metadata().drop_all(op.get_bind())
