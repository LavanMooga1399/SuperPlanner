"""M4 execution and replanning: 10 new tables, master columns on items / operations / lines / operators / plant /
work orders, job kind `aps_simulation` (`jobs.aps_simulation_id`); M3's `mfg_wo_op_progress` is migrated into
`mfg_wo_operations` and dropped (M4-DESIGN 3).

Revision ID: 0006_mfg_m4
Revises: 0005_mfg_m3
Create Date: 2026-10-31

Frozen migration: literal definitions only, never import the ORM models. New NOT NULL columns are added with a server
default that is dropped again in the same migration (M2 9.1). Progress rows with `done` become completed operations
(`source migrated`, name/group from the WO routing's operation of that seq, else the item's released primary
routing; `qty_planned = qty_good =` the WO quantity) plus one synthetic `complete` event each (`details.migrated`)
so the event log stays the single truth (M4-DESIGN 16.WP-S). `jobs.ck_jobs_one_target` becomes "exactly one of
four". `downgrade()` writes completed operations back as progress rows, then drops the M4 tables and columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_mfg_m4"
down_revision = "0005_mfg_m3"
branch_labels = None
depends_on = None

TABLES = ("mfg_wo_operations", "mfg_batch_loads", "mfg_batch_load_members", "mfg_floor_events", "mfg_downtime",
          "mfg_unit_serials", "mfg_replan_triggers", "mfg_notifications", "mfg_aps_simulations", "mfg_kpi_daily")
#: (table, column, type, server default or None, fk target or None, index name or None)
COLUMNS = (
    ("mfg_items", "issue_method", sa.String(16), "'manual'", None, None),   # S16: "backflush" has 9 characters
    ("mfg_operations", "capture_serial", sa.Boolean(), "false", None, None),
    ("mfg_lines", "location_id", sa.String(64), None, "mfg_locations", "ix_mfg_lines_location"),
    ("mfg_lines", "batch_merge", sa.Boolean(), "false", None, None),
    ("mfg_lines", "batch_wait_minutes", sa.Integer(), "0", None, None),
    ("mfg_operators", "user_id", sa.String(64), None, "users", "ix_mfg_operators_user"),
    ("mfg_plant", "replan_policy", sa.String(16), "'notify'", None, None),
    ("mfg_plant", "replan_debounce_minutes", sa.Integer(), "15", None, None),
    ("mfg_plant", "overrun_tolerance_pct", sa.Double(), "20", None, None),
    ("mfg_plant", "adherence_tolerance_minutes", sa.Integer(), "120", None, None),
    ("mfg_plant", "wo_receipt_location_id", sa.String(64), None, "mfg_locations", "ix_mfg_plant_wo_receipt_location"),
    ("mfg_plant", "backflush_location_id", sa.String(64), None, "mfg_locations", "ix_mfg_plant_backflush_location"),
    ("mfg_work_orders", "receipt_location_id", sa.String(64), None, "mfg_locations",
     "ix_mfg_work_orders_receipt_location"),
    ("mfg_work_orders", "released_to_floor_at", sa.DateTime(timezone=True), None, None, None),
    ("mfg_work_orders", "release_override", sa.String(200), None, None, None),
    ("mfg_aps_ops", "moved_by_downtime", sa.Boolean(), "false", None, None),          # 11: run results gain
)


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _columns_up() -> None:
    for table, col, type_, default, fk, ix in COLUMNS:
        args: list = []
        if fk is not None:
            args.append(sa.ForeignKey(f"{fk}.id", ondelete="SET NULL", name=f"fk_{table}_{col}_{fk}"))
        op.add_column(table, sa.Column(col, type_, *args, nullable=default is None,
                                       server_default=sa.text(default) if default is not None else None))
        if default is not None:
            op.alter_column(table, col, server_default=None)
        if ix is not None:
            op.create_index(ix, table, [col])


def _aps_actual_up() -> None:
    op.add_column("mfg_aps_ops", sa.Column("actual", _json(), nullable=True))


def _columns_down() -> None:
    for table, col, _t, _d, _fk, ix in reversed(COLUMNS):
        if ix is not None:
            op.drop_index(ix, table_name=table)
        op.drop_column(table, col)


def _jobs_up() -> None:
    op.add_column("jobs", sa.Column("aps_simulation_id", sa.String(64),
                                    sa.ForeignKey("mfg_aps_simulations.id", ondelete="CASCADE",
                                                  name="fk_jobs_aps_simulation_id_mfg_aps_simulations"),
                                    nullable=True))
    op.create_index("uq_jobs_aps_simulation", "jobs", ["aps_simulation_id"], unique=True,
                    postgresql_where=sa.text("aps_simulation_id IS NOT NULL"))
    op.drop_constraint("ck_jobs_one_target", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_one_target", "jobs",
                               "num_nonnulls(solver_run_id, finance_run_id, aps_run_id, aps_simulation_id) = 1")


def _jobs_down() -> None:
    op.execute("DELETE FROM jobs WHERE aps_simulation_id IS NOT NULL")
    op.drop_constraint("ck_jobs_one_target", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_one_target", "jobs",
                               "num_nonnulls(solver_run_id, finance_run_id, aps_run_id) = 1")
    op.drop_index("uq_jobs_aps_simulation", table_name="jobs")
    op.drop_column("jobs", "aps_simulation_id")


#: the routing of a WO: its own, else the item's released routing effective at the start (lowest priority number,
#: newest version) - the SQL analogue of `mfg.routing.primary_routing` without serial effectivity
_ROUTING_OF_WO = """
COALESCE(w.routing_id, (
    SELECT r.id FROM mfg_routings r
     WHERE r.item_id = w.item_id AND r.owner_id = w.owner_id AND r.status = 'released'
       AND (r.effective_from IS NULL OR r.effective_from <= w.start_date)
       AND (r.effective_to IS NULL OR w.start_date < r.effective_to)
     ORDER BY r.priority, r.version DESC, r.id LIMIT 1))
