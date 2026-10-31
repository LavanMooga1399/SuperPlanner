"""Replan triggers, policy and notifications (M4-DESIGN 7, 11 #216-221).

Rules (`mfg.replan`) run inside the writing request (floor events, downtime, WO / demand changes); time-based rules
(`not_started`, `late_receipt`) run on a sweep before trigger / notification reads. A trigger is inserted only when
no open / attached trigger has its `dedupe_key` (partial unique index; a concurrent duplicate loses the race inside a
savepoint) and creates one workspace notification.

Policy (plant `replan_policy`), applied after the writing transaction commits (`apply_policy`):
- `notify`: nothing (the planner runs `POST /replan/run`);
- `auto_whatif`: the first open warning/critical trigger enqueues a proposal run (a live run of the published run's
  parameters, label `Replan <time>`, `as_of` taken when it executes) with the job's `run_after = now + debounce`;
  later triggers attach to the queued proposal; while another run is queued/running nothing is enqueued and
  `after_run` re-checks when it finishes;
- `auto_publish`: as `auto_whatif`; `after_run` publishes the proposal when `mfg.replan.auto_publish_check` passes
  (audit `auto_publish`), else a notification says why.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....mfg import replan as R
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.locks import is_unique_violation
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo
from ..db_models import MfgItemRow, MfgLineRow, MfgPlantRow
from ..db_models_m2 import MfgWorkOrderRow
from ..db_models_m3 import MfgApsOpRow, MfgApsRunRow
from ..db_models_m4 import MfgNotificationRow, MfgReplanTriggerRow, MfgWoOperationRow
from .common import audit, read_tx
from .m2util import actor_id, page, run_tx, user_names

log = logging.getLogger(__name__)
REPLAN_LABEL = "Replan"


def _plant(s: Session) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow)).scalars().first()


def _published(s: Session) -> MfgApsRunRow | None:
    return s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()


# ---------------------------------------------------------------- records

def trigger_records(s: Session, rows: list[MfgReplanTriggerRow]) -> list[dict[str, Any]]:
    names = user_names(s, [r.handled_by for r in rows if r.handled_by])
    return [{"id": r.id, "kind": r.kind, "severity": r.severity, "ref_type": r.ref_type, "ref_id": r.ref_id,
             "detected_at": as_utc(r.detected_at), "dedupe_key": r.dedupe_key, "details": r.details or {},
             "status": r.status, "aps_run_id": r.aps_run_id,
             "handled_by": {"id": r.handled_by, "code": "", "name": names.get(r.handled_by, "")}
             if r.handled_by else None,
             "handled_at": as_utc(r.handled_at), "message": (r.details or {}).get("_message", ""),
             "note": r.note} for r in rows]


def _clean(rec: dict[str, Any]) -> dict[str, Any]:
    rec = dict(rec)
    rec["details"] = {k: v for k, v in rec["details"].items() if not k.startswith("_")}
    rec.pop("note", None)
    return rec


def notification_records(s: Session, rows: list[MfgNotificationRow]) -> list[dict[str, Any]]:
    names = user_names(s, [r.acknowledged_by for r in rows if r.acknowledged_by])
    return [{"id": r.id, "kind": r.kind, "severity": r.severity, "title": r.title, "body": r.body, "link": r.link,
             "trigger_id": r.trigger_id, "created_at": as_utc(r.created_at),
             "acknowledged_at": as_utc(r.acknowledged_at),
             "acknowledged_by": {"id": r.acknowledged_by, "code": "", "name": names.get(r.acknowledged_by, "")}
             if r.acknowledged_by else None} for r in rows]


# ---------------------------------------------------------------- raising

def notify(s: Session, kind: str, severity: str, title: str, body: str, link: str = "",
           trigger_id: str | None = None, now: datetime | None = None) -> MfgNotificationRow:
    row = MfgNotificationRow(id=new_id("ntf_"), kind=kind[:32], severity=severity, title=title[:200],
                             body=body[:1000], link=link[:300], trigger_id=trigger_id, created_at=now or utcnow(),
                             acknowledged_at=None, acknowledged_by=None)
    s.add(row)
    s.flush()
    return row


def raise_trigger(s: Session, t: R.Trigger | None, now: datetime) -> dict[str, Any] | None:
    if t is None:
        return None
    if s.execute(select(MfgReplanTriggerRow.id).where(MfgReplanTriggerRow.dedupe_key == t.dedupe_key,
                                                      MfgReplanTriggerRow.status.in_(("open", "attached")))).first():
        return None
    row = MfgReplanTriggerRow(id=new_id("rpt_"), kind=t.kind, severity=t.severity, ref_type=t.ref_type,
                              ref_id=t.ref_id, detected_at=now, dedupe_key=t.dedupe_key[:200],
                              details={**t.details, "_message": t.message}, status="open", aps_run_id=None,
                              handled_by=None, handled_at=None, note="")
    try:
        with s.begin_nested():
            s.add(row)
            s.flush()
    except IntegrityError as exc:
        if is_unique_violation(exc, "uq_mfg_replan_triggers_open"):
            return None
        raise
    notify(s, f"trigger.{t.kind}", t.severity, t.message.split(" with ")[0][:200], t.message,
           f"/mfg/replan?trigger={row.id}", row.id, now)
    return _clean(trigger_records(s, [row])[0])


def _pub_ops(s: Session, run_id: str, **where: Any) -> list[MfgApsOpRow]:
    q = select(MfgApsOpRow).where(MfgApsOpRow.run_id == run_id, MfgApsOpRow.status == "scheduled")
    for k, v in where.items():
        q = q.where(getattr(MfgApsOpRow, k) == v)
    return list(s.execute(q).scalars())


def on_downtime(s: Session, dt: Any, now: datetime) -> list[dict[str, Any]]:
    pub = _published(s)
    if pub is None:
        return []
    ln = s.get(MfgLineRow, dt.line_id)
    ops = [(o.op_no, as_utc(o.start_at), o.frozen) for o in _pub_ops(s, pub.id, line_id=dt.line_id)
           if o.start_at is not None]
    start = max(now, as_utc(dt.start_at))
    t = R.line_down(dt.id, dt.line_id, ln.code if ln else "", dt.kind, ops, start)
    rec = raise_trigger(s, t, now)
    return [rec] if rec else []


def on_floor_event(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow, ev: Any,
                   after: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    from ....mfg.floor import engine as E

    out: list[dict[str, Any]] = []
    label = f"{wo.number} op {op.seq}"
    if ev.event_type in ("report", "complete", "correct") and (ev.qty_scrap or 0) > 0 or ev.event_type == "correct":
        chain = [E.ChainOp(r.seq, r.status, r.qty_planned, r.qty_good, r.qty_scrap, r.qty_rework_out,
                           r.qty_rework_in) for r in rows]
        if E.shortfall(wo.qty, chain):
            first = min(chain, key=lambda c: c.seq)
            reach = first.qty_planned - sum(c.qty_scrap for c in chain)
            prio = wo.priority
            if wo.demand_line_id:
                from ..db_models_m2 import MfgDemandLineRow

                dl = s.get(MfgDemandLineRow, wo.demand_line_id)
                prio = min(prio, getattr(dl, "priority", prio) or prio) if dl is not None else prio
            out.append(raise_trigger(s, R.scrap_shortfall(wo.id, wo.number, wo.qty, reach, prio), now))
    if ev.event_type in ("setup_start", "start") and op.started_short:
        from .floor import _op_short

        out.append(raise_trigger(s, R.start_short(op.id, label, _op_short(s, wo, rows, op)), now))
    if op.status in ("running", "setup") and ev.event_type == "report":
        out.append(_overrun(s, wo, op, label, now))
    return [x for x in out if x]


def _overrun(s: Session, wo: MfgWorkOrderRow, op: MfgWoOperationRow, label: str, now: datetime
             ) -> dict[str, Any] | None:
    pub = _published(s)
    if pub is None:
        return None
    parts = [o for o in _pub_ops(s, pub.id, order_id=wo.id, seq=op.seq) if o.start_at and o.end_at]
    if not parts:
        return None
    ps, pe = min(as_utc(o.start_at) for o in parts), max(as_utc(o.end_at) for o in parts)
    pq = sum(o.qty for o in parts)
    run = sum(o.run_minutes for o in parts)
    remaining = op.qty_planned - op.qty_good - op.qty_scrap + op.qty_rework_in
    proj = R.projected_end(now, remaining, pq, float(run))
    p = _plant(s)
    return raise_trigger(s, R.overrun(op.id, label, ps, pe, proj, float(p.overrun_tolerance_pct if p else 20)), now)


def on_document(s: Session, ref_type: str, ref_id: str, label: str, priority: int, due: Any) -> list[dict[str, Any]]:
    """WO / demand line created or re-prioritised (7 `rush_order`)."""
    pub = _published(s)
    if pub is None or priority > R.RUSH_PRIORITY:
        return []
    from ....mfg.tz import plant_tz

    p = _plant(s)
    hz = as_utc(pub.horizon_end).astimezone(plant_tz(p) if p else UTC).date()
    rec = raise_trigger(s, R.rush_order(ref_type, ref_id, label, priority, due, hz), utcnow())
    return [rec] if rec else []


def sweep(s: Session, now: datetime) -> int:
    """Time-based rules: `not_started` (published ops past planned start + tolerance) and `late_receipt`."""
    pub = _published(s)
    if pub is None:
        return 0
    p = _plant(s)
    tol = int(p.adherence_tolerance_minutes if p else 120)
    n = 0
    cutoff = now - timedelta(minutes=tol)
    ops = list(s.execute(select(MfgApsOpRow).where(
        MfgApsOpRow.run_id == pub.id, MfgApsOpRow.status == "scheduled", MfgApsOpRow.order_type == "wo",
        MfgApsOpRow.split_index == 0, MfgApsOpRow.start_at < cutoff, MfgApsOpRow.start_at >= now - timedelta(days=7)))
        .scalars())
    if ops:
        rows = {(r.wo_id, r.seq): r for r in s.execute(select(MfgWoOperationRow).where(
            MfgWoOperationRow.wo_id.in_({o.order_id for o in ops}))).scalars()}
        for o in ops:
            r = rows.get((o.order_id, o.seq))
            if r is None or r.status != "pending":
                continue
            if raise_trigger(s, R.not_started(r.id, f"{o.order_number} op {o.seq}", as_utc(o.start_at), now, tol),
                             now):
                n += 1
    n += _late_receipts(s, pub, now)
    return n


def _late_receipts(s: Session, pub: MfgApsRunRow, now: datetime) -> int:
    from ....mfg.tz import plant_tz
    from ..db_models_m2 import MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow

    p = _plant(s)
    tz = plant_tz(p) if p else UTC
    today = now.astimezone(tz).date()
    consumers: dict[str, tuple[MfgApsOpRow, datetime]] = {}
    for o in s.execute(select(MfgApsOpRow).where(MfgApsOpRow.run_id == pub.id, MfgApsOpRow.status == "scheduled",
                                                 MfgApsOpRow.start_at.is_not(None))).scalars():
        for ref in ((o.release or {}).get("refs") or []):
            if ref.get("type") in ("po_schedule", "pr_schedule") and ref.get("id"):
                cur = consumers.get(ref["id"])
                if cur is None or as_utc(o.start_at) < cur[1]:
                    consumers[ref["id"]] = (o, as_utc(o.start_at))
    if not consumers:
        return 0
    n = 0
    for sc, ln, d in s.execute(select(MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow).join(
            MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).join(
            MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id).where(
            MfgPurchaseScheduleRow.id.in_(sorted(consumers)))).all():
        if sc.closed or sc.qty - sc.received_qty <= 1e-6:
            continue
        o, st = consumers[sc.id]
        it = s.get(MfgItemRow, ln.item_id)
        rd = int(it.receiving_days or 0) if it else 0
        exp = (sc.confirmed_date or sc.requested_date)
        avail = exp + timedelta(days=rd)
        t = R.late_receipt(sc.id, f"{d.number}/{ln.line_no}/{sc.seq}", exp, today, st,
                           st.astimezone(tz).date() if avail > st.astimezone(tz).date() else None, bool(o.frozen))
        if raise_trigger(s, t, now):
            n += 1
    return n


SWEEP_EVERY_SECONDS = 60.0
_last_sweep: dict[str, float] = {}


def _sweep_tx(ctx: AppContext) -> None:
    """The time-based rules at most once a minute per workspace (the UI reads notifications on every page)."""
    import time

    from ...db.ownership import current_owner

    owner = str(current_owner() or "")
    now_m = time.monotonic()
    if now_m - _last_sweep.get(owner, -1e9) < SWEEP_EVERY_SECONDS:
        return
    _last_sweep[owner] = now_m
    with read_tx(ctx) as s:
        if _published(s) is None:
            return
    try:
        n = run_tx(ctx, lambda s: sweep(s, utcnow()))
    except Exception:       # never fail a read because of the sweep
        log.exception("replan sweep failed")
        return
    if n:
        apply_policy(ctx)


# ---------------------------------------------------------------- reads / actions (216-221)

def list_triggers(ctx: AppContext, *, status: str | None, kind: str | None, limit: int, offset: int
                  ) -> dict[str, Any]:
    _sweep_tx(ctx)
    conds = []
    if status:
        conds.append(MfgReplanTriggerRow.status == status)
    if kind:
        conds.append(MfgReplanTriggerRow.kind == kind)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgReplanTriggerRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgReplanTriggerRow).where(*conds).order_by(
            MfgReplanTriggerRow.detected_at.desc(), MfgReplanTriggerRow.id).limit(limit).offset(offset)).scalars())
        counts = dict(s.execute(select(MfgReplanTriggerRow.status, func.count()).group_by(
            MfgReplanTriggerRow.status)).all())
        return page([_clean(r) for r in trigger_records(s, rows)], total, limit, offset,
                    counts={k: int(v) for k, v in counts.items()})


def close_trigger(ctx: AppContext, trigger_id: str, status: str, note: str) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        row = repo.get_row(s, MfgReplanTriggerRow, trigger_id, what="Replan trigger", lock=True)
        if row.status not in ("open", "attached"):
            raise ApiError(409, "MFG_INVALID_STATE", f"This trigger is {row.status} already.",
                           {"status": row.status, "action": status, "allowed_from": ["open", "attached"]})
        row.status, row.handled_by, row.handled_at, row.note = status, actor_id(), utcnow(), note
        s.flush()
        audit(s, "replan_trigger", row.id, status, {"kind": row.kind, "note": note})
        return _clean(trigger_records(s, [row])[0])

    return run_tx(ctx, fn)


def _replan_params(s: Session, pub: MfgApsRunRow | None, now: datetime) -> Any:
    from ....mfg.aps.model import ApsParams

    base = ApsParams.model_validate({k: v for k, v in (pub.params or {}).items() if k in ApsParams.model_fields}) \
        if pub is not None else ApsParams()
    return ApsParams(label=f"{REPLAN_LABEL} {now.strftime('%d %b %H:%M')}", horizon_days=base.horizon_days,
                     overtime=base.overtime, split=base.split, material=base.material,
                     include_planned=base.include_planned, improve_seconds=base.improve_seconds,
                     open_shifts=base.open_shifts)


def run_replan(ctx: AppContext, trigger_ids: list[str] | None, idem_key: str | None) -> tuple[dict[str, Any], bool]:
    """POST /replan/run: a proposal (live run of the published parameters, as_of now) for the given or all open
    triggers; they become `attached` to it."""
    from . import aps

    with read_tx(ctx) as s:
        pub = _published(s)
        q = select(MfgReplanTriggerRow.id).where(MfgReplanTriggerRow.status.in_(("open", "attached")))
        ids = list(s.execute(q).scalars()) if trigger_ids is None else trigger_ids
        known = set(s.execute(select(MfgReplanTriggerRow.id).where(MfgReplanTriggerRow.id.in_(ids))).scalars())
        for i, t in enumerate(ids):
            if t not in known:
                raise ApiError(422, "MFG_UNKNOWN_REFERENCE", f"Replan trigger {t!r} was not found.",
                               {"loc": ["body", "trigger_ids", i], "id": t})
        params = _replan_params(s, pub, utcnow())
    rec, replayed = aps.create_run(ctx, params, idem_key, extras={"replan": {"trigger_ids": ids, "auto": False}})
    if not replayed:
        def attach(s: Session) -> None:
            if _attach(s, ids, rec["id"], allow_running=True):
                audit(s, "aps_run", rec["id"], "replan_attach", {"triggers": ids})

        run_tx(ctx, attach)
    return rec, replayed


def _attach(s: Session, ids: list[str], run_id: str, *, allow_running: bool = False) -> bool:
    """Attach open triggers to a proposal under a lock on the run row, only while it is queued (review M9; a
    manual proposal also while it runs). Returns False when the run moved on (the triggers stay open)."""
    run = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.id == run_id).with_for_update()
                    .execution_options(populate_existing=True)).scalars().first()
    if run is None or run.status not in (("queued", "running") if allow_running else ("queued",)):
        return False
    for r in s.execute(select(MfgReplanTriggerRow).where(MfgReplanTriggerRow.id.in_(ids),
                                                         MfgReplanTriggerRow.status.in_(("open", "attached")))
                       .with_for_update()).scalars():
        r.status, r.aps_run_id = "attached", run_id
    s.flush()
    return True


def _sweep_background(ctx: AppContext) -> None:
    """The bell is read on every page: the time-based sweep runs off the request (at most once a minute)."""
    import threading
    import time

    from ...db.ownership import current_owner, owner_scope

    owner = current_owner()
    if not owner or time.monotonic() - _last_sweep.get(str(owner), -1e9) < SWEEP_EVERY_SECONDS:
        return

    def run() -> None:
        try:
            with owner_scope(owner):
                _sweep_tx(ctx)
        except Exception:  # pragma: no cover - logged; the next read retries
            log.exception("background replan sweep failed")

    threading.Thread(target=run, name="replan-sweep", daemon=True).start()


def list_notifications(ctx: AppContext, *, unacked: bool | None, limit: int, offset: int) -> dict[str, Any]:
    _sweep_background(ctx)
    conds = []
    if unacked:
        conds.append(MfgNotificationRow.acknowledged_at.is_(None))
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgNotificationRow).where(*conds)).scalar() or 0)
        un = int(s.execute(select(func.count()).select_from(MfgNotificationRow).where(
            MfgNotificationRow.acknowledged_at.is_(None))).scalar() or 0)
        rows = list(s.execute(select(MfgNotificationRow).where(*conds).order_by(
            MfgNotificationRow.created_at.desc(), MfgNotificationRow.id).limit(limit).offset(offset)).scalars())
        return page(notification_records(s, rows), total, limit, offset, unacked=un)


def ack_notification(ctx: AppContext, notification_id: str) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        row = repo.get_row(s, MfgNotificationRow, notification_id, what="Notification", lock=True)
        if row.acknowledged_at is None:
            row.acknowledged_at, row.acknowledged_by = utcnow(), actor_id()
            s.flush()
            audit(s, "notification", row.id, "ack", {"kind": row.kind})
        return notification_records(s, [row])[0]

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- policy

def apply_policy(ctx: AppContext) -> dict[str, Any] | None:
    """After a commit that raised triggers: start or join the debounced proposal (auto policies)."""
    from . import aps

    with read_tx(ctx) as s:
        p = _plant(s)
        policy = p.replan_policy if p is not None else "notify"
        open_ = list(s.execute(select(MfgReplanTriggerRow).where(MfgReplanTriggerRow.status == "open")).scalars())
        if not R.wants_run(policy, [t.severity for t in open_]):
            return None
        ids = [t.id for t in open_]
        active = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.status.in_(("queued", "running")))
                           ).scalars().first()
        if active is not None:
            rp = (active.extras or {}).get("replan")
            if active.status == "queued" and rp is not None and rp.get("auto"):
                run_id = active.id
            else:
                return None           # a manual run: after_run re-checks
        else:
            run_id = None
        pub = _published(s)
        debounce = int(p.replan_debounce_minutes if p is not None else 15)
        params = _replan_params(s, pub, utcnow())
    def attach(s: Session, rid: str) -> bool:
        ok = _attach(s, ids, rid)
        if ok:
            audit(s, "aps_run", rid, "replan_attach", {"triggers": ids, "policy": policy})
        return ok

    if run_id is not None:
        if run_tx(ctx, lambda s: attach(s, run_id)):
            return {"id": run_id, "attached": ids}
        return None                       # it started meanwhile: after_run re-checks the open triggers
    try:
        rec, _r = aps.create_run(ctx, params, None, extras={"replan": {"trigger_ids": ids, "auto": True,
                                                                        "policy": policy}},
                                 delay_minutes=debounce)
    except ApiError as e:
        if e.code in ("APS_RUN_IN_PROGRESS",):
            return apply_policy(ctx)
        msg = e.message
        log.warning("auto replan run not started: %s %s", e.code, msg)
        run_tx(ctx, lambda s: notify(s, "replan.failed", "warning", "Automatic replan could not start", msg))
        return None
    run_tx(ctx, lambda s: attach(s, rec["id"]))
    return rec


def after_run(ctx: AppContext, run_id: str) -> None:
    """Called by the APS job when a run finished: auto-publish a proposal (7) and re-check open triggers."""
    from . import aps

    with read_tx(ctx) as s:
        run = s.get(MfgApsRunRow, run_id)
        if run is None:
            return
        rp = (run.extras or {}).get("replan")
        status, row_version = run.status, run.row_version
        summary, validation = dict(run.summary or {}), dict(run.validation or {})
        pub = _published(s)
        pub_wt = float((pub.summary or {}).get("weighted_tardiness", 0.0)) if pub is not None else None
        frozen_moved = int(summary.get("frozen_moved", 0) or 0)
    if rp is not None and status == "completed" and rp.get("policy") == "auto_publish":
        ok, why = R.auto_publish_check(bool(validation.get("ok")), frozen_moved,
                                       float(summary.get("weighted_tardiness", 0.0)), pub_wt)
        if ok:
            try:
                # never across a changed freeze basis (review M5): a stale proposal stays a proposal
                aps.publish_run(ctx, run_id, f'"{row_version}"', confirm_stale_basis=False)
                run_tx(ctx, lambda s: (audit(s, "aps_run", run_id, "auto_publish", {"triggers": rp.get("trigger_ids")}),
                                       notify(s, "replan.published", "info", "Replan published automatically",
                                              "The proposal met the auto-publish rules and is now the published "
                                              "plan.", f"/mfg/schedule/runs/{run_id}")))
            except ApiError as e:
                ok, why = False, e.message
        if not ok:
            run_tx(ctx, lambda s: notify(s, "replan.not_published", "warning", "Replan kept as a proposal",
                                         f"The proposal was not published: {why}.", f"/mfg/schedule/runs/{run_id}"))
    elif rp is not None and status == "completed":
        run_tx(ctx, lambda s: notify(s, "replan.proposal", "info", "Replan proposal ready",
                                     "A replan proposal for the open triggers is ready to compare and publish.",
                                     f"/mfg/schedule/runs/{run_id}"))
    apply_policy(ctx)


def floor_summary(s: Session) -> dict[str, Any]:
    """`GET /summary` -> `floor` (11)."""
    from ..db_models_m4 import MfgDowntimeRow
    from .floor_effects import pending_of

    now = utcnow()
    running = int(s.execute(select(func.count()).select_from(MfgWoOperationRow).where(
        MfgWoOperationRow.status.in_(("setup", "running")))).scalar() or 0)
    down = int(s.execute(select(func.count(func.distinct(MfgDowntimeRow.line_id))).where(
        MfgDowntimeRow.start_at <= now, MfgDowntimeRow.end_at.is_(None))).scalar() or 0)
    trig = int(s.execute(select(func.count()).select_from(MfgReplanTriggerRow).where(
        MfgReplanTriggerRow.status.in_(("open", "attached")))).scalar() or 0)
    pend = sum(1 for r in s.execute(select(MfgWoOperationRow).where(
        MfgWoOperationRow.status != "pending")).scalars() if pending_of(r))
    return {"running_ops": running, "lines_down": down, "open_triggers": trig, "pending_backflush": pend}
