"""15.3 #3: each blocking defect class introduced through the API -> health `ok == false` with exactly the expected
codes, and every issue link is a working frontend link. Defects the API refuses up front (cycles; overlaps and
alternate-group errors, which release blocks) are asserted at the refusing call, with the same issue shape and
links, and health stays unchanged. Baseline: sample `small`, which has zero issues (M 10.2)."""

from __future__ import annotations

from typing import Any

import pytest

from accm1_helpers import Api, bom_input, check_link, item_input

KAVACH_INTENDED = {"MFG_LONG_LEAD_TIME", "MFG_SKILL_NOT_ON_SHIFT", "MFG_DUPLICATE_COMPONENT"}


@pytest.fixture
def small(api: Api) -> Api:
    api.load("small")
    h = api.health()
    assert h["ok"] and h["by_code"] == {}, h["by_code"]
    return api


def _health_codes(api: Api) -> tuple[bool, dict[str, int], list[dict[str, Any]]]:
    h = api.health()
    for issue in h["issues"]:
        check_link(api, issue)
    return h["ok"], h["by_code"], h["issues"]


def _draft_copy(api: Api, pn: str) -> dict[str, Any]:
    b = api.released_bom(pn)
    return api.post(f"/boms/{b['id']}/copy", {"revision": None}, version=b["row_version"])


