"""Planning master data and settings (M8-DESIGN 3, 4.6, 6.1, 11 I5-I7, R1-R3, N1-N2): item planning, packaging
levels, line rates and line planning fields, the changeover matrix, plant planning settings, the nightly chain.

Item planning and packaging share the item planning row's `row_version` (If-Match of both PUTs; "0" before the
first save). Line rates use the line's `row_version`. The changeover matrix is replaced as a whole; its version is
the number of matrix saves (max row version).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg.model_m8 import PACK_LEVELS, PlanningSettings
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow, MfgLineRow
from ..db_models_m8 import MfgChangeoverRow, MfgItemPackagingRow, MfgItemPlanningRow, MfgLineRateRow
from . import m8_examples
from .common import audit, check_version, read_tx, touch, unknown_ref, write_tx
from .m8common import PLANNING_DEFAULTS, planning_of, settings_of

LINE_FIELDS = ("planning", "oee", "clearance_minutes", "clean_every_hours", "clean_minutes", "chamber_pallets",
               "cycle_hours")


# ---------------------------------------------------------------- planning settings (N1)

def _settings_record(s: Session, plant: Any) -> dict[str, Any]:
    st = PlanningSettings.model_validate(plant.planning_settings) if plant is not None and plant.planning_settings \
        else PlanningSettings()
    return {**st.model_dump(mode="json"), "row_version": plant.row_version if plant is not None else 1}


def get_settings(ctx: AppContext) -> dict[str, Any]:
    from ..db_models import MfgPlantRow

    with read_tx(ctx) as s:
        return _settings_record(s, s.execute(select(MfgPlantRow)).scalars().first())


def put_settings(ctx: AppContext, a: Any, body: PlanningSettings, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, plant):
        check_version(plant, if_match)
        before = _settings_record(s, plant)
        plant.planning_settings = body.model_dump(mode="json")
        touch(plant)
        s.info.pop("sp_planning_settings", None)
        s.flush()
        after = _settings_record(s, plant)
        audit(s, "planning_settings", plant.id, "update", {}, before=before, after=after)
        return after


# ---------------------------------------------------------------- item planning (I5-I6)

def _item(s: Session, item_id: str, lock: bool = False) -> MfgItemRow:
    return repo.get_row(s, MfgItemRow, item_id, what="Item", lock=lock)


def _planning_record(item_id: str, row: MfgItemPlanningRow | None) -> dict[str, Any]:
    return {"id": row.id if row else None, "item_id": item_id, **planning_of(row),
            "row_version": row.row_version if row else 0}


def get_item_planning(ctx: AppContext, item_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _item(s, item_id)
        row = s.execute(select(MfgItemPlanningRow).where(MfgItemPlanningRow.item_id == item_id)).scalars().first()
        return _planning_record(item_id, row)


def _planning_row(s: Session, item_id: str, if_match: str | None) -> MfgItemPlanningRow:
    row = s.execute(select(MfgItemPlanningRow).where(MfgItemPlanningRow.item_id == item_id)
                    .with_for_update()).scalars().first()
    if if_match is not None:
        check_version(row, if_match, current=row.row_version if row else 0)
    if row is None:
        now = utcnow()
        row = MfgItemPlanningRow(id=new_id("ipn_"), item_id=item_id, **PLANNING_DEFAULTS, abc=None, xyz=None,
                                 row_version=0, created_at=now, updated_at=now)
        s.add(row)
    return row


def put_item_planning(ctx: AppContext, a: Any, item_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        it = _item(s, item_id, lock=True)
        if body.like_item_id is not None:
            if body.like_item_id == item_id:
                raise ApiError(422, "VALIDATION_ERROR", "An item cannot be its own like item.",
                               {"errors": [{"loc": ["body", "like_item_id"], "msg": "own item",
                                            "type": "value_error"}]})
            if s.get(MfgItemRow, body.like_item_id) is None:
                raise unknown_ref(["body", "like_item_id"], body.like_item_id, "Item")
        if body.replenishment == "rate" and it.make_buy != "make":
            raise ApiError(422, "VALIDATION_ERROR", "Only make items can be planned on flow lines (rate).",
                           {"errors": [{"loc": ["body", "replenishment"], "msg": "buy item", "type": "value_error"}]})
        row = _planning_row(s, item_id, if_match)
        ster = ("ster_cycle_code", "aeration_hours", "release_mode", "release_days")
        if any(getattr(row, k) != getattr(body, k) for k in ster) and not a.p.has("qa_plan_edit"):
            raise ApiError(403, "MFG_FORBIDDEN", "Sterilisation fields are maintained by quality (qa_plan_edit).",
                           {"fields": [k for k in ster if getattr(row, k) != getattr(body, k)]})
        before = _planning_record(item_id, row) if row.row_version else None
        for k, v in body.model_dump().items():
            setattr(row, k, v)
        touch(row)
        s.flush()
        rec = _planning_record(item_id, row)
        audit(s, "item_planning", item_id, "update", {"version": row.row_version}, before=before, after=rec)
        return rec


# ---------------------------------------------------------------- packaging (I7)

def _packaging_record(s: Session, item_id: str) -> dict[str, Any]:
    rows = list(s.execute(select(MfgItemPackagingRow).where(MfgItemPackagingRow.item_id == item_id)
                          .order_by(MfgItemPackagingRow.seq)).scalars())
    row = s.execute(select(MfgItemPlanningRow.row_version).where(MfgItemPlanningRow.item_id == item_id)).scalar()
    return {"item_id": item_id, "row_version": int(row or 0),
            "levels": [{"id": r.id, "seq": r.seq, "level": r.level, "code": r.code, "qty_base": r.qty_base,
                        "gtin": r.gtin, "weight_kg": r.weight_kg} for r in rows]}


def get_packaging(ctx: AppContext, item_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _item(s, item_id)
        return _packaging_record(s, item_id)


def put_packaging(ctx: AppContext, a: Any, item_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _item(s, item_id, lock=True)
        row = _planning_row(s, item_id, if_match)
        before = _packaging_record(s, item_id)
        levels = {lv.level for lv in body.levels}
        if row.order_pack_level and row.order_pack_level not in levels:
            raise ApiError(409, "MFG_PACK_INVALID", f"The order pack level {row.order_pack_level!r} must stay defined.",
                           {"order_pack_level": row.order_pack_level})
        s.execute(delete(MfgItemPackagingRow).where(MfgItemPackagingRow.item_id == item_id))
        now = utcnow()
        for lv in body.levels:
            s.add(MfgItemPackagingRow(id=new_id("pkg_"), item_id=item_id, level=lv.level,
                                      seq=PACK_LEVELS.index(lv.level) + 1, code=lv.code, qty_base=lv.qty_base,
                                      gtin=lv.gtin, weight_kg=lv.weight_kg, row_version=1, created_at=now,
                                      updated_at=now))
        touch(row)
        s.flush()
        rec = _packaging_record(s, item_id)
        audit(s, "item_packaging", item_id, "update", {"version": row.row_version},
              before={"levels": [{k: v for k, v in x.items() if k != "id"} for x in before["levels"]]},
              after={"levels": [{k: v for k, v in x.items() if k != "id"} for x in rec["levels"]]})
        return rec


# ---------------------------------------------------------------- line rates (R1-R2)

def _rates_record(s: Session, line: MfgLineRow) -> dict[str, Any]:
    rates = s.execute(select(MfgLineRateRow).where(MfgLineRateRow.line_id == line.id)
                      .order_by(MfgLineRateRow.item_family.nulls_last(), MfgLineRateRow.item_id)).scalars()
    return {"line_id": line.id, "line_code": line.code, "row_version": line.row_version,
            "line": {k: getattr(line, k) for k in LINE_FIELDS},
            "rates": [{"id": r.id, "item_id": r.item_id, "item_family": r.item_family,
                       "units_per_hour": r.units_per_hour, "oee": r.oee} for r in rates]}


def get_line_rates(ctx: AppContext, line_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _rates_record(s, repo.get_row(s, MfgLineRow, line_id, what="Line"))


def put_line_rates(ctx: AppContext, a: Any, line_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        line = repo.get_row(s, MfgLineRow, line_id, what="Line", lock=True)
        if if_match is not None:
            check_version(line, if_match)
        before = _rates_record(s, line)
        keys = [(r.item_id, r.item_family) for r in body.rates]
        if len(set(keys)) != len(keys):
            raise ApiError(422, "VALIDATION_ERROR", "Each item or family may have one rate per line.",
                           {"errors": [{"loc": ["body", "rates"], "msg": "duplicate", "type": "value_error"}]})
        ids = [r.item_id for r in body.rates if r.item_id]
        if ids:
            found = set(s.execute(select(MfgItemRow.id).where(MfgItemRow.id.in_(ids))).scalars())
            for k, r in enumerate(body.rates):
                if r.item_id and r.item_id not in found:
                    raise unknown_ref(["body", "rates", k, "item_id"], r.item_id, "Item")
        if body.line is not None:
            ln = body.line
            if ln.planning == "sterilisation" and (not ln.chamber_pallets or not ln.cycle_hours):
                raise ApiError(422, "MFG_STER_NO_CHAMBER", "A sterilisation line needs chamber pallets and a cycle "
                               "time.", {"line_id": line.id})
            for k in LINE_FIELDS:
                setattr(line, k, getattr(ln, k))
        s.execute(delete(MfgLineRateRow).where(MfgLineRateRow.line_id == line.id))
        now = utcnow()
        for r in body.rates:
            s.add(MfgLineRateRow(id=new_id("lrt_"), line_id=line.id, item_id=r.item_id, item_family=r.item_family,
                                 units_per_hour=r.units_per_hour, oee=r.oee, row_version=1, created_at=now,
                                 updated_at=now))
        touch(line)
        s.flush()
        rec = _rates_record(s, line)
        strip = (lambda d: {**d, "rates": [{k: v for k, v in x.items() if k != "id"} for x in d["rates"]]})
        audit(s, "line_rates", line.id, "update", {"version": line.row_version}, before=strip(before),
              after=strip(rec))
        return rec


# ---------------------------------------------------------------- changeover matrix (R3)

def _matrix_record(s: Session, family: str | None = None) -> dict[str, Any]:
    q = select(MfgChangeoverRow)
    if family:
        q = q.where(MfgChangeoverRow.line_setup_family == family)
    rows = list(s.execute(q.order_by(MfgChangeoverRow.line_setup_family, MfgChangeoverRow.from_key,
                                     MfgChangeoverRow.to_key, MfgChangeoverRow.kind)).scalars())
    ver = int(s.execute(select(func.coalesce(func.max(MfgChangeoverRow.row_version), 0))).scalar() or 0)
    return {"version": ver, "rows": [{"id": r.id, "line_setup_family": r.line_setup_family, "from_key": r.from_key,
                                      "to_key": r.to_key, "minutes": r.minutes, "cost": r.cost, "kind": r.kind}
                                     for r in rows]}


def get_changeover_matrix(ctx: AppContext, line_setup_family: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _matrix_record(s, line_setup_family)


def put_changeover_matrix(ctx: AppContext, a: Any, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        cur = _matrix_record(s)
        if if_match is not None:
            check_version(type("V", (), {"row_version": cur["version"]})(), if_match)
        s.execute(delete(MfgChangeoverRow))
        ver = cur["version"] + 1
        now = utcnow()
        for r in body.rows:
            s.add(MfgChangeoverRow(id=new_id("chg_"), line_setup_family=r.line_setup_family, from_key=r.from_key,
                                   to_key=r.to_key, minutes=r.minutes, cost=r.cost, kind=r.kind, row_version=ver,
                                   created_at=now, updated_at=now))
        s.flush()
        rec = _matrix_record(s)
        audit(s, "changeover_matrix", None, "update", {"rows": len(body.rows), "version": ver})
        return rec


# ---------------------------------------------------------------- nightly chain (N2, 6.1)

def nightly_run_now(ctx: AppContext, a: Any) -> dict[str, Any]:
    from . import nightly

    return nightly.start(ctx, a.p.owner_id, a.user_id, manual=True)


def nightly_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    from . import nightly

    return nightly.run(ctx, info)


__getattr__ = m8_examples.module_getattr(__name__)
