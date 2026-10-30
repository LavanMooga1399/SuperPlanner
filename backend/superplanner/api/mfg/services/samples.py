"""Sample datasets (M1-DESIGN 10, 9.3 #75-76) and reset (#77).

A sample load goes through the same `plan_import -> writer.apply` path as file imports (`release: true`), in one
transaction. `replace: true` first deletes all of the owner's mfg rows (reset semantics) in that transaction.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg import samples as S
from ....mfg.dataset import MfgDataset
from ....mfg.health import run_health_check
from ....mfg.io.plan import ImportOptions, plan_import
from ....mfg.model import PlantRecord
from ...context import AppContext
from ...db import new_id
from ...errors import ApiError, not_found
from .. import repo, repo_m2, writer
from ..db_models_m2 import ALL_MFG_MODELS
from .common import audit, plant_today, read_tx, write_tx

RESET_PHRASE = "DELETE ALL MANUFACTURING DATA"


def _reserve_released(s: Session, bundle: Any) -> None:
    """13.3: released / in-progress sample WOs reserve their open components (WO-number order), as
    `samples.sample_reservations` does for the pure state."""
    from sqlalchemy import select

    from ..db_models_m2 import MfgWoComponentRow, MfgWorkOrderRow
    from .workorders import reserve_in

    numbers = sorted(r["number"] for r in bundle.get("work_orders") or [] if r.get("status") in
                     ("released", "in_progress"))
    for no in numbers:
        w = s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.number == no)).scalars().first()
        if w is None:
            continue
        comps = list(s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == w.id)
                               .order_by(MfgWoComponentRow.id)).scalars())
        reserve_in(s, w, comps, None)


def list_samples() -> dict[str, Any]:
    return {"items": S.sample_list()}


def delete_all(s: Session) -> dict[str, int]:
    """Delete every mfg data row of the bound owner, children first (ORM delete statements, owner-filtered;
    M2-DESIGN 9.4: `ALL_MFG_MODELS`; workspace memberships survive)."""
    out: dict[str, int] = {}
    for model in reversed(ALL_MFG_MODELS):
        res = s.execute(delete(model).execution_options(synchronize_session=False))
        out[model.__tablename__[len("mfg_"):]] = int(res.rowcount or 0)
    s.expunge_all()
    return out


def reset(ctx: AppContext, confirm: str) -> dict[str, Any]:
    if confirm != RESET_PHRASE:
        raise ApiError(422, "MFG_RESET_CONFIRM", f"Type {RESET_PHRASE!r} to confirm the reset.",
                       {"confirm": RESET_PHRASE})
    with write_tx(ctx) as (s, _plant):
        deleted = delete_all(s)
        audit(s, "plant", None, "reset", {"deleted": deleted})
        return {"deleted": deleted}


def _errors(plan: Any) -> ApiError:
    return ApiError(409, "MFG_IMPORT_HAS_ERRORS",
                    f"The sample clashes with your data ({plan.error_count} problem(s)). Load it with replace, or "
                    "reset your data first.",
                    {"row_errors": plan.row_errors[:L.MAX_ROW_ERRORS_RETURNED], "error_count": plan.error_count})


def default_anchor(today: date) -> date:
    """13.1: the Monday on or before plant today."""
    return today - timedelta(days=today.weekday())


def load(ctx: AppContext, sample_id: str, replace: bool, anchor: date | None = None,
         include_transactions: bool = True) -> dict[str, Any]:
    if sample_id not in S.SAMPLES:
        raise not_found("Sample", sample_id)
    t0 = time.monotonic()
    with read_tx(ctx) as s:
        today = plant_today(repo.plant_or_default(s))
    anchor = anchor or default_anchor(today)
    bundle = S.build(sample_id, anchor=anchor, include_transactions=include_transactions)
    opts = ImportOptions(release=True, today=anchor)
    stock_date = anchor - timedelta(days=1)
    if replace:
        plan = plan_import(bundle, MfgDataset(plant=PlantRecord()), opts, id_factory=new_id)
        key = None
    else:
        with read_tx(ctx) as s:
            p = repo.plant_or_default(s)
            key = (p.id, p.data_version)
            ds = repo_m2.load_import_dataset(s)
        plan = plan_import(bundle, ds, opts, id_factory=new_id)
    with write_tx(ctx) as (s, plant):
        if replace:
            dv = plant.data_version
            delete_all(s)
            plant = repo.lock_plant(s)
            plant.data_version = dv + 1
            s.flush()
        elif (plant.id, plant.data_version - 1) != key or include_transactions:
            plan = plan_import(bundle, repo_m2.load_import_dataset(s), opts, id_factory=new_id)
        if not plan.ok:
            raise _errors(plan)
        if plan.has_writes():
            writer.apply(s, plan, plant, stock_date=stock_date)
            if include_transactions:
                _reserve_released(s, bundle)
        else:
            plant.data_version -= 1
        result = {"counts": plan.result_counts(), "duration_ms": int((time.monotonic() - t0) * 1000),
                  "data_version": plant.data_version}
        audit(s, "plant", plant.id, "sample_load", {"sample_id": sample_id, "replace": replace,
                                                     "anchor": anchor.isoformat(),
                                                     "include_transactions": include_transactions})
    with read_tx(ctx) as s:
        ds = repo.load_dataset(s)
    report = run_health_check(ds, plant_today(ds.plant), ds.plant.planning_horizon_days)
    return {"sample_id": sample_id, "result": result,
            "health": {"ok": report.ok, "counts": report.counts.model_dump()}}
