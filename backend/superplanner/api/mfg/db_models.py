"""Manufacturing tables (M1-DESIGN 6.2, review R7) on the shared `Base`; migration `0003_mfg`.

Every table mixes in `OwnedMixin` (also the child/link tables, M 0.3), so the central ownership filter protects
direct child queries. No server defaults. Relationships exist only for document composition (BOM -> lines,
routing -> operations -> tools, line -> item links, operator -> skill links); all are `lazy="raise"` (an accidental
N+1 fails instead of querying) with `passive_deletes=True` (ON DELETE CASCADE is done by the database).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Double, ForeignKey, Index, Integer,
                        String, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.models import Base, JsonType, utcnow
from ..db.ownership import OwnedMixin


def _ts(nullable: bool = False) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable, default=None if nullable else utcnow)


class _Editable:
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


_REL = {"lazy": "raise", "passive_deletes": True}


class MfgPlantRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_plant"
    __table_args__ = (UniqueConstraint("owner_id", name="uq_mfg_plant_owner"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    utc_offset: Mapped[str] = mapped_column(String(6))
    planning_horizon_days: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    attributes: Mapped[dict[str, Any]] = mapped_column(JsonType)
    data_version: Mapped[int] = mapped_column(Integer, default=0)
    # M2-DESIGN 9.2
    mrp_workdays: Mapped[list[Any]] = mapped_column(JsonType)
    mrp_day_minutes: Mapped[float] = mapped_column(Double)
    mrp_defer_tolerance_days: Mapped[int] = mapped_column(Integer)
    mrp_release_window_days: Mapped[int] = mapped_column(Integer)
    over_receipt_pct: Mapped[float] = mapped_column(Double)


class MfgItemRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_items"
    __table_args__ = (UniqueConstraint("owner_id", "part_number", name="uq_mfg_items_owner_pn"),
                      Index("ix_mfg_items_owner_family", "owner_id", "family"),
                      Index("ix_mfg_items_owner_updated", "owner_id", "updated_at", "id"),
                      Index("uq_mfg_items_owner_extref", "owner_id", "external_ref", unique=True,
                            postgresql_where=text("external_ref IS NOT NULL")))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    part_number: Mapped[str] = mapped_column(String(64))
    revision: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(500))
    uom: Mapped[str] = mapped_column(String(8))
    make_buy: Mapped[str] = mapped_column(String(8))
    family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    setup_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receiving_days: Mapped[int] = mapped_column(Integer)
    lot_rule: Mapped[str] = mapped_column(String(16))
    fixed_lot_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    min_order_qty: Mapped[float] = mapped_column(Double)
    order_multiple: Mapped[float] = mapped_column(Double)
    safety_stock: Mapped[float] = mapped_column(Double)
    serialized: Mapped[bool] = mapped_column(Boolean)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    handling_note: Mapped[str] = mapped_column(String(500))
    attributes: Mapped[dict[str, Any]] = mapped_column(JsonType)
    active: Mapped[bool] = mapped_column(Boolean)
    # M2-DESIGN 9.2
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    standard_cost: Mapped[float | None] = mapped_column(Double, nullable=True)
    lot_controlled: Mapped[bool] = mapped_column(Boolean)
    lot_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MfgGroupRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_groups"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_groups_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean)


class MfgSkillRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_skills"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_skills_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500))


class MfgToolPoolRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_tool_pools"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_tool_pools_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(500))


class MfgShiftTemplateRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_shift_templates"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_shift_templates_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500))
    shifts: Mapped[list[Any]] = mapped_column(JsonType)


class MfgLineRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_lines"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_lines_code"),
                      Index("ix_mfg_lines_group", "group_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("mfg_groups.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    speed_factor: Mapped[float] = mapped_column(Double)
    parallel_capacity: Mapped[int] = mapped_column(Integer)
    setup_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    eligible_families: Mapped[list[Any]] = mapped_column(JsonType)
    cost_per_hour: Mapped[float] = mapped_column(Double)
    active: Mapped[bool] = mapped_column(Boolean)

    item_links: Mapped[list["MfgLineItemRow"]] = relationship(back_populates="line", cascade="all, delete-orphan",
                                                              **_REL)


class MfgLineItemRow(OwnedMixin, Base):
    __tablename__ = "mfg_line_items"
    __table_args__ = (Index("ix_mfg_line_items_item", "item_id"), Index("ix_mfg_line_items_owner", "owner_id"))

    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="CASCADE"), primary_key=True)

    line: Mapped[MfgLineRow] = relationship(back_populates="item_links", lazy="raise")


class MfgBomRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_boms"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "revision", "version", name="uq_mfg_boms_key"),
                      Index("ix_mfg_boms_item_status", "item_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    revision: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    serial_from: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    serial_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str] = mapped_column(String(500))
    released_at: Mapped[datetime | None] = _ts(True)
    obsoleted_at: Mapped[datetime | None] = _ts(True)

    lines: Mapped[list["MfgBomLineRow"]] = relationship(back_populates="bom", cascade="all, delete-orphan", **_REL)


class MfgBomLineRow(OwnedMixin, Base):
    __tablename__ = "mfg_bom_lines"
    __table_args__ = (UniqueConstraint("bom_id", "find_number", "child_item_id", name="uq_mfg_bom_lines_key"),
                      Index("ix_mfg_bom_lines_child", "child_item_id"),
                      Index("ix_mfg_bom_lines_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bom_id: Mapped[str] = mapped_column(ForeignKey("mfg_boms.id", ondelete="CASCADE"))
    find_number: Mapped[str] = mapped_column(String(16))
    child_item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    qty_per: Mapped[float] = mapped_column(Double)
    uom: Mapped[str] = mapped_column(String(8))
    scrap_pct: Mapped[float] = mapped_column(Double)
    ref_designators: Mapped[str] = mapped_column(String(4000))
    alt_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alt_priority: Mapped[int] = mapped_column(Integer)
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(500))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bom: Mapped[MfgBomRow] = relationship(back_populates="lines", lazy="raise")


class MfgRoutingRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_routings"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "revision", "code", "version",
                                       name="uq_mfg_routings_key"),
                      Index("ix_mfg_routings_item_status", "item_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    revision: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    serial_from: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    serial_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str] = mapped_column(String(500))
    released_at: Mapped[datetime | None] = _ts(True)
    obsoleted_at: Mapped[datetime | None] = _ts(True)

    operations: Mapped[list["MfgOperationRow"]] = relationship(back_populates="routing",
                                                               cascade="all, delete-orphan", **_REL)


class MfgOperationRow(OwnedMixin, Base):
    __tablename__ = "mfg_operations"
    __table_args__ = (UniqueConstraint("routing_id", "seq", name="uq_mfg_operations_seq"),
                      Index("ix_mfg_operations_group", "group_id"), Index("ix_mfg_operations_skill", "skill_id"),
                      Index("ix_mfg_operations_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    routing_id: Mapped[str] = mapped_column(ForeignKey("mfg_routings.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500))
    group_id: Mapped[str] = mapped_column(ForeignKey("mfg_groups.id", ondelete="RESTRICT"))
    setup_minutes: Mapped[float] = mapped_column(Double)
    run_minutes: Mapped[float] = mapped_column(Double)
    run_per: Mapped[str] = mapped_column(String(8))
    units_per_panel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_per_batch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_minutes: Mapped[float] = mapped_column(Double)
    move_minutes: Mapped[float] = mapped_column(Double)
    wait_minutes: Mapped[float] = mapped_column(Double)
    labor: Mapped[str] = mapped_column(String(16))
    crew_size: Mapped[int] = mapped_column(Integer)
    skill_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_skills.id", ondelete="RESTRICT"), nullable=True)
    transfer_batch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yield_pct: Mapped[float] = mapped_column(Double)
    inspection_gate: Mapped[bool] = mapped_column(Boolean)
    interruptible: Mapped[bool] = mapped_column(Boolean)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    routing: Mapped[MfgRoutingRow] = relationship(back_populates="operations", lazy="raise")
    tools: Mapped[list["MfgOperationToolRow"]] = relationship(back_populates="operation",
                                                              cascade="all, delete-orphan", **_REL)


class MfgOperationToolRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_operation_tools"
    __table_args__ = (UniqueConstraint("operation_id", "tool_pool_id", name="uq_mfg_operation_tools"),
                      Index("ix_mfg_operation_tools_pool", "tool_pool_id"),
                      Index("ix_mfg_operation_tools_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mfg_operations.id", ondelete="CASCADE"))
    tool_pool_id: Mapped[str] = mapped_column(ForeignKey("mfg_tool_pools.id", ondelete="RESTRICT"))
    qty: Mapped[int] = mapped_column(Integer)

    operation: Mapped[MfgOperationRow] = relationship(back_populates="tools", lazy="raise")


class MfgShiftAssignmentRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_shift_assignments"
    __table_args__ = (CheckConstraint("(group_id IS NULL) <> (line_id IS NULL)",
                                      name="ck_mfg_shift_assignments_target"),
                      Index("ix_mfg_shift_assignments_group", "group_id"),
                      Index("ix_mfg_shift_assignments_line", "line_id"),
                      Index("ix_mfg_shift_assignments_template", "shift_template_id"),
                      Index("ix_mfg_shift_assignments_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shift_template_id: Mapped[str] = mapped_column(ForeignKey("mfg_shift_templates.id", ondelete="RESTRICT"))
    target_type: Mapped[str] = mapped_column(String(8))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_groups.id", ondelete="CASCADE"), nullable=True)
    line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lines.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    shift_names: Mapped[list[Any]] = mapped_column(JsonType)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    cost_per_hour: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_hours_per_week: Mapped[float | None] = mapped_column(Double, nullable=True)
    note: Mapped[str] = mapped_column(String(500))


class MfgCalendarExceptionRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_calendar_exceptions"
    __table_args__ = (Index("ix_mfg_calendar_exceptions_owner_start", "owner_id", "start_at"),
                      Index("ix_mfg_calendar_exceptions_group", "group_id"),
                      Index("ix_mfg_calendar_exceptions_line", "line_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(8))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_groups.id", ondelete="CASCADE"), nullable=True)
    line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lines.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    label: Mapped[str] = mapped_column(String(100))


class MfgOperatorRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_operators"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_operators_code"),
                      Index("ix_mfg_operators_template", "shift_template_id"),
                      Index("ix_mfg_operators_home_group", "home_group_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    shift_template_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_shift_templates.id", ondelete="RESTRICT"),
                                                          nullable=True)
    shift_names: Mapped[list[Any]] = mapped_column(JsonType)
    home_group_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_groups.id", ondelete="SET NULL"),
                                                      nullable=True)
    active: Mapped[bool] = mapped_column(Boolean)

    skill_links: Mapped[list["MfgOperatorSkillRow"]] = relationship(back_populates="operator",
                                                                    cascade="all, delete-orphan", **_REL)


class MfgOperatorSkillRow(OwnedMixin, Base):
    __tablename__ = "mfg_operator_skills"
    __table_args__ = (Index("ix_mfg_operator_skills_skill", "skill_id"),
                      Index("ix_mfg_operator_skills_owner", "owner_id"))

    operator_id: Mapped[str] = mapped_column(ForeignKey("mfg_operators.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("mfg_skills.id", ondelete="CASCADE"), primary_key=True)

    operator: Mapped[MfgOperatorRow] = relationship(back_populates="skill_links", lazy="raise")


class MfgImportRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_imports"
    __table_args__ = (Index("ix_mfg_imports_owner_created", "owner_id", "created_at"),
                      Index("ix_mfg_imports_expires", "expires_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    sheets: Mapped[Any] = mapped_column(JsonType)
    mapping: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    preview: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    result: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


#: The 18 tables in FK (creation) order; delete/drop in reverse.
MFG_MODELS: tuple[type[Base], ...] = (
    MfgPlantRow, MfgItemRow, MfgGroupRow, MfgSkillRow, MfgToolPoolRow, MfgShiftTemplateRow, MfgLineRow,
    MfgLineItemRow, MfgBomRow, MfgBomLineRow, MfgRoutingRow, MfgOperationRow, MfgOperationToolRow,
    MfgShiftAssignmentRow, MfgCalendarExceptionRow, MfgOperatorRow, MfgOperatorSkillRow, MfgImportRow)
MFG_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in MFG_MODELS)
