"""Phase 2b: users/sessions/rate limits, jobs/job_workers, owner_id on owned tables, actor_id, BIGINT event ids,
hot-path and backstop indexes (PHASE2B 3.3).

Revision ID: 0002_phase2b
Revises: 0001_initial
Create Date: 2026-10-19

Frozen migration: literal definitions only, never import the ORM models. PostgreSQL only (`batch_alter_table` emits
plain ALTER TABLE statements there).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_phase2b"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

LOCAL_USER_ID = "usr_local"
RESTART_ERROR = "Server restarted before the run finished."
OWNED_TABLES = ("problems", "solver_runs", "schedules", "finance_plans", "finance_runs", "finance_results")
BIGINT_ID_TABLES = ("solver_run_events", "finance_run_events", "audit_events")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _where(predicate: str) -> dict[str, Any]:
    return {"postgresql_where": sa.text(predicate)}


def _iso(dt: datetime) -> str:
    dt = dt.astimezone(UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


def _naive_utc(dt: Any) -> datetime:
    if dt is None:
        return datetime.min
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo is not None else dt


# ---------------------------------------------------------------- data steps

def _insert_local_user(bind: sa.Connection, now: datetime) -> None:
    users = sa.table("users", sa.column("id", sa.String), sa.column("email", sa.String),
                     sa.column("display_name", sa.String), sa.column("password_hash", sa.Text),
                     sa.column("is_local", sa.Boolean), sa.column("disabled", sa.Boolean),
                     sa.column("created_at", sa.DateTime(timezone=True)),
                     sa.column("updated_at", sa.DateTime(timezone=True)))
    exists = bind.execute(sa.select(users.c.id).where(users.c.id == LOCAL_USER_ID)).first()
    if exists is None:
        bind.execute(users.insert().values(id=LOCAL_USER_ID, email=None, display_name="Local user",
                                           password_hash=None, is_local=True, disabled=False,
                                           created_at=now, updated_at=now))


def _demote_extra_approved(bind: sa.Connection, now: datetime) -> None:
    """One approved schedule per problem (B 8.1.4): keep the newest approval, older ones become superseded."""
    sch = sa.table("schedules", sa.column("id", sa.String), sa.column("problem_id", sa.String),
                   sa.column("status", sa.String), sa.column("approved_at", sa.DateTime(timezone=True)),
                   sa.column("created_at", sa.DateTime(timezone=True)),
                   sa.column("superseded_at", sa.DateTime(timezone=True)))
    rows = bind.execute(sa.select(sch.c.id, sch.c.problem_id, sch.c.approved_at, sch.c.created_at)
                        .where(sch.c.status == "approved")).all()
    by_problem: dict[str, list[Any]] = {}
    for r in rows:
        by_problem.setdefault(r.problem_id, []).append(r)
    for items in by_problem.values():
        if len(items) < 2:
            continue
        items.sort(key=lambda r: (_naive_utc(r.approved_at or r.created_at), _naive_utc(r.created_at), r.id),
                   reverse=True)
        for r in items[1:]:
            bind.execute(sch.update().where(sch.c.id == r.id).values(status="superseded", superseded_at=now))


def _fail_extra_active_runs(bind: sa.Connection, now: datetime) -> None:
    """One active solver run per problem (B 8.1.4): keep the newest, fail the others like a restart would."""
    runs = sa.table("solver_runs", sa.column("id", sa.String), sa.column("problem_id", sa.String),
                    sa.column("status", sa.String), sa.column("error", sa.Text),
                    sa.column("created_at", sa.DateTime(timezone=True)),
                    sa.column("finished_at", sa.DateTime(timezone=True)))
    events = sa.table("solver_run_events", sa.column("run_id", sa.String), sa.column("seq", sa.Integer),
                      sa.column("type", sa.String), sa.column("payload", _json()),
                      sa.column("created_at", sa.DateTime(timezone=True)))
    rows = bind.execute(sa.select(runs.c.id, runs.c.problem_id, runs.c.created_at)
                        .where(runs.c.status.in_(("queued", "running")))).all()
    by_problem: dict[str, list[Any]] = {}
    for r in rows:
        by_problem.setdefault(r.problem_id, []).append(r)
    for items in by_problem.values():
        if len(items) < 2:
            continue
        items.sort(key=lambda r: (_naive_utc(r.created_at), r.id), reverse=True)
        for r in items[1:]:
            bind.execute(runs.update().where(runs.c.id == r.id)
                         .values(status="failed", error=RESTART_ERROR, finished_at=now))
            seq = int(bind.execute(sa.select(sa.func.max(events.c.seq)).where(events.c.run_id == r.id)).scalar()
                      or 0) + 1
            payload = {"run_id": r.id, "seq": seq, "type": "run_failed", "ts": _iso(now), "elapsed_seconds": 0.0,
                       "error": RESTART_ERROR}
            bind.execute(events.insert().values(run_id=r.id, seq=seq, type="run_failed", payload=payload,
                                                created_at=now))


# ---------------------------------------------------------------- upgrade

def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)

    # 1. accounts tables (B 4.2)
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_local", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("created_at"), _ts("updated_at"), _ts("password_changed_at", True), _ts("last_login_at", True),
    )
    op.create_index("uq_users_email", "users", ["email"], unique=True)
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        _ts("created_at"), _ts("last_seen_at"), _ts("expires_at"), _ts("revoked_at", True),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
    )
    op.create_index("uq_user_sessions_token", "user_sessions", ["token_hash"], unique=True)
    op.create_index("ix_user_sessions_user", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires", "user_sessions", ["expires_at"])
    op.create_table(
        "auth_rate_limits",
        sa.Column("bucket", sa.String(160), primary_key=True),
        _ts("window_start"),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_auth_rate_limits_window", "auth_rate_limits", ["window_start"])

    # 2. data: local user, legacy de-duplication (before the partial unique indexes)
    _insert_local_user(bind, now)
    _demote_extra_approved(bind, now)
    _fail_extra_active_runs(bind, now)

    # 3. owner_id on the owned roots: add nullable, backfill, then NOT NULL + FK
    for t in OWNED_TABLES:
        op.add_column(t, sa.Column("owner_id", sa.String(64), nullable=True))
        bind.execute(sa.text(f"UPDATE {t} SET owner_id = :u WHERE owner_id IS NULL"), {"u": LOCAL_USER_ID})
        with op.batch_alter_table(t) as b:
            b.alter_column("owner_id", existing_type=sa.String(64), nullable=False)
            b.create_foreign_key(f"fk_{t}_owner_id_users", "users", ["owner_id"], ["id"], ondelete="RESTRICT")

    # 4. audit actor (no FK: audit survives user deletion)
    op.add_column("audit_events", sa.Column("actor_id", sa.String(64), nullable=True))

    # 5. int8 event/audit ids
    for t in BIGINT_ID_TABLES:
        op.alter_column(t, "id", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)
        op.execute(f"ALTER SEQUENCE IF EXISTS {t}_id_seq AS bigint")

    # 6. indexes (hot queries, FK columns, backstops)
    op.create_index("ix_problems_owner_updated", "problems", ["owner_id", "updated_at", "id"])
    op.create_index("ix_finance_plans_owner_updated", "finance_plans", ["owner_id", "updated_at", "id"])
    op.create_index("ix_schedules_run_rank", "schedules", ["solver_run_id", "rank"])
    op.create_index("ix_schedules_problem_version", "schedules", ["problem_version_id"])
    op.create_index("ix_solver_runs_problem_version", "solver_runs", ["problem_version_id"])
    op.create_index("ix_finance_runs_plan_version", "finance_runs", ["plan_version_id"])
    op.create_index("ix_finance_results_plan_version", "finance_results", ["plan_version_id"])
    op.create_index("uq_finance_results_run", "finance_results", ["run_id"], unique=True)
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id", "created_at"])
    op.create_index("uq_solver_runs_one_active", "solver_runs", ["problem_id"], unique=True,
                    **_where("status IN ('queued', 'running')"))
    op.create_index("uq_schedules_one_approved", "schedules", ["problem_id"], unique=True,
                    **_where("status = 'approved'"))

    # 7. jobs (B 2.3)
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("solver_run_id", sa.String(64), sa.ForeignKey("solver_runs.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("finance_run_id", sa.String(64), sa.ForeignKey("finance_runs.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("owner_id", sa.String(64),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_jobs_owner_id_users"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        _ts("run_after"),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_token", sa.String(32), nullable=True),
        _ts("lease_expires_at", True), _ts("heartbeat_at", True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _ts("created_at"), _ts("updated_at"), _ts("started_at", True), _ts("finished_at", True),
        sa.CheckConstraint("(solver_run_id IS NULL) <> (finance_run_id IS NULL)", name="ck_jobs_one_target"),
    )
    op.create_index("ix_jobs_claim", "jobs", [sa.text("priority DESC"), "run_after", "created_at", "id"],
                    **_where("status = 'queued'"))
    op.create_index("ix_jobs_running_lease", "jobs", ["lease_expires_at"], **_where("status = 'running'"))
    op.create_index("uq_jobs_solver_run", "jobs", ["solver_run_id"], unique=True,
                    **_where("solver_run_id IS NOT NULL"))
    op.create_index("uq_jobs_finance_run", "jobs", ["finance_run_id"], unique=True,
                    **_where("finance_run_id IS NOT NULL"))
    op.create_index("uq_jobs_idempotency", "jobs", ["owner_id", "idempotency_key"], unique=True,
                    **_where("idempotency_key IS NOT NULL"))
    op.create_index("ix_jobs_status_finished", "jobs", ["status", "finished_at"])
    op.create_table(
        "job_workers",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("kinds", _json(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("busy", sa.Integer(), nullable=False),
        _ts("started_at"), _ts("heartbeat_at"), _ts("stopped_at", True),
    )


# ---------------------------------------------------------------- downgrade

def downgrade() -> None:

    op.drop_table("job_workers")
    for ix in ("ix_jobs_status_finished", "uq_jobs_idempotency", "uq_jobs_finance_run", "uq_jobs_solver_run",
               "ix_jobs_running_lease", "ix_jobs_claim"):
        op.drop_index(ix, table_name="jobs")
    op.drop_table("jobs")

    for ix, t in (("uq_schedules_one_approved", "schedules"), ("uq_solver_runs_one_active", "solver_runs"),
                  ("ix_audit_entity", "audit_events"), ("uq_finance_results_run", "finance_results"),
                  ("ix_finance_results_plan_version", "finance_results"),
                  ("ix_finance_runs_plan_version", "finance_runs"),
                  ("ix_solver_runs_problem_version", "solver_runs"),
                  ("ix_schedules_problem_version", "schedules"), ("ix_schedules_run_rank", "schedules"),
                  ("ix_finance_plans_owner_updated", "finance_plans"), ("ix_problems_owner_updated", "problems")):
        op.drop_index(ix, table_name=t)

    for t in BIGINT_ID_TABLES:
        op.execute(f"ALTER SEQUENCE IF EXISTS {t}_id_seq AS integer")
        op.alter_column(t, "id", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False)

    with op.batch_alter_table("audit_events") as b:
        b.drop_column("actor_id")
    for t in reversed(OWNED_TABLES):
        with op.batch_alter_table(t) as b:
            b.drop_constraint(f"fk_{t}_owner_id_users", type_="foreignkey")
            b.drop_column("owner_id")

    op.drop_index("ix_auth_rate_limits_window", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
    for ix in ("ix_user_sessions_expires", "ix_user_sessions_user", "uq_user_sessions_token"):
        op.drop_index(ix, table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("uq_users_email", table_name="users")
    op.drop_table("users")
