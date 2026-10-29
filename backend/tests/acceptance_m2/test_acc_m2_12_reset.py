"""Gate 2 #12: reset with every M2 table populated (sample with transactions, an MRP run, a conversion, a reversal)
leaves zero `mfg_*` data rows for the owner, keeps memberships (9.4), and leaves another user's data unchanged.
"""

from __future__ import annotations

from sqlalchemy import func, select

from accm2_helpers import MEMBER_ENDPOINTS, MRP_ENDPOINTS, RESET, add_member, mrp_planned, need_module

OWNER, OTHER = "reset-a@acc-m2.example.com", "reset-b@acc-m2.example.com"


def _counts(app, owner_id: str) -> dict[str, int]:
    m2 = need_module("superplanner.api.mfg.db_models_m2", "ALL_MFG_MODELS")
    from superplanner.api.db.ownership import system_scope

    out = {}
    with system_scope(), app.state.ctx.db.read() as s:
        for model in list(m2.ALL_MFG_MODELS) + list(getattr(m2, "MFG_ACCESS_MODELS", [])):
            out[model.__tablename__] = int(s.execute(select(func.count()).select_from(model)
                                                     .where(model.owner_id == owner_id)).scalar() or 0)
    return out


def _populate(api) -> None:
    api.load("small", anchor=None)
    run = api.run_mrp()
    rows = mrp_planned(api, run["id"])
    api.post(f"/mrp/runs/{run['id']}/planned-orders/convert", {
        "mode": "firm", "orders": [{"id": rows[0]["id"]}], "pr_grouping": "per_supplier", "add_to_pr_id": None,
        "reserve": False})
    loc = api.get("/locations")["items"][0]
    item = api.get("/items", limit=1)["items"][0]
    pst = api.post_stock(item["id"], loc["id"], 2) if item["make_buy"] != "phantom" else None
    if pst:
        api.post(f"/inventory/postings/{pst['id']}/reverse", {"note": ""})


def test_reset_clears_m2_data_keeps_members_and_other_users(acc):
    a = acc.user(OWNER)
    a.need(*MEMBER_ENDPOINTS, *MRP_ENDPOINTS, "POST /samples/{sample_id}/load", "POST /reset",
           "POST /mrp/runs/{run_id}/planned-orders/convert")
    add_member(acc, OWNER, "reset-m@acc-m2.example.com", ["viewer"])
    b = acc.user(OTHER)
    _populate(a)
    _populate(b)
    before_a, before_b = _counts(acc.app, acc.uid(OWNER)), _counts(acc.app, acc.uid(OTHER))
    populated = {t for t, n in before_a.items() if n}
    assert {"mfg_inv_balances", "mfg_inv_postings", "mfg_purchase_docs", "mfg_demand_orders", "mfg_mrp_runs",
            "mfg_mrp_planned_orders", "mfg_locations", "mfg_suppliers"} <= populated, populated
    a.post("/reset", RESET, status=200)
    after_a = _counts(acc.app, acc.uid(OWNER))
    assert {t: n for t, n in after_a.items() if n and t != "mfg_plant_members"} == {}
    assert after_a.get("mfg_plant_members") == before_a.get("mfg_plant_members") == 1
    assert _counts(acc.app, acc.uid(OTHER)) == before_b
    assert acc.user("reset-m@acc-m2.example.com").in_workspace(acc.uid(OWNER)).get("/locations")["items"] == []
