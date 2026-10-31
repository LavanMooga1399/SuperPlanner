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
            "samples": sample_list(), "health_codes": [{"code": c.code, "severity": c.severity} for c in CODES],
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
                "published_schedule": _published(s), "floor": _floor(s)}


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
    report = run_health_check(ds, as_of or plant_today(ds.plant),
                              horizon_days or ds.plant.planning_horizon_days)
    report.data_version = ds.plant.data_version
    return report
