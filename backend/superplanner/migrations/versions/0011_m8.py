"""M8 make-to-stock planning at volume (M8-DESIGN 3): item planning and packaging, line rates, changeover matrix,
demand history, forecast runs / versions / lines / overrides, safety-stock runs and lines, rate runs and blocks,
sterilisation loads and members, kanban loops and cards, validation baselines; columns on mfg_lines (planning,
oee, clearance, cleaning, chamber), mfg_plant (planning_settings), mfg_work_orders (kind widened to 12 for
`repetitive`, rate_run_id), mfg_lot_holds (planned_release), int_settings (sap). The job kinds `forecast_run`,
`ss_run`, `rate_run`, `ster_plan`, `nightly_plan`, `history_refresh`, `sap_sync` target `maintenance_runs`
(existing column): the job check is unchanged.

Revision ID: 0011_m8
Revises: 0010_m7
Create Date: 2026-11-25

Policy: expand. Frozen migration: literal definitions only. Additive only (the kind column is widened); NOT NULL
columns on existing tables are added with a server default (backfill) that is dropped right after (no server
defaults, M4 3.1). Downgrade deletes the new kinds' jobs, narrows `kind` back (M8 kinds -> `standard`) and drops
everything it added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_m8"
down_revision = "0010_m7"
branch_labels = None
depends_on = None
policy = "expand"

TABLES = ("mfg_item_planning", "mfg_item_packaging", "mfg_line_rates", "mfg_changeover_rows", "mfg_demand_history",
          "mfg_forecast_runs", "mfg_forecast_versions", "mfg_forecast_lines", "mfg_forecast_overrides", "mfg_ss_runs",
          "mfg_ss_lines", "mfg_rate_runs", "mfg_rate_blocks", "mfg_ster_loads", "mfg_ster_load_members",
          "mfg_kanban_loops", "mfg_kanban_cards", "val_baselines")
KINDS = ("forecast_run", "ss_run", "rate_run", "ster_plan", "nightly_plan", "history_refresh", "sap_sync")
COLUMNS = (("mfg_lines", "planning"), ("mfg_lines", "oee"), ("mfg_lines", "clearance_minutes"),
           ("mfg_lines", "clean_every_hours"), ("mfg_lines", "clean_minutes"), ("mfg_lines", "chamber_pallets"),
           ("mfg_lines", "cycle_hours"), ("mfg_plant", "planning_settings"), ("mfg_work_orders", "rate_run_id"),
           ("mfg_lot_holds", "planned_release"), ("int_settings", "sap"))


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _columns() -> None:
    op.add_column("mfg_lines", sa.Column("planning", sa.String(16), nullable=False,
                                         server_default=sa.text("'discrete'")))
    op.alter_column("mfg_lines", "planning", server_default=None)
    op.add_column("mfg_lines", sa.Column("oee", sa.Double(), nullable=False, server_default=sa.text("0.85")))
    op.alter_column("mfg_lines", "oee", server_default=None)
    op.add_column("mfg_lines", sa.Column("clearance_minutes", sa.Integer(), nullable=False,
                                         server_default=sa.text("0")))
    op.alter_column("mfg_lines", "clearance_minutes", server_default=None)
    op.add_column("mfg_lines", sa.Column("clean_every_hours", sa.Double(), nullable=True))
    op.add_column("mfg_lines", sa.Column("clean_minutes", sa.Integer(), nullable=True))
    op.add_column("mfg_lines", sa.Column("chamber_pallets", sa.Integer(), nullable=True))
    op.add_column("mfg_lines", sa.Column("cycle_hours", sa.Double(), nullable=True))
    op.add_column("mfg_plant", sa.Column("planning_settings", _json(), nullable=True))
    op.alter_column("mfg_work_orders", "kind", type_=sa.String(12), existing_type=sa.String(8),
                    existing_nullable=False)
    op.add_column("mfg_work_orders", sa.Column("rate_run_id", sa.String(64), nullable=True))
    op.add_column("mfg_lot_holds", sa.Column("planned_release", sa.Date(), nullable=True))
    op.add_column("int_settings", sa.Column("sap", _json(), nullable=True))


def _tables() -> None:
    op.create_table(
        "mfg_item_planning",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_item_planning_item_id_mfg_items"), nullable=False),
        sa.Column("replenishment", sa.String(8), nullable=False),
        sa.Column("forecast", sa.Boolean(), nullable=False),
        sa.Column("like_item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="SET NULL", name="fk_mfg_item_planning_like_item_id_mfg_items"), nullable=True),
        sa.Column("like_factor", sa.Double(), nullable=False),
        sa.Column("service_level", sa.Double(), nullable=True),
        sa.Column("order_pack_level", sa.String(8), nullable=True),
        sa.Column("campaign_key", sa.String(32), nullable=True),
        sa.Column("campaign_min_hours", sa.Double(), nullable=False),
        sa.Column("campaign_max_hours", sa.Double(), nullable=True),
        sa.Column("target_cover_days", sa.Integer(), nullable=False),
        sa.Column("ster_cycle_code", sa.String(16), nullable=True),
        sa.Column("aeration_hours", sa.Double(), nullable=True),
        sa.Column("release_mode", sa.String(12), nullable=False),
        sa.Column("release_days", sa.Double(), nullable=False),
        sa.Column("post_days", sa.Integer(), nullable=True),
        sa.Column("abc", sa.String(1), nullable=True),
        sa.Column("xyz", sa.String(1), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_item_planning_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", name="uq_mfg_item_planning_item"),
    )
    op.create_index("ix_mfg_item_planning_like", "mfg_item_planning", ["like_item_id"])
    op.create_index("ix_mfg_item_planning_owner", "mfg_item_planning", ["owner_id", "replenishment"])
    op.create_table(
        "mfg_item_packaging",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_item_packaging_item_id_mfg_items"), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("qty_base", sa.Double(), nullable=False),
        sa.Column("gtin", sa.String(14), nullable=True),
        sa.Column("weight_kg", sa.Double(), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_item_packaging_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "level", name="uq_mfg_item_packaging_level"),
    )
    op.create_index("ix_mfg_item_packaging_owner", "mfg_item_packaging", ["owner_id"])
    op.create_table(
        "mfg_line_rates",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("line_id", sa.String(64), sa.ForeignKey("mfg_lines.id", ondelete="CASCADE", name="fk_mfg_line_rates_line_id_mfg_lines"), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_line_rates_item_id_mfg_items"), nullable=True),
        sa.Column("item_family", sa.String(32), nullable=True),
        sa.Column("units_per_hour", sa.Double(), nullable=False),
        sa.Column("oee", sa.Double(), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_line_rates_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("line_id", "item_id", "item_family", name="uq_mfg_line_rates_key"),
    )
    op.create_index("ix_mfg_line_rates_item", "mfg_line_rates", ["item_id"])
    op.create_index("ix_mfg_line_rates_owner", "mfg_line_rates", ["owner_id"])
    op.create_table(
        "mfg_changeover_rows",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("line_setup_family", sa.String(32), nullable=False),
        sa.Column("from_key", sa.String(32), nullable=False),
        sa.Column("to_key", sa.String(32), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Double(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_changeover_rows_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "line_setup_family", "from_key", "to_key", "kind", name="uq_mfg_changeover_rows_key"),
    )
    op.create_table(
        "mfg_demand_history",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_demand_history_item_id_mfg_items"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("bucket", sa.String(1), nullable=False),
        sa.Column("qty", sa.Double(), nullable=False),
        sa.Column("cleaned_qty", sa.Double(), nullable=True),
        sa.Column("manual_qty", sa.Double(), nullable=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_demand_history_owner_id_users"), nullable=False),
        sa.UniqueConstraint("owner_id", "item_id", "bucket", "period_start", "source", name="uq_mfg_demand_history_key"),
    )
    op.create_index("ix_mfg_demand_history_item", "mfg_demand_history", ["item_id", "bucket", "period_start"])
    op.create_table(
        "mfg_forecast_runs",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("params", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("bucket", sa.String(1), nullable=False),
        sa.Column("first_period", sa.Date(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("summary", _json(), nullable=False),
        sa.Column("results", _json(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_forecast_runs_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_mfg_forecast_runs_number"),
    )
    op.create_index("ix_mfg_forecast_runs_owner", "mfg_forecast_runs", ["owner_id", "created_at"])
    op.create_table(
        "mfg_forecast_versions",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("mfg_forecast_runs.id", ondelete="SET NULL", name="fk_mfg_forecast_versions_run_id_mfg_forecast_runs"), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("bucket", sa.String(1), nullable=False),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("periods", sa.Integer(), nullable=False),
        sa.Column("activated_by", sa.String(64), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_forecast_versions_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_mfg_forecast_versions_number"),
    )
    op.create_index("ix_mfg_forecast_versions_owner", "mfg_forecast_versions", ["owner_id", "status"])
    op.create_index("ix_mfg_forecast_versions_run", "mfg_forecast_versions", ["run_id"])
    op.create_table(
        "mfg_forecast_lines",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("version_id", sa.String(64), sa.ForeignKey("mfg_forecast_versions.id", ondelete="CASCADE", name="fk_mfg_forecast_lines_version_id_mfg_forecast_versions"), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_forecast_lines_item_id_mfg_items"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("stat_qty", sa.Double(), nullable=False),
        sa.Column("final_qty", sa.Double(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_forecast_lines_owner_id_users"), nullable=False),
        sa.UniqueConstraint("version_id", "item_id", "period_start", name="uq_mfg_forecast_lines_key"),
    )
    op.create_index("ix_mfg_forecast_lines_item", "mfg_forecast_lines", ["owner_id", "item_id"])
    op.create_table(
        "mfg_forecast_overrides",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("version_id", sa.String(64), sa.ForeignKey("mfg_forecast_versions.id", ondelete="CASCADE", name="fk_mfg_forecast_overrides_version_id_mfg_forecast_versions"), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_forecast_overrides_item_id_mfg_items"), nullable=True),
        sa.Column("item_family", sa.String(32), nullable=True),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(4), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_forecast_overrides_owner_id_users"), nullable=False),
    )
    op.create_index("ix_mfg_forecast_overrides_item", "mfg_forecast_overrides", ["item_id"])
    op.create_index("ix_mfg_forecast_overrides_owner", "mfg_forecast_overrides", ["owner_id"])
    op.create_index("ix_mfg_forecast_overrides_version", "mfg_forecast_overrides", ["version_id", "seq"])
    op.create_table(
        "mfg_ss_runs",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("params", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("forecast_version_id", sa.String(64), sa.ForeignKey("mfg_forecast_versions.id", ondelete="SET NULL", name="fk_mfg_ss_runs_forecast_version_id_mfg_forecast_versions"), nullable=True),
        sa.Column("summary", _json(), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_ss_runs_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_mfg_ss_runs_number"),
    )
    op.create_index("ix_mfg_ss_runs_owner", "mfg_ss_runs", ["owner_id", "created_at"])
    op.create_index("ix_mfg_ss_runs_version", "mfg_ss_runs", ["forecast_version_id"])
    op.create_table(
        "mfg_ss_lines",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("mfg_ss_runs.id", ondelete="CASCADE", name="fk_mfg_ss_lines_run_id_mfg_ss_runs"), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_ss_lines_item_id_mfg_items"), nullable=False),
        sa.Column("abc", sa.String(1), nullable=False),
        sa.Column("xyz", sa.String(1), nullable=False),
        sa.Column("service_level", sa.Double(), nullable=False),
        sa.Column("z", sa.Double(), nullable=False),
        sa.Column("d_day", sa.Double(), nullable=False),
        sa.Column("sigma_d_day", sa.Double(), nullable=False),
        sa.Column("lt_days", sa.Double(), nullable=False),
        sa.Column("sigma_lt_days", sa.Double(), nullable=False),
        sa.Column("current_ss", sa.Double(), nullable=False),
        sa.Column("proposed_ss", sa.Double(), nullable=False),
        sa.Column("delta_value", sa.Double(), nullable=False),
        sa.Column("flags", _json(), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_ss_lines_owner_id_users"), nullable=False),
    )
    op.create_index("ix_mfg_ss_lines_item", "mfg_ss_lines", ["item_id"])
    op.create_index("ix_mfg_ss_lines_owner", "mfg_ss_lines", ["owner_id"])
    op.create_index("ix_mfg_ss_lines_run", "mfg_ss_lines", ["run_id", "item_id"])
    op.create_table(
        "mfg_rate_runs",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("params", _json(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("mrp_run_id", sa.String(64), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(64), nullable=True),
        sa.Column("objective", _json(), nullable=True),
        sa.Column("summary", _json(), nullable=True),
        sa.Column("explanations", _json(), nullable=True),
        sa.Column("shortages", _json(), nullable=True),
        sa.Column("validator", _json(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_rate_runs_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_mfg_rate_runs_number"),
    )
    op.create_index("ix_mfg_rate_runs_owner", "mfg_rate_runs", ["owner_id", "created_at"])
    op.create_table(
        "mfg_rate_blocks",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("mfg_rate_runs.id", ondelete="CASCADE", name="fk_mfg_rate_blocks_run_id_mfg_rate_runs"), nullable=False),
        sa.Column("line_id", sa.String(64), sa.ForeignKey("mfg_lines.id", ondelete="CASCADE", name="fk_mfg_rate_blocks_line_id_mfg_lines"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_rate_blocks_item_id_mfg_items"), nullable=True),
        sa.Column("campaign_no", sa.Integer(), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qty", sa.Double(), nullable=False),
        sa.Column("cases", sa.Integer(), nullable=True),
        sa.Column("prod_date", sa.Date(), nullable=False),
        sa.Column("wo_id", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_rate_blocks_owner_id_users"), nullable=False),
    )
    op.create_index("ix_mfg_rate_blocks_item", "mfg_rate_blocks", ["item_id"])
    op.create_index("ix_mfg_rate_blocks_line", "mfg_rate_blocks", ["line_id"])
    op.create_index("ix_mfg_rate_blocks_owner", "mfg_rate_blocks", ["owner_id"])
    op.create_index("ix_mfg_rate_blocks_run_line", "mfg_rate_blocks", ["run_id", "line_id", "start"])
    op.create_table(
        "mfg_ster_loads",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("chamber_line_id", sa.String(64), sa.ForeignKey("mfg_lines.id", ondelete="RESTRICT", name="fk_mfg_ster_loads_chamber_line_id_mfg_lines"), nullable=False),
        sa.Column("aeration_line_id", sa.String(64), nullable=True),
        sa.Column("cycle_code", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pallets", sa.Integer(), nullable=False),
        sa.Column("planned_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aeration_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_due", sa.Date(), nullable=False),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_aeration_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_load_id", sa.String(64), nullable=True),
        sa.Column("release_signature_id", sa.String(64), nullable=True),
        sa.Column("ncr_id", sa.String(64), nullable=True),
        sa.Column("flags", _json(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_ster_loads_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_mfg_ster_loads_number"),
    )
    op.create_index("ix_mfg_ster_loads_chamber", "mfg_ster_loads", ["chamber_line_id"])
    op.create_index("ix_mfg_ster_loads_owner", "mfg_ster_loads", ["owner_id", "status", "planned_start"])
    op.create_table(
        "mfg_ster_load_members",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("load_id", sa.String(64), sa.ForeignKey("mfg_ster_loads.id", ondelete="CASCADE", name="fk_mfg_ster_load_members_load_id_mfg_ster_loads"), nullable=False),
        sa.Column("wo_id", sa.String(64), nullable=True),
        sa.Column("rate_block_id", sa.String(64), nullable=True),
        sa.Column("lot_id", sa.String(64), nullable=True),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_ster_load_members_item_id_mfg_items"), nullable=False),
        sa.Column("qty", sa.Double(), nullable=False),
        sa.Column("pallets", sa.Double(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_ster_load_members_owner_id_users"), nullable=False),
    )
    op.create_index("ix_mfg_ster_load_members_item", "mfg_ster_load_members", ["item_id"])
    op.create_index("ix_mfg_ster_load_members_load", "mfg_ster_load_members", ["load_id"])
    op.create_index("ix_mfg_ster_load_members_lot", "mfg_ster_load_members", ["lot_id"])
    op.create_index("ix_mfg_ster_load_members_owner", "mfg_ster_load_members", ["owner_id"])
    op.create_index("ix_mfg_ster_load_members_wo", "mfg_ster_load_members", ["wo_id"])
    op.create_table(
        "mfg_kanban_loops",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("item_id", sa.String(64), sa.ForeignKey("mfg_items.id", ondelete="CASCADE", name="fk_mfg_kanban_loops_item_id_mfg_items"), nullable=False),
        sa.Column("location_id", sa.String(64), sa.ForeignKey("mfg_locations.id", ondelete="RESTRICT", name="fk_mfg_kanban_loops_location_id_mfg_locations"), nullable=False),
        sa.Column("source", sa.String(4), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("line_id", sa.String(64), nullable=True),
        sa.Column("cards", sa.Integer(), nullable=False),
        sa.Column("container_qty", sa.Double(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("consumed", sa.Double(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_kanban_loops_owner_id_users"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "number", name="uq_mfg_kanban_loops_number"),
        sa.UniqueConstraint("item_id", "location_id", name="uq_mfg_kanban_loops_item_location"),
    )
    op.create_index("ix_mfg_kanban_loops_location", "mfg_kanban_loops", ["location_id"])
    op.create_index("ix_mfg_kanban_loops_owner", "mfg_kanban_loops", ["owner_id"])
    op.create_table(
        "mfg_kanban_cards",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("loop_id", sa.String(64), sa.ForeignKey("mfg_kanban_loops.id", ondelete="CASCADE", name="fk_mfg_kanban_cards_loop_id_mfg_kanban_loops"), nullable=False),
        sa.Column("card_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("doc_type", sa.String(8), nullable=True),
        sa.Column("doc_id", sa.String(64), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_mfg_kanban_cards_owner_id_users"), nullable=False),
        sa.UniqueConstraint("loop_id", "card_no", name="uq_mfg_kanban_cards_no"),
    )
    op.create_index("ix_mfg_kanban_cards_doc", "mfg_kanban_cards", ["doc_id"])
    op.create_index("ix_mfg_kanban_cards_owner", "mfg_kanban_cards", ["owner_id"])
    op.create_table(
        "val_baselines",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", _json(), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_val_baselines_owner_id_users"), nullable=False),
    )
    op.create_index("ix_val_baselines_owner", "val_baselines", ["owner_id", "created_at"])


def upgrade() -> None:
    _columns()
    _tables()


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    op.execute("DELETE FROM maintenance_runs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    for table in reversed(TABLES):
        op.drop_table(table)
    for table, column in reversed(COLUMNS):
        op.drop_column(table, column)
    op.execute("UPDATE mfg_work_orders SET kind = 'standard' WHERE kind IN ('repetitive', 'kanban')")
    op.alter_column("mfg_work_orders", "kind", type_=sa.String(8), existing_type=sa.String(12),
                    existing_nullable=False)
