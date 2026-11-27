"""M9 dashboard tiles (M9-DESIGN 10) and the S&OP overdue-step scan (6.1).

Network workspace: `sop_cycle` (current step, overdue steps), `net_shortages` (final shortages of the published,
else latest completed, network run), `tariff_milestones` (milestones and the latest report's missed groups).
Plant: `mps_attainment` (actual `wo_receipt` vs MPS target, current month). Overdue S&OP steps notify the network
workspace once a day (the daily due scan)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, select


def tiles(s: Any, today: date) -> dict[str, Any]:
    from ..db_models import MfgPlantRow

    kind = s.execute(select(MfgPlantRow.kind)).scalar() or "plant"
    if kind == "network":
        return {"sop_cycle": _cycle(s, today), "net_shortages": _shortages(s),
                "tariff_milestones": _milestones(s)}
    return {"mps_attainment": _mps(s, today)}


def overdue_steps(s: Any, today: date) -> list[dict[str, Any]]:
    from ...db.models import utcnow  # noqa: F401
    from ..db_models_m9 import MfgSopCycleRow

    out = []
    for c in s.execute(select(MfgSopCycleRow).where(MfgSopCycleRow.status.in_(
            ("draft", "demand_review", "supply_review", "pre_sop", "executive")))).scalars():
        order = [st["step"] for st in c.steps]
        cur = order.index(c.status) if c.status in order else 0
        for i, st in enumerate(c.steps):
            if i >= cur and st.get("due") and not st.get("done_at") and date.fromisoformat(st["due"]) < today:
                out.append({"cycle_id": c.id, "number": c.number, "step": st["step"], "due": st["due"],
                            "owner_id": st.get("owner_id")})
    return out


def _cycle(s: Any, today: date) -> dict[str, Any]:
    from ..db_models_m9 import MfgSopCycleRow

    c = s.execute(select(MfgSopCycleRow).where(MfgSopCycleRow.status != "cancelled")
                  .order_by(MfgSopCycleRow.period.desc())).scalars().first()
    if c is None:
        return {"value": None, "unit": "step", "status": "n/a", "note": "No S&OP cycle yet.",
                "drill": [{"label": "S&OP", "path": "/mfg/sop"}]}
    over = [x for x in overdue_steps(s, today) if x["cycle_id"] == c.id]
    return {"value": c.status, "unit": "step", "status": "alert" if over else "ok",
            "details": {"number": c.number, "overdue": [x["step"] for x in over]},
            "drill": [{"label": c.number, "path": f"/mfg/sop/cycles/{c.id}"}], "note": ""}


def _shortages(s: Any) -> dict[str, Any]:
    from ..db_models_m9 import MfgNetRunRow, MfgNetShortageRow

    run = s.execute(select(MfgNetRunRow).where(MfgNetRunRow.published.is_(True))).scalars().first() or \
        s.execute(select(MfgNetRunRow).where(MfgNetRunRow.status == "completed")
                  .order_by(MfgNetRunRow.created_at.desc())).scalars().first()
    if run is None:
        return {"value": None, "unit": "count", "status": "n/a", "note": "No network run yet.",
                "drill": [{"label": "Network", "path": "/mfg/network"}]}
    rows = [r for r in s.execute(select(MfgNetShortageRow).where(MfgNetShortageRow.run_id == run.id)).scalars()
            if (r.detail or {}).get("final") and r.cause != "NET_LEAD_TIME"]
    n = len(rows)
    return {"value": n, "unit": "count", "status": "alert" if n else "ok",
            "details": {"run": run.number, "units": round(sum(r.qty for r in rows), 3)},
            "drill": [{"label": run.number, "path": f"/mfg/network/runs/{run.id}"}], "note": ""}


def _milestones(s: Any) -> dict[str, Any]:
    from ..db_models_m9 import MfgTariffMilestoneRow, MfgTariffReportRow

    n = int(s.execute(select(func.count()).select_from(MfgTariffMilestoneRow)).scalar() or 0)
    rep = s.execute(select(MfgTariffReportRow).where(MfgTariffReportRow.status == "completed")
                    .order_by(MfgTariffReportRow.created_at.desc())).scalars().first()
    missed = []
    if rep is not None and rep.result:
        for m in rep.result.get("milestones", []):
            if m.get("first_missed_month"):
                missed.append({"code": m["code"], "month": m["first_missed_month"]})
    return {"value": len(missed) if rep else None, "unit": "count",
            "status": "n/a" if rep is None else ("alert" if missed else "ok"),
            "details": {"milestones": n, "report": rep.number if rep else None, "missed": missed},
            "drill": [{"label": "Trade", "path": "/mfg/trade"}],
            "note": "" if rep else "No tariff report yet."}


def _mps(s: Any, today: date) -> dict[str, Any]:
    from ..db_models import MfgItemRow
    from ..db_models_m2 import MfgInvTransactionRow
    from ..db_models_m9 import MfgMpsTargetRow

    m = today.replace(day=1)
    tg = list(s.execute(select(MfgMpsTargetRow).where(MfgMpsTargetRow.month == m)).scalars())
    if not tg:
        return {"value": None, "unit": "%", "status": "n/a", "note": "No MPS target this month.",
                "drill": [{"label": "MPS", "path": "/mfg/mps"}]}
    fam = dict(s.execute(select(MfgItemRow.id, MfgItemRow.family)).all())
    act: dict[str, float] = defaultdict(float)
    for iid, q in s.execute(select(MfgInvTransactionRow.item_id, MfgInvTransactionRow.qty).where(
            MfgInvTransactionRow.txn_type == "wo_receipt", MfgInvTransactionRow.txn_date >= m)):
        if fam.get(iid):
            act[fam[iid]] += float(q)
    target = sum(t.qty_target for t in tg)
    done = sum(min(act.get(t.family, 0.0), t.qty_target) for t in tg)
    v = round(done / target, 4) if target else None
    elapsed = today.day / 30.0
    status = "n/a" if v is None else ("ok" if v >= elapsed * 0.9 else "watch" if v >= elapsed * 0.7 else "alert")
    return {"value": v, "unit": "%", "status": status, "details": {"families": len(tg), "target": target},
            "drill": [{"label": "MPS", "path": "/mfg/mps"}], "note": ""}


def scan_overdue(s: Any, today: date) -> int:
    """Daily: one notification per overdue step of the network workspace's open cycles."""
    from .replan import notify

    rows = overdue_steps(s, today)
    for x in rows:
        notify(s, "sop_overdue", "warning", f"{x['number']}: {x['step'].replace('_', ' ')} overdue",
               f"The {x['step'].replace('_', ' ')} step of {x['number']} was due on {x['due']}.",
               f"/mfg/sop/cycles/{x['cycle_id']}")
    return len(rows)
