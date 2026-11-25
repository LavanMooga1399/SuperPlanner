"""Sample loads (demo finding 4): the floor history of a sample is tied to a "history plan" - an APS run published
before the history started whose operations are the history operations at their planned times (most started
within the plant's adherence tolerance, every fifth one late) - so adherence and OEE of the history days are
measured against a plan (KPIs use the plan in force on each day). After the load an MRP run is made and the
history plan's staleness token is refreshed, so nothing shows "out of date" right after a sample load."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...context import AppContext
from ...db.models import new_id, utcnow
from ..db_models import MfgItemRow
from ..db_models_m2 import MfgWorkOrderRow
from ..db_models_m3 import MfgApsOpRow, MfgApsRunRow
from ..db_models_m4 import MfgWoOperationRow

LABEL = "Sample history plan"


def history_plan(s: Session, actor: str) -> str | None:
    rows = list(s.execute(select(MfgWoOperationRow).where(MfgWoOperationRow.actual_start.is_not(None))
                          .order_by(MfgWoOperationRow.actual_start, MfgWoOperationRow.id)).scalars())
    if not rows or s.execute(select(MfgApsRunRow.id).where(MfgApsRunRow.label == LABEL)).first() is not None:
        return None
    from ..repo_m3 import aps_inputs_token
    from .m2util import plant

    p = plant(s)
    tol = int(getattr(p, "adherence_tolerance_minutes", 120) or 120)
    wos = {w.id: w for w in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id.in_(
        sorted({r.wo_id for r in rows})))).scalars()}
    items = {i.id: i for i in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(
        sorted({w.item_id for w in wos.values()})))).scalars()}
    first = min(r.actual_start for r in rows)
    now = utcnow()
    n = int(s.execute(select(func.coalesce(func.max(MfgApsRunRow.run_no), 0))).scalar() or 0) + 1
    run = MfgApsRunRow(id=new_id("apr_"), run_no=n, kind="live", status="completed", label=LABEL,
                       note="Plan the sample's floor history was executed against (sample data).", pinned=True,
                       is_published=False, published_at=first - timedelta(days=1), published_by=actor,
                       parent_run_id=None, copy_of_run_id=None, mrp_run_id=None, basis_published_run_id=None,
                       params={}, as_of=first - timedelta(days=1), horizon_end=max(
                           (r.actual_end or r.actual_start) for r in rows) + timedelta(days=1),
                       master_fingerprint="", data_version=int(p.data_version or 0),
                       inputs_token=aps_inputs_token(s), job_id=None, cancel_requested=False, progress=None,
                       summary={"history": True, "operations": len(rows)}, score=None, validation=None,
                       extras=None, error=None, actor_id=actor, started_at=now, finished_at=now, duration_ms=0,
                       row_version=1, created_at=now, updated_at=now)
    s.add(run)
    s.flush()
    for k, r in enumerate(rows, start=1):
        w = wos[r.wo_id]
        it = items.get(w.item_id)
        late = k % 5 == 0
        shift = timedelta(minutes=(tol + 90) if late else (k % 3) * 20)      # planned earlier than it ran
        ps = r.actual_start - shift
        pe = (r.actual_end or r.actual_start + timedelta(hours=1)) - shift
        s.add(MfgApsOpRow(id=new_id("apo_"), run_id=run.id, op_no=k, order_type="wo", order_id=w.id,
                          order_number=w.number, planned_no=None, item_id=w.item_id,
                          part_number=it.part_number if it else "", seq=r.seq, name=r.name, group_id=r.group_id,
                          line_id=r.line_id, split_index=0, split_count=1, qty=r.qty_planned, start_at=ps,
                          end_at=pe, setup_minutes=0, run_minutes=int((pe - ps).total_seconds() // 60), pieces=[],
                          crew=[], tools=[], release=None, locked=False, frozen=False, status="scheduled",
                          reason=None, due_at=None, late_minutes=0, family="", setup_from_family=None,
                          moved_by_downtime=False, actual=None))
    s.flush()
    return run.id


def after_load(ctx: AppContext) -> dict[str, Any]:
    """MRP run for the loaded sample, then the history plan's token / MRP link / data version refreshed."""
    from ....mfg.mrp.model import MrpParams
    from ..db_models import MfgPlantRow
    from ..repo_m3 import aps_inputs_token
    from . import mrp

    out: dict[str, Any] = {}
    try:
        out["mrp_run"] = mrp.create_run(ctx, MrpParams(label="Sample load"))["id"]
    except Exception as exc:                       # the sample stays loaded; the planner can run MRP
        out["mrp_error"] = exc.__class__.__name__
        return out
    with ctx.db.write() as s:
        run = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.label == LABEL)).scalars().first()
        if run is not None:
            run.mrp_run_id = out["mrp_run"]
            run.inputs_token = aps_inputs_token(s)
            run.data_version = int(s.execute(select(MfgPlantRow.data_version)).scalar() or 0)
    return out
