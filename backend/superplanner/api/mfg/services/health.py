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
    limits: dict[str, Any] = dict(L.all_limits())
    limits["max_body_bytes"] = int(ctx.settings.max_body_bytes)
    return {"uoms": [{"code": u.code, "dimension": u.dimension, "factor": u.factor, "aliases": list(u.aliases)}
                     for u in UOMS],
            "enums": {k: list(v) for k, v in ENUMS.items()}, "limits": limits, "import_spec": meta_spec(),
            "samples": sample_list(), "health_codes": [{"code": c.code, "severity": c.severity} for c in CODES]}


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

        return {"counts": counts, "end_items": [item_ref(repo.to_record(r)) for r in ends],
                "data_version": plant.data_version}


def health(ctx: AppContext, as_of: date | None, horizon_days: int | None) -> Any:
    with read_tx(ctx) as s:
        ds = repo.load_dataset(s)
    if horizon_days is not None and not 7 <= horizon_days <= 730:
        raise ApiError(422, "VALIDATION_ERROR", "horizon_days must be between 7 and 730.",
                       {"errors": [{"loc": ["query", "horizon_days"], "msg": "must be 7..730", "type": "range"}]})
    report = run_health_check(ds, as_of or plant_today(ds.plant.utc_offset),
                              horizon_days or ds.plant.planning_horizon_days)
    report.data_version = ds.plant.data_version
    return report
