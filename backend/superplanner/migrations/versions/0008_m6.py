"""M6 planning assistant, mobile push, dashboards and digests: assistant conversations / turns / refs / usage,
push subscriptions, digest subscriptions, daily inventory snapshots; columns mfg_plant.assistant_enabled /
assistant_allow_whatif / dashboard_thresholds, mfg_downtime.acknowledged_by / acknowledged_at (M6-DESIGN 6).
The three new job kinds (`push_delivery`, `digest_send`, `inventory_snapshot`) target `maintenance_runs`
(existing column), so the job check is unchanged.

Revision ID: 0008_m6
Revises: 0007_m5
Create Date: 2026-11-06

Policy: expand (M6-DESIGN 4.2 item 6). Frozen migration: literal definitions only. Additive only; downgrade
deletes the new kinds' jobs and drops everything it added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_m6"
down_revision = "0007_m5"
branch_labels = None
depends_on = None
policy = "expand"

TABLES = ("assistant_conversations", "assistant_turns", "assistant_refs", "mfg_inventory_snapshots",
          "assistant_usage", "push_subscriptions", "digest_subscriptions")
KINDS = ("push_delivery", "digest_send", "inventory_snapshot")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _owner(table: str) -> sa.Column:
    return sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT",
                                                              name=f"fk_{table}_owner_id_users"), nullable=False)


def _user(table: str, col: str = "user_id") -> sa.Column:
    return sa.Column(col, sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE",
                                                       name=f"fk_{table}_{col}_users"), nullable=False)


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.add_column("mfg_plant", sa.Column("assistant_enabled", sa.Boolean(), nullable=False,
                                         server_default=sa.text("true")))
    op.add_column("mfg_plant", sa.Column("assistant_allow_whatif", sa.Boolean(), nullable=False,
                                         server_default=sa.text("true")))
    op.add_column("mfg_plant", sa.Column("dashboard_thresholds", _json(), nullable=True))
    op.add_column("mfg_downtime", sa.Column("acknowledged_by", sa.String(64), nullable=True))
    op.add_column("mfg_downtime", _ts("acknowledged_at"))

    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        _user("assistant_conversations"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("allow_whatif", sa.Boolean(), nullable=False),
        _ts("created_at", False), _ts("updated_at", False),
        _owner("assistant_conversations"),
    )
    op.create_index("ix_assistant_conversations_user", "assistant_conversations", ["owner_id", "user_id",
                                                                                   "updated_at"])
    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(64),
                  sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE",
                                name="fk_assistant_turns_conversation_id_assistant_conversations"), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("context", _json(), nullable=True),
        sa.Column("allow_whatif", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("steps", _json(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("citations", _json(), nullable=False),
        sa.Column("drafts", _json(), nullable=False),
        sa.Column("tool_log", _json(), nullable=True),
        sa.Column("error", _json(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("fallback_code", sa.String(64), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("tokens_cache_read", sa.Integer(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        _ts("created_at", False), _ts("started_at"), _ts("finished_at"), _ts("heartbeat_at"),
        _owner("assistant_turns"),
    )
    op.create_index("ix_assistant_turns_conversation", "assistant_turns", ["conversation_id", "created_at"])
    op.create_index("uq_assistant_turns_running", "assistant_turns", ["user_id"], unique=True,
                    postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index("ix_assistant_turns_created", "assistant_turns", ["created_at"])
    op.create_table(
        "assistant_refs",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(64),
                  sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE",
                                name="fk_assistant_refs_conversation_id_assistant_conversations"), nullable=False),
        sa.Column("ref_no", sa.Integer(), nullable=False),
        sa.Column("ref_type", sa.String(32), nullable=False),
        sa.Column("record_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("link", sa.String(300), nullable=False),
        _ts("created_at", False),
        _owner("assistant_refs"),
        sa.UniqueConstraint("conversation_id", "ref_no", name="uq_assistant_refs_no"),
    )
    op.create_index("ix_assistant_refs_record", "assistant_refs", ["conversation_id", "ref_type", "record_id"])
    op.create_table(
        "mfg_inventory_snapshots",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("item_family", sa.String(32), nullable=False),
        sa.Column("location_kind", sa.String(16), nullable=False),
        sa.Column("qty_value", sa.Double(), nullable=False),
        sa.Column("items", sa.Integer(), nullable=False),
        _ts("created_at", False),
        _owner("mfg_inventory_snapshots"),
        sa.UniqueConstraint("owner_id", "day", "item_family", "location_kind",
                            name="uq_mfg_inventory_snapshots_key"),
    )
    op.create_index("ix_mfg_inventory_snapshots_day", "mfg_inventory_snapshots", ["owner_id", "day"])
    op.create_table(
        "assistant_usage",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        _user("assistant_usage"),
        _user("assistant_usage", "owner_id"),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.UniqueConstraint("day", "user_id", "owner_id", name="uq_assistant_usage_key"),
    )
    op.create_index("ix_assistant_usage_owner_day", "assistant_usage", ["owner_id", "day"])
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        _user("push_subscriptions"),
        sa.Column("endpoint", sa.String(1000), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False),
        sa.Column("p256dh_enc", sa.Text(), nullable=False),
        sa.Column("auth_enc", sa.Text(), nullable=False),
        sa.Column("topics", _json(), nullable=False),
        sa.Column("user_agent", sa.String(300), nullable=False),
        _ts("created_at", False), _ts("last_success_at"),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "endpoint_hash", name="uq_push_subscriptions_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])
    op.create_table(
        "digest_subscriptions",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        _user("digest_subscriptions"),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("local_time", sa.String(5), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("time_zone", sa.String(64), nullable=False),
        _ts("created_at", False), _ts("last_sent_at"),
    )
    op.create_index("ix_digest_subscriptions_user", "digest_subscriptions", ["user_id"])


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    op.execute("DELETE FROM maintenance_runs WHERE kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_column("mfg_downtime", "acknowledged_at")
    op.drop_column("mfg_downtime", "acknowledged_by")
    op.drop_column("mfg_plant", "dashboard_thresholds")
    op.drop_column("mfg_plant", "assistant_allow_whatif")
    op.drop_column("mfg_plant", "assistant_enabled")
