"""Load seed (M8-DESIGN 14.2) and the M8 performance cases P1-P5, P8. The `small` profile runs the whole chain in
the normal suite; the BD-like profile (`-m slow`) records timings against the targets."""

from __future__ import annotations

import time

import pytest

from m8_helpers import owner_db


def _chain(client, api, budget: int) -> dict[str, float]:
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.services import forecast, invopt, mrp, rate, ster
    from superplanner.mfg.mrp.model import MrpParams
    from superplanner.mfg.rate.model import RateParams

    ctx = client.app.state.ctx
    db = owner_db(client)
    t: dict[str, float] = {}
    with owner_scope("usr_local"):
        t0 = time.monotonic()
        with db.write() as s:
            fr = forecast.run_now(s, "usr_local", {"horizon_periods": 6})
            from superplanner.api.mfg.db_models_m8 import MfgForecastVersionRow
            from sqlalchemy import select
            v = s.execute(select(MfgForecastVersionRow).where(MfgForecastVersionRow.run_id == fr.id)).scalars().one()
            v.status, v.activated_at = "active", fr.finished_at
        t["P1_forecast_s"] = time.monotonic() - t0
        t0 = time.monotonic()
        with db.write() as s:
            r = invopt._new_run(s, "usr_local", {}, "running")
            invopt.run_sync(s, r)
        t["P3_ss_s"] = time.monotonic() - t0
        t0 = time.monotonic()
        m = mrp.create_run(ctx, MrpParams(label="nightly-1", rate_supply=False, horizon_days=180))
        t["P2_mrp_forecast_s"] = time.monotonic() - t0
        assert m["status"] == "completed", m
        with db.write() as s:
            rid = rate._new_run(s, "usr_local", RateParams(horizon_days=30, time_budget_s=budget)).id
        t0 = time.monotonic()
        out = rate.compute(ctx, rid)
        t["P4_rate_s"] = time.monotonic() - t0
        assert out["status"] == "completed", api.get(f"/rate/runs/{rid}")["validator"]["violations"][:5]
        with db.write() as s:
            rate.publish_in(s, s.get(__import__("superplanner.api.mfg.db_models_m8", fromlist=["x"]).MfgRateRunRow,
                                     rid), "usr_local")
        t0 = time.monotonic()
        with db.write() as s:
            sp = ster.plan_in(s, "usr_local", None)
        t["P5_ster_s"] = time.monotonic() - t0
        assert sp["loads"] > 0
    t0 = time.monotonic()
    g = api.get(f"/rate/runs/{rid}/grid")
    t["P8_grid_s"] = time.monotonic() - t0
    assert g["cells"]
    t["construct_ms"] = max(x.get("construct_ms", 0) for x in api.get(f"/rate/runs/{rid}")["summary"]["stats"]
                            ["lines"].values())
    return t


def test_seed_small_and_chain(api, client):
    from superplanner.loadseed import seed

    res = seed(owner_db(client), "usr_local", profile="small")
    assert res["items"] == 150 and res["history_rows"] == 90 * 24
    t = _chain(client, api, 10)
    assert t["P4_rate_s"] < 60


@pytest.mark.slow
def test_bd_profile_timings(api, client):
    from superplanner.loadseed import seed

    t0 = time.monotonic()
    seed(owner_db(client), "usr_local", profile="bd")
    seed_s = time.monotonic() - t0
    t = _chain(client, api, 240)
    print({"seed_s": round(seed_s, 1), **{k: round(v, 2) for k, v in t.items()}})
    assert t["P1_forecast_s"] < 60 and t["P3_ss_s"] < 10 and t["P2_mrp_forecast_s"] < 90
    assert t["P4_rate_s"] < 300 and t["P5_ster_s"] < 10 and t["P8_grid_s"] < 0.8