"""

_MIGRATE_PROGRESS = f"""
INSERT INTO mfg_wo_operations (id, wo_id, seq, name, group_id, status, qty_planned, qty_good, qty_scrap,
    qty_rework_out, qty_rework_in, line_id, setup_minutes_actual, run_minutes_actual, labour_minutes, actual_start,
    actual_end, started_short, source, last_event_seq, effects, completed_at, completed_by, owner_id, row_version,
    created_at, updated_at)
SELECT p.id, p.wo_id, p.seq,
       COALESCE(o.name, 'Operation ' || p.seq::text), COALESCE(o.group_id, ''),
       'completed', w.qty, w.qty, 0, 0, 0, NULL, 0, 0, 0, NULL, p.done_at, false, 'migrated', NULL,
       CAST('{{}}' AS JSONB), p.done_at, p.done_by, p.owner_id, 1, p.created_at, p.updated_at
  FROM mfg_wo_op_progress p
  JOIN mfg_work_orders w ON w.id = p.wo_id
  LEFT JOIN mfg_operations o ON o.routing_id = {_ROUTING_OF_WO} AND o.seq = p.seq
 WHERE p.done
"""

_MIGRATE_EVENTS = """
INSERT INTO mfg_floor_events (id, wo_operation_id, wo_id, event_type, event_at, recorded_at, line_id, operator_ids,
    qty_good, qty_scrap, qty_rework, rework_to_seq, reason_code, note, client_event_id, batch_load_id, serials,
    corrects_event_id, forced, details, actor_id, owner_id)
