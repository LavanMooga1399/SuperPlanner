"""M9 S&OP / IBP service (M9-DESIGN 6, 7; S1-S23) in the organisation's network workspace.

Cycle: fixed steps `draft -> demand_review -> supply_review -> pre_sop -> executive -> approved -> published`
(+ `cancelled`); leaving `supply_review` needs a completed baseline scenario (409 `SOP_NO_BASELINE`), leaving
`pre_sop` a recommended scenario (409 `SOP_NO_RECOMMENDATION`). Approval is always signed (policy
`sop_cycle.approve`, M7 two-step flow); after the first signature the cycle is frozen (409 `SOP_CYCLE_LOCKED`);
`reopen` (reason) supersedes the signatures. Publish writes per node an activated consensus forecast version and the
MPS targets, and lists the scenario's structural changes as follow-ups.
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

from ....esig import content as C
from ....mfg.sop import demand as D
from ....mfg.sop import finance as FIN
from ....mfg.sop import lp as LP
from ....mfg.sop import scenario as SC
from ....mfg.sop import validator as VAL
from ....mfg.sop.model import STEPS, ScenarioInput
from ....mfg.trade.fx import FxTable
from ....mfg.trade.landed import Tariff
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...db.ownership import owner_scope, system_scope
from ...errors import ApiError
from .. import repo
from ..db_models_m9 import (MfgFxRateRow, MfgMpsTargetRow, MfgNetLaneRow, MfgNetRampCurveRow, MfgNetSourcingRow,
                            MfgSopCycleRow, MfgSopDemandRow, MfgSopOverrideRow, MfgSopScenarioRow, MfgTariffMilestoneRow,
                            MfgTariffRateRow)
from . import m9_examples
from .common import audit, check_version, jsonable, read_tx, write_tx
from .m8common import next_number, page, start_job, today
from .network import net_settings, org_nodes, require_network

EDIT_STEPS = ("draft", "demand_review", "supply_review", "pre_sop")


# ---------------------------------------------------------------- helpers

def _months(period: date, n: int) -> list[date]:
    return [D.add_months(period, k) for k in range(n)]


def _nth_workday(month: date, n: int) -> date:
    d, k = month, 0
    while True:
        if d.weekday() < 5:
            k += 1
            if k >= n:
                return d
        d += timedelta(days=1)


def _signed(s: Session, c: MfgSopCycleRow) -> bool:
    from ..db_models_m7 import EsigSignatureRow

    return s.execute(select(EsigSignatureRow.id).where(
        EsigSignatureRow.record_type == "sop_cycle", EsigSignatureRow.record_id == c.id,
        EsigSignatureRow.status == "valid", EsigSignatureRow.record_version == c.row_version).limit(1)).first() \
        is not None


def _editable(s: Session, c: MfgSopCycleRow) -> None:
    if c.status in ("approved", "published", "cancelled") or (c.status == "executive" and _signed(s, c)):
        raise ApiError(409, "SOP_CYCLE_LOCKED", "The cycle is signed or closed; reopen it to change it.",
                       {"status": c.status})
    if c.status not in EDIT_STEPS and c.status != "executive":
        raise ApiError(409, "SOP_CYCLE_LOCKED", "The cycle cannot be changed in this step.", {"status": c.status})


def _people(s: Session, ids: set[str]) -> dict[str, str]:
    from ...auth.models import UserRow

    ids = {i for i in ids if i}
    if not ids:
        return {}
    with system_scope():
        return {u.id: (u.display_name or u.email or u.id) for u in s.execute(select(UserRow).where(
            UserRow.id.in_(ids))).scalars()}


def _cycle(s: Session, c: MfgSopCycleRow, full: bool = True) -> dict[str, Any]:
    tdy = today(s)
    steps = []
    for st in c.steps or []:
        due = date.fromisoformat(st["due"]) if st.get("due") else None
        steps.append({**st, "owner_name": None, "overdue": bool(due and not st.get("done_at") and due < tdy
                                                                and STEPS.index(c.status if c.status in STEPS
                                                                                else "draft") <= STEPS.index(st["step"]))})
    ppl = _people(s, {st.get("owner_id") for st in steps} | {st.get("done_by") for st in steps}) if full else {}
    for st in steps:
        st["owner_name"] = ppl.get(st.get("owner_id") or "")
    rec = {"id": c.id, "row_version": c.row_version, "number": c.number, "period": c.period,
           "horizon_months": c.horizon_months, "status": c.status, "steps": steps,
           "demand_sources": c.demand_sources or {}, "recommended_scenario_id": c.recommended_scenario_id,
           "recommend_note": c.recommend_note, "approved_scenario_id": c.approved_scenario_id,
           "content_hash": c.content_hash, "publish_result": c.publish_result,
           "publish_job_status": "completed" if c.publish_result else None, "reopen_reason": c.reopen_reason,
           "report_currency": net_settings(s)["report_currency"], "signatures": [], "people": ppl,
           "created_at": c.created_at, "updated_at": c.updated_at}
    if full:
        from . import esig

        rec["signatures"] = esig.manifests(s, "sop_cycle", c.id)
    return rec


def _get_cycle(s: Session, cycle_id: str, lock: bool = False) -> MfgSopCycleRow:
    return repo.get_row(s, MfgSopCycleRow, cycle_id, what="S&OP cycle", lock=lock)


# ---------------------------------------------------------------- demand review data (6.2)

def node_demand(s: Session, version_id: str | None, months: list[date]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Item rows {family, item_key, month, stat, order} of the bound node + item basis (finals, history, asp)."""
    from ..db_models import MfgItemRow
    from ..db_models_m8 import MfgDemandHistoryRow, MfgForecastLineRow
    from .forecast import open_customer_orders
    from ....mfg.network.build import key_of

    items = {r.id: r for r in s.execute(select(MfgItemRow).where(MfgItemRow.active.is_(True))).scalars()}
    mset = set(months)
    rows: list[dict[str, Any]] = []
    if version_id:
        for iid, ps, fq in s.execute(select(MfgForecastLineRow.item_id, MfgForecastLineRow.period_start,
                                            MfgForecastLineRow.final_qty).where(
                MfgForecastLineRow.version_id == version_id)):
            it = items.get(iid)
            m = ps.replace(day=1)
            if it is None or not it.family or m not in mset:
                continue
            rows.append({"family": it.family, "item_key": key_of(it), "month": m, "stat": float(fq), "order": 0.0,
                         "item_id": iid})
    for od in open_customer_orders(s):
        it = items.get(od.item_id)
        if it is None or not it.family:
            continue
        m = od.due.replace(day=1) if hasattr(od, "due") else od[1].replace(day=1)
        if m < months[0]:
            m = months[0]
        if m not in mset:
            continue
        rows.append({"family": it.family, "item_key": key_of(it), "month": m, "stat": 0.0,
                     "order": float(od.qty if hasattr(od, "qty") else od[2]), "item_id": it.id})
    hist: dict[str, float] = defaultdict(float)
    since = D.add_months(months[0], -12)
    for iid, q in s.execute(select(MfgDemandHistoryRow.item_id, MfgDemandHistoryRow.qty).where(
            MfgDemandHistoryRow.period_start >= since, MfgDemandHistoryRow.bucket == "m")):
        hist[iid] += float(q or 0)
    asp: dict[str, list[float]] = defaultdict(list)
    cost: dict[str, list[float]] = defaultdict(list)
    for it in items.values():
        if not it.family:
            continue
        lp_ = (it.attributes or {}).get("list_price") or (it.attributes or {}).get("asp")
        if isinstance(lp_, (int, float)) and lp_ > 0:
            asp[it.family].append(float(lp_))
        if it.standard_cost:
            cost[it.family].append(float(it.standard_cost))
    basis = {"keys": {iid: (key_of(it), it.family) for iid, it in items.items() if it.family},
             "history": dict(hist), "asp": {f: sum(v) / len(v) for f, v in asp.items()},
             "cost": {f: sum(v) / len(v) for f, v in cost.items()}}
    return rows, basis


