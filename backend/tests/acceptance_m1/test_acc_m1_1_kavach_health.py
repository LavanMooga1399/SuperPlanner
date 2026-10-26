"""15.3 #1: load `kavach` via the API into an empty account -> health ok, 0 errors, exactly the intended
warnings/infos of M1-DESIGN 10.4 (MFG_LONG_LEAD_TIME, MFG_SKILL_NOT_ON_SHIFT (1, COATING / COAT-1),
MFG_DUPLICATE_COMPONENT); every issue link is a working frontend link."""

from __future__ import annotations

from accm1_helpers import Api, check_link

INTENDED = {"MFG_LONG_LEAD_TIME", "MFG_SKILL_NOT_ON_SHIFT", "MFG_DUPLICATE_COMPONENT"}


def _assert_kavach_health(api: Api) -> None:
    h = api.health()
    assert h["ok"] is True, h["counts"]
    assert h["counts"]["error"] == 0
    assert set(h["by_code"]) == INTENDED, h["by_code"]
    assert h["by_code"]["MFG_SKILL_NOT_ON_SHIFT"] == 1
    skill_issue = next(i for i in h["issues"] if i["code"] == "MFG_SKILL_NOT_ON_SHIFT")
    assert skill_issue["severity"] == "warning"
    assert skill_issue["entity"]["type"] == "skill"
    assert "COATING" in skill_issue["message"] and "COAT-1" in skill_issue["message"]
    assert "COATING" in skill_issue["entity"]["label"] and "COAT-1" in skill_issue["entity"]["label"]
    assert next(i for i in h["issues"] if i["code"] == "MFG_LONG_LEAD_TIME")["severity"] == "info"
    assert next(i for i in h["issues"] if i["code"] == "MFG_DUPLICATE_COMPONENT")["severity"] == "info"
    assert sum(h["counts"].values()) == sum(h["by_code"].values()) == len(h["issues"])
    assert h["truncated"] is False
    for issue in h["issues"]:
        check_link(api, issue)
    # long-lead parts: every flagged one is a buy item over 180 days (M 10.4: FPGAs/processors + radio module)
    for issue in (i for i in h["issues"] if i["code"] == "MFG_LONG_LEAD_TIME"):
        it = api.get(f"/items/{issue['entity']['id']}")
        assert it["make_buy"] == "buy" and it["lead_time_days"] > 180, it
    assert any(api.get(f"/items/{i['entity']['id']}")["part_number"] == "KV-MOD-GSM"
               for i in h["issues"] if i["code"] == "MFG_LONG_LEAD_TIME")


def test_kavach_loads_into_empty_single_user_account_with_health_ok(api: Api):
    assert api.get("/summary")["counts"]["items"] == 0
    out = api.load("kavach")
    assert out["sample_id"] == "kavach"
    assert out["health"]["ok"] is True and out["health"]["counts"]["error"] == 0
    s = api.get("/summary")
    c = s["counts"]
    assert 1150 <= c["items"] <= 1500 and 2200 <= c["bom_lines"] <= 2700 and c["groups"] == 20, c
    assert [e["part_number"] for e in s["end_items"]] == ["KV-TPU-1000"]
    _assert_kavach_health(api)
    top = api.item("KV-TPU-1000")
    ex = api.get(f"/items/{top['id']}/explosion", on="2026-11-02")
    assert 2300 <= ex["totals"]["rows"] <= 3000 and ex["totals"]["max_level"] == 4, ex["totals"]
    assert ex["warnings"] == []


def test_kavach_loads_into_empty_accounts_mode_account_with_health_ok(accounts):
    a, b = accounts
    out = a.load("kavach")
    assert out["health"]["ok"] is True
    _assert_kavach_health(a)
    # the other account stays empty and its health is trivially ok
    assert b.get("/summary")["counts"]["items"] == 0
    assert b.health()["by_code"] == {}


def test_second_load_is_all_unchanged_and_keeps_health(api: Api):
    api.load("kavach")
    dv = api.get("/summary")["data_version"]
    out = api.load("kavach")
    counts = out["result"]["counts"]
    for sheet, cnt in counts.items():
        assert cnt.get("create", 0) == cnt.get("update", 0) == cnt.get("delete", 0) == 0, (sheet, cnt)
    assert api.get("/summary")["data_version"] == dv
    _assert_kavach_health(api)