SELECT 'fev_' || md5(o.id), o.id, o.wo_id, 'complete', COALESCE(o.completed_at, o.updated_at), o.updated_at, NULL,
       CAST('[]' AS JSONB), o.qty_good, 0, NULL, NULL, NULL, 'Migrated from the M3 done marker', NULL, NULL, NULL,
       NULL, NULL, CAST('{"migrated": true}' AS JSONB), COALESCE(o.completed_by, o.owner_id), o.owner_id
  FROM mfg_wo_operations o WHERE o.source = 'migrated'
 ORDER BY o.owner_id, o.wo_id, o.seq
"""

_EVENT_CURSOR = """
UPDATE mfg_wo_operations o SET last_event_seq = e.seq
  FROM mfg_floor_events e WHERE e.wo_operation_id = o.id AND o.source = 'migrated'
"""


def _progress_table() -> None:
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


_PROGRESS_BACK = """
INSERT INTO mfg_wo_op_progress (id, wo_id, seq, done, done_at, done_by, owner_id, row_version, created_at, updated_at)
SELECT CASE WHEN left(o.id, 4) = 'wop_' THEN o.id ELSE 'wop_' || md5(o.id) END, o.wo_id, o.seq, true,
       COALESCE(o.completed_at, o.actual_end, o.updated_at), o.completed_by, o.owner_id, 1, o.created_at, o.updated_at
  FROM mfg_wo_operations o WHERE o.status IN ('completed', 'skipped')
