"""M7 regulated foundation and quality (M7-DESIGN 3): electronic signatures (policies, signatures, step-up tokens),
quality (sampling schemes, inspection plans and characteristics, inspection lots, results and their replay records,
switching states, NCRs and dispositions, CAPAs and actions, complaints, field actions and units, equipment,
calibrations, attachments, links), first-class lot/serial holds, Part 11 exports; columns on users (enrolment,
lockout), audit_events (changes, reason, signature_id, record_version), mfg_plant (part11_mode, qa_settings),
mfg_work_orders (kind, ncr_id), mfg_inv_transactions (ncr_id), mfg_unit_serials (hold), mfg_floor_events (qty_nc,
ncr_id, defect_code), orgs (session_idle_minutes). The job kinds `part11_export` and `qa_due_scan` target
`maintenance_runs` (existing column): the job check is unchanged.

Revision ID: 0010_m7
Revises: 0009_ux
Create Date: 2026-11-23

Policy: expand. Frozen migration: literal definitions only. Additive only; NOT NULL columns on existing tables are
added with a server default (backfill) that is dropped right after (no server defaults, M4 3.1). Existing open
`mfg_lots.hold = true` rows get a `manual` hold row so the derived flag stays true. Downgrade deletes the new kinds'
jobs and drops everything it added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_m7"
down_revision = "0009_ux"
branch_labels = None
depends_on = None
policy = "expand"

TABLES = ("esig_stepups", "esig_policies", "esig_signatures", "qa_sampling_schemes", "qa_inspection_plans",
          "qa_characteristics", "qa_inspection_lots", "qa_results", "qa_result_batches", "qa_switching_states",
          "mfg_lot_holds", "qa_ncrs", "qa_ncr_dispositions", "qa_capas", "qa_capa_actions", "qa_complaints",
          "qa_field_actions", "qa_field_action_units", "qa_equipment", "qa_calibrations", "qa_attachments",
          "qa_links", "part11_exports")
KINDS = ("part11_export", "qa_due_scan")
COLUMNS = (("users", "legal_name"), ("users", "esig_enrolled_at"), ("users", "esig_ack_version"),
           ("users", "esig_revoked_at"), ("users", "esig_failed"), ("users", "esig_locked_until"),
           ("users", "esig_password_hash"), ("audit_events", "changes"), ("audit_events", "reason"),
           ("audit_events", "signature_id"), ("audit_events", "record_version"), ("mfg_plant", "part11_mode"),
           ("mfg_plant", "qa_settings"), ("mfg_work_orders", "kind"), ("mfg_work_orders", "ncr_id"),
           ("mfg_inv_transactions", "ncr_id"), ("mfg_unit_serials", "hold"), ("mfg_floor_events", "qty_nc"),
           ("mfg_floor_events", "ncr_id"), ("mfg_floor_events", "defect_code"), ("orgs", "session_idle_minutes"))


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _columns() -> None:
    op.add_column("users", sa.Column("legal_name", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("esig_enrolled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("esig_ack_version", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("esig_revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("esig_failed", _json(), nullable=True))
    op.add_column("users", sa.Column("esig_locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("esig_password_hash", sa.Text(), nullable=True))
    op.add_column("audit_events", sa.Column("changes", _json(), nullable=True))
    op.add_column("audit_events", sa.Column("reason", sa.String(500), nullable=True))
    op.add_column("audit_events", sa.Column("signature_id", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("record_version", sa.Integer(), nullable=True))
    op.add_column("mfg_plant", sa.Column("part11_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column("mfg_plant", "part11_mode", server_default=None)
    op.add_column("mfg_plant", sa.Column("qa_settings", _json(), nullable=True))
    op.add_column("mfg_work_orders", sa.Column("kind", sa.String(8), nullable=False,
                                               server_default=sa.text("'standard'")))
    op.alter_column("mfg_work_orders", "kind", server_default=None)
    op.add_column("mfg_work_orders", sa.Column("ncr_id", sa.String(64), nullable=True))
    op.add_column("mfg_inv_transactions", sa.Column("ncr_id", sa.String(64), nullable=True))
    op.add_column("mfg_unit_serials", sa.Column("hold", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column("mfg_unit_serials", "hold", server_default=None)
    op.add_column("mfg_floor_events", sa.Column("qty_nc", sa.Double(), nullable=True))
    op.add_column("mfg_floor_events", sa.Column("ncr_id", sa.String(64), nullable=True))
    op.add_column("mfg_floor_events", sa.Column("defect_code", sa.String(32), nullable=True))
    op.add_column("orgs", sa.Column("session_idle_minutes", sa.Integer(), nullable=True))


def _tables() -> None:
    op.create_table(
        "esig_stepups",
        sa.Column("token_hash", sa.String(64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_esig_stepups_user_id_users"), nullable=False),
        sa.Column("session_ref", sa.String(64), nullable=False),
        sa.Column("amr", _json(), nullable=False),
        sa.Column("auth_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_esig_stepups_expires", "esig_stepups", ["expires_at"])
    op.create_index("ix_esig_stepups_user", "esig_stepups", ["user_id"])
    op.create_table(
        "esig_policies",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("steps", _json(), nullable=False),
        sa.Column("auth", sa.String(16), nullable=False),
        sa.Column("distinct_signers", sa.Boolean(), nullable=False),
        sa.Column("exclude_author", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_esig_policies_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "record_type", "action", name="uq_esig_policies_key"),
    )
    op.create_table(
        "esig_signatures",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("record_id", sa.String(64), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("meaning", sa.String(16), nullable=False),
        sa.Column("signer_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_esig_signatures_signer_id_users"), nullable=False),
        sa.Column("signer_legal_name", sa.String(200), nullable=False),
        sa.Column("signer_username", sa.String(254), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auth_method", sa.String(16), nullable=False),
        sa.Column("policy_id", sa.String(64), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", _json(), nullable=False),
        sa.Column("comment", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("audit_event_id", sa.Integer(), nullable=True),
        sa.Column("mac", sa.String(80), nullable=False),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("session_ref", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_esig_signatures_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_esig_signatures_record", "esig_signatures", ["owner_id", "record_type", "record_id"])
    op.create_index("ix_esig_signatures_signer", "esig_signatures", ["signer_id", "signed_at"])
    op.create_table(
        "qa_sampling_schemes",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("fixed_n", sa.Integer(), nullable=True),
        sa.Column("percent", sa.Double(), nullable=True),
        sa.Column("table", _json(), nullable=True),
        sa.Column("switching", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("author_id", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_sampling_schemes_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "code", name="uq_qa_sampling_schemes_code"),
    )
    op.create_table(
        "qa_inspection_plans",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="RESTRICT", name="fk_qa_inspection_plans_item_id_mfg_items"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("operation_seq", sa.Integer(), nullable=True),
        sa.Column("supplier_id", sa.String(64), sa.ForeignKey("mfg_suppliers.id", ondelete="RESTRICT", name="fk_qa_inspection_plans_supplier_id_mfg_suppliers"), nullable=True),
        sa.Column("customer", sa.String(100), nullable=True),
        sa.Column("scheme_id", sa.String(64), sa.ForeignKey("qa_sampling_schemes.id", ondelete="RESTRICT", name="fk_qa_inspection_plans_scheme_id_qa_sampling_schemes"), nullable=False),
        sa.Column("inspection_level", sa.String(8), nullable=False),
        sa.Column("aql", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("supersedes_id", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("author_id", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_inspection_plans_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", "version", name="uq_qa_inspection_plans_number"),
    )
    op.create_index("ix_qa_inspection_plans_item", "qa_inspection_plans", ["item_id"])
    op.create_index("ix_qa_inspection_plans_key", "qa_inspection_plans", ["owner_id", "item_id", "scope", "status"])
    op.create_index("ix_qa_inspection_plans_scheme", "qa_inspection_plans", ["scheme_id"])
    op.create_index("ix_qa_inspection_plans_supplier", "qa_inspection_plans", ["supplier_id"])
    op.create_table(
        "qa_characteristics",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("qa_inspection_plans.id", ondelete="CASCADE", name="fk_qa_characteristics_plan_id_qa_inspection_plans"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("unit", sa.String(16), nullable=True),
        sa.Column("nominal", sa.Double(), nullable=True),
        sa.Column("lsl", sa.Double(), nullable=True),
        sa.Column("usl", sa.Double(), nullable=True),
        sa.Column("method", sa.String(500), nullable=False),
        sa.Column("equipment_class", sa.String(32), nullable=True),
        sa.Column("sample_override", _json(), nullable=True),
        sa.Column("destructive", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_characteristics_owner_id_users"), nullable=False),
        sa.UniqueConstraint("plan_id", "seq", name="uq_qa_characteristics_seq"),
    )
    op.create_index("ix_qa_characteristics_owner", "qa_characteristics", ["owner_id"])
    op.create_table(
        "qa_inspection_lots",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("qa_inspection_plans.id", ondelete="RESTRICT", name="fk_qa_inspection_lots_plan_id_qa_inspection_plans"), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="RESTRICT", name="fk_qa_inspection_lots_item_id_mfg_items"), nullable=False),
        sa.Column("lot_id", sa.String(64), sa.ForeignKey("mfg_lots.id", ondelete="RESTRICT", name="fk_qa_inspection_lots_lot_id_mfg_lots"), nullable=True),
        sa.Column("wo_id", sa.String(64), sa.ForeignKey("mfg_work_orders.id", ondelete="RESTRICT", name="fk_qa_inspection_lots_wo_id_mfg_work_orders"), nullable=True),
        sa.Column("wo_operation_id", sa.String(64), sa.ForeignKey("mfg_wo_operations.id", ondelete="RESTRICT", name="fk_qa_inspection_lots_wo_operation_id_mfg_wo_operations"), nullable=True),
        sa.Column("posting_id", sa.String(64), nullable=True),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("customer", sa.String(100), nullable=True),
        sa.Column("lot_size", sa.Double(), nullable=False),
        sa.Column("sampling", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("verdict", _json(), nullable=True),
        sa.Column("decision", sa.String(8), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=False),
        sa.Column("ncr_id", sa.String(64), nullable=True),
        sa.Column("hold", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_inspection_lots_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_qa_inspection_lots_number"),
    )
    op.create_index("ix_qa_inspection_lots_due", "qa_inspection_lots", ["owner_id", "due_at"])
    op.create_index("ix_qa_inspection_lots_item", "qa_inspection_lots", ["item_id"])
    op.create_index("ix_qa_inspection_lots_lot", "qa_inspection_lots", ["lot_id"])
    op.create_index("ix_qa_inspection_lots_plan", "qa_inspection_lots", ["plan_id"])
    op.create_index("ix_qa_inspection_lots_status", "qa_inspection_lots", ["owner_id", "status", "scope"])
    op.create_index("ix_qa_inspection_lots_wo", "qa_inspection_lots", ["wo_id"])
    op.create_index("ix_qa_inspection_lots_wo_operation", "qa_inspection_lots", ["wo_operation_id"])
    op.create_table(
        "qa_results",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("inspection_lot_id", sa.String(64), sa.ForeignKey("qa_inspection_lots.id", ondelete="CASCADE", name="fk_qa_results_inspection_lot_id_qa_inspection_lots"), nullable=False),
        sa.Column("characteristic_id", sa.String(64), nullable=False),
        sa.Column("sample_no", sa.Integer(), nullable=False),
        sa.Column("value", sa.Double(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("defects", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("entered_by", sa.String(64), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrects_result_id", sa.String(64), nullable=True),
        sa.Column("superseded", sa.Boolean(), nullable=False),
        sa.Column("client_batch_id", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_results_owner_id_users"), nullable=False),
    )
    op.create_index("ix_qa_results_batch", "qa_results", ["owner_id", "client_batch_id"])
    op.create_index("ix_qa_results_owner_equipment", "qa_results", ["owner_id", "equipment_id", "entered_at"])
    op.create_index("ix_qa_results_sample", "qa_results", ["inspection_lot_id", "characteristic_id", "sample_no"])
    op.create_table(
        "qa_result_batches",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("client_batch_id", sa.String(64), nullable=False),
        sa.Column("inspection_lot_id", sa.String(64), sa.ForeignKey("qa_inspection_lots.id", ondelete="CASCADE", name="fk_qa_result_batches_inspection_lot_id_qa_inspection_lots"), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_result_batches_owner_id_users"), nullable=False),
        sa.UniqueConstraint("owner_id", "client_batch_id", name="uq_qa_result_batches_key"),
    )
    op.create_index("ix_qa_result_batches_lot", "qa_result_batches", ["inspection_lot_id"])
    op.create_table(
        "qa_switching_states",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("plan_key", sa.String(120), nullable=False),
        sa.Column("plan_number", sa.String(32), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_qa_switching_states_item_id_mfg_items"), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("history", _json(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_switching_states_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "plan_key", name="uq_qa_switching_states_key"),
    )
    op.create_index("ix_qa_switching_states_item", "qa_switching_states", ["item_id"])
    op.create_table(
        "mfg_lot_holds",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("lot_id", sa.String(64), sa.ForeignKey("mfg_lots.id", ondelete="RESTRICT", name="fk_mfg_lot_holds_lot_id_mfg_lots"), nullable=True),
        sa.Column("serial_id", sa.String(64), sa.ForeignKey("mfg_unit_serials.id", ondelete="RESTRICT", name="fk_mfg_lot_holds_serial_id_mfg_unit_serials"), nullable=True),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="RESTRICT", name="fk_mfg_lot_holds_item_id_mfg_items"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("placed_by", sa.String(64), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_by", sa.String(64), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_signature_id", sa.String(64), nullable=True),
        sa.Column("release_note", sa.String(500), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_lot_holds_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mfg_lot_holds_item", "mfg_lot_holds", ["item_id"])
    op.create_index("ix_mfg_lot_holds_lot", "mfg_lot_holds", ["lot_id"])
    op.create_index("ix_mfg_lot_holds_open_lot", "mfg_lot_holds", ["lot_id"], postgresql_where=sa.text("released_at IS NULL"))
    op.create_index("ix_mfg_lot_holds_serial", "mfg_lot_holds", ["serial_id"])
    op.create_index("ix_mfg_lot_holds_source", "mfg_lot_holds", ["owner_id", "source", "source_id"])
    op.create_table(
        "qa_ncrs",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="RESTRICT", name="fk_qa_ncrs_item_id_mfg_items"), nullable=True),
        sa.Column("lot_id", sa.String(64), sa.ForeignKey("mfg_lots.id", ondelete="RESTRICT", name="fk_qa_ncrs_lot_id_mfg_lots"), nullable=True),
        sa.Column("serials", _json(), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("wo_id", sa.String(64), nullable=True),
        sa.Column("wo_operation_id", sa.String(64), nullable=True),
        sa.Column("operation_seq", sa.Integer(), nullable=True),
        sa.Column("inspection_lot_id", sa.String(64), nullable=True),
        sa.Column("complaint_id", sa.String(64), nullable=True),
        sa.Column("place", sa.String(8), nullable=False),
        sa.Column("location_id", sa.String(64), nullable=True),
        sa.Column("qty_nc", sa.Double(), nullable=False),
        sa.Column("defect_codes", _json(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("containment", sa.Text(), nullable=False),
        sa.Column("investigation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("capa_required", sa.Boolean(), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_ncrs_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_qa_ncrs_number"),
    )
    op.create_index("ix_qa_ncrs_item", "qa_ncrs", ["item_id"])
    op.create_index("ix_qa_ncrs_lot", "qa_ncrs", ["lot_id"])
    op.create_index("ix_qa_ncrs_status", "qa_ncrs", ["owner_id", "status"])
    op.create_index("ix_qa_ncrs_wo_operation", "qa_ncrs", ["owner_id", "wo_operation_id", "status"])
    op.create_table(
        "qa_ncr_dispositions",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("ncr_id", sa.String(64), sa.ForeignKey("qa_ncrs.id", ondelete="CASCADE", name="fk_qa_ncr_dispositions_ncr_id_qa_ncrs"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("qty", sa.Double(), nullable=False),
        sa.Column("location_id", sa.String(64), nullable=True),
        sa.Column("rework_routing_id", sa.String(64), nullable=True),
        sa.Column("rework_to_seq", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.String(2000), nullable=False),
        sa.Column("justification", sa.String(2000), nullable=False),
        sa.Column("implemented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refs", _json(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_ncr_dispositions_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ncr_id", "line_no", name="uq_qa_ncr_dispositions_line"),
    )
    op.create_index("ix_qa_ncr_dispositions_owner", "qa_ncr_dispositions", ["owner_id"])
    op.create_table(
        "qa_capas",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("risk", _json(), nullable=True),
        sa.Column("owner_user_id", sa.String(64), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("root_cause", _json(), nullable=True),
        sa.Column("effectiveness", _json(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("sor", sa.String(16), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_capas_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_qa_capas_number"),
    )
    op.create_index("ix_qa_capas_status", "qa_capas", ["owner_id", "status"])
    op.create_table(
        "qa_capa_actions",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("capa_id", sa.String(64), sa.ForeignKey("qa_capas.id", ondelete="CASCADE", name="fk_qa_capa_actions_capa_id_qa_capas"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("owner_user_id", sa.String(64), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.String(2000), nullable=False),
        sa.Column("eco_id", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_capa_actions_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("capa_id", "seq", name="uq_qa_capa_actions_seq"),
    )
    op.create_index("ix_qa_capa_actions_owner", "qa_capa_actions", ["owner_id", "owner_user_id", "status"])
    op.create_table(
        "qa_complaints",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("aware_on", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("customer", sa.String(200), nullable=False),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("item_id", sa.String(64), nullable=True),
        sa.Column("lots", _json(), nullable=False),
        sa.Column("serials", _json(), nullable=False),
        sa.Column("qty_affected", sa.Double(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("reportability", _json(), nullable=False),
        sa.Column("investigation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sor", sa.String(16), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_complaints_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_qa_complaints_number"),
    )
    op.create_index("ix_qa_complaints_status", "qa_complaints", ["owner_id", "status"])
    op.create_table(
        "qa_field_actions",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("class", sa.String(4), nullable=True),
        sa.Column("regimes", _json(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("recall_id", sa.String(64), sa.ForeignKey("mfg_recalls.id", ondelete="RESTRICT", name="fk_qa_field_actions_recall_id_mfg_recalls"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("complete_reason", sa.String(500), nullable=True),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_field_actions_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_qa_field_actions_number"),
    )
    op.create_index("ix_qa_field_actions_recall", "qa_field_actions", ["recall_id"])
    op.create_table(
        "qa_field_action_units",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("field_action_id", sa.String(64), sa.ForeignKey("qa_field_actions.id", ondelete="CASCADE", name="fk_qa_field_action_units_field_action_id_qa_field_actions"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("serial_id", sa.String(64), nullable=True),
        sa.Column("lot_id", sa.String(64), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("customer", sa.String(200), nullable=False),
        sa.Column("demand_line_id", sa.String(64), nullable=True),
        sa.Column("qty", sa.Double(), nullable=False),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_field_action_units_owner_id_users"), nullable=False),
    )
    op.create_index("ix_qa_field_action_units_owner", "qa_field_action_units", ["owner_id"])
    op.create_index("ix_qa_field_action_units_status", "qa_field_action_units", ["field_action_id", "status"])
    op.create_table(
        "qa_equipment",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("equipment_class", sa.String(32), nullable=False),
        sa.Column("line_id", sa.String(64), sa.ForeignKey("mfg_lines.id", ondelete="SET NULL", name="fk_qa_equipment_line_id_mfg_lines"), nullable=True),
        sa.Column("tool_pool_id", sa.String(64), sa.ForeignKey("mfg_tool_pools.id", ondelete="SET NULL", name="fk_qa_equipment_tool_pool_id_mfg_tool_pools"), nullable=True),
        sa.Column("serial_no", sa.String(64), nullable=False),
        sa.Column("manufacturer", sa.String(100), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("calibration_required", sa.Boolean(), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("grace_days", sa.Integer(), nullable=False),
        sa.Column("last_calibrated_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("failed_on", sa.Date(), nullable=True),
        sa.Column("procedure_ref", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_equipment_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "code", name="uq_qa_equipment_code"),
    )
    op.create_index("ix_qa_equipment_due", "qa_equipment", ["owner_id", "due_on"])
    op.create_index("ix_qa_equipment_line", "qa_equipment", ["line_id"])
    op.create_index("ix_qa_equipment_tool_pool", "qa_equipment", ["tool_pool_id"])
    op.create_table(
        "qa_calibrations",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("equipment_id", sa.String(64), sa.ForeignKey("qa_equipment.id", ondelete="RESTRICT", name="fk_qa_calibrations_equipment_id_qa_equipment"), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("performed_by", sa.String(64), nullable=True),
        sa.Column("provider_name", sa.String(200), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("as_found", sa.String(2000), nullable=False),
        sa.Column("as_left", sa.String(2000), nullable=False),
        sa.Column("certificate_ref", sa.String(200), nullable=False),
        sa.Column("next_due_on", sa.Date(), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_calibrations_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qa_calibrations_equipment", "qa_calibrations", ["equipment_id", "performed_on"])
    op.create_index("ix_qa_calibrations_owner", "qa_calibrations", ["owner_id"])
    op.create_table(
        "qa_attachments",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.String(64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_attachments_owner_id_users"), nullable=False),
    )
    op.create_index("ix_qa_attachments_entity", "qa_attachments", ["owner_id", "entity_type", "entity_id"])
    op.create_table(
        "qa_links",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("from_type", sa.String(32), nullable=False),
        sa.Column("from_id", sa.String(64), nullable=False),
        sa.Column("to_type", sa.String(32), nullable=False),
        sa.Column("to_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_qa_links_owner_id_users"), nullable=False),
        sa.UniqueConstraint("owner_id", "from_type", "from_id", "to_type", "to_id", name="uq_qa_links_key"),
    )
    op.create_index("ix_qa_links_to", "qa_links", ["owner_id", "to_type", "to_id"])
    op.create_table(
        "part11_exports",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("params", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("manifest", _json(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_part11_exports_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_part11_exports_owner", "part11_exports", ["owner_id", "created_at"])


def upgrade() -> None:
    _columns()
    _tables()
    # 0.6: holds become rows. Lots quarantined by a recall keep a `recall` hold of that recall (review m6); every
    # other lot held before M7 keeps its hold as a `manual` hold (released through PUT /lots)
    op.execute("INSERT INTO mfg_lot_holds (id, owner_id, lot_id, serial_id, item_id, source, source_id, reason, "
               "placed_by, placed_at, released_by, released_at, release_signature_id, release_note, row_version, "
               "created_at, updated_at) "
               "SELECT DISTINCT ON (l.id) 'hld_' || md5('recall' || l.id), l.owner_id, l.id, NULL, l.item_id, "
               "'recall', r.id, 'Recall ' || r.number || ' (migrated)', r.actor_id, r.quarantined_at, NULL, NULL, "
               "NULL, '', 1, r.quarantined_at, r.quarantined_at "
               "FROM mfg_lots l JOIN mfg_recalls r ON r.owner_id = l.owner_id AND r.quarantined_at IS NOT NULL "
               "AND EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(r.report->'lots', '[]'::jsonb)) x "
               "WHERE x->>'lot_id' = l.id) WHERE l.hold ORDER BY l.id, r.quarantined_at DESC")
    op.execute("INSERT INTO mfg_lot_holds (id, owner_id, lot_id, serial_id, item_id, source, source_id, reason, "
               "placed_by, placed_at, released_by, released_at, release_signature_id, release_note, row_version, "
               "created_at, updated_at) "
               "SELECT 'hld_' || md5(l.id), l.owner_id, l.id, NULL, l.item_id, 'manual', NULL, "
               "'Hold before M7 (migrated)', l.owner_id, l.updated_at, NULL, NULL, NULL, '', 1, l.updated_at, "
               "l.updated_at FROM mfg_lots l WHERE l.hold AND NOT EXISTS (SELECT 1 FROM mfg_lot_holds h WHERE "
               "h.lot_id = l.id)")


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    op.execute("DELETE FROM maintenance_runs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    for table in reversed(TABLES):
        op.drop_table(table)
    for table, column in reversed(COLUMNS):
        op.drop_column(table, column)
