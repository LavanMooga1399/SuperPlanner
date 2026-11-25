"""M8 dashboard tiles (M8-DESIGN 12): forecast accuracy (lag 1), rate plan shortages, loads awaiting release."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select


def tiles(s: Any, today: date) -> dict[str, Any]:
    return {"forecast_accuracy": _accuracy(s), "rate_shortages": _rate(s), "ster_release": _ster(s, today)}


def _accuracy(s: Any) -> dict[str, Any]:
    from .forecast import accuracy_trend

    try:
        trend = accuracy_trend(s, 1, 6)
    except Exception:  # pragma: no cover - a tile never breaks the dashboard
        trend = []
    vals = [t for t in trend if t["wape"] is not None]
    v = vals[-1]["wape"] if vals else None
    status = "n/a" if v is None else ("alert" if v > 0.5 else "watch" if v > 0.25 else "ok")
    return {"value": v, "unit": "%", "status": status,
            "trend": [{"period": t["period_start"].isoformat(), "value": t["wape"]} for t in vals],
            "details": {"lag": 1, "bias": vals[-1]["bias"] if vals else None, "metric": "WAPE"},
            "drill": [{"label": "Forecast accuracy", "path": "/mfg/forecast/accuracy"}],
            "note": "" if vals else "No closed period with an active forecast yet."}


def _rate(s: Any) -> dict[str, Any]:
    from ..db_models_m8 import MfgRateRunRow

    run = s.execute(select(MfgRateRunRow).where(MfgRateRunRow.published.is_(True))
                    .order_by(MfgRateRunRow.published_at.desc())).scalars().first() or \
        s.execute(select(MfgRateRunRow).where(MfgRateRunRow.status == "completed")
                  .order_by(MfgRateRunRow.finished_at.desc())).scalars().first()
    if run is None:
        return {"value": None, "unit": "count", "status": "n/a", "note": "No rate plan yet.",
                "drill": [{"label": "Rate plans", "path": "/mfg/rate"}]}
    sh = run.shortages or []
    n = len(sh)
    return {"value": n, "unit": "count", "status": "alert" if n else "ok",
            "details": {"run_id": run.id, "number": run.number, "published": run.published,
                        "shortage_qty": round(sum(float(x.get("qty", 0)) for x in sh), 6),
                        "items": len({x.get("item_id") for x in sh})},
            "drill": [{"label": run.number, "path": f"/mfg/rate/runs/{run.id}/shortages"}]}


def _ster(s: Any, today: date) -> dict[str, Any]:
    from ..db_models_m8 import MfgSterLoadRow

    n, overdue = s.execute(select(func.count(), func.count().filter(MfgSterLoadRow.release_due < today)).where(
        MfgSterLoadRow.status == "awaiting_release")).one()
    n, overdue = int(n or 0), int(overdue or 0)
    return {"value": n, "unit": "count", "status": "alert" if overdue else ("watch" if n else "ok"),
            "details": {"awaiting_release": n, "overdue": overdue},
            "drill": [{"label": "Sterilisation", "path": "/mfg/sterilisation"}]}
