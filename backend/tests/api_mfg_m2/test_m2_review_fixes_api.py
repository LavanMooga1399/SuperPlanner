"""Regression tests for the M2 review round (one per defect: M1-M4, m1-m6, m8; m7 is frontend)."""

from __future__ import annotations

import io
import threading
import zipfile

from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, Api, acc_app, im, sign_up

OCTET = {"content-type": "application/octet-stream"}


def _bal(api: Api, item_id: str) -> list[dict]:
    return api.get("/inventory/balances", item_id=item_id)["items"]


def _released_wo(api: Api, fg: dict, comps: list[dict], number: str | None = None) -> dict:
    body = {"item_id": fg["id"], "qty": 1, "due_date": "2026-12-30", "components": comps}
    if number:
        body["number"] = number
    wo = api.post("/work-orders", body)
    return api.post(f"/work-orders/{wo['id']}/release", {"reserve": True}, status=200, version=wo["row_version"])


def _stage(api: Api, data: bytes, filename: str) -> tuple[dict, dict]:
    r = api.req("POST", "/imports", 201, params={"filename": filename}, content=data, headers=OCTET).json()
    m = api.put(f"/imports/{r['id']}/mapping", {"sheets": {s["name"]: s["suggested"] for s in r["sheets"]},
                                                "options": {}}, r["row_version"])
    return r, m


def _commit(api: Api, r: dict, m: dict):
    return api.req("POST", f"/imports/{r['id']}/commit", json={}, headers={"If-Match": f'"{m["row_version"]}"'})


def _without(api: Api, pn: str) -> bytes:
    """`work_orders` + `wo_components` export with the component rows of `pn` dropped."""
    z = zipfile.ZipFile(io.BytesIO(api.req("GET", "/export", 200, params={"format": "zip",
                                                                           "scope": "transactions"}).content))
    comps = "\n".join(x for x in z.read("wo_components.csv").decode().splitlines() if pn not in x) + "\n"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zz:
        zz.writestr("work_orders.csv", z.read("work_orders.csv").decode())
        zz.writestr("wo_components.csv", comps)
    return out.getvalue()


def test_m1_component_item_cannot_change_once_used(api: Api):
    a, b, fg, loc = api.item("PA"), api.item("PB"), api.item("FG", "make"), api.location("S1")
    api.receive(a["id"], loc["id"], 10)
    wo = _released_wo(api, fg, [{"item_id": a["id"], "required_qty": 10}])
    c = wo["components"][0]
    body = {"item_id": fg["id"], "qty": 1, "due_date": "2026-12-30",
            "components": [{"id": c["id"], "item_id": b["id"], "required_qty": 10}]}
    e = api.err("PUT", f"/work-orders/{wo['id']}", 422, "WO_COMPONENT_IN_USE", json=body,
                headers=im(wo["row_version"]))                                   # reserved
    assert e["details"]["component_id"] == c["id"]
    api.post("/inventory/postings", {"type": "wo_issue", "lines": [
        {"wo_component_id": c["id"], "location_id": loc["id"], "qty": 4}]})
    api.post("/inventory/postings", {"type": "wo_return", "lines": [
        {"wo_component_id": c["id"], "location_id": loc["id"], "qty": 4}]})
    wo = api.post(f"/work-orders/{wo['id']}/unreserve", {}, status=200, version=api.get(
        f"/work-orders/{wo['id']}")["row_version"])
    api.err("PUT", f"/work-orders/{wo['id']}", 422, "WO_COMPONENT_IN_USE", json=body,
            headers=im(wo["row_version"]))                                       # transactions (net 0 issued)
    assert sum(x["qty_on_hand"] for x in _bal(api, b["id"])) == 0


def test_m2_import_removing_components_releases_reservations_and_respects_the_ledger(api: Api):
    a, b, cc, fg, loc = api.item("PA"), api.item("PB"), api.item("PC"), api.item("FG", "make"), api.location("S1")
    for x in (a, b, cc):
        api.receive(x["id"], loc["id"], 10)
    _released_wo(api, fg, [{"item_id": a["id"], "required_qty": 5, "find_number": "10"},
                           {"item_id": b["id"], "required_qty": 5, "find_number": "20"},
                           {"item_id": cc["id"], "required_qty": 5, "find_number": "30"}], "WO-X")
    assert _bal(api, b["id"])[0]["qty_reserved"] == 5
    r, m = _stage(api, _without(api, "PB"), "x.zip")
    assert _commit(api, r, m).status_code == 200
    assert _bal(api, b["id"])[0]["qty_reserved"] == 0                           # no orphan reservation
    # a component referenced by the ledger (issued and returned: issued_qty 0) cannot be removed: IMP_IN_USE
    wo = api.doc("/work-orders", "WO-X")
    ca = next(x for x in wo["components"] if x["item"]["part_number"] == "PA")
    for t in ("wo_issue", "wo_return"):
        api.post("/inventory/postings", {"type": t, "lines": [
            {"wo_component_id": ca["id"], "location_id": loc["id"], "qty": 2}]})
    r, m = _stage(api, _without(api, "PA"), "y.zip")
    assert not m["preview"]["ok"]
    assert any(x["code"] == "IMP_IN_USE" for x in m["preview"]["row_errors"])
    res = _commit(api, r, m)
    assert res.status_code == 409 and res.json()["error"]["code"] == "MFG_IMPORT_HAS_ERRORS", res.text


