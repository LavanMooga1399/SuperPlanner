"""M7 tables (M7-DESIGN 3) on the shared `Base`; migration `0010_m7` (expand).

Electronic signatures (`esig_*`), the quality module (`qa_*`), first-class holds (`mfg_lot_holds`) and Part 11
export records. Every table except `esig_stepups` (platform, per person) is owned by the plant (`owner_id`), carries
an owner-led index and an index led by every FK column; no server defaults (M1-M6 conventions).

Registries: `M7_OWNED_MODELS` (FK order; reset deletes them in reverse), `M7_PLATFORM_MODELS`, `M7_TABLES`.
Columns added to existing tables live on their ORM classes (users, audit_events, mfg_plant, work orders,
transactions, serials, floor events, orgs) and are listed in `M7_COLUMNS` for the migration test.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Double, ForeignKey, Index, Integer, LargeBinary, String, Text, \
    UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin
from .db_models import _Editable


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


def _s(n: int, nullable: bool = False) -> Any:
    return mapped_column(String(n), nullable=nullable)


def _j(nullable: bool = False) -> Any:
    return mapped_column(JsonType, nullable=nullable)


# ---------------------------------------------------------------- electronic signatures (4)

class EsigPolicyRow(OwnedMixin, _Editable, Base):
    __tablename__ = "esig_policies"
    __table_args__ = (UniqueConstraint("owner_id", "record_type", "action", name="uq_esig_policies_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_type: Mapped[str] = _s(32)
    action: Mapped[str] = _s(32)
    #: [{meaning, roles[]}] (4.3)
    steps: Mapped[list[dict[str, Any]]] = _j()
    auth: Mapped[str] = _s(16)                         # password | password_totp
    distinct_signers: Mapped[bool] = mapped_column(Boolean)
    exclude_author: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[int] = mapped_column(Integer)


class EsigSignatureRow(OwnedMixin, _Editable, Base):
    """A signature record (0.1). Only `status` (valid -> superseded) and the bookkeeping stamps ever change; the MAC
    covers every other column."""
    __tablename__ = "esig_signatures"
    __table_args__ = (Index("ix_esig_signatures_record", "owner_id", "record_type", "record_id"),
                      Index("ix_esig_signatures_signer", "signer_id", "signed_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_type: Mapped[str] = _s(32)
    record_id: Mapped[str] = _s(64)
    record_version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = _s(32)
    step: Mapped[int] = mapped_column(Integer)
    meaning: Mapped[str] = _s(16)
    signer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    signer_legal_name: Mapped[str] = _s(200)
    signer_username: Mapped[str] = _s(254)
    signed_at: Mapped[datetime] = _dt(False)
    auth_method: Mapped[str] = _s(16)                  # password | password_totp | sso | sso_mfa
    policy_id: Mapped[str | None] = _s(64, True)
    policy_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = _s(64)
    content: Mapped[dict[str, Any]] = _j()
    comment: Mapped[str] = _s(500)
    status: Mapped[str] = _s(16)                       # valid | superseded
    audit_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mac: Mapped[str] = _s(80)
    client_ip: Mapped[str | None] = _s(64, True)
    session_ref: Mapped[str | None] = _s(64, True)


class EsigStepupRow(Base):
    """Platform: single-use 5-minute OIDC step-up tokens (4.2 (3))."""
    __tablename__ = "esig_stepups"
    __table_args__ = (Index("ix_esig_stepups_user", "user_id"), Index("ix_esig_stepups_expires", "expires_at"))

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_ref: Mapped[str] = _s(64)
    amr: Mapped[list[str]] = _j()
    auth_time: Mapped[datetime] = _dt(False)
    expires_at: Mapped[datetime] = _dt(False)
    used_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- inspection (5)

class QaSamplingSchemeRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_sampling_schemes"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_qa_sampling_schemes_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    kind: Mapped[str] = _s(8)                          # fixed | percent | full | table
    fixed_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent: Mapped[float | None] = mapped_column(Double, nullable=True)
    table: Mapped[dict[str, Any] | None] = _j(True)
    switching: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = _s(16)                       # draft | approved | obsolete
    approved_at: Mapped[datetime | None] = _dt()
    author_id: Mapped[str | None] = _s(64, True)
    note: Mapped[str] = _s(500)


class QaInspectionPlanRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_inspection_plans"
    __table_args__ = (UniqueConstraint("owner_id", "number", "version", name="uq_qa_inspection_plans_number"),
                      Index("ix_qa_inspection_plans_key", "owner_id", "item_id", "scope", "status"),
                      Index("ix_qa_inspection_plans_item", "item_id"),
                      Index("ix_qa_inspection_plans_supplier", "supplier_id"),
                      Index("ix_qa_inspection_plans_scheme", "scheme_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = _s(200)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    scope: Mapped[str] = _s(16)                        # incoming | in_process | final
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_suppliers.id", ondelete="RESTRICT"),
                                                    nullable=True)
    customer: Mapped[str | None] = _s(100, True)
    scheme_id: Mapped[str] = mapped_column(ForeignKey("qa_sampling_schemes.id", ondelete="RESTRICT"))
    inspection_level: Mapped[str] = _s(8)
    aql: Mapped[dict[str, Any]] = _j()                 # {critical, major, minor}
    status: Mapped[str] = _s(16)                       # draft | approved | obsolete
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    supersedes_id: Mapped[str | None] = _s(64, True)
    approved_at: Mapped[datetime | None] = _dt()
    author_id: Mapped[str | None] = _s(64, True)
    note: Mapped[str] = _s(500)


class QaCharacteristicRow(OwnedMixin, Base):
    __tablename__ = "qa_characteristics"
    __table_args__ = (UniqueConstraint("plan_id", "seq", name="uq_qa_characteristics_seq"),
                      Index("ix_qa_characteristics_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("qa_inspection_plans.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    kind: Mapped[str] = _s(16)                         # variable | attribute
    severity: Mapped[str] = _s(16)                     # critical | major | minor
    unit: Mapped[str | None] = _s(16, True)
    nominal: Mapped[float | None] = mapped_column(Double, nullable=True)
    lsl: Mapped[float | None] = mapped_column(Double, nullable=True)
    usl: Mapped[float | None] = mapped_column(Double, nullable=True)
    method: Mapped[str] = _s(500)
    equipment_class: Mapped[str | None] = _s(32, True)
    sample_override: Mapped[dict[str, Any] | None] = _j(True)
    destructive: Mapped[bool] = mapped_column(Boolean)


class QaInspectionLotRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_inspection_lots"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_inspection_lots_number"),
                      Index("ix_qa_inspection_lots_status", "owner_id", "status", "scope"),
                      Index("ix_qa_inspection_lots_plan", "plan_id"),
                      Index("ix_qa_inspection_lots_item", "item_id"),
                      Index("ix_qa_inspection_lots_lot", "lot_id"),
                      Index("ix_qa_inspection_lots_wo", "wo_id"),
                      Index("ix_qa_inspection_lots_wo_operation", "wo_operation_id"),
                      Index("ix_qa_inspection_lots_due", "owner_id", "due_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    plan_id: Mapped[str] = mapped_column(ForeignKey("qa_inspection_plans.id", ondelete="RESTRICT"))
    plan_version: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = _s(16)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    lot_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lots.id", ondelete="RESTRICT"), nullable=True)
    wo_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="RESTRICT"), nullable=True)
    wo_operation_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_wo_operations.id", ondelete="RESTRICT"),
                                                        nullable=True)
    posting_id: Mapped[str | None] = _s(64, True)
    supplier_id: Mapped[str | None] = _s(64, True)
    customer: Mapped[str | None] = _s(100, True)
    lot_size: Mapped[float] = mapped_column(Double)
    #: {characteristic_id: {n, ac, re, severity_state, aql}} frozen at creation
    sampling: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(16)                       # open | in_progress | ready | accepted | rejected | cancelled
    verdict: Mapped[dict[str, Any] | None] = _j(True)
    decision: Mapped[str | None] = _s(8, True)         # accept | reject
    decided_by: Mapped[str | None] = _s(64, True)
    decided_at: Mapped[datetime | None] = _dt()
    decision_note: Mapped[str] = _s(500)
    ncr_id: Mapped[str | None] = _s(64, True)
    hold: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = _s(16)                       # po_receipt | floor | wo_receipt | manual
    due_at: Mapped[datetime | None] = _dt()


class QaResultRow(OwnedMixin, Base):
    """Append-only; corrections are new rows (`corrects_result_id`), the corrected row is marked `superseded`."""
    __tablename__ = "qa_results"
    __table_args__ = (Index("ix_qa_results_sample", "inspection_lot_id", "characteristic_id", "sample_no"),
                      Index("ix_qa_results_owner_equipment", "owner_id", "equipment_id", "entered_at"),
                      Index("ix_qa_results_batch", "owner_id", "client_batch_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    inspection_lot_id: Mapped[str] = mapped_column(ForeignKey("qa_inspection_lots.id", ondelete="CASCADE"))
    characteristic_id: Mapped[str] = _s(64)
    sample_no: Mapped[int] = mapped_column(Integer)
    value: Mapped[float | None] = mapped_column(Double, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    defects: Mapped[int] = mapped_column(Integer)
    equipment_id: Mapped[str | None] = _s(64, True)
    note: Mapped[str] = _s(500)
    reason: Mapped[str | None] = _s(500, True)
    entered_by: Mapped[str] = _s(64)
    entered_at: Mapped[datetime] = _dt(False)
    corrects_result_id: Mapped[str | None] = _s(64, True)
    superseded: Mapped[bool] = mapped_column(Boolean)
    client_batch_id: Mapped[str | None] = _s(64, True)


class QaResultBatchRow(OwnedMixin, Base):
    """Replay record of a results batch (`client_batch_id` -> stored response, 5.2)."""
    __tablename__ = "qa_result_batches"
    __table_args__ = (UniqueConstraint("owner_id", "client_batch_id", name="uq_qa_result_batches_key"),
                      Index("ix_qa_result_batches_lot", "inspection_lot_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_batch_id: Mapped[str] = _s(64)
    inspection_lot_id: Mapped[str] = mapped_column(ForeignKey("qa_inspection_lots.id", ondelete="CASCADE"))
    request_hash: Mapped[str] = _s(64)
    response: Mapped[dict[str, Any]] = _j()
    created_at: Mapped[datetime] = _dt(False)


class QaSwitchingStateRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_switching_states"
    __table_args__ = (UniqueConstraint("owner_id", "plan_key", name="uq_qa_switching_states_key"),
                      Index("ix_qa_switching_states_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: plan number (versions share the state) | supplier id or '-'
    plan_key: Mapped[str] = _s(120)
    plan_number: Mapped[str] = _s(32)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="CASCADE"))
    supplier_id: Mapped[str | None] = _s(64, True)
    state: Mapped[str] = _s(16)                        # normal | tightened
    history: Mapped[list[Any]] = _j()                 # last decisions, newest last ("A"/"R")


# ---------------------------------------------------------------- holds (5.3)

class MfgLotHoldRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_lot_holds"
    __table_args__ = (Index("ix_mfg_lot_holds_open_lot", "lot_id", postgresql_where=text("released_at IS NULL")),
                      Index("ix_mfg_lot_holds_lot", "lot_id"),
                      Index("ix_mfg_lot_holds_serial", "serial_id"),
                      Index("ix_mfg_lot_holds_item", "item_id"),
                      Index("ix_mfg_lot_holds_source", "owner_id", "source", "source_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lot_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lots.id", ondelete="RESTRICT"), nullable=True)
    serial_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_unit_serials.id", ondelete="RESTRICT"),
                                                  nullable=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    source: Mapped[str] = _s(16)                       # inspection | ncr | recall | field_action | manual
    source_id: Mapped[str | None] = _s(64, True)
    reason: Mapped[str] = _s(500)
    placed_by: Mapped[str] = _s(64)
    placed_at: Mapped[datetime] = _dt(False)
    released_by: Mapped[str | None] = _s(64, True)
    released_at: Mapped[datetime | None] = _dt()
    release_signature_id: Mapped[str | None] = _s(64, True)
    release_note: Mapped[str] = _s(500)


# ---------------------------------------------------------------- NCR / CAPA / complaints / field actions (6, 7)

class QaNcrRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_ncrs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_ncrs_number"),
                      Index("ix_qa_ncrs_status", "owner_id", "status"),
                      Index("ix_qa_ncrs_item", "item_id"),
                      Index("ix_qa_ncrs_lot", "lot_id"),
                      Index("ix_qa_ncrs_wo_operation", "owner_id", "wo_operation_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    title: Mapped[str] = _s(200)
    source: Mapped[str] = _s(16)                       # inspection | floor | complaint | supplier | internal | audit
    severity: Mapped[str] = _s(16)                     # critical | major | minor
    item_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"), nullable=True)
    lot_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lots.id", ondelete="RESTRICT"), nullable=True)
    serials: Mapped[list[str]] = _j()
    supplier_id: Mapped[str | None] = _s(64, True)
    wo_id: Mapped[str | None] = _s(64, True)
    wo_operation_id: Mapped[str | None] = _s(64, True)
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inspection_lot_id: Mapped[str | None] = _s(64, True)
    complaint_id: Mapped[str | None] = _s(64, True)
    place: Mapped[str] = _s(8)                         # stock | wip
    location_id: Mapped[str | None] = _s(64, True)
    qty_nc: Mapped[float] = mapped_column(Double)
    defect_codes: Mapped[list[str]] = _j()
    description: Mapped[str] = mapped_column(Text)
    containment: Mapped[str] = mapped_column(Text)
    investigation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = _s(16)       # draft | open | proposed | approved | implemented | closed | cancelled
    capa_required: Mapped[bool] = mapped_column(Boolean)
    author_id: Mapped[str] = _s(64)
    closed_at: Mapped[datetime | None] = _dt()
    external_ref: Mapped[str | None] = _s(64, True)


class QaNcrDispositionRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_ncr_dispositions"
    __table_args__ = (UniqueConstraint("ncr_id", "line_no", name="uq_qa_ncr_dispositions_line"),
                      Index("ix_qa_ncr_dispositions_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ncr_id: Mapped[str] = mapped_column(ForeignKey("qa_ncrs.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = _s(24)                         # scrap | rework | use_as_is | return_to_supplier
    qty: Mapped[float] = mapped_column(Double)
    location_id: Mapped[str | None] = _s(64, True)
    rework_routing_id: Mapped[str | None] = _s(64, True)
    rework_to_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str] = _s(2000)
    justification: Mapped[str] = _s(2000)
    implemented_at: Mapped[datetime | None] = _dt()
    refs: Mapped[dict[str, Any]] = _j()                # posting ids, WO id, floor event id


class QaCapaRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_capas"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_capas_number"),
                      Index("ix_qa_capas_status", "owner_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    title: Mapped[str] = _s(200)
    kind: Mapped[str] = _s(16)                         # corrective | preventive
    problem: Mapped[str] = mapped_column(Text)
    risk: Mapped[dict[str, Any] | None] = _j(True)
    owner_user_id: Mapped[str | None] = _s(64, True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    root_cause: Mapped[dict[str, Any] | None] = _j(True)
    effectiveness: Mapped[dict[str, Any] | None] = _j(True)
    status: Mapped[str] = _s(24)
    #: system of record at creation (review M7): superplanner | external
    sor: Mapped[str] = _s(16)
    author_id: Mapped[str] = _s(64)
    closed_at: Mapped[datetime | None] = _dt()
    external_ref: Mapped[str | None] = _s(64, True)


class QaCapaActionRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_capa_actions"
    __table_args__ = (UniqueConstraint("capa_id", "seq", name="uq_qa_capa_actions_seq"),
                      Index("ix_qa_capa_actions_owner", "owner_id", "owner_user_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capa_id: Mapped[str] = mapped_column(ForeignKey("qa_capas.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = _s(16)                         # correction | corrective | preventive
    description: Mapped[str] = _s(2000)
    owner_user_id: Mapped[str | None] = _s(64, True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = _s(16)                       # open | done | cancelled
    done_at: Mapped[datetime | None] = _dt()
    evidence: Mapped[str] = _s(2000)
    eco_id: Mapped[str | None] = _s(64, True)


class QaComplaintRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_complaints"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_complaints_number"),
                      Index("ix_qa_complaints_status", "owner_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    received_on: Mapped[date] = mapped_column(Date)
    aware_on: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = _s(32)
    customer: Mapped[str] = _s(200)
    country: Mapped[str | None] = _s(2, True)
    item_id: Mapped[str | None] = _s(64, True)
    lots: Mapped[list[dict[str, Any]]] = _j()          # [{code, lot_id|null}]
    serials: Mapped[list[dict[str, Any]]] = _j()       # [{code, serial_id|null}]
    qty_affected: Mapped[float | None] = mapped_column(Double, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = _s(32)                   # death | serious_injury | malfunction | other
    reportability: Mapped[dict[str, Any]] = _j()
    investigation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = _s(16)                       # open | investigation | closed
    sor: Mapped[str] = _s(16)                          # system of record at creation (review M7)
    author_id: Mapped[str] = _s(64)
    closed_at: Mapped[datetime | None] = _dt()
    external_ref: Mapped[str | None] = _s(64, True)


class QaFieldActionRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_field_actions"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_field_actions_number"),
                      Index("ix_qa_field_actions_recall", "recall_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    title: Mapped[str] = _s(200)
    kind: Mapped[str] = _s(16)
    class_: Mapped[str | None] = mapped_column("class", String(4), nullable=True)
    regimes: Mapped[list[str]] = _j()
    strategy: Mapped[str] = mapped_column(Text)
    recall_id: Mapped[str] = mapped_column(ForeignKey("mfg_recalls.id", ondelete="RESTRICT"))
    status: Mapped[str] = _s(16)
    complete_reason: Mapped[str | None] = _s(500, True)
    author_id: Mapped[str] = _s(64)
    closed_at: Mapped[datetime | None] = _dt()


class QaFieldActionUnitRow(OwnedMixin, Base):
    __tablename__ = "qa_field_action_units"
    __table_args__ = (Index("ix_qa_field_action_units_status", "field_action_id", "status"),
                      Index("ix_qa_field_action_units_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    field_action_id: Mapped[str] = mapped_column(ForeignKey("qa_field_actions.id", ondelete="CASCADE"))
    kind: Mapped[str] = _s(8)                          # serial | lot
    serial_id: Mapped[str | None] = _s(64, True)
    lot_id: Mapped[str | None] = _s(64, True)
    code: Mapped[str] = _s(64)                         # serial or lot code (CSV import key)
    item_id: Mapped[str] = _s(64)
    customer: Mapped[str] = _s(200)
    demand_line_id: Mapped[str | None] = _s(64, True)
    qty: Mapped[float] = mapped_column(Double)
    in_stock: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = _s(16)
    note: Mapped[str] = _s(500)
    updated_by: Mapped[str | None] = _s(64, True)
    updated_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- equipment and calibration (8)

class QaEquipmentRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_equipment"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_qa_equipment_code"),
                      Index("ix_qa_equipment_line", "line_id"),
                      Index("ix_qa_equipment_tool_pool", "tool_pool_id"),
                      Index("ix_qa_equipment_due", "owner_id", "due_on"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    kind: Mapped[str] = _s(16)
    equipment_class: Mapped[str] = _s(32)
    line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lines.id", ondelete="SET NULL"), nullable=True)
    tool_pool_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_tool_pools.id", ondelete="SET NULL"),
                                                     nullable=True)
    serial_no: Mapped[str] = _s(64)
    manufacturer: Mapped[str] = _s(100)
    location: Mapped[str] = _s(100)
    status: Mapped[str] = _s(16)                       # active | out_of_service | retired
    calibration_required: Mapped[bool] = mapped_column(Boolean)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grace_days: Mapped[int] = mapped_column(Integer)
    last_calibrated_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: the date of the last failed calibration (return to service needs a passing one after it)
    failed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    procedure_ref: Mapped[str] = _s(100)
    provider: Mapped[str] = _s(16)                     # internal | external
    note: Mapped[str] = _s(500)


class QaCalibrationRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_calibrations"
    __table_args__ = (Index("ix_qa_calibrations_equipment", "equipment_id", "performed_on"),
                      Index("ix_qa_calibrations_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("qa_equipment.id", ondelete="RESTRICT"))
    performed_on: Mapped[date] = mapped_column(Date)
    performed_by: Mapped[str | None] = _s(64, True)
    provider_name: Mapped[str] = _s(200)
    result: Mapped[str] = _s(16)                       # pass | adjusted_pass | fail
    as_found: Mapped[str] = _s(2000)
    as_left: Mapped[str] = _s(2000)
    certificate_ref: Mapped[str] = _s(200)
    next_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)


# ---------------------------------------------------------------- attachments, links, exports (9, 4.5)

class QaAttachmentRow(OwnedMixin, Base):
    __tablename__ = "qa_attachments"
    __table_args__ = (Index("ix_qa_attachments_entity", "owner_id", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = _s(32)
    entity_id: Mapped[str] = _s(64)
    filename: Mapped[str] = _s(200)
    content_type: Mapped[str] = _s(64)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = _s(64)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by: Mapped[str] = _s(64)
    uploaded_at: Mapped[datetime] = _dt(False)


class QaLinkRow(OwnedMixin, Base):
    __tablename__ = "qa_links"
    __table_args__ = (UniqueConstraint("owner_id", "from_type", "from_id", "to_type", "to_id", name="uq_qa_links_key"),
                      Index("ix_qa_links_to", "owner_id", "to_type", "to_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_type: Mapped[str] = _s(32)
    from_id: Mapped[str] = _s(64)
    to_type: Mapped[str] = _s(32)
    to_id: Mapped[str] = _s(64)
    created_by: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)


class Part11ExportRow(OwnedMixin, _Editable, Base):
    __tablename__ = "part11_exports"
    __table_args__ = (Index("ix_part11_exports_owner", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(16)                       # queued | running | completed | failed
    file_path: Mapped[str | None] = _s(500, True)
    manifest: Mapped[dict[str, Any] | None] = _j(True)
    sha256: Mapped[str | None] = _s(64, True)
    error: Mapped[str | None] = _s(500, True)
    requested_by: Mapped[str] = _s(64)
    finished_at: Mapped[datetime | None] = _dt()


M7_OWNED_MODELS: tuple[type[Base], ...] = (
    EsigPolicyRow, EsigSignatureRow, QaSamplingSchemeRow, QaInspectionPlanRow, QaCharacteristicRow,
    QaInspectionLotRow, QaResultRow, QaResultBatchRow, QaSwitchingStateRow, MfgLotHoldRow, QaNcrRow,
    QaNcrDispositionRow, QaCapaRow, QaCapaActionRow, QaComplaintRow, QaFieldActionRow, QaFieldActionUnitRow,
    QaEquipmentRow, QaCalibrationRow, QaAttachmentRow, QaLinkRow, Part11ExportRow)
M7_PLATFORM_MODELS: tuple[type[Base], ...] = (EsigStepupRow,)
M7_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M7_PLATFORM_MODELS + M7_OWNED_MODELS)
#: reset (M2 9.4) deletes the plant's M7 rows (in reverse) with its data; signatures and policies go too (a reset is
#: refused for Part 11 plants, services/part11.reset_allowed)
M7_RESET_MODELS: tuple[type[Base], ...] = M7_OWNED_MODELS
#: (table, column) pairs added to existing tables by 0010_m7
M7_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "legal_name"), ("users", "esig_enrolled_at"), ("users", "esig_ack_version"),
    ("users", "esig_revoked_at"), ("users", "esig_failed"), ("users", "esig_locked_until"),
    ("users", "esig_password_hash"),
    ("audit_events", "changes"), ("audit_events", "reason"), ("audit_events", "signature_id"),
    ("audit_events", "record_version"),
    ("mfg_plant", "part11_mode"), ("mfg_plant", "qa_settings"),
    ("mfg_work_orders", "kind"), ("mfg_work_orders", "ncr_id"), ("mfg_inv_transactions", "ncr_id"),
    ("mfg_unit_serials", "hold"), ("mfg_floor_events", "qty_nc"), ("mfg_floor_events", "ncr_id"),
    ("mfg_floor_events", "defect_code"), ("orgs", "session_idle_minutes"))
