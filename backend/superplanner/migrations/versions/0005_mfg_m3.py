"""M3 finite-capacity scheduling (APS): 10 new tables, 4 new columns on `mfg_plant`, job kind `aps_run`
(`jobs.aps_run_id`) (M3-DESIGN 10).

Revision ID: 0005_mfg_m3
Revises: 0004_mfg_m2
Create Date: 2026-10-30

Frozen migration: literal definitions only, never import the ORM models. New NOT NULL plant columns are added with
a server default that is dropped again in the same migration (M2 9.1). `jobs.ck_jobs_one_target` becomes "exactly
one of solver_run_id / finance_run_id / aps_run_id". `downgrade()` drops the tables in reverse order, the job
column (deleting `aps_run` jobs first) and the plant columns, and restores the two-target check.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_mfg_m3"
down_revision = "0004_mfg_m2"
branch_labels = None
depends_on = None

TABLES = ("mfg_operation_line_rates", "mfg_setup_matrix", "mfg_operator_absences", "mfg_wo_op_progress",
          "mfg_aps_runs", "mfg_aps_ops", "mfg_aps_overtime", "mfg_aps_orders", "mfg_aps_exceptions", "mfg_aps_load")
PLANT_COLUMNS = ("time_zone", "aps_freeze_hours", "aps_horizon_days", "aps_overtime_policy")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _plant_columns() -> None:
    op.add_column("mfg_plant", sa.Column("time_zone", sa.String(64), nullable=True))
    op.add_column("mfg_plant", sa.Column("aps_freeze_hours", sa.Integer(), nullable=False,
                                         server_default=sa.text("48")))
    op.add_column("mfg_plant", sa.Column("aps_horizon_days", sa.Integer(), nullable=False,
                                         server_default=sa.text("42")))
    op.add_column("mfg_plant", sa.Column("aps_overtime_policy", sa.String(8), nullable=False,
                                         server_default=sa.text("'suggest'")))
    for col in PLANT_COLUMNS[1:]:
        op.alter_column("mfg_plant", col, server_default=None)


def _jobs_up() -> None:
    op.add_column("jobs", sa.Column("aps_run_id", sa.String(64),
                                    sa.ForeignKey("mfg_aps_runs.id", ondelete="CASCADE",
                                                  name="fk_jobs_aps_run_id_mfg_aps_runs"),
                                    nullable=True))
    op.create_index("uq_jobs_aps_run", "jobs", ["aps_run_id"], unique=True,
                    postgresql_where=sa.text("aps_run_id IS NOT NULL"))
    op.drop_constraint("ck_jobs_one_target", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_one_target", "jobs",
                               "num_nonnulls(solver_run_id, finance_run_id, aps_run_id) = 1")


def _jobs_down() -> None:
    op.execute("DELETE FROM jobs WHERE aps_run_id IS NOT NULL")
    op.drop_constraint("ck_jobs_one_target", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_one_target", "jobs", "(solver_run_id IS NULL) <> (finance_run_id IS NULL)")
    op.drop_index("uq_jobs_aps_run", table_name="jobs")
    op.drop_column("jobs", "aps_run_id")


def upgrade() -> None:
    _plant_columns()
    op.create_table(
        'mfg_operation_line_rates',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('operation_id', sa.String(64),
                  sa.ForeignKey('mfg_operations.id', ondelete='CASCADE',
                                name='fk_mfg_operation_line_rates_operation_id_mfg_operations'), nullable=False),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='CASCADE',
                                name='fk_mfg_operation_line_rates_line_id_mfg_lines'), nullable=False),
        sa.Column('setup_minutes', sa.Double(), nullable=True),
        sa.Column('run_minutes', sa.Double(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_operation_line_rates_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('operation_id', 'line_id', name='uq_mfg_operation_line_rates_key'),
    )
    op.create_index('ix_mfg_operation_line_rates_line', 'mfg_operation_line_rates', ['line_id'])
    op.create_index('ix_mfg_operation_line_rates_owner', 'mfg_operation_line_rates', ['owner_id'])
    op.create_table(
        'mfg_setup_matrix',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('line_setup_family', sa.String(32), nullable=False),
        sa.Column('from_family', sa.String(32), nullable=False),
        sa.Column('to_family', sa.String(32), nullable=False),
        sa.Column('setup_minutes', sa.Double(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_setup_matrix_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'line_setup_family', 'from_family', 'to_family',
                                name='uq_mfg_setup_matrix_key'),
    )
    op.create_table(
        'mfg_operator_absences',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('operator_id', sa.String(64),
                  sa.ForeignKey('mfg_operators.id', ondelete='CASCADE',
                                name='fk_mfg_operator_absences_operator_id_mfg_operators'), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_operator_absences_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfg_operator_absences_operator_start', 'mfg_operator_absences', ['operator_id', 'start_at'])
    op.create_index('ix_mfg_operator_absences_owner', 'mfg_operator_absences', ['owner_id'])
    op.create_table(
        'mfg_wo_op_progress',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('wo_id', sa.String(64),
                  sa.ForeignKey('mfg_work_orders.id', ondelete='CASCADE',
                                name='fk_mfg_wo_op_progress_wo_id_mfg_work_orders'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('done_by', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_wo_op_progress_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('wo_id', 'seq', name='uq_mfg_wo_op_progress_key'),
    )
    op.create_index('ix_mfg_wo_op_progress_owner', 'mfg_wo_op_progress', ['owner_id'])
    op.create_table(
        'mfg_aps_runs',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('pinned', sa.Boolean(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by', sa.String(64), nullable=True),
        sa.Column('parent_run_id', sa.String(64),
                  sa.ForeignKey('mfg_aps_runs.id', ondelete='SET NULL',
                                name='fk_mfg_aps_runs_parent_run_id_mfg_aps_runs'), nullable=True),
        sa.Column('copy_of_run_id', sa.String(64), nullable=True),
        sa.Column('mrp_run_id', sa.String(64), nullable=True),
        sa.Column('params', _json(), nullable=False),
        sa.Column('as_of', sa.DateTime(timezone=True), nullable=False),
        sa.Column('horizon_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('master_fingerprint', sa.String(64), nullable=False),
        sa.Column('data_version', sa.Integer(), nullable=False),
        sa.Column('inputs_token', _json(), nullable=False),
        sa.Column('job_id', sa.String(64), nullable=True),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('progress', _json(), nullable=True),
        sa.Column('summary', _json(), nullable=True),
        sa.Column('score', _json(), nullable=True),
        sa.Column('validation', _json(), nullable=True),
        sa.Column('extras', _json(), nullable=True),
        sa.Column('error', _json(), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_aps_runs_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'run_no', name='uq_mfg_aps_runs_no'),
    )
    op.create_index('ix_mfg_aps_runs_owner_created', 'mfg_aps_runs', ['owner_id', 'created_at'])
    op.create_index('ix_mfg_aps_runs_parent', 'mfg_aps_runs', ['parent_run_id'])
    op.create_index('uq_mfg_aps_runs_active', 'mfg_aps_runs', ['owner_id'], unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index('uq_mfg_aps_runs_published', 'mfg_aps_runs', ['owner_id'], unique=True, postgresql_where=sa.text("is_published"))
    op.create_table(
        'mfg_aps_ops',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_aps_runs.id', ondelete='CASCADE',
                                name='fk_mfg_aps_ops_run_id_mfg_aps_runs'), nullable=False),
        sa.Column('op_no', sa.Integer(), nullable=False),
        sa.Column('order_type', sa.String(8), nullable=False),
        sa.Column('order_id', sa.String(64), nullable=False),
        sa.Column('order_number', sa.String(32), nullable=False),
        sa.Column('planned_no', sa.Integer(), nullable=True),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('part_number', sa.String(64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('group_id', sa.String(64), nullable=False),
        sa.Column('line_id', sa.String(64), nullable=True),
        sa.Column('split_index', sa.Integer(), nullable=False),
        sa.Column('split_count', sa.Integer(), nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('setup_minutes', sa.Integer(), nullable=False),
        sa.Column('run_minutes', sa.Integer(), nullable=False),
        sa.Column('pieces', _json(), nullable=False),
        sa.Column('crew', _json(), nullable=False),
        sa.Column('tools', _json(), nullable=False),
        sa.Column('release', _json(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('frozen', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('reason', _json(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('late_minutes', sa.Integer(), nullable=False),
        sa.Column('family', sa.String(32), nullable=False),
        sa.Column('setup_from_family', sa.String(32), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_aps_ops_owner_id_users'), nullable=False),
        sa.UniqueConstraint('run_id', 'op_no', name='uq_mfg_aps_ops_no'),
    )
    op.create_index('ix_mfg_aps_ops_owner', 'mfg_aps_ops', ['owner_id'])
    op.create_index('ix_mfg_aps_ops_run_line_start', 'mfg_aps_ops', ['run_id', 'line_id', 'start_at'])
    op.create_index('ix_mfg_aps_ops_run_order', 'mfg_aps_ops', ['run_id', 'order_id'])
    op.create_table(
        'mfg_aps_overtime',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_aps_runs.id', ondelete='CASCADE',
                                name='fk_mfg_aps_overtime_run_id_mfg_aps_runs'), nullable=False),
        sa.Column('line_id', sa.String(64), nullable=False),
        sa.Column('assignment_id', sa.String(64), nullable=True),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('minutes', sa.Integer(), nullable=False),
        sa.Column('cost', sa.Double(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('tardiness_saved_minutes', sa.Double(), nullable=True),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('orders', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_aps_overtime_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_aps_overtime_owner', 'mfg_aps_overtime', ['owner_id'])
    op.create_index('ix_mfg_aps_overtime_run_line', 'mfg_aps_overtime', ['run_id', 'line_id', 'start_at'])
    op.create_table(
        'mfg_aps_orders',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_aps_runs.id', ondelete='CASCADE',
                                name='fk_mfg_aps_orders_run_id_mfg_aps_runs'), nullable=False),
        sa.Column('order_type', sa.String(8), nullable=False),
        sa.Column('order_id', sa.String(64), nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('planned_no', sa.Integer(), nullable=True),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('part_number', sa.String(64), nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('late_minutes', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Double(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('rank_label', sa.String(100), nullable=False),
        sa.Column('demand_refs', _json(), nullable=False),
        sa.Column('late_chain', _json(), nullable=False),
        sa.Column('late_text', sa.String(1000), nullable=False),
        sa.Column('unscheduled_ops', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_aps_orders_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_aps_orders_owner', 'mfg_aps_orders', ['owner_id'])
    op.create_index('ix_mfg_aps_orders_run_late', 'mfg_aps_orders', ['run_id', 'late_minutes'])
    op.create_index('ix_mfg_aps_orders_run_order', 'mfg_aps_orders', ['run_id', 'order_id'])
    op.create_table(
        'mfg_aps_exceptions',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_aps_runs.id', ondelete='CASCADE',
                                name='fk_mfg_aps_exceptions_run_id_mfg_aps_runs'), nullable=False),
        sa.Column('ex_no', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('severity', sa.String(8), nullable=False),
        sa.Column('subject', _json(), nullable=False),
        sa.Column('op_no', sa.Integer(), nullable=True),
        sa.Column('order_ref', _json(), nullable=True),
        sa.Column('message', sa.String(1000), nullable=False),
        sa.Column('refs', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_aps_exceptions_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_aps_exceptions_owner', 'mfg_aps_exceptions', ['owner_id'])
    op.create_index('ix_mfg_aps_exceptions_run_sev_code', 'mfg_aps_exceptions', ['run_id', 'severity', 'code'])
    op.create_table(
        'mfg_aps_load',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_aps_runs.id', ondelete='CASCADE',
                                name='fk_mfg_aps_load_run_id_mfg_aps_runs'), nullable=False),
        sa.Column('group_id', sa.String(64), nullable=False),
        sa.Column('line_id', sa.String(64), nullable=True),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('scheduled_minutes', sa.Double(), nullable=False),
        sa.Column('required_minutes', sa.Double(), nullable=False),
        sa.Column('base_minutes', sa.Double(), nullable=False),
        sa.Column('optional_minutes', sa.Double(), nullable=False),
        sa.Column('opened_minutes', sa.Double(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_aps_load_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_aps_load_owner', 'mfg_aps_load', ['owner_id'])
    op.create_index('ix_mfg_aps_load_run_group_day', 'mfg_aps_load', ['run_id', 'group_id', 'day'])

    _jobs_up()


def downgrade() -> None:
    _jobs_down()
    for table in reversed(TABLES):
        op.drop_table(table)
    for col in PLANT_COLUMNS:
        op.drop_column("mfg_plant", col)