def _build_demand(ctx: AppContext, s: Session, c: MfgSopCycleRow) -> None:
    from ..db_models import MfgPlantRow

    months = _months(c.period, c.horizon_months)
    nodes = org_nodes(s)
    prior: dict[tuple[str, str, date], float] = {}
    last = s.execute(select(MfgSopCycleRow).where(MfgSopCycleRow.status == "published",
                                                  MfgSopCycleRow.id != c.id).order_by(
        MfgSopCycleRow.period.desc())).scalars().first()
    if last is not None:
        for r in s.execute(select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == last.id)).scalars():
            prior[(r.node_owner_id, r.family, r.month)] = r.consensus_qty
    s.execute(delete(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id))
    sources = dict(c.demand_sources or {})
    out = []
    for n in nodes:
        with owner_scope(n["owner_id"]):
            from ..db_models_m8 import MfgForecastVersionRow

            vid = sources.get(n["owner_id"])
            if vid is None and n["owner_id"] not in sources:
                vid = s.execute(select(MfgForecastVersionRow.id).where(
                    MfgForecastVersionRow.owner_id == n["owner_id"], MfgForecastVersionRow.status == "active")
                ).scalar()
            sources[n["owner_id"]] = vid
            rows, basis = node_demand(s, vid, months)
            ccy = s.execute(select(MfgPlantRow.currency).where(MfgPlantRow.owner_id == n["owner_id"])).scalar() \
                or n["currency"]
        agg = D.aggregate({**r, "node": n["owner_id"]} for r in rows)
        for (node, fam, m), row in sorted(agg.items()):
            if basis["asp"].get(fam) is not None:
                asp, src = basis["asp"][fam], "history"
            elif basis["cost"].get(fam) is not None:
                asp, src = basis["cost"][fam], "cost"
            else:
                asp, src = None, "manual"
            out.append({"id": new_id("sdm_"), "owner_id": c.owner_id, "cycle_id": c.id, "node_owner_id": node,
                        "family": fam, "month": m, "stat_qty": round(row["stat_qty"], 6),
                        "order_qty": round(row["order_qty"], 6), "base_qty": round(row["base_qty"], 6),
                        "prior_consensus": prior.get((node, fam, m)), "consensus_qty": round(row["base_qty"], 6),
                        "asp": asp, "asp_currency": ccy, "asp_source": src,
                        "items": {k: {**v, "item_id": next((i for i, (kk, _f) in basis["keys"].items() if kk == k),
                                                            None), "hist": 0.0} for k, v in row["items"].items()}})
    if out:
        s.execute(MfgSopDemandRow.__table__.insert(), out)
    c.demand_sources = sources


def _reapply(s: Session, c: MfgSopCycleRow) -> None:
    rows = list(s.execute(select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id)).scalars())
    base = {(r.node_owner_id, r.family, r.month): r.base_qty for r in rows}
    ovr = list(s.execute(select(MfgSopOverrideRow).where(MfgSopOverrideRow.cycle_id == c.id,
                                                         MfgSopOverrideRow.removed_at.is_(None))).scalars())
    cons = D.apply_overrides(base, ovr)
    by = {(r.node_owner_id, r.family, r.month): r for r in rows}
    for k, v in cons.items():
        r = by.get(k)
        if r is None:
            r = MfgSopDemandRow(id=new_id("sdm_"), cycle_id=c.id, node_owner_id=k[0], family=k[1], month=k[2],
                                stat_qty=0.0, order_qty=0.0, base_qty=0.0, prior_consensus=None, consensus_qty=v,
                                asp=None, asp_currency="USD", asp_source="manual", items={})
            s.add(r)
            by[k] = r
        r.consensus_qty = v


# ---------------------------------------------------------------- cycles (S1-S6)

