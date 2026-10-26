"""Skills, operators and tool pools (M1-DESIGN 3.9; 9.3 #54-66)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.dataset import ref
from ....mfg.model import (OperatorInput, OperatorRecord, SkillInput, SkillRecord, ToolPoolInput, ToolPoolRecord)
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import (MfgGroupRow, MfgOperationRow, MfgOperationToolRow, MfgOperatorRow, MfgOperatorSkillRow,
                         MfgShiftTemplateRow, MfgSkillRow, MfgToolPoolRow)
from .common import (audit, check_limit, check_version, count, ensure_unique, ilike, in_use, read_tx, touch,
                     unknown_ref, write_tx)

# ---------------------------------------------------------------- skills


def _skill_counts(s: Session, ids: list[str] | None = None) -> tuple[dict[str, int], dict[str, int]]:
    qo = select(MfgOperatorSkillRow.skill_id, func.count()).group_by(MfgOperatorSkillRow.skill_id)
    qp = select(MfgOperationRow.skill_id, func.count()).where(MfgOperationRow.skill_id.is_not(None)) \
        .group_by(MfgOperationRow.skill_id)
    if ids is not None:
        qo = qo.where(MfgOperatorSkillRow.skill_id.in_(ids))
        qp = qp.where(MfgOperationRow.skill_id.in_(ids))
    return ({k: int(v) for k, v in s.execute(qo).all()}, {k: int(v) for k, v in s.execute(qp).all()})


def _skill_record(s: Session, row: MfgSkillRow) -> SkillRecord:
    o, p = _skill_counts(s, [row.id])
    return repo.to_record(row, operator_count=o.get(row.id, 0), operation_count=p.get(row.id, 0))


def list_skills(ctx: AppContext, q: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        stmt = select(MfgSkillRow)
        if q:
            stmt = stmt.where(ilike(MfgSkillRow.code, q) | ilike(MfgSkillRow.name, q))
        rows = list(s.execute(stmt.order_by(MfgSkillRow.code, MfgSkillRow.id)).scalars())
        o, p = _skill_counts(s)
        return {"items": [repo.to_record(r, operator_count=o.get(r.id, 0), operation_count=p.get(r.id, 0))
                          for r in rows]}


def create_skill(ctx: AppContext, inp: SkillInput) -> SkillRecord:
    with write_tx(ctx) as (s, _):
        ensure_unique(s, MfgSkillRow, "A skill", {"code": inp.code})
        check_limit(s, MfgSkillRow, L.MAX_SKILLS, "skills")
        now = utcnow()
        row = MfgSkillRow(id=new_id("skl_"), code=inp.code, name=inp.name, description=inp.description,
                          row_version=1, created_at=now, updated_at=now)
        s.add(row)
        s.flush()
        audit(s, "skill", row.id, "create", {"version": 1})
        return repo.to_record(row)


def update_skill(ctx: AppContext, skill_id: str, inp: SkillInput, if_match: str | None) -> SkillRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgSkillRow, skill_id, what="Skill", lock=True)
        check_version(row, if_match)
        ensure_unique(s, MfgSkillRow, "A skill", {"code": inp.code}, exclude_id=row.id)
        row.code, row.name, row.description = inp.code, inp.name, inp.description
        touch(row)
        s.flush()
        audit(s, "skill", row.id, "update", {"version": row.row_version})
        return _skill_record(s, row)


def delete_skill(ctx: AppContext, skill_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgSkillRow, skill_id, what="Skill", lock=True)
        check_version(row, if_match)
        refs = {"operations": count(s, MfgOperationRow, MfgOperationRow.skill_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Skill {row.code}", refs)
        s.delete(row)
        s.flush()
        audit(s, "skill", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- tool pools


def _tool_counts(s: Session, ids: list[str] | None = None) -> dict[str, int]:
    q = select(MfgOperationToolRow.tool_pool_id, func.count(func.distinct(MfgOperationToolRow.operation_id))) \
        .group_by(MfgOperationToolRow.tool_pool_id)
    if ids is not None:
        q = q.where(MfgOperationToolRow.tool_pool_id.in_(ids))
    return {k: int(v) for k, v in s.execute(q).all()}


def list_tool_pools(ctx: AppContext, q: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        stmt = select(MfgToolPoolRow)
        if q:
            stmt = stmt.where(ilike(MfgToolPoolRow.code, q) | ilike(MfgToolPoolRow.name, q))
        rows = list(s.execute(stmt.order_by(MfgToolPoolRow.code, MfgToolPoolRow.id)).scalars())
        c = _tool_counts(s)
        return {"items": [repo.to_record(r, operation_count=c.get(r.id, 0)) for r in rows]}


def _set_pool(row: MfgToolPoolRow, inp: ToolPoolInput) -> None:
    row.code, row.name, row.kind, row.quantity, row.note = inp.code, inp.name, inp.kind, inp.quantity, inp.note


def create_tool_pool(ctx: AppContext, inp: ToolPoolInput) -> ToolPoolRecord:
    with write_tx(ctx) as (s, _):
        ensure_unique(s, MfgToolPoolRow, "A tool pool", {"code": inp.code})
        check_limit(s, MfgToolPoolRow, L.MAX_TOOL_POOLS, "tool pools")
        now = utcnow()
        row = MfgToolPoolRow(id=new_id("tlp_"), row_version=1, created_at=now, updated_at=now)
        _set_pool(row, inp)
        s.add(row)
        s.flush()
        audit(s, "tool_pool", row.id, "create", {"version": 1})
        return repo.to_record(row)


def update_tool_pool(ctx: AppContext, pool_id: str, inp: ToolPoolInput, if_match: str | None) -> ToolPoolRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgToolPoolRow, pool_id, what="Tool pool", lock=True)
        check_version(row, if_match)
        ensure_unique(s, MfgToolPoolRow, "A tool pool", {"code": inp.code}, exclude_id=row.id)
        _set_pool(row, inp)
        touch(row)
        s.flush()
        audit(s, "tool_pool", row.id, "update", {"version": row.row_version})
        return repo.to_record(row, operation_count=_tool_counts(s, [row.id]).get(row.id, 0))


def delete_tool_pool(ctx: AppContext, pool_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgToolPoolRow, pool_id, what="Tool pool", lock=True)
        check_version(row, if_match)
        refs = {"operations": count(s, MfgOperationToolRow, MfgOperationToolRow.tool_pool_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Tool pool {row.code}", refs)
        s.delete(row)
        s.flush()
        audit(s, "tool_pool", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- operators


def operator_records(s: Session, rows: list[MfgOperatorRow]) -> list[OperatorRecord]:
    if not rows:
        return []
    ids = [r.id for r in rows]
    links: dict[str, list[str]] = {}
    for oid, sid in s.execute(select(MfgOperatorSkillRow.operator_id, MfgOperatorSkillRow.skill_id)
                              .where(MfgOperatorSkillRow.operator_id.in_(ids))).all():
        links.setdefault(oid, []).append(sid)
    skill_ids = sorted({x for v in links.values() for x in v})
    skills = {k.id: k for k in s.execute(select(MfgSkillRow).where(MfgSkillRow.id.in_(skill_ids))).scalars()} \
        if skill_ids else {}
    tids = sorted({r.shift_template_id for r in rows if r.shift_template_id})
    tpls = {t.id: t for t in s.execute(select(MfgShiftTemplateRow).where(MfgShiftTemplateRow.id.in_(tids)))
            .scalars()} if tids else {}
    gids = sorted({r.home_group_id for r in rows if r.home_group_id})
    groups = {g.id: g for g in s.execute(select(MfgGroupRow).where(MfgGroupRow.id.in_(gids))).scalars()} \
        if gids else {}
    out = []
    for r in rows:
        sk = sorted((skills[x] for x in links.get(r.id, []) if x in skills), key=lambda k: k.code)
        out.append(repo.to_record(
            r, skill_ids=[k.id for k in sk], skills=[ref(k) for k in sk],
            shift_template=ref(tpls[r.shift_template_id]) if r.shift_template_id in tpls else None,
            home_group=ref(groups[r.home_group_id]) if r.home_group_id in groups else None))
    return out


def list_operators(ctx: AppContext, q: str | None, active: bool | None, skill_id: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        stmt = select(MfgOperatorRow)
        if q:
            stmt = stmt.where(ilike(MfgOperatorRow.code, q) | ilike(MfgOperatorRow.name, q))
        if active is not None:
            stmt = stmt.where(MfgOperatorRow.active.is_(active))
        if skill_id:
            stmt = stmt.where(MfgOperatorRow.id.in_(select(MfgOperatorSkillRow.operator_id)
                                                    .where(MfgOperatorSkillRow.skill_id == skill_id)))
        rows = list(s.execute(stmt.order_by(MfgOperatorRow.code, MfgOperatorRow.id)).scalars())
        return {"items": operator_records(s, rows)}


def _operator_refs(s: Session, inp: OperatorInput) -> None:
    if inp.skill_ids:
        found = set(s.execute(select(MfgSkillRow.id).where(MfgSkillRow.id.in_(inp.skill_ids))).scalars())
        for i, x in enumerate(inp.skill_ids):
            if x not in found:
                raise unknown_ref(["body", "skill_ids", i], x, "Skill")
    if inp.shift_template_id is not None:
        t = s.execute(select(MfgShiftTemplateRow).where(MfgShiftTemplateRow.id == inp.shift_template_id)) \
            .scalars().first()
        if t is None:
            raise unknown_ref(["body", "shift_template_id"], inp.shift_template_id, "Shift template")
        names = {sh["name"] for sh in t.shifts or []}
        bad = [n for n in inp.shift_names if n not in names]
        if bad:
            raise ApiError(422, "VALIDATION_ERROR", f"The shift template has no shift named {bad[0]!r}.",
                           {"errors": [{"loc": ["body", "shift_names", inp.shift_names.index(b)],
                                        "msg": f"unknown shift name {b!r}", "type": "value_error"} for b in bad]})
    if inp.home_group_id is not None and \
            s.execute(select(MfgGroupRow.id).where(MfgGroupRow.id == inp.home_group_id)).scalar() is None:
        raise unknown_ref(["body", "home_group_id"], inp.home_group_id, "Stage")


def _set_operator(s: Session, row: MfgOperatorRow, inp: OperatorInput, old: list[str]) -> None:
    row.code, row.name, row.active = inp.code, inp.name, inp.active
    row.shift_template_id, row.home_group_id = inp.shift_template_id, inp.home_group_id
    row.shift_names = list(inp.shift_names)
    s.flush()
    new, prev = set(inp.skill_ids), set(old)
    for x in sorted(prev - new):
        link_row = s.get(MfgOperatorSkillRow, (row.id, x))
        if link_row is not None:
            s.delete(link_row)
    for x in sorted(new - prev):
        s.add(MfgOperatorSkillRow(operator_id=row.id, skill_id=x))


def create_operator(ctx: AppContext, inp: OperatorInput) -> OperatorRecord:
    with write_tx(ctx) as (s, _):
        _operator_refs(s, inp)
        ensure_unique(s, MfgOperatorRow, "An operator", {"code": inp.code})
        check_limit(s, MfgOperatorRow, L.MAX_OPERATORS, "operators")
        now = utcnow()
        row = MfgOperatorRow(id=new_id("emp_"), row_version=1, created_at=now, updated_at=now)
        s.add(row)
        _set_operator(s, row, inp, [])
        s.flush()
        audit(s, "operator", row.id, "create", {"version": 1})
        return operator_records(s, [row])[0]


def get_operator(ctx: AppContext, operator_id: str) -> OperatorRecord:
    with read_tx(ctx) as s:
        return operator_records(s, [repo.get_row(s, MfgOperatorRow, operator_id, what="Operator")])[0]


def update_operator(ctx: AppContext, operator_id: str, inp: OperatorInput, if_match: str | None) -> OperatorRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgOperatorRow, operator_id, what="Operator", lock=True)
        check_version(row, if_match)
        _operator_refs(s, inp)
        ensure_unique(s, MfgOperatorRow, "An operator", {"code": inp.code}, exclude_id=row.id)
        old = list(s.execute(select(MfgOperatorSkillRow.skill_id).where(MfgOperatorSkillRow.operator_id == row.id))
                   .scalars())
        _set_operator(s, row, inp, old)
        touch(row)
        s.flush()
        audit(s, "operator", row.id, "update", {"version": row.row_version})
        return operator_records(s, [row])[0]


def delete_operator(ctx: AppContext, operator_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgOperatorRow, operator_id, what="Operator", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "operator", row.id, "delete", {"version": row.row_version})
