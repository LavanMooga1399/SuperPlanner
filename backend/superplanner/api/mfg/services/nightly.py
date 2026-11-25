"""Nightly planning chain (M8-DESIGN 6.1; job `nightly_plan`, per plant at `planning_settings.nightly_at` when
`nightly_enabled`, or on demand N2).

Steps, sequential in one duty run (M2 "one running MRP per plant" holds): history refresh -> on the first working
day of the month a forecast run + safety-stock run (drafts only) -> MRP pass 1 (live, `rate_supply false`, label
`nightly-1`) -> rate run (published only with `auto_publish`) -> sterilisation plan -> MRP pass 2 (live,
`nightly-2`). A failing step stops the chain; planners get a notification. Each step's result is recorded in the
duty run's results (`steps`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select

from ...context import AppContext
from ...db.models import utcnow

STEPS = ("history_refresh", "forecast_run", "ss_run", "mrp_pass1", "rate_run", "ster_plan", "mrp_pass2")


def start(ctx: AppContext, owner: str, actor: str, *, manual: bool = False) -> dict[str, Any]:
    from ....integration.jobs import active_run, new_run
    from ...errors import ApiError
    from .common import write_tx

    with write_tx(ctx, lock=False) as (s, _):
        if active_run(s, "nightly_plan", owner):
            raise ApiError(409, "PLANNING_CHAIN_RUNNING", "The planning chain is already running for this plant.", {})
        rid, job = new_run(s, ctx, "nightly_plan", owner, {"actor": actor, "manual": manual})
    ctx.jobs.dispatch(job)
    return {"run_id": rid, "status": "queued", "started_at": None,
            "steps": [{"step": k, "status": "queued", "ref_id": None, "error": None} for k in STEPS]}


def first_workday_of_month(d: date, is_workday: Callable[[date], bool]) -> bool:
    x = d.replace(day=1)
    while not is_workday(x):
        x += timedelta(days=1)
    return x == d


def run(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    from ....mfg.mrp.model import MrpParams
    from ....mfg.rate.model import RateParams
    from . import forecast, invopt, mrp, rate, ster
    from .m8common import settings_of, today, work_calendar

    actor = (info.get("params") or {}).get("actor") or info.get("owner") or "usr_local"
    steps: list[dict[str, Any]] = []

    def step(name: str, fn: Callable[[], Any]) -> bool:
        rec = {"step": name, "status": "running", "ref_id": None, "error": None, "at": utcnow().isoformat()}
        steps.append(rec)
        try:
            rec["ref_id"] = fn()
            rec["status"] = "completed"
            return True
        except Exception as exc:  # the chain stops; planners are told
            rec["status"], rec["error"] = "failed", f"{exc.__class__.__name__}: {exc}"[:500]
            _notify(ctx, name, rec["error"])
            return False

    def hist() -> None:
        with ctx.write_guard(), ctx.db.write() as s:
            forecast.refresh(s)

    if not step("history_refresh", hist):
        return {"steps": steps}
    with ctx.db.read() as s:
        d = today(s)
        monthly = first_workday_of_month(d, work_calendar(s).is_workday) or bool(
            (info.get("params") or {}).get("force_monthly"))
        st = settings_of(s)
    if monthly:
        def fc() -> str:
            with ctx.write_guard(), ctx.db.write() as s:
                return forecast.run_now(s, actor, {}).id
        if not step("forecast_run", fc):
            return {"steps": steps}

        def ss() -> str:
            with ctx.write_guard(), ctx.db.write() as s:
                r = invopt._new_run(s, actor, {}, "running")
                invopt.run_sync(s, r)
                return r.id
        if not step("ss_run", ss):
            return {"steps": steps}
    if not step("mrp_pass1", lambda: mrp.create_run(ctx, MrpParams(label="nightly-1", rate_supply=False))["id"]):
        return {"steps": steps}

    def rr() -> str:
        with ctx.write_guard(), ctx.db.write() as s:
            r = rate._new_run(s, actor, RateParams(label="nightly"))
            rid = r.id
        out = rate.compute(ctx, rid)
        if st.auto_publish and out.get("status") == "completed":
            from .. import repo
            from ..db_models_m8 import MfgRateRunRow

            with ctx.write_guard(), ctx.db.write() as s:
                rate.publish_in(s, repo.get_row(s, MfgRateRunRow, rid, what="Rate run", lock=True), actor)
        if out.get("status") != "completed":
            raise RuntimeError(f"rate run {out.get('status')}")
        return rid
    if not step("rate_run", rr):
        return {"steps": steps}

    def sp() -> Any:
        with ctx.write_guard(), ctx.db.write() as s:
            return ster.plan_in(s, actor, None).get("load_ids", [])[:1] or None
    if not step("ster_plan", sp):
        return {"steps": steps}
    step("mrp_pass2", lambda: mrp.create_run(ctx, MrpParams(label="nightly-2"))["id"])
    return {"steps": steps}


def _notify(ctx: AppContext, name: str, error: str) -> None:
    try:
        from .replan import notify

        with ctx.write_guard(), ctx.db.write() as s:
            notify(s, "planning_chain", "warning", f"Nightly planning stopped at {name.replace('_', ' ')}", error,
                   "/mfg/rate")
    except Exception:  # pragma: no cover - a notification never hides the failure itself
        pass


def due_plants(s: Any, now: datetime) -> list[str]:
    """Plants whose nightly chain is due (enabled, local time past `nightly_at`, not run today)."""
    from ....integration.jobs import active_run
    from ....mfg.model_m8 import PlanningSettings
    from ....mfg.tz import plant_tz
    from ..db_models import MfgPlantRow
    from ..db_models_m5 import MaintenanceRunRow

    out = []
    for p in s.execute(select(MfgPlantRow).where(MfgPlantRow.planning_settings.is_not(None))).scalars():
        st = PlanningSettings.model_validate(p.planning_settings)
        if not st.nightly_enabled:
            continue
        local = now.astimezone(plant_tz(p))
        hh, mm = (int(x) for x in st.nightly_at.split(":"))
        if (local.hour, local.minute) < (hh, mm) or active_run(s, "nightly_plan", p.owner_id):
            continue
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        ran = s.execute(select(MaintenanceRunRow.id).where(
            MaintenanceRunRow.kind == "nightly_plan", MaintenanceRunRow.owner_scope_id == p.owner_id,
            MaintenanceRunRow.created_at >= start).limit(1)).first()
        if ran is None:
            out.append(p.owner_id)
    return out
