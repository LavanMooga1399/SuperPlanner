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
    t["P8_grid_cold_s"] = time.monotonic() - t0
    warm = []
    for _k in range(3):
        t0 = time.monotonic()
        api.get(f"/rate/runs/{rid}/grid")
        warm.append(time.monotonic() - t0)
    t["P8_grid_s"] = sorted(warm)[1]                     # median of 3 warm calls
    t["grid_cells"] = len(g["cells"])
    assert g["cells"]
    t["construct_ms"] = max(x.get("construct_ms", 0) for x in api.get(f"/rate/runs/{rid}")["summary"]["stats"]
                            ["lines"].values())
    return t


def test_seed_small_and_chain(api, client):
    from superplanner.loadseed import seed

    res = seed(owner_db(client), "usr_local", profile="small")
    assert res["items"] == 150
    from superplanner.api.db.models import AuditEventRow
    from superplanner.api.db.ownership import system_scope
    with system_scope(), owner_db(client).read() as s:
        assert s.query(AuditEventRow).filter(AuditEventRow.action == "load_seed").count() == 1 and res["history_rows"] == 90 * 24
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


def test_load_seed_guards(api, client):
    """Review 5: CLI confirmation flags, postings need --force, Part 11 refused (seed and sample replace)."""
    import io

    from superplanner import manage
    from superplanner.loadseed import SeedRefused, seed

    url = str(owner_db(client).engine.url.render_as_string(hide_password=False))
    err = io.StringIO()
    assert manage.main(["--url", url, "load-seed", "--profile", "small"], out=io.StringIO(), err=err) == 1
    assert "--replace-all-data --yes" in err.getvalue()
    it = api.item("GUARD-1")
    loc = api.location("ST-G")
    api.receive(it["id"], loc["id"], 5)
    with pytest.raises(SeedRefused):
        seed(owner_db(client), "usr_local", profile="small")
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models import MfgPlantRow
    with owner_scope("usr_local"), owner_db(client).write() as s:
        s.query(MfgPlantRow).one().part11_mode = True
    with pytest.raises(SeedRefused):
        seed(owner_db(client), "usr_local", profile="small", force=True)
    api.err("POST", "/samples/small/load", 409, "PART11_DELETE_NOT_ALLOWED", json={"replace": True})
    from superplanner.api.db.models import AuditEventRow
    from superplanner.api.db.ownership import system_scope
    with system_scope(), owner_db(client).read() as s:
        assert not s.query(AuditEventRow).filter(AuditEventRow.action == "load_seed").count()
