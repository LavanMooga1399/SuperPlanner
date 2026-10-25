"""M1 manufacturing master data: the 18 `mfg_*` tables (M1-DESIGN 6.2, review R7).

Revision ID: 0003_mfg
Revises: 0002_phase2b
Create Date: 2026-10-25

Frozen migration: literal definitions only, never import the ORM models. Only creates tables (no batch rebuild of
existing tables), in FK order; `downgrade()` drops exactly these tables in reverse order. Every table is owned
(`owner_id` -> users.id RESTRICT). No server defaults (the ORM sets every value).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_mfg"
down_revision = "0002_phase2b"
branch_labels = None
depends_on = None

TABLES = ("mfg_plant", "mfg_items", "mfg_groups", "mfg_skills", "mfg_tool_pools", "mfg_shift_templates",
          "mfg_lines", "mfg_line_items", "mfg_boms", "mfg_bom_lines", "mfg_routings", "mfg_operations",
          "mfg_operation_tools", "mfg_shift_assignments", "mfg_calendar_exceptions", "mfg_operators",
          "mfg_operator_skills", "mfg_imports")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        'mfg_plant',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('utc_offset', sa.String(6), nullable=False),
        sa.Column('planning_horizon_days', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('attributes', _json(), nullable=False),
        sa.Column('data_version', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_plant_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', name='uq_mfg_plant_owner'),
    )
    op.create_table(
        'mfg_items',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('part_number', sa.String(64), nullable=False),
        sa.Column('revision', sa.String(16), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('uom', sa.String(8), nullable=False),
        sa.Column('make_buy', sa.String(8), nullable=False),
        sa.Column('family', sa.String(32), nullable=True),
        sa.Column('setup_family', sa.String(32), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('receiving_days', sa.Integer(), nullable=False),
        sa.Column('lot_rule', sa.String(16), nullable=False),
        sa.Column('fixed_lot_qty', sa.Double(), nullable=True),
        sa.Column('min_order_qty', sa.Double(), nullable=False),
        sa.Column('order_multiple', sa.Double(), nullable=False),
        sa.Column('safety_stock', sa.Double(), nullable=False),
        sa.Column('serialized', sa.Boolean(), nullable=False),
        sa.Column('shelf_life_days', sa.Integer(), nullable=True),
        sa.Column('handling_class', sa.String(32), nullable=True),
        sa.Column('handling_note', sa.String(500), nullable=False),
        sa.Column('attributes', _json(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_items_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'part_number', name='uq_mfg_items_owner_pn'),
    )
    op.create_index('ix_mfg_items_owner_family', 'mfg_items', ['owner_id', 'family'])
    op.create_index('ix_mfg_items_owner_updated', 'mfg_items', ['owner_id', 'updated_at', 'id'])
    op.create_table(
        'mfg_groups',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('kind', sa.String(32), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_groups_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_groups_code'),
    )
    op.create_table(
        'mfg_skills',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_skills_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_skills_code'),
    )
    op.create_table(
        'mfg_tool_pools',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('kind', sa.String(32), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_tool_pools_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_tool_pools_code'),
    )
    op.create_table(
        'mfg_shift_templates',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('shifts', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_shift_templates_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_shift_templates_code'),
    )
    op.create_table(
        'mfg_lines',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('group_id', sa.String(64),
                  sa.ForeignKey('mfg_groups.id', ondelete='RESTRICT', name='fk_mfg_lines_group_id_mfg_groups'),
                  nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('speed_factor', sa.Double(), nullable=False),
        sa.Column('parallel_capacity', sa.Integer(), nullable=False),
        sa.Column('setup_family', sa.String(32), nullable=True),
        sa.Column('eligible_families', _json(), nullable=False),
        sa.Column('cost_per_hour', sa.Double(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_lines_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_lines_code'),
    )
    op.create_index('ix_mfg_lines_group', 'mfg_lines', ['group_id'])
    op.create_table(
        'mfg_line_items',
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='CASCADE', name='fk_mfg_line_items_line_id_mfg_lines'),
                  nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='CASCADE', name='fk_mfg_line_items_item_id_mfg_items'),
                  nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_line_items_owner_id_users'),
                  nullable=False),
        sa.PrimaryKeyConstraint('line_id', 'item_id'),
    )
    op.create_index('ix_mfg_line_items_item', 'mfg_line_items', ['item_id'])
    op.create_index('ix_mfg_line_items_owner', 'mfg_line_items', ['owner_id'])
    op.create_table(
        'mfg_boms',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_boms_item_id_mfg_items'),
                  nullable=False),
        sa.Column('revision', sa.String(16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('serial_from', sa.BigInteger(), nullable=True),
        sa.Column('serial_to', sa.BigInteger(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('obsoleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_boms_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'item_id', 'revision', 'version', name='uq_mfg_boms_key'),
    )
    op.create_index('ix_mfg_boms_item_status', 'mfg_boms', ['item_id', 'status'])
    op.create_table(
        'mfg_bom_lines',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('bom_id', sa.String(64),
                  sa.ForeignKey('mfg_boms.id', ondelete='CASCADE', name='fk_mfg_bom_lines_bom_id_mfg_boms'),
                  nullable=False),
        sa.Column('find_number', sa.String(16), nullable=False),
        sa.Column('child_item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_bom_lines_child_item_id_mfg_items'),
                  nullable=False),
        sa.Column('qty_per', sa.Double(), nullable=False),
        sa.Column('uom', sa.String(8), nullable=False),
        sa.Column('scrap_pct', sa.Double(), nullable=False),
        sa.Column('ref_designators', sa.String(4000), nullable=False),
        sa.Column('alt_group', sa.String(16), nullable=True),
        sa.Column('alt_priority', sa.Integer(), nullable=False),
        sa.Column('operation_seq', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_bom_lines_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('bom_id', 'find_number', 'child_item_id', name='uq_mfg_bom_lines_key'),
    )
    op.create_index('ix_mfg_bom_lines_child', 'mfg_bom_lines', ['child_item_id'])
    op.create_index('ix_mfg_bom_lines_owner', 'mfg_bom_lines', ['owner_id'])
    op.create_table(
        'mfg_routings',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_routings_item_id_mfg_items'),
                  nullable=False),
        sa.Column('revision', sa.String(16), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('serial_from', sa.BigInteger(), nullable=True),
        sa.Column('serial_to', sa.BigInteger(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('obsoleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_routings_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'item_id', 'revision', 'code', 'version', name='uq_mfg_routings_key'),
    )
    op.create_index('ix_mfg_routings_item_status', 'mfg_routings', ['item_id', 'status'])
    op.create_table(
        'mfg_operations',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('routing_id', sa.String(64),
                  sa.ForeignKey('mfg_routings.id', ondelete='CASCADE',
                                name='fk_mfg_operations_routing_id_mfg_routings'),
                  nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('group_id', sa.String(64),
                  sa.ForeignKey('mfg_groups.id', ondelete='RESTRICT', name='fk_mfg_operations_group_id_mfg_groups'),
                  nullable=False),
        sa.Column('setup_minutes', sa.Double(), nullable=False),
        sa.Column('run_minutes', sa.Double(), nullable=False),
        sa.Column('run_per', sa.String(8), nullable=False),
        sa.Column('units_per_panel', sa.Integer(), nullable=True),
        sa.Column('units_per_batch', sa.Integer(), nullable=True),
        sa.Column('queue_minutes', sa.Double(), nullable=False),
        sa.Column('move_minutes', sa.Double(), nullable=False),
        sa.Column('wait_minutes', sa.Double(), nullable=False),
        sa.Column('labor', sa.String(16), nullable=False),
        sa.Column('crew_size', sa.Integer(), nullable=False),
        sa.Column('skill_id', sa.String(64),
                  sa.ForeignKey('mfg_skills.id', ondelete='RESTRICT', name='fk_mfg_operations_skill_id_mfg_skills'),
                  nullable=True),
        sa.Column('transfer_batch', sa.Integer(), nullable=True),
        sa.Column('yield_pct', sa.Double(), nullable=False),
        sa.Column('inspection_gate', sa.Boolean(), nullable=False),
        sa.Column('interruptible', sa.Boolean(), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_operations_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('routing_id', 'seq', name='uq_mfg_operations_seq'),
    )
    op.create_index('ix_mfg_operations_group', 'mfg_operations', ['group_id'])
    op.create_index('ix_mfg_operations_owner', 'mfg_operations', ['owner_id'])
    op.create_index('ix_mfg_operations_skill', 'mfg_operations', ['skill_id'])
    op.create_table(
        'mfg_operation_tools',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('operation_id', sa.String(64),
                  sa.ForeignKey('mfg_operations.id', ondelete='CASCADE',
                                name='fk_mfg_operation_tools_operation_id_mfg_operations'),
                  nullable=False),
        sa.Column('tool_pool_id', sa.String(64),
                  sa.ForeignKey('mfg_tool_pools.id', ondelete='RESTRICT',
                                name='fk_mfg_operation_tools_tool_pool_id_mfg_tool_pools'),
                  nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_operation_tools_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('operation_id', 'tool_pool_id', name='uq_mfg_operation_tools'),
    )
    op.create_index('ix_mfg_operation_tools_owner', 'mfg_operation_tools', ['owner_id'])
    op.create_index('ix_mfg_operation_tools_pool', 'mfg_operation_tools', ['tool_pool_id'])
    op.create_table(
        'mfg_shift_assignments',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('shift_template_id', sa.String(64),
                  sa.ForeignKey('mfg_shift_templates.id', ondelete='RESTRICT',
                                name='fk_mfg_shift_assignments_shift_template_id_mfg_shift_templates'),
                  nullable=False),
        sa.Column('target_type', sa.String(8), nullable=False),
        sa.Column('group_id', sa.String(64),
                  sa.ForeignKey('mfg_groups.id', ondelete='CASCADE',
                                name='fk_mfg_shift_assignments_group_id_mfg_groups'),
                  nullable=True),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='CASCADE', name='fk_mfg_shift_assignments_line_id_mfg_lines'),
                  nullable=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('shift_names', _json(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('cost_per_hour', sa.Double(), nullable=True),
        sa.Column('max_hours_per_week', sa.Double(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_shift_assignments_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('(group_id IS NULL) <> (line_id IS NULL)', name='ck_mfg_shift_assignments_target'),
    )
    op.create_index('ix_mfg_shift_assignments_group', 'mfg_shift_assignments', ['group_id'])
    op.create_index('ix_mfg_shift_assignments_line', 'mfg_shift_assignments', ['line_id'])
    op.create_index('ix_mfg_shift_assignments_owner', 'mfg_shift_assignments', ['owner_id'])
    op.create_index('ix_mfg_shift_assignments_template', 'mfg_shift_assignments', ['shift_template_id'])
    op.create_table(
        'mfg_calendar_exceptions',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('scope', sa.String(8), nullable=False),
        sa.Column('group_id', sa.String(64),
                  sa.ForeignKey('mfg_groups.id', ondelete='CASCADE',
                                name='fk_mfg_calendar_exceptions_group_id_mfg_groups'),
                  nullable=True),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_lines.id', ondelete='CASCADE',
                                name='fk_mfg_calendar_exceptions_line_id_mfg_lines'),
                  nullable=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_calendar_exceptions_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfg_calendar_exceptions_group', 'mfg_calendar_exceptions', ['group_id'])
    op.create_index('ix_mfg_calendar_exceptions_line', 'mfg_calendar_exceptions', ['line_id'])
    op.create_index('ix_mfg_calendar_exceptions_owner_start', 'mfg_calendar_exceptions', ['owner_id', 'start_at'])
    op.create_table(
        'mfg_operators',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('shift_template_id', sa.String(64),
                  sa.ForeignKey('mfg_shift_templates.id', ondelete='RESTRICT',
                                name='fk_mfg_operators_shift_template_id_mfg_shift_templates'),
                  nullable=True),
        sa.Column('shift_names', _json(), nullable=False),
        sa.Column('home_group_id', sa.String(64),
                  sa.ForeignKey('mfg_groups.id', ondelete='SET NULL', name='fk_mfg_operators_home_group_id_mfg_groups'),
                  nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_operators_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_operators_code'),
    )
    op.create_index('ix_mfg_operators_home_group', 'mfg_operators', ['home_group_id'])
    op.create_index('ix_mfg_operators_template', 'mfg_operators', ['shift_template_id'])
    op.create_table(
        'mfg_operator_skills',
        sa.Column('operator_id', sa.String(64),
                  sa.ForeignKey('mfg_operators.id', ondelete='CASCADE',
                                name='fk_mfg_operator_skills_operator_id_mfg_operators'),
                  nullable=False),
        sa.Column('skill_id', sa.String(64),
                  sa.ForeignKey('mfg_skills.id', ondelete='CASCADE', name='fk_mfg_operator_skills_skill_id_mfg_skills'),
                  nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_operator_skills_owner_id_users'),
                  nullable=False),
        sa.PrimaryKeyConstraint('operator_id', 'skill_id'),
    )
    op.create_index('ix_mfg_operator_skills_owner', 'mfg_operator_skills', ['owner_id'])
    op.create_index('ix_mfg_operator_skills_skill', 'mfg_operator_skills', ['skill_id'])
    op.create_table(
        'mfg_imports',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('format', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('sheets', _json(), nullable=False),
        sa.Column('mapping', _json(), nullable=True),
        sa.Column('preview', _json(), nullable=True),
        sa.Column('result', _json(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_imports_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfg_imports_expires', 'mfg_imports', ['expires_at'])
    op.create_index('ix_mfg_imports_owner_created', 'mfg_imports', ['owner_id', 'created_at'])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
