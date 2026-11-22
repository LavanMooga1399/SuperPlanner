"""UX upgrade backend support (docs/UX-STANDARD.md "Backend support"): `user_preferences` (per person, one small
JSON document per key) and `mfg_bulk_requests` (plant-owned Idempotency-Key replay records of bulk actions).

Revision ID: 0009_ux
Revises: 0008_m6
Create Date: 2026-11-22

Policy: expand. Frozen migration: literal definitions only. Two new tables, nothing else; the app role gets its
privileges through the owner's default privileges (scripts/pg_setup_roles.sql). Downgrade drops both tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_ux"
down_revision = "0008_m6"
branch_labels = None
depends_on = None
policy = "expand"

TABLES = ("user_preferences", "mfg_bulk_requests")


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE",
                                                          name="fk_user_preferences_user_id_users"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", _json(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        _ts("created_at"), _ts("updated_at"),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_user_preferences"),
    )
    op.create_table(
        "mfg_bulk_requests",
        sa.Column("id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("response", _json(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT",
                                                           name="fk_mfg_bulk_requests_owner_id_users"),
                  nullable=False),
        sa.UniqueConstraint("owner_id", "actor_id", "idempotency_key", name="uq_mfg_bulk_requests_key"),
    )
    op.create_index("ix_mfg_bulk_requests_created", "mfg_bulk_requests", ["created_at"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
