"""`/meta`, `/summary` and `/health` (M1-DESIGN 9.3 #1, #2, #67; 9.6). Reads never insert rows."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from ....mfg import limits as L
from ....mfg.health import run_health_check
from ....mfg.io.spec import meta_spec
from ....mfg.messages import CODES
from ....mfg.model import ENUMS
from ....mfg.samples import sample_list
from ....mfg.units import UOMS
from ...context import AppContext
from ...errors import ApiError
from .. import repo
from ..db_models import (MfgBomLineRow, MfgBomRow, MfgGroupRow, MfgItemRow, MfgLineRow, MfgOperationRow,
                         MfgOperatorRow, MfgRoutingRow, MfgShiftTemplateRow, MfgToolPoolRow)
from .common import plant_today, read_tx


def meta(ctx: AppContext) -> dict[str, Any]:
    from ....mfg.tz import zone_names

    limits: dict[str, Any] = dict(L.all_limits())
    limits["max_body_bytes"] = int(ctx.settings.max_body_bytes)
    return {"uoms": [{"code": u.code, "dimension": u.dimension, "factor": u.factor, "aliases": list(u.aliases)}
                     for u in UOMS],
            "enums": {k: list(v) for k, v in ENUMS.items()}, "limits": limits, "import_spec": meta_spec(),
            "samples": sample_list(), "health_codes": [{"code": c.code, "severity": c.severity} for c in CODES]
            + [{"code": c, "severity": sv} for c, sv in QA_HEALTH_CODES],
            "time_zones": list(zone_names())}   # M3-DESIGN 12: IANA picker


def _published(s: Any) -> Any:
    from .aps import published_summary

    return published_summary(s)


def summary(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        plant = repo.plant_or_default(s)
        mb = dict(s.execute(select(MfgItemRow.make_buy, func.count()).group_by(MfgItemRow.make_buy)).all())

        def n(model: Any) -> int:
            return int(s.execute(select(func.count()).select_from(model)).scalar() or 0)

        counts = {"items": sum(int(v) for v in mb.values()), "make": int(mb.get("make", 0)),
                  "buy": int(mb.get("buy", 0)), "phantom": int(mb.get("phantom", 0)), "boms": n(MfgBomRow),
                  "bom_lines": n(MfgBomLineRow), "routings": n(MfgRoutingRow), "operations": n(MfgOperationRow),
                  "groups": n(MfgGroupRow), "lines": n(MfgLineRow), "shift_templates": n(MfgShiftTemplateRow),
                  "operators": n(MfgOperatorRow), "tool_pools": n(MfgToolPoolRow)}
        child = select(MfgBomLineRow.child_item_id).join(MfgBomRow, MfgBomRow.id == MfgBomLineRow.bom_id) \
            .where(MfgBomRow.status != "obsolete")
        has_doc = MfgItemRow.id.in_(select(MfgBomRow.item_id).where(MfgBomRow.status == "released")) | \
            MfgItemRow.id.in_(select(MfgRoutingRow.item_id).where(MfgRoutingRow.status == "released"))
        ends = list(s.execute(select(MfgItemRow).where(MfgItemRow.make_buy == "make", MfgItemRow.active.is_(True),
                                                       has_doc, MfgItemRow.id.not_in(child))
                              .order_by(MfgItemRow.part_number).limit(50)).scalars())
        from ....mfg.dataset import item_ref

        counts.update(_m2_counts(s))
        from .mrp import summary_latest

        return {"counts": counts, "end_items": [item_ref(repo.to_record(r)) for r in ends],
                "data_version": plant.data_version, "latest_run": summary_latest(s),
                "published_schedule": _published(s), "floor": _floor(s), "qa": _qa_summary(s)}


def _qa_summary(s: Any) -> dict[str, int]:
    """M7-DESIGN 9: `/summary.qa`."""
    from ...db.models import utcnow
    from ..db_models_m7 import QaCapaRow, QaEquipmentRow, QaInspectionLotRow, QaNcrRow
    from .common import plant_today

    def n(q: Any) -> int:
        return int(s.execute(q).scalar() or 0)

    d = plant_today(repo.plant_or_default(s))
    from datetime import timedelta

    from .qa_common import settings_of

    warn = settings_of(s).cal_due_warning_days
    open_lots = QaInspectionLotRow.status.in_(("open", "in_progress", "ready"))
    return {"open_lots": n(select(func.count()).select_from(QaInspectionLotRow).where(open_lots)),
            "overdue_lots": n(select(func.count()).select_from(QaInspectionLotRow).where(
                open_lots, QaInspectionLotRow.due_at < utcnow())),
            "open_ncrs": n(select(func.count()).select_from(QaNcrRow).where(
                QaNcrRow.status.in_(("draft", "open", "proposed", "approved", "implemented")))),
            "overdue_capas": n(select(func.count()).select_from(QaCapaRow).where(
                QaCapaRow.status.in_(("draft", "investigation", "plan_approval", "implementation",
                                      "effectiveness_check")), QaCapaRow.due_on < d)),
            "equipment_due": n(select(func.count()).select_from(QaEquipmentRow).where(
                QaEquipmentRow.status == "active", QaEquipmentRow.calibration_required.is_(True),
                QaEquipmentRow.due_on <= d + timedelta(days=warn)))}


def _floor(s: Any) -> dict[str, Any]:
    from .replan import floor_summary            # M4-DESIGN 11

    return floor_summary(s)


def _m2_counts(s: Any) -> dict[str, int]:
    """M2-DESIGN 12.3: additive `/summary` counts."""
    from ..db_models_m2 import (MfgDemandLineRow, MfgDemandOrderRow, MfgLocationRow, MfgPurchaseDocRow,
                                MfgPurchaseLineRow, MfgPurchaseScheduleRow, MfgSupplierRow, MfgWorkOrderRow)
    from .common import plant_today

    def n(q: Any) -> int:
        return int(s.execute(q).scalar() or 0)

    today = plant_today(repo.plant_or_default(s))
    dock = func.coalesce(MfgPurchaseScheduleRow.confirmed_date, MfgPurchaseScheduleRow.requested_date)
    return {
        "locations": n(select(func.count()).select_from(MfgLocationRow)),
        "suppliers": n(select(func.count()).select_from(MfgSupplierRow)),
        "open_purchase_orders": n(select(func.count()).select_from(MfgPurchaseDocRow).where(
            MfgPurchaseDocRow.doc_type == "po", MfgPurchaseDocRow.status.in_(("draft", "open", "partially_received")))),
        "open_purchase_requests": n(select(func.count()).select_from(MfgPurchaseDocRow).where(
            MfgPurchaseDocRow.doc_type == "pr", MfgPurchaseDocRow.status.in_(("draft", "submitted", "approved")))),
        "overdue_schedules": n(select(func.count()).select_from(MfgPurchaseScheduleRow).join(
            MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).join(
            MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id).where(
            MfgPurchaseScheduleRow.closed.is_(False), MfgPurchaseLineRow.status == "open",
            MfgPurchaseScheduleRow.qty - MfgPurchaseScheduleRow.received_qty > 1e-6, dock < today,
            MfgPurchaseDocRow.status.in_(("open", "partially_received", "draft", "submitted", "approved")))),
        "open_demand_lines": n(select(func.count()).select_from(MfgDemandLineRow).join(
            MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id).where(
            MfgDemandOrderRow.status == "open", MfgDemandLineRow.qty - MfgDemandLineRow.shipped_qty > 1e-6)),
        "open_work_orders": n(select(func.count()).select_from(MfgWorkOrderRow).where(
            MfgWorkOrderRow.status.in_(("planned", "released", "in_progress")))),
    }


def health(ctx: AppContext, as_of: date | None, horizon_days: int | None) -> Any:
    with read_tx(ctx) as s:
        ds = repo.load_dataset(s)
    if horizon_days is not None and not 7 <= horizon_days <= 730:
        raise ApiError(422, "VALIDATION_ERROR", "horizon_days must be between 7 and 730.",
                       {"errors": [{"loc": ["query", "horizon_days"], "msg": "must be 7..730", "type": "range"}]})
    d0 = as_of or plant_today(ds.plant)
    hd = horizon_days or ds.plant.planning_horizon_days
    report = run_health_check(ds, d0, hd)
    report.data_version = ds.plant.data_version
    with read_tx(ctx) as s:
        _qa_issues(s, report, ds, d0, hd)
        _m8_issues(s, report, ds)
    return report


M8_HEALTH_CODES = (("MFG_RATE_NO_RATE", "warning"), ("MFG_PACK_INVALID", "warning"),
                   ("MFG_STER_NO_CHAMBER", "warning"))


def _m8_issues(s: Any, report: Any, ds: Any) -> None:
    """M8-DESIGN 13.1: rate items without a line rate on an active flow line, an order pack level without its
    packaging level, sterilised items without a chamber."""
    from sqlalchemy import select

    from ....mfg.model import EntityRef, HealthIssue
    from ..db_models import MfgLineRow
    from ..db_models_m8 import MfgItemPackagingRow, MfgItemPlanningRow, MfgLineRateRow

    plan = list(s.execute(select(MfgItemPlanningRow)).scalars())
    if not plan:
        return
    flow = {r.id for r in s.execute(select(MfgLineRow).where(MfgLineRow.active.is_(True),
                                                             MfgLineRow.planning == "flow")).scalars()}
    chambers = s.execute(select(MfgLineRow.id).where(MfgLineRow.active.is_(True),
                                                     MfgLineRow.planning == "sterilisation").limit(1)).first()
    rates = [(r.line_id, r.item_id, r.item_family) for r in s.execute(select(MfgLineRateRow)).scalars()
             if r.line_id in flow]
    levels: dict[str, set[str]] = {}
    for i, lv in s.execute(select(MfgItemPackagingRow.item_id, MfgItemPackagingRow.level)):
        levels.setdefault(i, set()).add(lv)
    new: list[Any] = []
    for p in sorted(plan, key=lambda x: x.item_id):
        it = ds.items.get(p.item_id)
        if it is None:
            continue
        ref = EntityRef(type="item", id=it.id, label=it.part_number)
        if p.replenishment == "rate" and not any(i == it.id or (f is not None and f == it.family)
                                                 for _l, i, f in rates):
            new.append(HealthIssue(code="MFG_RATE_NO_RATE", severity="warning",
                                   message=f"{it.part_number} is rate planned but no flow line has a rate for it.",
                                   fix="Add a line rate for the item or its family.", entity=ref,
                                   link=f"/mfg/items/{it.id}"))
        if p.order_pack_level and p.order_pack_level not in levels.get(it.id, set()):
            new.append(HealthIssue(code="MFG_PACK_INVALID", severity="warning",
                                   message=f"{it.part_number} orders in {p.order_pack_level}s but has no such "
                                           f"packaging level.", fix="Add the packaging level.", entity=ref,
                                   link=f"/mfg/items/{it.id}"))
        if p.ster_cycle_code and chambers is None:
            new.append(HealthIssue(code="MFG_STER_NO_CHAMBER", severity="warning",
                                   message=f"{it.part_number} needs sterilisation cycle {p.ster_cycle_code} but the "
                                           f"plant has no sterilisation chamber.",
                                   fix="Set a line's planning to sterilisation with pallets and cycle hours.",
                                   entity=ref))
    if not new:
        return
    report.issues = list(report.issues) + new
    for x in new:
        report.by_code[x.code] = report.by_code.get(x.code, 0) + 1
        setattr(report.counts, x.severity, getattr(report.counts, x.severity) + 1)


QA_HEALTH_CODES = (("QA_LINE_BLOCKED", "error"), ("QA_TOOL_POOL_REDUCED", "warning"),
                   ("QA_EQUIPMENT_DUE_IN_HORIZON", "info"))


def _qa_issues(s: Any, report: Any, ds: Any, as_of: date, horizon_days: int) -> None:
    """M7-DESIGN 8 (3): lines blocked by invalid equipment, reduced tool pools, equipment due in the horizon."""
    from datetime import timedelta

    from ....mfg.model import EntityRef, HealthIssue
    from ..db_models_m7 import QaEquipmentRow
    from .qa_equipment import line_blocks, tool_pool_valid_units

    end = as_of + timedelta(days=horizon_days)
    new: list[Any] = []
    for line_id, b in sorted(line_blocks(s, as_of, end).items()):
        ln = ds.lines.get(line_id)
        lab = ln.code if ln else line_id
        if b["from"] <= as_of:
            new.append(HealthIssue(code="QA_LINE_BLOCKED", severity="error",
                                   message=f"Line {lab} is unavailable: {b['reason']}.",
                                   fix="Calibrate the equipment or take it off the line.",
                                   entity=EntityRef(type="line", id=line_id, label=lab),
                                   related=[EntityRef(type="equipment", id=b["equipment_id"], label=b["equipment"])],
                                   link=f"/mfg/qa/equipment/{b['equipment_id']}"))
        else:
            new.append(HealthIssue(code="QA_EQUIPMENT_DUE_IN_HORIZON", severity="info",
                                   message=f"{b['equipment']} on line {lab} becomes invalid on "
                                           f"{b['from'].isoformat()}; the line is blocked from then.",
                                   fix="Schedule the calibration before that day.",
                                   entity=EntityRef(type="equipment", id=b["equipment_id"], label=b["equipment"]),
                                   link=f"/mfg/qa/equipment/{b['equipment_id']}"))
    for pid, n in sorted(tool_pool_valid_units(s, as_of).items()):
        tp = ds.tool_pools.get(pid)
        if tp is not None and n < tp.quantity:
            new.append(HealthIssue(code="QA_TOOL_POOL_REDUCED", severity="warning",
                                   message=f"Tool pool {tp.code}: {n} of {tp.quantity} units are in calibration.",
                                   fix="Calibrate the linked units.",
                                   entity=EntityRef(type="tool_pool", id=pid, label=tp.code)))
    del QaEquipmentRow
    if not new:
        return
    report.issues = list(report.issues) + new
    for x in new:
        report.by_code[x.code] = report.by_code.get(x.code, 0) + 1
        setattr(report.counts, x.severity, getattr(report.counts, x.severity) + 1)
    report.ok = report.counts.error == 0