"""


def upgrade() -> None:
    _columns_up()
    _aps_actual_up()
    op.create_table(
        'mfg_wo_operations',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('wo_id', sa.String(64),
                  sa.ForeignKey('mfg_work_orders.id', ondelete='CASCADE',
                                name='fk_mfg_wo_operations_wo_id_mfg_work_orders'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('group_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('qty_planned', sa.Double(), nullable=False),
        sa.Column('qty_good', sa.Double(), nullable=False),
        sa.Column('qty_scrap', sa.Double(), nullable=False),
        sa.Column('qty_rework_out', sa.Double(), nullable=False),
        sa.Column('qty_rework_in', sa.Double(), nullable=False),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='SET NULL',
                                name='fk_mfg_wo_operations_line_id_mfg_lines'), nullable=True),
        sa.Column('setup_minutes_actual', sa.Double(), nullable=False),
        sa.Column('run_minutes_actual', sa.Double(), nullable=False),
        sa.Column('labour_minutes', sa.Double(), nullable=False),
        sa.Column('actual_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_short', sa.Boolean(), nullable=False),
        sa.Column('source', sa.String(8), nullable=False),
        sa.Column('last_event_seq', sa.BigInteger(), nullable=True),
        sa.Column('effects', _json(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_wo_operations_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('wo_id', 'seq', name='uq_mfg_wo_operations_key'),
    )
    op.create_index('ix_mfg_wo_operations_line', 'mfg_wo_operations', ['line_id'])
    op.create_index('ix_mfg_wo_operations_owner_status', 'mfg_wo_operations', ['owner_id', 'status'])
    op.create_table(
        'mfg_batch_loads',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='RESTRICT',
                                name='fk_mfg_batch_loads_line_id_mfg_lines'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('aps_run_id', sa.String(64), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_batch_loads_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfg_batch_loads_line_status', 'mfg_batch_loads', ['line_id', 'status'])
    op.create_index('ix_mfg_batch_loads_owner_status', 'mfg_batch_loads', ['owner_id', 'status'])
    op.create_table(
        'mfg_batch_load_members',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('load_id', sa.String(64),
                  sa.ForeignKey('mfg_batch_loads.id', ondelete='CASCADE',
                                name='fk_mfg_batch_load_members_load_id_mfg_batch_loads'), nullable=False),
        sa.Column('wo_operation_id', sa.String(64),
                  sa.ForeignKey('mfg_wo_operations.id', ondelete='RESTRICT',
                                name='fk_mfg_batch_load_members_wo_operation_id_mfg_wo_operations'), nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_batch_load_members_owner_id_users'), nullable=False),
        sa.UniqueConstraint('load_id', 'wo_operation_id', name='uq_mfg_batch_load_members_key'),
    )
    op.create_index('ix_mfg_batch_load_members_owner', 'mfg_batch_load_members', ['owner_id'])
    op.create_index('ix_mfg_batch_load_members_wo_operation', 'mfg_batch_load_members', ['wo_operation_id'])
    op.create_table(
        'mfg_floor_events',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('wo_operation_id', sa.String(64),
                  sa.ForeignKey('mfg_wo_operations.id', ondelete='RESTRICT',
                                name='fk_mfg_floor_events_wo_operation_id_mfg_wo_operations'), nullable=False),
        sa.Column('wo_id', sa.String(64),
                  sa.ForeignKey('mfg_work_orders.id', ondelete='RESTRICT',
                                name='fk_mfg_floor_events_wo_id_mfg_work_orders'), nullable=False),
        sa.Column('event_type', sa.String(16), nullable=False),
        sa.Column('event_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('line_id', sa.String(64), nullable=True),
        sa.Column('operator_ids', _json(), nullable=False),
        sa.Column('qty_good', sa.Double(), nullable=True),
        sa.Column('qty_scrap', sa.Double(), nullable=True),
        sa.Column('qty_rework', sa.Double(), nullable=True),
        sa.Column('rework_to_seq', sa.Integer(), nullable=True),
        sa.Column('reason_code', sa.String(32), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('client_event_id', sa.String(64), nullable=True),
        sa.Column('batch_load_id', sa.String(64),
                  sa.ForeignKey('mfg_batch_loads.id', ondelete='SET NULL',
                                name='fk_mfg_floor_events_batch_load_id_mfg_batch_loads'), nullable=True),
        sa.Column('serials', _json(), nullable=True),
        sa.Column('corrects_event_id', sa.String(64),
                  sa.ForeignKey('mfg_floor_events.id', ondelete='SET NULL',
                                name='fk_mfg_floor_events_corrects_event_id_mfg_floor_events'), nullable=True),
        sa.Column('forced', sa.String(200), nullable=True),
        sa.Column('details', _json(), nullable=False),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_floor_events_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_floor_events_batch_load', 'mfg_floor_events', ['batch_load_id'])
    op.create_index('ix_mfg_floor_events_corrects', 'mfg_floor_events', ['corrects_event_id'])
    op.create_index('ix_mfg_floor_events_line_at', 'mfg_floor_events', ['line_id', 'event_at'])
    op.create_index('ix_mfg_floor_events_op_seq', 'mfg_floor_events', ['wo_operation_id', 'seq'])
    op.create_index('ix_mfg_floor_events_owner_at', 'mfg_floor_events', ['owner_id', 'event_at'])
    op.create_index('ix_mfg_floor_events_wo', 'mfg_floor_events', ['wo_id'])
    op.create_index('uq_mfg_floor_events_client', 'mfg_floor_events', ['owner_id', 'client_event_id'],
                    unique=True, postgresql_where=sa.text("client_event_id IS NOT NULL"))
    op.create_table(
        'mfg_downtime',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='RESTRICT',
                                name='fk_mfg_downtime_line_id_mfg_lines'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('planned', sa.Boolean(), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expected_end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.String(200), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('reported_by', sa.String(64), nullable=True),
        sa.Column('closed_by', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_downtime_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfg_downtime_line_start', 'mfg_downtime', ['line_id', 'start_at'])
    op.create_index('ix_mfg_downtime_owner_start', 'mfg_downtime', ['owner_id', 'start_at'])
    op.create_table(
        'mfg_unit_serials',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT',
                                name='fk_mfg_unit_serials_item_id_mfg_items'), nullable=False),
        sa.Column('serial', sa.String(64), nullable=False),
        sa.Column('wo_id', sa.String(64),
                  sa.ForeignKey('mfg_work_orders.id', ondelete='SET NULL',
                                name='fk_mfg_unit_serials_wo_id_mfg_work_orders'), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('captured_op_seq', sa.Integer(), nullable=True),
        sa.Column('parent_serial_id', sa.String(64),
                  sa.ForeignKey('mfg_unit_serials.id', ondelete='SET NULL',
                                name='fk_mfg_unit_serials_parent_serial_id_mfg_unit_serials'), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_wo_id', sa.String(64), nullable=True),
        sa.Column('event_id', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_unit_serials_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'item_id', 'serial', name='uq_mfg_unit_serials_key'),
    )
    op.create_index('ix_mfg_unit_serials_item_status', 'mfg_unit_serials', ['item_id', 'status'])
    op.create_index('ix_mfg_unit_serials_parent', 'mfg_unit_serials', ['parent_serial_id'])
    op.create_index('ix_mfg_unit_serials_wo', 'mfg_unit_serials', ['wo_id'])
    op.create_table(
        'mfg_replan_triggers',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('severity', sa.String(8), nullable=False),
        sa.Column('ref_type', sa.String(16), nullable=False),
        sa.Column('ref_id', sa.String(64), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dedupe_key', sa.String(200), nullable=False),
        sa.Column('details', _json(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('aps_run_id', sa.String(64), nullable=True),
        sa.Column('handled_by', sa.String(64), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_replan_triggers_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_replan_triggers_owner_status', 'mfg_replan_triggers', ['owner_id', 'status', 'detected_at'])
    op.create_index('uq_mfg_replan_triggers_open', 'mfg_replan_triggers', ['owner_id', 'dedupe_key'],
                    unique=True, postgresql_where=sa.text("status IN ('open', 'attached')"))
    op.create_table(
        'mfg_notifications',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('severity', sa.String(8), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.String(1000), nullable=False),
        sa.Column('link', sa.String(300), nullable=False),
        sa.Column('trigger_id', sa.String(64),
                  sa.ForeignKey('mfg_replan_triggers.id', ondelete='SET NULL',
                                name='fk_mfg_notifications_trigger_id_mfg_replan_triggers'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_notifications_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_notifications_owner_created', 'mfg_notifications', ['owner_id', 'created_at'])
    op.create_index('ix_mfg_notifications_trigger', 'mfg_notifications', ['trigger_id'])
    op.create_table(
        'mfg_aps_simulations',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('base_run_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('samples', sa.Integer(), nullable=False),
        sa.Column('params', _json(), nullable=False),
        sa.Column('results', _json(), nullable=True),
        sa.Column('error', _json(), nullable=True),
        sa.Column('job_id', sa.String(64), nullable=True),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_aps_simulations_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfg_aps_simulations_owner_created', 'mfg_aps_simulations', ['owner_id', 'created_at'])
    op.create_index('uq_mfg_aps_simulations_active', 'mfg_aps_simulations', ['owner_id'],
                    unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_table(
        'mfg_kpi_daily',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('metric', sa.String(32), nullable=False),
        sa.Column('dim_type', sa.String(8), nullable=False),
        sa.Column('dim_id', sa.String(64), nullable=False),
        sa.Column('num', sa.Double(), nullable=False),
        sa.Column('den', sa.Double(), nullable=False),
        sa.Column('value', sa.Double(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_kpi_daily_owner_id_users'), nullable=False),
        sa.UniqueConstraint('owner_id', 'day', 'metric', 'dim_type', 'dim_id', name='uq_mfg_kpi_daily_key'),
    )

    _jobs_up()
    op.execute(_MIGRATE_PROGRESS)
    op.execute(_MIGRATE_EVENTS)
    op.execute(_EVENT_CURSOR)
    op.drop_table("mfg_wo_op_progress")


def downgrade() -> None:
    _progress_table()
    op.execute(_PROGRESS_BACK)
    _jobs_down()
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_column("mfg_aps_ops", "actual")
    _columns_down()
