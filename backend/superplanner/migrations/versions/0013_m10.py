"""M10 eDHR, UDI / labels, validation and enterprise rollout (M10-DESIGN 3): DHR records and exceptions, deviations,
customer agreements, CoAs, batch packs, document renditions, UDI device records, label templates / assignments /
printers / print jobs / print events, UDI exports, validation packages; columns on orgs (data_region),
mfg_item_planning (dhr_required), mfg_operations (max_minutes, max_wait_minutes), int_endpoints (region,
cross_region_signature_id). The job kinds `dhr_assemble`, `batch_pack`, `udi_export`, `label_send`,
`validation_package` target `maintenance_runs` (existing column): the job check is unchanged. `mfg_lot_holds.source`
gains `dhr` and `mfg_change_request_items.doc_type` gains `label` (String columns: no schema change).

Revision ID: 0013_m10
Revises: 0012_m9
Create Date: 2026-11-27

Policy: expand. Frozen migration: literal definitions only. Additive only (all new columns nullable). Data step:
plants in Part 11 mode get `assistant_enabled = false` (M10-DESIGN 9.1, release note; switched on again only by a
signed `plant.assistant_on`). Downgrade: open `dhr` holds are released with a system reason (lot hold flags
recomputed), label items of change requests are removed, M10 signatures and policies are deleted (as M8 review 11),
the new kinds' jobs are deleted and everything added is dropped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_m10"
down_revision = "0012_m9"
branch_labels = None
depends_on = None
policy = "expand"

TABLES = ('dhr_records', 'doc_renditions', 'lbl_print_jobs', 'lbl_printers', 'lbl_templates', 'qa_batch_packs', 'qa_coas', 'qa_customer_agreements', 'qa_deviations', 'udi_exports', 'val_packages', 'dhr_exceptions', 'lbl_assignments', 'lbl_print_events', 'udi_device_records')
KINDS = ('dhr_assemble', 'batch_pack', 'udi_export', 'label_send', 'validation_package')
COLUMNS = (('int_endpoints', 'region'), ('int_endpoints', 'cross_region_signature_id'), ('mfg_item_planning', 'dhr_required'), ('mfg_operations', 'max_minutes'), ('mfg_operations', 'max_wait_minutes'), ('orgs', 'data_region'))
#: signature record types / (record_type, action) pairs added by M10 (deleted on downgrade)
RECORD_TYPES = ('dhr', 'deviation', 'customer_agreement', 'coa', 'udi_device', 'label_job', 'validation_package',
                'int_endpoint')
ACTIONS = (('eco', 'approve_label'), ('plant', 'assistant_on'))


def _columns() -> None:
    op.add_column('int_endpoints', sa.Column('region', sa.String(length=8), nullable=True))
    op.add_column('int_endpoints', sa.Column('cross_region_signature_id', sa.String(length=64), nullable=True))
    op.add_column('mfg_item_planning', sa.Column('dhr_required', sa.Boolean(), nullable=True))
    op.add_column('mfg_operations', sa.Column('max_minutes', sa.Integer(), nullable=True))
    op.add_column('mfg_operations', sa.Column('max_wait_minutes', sa.Integer(), nullable=True))
    op.add_column('orgs', sa.Column('data_region', sa.String(length=8), nullable=True))


def _tables() -> None:
    op.create_table('dhr_records',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('subject_kind', sa.String(length=4), nullable=False),
    sa.Column('lot_id', sa.String(length=64), nullable=True),
    sa.Column('wo_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('item_id', sa.String(length=64), nullable=False),
    sa.Column('item_revision', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('supersedes_id', sa.String(length=64), nullable=True),
    sa.Column('superseded_by_id', sa.String(length=64), nullable=True),
    sa.Column('changed_after_release', sa.Boolean(), nullable=False),
    sa.Column('assembled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('section_hashes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('counts', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('hold_id', sa.String(length=64), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision', sa.String(length=8), nullable=True),
    sa.Column('rendition_id', sa.String(length=64), nullable=True),
    sa.Column('renderer_version', sa.String(length=16), nullable=True),
    sa.Column('reassemble_reason', sa.String(length=500), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_dhr_records_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', 'version', name='uq_dhr_records_number')
    )
    op.create_index('ix_dhr_records_lot', 'dhr_records', ['lot_id'], unique=False)
    op.create_index('ix_dhr_records_status', 'dhr_records', ['owner_id', 'status'], unique=False)
    op.create_table('doc_renditions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=24), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('entity_version', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=4), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=True),
    sa.Column('file_path', sa.String(length=500), nullable=True),
    sa.Column('renderer_version', sa.String(length=16), nullable=False),
    sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_doc_renditions_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_doc_renditions_entity', 'doc_renditions', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_doc_renditions_owner', 'doc_renditions', ['owner_id'], unique=False)
    op.create_table('lbl_print_jobs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('item_id', sa.String(length=64), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('udi_id', sa.String(length=64), nullable=False),
    sa.Column('lot_id', sa.String(length=64), nullable=False),
    sa.Column('wo_id', sa.String(length=64), nullable=True),
    sa.Column('template_id', sa.String(length=64), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('serials', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('data_sha256', sa.String(length=64), nullable=False),
    sa.Column('output', sa.String(length=4), nullable=False),
    sa.Column('target', sa.String(length=8), nullable=False),
    sa.Column('printer_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('totals', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('recon_explanation', sa.String(length=1000), nullable=True),
    sa.Column('reconciled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_lbl_print_jobs_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_lbl_print_jobs_number')
    )
    op.create_index('ix_lbl_print_jobs_lot', 'lbl_print_jobs', ['owner_id', 'lot_id'], unique=False)
    op.create_index('ix_lbl_print_jobs_status', 'lbl_print_jobs', ['owner_id', 'status'], unique=False)
    op.create_index('ix_lbl_print_jobs_udi', 'lbl_print_jobs', ['udi_id'], unique=False)
    op.create_table('lbl_printers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('host', sa.String(length=253), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('dpi', sa.Integer(), nullable=False),
    sa.Column('line_id', sa.String(length=64), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_lbl_printers_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'code', name='uq_lbl_printers_code')
    )
    op.create_table('lbl_templates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('width_mm', sa.Double(), nullable=False),
    sa.Column('height_mm', sa.Double(), nullable=False),
    sa.Column('dpi', sa.Integer(), nullable=False),
    sa.Column('languages', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('elements', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('eco_id', sa.String(length=64), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supersedes_id', sa.String(length=64), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_lbl_templates_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'code', 'version', name='uq_lbl_templates_code')
    )
    op.create_index('ix_lbl_templates_status', 'lbl_templates', ['owner_id', 'status'], unique=False)
    op.create_table('qa_batch_packs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('agreement_id', sa.String(length=64), nullable=False),
    sa.Column('lot_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('customer', sa.String(length=100), nullable=False),
    sa.Column('demand_line_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('documents', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rendition_id', sa.String(length=64), nullable=True),
    sa.Column('error', sa.String(length=2000), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_qa_batch_packs_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_qa_batch_packs_number')
    )
    op.create_table('qa_coas',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('agreement_id', sa.String(length=64), nullable=False),
    sa.Column('agreement_version', sa.Integer(), nullable=False),
    sa.Column('lot_id', sa.String(length=64), nullable=False),
    sa.Column('dhr_id', sa.String(length=64), nullable=False),
    sa.Column('customer', sa.String(length=100), nullable=False),
    sa.Column('demand_line_id', sa.String(length=64), nullable=True),
    sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('rendition_id', sa.String(length=64), nullable=True),
    sa.Column('void_reason', sa.String(length=500), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_qa_coas_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_qa_coas_number')
    )
    op.create_index('ix_qa_coas_lot', 'qa_coas', ['owner_id', 'lot_id'], unique=False)
    op.create_table('qa_customer_agreements',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('customer', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('external_ref', sa.String(length=64), nullable=False),
    sa.Column('item_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('coa', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('pack', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('supersedes_id', sa.String(length=64), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_qa_customer_agreements_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', 'version', name='uq_qa_customer_agreements_number')
    )
    op.create_index('ix_qa_customer_agreements_customer', 'qa_customer_agreements', ['owner_id', 'customer'], unique=False)
    op.create_table('qa_deviations',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('scope', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('risk', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('ncr_id', sa.String(length=64), nullable=True),
    sa.Column('capa_id', sa.String(length=64), nullable=True),
    sa.Column('author_id', sa.String(length=64), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.String(length=2000), nullable=True),
    sa.Column('external_ref', sa.String(length=64), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_qa_deviations_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_qa_deviations_number')
    )
    op.create_index('ix_qa_deviations_status', 'qa_deviations', ['owner_id', 'status'], unique=False)
    op.create_table('udi_exports',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=5), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('rule_version', sa.String(length=16), nullable=False),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('rendition_id', sa.String(length=64), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_udi_exports_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_udi_exports_number')
    )
    op.create_table('val_packages',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('baseline_id', sa.String(length=64), nullable=True),
    sa.Column('prev_baseline_id', sa.String(length=64), nullable=True),
    sa.Column('manifest', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('file_path', sa.String(length=500), nullable=True),
    sa.Column('data', sa.LargeBinary(), nullable=True),
    sa.Column('size', sa.Integer(), nullable=True),
    sa.Column('error', sa.String(length=2000), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_val_packages_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'number', name='uq_val_packages_number')
    )
    op.create_index('ix_val_packages_kind', 'val_packages', ['owner_id', 'kind'], unique=False)
    op.create_table('dhr_exceptions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('record_id', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=5), nullable=False),
    sa.Column('section', sa.String(length=16), nullable=False),
    sa.Column('ref_type', sa.String(length=24), nullable=False),
    sa.Column('ref_id', sa.String(length=64), nullable=True),
    sa.Column('ref_number', sa.String(length=32), nullable=True),
    sa.Column('message', sa.String(length=500), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('disposition', sa.String(length=10), nullable=True),
    sa.Column('disposition_ref', sa.String(length=64), nullable=True),
    sa.Column('comment', sa.String(length=1000), nullable=True),
    sa.Column('carried', sa.Boolean(), nullable=False),
    sa.Column('reviewed_by', sa.String(length=64), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_dhr_exceptions_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['record_id'], ['dhr_records.id'], name=op.f('fk_dhr_exceptions_record_id_dhr_records'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dhr_exceptions_owner', 'dhr_exceptions', ['owner_id'], unique=False)
    op.create_index('ix_dhr_exceptions_record', 'dhr_exceptions', ['record_id', 'severity'], unique=False)
    op.create_table('lbl_assignments',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('item_id', sa.String(length=64), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('customer', sa.String(length=100), nullable=True),
    sa.Column('template_code', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['mfg_items.id'], name=op.f('fk_lbl_assignments_item_id_mfg_items'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_lbl_assignments_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('item_id', 'level', 'customer', name='uq_lbl_assignments_key')
    )
    op.create_index('ix_lbl_assignments_owner', 'lbl_assignments', ['owner_id'], unique=False)
    op.create_table('lbl_print_events',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('serials', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('position', sa.String(length=6), nullable=True),
    sa.Column('scan', sa.String(length=400), nullable=True),
    sa.Column('result', sa.String(length=8), nullable=True),
    sa.Column('mismatch', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('client_event_id', sa.String(length=64), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['lbl_print_jobs.id'], name=op.f('fk_lbl_print_events_job_id_lbl_print_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_lbl_print_events_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_lbl_print_events_job', 'lbl_print_events', ['job_id', 'at'], unique=False)
    op.create_index('uq_lbl_print_events_client', 'lbl_print_events', ['owner_id', 'client_event_id'], unique=True, postgresql_where=sa.text('client_event_id IS NOT NULL'))
    op.create_table('udi_device_records',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('packaging_id', sa.String(length=64), nullable=False),
    sa.Column('item_id', sa.String(length=64), nullable=False),
    sa.Column('gtin', sa.String(length=14), nullable=False),
    sa.Column('di_kind', sa.String(length=12), nullable=False),
    sa.Column('qty_per_package', sa.Integer(), nullable=False),
    sa.Column('contains_gtin', sa.String(length=14), nullable=True),
    sa.Column('pi_flags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('attrs', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('commercial_distribution_date', sa.Date(), nullable=True),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_udi_device_records_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['packaging_id'], ['mfg_item_packaging.id'], name=op.f('fk_udi_device_records_packaging_id_mfg_item_packaging'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('packaging_id', name='uq_udi_device_records_packaging')
    )
    op.create_index('ix_udi_device_records_gtin', 'udi_device_records', ['owner_id', 'gtin'], unique=False)
    op.create_index('ix_udi_device_records_item', 'udi_device_records', ['owner_id', 'item_id'], unique=False)


def upgrade() -> None:
    _columns()
    _tables()
    op.execute("UPDATE mfg_plant SET assistant_enabled = false WHERE part11_mode IS TRUE")


def downgrade() -> None:
    op.execute("UPDATE mfg_lot_holds SET released_at = now(), released_by = 'system', "
               "release_note = 'Released by the system: eDHR removed (downgrade 0013_m10)', "
               "row_version = row_version + 1, updated_at = now() WHERE source = 'dhr' AND released_at IS NULL")
    op.execute("UPDATE mfg_lots SET hold = EXISTS (SELECT 1 FROM mfg_lot_holds h WHERE h.lot_id = mfg_lots.id "
               "AND h.released_at IS NULL) WHERE id IN (SELECT lot_id FROM mfg_lot_holds WHERE source = 'dhr')")
    op.execute("DELETE FROM mfg_change_request_items WHERE doc_type = 'label'")
    types = ", ".join(f"'{t}'" for t in RECORD_TYPES)
    pairs = " OR ".join(f"(record_type = '{t}' AND action = '{a}')" for t, a in ACTIONS)
    for table in ("esig_signatures", "esig_policies"):
        op.execute(f"DELETE FROM {table} WHERE record_type IN ({types}) OR {pairs}")
    op.execute("DELETE FROM jobs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    op.execute("DELETE FROM maintenance_runs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    for table in reversed(TABLES):
        op.drop_table(table)
    for table, column in reversed(COLUMNS):
        op.drop_column(table, column)
