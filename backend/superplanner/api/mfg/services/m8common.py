"""Shared helpers of the M8 services (M8-DESIGN 3, 4.6): planning settings, item planning with defaults, the plant
working-day calendar, numbering, paging, job runs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg.model_m8 import ItemPlanningInput, PlanningSettings
from ....mfg.workdays import WorkCalendar
from ..db_models import MfgCalendarExceptionRow, MfgItemRow, MfgPlantRow
from ..db_models_m8 import MfgItemPackagingRow, MfgItemPlanningRow

PLANNING_DEFAULTS = ItemPlanningInput().model_dump()


def settings_of(s: Session) -> PlanningSettings:
    cache = s.info.get("sp_planning_settings")
    if cache is None:
        raw = s.execute(select(MfgPlantRow.planning_settings)).scalar()
        cache = PlanningSettings.model_validate(raw) if raw else PlanningSettings()
        s.info["sp_planning_settings"] = cache
    return cache


def plant_row(s: Session) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow)).scalars().first()


def today(s: Session) -> date:
    from .m2util import today as _today

    return _today(s)


def work_calendar(s: Session) -> WorkCalendar:
    """Plant working weekdays (`mrp_workdays`) and whole-day plant holidays / shutdowns."""
    from ....mfg.tz import plant_tz

    p = plant_row(s)
    workdays = list(p.mrp_workdays) if p is not None and p.mrp_workdays else ["mon", "tue", "wed", "thu", "fri"]
    holidays: set[date] = set()
    if p is not None:
        tz = plant_tz(p)
        for e in s.execute(select(MfgCalendarExceptionRow).where(MfgCalendarExceptionRow.scope == "plant",
                                                                 MfgCalendarExceptionRow.kind.in_(
                                                                     ("holiday", "shutdown")))).scalars():
            a, b = e.start_at.astimezone(tz), e.end_at.astimezone(tz)
            d = a.date() if (a.hour, a.minute, a.second) == (0, 0, 0) else a.date() + timedelta(days=1)
            while datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(days=1) <= b:
                holidays.add(d)
                d += timedelta(days=1)
    return WorkCalendar(workdays, holidays)


def planning_rows(s: Session, item_ids: Iterable[str] | None = None) -> dict[str, MfgItemPlanningRow]:
    q = select(MfgItemPlanningRow)
    if item_ids is not None:
        ids = list(item_ids)
        if not ids:
            return {}
        q = q.where(MfgItemPlanningRow.item_id.in_(ids))
    return {r.item_id: r for r in s.execute(q).scalars()}


def planning_of(row: MfgItemPlanningRow | None) -> dict[str, Any]:
    """Item planning values (defaults when the item has no row)."""
    if row is None:
        return {**PLANNING_DEFAULTS, "abc": None, "xyz": None}
    out = {k: getattr(row, k) for k in PLANNING_DEFAULTS}
    out.update(abc=row.abc, xyz=row.xyz)
    return out


def packaging(s: Session, item_ids: Iterable[str] | None = None) -> dict[str, dict[str, float]]:
    """item -> {level: qty_base}."""
    q = select(MfgItemPackagingRow.item_id, MfgItemPackagingRow.level, MfgItemPackagingRow.qty_base)
    if item_ids is not None:
        ids = list(item_ids)
        if not ids:
            return {}
        q = q.where(MfgItemPackagingRow.item_id.in_(ids))
    out: dict[str, dict[str, float]] = {}
    for item_id, level, qty in s.execute(q):
        out.setdefault(item_id, {})[level] = float(qty)
    return out


def item_map(s: Session, ids: Iterable[str] | None = None) -> dict[str, MfgItemRow]:
    q = select(MfgItemRow)
    if ids is not None:
        ids = list(ids)
        if not ids:
            return {}
        q = q.where(MfgItemRow.id.in_(ids))
    return {r.id: r for r in s.execute(q).scalars()}


def iref(row: MfgItemRow | None, item_id: str = "") -> dict[str, Any]:
    if row is None:
        return {"id": item_id, "part_number": None, "revision": None, "name": None}
    return {"id": row.id, "part_number": row.part_number, "revision": row.revision, "name": row.description}


def next_number(s: Session, kind: str, model: Any) -> str:
    from .. import repo_m2

    return repo_m2.next_number(s, kind, repo_m2.number_taken(s, model))


def total(s: Session, q: Any) -> int:
    return int(s.execute(select(func.count()).select_from(q.order_by(None).subquery())).scalar() or 0)


def page(items: list[Any], n: int, limit: int, offset: int, **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": n, "limit": limit, "offset": offset, **extra}


def r6(x: float | None) -> float | None:
    return None if x is None else round(float(x), 6)


def start_job(s: Session, ctx: Any, kind: str, owner_id: str, params: dict[str, Any]) -> tuple[str, Any]:
    from ....integration.jobs import new_run

    return new_run(s, ctx, kind, owner_id, params)
