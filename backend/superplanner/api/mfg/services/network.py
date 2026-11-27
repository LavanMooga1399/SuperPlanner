"""M9 network service (M9-DESIGN 4, 5; N1-N16). Runs in the organisation's network workspace (bound owner).

Nodes = the organisation's `plant` and `dc` workspaces; lane / rule node ids must be nodes of the same organisation
(422 `NET_UNKNOWN_NODE` otherwise: cross-organisation ids are never resolved). Plant data is read per node inside
that node's owner scope (`network/build.py`); records link into a plant only for its members.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg.network import build as B
from ....mfg.network import engine as E
from ....mfg.network import peg as PEG
from ....mfg.network import validator as VAL
from ....mfg.network.model import (NET_SETTINGS_DEFAULTS, NetError, NetLane, NetParams, NetRule)
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...db.ownership import current_owner, owner_scope, system_scope
from ...errors import ApiError
from .. import repo
from ..db_models_m9 import (MfgNetLaneRow, MfgNetProductionRow, MfgNetProjectionRow, MfgNetRampCurveRow,
                            MfgNetRunRow, MfgNetShortageRow, MfgNetSourcingRow, MfgNetTransferRow)
from . import m9_examples
from .common import audit, check_version, jsonable, read_tx, write_tx
from .m8common import next_number, page, start_job, today

STD26 = [{"week": 0, "rate_pct": 25, "yield_pct": 85}, {"week": 4, "rate_pct": 50, "yield_pct": 90},
         {"week": 8, "rate_pct": 75, "yield_pct": 94}, {"week": 13, "rate_pct": 90, "yield_pct": 97},
         {"week": 26, "rate_pct": 100, "yield_pct": 98}]
RETAIN_RUNS = 60


# ---------------------------------------------------------------- workspace, settings, nodes

def seed_workspace(s: Session) -> None:
    """A new network workspace: ramp curve `STD26` (6.4) and the policy `sop_cycle.approve` (6.6)."""
    if s.execute(select(MfgNetRampCurveRow.id).where(MfgNetRampCurveRow.code == "STD26")).first() is None:
        now = utcnow()
        s.add(MfgNetRampCurveRow(id=new_id("rmp_"), code="STD26", name="Standard 26-week ramp", points=STD26,
                                 row_version=1, created_at=now, updated_at=now))
    from .esig import seed_policies

    seed_policies(s)


def net_settings(s: Session) -> dict[str, Any]:
    from ..db_models import MfgPlantRow

    raw = s.execute(select(MfgPlantRow.planning_settings)).scalar() or {}
    return {k: raw.get(k, v) for k, v in NET_SETTINGS_DEFAULTS.items()}


def require_network(s: Session) -> str:
    """The bound workspace's organisation id (the guard in `access` already checked the kind)."""
    owner = str(current_owner())
    from ..db_models_m5 import OrgPlantRow

    with system_scope():
        org = s.execute(select(OrgPlantRow.org_id).where(OrgPlantRow.plant_owner_id == owner)).scalar()
    if org is None:
        raise ApiError(409, "NET_WORKSPACE_REQUIRED", "This page belongs to the organisation's network workspace.", {})
    return org


def org_nodes(s: Session, user_id: str | None = None) -> list[dict[str, Any]]:
    """The organisation's plant and DC nodes (system scope; ordered by code)."""
    from ....mfg.model import plant_locale
    from ..db_models import MfgLineRow, MfgPlantRow
    from ..db_models_m2 import MfgPlantMemberRow
    from ..db_models_m5 import OrgPlantRow

    org = require_network(s)
    with system_scope():
        rows = s.execute(select(OrgPlantRow, MfgPlantRow).outerjoin(
            MfgPlantRow, MfgPlantRow.owner_id == OrgPlantRow.plant_owner_id).where(OrgPlantRow.org_id == org)
            .order_by(OrgPlantRow.code)).all()
        owners = [o.plant_owner_id for o, _p in rows]
        lines = dict(s.execute(select(MfgLineRow.owner_id, func.count()).where(MfgLineRow.owner_id.in_(owners))
                               .group_by(MfgLineRow.owner_id)).all()) if owners else {}
        members = set(s.execute(select(MfgPlantMemberRow.owner_id).where(
            MfgPlantMemberRow.user_id == user_id, MfgPlantMemberRow.active.is_(True),
            MfgPlantMemberRow.owner_id.in_(owners))).scalars()) if user_id and owners else set()
    out = []
    for o, p in rows:
        kind = p.kind if p is not None else "plant"
        if kind == "network":
            continue
        country, _loc = plant_locale(p.attributes if p else None, p.currency if p else None,
                                     p.time_zone if p else None)
        out.append({"owner_id": o.plant_owner_id, "code": o.code, "name": o.name, "kind": kind,
                    "country": country, "currency": (p.currency if p else None) or "USD",
                    "tz": (p.time_zone or p.utc_offset) if p else "UTC", "member": o.plant_owner_id in members,
                    "lines": int(lines.get(o.plant_owner_id, 0))})
    return out


def _node_ids(s: Session) -> dict[str, dict[str, Any]]:
    return {n["owner_id"]: n for n in org_nodes(s)}


def _check_nodes(nodes: dict[str, Any], *ids: str | None) -> None:
    for i in ids:
        if i is not None and i not in nodes:
            raise ApiError(422, "NET_UNKNOWN_NODE", "This node is not a plant or DC of the organisation.", {"id": i})


def list_nodes(ctx: AppContext, a: Any) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return {"items": org_nodes(s, a.user_id)}


# ---------------------------------------------------------------- lanes (N2-N4)

def _lane(r: MfgNetLaneRow) -> dict[str, Any]:
    return {"id": r.id, "from_owner_id": r.from_owner_id, "to_owner_id": r.to_owner_id, "mode": r.mode,
            "transit_days": r.transit_days, "freight_per_unit": r.freight_per_unit, "freight_per_kg": r.freight_per_kg,
            "currency": r.currency, "active": r.active, "row_version": r.row_version, "updated_at": r.updated_at}