def list_cycles(ctx: AppContext, status: str | None, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        require_network(s)
        q = select(MfgSopCycleRow)
        if status:
            q = q.where(MfgSopCycleRow.status.in_(status.split(",")))
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = s.execute(q.order_by(MfgSopCycleRow.period.desc(), MfgSopCycleRow.number.desc()).limit(limit)
                         .offset(offset)).scalars()
        return page([_cycle(s, c, full=False) for c in rows], n, limit, offset)


def create_cycle(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        require_network(s)
        nodes = {n["owner_id"] for n in org_nodes(s)}
        for n in (body.forecast_versions or {}):
            if n not in nodes:
                raise ApiError(422, "NET_UNKNOWN_NODE", "This node is not a plant or DC of the organisation.",
                               {"id": n})
        if s.execute(select(MfgSopCycleRow.id).where(MfgSopCycleRow.period == body.period,
                                                     MfgSopCycleRow.status != "cancelled")).first():
            raise ApiError(409, "SOP_CYCLE_EXISTS", "A cycle for this period exists.",
                           {"period": body.period.isoformat()})
        number = f"SOP-{body.period.year}-{body.period.month:02d}"
        k = 1
        while s.execute(select(MfgSopCycleRow.id).where(MfgSopCycleRow.number == number)).first():
            k += 1
            number = f"SOP-{body.period.year}-{body.period.month:02d}-{k}"
        cal = net_settings(s)["sop_calendar"]
        steps = [{"step": st, "due": _nth_workday(body.period, int(cal[st])).isoformat() if st in cal else None,
                  "owner_id": a.user_id if st != "executive" else None, "done_at": None, "done_by": None,
                  "note": None} for st in STEPS]
        now = utcnow()
        c = MfgSopCycleRow(id=new_id("scy_"), number=number, period=body.period, horizon_months=body.horizon_months,
                           status="draft", steps=steps, demand_sources=dict(body.forecast_versions or {}),
                           recommended_scenario_id=None, recommend_note=None, approved_scenario_id=None,
                           content_hash=None, publish_result=None, reopen_reason=None, row_version=1,
                           created_at=now, updated_at=now)
        s.add(c)
        s.flush()
        _build_demand(ctx, s, c)
        s.flush()
        audit(s, "sop_cycle", c.id, "create", {"number": number, "period": body.period.isoformat()})
        return _cycle(s, c)


def get_cycle(ctx: AppContext, cycle_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _cycle(s, _get_cycle(s, cycle_id))


def _touch(c: MfgSopCycleRow) -> None:
    c.row_version += 1
    c.updated_at = utcnow()


def advance(ctx: AppContext, a: Any, cycle_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        check_version(c, if_match) if if_match else None
        if c.status not in ("draft", "demand_review", "supply_review", "pre_sop"):
            raise ApiError(409, "MFG_INVALID_STATE", "This step is left by approving or publishing.",
                           {"status": c.status})
        if c.status == "supply_review" and not s.execute(select(MfgSopScenarioRow.id).where(
                MfgSopScenarioRow.cycle_id == c.id, MfgSopScenarioRow.baseline.is_(True),
                MfgSopScenarioRow.status == "completed")).first():
            raise ApiError(409, "SOP_NO_BASELINE", "Run the baseline scenario before leaving the supply review.", {})
        if c.status == "pre_sop" and not c.recommended_scenario_id:
            raise ApiError(409, "SOP_NO_RECOMMENDATION", "Recommend a scenario before the executive meeting.", {})
        nxt = STEPS[STEPS.index(c.status) + 1]
        steps = [dict(x) for x in c.steps]
        for st in steps:
            if st["step"] == c.status:
                st.update(done_at=utcnow().isoformat(), done_by=a.user_id, note=body.note or None)
        c.steps, c.status = steps, nxt
        _touch(c)
        audit(s, "sop_cycle", c.id, "advance", {"to": nxt, "note": body.note})
        return _cycle(s, c)


def reopen(ctx: AppContext, a: Any, cycle_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    from . import esig

    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        check_version(c, if_match) if if_match else None
        if c.status not in ("executive", "approved"):
            raise ApiError(409, "MFG_INVALID_STATE", "Only a cycle at the executive step or approved can be reopened.",
                           {"status": c.status})
        n = 0
        for v in range(1, c.row_version + 1):
            n += esig.supersede_pending(s, "sop_cycle", c.id, v)
        steps = [dict(x) for x in c.steps]
        after = False
        for st in steps:
            if st["step"] == body.to_step:
                after = True
            if after:
                st.update(done_at=None, done_by=None)
        c.steps, c.status, c.reopen_reason = steps, body.to_step, body.reason
        c.approved_scenario_id, c.content_hash = None, None
        _touch(c)
        audit(s, "sop_cycle", c.id, "reopen", {"to": body.to_step, "superseded": n}, reason=body.reason)
        return _cycle(s, c)


def cancel(ctx: AppContext, a: Any, cycle_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        check_version(c, if_match) if if_match else None
        if c.status in ("published", "cancelled"):
            raise ApiError(409, "MFG_INVALID_STATE", "A published or cancelled cycle cannot be cancelled.",
                           {"status": c.status})
        c.status = "cancelled"
        _touch(c)
        audit(s, "sop_cycle", c.id, "cancel", {}, reason=body.reason)
        return _cycle(s, c)


# ---------------------------------------------------------------- demand review (S7-S10)

def _override(o: MfgSopOverrideRow) -> dict[str, Any]:
    return {"id": o.id, "node_owner_id": o.node_owner_id, "family": o.family, "month_from": o.month_from,
            "month_to": o.month_to, "mode": o.mode, "value": o.value, "reason": o.reason, "seq": o.seq,
            "created_by": o.created_by, "created_at": o.created_at, "removed_at": o.removed_at}


def _drow(r: MfgSopDemandRow) -> dict[str, Any]:
    return {"id": r.id, "node_owner_id": r.node_owner_id, "family": r.family, "month": r.month,
            "stat_qty": r.stat_qty, "order_qty": r.order_qty, "base_qty": r.base_qty,
            "prior_consensus": r.prior_consensus, "consensus_qty": r.consensus_qty, "asp": r.asp,
            "asp_currency": r.asp_currency, "asp_source": r.asp_source}


def demand(ctx: AppContext, cycle_id: str, node: str | None, family: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        c = _get_cycle(s, cycle_id)
        q = select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id)
        if node:
            q = q.where(MfgSopDemandRow.node_owner_id == node)
        if family:
            q = q.where(MfgSopDemandRow.family == family)
        rows = list(s.execute(q.order_by(MfgSopDemandRow.node_owner_id, MfgSopDemandRow.family,
                                         MfgSopDemandRow.month)).scalars())
        ovr = s.execute(select(MfgSopOverrideRow).where(MfgSopOverrideRow.cycle_id == c.id).order_by(
            MfgSopOverrideRow.seq)).scalars()
        return {"months": _months(c.period, c.horizon_months), "families": sorted({r.family for r in rows}),
                "items": [_drow(r) for r in rows], "overrides": [_override(o) for o in ovr]}


def list_overrides(ctx: AppContext, cycle_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        c = _get_cycle(s, cycle_id)
        return {"items": [_override(o) for o in s.execute(select(MfgSopOverrideRow).where(
            MfgSopOverrideRow.cycle_id == c.id).order_by(MfgSopOverrideRow.seq)).scalars()]}


def create_override(ctx: AppContext, a: Any, cycle_id: str, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        _editable(s, c)
        seq = int(s.execute(select(func.max(MfgSopOverrideRow.seq)).where(MfgSopOverrideRow.cycle_id == c.id))
                  .scalar() or 0) + 1
        o = MfgSopOverrideRow(id=new_id("sdo_"), cycle_id=c.id, node_owner_id=body.node_owner_id, family=body.family,
                              month_from=body.month_from, month_to=body.month_to, mode=body.mode, value=body.value,
                              reason=body.reason, seq=seq, created_by=a.user_id, created_at=utcnow(), removed_at=None)
        s.add(o)
        s.flush()
        _reapply(s, c)
        _touch(c)
        audit(s, "sop_override", o.id, "create", jsonable(_override(o)), reason=body.reason)
        return _override(o)


def remove_override(ctx: AppContext, a: Any, override_id: str) -> dict[str, Any]:
    from ...audit_diff import current_reason

    with write_tx(ctx) as (s, _):
        o = repo.get_row(s, MfgSopOverrideRow, override_id, what="Demand override", lock=True)
        reason = current_reason()
        if not reason:
            raise ApiError(422, "REASON_REQUIRED", "Removing an override needs a reason (X-SP-Change-Reason).", {})
        c = _get_cycle(s, o.cycle_id, lock=True)
        _editable(s, c)
        if o.removed_at is None:
            o.removed_at = utcnow()
            _reapply(s, c)
            _touch(c)
        audit(s, "sop_override", o.id, "remove", {"family": o.family}, reason=reason)
        return _override(o)


def put_asp(ctx: AppContext, a: Any, cycle_id: str, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        _editable(s, c)
        n = 0
        for row in body.rows:
            for r in s.execute(select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id,
                                                             MfgSopDemandRow.node_owner_id == row.node_owner_id,
                                                             MfgSopDemandRow.family == row.family)).scalars():
                r.asp, r.asp_currency, r.asp_source = row.asp, row.currency, "manual"
                n += 1
        _touch(c)
        audit(s, "sop_cycle", c.id, "asp", {"rows": n}, reason=body.reason or None)
    return demand(ctx, cycle_id, None, None)


def recommend(ctx: AppContext, a: Any, cycle_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        check_version(c, if_match) if if_match else None
        _editable(s, c)
        sc = repo.get_row(s, MfgSopScenarioRow, body.scenario_id, what="Scenario")
        if sc.cycle_id != c.id or sc.status != "completed" or not (sc.validator or {}).get("ok"):
            raise ApiError(409, "SOP_SCENARIO_INVALID", "Recommend a completed, validator-clean scenario of this "
                           "cycle.", {"status": sc.status})
        c.recommended_scenario_id, c.recommend_note = sc.id, body.note
        _touch(c)
        audit(s, "sop_cycle", c.id, "recommend", {"scenario": sc.number})
        return _cycle(s, c)


# ---------------------------------------------------------------- approval (6.6, S22)

def content(s: Session, c: MfgSopCycleRow) -> dict[str, Any]:
    rows = [_drow(r) for r in s.execute(select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id)).scalars()]
    sc = s.get(MfgSopScenarioRow, c.approved_scenario_id or c.recommended_scenario_id) \
        if (c.approved_scenario_id or c.recommended_scenario_id) else None
    res_hash = hashlib.sha256(json.dumps(sc.result or {}, sort_keys=True, default=str).encode()).hexdigest() \
        if sc else None
    k = (sc.kpis or {}).get("horizon") if sc else None
    return {"cycle": c.number, "period": c.period.isoformat(), "consensus_hash": D.content_hash_table(rows),
            "scenario": sc.number if sc else None, "result_hash": res_hash,
            "kpis": {x: k.get(x) for x in ("consensus_units", "delivered_units", "unmet_units", "revenue",
                                           "gross_margin", "capex")} if k else None,
            "validator_ok": bool((sc.validator or {}).get("ok")) if sc else None}


def _loader(s: Session, record_id: str, lock: bool) -> C.Loaded:
    c = _get_cycle(s, record_id, lock=lock)
    ct = content(s, c)
    k = ct["kpis"] or {}
    return C.Loaded(c, ct, c.row_version, None, [("Cycle", c.number), ("Scenario", ct["scenario"] or "-"),
                                                ("Service", f"{k.get('delivered_units') or 0:,.0f} / "
                                                            f"{k.get('consensus_units') or 0:,.0f}")])


C.register("sop_cycle", _loader)


def approve(ctx: AppContext, a: Any, cycle_id: str, body: Any) -> dict[str, Any]:
    from . import esig

    with read_tx(ctx) as s:
        c = _get_cycle(s, cycle_id)
        if c.status != "executive":
            raise ApiError(409, "MFG_INVALID_STATE", "The cycle is approved at the executive step.",
                           {"status": c.status})
    auth = esig.authenticate(ctx, a, "sop_cycle", "approve", body.signature)
    with write_tx(ctx, lock=False) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        if c.status != "executive":
            raise ApiError(409, "MFG_INVALID_STATE", "The cycle is approved at the executive step.",
                           {"status": c.status})
        sc = s.get(MfgSopScenarioRow, body.scenario_id)
        if sc is None or sc.cycle_id != c.id:
            raise ApiError(404, "NOT_FOUND", "Scenario not found.", {"id": body.scenario_id})
        if sc.status != "completed" or not (sc.validator or {}).get("ok") or sc.id != c.recommended_scenario_id:
            raise ApiError(409, "SOP_SCENARIO_INVALID", "Only the recommended, validator-clean scenario can be "
                           "approved.", {"recommended": c.recommended_scenario_id})
        out = esig.sign(s, a, auth, "sop_cycle", c.id, "approve", body.signature)
        if out.pending is not None:
            return out.pending
        c.approved_scenario_id = sc.id
        c.content_hash = C.content_hash(content(s, c))
        steps = [dict(x) for x in c.steps]
        for st in steps:
            if st["step"] == "executive":
                st.update(done_at=utcnow().isoformat(), done_by=a.user_id)
        c.steps, c.status = steps, "approved"
        audit(s, "sop_cycle", c.id, "approve", {"scenario": sc.number, "signatures": out.signature_ids})
        _touch_after_sign(c)
        s.flush()
        return _cycle(s, c)


def _touch_after_sign(c: MfgSopCycleRow) -> None:
    c.updated_at = utcnow()          # row_version kept: the signatures stay attached to the signed version


# ---------------------------------------------------------------- scenarios (S11-S21)

def _scenario(r: MfgSopScenarioRow) -> dict[str, Any]:
    return {"id": r.id, "row_version": r.row_version, "number": r.number, "cycle_id": r.cycle_id,
            "baseline": r.baseline, "name": r.name, "changes": r.changes or [], "capex_note": r.capex_note,
            "enforce_milestones": r.enforce_milestones, "status": r.status, "input_hash": r.input_hash,
            "kpis": r.kpis, "validator": r.validator, "warnings": r.warnings or [], "error": r.error,
            "run_at": r.run_at, "updated_at": r.updated_at}


def list_scenarios(ctx: AppContext, cycle_id: str | None, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        require_network(s)
        q = select(MfgSopScenarioRow)
        if cycle_id:
            q = q.where(MfgSopScenarioRow.cycle_id == cycle_id)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = s.execute(q.order_by(MfgSopScenarioRow.number).limit(limit).offset(offset)).scalars()
        return page([_scenario(r) for r in rows], n, limit, offset)


def _changes(body: ScenarioInput) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json", by_alias=True) for c in body.changes]


def create_scenario(ctx: AppContext, a: Any, body: ScenarioInput) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        require_network(s)
        baseline = False
        if body.cycle_id:
            c = _get_cycle(s, body.cycle_id, lock=True)
            _editable(s, c)
            baseline = not s.execute(select(MfgSopScenarioRow.id).where(
                MfgSopScenarioRow.cycle_id == c.id)).first() and not body.changes
        now = utcnow()
        r = MfgSopScenarioRow(id=new_id("ssc_"), number=next_number(s, "SC", MfgSopScenarioRow),
                              cycle_id=body.cycle_id, name=body.name, baseline=baseline, changes=_changes(body),
                              capex_note=body.capex_note, enforce_milestones=body.enforce_milestones, status="draft",
                              input_hash=None, result=None, kpis=None, validator=None, warnings=None, error=None,
                              run_at=None, row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "sop_scenario", r.id, "create", {"number": r.number, "changes": len(r.changes)})
        return _scenario(r)


def get_scenario(ctx: AppContext, scenario_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _scenario(repo.get_row(s, MfgSopScenarioRow, scenario_id, what="Scenario"))


def _scenario_editable(s: Session, r: MfgSopScenarioRow) -> None:
    if r.status == "running":
        raise ApiError(409, "MFG_INVALID_STATE", "The scenario is running.", {"status": r.status})
    if r.cycle_id:
        c = _get_cycle(s, r.cycle_id)
        _editable(s, c)
        if r.id in (c.recommended_scenario_id, c.approved_scenario_id) and c.status not in EDIT_STEPS:
            raise ApiError(409, "SOP_CYCLE_LOCKED", "The recommended scenario of a cycle at the executive step "
                           "cannot change.", {})


def update_scenario(ctx: AppContext, a: Any, scenario_id: str, body: ScenarioInput, if_match: str | None
                    ) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgSopScenarioRow, scenario_id, what="Scenario", lock=True)
        check_version(r, if_match) if if_match else None
        _scenario_editable(s, r)
        r.name, r.changes, r.capex_note, r.enforce_milestones = body.name, _changes(body), body.capex_note, \
            body.enforce_milestones
        if r.changes:
            r.baseline = False
        r.status, r.result, r.kpis, r.validator, r.error, r.input_hash = "draft", None, None, None, None, None
        r.row_version += 1
        r.updated_at = utcnow()
        audit(s, "sop_scenario", r.id, "update", {"changes": len(r.changes)})
        return _scenario(r)


def delete_scenario(ctx: AppContext, a: Any, scenario_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        r = repo.get_row(s, MfgSopScenarioRow, scenario_id, what="Scenario", lock=True)
        check_version(r, if_match) if if_match else None
        _scenario_editable(s, r)
        if r.cycle_id:
            c = _get_cycle(s, r.cycle_id)
            if r.id in (c.recommended_scenario_id, c.approved_scenario_id):
                raise ApiError(409, "MFG_IN_USE", "The cycle recommends this scenario.", {})
        audit(s, "sop_scenario", r.id, "delete", {"number": r.number})
        s.delete(r)


def copy_scenario(ctx: AppContext, a: Any, scenario_id: str, body: Any) -> dict[str, Any]:
    with read_tx(ctx) as s:
        src = repo.get_row(s, MfgSopScenarioRow, scenario_id, what="Scenario")
        data = {"cycle_id": body.cycle_id, "name": body.name or f"{src.name} (copy)", "changes": src.changes or [],
                "capex_note": src.capex_note, "enforce_milestones": src.enforce_milestones}
    return create_scenario(ctx, a, ScenarioInput.model_validate(data))


def run_scenario(ctx: AppContext, a: Any, scenario_id: str) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        r = repo.get_row(s, MfgSopScenarioRow, scenario_id, what="Scenario", lock=True)
        if r.status == "running":
            raise ApiError(409, "MFG_INVALID_STATE", "The scenario is running.", {})
        if r.cycle_id:
            c = _get_cycle(s, r.cycle_id)
            if c.status not in EDIT_STEPS:
                raise ApiError(409, "SOP_CYCLE_LOCKED", "The cycle is at the executive step or closed.",
                               {"status": c.status})
        r.status, r.error = "running", None
        r.row_version += 1
        _rid, job = start_job(s, ctx, "sop_scenario_run", r.owner_id, {"scenario_id": r.id})
        audit(s, "sop_scenario", r.id, "run", {"number": r.number})
        rec = _scenario(r)
    ctx.jobs.dispatch(job)
    return rec


def _tables(s: Session) -> tuple[FxTable, list[Tariff], dict[str, list[Any]], list[dict[str, Any]]]:
    fx = FxTable([(r.from_ccy, r.to_ccy, r.month, r.rate) for r in s.execute(select(MfgFxRateRow)).scalars()])
    tariffs = [Tariff(r.dest_country, r.hts_prefix, r.coo, r.layer, r.rate_pct, r.per_unit, r.per_unit_currency,
                      r.valid_from, r.valid_to) for r in s.execute(select(MfgTariffRateRow)).scalars()]
    curves_ = {r.code: r.points for r in s.execute(select(MfgNetRampCurveRow)).scalars()}
    ms = [{"id": r.id, "code": r.code, "family": r.family, "hts_prefix": r.hts_prefix, "rule": r.rule,
           "min_pct": float((r.rule or {}).get("min_pct", 0)), "effective": r.effective, "dest": r.dest_country}
          for r in s.execute(select(MfgTariffMilestoneRow).order_by(MfgTariffMilestoneRow.code)).scalars()]
    return fx, tariffs, curves_, ms


def problem_for(ctx: AppContext, r: MfgSopScenarioRow) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """(SopProblem, meta, context) of a scenario; per-node reads in each node's owner scope."""
    from ..repo_m2 import snapshot_tx

    with read_tx(ctx) as s:
        st = net_settings(s)
        nodes = org_nodes(s)
        if r.cycle_id:
            c = s.get(MfgSopCycleRow, r.cycle_id)
            period, horizon = c.period, c.horizon_months
            drows = list(s.execute(select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id)).scalars())
            dem = {(x.node_owner_id, x.family, x.month): x.consensus_qty for x in drows}
            orders = {(x.node_owner_id, x.family, x.month): x.order_qty for x in drows}
            asp_rows = {(x.node_owner_id, x.family): (x.asp, x.asp_currency) for x in drows}
        else:
            period, horizon = today(s).replace(day=1), 18
            dem, orders, asp_rows = {}, {}, {}
        lanes = [{"id": x.id, "src": x.from_owner_id, "dst": x.to_owner_id, "transit_days": x.transit_days,
                  "freight_per_unit": x.freight_per_unit, "currency": x.currency, "active": x.active}
                 for x in s.execute(select(MfgNetLaneRow)).scalars()]
        rules = [{"id": x.id, "dest": x.dest_owner_id, "key": x.item_key, "family": x.family,
                  "source_kind": x.source_kind, "source": x.source_owner_id, "supplier_code": x.supplier_code,
                  "priority": x.priority} for x in s.execute(select(MfgNetSourcingRow).where(
                      MfgNetSourcingRow.active.is_(True))).scalars()]
        fx, tariffs, curves_, ms = _tables(s)
    months = _months(period, horizon)
    data = {}
    for n in nodes:
        with owner_scope(n["owner_id"]), snapshot_tx(ctx.db) as s:
            data[n["owner_id"]] = SC.node_data(s, n, months)
            if not r.cycle_id:
                from ..db_models_m8 import MfgForecastVersionRow

                vid = s.execute(select(MfgForecastVersionRow.id).where(
                    MfgForecastVersionRow.status == "active")).scalar()
                rows, _b = node_demand(s, vid, months)
                for k, row in D.aggregate({**x, "node": n["owner_id"]} for x in rows).items():
                    dem[k] = row["base_qty"]
                    orders[k] = row["order_qty"]
    md = None
    try:
        from ....mfg.trade import content as TC

        md = TC.make_domestic_shares(data, st, ms)
    except (ImportError, AttributeError):
        md = None
    p, meta = SC.build_problem(months=months, nodes=data, demand=dem, orders=orders, lanes=lanes, rules=rules,
                               settings=st, fx=fx, tariffs=tariffs, curves_by_code=curves_, milestones=ms,
                               changes=list(r.changes or []), enforce=r.enforce_milestones, make_domestic=md)
    rc = st["report_currency"]
    asp: dict[tuple[str, str], float | None] = {}
    for (n, f), (val, ccy) in asp_rows.items():
        x, _fl = fx.convert(val, ccy, rc, months[0])
        asp[(n, f)] = x
    primary = {}
    for ru in sorted(rules, key=lambda x: x["priority"]):
        if ru["source_kind"] == "plant" and ru["family"]:
            primary.setdefault((ru["dest"], ru["family"]), ru["source"])
    return p, meta, {"asp": asp, "primary": primary, "milestones": ms}


def _ser(d: dict[tuple, float]) -> list[list[Any]]:
    return [[*(x.isoformat() if isinstance(x, date) else x for x in k), v] for k, v in sorted(d.items(),
                                                                                              key=lambda kv: str(kv[0]))]


def _deser(rows: list[list[Any]]) -> dict[tuple, float]:
    out = {}
    for row in rows or []:
        *k, v = row
        k[-1] = date.fromisoformat(k[-1])
        out[tuple(k)] = v
    return out


def compute(ctx: AppContext, scenario_id: str) -> dict[str, Any]:
    t0 = time.monotonic()
    with read_tx(ctx) as s:
        row = s.get(MfgSopScenarioRow, scenario_id)
        if row is None:
            return {"error": "scenario gone"}
        from types import SimpleNamespace

        r = SimpleNamespace(cycle_id=row.cycle_id, changes=list(row.changes or []),
                            enforce_milestones=row.enforce_milestones)
    try:
        p, meta, extra = problem_for(ctx, r)
        t1 = time.monotonic()
        res = LP.solve(p)
        t2 = time.monotonic()
        if res.status != "optimal":
            raise _LpFail(res.status)
        rep = VAL.validate(p, res)
        t3 = time.monotonic()
        capex = [(date.fromisoformat(m), x) for m, x in meta["capex"]]
        rows = FIN.cells(p, res, extra["asp"], capex)
        kpis = FIN.kpis(p, res, rows, meta["currency"], [m for m in extra["milestones"] if m.get("family")])
        result = {"problem": {"months": [m.isoformat() for m in p.months], "nodes": p.nodes, "families": p.families,
                              "demand": _ser(p.demand), "hours": _ser(p.hours),
                              "hpu": [[n, g, f, h] for (n, g, f), h in sorted(p.hpu.items())],
                              "std_cost": [[n, f, v] for (n, f), v in sorted(p.std_cost.items())],
                              "conv_cost": [[n, f, v] for (n, f), v in sorted(p.conv_cost.items())],
                              "ss_target": [[n, f, v] for (n, f), v in sorted(p.ss_target.items())],
                              "buys": [[b.node, b.family, b.code, b.landed] for b in p.buys],
                              "lanes": [[ln.id, ln.src, ln.dst, ln.transit_months, ln.freight_per_unit]
                                        for ln in p.lanes],
                              "make_allowed": sorted([n, f] for n, f in p.make_allowed),
                              "asp": [[n, f, v] for (n, f), v in sorted(extra["asp"].items())],
                              "primary": [[n, f, v] for (n, f), v in sorted(extra["primary"].items())]},
                  "make": _ser(res.make), "buy": _ser(res.buy), "ship": _ser(res.ship), "inv": _ser(res.inv),
                  "unmet": _ser(res.unmet), "ss_short": _ser(res.ss_short), "objective": res.objective,
                  "meta": meta, "timings": {"build_s": round(t1 - t0, 3), "lp_s": round(t2 - t1, 3),
                                            "validator_s": round(t3 - t2, 3)}}
        hsh = hashlib.sha256(json.dumps(result["problem"], sort_keys=True, default=str).encode()).hexdigest()
        status, err = "completed", None
        warnings = meta["warnings"] + res.explanations
    except _LpFail as exc:
        status, err, result, kpis, rep, hsh, warnings = "failed", f"SOP_LP_{exc.args[0].upper()}", None, None, None, \
            None, []
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgSopScenarioRow, scenario_id, with_for_update=True)
        r.status, r.error, r.result, r.kpis, r.validator = status, err, jsonable(result), jsonable(kpis), rep
        r.input_hash, r.warnings, r.run_at, r.updated_at = hsh, jsonable(warnings)[:200], utcnow(), utcnow()
        r.row_version += 1
    return {"status": status, "error": err, "duration_s": round(time.monotonic() - t0, 3)}


class _LpFail(Exception):
    pass


def scenario_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    try:
        return compute(ctx, info["params"]["scenario_id"])
    except Exception as exc:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgSopScenarioRow, info["params"]["scenario_id"], with_for_update=True)
            if r is not None:
                r.status, r.error = "failed", f"{exc.__class__.__name__}: {exc}"[:2000]
        raise


def _completed(s: Session, scenario_id: str) -> MfgSopScenarioRow:
    r = repo.get_row(s, MfgSopScenarioRow, scenario_id, what="Scenario")
    if r.status != "completed" or not r.result:
        raise ApiError(409, "SOP_SCENARIO_NOT_RUN", "Run the scenario first.", {"status": r.status})
    from types import SimpleNamespace

    return SimpleNamespace(result=r.result, warnings=list(r.warnings or []), changes=list(r.changes or []))


class _P:
    """A light SopProblem view rebuilt from a stored result (views do not re-read plants)."""

    def __init__(self, pr: dict[str, Any]):
        from ....mfg.sop.model import SopBuy, SopLane

        self.months = [date.fromisoformat(m) for m in pr["months"]]
        self.nodes, self.families = pr["nodes"], pr["families"]
        self.demand = _deser(pr["demand"])
        self.hours = _deser(pr["hours"])
        self.hpu = {(n, g, f): h for n, g, f, h in pr["hpu"]}
        self.std_cost = {(n, f): v for n, f, v in pr["std_cost"]}
        self.conv_cost = {(n, f): v for n, f, v in pr["conv_cost"]}
        self.ss_target = {(n, f): v for n, f, v in pr["ss_target"]}
        self.buys = [SopBuy(n, f, c, x) for n, f, c, x in pr["buys"]]
        self.lanes = [SopLane(i, a, b, tm, fr) for i, a, b, tm, fr in pr["lanes"]]
        self.make_allowed = frozenset((n, f) for n, f in pr["make_allowed"])
        self.asp = {(n, f): v for n, f, v in pr["asp"]}
        self.primary = {(n, f): v for n, f, v in pr["primary"]}
        self.make_domestic: dict[Any, float] = {}


class _R:
    def __init__(self, res: dict[str, Any]):
        self.make, self.buy, self.ship = _deser(res["make"]), _deser(res["buy"]), _deser(res["ship"])
        self.inv, self.unmet, self.ss_short = _deser(res["inv"]), _deser(res["unmet"]), _deser(res["ss_short"])


def plan(ctx: AppContext, scenario_id: str, node: str | None, family: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, scenario_id)
    p, res = _P(r.result["problem"]), _R(r.result)
    lanes = {ln.id: ln for ln in p.lanes}
    idx = {t: i for i, t in enumerate(p.months)}
    sin: dict[tuple[str, str, date], float] = defaultdict(float)
    sout: dict[tuple[str, str, date], float] = defaultdict(float)
    for (lid, f, t), q in res.ship.items():
        ln = lanes[lid]
        sout[(ln.src, f, t)] += q
        j = idx[t] + ln.transit_months
        if j < len(p.months):
            sin[(ln.dst, f, p.months[j])] += q
    items = []
    for n in p.nodes:
        if node and n != node:
            continue
        for f in p.families:
            if family and f != family:
                continue
            for t in p.months:
                d = p.demand.get((n, f, t), 0.0)
                buy = {c: q for (nn, ff, c, tt), q in res.buy.items() if (nn, ff, tt) == (n, f, t)}
                row = {"node_owner_id": n, "family": f, "month": t, "consensus": d,
                       "make": res.make.get((n, f, t), 0.0), "buy": buy, "ship_in": sin[(n, f, t)],
                       "ship_out": sout[(n, f, t)], "inv": res.inv.get((n, f, t), 0.0),
                       "delivered": round(d - res.unmet.get((n, f, t), 0.0), 6),
                       "unmet": res.unmet.get((n, f, t), 0.0), "ss_short": res.ss_short.get((n, f, t), 0.0),
                       "ss_target": p.ss_target.get((n, f), 0.0)}
                if any(row[k] for k in ("consensus", "make", "ship_in", "ship_out", "inv")) or buy:
                    items.append(row)
    return {"months": p.months, "items": items}


def rough_cut(ctx: AppContext, scenario_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, scenario_id)
    p, res = _P(r.result["problem"]), _R(r.result)
    return {"months": p.months, "items": SC.rough_cut(p, res.make, p.primary, r.result["meta"].get("ramp", {}))}


def financial(ctx: AppContext, scenario_id: str, group_by: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, scenario_id)
    p, res = _P(r.result["problem"]), _R(r.result)
    capex = [(date.fromisoformat(m), x) for m, x in r.result["meta"]["capex"]]
    rows = FIN.cells(p, res, p.asp, capex)
    v = FIN.view(p, rows, group_by)
    warn = [w for w in r.warnings or [] if w.get("code") in ("FX_MISSING", "ASP_FROM_COST")]
    return {"currency": r.result["meta"]["currency"], "group_by": group_by, "months": p.months, "rows": v["rows"],
            "totals": v["totals"], "warnings": warn}


def make_buy(ctx: AppContext, scenario_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        r = _completed(s, scenario_id)
    p, res = _P(r.result["problem"]), _R(r.result)
    duty = r.result["meta"].get("duty", {})
    out = []
    keys = sorted({(n, f) for (n, f) in p.make_allowed} | {(b.node, b.family) for b in p.buys})
    for n, f in keys:
        made = sum(q for (nn, ff, _t), q in res.make.items() if (nn, ff) == (n, f))
        bought = sum(q for (nn, ff, _c, _t), q in res.buy.items() if (nn, ff) == (n, f))
        tot = made + bought
        hours = sum(h for (nn, _g, ff), h in p.hpu.items() if (nn, ff) == (n, f))
        out.append({"node_owner_id": n, "family": f, "currency": r.result["meta"]["currency"],
                    "make_unit_cost": p.conv_cost.get((n, f)) if (n, f) in p.make_allowed else None,
                    "buy": [{"supplier_code": b.code, "coo": duty.get(f"{n}|{f}|{b.code}", {}).get("coo"),
                             "landed_unit_cost": b.landed,
                             "duty_share": duty.get(f"{n}|{f}|{b.code}", {}).get("duty_share")}
                            for b in p.buys if (b.node, b.family) == (n, f)],
                    "split_make": round(made / tot, 4) if tot else 0.0,
                    "split_buy": round(bought / tot, 4) if tot else 0.0, "hours_freed": round(bought * hours, 2)})
    return {"items": out}


def compare(ctx: AppContext, ids: str) -> dict[str, Any]:
    lst = [x for x in ids.split(",") if x][:5]
    if not lst:
        raise ApiError(422, "VALIDATION_ERROR", "Give 1 to 5 scenario ids.", {})
    with read_tx(ctx) as s:
        rows = [repo.get_row(s, MfgSopScenarioRow, i, what="Scenario") for i in lst]
        cur = net_settings(s)["report_currency"]
        base = rows[0].kpis
        items = []
        for i, r in enumerate(rows):
            items.append({"scenario": {"id": r.id, "number": r.number, "name": r.name, "status": r.status,
                                       "baseline": r.baseline,
                                       "validator_ok": (r.validator or {}).get("ok") if r.validator else None},
                          "kpis": r.kpis, "delta": None if i == 0 else FIN.delta(base, r.kpis)})
    return {"currency": cur, "items": items}


# ---------------------------------------------------------------- publish (6.6, S23)

def publish(ctx: AppContext, a: Any, cycle_id: str) -> dict[str, Any]:
    """Per node: a consensus forecast version (copy of the pinned version scaled to consensus per family-month,
    activated), MPS targets (months >= period) from the approved scenario's make plan; follow-ups for structural
    changes. Idempotent: a published cycle answers its record."""
    from ..db_models_m8 import MfgDemandHistoryRow, MfgForecastLineRow, MfgForecastVersionRow

    with write_tx(ctx) as (s, _):
        c = _get_cycle(s, cycle_id, lock=True)
        if c.status == "published":
            return _cycle(s, c)
        if c.status != "approved":
            raise ApiError(409, "MFG_INVALID_STATE", "Only an approved cycle can be published.", {"status": c.status})
        sc = s.get(MfgSopScenarioRow, c.approved_scenario_id)
        res = _R(sc.result)
        pr = _P(sc.result["problem"])
        rows = list(s.execute(select(MfgSopDemandRow).where(MfgSopDemandRow.cycle_id == c.id)).scalars())
        cons: dict[str, dict[tuple[str, date], float]] = defaultdict(dict)
        for x in rows:
            cons[x.node_owner_id][(x.family, x.month)] = x.consensus_qty
        nodes = org_nodes(s)
        out_nodes = []
        reason = f"Published from {c.number} (approved)"
        now = utcnow()
        for n in nodes:
            nid = n["owner_id"]
            warnings: list[dict[str, Any]] = []
            vid_new = None
            targets = 0
            with owner_scope(nid):
                from ..db_models import MfgItemRow
                from ....mfg.network.build import key_of

                items = {i.id: i for i in s.execute(select(MfgItemRow)).scalars()}
                src_vid = (c.demand_sources or {}).get(nid)
                src = s.get(MfgForecastVersionRow, src_vid) if src_vid else None
                if cons.get(nid):
                    finals: dict[tuple[str, date], dict[str, float]] = defaultdict(dict)
                    if src is not None:
                        for ln in s.execute(select(MfgForecastLineRow).where(
                                MfgForecastLineRow.version_id == src.id)).scalars():
                            it = items.get(ln.item_id)
                            if it is not None and it.family:
                                finals[(it.family, ln.period_start.replace(day=1))][ln.item_id] = \
                                    finals[(it.family, ln.period_start.replace(day=1))].get(ln.item_id, 0.0) + \
                                    ln.final_qty
                    hist: dict[str, float] = defaultdict(float)
                    for iid, q in s.execute(select(MfgDemandHistoryRow.item_id, MfgDemandHistoryRow.qty).where(
                            MfgDemandHistoryRow.bucket == "m",
                            MfgDemandHistoryRow.period_start >= D.add_months(c.period, -12))):
                        hist[iid] += float(q or 0)
                    v = MfgForecastVersionRow(
                        id=new_id("fcv_"), number=next_number(s, "FCV", MfgForecastVersionRow),
                        name=f"{c.number} consensus"[:100], run_id=src.run_id if src else None, status="draft",
                        bucket="m", start=c.period, periods=c.horizon_months, activated_by=None, activated_at=None,
                        archived_at=None, note="source sop", row_version=1, created_at=now, updated_at=now)
                    s.add(v)
                    s.flush()
                    lines = []
                    for (fam, m), q in sorted(cons[nid].items()):
                        fin = finals.get((fam, m), {})
                        fh = {i: hist.get(i, 0.0) for i, it in items.items() if it.family == fam and it.active}
                        qty, err = D.disaggregate(q, fin, fh)
                        if err:
                            if q > 0:
                                warnings.append({"code": err, "node": nid, "family": fam, "month": m})
                            continue
                        for iid, x in qty.items():
                            lines.append({"id": new_id("fcl_"), "owner_id": nid, "version_id": v.id, "item_id": iid,
                                          "period_start": m, "stat_qty": float(fin.get(iid, 0.0)), "final_qty": x})
                    if lines:
                        s.execute(MfgForecastLineRow.__table__.insert(), lines)
                    for old in s.execute(select(MfgForecastVersionRow).where(
                            MfgForecastVersionRow.status == "active").with_for_update()).scalars():
                        old.status, old.archived_at, old.row_version, old.updated_at = "archived", now, \
                            old.row_version + 1, now
                    v.status, v.activated_by, v.activated_at, v.row_version = "active", a.user_id, now, 2
                    audit(s, "forecast_version", v.id, "activate", {"via": f"sop:{c.number}",
                                                                   "lines": len(lines)}, reason=reason)
                    vid_new = v.id
                # MPS targets from the make plan
                make = {(f, t): q for (nn, f, t), q in res.make.items() if nn == nid and t >= c.period}
                if make or n["kind"] == "plant":
                    s.execute(delete(MfgMpsTargetRow).where(MfgMpsTargetRow.owner_id == nid,
                                                            MfgMpsTargetRow.month >= c.period))
                    hrs = defaultdict(dict)
                    for (nn, g, f), h in pr.hpu.items():
                        if nn == nid:
                            hrs[f][g] = h
                    for (f, t), q in sorted(make.items()):
                        s.add(MfgMpsTargetRow(id=new_id("mps_"), cycle_id=c.id, cycle_number=c.number, family=f,
                                              month=t, qty_target=q, hours={g: round(q * h, 3) for g, h in
                                                                            hrs.get(f, {}).items()},
                                              created_at=now))
                        targets += 1
                    if targets:
                        audit(s, "mps_targets", None, "replace", {"via": f"sop:{c.number}", "targets": targets})
            out_nodes.append({"node": nid, "forecast_version_id": vid_new, "targets": targets,
                              "warnings": jsonable(warnings)})
        follow = [{"change_id": ch.get("id"), "kind": ch["kind"], "label": ch.get("label") or ch["kind"],
                   "node": ch.get("node") or ch.get("dest_node")}
                  for ch in (sc.changes or []) if ch["kind"] in ("add_line", "add_node", "sourcing", "make_vs_buy",
                                                                 "supplier_allocation", "capacity_change")]
        c.publish_result = {"nodes": out_nodes, "follow_ups": follow, "published_at": now.isoformat()}
        steps = [dict(x) for x in c.steps]
        for st in steps:
            if st["step"] in ("approved", "published"):
                st.update(done_at=now.isoformat(), done_by=a.user_id)
        c.steps, c.status = steps, "published"
        _touch(c)
        audit(s, "sop_cycle", c.id, "publish", {"nodes": len(out_nodes), "follow_ups": len(follow)})
        return _cycle(s, c)


def publish_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:   # pragma: no cover - sync publish
    return {"status": "skipped"}


__getattr__ = m9_examples.module_getattr(__name__)
