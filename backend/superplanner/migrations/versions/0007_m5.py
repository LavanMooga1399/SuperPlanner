"""M5 integration and traceability: identity (OIDC identities, TOTP, API tokens), organisations and plants,
integration (settings, endpoints, value maps, mapping profiles, inbox, outbox, deliveries, reconciliations), ECO,
genealogy edges, recalls, transfer orders; columns users.kind, audit_events.owner_id / chain_hash,
mfg_boms / mfg_routings.locked_by_cr_id, mfg_inv_transactions.transfer_line_id; seven job kinds with their target
columns (M5-DESIGN 10).

Revision ID: 0007_m5
Revises: 0006_mfg_m4
Create Date: 2026-11-05

Frozen migration: literal definitions only. Additive only (8: expand -> deploy -> contract); downgrade drops
everything it added (deleting the new kinds' jobs first) and restores the four-target job check.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_m5"
down_revision = "0006_mfg_m4"
branch_labels = None
depends_on = None

TABLES = ('user_identities', 'user_totp', 'oidc_states', 'auth_pending_logins', 'api_tokens', 'orgs', 'org_members',
          'org_plants', 'org_publishes', 'maintenance_runs', 'int_settings', 'int_endpoints', 'int_value_maps',
          'int_mapping_profiles', 'int_inbox', 'int_outbox', 'int_deliveries', 'int_reconciliations',
          'mfg_change_requests', 'mfg_change_request_items', 'mfg_trace_edges', 'mfg_recalls', 'mfg_transfer_orders',
          'mfg_transfer_lines', 'int_sync_state', 'audit_chain_heads')
JOB_TARGETS = (('int_inbox_id', 'int_inbox'),
               ('int_reconciliation_id', 'int_reconciliations'),
               ('maintenance_run_id', 'maintenance_runs'), ('org_publish_id', 'org_publishes'))
OLD_CHECK = "num_nonnulls(solver_run_id, finance_run_id, aps_run_id, aps_simulation_id) = 1"
NEW_CHECK = ("num_nonnulls(solver_run_id, finance_run_id, aps_run_id, aps_simulation_id, "
             + ", ".join(c for c, _t in JOB_TARGETS) + ") = 1")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _columns_up() -> None:
    op.add_column("users", sa.Column("kind", sa.String(16), nullable=False, server_default=sa.text("'person'")))
    op.add_column("audit_events", sa.Column("owner_id", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("chain_hash", sa.String(80), nullable=True))
    op.create_index("ix_audit_owner_id", "audit_events", ["owner_id", "id"])
    op.add_column("mfg_boms", sa.Column("locked_by_cr_id", sa.String(64), nullable=True))
    op.add_column("mfg_routings", sa.Column("locked_by_cr_id", sa.String(64), nullable=True))
    op.add_column("mfg_inv_transactions", sa.Column("transfer_line_id", sa.String(64), nullable=True))


def _columns_down() -> None:
    op.drop_column("mfg_inv_transactions", "transfer_line_id")
    op.drop_column("mfg_routings", "locked_by_cr_id")
    op.drop_column("mfg_boms", "locked_by_cr_id")
    op.drop_index("ix_audit_owner_id", table_name="audit_events")
    op.drop_column("audit_events", "chain_hash")
    op.drop_column("audit_events", "owner_id")
    op.drop_column("users", "kind")


def _jobs_up() -> None:
    for col, table in JOB_TARGETS:
        op.add_column("jobs", sa.Column(col, sa.String(64), sa.ForeignKey(f"{table}.id", ondelete="CASCADE",
                                                                         name=f"fk_jobs_{col}_{table}"),
                                        nullable=True))
    op.drop_constraint("ck_jobs_one_target", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_one_target", "jobs", NEW_CHECK)


def _jobs_down() -> None:
    op.execute("DELETE FROM jobs WHERE " + " OR ".join(f"{c} IS NOT NULL" for c, _t in JOB_TARGETS))
    op.drop_constraint("ck_jobs_one_target", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_one_target", "jobs", OLD_CHECK)
    for col, _table in reversed(JOB_TARGETS):
        op.drop_column("jobs", col)


def upgrade() -> None:
    _columns_up()
    op.create_table(
        'user_identities',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('issuer', sa.String(300), nullable=False),
        sa.Column('sub', sa.String(255), nullable=False),
        sa.Column('user_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='CASCADE',
                                name='fk_user_identities_user_id_users'), nullable=False),
        sa.Column('email', sa.String(254), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('issuer', 'sub', name='uq_user_identities_sub'),
    )
    op.create_index('ix_user_identities_user', 'user_identities', ['user_id'])
    op.create_table(
        'user_totp',
        sa.Column('user_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='CASCADE',
                                name='fk_user_totp_user_id_users'), primary_key=True, nullable=False),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_step', sa.BigInteger(), nullable=True),
        sa.Column('recovery_hashes', _json(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'oidc_states',
        sa.Column('state_hash', sa.String(64), primary_key=True, nullable=False),
        sa.Column('nonce', sa.String(128), nullable=False),
        sa.Column('verifier_enc', sa.Text(), nullable=False),
        sa.Column('next_url', sa.String(500), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_oidc_states_expires', 'oidc_states', ['expires_at'])
    op.create_table(
        'auth_pending_logins',
        sa.Column('token_hash', sa.String(64), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='CASCADE',
                                name='fk_auth_pending_logins_user_id_users'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
    )
    op.create_index('ix_auth_pending_logins_user', 'auth_pending_logins', ['user_id'])
    op.create_table(
        'api_tokens',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('user_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='CASCADE', name='fk_api_tokens_user_id_users'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('prefix', sa.String(16), nullable=False),
        sa.Column('scopes', _json(), nullable=False),
        sa.Column('workspace_owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='CASCADE',
                                name='fk_api_tokens_workspace_owner_id_users'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_ip', sa.String(64), nullable=True),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('token_hash', name='uq_api_tokens_hash'),
    )
    op.create_index('ix_api_tokens_user', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_workspace', 'api_tokens', ['workspace_owner_id'])
    op.create_table(
        'orgs',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('slug', sa.String(64), nullable=False),
        sa.Column('require_2fa', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('slug', name='uq_orgs_slug'),
    )
    op.create_table(
        'org_members',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('org_id', sa.String(64),
                  sa.ForeignKey('orgs.id', ondelete='CASCADE', name='fk_org_members_org_id_orgs'), nullable=False),
        sa.Column('user_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='CASCADE', name='fk_org_members_user_id_users'), nullable=False),
        sa.Column('org_role', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('org_id', 'user_id', name='uq_org_members_user'),
    )
    op.create_index('ix_org_members_user', 'org_members', ['user_id'])
    op.create_table(
        'org_plants',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('org_id', sa.String(64),
                  sa.ForeignKey('orgs.id', ondelete='CASCADE', name='fk_org_plants_org_id_orgs'), nullable=False),
        sa.Column('plant_owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_org_plants_plant_owner_id_users'), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('org_id', 'code', name='uq_org_plants_code'),
        sa.UniqueConstraint('plant_owner_id', name='uq_org_plants_owner'),
    )
    op.create_table(
        'org_publishes',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('org_id', sa.String(64),
                  sa.ForeignKey('orgs.id', ondelete='CASCADE', name='fk_org_publishes_org_id_orgs'), nullable=False),
        sa.Column('source_owner_id', sa.String(64), nullable=False),
        sa.Column('target_owner_ids', _json(), nullable=False),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('part_number_prefix', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('results', _json(), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_org_publishes_org', 'org_publishes', ['org_id', 'created_at'])
    op.create_table(
        'maintenance_runs',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('owner_scope_id', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('params', _json(), nullable=False),
        sa.Column('results', _json(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_maintenance_runs_kind', 'maintenance_runs', ['kind', 'created_at'])
    op.create_table(
        'int_settings',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('adapter', sa.String(32), nullable=False),
        sa.Column('plant_code', sa.String(32), nullable=False),
        sa.Column('sor', _json(), nullable=False),
        sa.Column('goods_receipts_owner', sa.String(16), nullable=False),
        sa.Column('filedrop_enabled', sa.Boolean(), nullable=False),
        sa.Column('export_enabled', sa.Boolean(), nullable=False),
        sa.Column('export_interval_minutes', sa.Integer(), nullable=False),
        sa.Column('export_cursor', sa.BigInteger(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_settings_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', name='uq_int_settings_owner'),
    )
    op.create_table(
        'int_endpoints',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('event_types', _json(), nullable=False),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('cursor', sa.BigInteger(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_endpoints_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_int_endpoints_owner', 'int_endpoints', ['owner_id'])
    op.create_table(
        'int_value_maps',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('domain', sa.String(32), nullable=False),
        sa.Column('external_value', sa.String(64), nullable=False),
        sa.Column('internal_value', sa.String(64), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_value_maps_owner_id_users'), nullable=False),
        sa.UniqueConstraint('owner_id', 'domain', 'external_value', name='uq_int_value_maps_key'),
    )
    op.create_table(
        'int_mapping_profiles',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('file_pattern', sa.String(200), nullable=False),
        sa.Column('mapping', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_mapping_profiles_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'name', name='uq_int_mapping_profiles_name'),
    )
    op.create_table(
        'int_inbox',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('entity', sa.String(32), nullable=False),
        sa.Column('mode', sa.String(24), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('counts', _json(), nullable=False),
        sa.Column('results', _json(), nullable=True),
        sa.Column('payload', _json(), nullable=True),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_int_inbox_owner_id_users'), nullable=False),
        sa.UniqueConstraint('owner_id', 'idempotency_key', name='uq_int_inbox_idem'),
    )
    op.create_index('ix_int_inbox_owner_received', 'int_inbox', ['owner_id', 'received_at'])
    op.create_table(
        'int_outbox',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('type', sa.String(48), nullable=False),
        sa.Column('entity_ref', sa.String(64), nullable=True),
        sa.Column('data', _json(), nullable=False),
        sa.Column('actor_id', sa.String(64), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_int_outbox_owner_id_users'), nullable=False),
    )
    op.create_index('ix_int_outbox_owner_seq', 'int_outbox', ['owner_id', 'seq'])
    op.create_table(
        'int_deliveries',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('endpoint_id', sa.String(64),
                  sa.ForeignKey('int_endpoints.id', ondelete='CASCADE',
                                name='fk_int_deliveries_endpoint_id_int_endpoints'), nullable=False),
        sa.Column('event_seq', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(500), nullable=True),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_deliveries_owner_id_users'), nullable=False),
        sa.UniqueConstraint('endpoint_id', 'event_seq', name='uq_int_deliveries_event'),
    )
    op.create_index('ix_int_deliveries_due', 'int_deliveries', ['status', 'next_attempt_at'])
    op.create_table(
        'int_reconciliations',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('entities', _json(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('summary', _json(), nullable=True),
        sa.Column('results', _json(), nullable=True),
        sa.Column('snapshot', _json(), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_reconciliations_owner_id_users'), nullable=False),
    )
    op.create_index('ix_int_reconciliations_owner', 'int_reconciliations', ['owner_id', 'created_at'])
    op.create_table(
        'mfg_change_requests',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('reason', sa.String(1000), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('source', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('requested_by', sa.String(64), nullable=False),
        sa.Column('submitted_by', sa.String(64), nullable=True),
        sa.Column('approved_by', sa.String(64), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('implemented_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('effectivity', _json(), nullable=False),
        sa.Column('note', sa.String(1000), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_change_requests_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_change_requests_number'),
    )
    op.create_index('ix_mfg_change_requests_owner_status', 'mfg_change_requests', ['owner_id', 'status'])
    op.create_table(
        'mfg_change_request_items',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('cr_id', sa.String(64),
                  sa.ForeignKey('mfg_change_requests.id', ondelete='CASCADE',
                                name='fk_mfg_change_request_items_cr_id_mfg_change_requests'), nullable=False),
        sa.Column('doc_type', sa.String(8), nullable=False),
        sa.Column('doc_id', sa.String(64), nullable=False),
        sa.Column('supersedes_doc_id', sa.String(64), nullable=True),
        sa.Column('disposition', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_change_request_items_owner_id_users'), nullable=False),
        sa.UniqueConstraint('cr_id', 'doc_id', name='uq_mfg_change_request_items_doc'),
    )
    op.create_index('ix_mfg_change_request_items_owner', 'mfg_change_request_items', ['owner_id'])
    op.create_table(
        'mfg_trace_edges',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('from_kind', sa.String(16), nullable=False),
        sa.Column('from_id', sa.String(64), nullable=False),
        sa.Column('from_item_id', sa.String(64), nullable=True),
        sa.Column('to_kind', sa.String(16), nullable=False),
        sa.Column('to_id', sa.String(64), nullable=False),
        sa.Column('to_item_id', sa.String(64), nullable=True),
        sa.Column('qty', sa.Double(), nullable=True),
        sa.Column('precision', sa.String(8), nullable=False),
        sa.Column('event_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('posting_id', sa.String(64), nullable=True),
        sa.Column('floor_event_id', sa.String(64), nullable=True),
        sa.Column('plant_owner_id', sa.String(64), nullable=True),
        sa.Column('source_key', sa.String(200), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_trace_edges_owner_id_users'), nullable=False),
    )
    op.create_index('ix_mfg_trace_edges_from', 'mfg_trace_edges', ['owner_id', 'from_kind', 'from_id'])
    op.create_index('ix_mfg_trace_edges_from_item', 'mfg_trace_edges', ['from_item_id'])
    op.create_index('ix_mfg_trace_edges_to', 'mfg_trace_edges', ['owner_id', 'to_kind', 'to_id'])
    op.create_index('uq_mfg_trace_edges_source', 'mfg_trace_edges', ['source_key'], unique=True)
    op.create_table(
        'mfg_recalls',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('sources', _json(), nullable=False),
        sa.Column('include_possible', sa.Boolean(), nullable=False),
        sa.Column('report', _json(), nullable=True),
        sa.Column('quarantined_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_mfg_recalls_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_recalls_number'),
    )
    op.create_table(
        'mfg_transfer_orders',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('direction', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('source_owner_id', sa.String(64), nullable=False),
        sa.Column('dest_owner_id', sa.String(64), nullable=False),
        sa.Column('mirror_of', sa.String(64), nullable=True),
        sa.Column('from_location_id', sa.String(64), nullable=True),
        sa.Column('to_location_id', sa.String(64), nullable=True),
        sa.Column('note', sa.String(500), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_transfer_orders_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'number', name='uq_mfg_transfer_orders_number'),
    )
    op.create_index('ix_mfg_transfer_orders_mirror', 'mfg_transfer_orders', ['mirror_of'])
    op.create_index('ix_mfg_transfer_orders_owner_status', 'mfg_transfer_orders', ['owner_id', 'status'])
    op.create_table(
        'mfg_transfer_lines',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('order_id', sa.String(64),
                  sa.ForeignKey('mfg_transfer_orders.id', ondelete='CASCADE',
                                name='fk_mfg_transfer_lines_order_id_mfg_transfer_orders'), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.String(64),
                  sa.ForeignKey('mfg_items.id', ondelete='RESTRICT',
                                name='fk_mfg_transfer_lines_item_id_mfg_items'), nullable=False),
        sa.Column('qty', sa.Double(), nullable=False),
        sa.Column('shipped_qty', sa.Double(), nullable=False),
        sa.Column('received_qty', sa.Double(), nullable=False),
        sa.Column('ship_date', sa.Date(), nullable=False),
        sa.Column('receive_date', sa.Date(), nullable=False),
        sa.Column('mirror_line_id', sa.String(64), nullable=True),
        sa.Column('in_transit', _json(), nullable=False),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_mfg_transfer_lines_owner_id_users'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('order_id', 'line_no', name='uq_mfg_transfer_lines_no'),
    )
    op.create_index('ix_mfg_transfer_lines_item', 'mfg_transfer_lines', ['item_id'])
    op.create_index('ix_mfg_transfer_lines_owner', 'mfg_transfer_lines', ['owner_id'])
    # 15.WP-S (security review, before release): shared-SoR sync state, audit chain heads, unique plant codes,
    # append-only audit rows for every role but the owner
    op.create_table(
        'int_sync_state',
        sa.Column('id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('entity', sa.String(32), nullable=False),
        sa.Column('record_id', sa.String(64), nullable=False),
        sa.Column('ref', sa.String(64), nullable=True),
        sa.Column('synced_version', sa.Integer(), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('conflict', _json(), nullable=True),
        sa.Column('conflict_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', sa.String(64),
                  sa.ForeignKey('users.id', ondelete='RESTRICT',
                                name='fk_int_sync_state_owner_id_users'), nullable=False),
        sa.UniqueConstraint('owner_id', 'entity', 'record_id', name='uq_int_sync_state_record'),
    )
    op.create_index('ix_int_sync_state_conflicts', 'int_sync_state', ['owner_id', 'conflict_at'])
    op.create_table(
        'audit_chain_heads',
        sa.Column('owner_key', sa.String(64), primary_key=True, nullable=False),
        sa.Column('last_id', sa.BigInteger(), nullable=False),
        sa.Column('head_hash', sa.String(80), nullable=False),
        sa.Column('mac', sa.String(80), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('uq_int_settings_plant_code', 'int_settings', [sa.text('lower(plant_code)')], unique=True,
                    postgresql_where=sa.text("plant_code <> ''"))
    op.execute("""DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT DISTINCT grantee FROM information_schema.role_table_grants
           WHERE table_name = 'audit_events' AND privilege_type IN ('UPDATE', 'DELETE')
             AND grantee NOT IN (current_user, 'PUBLIC') LOOP
    EXECUTE format('REVOKE UPDATE, DELETE ON audit_events FROM %I', r.grantee);
  END LOOP;
END $$""")

    _jobs_up()


def downgrade() -> None:
    _jobs_down()
    for table in reversed(TABLES):
        op.drop_table(table)
    _columns_down()