def test_m3_unreserve_racing_a_count_keeps_qty_reserved_consistent(client: TestClient, api: Api):
    a, fg, loc = api.item("PA"), api.item("FG", "make"), api.location("S1")
    api.receive(a["id"], loc["id"], 40)
    many = [api.item(f"Z{i:03d}")["id"] for i in range(80)]
    api.post("/inventory/postings", {"type": "receipt_misc", "lines": [
        {"item_id": i, "location_id": loc["id"], "qty": 5} for i in many]})
    for k in range(3):
        x = _released_wo(api, fg, [{"item_id": a["id"], "required_qty": 5}])
        y = _released_wo(api, fg, [{"item_id": a["id"], "required_qty": 5}])
        lines = [{"item_id": a["id"], "location_id": loc["id"], "counted_qty": 40 - k}] + \
            [{"item_id": i, "location_id": loc["id"], "counted_qty": 4 - (k % 2)} for i in many]
        out: dict[str, int] = {}
        bar = threading.Barrier(2)

        def count() -> None:
            bar.wait()
            out["count"] = client.post(MFG + "/inventory/postings", json={"type": "count", "lines": lines}).status_code

        def unreserve() -> None:
            bar.wait()
            out["unres"] = client.post(MFG + f"/work-orders/{x['id']}/unreserve", json={},
                                       headers=im(x["row_version"])).status_code

        ts = [threading.Thread(target=count), threading.Thread(target=unreserve)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert out == {"count": 201, "unres": 200}, out
        bal = _bal(api, a["id"])[0]
        held = sum(c["reserved_qty"] for w in (x, y) for c in api.get(f"/work-orders/{w['id']}")["components"])
        assert abs(bal["qty_reserved"] - held) < 1e-6 and abs(held - 5) < 1e-6, (bal, held)
        api.post(f"/work-orders/{y['id']}/unreserve", {}, status=200, version=api.get(
            f"/work-orders/{y['id']}")["row_version"])


def test_m4_concurrent_retries_with_one_key_replay(client: TestClient, api: Api):
    a, loc = api.item("PA"), api.location("S1")
    api.receive(a["id"], loc["id"], 30)
    for k in range(3):
        body = {"type": "issue_misc", "reason_code": "SCRAP", "lines": [
            {"item_id": a["id"], "location_id": loc["id"], "qty": 10}]}
        got: list[tuple[int, str | None, str | None]] = []
        bar = threading.Barrier(2)

        def go() -> None:
            bar.wait()
            r = client.post(MFG + "/inventory/postings", json=body, headers={"Idempotency-Key": f"race-{k}"})
            got.append((r.status_code, r.headers.get("Idempotent-Replay"), r.json().get("id")))

        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sorted(g[0] for g in got) == [200, 201], got
        assert got[0][2] == got[1][2]
    assert sum(x["qty_on_hand"] for x in _bal(api, a["id"])) == 0
    # convert_pr: a retry with the same key and the (now old) If-Match replays instead of 412
    sup = api.supplier("SUP")
    pr = api.post("/purchase-requests", {"supplier_id": sup["id"], "lines": [{"item_id": a["id"], "schedules": [
        {"requested_date": "2026-12-01", "qty": 1}]}]})
    pr = api.post(f"/purchase-requests/{pr['id']}/submit", version=pr["row_version"], status=200)
    pr = api.post(f"/purchase-requests/{pr['id']}/approve", version=pr["row_version"], status=200)
    h = {**im(pr["row_version"]), "Idempotency-Key": "cv-pr"}
    first = api.req("POST", f"/purchase-requests/{pr['id']}/convert", 201, json={}, headers=h).json()
    again = api.req("POST", f"/purchase-requests/{pr['id']}/convert", 200, json={}, headers=h)
    assert again.headers["Idempotent-Replay"] == "true" and again.json()["po"]["id"] == first["po"]["id"]


def test_m1_minor_wo_put_checks_the_demand_line(api: Api):
    fg = api.item("FG", "make")
    wo = api.post("/work-orders", {"item_id": fg["id"], "qty": 1, "due_date": "2026-12-30", "components": []})
    api.err("PUT", f"/work-orders/{wo['id']}", 422, "MFG_UNKNOWN_REFERENCE", json={
        "item_id": fg["id"], "qty": 1, "due_date": "2026-12-30", "demand_line_id": "dml_" + "0" * 32},
        headers=im(wo["row_version"]))


def test_m2_minor_lot_control_cannot_change_with_stock(api: Api):
    a, loc = api.item("PA"), api.location("S1")
    api.receive(a["id"], loc["id"], 10)
    it = api.get(f"/items/{a['id']}")
    body = {k: it[k] for k in it if k not in ("id", "row_version", "created_at", "updated_at", "has_bom",
                                               "has_routing", "used_in_count")}
    body["lot_controlled"] = True
    e = api.err("PUT", f"/items/{a['id']}", 409, "MFG_IN_USE", json=body, headers=im(it["row_version"]))
    assert e["details"]["references"]["balances"] == 1


def test_m3_minor_imported_approved_pr_needs_approval_and_no_self_approval(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        owner = Api(oc)
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        owner.item("PA")
        sign_up_p, sign_up_b = sign_up(app, "plan@example.com"), sign_up(app, "both@example.com")
        owner.post("/members", {"email": "plan@example.com", "roles": ["planner"]})
        owner.post("/members", {"email": "both@example.com", "roles": ["planner", "approver"]})
        csv = b"doc_type,number,status\npr,PR-IMP-1,approved\n"
        planner = Api(sign_up_p, oid)
        r, m = _stage(planner, csv, "purchase_docs.csv")
        res = _commit(planner, r, m)
        assert res.status_code == 403 and res.json()["error"]["details"]["permission"] == "pr_approve", res.text
        both = Api(sign_up_b, oid)
        r, m = _stage(both, csv, "purchase_docs.csv")
        res = _commit(both, r, m)
        assert res.status_code == 409 and res.json()["error"]["code"] == "PUR_SELF_APPROVAL", res.text


def test_m4_minor_wo_receipt_reversal_reverts_scrap(api: Api):
    fg, loc = api.item("FG", "make"), api.location("S1")
    wo = api.post("/work-orders", {"item_id": fg["id"], "qty": 5, "due_date": "2026-12-30", "components": []})
    wo = api.post(f"/work-orders/{wo['id']}/release", {}, status=200, version=wo["row_version"])
    p = api.post("/inventory/postings", {"type": "wo_receipt", "lines": [
        {"wo_id": wo["id"], "location_id": loc["id"], "qty": 1, "scrap_qty": 2}]})
    assert api.get(f"/work-orders/{wo['id']}")["qty_scrapped"] == 2
    api.post(f"/inventory/postings/{p['id']}/reverse", {})
    w = api.get(f"/work-orders/{wo['id']}")
    assert w["qty_scrapped"] == 0 and w["qty_completed"] == 0


def test_m5_m8_issue_trims_reservations_on_other_balances(api: Api):
    a, fg, s1, s2 = api.item("PA"), api.item("FG", "make"), api.location("S1"), api.location("S2")
    api.receive(a["id"], s1["id"], 6)
    api.receive(a["id"], s2["id"], 20)
    wo = _released_wo(api, fg, [{"item_id": a["id"], "required_qty": 10}])
    c = wo["components"][0]
    reserved = {b["location"]["code"]: b["qty_reserved"] for b in _bal(api, a["id"])}
    assert sum(reserved.values()) == 10 and len([v for v in reserved.values() if v > 0]) == 2, reserved
    # issue everything from S2: its own reservation there is consumed, the one on S1 must be trimmed (m5/m8)
    other = s2
    api.post("/inventory/postings", {"type": "wo_issue", "lines": [
        {"wo_component_id": c["id"], "location_id": other["id"], "qty": 10, "over_issue": True}]})
    assert all(b["qty_reserved"] == 0 for b in _bal(api, a["id"])), _bal(api, a["id"])
    assert api.get(f"/work-orders/{wo['id']}")["components"][0]["reserved_qty"] == 0


def test_m6_staleness_sees_deletes_and_lot_edits(api: Api):
    a = api.item("PA", lot_controlled=True)
    loc = api.location("S1")
    api.post("/inventory/postings", {"type": "receipt_misc", "lines": [
        {"item_id": a["id"], "location_id": loc["id"], "qty": 2, "lot_code": "L1"}]})
    prs = [api.post("/purchase-requests", {"lines": [{"item_id": a["id"], "schedules": [
        {"requested_date": "2026-12-01", "qty": 1}]}]}) for _ in range(2)]
    run = api.post("/mrp/runs", {})
    assert not run["stale"]["is_stale"]
    api.delete(f"/purchase-requests/{prs[0]['id']}", prs[0]["row_version"])    # not the newest: max unchanged
    assert api.get(f"/mrp/runs/{run['id']}")["stale"]["transactions_changed"]
    run = api.post("/mrp/runs", {})
    lot = api.get("/lots", item_id=a["id"])["items"][0]
    api.put(f"/lots/{lot['id']}", {"hold": True}, lot["row_version"])
    assert api.get(f"/mrp/runs/{run['id']}")["stale"]["transactions_changed"]
