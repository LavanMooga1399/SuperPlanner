"""Daily QA due scan (M7-DESIGN 3, job kind `qa_due_scan` on `maintenance_runs`): calibration due soon / overdue,
overdue inspection lots, overdue CAPAs and overdue complaint reports -> plant notifications (one per topic per
day, texts from the backend catalog in the plant's language). Enqueued by the scheduler tick once per plant-local
day after 06:00 for plants with quality records."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

SCAN_LOCAL_HOUR = 6


def due_plants(s: Session, now: datetime) -> list[str]:
    from ....mfg.tz import plant_tz
    from ..db_models import MfgPlantRow
    from ..db_models_m5 import MaintenanceRunRow
    from ..db_models_m7 import QaEquipmentRow, QaInspectionLotRow

    has = set(s.execute(select(QaEquipmentRow.owner_id).distinct()).scalars()) | \
        set(s.execute(select(QaInspectionLotRow.owner_id).distinct()).scalars())
    out = []
    for p in s.execute(select(MfgPlantRow).where(MfgPlantRow.owner_id.in_(sorted(has)))).scalars() if has else []:
        tz = plant_tz(p)
        local = now.astimezone(tz)
        if local.hour < SCAN_LOCAL_HOUR:
            continue
        last = s.execute(select(func.max(MaintenanceRunRow.created_at)).where(
            MaintenanceRunRow.kind == "qa_due_scan", MaintenanceRunRow.owner_scope_id == p.owner_id)).scalar()
        if last is None or last.astimezone(tz).date() < local.date():
            out.append(p.owner_id)
    return out


def scan(s: Session) -> dict[str, Any]:
    from ....i18n import plant_locale, t
    from ...db.models import utcnow
    from ....qa.equipment import due_state
    from ..db_models import MfgPlantRow
    from ..db_models_m7 import QaCapaRow, QaComplaintRow, QaEquipmentRow, QaInspectionLotRow
    from .m2util import today
    from .qa_common import settings_of
    from .qa_complaints import reporting_due
    from .replan import notify

    plant = s.execute(select(MfgPlantRow)).scalars().first()
    loc = plant_locale(plant)
    d = today(s)
    warn = settings_of(s).cal_due_warning_days
    eqs = list(s.execute(select(QaEquipmentRow).where(QaEquipmentRow.status == "active",
                                                      QaEquipmentRow.calibration_required.is_(True))).scalars())
    soon = sorted(e.code for e in eqs if due_state(e, d, warn) in ("due_soon", "in_grace"))
    over = sorted(e.code for e in eqs if due_state(e, d, warn) == "overdue")
    lots = sorted(s.execute(select(QaInspectionLotRow.number).where(
        QaInspectionLotRow.status.in_(("open", "in_progress", "ready")), QaInspectionLotRow.due_at < utcnow())).scalars())
    capas = sorted(s.execute(select(QaCapaRow.number).where(QaCapaRow.status.in_(
        ("draft", "investigation", "plan_approval", "implementation", "effectiveness_check")),
        QaCapaRow.due_on < d)).scalars())
    reports = sorted(c.number for c in s.execute(select(QaComplaintRow).where(QaComplaintRow.status != "closed"))
                     .scalars() if any(x["overdue"] for x in reporting_due(s, c)))
    out = {"due_soon": soon, "overdue": over, "lots": lots, "capas": capas, "reports": reports}
    link = {"cal_due": "/mfg/qa/equipment", "cal_overdue": "/mfg/qa/equipment", "lots_overdue":
            "/mfg/qa/inspection-lots", "capa_overdue": "/mfg/qa/capas", "report_due": "/mfg/qa/complaints"}
    for key, vals, sev, kw in (("cal_due", soon, "info", {"codes": ", ".join(soon[:20]), "days": warn}),
                               ("cal_overdue", over, "warning", {"codes": ", ".join(over[:20])}),
                               ("lots_overdue", lots, "warning", {"numbers": ", ".join(lots[:20])}),
                               ("capa_overdue", capas, "warning", {"numbers": ", ".join(capas[:20])}),
                               ("report_due", reports, "warning", {"numbers": ", ".join(reports[:20])})):
        if vals:
            notify(s, f"qa_{key}", sev, t(f"qa.{key}.title", loc, count=len(vals)), t(f"qa.{key}.body", loc, **kw),
                   link[key])
    return {k: len(v) for k, v in out.items()}


def run_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ....integration.jobs import run_duty

    def fn(info: dict[str, Any]) -> dict[str, Any]:
        with ctx.write_guard(), ctx.db.write() as s:
            return scan(s)

    run_duty(ctx, run_id, lease, fn)


__all__ = ["due_plants", "run_job", "scan"]
del timedelta
