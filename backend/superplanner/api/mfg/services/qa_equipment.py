"""Equipment and calibration (M7-DESIGN 8)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....qa.equipment import valid
from ...errors import ApiError
from ..db_models_m7 import QaEquipmentRow
from . import m7_examples


def _plant_date(s: Session, at: datetime) -> date:
    from ....mfg.tz import plant_tz
    from .m2util import plant

    return at.astimezone(plant_tz(plant(s))).date()


def check_line(s: Session, line_id: str, at: datetime) -> None:
    """Floor `setup_start` / `start` on a line with linked equipment that is not valid: 409, no override (8)."""
    rows = list(s.execute(select(QaEquipmentRow).where(QaEquipmentRow.line_id == line_id,
                                                       QaEquipmentRow.status != "retired")).scalars())
    if not rows:
        return
    d = _plant_date(s, at)
    bad = [e for e in rows if not valid(e, d)]
    if bad:
        raise ApiError(409, "QA_LINE_EQUIPMENT_INVALID", f"{bad[0].code} on this line is not valid "
                       f"({'calibration overdue' if bad[0].status == 'active' else bad[0].status}); calibrate it or "
                       "remove it from the line.", {"equipment": [
                           {"id": e.id, "code": e.code, "status": e.status,
                            "due_on": e.due_on.isoformat() if e.due_on else None} for e in bad]})


__getattr__ = m7_examples.module_getattr(__name__)