def test_cycle_attempts_are_rejected_and_change_nothing(small: Api):
    api = small
    top = api.item("SM-100")
    draft = _draft_copy(api, "SM-100")
    body = bom_input(draft)
    body["lines"].append({"find_number": "999", "child_item_id": top["id"], "qty_per": 1})
    r = api.raw("PUT", f"/boms/{draft['id']}", json=body, headers={"If-Match": f'"{draft["row_version"]}"'})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_BOM_CYCLE", r.text
    assert r.json()["error"]["details"]["cycle"] == ["SM-100", "SM-100"]
    # two-item cycle: SM-X (draft BOM containing SM-100), then SM-100's draft adds SM-X
    x = api.post("/items", {"part_number": "SM-X", "make_buy": "make"})
    xb = api.post("/boms", {"item_id": x["id"], "lines": [{"find_number": "10", "child_item_id": top["id"],
                                                             "qty_per": 1}]})
    body = bom_input(api.get(f"/boms/{draft['id']}"))
    body["lines"].append({"find_number": "999", "child_item_id": x["id"], "qty_per": 1})
    r = api.raw("PUT", f"/boms/{draft['id']}", json=body, headers={"If-Match": f'"{draft["row_version"]}"'})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_BOM_CYCLE", r.text
    assert r.json()["error"]["details"]["cycle"] == ["SM-100", "SM-X", "SM-100"]
    r = api.raw("POST", "/boms", json={"item_id": top["id"], "lines": [{"find_number": "1", "child_item_id": x["id"],
                                                                       "qty_per": 1}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_BOM_CYCLE", r.text
    assert api.get(f"/boms/{draft['id']}")["row_version"] == draft["row_version"]
    api.delete(f"/boms/{draft['id']}", draft["row_version"])
    api.delete(f"/boms/{xb['id']}", xb["row_version"])
    api.delete(f"/items/{x['id']}", api.get(f"/items/{x['id']}")["row_version"])
    ok, codes, _ = _health_codes(api)
    assert ok and codes == {}


def test_make_item_without_routing(small: Api):
    api = small
    lbl = api.item("SM-LBL-01")
    kit = api.post("/items", {"part_number": "SM-KIT", "make_buy": "make", "description": "Label kit"})
    b = api.post("/boms", {"item_id": kit["id"], "lines": [{"find_number": "10", "child_item_id": lbl["id"],
                                                              "qty_per": 1}]})
    api.post(f"/boms/{b['id']}/release", {"effective_from": "2026-01-01"}, status=200, version=b["row_version"])
    ok, codes, issues = _health_codes(api)
    assert not ok and codes == {"MFG_MAKE_NO_ROUTING": 1}, codes
    assert issues[0]["entity"] == {"type": "item", "id": kit["id"], "label": "SM-KIT"}


def test_group_without_shift(small: Api):
    api = small
    aoi = api.by_code("/groups", "AOI")
    for a in api.get("/shift-assignments", group_id=aoi["id"])["items"]:
        api.delete(f"/shift-assignments/{a['id']}", a["row_version"])
    ok, codes, issues = _health_codes(api)
    assert not ok and codes == {"MFG_GROUP_NO_SHIFT": 1}, codes
    assert issues[0]["entity"]["id"] == aoi["id"]


def test_buy_item_without_lead_time(small: Api):
    api = small
    lbl = api.item("SM-LBL-01")
    body = item_input(lbl) | {"lead_time_days": None}
    api.put(f"/items/{lbl['id']}", body, lbl["row_version"])
    ok, codes, issues = _health_codes(api)
    assert not ok and codes == {"MFG_BUY_NO_LEAD_TIME": 1}, codes
    assert issues[0]["entity"]["id"] == lbl["id"] and issues[0]["link"] == f"/mfg/items/{lbl['id']}"


def test_unit_mismatch(small: Api):
    api = small
    lbl = api.item("SM-LBL-01")
    api.put(f"/items/{lbl['id']}", item_input(lbl) | {"uom": "M"}, lbl["row_version"])
    ok, codes, issues = _health_codes(api)
    assert not ok and codes == {"MFG_UOM_MISMATCH": 1}, codes
    bom = api.released_bom("SM-100")
    line = next(ln for ln in bom["lines"] if ln["child_item_id"] == lbl["id"])
    assert issues[0]["entity"]["type"] == "bom_line" and issues[0]["entity"]["id"] == line["id"]
    assert issues[0]["link"] == f"/mfg/items/{bom['item_id']}/bom?bom={bom['id']}&line={line['id']}"


def test_unit_mismatch_in_a_draft_blocks_release(small: Api):
    api = small
    draft = _draft_copy(api, "SM-100")
    body = bom_input(draft)
    lbl = api.item("SM-LBL-01")
    for ln in body["lines"]:
        if ln["child_item_id"] == lbl["id"]:
            ln["uom"] = "KG"
    draft = api.put(f"/boms/{draft['id']}", body, draft["row_version"])
    r = api.raw("POST", f"/boms/{draft['id']}/release", json={"effective_from": "2026-12-01",
                                                              "supersede_previous": True},
                headers={"If-Match": f'"{draft["row_version"]}"'})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_RELEASE_BLOCKED", r.text
    issues = r.json()["error"]["details"]["issues"]
    assert {i["code"] for i in issues} == {"MFG_UOM_MISMATCH"}
    for i in issues:
        check_link(api, i)
        assert "/edit?line=" in i["link"]


def test_bom_and_routing_overlap_is_blocked_at_release(small: Api):
    api = small
    draft = _draft_copy(api, "SM-100")
    for body in ({"effective_from": "2026-06-01", "supersede_previous": False},
                 {"effective_from": "2025-06-01", "supersede_previous": True}):   # v1 starts later: not superseded
        r = api.raw("POST", f"/boms/{draft['id']}/release", json=body,
                    headers={"If-Match": f'"{draft["row_version"]}"'})
        assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_RELEASE_BLOCKED", r.text
        issues = r.json()["error"]["details"]["issues"]
        assert {i["code"] for i in issues} == {"MFG_BOM_EFFECTIVITY_OVERLAP"}, issues
        for i in issues:
            check_link(api, i)
    rt = api.released_routing("SM-100")
    rd = api.post(f"/routings/{rt['id']}/copy", {"revision": None, "code": None}, version=rt["row_version"])
    r = api.raw("POST", f"/routings/{rd['id']}/release", json={"effective_from": "2026-06-01"},
                headers={"If-Match": f'"{rd["row_version"]}"'})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_RELEASE_BLOCKED", r.text
    issues = r.json()["error"]["details"]["issues"]
    assert {i["code"] for i in issues} == {"MFG_ROUTING_EFFECTIVITY_OVERLAP"}, issues
    for i in issues:
        check_link(api, i)
    assert api.get(f"/boms/{draft['id']}")["status"] == "draft"
    ok, codes, _ = _health_codes(api)
    assert ok and codes == {}, codes          # drafts of items with released documents raise nothing


@pytest.mark.parametrize("prios,code", [((2, 3), "MFG_ALT_NO_PRIMARY"), ((1, 1), "MFG_ALT_DUPLICATE_PRIORITY")])
def test_alternate_group_errors_block_release(small: Api, prios: tuple[int, int], code: str):
    api = small
    draft = _draft_copy(api, "SM-100")
    body = bom_input(draft)
    r10k, r1k = api.item("SM-RES-10K"), api.item("SM-RES-1K")
    for ln in body["lines"]:
        if ln["child_item_id"] == r10k["id"]:
            ln.update(alt_group="R", alt_priority=prios[0])
        if ln["child_item_id"] == r1k["id"]:
            ln.update(alt_group="R", alt_priority=prios[1])
    draft = api.put(f"/boms/{draft['id']}", body, draft["row_version"])
    r = api.raw("POST", f"/boms/{draft['id']}/release", json={"effective_from": "2026-12-01",
                                                              "supersede_previous": True},
                headers={"If-Match": f'"{draft["row_version"]}"'})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MFG_RELEASE_BLOCKED", r.text
    issues = r.json()["error"]["details"]["issues"]
    assert {i["code"] for i in issues} == {code}, issues
    for i in issues:
        check_link(api, i)
    assert api.released_bom("SM-100")["effective_to"] is None       # nothing superseded by a blocked release


def test_uninterruptible_burn_in_on_a_reg_only_group(api: Api):
    api.load("kavach")
    burn = api.by_code("/groups", "BURNIN")
    reg = api.by_code("/shift-templates", "REG")
    for a in api.get("/shift-assignments", group_id=burn["id"])["items"]:
        api.delete(f"/shift-assignments/{a['id']}", a["row_version"])
    api.post("/shift-assignments", {"shift_template_id": reg["id"], "target_type": "group", "group_id": burn["id"],
                                    "kind": "base", "effective_from": "2026-01-01"})
    ok, codes, issues = _health_codes(api)
    assert not ok
    assert set(codes) - KAVACH_INTENDED == {"MFG_UNINTERRUPTIBLE_TOO_LONG"}, codes
    assert KAVACH_INTENDED <= set(codes), codes
    bad = [i for i in issues if i["code"] == "MFG_UNINTERRUPTIBLE_TOO_LONG"]
    tpu = api.item("KV-TPU-1000")
    assert len(bad) == 1 and bad[0]["entity"]["type"] == "operation"
    assert bad[0]["link"].startswith(f"/mfg/items/{tpu['id']}/routing?routing=") and bad[0]["link"].endswith("&op=20")
