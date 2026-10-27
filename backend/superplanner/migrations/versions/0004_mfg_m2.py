"""M2 inventory, purchasing, demand, MRP, work orders and workspaces: 22 new tables, 9 new columns on `mfg_items`
and `mfg_plant` (M2-DESIGN 9).

Revision ID: 0004_mfg_m2
Revises: 0003_mfg
Create Date: 2026-10-27

Frozen migration: literal definitions only, never import the ORM models. New NOT NULL columns on existing tables are
added with a server default that is dropped again in the same migration (no server defaults remain, M1 rule).
Tables are created in FK order; `downgrade()` drops exactly these tables in reverse order and the added columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_mfg_m2"
down_revision = "0003_mfg"
branch_labels = None
depends_on = None

TABLES = ("mfg_locations", "mfg_suppliers", "mfg_item_suppliers", "mfg_lots", "mfg_purchase_docs",
          "mfg_purchase_lines", "mfg_purchase_schedules", "mfg_demand_orders", "mfg_demand_lines", "mfg_work_orders",
          "mfg_wo_components", "mfg_inv_balances", "mfg_inv_reservations", "mfg_inv_postings", "mfg_inv_transactions",
          "mfg_number_series", "mfg_mrp_runs", "mfg_mrp_planned_orders", "mfg_mrp_exceptions", "mfg_mrp_item_results",
          "mfg_mrp_demand_results", "mfg_plant_members")
ITEM_COLUMNS = ("external_ref", "standard_cost", "lot_controlled", "lot_period_days")
PLANT_COLUMNS = ("mrp_workdays", "mrp_day_minutes", "mrp_defer_tolerance_days", "mrp_release_window_days",
                 "over_receipt_pct")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _columns() -> None:
    op.add_column("mfg_items", sa.Column("external_ref", sa.String(64), nullable=True))
    op.add_column("mfg_items", sa.Column("standard_cost", sa.Double(), nullable=True))
    op.add_column("mfg_items", sa.Column("lot_controlled", sa.Boolean(), nullable=False,
                                         server_default=sa.text("false")))
    op.add_column("mfg_items", sa.Column("lot_period_days", sa.Integer(), nullable=True))
    op.alter_column("mfg_items", "lot_controlled", server_default=None)
    op.create_index("uq_mfg_items_owner_extref", "mfg_items", ["owner_id", "external_ref"], unique=True,
                    postgresql_where=sa.text("external_ref IS NOT NULL"))
    op.add_column("mfg_plant", sa.Column("mrp_workdays", _json(), nullable=False,
                                         server_default=sa.text("""'["mon","tue","wed","thu","fri","sat"]'""")))
    op.add_column("mfg_plant", sa.Column("mrp_day_minutes", sa.Double(), nullable=False,
                                         server_default=sa.text("480")))
    op.add_column("mfg_plant", sa.Column("mrp_defer_tolerance_days", sa.Integer(), nullable=False,
                                         server_default=sa.text("7")))
    op.add_column("mfg_plant", sa.Column("mrp_release_window_days", sa.Integer(), nullable=False,
                                         server_default=sa.text("7")))
    op.add_column("mfg_plant", sa.Column("over_receipt_pct", sa.Double(), nullable=False,
                                         server_default=sa.text("0")))
    for col in PLANT_COLUMNS:
        op.alter_column("mfg_plant", col, server_default=None)


def upgrade() -> None:
    _columns()
    op.create_table(
        'mfg_locations',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('receipt_default', sa.Boolean(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_locations_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_locations_code'),
    )
    op.create_index('uq_mfg_locations_extref', 'mfg_locations', ['owner_id', 'external_ref'],
                    unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"))
    op.create_table(
        'mfg_suppliers',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('contact_name', sa.String(200), nullable=False),
        sa.Column('email', sa.String(200), nullable=False),
        sa.Column('phone', sa.String(50), nullable=False),
        sa.Column('address', sa.String(500), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_suppliers_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'code', name='uq_mfg_suppliers_code'),
    )
    op.create_index('uq_mfg_suppliers_extref', 'mfg_suppliers', ['owner_id', 'external_ref'],
                    unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"))
    op.create_table(
        'mfg_item_suppliers',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='CASCADE', name='fk_mfg_item_suppliers_item_id_mfg_items'),
                  nullable=False),
        sa.Column('supplier_id', sa.String(64),
                  sa.ForeignKey('mfg_suppliers.id', ondelete='CASCADE',
                                name='fk_mfg_item_suppliers_supplier_id_mfg_suppliers'),
                  nullable=False),
        sa.Column('supplier_part_number', sa.String(64), nullable=False),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('min_order_qty', sa.Double(), nullable=False),
        sa.Column('order_multiple', sa.Double(), nullable=False),
        sa.Column('purchase_unit', sa.String(32), nullable=True),
        sa.Column('units_per_purchase_unit', sa.Double(), nullable=False),
        sa.Column('unit_price', sa.Double(), nullable=True),
        sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('preferred', sa.Boolean(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_item_suppliers_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'item_id', 'supplier_id', name='uq_mfg_item_suppliers_key'),
    )
    op.create_index('ix_mfg_item_suppliers_item', 'mfg_item_suppliers', ['item_id'])
    op.create_index('ix_mfg_item_suppliers_supplier', 'mfg_item_suppliers', ['supplier_id'])
    op.create_table(
        'mfg_lots',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_lots_item_id_mfg_items'),
                  nullable=False),
        sa.Column('lot_code', sa.String(64), nullable=False),
        sa.Column('expires_on', sa.Date(), nullable=True),
        sa.Column('received_on', sa.Date(), nullable=True),
        sa.Column('supplier_lot', sa.String(64), nullable=False),
        sa.Column('hold', sa.Boolean(), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_lots_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'item_id', 'lot_code', name='uq_mfg_lots_key'),
    )
    op.create_index('ix_mfg_lots_item', 'mfg_lots', ['item_id'])
    op.create_index('ix_mfg_lots_owner_expires', 'mfg_lots', ['owner_id', 'expires_on'])
    op.create_table(
        'mfg_purchase_docs',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('doc_type', sa.String(2), nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('supplier_id', sa.String(64),
                  sa.ForeignKey('mfg_suppliers.id', ondelete='RESTRICT',
                                name='fk_mfg_purchase_docs_supplier_id_mfg_suppliers'),
                  nullable=True),
        sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('order_date', sa.Date(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('source', sa.String(8), nullable=False),
        sa.Column('source_run_no', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_by', sa.String(64), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(64), nullable=True),
        sa.Column('rejected_reason', sa.String(500), nullable=False),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_purchase_docs_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'doc_type', 'number', name='uq_mfg_purchase_docs_number'),
    )
    op.create_index('ix_mfg_purchase_docs_owner_status', 'mfg_purchase_docs', ['owner_id', 'doc_type', 'status'])
    op.create_index('ix_mfg_purchase_docs_supplier', 'mfg_purchase_docs', ['supplier_id'])
    op.create_index('uq_mfg_purchase_docs_extref', 'mfg_purchase_docs', ['owner_id', 'doc_type', 'external_ref'],
                    unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"))
    op.create_table(
        'mfg_purchase_lines',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('doc_id', sa.String(64),
                  sa.ForeignKey('mfg_purchase_docs.id', ondelete='CASCADE',
                                name='fk_mfg_purchase_lines_doc_id_mfg_purchase_docs'),
                  nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_purchase_lines_item_id_mfg_items'),
                  nullable=False),
        sa.Column('unit_price', sa.Double(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('source_pr_line_id', sa.String(64),
                  sa.ForeignKey('mfg_purchase_lines.id', ondelete='SET NULL',
                                name='fk_mfg_purchase_lines_source_pr_line_id_mfg_purchase_lines'),
                  nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_purchase_lines_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('doc_id', 'line_no', name='uq_mfg_purchase_lines_no'),
    )
    op.create_index('ix_mfg_purchase_lines_item', 'mfg_purchase_lines', ['item_id'])
    op.create_index('ix_mfg_purchase_lines_owner', 'mfg_purchase_lines', ['owner_id'])
    op.create_index('ix_mfg_purchase_lines_source_pr_line', 'mfg_purchase_lines', ['source_pr_line_id'])
    op.create_table(
        'mfg_purchase_schedules',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('line_id', sa.String(64),
                  sa.ForeignKey('mfg_purchase_lines.id', ondelete='CASCADE',
                                name='fk_mfg_purchase_schedules_line_id_mfg_purchase_lines'),
                  nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('requested_date', sa.Date(), nullable=False),
        sa.Column('confirmed_date', sa.Date(), nullable=True),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('received_qty', sa.Double(), nullable=False),
        sa.Column('closed', sa.Boolean(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_purchase_schedules_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('received_qty >= 0', name='ck_mfg_purchase_schedules_received'),
        sa.UniqueConstraint('line_id', 'seq', name='uq_mfg_purchase_schedules_seq'),
    )
    op.create_index('ix_mfg_purchase_schedules_owner_requested', 'mfg_purchase_schedules',
                    ['owner_id', 'requested_date'])
    op.create_table(
        'mfg_demand_orders',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('demand_type', sa.String(16), nullable=False),
        sa.Column('customer', sa.String(200), nullable=False),
        sa.Column('program', sa.String(32), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_demand_orders_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_demand_orders_number'),
    )
    op.create_index('ix_mfg_demand_orders_owner_status', 'mfg_demand_orders', ['owner_id', 'status'])
    op.create_index('uq_mfg_demand_orders_extref', 'mfg_demand_orders', ['owner_id', 'external_ref'],
                    unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"))
    op.create_table(
        'mfg_demand_lines',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('order_id', sa.String(64),
                  sa.ForeignKey('mfg_demand_orders.id', ondelete='CASCADE',
                                name='fk_mfg_demand_lines_order_id_mfg_demand_orders'),
                  nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_demand_lines_item_id_mfg_items'),
                  nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('shipped_qty', sa.Double(), nullable=False),
        sa.Column('serial_from', sa.BigInteger(), nullable=True),
        sa.Column('serial_to', sa.BigInteger(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_demand_lines_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('order_id', 'line_no', name='uq_mfg_demand_lines_no'),
    )
    op.create_index('ix_mfg_demand_lines_item', 'mfg_demand_lines', ['item_id'])
    op.create_index('ix_mfg_demand_lines_owner_due', 'mfg_demand_lines', ['owner_id', 'due_date'])
    op.create_table(
        'mfg_work_orders',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_work_orders_item_id_mfg_items'),
                  nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('qty_completed', sa.Double(), nullable=False),
        sa.Column('qty_scrapped', sa.Double(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('serial_from', sa.BigInteger(), nullable=True),
        sa.Column('serial_to', sa.BigInteger(), nullable=True),
        sa.Column('bom_id', sa.String(64),
                  sa.ForeignKey('mfg_boms.id', ondelete='SET NULL', name='fk_mfg_work_orders_bom_id_mfg_boms'),
                  nullable=True),
        sa.Column('routing_id', sa.String(64),
                  sa.ForeignKey('mfg_routings.id', ondelete='SET NULL',
                                name='fk_mfg_work_orders_routing_id_mfg_routings'),
                  nullable=True),
        sa.Column('demand_line_id', sa.String(64),
                  sa.ForeignKey('mfg_demand_lines.id', ondelete='SET NULL',
                                name='fk_mfg_work_orders_demand_line_id_mfg_demand_lines'),
                  nullable=True),
        sa.Column('source', sa.String(8), nullable=False),
        sa.Column('source_run_no', sa.Integer(), nullable=True),
        sa.Column('source_planned_no', sa.Integer(), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_work_orders_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_work_orders_number'),
    )
    op.create_index('ix_mfg_work_orders_bom', 'mfg_work_orders', ['bom_id'])
    op.create_index('ix_mfg_work_orders_demand_line', 'mfg_work_orders', ['demand_line_id'])
    op.create_index('ix_mfg_work_orders_item', 'mfg_work_orders', ['item_id'])
    op.create_index('ix_mfg_work_orders_owner_status', 'mfg_work_orders', ['owner_id', 'status'])
    op.create_index('ix_mfg_work_orders_routing', 'mfg_work_orders', ['routing_id'])
    op.create_index('uq_mfg_work_orders_extref', 'mfg_work_orders', ['owner_id', 'external_ref'],
                    unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"))
    op.create_table(
        'mfg_wo_components',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('wo_id', sa.String(64),
                  sa.ForeignKey('mfg_work_orders.id', ondelete='CASCADE',
                                name='fk_mfg_wo_components_wo_id_mfg_work_orders'),
                  nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_wo_components_item_id_mfg_items'),
                  nullable=False),
        sa.Column('required_qty', sa.Double(), nullable=False),
        sa.Column('issued_qty', sa.Double(), nullable=False),
        sa.Column('operation_seq', sa.Integer(), nullable=True),
        sa.Column('find_number', sa.String(16), nullable=True),
        sa.Column('alt_group', sa.String(16), nullable=True),
        sa.Column('bom_line_id', sa.String(64), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_wo_components_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('issued_qty >= 0', name='ck_mfg_wo_components_issued'),
    )
    op.create_index('ix_mfg_wo_components_item', 'mfg_wo_components', ['item_id'])
    op.create_index('ix_mfg_wo_components_owner', 'mfg_wo_components', ['owner_id'])
    op.create_index('ix_mfg_wo_components_wo', 'mfg_wo_components', ['wo_id'])
    op.create_table(
        'mfg_inv_balances',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_inv_balances_item_id_mfg_items'),
                  nullable=False),
        sa.Column('location_id', sa.String(64),
                  sa.ForeignKey('mfg_locations.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_balances_location_id_mfg_locations'),
                  nullable=False),
        sa.Column('lot_id', sa.String(64),
                  sa.ForeignKey('mfg_lots.id', ondelete='RESTRICT', name='fk_mfg_inv_balances_lot_id_mfg_lots'),
                  nullable=True),
        sa.Column('lot_key', sa.String(64), nullable=False),
        sa.Column('qty_on_hand', sa.Double(), nullable=False),
        sa.Column('qty_reserved', sa.Double(), nullable=False),
        sa.Column('last_receipt_on', sa.Date(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_inv_balances_owner_id_users'),
                  nullable=False),
        sa.CheckConstraint('qty_on_hand >= 0', name='ck_mfg_inv_balances_on_hand'),
        sa.CheckConstraint('qty_reserved >= 0', name='ck_mfg_inv_balances_reserved'),
        sa.CheckConstraint('qty_reserved <= qty_on_hand + 0.000001', name='ck_mfg_inv_balances_reserved_le_on_hand'),
        sa.UniqueConstraint('owner_id', 'item_id', 'location_id', 'lot_key', name='uq_mfg_inv_balances_key'),
    )
    op.create_index('ix_mfg_inv_balances_item', 'mfg_inv_balances', ['item_id'])
    op.create_index('ix_mfg_inv_balances_location', 'mfg_inv_balances', ['location_id'])
    op.create_index('ix_mfg_inv_balances_lot', 'mfg_inv_balances', ['lot_id'])
    op.create_table(
        'mfg_inv_reservations',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('wo_component_id', sa.String(64),
                  sa.ForeignKey('mfg_wo_components.id', ondelete='CASCADE',
                                name='fk_mfg_inv_reservations_wo_component_id_mfg_wo_components'),
                  nullable=False),
        sa.Column('balance_id', sa.String(64),
                  sa.ForeignKey('mfg_inv_balances.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_reservations_balance_id_mfg_inv_balances'),
                  nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_inv_reservations_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('wo_component_id', 'balance_id', name='uq_mfg_inv_reservations_key'),
    )
    op.create_index('ix_mfg_inv_reservations_balance', 'mfg_inv_reservations', ['balance_id'])
    op.create_index('ix_mfg_inv_reservations_owner', 'mfg_inv_reservations', ['owner_id'])
    op.create_table(
        'mfg_inv_postings',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('type', sa.String(16), nullable=False),
        sa.Column('txn_date', sa.Date(), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('reason_code', sa.String(32), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=True),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('reversal_of_id', sa.String(64),
                  sa.ForeignKey('mfg_inv_postings.id', ondelete='SET NULL',
                                name='fk_mfg_inv_postings_reversal_of_id_mfg_inv_postings'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_inv_postings_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_inv_postings_number'),
    )
    op.create_index('ix_mfg_inv_postings_owner_created', 'mfg_inv_postings', ['owner_id', 'created_at'])
    op.create_index('ix_mfg_inv_postings_reversal_of', 'mfg_inv_postings', ['reversal_of_id'])
    op.create_index('uq_mfg_inv_postings_idem', 'mfg_inv_postings', ['owner_id', 'idempotency_key'],
                    unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_table(
        'mfg_inv_transactions',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('posting_id', sa.String(64),
                  sa.ForeignKey('mfg_inv_postings.id', ondelete='CASCADE',
                                name='fk_mfg_inv_transactions_posting_id_mfg_inv_postings'),
                  nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('txn_type', sa.String(16), nullable=False),
        sa.Column('txn_date', sa.Date(), nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT', name='fk_mfg_inv_transactions_item_id_mfg_items'),
                  nullable=False),
        sa.Column('location_id', sa.String(64),
                  sa.ForeignKey('mfg_locations.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_transactions_location_id_mfg_locations'),
                  nullable=False),
        sa.Column('lot_id', sa.String(64),
                  sa.ForeignKey('mfg_lots.id', ondelete='RESTRICT', name='fk_mfg_inv_transactions_lot_id_mfg_lots'),
                  nullable=True),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('balance_after', sa.Double(), nullable=False),
        sa.Column('unit_cost', sa.Double(), nullable=True),
        sa.Column('schedule_id', sa.String(64),
                  sa.ForeignKey('mfg_purchase_schedules.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_transactions_schedule_id_mfg_purchase_schedules'),
                  nullable=True),
        sa.Column('wo_id', sa.String(64),
                  sa.ForeignKey('mfg_work_orders.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_transactions_wo_id_mfg_work_orders'),
                  nullable=True),
        sa.Column('wo_component_id', sa.String(64),
                  sa.ForeignKey('mfg_wo_components.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_transactions_wo_component_id_mfg_wo_components'),
                  nullable=True),
        sa.Column('demand_line_id', sa.String(64),
                  sa.ForeignKey('mfg_demand_lines.id', ondelete='RESTRICT',
                                name='fk_mfg_inv_transactions_demand_line_id_mfg_demand_lines'),
                  nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_inv_transactions_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('seq', name='uq_mfg_inv_transactions_seq'),
    )
    op.create_index('ix_mfg_inv_transactions_demand_line', 'mfg_inv_transactions', ['demand_line_id'])
    op.create_index('ix_mfg_inv_transactions_item_seq', 'mfg_inv_transactions', ['item_id', 'seq'])
    op.create_index('ix_mfg_inv_transactions_location', 'mfg_inv_transactions', ['location_id'])
    op.create_index('ix_mfg_inv_transactions_lot', 'mfg_inv_transactions', ['lot_id'])
    op.create_index('ix_mfg_inv_transactions_owner_seq', 'mfg_inv_transactions', ['owner_id', 'seq'])
    op.create_index('ix_mfg_inv_transactions_posting', 'mfg_inv_transactions', ['posting_id'])
    op.create_index('ix_mfg_inv_transactions_schedule', 'mfg_inv_transactions', ['schedule_id'])
    op.create_index('ix_mfg_inv_transactions_wo', 'mfg_inv_transactions', ['wo_id'])
    op.create_index('ix_mfg_inv_transactions_wo_component', 'mfg_inv_transactions', ['wo_component_id'])
    op.create_table(
        'mfg_number_series',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('prefix', sa.String(16), nullable=False),
        sa.Column('next_value', sa.BigInteger(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_number_series_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('owner_id', 'kind', name='uq_mfg_number_series_kind'),
    )
    op.create_table(
        'mfg_mrp_runs',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('pinned', sa.Boolean(), nullable=False),
        sa.Column('params', _json(), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('horizon_days', sa.Integer(), nullable=False),
        sa.Column('master_fingerprint', sa.String(64), nullable=False),
        sa.Column('data_version', sa.Integer(), nullable=False),
        sa.Column('inputs_token', _json(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('summary', _json(), nullable=True),
        sa.Column('error', _json(), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_mrp_runs_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'run_no', name='uq_mfg_mrp_runs_no'),
    )
    op.create_index('ix_mfg_mrp_runs_owner_created', 'mfg_mrp_runs', ['owner_id', 'created_at'])
    op.create_index('uq_mfg_mrp_runs_running', 'mfg_mrp_runs', ['owner_id'],
                    unique=True, postgresql_where=sa.text("status = 'running'"))
    op.create_table(
        'mfg_mrp_planned_orders',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_mrp_runs.id', ondelete='CASCADE',
                                name='fk_mfg_mrp_planned_orders_run_id_mfg_mrp_runs'),
                  nullable=False),
        sa.Column('planned_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('part_number', sa.String(64), nullable=False),
        sa.Column('supplier_id', sa.String(64), nullable=True),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('need_date', sa.Date(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('dock_date', sa.Date(), nullable=True),
        sa.Column('projected_start', sa.Date(), nullable=False),
        sa.Column('projected_due', sa.Date(), nullable=False),
        sa.Column('late_days', sa.Integer(), nullable=False),
        sa.Column('release_status', sa.String(16), nullable=False),
        sa.Column('segment', _json(), nullable=True),
        sa.Column('bom_id', sa.String(64), nullable=True),
        sa.Column('routing_id', sa.String(64), nullable=True),
        sa.Column('llc', sa.Integer(), nullable=False),
        sa.Column('lot_note', sa.String(200), nullable=False),
        sa.Column('peg_summary', _json(), nullable=False),
        sa.Column('order_key', sa.String(200), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('converted_type', sa.String(8), nullable=True),
        sa.Column('converted_id', sa.String(64), nullable=True),
        sa.Column('converted_number', sa.String(32), nullable=True),
        sa.Column('converted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('converted_by', sa.String(64), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_mrp_planned_orders_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('run_id', 'planned_no', name='uq_mfg_mrp_planned_orders_no'),
    )
    op.create_index('ix_mfg_mrp_planned_orders_owner', 'mfg_mrp_planned_orders', ['owner_id'])
    op.create_index('ix_mfg_mrp_planned_orders_run_item', 'mfg_mrp_planned_orders', ['run_id', 'item_id'])
    op.create_index('ix_mfg_mrp_planned_orders_run_kind_start', 'mfg_mrp_planned_orders',
                    ['run_id', 'kind', 'start_date'])
    op.create_table(
        'mfg_mrp_exceptions',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_mrp_runs.id', ondelete='CASCADE',
                                name='fk_mfg_mrp_exceptions_run_id_mfg_mrp_runs'),
                  nullable=False),
        sa.Column('ex_no', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('severity', sa.String(8), nullable=False),
        sa.Column('item_id', sa.String(64), nullable=True),
        sa.Column('part_number', sa.String(64), nullable=True),
        sa.Column('demand_line_id', sa.String(64), nullable=True),
        sa.Column('subject', _json(), nullable=False),
        sa.Column('ex_date', sa.Date(), nullable=True),
        sa.Column('qty', sa.Double(), nullable=True),
        sa.Column('days', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(1000), nullable=False),
        sa.Column('action', sa.String(500), nullable=False),
        sa.Column('suggested', _json(), nullable=True),
        sa.Column('related', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_mrp_exceptions_owner_id_users'),
                  nullable=False),
    )
    op.create_index('ix_mfg_mrp_exceptions_owner', 'mfg_mrp_exceptions', ['owner_id'])
    op.create_index('ix_mfg_mrp_exceptions_run_item', 'mfg_mrp_exceptions', ['run_id', 'item_id'])
    op.create_index('ix_mfg_mrp_exceptions_run_sev_code', 'mfg_mrp_exceptions', ['run_id', 'severity', 'code'])
    op.create_table(
        'mfg_mrp_item_results',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_mrp_runs.id', ondelete='CASCADE',
                                name='fk_mfg_mrp_item_results_run_id_mfg_mrp_runs'),
                  nullable=False),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('part_number', sa.String(64), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('make_buy', sa.String(8), nullable=False),
        sa.Column('uom', sa.String(8), nullable=False),
        sa.Column('llc', sa.Integer(), nullable=False),
        sa.Column('on_hand', sa.Double(), nullable=False),
        sa.Column('gross_qty', sa.Double(), nullable=False),
        sa.Column('existing_supply_qty', sa.Double(), nullable=False),
        sa.Column('planned_qty', sa.Double(), nullable=False),
        sa.Column('planned_count', sa.Integer(), nullable=False),
        sa.Column('first_short_date', sa.Date(), nullable=True),
        sa.Column('short_qty', sa.Double(), nullable=False),
        sa.Column('late_qty', sa.Double(), nullable=False),
        sa.Column('min_balance', sa.Double(), nullable=False),
        sa.Column('exception_count', sa.Integer(), nullable=False),
        sa.Column('detail', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_mrp_item_results_owner_id_users'),
                  nullable=False),
        sa.UniqueConstraint('run_id', 'item_id', name='uq_mfg_mrp_item_results_item'),
    )
    op.create_index('ix_mfg_mrp_item_results_owner', 'mfg_mrp_item_results', ['owner_id'])
    op.create_index('ix_mfg_mrp_item_results_run_pn', 'mfg_mrp_item_results', ['run_id', 'part_number'])
    op.create_table(
        'mfg_mrp_demand_results',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('run_id', sa.String(64),
                  sa.ForeignKey('mfg_mrp_runs.id', ondelete='CASCADE',
                                name='fk_mfg_mrp_demand_results_run_id_mfg_mrp_runs'),
                  nullable=False),
        sa.Column('demand_line_id', sa.String(64), nullable=True),
        sa.Column('order_id', sa.String(64), nullable=True),
        sa.Column('order_number', sa.String(32), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('extra', sa.Boolean(), nullable=False),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('part_number', sa.String(64), nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('projected_date', sa.Date(), nullable=True),
        sa.Column('late_days', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('program', sa.String(32), nullable=True),
        sa.Column('segment', _json(), nullable=True),
        sa.Column('limiting', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_mrp_demand_results_owner_id_users'),
                  nullable=False),
    )
    op.create_index('ix_mfg_mrp_demand_results_owner', 'mfg_mrp_demand_results', ['owner_id'])
    op.create_index('ix_mfg_mrp_demand_results_run_late', 'mfg_mrp_demand_results', ['run_id', 'late_days'])
    op.create_index('ix_mfg_mrp_demand_results_run_line', 'mfg_mrp_demand_results', ['run_id', 'demand_line_id'])
    op.create_table(
        'mfg_plant_members',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_plant_members_user_id_users'),
                  nullable=False),
        sa.Column('roles', _json(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('invited_by', sa.String(64), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_plant_members_owner_id_users'),
                  nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'user_id', name='uq_mfg_plant_members_user'),
    )
    op.create_index('ix_mfg_plant_members_user', 'mfg_plant_members', ['user_id'])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_index("uq_mfg_items_owner_extref", table_name="mfg_items")
    for col in ITEM_COLUMNS:
        op.drop_column("mfg_items", col)
    for col in PLANT_COLUMNS:
        op.drop_column("mfg_plant", col)
