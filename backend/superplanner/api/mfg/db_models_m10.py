"""M10 tables (M10-DESIGN 3) on the shared `Base`; migration `0013_m10` (expand). All plant-owned.

eDHR records and their exceptions, deviations, customer agreements, CoAs, batch packs, document renditions, UDI
device records, label templates / assignments / printers / print jobs / print events (append-only), UDI exports
and validation packages. Columns on existing tables live on their ORM classes (orgs.data_region,
mfg_item_planning.dhr_required, mfg_operations.max_minutes / max_wait_minutes, int_endpoints.region /
cross_region_signature_id) and are listed in `M10_COLUMNS`. No server defaults (M1-M9 conventions).
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


def _f(nullable: bool = False) -> Any:
    return mapped_column(Double, nullable=nullable)


def _i(nullable: bool = False) -> Any:
    return mapped_column(Integer, nullable=nullable)


def _b(nullable: bool = False) -> Any:
    return mapped_column(Boolean, nullable=nullable)


def _id() -> Any:
    return mapped_column(String(64), primary_key=True)


# ---------------------------------------------------------------- eDHR (4)

class DhrRecordRow(OwnedMixin, _Editable, Base):
    __tablename__ = "dhr_records"
    __table_args__ = (UniqueConstraint("owner_id", "number", "version", name="uq_dhr_records_number"),
                      Index("ix_dhr_records_status", "owner_id", "status"),
                      Index("ix_dhr_records_lot", "lot_id"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    version: Mapped[int] = _i()
    subject_kind: Mapped[str] = _s(4)
    lot_id: Mapped[str | None] = _s(64, True)
    wo_ids: Mapped[list[str]] = _j()
    item_id: Mapped[str] = _s(64)
    item_revision: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(12)
    supersedes_id: Mapped[str | None] = _s(64, True)
    superseded_by_id: Mapped[str | None] = _s(64, True)
    changed_after_release: Mapped[bool] = _b()
    assembled_at: Mapped[datetime] = _dt(False)
    content: Mapped[dict[str, Any]] = _j()
    content_sha256: Mapped[str] = _s(64)
    section_hashes: Mapped[dict[str, Any]] = _j()
    counts: Mapped[dict[str, Any]] = _j()
    hold_id: Mapped[str | None] = _s(64, True)
    released_at: Mapped[datetime | None] = _dt()
    decision: Mapped[str | None] = _s(8, True)
    rendition_id: Mapped[str | None] = _s(64, True)
    renderer_version: Mapped[str | None] = _s(16, True)
    reassemble_reason: Mapped[str | None] = _s(500, True)


class DhrExceptionRow(OwnedMixin, _Editable, Base):
    __tablename__ = "dhr_exceptions"
    __table_args__ = (Index("ix_dhr_exceptions_record", "record_id", "severity"),
                      Index("ix_dhr_exceptions_owner", "owner_id"))

    id: Mapped[str] = _id()
    record_id: Mapped[str] = mapped_column(ForeignKey("dhr_records.id", ondelete="CASCADE"))
    code: Mapped[str] = _s(32)
    severity: Mapped[str] = _s(5)
    section: Mapped[str] = _s(16)
    ref_type: Mapped[str] = _s(24)
    ref_id: Mapped[str | None] = _s(64, True)
    ref_number: Mapped[str | None] = _s(32, True)
    message: Mapped[str] = _s(500)
    data: Mapped[dict[str, Any]] = _j()
    fingerprint: Mapped[str] = _s(64)
    disposition: Mapped[str | None] = _s(10, True)
    disposition_ref: Mapped[str | None] = _s(64, True)
    comment: Mapped[str | None] = _s(1000, True)
    carried: Mapped[bool] = _b()
    reviewed_by: Mapped[str | None] = _s(64, True)
    reviewed_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- deviations (4.4)

class QaDeviationRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_deviations"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_deviations_number"),
                      Index("ix_qa_deviations_status", "owner_id", "status"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    kind: Mapped[str] = _s(10)
    title: Mapped[str] = _s(200)
    description: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict[str, Any]] = _j()
    risk: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(10)
    ncr_id: Mapped[str | None] = _s(64, True)
    capa_id: Mapped[str | None] = _s(64, True)
    author_id: Mapped[str] = _s(64)
    approved_at: Mapped[datetime | None] = _dt()
    closed_at: Mapped[datetime | None] = _dt()
    outcome: Mapped[str | None] = _s(2000, True)
    external_ref: Mapped[str | None] = _s(64, True)


# ---------------------------------------------------------------- customer agreements, CoA, packs (6)

class QaCustomerAgreementRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_customer_agreements"
    __table_args__ = (UniqueConstraint("owner_id", "number", "version", name="uq_qa_customer_agreements_number"),
                      Index("ix_qa_customer_agreements_customer", "owner_id", "customer"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    version: Mapped[int] = _i()
    customer: Mapped[str] = _s(100)
    title: Mapped[str] = _s(200)
    external_ref: Mapped[str] = _s(64)
    item_ids: Mapped[list[str]] = _j()
    coa: Mapped[dict[str, Any]] = _j()
    pack: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(10)
    supersedes_id: Mapped[str | None] = _s(64, True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)


class QaCoaRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_coas"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_coas_number"),
                      Index("ix_qa_coas_lot", "owner_id", "lot_id"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    agreement_id: Mapped[str] = _s(64)
    agreement_version: Mapped[int] = _i()
    lot_id: Mapped[str] = _s(64)
    dhr_id: Mapped[str] = _s(64)
    customer: Mapped[str] = _s(100)
    demand_line_id: Mapped[str | None] = _s(64, True)
    content: Mapped[dict[str, Any]] = _j()
    content_sha256: Mapped[str] = _s(64)
    status: Mapped[str] = _s(8)
    rendition_id: Mapped[str | None] = _s(64, True)
    void_reason: Mapped[str | None] = _s(500, True)


class QaBatchPackRow(OwnedMixin, _Editable, Base):
    __tablename__ = "qa_batch_packs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_qa_batch_packs_number"),)

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    agreement_id: Mapped[str] = _s(64)
    lot_ids: Mapped[list[str]] = _j()
    customer: Mapped[str] = _s(100)
    demand_line_id: Mapped[str | None] = _s(64, True)
    status: Mapped[str] = _s(10)
    documents: Mapped[list[Any]] = _j()
    rendition_id: Mapped[str | None] = _s(64, True)
    error: Mapped[str | None] = _s(2000, True)


class DocRenditionRow(OwnedMixin, Base):
    """Append-only generated documents (PDF / JSON / zip / ZPL / CSV / xlsx); <= 5 MB inline, else a file under
    `ARCHIVE_DIR/<owner>/renditions/`."""
    __tablename__ = "doc_renditions"
    __table_args__ = (Index("ix_doc_renditions_entity", "entity_type", "entity_id"),
                      Index("ix_doc_renditions_owner", "owner_id"))

    id: Mapped[str] = _id()
    entity_type: Mapped[str] = _s(24)
    entity_id: Mapped[str] = _s(64)
    entity_version: Mapped[int] = _i()
    kind: Mapped[str] = _s(4)
    filename: Mapped[str] = _s(200)
    sha256: Mapped[str] = _s(64)
    size: Mapped[int] = _i()
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    file_path: Mapped[str | None] = _s(500, True)
    renderer_version: Mapped[str] = _s(16)
    meta: Mapped[dict[str, Any]] = _j()
    created_by: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)


# ---------------------------------------------------------------- UDI and labels (7)

class UdiDeviceRecordRow(OwnedMixin, _Editable, Base):
    __tablename__ = "udi_device_records"
    __table_args__ = (UniqueConstraint("packaging_id", name="uq_udi_device_records_packaging"),
                      Index("ix_udi_device_records_item", "owner_id", "item_id"),
                      Index("ix_udi_device_records_gtin", "owner_id", "gtin"))

    id: Mapped[str] = _id()
    packaging_id: Mapped[str] = mapped_column(ForeignKey("mfg_item_packaging.id", ondelete="RESTRICT"))
    item_id: Mapped[str] = _s(64)
    gtin: Mapped[str] = _s(14)
    di_kind: Mapped[str] = _s(12)
    qty_per_package: Mapped[int] = _i()
    contains_gtin: Mapped[str | None] = _s(14, True)
    pi_flags: Mapped[dict[str, Any]] = _j()
    attrs: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(10)
    commercial_distribution_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class LblTemplateRow(OwnedMixin, _Editable, Base):
    __tablename__ = "lbl_templates"
    __table_args__ = (UniqueConstraint("owner_id", "code", "version", name="uq_lbl_templates_code"),
                      Index("ix_lbl_templates_status", "owner_id", "status"))

    id: Mapped[str] = _id()
    code: Mapped[str] = _s(32)
    version: Mapped[int] = _i()
    name: Mapped[str] = _s(200)
    level: Mapped[str] = _s(8)
    width_mm: Mapped[float] = _f()
    height_mm: Mapped[float] = _f()
    dpi: Mapped[int] = _i()
    languages: Mapped[list[str]] = _j()
    elements: Mapped[list[Any]] = _j()
    status: Mapped[str] = _s(10)
    eco_id: Mapped[str | None] = _s(64, True)
    approved_at: Mapped[datetime | None] = _dt()
    supersedes_id: Mapped[str | None] = _s(64, True)


class LblAssignmentRow(OwnedMixin, _Editable, Base):
    __tablename__ = "lbl_assignments"
    __table_args__ = (UniqueConstraint("item_id", "level", "customer", name="uq_lbl_assignments_key"),
                      Index("ix_lbl_assignments_owner", "owner_id"))

    id: Mapped[str] = _id()
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="CASCADE"))
    level: Mapped[str] = _s(8)
    customer: Mapped[str | None] = _s(100, True)
    template_code: Mapped[str] = _s(32)


class LblPrinterRow(OwnedMixin, _Editable, Base):
    __tablename__ = "lbl_printers"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_lbl_printers_code"),)

    id: Mapped[str] = _id()
    code: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    kind: Mapped[str] = _s(8)
    host: Mapped[str] = _s(253)
    port: Mapped[int] = _i()
    dpi: Mapped[int] = _i()
    line_id: Mapped[str | None] = _s(64, True)
    active: Mapped[bool] = _b()


class LblPrintJobRow(OwnedMixin, _Editable, Base):
    __tablename__ = "lbl_print_jobs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_lbl_print_jobs_number"),
                      Index("ix_lbl_print_jobs_lot", "owner_id", "lot_id"),
                      Index("ix_lbl_print_jobs_status", "owner_id", "status"),
                      Index("ix_lbl_print_jobs_udi", "udi_id"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    item_id: Mapped[str] = _s(64)
    level: Mapped[str] = _s(8)
    udi_id: Mapped[str] = _s(64)
    lot_id: Mapped[str] = _s(64)
    wo_id: Mapped[str | None] = _s(64, True)
    template_id: Mapped[str] = _s(64)
    qty: Mapped[int] = _i()
    serials: Mapped[list[str] | None] = _j(True)
    data: Mapped[dict[str, Any]] = _j()
    data_sha256: Mapped[str] = _s(64)
    output: Mapped[str] = _s(4)
    target: Mapped[str] = _s(8)
    printer_id: Mapped[str | None] = _s(64, True)
    status: Mapped[str] = _s(10)
    totals: Mapped[dict[str, Any]] = _j()
    recon_explanation: Mapped[str | None] = _s(1000, True)
    reconciled_at: Mapped[datetime | None] = _dt()


class LblPrintEventRow(OwnedMixin, Base):
    """Append-only."""
    __tablename__ = "lbl_print_events"
    __table_args__ = (Index("ix_lbl_print_events_job", "job_id", "at"),
                      Index("uq_lbl_print_events_client", "owner_id", "client_event_id", unique=True,
                            postgresql_where=text("client_event_id IS NOT NULL")))

    id: Mapped[str] = _id()
    job_id: Mapped[str] = mapped_column(ForeignKey("lbl_print_jobs.id", ondelete="CASCADE"))
    kind: Mapped[str] = _s(10)
    qty: Mapped[int] = _i()
    serials: Mapped[list[str] | None] = _j(True)
    position: Mapped[str | None] = _s(6, True)
    scan: Mapped[str | None] = _s(400, True)
    result: Mapped[str | None] = _s(8, True)
    mismatch: Mapped[dict[str, Any] | None] = _j(True)
    reason: Mapped[str | None] = _s(500, True)
    actor_id: Mapped[str] = _s(64)
    at: Mapped[datetime] = _dt(False)
    client_event_id: Mapped[str | None] = _s(64, True)


class UdiExportRow(OwnedMixin, _Editable, Base):
    __tablename__ = "udi_exports"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_udi_exports_number"),)

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    kind: Mapped[str] = _s(5)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(10)
    rule_version: Mapped[str] = _s(16)
    result: Mapped[dict[str, Any] | None] = _j(True)
    rendition_id: Mapped[str | None] = _s(64, True)


# ---------------------------------------------------------------- validation packages (8)

class ValPackageRow(OwnedMixin, _Editable, Base):
    __tablename__ = "val_packages"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_val_packages_number"),
                      Index("ix_val_packages_kind", "owner_id", "kind"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    kind: Mapped[str] = _s(10)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(10)
    baseline_id: Mapped[str | None] = _s(64, True)
    prev_baseline_id: Mapped[str | None] = _s(64, True)
    manifest: Mapped[dict[str, Any] | None] = _j(True)
    sha256: Mapped[str | None] = _s(64, True)
    file_path: Mapped[str | None] = _s(500, True)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    size: Mapped[int | None] = _i(True)
    error: Mapped[str | None] = _s(2000, True)


# ---------------------------------------------------------------- registries

#: FK order (reset deletes in reverse)
M10_OWNED_MODELS: tuple[type[Base], ...] = (
    DhrRecordRow, DhrExceptionRow, QaDeviationRow, QaCustomerAgreementRow, QaCoaRow, QaBatchPackRow,
    DocRenditionRow, UdiDeviceRecordRow, LblTemplateRow, LblAssignmentRow, LblPrinterRow, LblPrintJobRow,
    LblPrintEventRow, UdiExportRow, ValPackageRow)
M10_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M10_OWNED_MODELS)
M10_RESET_MODELS: tuple[type[Base], ...] = M10_OWNED_MODELS
#: (table, column) pairs added to existing tables by 0013_m10
M10_COLUMNS: tuple[tuple[str, str], ...] = (
    ("orgs", "data_region"), ("mfg_item_planning", "dhr_required"), ("mfg_operations", "max_minutes"),
    ("mfg_operations", "max_wait_minutes"), ("int_endpoints", "region"),
    ("int_endpoints", "cross_region_signature_id"))
M10_ID_PREFIXES = {"dhr": "dhr_", "dhr_exception": "dhx_", "deviation": "dev_", "agreement": "cqa_", "coa": "coa_",
                   "batch_pack": "bpk_", "rendition": "rnd_", "udi_device": "udi_", "label_template": "lbt_",
                   "label_assignment": "lba_", "printer": "lpr_", "print_job": "lpj_", "print_event": "lpe_",
                   "udi_export": "uex_", "val_package": "vpk_"}
#: job kinds (duty runs on `maintenance_runs`)
M10_JOB_KINDS = ("dhr_assemble", "batch_pack", "udi_export", "label_send", "validation_package")
#: regulated entities (M7 4.4: Part 11 reasons and field-level audit); renditions and print events are append-only
M10_REGULATED = ("dhr", "dhr_exception", "deviation", "customer_agreement", "coa", "batch_pack", "udi_device",
                 "label_template", "label_assignment", "printer", "print_job", "udi_export", "val_package")
