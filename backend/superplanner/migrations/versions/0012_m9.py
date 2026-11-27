"""M9 network, S&OP/IBP and sourcing (M9-DESIGN 3): network lanes, sourcing rules, ramp curves, network runs with
transfers / production / shortages / projection, S&OP cycles, demand rows and overrides, scenarios, MPS targets, item
trade data, tariff / FX / milestone / country-risk tables and tariff reports; columns on mfg_plant (kind),
mfg_item_suppliers (coo, hts_code, incoterm, freight_per_unit, cap_per_month), mfg_lots (coo, coo_source,
unit_value, domestic shares), mfg_transfer_orders (source, net_run_id). The job kinds `net_run`, `net_publish`, `sop_scenario_run`, `sop_publish`, `content_rollup`, `tariff_report`
target `maintenance_runs` (existing column): the job check is unchanged.

Revision ID: 0012_m9
Revises: 0011_m8
Create Date: 2026-11-27

Policy: expand. Frozen migration: literal definitions only. Additive only; NOT NULL columns on existing tables are
added with a server default (backfill) that is dropped right after (no server defaults, M4 3.1). Downgrade: network
transfer orders become manual (the column goes), `sop_cycle` signatures and policies are deleted (as M8 review 11),
the new kinds' jobs are deleted and everything added is dropped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_m9"
down_revision = "0011_m8"
branch_labels = None
depends_on = None
policy = "expand"

TABLES = ('mfg_country_risk', 'mfg_fx_rates', 'mfg_mps_targets', 'mfg_net_lanes', 'mfg_net_ramp_curves', 'mfg_net_runs', 'mfg_sop_cycles', 'mfg_tariff_milestones', 'mfg_tariff_rates', 'mfg_tariff_reports', 'mfg_item_trade', 'mfg_net_production', 'mfg_net_projection', 'mfg_net_shortages', 'mfg_net_sourcing', 'mfg_net_transfers', 'mfg_sop_demand', 'mfg_sop_demand_overrides', 'mfg_sop_scenarios')
KINDS = ('net_run', 'net_publish', 'sop_scenario_run', 'sop_publish', 'content_rollup', 'tariff_report')
COLUMNS = (('mfg_item_suppliers', 'coo'), ('mfg_item_suppliers', 'hts_code'), ('mfg_item_suppliers', 'incoterm'), ('mfg_item_suppliers', 'freight_per_unit'), ('mfg_item_suppliers', 'cap_per_month'), ('mfg_lots', 'coo'), ('mfg_lots', 'coo_source'), ('mfg_lots', 'unit_value'), ('mfg_lots', 'dom_share_value'), ('mfg_lots', 'dom_share_weight'), ('mfg_lots', 'dom_estimated'), ('mfg_lots', 'dom_computed_at'), ('mfg_plant', 'kind'), ('mfg_transfer_orders', 'source'), ('mfg_transfer_orders', 'net_run_id'))


def _columns() -> None:
    op.add_column('mfg_item_suppliers', sa.Column('coo', sa.String(length=2), nullable=True))
    op.add_column('mfg_item_suppliers', sa.Column('hts_code', sa.String(length=10), nullable=True))
    op.add_column('mfg_item_suppliers', sa.Column('incoterm', sa.String(length=3), nullable=True))
    op.add_column('mfg_item_suppliers', sa.Column('freight_per_unit', sa.Double(), nullable=True))
    op.add_column('mfg_item_suppliers', sa.Column('cap_per_month', sa.Double(), nullable=True))
    op.add_column('mfg_lots', sa.Column('coo', sa.String(length=2), nullable=True))
    op.add_column('mfg_lots', sa.Column('coo_source', sa.String(length=8), nullable=True))
    op.add_column('mfg_lots', sa.Column('unit_value', sa.Double(), nullable=True))
    op.add_column('mfg_lots', sa.Column('dom_share_value', sa.Double(), nullable=True))
    op.add_column('mfg_lots', sa.Column('dom_share_weight', sa.Double(), nullable=True))
    op.add_column('mfg_lots', sa.Column('dom_estimated', sa.Boolean(), nullable=True))
    op.add_column('mfg_lots', sa.Column('dom_computed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mfg_plant', sa.Column('kind', sa.String(length=8), nullable=False, server_default=sa.text("'plant'")))
    op.alter_column('mfg_plant', 'kind', server_default=None)
    op.add_column('mfg_transfer_orders', sa.Column('source', sa.String(length=8), nullable=False, server_default=sa.text("'manual'")))
    op.alter_column('mfg_transfer_orders', 'source', server_default=None)
    op.add_column('mfg_transfer_orders', sa.Column('net_run_id', sa.String(length=64), nullable=True))


def _tables() -> None:
    op.create_table('mfg_country_risk',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_country_risk_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'country', name='uq_mfg_country_risk_country')
    )
    op.create_table('mfg_fx_rates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('from_ccy', sa.String(length=3), nullable=False),
    sa.Column('to_ccy', sa.String(length=3), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('rate', sa.Double(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_fx_rates_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'from_ccy', 'to_ccy', 'month', name='uq_mfg_fx_rates_key')
    )
    op.create_table('mfg_mps_targets',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('cycle_id', sa.String(length=64), nullable=False),
    sa.Column('cycle_number', sa.String(length=32), nullable=True),
    sa.Column('family', sa.String(length=32), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('qty_target', sa.Double(), nullable=False),
    sa.Column('hours', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_mps_targets_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'family', 'month', name='uq_mfg_mps_targets_key')
    )
    op.create_table('mfg_net_lanes',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('from_owner_id', sa.String(length=64), nullable=False),
    sa.Column('to_owner_id', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('transit_days', sa.Integer(), nullable=False),
    sa.Column('freight_per_unit', sa.Double(), nullable=False),
    sa.Column('freight_per_kg', sa.Double(), nullable=True),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_lanes_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'from_owner_id', 'to_owner_id', 'mode', name='uq_mfg_net_lanes_key')
    )
    op.create_table('mfg_net_ramp_curves',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('points', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_ramp_curves_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_net_ramp_curves_code')
    )
    op.create_table('mfg_net_runs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=True),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('validator', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('explanations', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('published', sa.Boolean(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by', sa.String(length=64), nullable=True),
    sa.Column('publish_result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error', sa.String(length=2000), nullable=True),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_runs_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_net_runs_number')
    )
    op.create_index('ix_mfg_net_runs_owner', 'mfg_net_runs', ['owner_id', 'created_at'], unique=False)
    op.create_table('mfg_sop_cycles',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('period', sa.Date(), nullable=False),
    sa.Column('horizon_months', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('steps', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('demand_sources', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('recommended_scenario_id', sa.String(length=64), nullable=True),
    sa.Column('recommend_note', sa.String(length=2000), nullable=True),
    sa.Column('approved_scenario_id', sa.String(length=64), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('publish_result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('reopen_reason', sa.String(length=500), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_sop_cycles_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_sop_cycles_number')
    )
    op.create_index('ix_mfg_sop_cycles_owner', 'mfg_sop_cycles', ['owner_id', 'period'], unique=False)
    op.create_table('mfg_tariff_milestones',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('dest_country', sa.String(length=2), nullable=False),
    sa.Column('family', sa.String(length=32), nullable=True),
    sa.Column('hts_prefix', sa.String(length=10), nullable=True),
    sa.Column('rule', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('effective', sa.Date(), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_tariff_milestones_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_tariff_milestones_code')
    )
    op.create_table('mfg_tariff_rates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('dest_country', sa.String(length=2), nullable=False),
    sa.Column('hts_prefix', sa.String(length=10), nullable=False),
    sa.Column('coo', sa.String(length=2), nullable=False),
    sa.Column('layer', sa.String(length=16), nullable=False),
    sa.Column('rate_pct', sa.Double(), nullable=False),
    sa.Column('per_unit', sa.Double(), nullable=True),
    sa.Column('per_unit_currency', sa.String(length=8), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_tariff_rates_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'dest_country', 'hts_prefix', 'coo', 'layer', 'valid_from', name='uq_mfg_tariff_rates_key')
    )
    op.create_table('mfg_tariff_reports',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error', sa.String(length=2000), nullable=True),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_tariff_reports_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_tariff_reports_number')
    )
    op.create_table('mfg_item_trade',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('item_id', sa.String(length=64), nullable=False),
    sa.Column('hts_code', sa.String(length=10), nullable=True),
    sa.Column('coo', sa.String(length=2), nullable=True),
    sa.Column('material_class', sa.String(length=16), nullable=True),
    sa.Column('unit_weight_kg', sa.Double(), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['mfg_items.id'], name=op.f('fk_mfg_item_trade_item_id_mfg_items'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_item_trade_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('item_id', name='uq_mfg_item_trade_item')
    )
    op.create_index('ix_mfg_item_trade_owner', 'mfg_item_trade', ['owner_id'], unique=False)
    op.create_table('mfg_net_production',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('node_owner_id', sa.String(length=64), nullable=False),
    sa.Column('item_key', sa.String(length=64), nullable=False),
    sa.Column('week', sa.Date(), nullable=False),
    sa.Column('qty', sa.Double(), nullable=False),
    sa.Column('kind', sa.String(length=4), nullable=False),
    sa.Column('cap_group', sa.String(length=32), nullable=True),
    sa.Column('hours', sa.Double(), nullable=False),
    sa.Column('prebuilt_from', sa.Date(), nullable=True),
    sa.Column('pegs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_production_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['mfg_net_runs.id'], name=op.f('fk_mfg_net_production_run_id_mfg_net_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mfg_net_production_owner', 'mfg_net_production', ['owner_id'], unique=False)
    op.create_index('ix_mfg_net_production_run', 'mfg_net_production', ['run_id', 'node_owner_id', 'item_key'], unique=False)
    op.create_table('mfg_net_projection',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('node_owner_id', sa.String(length=64), nullable=False),
    sa.Column('item_key', sa.String(length=64), nullable=False),
    sa.Column('week', sa.Date(), nullable=False),
    sa.Column('gross', sa.Double(), nullable=False),
    sa.Column('receipts', sa.Double(), nullable=False),
    sa.Column('planned_in', sa.Double(), nullable=False),
    sa.Column('planned_out', sa.Double(), nullable=False),
    sa.Column('projected', sa.Double(), nullable=False),
    sa.Column('ss', sa.Double(), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_projection_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['mfg_net_runs.id'], name=op.f('fk_mfg_net_projection_run_id_mfg_net_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'node_owner_id', 'item_key', 'week', name='uq_mfg_net_projection_key')
    )
    op.create_index('ix_mfg_net_projection_owner', 'mfg_net_projection', ['owner_id'], unique=False)
    op.create_table('mfg_net_shortages',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('node_owner_id', sa.String(length=64), nullable=False),
    sa.Column('item_key', sa.String(length=64), nullable=False),
    sa.Column('week', sa.Date(), nullable=False),
    sa.Column('qty', sa.Double(), nullable=False),
    sa.Column('cause', sa.String(length=24), nullable=False),
    sa.Column('detail', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_shortages_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['mfg_net_runs.id'], name=op.f('fk_mfg_net_shortages_run_id_mfg_net_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mfg_net_shortages_owner', 'mfg_net_shortages', ['owner_id'], unique=False)
    op.create_index('ix_mfg_net_shortages_run', 'mfg_net_shortages', ['run_id', 'node_owner_id'], unique=False)
    op.create_table('mfg_net_sourcing',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('dest_owner_id', sa.String(length=64), nullable=False),
    sa.Column('item_key', sa.String(length=64), nullable=True),
    sa.Column('family', sa.String(length=32), nullable=True),
    sa.Column('source_kind', sa.String(length=8), nullable=False),
    sa.Column('source_owner_id', sa.String(length=64), nullable=True),
    sa.Column('supplier_code', sa.String(length=32), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('quota_pct', sa.Double(), nullable=True),
    sa.Column('lane_id', sa.String(length=64), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lane_id'], ['mfg_net_lanes.id'], name=op.f('fk_mfg_net_sourcing_lane_id_mfg_net_lanes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_sourcing_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mfg_net_sourcing_lane', 'mfg_net_sourcing', ['lane_id'], unique=False)
    op.create_index('ix_mfg_net_sourcing_owner', 'mfg_net_sourcing', ['owner_id', 'dest_owner_id'], unique=False)
    op.create_table('mfg_net_transfers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('src_owner_id', sa.String(length=64), nullable=False),
    sa.Column('dst_owner_id', sa.String(length=64), nullable=False),
    sa.Column('item_key', sa.String(length=64), nullable=False),
    sa.Column('lane_id', sa.String(length=64), nullable=True),
    sa.Column('ship_date', sa.Date(), nullable=False),
    sa.Column('receive_date', sa.Date(), nullable=False),
    sa.Column('qty', sa.Double(), nullable=False),
    sa.Column('firm', sa.Boolean(), nullable=False),
    sa.Column('to_id', sa.String(length=64), nullable=True),
    sa.Column('pegs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_net_transfers_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['mfg_net_runs.id'], name=op.f('fk_mfg_net_transfers_run_id_mfg_net_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mfg_net_transfers_owner', 'mfg_net_transfers', ['owner_id'], unique=False)
    op.create_index('ix_mfg_net_transfers_run', 'mfg_net_transfers', ['run_id', 'dst_owner_id', 'item_key'], unique=False)
    op.create_table('mfg_sop_demand',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('cycle_id', sa.String(length=64), nullable=False),
    sa.Column('node_owner_id', sa.String(length=64), nullable=False),
    sa.Column('family', sa.String(length=32), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('stat_qty', sa.Double(), nullable=False),
    sa.Column('order_qty', sa.Double(), nullable=False),
    sa.Column('base_qty', sa.Double(), nullable=False),
    sa.Column('prior_consensus', sa.Double(), nullable=True),
    sa.Column('consensus_qty', sa.Double(), nullable=False),
    sa.Column('asp', sa.Double(), nullable=True),
    sa.Column('asp_currency', sa.String(length=8), nullable=False),
    sa.Column('asp_source', sa.String(length=8), nullable=False),
    sa.Column('items', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['cycle_id'], ['mfg_sop_cycles.id'], name=op.f('fk_mfg_sop_demand_cycle_id_mfg_sop_cycles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_sop_demand_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cycle_id', 'node_owner_id', 'family', 'month', name='uq_mfg_sop_demand_key')
    )
    op.create_index('ix_mfg_sop_demand_owner', 'mfg_sop_demand', ['owner_id'], unique=False)
    op.create_table('mfg_sop_demand_overrides',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('cycle_id', sa.String(length=64), nullable=False),
    sa.Column('node_owner_id', sa.String(length=64), nullable=True),
    sa.Column('family', sa.String(length=32), nullable=False),
    sa.Column('month_from', sa.Date(), nullable=False),
    sa.Column('month_to', sa.Date(), nullable=False),
    sa.Column('mode', sa.String(length=4), nullable=False),
    sa.Column('value', sa.Double(), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['cycle_id'], ['mfg_sop_cycles.id'], name=op.f('fk_mfg_sop_demand_overrides_cycle_id_mfg_sop_cycles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_sop_demand_overrides_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mfg_sop_demand_overrides_cycle', 'mfg_sop_demand_overrides', ['cycle_id', 'seq'], unique=False)
    op.create_index('ix_mfg_sop_demand_overrides_owner', 'mfg_sop_demand_overrides', ['owner_id'], unique=False)
    op.create_table('mfg_sop_scenarios',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('cycle_id', sa.String(length=64), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('baseline', sa.Boolean(), nullable=False),
    sa.Column('changes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('capex_note', sa.String(length=2000), nullable=False),
    sa.Column('enforce_milestones', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=True),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('kpis', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('validator', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('warnings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error', sa.String(length=2000), nullable=True),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cycle_id'], ['mfg_sop_cycles.id'], name=op.f('fk_mfg_sop_scenarios_cycle_id_mfg_sop_cycles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mfg_sop_scenarios_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_sop_scenarios_number')
    )
    op.create_index('ix_mfg_sop_scenarios_cycle', 'mfg_sop_scenarios', ['cycle_id'], unique=False)


def upgrade() -> None:
    _columns()
    _tables()


def downgrade() -> None:
    op.execute("DELETE FROM esig_signatures WHERE record_type = 'sop_cycle'")
    op.execute("DELETE FROM esig_policies WHERE record_type = 'sop_cycle'")
    op.execute("DELETE FROM jobs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    op.execute("DELETE FROM maintenance_runs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    for table in reversed(TABLES):
        op.drop_table(table)
    for table, column in reversed(COLUMNS):
        op.drop_column(table, column)
