"""M5 tables (M5-DESIGN 10) on the shared `Base`; migration `0007_m5`.

Identity and organisation tables are platform tables (not owned, like `users`); integration and mfg tables are
owned by the plant (`owner_id`, M2 0 decision 10: one owner = one plant). Registries: `M5_OWNED_MODELS` (FK order,
reset deletes them in reverse), `M5_PLATFORM_MODELS`, `M5_TABLES`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (text, BigInteger, Boolean, Date, DateTime, Double, ForeignKey, Identity, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin
from .db_models import _Editable
from .db_models_m4 import ALL_MFG_MODELS as _M1_M4_MODELS


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


def _s(n: int, nullable: bool = False) -> Any:
    return mapped_column(String(n), nullable=nullable)


# ---------------------------------------------------------------- identity (3.1-3.3), platform tables

class UserIdentityRow(Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("issuer", "sub", name="uq_user_identities_sub"),
                      Index("ix_user_identities_user", "user_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    issuer: Mapped[str] = _s(300)
    sub: Mapped[str] = _s(255)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str | None] = _s(254, True)
    created_at: Mapped[datetime] = _dt(False)
    last_login_at: Mapped[datetime | None] = _dt()


class UserTotpRow(Base):
    __tablename__ = "user_totp"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    secret_enc: Mapped[str] = mapped_column(Text)
    enabled_at: Mapped[datetime | None] = _dt()
    last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recovery_hashes: Mapped[list[str]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = _dt(False)


class OidcStateRow(Base):
    __tablename__ = "oidc_states"
    __table_args__ = (Index("ix_oidc_states_expires", "expires_at"),)

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)   # sha256 of the state (I4)
    nonce: Mapped[str] = _s(128)
    verifier_enc: Mapped[str] = mapped_column(Text)
    next_url: Mapped[str] = _s(500)
    expires_at: Mapped[datetime] = _dt(False)


class PendingLoginRow(Base):
    """Password verified, TOTP pending (3.2: 5 minutes)."""
    __tablename__ = "auth_pending_logins"
    __table_args__ = (Index("ix_auth_pending_logins_user", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = _dt(False)
    attempts: Mapped[int] = mapped_column(Integer)


class ApiTokenRow(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_api_tokens_hash"),
                      Index("ix_api_tokens_user", "user_id"), Index("ix_api_tokens_workspace", "workspace_owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = _s(16)                                  # personal | plant
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = _s(100)
    token_hash: Mapped[str] = _s(64)
    prefix: Mapped[str] = _s(16)
    scopes: Mapped[list[str]] = mapped_column(JsonType)
    workspace_owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = _dt(False)
    last_used_at: Mapped[datetime | None] = _dt()
    last_used_ip: Mapped[str | None] = _s(64, True)
    created_by: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    revoked_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- organisations (3.4), platform tables

class OrgRow(Base):
    __tablename__ = "orgs"
    __table_args__ = (UniqueConstraint("slug", name="uq_orgs_slug"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = _s(200)
    slug: Mapped[str] = _s(64)
    require_2fa: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _dt(False)
    updated_at: Mapped[datetime] = _dt(False)
    row_version: Mapped[int] = mapped_column(Integer)


class OrgMemberRow(Base):
    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_members_user"),
                      Index("ix_org_members_user", "user_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    org_role: Mapped[str] = _s(16)                              # org_admin | org_member
    #: 15.WP-S: None = invited, not yet accepted (ORG_SELF_SERVICE=false); the org manages the user only after
    accepted_at: Mapped[datetime | None] = _dt()
    created_at: Mapped[datetime] = _dt(False)
    row_version: Mapped[int] = mapped_column(Integer)


class OrgPlantRow(Base):
    __tablename__ = "org_plants"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_org_plants_code"),
                      UniqueConstraint("plant_owner_id", name="uq_org_plants_owner"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    plant_owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    code: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    created_at: Mapped[datetime] = _dt(False)
    row_version: Mapped[int] = mapped_column(Integer)


class OrgPublishRow(Base):
    """A master-data publish run (3.4; job kind `org_publish`)."""
    __tablename__ = "org_publishes"
    __table_args__ = (Index("ix_org_publishes_org", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    source_owner_id: Mapped[str] = _s(64)
    target_owner_ids: Mapped[list[str]] = mapped_column(JsonType)
    scope: Mapped[str] = _s(16)
    part_number_prefix: Mapped[str | None] = _s(64, True)
    status: Mapped[str] = _s(16)
    results: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    actor_id: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    finished_at: Mapped[datetime | None] = _dt()


class MaintenanceRunRow(Base):
    """Retention / archive / trace backfill runs (7, 6.1; job kinds `maintenance_retention`, `trace_backfill`)."""
    __tablename__ = "maintenance_runs"
    __table_args__ = (Index("ix_maintenance_runs_kind", "kind", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = _s(32)
    owner_scope_id: Mapped[str | None] = _s(64, True)          # None = every owner
    status: Mapped[str] = _s(16)
    params: Mapped[dict[str, Any]] = mapped_column(JsonType)
    results: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = _dt(False)
    finished_at: Mapped[datetime | None] = _dt()


class AuditChainHeadRow(Base):
    """Per-owner head of the audit hash chain (`owner_key` '' = platform): last id / hash and a keyed MAC over them,
    written at commit - detects deleted newest rows (15.WP-S)."""
    __tablename__ = "audit_chain_heads"

    owner_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_id: Mapped[int] = mapped_column(BigInteger)
    head_hash: Mapped[str] = _s(80)
    mac: Mapped[str] = _s(80)
    updated_at: Mapped[datetime] = _dt(False)


# ---------------------------------------------------------------- integration (4.1), owned by the plant

class IntSettingsRow(OwnedMixin, _Editable, Base):
    __tablename__ = "int_settings"
    __table_args__ = (UniqueConstraint("owner_id", name="uq_int_settings_owner"),
                      # plant codes name the file-drop folders: unique across plants (15.WP-S)
                      Index("uq_int_settings_plant_code", text("lower(plant_code)"), unique=True,
                            postgresql_where=text("plant_code <> ''")))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    adapter: Mapped[str] = _s(32)
    plant_code: Mapped[str] = _s(32)
    sor: Mapped[dict[str, str]] = mapped_column(JsonType)                 # entity -> erp | superplanner | shared
    goods_receipts_owner: Mapped[str] = _s(16)                           # erp | superplanner (14 Q2)
    filedrop_enabled: Mapped[bool] = mapped_column(Boolean)
    export_enabled: Mapped[bool] = mapped_column(Boolean)
    export_interval_minutes: Mapped[int] = mapped_column(Integer)
    export_cursor: Mapped[int] = mapped_column(BigInteger)


class IntEndpointRow(OwnedMixin, _Editable, Base):
    __tablename__ = "int_endpoints"
    __table_args__ = (Index("ix_int_endpoints_owner", "owner_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = _s(100)
    url: Mapped[str] = _s(500)
    event_types: Mapped[list[str]] = mapped_column(JsonType)
    secret_enc: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    cursor: Mapped[int] = mapped_column(BigInteger)                      # last delivered seq (FIFO)


class IntValueMapRow(OwnedMixin, Base):
    __tablename__ = "int_value_maps"
    __table_args__ = (UniqueConstraint("owner_id", "domain", "external_value", name="uq_int_value_maps_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = _s(32)                                         # uom | location | reason | status
    external_value: Mapped[str] = _s(64)
    internal_value: Mapped[str] = _s(64)


class IntMappingProfileRow(OwnedMixin, _Editable, Base):
    __tablename__ = "int_mapping_profiles"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_int_mapping_profiles_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = _s(100)
    file_pattern: Mapped[str] = _s(200)
    mapping: Mapped[dict[str, Any]] = mapped_column(JsonType)


class IntSyncStateRow(OwnedMixin, Base):
    """4.4 `shared` SoR: the row version an inbound write left on a record, and the last conflict (both sides
    changed the record since the previous sync), reported by reconciliation (`sor_conflicts`)."""
    __tablename__ = "int_sync_state"
    __table_args__ = (UniqueConstraint("owner_id", "entity", "record_id", name="uq_int_sync_state_record"),
                      Index("ix_int_sync_state_conflicts", "owner_id", "conflict_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity: Mapped[str] = _s(32)
    record_id: Mapped[str] = _s(64)
    ref: Mapped[str | None] = _s(64, True)
    synced_version: Mapped[int] = mapped_column(Integer)
    synced_at: Mapped[datetime] = _dt(False)
    conflict: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    conflict_at: Mapped[datetime | None] = _dt()


class IntInboxRow(OwnedMixin, Base):
    __tablename__ = "int_inbox"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_int_inbox_idem"),
                      Index("ix_int_inbox_owner_received", "owner_id", "received_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = _s(16)                                         # rest | filedrop
    idempotency_key: Mapped[str] = _s(128)
    entity: Mapped[str] = _s(32)
    mode: Mapped[str] = _s(24)
    status: Mapped[str] = _s(16)
    counts: Mapped[dict[str, int]] = mapped_column(JsonType)
    results: Mapped[list[Any] | None] = mapped_column(JsonType, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)   # purged after 30 days (7)
    payload_hash: Mapped[str] = _s(64)
    actor_id: Mapped[str] = _s(64)
    received_at: Mapped[datetime] = _dt(False)
    finished_at: Mapped[datetime | None] = _dt()


class IntOutboxRow(OwnedMixin, Base):
    __tablename__ = "int_outbox"
    __table_args__ = (Index("ix_int_outbox_owner_seq", "owner_id", "seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    type: Mapped[str] = _s(48)
    entity_ref: Mapped[str | None] = _s(64, True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)
    actor_id: Mapped[str | None] = _s(64, True)
    occurred_at: Mapped[datetime] = _dt(False)


class IntDeliveryRow(OwnedMixin, Base):
    __tablename__ = "int_deliveries"
    __table_args__ = (UniqueConstraint("endpoint_id", "event_seq", name="uq_int_deliveries_event"),
                      Index("ix_int_deliveries_due", "status", "next_attempt_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("int_endpoints.id", ondelete="CASCADE"))
    event_seq: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = _s(16)                                          # pending | delivered | dead
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime | None] = _dt()
    last_error: Mapped[str | None] = _s(500, True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = _dt()
    created_at: Mapped[datetime] = _dt(False)


class IntReconciliationRow(OwnedMixin, Base):
    __tablename__ = "int_reconciliations"
    __table_args__ = (Index("ix_int_reconciliations_owner", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entities: Mapped[list[str]] = mapped_column(JsonType)
    status: Mapped[str] = _s(16)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    results: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    actor_id: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    finished_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- ECO (5), genealogy (6), transfers (3.5)

class MfgChangeRequestRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_change_requests"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_change_requests_number"),
                      Index("ix_mfg_change_requests_owner_status", "owner_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    title: Mapped[str] = _s(200)
    reason: Mapped[str] = _s(1000)
    kind: Mapped[str] = _s(8)
    source: Mapped[str] = _s(8)
    status: Mapped[str] = _s(16)
    priority: Mapped[int] = mapped_column(Integer)
    requested_by: Mapped[str] = _s(64)
    submitted_by: Mapped[str | None] = _s(64, True)
    approved_by: Mapped[str | None] = _s(64, True)
    approved_at: Mapped[datetime | None] = _dt()
    implemented_at: Mapped[datetime | None] = _dt()
    effectivity: Mapped[dict[str, Any]] = mapped_column(JsonType)
    note: Mapped[str] = _s(1000)


class MfgChangeRequestItemRow(OwnedMixin, Base):
    __tablename__ = "mfg_change_request_items"
    __table_args__ = (UniqueConstraint("cr_id", "doc_id", name="uq_mfg_change_request_items_doc"),
                      Index("ix_mfg_change_request_items_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cr_id: Mapped[str] = mapped_column(ForeignKey("mfg_change_requests.id", ondelete="CASCADE"))
    doc_type: Mapped[str] = _s(8)
    doc_id: Mapped[str] = _s(64)
    supersedes_doc_id: Mapped[str | None] = _s(64, True)
    disposition: Mapped[dict[str, Any]] = mapped_column(JsonType)


class MfgTraceEdgeRow(OwnedMixin, Base):
    __tablename__ = "mfg_trace_edges"
    __table_args__ = (Index("ix_mfg_trace_edges_from", "owner_id", "from_kind", "from_id"),
                      Index("ix_mfg_trace_edges_to", "owner_id", "to_kind", "to_id"),
                      Index("ix_mfg_trace_edges_from_item", "from_item_id"),
                      Index("uq_mfg_trace_edges_source", "source_key", unique=True))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_kind: Mapped[str] = _s(16)
    from_id: Mapped[str] = _s(64)
    from_item_id: Mapped[str | None] = _s(64, True)
    to_kind: Mapped[str] = _s(16)
    to_id: Mapped[str] = _s(64)
    to_item_id: Mapped[str | None] = _s(64, True)
    qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    precision: Mapped[str] = _s(8)                                        # exact | possible
    event_at: Mapped[datetime] = _dt(False)
    posting_id: Mapped[str | None] = _s(64, True)
    floor_event_id: Mapped[str | None] = _s(64, True)
    plant_owner_id: Mapped[str | None] = _s(64, True)                     # the other plant of a cross-plant edge
    #: idempotency of writers / backfill: "<posting|event id>:<from_id>:<to_id>"
    source_key: Mapped[str] = _s(200)


class MfgRecallRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_recalls"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_recalls_number"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JsonType)
    include_possible: Mapped[bool] = mapped_column(Boolean)
    report: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    quarantined_at: Mapped[datetime | None] = _dt()
    actor_id: Mapped[str] = _s(64)


class MfgTransferOrderRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_transfer_orders"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_transfer_orders_number"),
                      Index("ix_mfg_transfer_orders_owner_status", "owner_id", "status"),
                      Index("ix_mfg_transfer_orders_mirror", "mirror_of"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    direction: Mapped[str] = _s(8)                                        # out (source) | in (destination mirror)
    status: Mapped[str] = _s(16)
    source_owner_id: Mapped[str] = _s(64)
    dest_owner_id: Mapped[str] = _s(64)
    mirror_of: Mapped[str | None] = _s(64, True)
    from_location_id: Mapped[str | None] = _s(64, True)
    to_location_id: Mapped[str | None] = _s(64, True)
    note: Mapped[str] = _s(500)


class MfgTransferLineRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_transfer_lines"
    __table_args__ = (UniqueConstraint("order_id", "line_no", name="uq_mfg_transfer_lines_no"),
                      Index("ix_mfg_transfer_lines_owner", "owner_id"), Index("ix_mfg_transfer_lines_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("mfg_transfer_orders.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(Double)
    shipped_qty: Mapped[float] = mapped_column(Double)
    received_qty: Mapped[float] = mapped_column(Double)
    ship_date: Mapped[date] = mapped_column(Date)
    receive_date: Mapped[date] = mapped_column(Date)
    mirror_line_id: Mapped[str | None] = _s(64, True)
    in_transit: Mapped[list[dict[str, Any]]] = mapped_column(JsonType)   # shipped lots awaiting receipt


M5_PLATFORM_MODELS: tuple[type[Base], ...] = (UserIdentityRow, UserTotpRow, OidcStateRow, PendingLoginRow, ApiTokenRow,
                                              OrgRow, OrgMemberRow, OrgPlantRow, OrgPublishRow, MaintenanceRunRow,
                                              AuditChainHeadRow)
M5_OWNED_MODELS: tuple[type[Base], ...] = (IntSettingsRow, IntEndpointRow, IntValueMapRow, IntMappingProfileRow,
                                           IntInboxRow, IntOutboxRow, IntDeliveryRow, IntReconciliationRow,
                                           MfgChangeRequestRow, MfgChangeRequestItemRow, MfgTraceEdgeRow, MfgRecallRow,
                                           MfgTransferOrderRow, MfgTransferLineRow, IntSyncStateRow)
M5_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M5_PLATFORM_MODELS + M5_OWNED_MODELS)
#: reset (M2 9.4) deletes these in reverse; trace edges are append-only traceability (I3) but belong to the plant's
#: data like the ledger, so a reset (which also deletes the ledger) removes them too
ALL_MFG_MODELS: tuple[type[Base], ...] = _M1_M4_MODELS + M5_OWNED_MODELS
ALL_MFG_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in ALL_MFG_MODELS)