def list_lanes(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        require_network(s)
        rows = s.execute(select(MfgNetLaneRow).order_by(MfgNetLaneRow.from_owner_id, MfgNetLaneRow.to_owner_id,
                                                        MfgNetLaneRow.mode)).scalars()
        return {"items": [_lane(r) for r in rows]}


def _dup_lane(s: Session, body: Any, own_id: str | None) -> None:
    q = select(MfgNetLaneRow.id).where(MfgNetLaneRow.from_owner_id == body.from_owner_id,
                                       MfgNetLaneRow.to_owner_id == body.to_owner_id, MfgNetLaneRow.mode == body.mode)
    if own_id:
        q = q.where(MfgNetLaneRow.id != own_id)
    if s.execute(q).first():
        raise ApiError(409, "MFG_DUPLICATE_KEY", "This lane exists.", {"key": {"from": body.from_owner_id,
                                                                               "to": body.to_owner_id,
                                                                               "mode": body.mode}})


def create_lane(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _check_nodes(_node_ids(s), body.from_owner_id, body.to_owner_id)
        _dup_lane(s, body, None)
        now = utcnow()
        r = MfgNetLaneRow(id=new_id("nln_"), **body.model_dump(), row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "net_lane", r.id, "create", body.model_dump(mode="json"))
        return _lane(r)


def update_lane(ctx: AppContext, a: Any, lane_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgNetLaneRow, lane_id, what="Lane", lock=True)
        check_version(r, if_match)
        _check_nodes(_node_ids(s), body.from_owner_id, body.to_owner_id)
        _dup_lane(s, body, r.id)
        before = _lane(r)
        for k, v in body.model_dump().items():
            setattr(r, k, v)
        r.row_version += 1
        r.updated_at = utcnow()
        s.flush()
        audit(s, "net_lane", r.id, "update", None, before=before, after=_lane(r))
        return _lane(r)


def delete_lane(ctx: AppContext, a: Any, lane_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgNetLaneRow, lane_id, what="Lane", lock=True)
        check_version(r, if_match)
        if s.execute(select(MfgNetSourcingRow.id).where(MfgNetSourcingRow.lane_id == r.id,
                                                        MfgNetSourcingRow.active.is_(True))).first():
            raise ApiError(409, "MFG_IN_USE", "Active sourcing rules use this lane.", {"id": r.id})
        audit(s, "net_lane", r.id, "delete", jsonable(_lane(r)))
        s.delete(r)


# ---------------------------------------------------------------- sourcing (N5-N7)

def _rule(r: MfgNetSourcingRow) -> dict[str, Any]:
    return {"id": r.id, "dest_owner_id": r.dest_owner_id, "item_key": r.item_key, "family": r.family,
            "source_kind": r.source_kind, "source_owner_id": r.source_owner_id, "supplier_code": r.supplier_code,
            "priority": r.priority, "quota_pct": r.quota_pct, "lane_id": r.lane_id, "valid_from": r.valid_from,
            "valid_to": r.valid_to, "active": r.active, "row_version": r.row_version, "updated_at": r.updated_at}


def list_sourcing(ctx: AppContext, dest: str | None, key: str | None, family: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        require_network(s)
        q = select(MfgNetSourcingRow)
        if dest:
            q = q.where(MfgNetSourcingRow.dest_owner_id == dest)
        if key:
            q = q.where(MfgNetSourcingRow.item_key == key)
        if family:
            q = q.where(MfgNetSourcingRow.family == family)
        rows = s.execute(q.order_by(MfgNetSourcingRow.dest_owner_id, MfgNetSourcingRow.item_key,
                                    MfgNetSourcingRow.family, MfgNetSourcingRow.priority, MfgNetSourcingRow.id)
                         ).scalars()
        return {"items": [_rule(r) for r in rows]}


def _check_rule(s: Session, body: Any) -> None:
    _check_nodes(_node_ids(s), body.dest_owner_id, body.source_owner_id)
    if body.lane_id:
        ln = s.execute(select(MfgNetLaneRow).where(MfgNetLaneRow.id == body.lane_id)).scalars().first()
        if ln is None or ln.from_owner_id != body.source_owner_id or ln.to_owner_id != body.dest_owner_id:
            raise ApiError(422, "NET_NO_LANE", "The lane does not join the source to the destination.",
                           {"lane_id": body.lane_id})
    elif body.source_kind == "plant" and not s.execute(select(MfgNetLaneRow.id).where(
            MfgNetLaneRow.from_owner_id == body.source_owner_id, MfgNetLaneRow.to_owner_id == body.dest_owner_id,
            MfgNetLaneRow.active.is_(True))).first():
        raise ApiError(422, "NET_NO_LANE", "There is no active lane from the source to the destination.",
                       {"from": body.source_owner_id, "to": body.dest_owner_id})


def create_sourcing(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _check_rule(s, body)
        now = utcnow()
        r = MfgNetSourcingRow(id=new_id("nsg_"), **body.model_dump(), row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "net_sourcing", r.id, "create", body.model_dump(mode="json"))
        return _rule(r)


def update_sourcing(ctx: AppContext, a: Any, rule_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgNetSourcingRow, rule_id, what="Sourcing rule", lock=True)
        check_version(r, if_match)
        _check_rule(s, body)
        before = _rule(r)
        for k, v in body.model_dump().items():
            setattr(r, k, v)
        r.row_version += 1
        r.updated_at = utcnow()
        s.flush()
        audit(s, "net_sourcing", r.id, "update", None, before=before, after=_rule(r))
        return _rule(r)


def delete_sourcing(ctx: AppContext, a: Any, rule_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgNetSourcingRow, rule_id, what="Sourcing rule", lock=True)
        check_version(r, if_match)
        audit(s, "net_sourcing", r.id, "delete", jsonable(_rule(r)))
        s.delete(r)


def _rules(s: Session) -> list[NetRule]:
    return [NetRule(r.id, r.dest_owner_id, r.item_key, r.family, r.source_kind, r.source_owner_id, r.supplier_code,
                    r.priority, r.quota_pct, r.lane_id, r.valid_from, r.valid_to)
            for r in s.execute(select(MfgNetSourcingRow).where(MfgNetSourcingRow.active.is_(True))
                               .order_by(MfgNetSourcingRow.id)).scalars()]


def _lanes(s: Session) -> list[NetLane]:
    return [NetLane(r.id, r.from_owner_id, r.to_owner_id, r.mode, r.transit_days, r.freight_per_unit, r.active)
            for r in s.execute(select(MfgNetLaneRow).order_by(MfgNetLaneRow.id)).scalars()]


def _family_of(s: Session, node: str, key: str) -> str | None:
    from ..db_models import MfgItemRow

    with owner_scope(node):
        row = s.execute(select(MfgItemRow.family).where((MfgItemRow.external_ref == key) | (
            (MfgItemRow.part_number == key) & MfgItemRow.external_ref.is_(None)))).first()
    return row[0] if row else None


def resolve(ctx: AppContext, dest: str, key: str, at: date | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        nodes = _node_ids(s)
        _check_nodes(nodes, dest)
        at = at or today(s)
        fam = _family_of(s, dest, key)
        lanes = _lanes(s)
        rs = [r for r in _rules(s) if r.dest == dest and (r.valid_from is None or r.valid_from <= at)
              and (r.valid_to is None or r.valid_to >= at)]
        by_key = [r for r in rs if r.key == key]
        chosen = by_key or [r for r in rs if r.key is None and fam is not None and r.family == fam]
        chosen.sort(key=lambda r: (r.priority, r.id))
        warnings = []
        quota = any(r.quota_pct is not None for r in chosen)
        if quota and abs(sum(r.quota_pct or 0 for r in chosen) - 100) > 0.01:
            warnings.append("NET_QUOTA_SUM")

        def transit(r: NetRule) -> int | None:
            if r.source_kind != "plant":
                return None
            cands = [ln for ln in lanes if ln.active and (ln.id == r.lane_id if r.lane_id else (
                ln.src == r.source and ln.dst == r.dest))]
            if not cands:
                warnings.append("NET_NO_LANE")
                return None
            return min(ln.transit_days for ln in cands)
        return {"dest_owner_id": dest, "key": key, "date": at, "family": fam,
                "matched_by": "item" if by_key else ("family" if chosen else None),
                "mode": "none" if not chosen else ("quota" if quota else "priority"),
                "sources": [{"rule_id": r.id, "source_kind": r.source_kind, "source_owner_id": r.source,
                             "supplier_code": r.supplier_code, "priority": r.priority, "quota_pct": r.quota_pct,
                             "lane_id": r.lane_id, "transit_days": transit(r)} for r in chosen],
                "warnings": sorted(set(warnings))}


# ---------------------------------------------------------------- ramp curves (N16)

def get_curves(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        require_network(s)
        return {"items": [{"code": r.code, "name": r.name, "points": r.points} for r in s.execute(
            select(MfgNetRampCurveRow).order_by(MfgNetRampCurveRow.code)).scalars()]}


def put_curves(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        require_network(s)
        codes = [c.code for c in body.curves]
        if len(codes) != len(set(codes)):
            raise ApiError(422, "MFG_DUPLICATE_KEY", "Curve codes are unique.", {})
        old = {r.code: r for r in s.execute(select(MfgNetRampCurveRow)).scalars()}
        now = utcnow()
        for c in body.curves:
            pts = [p.model_dump() for p in c.points]
            r = old.pop(c.code, None)
            if r is None:
                s.add(MfgNetRampCurveRow(id=new_id("rmp_"), code=c.code, name=c.name, points=pts, row_version=1,
                                         created_at=now, updated_at=now))
            elif r.name != c.name or r.points != pts:
                r.name, r.points, r.row_version, r.updated_at = c.name, pts, r.row_version + 1, now
        for r in old.values():
            s.delete(r)
        s.flush()
        audit(s, "ramp_curves", None, "replace", {"codes": codes})
    return get_curves(ctx)


# ---------------------------------------------------------------- runs (N8-N13)

def _run(r: MfgNetRunRow) -> dict[str, Any]:
    summ = dict(r.summary or {})
    summ.pop("items", None)
    return {"id": r.id, "number": r.number, "label": r.label, "status": r.status, "as_of": r.as_of,
            "params": {k: v for k, v in (r.params or {}).items() if not k.startswith("_")},
            "input_hash": r.input_hash, "summary": summ or None, "validator": r.validator,
            "explanations": (r.explanations or [])[:200], "published": r.published, "published_at": r.published_at,
            "published_by": r.published_by, "publish_result": r.publish_result, "error": r.error,
            "actor_id": r.actor_id, "created_at": r.created_at, "started_at": r.started_at,
            "finished_at": r.finished_at, "duration_ms": r.duration_ms}


def list_runs(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        require_network(s)
        n = int(s.execute(select(func.count()).select_from(MfgNetRunRow)).scalar() or 0)
        rows = s.execute(select(MfgNetRunRow).order_by(MfgNetRunRow.created_at.desc(), MfgNetRunRow.number.desc())
                         .limit(limit).offset(offset)).scalars()
        return page([_run(r) for r in rows], n, limit, offset)


def preflight(rules: list[NetRule], lanes: list[NetLane], codes: dict[str, str]) -> None:
    """Synchronous checks of `POST /net/runs` (422): quota sums, lanes of plant rules, rule loops per key /
    family (loops through BOMs or mixed key / family rules surface as a failed run with `NET_CYCLE`)."""
    sets: dict[tuple[str, str | None, str | None], list[NetRule]] = defaultdict(list)
    for r in rules:
        sets[(r.dest, r.key, r.family)].append(r)
    for (dest, key, fam), rs in sorted(sets.items(), key=lambda x: str(x[0])):
        if any(r.quota_pct is not None for r in rs):
            tot = sum(r.quota_pct or 0 for r in rs)
            if abs(tot - 100) > 0.01:
                raise ApiError(422, "NET_QUOTA_SUM", f"The quotas for {key or fam} at {codes.get(dest, dest)} sum "
                               f"to {tot:g} %, not 100 %.", {"dest": dest, "key": key, "family": fam, "sum": tot})
    for r in rules:
        if r.source_kind == "plant" and not any(ln.active and ((ln.id == r.lane_id) if r.lane_id else (
                ln.src == r.source and ln.dst == r.dest)) for ln in lanes):
            raise ApiError(422, "NET_NO_LANE", "A sourcing rule has no active lane.", {"rule_id": r.id})
    graph: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rules:
        if r.source_kind == "plant" and r.source:
            graph[(r.key or "", r.family or "")].add(f"{r.dest}>{r.source}")
    for label, edges in graph.items():
        adj: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            a, b = e.split(">")
            adj[a].append(b)
        state: dict[str, int] = {}

        def dfs(n: str, path: list[str]) -> None:
            state[n] = 1
            for m in sorted(adj.get(n, [])):
                if state.get(m) == 1:
                    cyc = path[path.index(m):] + [m] if m in path else [n, m]
                    raise ApiError(422, "NET_CYCLE", "The sourcing rules form a loop: " + " -> ".join(
                        codes.get(x, x) for x in cyc) + f" ({label[0] or label[1]}).",
                        {"path": [{"node": x, "code": codes.get(x, x)} for x in cyc],
                         "key": label[0] or None, "family": label[1] or None})
                if state.get(m) is None:
                    dfs(m, path + [m])
            state[n] = 2

        for n in sorted(adj):
            if state.get(n) is None:
                dfs(n, [n])


def create_run(ctx: AppContext, a: Any, body: NetParams) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        nodes = _node_ids(s)
        if body.node_ids:
            _check_nodes(nodes, *body.node_ids)
        for n, v in (body.forecast_versions or {}).items():
            _check_nodes(nodes, n)
        preflight(_rules(s), _lanes(s), {k: v["code"] for k, v in nodes.items()})
        st = net_settings(s)
        as_of = body.as_of or today(s)
        r = MfgNetRunRow(id=new_id("nrn_"), number=next_number(s, "NR", MfgNetRunRow), label=body.label,
                         params=body.model_dump(mode="json", exclude={"label"}) | {"_settings": st},
                         status="queued", as_of=as_of, input_hash=None, summary=None, validator=None,
                         explanations=None, published=False, published_at=None, published_by=None,
                         publish_result=None, error=None, actor_id=a.user_id, created_at=utcnow(), started_at=None,
                         finished_at=None, duration_ms=None)
        s.add(r)
        s.flush()
        _rid, job = start_job(s, ctx, "net_run", r.owner_id, {"run_id": r.id})
        audit(s, "net_run", r.id, "create", {"number": r.number, "params": r.params})
        rec = _run(r)
    ctx.jobs.dispatch(job)
    return rec


def snapshot(ctx: AppContext, params: NetParams, as_of: date, st: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """The NetProblem of the bound network workspace + item names per node (one snapshot per node, 5.2)."""
    from ..repo_m2 import snapshot_tx

    with read_tx(ctx) as s:
        nodes = org_nodes(s)
        rules, lanes = _rules(s), _lanes(s)
    if params.node_ids:
        nodes = [n for n in nodes if n["owner_id"] in params.node_ids]
    horizon = params.horizon_weeks or int(st["net_horizon_weeks"])
    parts = []
    for n in nodes:
        with owner_scope(n["owner_id"]), snapshot_tx(ctx.db) as s:
            fv = (params.forecast_versions or {}).get(n["owner_id"])
            parts.append(B.build_node(s, n, as_of, horizon, fv))
    ids = {n["owner_id"] for n in nodes}
    rules = [r for r in rules if r.dest in ids and (r.source is None or r.source in ids)]
    p = B.assemble(parts, rules, lanes, as_of=as_of, horizon=horizon,
                   constrained=params.constrained if params.constrained is not None else bool(st["net_constrained"]),
                   prebuild=params.prebuild_weeks if params.prebuild_weeks is not None
                   else int(st["net_prebuild_weeks"]),
                   firm_days=params.firm_days if params.firm_days is not None else int(st["net_firm_days"]),
                   currency=st["report_currency"])
    names = {pt.node.id: {k: [pt.item_ids.get(k), *pt.names[k]] for k in pt.names} for pt in parts}
    return p, names


def _hash(p: Any) -> str:
    def enc(o: Any) -> Any:
        if hasattr(o, "__dataclass_fields__"):
            return {k: enc(getattr(o, k)) for k in o.__dataclass_fields__}
        if isinstance(o, (list, tuple)):
            return [enc(x) for x in o]
        if isinstance(o, (set, frozenset)):
            return sorted(enc(x) for x in o)
        if isinstance(o, dict):
            return {str(k): enc(v) for k, v in o.items()}
        if isinstance(o, date):
            return o.isoformat()
        return o
    return hashlib.sha256(json.dumps(enc(p), sort_keys=True, default=str).encode()).hexdigest()


def compute(ctx: AppContext, run_id: str) -> dict[str, Any]:
    t0 = time.monotonic()
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgNetRunRow, run_id, with_for_update=True)
        if r is None:
            return {"error": "run gone"}
        r.status, r.started_at = "running", utcnow()
        params = NetParams.model_validate({k: v for k, v in r.params.items() if not k.startswith("_")})
        st = r.params.get("_settings") or NET_SETTINGS_DEFAULTS
        as_of = r.as_of
    timings: dict[str, float] = {}
    try:
        p, names = snapshot(ctx, params, as_of, st)
        timings["snapshot_s"] = round(time.monotonic() - t0, 3)
        t1 = time.monotonic()
        res = E.solve(p)
        timings["engine_s"] = round(time.monotonic() - t1, 3)
        t2 = time.monotonic()
        rep = VAL.validate(p, res)
        timings["validator_s"] = round(time.monotonic() - t2, 3)
    except NetError as exc:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgNetRunRow, run_id, with_for_update=True)
            r.status, r.error, r.finished_at = "failed", f"{exc.code}: {exc.message}"[:2000], utcnow()
            r.explanations = [{"code": exc.code, "detail": jsonable(exc.details)}]
            r.duration_ms = int((time.monotonic() - t0) * 1000)
        return {"status": "failed", "error": exc.code}
    store(ctx, run_id, p, res, rep, names, timings, t0)
    return {"status": "completed", "validator_ok": rep["ok"], **timings}


def store(ctx: AppContext, run_id: str, p: Any, res: Any, rep: dict[str, Any], names: dict[str, Any],
          timings: dict[str, float], t0: float) -> None:
    def pj(pegs: list[Any]) -> list[dict[str, Any]]:
        return [{"node": g.node, "kind": g.kind, "ref": g.ref, "qty": g.qty, "late_weeks": g.late_weeks}
                for g in pegs]

    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgNetRunRow, run_id, with_for_update=True)
        owner = r.owner_id
        tr = [{"id": new_id("npt_"), "owner_id": owner, "run_id": run_id, "src_owner_id": t.src, "dst_owner_id": t.dst,
               "item_key": t.key, "lane_id": t.lane_id, "ship_date": t.ship_date, "receive_date": t.receive_date,
               "qty": t.qty, "firm": t.firm, "to_id": None, "pegs": pj(t.pegs)} for t in res.transfers]
        pr = [{"id": new_id("npp_"), "owner_id": owner, "run_id": run_id, "node_owner_id": x.node, "item_key": x.key,
               "week": x.week, "qty": x.qty, "kind": x.kind, "cap_group": x.cap_group or x.supplier_code,
               "hours": x.hours, "prebuilt_from": x.prebuilt_from, "pegs": pj(x.pegs)} for x in res.production]
        sh = [{"id": new_id("nsh_"), "owner_id": owner, "run_id": run_id, "node_owner_id": x.node, "item_key": x.key,
               "week": x.week, "qty": x.qty, "cause": x.cause, "detail": jsonable(x.detail)} for x in res.shortages]
        pj_rows = [{"id": new_id("npj_"), "owner_id": owner, "run_id": run_id, "node_owner_id": x.node,
                    "item_key": x.key, "week": x.week, "gross": x.gross, "receipts": x.receipts,
                    "planned_in": x.planned_in, "planned_out": x.planned_out, "projected": x.projected, "ss": x.ss}
                   for x in res.projection]
        for model, rows in ((MfgNetTransferRow, tr), (MfgNetProductionRow, pr), (MfgNetShortageRow, sh),
                            (MfgNetProjectionRow, pj_rows)):
            for i in range(0, len(rows), 5000):
                s.execute(model.__table__.insert(), rows[i:i + 5000])
        util = [{"node": u.node, "cap_group": u.cap_group, "week": u.week.isoformat(), "available": u.available,
                 "used": u.used} for u in res.utilisation]
        r.summary = {**res.kpis, "items": names, "utilisation": util, "timings": timings,
                     "weeks": [w.isoformat() for w in res.weeks]}
        r.validator = rep
        r.explanations = jsonable(res.explanations)[:2000]
        r.input_hash = _hash(p)
        r.status, r.finished_at = "completed", utcnow()
        r.duration_ms = int((time.monotonic() - t0) * 1000)
        _retention(s)


def _retention(s: Session) -> None:
    keep = [x for x, in s.execute(select(MfgNetRunRow.id).order_by(MfgNetRunRow.created_at.desc())
                                  .limit(RETAIN_RUNS)).all()]
    s.execute(delete(MfgNetRunRow).where(MfgNetRunRow.id.not_in(keep), MfgNetRunRow.published.is_(False),
                                         MfgNetRunRow.status.in_(("completed", "failed"))))


def run_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    return compute(ctx, info["params"]["run_id"])


def _get_run(s: Session, run_id: str) -> MfgNetRunRow:
    return repo.get_row(s, MfgNetRunRow, run_id, what="Network run")


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _run(_get_run(s, run_id))


def _names(r: MfgNetRunRow) -> dict[str, dict[str, list[Any]]]:
    return (r.summary or {}).get("items") or {}


def _uom(names: dict[str, Any], node: str, key: str) -> str:
    v = names.get(node, {}).get(key)
    return (v[3] if v and len(v) > 3 else None) or "EA"


def grid(ctx: AppContext, run_id: str, node: str | None, key: str | None, family: str | None, page_no: int,
         limit: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _get_run(s, run_id)
        names = _names(r)
        q = select(MfgNetProjectionRow.node_owner_id, MfgNetProjectionRow.item_key).where(
            MfgNetProjectionRow.run_id == r.id).distinct()
        if node:
            q = q.where(MfgNetProjectionRow.node_owner_id == node)
        if key:
            q = q.where(MfgNetProjectionRow.item_key == key)
        pairs = sorted(s.execute(q).all())
        if family:
            pairs = [x for x in pairs if (names.get(x[0], {}).get(x[1]) or [None, None, None])[2] == family]
        n = len(pairs)
        off = (page_no - 1) * limit
        chosen = pairs[off:off + limit]
        rows: dict[tuple[str, str], list[Any]] = defaultdict(list)
        if chosen:
            nodes = {x[0] for x in chosen}
            keys = {x[1] for x in chosen}
            for x in s.execute(select(MfgNetProjectionRow).where(
                    MfgNetProjectionRow.run_id == r.id, MfgNetProjectionRow.node_owner_id.in_(nodes),
                    MfgNetProjectionRow.item_key.in_(keys)).order_by(MfgNetProjectionRow.week)).scalars():
                if (x.node_owner_id, x.item_key) in set(chosen):
                    rows[(x.node_owner_id, x.item_key)].append(x)
        items = []
        for nd, k in chosen:
            meta = names.get(nd, {}).get(k) or [None, None, None, "EA"]
            items.append({"node_owner_id": nd, "item_key": k, "item_id": meta[0], "description": meta[1],
                          "family": meta[2], "uom": meta[3] or "EA",
                          "cells": [{"week": x.week, "gross": x.gross, "receipts": x.receipts,
                                     "planned_in": x.planned_in, "planned_out": x.planned_out,
                                     "projected": x.projected, "ss": x.ss} for x in rows[(nd, k)]]})
        weeks = (r.summary or {}).get("weeks") or []
        return {"items": items, "total": n, "limit": limit, "offset": off, "weeks": weeks}


def _to_numbers(s: Session, ids: set[str]) -> dict[str, str]:
    from ..db_models_m5 import MfgTransferOrderRow

    if not ids:
        return {}
    with system_scope():
        return dict(s.execute(select(MfgTransferOrderRow.id, MfgTransferOrderRow.number).where(
            MfgTransferOrderRow.id.in_(ids))).all())


def _transfer(t: MfgNetTransferRow, names: dict[str, Any], numbers: dict[str, str]) -> dict[str, Any]:
    return {"id": t.id, "src_owner_id": t.src_owner_id, "dst_owner_id": t.dst_owner_id, "item_key": t.item_key,
            "lane_id": t.lane_id, "ship_date": t.ship_date, "receive_date": t.receive_date, "qty": t.qty,
            "uom": _uom(names, t.dst_owner_id, t.item_key), "firm": t.firm, "to_id": t.to_id,
            "to_number": numbers.get(t.to_id or ""), "pegs": [{k: p[k] for k in ("node", "kind", "ref", "qty")}
                                                              for p in t.pegs]}


def transfers(ctx: AppContext, run_id: str, src: str | None, dst: str | None, limit: int, offset: int
              ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _get_run(s, run_id)
        q = select(MfgNetTransferRow).where(MfgNetTransferRow.run_id == r.id)
        if src:
            q = q.where(MfgNetTransferRow.src_owner_id == src)
        if dst:
            q = q.where(MfgNetTransferRow.dst_owner_id == dst)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = list(s.execute(q.order_by(MfgNetTransferRow.ship_date, MfgNetTransferRow.src_owner_id,
                                         MfgNetTransferRow.dst_owner_id, MfgNetTransferRow.item_key)
                              .limit(limit).offset(offset)).scalars())
        nums = _to_numbers(s, {t.to_id for t in rows if t.to_id})
        return page([_transfer(t, _names(r), nums) for t in rows], n, limit, offset)


def shortages(ctx: AppContext, run_id: str, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _get_run(s, run_id)
        q = select(MfgNetShortageRow).where(MfgNetShortageRow.run_id == r.id)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = s.execute(q.order_by(MfgNetShortageRow.week, MfgNetShortageRow.node_owner_id,
                                    MfgNetShortageRow.item_key, MfgNetShortageRow.cause).limit(limit)
                         .offset(offset)).scalars()
        names = _names(r)
        return page([{"id": x.id, "node_owner_id": x.node_owner_id, "item_key": x.item_key, "week": x.week,
                      "qty": x.qty, "uom": _uom(names, x.node_owner_id, x.item_key), "cause": x.cause,
                      "detail": x.detail} for x in rows], n, limit, offset)


def utilisation(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _get_run(s, run_id)
        return {"items": (r.summary or {}).get("utilisation") or []}


def _objects(s: Session, run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objs: list[dict[str, Any]] = []
    tos = []
    for t in s.execute(select(MfgNetTransferRow).where(MfgNetTransferRow.run_id == run_id)).scalars():
        objs.append({"id": t.id, "type": "transfer", "src": t.src_owner_id, "dst": t.dst_owner_id,
                     "node": t.dst_owner_id, "key": t.item_key, "week": t.ship_date, "qty": t.qty, "pegs": t.pegs,
                     "to_id": t.to_id})
        if t.to_id:
            tos.append(t.to_id)
    nums = _to_numbers(s, set(tos))
    for o in objs:
        o["to_number"] = nums.get(o.get("to_id") or "")
    for x in s.execute(select(MfgNetProductionRow).where(MfgNetProductionRow.run_id == run_id)).scalars():
        objs.append({"id": x.id, "type": "production", "node": x.node_owner_id, "key": x.item_key, "week": x.week,
                     "qty": x.qty, "pegs": x.pegs, "kind": x.kind,
                     "supplier_code": x.cap_group if x.kind == "buy" else None})
    sh = [{"id": x.id, "node": x.node_owner_id, "key": x.item_key, "week": x.week, "qty": x.qty, "cause": x.cause,
           "detail": x.detail} for x in s.execute(select(MfgNetShortageRow).where(
               MfgNetShortageRow.run_id == run_id)).scalars()]
    return objs, sh


def pegging(ctx: AppContext, a: Any, run_id: str, node: str | None, key: str | None, week: date | None,
            supply_id: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _get_run(s, run_id)
        members = {n["owner_id"] for n in org_nodes(s, a.user_id) if n["member"]}
        objs, sh = _objects(s, r.id)

    def link(nd: str, o: dict[str, Any]) -> str | None:
        """UI routes of the plant records (only for members of that plant)."""
        if nd not in members:
            return None
        if o.get("type") == "transfer":
            return f"/mfg/transfers/{o['to_id']}" if o.get("to_id") else "/mfg/transfers"
        if o.get("type") == "production":
            return "/mfg/purchasing" if o.get("kind") == "buy" else "/mfg/work-orders"
        if o.get("type") == "demand" and o.get("ref"):
            return f"/mfg/demand?search={o['ref'].split('/')[0]}"
        return None

    if supply_id:
        o = next((x for x in objs if x["id"] == supply_id), None)
        if o is None:
            raise ApiError(404, "NOT_FOUND", "Planned supply not found.", {"id": supply_id})
        return {"direction": "up", "root": PEG.up(o, link)}
    if not node or not key:
        raise ApiError(422, "VALIDATION_ERROR", "Give node and key, or supply_id.",
                       {"errors": [{"loc": ["query", "node"], "msg": "required", "type": "missing"}]})
    refs: dict[str, float] = defaultdict(float)
    for o in objs:
        at = (o["dst"] if o["type"] == "transfer" else o["node"], o["key"])
        if at != (node, key) or (week is not None and o["week"] > week + timedelta(days=6)):
            continue
        for p in o["pegs"]:
            if p["node"] == node and p["kind"] != "ss":
                refs[p["ref"]] += p["qty"]
    for x in sh:
        if (x["node"], x["key"]) == (node, key) and x["detail"].get("final"):
            for p in x["detail"].get("pegs", []):
                refs[p["ref"]] += 0.0
    def tree(ref: str, q: float) -> dict[str, Any]:
        t = PEG.down(ref, node, key, week, round(q, 6), objs, sh, link)
        if not ref.startswith(("FC:", "SS:")):
            t["link"] = link(node, {"type": "demand", "ref": ref})
        return t

    if len(refs) == 1:
        ref, q = next(iter(refs.items()))
        return {"direction": "down", "root": tree(ref, q)}
    kids = [tree(ref, q) for ref, q in sorted(refs.items())[:50]]
    return {"direction": "down", "root": {"id": f"v:{node}:{key}", "kind": "demand", "node_owner_id": node,
                                          "item_key": key, "week": week, "qty": round(sum(refs.values()), 6),
                                          "ref": None, "cause": None, "link": None, "children": kids}}


# ---------------------------------------------------------------- publish (5.4; N15) and plant MRP inputs

class _Lines:
    def __init__(self, lines: list[Any]):
        self.lines = lines


class _Line:
    def __init__(self, item_id: str, qty: float, ship: date, recv: date):
        self.item_id, self.qty, self.ship_date, self.receive_date, self.line_no = item_id, qty, ship, recv, None


def _key_of_items(s: Session, owner: str, ids: set[str]) -> dict[str, str]:
    from ..db_models import MfgItemRow

    if not ids:
        return {}
    with system_scope():
        return {r.id: B.key_of(r) for r in s.execute(select(MfgItemRow).where(MfgItemRow.owner_id == owner,
                                                                                MfgItemRow.id.in_(ids))).scalars()}


def _to_summary(o: Any, lines: list[Any]) -> dict[str, Any]:
    return {"to_id": o.id, "number": o.number, "src_owner_id": o.source_owner_id, "dst_owner_id": o.dest_owner_id,
            "ship_date": min((ln.ship_date for ln in lines), default=None), "lines": len(lines),
            "qty": round(sum(ln.qty for ln in lines), 6)}


def publish(ctx: AppContext, a: Any, run_id: str) -> dict[str, Any]:
    """Firm transfers (ship <= today + firm days) become M5 transfer orders (`source network`, status open), grouped by
    (source, destination, lane, ship date); open unshipped network TOs whose lines all match a planned firm transfer
    (key, ship date, qty) are kept and re-linked, the others cancelled ("Superseded by network plan NR-...");
    shipped TOs are never touched. Later transfers reach plant MRP from the published run (`mrp_inputs`)."""
    from ....mfg import transfers as TRM
    from .. import repo_m2
    from ..db_models_m5 import MfgTransferLineRow, MfgTransferOrderRow
    from .transfers import _write_lines

    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgNetRunRow, run_id, what="Network run", lock=True)
        if r.status != "completed" or not (r.validator or {}).get("ok"):
            raise ApiError(409, "NET_NOT_PUBLISHABLE", "Only a completed, validator-clean network run can be "
                           "published.", {"status": r.status, "validator_ok": (r.validator or {}).get("ok")})
        if r.as_of < today(s):
            raise ApiError(409, "NET_RUN_STALE", "This network plan was made on an earlier day; run it again.",
                           {"as_of": r.as_of.isoformat()})
        nodes = _node_ids(s)
        names = _names(r)
        firm = list(s.execute(select(MfgNetTransferRow).where(MfgNetTransferRow.run_id == r.id,
                                                              MfgNetTransferRow.firm.is_(True))
                              .order_by(MfgNetTransferRow.ship_date, MfgNetTransferRow.id)).scalars())
        later = int(s.execute(select(func.count()).select_from(MfgNetTransferRow).where(
            MfgNetTransferRow.run_id == r.id, MfgNetTransferRow.firm.is_(False))).scalar() or 0)
        reason = f"Superseded by network plan {r.number}"
        via = f"network:{r.number}"
        result: dict[str, Any] = {"created": [], "kept": [], "cancelled": [], "network_demands": later,
                                  "network_supplies": later, "warnings": []}
        open_planned = {t.id: t for t in firm}
        with system_scope():
            # review M1: lock the candidate TOs and their mirrors (ordered by id), then re-check status and
            # shipments on the locked rows - a TO shipped concurrently is never cancelled
            cand = list(s.execute(select(MfgTransferOrderRow.id).where(
                MfgTransferOrderRow.source == "network", MfgTransferOrderRow.direction == "out",
                MfgTransferOrderRow.status.in_(("draft", "open")),
                MfgTransferOrderRow.source_owner_id.in_(list(nodes)))).scalars())
            mirrors = list(s.execute(select(MfgTransferOrderRow.id).where(
                MfgTransferOrderRow.mirror_of.in_(cand))).scalars()) if cand else []
            locked = {o.id: o for o in s.execute(select(MfgTransferOrderRow).where(
                MfgTransferOrderRow.id.in_(sorted(cand + mirrors))).order_by(MfgTransferOrderRow.id)
                .with_for_update().execution_options(populate_existing=True)).scalars()} if cand else {}
            all_lines: dict[str, list[Any]] = defaultdict(list)
            if cand:
                for ln in s.execute(select(MfgTransferLineRow).where(MfgTransferLineRow.order_id.in_(sorted(cand)))
                                    .order_by(MfgTransferLineRow.id).with_for_update()
                                    .execution_options(populate_existing=True)).scalars():
                    all_lines[ln.order_id].append(ln)
            by_mirror = {o.mirror_of: o for o in locked.values() if o.mirror_of}
            existing = sorted((locked[i] for i in cand), key=lambda o: o.number)
            for o in existing:
                if o.status not in ("draft", "open"):
                    continue                                          # changed before the lock
                lines = sorted(all_lines.get(o.id, []), key=lambda ln: ln.line_no)
                if any(ln.shipped_qty > 0 for ln in lines):
                    continue                                          # shipped TOs are never touched
                keys = _key_of_items(s, o.source_owner_id, {ln.item_id for ln in lines})
                match: list[str] = []
                for ln in lines:
                    hit = next((t.id for t in open_planned.values() if t.id not in match
                                and t.src_owner_id == o.source_owner_id and t.dst_owner_id == o.dest_owner_id
                                and t.item_key == keys.get(ln.item_id) and t.ship_date == ln.ship_date
                                and abs(t.qty - ln.qty) <= 1e-6), None)
                    if hit is None:
                        break
                    match.append(hit)
                if len(match) == len(lines) and lines:
                    for tid in match:
                        open_planned.pop(tid).to_id = o.id
                    o.net_run_id = r.id
                    result["kept"].append(_to_summary(o, lines))
                    continue
                mirror = by_mirror.get(o.id)
                for x in (o, mirror):
                    if x is not None and TRM.can("cancel", x.status, 0.0):
                        x.status, x.row_version, x.updated_at = "cancelled", x.row_version + 1, utcnow()
                for owner, oid in ((o.source_owner_id, o.id), (o.dest_owner_id, mirror.id if mirror else None)):
                    if oid is not None:                               # review m1: both plants' audit chains
                        with owner_scope(owner):
                            audit(s, "transfer_order", oid, "cancel", {"number": o.number, "via": via},
                                  reason=reason)
                result["cancelled"].append(_to_summary(o, lines))
            groups: dict[tuple[str, str, str | None, date], list[MfgNetTransferRow]] = defaultdict(list)
            for t in open_planned.values():
                groups[(t.src_owner_id, t.dst_owner_id, t.lane_id, t.ship_date)].append(t)
            for (src, dst, _lane_id, ship), ts in sorted(groups.items(), key=lambda x: (x[0][3], x[0][0], x[0][1])):
                lines = []
                for t in sorted(ts, key=lambda t: t.item_key):
                    iid = (names.get(src, {}).get(t.item_key) or [None])[0]
                    if iid is None:
                        result["warnings"].append({"code": "NET_ITEM_MISSING", "node": src, "key": t.item_key})
                        continue
                    lines.append((t, _Line(iid, t.qty, t.ship_date, t.receive_date)))
                if not lines:
                    continue

                def taken(c: str, src: str = src, dst: str = dst) -> bool:
                    return s.execute(select(MfgTransferOrderRow.id).where(
                        MfgTransferOrderRow.owner_id.in_([src, dst]), MfgTransferOrderRow.number == c)).first() \
                        is not None
                with owner_scope(src):
                    number = repo_m2.next_number(s, "TO", taken)
                now = utcnow()
                so = MfgTransferOrderRow(id=new_id("tro_"), owner_id=src, number=number, direction="out",
                                         status="open", source_owner_id=src, dest_owner_id=dst, mirror_of=None,
                                         from_location_id=None, to_location_id=None, note=f"Network plan {r.number}",
                                         source="network", net_run_id=r.id, row_version=1, created_at=now,
                                         updated_at=now)
                from .transfers import _dest_location

                do = MfgTransferOrderRow(id=new_id("tro_"), owner_id=dst, number=number, direction="in",
                                         status="open", source_owner_id=src, dest_owner_id=dst, mirror_of=so.id,
                                         from_location_id=None, to_location_id=_dest_location(s, dst, None),
                                         note=f"Network plan {r.number}", source="network", net_run_id=r.id,
                                         row_version=1, created_at=now, updated_at=now)
                so.to_location_id = do.to_location_id
                s.add_all([so, do])
                s.flush()
                try:
                    _write_lines(s, so, do, _Lines([x for _t, x in lines]))
                except ApiError as exc:
                    result["warnings"].append({"code": exc.code, "node": dst, "detail": jsonable(exc.details)})
                    s.delete(do)
                    s.delete(so)
                    s.flush()
                    continue
                for t, _x in lines:
                    t.to_id = so.id
                for owner, oid in ((src, so.id), (dst, do.id)):
                    with owner_scope(owner):
                        audit(s, "transfer_order", oid, "create", {"number": number, "via": via, "source": "network"})
                result["created"].append(_to_summary(so, [x for _t, x in lines]))
        for o in s.execute(select(MfgNetRunRow).where(MfgNetRunRow.published.is_(True),
                                                      MfgNetRunRow.id != r.id)).scalars():
            o.published = False
        r.published, r.published_at, r.published_by = True, utcnow(), a.user_id
        r.publish_result = jsonable(result)
        audit(s, "net_run", r.id, "publish", {"number": r.number, "created": len(result["created"]),
                                              "kept": len(result["kept"]), "cancelled": len(result["cancelled"])})
        s.flush()
        return _run(r)


def publish_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:   # pragma: no cover - sync publish
    return {"status": "skipped"}


def mrp_inputs(s: Session) -> tuple[list[Any], list[Any]]:
    """Plant MRP (5.4): the published network run's later transfers out of / into the bound plant ->
    (`NetworkDemandSnap`s, `RateSupplySnap`s). Empty outside an organisation with a published network run."""
    from ....mfg.mrp.model import NetworkDemandSnap, RateSupplySnap
    from ..db_models import MfgPlantRow
    from ..db_models_m5 import OrgPlantRow

    owner = str(current_owner())
    with system_scope():
        org = s.execute(select(OrgPlantRow.org_id).where(OrgPlantRow.plant_owner_id == owner)).scalar()
        if org is None:
            return [], []
        codes = dict(s.execute(select(OrgPlantRow.plant_owner_id, OrgPlantRow.code).where(
            OrgPlantRow.org_id == org)).all())
        net = s.execute(select(MfgPlantRow.owner_id).where(MfgPlantRow.owner_id.in_(list(codes)),
                                                           MfgPlantRow.kind == "network")).scalar()
        if net is None:
            return [], []
        run = s.execute(select(MfgNetRunRow).where(MfgNetRunRow.owner_id == net, MfgNetRunRow.published.is_(True))
                        .order_by(MfgNetRunRow.published_at.desc())).scalars().first()
        if run is None:
            return [], []
        rows = list(s.execute(select(MfgNetTransferRow).where(
            MfgNetTransferRow.run_id == run.id, MfgNetTransferRow.firm.is_(False),
            (MfgNetTransferRow.src_owner_id == owner) | (MfgNetTransferRow.dst_owner_id == owner))
            .order_by(MfgNetTransferRow.ship_date, MfgNetTransferRow.id)).scalars())
    names = _names(run).get(owner, {})
    dem, sup = [], []
    for t in rows:
        iid = (names.get(t.item_key) or [None])[0]
        if iid is None:
            continue
        pegs = [p for p in t.pegs if p.get("kind") != "ss"][:5]
        first = pegs[0]["ref"] if pegs else None
        if t.src_owner_id == owner:
            dst = codes.get(t.dst_owner_id, "?")
            label = f"Transfer to {dst}" + (f" for {first}" if first else "")
            dem.append(NetworkDemandSnap(iid, t.ship_date, float(t.qty), t.id, label, 5,
                                         {"net_run": run.number, "dst": dst, "pegs": pegs}))
        if t.dst_owner_id == owner:
            label = f"Transfer from {codes.get(t.src_owner_id, '?')} ({run.number})"
            sup.append(RateSupplySnap(iid, t.receive_date, float(t.qty), t.id, label))
    return dem, sup


__getattr__ = m9_examples.module_getattr(__name__)
